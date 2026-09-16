"""Dashboard do Dataframe.

    py ui/app.py     ->  http://127.0.0.1:8050

Backtest unico com auditoria visual: candles com as setas de entrada e saida,
curva de capital com underwater, painel estatistico e a lista de trades.
Clicar num trade da lista leva o grafico ate ele.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dash_tvlwc
from dash import Dash, dcc, html

from ui import data as D
from ui import theme as T
from ui.components import (analytics_charts, candidata_panel, controls,
                           mining, results_grid, stats_cards, wfa_panel)

# O simbolo NAO mora mais no codigo: vem do banco. Este e so o padrao de
# arranque, o primeiro instrumento com barras.
def _padrao() -> str:
    lista = D.instrumentos()
    return lista[0]["symbol"] if lista else "WIN$N"

FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Archivo:wght@500;600;700&"
    "family=JetBrains+Mono:wght@400;500;600;700&display=swap"
)

RANGES = [("1D", 1), ("5D", 5), ("1M", 30), ("3M", 90), ("1A", 365), ("Tudo", 0)]


def topbar(simbolo):
    return html.Header(
        [
            html.Div(
                [
                    html.Span("Dataframe", className="brand"),
                    dcc.Dropdown(
                        id="ativo", value=simbolo, clearable=False,
                        className="dd dd-ativo",
                        options=[{"label": i["symbol"], "value": i["symbol"]}
                                 for i in D.instrumentos()],
                    ),
                    # Duas atividades diferentes, nao duas abas do mesmo:
                    # backtest e conferir se a estrategia faz o que voce
                    # desenhou; mineracao e procurar regiao boa no espaco.
                    dcc.RadioItems(
                        id="modo", value="backtest", className="modo",
                        options=[{"label": "Backtest", "value": "backtest"},
                                 {"label": "Mineração", "value": "mineracao"},
                                 {"label": "Walk-Forward", "value": "wfa"},
                                 {"label": "Candidata", "value": "candidata"}],
                    ),
                ],
                className="brand-wrap",
            ),
            # O cartao "periodo" ja diz a janela medida, e o tempo do motor
            # nao ajuda a decidir nada - o cabecalho fica so com a identidade.
            html.Span(id="meta-tempo", style={"display": "none"}),
        ],
        className="topbar",
    )


def chart_toolbar():
    return html.Div(
        [
            html.Div(
                [html.Button(rot, id={"type": "rng", "dias": d}, n_clicks=0,
                             className="chip") for rot, d in RANGES],
                className="chips",
            ),
            html.Div(
                [
                    dcc.Dropdown(
                        id="tf", value="auto", clearable=False, className="dd dd-sm",
                        options=[{"label": "automático", "value": "auto"}]
                        + [{"label": k, "value": k} for k in D.TIMEFRAMES],
                    ),
                    html.Span(id="tf-info", className="tf-info"),
                ],
                className="tool-right",
            ),
        ],
        className="toolbar",
    )


def painel(inicio, fim):
    """A curva de capital manda na tela: e a leitura principal.

    O grafico de candles serve para conferir se a estrategia esta fazendo o
    que deveria, entao divide a faixa de baixo com a lista de trades.
    """
    return html.Main(
        [
            # cartoes sao resultado de BACKTEST: em modo mineracao nao tem
            # o que mostrar ali, entao entram no bloco que some junto
            html.Div(id="painel-backtest", children=[
                html.Div(stats_cards.vazio(), id="cards"),
                html.Section(
                [
                    html.Div(
                        [html.H2("Curva de capital", className="panel-title hero"),
                         html.Span("equity acima · underwater drawdown abaixo",
                                   className="panel-note")],
                        className="panel-head",
                    ),
                    dash_tvlwc.Tvlwc(
                        id="chart-capital",
                        series=[],
                        chartOptions={**T.CHART_OPTIONS,
                                      "timeScale": {**T.CHART_OPTIONS["timeScale"],
                                                    "timeVisible": False,
                                                    # a curva mostra o backtest
                                                    # inteiro; folga à direita
                                                    # só encolheria o desenho
                                                    "rightOffset": 0}},
                        height="100%",
                    ),
                ],
                className="panel panel-equity",
            ),

            html.Section(
                [
                    html.Div(
                        [html.H2("Diagnóstico", className="panel-title"),
                         html.Button("Visualizar estratégia", id="btn-chart",
                                     n_clicks=0, className="btn-ghost")],
                        className="panel-head",
                    ),
                    analytics_charts.abas(results_grid.grid()),
                ],
                className="panel panel-grid",
            )], className="modo-bloco"),

            html.Div(id="painel-mineracao", className="modo-bloco",
                     children=[mining.barra_acoes(), mining.painel_analise(),
                               mining.painel()],
                     style={"display": "none"}),

            # o terceiro modo: aqui os parametros MUDAM a cada janela, e o
            # que se mede e o processo de escolher - nao um numero
            # `modo-bloco` (flex COLUNA) tem que estar aqui, no elemento que
            # o callback liga e desliga. Sem a classe, o `display:flex` do
            # callback virava container de LINHA e o conteúdo encolhia para a
            # largura natural, deixando um vazio à direita.
            html.Div(id="painel-wfa", className="modo-bloco",
                     children=wfa_panel.painel(), style={"display": "none"}),

            # `candidata_panel.painel()` já é o `html.Div#painel-candidata`
            # (classe `modo-bloco cand`) — envolvê-lo em outro Div com o
            # mesmo id duplicaria o id e o Dash recusa o layout na primeira
            # requisição (`DuplicateIdError`), diferente do padrão do WFA
            # acima, cujo `painel()` devolve uma LISTA de filhos, sem id.
            candidata_panel.painel(),
        ],
        className="main",
    )


def modal():
    """O grafico de precos vive aqui: espremido ao lado da tabela ele nao
    serve nem para conferir uma entrada, e ele nao e a leitura principal."""
    return html.Div(
        [
            html.Div(id="modal-fundo", className="modal-fundo", n_clicks=0),
            html.Div(
                [
                    html.Div(
                        [html.H2("Auditoria da estratégia", className="panel-title hero"),
                         html.Span(id="chart-info", className="panel-note"),
                         html.Button("✕", id="btn-close", n_clicks=0,
                                     className="btn-close", title="fechar")],
                        className="panel-head",
                    ),
                    chart_toolbar(),
                    dash_tvlwc.Tvlwc(
                        id="chart-preco",
                        series=[],
                        chartOptions=T.CHART_OPTIONS,
                        height="100%",
                        subscribeClick=True,
                    ),
                ],
                className="modal-caixa",
            ),
        ],
        id="modal", className="modal",
    )


def sidebar(inicio, fim):
    return html.Aside(
        [controls.periodo(inicio, fim), mining.controles(),
         controls.seletor_estrategia(), controls.parametros(),
         controls.execucao()],
        className="sidebar", id="sidebar",
    )


def build() -> Dash:
    simbolo = _padrao()
    inicio, fim = D.span(simbolo)

    app = Dash(__name__, title="Dataframe", update_title=None,
               suppress_callback_exceptions=True)
    app.index_string = f"""<!DOCTYPE html>
