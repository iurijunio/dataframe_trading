"""Pontos viram dinheiro aqui, e so aqui.

O kernel devolve trades em pontos. O dimensionamento (contratos fixos ou
risco fixo) e os custos sao aplicados depois, sobre o MESMO conjunto de
trades. Por isso as duas curvas de capital saem de graca - e por isso da
para ver quando um resultado bonito vinha so do efeito de composicao, e nao
da qualidade do sinal.

Toda metrica e liquida de custo. Sem isso, estrategia de giro alto sempre
parece lucrativa.
"""

from __future__ import annotations

import numpy as np

from .engine import kernel as K
from .wfa import sharpe_diario
from .engine.execution import BacktestResult, ExecutionProfile

TRADING_DAYS_YEAR = 252


def contracts_for(res: BacktestResult, modo: str | None = None) -> np.ndarray:
    """Contratos por trade, segundo o modo de dimensionamento."""
    p = res.profile
    modo = modo or p.modo_posicao
    n = res.n_trades
    if n == 0:
        return np.empty(0, dtype=np.int64)

    if modo == "contratos_fixos":
        return np.full(n, max(1, int(p.contratos)), dtype=np.int64)

    if modo == "risco_fixo":
        if not p.risco_por_trade:
            raise ValueError("modo 'risco_fixo' exige risco_por_trade no perfil.")
        ponto = float(res.instrument.get("point_value", 1.0))
        risco_pontos = np.maximum(res.sl_at_entry, 1)
        qtd = np.floor(p.risco_por_trade / (risco_pontos * ponto))
        return np.maximum(qtd, 1).astype(np.int64)

    raise ValueError(f"modo de dimensionamento desconhecido: {modo!r}")


def monetize(res: BacktestResult, modo: str | None = None) -> dict[str, np.ndarray]:
    """Converte pontos em reais, liquido de custos."""
    p = res.profile
    ponto = float(res.instrument.get("point_value", 1.0))
    qtd = contracts_for(res, modo)

    bruto = res.trades["points"] * ponto * qtd
    # Corretagem e emolumentos sao por contrato e por PONTA: entrada + saida.
    custo = (p.corretagem_por_contrato + p.emolumentos_por_contrato) * qtd * 2
    liquido = bruto - custo

    return {
        "contratos": qtd,
        "bruto": bruto,
        "custo": custo,
        "liquido": liquido,
        "equity": p.capital_inicial + np.cumsum(liquido),
    }


def _drawdown(equity: np.ndarray, capital_inicial: float):
    """O mergulho em reais e em tres leituras percentuais.

    O MT5 reporta DUAS coisas diferentes, e confundi-las e classico:

      Balance Drawdown Maximal   - acha o maior mergulho em DINHEIRO e
                                   informa o percentual DAQUELE ponto;
      Balance Drawdown Relative  - acha o maior mergulho em PERCENTUAL, que
                                   pode estar em outro ponto da curva.

    `dd_abs` e `dd_pct` sao o primeiro par. `dd_rel_pct` e o segundo numero,
    calculado a parte porque o maximo percentual nem sempre coincide com o
    maximo absoluto: uma queda de 2.000 sobre um pico de 11.000 (18,2%) e
    mais dolorosa que uma de 3.000 sobre um pico de 20.000 (15,0%), mesmo
    sendo menor em reais.

    `dd_pct_capital` divide pelo capital inicial - a conta que se faz de
    cabeca. Os tres divergem assim que a curva sobe: R$ 791 sao 5,5% de um
    pico de R$ 14.333 e 7,9% dos R$ 10.000 do inicio.
    """
    if equity.size == 0:
        return 0.0, 0.0, 0.0, 0.0, 0
    curva = np.concatenate(([capital_inicial], equity))
    pico = np.maximum.accumulate(curva)
    dd = curva - pico
    i = int(np.argmin(dd))
    dd_abs = float(-dd[i])
    dd_pct = float(-dd[i] / pico[i] * 100) if pico[i] else 0.0
    dd_pct_cap = float(dd_abs / capital_inicial * 100) if capital_inicial else 0.0
    # o maior mergulho PERCENTUAL, que pode nao ser o mesmo ponto do maior
    # mergulho em reais
    rel = np.divide(pico - curva, pico, out=np.zeros_like(curva, dtype=float),
                    where=pico > 0)
    dd_rel_pct = float(rel.max() * 100)

    # duracao: maior sequencia sem fazer novo topo
    submerso = curva < pico
    maior = atual = 0
    for s in submerso:
        atual = atual + 1 if s else 0
        maior = max(maior, atual)
    return dd_abs, dd_pct, dd_pct_cap, dd_rel_pct, maior


