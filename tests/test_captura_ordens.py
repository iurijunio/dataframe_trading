"""A captura com as ordens da demo (spec 2026-10-08-ao-vivo-ordens §3,
§3.1, §6.4, §7.3): o motor roda em cada volta ANTES de qualquer escrita no
banco, com a volta rápida perto da virada do minuto, e nenhuma falha no
caminho das ordens para a gravação dos candles.

O MT5 é o falso de ordens (`tests/mt5_falso.py`) com as barras do falso da
captura (`tests/test_captura_processo.py`). Nada aqui fala com terminal nem
toca o banco ou as pastas reais (o conftest desvia banco, diário e comandos).
"""
from __future__ import annotations

import importlib
import sys
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import captura as P  # noqa: E402
from core import ao_vivo, diario_ordens, ordens, papel, papel_backtest  # noqa: E402
from core import captura as C  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import papel_vivo as PV  # noqa: E402
from core.diario_ordens import Diario  # noqa: E402
from strategies.base import Signals  # noqa: E402
from tests.fabrica_ao_vivo import barras_sinteticas, ligacao_com_plano  # noqa: E402
from tests.mt5_falso import MT5Ordens  # noqa: E402
from tests.test_captura_processo import _DT, Mono, _epoch, base  # noqa: E402,F401

DIA = date(2026, 10, 9)                       # sexta; WINV26 vence dia 14
T0 = datetime(2026, 10, 9, 9, 0)
SINAL = datetime(2026, 10, 9, 10, 0)          # fecha com o sinal de compra
ENTRADA = SINAL + timedelta(minutes=1)
LOGIN, SERVIDOR = 1193398927, "ClearInvestimentos-DEMO"
PRECO = 189_000
MARCA = 189_120          # fechamento que a estratégia de mentira lê como sinal
PERFIL = {"timeframe": "M1", "entrada_inicio": "09:00", "entrada_fim": "17:00",
          "fechamento": "17:50", "stop_tipo": "pontos", "stop_pontos": 200,
          "alvo_tipo": "pontos", "alvo_pontos": 400,
          "dias_semana": [1, 2, 3, 4, 5]}


def _as(hh, mm, ss=0):
    return datetime(2026, 10, 9, hh, mm, ss)


# --------------------------------------------------------------- o falso
class MT5Captura(MT5Ordens):
    """O falso de ordens com o que a captura usa para os candles: barras
    por minuto (só as que já existem na hora do servidor `agora`),
    initialize/symbol_select/shutdown e o terminal que fecha."""

    def __init__(self, **k):
        super().__init__(preco=PRECO, agora=_as(9, 0), **k)
        self.aberto = True
        self.tick_ok = True
        self.inits = 0
        self.barras = {}
        t = T0
        while t <= _as(18, 24):
            self.barras[t] = (PRECO, PRECO + 50, PRECO - 50, PRECO)
            t += timedelta(minutes=1)
        self.barras[SINAL] = (PRECO, MARCA + 30, PRECO - 50, MARCA)

    def initialize(self, path=None, **k):
        self.inits += 1
        return self.aberto

    def shutdown(self):
        pass

    def symbol_select(self, s, on):
        return True

    def terminal_info(self):
        return super().terminal_info() if self.aberto else None

    def symbol_info_tick(self, s):
        return super().symbol_info_tick(s) if self.tick_ok else None

    def copy_rates_range(self, s, tf, desde, ate):
        d, a = desde.replace(tzinfo=None), ate.replace(tzinfo=None)
        linhas = [(_epoch(t), *v, 50, 5, 0) for t, v in sorted(self.barras.items())
                  if d <= t <= a and t <= self.agora]
        return np.array(linhas, dtype=_DT) if linhas else None


def _mod():
    """Compra no fechamento de toda barra que fecha na MARCA."""
    def signals(bars, params):
        z = np.zeros(len(bars["close"]), dtype=bool)
        return Signals(bars["close"] == MARCA, z, z.copy(), z.copy())
    return SimpleNamespace(signals=signals)


@pytest.fixture
def mods(monkeypatch):
    m = _mod()
    monkeypatch.setattr(papel, "_modulo", lambda estrategia, h, cache: m)
    return m


def _ligacao(nome, *, fase="demo", run_id=1, portfolio_id=None):
    f = ligacao_com_plano(nome, params={}, profile=PERFIL, contratos=1,
                          run_id=run_id, portfolio_id=portfolio_id,
                          agora=datetime(2026, 9, 1, 10),
                          adicionado_em="2026-09-01 09:00")
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET fase = ?, contratos_demo = 3 "
                    "WHERE ligacao_id = ?", [fase, f.lig])
    return f


@pytest.fixture
def mundo(base, mods):
    """Uma ligação em fase demo num portfólio com a conta demo logada no
    MT5 (limite cadastrado). O Envio começa desligado, como no app."""
    f = _ligacao("demo-a")
    f.conta = ao_vivo.criar_conta("demo-1", "demo", 1000.0, login=LOGIN,
                                  servidor=SERVIDOR)
    ao_vivo.definir_contas(f.pf, f.conta, None)
    return f