<html>
<head>
  {{%metas%}}<title>{{%title%}}</title>{{%favicon%}}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="{FONTS}">
  {{%css%}}
</head>
<body>{{%app_entry%}}<footer>{{%config%}}{{%scripts%}}{{%renderer%}}</footer></body>
</html>"""

    app.layout = html.Div(
        [
            dcc.Store(id="store-run"),
            dcc.Store(id="store-window"),
            # avisa o relógio que uma varredura de walk-forward começou. Sem
            # ele havia corrida: `pulso` e `wfa_executar` disparam juntos no
            # clique, e quando o pulso vinha primeiro ainda via rodando=False
            # e deixava o relógio parado — a tela congelava em "varrendo…".
            dcc.Store(id="store-wfa"),
            # a varredura acabou: muda UMA vez por varredura, e é ela — não o
            # relógio — que dispara o cálculo das janelas
            dcc.Store(id="store-varredura"),
            # um walk-forward salvo foi escolhido: força o cálculo mesmo
            # quando IS, OOS e inteligência gravados já são os da tela
            dcc.Store(id="store-wfa-carregar"),
            # as sete matrizes ficaram prontas no servidor: a chave muda uma
            # vez por varredura e estado do holdout
            dcc.Store(id="store-matriz"),
            # a lista de walk-forwards salvos mudou (exclusão)
            dcc.Store(id="store-wfa-lista"),
            # Avisa que a MINERAÇÃO terminou. As análises pesadas
            # (Distribuição, Porteira, Critérios) ouvem este store em vez do
            # rowData da tabela: o rowData é reescrito a cada 800 ms enquanto
            # a varredura corre, e recalcular três painéis sobre 5.000
            # combinações nessa cadência travava a tela inteira.
            dcc.Store(id="store-mine"),
            # so pulsa enquanto a mineracao corre; ver callbacks.pulso
            dcc.Interval(id="tick", interval=800, disabled=True),
            topbar(simbolo),
            html.Div([sidebar(inicio, fim), painel(inicio, fim)], className="body"),
            modal(),
        ],
        className="app",
    )

    from core.optimizer import sanear_runs_orfas
    from ui import callbacks  # registra os callbacks

    # O esquema é aplicado na SUBIDA do app. Antes só acontecia ao salvar uma
    # mineração: uma coluna nova (ALTER TABLE em schema.sql) não existia no
    # banco até alguém salvar, e a primeira leitura dela quebrava a tela.
    from core import db_manager
    with db_manager.connect_write() as con:
        db_manager.init_schema(con)

    # o processo está subindo agora: nenhuma mineração pode estar em curso,
    # então qualquer 'rodando' no banco é resto de execução morta
    orfas = sanear_runs_orfas()
    if orfas:
        print(f"  {orfas} minerações órfãs fechadas no banco")

    callbacks.register(app)
    return app


if __name__ == "__main__":
    # PORT permite subir uma segunda instancia lado a lado (conferir um
    # ajuste sem derrubar a que esta aberta). Sem a variavel, 8050 de sempre.
    build().run(debug=False, port=int(os.environ.get("PORT") or 8050))
