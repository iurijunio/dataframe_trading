"""Painel de mineração: walk-forward, análise da varredura e tabela.

A tabela ordena por SCORE ROBUSTO, não por lucro. Lucro fora da amostra
sozinho ainda premia sorte; o robusto é a mediana dos vizinhos na grade, o
que empurra platôs para cima e derruba picos isolados.
"""

from __future__ import annotations

import dash_ag_grid as dag
from dash import dcc, html

from core import mineracao_stats as MS

from . import mine_criterios, mine_porteira, scatter

BRL = {"function": "params.value == null ? '' : params.value.toLocaleString('pt-BR',"
                   "{minimumFractionDigits:2,maximumFractionDigits:2})"}
N2 = {"function": "params.value == null ? '—' : params.value.toFixed(2)"}

COLUNAS = [
    {"field": "n", "headerName": "#", "width": 66, "pinned": "left"},
    {"field": "params_txt", "headerName": "combinação", "flex": 1, "minWidth": 220,
     "pinned": "left", "cellClass": "col-params"},
    # duas colunas de propósito: "score" existe desde o primeiro resultado,
    # "robusto" só nasce no fim, quando a grade inteira permite olhar vizinhos
    {"field": "score", "headerName": "score", "width": 96,
     "type": "numericColumn", "valueFormatter": N2,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "robusto", "headerName": "score robusto", "width": 128,
     # sem sort do lado do cliente: a ordem vem do servidor, que usa o robusto
     # quando existe e o score cru enquanto a varredura ainda corre
     "type": "numericColumn", "valueFormatter": N2,
     "headerTooltip": "mediana dos vizinhos na grade — platô vence pico isolado",
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "folds", "headerName": "períodos +", "width": 104,
     "headerTooltip": "em quantas janelas de teste a combinação lucrou"},
    {"field": "consistencia", "headerName": "consist. %", "width": 106,
     "type": "numericColumn",
     "cellClassRules": {"pos": "params.value >= 60", "neg": "params.value < 40"}},
    {"field": "mediana_fold", "headerName": "mediana/período", "width": 136,
     "type": "numericColumn", "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "lucro", "headerName": "lucro total", "width": 122,
     "type": "numericColumn", "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "fr", "headerName": "fator recup.", "width": 116,
     "type": "numericColumn", "valueFormatter": N2,
     "headerTooltip": "lucro ÷ drawdown — critério padrão de otimização do MT5",
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "pf", "headerName": "PF", "width": 84,
     "type": "numericColumn", "valueFormatter": N2},
    {"field": "dd", "headerName": "drawdown", "width": 114,
     "type": "numericColumn", "valueFormatter": BRL},
    {"field": "trades", "headerName": "trades", "width": 96, "type": "numericColumn"},
    {"field": "filtro", "headerName": "filtro", "width": 122,
     "cellClassRules": {"neg": "params.value != 'ok'"}},
]


def controles():
    def num(id_, v, step=1, minimo=0):
        return dcc.Input(id=id_, type="number", value=v, step=step, min=minimo,
                         className="inp", debounce=True)

    def fld(label, comp, hint=None):
        return html.Div([html.Label(label, className="fld-label"), comp,
                         html.Span(hint, className="fld-hint") if hint else None],
                        className="fld")

    return html.Section(
        [
            # NAO se chama "Walk-forward": aqui os parametros sao FIXOS em
            # todas as janelas. O que se mede e consistencia entre periodos.
            # O walk-forward de verdade - que REOTIMIZA a cada janela - e o
            # terceiro modo da plataforma.
            html.Div(html.H2("Consistência entre períodos", className="sec-title"),
                     className="sec-head"),
            html.Div(
                [
                    html.Div([
                        fld("treino (meses)", num("wf-treino", 12, 1, 1)),
                        fld("teste (meses)", num("wf-teste", 3, 1, 1)),
                        fld("passo (meses)", num("wf-passo", 3, 1, 1)),
                        fld("holdout (meses)", num("wf-holdout", 12, 1, 0)),
                    ], className="grid-2"),
                    fld("processos", num("wf-workers", 12, 1, 1)),
                    html.P(id="wf-resumo", className="grid-size"),
                    html.P(id="mine-salvo", className="fld-hint solo"),
                ],
                className="sec-body",
            ),
        ],
        className="sec", id="sec-mineracao",
    )


