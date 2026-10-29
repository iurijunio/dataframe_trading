"""O app abre no WIN$N mesmo quando outro ativo tem mais barras."""
from core import db_manager as db
from tests.fabrica_ao_vivo import inserir_barras
import numpy as np

from ui import app


def _barras(n: int) -> dict:
    ts = np.arange(n).astype("timedelta64[m]") + np.datetime64("2026-01-05T09:00")
    v = np.full(n, 100)
    return {"ts": ts, "open": v, "high": v, "low": v, "close": v}


def _semear(simbolos: dict[str, int]) -> None:
    with db.connect() as con:
        db.init_schema(con)
        for s, n in simbolos.items():
            con.execute("INSERT INTO instruments (symbol, description) "
                        "VALUES (?, ?)", [s, s])
            inserir_barras(con, _barras(n), symbol=s)


def test_padrao_e_win_mesmo_com_outro_ativo_mais_populoso():
    _semear({"WIN$N": 5, "MNQ": 20})
    assert app._padrao() == "WIN$N"


def test_padrao_sem_win_usa_o_primeiro():
    _semear({"MES": 5, "MNQ": 20})
    assert app._padrao() == "MNQ"


def test_padrao_sem_instrumentos_e_win():
    with db.connect() as con:
        db.init_schema(con)
    assert app._padrao() == "WIN$N"
