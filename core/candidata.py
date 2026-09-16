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
    dentro = (pos < len(dias)) & (dias[np.clip(pos, 0, len(dias) - 1)] == d)
    pnl = np.bincount(pos[dentro], weights=liq[dentro], minlength=len(dias))
    return dias, pnl


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