def barra_acoes():
    """Tudo que se faz com uma varredura, numa faixa só, acima dos resultados.

    Nada vai para o banco sozinho: minerar é exploratório, dezenas de
    tentativas até achar cluster, e guardar todas enche o disco de lixo.
    """
    return html.Section(
        [
            html.Div([
                html.Button("Minerar", id="btn-minerar", n_clicks=0,
                            className="btn-primary", disabled=True),
                html.Button("Parar", id="btn-parar", n_clicks=0,
                            className="btn-ghost btn-parar"),
            ], className="acoes acoes-run"),

            html.Div([
                html.Div(id="espaco-busca", className="contagem"),
                html.Div(id="mine-contagem", className="contagem"),
            ], className="contagens"),

            html.Div([
                dcc.Input(id="mine-nome", type="text", className="inp",
                          placeholder="nome da mineração", debounce=True),
                html.Button("Salvar", id="btn-salvar", n_clicks=0,
                            className="btn-ghost btn-salvar", disabled=True),
            ], className="acoes acoes-salvar"),

            html.Div([
                dcc.Dropdown(id="mine-carregar", className="dd dd-carregar",
                             placeholder="carregar mineração salva…",
                             options=[]),
                # dois cliques para apagar: o primeiro vira "confirmar?".
                # Apagar é irreversível e o alvo fica num seletor onde a
                # linha errada está a um pixel da certa.
                html.Button("Excluir", id="btn-excluir-mine", n_clicks=0,
                            className="btn-ghost btn-excluir", disabled=True),
            ], className="acoes acoes-carregar"),
        ],
        className="barra-acoes",
    )


def painel():
    return html.Section(
        [
            html.Div(
                [html.H2("Mineração", className="panel-title"),
                 # progresso e tempo restante juntos: separados por meia tela,
                 # era preciso olhar dois cantos para saber uma coisa so
                 html.Div(
                     [html.Div(html.Div(id="mine-bar", className="prog-bar"),
                               className="prog"),
                      html.Span(id="mine-info", className="prog-txt")],
                     className="prog-wrap"),
                 ],
                className="panel-head",
            ),
            dag.AgGrid(
                id="grid-mine",
                columnDefs=COLUNAS,
                rowData=[],
                className="ag-theme-alpine-dark grid-trades",
                dashGridOptions={
                    "rowSelection": "single", "animateRows": False,
                    "rowHeight": 30, "headerHeight": 34, "suppressCellFocus": True,
                    "localeText": {"noRowsToShow": "Configure as faixas e clique em Minerar."},
                },
                defaultColDef={"sortable": True, "filter": True, "resizable": True},
                style={"height": "100%", "width": "100%"},
            ),
        ],
        className="panel panel-mine",
    )


def painel_analise():
    """As três leituras da varredura, em abas — o mesmo padrão do Diagnóstico
    do backtest.

    A ordem é a do método: **onde** está a região boa (Dispersão), **como é**
    a região inteira (Distribuição), se ela **merece seguir** (Porteira) e,
    por fim, **quem passa** nos números que você fixou (Critérios). A tabela
    de resultados fica abaixo, comum às quatro.
    """
    def aba(rotulo, valor, filhos, classe="aba-corpo"):
        return dcc.Tab(label=rotulo, value=valor, className="aba",
                       selected_className="aba-on",
                       children=html.Div(filhos, className=classe))

    return html.Section(
        [
            html.Div(html.H2("Análise da varredura", className="panel-title"),
                     className="panel-head"),
            dcc.Tabs(
                id="abas-mine", value="dispersao", className="abas",
                parent_className="abas-wrap", content_className="abas-corpo",
                children=[
                    aba("Dispersão", "dispersao", scatter.corpo(),
                        "aba-corpo aba-dispersao"),
                    aba("Distribuição", "distribuicao", [
                        html.Div(
                            dcc.Dropdown(
                                id="dist-metrica", className="dd dd-sm",
                                value="lucro", clearable=False,
                                options=[{"label": r, "value": v}
                                         for r, v in MS.METRICAS]),
                            className="aba-tools"),
                        html.Div(id="mine-cards-dist"),
                        html.Div([
                            dcc.Graph(id="g-mine-hist", className="graf-mine",
                                      config={"displayModeBar": False,
                                              "responsive": True}),
                            dcc.Graph(id="g-mine-curva", className="graf-mine",
                                      config={"displayModeBar": False,
                                              "responsive": True}),
                        ], className="grade-mine"),
                    ], "aba-corpo aba-dist"),
                    aba("Porteira", "porteira",
                        html.Div(mine_porteira.vazio(), id="aba-porteira")),
                    aba("Critérios", "criterios", mine_criterios.painel()),
                ],
            ),
        ],
        className="panel panel-analise",
    )
