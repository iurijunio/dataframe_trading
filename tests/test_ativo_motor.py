from datetime import datetime

import numpy as np

from core import ativo
from core.engine.execution import ExecutionProfile

WIN_CFG = {"symbol": "WIN$N", "currency": "BRL", "timezone": "America/Sao_Paulo",
           "price_decimals": 0, "tick_size": 5, "point_value": 0.20, "tick_value": 1.0}
MES_CFG = {"symbol": "MES", "currency": "USD", "timezone": "America/New_York",
           "price_decimals": 2, "tick_size": 0.25, "point_value": 5.0, "tick_value": 1.25,
           "sessao_abertura": "18:00", "abertura_referencia": "09:30"}
MES = ativo.ficha_de(MES_CFG)


def test_identidade_do_win():
    f = ativo.ficha_do_instrumento(WIN_CFG)
    assert ativo.instrumento_para_motor(WIN_CFG, f) is WIN_CFG
    p = ExecutionProfile()
    assert ativo.perfil_para_motor(p, f) is p
    params = {"a": 1}
    assert ativo.params_para_motor(params, {"a": {"unidade": "pontos"}}, f) is params
    trades = {"entry_px": np.array([1])}
    assert ativo.trades_para_exibir(trades, f) is trades
    assert ativo.pontos_para_exibir(5, f) == 5


def test_ficha_do_instrumento():
    assert ativo.ficha_do_instrumento({"tick_size": 5, "point_value": 0.2}) is None
    assert ativo.ficha_do_instrumento(MES_CFG) is not None


def test_instrumento_mes():
    conv = ativo.instrumento_para_motor(MES_CFG, MES)
    assert conv is not MES_CFG
    assert conv["tick_size"] == 25 and conv["point_value"] == 0.05
    assert conv["_unidade"] == "guardada"
    assert "_unidade" not in MES_CFG
    assert ativo.ficha_do_instrumento(conv) is None


def test_perfil_mes():
    p = ExecutionProfile(stop_pontos=10, alvo_pontos=20, trailing_pontos=5,
                         entrada_inicio="09:30", entrada_fim="16:00", fechamento="16:50",
                         sem_entrada1="12:00", limite_perda_contrato=50.0,
                         corretagem_por_contrato=1.5)
    q = ativo.perfil_para_motor(p, MES)
    assert (q.stop_pontos, q.alvo_pontos, q.trailing_pontos) == (1000, 2000, 500)
    assert all(isinstance(v, int) for v in (q.stop_pontos, q.alvo_pontos, q.trailing_pontos))
    assert (q.entrada_inicio, q.entrada_fim, q.fechamento) == ("15:30", "22:00", "22:50")
    assert q.sem_entrada1 == "18:00" and q.sem_entrada2 == "" and q.sem_entrada3 == ""
    assert q.limite_perda_contrato == 50.0 and q.corretagem_por_contrato == 1.5
    assert (p.stop_pontos, p.entrada_inicio) == (10, "09:30")


def test_params():
    out = ativo.params_para_motor({"a": 12, "b": 3}, {"a": {"unidade": "pontos"}, "b": {}}, MES)
    assert out == {"a": 1200, "b": 3} and isinstance(out["a"], int)


def test_trades():
    trades = {
        "entry_ts": np.array(["2024-06-17T15:30"], dtype="datetime64[ns]"),
        "exit_ts": np.array(["2024-06-17T16:00"], dtype="datetime64[ns]"),
        "entry_px": np.array([543225]), "exit_px": np.array([543100]),
        "points": np.array([-125]), "mae": np.array([-200]), "mfe": np.array([50]),
        "side": np.array([1]),
    }
    out = ativo.trades_para_exibir(trades, MES)
    assert out["entry_ts"][0] == np.datetime64("2024-06-17T09:30")
    assert out["exit_ts"][0] == np.datetime64("2024-06-17T10:00")
    assert out["entry_px"][0] == 5432.25 and out["points"][0] == -1.25
    assert out["mae"][0] == -2.0 and out["mfe"][0] == 0.5
    assert out["side"] is trades["side"]
    assert trades["entry_px"][0] == 543225


def test_hora_do_pregao():
    assert ativo.hora_do_pregao_para_exibir(15, MES) == 9
    assert ativo.hora_do_pregao_para_exibir(3, MES) == 21
    assert ativo.hora_do_pregao_para_exibir(15, None) == 15


def test_perfil_padrao():
    assert ativo.perfil_padrao(MES) is None
    f = ativo.ficha_de({**MES_CFG, "perfil_padrao": {"stop_pontos": 10}})
    assert ativo.perfil_padrao(f) == {"stop_pontos": 10}
