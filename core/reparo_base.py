"""Correção da base com hora deslocada (spec 2026-10-01-ao-vivo-captura §0).

A sincronização de 23/09/2026 subtraiu 3 h de cada candle vindo do MT5.
Tudo o que foi minerado e testado depois disso olhou para pregões de
06:00 a 15:24; o usuário decidiu apagar a cadeia inteira e recomeçar.
Feito por SQL direto, de propósito: as funções da tela recusam apagar
cadeia protegida (plano em vigor), e aqui apagar tudo é a decisão.
"""
from __future__ import annotations

from datetime import date, time

# ordem: filhos antes dos pais. Contas e o diário ficam — são registro do
# que existiu, não resultado calculado sobre a base errada.
TABELAS_DERIVADAS = (
    "mining_trials", "wfa_trades", "planos_operacao", "wfa_runs",
    "mining_runs", "portfolio_membros", "portfolio_variantes",
    "portfolios", "estrategia_variantes",
)

ABRE = ((time(9, 0), time(9, 15)), (time(13, 0), time(13, 15)))  # 13h: quarta de cinzas
FECHA = (time(17, 45), time(18, 30))


def apagar_derivados(con) -> dict[str, int]:
    apagadas = {}
    for t in TABELAS_DERIVADAS:
        apagadas[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        con.execute(f"DELETE FROM {t}")
    return apagadas


def apagar_lotes(con, symbol: str, ids) -> int:
    ids = [int(i) for i in ids]
    marcas = ",".join("?" * len(ids))
    n = con.execute(f"SELECT count(*) FROM bars_m1 WHERE symbol = ? "
                    f"AND src_ingest_id IN ({marcas})", [symbol, *ids]).fetchone()[0]
    con.execute(f"DELETE FROM bars_m1 WHERE symbol = ? AND src_ingest_id IN ({marcas})",
                [symbol, *ids])
    return n


def sessoes_suspeitas(con, symbol: str, desde: date) -> list[dict]:
    """Pregões cujo primeiro ou último candle está fora do horário da B3.
    É para um humano olhar, não para corrigir sozinho: dia de fechamento
    antecipado aparece aqui e é legítimo."""
    linhas = con.execute(
        "SELECT date, first_ts, last_ts, bar_count FROM trading_days "
        "WHERE symbol = ? AND date >= ? ORDER BY date", [symbol, desde]).fetchall()
    fora = []
    for dia, primeiro, ultimo, n in linhas:
        abre_ok = any(a <= primeiro.time() <= b for a, b in ABRE)
        fecha_ok = FECHA[0] <= ultimo.time() <= FECHA[1]
        if not (abre_ok and fecha_ok):
            fora.append({"dia": dia, "abre": f"{primeiro:%H:%M}",
                         "fecha": f"{ultimo:%H:%M}", "candles": n})
    return fora
