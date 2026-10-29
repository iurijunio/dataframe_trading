from datetime import datetime

import polars as pl

from core import db_manager as db, ingest
from ui import data as D


def _barra(con, symbol, ts, preco):
    df = pl.DataFrame({"ts": [ts], "open": [preco], "high": [preco], "low": [preco], "close": [preco],
                       "tick_volume": [1], "volume": [1], "spread": [None]},
                      schema_overrides={"spread": pl.Int32})
    ingest.ingest_df(con, df, symbol, "teste", f"sha-{symbol}")


def test_mes_sai_em_hora_de_ny_e_pontos():
    with db.connect() as con:
        db.init_schema(con); db.sync_instruments(con)
        _barra(con, "MES", datetime(2024, 6, 17, 15, 30), 543225)
    out = D.candles("MES", datetime(2024, 6, 17), datetime(2024, 6, 17, 23, 59), "M1")
    c = out["candles"][0]
    assert c["time"] == D.to_epoch(datetime(2024, 6, 17, 9, 30)) and c["open"] == 5432.25
    assert out["volume"][0]["time"] == c["time"]


def test_win_igual_a_hoje():
    with db.connect() as con:
        db.init_schema(con); db.sync_instruments(con)
        _barra(con, "WIN$N", datetime(2024, 6, 17, 9, 0), 130005)
    c = D.candles("WIN$N", datetime(2024, 6, 17), datetime(2024, 6, 17, 23, 59), "M1")["candles"][0]
    assert c["time"] == D.to_epoch(datetime(2024, 6, 17, 9, 0)) and c["open"] == 130005
    assert isinstance(c["open"], int)
