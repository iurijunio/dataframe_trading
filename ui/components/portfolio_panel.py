"""Portfólio: agrupar variantes, ver membros, correlação e risco diário.

Só a fatia de portfólio e correlação (projeto D, parte 2) — alocação de
capital por variante e gatilho automático de reotimização ficam de fora,
ver docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md §2.
"""
from __future__ import annotations

from dash import dcc, html

from .cartao import brl, card


def painel():
    return html.Div(
        [
            html.Section([
                html.H2("Portfólio", className="panel-title"),
                html.Div([
                    dcc.Input(id="pf-novo-nome", type="text", className="inp",
                              placeholder="nome do novo portfólio",
                              debounce=True),
                    html.Button("Criar", id="pf-btn-criar", n_clicks=0,
                                className="btn-ghost"),
                ], className="acoes"),
                html.Div(id="pf-lista", className="est-lista"),
            ], className="panel"),
            html.Section(
                id="pf-detalhe", className="panel", style={"display": "none"},
                children=[
                    html.H3(id="pf-detalhe-titulo"),
                    html.Div([
                        dcc.Dropdown(id="pf-add-variante", className="dd dd-sm",
                                    placeholder="adicionar variante…",
                                    options=[]),
                        html.Button("Adicionar", id="pf-btn-add", n_clicks=0,
                                    className="btn-ghost"),
                    ], className="acoes"),
                    html.Div(id="pf-membros"),
                    html.Div(id="pf-risco"),
                    html.Div(id="pf-heatmap"),
                    html.Div(id="pf-avisos"),
                ],
            ),
        ],
        id="painel-portfolio", className="modo-bloco",
        style={"display": "none"},
    )


def cartao_portfolio(portfolio_id: int, nome: str, n_membros: int) -> html.Div:
    return html.Div(
        [html.Span(nome, className="est-cartao-nome"),
         html.Span(f"{n_membros} variante(s)", className="est-cartao-nota")],
        id={"type": "pf-cartao", "portfolio_id": portfolio_id},
        className="est-cartao", n_clicks=0,
    )


def linha_membro(variante_id: int, nome: str, estrategia: str,
                 sem_plano_ativo: bool) -> html.Div:
    nota = "sem plano ativo" if sem_plano_ativo else "plano ativo"
    return html.Div(
        [html.Span(f"{nome} · {estrategia}", className="est-variante-nome"),
         html.Span(nota, className="est-variante-nota"
                   + (" pf-sem-plano" if sem_plano_ativo else "")),
         html.Button("remover", id={"type": "pf-btn-remover",
                                    "variante_id": variante_id},
                     className="btn-ghost btn-sm", n_clicks=0)],
        className="est-variante",
    )


def card_risco(risco: dict | None) -> html.Div:
    if risco is None:
        return html.P("adicione pelo menos duas variantes com plano ativo "
                      "e trades no mesmo dia para ver o risco combinado.")
    sinal = "neg" if risco["p90"] < 0 else "pos"
    return card("drawdown diário combinado (p90)", brl(risco["p90"]),
                explica="Estimativa por simulação: o valor só é "
                        "ultrapassado em 10% dos cenários simulados — não "
                        "é o pior caso absoluto.",
                sinal=sinal, nota=f"pior dia: {risco['pior_dia']}")


def _cor_celula(r: float | None) -> str:
    if r is None:
        return "rgba(255,255,255,.03)"
    alpha = min(abs(r), 1.0)
    cor = "255,77,125" if r >= 0 else "0,245,160"
    return f"rgba({cor},{alpha:.2f})"


def heatmap(nomes: list[str], matriz: list[list]) -> html.Div:
    if len(nomes) < 2:
        return html.P("adicione pelo menos duas variantes com plano ativo "
                      "para ver a correlação.")
    n = len(nomes)
    cabecalho = [html.Div("", className="pf-heat-canto")] + [
        html.Div(nome, className="pf-heat-rotulo") for nome in nomes]
    linhas = [cabecalho]
    for i in range(n):
        linha = [html.Div(nomes[i], className="pf-heat-rotulo")]
        for j in range(n):
            v = matriz[i][j]
            texto = f"{v:.2f}" if v is not None else "—"
            linha.append(html.Div(
                texto, className="pf-heat-cel",
                style={"backgroundColor": _cor_celula(v)}))
        linhas.append(linha)
    return html.Div(
        [html.Div(linha, className="pf-heat-linha") for linha in linhas],
        className="pf-heatmap",
        style={"gridTemplateColumns": f"auto repeat({n}, 1fr)"},
    )
