"""Processo "Ordens real" (ordens_real.py, spec conta-real §4.1, §4.3, §6, §10):
trava própria, conta real pelo cadastro, arquivo de desejados fresco ou velho,
comandos só da pasta da real, batimento a cada volta e nenhuma escrita no banco.

O MT5 é o falso de ordens com a conta REAL (trade_mode 2). Nada aqui fala com
terminal: o relógio anda um segundo por volta e o retrato é injetado.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

import ordens_real as R
from core import comandos
from core import corretora as K
from core import db_manager as db
from core import diario_ordens
from core import papel_vivo as PV
from core import ponte
from core.papel_vivo import POSICAO, Desejado, LigacaoViva, Retrato
from tests.mt5_falso import MT5Ordens

DIA = date(2026, 10, 9)
BASE = datetime(2026, 10, 9, 9, 59, 50)            # pregão, 10 s antes da entrada
ENTRADA = datetime(2026, 10, 9, 10, 1, 0)
LOGIN_REAL, SERVIDOR_REAL = 2000777, "ClearInvestimentos-REAL"
CONTA_REAL, CONTA_DEMO = 2, 1
TERMINAL_REAL = "C:/mt5real/terminal64.exe"
CONTRATO = {"simbolo": "WINV26", "motivo": None, "vence_em": date(2026, 10, 14),
            "amanha": None}
D = Desejado(POSICAO, lado=1, entry_ts=ENTRADA, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=0)


class MT5Real(MT5Ordens):
    """Terminal da conta real: logado na conta real, sem pedido de inicialização."""

    def __init__(self):
        super().__init__(login=LOGIN_REAL, servidor=SERVIDOR_REAL, agora=BASE)
        self.trade_mode = 2                        # ACCOUNT_TRADE_MODE_REAL
        self.inits: list = []

    def initialize(self, path=None, **kw):
        self.inits.append(path)
        return True

    def shutdown(self):
        pass

    def symbol_select(self, s, on=True):
        return True


class Relogio:
    """Hora do PC e do servidor andando juntas: cada volta é um segundo."""

    def __init__(self, inicio):
        self.inicio, self.t = inicio, 0.0

    def agora(self):
        return self.inicio + timedelta(seconds=self.t)

    def mono(self):
        return self.t


def retrato_real(envio=True):
    lv = LigacaoViva(ligacao_id=4, portfolio_id=1, status="rodando", motivo=None,
                     plano=None, modulo=None, fase="real", conta_id=CONTA_REAL,
                     contratos_conta=2, ligada=True, desvio=10)
    contas = {CONTA_REAL: {"login": LOGIN_REAL, "servidor": SERVIDOR_REAL,
                           "limite": 500.0, "envio": envio, "tipo": "real"},
              CONTA_DEMO: {"login": 1193398927, "servidor": "ClearInvestimentos-DEMO",
                           "limite": 500.0, "envio": True, "tipo": "demo"}}
    return Retrato(dia=DIA, lido_em=BASE, ligacoes={4: lv}, contas=contas,
                   portfolio_de={4: 1})


class Cena:
    def __init__(self, mt5, rel, servico, ret):
        self.mt5, self.rel, self.servico, self.ret = mt5, rel, servico, ret

    def voltas(self, n):
        for _ in range(n):
            self.rel.t += 1
            self.mt5.agora = self.rel.agora()
            self.servico.volta()

    def ate(self, hora):
        while self.rel.agora() < hora:
            self.voltas(1)


def _desejados_no_arquivo(vivo_velho=False, contrato=CONTRATO, seq=1):
    dados = ponte.serializar({4: D}, True, contrato, seq, BASE)
    if vivo_velho:
        dados["vivo_em"] = time.time() - 60
    ponte.escrever(dados)


@pytest.fixture
def cena(tmp_path, monkeypatch):
    # o banco existe (o retrato e o terminal da conta real saem dele)
    with db.connect_write() as con:
        db.init_schema(con)
    mt5, rel = MT5Real(), Relogio(BASE)
    ret = {"atual": retrato_real()}
    monkeypatch.setattr(PV, "ler_retrato", lambda con, dia, agora, cache, **k: ret["atual"])
    servico = R.ServicoReal(mt5=mt5, terminal=TERMINAL_REAL, agora=rel.agora,
                            mono=rel.mono, terminal_aberto=lambda: True)
    c = Cena(mt5, rel, servico, ret)
    return c


def entradas(mt5):
    return [r for r in mt5.enviados if r["action"] == 1 and "position" not in r]


def eventos_reais():
    return diario_ordens.Diario(diario_ordens.PASTA / "real", DIA).eventos


# ------------------------------------------------------------- processo
def test_segunda_instancia_sai_com_4(tmp_path):
    trava = R.P.travar(R.PASTA / "ordens_real.lock")
    assert trava is not None
    assert R.main([]) == R.OUTRA_INSTANCIA
    trava.close()


def test_sem_conta_real_sai_com_3(tmp_path):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em, terminal) "
                    "VALUES (1, 'demo', 'demo', now(), 'C:/demo/terminal64.exe')")
    assert R.main([]) == R.SAIR_SEM_REABRIR
    assert (R.PASTA / "estado_real.json").exists()


def test_conta_real_sem_terminal_sai_com_3(tmp_path):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em) "
                    "VALUES (2, 'real', 'real', now())")
    assert R.main([]) == R.SAIR_SEM_REABRIR


def test_terminal_da_conta_real_ignora_a_demo(tmp_path):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em, terminal) "
                    "VALUES (1, 'demo', 'demo', now(), 'C:/demo/terminal64.exe')")
        con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em, terminal) "
                    "VALUES (2, 'real', 'real', now(), ?)", [TERMINAL_REAL])
    assert R._terminal_da_conta_real() == TERMINAL_REAL


# ------------------------------------------------------------- ordens
def test_arquivo_fresco_com_posicao_envia_entrada_na_real_e_grava_ack(cena):
    _desejados_no_arquivo()
    cena.ate(ENTRADA + timedelta(seconds=2))
    envios = entradas(cena.mt5)
    assert envios and envios[0]["magic"] == K.magic(4)
    assert ponte.ler_ack() == 1
    ev = [e for e in eventos_reais() if e["tipo"] == "executada"]
    assert ev and ev[0]["evento_id"].startswith("real-")
    assert cena.mt5.inits == [TERMINAL_REAL]


def test_arquivo_velho_nao_entra_e_protege(cena):
    _desejados_no_arquivo(vivo_velho=True)
    cena.ate(ENTRADA + timedelta(seconds=2))
    assert entradas(cena.mt5) == []
    assert ponte.ler_ack() is None
    assert cena.servico.ordens_estado["disponivel"] is False


def test_contrato_que_nao_negocia_no_terminal_nao_entra(cena):
    _desejados_no_arquivo()
    orig = cena.mt5.symbol_info

    def sem_negociar(s):
        info = orig(s)
        return NS(**{**vars(info), "trade_mode": 3}) if s == "WINV26" else info
    cena.mt5.symbol_info = sem_negociar
    cena.ate(ENTRADA + timedelta(seconds=2))
    assert entradas(cena.mt5) == []
    pode, motivo = cena.servico._checar_contrato(CONTRATO, "WINV26")
    assert pode is False and "não está negociável" in motivo


def test_terminal_nao_aberto_nao_e_aberto_pelo_processo(cena):
    cena.servico.terminal_aberto = lambda: False
    cena.voltas(3)
    assert cena.mt5.inits == []
    assert cena.servico.mt5_estado == "fechado"


# ------------------------------------------------------------- comandos
def test_comando_so_da_pasta_real(cena):
    comandos.escrever(comandos.PASTA, "zerar_tudo")          # demo: não é desta conta
    comandos.escrever(comandos.PASTA_REAL, "zerar_tudo")     # real: consumido
    cena.voltas(2)
    assert list(comandos.PASTA_REAL.glob("*.json")) == []
    assert len(list(comandos.PASTA.glob("*.json"))) == 1


# ------------------------------------------------------------- batimento e banco
def test_batimento_sai_em_toda_volta(cena, monkeypatch):
    chamadas = []
    orig = ponte.gravar_vivo_real
    monkeypatch.setattr(ponte, "gravar_vivo_real",
                        lambda: (chamadas.append(1), orig())[1])
    cena.voltas(5)
    assert len(chamadas) == 5
    assert ponte.real_ativo(agora_pc=time.time())


def test_nenhuma_escrita_no_banco(cena, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("o processo da real não pode escrever no banco")
    monkeypatch.setattr(db, "connect_write", explode)
    _desejados_no_arquivo()
    cena.ate(ENTRADA + timedelta(seconds=2))
    assert entradas(cena.mt5)


# ------------------------------------------------------------- falhas
def test_erro_na_volta_nao_derruba_o_processo(cena, monkeypatch):
    def quebra():
        raise RuntimeError("corretora meio fora")
    monkeypatch.setattr(cena.servico, "volta", quebra)
    assert cena.servico.passo_seguro() == R.VOLTA_LENTA
