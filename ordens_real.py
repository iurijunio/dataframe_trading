"""Processo "Ordens real" — as ordens da conta real, à parte da captura.

    .venv/Scripts/python.exe ordens_real.py   (o ordens_real.bat abre numa janela própria)

Spec: docs/superpowers/specs/2026-10-19-conta-real-design.md §4.1, §4.3, §6, §10.
Não grava candle, não calcula papel e não escreve no banco: lê em `ponte`
os desejados que a captura publica, age no terminal da conta real e devolve
o `seq` que tratou (`ack_real.json`). O banco entra só em leitura, para o
retrato da configuração (`papel_vivo.ler_retrato(..., tipo="real")`).
Trava, retrato e log próprios: nada aqui mexe no processo da demo.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import captura as P  # trava, terminal aberto, relógio do tick, erro de configuração
from core import captura as C
from core import comandos, contrato_dia, diario_ordens, ordens, papel_vivo, ponte
from core import corretora as K
from core import db_manager as db

SAIR_SEM_REABRIR = 3      # configuração: reabrir não resolve
OUTRA_INSTANCIA = 4       # já há um processo da real aberto: o .bat sai calado
PASTA = db.DATA / "ao_vivo"
SIMBOLO = "WIN$N"
ARQ_ESTADO = "estado_real.json"
ARQ_RETRATO = "retrato.json"        # dentro de ordens/real (o da demo fica em ordens/)
A_CADA_RETRATO = 5                  # s, fora da janela da virada
A_CADA_CONEXAO = 5                  # s entre tentativas de abrir o terminal da real
FALHAS_SIMBOLO = 3
TIMEOUT_INICIALIZAR_MS = 10_000
# 10 ms do segundo 58 ao 10 do servidor (a ordem do minuto novo sai logo que a
# barra aparece); 0,5 s fora disso
VOLTA_RAPIDA, VOLTA_LENTA = 0.01, 0.5
RAPIDA_ANTES_S, RAPIDA_DEPOIS_S = 58, 10
LOG_REPETIDO_S = 60

log = logging.getLogger("ordens_real")


def _perto_da_virada(srv: datetime) -> bool:
    s = srv.second + srv.microsecond / 1e6
    return s >= RAPIDA_ANTES_S or s <= RAPIDA_DEPOIS_S


def _pasta_retrato() -> Path:
    return Path(diario_ordens.PASTA) / "real"


class ServicoReal:
    def __init__(self, mt5, terminal, simbolo=SIMBOLO, agora=datetime.now,
                 mono=time.monotonic, pasta=None, terminal_aberto=P.terminal_aberto):
        self.mt5, self.terminal, self.simbolo = mt5, terminal, simbolo
        self.agora, self.mono = agora, mono
        self.pasta = Path(pasta if pasta is not None else PASTA)
        self.terminal_aberto = terminal_aberto
        self.inst = db.load_instrument_yaml(simbolo)
        self.relogio = C.RelogioServidor()
        # o diário da conta real vive numa pasta sua: nunca mistura com a demo
        self.motor = ordens.Motor(Path(diario_ordens.PASTA) / "real", self.inst,
                                  origem="real",
                                  relogio=lambda: self.relogio.agora(self.mono()),
                                  mono=self.mono)
        self.guarda = contrato_dia.GuardaPreco(self.motor.tick)
        self.mt5_estado, self.mt5_desde = "fechado", None
        self.conectado = self.novo_login = False
        self.falhas_simbolo = 0
        self._mono_conexao = None
        self.conta = None
        self.conectado_desde = None
        self.dia = None
        self.retrato = self.retrato_em = self._retrato_tentado = None
        self._retrato_salvo = None
        self.cache_codigo: dict = {}
        self.contrato_dia = None
        self._negociavel: set = set()     # contratos já conferidos no terminal
        self._guarda_bloqueada = False
        self._disponivel = False
        self._seq_tratado = None          # último seq da ponte que esta conta tratou
        self.ordens_estado = None
        self._falhas_log: dict = {}

    # ------------------------------------------------------------ falhas
    def _falha(self, onde: str, erro: Exception) -> None:
        """Traceback uma vez por mensagem distinta; depois uma linha por minuto."""
        texto = f"{type(erro).__name__}: {erro}"
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
        self._falhas_log.pop(onde, None)

    # --------------------------------------------------------------- MT5
    def _fora(self, estado: str, agora) -> bool:
        if self.mt5_estado != estado:
            self.mt5_desde = agora
        self.mt5_estado = estado
        return False

    def _mt5(self, agora, m) -> bool:
        mt5 = self.mt5
        # o terminal só abre com um MT5 da conta real já rodando (o caminho é
        # o da conta cadastrada); sem ele, tenta de novo a cada 5 s
        ultimo = self._mono_conexao
        if not self.conectado and (ultimo is None or m - ultimo >= A_CADA_CONEXAO):
            self._mono_conexao = m
            if self.terminal_aberto():
                ok = mt5.initialize(path=self.terminal, timeout=TIMEOUT_INICIALIZAR_MS)
                self.conectado = self.novo_login = bool(ok)
        if not self.conectado:
            return self._fora("fechado", agora)
        info = mt5.terminal_info()
        if info is None:
            self.conectado = False
            with contextlib.suppress(Exception):
                mt5.shutdown()
            return self._fora("fechado", agora)
        if not info.connected:
            return self._fora("sem_conexao", agora)
        if self.novo_login:
            if not mt5.symbol_select(self.simbolo, True):
                self.falhas_simbolo += 1
                if self.falhas_simbolo >= FALHAS_SIMBOLO:
                    raise P.ErroDeConfiguracao(f"o MT5 da conta real não tem {self.simbolo}")
                return self._fora("sem_conexao", agora)
            self.falhas_simbolo = 0
            self.novo_login = False
            self._negociavel = set()
        conta = mt5.account_info()
        self.conta = ({"login": int(conta.login), "servidor": conta.server}
                      if conta is not None else None)
        if self.mt5_estado != "conectado":
            # cada (re)conexão reinicia a graça de 5 s sem entradas
            self.conectado_desde = m
            self._negociavel = set()
        self.mt5_estado, self.mt5_desde = "conectado", None
        return True

    # ------------------------------------------------------------- volta
    def volta(self) -> float:
        agora, m = self.agora(), self.mono()
        conectado = self._mt5(agora, m)
        srv = None
        if conectado:
            self.relogio.observar(P._hora_do_tick(self.mt5.symbol_info_tick(self.simbolo)), m)
            srv = self.relogio.agora(m)
        self._ordens(agora, m, conectado, srv)
        # o batimento sai em toda volta: a captura sabe que esta conta está viva
        ponte.gravar_vivo_real()
        self._publicar(agora)
        return VOLTA_RAPIDA if srv is not None and _perto_da_virada(srv) else VOLTA_LENTA

    def _ordens(self, agora, m, conectado: bool, srv) -> None:
        """Erro nas ordens vai ao log, ao estado e a um chamado; nunca mata o
        processo (a próxima volta tenta de novo)."""
        quando = srv or agora
        try:
            self._volta_ordens(agora, m, conectado, srv)
        except Exception as e:
            self._falha("caminho das ordens da conta real falhou", e)
            self.ordens_estado = {"erro": str(e), "vivo_em": quando}
            try:
                self.motor._chamar("ordens_falhou", "ordens_falhou",
                                   f"erro nas ordens: {e}", quando)
            except Exception as e2:
                self._falha("não consegui abrir o chamado da falha das ordens", e2)
            return
        self._sem_falha("caminho das ordens da conta real falhou")
        if not (self.ordens_estado or {}).get("falhou"):
            try:
                self.motor._fechar("ordens_falhou", quando)
            except Exception as e:
                self._falha("não consegui fechar o chamado da falha das ordens", e)

    def _volta_ordens(self, agora, m, conectado: bool, srv) -> None:
        quando = srv or agora
        dia = quando.date()
        if self.dia != dia:
            self._virar_dia(dia)
        diario = self.motor.diario(dia)

        if not conectado:
            self.motor._condicao(
                "mt5_fora", bool(diario.ligacoes_abertas()),
                "MT5 da conta real fora do ar com posição da automação aberta "
                "(stop e alvo seguem na corretora)", quando)
            self.motor.recusar_testes(comandos.PASTA_REAL, diario, quando, "MT5 fora do ar")
            self.ordens_estado = self._parados("MT5 fora do ar", quando)
            return
        self.motor._fechar("mt5_fora", quando)

        no_pregao = srv is not None and C.em_pregao(srv, C.FECHAMENTO_PADRAO)
        if not no_pregao and not self._posicionada(diario):
            motivo = "fora do pregão" if srv is not None else "sem relógio do servidor"
            self.motor.recusar_testes(comandos.PASTA_REAL, diario, quando, motivo)
            self.ordens_estado = self._parados(motivo, quando)
            return

        self._ler_retrato(quando, m, srv)
        desejados, contrato, seq = self._ler_desejados()
        self.contrato_dia = contrato
        simbolo = (contrato or {}).get("simbolo")
        if no_pregao and simbolo:
            self._vigiar_preco(simbolo, srv)
        contrato_ok, motivo_contrato = self._checar_contrato(contrato, simbolo)
        est = self.motor.passo(
            self.mt5, agora_srv=srv, retrato=self.retrato, desejados=desejados,
            disponivel=self._disponivel, comandos=comandos.PASTA_REAL, simbolo=simbolo,
            contrato_ok=contrato_ok, contrato_motivo=motivo_contrato,
            conectado_ha_s=(m - self.conectado_desde
                            if self.conectado_desde is not None else 0.0),
            no_pregao=no_pregao)
        # o ack sai DEPOIS do passo: a demo espera que a ordem desse seq tenha saído
        if seq is not None and seq != self._seq_tratado:
            ponte.gravar_ack(seq)
            self._seq_tratado = seq
        self.ordens_estado = {**est, **self._extra()}

    def _ler_desejados(self):
        """Só o arquivo fresco conta; velho ou ausente = nada entra, só se protege."""
        d = ponte.ler_arquivo()
        if d is None or not ponte.fresco(d):
            self._disponivel = False
            return {}, None, None
        desejados, disponivel, contrato, seq, _ = ponte.ler(d)
        self._disponivel = disponivel
        return desejados, contrato, seq

    def _checar_contrato(self, contrato, simbolo):
        """(pode operar, motivo). O contrato precisa estar negociável no
        próprio terminal da real, e a guarda de preço não pode estar presa."""
        if not simbolo:
            return False, (contrato or {}).get("motivo") or ordens.SEM_CONTRATO
        if simbolo not in self._negociavel:
            if not self._negociavel_no_terminal(simbolo):
                return False, f"o contrato {simbolo} não está negociável no terminal da conta real"
            self._negociavel.add(simbolo)
        if self._guarda_bloqueada:
            return False, ordens.GUARDA_PRECO
        return True, None

    def _negociavel_no_terminal(self, simbolo: str) -> bool:
        try:
            if not self.mt5.symbol_select(simbolo, True):
                return False
            info = self.mt5.symbol_info(simbolo)
            return info is not None and info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_FULL
        except Exception as e:
            self._falha(f"não consegui conferir o contrato {simbolo} no terminal real", e)
            return False

    def _vigiar_preco(self, simbolo: str, srv) -> None:
        """Guarda de preço (spec §5.6), a mesma régua da captura: contrato e
        WIN$N afastados por mais de 60 s param as entradas da real."""
        tc = self.mt5.symbol_info_tick(simbolo)
        tb = self.mt5.symbol_info_tick(self.simbolo)
        pc, pb = float(getattr(tc, "last", 0) or 0), float(getattr(tb, "last", 0) or 0)
        if pc <= 0 or pb <= 0:
            return
        self._guarda_bloqueada = self.guarda.observar(srv, pc, pb)
        self.motor._condicao(
            "preco_contrato", self._guarda_bloqueada,
            f"preço do contrato {simbolo} não bate com o {self.simbolo} "
            "(entradas paradas)", srv)

    def _posicionada(self, diario) -> bool:
        """Posição da automação na real (ou no diário): é ela que pede o motor
        fora do pregão. Leitura que falha conta como sim."""
        try:
            pos = self.mt5.positions_get()
        except Exception:
            return True
        if pos is None:
            return True
        return (any(K.ligacao_do_magic(p.magic) is not None
                    or int(p.magic or 0) == K.MAGIC_TESTE for p in pos)
                or bool(diario.ligacoes_abertas()))

    def _virar_dia(self, dia) -> None:
        self.dia = dia
        self.retrato = self.retrato_em = self._retrato_tentado = None
        self.contrato_dia = None
        self.guarda = contrato_dia.GuardaPreco(self.motor.tick)
        self._guarda_bloqueada = False
        self._negociavel = set()

    def _parados(self, motivo, quando) -> dict:
        return {"foto": None, "parado": motivo, "vivo_em": quando,
                "chamados": [dict(c, chave=k) for k, c in self.motor.chamados.items()],
                "teste": self.motor.teste.estado(), **self._extra()}

    def _extra(self) -> dict:
        return {"retrato_em": self.retrato_em, "disponivel": self._disponivel,
                "retrato_antigo": bool(self.retrato is not None and self.retrato.antigo),
                "contrato_dia": self.contrato_dia,
                "preco_contrato_bloqueado": self._guarda_bloqueada}

    # ----------------------------------------------------------- retrato
    def _ler_retrato(self, quando, m, srv) -> None:
        """Só-leitura, a cada 5 s; perto da virada fica o retrato anterior."""
        if self.retrato is not None and srv is not None and _perto_da_virada(srv):
            return
        if self._retrato_tentado is not None and m - self._retrato_tentado < A_CADA_RETRATO:
            return
        self._retrato_tentado = m
        try:
            con = db.connect(read_only=True, tentativas=1, espera=0)
        except RuntimeError:
            self._retrato_do_arquivo()
            return
        except Exception as e:
            self._falha("não consegui abrir o banco para o retrato da conta real", e)
            self._retrato_do_arquivo()
            return
        try:
            with con:
                novo = papel_vivo.ler_retrato(con, quando.date(), quando, self.cache_codigo,
                                              symbol=self.simbolo, tipo="real")
        except Exception as e:
            self._falha("não consegui ler o retrato da conta real", e)
            self._retrato_do_arquivo()
            return
        self._sem_falha("não consegui ler o retrato da conta real")
        self.retrato, self.retrato_em = novo, quando
        self._salvar_retrato(novo)

    def _salvar_retrato(self, r) -> None:
        try:
            dados = papel_vivo.retrato_para_json(r)
            chave = json.dumps({k: v for k, v in dados.items() if k != "lido_em"},
                               sort_keys=True, default=P._json_simples)
            if chave == self._retrato_salvo:
                return
            pasta = _pasta_retrato()
            pasta.mkdir(parents=True, exist_ok=True)
            tmp = pasta / (ARQ_RETRATO + ".tmp")
            tmp.write_text(json.dumps(dados, default=P._json_simples), encoding="utf-8")
            os.replace(tmp, pasta / ARQ_RETRATO)
            self._retrato_salvo = chave
        except Exception as e:
            self._falha("não consegui salvar o retrato da conta real", e)

    def _retrato_do_arquivo(self) -> None:
        """Banco ocupado sem retrato em memória: o último salvo, marcado
        `antigo` — a real sabe a conta e protege; nada entra até o banco voltar."""
        if self.retrato is not None:
            return
        arq = _pasta_retrato() / ARQ_RETRATO
        if not arq.exists():
            return
        try:
            r = papel_vivo.retrato_de_json(json.loads(arq.read_text(encoding="utf-8")))
        except Exception as e:
            self._falha("não consegui ler o retrato salvo da conta real", e)
            return
        self.retrato, self.retrato_em = r, r.lido_em
        log.warning("banco ocupado: ordens reais com o retrato salvo de %s (nada entra)",
                    r.lido_em)

    # ------------------------------------------------------------ estado
    def _publicar(self, agora, erro: str | None = None) -> None:
        dados = {"pid": os.getpid(), "atualizado_em": agora, "mt5": self.mt5_estado,
                 "mt5_desde": self.mt5_desde, "conta": self.conta,
                 "simbolo": self.simbolo, "ordens": self.ordens_estado, "erro": erro}
        try:
            C.escrever_estado(self.pasta / ARQ_ESTADO, dados)
        except OSError as e:
            self._falha("não consegui escrever o estado da conta real", e)

    def passo_seguro(self) -> float:
        """Erro passageiro não derruba o processo: vai ao log, ao estado e a um
        chamado, e a próxima volta tenta de novo."""
        try:
            return self.volta()
        except P.ErroDeConfiguracao:
            raise
        except Exception as e:
            self._falha("volta das ordens da conta real", e)
            with contextlib.suppress(Exception):
                self.motor._chamar("ordens_falhou", "ordens_falhou",
                                   f"erro nas ordens reais: {e}", self.agora())
            with contextlib.suppress(Exception):
                self._publicar(self.agora(), erro=str(e))
            return VOLTA_LENTA

    def rodar(self) -> None:
        while True:
            time.sleep(self.passo_seguro())


# ----------------------------------------------------------------- processo
def _configurar_log() -> None:
    if log.handlers:
        return
    PASTA.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%d/%m %H:%M:%S")
    arquivo = RotatingFileHandler(PASTA / "ordens_real.log", maxBytes=5 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    for h in (arquivo, console):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def _terminal_da_conta_real() -> str | None:
    """Caminho do terminal da conta real cadastrada e não arquivada. Sem ele
    não há o que abrir: nunca se cai no terminal padrão (poderia ser a demo)."""
    with db.connect(read_only=True, tentativas=4) as con:
        linha = con.execute(
            "SELECT terminal FROM contas WHERE arquivada_em IS NULL "
            "AND terminal IS NOT NULL AND tipo = 'real' "
            "ORDER BY conta_id DESC LIMIT 1").fetchone()
    return linha[0] if linha else None


def _estado_de_erro(erro: str) -> None:
    with contextlib.suppress(Exception):
        C.escrever_estado(PASTA / ARQ_ESTADO, {
            "pid": os.getpid(), "atualizado_em": datetime.now(), "mt5": "fechado",
            "erro": erro})


def _executar(args) -> int:
    _configurar_log()
    try:
        terminal = _terminal_da_conta_real()
    except Exception:
        log.exception("não consegui ler a conta real no banco")
        return 1                       # reabre com espera (o .bat)
    if terminal is None:
        msg = ("sem conta real cadastrada com o terminal (MT5): cadastre a conta real "
               "com o caminho do terminal antes de ligar as ordens reais")
        log.error(msg)
        _estado_de_erro(msg)
        return SAIR_SEM_REABRIR
    try:
        import MetaTrader5 as mt5
    except ImportError:
        msg = "o pacote MetaTrader5 não está instalado neste computador"
        log.error(msg)
        _estado_de_erro(msg)
        return SAIR_SEM_REABRIR
    try:
        servico = ServicoReal(mt5=mt5, terminal=terminal, simbolo=args.simbolo)
    except FileNotFoundError as e:
        log.error("erro de configuração: %s", e)
        _estado_de_erro(str(e))
        return SAIR_SEM_REABRIR
    log.info("ordens reais iniciadas: %s, terminal %s", args.simbolo, terminal)
    try:
        servico.rodar()
    except KeyboardInterrupt:
        log.info("ordens reais encerradas pelo usuário")
        with contextlib.suppress(Exception):
            mt5.shutdown()
        return 0
    except P.ErroDeConfiguracao as e:
        log.error("erro de configuração: %s", e)
        _estado_de_erro(str(e))
        return SAIR_SEM_REABRIR
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Processo das ordens da conta real.")
    p.add_argument("--simbolo", default=SIMBOLO)
    args = p.parse_args(argv)

    # trava antes do log: a segunda janela não pode girar o log da primeira
    trava = P.travar(PASTA / "ordens_real.lock")
    if trava is None:
        print("outra janela das ordens reais já está aberta")
        return OUTRA_INSTANCIA
    try:
        return _executar(args)
    finally:
        trava.close()


if __name__ == "__main__":
    sys.exit(main())