def _max_consecutivas(liquido: np.ndarray) -> int:
    maior = atual = 0
    for v in liquido:
        atual = atual + 1 if v < 0 else 0
        maior = max(maior, atual)
    return maior


def resumo(liquido, custo, saida_ts, capital_inicial: float,
           n_pregoes: int | None = None) -> dict:
    """As métricas que só dependem do resultado de cada trade.

    Separada de `compute` para que QUALQUER sequência de trades seja medida
    com a mesma régua: o backtest, a curva fora da amostra do walk-forward e,
    amanhã, a curva combinada de um portfólio. Se cada tela calculasse o seu
    Sharpe, cedo ou tarde dois cartões com o mesmo nome dariam números
    diferentes para a mesma curva.

    `saida_ts` porque o dia de um trade é o dia em que o resultado se
    REALIZA — é por ele que se agrega a série diária do Sharpe.

    `n_pregoes`: quantos pregões o período teve. Os dias sem trade entram no
    Sharpe e no Sortino como retorno zero. Sem ele, conta os dias úteis entre
    o primeiro e o último trade.
    """
    liq = np.asarray(liquido, dtype=np.float64)
    n = int(liq.size)
    if n == 0:
        return {"trades": 0}
    custo = (np.zeros(n) if custo is None
             else np.asarray(custo, dtype=np.float64))

    ganhos = liq[liq > 0]
    perdas = liq[liq < 0]
    soma_ganhos = float(ganhos.sum())
    soma_perdas = float(-perdas.sum())

    equity = capital_inicial + np.cumsum(liq)
    dd_abs, dd_pct, dd_pct_cap, dd_rel, dd_dur = _drawdown(equity,
                                                           capital_inicial)
    lucro = float(liq.sum())

    # Sharpe e Sortino sobre retorno DIARIO, nao por trade - e com os pregoes
    # SEM trade entrando como zero. Calcular so nos dias operados inflava
    # quem opera pouco (4 trades num ano davam Sharpe na casa das centenas).
    dias = np.asarray(saida_ts).astype("datetime64[D]")
    dias_unicos, inv = np.unique(dias, return_inverse=True)
    por_dia = np.zeros(len(dias_unicos))
    np.add.at(por_dia, inv, liq)
    ret_dia = por_dia / capital_inicial if capital_inicial else por_dia
    if n_pregoes is None:
        n_pregoes = int(np.busday_count(dias_unicos[0],
                                        dias_unicos[-1] + np.timedelta64(1, "D")))
    n_dias = max(int(n_pregoes), len(ret_dia))
    raiz = np.sqrt(TRADING_DAYS_YEAR)
    sharpe = sharpe_diario(ret_dia, n_dias)
    # Sortino: a média sobre o desvio das PERDAS (downside deviation), com
    # os dias parados no denominador. A versão anterior usava o desvio padrão
    # só dos dias negativos, que não é a definição.
    desvio_perdas = float(np.sqrt((np.minimum(ret_dia, 0.0) ** 2).sum() / n_dias))
    media_dia = float(ret_dia.sum()) / n_dias

    return {
        "trades": n,
        "lucro_liquido": lucro,
        "lucro_bruto": float((liq + custo).sum()),
        "custo_total": float(custo.sum()),
        # mesma convenção de `wfa.metricas`: sem perda, PF infinito só se
        # houve ganho — todos os trades zerados dão 0, e não infinito
        "profit_factor": ((soma_ganhos / soma_perdas) if soma_perdas
                          else (float("inf") if soma_ganhos else 0.0)),
        "win_rate": float(len(ganhos) / n * 100),
        "payoff": (float(ganhos.mean()) / float(-perdas.mean())) if len(perdas) and len(ganhos) else 0.0,
        "expectativa": float(liq.mean()),
        "max_drawdown": dd_abs,
        "max_drawdown_pct": dd_pct,
        "max_drawdown_pct_capital": dd_pct_cap,
        # Balance Drawdown Relative do MT5: o maior mergulho em percentual
        "max_drawdown_rel_pct": dd_rel,
        "drawdown_duracao_trades": dd_dur,
        "fator_recuperacao": ((lucro / dd_abs) if dd_abs
                              else (float("inf") if lucro > 0 else 0.0)),
        "sharpe": sharpe,
        "sortino": float(media_dia / desvio_perdas * raiz) if desvio_perdas else 0.0,
        "max_perdas_consecutivas": _max_consecutivas(liq),
        "pregoes_operados": int(len(dias_unicos)),
        "trades_por_dia": float(n / len(dias_unicos)),
    }


