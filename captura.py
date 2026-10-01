"""Serviço de captura — grava cada candle M1 fechado do WIN$N, ao vivo.

    .venv/Scripts/python.exe captura.py      (o iniciar.bat abre numa janela própria)

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md.
Processo à parte da tela de propósito: a tela reinicia a cada mudança e
trava em mineração; um laço contínuo dentro dela perderia candle (e, na
parte 4, ordem). Toda decisão mora em core/captura.py; aqui só o laço.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import polars as pl

from core import calendar as cal
from core import captura as C
from core import db_manager as db
from core import rollovers as roll
from core.mt5_source import barras_de_taxas

SAIR_SEM_REABRIR = 3      # configuração: reabrir não resolve
OUTRA_INSTANCIA = 4       # já há uma captura rodando: o .bat sai calado
PASTA = db.DATA / "ao_vivo"

log = logging.getLogger("captura")

# Lacuna e conferência custam uma releitura do dia no MT5 e uma conexão ao
# banco; a cada volta de 1 s seria desperdício. Um minuto basta para a
# lacuna (o candle seguinte já a revelaria) e 5 min para a conferência.
A_CADA_LACUNA = 60
A_CADA_CONFERENCIA = 300

# Fora do pregão a captura só precisa dizer que está viva; com o MT5 fora
# do ar, 5 s deixa a volta pegar a reconexão logo.
ESPERA_PREGAO, ESPERA_FORA, ESPERA_SEM_MT5 = 1, 30, 5

# Candle recente (do servidor) = mercado vivo, mesmo depois do fechamento
# esperado: por uns 5 pregões após a troca de horário dos EUA a moda ainda
# diz 17:54 com a B3 indo até 18:24.
MERCADO_VIVO = timedelta(minutes=10)


class ErroDeConfiguracao(RuntimeError):
    """Erro que reabrir não resolve: o .bat não deve tentar de novo."""


class _Ocupado(Exception):
    """O banco está com outro escritor (mineração gravando): pula o passo."""


def travar(caminho: Path):
    """Trava de instância pelo Windows (msvcrt.locking): se o processo
    morrer, o sistema solta sozinho — um arquivo .pid ficaria órfão.
    Quem chama guarda o objeto devolvido pela vida inteira do processo."""
    import msvcrt
    caminho.parent.mkdir(parents=True, exist_ok=True)
    f = open(caminho, "a+")
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except OSError:
        f.close()
        return None


def terminal_aberto() -> bool:
    """`initialize()` com o MT5 fechado abriria um terminal sozinho — na
    frente do usuário, talvez logado na conta errada. Por isso só se chama
    com um terminal64.exe já rodando. Limitação: com dois MT5 instalados,
    não confere qual deles está aberto."""
    try:
        saida = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "terminal64.exe" in saida.lower()


def _nao_hibernar(pregao: bool) -> None:
    """No pregão pede ao Windows para não hibernar: PC dormindo é candle que
    só volta na recuperação. Fora dele devolve o controle ao Windows."""
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
    except (ImportError, AttributeError):
        return
    kernel.SetThreadExecutionState(0x80000000 | 0x00000001 if pregao else 0x80000000)


def _hora_do_tick(tick) -> datetime | None:
    # Mesma regra das barras: o epoch do MT5 já é o relógio de Brasília.
    if tick is None or not getattr(tick, "time", None):
        return None
    return datetime.fromtimestamp(tick.time, timezone.utc).replace(tzinfo=None)


def _utc(d: datetime) -> datetime:
    # O pacote MetaTrader5 converte datetime sem fuso pelo fuso do PC; marcado
    # como UTC, o valor segue como está (ver mt5_source.buscar_barras).
    return d.replace(tzinfo=timezone.utc)


class Servico:
    def __init__(self, mt5, simbolo="WIN$N", terminal=None, agora=datetime.now,
                 mono=time.monotonic, pasta=PASTA, terminal_aberto=terminal_aberto,
                 price_decimals=0):
        self.mt5, self.simbolo, self.terminal = mt5, simbolo, terminal
        self.agora, self.mono, self.pasta = agora, mono, Path(pasta)
        self.terminal_aberto, self.price_decimals = terminal_aberto, price_decimals
        # Sem o YAML não dá para refazer as rolagens na conferência. O erro
        # sobe na primeira volta, não aqui: o main precisa do Servico para
        # publicar o aviso no estado.
        try:
            self.inst = db.load_instrument_yaml(simbolo)
            self._sem_yaml = None
        except FileNotFoundError as e:
            self.inst, self._sem_yaml = {}, str(e)
        self.relogio = C.RelogioServidor()

        self.carregado = False          # leitura inicial do banco já feita
        self.dia = None
        self.ultimo = None              # maior ts salvo no banco
        self.fechamento = None
        self.conectado = False          # initialize() feito e válido
        self.novo_login = False
        self.mt5_estado, self.mt5_desde = "fechado", None
        self.conta, self.contrato = None, None
        self.agora_srv, self.desvio = None, None
        self.em_formacao = None
        self.candle_mais_novo = None
        self.primeiro_hoje = None
        self.lacunas_hoje: list[datetime] = []
        self.gravados = self.recuperados = self.revisados = 0
        self.conferencia = {"status": "pendente"}
        self.banco_ocupado_desde = None
        self.pregao = False
        self._mono_lacuna = None
        self._mono_conferencia = None

    # ------------------------------------------------------------- banco
    @contextlib.contextmanager
    def _banco(self, agora, escrita: bool):
        """No máximo ~1 s de espera: a volta não pode travar atrás de uma
        mineração. Ocupado vira `_Ocupado`, que o passo trata como "pula"."""
        try:
            con = (db.connect_write(tentativas=4, espera=0.25) if escrita
                   else db.connect(read_only=True, tentativas=4))
        except RuntimeError:
            self.banco_ocupado_desde = self.banco_ocupado_desde or agora
            raise _Ocupado from None
        try:
            yield con
        finally:
            con.close()

    def _gravou(self) -> None:
        self.banco_ocupado_desde = None

    def _carregar(self, agora) -> None:
        """Primeira volta, e a cada troca de dia: de onde a captura retoma e
        o placar que um reinício não pode zerar."""
        hoje = agora.date()
        with self._banco(agora, escrita=False) as con:
            if not self.carregado:
                ultimo = con.execute("SELECT max(ts) FROM bars_m1 WHERE symbol = ?",
                                     [self.simbolo]).fetchone()[0]
                if ultimo is None:
                    raise ErroDeConfiguracao(
                        "base vazia — rode corrigir_base.py ou cli.py ingest antes")
                self.ultimo = ultimo
            if self.fechamento is None or self.dia not in (None, hoje):
                self.fechamento = C.fechamento_esperado(con, self.simbolo)
            self.gravados = con.execute(
                "SELECT count(*) FROM bars_m1 b JOIN ingest_log l "
                "ON l.ingest_id = b.src_ingest_id WHERE b.symbol = ? "
                "AND CAST(b.ts AS DATE) = ? AND l.source_file LIKE ?",
                [self.simbolo, hoje, C.PREFIXO_CAPTURA + "%"]).fetchone()[0]
            conf = con.execute(
                "SELECT max(ingested_at) FROM ingest_log WHERE symbol = ? "
                "AND source_file = ?",
                [self.simbolo, f"{C.PREFIXO_CONFERENCIA}{hoje:%Y-%m-%d}"]).fetchone()[0]
            self.conferencia = ({"status": "concluida", "em": conf} if conf
                                else {"status": "pendente"})
            self.primeiro_hoje = con.execute(
                "SELECT min(ts) FROM bars_m1 WHERE symbol = ? AND CAST(ts AS DATE) = ?",
                [self.simbolo, hoje]).fetchone()[0]
        # recuperados/revisados não estão no banco de forma barata: recomeçam
        # do zero a cada reabertura da captura (aceito; só o placar da tela).
        if self.dia not in (None, hoje):
            self.recuperados = self.revisados = 0
            self.lacunas_hoje = []
        self.dia = hoje
        self.carregado = True

    # --------------------------------------------------------------- MT5
    def _mt5(self, agora) -> bool:
        mt5 = self.mt5
        if not self.conectado:
            if self.terminal_aberto():
                ok = (mt5.initialize(path=self.terminal) if self.terminal
                      else mt5.initialize())
                self.conectado = self.novo_login = bool(ok)
        if not self.conectado:
            return self._fora_do_ar("fechado", agora)
        info = mt5.terminal_info()
        if info is None:
            # terminal fechado depois de conectado: a volta seguinte reinicializa
            self.conectado = False
            with contextlib.suppress(Exception):
                mt5.shutdown()
            return self._fora_do_ar("fechado", agora)
        if not info.connected:
            return self._fora_do_ar("sem_conexao", agora)
        self.mt5_estado, self.mt5_desde = "conectado", None
        if self.novo_login:
            # a cada (re)conexão: o usuário pode ter trocado de conta no terminal
            if not mt5.symbol_select(self.simbolo, True):
                raise ErroDeConfiguracao(f"o MT5 não tem {self.simbolo}")
            conta = mt5.account_info()
            self.conta = ({"login": int(conta.login), "servidor": conta.server}
                          if conta is not None else None)
            # na série contínua (WIN$N) a Clear devolve basis vazio: None, não ""
            self.contrato = getattr(mt5.symbol_info(self.simbolo), "basis", None) or None
            self.novo_login = False
        return True

    def _fora_do_ar(self, estado: str, agora) -> bool:
        if self.mt5_estado != estado:
            self.mt5_desde = agora
        self.mt5_estado = estado
        return False

    def _taxas(self, desde: datetime, ate: datetime) -> pl.DataFrame | None:
        taxas = self.mt5.copy_rates_range(self.simbolo, self.mt5.TIMEFRAME_M1,
                                          _utc(desde), _utc(ate))
        if taxas is None or len(taxas) == 0:
            return None
        return barras_de_taxas(taxas)

    def _origem(self) -> str:
        c = self.conta or {}
        return C.origem_captura(c.get("login"), c.get("servidor"))

    # -------------------------------------------------------------- passos
    def _buscar_e_gravar(self, agora, m) -> None:
        df = self._taxas(self.ultimo + timedelta(minutes=1), agora + timedelta(days=1))
        if df is None:
            self.em_formacao = None
            return
        prontos = C.fechados(df, self.agora_srv)
        ultima = df.row(-1, named=True)
        self.em_formacao = ({k: ultima[k] for k in ("ts", "open", "high", "low", "close")}
                            if prontos.height < df.height else None)
        mais_novo = df["ts"].max()
        if self.candle_mais_novo is None or mais_novo > self.candle_mais_novo:
            self.candle_mais_novo = mais_novo
        if prontos.height == 0:
            return
        try:
            with self._banco(agora, escrita=True) as con:
                r = C.gravar(con, self.simbolo, prontos, self._origem(), self.price_decimals)
        except _Ocupado:
            # sem avançar `ultimo`: a volta seguinte pede os mesmos candles ao MT5
            return
        self._gravou()
        self.ultimo = max(self.ultimo, prontos["ts"].max())
        self.gravados += r["inseridos"]
        self.revisados += r["revisados"]
        limite = (self.agora_srv or agora) - timedelta(minutes=2)
        self.recuperados += prontos.filter(pl.col("ts") < limite).height
        self._marca_primeiro(prontos, agora)

    def _marca_primeiro(self, barras: pl.DataFrame, agora) -> None:
        de_hoje = barras.filter(pl.col("ts").dt.date() == agora.date())
        if de_hoje.height and (self.primeiro_hoje is None
                               or de_hoje["ts"].min() < self.primeiro_hoje):
            self.primeiro_hoje = de_hoje["ts"].min()

    def _lacunas(self, agora, m) -> None:
        if not C.em_pregao(agora, self.fechamento):
            return
        if self._mono_lacuna is not None and m - self._mono_lacuna < A_CADA_LACUNA:
            return
        zero = datetime.combine(agora.date(), datetime.min.time())
        df = self._taxas(zero, agora + timedelta(days=1))
        mt5_hoje = (C.fechados(df, self.agora_srv) if df is not None
                    else pl.DataFrame(schema={"ts": pl.Datetime}))
        mt5_hoje = mt5_hoje.filter(pl.col("ts").dt.date() == agora.date())
        try:
            with self._banco(agora, escrita=False) as con:
                banco = [r[0] for r in con.execute(
                    "SELECT ts FROM bars_m1 WHERE symbol = ? AND CAST(ts AS DATE) = ?",
                    [self.simbolo, agora.date()]).fetchall()]
        except _Ocupado:
            return
        self._mono_lacuna = m
        faltam = C.lacunas(mt5_hoje["ts"].to_list(), banco)
        self.lacunas_hoje = faltam
        if not faltam:
            return
        # a recuperação é o mesmo gravar: a lacuna se fecha sozinha
        repor = mt5_hoje.filter(pl.col("ts").is_in(faltam))
        try:
            with self._banco(agora, escrita=True) as con:
                r = C.gravar(con, self.simbolo, repor, self._origem(), self.price_decimals)
        except _Ocupado:
            return
        self._gravou()
        log.info("lacuna recuperada: %d candle(s) de %s a %s",
                 repor.height, faltam[0], faltam[-1])
        self.lacunas_hoje = []
        self.gravados += r["inseridos"]
        self.revisados += r["revisados"]
        self.recuperados += r["inseridos"]
        self.ultimo = max(self.ultimo, repor["ts"].max())
        self._marca_primeiro(repor, agora)

    def _fechou_hoje(self, agora) -> bool:
        if agora <= datetime.combine(agora.date(), self.fechamento) + C.FOLGA_FECHAMENTO:
            return False
        novo = self.candle_mais_novo
        if novo is None or novo.date() != agora.date():
            return True
        # o segundo critério: a moda do fechamento pode estar atrasada uma
        # troca de horário dos EUA; candle recente diz que o mercado segue
        return novo <= (self.agora_srv or agora) - MERCADO_VIVO

    def _conferir(self, agora, m) -> None:
        if (self._mono_conferencia is not None
                and m - self._mono_conferencia < A_CADA_CONFERENCIA):
            return
        try:
            with self._banco(agora, escrita=True) as con:
                self._mono_conferencia = m
                self._conferir_com(con, agora)
        except _Ocupado:
            return      # a janela não conta: tenta de novo na volta seguinte
        except ErroDeConfiguracao:
            raise
        except Exception as e:
            log.exception("conferência do dia falhou")
            self.conferencia = {"status": "falhou", "em": agora, "erro": str(e)}

    def _conferir_com(self, con, agora) -> None:
        dias = C.dias_pendentes(con, self.simbolo, agora.date(), self._fechou_hoje(agora))
        if not dias:
            return
        feitos, falhas = [], []
        for dia in dias:
            zero = datetime.combine(dia, datetime.min.time())
            df = self._taxas(zero, zero + timedelta(hours=23, minutes=59))
            # dia passado está todo fechado; o de hoje segue a hora do servidor
            ref = self.agora_srv if dia == agora.date() else agora
            df = (C.fechados(df, ref) if df is not None
                  else pl.DataFrame(schema={"ts": pl.Datetime}))
            try:
                r = C.conferir_dia(con, self.simbolo, dia, df, agora=agora,
                                   price_decimals=self.price_decimals)
            except ValueError as e:
                # o MT5 não tem o dia (histórico curto, terminal recém-aberto):
                # o dia segue pendente e volta na próxima janela
                log.warning("conferência de %s: %s", dia, e)
                falhas.append(str(e))
                continue
            log.info("conferência de %s: %d revisado(s), %d faltante(s)",
                     dia, r["revisados"], r["faltantes"])
            feitos.append(dia)
        if feitos:
            cal.rebuild_trading_days(con, self.simbolo)
            roll.rebuild_rollovers(con, self.simbolo, self.inst.get("rollover_policy"))
            db.export_parquet(con, self.simbolo)
            self._gravou()
        if falhas:
            self.conferencia = {"status": "falhou", "em": agora, "dias": feitos,
                                "erro": "; ".join(falhas)}
        else:
            self.conferencia = {"status": "concluida", "em": agora, "dias": feitos}

    # ---------------------------------------------------------------- volta
    def volta(self) -> float:
        """Uma volta; devolve quantos segundos esperar. Nenhum passo sai
        antes do estado: a tela precisa ver o que aconteceu, até o "nada"."""
        if self._sem_yaml:
            raise ErroDeConfiguracao(self._sem_yaml)
        agora, m = self.agora(), self.mono()
        if not self.carregado or self.dia != agora.date():
            with contextlib.suppress(_Ocupado):
                self._carregar(agora)

        conectado = self._mt5(agora)
        if conectado:
            self.relogio.observar(_hora_do_tick(self.mt5.symbol_info_tick(self.simbolo)), m)
            self.agora_srv = self.relogio.agora(m)
            self.desvio = self.relogio.desvio_s(agora, m)
            if self.carregado:
                self._buscar_e_gravar(agora, m)
                self._lacunas(agora, m)
                self._conferir(agora, m)

        fechamento = self.fechamento or C.FECHAMENTO_PADRAO
        novo = self.candle_mais_novo
        self.pregao = C.em_pregao(agora, fechamento) or (
            novo is not None and novo.date() == agora.date()
            and (self.agora_srv or agora) - novo < MERCADO_VIVO)
        _nao_hibernar(self.pregao)

        self.publicar(agora, erro=None)
        if not conectado:
            return ESPERA_SEM_MT5
        return ESPERA_PREGAO if self.pregao else ESPERA_FORA

    def publicar(self, agora, erro) -> None:
        fechamento = self.fechamento or C.FECHAMENTO_PADRAO
        dados = {
            "pid": os.getpid(),
            "atualizado_em": agora,
            "mt5": self.mt5_estado,
            "mt5_desde": self.mt5_desde,
            "conta": self.conta,
            "contrato_vigente": self.contrato,
            "simbolo": self.simbolo,
            "fechamento_esperado": f"{fechamento:%H:%M}",
            "em_pregao": self.pregao,
            "ultimo_salvo": self.ultimo,
            "em_formacao": self.em_formacao,
            "lacunas_hoje": self.lacunas_hoje,
            "gravados_hoje": self.gravados,
            # recuperados e revisados recomeçam do zero quando a captura reabre
            "recuperados_hoje": self.recuperados,
            "revisados_hoje": self.revisados,
            "conferencia": self.conferencia,
            "banco_ocupado_desde": self.banco_ocupado_desde,
            # só um desvio que importa: abaixo de 30 s é ruído do tick
            "relogio_desvio_s": (round(self.desvio, 1)
                                 if self.desvio is not None and abs(self.desvio) > 30
                                 else None),
            "primeiro_candle_hoje": self.primeiro_hoje,
            "erro": erro,
        }
        try:
            C.escrever_estado(self.pasta / "estado.json", dados)
        except OSError:
            # a tela segurando o arquivo não pode parar a gravação de candles
            log.exception("não consegui escrever o estado.json")

    def passo_seguro(self) -> float:
        """A volta como o `rodar()` a faz: erro passageiro vai para o log e
        para o estado, e o laço segue."""
        try:
            return self.volta()
        except ErroDeConfiguracao:
            raise
        except Exception as e:
            log.exception("erro na volta da captura")
            try:
                self.publicar(self.agora(), erro=str(e))
            except Exception:
                log.exception("não consegui publicar o erro no estado")
            return 5

    def rodar(self) -> None:
        while True:
            time.sleep(self.passo_seguro())


def _configurar_log() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%d/%m %H:%M:%S")
    arquivo = RotatingFileHandler(PASTA / "captura.log", maxBytes=5 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    for h in (arquivo, console):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def _terminal_da_conta() -> str | None:
    """Com dois MT5 instalados, o caminho cadastrado na conta diz qual abrir."""
    try:
        with db.connect(read_only=True, tentativas=4) as con:
            linha = con.execute(
                "SELECT terminal FROM contas WHERE arquivada_em IS NULL "
                "AND terminal IS NOT NULL ORDER BY conta_id DESC LIMIT 1").fetchone()
    except Exception:
        return None
    return linha[0] if linha else None


def _estado_de_erro(erro: str) -> None:
    with contextlib.suppress(Exception):
        C.escrever_estado(PASTA / "estado.json", {
            "pid": os.getpid(), "atualizado_em": datetime.now(), "mt5": "fechado",
            "erro": erro})


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Serviço de captura de candles M1.")
    p.add_argument("--simbolo", default="WIN$N")
    p.add_argument("--terminal", default=None, help="caminho do terminal64.exe")
    args = p.parse_args(argv)

    # A trava vem antes do log: a segunda janela não pode escrever no log da
    # primeira (nem girá-lo).
    trava = travar(PASTA / "captura.lock")
    if trava is None:
        print("outra janela da captura já está aberta")
        return OUTRA_INSTANCIA
    _configurar_log()

    try:
        import MetaTrader5 as mt5
    except ImportError:
        msg = "o pacote MetaTrader5 não está instalado neste computador"
        log.error(msg)
        _estado_de_erro(msg)
        return SAIR_SEM_REABRIR

    terminal = args.terminal or _terminal_da_conta()
    servico = Servico(mt5=mt5, simbolo=args.simbolo, terminal=terminal, pasta=PASTA)
    log.info("captura iniciada: %s, terminal %s", args.simbolo, terminal or "padrão")
    try:
        servico.rodar()
    except KeyboardInterrupt:
        log.info("captura encerrada pelo usuário")
        with contextlib.suppress(Exception):
            mt5.shutdown()
        return 0
    except ErroDeConfiguracao as e:
        log.error("erro de configuração: %s", e)
        servico.publicar(datetime.now(), erro=str(e))
        return SAIR_SEM_REABRIR
    finally:
        trava.close()


if __name__ == "__main__":
    sys.exit(main())
