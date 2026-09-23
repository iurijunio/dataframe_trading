"""Callbacks da tela Estratégias — lista de módulos e variantes em uso."""
from __future__ import annotations

from dash import ALL, Input, Output, ctx, html, no_update

from core import variantes as V
from strategies import registry

from .components import estrategias_panel as EP


def register(app):
    @app.callback(
        Output("est-lista", "children"),
        Input("modo", "value"),
    )
    def listar_estrategias(modo):
        if modo != "estrategias":
            return no_update
        return [EP.cartao_estrategia(e["modulo"], e["label"], e["n_params"])
                for e in registry.descobrir()]

    @app.callback(
        Output("est-detalhe", "style"),
        Output("est-detalhe-titulo", "children"),
        Output("est-variantes", "children"),
        Input({"type": "est-cartao", "modulo": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def abrir_detalhe(cliques):
        # `n_clicks` é cumulativo por cartão, não reseta entre cliques -
        # pegar o primeiro "truthy" reabria sempre o mesmo cartão (o de
        # menor índice já clicado), não o que acabou de ser clicado.
        # `ctx.triggered_id` é o único jeito confiável de saber QUAL
        # cartão disparou desta vez.
        if not ctx.triggered_id:
            return {"display": "none"}, no_update, no_update
        modulo = ctx.triggered_id["modulo"]
        vs = V.listar(modulo)
        if not vs:
            corpo = html.P("nenhuma variante ainda para esta estratégia.")
        else:
            corpo = [EP.linha_variante(v["nome"], V.linha_do_tempo(v["variante_id"]))
                     for v in vs]
        rotulo = next((e["label"] for e in registry.descobrir()
                      if e["modulo"] == modulo), modulo)
        return {"display": "block"}, rotulo, corpo