def compute(res: BacktestResult, modo: str | None = None) -> dict:
    p = res.profile
    m = monetize(res, modo)
    n = res.n_trades

    if n == 0:
        return {
            "modo_posicao": modo or p.modo_posicao,
            "trades": 0,
            "barras_ambiguas": res.ambiguous_bars,
            "barras_ambiguas_pct": 0.0,
            "dias_bloqueados": res.bloqueios,
            "passa_filtro": p.min_operacoes <= 0,
        }

    return {
        "modo_posicao": modo or p.modo_posicao,
        **resumo(m["liquido"], m["custo"], res.trades["exit_ts"],
                 p.capital_inicial),
        # o bruto do próprio monetize, e não liquido + custo: é o número de
        # origem, sem uma volta de ponto flutuante no meio
        "lucro_bruto": float(m["bruto"].sum()),
        "pontos_liquidos": int(res.trades["points"].sum()),
        "duracao_media_barras": float(res.trades["bars_held"].mean()),
        "mae_medio": float(res.trades["mae"].mean()),
        "mfe_medio": float(res.trades["mfe"].mean()),
        "barras_ambiguas": res.ambiguous_bars,
        "barras_ambiguas_pct": float(res.ambiguous_bars / res.n_bars * 100),
        # quantas vezes um limite diario interrompeu o dia
        "dias_bloqueados": res.bloqueios,
        # filtro de mineracao: combinacao com poucas operacoes nao conta
        "passa_filtro": n >= p.min_operacoes if p.min_operacoes else True,
        "saidas": {
            K.EXIT_LABELS[k]: int((res.trades["reason"] == k).sum())
            for k in sorted(set(res.trades["reason"].tolist()))
        },
    }


def compare_sizing(res: BacktestResult) -> dict[str, dict]:
    """Os dois modos, lado a lado, sobre o mesmo conjunto de trades."""
    out = {"contratos_fixos": compute(res, "contratos_fixos")}
    if res.profile.risco_por_trade:
        out["risco_fixo"] = compute(res, "risco_fixo")
    return out


def format_panel(m: dict) -> str:
    if not m.get("trades"):
        return "nenhum trade."
    br = lambda v: f"R$ {v:>12,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return "\n".join([
        f"  trades              : {m['trades']:>12,}".replace(",", "."),
        f"  lucro liquido       : {br(m['lucro_liquido'])}",
        f"  custo total         : {br(m['custo_total'])}",
        f"  profit factor       : {m['profit_factor']:>15.2f}",
        f"  win rate            : {m['win_rate']:>14.1f}%",
        f"  payoff              : {m['payoff']:>15.2f}",
        f"  expectativa/trade   : {br(m['expectativa'])}",
        f"  max drawdown        : {br(m['max_drawdown'])}  "
        f"({m['max_drawdown_pct']:.1f}% do pico · "
        f"{m['max_drawdown_pct_capital']:.1f}% do capital)",
        f"  fator recuperacao   : {m['fator_recuperacao']:>15.2f}",
        f"  sharpe              : {m['sharpe']:>15.2f}",
        f"  sortino             : {m['sortino']:>15.2f}",
        f"  perdas consecutivas : {m['max_perdas_consecutivas']:>12}",
        f"  trades por dia      : {m['trades_por_dia']:>15.2f}",
        f"  barras ambiguas     : {m['barras_ambiguas']:>12,} "
        f"({m['barras_ambiguas_pct']:.3f}%)".replace(",", "."),
        f"  saidas              : {m['saidas']}",
    ])
