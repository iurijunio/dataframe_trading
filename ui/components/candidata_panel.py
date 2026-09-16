"""O quarto modo: a candidata.

Recebe um walk-forward salvo e pergunta quanto daquilo sobrevive fora do
cenário perfeito. Ver docs/PLANO-CANDIDATA.md.
"""

from __future__ import annotations

from dash import dcc, html


def painel():
    return html.Div(
        [
            html.Div(
                [
                    # nasce vazio: um WFA salvo depois de o processo subir só
                    # apareceria reiniciando o servidor. Quem preenche é o
                    # callback `cand_opcoes`, em `ui/callbacks_candidata.py`
                    # — o mesmo padrão de `wfa-salvos` em `wfa_panel.py`.
                    dcc.Dropdown(id="cand-wfa", className="dd dd-wfa",
                                 placeholder="walk-forward salvo…",
                                 options=[], value=None),
                    html.Span(id="cand-resumo", className="cand-resumo"),
                ],
                className="cand-topo",
            ),
            html.Div(id="cand-portoes", className="cand-portoes"),
            html.Div(id="cand-blocos", className="cand-blocos"),
        ],
        # escondido de saída: sem isto o Dash serve o primeiro HTML com este
        # painel VISÍVEL (`.modo-bloco` é display:flex) empilhado embaixo do
        # Backtest, até o callback `modo` resolver no cliente — mesma
        # armadilha que `painel-mineracao` e `painel-wfa` já evitam em
        # `ui/app.py`.
        id="painel-candidata", className="modo-bloco cand",
        style={"display": "none"},
    )