class Cena:
    """O relógio do servidor, o do PC e o monotonic andando juntos."""

    def __init__(self, base_, mt5=None, mono=None):
        self.base = base_
        self.mt5 = mt5 or MT5Captura()
        self.mono = mono or Mono()
        self.s = self.novo_servico()

    def novo_servico(self):
        return P.Servico(mt5=self.mt5, agora=lambda: _as(9, 0), mono=self.mono,
                         pasta=self.base / "ao_vivo", terminal_aberto=lambda: True)

    def ir(self, quando, s=None):
        s = s or self.s
        self.mt5.agora = quando
        self.mono.t = 1000.0 + (quando - T0).total_seconds()
        s.agora = lambda: quando
        return s.volta()

    def seguir(self, espera, s=None):
        """Como o `rodar()`: dorme o que a volta anterior pediu A PARTIR do
        relógio de agora — o tempo que a volta gastou (um banco que dormiu)
        já está no mono — e roda a próxima. Servidor e PC andam com o mono."""
        s = s or self.s
        self.mono.t += espera
        quando = T0 + timedelta(seconds=self.mono.t - 1000.0)
        self.mt5.agora = quando
        s.agora = lambda: quando
        return s.volta()

    def estado(self):
        return C.ler_estado(self.base / "ao_vivo" / "estado.json")

    def entradas(self):
        return [r for r in self.mt5.enviados
                if r["action"] == self.mt5.TRADE_ACTION_DEAL and "position" not in r]

    def saidas(self):
        return [r for r in self.mt5.enviados
                if r["action"] == self.mt5.TRADE_ACTION_DEAL and "position" in r]


def _eventos(tipo=None, dia=DIA):
    return [e for e in Diario(diario_ordens.PASTA, dia).eventos
            if tipo is None or e["tipo"] == tipo]


def _chamados(chave):
    return [e for e in _eventos() if e["tipo"] in ("chamado", "chamado_fechado")
            and (e.get("chave") == chave or e.get("motivo") == chave)]


@pytest.fixture
def cena(base, mundo):
    ao_vivo.ligar_envio(mundo.conta, True)
    return Cena(base)


def _ocupar(monkeypatch, leitura=True):
    """Banco com outro escritor (mineração gravando): escrita e, opcionalmente,
    leitura falham. Devolve a função que solta o banco."""
    reais = (db.connect_write, db.connect)

    def ocupado(*a, **k):
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect_write", ocupado)
    if leitura:
        monkeypatch.setattr(db, "connect", ocupado)

    def soltar():
        monkeypatch.setattr(db, "connect_write", reais[0])
        monkeypatch.setattr(db, "connect", reais[1])
    return soltar


# ------------------------------------------------------------ §6.4 caso 1
def test_sinal_das_10_envia_a_ordem_na_volta_das_10_01_01(cena, mundo):
    cena.ir(_as(10, 0, 30))           # conecta, lê o retrato, escolhe o contrato
    assert cena.entradas() == []
    cena.ir(_as(10, 1, 1))
    [req] = cena.entradas()
    assert req["symbol"] == "WINV26" and req["magic"] == 7_000_000 + mundo.lig
    assert req["volume"] == 3 and req["type"] == cena.mt5.ORDER_TYPE_BUY
    [ex] = _eventos("executada")
    assert ex["entry_ts"] == ENTRADA and 0 <= ex["atraso_ms"] <= 1500
    # a rolagem do dia ficou no diário, uma vez
    assert [e["simbolo"] for e in _eventos("rolagem")] == ["WINV26"]


def test_ordem_sai_antes_de_qualquer_escrita_no_banco(cena, monkeypatch):
    cena.ir(_as(10, 0, 30))
    linha = []
    real_escrita, real_envio = db.connect_write, cena.mt5.order_send

    def escrita(**k):
        linha.append("banco")
        return real_escrita(**k)

    def envio(req):
        linha.append("ordem")
        return real_envio(req)
    monkeypatch.setattr(db, "connect_write", escrita)
    cena.mt5.order_send = envio
    cena.ir(_as(10, 1, 1))            # o candle das 10:00 fechou: há o que gravar
    assert "banco" in linha and "ordem" in linha
    assert linha.index("ordem") < linha.index("banco")


def test_papel_gravado_ve_a_barra_provisoria(cena, mundo):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    with db.connect(read_only=True) as con:
        ops = con.execute("SELECT entry_ts, aberta FROM papel_operacoes "
                          "WHERE ligacao_id = ?", [mundo.lig]).fetchall()
    assert ops == [(ENTRADA, True)]


# ------------------------------------------------------------ §6.4 caso 2
@pytest.mark.parametrize("servidor_stopou", [True, False])
def test_stop_no_minuto_da_entrada_sai_e_nunca_reentra(cena, mundo, servidor_stopou):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    [ex] = _eventos("executada")
    # o candle das 10:01 fecha batendo o stop do papel (189_005 - 200)
    cena.mt5.barras[ENTRADA] = (PRECO, PRECO + 50, PRECO - 300, PRECO - 100)
    if servidor_stopou:
        cena.mt5.stopar(ex["ticket"])
    cena.ir(_as(10, 2, 1))
    cena.ir(_as(10, 2, 3))
    cena.ir(_as(10, 2, 20))
    if servidor_stopou:
        assert [e["ticket"] for e in _eventos("saiu_antes")] == [ex["ticket"]]
        assert cena.saidas() == []
    else:
        assert [r["position"] for r in cena.saidas()] == [ex["ticket"]]
        assert _eventos("saida_executada")
    assert len(cena.entradas()) == 1          # nunca reentra
    assert cena.mt5.posicoes == {}


# ------------------------------------------------------------ §6.4 caso 6
def test_reinicio_com_posicao_nao_sai_por_falta_de_papel(cena, mundo, monkeypatch):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    [ex] = _eventos("executada")
    enviados = len(cena.mt5.enviados)

    # a captura reabre às 10:30:20 com o banco ocupado: sem retrato, o papel
    # está indisponível — só protege, nenhuma posição sai
    soltar = _ocupar(monkeypatch)
    s2 = cena.novo_servico()
    cena.ir(_as(10, 30, 20), s2)
    assert len(cena.mt5.enviados) == enviados
    assert s2._disponivel is False
    assert C.ler_estado(cena.base / "ao_vivo" / "estado.json")["ordens"]["foto"] == "ok"

    # o banco solta: calcula na hora e a posição do papel segue a mesma
    soltar()
    cena.ir(_as(10, 30, 26), s2)
    cena.ir(_as(10, 30, 28), s2)
    assert s2._disponivel is True
    d = s2._desejados[mundo.lig]
    assert (d.estado, d.entry_ts) == (PV.POSICAO, ENTRADA)
    assert len(cena.mt5.enviados) == enviados
    assert list(cena.mt5.posicoes) == [ex["ticket"]]


