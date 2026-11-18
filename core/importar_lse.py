"""Bar conversion used by the sibling project prop_live (human UTC bars -> stored format).

The LSE data feed was discarded; only `preparar` remains because prop_live imports it as
`core.importar_lse.preparar` (see prop_live `platform_modules.py`) and the contract test
`tests/test_superficie_prop_live.py` pins it. Renaming or moving this module (e.g. to a
`bar_conversion` module) must be coordinated with prop_live, or its bridge breaks.
"""
from __future__ import annotations

import polars as pl

from core import ativo
from core.ativo import Ficha


def preparar(df: pl.DataFrame, f: Ficha) -> pl.DataFrame:
    """Formato da base: preco inteiro em unidades guardadas, ts em relogio de pregao."""
    volume = df["volume"].cast(pl.Float64)
    if volume.is_null().any() or (volume % 1 != 0).any():
        raise ValueError("volume com valores nao inteiros ou nulos.")
    # Arredondar ao tick antes de escalar: a fonte traz 7665.499999999999.
    precos = [(pl.col(c) / f.tick_size).round(0).cast(pl.Int64) * f.tick_unid
              for c in ("open", "high", "low", "close")]
    return df.select(
        ativo.utc_para_pregao(pl.col("time"), f).alias("ts"),
        *[p.alias(c) for p, c in zip(precos, ("open", "high", "low", "close"))],
        pl.col("trades").cast(pl.Int64).alias("tick_volume"),
        pl.col("volume").cast(pl.Int64),
        pl.lit(None, dtype=pl.Int32).alias("spread"),
    ).sort("ts")
