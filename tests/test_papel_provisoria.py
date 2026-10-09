"""Barra provisória: a entrada aparece no primeiro segundo do minuto, igual
ao que o candle real daria (spec §3)."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np

from core import papel
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
