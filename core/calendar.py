"""trading_days - o calendario de pregoes, derivado das proprias barras.

Nao existe lista de feriados escrita a mao aqui, e isso e proposital: o que
vale e o que o mercado efetivamente negociou. O historico atual tem tres
padroes de horario (fecha 17:54 em 486 pregoes, 18:24 em 754, e 5 quartas
de carnaval abrindo as 13:00), e nenhum deles precisa ser conhecido de
antemao para esta tabela sair certa.
"""

from __future__ import annotations

# Um pregao com menos que esta fracao da mediana de barras do simbolo e
# tratado como parcial (na pratica: as quartas de carnaval, com 325 barras
# contra a mediana de 535).
PARTIAL_RATIO = 0.7


def rebuild_trading_days(con, symbol: str) -> int:
    con.execute("DELETE FROM trading_days WHERE symbol = ?", [symbol])
    con.execute(
        """
        INSERT INTO trading_days
        WITH d AS (
            SELECT symbol,
                   CAST(ts AS DATE) AS date,
                   min(ts)          AS first_ts,
                   max(ts)          AS last_ts,
                   count(*)         AS bar_count
            FROM bars_m1
            WHERE symbol = ?
            GROUP BY 1, 2
        ),
        med AS (SELECT median(bar_count) AS mc FROM d)
        SELECT d.symbol, d.date, d.first_ts, d.last_ts, d.bar_count,
               d.bar_count < ? * (SELECT mc FROM med)
        FROM d
        ORDER BY d.date
        """,
        [symbol, PARTIAL_RATIO],
    )
    return con.execute(
        "SELECT count(*) FROM trading_days WHERE symbol = ?", [symbol]
    ).fetchone()[0]


def session_shape(con, symbol: str) -> list[tuple]:
    """Quantos pregoes abrem/fecham em cada horario. E o que dispensa
    calendario dinamico no motor: se nenhum pregao fecha antes das 17:30,
    encerrar as 17:30 e seguro por construcao."""
    return con.execute(
        """
        SELECT CAST(first_ts AS TIME) AS abertura,
               CAST(last_ts  AS TIME) AS fechamento,
               count(*) AS pregoes
        FROM trading_days
        WHERE symbol = ?
        GROUP BY 1, 2
        ORDER BY pregoes DESC
        """,
        [symbol],
    ).fetchall()


def earliest_close(con, symbol: str):
    return con.execute(
        "SELECT min(CAST(last_ts AS TIME)) FROM trading_days WHERE symbol = ?",
        [symbol],
    ).fetchone()[0]
