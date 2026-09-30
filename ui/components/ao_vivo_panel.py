"""Tela Ao vivo › Estratégias: o que está (ou vai estar) rodando.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md §5.
Só desenha — quem lê o banco é `ui/callbacks_ao_vivo.py`. As outras
sub-telas (Pregão, Conta, Histórico) só entram quando a parte delas
existir: tela vazia confunde.
"""
from __future__ import annotations

from dash import dcc, html

FASES = {"papel": "papel", "demo": "demo", "real_minimo": "real mínimo",
         "real": "real"}


def _secao(titulo, nota, *filhos):
    return html.Section([
        html.Div([html.H3(titulo, className="panel-title"),
                  html.Span(nota, className="panel-note")],
                 className="panel-head"),
        *filhos,
    ], className="panel")


def painel():
    return html.Div([
        # um número que sobe a cada ação: é ele que manda redesenhar
        dcc.Store(id="av-versao", data=0),
        # o botão que está pedindo confirmação (segundo clique executa)
        dcc.Store(id="av-armado", data=None),
        # a variante com a ficha aberta
        dcc.Store(id="av-aberta", data=None),
        html.Section([
            html.Div([html.H2("Ao vivo", className="panel-title"),
                      html.Span("Estratégias", className="chip av-subtela")],
                     className="panel-head"),
            html.Div(id="av-aviso", className="av-aviso"),
        ], className="panel"),
        _secao("Portfólios", "ligue o portfólio para as variantes dele rodarem "
               "(por enquanto só no papel, sem enviar ordem)",
               html.Div(id="av-portfolios", className="av-lista")),
        _secao("Variantes", "clique no nome para abrir a ficha: de onde veio o "
               "plano, o que ele opera e o que já mudou",
               html.Div(id="av-variantes", className="av-lista-col")),
        _secao("Contas", "contas do MT5 onde as ordens vão cair a partir da "
               "fase demo — o limite de perda diária é da mesa",
               html.Div([
                   dcc.Input(id="av-conta-nome", type="text", className="inp",
                             placeholder="nome da conta (ex.: Demo XP)"),
                   dcc.Dropdown(id="av-conta-tipo", className="dd dd-sm",
                                clearable=False, value="demo",
                                options=[{"label": "demo", "value": "demo"},
                                         {"label": "real", "value": "real"}]),
                   dcc.Input(id="av-conta-limite", type="text",
                             inputMode="numeric", className="inp",
                             placeholder="limite de perda diária (R$, opcional)"),
                   html.Button("Criar conta", id="av-btn-conta-criar",
                               n_clicks=0, className="btn-ghost"),
               ], className="acoes"),
               html.Div(id="av-contas", className="av-lista-col")),
        _secao("Arrumação", "planos ativos que não pertencem a nenhuma "
               "variante — só entram em portfólio depois de vinculados",
               html.Div(id="av-arrumacao", className="av-lista-col")),
    ], id="painel-aovivo", className="modo-bloco", style={"display": "none"})