# ------------------------------------------------------------ §6.4 caso 7
def test_nenhuma_entrada_nos_5_s_depois_de_conectar(cena):
    cena.ir(_as(10, 1, 1))            # primeira volta: acabou de conectar
    assert cena.entradas() == []
    cena.ir(_as(10, 1, 3))
    assert cena.entradas() == []
    cena.ir(_as(10, 1, 6))
    assert len(cena.entradas()) == 1


def test_lista_vazia_ao_reconectar_nao_duplica_e_chama_mt5_fora(cena):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    assert len(cena.entradas()) == 1
    cena.mt5.conectado = False        # a corretora cai com a posição aberta
    cena.ir(_as(10, 1, 10))
    assert [e["tipo"] for e in _chamados("mt5_fora")] == ["chamado"]
    cena.mt5.conectado = True
    cena.mt5.vazio_uma_vez = True     # positions_get vazio logo após voltar
    for seg in (12, 13, 14, 15):
        cena.ir(_as(10, 1, seg))
    assert len(cena.entradas()) == 1
    assert [e["tipo"] for e in _chamados("mt5_fora")] == ["chamado", "chamado_fechado"]


def test_conectado_desde_reinicia_quando_a_corretora_volta(cena):
    cena.ir(_as(10, 0, 30))
    assert cena.s.conectado_desde == cena.mono.t
    cena.mt5.conectado = False
    cena.ir(_as(10, 0, 40))
    cena.mt5.conectado = True
    cena.ir(_as(10, 0, 45))
    assert cena.s.conectado_desde == cena.mono.t


# ----------------------------------------------------------- §6.4 caso 11
def test_candle_revisado_apaga_o_sinal_e_a_posicao_sai(cena):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    [ex] = _eventos("executada")
    # o MT5 revisa o 10:00 (o leilão consolidado): o sinal some
    cena.mt5.barras[SINAL] = (PRECO, PRECO + 50, PRECO - 50, PRECO)
    cena.ir(_as(10, 1, 20))
    assert [r["position"] for r in cena.saidas()] == [ex["ticket"]]
    assert len(cena.entradas()) == 1


def test_candle_revisado_que_cria_entrada_no_passado_nao_entra(cena):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    cena.mt5.barras[SINAL] = (PRECO, PRECO + 50, PRECO - 50, PRECO)
    t = _as(9, 30)
    cena.mt5.barras[t] = (PRECO, MARCA + 30, PRECO - 50, MARCA)
    cena.ir(_as(10, 1, 20))
    cena.ir(_as(10, 1, 22))
    cena.ir(_as(10, 1, 25))
    # o papel agora quer a operação das 09:31: já passou a janela de 30 s,
    # então nunca é enviada; a das 10:01 (que não é mais a atual) sai
    assert s_desejado(cena).entry_ts == t + timedelta(minutes=1)
    assert len(cena.entradas()) == 1
    assert not [e for e in _eventos("enviando") if e["entry_ts"] != ENTRADA]
    assert len(cena.saidas()) == 1 and cena.mt5.posicoes == {}


def s_desejado(cena):
    [d] = cena.s._desejados.values()
    return d


# ----------------------------------------------------------- §6.4 caso 18
def test_banco_ocupado_2_min_entrada_e_saida_saem_e_o_espelho_vem_depois(
        cena, monkeypatch):
    cena.ir(_as(10, 0, 30))
    soltar = _ocupar(monkeypatch)
    cena.ir(_as(10, 1, 1))
    assert len(cena.entradas()) == 1
    cena.mt5.barras[ENTRADA] = (PRECO, PRECO + 50, PRECO - 300, PRECO - 100)
    cena.ir(_as(10, 2, 1))
    assert len(cena.saidas()) == 1
    cena.ir(_as(10, 2, 30))
    soltar()
    with db.connect(read_only=True) as con:     # nada da entrada chegou ao banco ainda
        assert con.execute("SELECT count(*) FROM ordens_eventos "
                           "WHERE ligacao_id IS NOT NULL").fetchone()[0] == 0
    cena.ir(_as(10, 3, 1))            # o candle das 10:02 grava: o espelho vai junto
    with db.connect(read_only=True) as con:
        tipos = {r[0] for r in con.execute("SELECT tipo FROM ordens_eventos").fetchall()}
    assert {"enviando", "executada", "saida_enviando", "saida_executada"} <= tipos


# ----------------------------------------------------------- §6.4 caso 19
def test_sem_tick_nao_entra(cena):
    cena.ir(_as(10, 0, 30))
    cena.mt5.tick_ok = False
    cena.ir(_as(10, 1, 1))
    cena.ir(_as(10, 1, 3))
    assert cena.mt5.enviados == []
    assert cena.estado()["ordens"]["vivo_em"] is not None


# ------------------------------------------------------- guarda de preço
def test_guarda_de_preco_por_mais_de_60_s_chama_e_fecha_quando_solta(cena):
    cena.ir(_as(9, 59, 0))            # contrato escolhido com os preços iguais
    cena.mt5.precos["WINV26"] = PRECO + 100      # 20 ticks longe do WIN$N
    cena.ir(_as(9, 59, 30))
    assert _chamados("preco_contrato") == []
    cena.ir(_as(10, 0, 31))
    assert [e["tipo"] for e in _chamados("preco_contrato")] == ["chamado"]
    cena.ir(_as(10, 1, 1))            # entrada barrada: preço do contrato não bate
    assert cena.entradas() == []
    cena.mt5.precos["WINV26"] = PRECO
    cena.ir(_as(10, 1, 5))
    assert [e["tipo"] for e in _chamados("preco_contrato")] == ["chamado", "chamado_fechado"]


