"""Telas de trades: MES/MNQ em hora de NY e pontos; WIN identico ao de sempre."""
from types import SimpleNamespace

import numpy as np

from core import ativo, analytics
from core.engine import kernel as K
from core.engine.execution import ExecutionProfile
from ui import callbacks
from ui.components import charts, results_grid
from ui.data import to_epoch

MES = ativo.ficha_de({"symbol": "MES", "currency": "USD", "timezone": "America/New_York",
                      "price_decimals": 2, "tick_size": 0.25, "point_value": 5.0,
                      "tick_value": 1.25, "sessao_abertura": "18:00",
                      "abertura_referencia": "09:30"})
WIN = ativo.ficha_de({"symbol": "WIN$N", "currency": "BRL", "timezone": "America/Sao_Paulo",
                      "price_decimals": 0, "tick_size": 5, "point_value": 0.20,
                      "tick_value": 1.0})


def _trades(entry_ts, saida_ts, px, pontos, mae, mfe):
    return {
        "entry_i": np.array([0]), "exit_i": np.array([1]),
        "side": np.array([1]),
        "entry_px": np.array([px], dtype=np.int64),
        "exit_px": np.array([px + pontos], dtype=np.int64),
        "reason": np.array([K.EXIT_TARGET]),
        "mae": np.array([mae], dtype=np.int64), "mfe": np.array([mfe], dtype=np.int64),
        "points": np.array([pontos], dtype=np.int64),
        "bars_held": np.array([5]),
        "entry_ts": np.array([entry_ts], dtype="datetime64[ns]"),
        "exit_ts": np.array([saida_ts], dtype="datetime64[ns]"),
    }


def _res(trades, sl, tp, instr, perfil=None):
    return SimpleNamespace(trades=trades, sl_at_entry=np.array([sl], dtype=np.int64),
                           tp_at_entry=np.array([tp], dtype=np.int64),
                           profile=perfil or ExecutionProfile(), instrument=instr)


T_MES = _trades("2024-06-17T15:30", "2024-06-17T15:45", 543225, 125, 40, 200)
R_MES = _res(T_MES, 1000, 2000, {"tick_size": 25, "_unidade": "guardada"})
DIN = {"liquido": np.array([6.25]), "contratos": np.array([1])}
T_WIN = _trades("2024-06-17T09:30", "2024-06-17T09:45", 130000, 125, 40, 200)
R_WIN = _res(T_WIN, 300, 600, {"tick_size": 5, "point_value": 0.2})


def test_rows_mes_em_hora_de_ny_e_pontos():
    r = results_grid.rows(T_MES, DIN, MES)[0]
    assert r["entrada"] == "17/06/2024  09:30" and r["saida"] == "17/06/2024  09:45"
    assert r["preco_ent"] == 5432.25 and r["preco_sai"] == 5433.5
    assert r["pontos"] == 1.25 and r["mae"] == 0.4 and r["mfe"] == 2.0
    assert r["t_ent"] == "2024-06-17T15:30" and r["t_sai"] == "2024-06-17T15:45"
    assert r["dec"] == 2


def test_rows_win_identico_sem_ficha():
    assert results_grid.rows(T_WIN, DIN, WIN) == results_grid.rows(T_WIN, DIN)
    r = results_grid.rows(T_WIN, DIN, WIN)[0]
    assert "dec" not in r and type(r["preco_ent"]) is int and type(r["pontos"]) is int


def test_trade_markers_mes():
    m = charts.trade_markers(T_MES, 0, 10**10, f=MES)
    assert m[0]["time"] == to_epoch(np.datetime64("2024-06-17T09:30"))
    assert m[1]["text"] == "+1.25"


def test_trade_markers_win_identico():
    assert charts.trade_markers(T_WIN, 0, 10**10, f=WIN) == charts.trade_markers(T_WIN, 0, 10**10)


def test_trade_price_lines_mes():
    l = {x["title"]: x["price"] for x in charts.trade_price_lines(R_MES, 0, MES)}
    assert l["entrada"] == 5432.25 and l["stop"] == 5422.25 and l["alvo"] == 5452.25


def test_trade_price_lines_win_identico():
    assert charts.trade_price_lines(R_WIN, 0, WIN) == charts.trade_price_lines(R_WIN, 0)


def test_por_hora_mes_rotulo_de_ny():
    ts = np.array(["2024-06-17T15:30"], dtype="datetime64[s]")
    d = analytics.por_hora(ts, np.array([1.0]), MES)
    assert "09h" in str(d)
    assert str(analytics.por_hora(ts, np.array([1.0]), WIN)) == str(analytics.por_hora(ts, np.array([1.0])))


def test_referencias_operadas_em_pontos_humanos():
    assert callbacks._referencias_operadas(R_MES, ExecutionProfile(), MES) == (10.0, 20.0)
    assert callbacks._referencias_operadas(R_WIN, ExecutionProfile(), WIN) == (300, 600)
    assert callbacks._referencias_operadas(R_WIN, ExecutionProfile()) == (300, 600)


def test_referencias_sem_trades_usam_perfil_humano():
    vazio = _res(_trades("2024-06-17T15:30", "2024-06-17T15:45", 1, 1, 1, 1), 1, 1, {})
    vazio.sl_at_entry = vazio.sl_at_entry[:0]
    vazio.tp_at_entry = vazio.tp_at_entry[:0]
    p = ExecutionProfile(stop_pontos=12, alvo_pontos=30)
    assert callbacks._referencias_operadas(vazio, p, MES) == (12, 30)


def test_detalhes_mes_nao_zera_a_folga(monkeypatch):
    vistos = {}
    monkeypatch.setattr(callbacks.DC, "render", lambda *a: vistos.setdefault("a", a))
    n = 25
    t = {k: np.repeat(v, n) for k, v in T_MES.items()}
    t["reason"] = np.repeat(K.EXIT_STOP, n)
    t["points"] = np.repeat(-1005, n)       # perdeu 10.05 com stop de 10.00
    res = _res(t, 1000, 2000, {"tick_size": 25, "_unidade": "guardada"},
               ExecutionProfile(slippage_ticks=1))
    res.sl_at_entry = np.repeat(1000, n)
    res.tp_at_entry = np.repeat(2000, n)
    res.n_bars = 100
    run = {"profile": ExecutionProfile(slippage_ticks=1), "metrics": {"trades": n}, "pregoes": 5}
    callbacks._detalhes(res, run, np.repeat(-50.0, n), MES)
    risco = vistos["a"][3]
    # limite = 10.00 + 0.25 de folga: -10.05 nao e stop furado (com folga 0 seria)
    assert risco["stops_furados"] == 0
