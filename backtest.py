"""Backtest unico pela linha de comando.

    py backtest.py
    py backtest.py --tf M15 --media-rapida 5 --media-lenta 40
    py backtest.py --stop-tipo atr --stop-atr-mult 2 --alvo 800 --breakeven 50

Tudo que aparece como opcao aqui e camada 3 (parametros) ou camada 4
(execucao). Nenhuma delas exige tocar na estrategia - que e o ponto.
A interface em ui/app.py cobre os mesmos campos com mais conforto.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import db_manager as db  # noqa: E402
from core import metrics  # noqa: E402
from core.engine.execution import ExecutionProfile, prepare_bars, run_strategy  # noqa: E402
from strategies import registry  # noqa: E402
from strategies.base import validate  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", default="WIN$N")
    p.add_argument("--de", default=None, help="data inicial (AAAA-MM-DD)")
    p.add_argument("--ate", default=None, help="data final (AAAA-MM-DD)")
    p.add_argument("--tf", default="M5", help="tempo grafico da estrategia")
    p.add_argument("--estrategia", default=None,
                   help="modulo em strategies/ (padrao: %(default)s)")

    g = p.add_argument_group("camada 3 - parametros da estrategia")
    g.add_argument("--media-rapida", type=int)
    g.add_argument("--media-lenta", type=int)

    e = p.add_argument_group("camada 4 - execucao")
    e.add_argument("--entradas-de", default="09:00")
    e.add_argument("--entradas-ate", default="17:00")
    e.add_argument("--fechamento", default="17:30")
    e.add_argument("--direcao", default="ambas", choices=("ambas", "compra", "venda"))
    e.add_argument("--alvo-tipo", default="pontos", choices=("pontos", "atr"))
    e.add_argument("--alvo", type=int, default=600)
    e.add_argument("--alvo-atr-per", type=int, default=20)
    e.add_argument("--alvo-atr-mult", type=float, default=3.0)
    e.add_argument("--stop-tipo", default="pontos", choices=("pontos", "atr"))
    e.add_argument("--stop", type=int, default=300)
    e.add_argument("--stop-atr-per", type=int, default=20)
    e.add_argument("--stop-atr-mult", type=float, default=1.5)
    e.add_argument("--breakeven", type=float, default=0, help="%% do alvo")
    e.add_argument("--step-gatilho", type=float, default=0, help="%% do alvo")
    e.add_argument("--step-dist", type=float, default=0, help="%% do alvo")
    e.add_argument("--trailing", type=int, default=0, help="pontos")
    e.add_argument("--lim-ganho", type=float, default=0, help="R$ por contrato")
    e.add_argument("--lim-perda", type=float, default=0, help="R$ por contrato")
    e.add_argument("--max-trades", type=int, default=0)
    e.add_argument("--max-loss", type=int, default=0)
    e.add_argument("--slippage", type=int, default=1, help="ticks")
    e.add_argument("--corretagem", type=float, default=0.50)
    e.add_argument("--emolumentos", type=float, default=0.27)
    e.add_argument("--contratos", type=int, default=1)
    e.add_argument("--risco-por-trade", type=float, default=None)
    e.add_argument("--capital", type=float, default=10_000.0)

    a = p.parse_args()

    estrategia = registry.definir(a.estrategia) if a.estrategia else registry.atual()
    params = validate(estrategia.params_schema,
                      {"media_rapida": a.media_rapida, "media_lenta": a.media_lenta})

    profile = ExecutionProfile(
        timeframe=a.tf,
        entrada_inicio=a.entradas_de, entrada_fim=a.entradas_ate,
        fechamento=a.fechamento, direcao=a.direcao,
        alvo_tipo=a.alvo_tipo, alvo_pontos=a.alvo,
        alvo_atr_periodo=a.alvo_atr_per, alvo_atr_mult=a.alvo_atr_mult,
        stop_tipo=a.stop_tipo, stop_pontos=a.stop,
        stop_atr_periodo=a.stop_atr_per, stop_atr_mult=a.stop_atr_mult,
        breakeven_pct=a.breakeven, step_gatilho_pct=a.step_gatilho,
        step_distancia_pct=a.step_dist, trailing_pontos=a.trailing,
        limite_ganho_contrato=a.lim_ganho, limite_perda_contrato=a.lim_perda,
        max_trades_dia=a.max_trades, max_prejuizos_dia=a.max_loss,
        slippage_ticks=a.slippage, corretagem_por_contrato=a.corretagem,
        emolumentos_por_contrato=a.emolumentos, contratos=a.contratos,
        risco_por_trade=a.risco_por_trade, capital_inicial=a.capital,
    )

    with db.connect(read_only=True) as con:
        instrument = db.load_instrument_yaml(a.symbol)
        bars = prepare_bars(con, a.symbol, a.de, a.ate)

    if not len(bars["open"]):
        sys.exit(f"nenhuma barra para {a.symbol}. Rode 'cli.py ingest' primeiro.")

    t = time.perf_counter()
    res = run_strategy(bars, estrategia, params, profile, instrument)
    ms = (time.perf_counter() - t) * 1000

    print(f"=== {estrategia.name} | {a.symbol} | {a.tf} ===")
    print(f"barras     : {len(bars['open']):,}".replace(",", "."))
    print(f"periodo    : {bars['ts'][0]}  ->  {bars['ts'][-1]}")
    print(f"parametros : {json.dumps(params)}")
    print(f"janela     : entradas {profile.entrada_inicio}-{profile.entrada_fim} | "
          f"fecha {profile.fechamento} | direcao {profile.direcao}")
    print(f"gestao     : alvo {profile.alvo_tipo} | stop {profile.stop_tipo} | "
          f"slippage {profile.slippage_ticks} tick(s)")
    print(f"tempo      : {ms:.0f} ms")
    print()

    for modo, m in metrics.compare_sizing(res).items():
        print(f"--- {modo} ---")
        print(metrics.format_panel(m))
        print()


if __name__ == "__main__":
    main()