# ---------------------------------------------------------------- cadência
def test_volta_rapida_perto_da_virada_do_minuto(cena):
    assert cena.ir(_as(10, 0, 30)) == P.ESPERA_PREGAO
    assert cena.ir(_as(10, 0, 58)) == P.VOLTA_RAPIDA
    assert cena.ir(_as(10, 0, 59)) == P.VOLTA_RAPIDA
    assert cena.ir(_as(10, 1, 5)) == P.VOLTA_RAPIDA
    assert cena.ir(_as(10, 1, 10)) == P.VOLTA_RAPIDA
    assert cena.ir(_as(10, 1, 11)) == P.ESPERA_PREGAO
    assert cena.ir(_as(10, 1, 30)) == P.ESPERA_PREGAO


def test_fora_do_pregao_a_volta_e_a_de_hoje(cena):
    assert cena.ir(_as(18, 40, 59)) == P.ESPERA_FORA


# ----------------------------------------------------- desejados no minuto
def test_desejados_so_recalculam_quando_o_minuto_muda(cena, monkeypatch):
    real = PV.desejados
    chamadas = []

    def espiao(*a, **k):
        chamadas.append(a)
        return real(*a, **k)
    monkeypatch.setattr(PV, "desejados", espiao)
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 0, 31))
    cena.ir(_as(10, 0, 36))           # o retrato é relido (5 s) sem mudar nada
    cena.ir(_as(10, 0, 59))
    assert len(chamadas) == 1
    cena.ir(_as(10, 1, 1))            # minuto novo
    cena.ir(_as(10, 1, 1, ))
    cena.ir(_as(10, 1, 2))
    assert len(chamadas) == 2


# ---------------------------------------------------------------- estado
def test_estado_json_tem_o_bloco_das_ordens(cena, mundo):
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    o = cena.estado()["ordens"]
    assert o["foto"] == "ok" and o["contrato"] == "WINV26" and o["envio"] is True
    assert o["vivo_em"] == "2026-10-09T10:01:01" and o["disponivel"] is True
    assert o["ligacoes"][str(mundo.lig)]["desejado"] == PV.POSICAO
    assert o["retrato_em"] is not None and o["contrato_dia"]["simbolo"] == "WINV26"
    assert o["conta"]["confere"] is True


def test_fora_do_pregao_sem_posicao_so_publica(cena):
    cena.ir(_as(18, 40))
    o = cena.estado()["ordens"]
    assert o["foto"] is None and o["vivo_em"] == "2026-10-09T18:40:00"
    assert cena.mt5.enviados == []


