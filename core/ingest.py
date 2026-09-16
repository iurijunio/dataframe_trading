"""Ingestao de exportacoes M1 do MT5 - por MERGE, nunca por carga.

O terminal do MT5 serve no maximo ~5 anos de M1 do mini indice. A planilha
exportada hoje comeca em marco/2021; a de amanha ja nao tem 16/03/2021.
Consumir a planilha direto significa operar para sempre numa janela
deslizante. Somando cada exportacao a anterior, a base vira um arquivo que
ganha um pregao por dia e nunca perde a ponta antiga.

Isso poe duas exigencias neste modulo:

1. Exportacoes sucessivas se sobrepoem em ANOS inteiros. Deduplicar por
   (symbol, ts) e o facil.

2. O dificil e o conflito: mesmo timestamp, OHLC diferente. O MT5 revisa
   historico. Se a regra fosse "ignora o que ja existe", a base guardaria a
   versao velha para sempre e ninguem ficaria sabendo. A regra aqui e:
   a exportacao mais recente vence, e toda divergencia e contada e
   registrada em ingest_log.

"Mais recente" e a exportacao com a barra mais nova (source_max_ts), com
desempate pelo sha256 - nao e a ultima a ser importada. Por isso importar
A e depois B da exatamente a mesma tabela que importar B e depois A.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import polars as pl

MT5_COLUMNS = {
    "<DATE>": "date_str",
    "<TIME>": "time_str",
    "<OPEN>": "open",
    "<HIGH>": "high",
    "<LOW>": "low",
    "<CLOSE>": "close",
    "<TICKVOL>": "tick_volume",
    "<VOL>": "volume",
    "<SPREAD>": "spread",
}

PRICE_COLS = ("open", "high", "low", "close")

_CONTENT_COLS = (*PRICE_COLS, "tick_volume", "volume", "spread")


def _differs(base: str = "b", stage: str = "s") -> str:
    """Predicado 'estas duas versoes da mesma barra divergem'."""
    return " OR ".join(
        f"{base}.{c} IS DISTINCT FROM {stage}.{c}" for c in _CONTENT_COLS
    )


_DIFFERS = _differs()


@dataclass
class IngestResult:
    ingest_id: int
    symbol: str
    source_file: str
    rows_in_file: int
    rows_inserted: int
    rows_updated: int
    rows_rejected: int
    rows_identical: int
    ts_from: datetime
    ts_to: datetime
    conflicts: list[dict]

    def summary(self) -> str:
        return (
            f"[{self.symbol}] {Path(self.source_file).name}\n"
            f"  periodo do arquivo : {self.ts_from} -> {self.ts_to}\n"
            f"  linhas no arquivo  : {self.rows_in_file:,}\n"
            f"  inseridas          : {self.rows_inserted:,}\n"
            f"  ja identicas       : {self.rows_identical:,}\n"
            f"  divergentes/venceu : {self.rows_updated:,}\n"
            f"  divergentes/perdeu : {self.rows_rejected:,}"
        ).replace(",", ".")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_mt5_export(path: Path, price_decimals: int = 0) -> pl.DataFrame:
    """Le o TSV do MT5 e devolve um DataFrame validado.

    Levanta erro em vez de adivinhar: coluna faltando, timestamp duplicado
    dentro do proprio arquivo ou preco nao inteiro num instrumento que
    deveria ter preco inteiro sao todos motivo de parar.
    """
    df = pl.read_csv(path, separator="\t", has_header=True)

    faltando = [c for c in MT5_COLUMNS if c not in df.columns]
    if faltando:
        raise ValueError(
            f"{path.name}: colunas ausentes {faltando}. "
            f"Encontradas: {df.columns}. "
            "Exporte do MT5 em M1 com o layout padrao (separador TAB)."
        )

    df = df.select(list(MT5_COLUMNS)).rename(MT5_COLUMNS)

    df = df.with_columns(
        pl.concat_str([pl.col("date_str"), pl.col("time_str")], separator=" ")
        .str.to_datetime(format="%Y.%m.%d %H:%M:%S")
        .alias("ts")
    ).drop("date_str", "time_str")

    if df.height == 0:
        raise ValueError(f"{path.name}: arquivo sem linhas de dados.")

    dups = df.height - df.select("ts").n_unique()
    if dups:
        raise ValueError(f"{path.name}: {dups} timestamps duplicados dentro do arquivo.")

    if price_decimals == 0:
        for col in PRICE_COLS:
            nao_inteiros = df.filter(
                pl.col(col).cast(pl.Float64) % 1 != 0
            ).height
            if nao_inteiros:
                raise ValueError(
                    f"{path.name}: coluna {col} tem {nao_inteiros} valores nao "
                    "inteiros, mas o instrumento declara price_decimals: 0."
                )
        df = df.with_columns([pl.col(c).cast(pl.Int64) for c in PRICE_COLS])

    invalidas = df.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
    ).height
    if invalidas:
        raise ValueError(f"{path.name}: {invalidas} barras com OHLC incoerente.")

    return df.select(
        "ts", "open", "high", "low", "close", "tick_volume", "volume", "spread"
    ).sort("ts")


def ingest_csv(con, path: Path | str, symbol: str, price_decimals: int = 0) -> IngestResult:
    """Importa uma exportacao. Tudo ou nada.

    A carga roda dentro de uma transacao porque o registro em ingest_log e
    escrito ANTES do merge (o merge precisa do ingest_id para marcar a
    proveniencia das barras). Sem transacao, uma falha no meio deixaria um
    registro de carga que nunca aconteceu - e, pior, barras apontando para
    uma proveniencia parcial.
    """
    path = Path(path)
    df = read_mt5_export(path, price_decimals=price_decimals)  # noqa: F841  (lido pelo DuckDB)

    con.execute("BEGIN TRANSACTION")
    try:
        result = _merge(con, path, symbol, df)
    except Exception:
        con.execute("ROLLBACK")
        con.execute("DROP TABLE IF EXISTS _stage")
        raise
    con.execute("COMMIT")
    return result


def _merge(con, path: Path, symbol: str, df) -> IngestResult:
    src_min = df["ts"].min()
    src_max = df["ts"].max()
    sha = sha256_of(path)

    ingest_id = con.execute("SELECT nextval('seq_ingest_id')").fetchone()[0]
    con.execute(
        """
        INSERT INTO ingest_log
            (ingest_id, symbol, source_file, source_sha256,
             source_min_ts, source_max_ts, rows_in_file,
             rows_inserted, rows_updated, rows_rejected, rows_identical,
             conflict_sample, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, NULL, ?)
        """,
        [ingest_id, symbol, str(path), sha, src_min, src_max, df.height, datetime.now()],
    )

    con.execute("DROP TABLE IF EXISTS _stage")
    con.execute(
        """
        CREATE TEMP TABLE _stage AS
        SELECT ? AS symbol, ts, open, high, low, close,
               tick_volume, volume, spread
        FROM df
        """,
        [symbol],
    )

    # "Esta exportacao e mais nova que a que forneceu a barra que ja esta la?"
    # Comparacao por (source_max_ts, sha256) - determinista e independente
    # da ordem de importacao.
    wins = """
        (ol.source_max_ts < ?
         OR (ol.source_max_ts = ? AND ol.source_sha256 < ?))
    """
    wins_args = [src_max, src_max, sha]

    identical = con.execute(
        f"""
        SELECT count(*) FROM _stage s
        JOIN bars_m1 b ON b.symbol = s.symbol AND b.ts = s.ts
        WHERE NOT ({_DIFFERS})
        """
    ).fetchone()[0]

    conflicts_total = con.execute(
        f"""
        SELECT count(*) FROM _stage s
        JOIN bars_m1 b ON b.symbol = s.symbol AND b.ts = s.ts
        WHERE {_DIFFERS}
        """
    ).fetchone()[0]

    conflicts_won = con.execute(
        f"""
        SELECT count(*) FROM _stage s
        JOIN bars_m1 b   ON b.symbol = s.symbol AND b.ts = s.ts
        JOIN ingest_log ol ON ol.ingest_id = b.src_ingest_id
        WHERE ({_DIFFERS}) AND {wins}
        """,
        wins_args,
    ).fetchone()[0]

    sample = con.execute(
        f"""
        SELECT s.ts, b.open, b.high, b.low, b.close,
                     s.open, s.high, s.low, s.close
        FROM _stage s
        JOIN bars_m1 b ON b.symbol = s.symbol AND b.ts = s.ts
        WHERE {_DIFFERS}
        ORDER BY s.ts LIMIT 5
        """
    ).fetchall()
    conflicts = [
        {
            "ts": str(r[0]),
            "na_base": {"o": r[1], "h": r[2], "l": r[3], "c": r[4]},
            "no_arquivo": {"o": r[5], "h": r[6], "l": r[7], "c": r[8]},
        }
        for r in sample
    ]

    # So barras DIVERGENTES em que esta exportacao vence sao removidas, para
    # serem reinseridas logo abaixo. Barras identicas ficam intocadas e
    # mantem a proveniencia original. Rodar o mesmo arquivo duas vezes nao
    # muda nada: nada diverge, nada e novo.
    con.execute(
        f"""
        DELETE FROM bars_m1
        WHERE EXISTS (
            SELECT 1
            FROM _stage s
            JOIN ingest_log ol ON ol.ingest_id = bars_m1.src_ingest_id
            WHERE s.symbol = bars_m1.symbol AND s.ts = bars_m1.ts
              AND ({_differs("bars_m1", "s")})
              AND {wins}
        )
        """,
        wins_args,
    )

    inserted = con.execute(
        """
        INSERT INTO bars_m1
        SELECT s.symbol, s.ts, s.open, s.high, s.low, s.close,
               s.tick_volume, s.volume, s.spread, ?
        FROM _stage s
        LEFT JOIN bars_m1 b ON b.symbol = s.symbol AND b.ts = s.ts
        WHERE b.ts IS NULL
        RETURNING 1
        """,
        [ingest_id],
    ).fetchall()
    rows_inserted = len(inserted) - conflicts_won

    con.execute("DROP TABLE IF EXISTS _stage")
    con.execute(
        """
        UPDATE ingest_log
        SET rows_inserted = ?, rows_updated = ?, rows_rejected = ?,
            rows_identical = ?, conflict_sample = ?
        WHERE ingest_id = ?
        """,
        [
            rows_inserted,
            conflicts_won,
            conflicts_total - conflicts_won,
            identical,
            json.dumps(conflicts, ensure_ascii=False) if conflicts else None,
            ingest_id,
        ],
    )

    return IngestResult(
        ingest_id=ingest_id,
        symbol=symbol,
        source_file=str(path),
        rows_in_file=df.height,
        rows_inserted=rows_inserted,
        rows_updated=conflicts_won,
        rows_rejected=conflicts_total - conflicts_won,
        rows_identical=identical,
        ts_from=src_min,
        ts_to=src_max,
        conflicts=conflicts,
    )
