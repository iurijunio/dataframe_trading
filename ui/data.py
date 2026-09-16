"""Acesso a dados para a interface.

Duas regras aqui:

1. Nunca mandar 688 mil candles para o navegador. A janela visivel e
   agregada no DuckDB para o timeframe adequado e limitada a MAX_CANDLES.

2. As barras completas ficam em cache no processo. Um backtest custa ~50 ms,
   mas carregar 688 mil barras do banco custa ~90 ms - recarregar a cada
   clique seria o gargalo da interface, nao o motor.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from core import db_manager as db
from core.engine.execution import prepare_bars

MAX_CANDLES = 4000

TIMEFRAMES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": None,
}

_bars_cache: dict[str, dict] = {}
_meta_cache: dict[str, dict] = {}


def bars(symbol: str) -> dict:
    if symbol not in _bars_cache:
        with db.connect(read_only=True) as con:
            _bars_cache[symbol] = prepare_bars(con, symbol)
    return _bars_cache[symbol]


def instrumentos() -> list[dict]:
    """Os instrumentos que TÊM barras, do mais populoso para o menos.

    A plataforma nasceu no mini índice, mas nunca foi só dele: o símbolo
    saiu do código e passou a vir daqui, para que acrescentar um ativo seja
    ingerir um CSV e não editar Python.
    """
    with db.connect(read_only=True) as con:
        linhas = con.execute("""
            SELECT i.symbol, i.description, count(b.ts) AS n
            FROM instruments i JOIN bars_m1 b USING (symbol)
            GROUP BY i.symbol, i.description
            ORDER BY n DESC
        """).fetchall()
    return [{"symbol": s, "descricao": d, "barras": int(n)} for s, d, n in linhas]


def instrument(symbol: str) -> dict:
    if symbol not in _meta_cache:
        _meta_cache[symbol] = db.load_instrument_yaml(symbol)
    return _meta_cache[symbol]


def span(symbol: str) -> tuple[datetime, datetime]:
    ts = bars(symbol)["ts"]
    return ts[0].astype("datetime64[s]").item(), ts[-1].astype("datetime64[s]").item()


def to_epoch(ts) -> int:
    """Timestamps sao horario de Brasilia sem fuso. A biblioteca de grafico
    interpreta o numero como UTC, entao mandamos o horario de parede como se
    fosse UTC - assim o eixo mostra 09:00 quando o pregao abriu 09:00."""
    return int(np.datetime64(ts, "s").astype("int64"))


def auto_timeframe(inicio: datetime, fim: datetime) -> str:
    """Maior resolucao que cabe em MAX_CANDLES para a janela pedida."""
    minutos = max(1, int((fim - inicio).total_seconds() // 60))
    for nome, passo in TIMEFRAMES.items():
        if passo is None:
            return nome
        if minutos / passo <= MAX_CANDLES:
            return nome
    return "D1"


def candles(symbol: str, inicio: datetime, fim: datetime, tf: str = "auto") -> dict:
    """Candles agregados para a janela visivel."""
    if tf == "auto":
        tf = auto_timeframe(inicio, fim)
    passo = TIMEFRAMES[tf]

    if passo is None:
        bucket = "CAST(ts AS DATE)"
    else:
        bucket = f"time_bucket(INTERVAL '{passo} minutes', ts)"

    with db.connect(read_only=True) as con:
        rows = con.execute(
            f"""
            SELECT {bucket} AS t,
                   first(open  ORDER BY ts) AS o,
                   max(high)                AS h,
                   min(low)                 AS l,
                   last(close ORDER BY ts)  AS c,
                   sum(tick_volume)         AS v
            FROM bars_m1
            WHERE symbol = ? AND ts >= ? AND ts <= ?
            GROUP BY 1 ORDER BY 1
            LIMIT {MAX_CANDLES}
            """,
            [symbol, inicio, fim],
        ).fetchall()

    return {
        "timeframe": tf,
        "candles": [
            {"time": to_epoch(r[0]), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4]}
            for r in rows
        ],
        "volume": [
            {"time": to_epoch(r[0]), "value": int(r[5]),
             "color": "rgba(72,190,146,.35)" if r[4] >= r[1] else "rgba(229,128,110,.35)"}
            for r in rows
        ],
    }


def default_window(symbol: str, dias: int = 5) -> tuple[datetime, datetime]:
    _, fim = span(symbol)
    return fim - timedelta(days=dias), fim
