"""Serviço de captura — grava cada candle M1 fechado do WIN$N, ao vivo.

    .venv/Scripts/python.exe captura.py      (o iniciar.bat abre numa janela própria)

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md.
Processo à parte da tela de propósito: a tela reinicia a cada mudança e
trava em mineração; um laço contínuo dentro dela perderia candle (e, na
parte 4, ordem). Toda decisão mora em core/captura.py (candles) e em
core/ordens.py (ordens); aqui só o laço.

Parte 4 (spec 2026-10-08-ao-vivo-ordens-design.md §3): as ordens rodam no
mesmo fio (o pacote MetaTrader5 não é seguro entre threads), em cada volta,
ANTES de qualquer escrita no banco — gravar candle, papel, conferência e
Parquet podem levar segundos, e uma saída não espera por eles.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, time as hora, timedelta, timezone
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np
import polars as pl

from core import calendar as cal
from core import captura as C
from core import comandos, contrato_dia, diario_ordens, ordens, papel
from core import corretora as K
from core import db_manager as db
from core import papel_backtest, papel_vivo, ponte
from core import rollovers as roll
from core.mt5_source import barras_de_taxas

SAIR_SEM_REABRIR = 3      # configuração: reabrir não resolve
OUTRA_INSTANCIA = 4       # já há uma captura rodando: o .bat sai calado
PASTA = db.DATA / "ao_vivo"
ESPERA_ACK_S = 0.2        # quanto a demo espera a real tratar um seq novo (R11)

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

# Logo após o login o terminal ainda carrega a lista de símbolos e o
# symbol_select pode falhar uma vez: só três voltas seguidas recusando
# viram erro de configuração (que fecha a captura de vez).
FALHAS_SIMBOLO = 3
# O padrão do initialize() é 60 s: com o terminal travado, a volta inteira
# (e o estado que a tela lê) pararia junto.
TIMEOUT_INICIALIZAR_MS = 10_000

# Perto da virada do minuto (servidor, no pregão) a volta roda a cada 0,1 s:
# a entrada do backtest é na abertura do minuto, e cada segundo de atraso
# é derrapagem que ele não tem (spec §3.1). Do segundo 58 ao 10.
VOLTA_RAPIDA = 0.1
RAPIDA_ANTES_S, RAPIDA_DEPOIS_S = 58, 10
# O retrato da configuração (ligações, fases, contas, Envio) é relido a cada
# 5 s, com UMA tentativa sem espera: o banco ocupado por uma mineração não
# pode atrasar a volta das ordens; fica o retrato anterior.
A_CADA_RETRATO = 5


def _json_simples(o):
    """Decimal do banco (limite da conta) vira número; o resto, texto."""
    return float(o) if isinstance(o, Decimal) else str(o)
# Falha que se repete a cada volta: traceback uma vez, depois uma linha por minuto.
LOG_REPETIDO_S = 60
# A conferência papel × backtest roda o backtest do histórico inteiro
# (segundos): só fora do pregão — antes das 08:57 (folga para a fila não
# atravessar a abertura das 09:00) ou depois do fechamento.
BACKTEST_ATE = hora(8, 57)
_HOJE_VAZIO = {"ts": np.array([], dtype="datetime64[ns]"),
               **{k: np.array([], dtype=np.int64)
                  for k in ("open", "high", "low", "close", "tick_volume", "volume")}}


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


def _espelho_em(simbolo: str) -> datetime:
    """Quando o espelho Parquet foi gravado (hora local, como o ingested_at);
    sem espelho, `datetime.min` — mais velho que qualquer conferência."""
    pasta = db.PARQUET_DIR / db.safe_symbol(simbolo)
    tempos = [p.stat().st_mtime for p in pasta.rglob("*.parquet")] if pasta.exists() else []
    return datetime.fromtimestamp(max(tempos)) if tempos else datetime.min


def _utc(d: datetime) -> datetime:
    # O pacote MetaTrader5 converte datetime sem fuso pelo fuso do PC; marcado
    # como UTC, o valor segue como está (ver mt5_source.buscar_barras).
    return d.replace(tzinfo=timezone.utc)


class Servico:
    def __init__(self, mt5, simbolo="WIN$N", terminal=None, agora=datetime.now,
                 mono=time.monotonic, pasta=PASTA, terminal_aberto=terminal_aberto,
                 price_decimals=None):
        self.mt5, self.simbolo, self.terminal = mt5, simbolo, terminal
        self.agora, self.mono, self.pasta = agora, mono, Path(pasta)
        self.terminal_aberto = terminal_aberto
        # Sem o YAML não dá para refazer as rolagens na conferência. O erro
        # sobe na primeira volta, não aqui: o main precisa do Servico para
        # publicar o aviso no estado.
        try:
            self.inst = db.load_instrument_yaml(simbolo)
            self._sem_yaml = None
        except FileNotFoundError as e:
            self.inst, self._sem_yaml = {}, str(e)
        # o arredondamento tem de ser o mesmo do ingest manual e do
        # Sincronizar, senão cada um regravaria o candle do outro
        self.price_decimals = (self.inst.get("price_decimals", 0)
                               if price_decimals is None else price_decimals)
        self.relogio = C.RelogioServidor()

        self.carregado = False          # leitura inicial do banco já feita
        self.dia = None
        self.ultimo = None              # maior ts salvo no banco
        self.fechamento = None
        self.conectado = False          # initialize() feito e válido
        self.novo_login = False
        self.falhas_simbolo = 0
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
        self.reexportar = False         # dia conferido sem pregões/Parquet refeitos
        self._dias_conferidos: list = []
        # A reconferência da manhã tem estado próprio: falhar nela não é a
        # conferência de HOJE falhar, e rodar às 08:56 não a conclui.
        self.reconferencia = {"em": None, "dias": [], "erro": None, "abandonados": []}
        self._abandonados_avisados: set = set()
        # Quando a captura reescreveu candles já espelhados (conferência de
        # qualquer dia, reconferência): a tela limpa o cache de barras.
        self.base_alterada_em = None
        # O papel (spec 2026-10-02-ao-vivo-papel §4.4.6). O cache vive o
        # processo inteiro: guarda o módulo de cada estratégia pelo hash do
        # arquivo, para recarregar só quando o código no disco muda.
        self.cache_codigo: dict = {}
        # "Refazer o papel sem esperar candle": com o banco ocupado, e na
        # subida — o processo pode ter caído no meio do pregão, e o papel
        # gravado não pode ficar parado até o próximo candle (ordens §5.1).
        self.papel_pendente = True
        self.papel_em = None
        # por origem: o cálculo de um minuto dar certo não apaga a falha da
        # conferência de ontem, e vice-versa
        self.papel_erros = {"calculo": None, "conferencia": None}
        self.papel_ligacoes: dict = {}
        self._papel_ok = True           # nenhuma falha do papel nesta janela
        self.papel_divergencias = 0
        self._schema_ok = False         # tabelas do papel criadas neste banco

        # Ordens (spec 2026-10-08-ao-vivo-ordens §3, §5). O caminho da ordem
        # não usa o banco: retrato, aquecimento e desejados vivem aqui, em
        # memória. A pasta do diário é lida de `diario_ordens.PASTA` agora
        # (nunca importada): o conftest a desvia nos testes. Sem o YAML não
        # há tick nem valor do ponto — a primeira volta já sai com o erro.
        self.motor = (ordens.Motor(diario_ordens.PASTA, self.inst,
                                   relogio=lambda: self.relogio.agora(self.mono()),
                                   mono=self.mono)
                      if self.inst else None)
        self.retrato = None             # papel_vivo.Retrato da configuração
        self.retrato_em = None          # hora (servidor) do retrato em memória
        self._retrato_tentado = None    # mono da última tentativa de leitura
        self._retrato_salvo = None      # conteúdo do último retrato salvo em arquivo
        self.aquecimento = None         # papel_vivo.Aquecimento do dia
        self.aquecimento_chave = None   # plano_id das ligações quando carregou
        # `self.contrato` (acima) é o texto publicado como contrato_vigente;
        # o contrato que a automação opera hoje é o dict de contrato_dia
        self.contrato_dia = None
        self.guarda = contrato_dia.GuardaPreco(int(self.inst.get("tick_size", 5)))
        self._guarda_bloqueada = False
        self.conectado_desde = None     # mono da última passagem a "conectado"
        self.ordens_estado = None       # bloco "ordens" do estado.json
        # o último que o passo viu: com as ordens paradas (fora do pregão,
        # MT5 fora) o selo do topo ainda diz se há demo e de que conta
        self._n_demo = None
        self._conta_logada = None
        # Os desejados só se recalculam quando o minuto em formação, as
        # barras fechadas de hoje ou as ligações do retrato mudam: a volta
        # de 0,1 s não pode refazer o papel dez vezes por segundo.
        self._minuto_calculado = None
        self._desejados: dict = {}
        # o que vai ao motor: `_desejados` com o zerado no toque do stop/alvo
        # pelo candle em formação (`_aplicar_toque`, a cada volta)
        self._desejados_ordens: dict = {}
        self._formacao = None           # (máxima, mínima) do minuto em formação
        self._toque_em: dict = {}       # ligação -> hora da primeira volta tocada
        self._disponivel = False
        # ponte com a real: o seq sobe só quando o conteúdo publicado muda
        # (reinício zera; a real compara "mudou", não "aumentou")
        self._seq_ponte = 0
        self._ponte_conteudo = None
        self._versao_papel = 0         # sobe quando retrato/aquecimento mudam
        self._ordens_dia = None
        self._contrato_falha = None     # último motivo logado (sem repetir no log)
        # O diário das ordens vai ao banco na escrita que a volta já abre;
        # na subida e na virada do dia vão os arquivos dos últimos dias
        # inteiros (eventos depois do último candle de ontem, queda antes
        # do espelho).
        self._espelhar_tudo = True
        self._falhas_log: dict = {}     # onde -> (mensagem, mono do último log)
        # o minuto (servidor) cujas ordens já rodaram com a barra dele: até
        # lá, perto da virada, nenhum passo do banco roda (ordens primeiro)
        self._minuto_ordens = None
        self._provisoria_ts = None
        # (ligação, dia) cujo papel × backtest falhou neste processo: uma
        # falha que se repete não volta a cada janela de 5 min
        self._backtest_falhou: set = set()

    # ------------------------------------------------------------- banco
    @contextlib.contextmanager
    def _banco(self, agora, escrita: bool):
        """No máximo ~1 s de espera fora do pregão; NENHUMA no pregão: a
        volta da virada do minuto (0,1 s) não pode dormir atrás de uma
        mineração gravando ou da tela lendo — a próxima volta tenta de novo.
        Ocupado vira `_Ocupado`, que o passo trata como "pula"."""
        tentativas, espera = (1, 0) if self._no_pregao(agora) else (4, 0.25)
        try:
            con = (db.connect_write(tentativas=tentativas, espera=espera) if escrita
                   else db.connect(read_only=True, tentativas=tentativas, espera=espera))
        except RuntimeError:
            self.banco_ocupado_desde = self.banco_ocupado_desde or agora
            raise _Ocupado from None
        try:
            yield con
        finally:
            con.close()

    def _gravou(self) -> None:
        self.banco_ocupado_desde = None

    def _no_pregao(self, agora) -> bool:
        """Pregão AGORA, pela hora do servidor desta volta (do PC sem ela):
        horário do pregão ou mercado vivo depois do fechamento esperado — a
        mesma régua do `self.pregao`, que só é atualizado no fim da volta."""
        srv = (self.agora_srv if self.mt5_estado == "conectado" else None) or agora
        novo = self.candle_mais_novo
        return C.em_pregao(srv, self.fechamento or C.FECHAMENTO_PADRAO) or (
            novo is not None and novo.date() == srv.date() and srv - novo < MERCADO_VIVO)

    def _falha(self, onde: str, erro: Exception) -> None:
        """Log de uma falha que pode se repetir a cada volta (0,1 s): o
        traceback uma vez por mensagem distinta, depois uma linha curta no
        máximo a cada minuto — senão o log rotativo giraria em minutos."""
        texto = f"{type(erro).__name__}: {erro}"
        # a "mesma" falha com outro ticket, retcode ou hora não é distinta:
        # tipo + primeira linha, com os números trocados por #
        linha = (str(erro).splitlines() or [""])[0]
        chave = f"{type(erro).__name__}: {re.sub(r'[0-9]+', '#', linha)}"
        m = self.mono()
        ultimo = self._falhas_log.get(onde)
        if ultimo is None or ultimo[0] != chave:
            log.error("%s", onde, exc_info=erro)
        elif m - ultimo[1] >= LOG_REPETIDO_S:
            log.warning("%s (segue falhando): %s", onde, texto)
        else:
            return
        self._falhas_log[onde] = (chave, m)

    def _sem_falha(self, onde: str) -> None:
        # voltou a dar certo: a próxima falha merece o traceback de novo
        self._falhas_log.pop(onde, None)

    def _espelhar(self, con, agora, tudo: bool = False) -> None:
        """Leva o diário das ordens ao banco (`ordens_eventos`) na conexão
        de escrita que a volta JÁ abriu — nunca uma escrita só para isto, e
        nunca dentro de `db.transacao` (cada evento entra sozinho; um que
        falhe não leva os outros junto). O diário em arquivo é a verdade;
        o banco é espelho e pode atrasar (spec ordens §7.2)."""
        if self.motor is None:
            return
        try:
            if tudo or self._espelhar_tudo:
                diario_ordens.espelhar_pendentes(
                    diario_ordens.PASTA, con, hoje=(self.agora_srv or agora).date())
                self._espelhar_tudo = False
            elif self.motor._diario is not None:
                self.motor._diario.espelhar(con)
        except Exception as e:
            # o espelho não pode custar o candle que acabou de ser gravado
            self._falha("não consegui espelhar o diário das ordens no banco", e)
        else:
            self._sem_falha("não consegui espelhar o diário das ordens no banco")

    def _garantir_schema(self, agora) -> None:
        """As tabelas que a captura usa e o app cria na subida (papel_*).

        A captura abre pelo `iniciar.bat` junto com o app, e nada garante
        que o app subiu primeiro com o schema novo: no banco que ainda não
        tem `papel_pregoes`, todo cálculo do papel falhava. Idempotente
        (`IF NOT EXISTS`), uma vez por processo; banco ocupado tenta de novo
        na volta seguinte, sem segurar a captura dos candles.
        """
        try:
            with self._banco(agora, escrita=True) as con:
                db.init_schema(con)
                # a primeira escrita da subida: o diário que ficou sem
                # espelho (queda, banco ocupado) chega ao banco aqui
                self._espelhar(con, agora)
        except _Ocupado:
            return
        except Exception:
            # schema que não sobe (ex.: tabela de mineração divergente) é
            # problema do app; o papel acusa a falha sozinho, os candles seguem
            log.exception("não consegui conferir o schema do banco")
        else:
            self._gravou()
        self._schema_ok = True

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
                ultima_conf = con.execute(
                    "SELECT max(ingested_at) FROM ingest_log WHERE symbol = ? "
                    "AND (source_file LIKE ? OR source_file LIKE ?)",
                    [self.simbolo, C.PREFIXO_CONFERENCIA + "%",
                     C.PREFIXO_RECONFERENCIA + "%"]).fetchone()[0]
                # A marca de "reexportar" não sobrevive ao processo: se a
                # captura caiu entre a conferência e o Parquet, o espelho
                # mais velho que a última conferência denuncia.
                self.reexportar = (ultima_conf is not None
                                   and _espelho_em(self.simbolo) < ultima_conf)
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
    def _mt5(self, agora, m=None) -> bool:
        mt5 = self.mt5
        if not self.conectado:
            if self.terminal_aberto():
                espera = {"timeout": TIMEOUT_INICIALIZAR_MS}
                ok = (mt5.initialize(path=self.terminal, **espera) if self.terminal
                      else mt5.initialize(**espera))
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
        if self.novo_login:
            # a cada (re)conexão: o usuário pode ter trocado de conta no terminal
            if not mt5.symbol_select(self.simbolo, True):
                self.falhas_simbolo += 1
                if self.falhas_simbolo >= FALHAS_SIMBOLO:
                    raise ErroDeConfiguracao(f"o MT5 não tem {self.simbolo}")
                # novo_login segue ligado: a volta seguinte tenta de novo
                return self._fora_do_ar("sem_conexao", agora)
            self.falhas_simbolo = 0
            conta = mt5.account_info()
            self.conta = ({"login": int(conta.login), "servidor": conta.server}
                          if conta is not None else None)
            # na série contínua (WIN$N) a Clear devolve basis vazio: None, não ""
            self.contrato = getattr(mt5.symbol_info(self.simbolo), "basis", None) or None
            self.novo_login = False
        else:
            # a cada volta, não só no login: o usuário pode trocar de conta
            # no terminal sem a conexão cair (spec ordens §4, item 6). A
            # conferência que barra a ordem é a do Motor, pela fotografia.
            conta = mt5.account_info()
            if conta is not None:
                self.conta = {"login": int(conta.login), "servidor": conta.server}
        if self.mt5_estado != "conectado":
            # toda volta ao "conectado" — initialize novo ou a corretora que
            # caiu e voltou com o terminal aberto — reinicia a graça de 5 s
            # sem entradas (a lista de posições pode vir vazia) e a escolha
            # do contrato do dia
            self.conectado_desde = self.mono() if m is None else m
            self.contrato_dia = None
        self.mt5_estado, self.mt5_desde = "conectado", None
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
    def _buscar_e_gravar(self, agora, m) -> bool:
        """Devolve se gravou candle: só então o papel tem o que recalcular."""
        df = self._taxas(self.ultimo + timedelta(minutes=1), agora + timedelta(days=1))
        if df is None:
            self.em_formacao = None
            return False
        prontos = C.fechados(df, self.agora_srv)
        ultima = df.row(-1, named=True)
        self.em_formacao = ({k: ultima[k] for k in ("ts", "open", "high", "low", "close")}
                            if prontos.height < df.height else None)
        mais_novo = df["ts"].max()
        if self.candle_mais_novo is None or mais_novo > self.candle_mais_novo:
            self.candle_mais_novo = mais_novo
        if prontos.height == 0:
            return False
        try:
            with self._banco(agora, escrita=True) as con:
                r = C.gravar(con, self.simbolo, prontos, self._origem(), self.price_decimals)
                # o candle primeiro; o diário das ordens pega carona no escritor
                self._espelhar(con, agora)
        except _Ocupado:
            # sem avançar `ultimo`: a volta seguinte pede os mesmos candles ao MT5
            return False
        self._gravou()
        self.ultimo = max(self.ultimo, prontos["ts"].max())
        # Voltando de dias desligado, o lote traz dias anteriores; o placar é
        # de hoje e precisa bater com o que o reinício relê do banco. O
        # `inseridos` é do lote inteiro: o min cobre o caso normal, em que
        # tudo depois do último salvo é novo.
        de_hoje = prontos.filter(pl.col("ts").dt.date() == agora.date())
        self.gravados += min(r["inseridos"], de_hoje.height)
        self.revisados += r["revisados"]
        limite = (self.agora_srv or agora) - timedelta(minutes=2)
        self.recuperados += de_hoje.filter(pl.col("ts") < limite).height
        self._marca_primeiro(prontos, agora)
        return True

    def _marca_primeiro(self, barras: pl.DataFrame, agora) -> None:
        de_hoje = barras.filter(pl.col("ts").dt.date() == agora.date())
        if de_hoje.height and (self.primeiro_hoje is None
                               or de_hoje["ts"].min() < self.primeiro_hoje):
            self.primeiro_hoje = de_hoje["ts"].min()

    def _lacunas(self, agora, m) -> bool:
        """Devolve se recuperou candle (o papel do dia mudou com ele)."""
        if not C.em_pregao(agora, self.fechamento):
            return False
        if self._mono_lacuna is not None and m - self._mono_lacuna < A_CADA_LACUNA:
            return False
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
            return False
        self._mono_lacuna = m
        faltam = C.lacunas(mt5_hoje["ts"].to_list(), banco)
        self.lacunas_hoje = faltam
        if not faltam:
            return False
        # a recuperação é o mesmo gravar: a lacuna se fecha sozinha
        repor = mt5_hoje.filter(pl.col("ts").is_in(faltam))
        try:
            with self._banco(agora, escrita=True) as con:
                r = C.gravar(con, self.simbolo, repor, self._origem(), self.price_decimals)
        except _Ocupado:
            return False
        self._gravou()
        log.info("lacuna recuperada: %d candle(s) de %s a %s",
                 repor.height, faltam[0], faltam[-1])
        self.lacunas_hoje = []
        self.gravados += r["inseridos"]
        self.revisados += r["revisados"]
        self.recuperados += r["inseridos"]
        self.ultimo = max(self.ultimo, repor["ts"].max())
        self._marca_primeiro(repor, agora)
        return True

    def _papel(self, agora) -> None:
        """O papel de hoje, recalculado inteiro (o pregão até o último candle).

        Calcula numa leitura curta e só depois pega o escritor: o motor não
        pode segurar a trava do banco (spec §4.4.6). Banco ocupado vira
        "pendente", refeito na volta seguinte mesmo sem candle novo — senão
        o papel ficaria um minuto atrás até o próximo candle. Qualquer outra
        falha vai para o log e para o estado, nunca para a volta: a captura
        existe para gravar candles, e o `publicar` não pode atrasar por causa
        do papel.
        """
        dia = agora.date()
        self.papel_pendente = False
        # O minuto em formação vira barra provisória (spec ordens §3): sem
        # ela a entrada do sinal das 10:00 só apareceria às 10:02 no papel
        # gravado, um minuto depois da ordem da demo.
        # com máxima/mínima: o papel fecha a operação no toque do stop/alvo
        # (`papel.calcular`), como a ordem da corretora
        em = self.em_formacao
        provisoria = ((em["ts"], int(round(em["open"])),
                       int(round(em["high"])), int(round(em["low"])))
                      if em and em["ts"].date() == dia else None)
        try:
            with self._banco(agora, escrita=False) as con:
                res = papel.rodar_dia(con, dia, agora, self.cache_codigo,
                                      symbol=self.simbolo, provisoria=provisoria)
            if res:
                with self._banco(agora, escrita=True) as con:
                    papel.gravar(con, res, agora)
                self._gravou()
        except _Ocupado:
            self.papel_pendente = True
            return
        except Exception as e:
            # sem "pendente": a mesma falha a cada segundo só encheria o log;
            # o candle seguinte tenta de novo
            log.exception("papel do dia %s falhou", dia)
            self.papel_erros["calculo"] = str(e)
            return
        self.papel_em = agora
        self.papel_erros["calculo"] = None
        self._anotar_papel(res)

    def _anotar_papel(self, resultados) -> None:
        # O `dia` vai junto: um pregão de ontem que ficou "rodando" (o cálculo
        # falhou na conferência) não pode parecer o pregão de hoje na tela.
        for r in resultados:
            self.papel_ligacoes[str(r["ligacao_id"])] = {
                "status": r["status"], "motivo": r["motivo"], "dia": r["dia"]}

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
        falha_papel = None
        try:
            with self._banco(agora, escrita=False) as con:
                dias = C.dias_pendentes(con, self.simbolo, agora.date(),
                                        self._fechou_hoje(agora))
                rever = [d for d in C.dias_a_reconferir(con, self.simbolo, agora.date())
                         if C.pode_reconferir(d, agora)]
                self._avisar_abandonados(C.dias_abandonados(con, self.simbolo,
                                                            agora.date()))
                try:
                    papel_dias = [d for d in self._papel_a_conferir(con)
                                  if d not in dias]
                    reabrir = self._papel_a_reabrir(con)
                except Exception as e:
                    # Os candles não esperam o papel: um erro aqui (a tabela
                    # do papel ainda não existe, uma consulta que quebrou)
                    # impedia a conferência e o Parquet do dia, a cada volta
                    # de 1 s, com um traceback no log a cada vez.
                    log.exception("não consegui listar o papel por conferir")
                    falha_papel = str(e)
                    papel_dias, reabrir = [], []
                backtest = self._backtest_pendentes(con, agora)
                self._divergencias(con)
        except _Ocupado:
            return      # a janela não conta: tenta de novo na volta seguinte
        if falha_papel is not None:
            self.papel_erros["conferencia"] = falha_papel
        elif not dias and not papel_dias:
            # nada do papel por conferir: uma falha antiga já não vale
            self.papel_erros["conferencia"] = None
        if not (dias or rever or reabrir or self.reexportar or papel_dias or backtest):
            self._mono_conferencia = m
            return
        try:
            # Os dias vêm do MT5 antes de pegar o escritor: a mineração e a
            # tela não esperam o terminal responder.
            barras = {dia: self._barras_do_dia(dia, agora) for dia in dias}
            rebarras, reerros = self._barras_para_reconferir(rever, agora)
            with self._banco(agora, escrita=True) as con:
                self._mono_conferencia = m
                # os eventos das ordens depois do último candle do dia (a
                # zeragem do fechamento) só chegam ao banco por esta escrita
                self._espelhar(con, agora, tudo=True)
                self._papel_ok = True
                # antes dos candles: uma falha na conferência deles não pode
                # adiar de novo o papel de um dia que já foi conferido
                for dia in papel_dias:
                    self._conferir_papel(con, dia, agora)
                feitos = self._reconferir_com(con, agora, rebarras, reerros)
                # Depois dos candles, e também para dia reconferido antes:
                # se o processo caiu entre os candles e o papel, é a
                # divergência que o traz de volta (`_papel_a_reabrir`).
                for dia in sorted(set(reabrir) | set(feitos)):
                    self._reabrir_papel(con, dia, agora)
                self._conferir_com(con, agora, barras)
                if self._papel_ok and falha_papel is None:
                    self.papel_erros["conferencia"] = None
                # por último: o papel tem de estar reaberto e conferido nos
                # candles finais antes de ser comparado com o backtest
                self._conferir_backtest(con, agora)
        except _Ocupado:
            return
        except ErroDeConfiguracao:
            raise
        except Exception as e:
            # Falha do MT5 antes do escritor também gasta a janela: sem isto
            # a conferência se repetiria a cada volta de 1 s, com um traceback
            # no log a cada vez — o log rotativo giraria em poucas horas.
            self._mono_conferencia = m
            log.exception("conferência do dia falhou")
            if dias or not rever:
                self.conferencia = {"status": "falhou", "em": agora,
                                    "dias": self._dias_conferidos, "erro": str(e)}
            else:
                # janela só da reconferência: o cartão de hoje não é dela
                self.reconferencia = {**self.reconferencia, "erro": str(e)}

    def _pode_backtest(self, agora) -> bool:
        """A conferência papel × backtest roda o backtest do histórico
        inteiro (segundos com a trava do banco): só antes das 08:57 ou
        depois do fechamento — nunca no meio de um pregão com ordens.

        Pela hora do servidor AGORA (não a do começo da volta): cada pregão
        conferido custa segundos, e a fila da manhã não pode atravessar a
        abertura. Sem relógio do servidor, o do PC agora."""
        srv = self.relogio.agora(self.mono()) or self.agora()
        if srv.weekday() >= 5 or srv.time() < BACKTEST_ATE:
            return True
        return self.fechamento is not None and self._fechou_hoje(agora)

    def _backtest_pendentes(self, con, agora) -> list:
        if not self._pode_backtest(agora):
            return []
        try:
            return [p for p in papel_backtest.pendentes(con, self.simbolo)
                    if p not in self._backtest_falhou]
        except Exception:
            log.exception("não consegui listar a conferência papel × backtest")
            return []

    def _conferir_backtest(self, con, agora) -> None:
        """Cada pregão pendente à parte: um plano que não roda não impede
        a conferência dos outros, nem a dos candles (já gravada). O relógio
        é conferido antes de cada um; passou do corte, o resto fica para a
        próxima janela. Pregão que falha não volta neste processo (o mesmo
        erro a cada 5 min só encheria o log e seguraria o escritor)."""
        for p in self._backtest_pendentes(con, agora):
            if not self._pode_backtest(agora):
                log.info("papel × backtest: corte da manhã; o resto fica para depois")
                break
            lig, dia = p
            try:
                papel_backtest.conferir(con, lig, dia, self.cache_codigo, agora,
                                        symbol=self.simbolo)
            except Exception:
                log.exception("papel × backtest da ligação %s em %s falhou "
                              "(não tento de novo até reabrir a captura)", lig, dia)
                self._backtest_falhou.add(p)

    def _conferir_papel(self, con, dia, agora) -> None:
        """A última volta do papel do dia, com os candles já conferidos —
        inclusive dia recuperado de PC desligado, que só ganha papel aqui.
        Na mesma conexão de escrita da conferência: o checksum gravado tem
        de ser o das barras que acabaram de ser conferidas."""
        try:
            res = papel.conferir(con, dia, agora, self.cache_codigo,
                                 symbol=self.simbolo)
        except Exception as e:
            # os candles do dia estão conferidos e isso não se desfaz por
            # causa do papel; o pregão segue "rodando" e `_papel_a_conferir`
            # o traz de volta na próxima janela
            log.exception("papel da conferência de %s falhou", dia)
            self.papel_erros["conferencia"] = f"{dia:%d/%m/%Y}: {e}"
            self._papel_ok = False
            return
        self.papel_em = agora
        self._anotar_papel(res)

    def _papel_a_conferir(self, con) -> list:
        """Dias com os candles já conferidos e o papel não: a marca
        conferencia://<dia> é gravada ANTES do papel, então o dia sai das
        pendências dos candles mesmo se o papel falhar, ou se o processo
        fechar entre um e outro. Sem isto o pregão ficaria "rodando" para
        sempre — operação aberta aberta, divergência cega.

        Pregão "rodando" ou ligação sem linha no dia. Só a partir do primeiro
        pregão de papel gravado: os dias anteriores ao papel existir não são
        "pendências", e conferi-los agora inventaria um histórico de papel
        que nunca rodou ao vivo.
        """
        prefixo = C.PREFIXO_CONFERENCIA
        candidatos = [r[0] for r in con.execute(
            "WITH conf AS (SELECT DISTINCT CAST(substr(source_file, ?) AS DATE) AS d "
            "  FROM ingest_log WHERE symbol = ? AND source_file LIKE ?) "
            "SELECT DISTINCT c.d FROM conf c "
            # removida no próprio dia (ou depois) ainda tem o pregão daquele
            # dia a encerrar — `papel.rodar_dia` o interrompe
            "JOIN portfolio_membros pm "
            "  ON (pm.removido_em IS NULL OR pm.removido_em >= c.d) "
            "  AND pm.adicionado_em < c.d + INTERVAL 1 DAY "
            "LEFT JOIN papel_pregoes pp ON pp.ligacao_id = pm.ligacao_id AND pp.dia = c.d "
            "WHERE c.d >= (SELECT min(dia) FROM papel_pregoes) "
            # sem linha no dia só pede papel quem não saiu nele: removida
            # antes do primeiro cálculo não tem pregão a encerrar, e o
            # papel nunca cria um para ela — o dia voltaria a cada janela
            "  AND (pp.status = 'rodando' OR (pp.status IS NULL AND "
            "       (pm.removido_em IS NULL "
            "        OR pm.removido_em >= c.d + INTERVAL 1 DAY))) ORDER BY c.d",
            [len(prefixo) + 1, self.simbolo, prefixo + "%"]).fetchall()]
        out = []
        for dia in candidatos:
            # a regra fina de quem entra no papel do dia (plano do símbolo,
            # adicionada até o fim do dia) é a do próprio papel
            gravados = dict(con.execute(
                "SELECT ligacao_id, status FROM papel_pregoes WHERE dia = ?",
                [dia]).fetchall())
            # a mesma regra do SQL: removida no dia sem linha = nada a fazer
            if any(gravados.get(l["ligacao_id"],
                                None if l["removida_em"] else "rodando")
                   == "rodando"
                   for l in papel.ligacoes_do_papel(con, self.simbolo, dia)):
                out.append(dia)
        return out

    def _divergencias(self, con) -> None:
        # Uma soma por dia conferido: barato, mas a cada candle seria
        # desperdício. Na janela da conferência (5 min) basta — candle
        # corrigido depois só vem de reimportação ou reparo.
        try:
            self.papel_divergencias = len(papel.divergencias(con, self.simbolo))
        except Exception:
            log.exception("não consegui conferir as divergências do papel")

    def _barras_do_dia(self, dia, agora) -> pl.DataFrame:
        zero = datetime.combine(dia, datetime.min.time())
        df = self._taxas(zero, zero + timedelta(hours=23, minutes=59))
        if df is None:
            return pl.DataFrame(schema={"ts": pl.Datetime})
        # dia passado está todo fechado; o de hoje segue a hora do servidor
        return C.fechados(df, self.agora_srv if dia == agora.date() else agora)

    def _barras_para_reconferir(self, dias, agora) -> tuple[dict, list]:
        """Os dias do MT5, um a um: a falha de um (terminal que caiu no meio)
        não pode virar falha da conferência de hoje."""
        barras, erros = {}, []
        for dia in dias:
            try:
                barras[dia] = self._barras_do_dia(dia, agora)
            except Exception as e:
                log.exception("reconferência de %s: MT5 falhou", dia)
                erros.append(f"{dia:%d/%m/%Y}: {e}")
        return barras, erros

    def _reconferir_com(self, con, agora, barras: dict, erros: list) -> list:
        """A manhã seguinte: deixa cada dia já conferido idêntico ao MT5.

        De madrugada a corretora consolida o histórico — o leilão de
        fechamento que a captura gravou como candle próprio (18:31) vai para
        dentro do 18:24 —, e o histórico que o backtest usa é esse. A
        reconstrução e o Parquet ficam com o `_conferir_com` logo depois
        (marca `reexportar`), que já sabe refazê-los se falharem. Devolve os
        dias reconferidos.
        """
        feitos = []
        for dia, df in barras.items():
            try:
                # A marca sai da mesma hora que o papel grava no
                # `calculado_em` (`agora`): é por ela que `papel.reabriveis`
                # separa o papel conferido antes da reconferência (reabre) do
                # conferido depois (congelado, decisão 6). Vence a conferência
                # da véspera sem folga nenhuma: só roda a partir das 08:55.
                r = C.reconferir_dia(con, self.simbolo, dia, df, agora=agora,
                                     price_decimals=self.price_decimals)
            except Exception as e:
                # nada foi apagado (rollback); a próxima janela tenta de novo,
                # até o dia sair do prazo de 5 pregões
                log.warning("reconferência de %s: %s", dia, e)
                erros.append(f"{dia:%d/%m/%Y}: {e}")
                continue
            log.info("reconferência de %s: %d revisado(s), %d faltante(s), "
                     "%d removido(s)", dia, r["revisados"], r["faltantes"],
                     r["removidos"])
            feitos.append(dia)
            self.reexportar = True
        if feitos or erros:
            self.reconferencia = {
                **self.reconferencia,
                "em": agora if feitos else self.reconferencia["em"],
                "dias": feitos, "erro": "; ".join(erros) or None}
        return feitos

    def _reabrir_papel(self, con, dia, agora) -> None:
        try:
            reabertos = papel.reabrir_reconferido(con, dia, symbol=self.simbolo)
        except Exception as e:
            log.exception("papel da reconferência de %s falhou", dia)
            self.papel_erros["conferencia"] = f"{dia:%d/%m/%Y}: {e}"
            self._papel_ok = False
            return
        # Reaberto e não conferido (falha no cálculo) fica "rodando" num dia
        # com a marca conferencia://: `_papel_a_conferir` o traz de volta.
        if reabertos:
            self._conferir_papel(con, dia, agora)

    def _papel_a_reabrir(self, con) -> list:
        """Dias reconferidos com papel conferido em divergência que ainda dá
        para refazer. Pela divergência, não por "acabou de reconferir": a
        captura pode cair entre o COMMIT dos candles e o papel."""
        n = len(C.PREFIXO_RECONFERENCIA) + 1
        marcados = {r[0] for r in con.execute(
            "SELECT DISTINCT CAST(substr(source_file, ?) AS DATE) FROM ingest_log "
            "WHERE symbol = ? AND source_file LIKE ?",
            [n, self.simbolo, C.PREFIXO_RECONFERENCIA + "%"]).fetchall()}
        if not marcados:
            return []
        dias = sorted({d["dia"] for d in papel.divergencias(con, self.simbolo)} & marcados)
        return [d for d in dias if papel.reabriveis(con, d, symbol=self.simbolo)]

    def _avisar_abandonados(self, dias) -> None:
        novos = [d for d in dias if d not in self._abandonados_avisados]
        for d in novos:
            log.warning("reconferência de %s abandonada: o MT5 não o devolveu em "
                        "%d pregões; o dia fica como a conferência o deixou",
                        d, C.PREGOES_PARA_RECONFERIR)
        self._abandonados_avisados |= set(novos)
        self.reconferencia = {**self.reconferencia, "abandonados": list(dias)}

    def _conferir_com(self, con, agora, barras: dict) -> None:
        falhas = []
        for dia, df in barras.items():
            try:
                # A conferência tem de vencer a captura do mesmo dia mesmo com
                # o relógio do PC atrasado: a marca sai da hora mais adiantada
                # entre PC e servidor, mais um minuto de folga.
                marca = max(agora, self.agora_srv or agora) + timedelta(minutes=1)
                r = C.conferir_dia(con, self.simbolo, dia, df, agora=marca,
                                   price_decimals=self.price_decimals)
            except ValueError as e:
                # o MT5 não tem o dia (histórico curto, terminal recém-aberto):
                # o dia segue pendente e volta na próxima janela
                log.warning("conferência de %s: %s", dia, e)
                falhas.append(str(e))
                continue
            log.info("conferência de %s: %d revisado(s), %d faltante(s)",
                     dia, r["revisados"], r["faltantes"])
            self._dias_conferidos.append(dia)
            self._conferir_papel(con, dia, agora)
            # A linha conferencia://<dia> já foi gravada: o dia sai das
            # pendências. Se a reconstrução ou o Parquet falharem daqui em
            # diante, só esta marca faz a próxima janela refazê-los — sem ela
            # a mineração ficaria lendo o espelho velho para sempre.
            self.reexportar = True
        if self.reexportar:
            cal.rebuild_trading_days(con, self.simbolo)
            roll.rebuild_rollovers(con, self.simbolo, self.inst.get("rollover_policy"))
            db.export_parquet(con, self.simbolo)
            self.reexportar = False
            self.base_alterada_em = agora
            self._gravou()
        feitos, self._dias_conferidos = self._dias_conferidos, []
        hoje = agora.date()
        if falhas:
            self.conferencia = {"status": "falhou", "em": agora, "dias": feitos,
                                "erro": "; ".join(falhas)}
        elif hoje in feitos or (self.conferencia.get("status") == "falhou"
                                and self._hoje_conferido(con, hoje)):
            # só a conferência de HOJE conclui o cartão de hoje (ou refazer o
            # Parquet que ela deixou por fazer); a de um dia recuperado ou a
            # reconferência das 08:56 não
            self.conferencia = {"status": "concluida", "em": agora, "dias": feitos}

    def _hoje_conferido(self, con, hoje) -> bool:
        return con.execute(
            "SELECT 1 FROM ingest_log WHERE symbol = ? AND source_file = ?",
            [self.simbolo, f"{C.PREFIXO_CONFERENCIA}{hoje:%Y-%m-%d}"]).fetchone() is not None

    # -------------------------------------------------------------- ordens
    def _ordens(self, agora, m) -> None:
        """A volta das ordens (spec ordens §3, §5). Qualquer erro aqui vai
        para o log, para o estado e para um chamado — nunca para a volta: a
        captura existe para gravar candles, e o papel e a conferência não
        podem parar por causa das ordens."""
        if self.motor is None:
            return
        quando = (self.agora_srv if self.mt5_estado == "conectado" else None) or agora
        try:
            self._ordens_volta(agora, m)
        except Exception as e:
            self._falha("caminho das ordens falhou", e)
            # as ordens deste minuto foram tentadas: um caminho quebrado não
            # segura os candles até o segundo 10 de cada minuto
            self._minuto_ordens = quando.replace(second=0, microsecond=0)
            self.ordens_estado = {"erro": str(e), "vivo_em": quando}
            try:
                self.motor._chamar("ordens_falhou", "ordens_falhou",
                                   f"erro nas ordens: {e}", quando)
            except Exception as e2:
                self._falha("não consegui abrir o chamado da falha das ordens", e2)
            return
        self._sem_falha("caminho das ordens falhou")
        if not (self.ordens_estado or {}).get("falhou"):
            # volta limpa: nada estourou aqui e o passo (se rodou) diz que
            # também não — inclusive nos retornos antecipados dele (conta
            # errada, Algo desligado), que nunca chegam ao fechamento do
            # próprio passo. Se o passo falhou, o chamado é dele e fica.
            try:
                self.motor._fechar("ordens_falhou", quando)
            except Exception as e:
                self._falha("não consegui fechar o chamado da falha das ordens", e)

    def _ordens_volta(self, agora, m) -> None:
        conectado = self.mt5_estado == "conectado"
        srv = self.agora_srv if conectado else None
        # tudo com o mesmo dia (o do servidor): planejar e executar não
        # podem discordar sobre que diário vale (§5.1)
        quando = srv or agora
        dia = quando.date()
        if self._ordens_dia != dia:
            self._virar_dia(dia)
        diario = self.motor.diario(dia)

        if not conectado:
            # sem MT5 nada pode; com posição da automação aberta, o usuário
            # precisa saber (o stop e o alvo seguem no servidor)
            self.motor._condicao(
                "mt5_fora", bool(diario.ligacoes_abertas()),
                "MT5 fora do ar com posição da automação aberta "
                "(stop e alvo seguem na corretora)", agora)
            self.motor.recusar_testes(comandos.PASTA, diario, agora, "MT5 fora do ar")
            self.ordens_estado = self._ordens_paradas("MT5 fora do ar", agora)
            return
        self.motor._fechar("mt5_fora", quando)

        no_pregao = srv is not None and self._no_pregao(srv)
        if not no_pregao and not self._automacao_posicionada(diario):
            self.motor.recusar_testes(comandos.PASTA, diario, quando, "fora do pregão"
                                      if srv is not None else "sem relógio do servidor")
            self.ordens_estado = self._ordens_paradas(
                "fora do pregão" if srv is not None else "sem relógio do servidor",
                quando)
            return

        self._ler_retrato(quando, m)
        if no_pregao:
            self._escolher_contrato(srv, diario)
            self._vigiar_preco(srv)
        self._calcular_desejados(srv)
        self._aplicar_toque(srv)
        # a ponte sai ANTES da demo: a real vê o que a demo vai fazer. Só
        # chega aqui uma volta que calculou os desejados; nos retornos
        # antecipados acima (MT5 fora, fora do pregão sem posição, sem
        # relógio) nada é publicado e a real vê o arquivo velho, que só a
        # protege (R9): é de propósito
        self._publicar_ponte(srv)
        simbolo = (self.contrato_dia or {}).get("simbolo")
        est = self.motor.passo(
            self.mt5, agora_srv=srv, retrato=self.retrato,
            desejados=self._desejados_ordens, disponivel=self._disponivel,
            # a pasta é lida agora (o conftest a desvia); cada comando vai ao
            # diário antes de o arquivo sumir
            comandos=comandos.PASTA, simbolo=simbolo,
            contrato_ok=simbolo is not None and not self._guarda_bloqueada,
            contrato_motivo=self._contrato_motivo(srv),
            conectado_ha_s=(m - self.conectado_desde
                            if self.conectado_desde is not None else 0.0),
            no_pregao=no_pregao)
        # as ordens do minuto em formação já rodaram com a barra dele: os
        # passos do banco desta virada podem seguir (`_banco_espera`)
        if self._provisoria_ts is not None:
            self._minuto_ordens = self._provisoria_ts
        if est.get("n_demo") is not None:
            self._n_demo = est["n_demo"]
        if (est.get("conta") or {}).get("conta_id") is not None:
            self._conta_logada = est["conta"]["conta_id"]
        self.ordens_estado = {**est, **self._ordens_extra()}

    def _publicar_ponte(self, srv) -> None:
        """Publica os desejados para o processo da conta real (spec
        conta-real §4.2, R8–R11). O `seq` sobe só quando o conteúdo muda; a
        falha de escrita não gasta o seq (a próxima volta tenta de novo) e
        nunca levanta para a volta."""
        try:
            dados = ponte.serializar(self._desejados_ordens, self._disponivel,
                                     self.contrato_dia, self._seq_ponte, srv)
            conteudo = {k: v for k, v in dados.items()
                        if k not in ponte.CAMPOS_VIVOS}
            novo = conteudo != self._ponte_conteudo
            if novo:
                dados["seq"] = self._seq_ponte + 1
            if not ponte.escrever(dados) or not novo:
                return
            self._seq_ponte, self._ponte_conteudo = dados["seq"], conteudo
            # sem o processo da real vivo não há quem responda o ack: a demo
            # segue sem esperar (um seq novo não pode atrasar a ordem)
            if ponte.real_ativo():
                self._esperar_ack(self._seq_ponte)
        except Exception:
            log.exception("ponte: não consegui publicar os desejados")

    def _esperar_ack(self, seq) -> bool:
        """Espera a real tratar o `seq` por até 200 ms (laço de 10 ms). Sem
        ack a demo segue: a real fora não segura a demo (R11)."""
        fim = time.monotonic() + ESPERA_ACK_S
        while True:
            if ponte.ler_ack() == seq:
                return True
            if time.monotonic() >= fim:
                return False
            time.sleep(0.01)

    def _contrato_motivo(self, srv):
        """Por que o contrato não opera agora (None = opera). Sem contrato
        escolhido ainda (WIN$N com último 0 às 09:00, lista que falhou) é
        passageiro: a entrada tenta de novo e sai quando a volta seguinte
        escolher. Vencimento hoje e a guarda de preço são do dia/minutos."""
        c = self.contrato_dia or {}
        if c.get("simbolo"):
            return ordens.GUARDA_PRECO if self._guarda_bloqueada else None
        if c.get("vence_em") is not None and srv is not None \
                and c["vence_em"] == srv.date():
            return c.get("motivo") or ordens.SEM_CONTRATO_HOJE
        return ordens.SEM_CONTRATO

    def _virar_dia(self, dia) -> None:
        """Nada atravessa a noite: retrato, aquecimento, contrato e
        desejados do dia anterior não valem hoje (§3: aquecimento uma vez
        por pregão; §5.6: contrato fixo no dia)."""
        if self._ordens_dia is not None:
            self._espelhar_tudo = True      # o fim de ontem ainda não foi ao banco
        self._ordens_dia = dia
        self.retrato = self.retrato_em = self._retrato_tentado = None
        self.aquecimento = self.aquecimento_chave = None
        self.contrato_dia = None
        self.guarda = contrato_dia.GuardaPreco(self.motor.tick)
        self._guarda_bloqueada = False
        self._minuto_calculado, self._desejados, self._disponivel = None, {}, False
        self._desejados_ordens, self._formacao, self._toque_em = {}, None, {}

    def _automacao_posicionada(self, diario) -> bool:
        """Há posição com o magic da automação (na corretora ou aberta no
        diário)? Fora do pregão é só ela que pede o motor. Leitura que falha
        conta como "sim": na dúvida o motor roda (e ele mesmo não decide
        nada sem fotografia confiável)."""
        try:
            pos = self.mt5.positions_get()
        except Exception:
            return True
        if pos is None:
            return True
        # a posição da "Ordem de teste" também: sobrou de antes, é o motor
        # que a encerra
        return (any(K.ligacao_do_magic(p.magic) is not None
                    or int(p.magic or 0) == K.MAGIC_TESTE for p in pos)
                or bool(diario.ligacoes_abertas()))

    def _ordens_paradas(self, motivo, quando) -> dict:
        """Nada sai agora, mas o topo ainda mostra o interruptor do Envio
        (do último retrato: o da conta logada por último, senão qualquer
        conta ligada), a trava do dia e quantas ligações estão na demo —
        o último valor conhecido quando não há retrato."""
        r = self.retrato
        n = ordens.n_demo(r) if r is not None else self._n_demo
        envio = None
        if r is not None:
            contas = r.contas
            cid = self._conta_logada
            envio = (bool(contas[cid].get("envio")) if cid in contas
                     else any(c.get("envio") for c in contas.values()))
        trava = None
        try:
            evs = [e for e in self.motor.diario(quando.date()).eventos
                   if e["tipo"] == "conta_travada"
                   and (self._conta_logada is None
                        or e.get("conta_id") == self._conta_logada)]
        except Exception:
            evs = []        # diário ilegível não pode derrubar o estado
        if evs:
            trava = {"desde": evs[-1]["quando"], "perda": evs[-1].get("perda"),
                     "limite": evs[-1].get("limite")}
        return {"foto": None, "parado": motivo, "vivo_em": quando,
                "n_demo": n, "envio": envio, "travada": trava,
                "chamados": [dict(c, chave=k) for k, c in self.motor.chamados.items()],
                "teste": self.motor.teste.estado(),
                **self._ordens_extra()}

    def _ordens_extra(self) -> dict:
        return {"retrato_em": self.retrato_em, "disponivel": self._disponivel,
                "retrato_antigo": bool(self.retrato is not None and self.retrato.antigo),
                "contrato_dia": self.contrato_dia,
                "preco_contrato_bloqueado": self._guarda_bloqueada}

    def _ler_retrato(self, quando, m) -> None:
        """A configuração do banco, relida a cada 5 s numa tentativa só e
        sem espera: banco ocupado = fica o retrato anterior (o estado mostra
        a idade). A hora é a do servidor: o "zerar tudo" e o desligar do
        Envio só terminam com um retrato lido DEPOIS do comando, e os dois
        relógios têm de ser o mesmo. O aquecimento vem na mesma leitura."""
        if self.retrato is not None and self._janela_da_virada():
            # perto da virada a volta é das ordens: o retrato de segundos
            # atrás serve; reler (preparar o dia, ler o banco) atrasaria a entrada
            return
        if self._retrato_tentado is not None and m - self._retrato_tentado < A_CADA_RETRATO:
            return
        self._retrato_tentado = m
        try:
            con = db.connect(read_only=True, tentativas=1, espera=0)
        except RuntimeError:
            # ocupado: o normal com uma mineração gravando
            self._retrato_do_arquivo()
            return
        except Exception as e:
            self._falha("não consegui abrir o banco para o retrato das ordens", e)
            self._retrato_do_arquivo()
            return
        try:
            with con:
                novo = papel_vivo.ler_retrato(con, quando.date(), quando,
                                              self.cache_codigo, symbol=self.simbolo)
                chave = tuple(sorted(lv.plano["plano_id"] for lv in novo.ligacoes.values()
                                     if lv.plano is not None))
                if (self.aquecimento is None or chave != self.aquecimento_chave
                        or papel_vivo.pregoes_necessarios(novo) > self.aquecimento.pregoes):
                    self.aquecimento = papel_vivo.carregar_aquecimento(
                        con, self.simbolo, quando.date(), novo)
                    self.aquecimento_chave = chave
                    self._versao_papel += 1
        except Exception as e:
            self._falha("não consegui ler o retrato da configuração das ordens", e)
            self._retrato_do_arquivo()
            return
        self._sem_falha("não consegui ler o retrato da configuração das ordens")
        antigo, self.retrato, self.retrato_em = self.retrato, novo, quando
        # relido a cada 5 s, mas os desejados só mudam se as ligações mudaram
        # (fase, ligada, plano, períodos): senão refaria o papel à toa
        if antigo is None or antigo.antigo or antigo.dia != novo.dia \
                or antigo.ligacoes != novo.ligacoes:
            self._versao_papel += 1
        self._salvar_retrato(novo)

    # o retrato salvo (M3): ao lado do diário, lido de diario_ordens.PASTA na
    # hora (o conftest a desvia) — nunca a pasta real num teste
    ARQ_RETRATO = "retrato.json"

    def _salvar_retrato(self, r) -> None:
        """Guarda o último retrato lido do banco num arquivo local, com
        escrita atômica (temporário + replace): a captura que reabre com o
        banco preso pela mineração não fica sem saber a conta e as ligações.
        Só regrava quando o conteúdo muda (o retrato é relido a cada 5 s).
        Falhar aqui nunca para as ordens."""
        try:
            dados = papel_vivo.retrato_para_json(r)
            chave = json.dumps({k: v for k, v in dados.items() if k != "lido_em"},
                               sort_keys=True, default=_json_simples)
            if chave == self._retrato_salvo:
                return
            pasta = Path(diario_ordens.PASTA)
            pasta.mkdir(parents=True, exist_ok=True)
            tmp = pasta / (self.ARQ_RETRATO + ".tmp")
            tmp.write_text(json.dumps(dados, default=_json_simples), encoding="utf-8")
            os.replace(tmp, pasta / self.ARQ_RETRATO)
            self._retrato_salvo = chave
        except Exception as e:
            self._falha("não consegui salvar o retrato das ordens", e)
        else:
            self._sem_falha("não consegui salvar o retrato das ordens")

    def _retrato_do_arquivo(self) -> None:
        """Sem retrato nenhum (subida, virada do dia) e banco indisponível:
        o último salvo, marcado `antigo` — a automação sabe a conta, protege
        e sai por comando; nada entra até o banco responder."""
        if self.retrato is not None:
            return
        arq = Path(diario_ordens.PASTA) / self.ARQ_RETRATO
        if not arq.exists():
            return
        try:
            r = papel_vivo.retrato_de_json(json.loads(arq.read_text(encoding="utf-8")))
        except Exception as e:
            self._falha("não consegui ler o retrato salvo das ordens", e)
            return
        self.retrato, self.retrato_em = r, r.lido_em
        self._versao_papel += 1
        log.warning("banco ocupado: ordens com o retrato salvo de %s (nada entra)",
                    r.lido_em)

    def _escolher_contrato(self, srv, diario) -> None:
        """Na primeira volta conectada do pregão (e a cada nova conexão).
        Sem preço ainda (WIN$N com último 0 às 09:00) tenta de novo nas
        voltas seguintes; o vencimento hoje fixa o dia sem entradas."""
        c = self.contrato_dia
        if c is not None and (c["simbolo"] or c.get("vence_em")):
            return
        try:
            c = contrato_dia.escolher(self.mt5, srv.date(), base=self.simbolo)
        except Exception as e:
            c = {"simbolo": None, "motivo": f"falha ao escolher o contrato: {e}",
                 "vence_em": None, "amanha": None}
        self.contrato_dia = c
        if c["simbolo"] is None:
            if c["motivo"] != self._contrato_falha:
                log.warning("contrato do dia: %s", c["motivo"])
            self._contrato_falha = c["motivo"]
            return
        self._contrato_falha = None
        rolagens = [e for e in diario.eventos if e["tipo"] == "rolagem"]
        if not rolagens or rolagens[-1].get("simbolo") != c["simbolo"]:
            diario.registrar("rolagem", quando=srv, simbolo=c["simbolo"],
                             motivo=c["motivo"])

    def _vigiar_preco(self, srv) -> None:
        """Guarda de preço (§5.6): contrato e WIN$N afastados mais de 2
        ticks por mais de 60 s param as entradas e chamam o usuário; o
        chamado fecha quando a guarda solta. Sem preço válido (último 0,
        sem tick) não observa — nem prende nem solta."""
        simbolo = (self.contrato_dia or {}).get("simbolo")
        if not simbolo:
            return
        tc, tb = self.mt5.symbol_info_tick(simbolo), self.mt5.symbol_info_tick(self.simbolo)
        pc, pb = float(getattr(tc, "last", 0) or 0), float(getattr(tb, "last", 0) or 0)
        if pc <= 0 or pb <= 0:
            return
        self._guarda_bloqueada = self.guarda.observar(srv, pc, pb)
        self.motor._condicao(
            "preco_contrato", self._guarda_bloqueada,
            f"preço do contrato {simbolo} não bate com o {self.simbolo} "
            "(entradas paradas)", srv)

    def _barras_hoje(self, srv):
        """As barras de hoje do MT5 (memória, não banco): só as fechadas, e
        o minuto em formação como `provisoria = (ts, abertura)`."""
        zero = datetime.combine(srv.date(), hora())
        df = self._taxas(zero, srv + timedelta(days=1))
        self._formacao = None
        if df is None:
            return _HOJE_VAZIO, None
        df = df.filter(pl.col("ts").dt.date() == srv.date())
        prontos = C.fechados(df, srv)
        provisoria = None
        if prontos.height < df.height:
            u = df.sort("ts").row(-1, named=True)
            provisoria = (u["ts"], int(round(u["open"])))
            self._formacao = (int(round(u["high"])), int(round(u["low"])))
        return papel_vivo.barras_de_hoje(prontos), provisoria

    def _aplicar_toque(self, srv) -> None:
        """Zera no toque o desejado cujo stop/alvo a máxima ou a mínima do
        minuto em formação já tocou (só leitura de memória, a cada volta). A
        hora do toque é a da PRIMEIRA volta em que a ligação ficou tocada;
        some quando deixa de estar."""
        maxima, minima = self._formacao or (None, None)
        com = papel_vivo.aplicar_toque(self._desejados, maxima, minima)
        novo, tocados = {}, {}
        for lig, d in com.items():
            era = self._desejados.get(lig)
            if d.estado == papel_vivo.ZERADO and era is not None                     and era.estado == papel_vivo.POSICAO:
                tocados[lig] = self._toque_em.get(lig, srv)
                d = replace(d, toque_em=tocados[lig])
            novo[lig] = d
        # ligação que acabou de tocar: o papel gravado regrava já, no
        # próximo passo, em vez de esperar o próximo minuto
        if set(tocados) - set(self._toque_em):
            self.papel_pendente = True
        self._toque_em = tocados
        self._desejados_ordens = novo

    def _calcular_desejados(self, srv) -> None:
        if srv is None:
            # sem relógio do servidor nada se sabe: só a proteção (§5.1)
            self._desejados, self._disponivel, self._minuto_calculado = {}, False, None
            self._provisoria_ts = None
            return
        hoje, provisoria = self._barras_hoje(srv)
        self._provisoria_ts = provisoria[0] if provisoria else None
        if self.retrato is not None and self.retrato.antigo:
            # o retrato salvo não tem plano nem código: papel indisponível
            # (só protege) até o banco responder
            self._desejados, self._disponivel, self._minuto_calculado = {}, False, None
            return
        # o candle fechado que o MT5 revisa (caso 11) também refaz: a chave
        # leva o conteúdo das barras, não só o minuto
        chave = (self._versao_papel, provisoria, len(hoje["ts"]),
                 hash(tuple(hoje[k].tobytes() for k in ("ts", "open", "high", "low", "close"))))
        if chave == self._minuto_calculado:
            return
        try:
            self._desejados, self._disponivel = papel_vivo.desejados(
                self.retrato, self.aquecimento, hoje, provisoria, self.inst, srv)
        except Exception as e:
            self._falha("papel das ordens falhou", e)
            self._desejados, self._disponivel = {}, False
        else:
            self._sem_falha("papel das ordens falhou")
        self._minuto_calculado = chave

    # ---------------------------------------------------------------- volta
    def volta(self) -> float:
        """Uma volta; devolve quantos segundos esperar. Nenhum passo sai
        antes do estado: a tela precisa ver o que aconteceu, até o "nada"."""
        if self._sem_yaml:
            raise ErroDeConfiguracao(self._sem_yaml)
        agora, m = self.agora(), self.mono()
        if not self._schema_ok:
            self._garantir_schema(agora)
        if not self.carregado or self.dia != agora.date():
            with contextlib.suppress(_Ocupado):
                self._carregar(agora)

        conectado = self._mt5(agora, m)
        if conectado:
            self.relogio.observar(_hora_do_tick(self.mt5.symbol_info_tick(self.simbolo)), m)
            self.agora_srv = self.relogio.agora(m)
            self.desvio = self.relogio.desvio_s(agora, m)
        # As ordens antes de qualquer escrita no banco (spec ordens §3): o
        # candle, o papel gravado, a conferência e o Parquet esperam por
        # elas, nunca o contrário. Sem MT5 só vigia (chamado `mt5_fora`).
        self._ordens(agora, m)
        if conectado and not self._banco_espera():
            if self.carregado:
                novo = self._buscar_e_gravar(agora, m)
                novo = self._lacunas(agora, m) or novo
                # Só com candle novo: sem ele o recálculo daria o mesmo
                # resultado, e cada volta de 1 s pegaria o escritor à toa.
                if novo or self.papel_pendente:
                    self._papel(agora)
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
        if self.pregao and self._perto_da_virada():
            return VOLTA_RAPIDA
        return ESPERA_PREGAO if self.pregao else ESPERA_FORA

    def _janela_da_virada(self) -> bool:
        return (self.agora_srv is not None and self._perto_da_virada()
                and self._no_pregao(self.agora_srv))

    def _banco_espera(self) -> bool:
        """Perto da virada, no pregão, os passos do banco (candle, lacuna,
        papel, conferência) esperam as ordens do minuto novo: do segundo 58
        até a volta em que o motor rodou com a barra desse minuto (ou até o
        segundo 10). Sem isto, uma gravação ou o Parquet no segundo 59
        seguraria a primeira volta do minuto. O candle não se perde: a
        volta seguinte o pede de novo ao MT5."""
        if not self._janela_da_virada():
            return False
        srv = self.agora_srv
        minuto = srv.replace(second=0, microsecond=0)
        if srv.second >= RAPIDA_ANTES_S:
            return True                  # o minuto que vem ainda nem começou
        return self._minuto_ordens != minuto

    def _perto_da_virada(self) -> bool:
        """Do segundo 58 ao 10 do minuto, na hora do SERVIDOR (o PC pode
        estar um minuto atrás): a ordem do minuto novo sai no primeiro
        décimo de segundo em que a barra dele aparece (spec ordens §3.1)."""
        srv = self.agora_srv
        if srv is None:
            return False
        s = srv.second + srv.microsecond / 1e6
        return s >= RAPIDA_ANTES_S or s <= RAPIDA_DEPOIS_S

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
            "reconferencia": self.reconferencia,
            "base_alterada_em": self.base_alterada_em,
            "banco_ocupado_desde": self.banco_ocupado_desde,
            # só um desvio que importa: abaixo de 30 s é ruído do tick
            "relogio_desvio_s": (round(self.desvio, 1)
                                 if self.desvio is not None and abs(self.desvio) > 30
                                 else None),
            "primeiro_candle_hoje": self.primeiro_hoje,
            # A tela relê o papel do banco quando `calculado_em` muda.
            # `ligacoes` é só um aviso do que a captura viu por último (fica
            # entrada de outros dias e de ligação já removida): a tela filtra
            # por `dia == hoje` e lê o status de verdade de `papel_pregoes`.
            "papel": {
                "calculado_em": self.papel_em,
                "pendente": self.papel_pendente,
                "ligacoes": self.papel_ligacoes,
                "divergencias": self.papel_divergencias,
                "erros": self.papel_erros,
            },
            # spec ordens §7.3; a tela só relê o banco quando `ordens_em` muda
            "ordens": self.ordens_estado,
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
    """Com dois MT5 instalados, o caminho cadastrado na conta diz qual abrir.

    Banco que não responde NÃO devolve None: sem o caminho, o MT5 abriria o
    terminal padrão, que pode ser o da conta real. Levanta exceção comum (não
    ErroDeConfiguracao) para o .bat reabrir daqui a 10 s."""
    try:
        with db.connect(read_only=True, tentativas=4) as con:
            linha = con.execute(
                # só a conta DEMO: a captura nunca abre o terminal da conta
                # real (a real tem processo próprio — parte 5)
                "SELECT terminal FROM contas WHERE arquivada_em IS NULL "
                "AND terminal IS NOT NULL AND tipo = 'demo' "
                "ORDER BY conta_id DESC LIMIT 1").fetchone()
    except Exception as erro:
        raise RuntimeError(
            f"não consegui ler o banco para achar o terminal da conta: {erro}") from erro
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

    try:
        terminal = args.terminal or _terminal_da_conta()
    except RuntimeError as erro:
        # sem caminho do terminal não se inicializa o MT5: sai com erro comum,
        # e o captura.bat reabre em 10 s
        log.error("%s", erro)
        trava.close()
        raise
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