# ------------------------------------------------- falha não para a captura
def test_erro_nas_ordens_nao_para_os_candles(cena, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("motor quebrou")
    monkeypatch.setattr(ordens.Motor, "passo", quebra)
    cena.ir(_as(10, 0, 30))
    e = cena.estado()
    assert e["erro"] is None and e["gravados_hoje"] == 60
    assert e["ordens"]["erro"] == "motor quebrou"
    assert [c["tipo"] for c in _chamados("ordens_falhou")] == ["chamado"]
    cena.ir(_as(10, 1, 1))
    assert cena.estado()["gravados_hoje"] == 61


# ------------------------------------------------- Envio desligado (padrão)
def test_envio_desligado_so_registra_seria_enviada_da_ligacao_em_demo(base, mundo):
    papel_ = _ligacao("papel-b", fase="papel", run_id=2, portfolio_id=mundo.pf)
    c = Cena(base)
    for t in (_as(10, 0, 30), _as(10, 1, 1), _as(10, 1, 3), _as(10, 1, 20)):
        c.ir(t)
    # o ensaio confere o formato na corretora (order_check), nunca envia
    assert c.mt5.enviados == []
    assert [r["magic"] for r in c.mt5.checados] == [7_000_000 + mundo.lig]
    assert [e["ligacao_id"] for e in _eventos("seria_enviada")] == [mundo.lig]
    assert _eventos("seria_enviada")[0]["retcode"] == 0
    assert papel_.lig not in {e.get("ligacao_id") for e in _eventos()}


# ---------------------------------------------------------------- espelho
def test_espelho_so_na_escrita_que_a_volta_ja_abre_e_em_autocommit(cena, monkeypatch):
    escritas, espelhos = [], []
    real_escrita = db.connect_write

    def escrita(**k):
        con = real_escrita(**k)
        escritas.append(con)
        return con
    monkeypatch.setattr(db, "connect_write", escrita)

    def conferir(con):
        assert any(con is e for e in escritas), "espelho fora de uma escrita"
        # em autocommit: abrir uma transação aqui não pode falhar
        con.execute("BEGIN TRANSACTION")
        con.execute("ROLLBACK")

    real_dia, real_todos = Diario.espelhar, diario_ordens.espelhar_pendentes

    def espelhar(self, con):
        conferir(con)
        espelhos.append("dia")
        return real_dia(self, con)

    def pendentes(pasta, con, *a, **k):
        conferir(con)
        espelhos.append("todos")
        return real_todos(pasta, con, *a, **k)
    monkeypatch.setattr(Diario, "espelhar", espelhar)
    monkeypatch.setattr(diario_ordens, "espelhar_pendentes", pendentes)

    cena.ir(_as(10, 0, 30))           # subida: o primeiro escritor leva tudo
    assert espelhos[:1] == ["todos"]
    n_escritas, n_espelhos = len(escritas), len(espelhos)
    cena.ir(_as(10, 0, 31))           # sem candle novo: nenhuma escrita, nenhum espelho
    assert (len(escritas), len(espelhos)) == (n_escritas, n_espelhos)
    cena.ir(_as(10, 1, 1))            # entrada + candle das 10:00
    assert espelhos[n_espelhos:] and len(escritas) > n_escritas
    with db.connect(read_only=True) as con:
        tipos = {r[0] for r in con.execute("SELECT tipo FROM ordens_eventos").fetchall()}
    assert {"enviando", "executada"} <= tipos


# ---------------------------------------------------- papel × backtest
def test_papel_backtest_so_fora_do_pregao(cena, mundo, monkeypatch):
    feitos, listados = [], []

    def pendentes(con, symbol="WIN$N"):
        listados.append(1)
        return [(mundo.lig, date(2026, 10, 8))]

    def conferir(con, lig, dia, cache, agora, symbol="WIN$N"):
        feitos.append((lig, dia))
        return {}
    monkeypatch.setattr(papel_backtest, "pendentes", pendentes)
    monkeypatch.setattr(papel_backtest, "conferir", conferir)

    cena.s.reexportar = True          # força a escrita da conferência no pregão
    cena.ir(_as(10, 5))
    assert cena.s.reexportar is False         # a escrita da conferência aconteceu
    assert feitos == [] and listados == []

    cena.ir(_as(18, 40))              # depois do fechamento
    assert feitos == [(mundo.lig, date(2026, 10, 8))]


# ----------------------------------------------------------------- orçamento
@pytest.mark.lento
def test_desejados_cabe_em_300_ms_com_o_aquecimento_da_maior_estrategia():
    """Spec §3.1: cálculo do papel < 300 ms por ligação, com o aquecimento
    real da maior estratégia do portfólio do usuário (rompimento_ema_abertura,
    ema_longa 600, M7). Barras sintéticas do mesmo tamanho."""
    mod = importlib.import_module("strategies.rompimento_ema_abertura")
    plano = {"plano_id": 1, "contratos": 1,
             "params": {"ema_curta": 9, "ema_longa": 600, "distancia_abertura": 0},
             "profile": {**PERFIL, "timeframe": "M7"}}
    estrat, perfil = papel.perfil_do_plano(plano)
    pregoes = papel.pregoes_de_aquecimento(mod, estrat, perfil)
    b, dias = barras_sinteticas(n_dias=pregoes + 1)
    hoje_dia = dias[-1]
    agora = datetime.combine(hoje_dia, datetime.min.time()) + timedelta(hours=12, seconds=30)
    corte = np.datetime64(datetime.combine(hoje_dia, datetime.min.time()), "ns")
    minuto = np.datetime64(agora.replace(second=0), "ns")
    antes = b["ts"] < corte
    hoje = (b["ts"] >= corte) & (b["ts"] < minuto)
    aquec = PV.Aquecimento({k: v[antes] for k, v in b.items()}, pregoes)
    barras_hoje = {k: v[hoje] for k, v in b.items()}
    prov = (agora.replace(second=0), int(b["open"][np.flatnonzero(b["ts"] == minuto)[0]]))
    lv = PV.LigacaoViva(ligacao_id=1, portfolio_id=1, status="rodando", motivo=None,
                        plano=plano, modulo=mod,
                        periodos=[(datetime(2000, 1, 1), datetime(2100, 1, 1))],
                        fase="demo", conta_id=1, ligada=True)
    ret = PV.Retrato(dia=hoje_dia, lido_em=agora, ligacoes={1: lv}, contas={},
                     portfolio_de={1: 1})
    inst = db.load_instrument_yaml("WIN$N")

    des, ok = PV.desejados(ret, aquec, barras_hoje, prov, inst, agora)   # compila o numba
    assert ok and 1 in des and des[1].estado in (PV.POSICAO, PV.ZERADO)
    tempos = []
    for _ in range(5):
        t = _time.perf_counter()
        PV.desejados(ret, aquec, barras_hoje, prov, inst, agora)
        tempos.append(_time.perf_counter() - t)
    medido = sorted(tempos)[len(tempos) // 2]
    print(f"\npapel_vivo.desejados: {len(aquec.barras['ts'])} barras de aquecimento "
          f"({pregoes} pregões), mediana {medido * 1000:.0f} ms, "
          f"tempos {[round(x * 1000) for x in tempos]} ms")
    assert medido < 0.300


# ===================================================== rodada de correções 1
def _banco_lento(cena, monkeypatch):
    """Banco ocupado que DORME como o de verdade: cada conexão pedida avança
    o relógio pelas tentativas × espera pedidas. Devolve (chamadas, soltar)."""
    chamadas = []
    reais = (db.connect_write, db.connect)

    def lento(*a, **k):
        chamadas.append(dict(k))
        cena.mono.t += k.get("tentativas", 60) * k.get("espera", 0.25)
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect_write", lento)
    monkeypatch.setattr(db, "connect", lento)

    def soltar():
        monkeypatch.setattr(db, "connect_write", reais[0])
        monkeypatch.setattr(db, "connect", reais[1])
    return chamadas, soltar


def test_banco_ocupado_na_virada_nao_atrasa_a_ordem(cena, monkeypatch):
    cena.ir(_as(10, 0, 30))
    chamadas, soltar = _banco_lento(cena, monkeypatch)
    cena.ir(_as(10, 0, 40))
    # há passos do banco por fazer na virada: o papel ficou por gravar e a
    # janela da conferência venceu
    cena.s.papel_pendente = True
    cena.s._mono_conferencia = None
    chamadas.clear()
    # o laço de verdade a partir das 10:00:59,5: cada volta dorme o que a
    # anterior pediu, depois de gastar o que gastou (o banco dormindo)
    espera = cena.ir(datetime(2026, 10, 9, 10, 0, 59, 500_000))
    antes_da_virada = list(chamadas)
    while not _eventos("executada") and cena.mono.t < 1000.0 + 3665:
        espera = cena.seguir(espera)
    [ex] = _eventos("executada")
    assert ex["atraso_ms"] < 1000
    # o minuto novo ainda não tinha rodado as ordens: nenhum passo do banco
    assert antes_da_virada == []
    # depois das ordens o banco é tentado, mas sem esperar (pregão)
    assert chamadas and all((k.get("tentativas"), k.get("espera")) == (1, 0)
                            for k in chamadas)
    soltar()
    cena.ir(_as(10, 1, 2))            # o candle das 10:00 vem numa volta seguinte
    assert cena.estado()["gravados_hoje"] == 61


def test_papel_backtest_para_no_corte_das_08_57(cena, mundo, monkeypatch):
    todos = [(mundo.lig, date(2026, 10, d)) for d in (6, 7, 8)]
    feitos = []
    monkeypatch.setattr(papel_backtest, "pendentes",
                        lambda con, symbol="WIN$N": [p for p in todos if p not in feitos])

    def conferir(con, lig, dia, cache, agora, symbol="WIN$N"):
        feitos.append((lig, dia))
        cena.mono.t += 70             # o backtest do histórico inteiro custa
        return {}
    monkeypatch.setattr(papel_backtest, "conferir", conferir)
    cena.ir(_as(8, 56, 20))
    # 08:56:20 → o primeiro; depois dele o relógio passou das 08:57: para
    assert feitos == todos[:1]
    cena.ir(_as(18, 40))              # depois do fechamento: o resto
    assert feitos == todos


def test_papel_backtest_que_falha_nao_volta_a_cada_janela(cena, mundo, monkeypatch):
    monkeypatch.setattr(papel_backtest, "pendentes",
                        lambda con, symbol="WIN$N": [(mundo.lig, date(2026, 10, 8))])
    chamadas = []

    def conferir(*a, **k):
        chamadas.append(a)
        raise RuntimeError("plano não roda")
    monkeypatch.setattr(papel_backtest, "conferir", conferir)
    cena.ir(_as(18, 40))
    cena.ir(_as(18, 46))              # a janela seguinte (5 min)
    cena.ir(_as(18, 52))
    assert len(chamadas) == 1


def test_chamado_ordens_falhou_fecha_numa_volta_limpa_sem_passo(cena, monkeypatch):
    quebrado = {"sim": True}
    real = ordens.Motor.passo

    def passo(self, *a, **k):
        if quebrado["sim"]:
            raise RuntimeError("motor quebrou")
        return real(self, *a, **k)
    monkeypatch.setattr(ordens.Motor, "passo", passo)
    cena.ir(_as(10, 0, 30))
    assert [c["tipo"] for c in _chamados("ordens_falhou")] == ["chamado"]
    quebrado["sim"] = False
    cena.mt5.tick_ok = False          # sem relógio e sem posição: não chega ao passo
    cena.ir(_as(10, 0, 40))
    assert [c["tipo"] for c in _chamados("ordens_falhou")] == ["chamado", "chamado_fechado"]


def test_retrato_nao_e_relido_perto_da_virada(cena, monkeypatch):
    real = PV.ler_retrato
    lidos = []

    def ler(*a, **k):
        lidos.append(a[2])
        return real(*a, **k)
    monkeypatch.setattr(PV, "ler_retrato", ler)
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 0, 58))
    cena.ir(_as(10, 1, 5))
    assert len(lidos) == 1
    cena.ir(_as(10, 1, 20))
    assert len(lidos) == 2


