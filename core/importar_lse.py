"""Leitura dos arquivos do London Strategic Edge (futuros CME, 1 minuto).

Os Parquet vem do download do site, em partes (o limite e de 2,5 M linhas por
download, entao o historico inteiro de um ativo chega em 2 ou mais arquivos que
as vezes se sobrepoem). Colunas: `time` (UTC, inicio do minuto), open, high,
low, close, volume e trades. Aqui o arquivo vira o formato da base
(`core/ingest.validar`) e os pregoes com falha da fonte sao apontados.

Pregao suspeito = o que, no relogio de pregao, tem um vazio de mais de 60 min
entre barras, comeca mais de 60 min depois da abertura ou termina antes das
12:00 NY. O limite e estrito: comecar no minuto 60 nao e suspeito (o recorte
de teste comeca ali). O ultimo pregao do arquivo fica de fora, porque o
download pode ter cortado no meio dele (veja `pregao_incompleto`). Reduzir o
pregao curto de vespera de feriado a "suspeito" seria erro: ele fecha 13:15
NY, depois das 12:00.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

from core import ativo
from core.ativo import Ficha

_COLUNAS = ["time", "open", "high", "low", "close", "volume", "trades"]
_COMPARAR = ["open", "high", "low", "close", "volume"]
_FIM_DO_PREGAO = 22 * 60 + 59  # 16:59 NY no relogio de pregao
_FIM_CEDO = "12:00"
_LIMITE_VAZIO_MIN = 60


def ler_partes(paths: list[Path]) -> pl.DataFrame:
    """Junta as partes. Sobreposicao so vale se as barras forem identicas."""
    partes = []
    for p in paths:
        df = pl.read_parquet(p)
        faltam = [c for c in _COLUNAS if c not in df.columns]
        if faltam:
            raise ValueError(f"{Path(p).name}: colunas ausentes ({', '.join(faltam)}).")
        partes.append(df.select(_COLUNAS).with_columns(
            pl.col("time").dt.convert_time_zone("UTC").dt.cast_time_unit("us"),
            pl.col("trades").cast(pl.Int64),
        ))
    todo = pl.concat(partes, how="vertical")

    repetidos = todo.filter(pl.col("time").is_duplicated())
    if repetidos.height:
        # n_unique conta nulo como valor, entao nulo x numero tambem diverge.
        div = (repetidos.group_by("time")
               .agg([pl.col(c).n_unique().alias(c) for c in _COMPARAR])
               .filter(pl.any_horizontal([pl.col(c) > 1 for c in _COMPARAR]))
               .sort("time"))
        if div.height:
            # strftime em vez de to_list: datetime com fuso exige tzdata no Windows.
            ex = ", ".join(div["time"].head(5).dt.strftime("%Y-%m-%d %H:%M UTC").to_list())
            raise ValueError(
                f"{div.height} barras da sobreposicao entre as partes diverge (ex.: {ex})."
            )
    return todo.unique(subset="time", keep="first").sort("time")


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


def _hhmm_ny(ts, f: Ficha) -> str:
    return ativo.hora_para_exibir(ts, f).strftime("%H:%M")


def pregoes_suspeitos(df: pl.DataFrame, f: Ficha) -> dict[str, str]:
    """Data do pregao -> motivo (em hora de NY). Ignora o ultimo pregao do df."""
    if df.height == 0:
        return {}
    d = df.select("ts").sort("ts").with_columns(
        pl.col("ts").dt.date().alias("dia"),
        (pl.col("ts").dt.hour().cast(pl.Int32) * 60 + pl.col("ts").dt.minute().cast(pl.Int32)).alias("min"),
    ).with_columns(pl.col("min").diff().over("dia").alias("salto"))
    ultimo = d["dia"].max()
    por_dia = d.group_by("dia").agg(
        pl.col("ts").first().alias("primeira"),
        pl.col("ts").last().alias("ultima"),
        pl.col("min").first().alias("min_ini"),
        pl.col("min").last().alias("min_fim"),
        pl.col("salto").max().alias("maior_salto"),
        pl.col("ts").sort_by(pl.col("salto").fill_null(0)).last().alias("fim_do_salto"),
    ).filter(pl.col("dia") != ultimo).sort("dia")

    limite_fim = ativo.hora_para_minuto(_FIM_CEDO) + f.deslocamento_min
    out: dict[str, str] = {}
    for r in por_dia.iter_rows(named=True):
        if r["maior_salto"] is not None and r["maior_salto"] > _LIMITE_VAZIO_MIN:
            inicio = r["fim_do_salto"] - timedelta(minutes=r["maior_salto"] - 1)
            motivo = f"vazio de {r['maior_salto'] - 1} min a partir de {_hhmm_ny(inicio, f)} NY"
        elif r["min_ini"] > _LIMITE_VAZIO_MIN:
            motivo = f"comecou as {_hhmm_ny(r['primeira'], f)} NY"
        elif r["min_fim"] < limite_fim:
            motivo = f"terminou as {_hhmm_ny(r['ultima'], f)} NY"
        else:
            continue
        out[str(r["dia"])] = motivo
    return out


def pregao_incompleto(df: pl.DataFrame) -> str | None:
    """Data do ultimo pregao se a ultima barra for antes das 22:59 (16:59 NY)."""
    if df.height == 0:
        return None
    ultima = df["ts"].max()
    if ultima.hour * 60 + ultima.minute < _FIM_DO_PREGAO:
        return str(ultima.date())
    return None
