"""Deteccao das viradas de contrato na serie continua (WIN$N).

O arquivo do MT5 e uma serie emendada: quando o contrato vira, o preco salta
milhares de pontos de um pregao para o outro sem que nada tenha acontecido no
mercado. Para day trade puro isso e inofensivo - nunca se atravessa a noite.
Vira problema real no primeiro instrumento com carrego, e a tabela e barata
de construir agora e cara de descobrir que faltava depois.

A regra da B3 para o WIN e: vencimento na quarta-feira mais proxima do dia 15
dos meses pares. Conferido contra os gaps medidos no historico - as quatro
maiores viradas recentes caem exatamente em 18/02/2026, 15/10/2025,
13/08/2025 e 18/06/2025, todas quartas-feiras pela regra.

A deteccao aqui e por CALENDARIO, nao por tamanho de gap: gap grande tambem
acontece em dia de noticia, e confundir os dois marcaria como rolagem um
movimento que foi real. O gap medido entra como confirmacao.
"""

from __future__ import annotations

from datetime import date, timedelta

EVEN_MONTHS = (2, 4, 6, 8, 10, 12)
WEDNESDAY = 2  # date.weekday(): segunda = 0

# Acima disso, o gap medido no dia da virada confirma a rolagem.
CONFIRM_GAP_POINTS = 500


def wednesday_nearest_15(year: int, month: int) -> date:
    """Quarta-feira mais proxima do dia 15. Nunca ha empate: as quartas
    distam 7 dias, entao as distancias ao dia 15 nunca sao iguais."""
    candidatas = [
        date(year, month, d)
        for d in range(9, 22)
        if date(year, month, d).weekday() == WEDNESDAY
    ]
    return min(candidatas, key=lambda d: abs(d.day - 15))


def expected_rollover_dates(first: date, last: date) -> list[date]:
    out = []
    for year in range(first.year, last.year + 1):
        for month in EVEN_MONTHS:
            d = wednesday_nearest_15(year, month)
            if first <= d <= last:
                out.append(d)
    return sorted(out)


def rebuild_rollovers(con, symbol: str, policy: str = "b3_even_month_wed_nearest_15") -> int:
    con.execute("DELETE FROM rollovers WHERE symbol = ?", [symbol])
    if policy in (None, "none"):
        return 0
    if policy != "b3_even_month_wed_nearest_15":
        raise ValueError(f"rollover_policy desconhecida: {policy!r}")

    span = con.execute(
        "SELECT min(date), max(date) FROM trading_days WHERE symbol = ?", [symbol]
    ).fetchone()
    if not span or span[0] is None:
        return 0

    dias = [
        r[0]
        for r in con.execute(
            "SELECT date FROM trading_days WHERE symbol = ? ORDER BY date", [symbol]
        ).fetchall()
    ]
    dias_set = set(dias)

    # Se a quarta-feira cair em feriado, a virada aparece no proximo pregao.
    alvos = []
    for d in expected_rollover_dates(span[0], span[1]):
        cur = d
        for _ in range(10):
            if cur in dias_set:
                alvos.append(cur)
                break
            cur += timedelta(days=1)
    if not alvos:
        return 0

    con.execute(
        f"""
        INSERT INTO rollovers
        WITH d AS (
            SELECT date, first_ts,
                   lag(date)    OVER (ORDER BY date) AS prev_date,
                   lag(last_ts) OVER (ORDER BY date) AS prev_last_ts
            FROM trading_days
            WHERE symbol = ?
        )
        SELECT ?, d.date, d.prev_date, pb.close, nb.open,
               nb.open - pb.close,
               CASE WHEN abs(nb.open - pb.close) >= ?
                    THEN 'calendar+gap' ELSE 'calendar' END
        FROM d
        JOIN bars_m1 pb ON pb.symbol = ? AND pb.ts = d.prev_last_ts
        JOIN bars_m1 nb ON nb.symbol = ? AND nb.ts = d.first_ts
        WHERE d.date IN ({', '.join('?' * len(alvos))})
        ORDER BY d.date
        """,
        [symbol, symbol, CONFIRM_GAP_POINTS, symbol, symbol, *alvos],
    )
    return con.execute(
        "SELECT count(*) FROM rollovers WHERE symbol = ?", [symbol]
    ).fetchone()[0]


def unexplained_gaps(con, symbol: str, threshold: int = 2000) -> list[tuple]:
    """Gaps grandes que NAO sao rolagem - dias de noticia, na maior parte.
    Nao vao para a tabela: existem para voce olhar e decidir."""
    return con.execute(
        """
        WITH d AS (
            SELECT date, first_ts,
                   lag(date)    OVER (ORDER BY date) AS prev_date,
                   lag(last_ts) OVER (ORDER BY date) AS prev_last_ts
            FROM trading_days
            WHERE symbol = ?
        )
        SELECT d.prev_date, d.date, pb.close, nb.open, nb.open - pb.close AS gap
        FROM d
        JOIN bars_m1 pb ON pb.symbol = ? AND pb.ts = d.prev_last_ts
        JOIN bars_m1 nb ON nb.symbol = ? AND nb.ts = d.first_ts
        LEFT JOIN rollovers r ON r.symbol = ? AND r.date = d.date
        WHERE r.date IS NULL AND abs(nb.open - pb.close) >= ?
        ORDER BY abs(gap) DESC
        """,
        [symbol, symbol, symbol, symbol, threshold],
    ).fetchall()