def test_falha_repetida_loga_o_traceback_uma_vez_e_depois_uma_linha_por_minuto(
        cena, monkeypatch, caplog):
    def quebra(*a, **k):
        raise RuntimeError("motor quebrou")
    monkeypatch.setattr(ordens.Motor, "passo", quebra)
    with caplog.at_level("INFO", logger="captura"):
        for t in (_as(10, 0, 30), _as(10, 0, 31), _as(10, 0, 32), _as(10, 0, 50)):
            cena.ir(t)
        cena.ir(_as(10, 1, 40))       # mais de um minuto depois
    recs = [r for r in caplog.records if "caminho das ordens falhou" in r.getMessage()]
    assert [bool(r.exc_info) for r in recs] == [True, False]
    assert "segue falhando" in recs[1].getMessage()


# ===================================================== rodada de correções 2
def test_ordens_falhou_fecha_quando_o_passo_volta_cedo_sem_erro(base, mods, monkeypatch):
    """O cenário do usuário hoje: nenhuma ligação em demo e a conta logada no
    MT5 fora de qualquer portfólio — o passo volta cedo (conta não confere)
    a cada volta, sem chegar ao fechamento do próprio passo."""
    _ligacao("so-papel", fase="papel")
    c = Cena(base)
    real = P.Servico._barras_hoje
    falhar = {"sim": True}

    def barras(self, srv):
        if falhar["sim"]:
            raise OSError("terminal não respondeu")
        return real(self, srv)
    monkeypatch.setattr(P.Servico, "_barras_hoje", barras)
    c.ir(_as(10, 0, 30))
    assert [e["tipo"] for e in _chamados("ordens_falhou")] == ["chamado"]
    falhar["sim"] = False
    c.ir(_as(10, 0, 31))
    c.ir(_as(10, 0, 32))
    o = c.estado()["ordens"]
    assert o["conta"]["confere"] is False and o["falhou"] is False
    assert [e["tipo"] for e in _chamados("ordens_falhou")] == ["chamado", "chamado_fechado"]


def test_passo_que_falha_mantem_o_chamado(cena, monkeypatch):
    # falha DENTRO do passo (execução): o chamado é do passo e fica aberto
    def quebra(self, *a, **k):
        raise RuntimeError("terminal caiu no envio")
    monkeypatch.setattr(ordens.Motor, "executar", quebra)
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    assert cena.estado()["ordens"]["falhou"] is True
    assert [e["tipo"] for e in _chamados("ordens_falhou")] == ["chamado"]


def test_falha_com_numeros_diferentes_e_a_mesma_no_log(cena, caplog):
    s = cena.s
    with caplog.at_level("INFO", logger="captura"):
        for ticket in (1001, 1002, 1003):
            try:
                raise RuntimeError(f"saída do ticket {ticket} recusada (retcode 100{ticket % 10})")
            except RuntimeError as e:
                s._falha("ordens", e)
        try:
            raise RuntimeError("outra coisa")
        except RuntimeError as e:
            s._falha("ordens", e)
    tracebacks = [r for r in caplog.records if r.exc_info]
    assert len(tracebacks) == 2


