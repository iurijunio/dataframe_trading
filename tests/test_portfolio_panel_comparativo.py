"""`ui/components/portfolio_panel.py::_cor_comparativo`/`tabela_comparativa`.

Achado da revisão: profit_factor e fator_recuperação viram +inf quando a
variante ainda não teve NENHUMA perda (edge real, sem "quanto" pra
dividir). Sem tratar à parte, um inf entrando no min/max da coluna fazia
frac=(finito/inf)=0 pra TODA linha finita - pintava tudo de "pior" mesmo
quando a própria linha do inf era, de fato, a melhor da coluna.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import portfolio_panel as PP  # noqa: E402


def test_cor_comparativo_inf_nao_maior_e_melhor_ganha_cor_de_melhor():
    assert PP._cor_comparativo(float("inf"), 1.0, 5.0, invertido=False) == PP._COR_MELHOR


def test_cor_comparativo_finito_ao_lado_de_inf_nao_cai_pra_pior():
    """A linha com profit_factor=5 é melhor que a com 3 - mesmo com uma
    terceira linha em +inf na mesma coluna, 5 não pode pintar igual a 3."""
    linhas = [
        ("a", {"capital_inicial": 1000.0, "trades": 10, "lucro_liquido": 1.0,
               "max_drawdown": 1.0, "max_drawdown_pct_capital": 1.0,
               "fator_recuperacao": 1.0, "profit_factor": 3.0,
               "win_rate": 50.0, "sharpe": 1.0}, False),
        ("b", {"capital_inicial": 1000.0, "trades": 10, "lucro_liquido": 1.0,
               "max_drawdown": 1.0, "max_drawdown_pct_capital": 1.0,
               "fator_recuperacao": 1.0, "profit_factor": 5.0,
               "win_rate": 50.0, "sharpe": 1.0}, False),
        ("c (sem perda)", {"capital_inicial": 1000.0, "trades": 10,
               "lucro_liquido": 1.0, "max_drawdown": 1.0,
               "max_drawdown_pct_capital": 1.0, "fator_recuperacao": 1.0,
               "profit_factor": float("inf"), "win_rate": 50.0, "sharpe": 1.0}, False),
    ]
    tabela = PP.tabela_comparativa(linhas)
    linhas_tr = tabela.children[1].children  # tbody -> [Tr, Tr, Tr]

    def cor_profit_factor(tr):
        # colunas: nome, capital, lucro, dd, dd%, fr, PF, wr, sharpe, trades
        return tr.children[6].style.get("backgroundColor")

    cor_a = cor_profit_factor(linhas_tr[0])  # PF=3, o pior dos 3
    cor_b = cor_profit_factor(linhas_tr[1])  # PF=5, melhor que "a"
    cor_c = cor_profit_factor(linhas_tr[2])  # PF=inf, melhor de todos

    assert cor_c == PP._COR_MELHOR
    assert cor_a != cor_b, "PF=3 e PF=5 não podem cair na mesma cor"
    assert cor_a == PP._COR_PIOR  # o pior finito ainda vira "pior" de verdade
