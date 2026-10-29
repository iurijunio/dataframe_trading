"""Leitura dos arquivos do London Strategic Edge (futuros CME, 1 minuto).

Os Parquet vem do download do site, em partes (o limite e de 2,5 M linhas por
download, entao o historico inteiro de um ativo chega em 2 ou mais arquivos que
as vezes se sobrepoem). Colunas: `time` (UTC, inicio do minuto), open, high,
low, close, volume e trades. Aqui o arquivo vira o formato da base
(`core/ingest.validar`) e os pregoes com falha da fonte sao apontados.

Pregao suspeito = o que, no relogio de pregao, tem um vazio de mais de 60 min
entre barras, comeca mais de 60 min depois da abertura, termina antes das
16:59 NY ou nem existe (dia util sem nenhuma barra, fora os feriados de
fechamento total). O limite do comeco e estrito: comecar no minuto 60 nao e
suspeito (o recorte de teste comeca ali). Fim cedo nao conta quando a ultima
barra cai entre 12:59 e 13:15 NY: sao os fechamentos antecipados oficiais da
CME (13:00 e 13:15). O ultimo pregao do arquivo fica de fora, porque o
download pode ter cortado no meio dele (veja `pregao_incompleto`).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from core import ativo
from core import calendar as cal
from core import db_manager as db
from core import ingest as ing
from core import rollovers as roll
from core.ativo import Ficha

_COLUNAS = ["time", "open", "high", "low", "close", "volume", "trades"]
_COMPARAR = ["open", "high", "low", "close", "volume"]
_FIM_DO_PREGAO = 22 * 60 + 59  # 16:59 NY no relogio de pregao
_FIM_CHEIO = "16:59"
_FECHAMENTO_ANTECIPADO = ("12:59", "13:15")  # ultima barra: 13:15 NY (fecha 13:00 ou 13:15)
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


def _pascoa(ano: int) -> date:
    """Algoritmo gregoriano anonimo (Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_de_fechamento_total(ano: int) -> set[date]:
    """Dias uteis em que a CME nao abre: Ano Novo, Sexta-feira Santa e Natal.

    Natal em sabado fecha na sexta anterior; Natal e Ano Novo em domingo, na
    segunda seguinte. Ano Novo em sabado nao desloca nada (a CME abre em 31/12). Os outros feriados dos EUA tem pregao curto (ou normal),
    entao o pregao existe e nao entra aqui.
    """
    def domingo_vira_segunda(d: date) -> date:
        return d + timedelta(days=1) if d.weekday() == 6 else d
    natal = domingo_vira_segunda(date(ano, 12, 25))
    if natal.weekday() == 5:
        natal -= timedelta(days=1)
    return {domingo_vira_segunda(date(ano, 1, 1)), _pascoa(ano) - timedelta(days=2), natal}


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

    desl = f.deslocamento_min
    fim_cheio = ativo.hora_para_minuto(_FIM_CHEIO) + desl
    cedo_ok = (ativo.hora_para_minuto(_FECHAMENTO_ANTECIPADO[0]) + desl,
               ativo.hora_para_minuto(_FECHAMENTO_ANTECIPADO[1]) + desl)
    out: dict[str, str] = {}
    for r in por_dia.iter_rows(named=True):
        motivos = []
        if r["maior_salto"] is not None and r["maior_salto"] > _LIMITE_VAZIO_MIN:
            inicio = r["fim_do_salto"] - timedelta(minutes=r["maior_salto"] - 1)
            motivos.append(f"vazio de {r['maior_salto'] - 1} min a partir de {_hhmm_ny(inicio, f)} NY")
        if r["min_ini"] > _LIMITE_VAZIO_MIN:
            motivos.append(f"comecou as {_hhmm_ny(r['primeira'], f)} NY")
        if r["min_fim"] < fim_cheio and not cedo_ok[0] <= r["min_fim"] <= cedo_ok[1]:
            motivos.append(f"terminou as {_hhmm_ny(r['ultima'], f)} NY")
        if motivos:
            out[str(r["dia"])] = "; ".join(motivos)

    # Pregao que nao tem nenhuma barra nao aparece no group_by acima.
    presentes = set(d["dia"].unique().to_list())
    dia = d["dia"].min()
    while (dia := dia + timedelta(days=1)) < ultimo:
        if (dia.weekday() < 5 and dia not in presentes
                and dia not in feriados_de_fechamento_total(dia.year)):
            out[str(dia)] = "pregao inteiro ausente"
    return dict(sorted(out.items()))


def pregao_incompleto(df: pl.DataFrame) -> str | None:
    """Data do ultimo pregao se a ultima barra for antes das 22:59 (16:59 NY)."""
    if df.height == 0:
        return None
    ultima = df["ts"].max()
    if ultima.hour * 60 + ultima.minute < _FIM_DO_PREGAO:
        return str(ultima.date())
    return None


class SuspeitoNovo(Exception):
    """Pregao suspeito que a ficha ainda nao decidiu (descartar ou manter)."""

    def __init__(self, pregoes: dict[str, str]):
        self.pregoes = pregoes
        super().__init__(f"{len(pregoes)} pregoes suspeitos sem decisao na ficha: "
                         + ", ".join(pregoes))


@dataclass
class ResultadoLSE:
    ingest: ing.IngestResult
    descartados: dict[str, str]
    incompleto: str | None


def _ficha(symbol: str) -> Ficha:
    return ativo.ficha(symbol)


def importar(con, symbol: str, paths: list[Path]) -> ResultadoLSE:
    """Importa os arquivos do LSE para a base. Para antes de gravar se houver
    pregao suspeito que a ficha nao descartou nem manteve."""
    f = _ficha(symbol)
    paths = sorted((Path(p) for p in paths), key=lambda p: p.name)
    df = preparar(ler_partes(paths), f)

    suspeitos = pregoes_suspeitos(df, f)
    novos = {d: m for d, m in suspeitos.items()
             if d not in f.pregoes_descartados and d not in f.pregoes_mantidos}
    if novos:
        raise SuspeitoNovo(novos)

    incompleto = pregao_incompleto(df)
    fora = set(f.pregoes_descartados)
    if incompleto:
        fora.add(incompleto)
    # Descartado que nao esta nos dados (pregao ausente) nao remove nada,
    # mas continua contando como descartado.
    df = df.filter(~pl.col("ts").dt.strftime("%Y-%m-%d").is_in(list(fora)))
    descartados = dict(f.pregoes_descartados)

    sha = hashlib.sha256("".join(ing.sha256_of(p) for p in paths).encode()).hexdigest()
    origem = "lse:" + ";".join(p.name for p in paths)
    res = ing.ingest_df(con, df, symbol, origem, sha, price_decimals=0)
    con.execute("UPDATE ingest_log SET observacao = ? WHERE ingest_id = ?",
                [json.dumps({"descartados": descartados, "incompleto": incompleto},
                            ensure_ascii=False), res.ingest_id])

    cal.rebuild_trading_days(con, symbol)
    roll.rebuild_rollovers(con, symbol, "none")
    db.export_parquet(con, symbol)
    return ResultadoLSE(res, descartados, incompleto)
