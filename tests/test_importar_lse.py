from datetime import datetime, timezone

import polars as pl
import pytest

from core import ativo, importar_lse as lse

MES = ativo.ficha("MES")


def _bars(times, volume=78.0):
    n = len(times)
    return pl.DataFrame({"time": times, "open": [7665.25] * n, "high": [7665.5] * n,
                         "low": [7665.0] * n, "close": [7665.25] * n,
                         "volume": [volume] * n, "trades": [40] * n},
                        schema_overrides={"time": pl.Datetime("us", "UTC")})


def test_preparar_arredonda_ao_tick_e_escala():
    t = datetime(2026, 9, 15, 20, 59, tzinfo=timezone.utc)
    df = pl.DataFrame({"time": [t], "open": [7665.25], "high": [7665.499999999999],
                       "low": [7664.999999999999], "close": [7665.499999999999],
                       "volume": [78.0], "trades": [40]},
                      schema_overrides={"time": pl.Datetime("us", "UTC")})
    out = lse.preparar(df, MES)
    assert out.row(0, named=True)["high"] == 766550 and out["low"][0] == 766500
    assert out["tick_volume"][0] == 40 and out["volume"][0] == 78
    assert out["spread"].dtype == pl.Int32 and out["spread"][0] is None
    assert out["open"].dtype == pl.Int64


def test_preparar_recusa_volume_fracionario():
    t = datetime(2026, 9, 15, 20, 59, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="volume"):
        lse.preparar(_bars([t], volume=78.5), MES)


def test_preparar_passa_pela_validacao_da_base():
    from core.ingest import validar
    times = [datetime(2024, 12, 17, 14, m, tzinfo=timezone.utc) for m in (0, 1, 2)]
    validar(lse.preparar(_bars(times), MES), "teste", price_decimals=MES.price_decimals)