# ------------------------------------- topo da tela fora do pregão (tarefa 14)
def test_fora_do_pregao_publica_envio_n_demo_e_trava(cena, mundo):
    """Parado, nada sai — mas o selo do topo ainda diz o interruptor do
    Envio (último retrato), se há demo e se a conta travou hoje."""
    cena.ir(_as(10, 0, 30))
    assert cena.estado()["ordens"]["n_demo"] == 1
    cena.ir(_as(18, 40))
    o = cena.estado()["ordens"]
    assert o["parado"] and o["n_demo"] == 1 and o["envio"] is True
    assert o["travada"] is None
    cena.s.motor.diario(DIA).registrar("conta_travada", quando=_as(15, 0),
                                       conta_id=mundo.conta, perda=900.0,
                                       limite=1000.0)
    cena.ir(_as(18, 41))
    t = cena.estado()["ordens"]["travada"]
    assert t["perda"] == 900.0 and t["desde"].startswith("2026-10-09T15:00")


def test_fora_do_pregao_sem_retrato_nao_inventa(cena):
    cena.ir(_as(18, 40))
    o = cena.estado()["ordens"]
    assert o["n_demo"] is None and o["envio"] is None


# ======================================================= correção final (09/10)
@pytest.mark.lento
def test_order_check_do_ensaio_cabe_no_orcamento_e_vem_depois_das_saidas(tmp_path):
    """I3 + spec §3.1 (virada → ordem < 1 s): o ensaio passa cada pedido
    pelo order_check. Com 5 ligações em demo e um order_check pessimista de
    50 ms (no terminal é uma chamada local), a volta inteira cabe em 1 s, o
    custo do motor além das chamadas fica pequeno, e a saída de uma posição
    da automação sai ANTES do primeiro order_check — o ensaio nunca segura
    uma saída."""
    from core.papel_vivo import Desejado, LigacaoViva, Retrato
    espera = 0.050
    agora = datetime(2026, 10, 9, 10, 1, 1)
    mt5 = MT5Ordens(agora=agora)
    linha = []
    real_check, real_send = mt5.order_check, mt5.order_send

    def check(req):
        linha.append("check")
        _time.sleep(espera)
        return real_check(req)

    def send(req):
        linha.append("send")
        return real_send(req)
    mt5.order_check, mt5.order_send = check, send
    velha = mt5.abrir_manual(1, magic=7_000_000 + 9)       # da automação: sai
    ligs = {i: LigacaoViva(ligacao_id=i, portfolio_id=1, status="rodando", motivo=None,
                           plano=None, modulo=None, fase="demo", conta_id=2,
                           ligada=True, desvio=10) for i in range(1, 6)}
    ret = Retrato(dia=DIA, lido_em=agora, ligacoes=ligs,
                  contas={2: {"login": LOGIN, "servidor": SERVIDOR, "limite": 1e6,
                              "envio": False}},
                  portfolio_de={i: 1 for i in ligs})
    ts = agora.replace(second=0)
    des = {i: Desejado(PV.POSICAO, lado=1, entry_ts=ts, entry_px=PRECO,
                       stop_px=PRECO - 200, alvo_px=PRECO + 400, contratos=1)
           for i in ligs}
    m = ordens.Motor(tmp_path, {"tick_size": 5, "point_value": 0.2})
    t0 = _time.perf_counter()
    m.passo(mt5, agora_srv=agora, retrato=ret, desejados=des, disponivel=True,
            comandos=[], simbolo="WINV26", contrato_ok=True, conectado_ha_s=60.0)
    total = _time.perf_counter() - t0
    seria = [e for e in m.diario(DIA).eventos if e["tipo"] == "seria_enviada"]
    print(f"\nensaio com order_check: {len(seria)} ligações, {total * 1000:.0f} ms "
          f"({len(ligs)} × {espera * 1000:.0f} ms de order_check)")
    assert len(seria) == 5 and all(e["retcode"] == 0 for e in seria)
    assert velha not in mt5.posicoes
    assert linha[0] == "send" and linha.count("send") == 1      # a saída primeiro
    assert total < 1.0
    assert total - len(ligs) * espera < 0.150                   # o resto do motor


def test_subida_com_banco_ocupado_usa_o_retrato_salvo_e_protege(cena, mundo, monkeypatch):
    """M3: a captura cai logo depois de a proteção da entrada falhar e volta
    com o banco preso pela mineração. Sem retrato do banco, o salvo (ao lado
    do diário) diz a conta: a posição sem SL/TP recebe a proteção gravada
    no diário. Nada entra; nada sai por falta de papel."""
    from core import diario_ordens as DO
    cena.mt5.roteiro = [10009, 10018]          # entra; a proteção é recusada
    cena.ir(_as(10, 0, 30))
    arq = Path(DO.PASTA) / P.Servico.ARQ_RETRATO
    assert arq.exists() and "ao_vivo" in str(arq) and str(RAIZ) not in str(arq)
    cena.ir(_as(10, 1, 1))
    [ex] = _eventos("executada")
    assert cena.mt5.posicoes[ex["ticket"]].sl == 0

    _ocupar(monkeypatch)
    s2 = cena.novo_servico()
    cena.ir(_as(10, 1, 2), s2)
    assert s2.retrato is not None and s2.retrato.antigo
    p = cena.mt5.posicoes[ex["ticket"]]
    assert p.sl == 188_805 and p.tp == 189_405
    assert len(cena.entradas()) == 1 and cena.saidas() == []
    o = cena.estado()["ordens"]
    assert o["retrato_antigo"] is True and o["envio"] is True
    # depois de 3 min o chamado do papel parado diz a verdade
    cena.ir(_as(10, 4, 5), s2)
    texto = s2.motor.chamados["papel_parado"]["texto"]
    assert "banco ocupado" in texto and "configuração salva" in texto
    assert len(cena.entradas()) == 1 and cena.saidas() == []


