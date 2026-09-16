"""A tela Candidata: o passo 10 da metodologia sobre a curva que o
otimizador nunca viu.

Aqui ficam as contas puras — sem Dash, sem banco. Quem lê o banco é o
callback; quem decide é o portão; quem calcula é este módulo.
"""

from __future__ import annotations

import numpy as np


def chave(params: dict) -> tuple:
    """Endereço canônico de uma combinação na grade.

    `wfa_runs.deploy` volta do JSON com 78.0 e `mining_trials` gravou 78:
    comparar dicionários direto devolve "nenhum vizinho encontrado" sem
    levantar erro nenhum — o pior tipo de defeito.
    """
    itens = []
    for nome in sorted(params):
        v = params[nome]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            itens.append((nome, v))
        else:
            itens.append((nome, round(float(v), 6)))
    return tuple(itens)


def por_pregao(saida_ts, liquido, de=None, ate=None):
    """O resultado por pregão, com os dias parados valendo zero.

    O trade entra no dia da SAÍDA, que é quando o resultado se realiza.
    Contar só os dias operados inflava quem opera pouco — quatro trades num
    ano davam Sharpe 129. E é o pregão, não o trade, a unidade em que a
    camada 4 impõe limite e em que o risco se materializa.
    """
    d = np.asarray(saida_ts, dtype="datetime64[D]")
    liq = np.asarray(liquido, dtype=float)
    if not len(d):
        return np.array([], dtype="datetime64[D]"), np.array([])
    ini = np.datetime64(de, "D") if de is not None else d.min()
    fim = np.datetime64(ate, "D") if ate is not None else d.max() + np.timedelta64(1, 'D')
    dias = np.arange(ini, fim)
    dias = dias[np.is_busday(dias)]
    if not len(dias):
        return dias, np.array([])
    pos = np.searchsorted(dias, d)
    # trade fora de `dias` (fim de semana/feriado, ou fora do recorte de/ate)
    # cai fora de `dentro` e é descartado em silêncio — de propósito: é o
    # mesmo mecanismo que faz o corte de/ate funcionar, não um bug
    dentro = (pos < len(dias)) & (dias[np.clip(pos, 0, len(dias) - 1)] == d)
    pnl = np.bincount(pos[dentro], weights=liq[dentro], minlength=len(dias))
    return dias, pnl


MIN_TRADES = 100


def leitura_robustez(trades: list[dict], capital: float,
                     horizonte_pregoes: int | None = None) -> dict:
    """O bloco 1: a robustez medida na curva que o otimizador nunca viu.

    Dois recortes sempre: a curva inteira e os últimos 12 meses. O mini
    índice foi de 96 mil a 197 mil pontos dentro da própria amostra — stop e
    alvo em pontos não significam a mesma coisa nas duas pontas, e o risco do
    regime atual não é a média de cinco anos. Vale o pior dos dois.
    """
    if len(trades) < MIN_TRADES:
        return {"erro": f"menos de {MIN_TRADES} trades fora da amostra"}

    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liq = np.array([t["liquido"] for t in trades], dtype=float)
    custo = np.array([t.get("custo", 0.0) for t in trades], dtype=float)
    dias, pnl = por_pregao(saida, liq)
    corte = dias[-1] - np.timedelta64(365, "D")
    # unidade explícita: somar int puro a datetime64 está deprecado no numpy
    ate12 = dias[-1] + np.timedelta64(1, "D")
    _, pnl12 = por_pregao(saida, liq, de=str(corte), ate=str(ate12))

    from . import metrics, robustez
    return {
        "resumo": metrics.resumo(liq, custo, saida, capital, len(dias)),
        "boot": robustez.bootstrap(pnl, capital, horizonte=horizonte_pregoes),
        "boot_12m": robustez.bootstrap(pnl12, capital,
                                       horizonte=horizonte_pregoes),
        # a permutação sobrevive como o que ela realmente mede: e se a mesma
        # sequência de resultados tivesse vindo noutra ordem
        "ordenacao": robustez.monte_carlo(liq, capital),
        "concentracao": robustez.concentracao(liq),
        "pregoes": len(dias),
    }


def risco_de_desligar(boot: dict, limite: float) -> float | None:
    """Chance de bater o limite de desligamento ESTANDO a estratégia viva.

    O bootstrap simula trajetórias de uma estratégia que continua funcionando
    como funcionou. Se X% delas encostam no limite, esse é o preço do
    disjuntor: desligar na hora errada X% das vezes. Sem este número, o
    limite não está calibrado — está chutado.
    """
    quedas = (boot or {}).get("quedas")
    if quedas is None or not len(quedas):
        return None
    return float((np.asarray(quedas) >= limite).mean() * 100)
