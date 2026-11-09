"""Operação: callbacks da demo e da real (ordens, diário, chamados, contratos)."""
from __future__ import annotations

import time

import duckdb
from dash import ALL, Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

from ..components import ordens_panel as OR

from .dados import _armado_valido, _visivel, abrir_editor, acao_chamado, custo_editor, ler_diario, ler_ordens, salvar_editor
from .montagem import _conta_do_chamado


def register(app):
    # ------------------------------------------------- parte 4: a demo
    @app.callback(
        Output("av-op-ord-operacoes", "children"),
        Output("av-op-ord-selo", "children"),
        Output("av-op-ord-cmp", "children"),
        Output("av-op-ord-dados", "data"),
        Output("av-op-real-operacoes", "children"),
        Output("av-op-ord-cmp-real", "children"),
        # o diário das ordens só muda quando `ordens_em` muda; o papel (o
        # par de cada operação) quando `av-op-versao` muda — nunca o pulso
        Input("av-op-ord-versao", "data"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-acao-versao", "data"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def ordens_op(_ordens_em, _versao, pid, _acoes, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        try:
            return ler_ordens(pid)
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate

    @app.callback(
        Output("av-op-ord-diario", "children"),
        Input("av-op-ord-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-ord-diario-filtro", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def diario_op(_ordens_em, pid, filtro, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        try:
            return ler_diario(pid, filtro == "problemas")
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate

    @app.callback(
        Output("av-op-ord-armado", "data"),
        Output("av-op-ord-escondidos", "data"),
        Output("av-op-ord-enviados", "data"),
        Output("av-op-aviso", "children", allow_duplicate=True),
        Input({"type": "av-op-ord-acao", "acao": ALL, "id": ALL}, "n_clicks"),
        State("av-op-ord-armado", "data"),
        State("av-op-ord-escondidos", "data"),
        State("av-op-ord-enviados", "data"),
        prevent_initial_call=True,
    )
    def chamado_op(_cliques, armado, escondidos, enviados):
        # o pulso redesenha os botões a cada 2 s com n_clicks=0: só clique
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        return acao_chamado(gat["acao"], gat["id"], armado, escondidos,
                            enviados, time.time(),
                            tipo=_conta_do_chamado(gat["id"]))

    @app.callback(
        Output({"type": "av-op-ord-acao", "acao": ALL, "id": ALL}, "children"),
        Output({"type": "av-op-ord-acao", "acao": ALL, "id": ALL}, "className"),
        Input("av-op-ord-armado", "data"),
        prevent_initial_call=True,
    )
    def rotulos_ord(armado):
        chave = _armado_valido(armado, time.time())
        estados = [OR.rotulo_botao(o["id"]["acao"], o["id"]["id"], chave)
                   for o in ctx.outputs_list[0]]
        return [e[0] for e in estados], [e[1] for e in estados]

    # desarma sozinho depois de 5 s, como os outros botões de dois cliques
    app.clientside_callback(
        """function (armado) {
            window._avOpOrdArmado = armado || null;
            var marca = window._avOpOrdArmado;
            if (armado) {
                setTimeout(function () {
                    if (window._avOpOrdArmado === marca) {
                        window._avOpOrdArmado = null;
                        window.dash_clientside.set_props('av-op-ord-armado', {data: null});
                    }
                }, 5000);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-ord-chamados", "role"),
        Input("av-op-ord-armado", "data"),
        prevent_initial_call=True,
    )

    # ------------------------------------- contratos da demo (o ✎)
    @app.callback(
        Output("av-op-ord-ctr-pop", "style"),
        Output("av-op-ord-ctr-alvo", "data"),
        Output("av-op-ord-ctr-valor", "value"),
        Output("av-op-ord-ctr-titulo", "children"),
        Output("av-op-ord-ctr-antes", "children"),
        Output("av-op-ord-ctr-erro", "children"),
        Output("av-op-ord-ctr-conta", "data"),
        Input({"type": "av-op-ord-ctr", "id": ALL}, "n_clicks"),
        Input({"type": "av-op-ctr-real", "id": ALL}, "n_clicks"),
        Input("av-op-ord-ctr-cancelar", "n_clicks"),
        State("av-op-vars", "data"),
        prevent_initial_call=True,
    )
    def editor_ctr(_lapis, _lapis_real, _cancelar, vars_):
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        if gat == "av-op-ord-ctr-cancelar":
            return ({"display": "none"}, None, no_update, no_update, no_update, "",
                    no_update)
        # o ✎ da parte REAL abre o editor da conta real; o da DEMO, o da demo
        conta = "real" if gat.get("type") == "av-op-ctr-real" else "demo"
        return (*abrir_editor(gat["id"], vars_, conta), "", conta)

    @app.callback(
        Output("av-op-ord-ctr-custo", "children"),
        Input("av-op-ord-ctr-valor", "value"),
        # Input também: abrir outra variante com o mesmo valor no campo
        # não muda o `value`, e o custo ficaria o da anterior
        Input("av-op-ord-ctr-alvo", "data"),
        State("av-op-ord-ctr-conta", "data"),
        prevent_initial_call=True,
    )
    def custo_ctr(valor, lig, conta):
        return custo_editor(lig, valor, conta or "demo")

    @app.callback(
        Output("av-op-ord-ctr-pop", "style", allow_duplicate=True),
        Output("av-op-ord-ctr-erro", "children", allow_duplicate=True),
        Output("av-op-acao-versao", "data", allow_duplicate=True),
        Output("av-op-aviso", "children", allow_duplicate=True),
        Input("av-op-ord-ctr-salvar", "n_clicks"),
        State("av-op-ord-ctr-alvo", "data"),
        State("av-op-ord-ctr-valor", "value"),
        State("av-op-acao-versao", "data"),
        State("av-op-ord-ctr-conta", "data"),
        prevent_initial_call=True,
    )
    def salvar_ctr(n, lig, valor, versao, conta):
        if not n:
            raise PreventUpdate
        ok, msg = salvar_editor(lig, valor, conta or "demo")
        if not ok:
            return no_update, msg, no_update, no_update
        # sobe a versão: os cartões redesenham com o número novo
        return {"display": "none"}, "", (versao or 0) + 1, msg
