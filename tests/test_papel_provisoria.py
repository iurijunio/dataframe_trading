"""Barra provisória: a entrada aparece no primeiro segundo do minuto, igual
ao que o candle real daria (spec §3)."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from core import papel
from core.engine import kernel as K
from strategies.base import Signals

DIA = date(2026, 10, 9)
SINAL = datetime(2026, 10, 9, 10, 0)
INST = {"symbol": "WIN$N", "tick_size": 5, "point_value": 0.2, "tick_value": 1.0}
PLANO = {"plano_id": 1, "contratos": 1, "params": {},
         "profile": {"timeframe": "M1", "entrada_inicio": "09:00",
                     "entrada_fim": "17:00", "fechamento": "17:50",
                     "stop_tipo": "pontos", "stop_pontos": 200,
                     "alvo_tipo": "pontos", "alvo_pontos": 400,
                     "dias_semana": [1, 2, 3, 4, 5]}}


def _mod():
    def signals(bars, params):
        n = len(bars["close"])
        el = bars["ts"] == np.datetime64(SINAL, "ns")
        z = np.zeros(n, dtype=bool)
        return Signals(el, z, z.copy(), z.copy())
    return SimpleNamespace(signals=signals)


def _barras(ate: datetime):
    ts = np.arange(np.datetime64("2026-10-09T09:00", "ns"),
                   np.datetime64(ate, "ns") + np.timedelta64(1, "m"),
                   np.timedelta64(1, "m"))
    n = len(ts)
    base = np.full(n, 189_000, dtype=np.int64)
    return {"ts": ts, "open": base, "high": base + 50, "low": base - 50,
            "close": base, "tick_volume": np.zeros(n, np.int64),
            "volume": np.zeros(n, np.int64)}


def test_sem_provisoria_a_entrada_so_aparece_no_minuto_seguinte():
    assert papel.calcular(_barras(SINAL), DIA, PLANO, _mod(), INST) == []


def test_com_provisoria_a_entrada_aparece_ja_as_10_01_aberta():
    b = papel.com_barra_provisoria(_barras(SINAL), SINAL + timedelta(minutes=1), 189_100)
    ops = papel.calcular(b, DIA, PLANO, _mod(), INST)
    assert len(ops) == 1 and ops[0]["aberta"]
    assert ops[0]["entry_ts"] == SINAL + timedelta(minutes=1)


def test_provisoria_da_a_mesma_entrada_que_o_candle_real():
    prov = papel.com_barra_provisoria(_barras(SINAL), SINAL + timedelta(minutes=1), 189_100)
    real = _barras(SINAL + timedelta(minutes=1))
    real["open"] = real["open"].copy()
    real["open"][-1] = 189_100                        # a abertura que o MT5 mostrou
    real = papel.com_barra_provisoria(real, SINAL + timedelta(minutes=2), 189_120)
    a = papel.calcular(prov, DIA, PLANO, _mod(), INST)[0]
    b = papel.calcular(real, DIA, PLANO, _mod(), INST)[0]
    assert (a["entry_ts"], a["entry_px"], a["side"], a["stop_px"], a["alvo_px"]) == \
           (b["entry_ts"], b["entry_px"], b["side"], b["stop_px"], b["alvo_px"])


def test_provisoria_repetida_velha_ou_depois_de_buraco_nao_entra():
    b = _barras(SINAL)
    assert papel.com_barra_provisoria(b, SINAL, 1) is b
    assert papel.com_barra_provisoria(b, SINAL + timedelta(minutes=3), 1) is b
    assert papel.com_barra_provisoria(None, SINAL, 1) is None
    c = papel.com_barra_provisoria(b, SINAL + timedelta(minutes=1), 189_100)
    assert len(c["ts"]) == len(b["ts"]) + 1
    assert c["open"][-1] == c["high"][-1] == c["low"][-1] == c["close"][-1] == 189_100


# ---- saídas forçadas na barra provisória: o "fechamento" dela é falso
def _plano(**perfil):
    return {**PLANO, "profile": {**PLANO["profile"], **perfil}}


def _com_prov(ate_real: datetime, abertura: int):
    return papel.com_barra_provisoria(_barras(ate_real),
                                      ate_real + timedelta(minutes=1), abertura)


def test_fechamento_no_minuto_provisorio_continua_aberta():
    plano = _plano(fechamento="10:03")
    b = _com_prov(datetime(2026, 10, 9, 10, 2), 189_300)
    op = papel.calcular(b, DIA, plano, _mod(), INST, provisoria=True)[0]
    assert op["aberta"] and op["exit_ts"] is None
    assert op["exit_px"] is None and op["reason"] is None


def test_fechamento_com_candle_real_fecha_igual_a_versao_sem_provisoria():
    plano = _plano(fechamento="10:03")
    real = _barras(datetime(2026, 10, 9, 10, 3))
    sem = papel.calcular(real, DIA, plano, _mod(), INST)[0]
    com = papel.com_barra_provisoria(real, datetime(2026, 10, 9, 10, 4), 189_300)
    com = papel.calcular(com, DIA, plano, _mod(), INST, provisoria=True)[0]
    assert not com["aberta"] and not sem["aberta"]
    assert (com["exit_ts"], com["exit_px"], com["reason"]) == \
           (sem["exit_ts"], sem["exit_px"], sem["reason"])
    assert com["exit_px"] == 188_995           # o fechamento real, não 189_300


def test_tempo_maximo_na_barra_provisoria_continua_aberta():
    plano = _plano(max_barras=2)
    b = _com_prov(datetime(2026, 10, 9, 10, 2), 189_300)
    op = papel.calcular(b, DIA, plano, _mod(), INST, provisoria=True)[0]
    assert op["aberta"] and op["exit_px"] is None


def test_saida_por_sinal_na_provisoria_fecha_na_abertura():
    def signals(bars, params):
        n = len(bars["close"])
        z = np.zeros(n, dtype=bool)
        el = bars["ts"] == np.datetime64(SINAL, "ns")
        xl = bars["ts"] == np.datetime64(SINAL + timedelta(minutes=1), "ns")
        return Signals(el, z.copy(), xl, z.copy())
    mod = SimpleNamespace(signals=signals)
    b = _com_prov(datetime(2026, 10, 9, 10, 1), 189_100)
    op = papel.calcular(b, DIA, PLANO, mod, INST, provisoria=True)[0]
    assert not op["aberta"] and op["exit_px"] is not None
    assert op["exit_ts"] == SINAL + timedelta(minutes=2)


# ---- stop/alvo INICIAIS: os que valem durante o minuto da entrada
def test_stop_e_alvo_iniciais_da_compra():
    plano = _plano(breakeven_pct=25)
    # entra 10:01 a 189_000 (+ derrapagem); a provisória das 10:06 abre 200
    # acima: o breakeven moveria o stop no fim dela
    b = papel.com_barra_provisoria(_barras(datetime(2026, 10, 9, 10, 5)),
                                   datetime(2026, 10, 9, 10, 6), 189_200)
    op = papel.calcular(b, DIA, plano, _mod(), INST, provisoria=True)[0]
    assert op["side"] == 1 and op["aberta"]
    assert op["stop_ini_px"] == op["entry_px"] - 200
    assert op["alvo_ini_px"] == op["entry_px"] + 400
    assert op["stop_px"] == op["entry_px"]          # o breakeven já agiu


def test_stop_e_alvo_iniciais_da_venda():
    def signals(bars, params):
        n = len(bars["close"])
        z = np.zeros(n, dtype=bool)
        es = bars["ts"] == np.datetime64(SINAL, "ns")
        return Signals(z, es, z.copy(), z.copy())
    b = _com_prov(datetime(2026, 10, 9, 10, 3), 189_000)
    op = papel.calcular(b, DIA, PLANO, SimpleNamespace(signals=signals), INST,
                        provisoria=True)[0]
    assert op["side"] == -1
    assert op["stop_ini_px"] == op["entry_px"] + 200
    assert op["alvo_ini_px"] == op["entry_px"] - 400


def test_sem_alvo_o_alvo_inicial_e_none():
    plano = _plano(alvo_pontos=0)
    b = _com_prov(datetime(2026, 10, 9, 10, 3), 189_000)
    op = papel.calcular(b, DIA, plano, _mod(), INST, provisoria=True)[0]
    assert op["alvo_ini_px"] is None and op["alvo_px"] is None
    assert op["stop_ini_px"] == op["entry_px"] - 200

# ---- toque do stop/alvo no minuto em formação: a operação fecha no toque
def _mod_venda():
    def signals(bars, params):
        n = len(bars["close"])
        z = np.zeros(n, dtype=bool)
        es = bars["ts"] == np.datetime64(SINAL, "ns")
        return Signals(z, es, z.copy(), z.copy())
    return SimpleNamespace(signals=signals)


PROV = datetime(2026, 10, 9, 10, 6)     # minuto em formação
ANTES = datetime(2026, 10, 9, 10, 5)    # último minuto real


def _aberta(mod=None, plano=None, toque=None, abertura=189_000):
    b = _com_prov(ANTES, abertura)
    ops = papel.calcular(b, DIA, plano or PLANO, mod or _mod(), INST,
                         provisoria=True, toque=toque)
    return ops[0]


def test_sem_toque_a_operacao_segue_aberta_como_hoje():
    sem = _aberta()
    assert sem["aberta"] and sem["exit_px"] is None
    assert _aberta(toque=(189_050, 188_950)) == sem


def test_toque_no_stop_da_compra_fecha_no_toque_com_derrapagem():
    custos = _plano(corretagem_por_contrato=0.5, emolumentos_por_contrato=0.25)
    op0 = _aberta(plano=custos)
    stop = op0["stop_px"]
    op = _aberta(plano=custos, toque=(189_000, stop - 10))
    assert not op["aberta"]
    assert op["exit_ts"] == PROV
    assert op["reason"] == K.EXIT_STOP
    assert op["exit_px"] == stop - 5                     # 1 tick contra
    assert op["points"] == op["exit_px"] - op0["entry_px"]
    bruto = op["points"] * 0.2 * CONTRATOS_PLANO
    assert op["bruto"] == pytest.approx(bruto)
    assert op["custo"] == pytest.approx((0.5 + 0.25) * 1 * 2)
    assert op["liquido"] == pytest.approx(bruto - 1.5)


def test_toque_no_alvo_da_compra_fecha_no_alvo():
    op0 = _aberta()
    alvo = op0["alvo_px"]
    op = _aberta(toque=(alvo + 10, 188_950))
    assert not op["aberta"] and op["reason"] == K.EXIT_TARGET
    assert op["exit_px"] == alvo - 5


def test_stop_tem_prioridade_quando_stop_e_alvo_tocam_no_mesmo_minuto():
    op0 = _aberta()
    op = _aberta(toque=(op0["alvo_px"] + 10, op0["stop_px"] - 10))
    assert op["reason"] == K.EXIT_STOP


def test_gap_na_abertura_sai_na_abertura():
    # abertura já abaixo do stop: a própria provisória (O=H=L=C) já sai ali
    op0 = _aberta()
    abertura = op0["stop_px"] - 30
    op = _aberta(toque=(abertura, abertura), abertura=abertura)
    assert not op["aberta"] and op["reason"] == K.EXIT_STOP
    assert op["exit_px"] == abertura - 5


def test_toque_na_venda_no_stop_e_no_alvo():
    op0 = _aberta(mod=_mod_venda())
    assert op0["side"] == -1
    op = _aberta(mod=_mod_venda(), toque=(op0["stop_px"] + 10, 188_950))
    assert not op["aberta"] and op["reason"] == K.EXIT_STOP
    assert op["exit_px"] == op0["stop_px"] + 5          # venda sai mais alto
    op = _aberta(mod=_mod_venda(), toque=(189_050, op0["alvo_px"] - 10))
    assert not op["aberta"] and op["reason"] == K.EXIT_TARGET
    assert op["exit_px"] == op0["alvo_px"] + 5


CONTRATOS_PLANO = 1


# equivalência: o toque na provisória dá a MESMA operação que o candle real
# fechado com a mesma máxima/mínima
@pytest.mark.parametrize("venda", [False, True])
@pytest.mark.parametrize("bate_alvo", [False, True])
def test_toque_no_minuto_igual_ao_candle_fechado(venda, bate_alvo):
    mod = _mod_venda() if venda else _mod()
    op0 = _aberta(mod=mod)
    nivel = op0["alvo_px"] if bate_alvo else op0["stop_px"]
    if (not venda) == bate_alvo:                         # toca a máxima
        maxima, minima = nivel + 10, 188_950
    else:                                                # toca a mínima
        maxima, minima = 189_050, nivel - 10
    toque = _aberta(mod=mod, toque=(maxima, minima))
    real = _barras(PROV)
    real["high"][-1], real["low"][-1] = maxima, minima
    fechado = papel.calcular(real, DIA, PLANO, mod, INST)[0]
    assert not toque["aberta"] and not fechado["aberta"]
    for campo in ("exit_ts", "exit_px", "reason", "points", "mae", "mfe"):
        assert toque[campo] == fechado[campo], campo
    assert toque["liquido"] == pytest.approx(fechado["liquido"])