def test_subida_com_banco_ocupado_sem_retrato_salvo_nao_protege(cena, mundo, monkeypatch):
    # o controle do teste acima: sem o arquivo, a automação fica sem a conta
    from core import diario_ordens as DO
    cena.mt5.roteiro = [10009, 10018]
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    [ex] = _eventos("executada")
    (Path(DO.PASTA) / P.Servico.ARQ_RETRATO).unlink()
    _ocupar(monkeypatch)
    s2 = cena.novo_servico()
    cena.ir(_as(10, 1, 2), s2)
    assert s2.retrato is None and cena.mt5.posicoes[ex["ticket"]].sl == 0


def test_retrato_salvo_some_quando_o_banco_volta(cena, mundo, monkeypatch):
    from core import diario_ordens as DO
    cena.ir(_as(10, 0, 30))
    soltar = _ocupar(monkeypatch)
    s2 = cena.novo_servico()
    cena.ir(_as(10, 0, 40), s2)
    assert s2.retrato.antigo and s2._disponivel is False
    soltar()
    cena.ir(_as(10, 0, 46), s2)
    cena.ir(_as(10, 0, 47), s2)
    assert not s2.retrato.antigo and s2._disponivel is True
    assert Path(DO.PASTA, P.Servico.ARQ_RETRATO).exists()


def test_contrato_escolhido_um_instante_depois_ainda_entra(cena, mundo):
    """M1: às 10:01:01 o WIN$N está com último 0 (contrato não escolhido);
    na volta seguinte o preço chega, o contrato é escolhido e a entrada sai."""
    cena.mt5.precos["WIN$N"] = 0
    cena.ir(_as(10, 0, 30))
    assert cena.s.contrato_dia["simbolo"] is None
    cena.ir(_as(10, 1, 1))
    assert cena.entradas() == [] and not _eventos("nao_entrou")
    assert _eventos("recusada")[0]["motivo"] == ordens.SEM_CONTRATO
    cena.mt5.precos["WIN$N"] = PRECO
    cena.ir(_as(10, 1, 3))
    assert len(cena.entradas()) == 1 and _eventos("executada")


def test_zerar_clicado_ontem_fora_do_pregao_nao_trava_hoje(cena, mundo):
    """I1 na captura: o comando escrito ontem à noite (sem posição, as
    ordens paradas) fica na pasta e é lido na manhã seguinte: descartado."""
    import json as _json
    from core import comandos as CMD
    pasta = Path(CMD.PASTA)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "20261008193000000000-x.json").write_text(_json.dumps(
        {"id": "x", "tipo": "zerar_tudo", "criado_em": "2026-10-08T19:30:00"}),
        encoding="utf-8")
    cena.ir(_as(10, 0, 30))
    cena.ir(_as(10, 1, 1))
    assert not list(pasta.glob("*.json"))
    # (o "envio" é o ligar do Envio que o cenário fez pela ficha)
    assert [e["motivo"] for e in _eventos("comando") if e["motivo"] != "envio"] == \
        [ordens.ZERAR_DESCARTADO]
    assert len(cena.entradas()) == 1 and cena.estado()["ordens"]["zerar"] is False


# ================================================ Ordem de teste (15/10/2026)
def test_ordem_teste_pelo_arquivo_roda_na_captura_com_o_envio_desligado(base, mundo):
    from core import comandos
    from core import corretora as K
    c = Cena(base)                    # o Envio segue desligado (como no app)
    c.ir(_as(10, 0, 30))
    comandos.escrever(comandos.PASTA, "ordem_teste", conta_id=mundo.conta)
    c.ir(_as(10, 0, 31))
    teste = [r for r in c.mt5.enviados if r.get("magic") == K.MAGIC_TESTE]
    assert len(teste) == 1 and teste[0]["symbol"] == "WINV26"
    assert not list(Path(comandos.PASTA).glob("*.json"))
    o = c.estado()["ordens"]
    assert o["teste"]["situacao"] == "andamento"


def test_ordem_teste_fora_do_pregao_e_recusada_na_hora(cena, mundo):
    from core import comandos
    comandos.escrever(comandos.PASTA, "ordem_teste", conta_id=mundo.conta)
    cena.ir(_as(18, 40))
    assert cena.mt5.enviados == []
    # só o pedido de teste sai da pasta (o do Envio fica para o pregão)
    assert [c["tipo"] for c in comandos.consumir(comandos.PASTA)] == ["envio"]
    f = _eventos("teste_falhou")
    assert len(f) == 1 and f[0]["motivo"] == "fora do pregão"
    assert cena.estado()["ordens"]["teste"]["texto"] == "Teste recusado: fora do pregão"


def test_ordem_teste_com_mt5_fora_e_recusada_e_nao_roda_depois(cena, mundo):
    from core import comandos
    cena.mt5.conectado = False
    comandos.escrever(comandos.PASTA, "zerar_tudo")
    comandos.escrever(comandos.PASTA, "ordem_teste", conta_id=mundo.conta)
    cena.s.mt5_estado = "desconectado"
    cena.s._ordens(_as(10, 0, 30), cena.mono.t)
    f = _eventos("teste_falhou")
    assert len(f) == 1 and f[0]["motivo"] == "MT5 fora do ar"
    # o Zerar tudo fica para a volta que pode cumpri-lo
    assert [c["tipo"] for c in comandos.consumir(comandos.PASTA)] == ["envio", "zerar_tudo"]


def test_posicao_de_teste_que_sobrou_fora_do_pregao_e_encerrada(cena):
    from core import corretora as K
    t = cena.mt5.abrir_manual(1, magic=K.MAGIC_TESTE)
    cena.ir(_as(18, 40))
    assert t not in cena.mt5.posicoes
