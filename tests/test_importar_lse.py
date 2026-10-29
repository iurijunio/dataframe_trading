from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from core import ativo, importar_lse as lse

D = Path(__file__).parent / "dados" / "lse"
MES = ativo.ficha("MES")


def test_partes_sobrepostas_identicas_emendam():
    df = lse.ler_partes([D / "mnq_parte_a.parquet", D / "mnq_parte_b.parquet"])
    assert df["time"].is_unique().all() and df["time"].is_sorted()
    # a sobreposicao existe de verdade: sem a emenda haveria linhas repetidas
    soma = pl.read_parquet(D / "mnq_parte_a.parquet").height + pl.read_parquet(D / "mnq_parte_b.parquet").height
    assert df.height < soma


def test_sobreposicao_divergente_para(tmp_path):
    b = pl.read_parquet(D / "mnq_parte_b.parquet")
    b = b.with_columns(pl.when(pl.int_range(pl.len()) == 0).then(pl.col("close") + 0.25)
                       .otherwise(pl.col("close")).alias("close"))
    b.write_parquet(tmp_path / "b.parquet")
    with pytest.raises(ValueError, match="diverg"):
        lse.ler_partes([D / "mnq_parte_a.parquet", tmp_path / "b.parquet"])


def test_coluna_faltando_cita_o_arquivo(tmp_path):
    pl.read_parquet(D / "mnq_parte_a.parquet").drop("trades").write_parquet(tmp_path / "x.parquet")
    with pytest.raises(ValueError, match="x.parquet"):
        lse.ler_partes([tmp_path / "x.parquet"])


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
    df = pl.DataFrame({"time": [t], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                       "volume": [78.5], "trades": [40]},
                      schema_overrides={"time": pl.Datetime("us", "UTC")})
    with pytest.raises(ValueError, match="volume"):
        lse.preparar(df, MES)


def test_preparar_passa_pela_validacao_da_base():
    from core.ingest import validar
    df = lse.preparar(lse.ler_partes([D / "mes_2024_12.parquet"]), MES)
    validar(df, "teste", price_decimals=MES.price_decimals)


def test_buraco_de_marco_2020_e_suspeito():
    s = lse.pregoes_suspeitos(lse.preparar(lse.ler_partes([D / "mes_2020_03.parquet"]), MES), MES)
    assert {"2020-03-02", "2020-03-03"} <= set(s)
    assert "2020-02-28" not in s and "2020-03-04" not in s
    assert "NY" in s["2020-03-02"] and "NY" in s["2020-03-03"]


def test_vespera_de_natal_nao_e_suspeita():
    s = lse.pregoes_suspeitos(lse.preparar(lse.ler_partes([D / "mes_2024_12.parquet"]), MES), MES)
    assert "2024-12-24" not in s and "2024-12-26" not in s
    assert "2024-12-23" not in s  # comeca no minuto 60: limite estrito


def test_vazio_dentro_do_pregao_e_suspeito():
    df = lse.preparar(lse.ler_partes([D / "mes_2024_12.parquet"]), MES)
    # abre um buraco de ~5 h no pregao de 26/12, no meio do dia
    ts = pl.col("ts")
    furo = df.filter(~((ts >= pl.datetime(2024, 12, 26, 12, 0)) & (ts < pl.datetime(2024, 12, 26, 17, 0))))
    s = lse.pregoes_suspeitos(furo, MES)
    assert "2024-12-26" in s and "vazio" in s["2024-12-26"]


def test_ultimo_pregao_incompleto():
    df = lse.preparar(lse.ler_partes([D / "mnq_parte_a.parquet"]), MES)  # termina 20/09 16:59 NY
    assert lse.pregao_incompleto(df) is None
    assert lse.pregao_incompleto(df.filter(pl.col("ts").dt.hour() < 20)) == str(df["ts"].dt.date().max())
