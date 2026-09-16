"""O quarto modo: a candidata.

Recebe um walk-forward salvo e pergunta quanto daquilo sobrevive fora do
cenário perfeito. Ver docs/PLANO-CANDIDATA.md.
"""

from __future__ import annotations

from dash import dcc, html

from core import wfa_store


def _opcoes():
    return [{"label": w["rotulo"], "value": w["wfa_id"]}
            for w in wfa_store.listar()]


def painel():
    return html.Div(
        [
            html.Div(
                [
                    dcc.Dropdown(id="cand-wfa", className="dd dd-wfa",
                                 placeholder="walk-forward salvo…",
                                 options=_opcoes(), value=None),
                    html.Span(id="cand-resumo", className="cand-resumo"),
                ],
                className="cand-topo",
            ),
            html.Div(id="cand-portoes", className="cand-portoes"),
            html.Div(id="cand-blocos", className="cand-blocos"),
        ],
        id="painel-candidata", className="modo-bloco cand",
    )
