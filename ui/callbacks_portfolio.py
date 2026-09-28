"""Callbacks da tela Portfólio — portfólios, membros, correlação e risco."""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, html, no_update

from core import portfolio as P
from core import variantes as V

from .components import portfolio_panel as PP


def register(app):
    @app.callback(
        Output("pf-lista", "children"),
        Input("modo", "value"),
        Input("pf-btn-criar", "n_clicks"),
        State("pf-novo-nome", "value"),
        prevent_initial_call=False,
    )
    def listar_portfolios(modo, n_criar, nome_novo):
        if ctx.triggered_id == "pf-btn-criar" and (nome_novo or "").strip():
            P.criar(nome_novo.strip())
        if modo != "portfolio":
            return no_update
        return [PP.cartao_portfolio(p["portfolio_id"], p["nome"], p["n_membros"])
                for p in P.listar()]

    @app.callback(
        Output("pf-add-variante", "options"),
        Input("modo", "value"),
    )
    def opcoes_variantes(modo):
        if modo != "portfolio":
            return no_update
        return [{"label": f"{v['nome']} ({v['estrategia']})",
                 "value": v["variante_id"]} for v in V.listar()]

    @app.callback(
        Output("pf-detalhe", "style"),
        Output("pf-detalhe-titulo", "children"),
        Output("pf-curva", "figure"),
        Output("pf-membros", "children"),
        Output("pf-heatmap", "children"),
        Output("pf-risco", "children"),
        Output("pf-avisos", "children"),
        Output("store-portfolio-aberto", "data"),
        Input({"type": "pf-cartao", "portfolio_id": ALL}, "n_clicks"),
        Input("pf-btn-add", "n_clicks"),
        Input({"type": "pf-btn-remover", "variante_id": ALL}, "n_clicks"),
        State("pf-add-variante", "value"),
        State("store-portfolio-aberto", "data"),
        prevent_initial_call=True,
    )
    def abrir_detalhe(_cliques_cartao, _add, _remover, variante_add, pid):
        # Input de padrao-matching (ALL) dispara so por um cartao NOVO
        # aparecer no DOM (n_clicks=0, nunca clicado de verdade) - sem o
        # `valor_disparo`, criar um segundo portfolio "roubava" a tela de
        # quem estava vendo outro (achado na revisao do agente).
        gatilho = ctx.triggered_id
        valor_disparo = ctx.triggered[0]["value"] if ctx.triggered else None
        if (isinstance(gatilho, dict) and gatilho.get("type") == "pf-cartao"
                and valor_disparo):
            pid = gatilho["portfolio_id"]
        elif gatilho == "pf-btn-add" and pid is not None and variante_add:
            P.adicionar_variante(pid, variante_add)
        elif (isinstance(gatilho, dict) and gatilho.get("type") == "pf-btn-remover"
              and valor_disparo and pid is not None):
            P.remover_variante(pid, gatilho["variante_id"])
        elif isinstance(gatilho, dict) and not valor_disparo:
            # cartao/botao novo so apareceu no DOM - nao e navegacao nenhuma,
            # so re-renderiza o que ja estava aberto (ou nada, se pid None)
            pass

        if pid is None:
            return ({"display": "none"}, no_update, no_update, no_update,
                    no_update, no_update, no_update, pid)

        nome = next((p["nome"] for p in P.listar() if p["portfolio_id"] == pid), "")
        ms = P.membros(pid)

        curvas = P.curvas(pid)
        series = curvas["series"]
        linhas_membros = [
            PP.linha_membro(
                m["variante_id"], m["nome"], m["estrategia"],
                m["sem_plano_ativo"],
                resumo=_resumo_membro(series.get(m["nome"])))
            for m in ms
        ] or [html.P("nenhuma variante neste portfólio ainda.")]

        r = P.correlacao(pid)
        # "sem plano ativo" já sai de correlacao() E de curvas() para o
        # mesmo membro - junta sem duplicar a linha na lista de avisos
        avisos_txt = list(dict.fromkeys(r["avisos"] + curvas["avisos"]))
        avisos = html.Ul([html.Li(a) for a in avisos_txt]) if avisos_txt else None

        return ({"display": "block"}, nome, PP.figura_curva(series),
                linhas_membros, PP.heatmap(r["variantes"], r["matriz"]),
                PP.card_risco(r["risco_diario"]), avisos, pid)

    def _resumo_membro(dados: dict | None) -> dict | None:
        if not dados or not dados["pontos"]:
            return None
        return {"retorno": dados["pontos"][-1]["capital"] - dados["capital_inicial"],
                "trades": len(dados["pontos"])}
