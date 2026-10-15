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
from ui.components import (analytics_charts, ao_vivo_panel, candidata_panel,
                           controls,
                           estrategias_panel, mining, portfolio_panel,
                           results_grid, stats_cards, wfa_panel)

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
                    # dcc.Tabs, nao RadioItems: o RadioItems do Dash 4
                    # reenviava o valor antigo e o menu voltava sozinho.
                    dcc.Tabs(
                        id="modo", value="backtest", className="modo",
                        parent_className="modo-pai",
                        content_style={"display": "none"},
                        children=[
                            dcc.Tab(label=r, value=v, className="modo-aba",
                                    selected_className="modo-aba-sel")
                            for r, v in [("Backtest", "backtest"),
                                         ("Mineração", "mineracao"),
                                         ("Walk-Forward", "wfa"),
                                         ("Candidata", "candidata"),
                                         ("Estratégias", "estrategias"),
                                         ("Portfólio", "portfolio"),
                                         ("Ao vivo", "aovivo")]],
                    ),
                ],
                className="brand-wrap",
            ),
            # O cartao "periodo" ja diz a janela medida, e o tempo do motor
            # nao ajuda a decidir nada - o cabecalho fica so com a identidade.
            html.Span(id="meta-tempo", style={"display": "none"}),
            html.Div(
                [
                    html.Button(id="reotimizar-selo",
                                className="reotimizar-selo", n_clicks=0,
                                style={"display": "none"}),
                    html.Div(id="reotimizar-lista",
                             className="reotimizar-lista",
                             style={"display": "none"}),
                ],
                className="reotimizar-wrap",
            ),
            html.Div(
                [
                    # o selo e o botão juntos: com a captura ativa o botão
                    # desliga, e o selo ao lado diz por quê
                    html.Span(id="captura-selo", className="captura-selo",
                              style={"display": "none"}),
                    # parte 4: o Envio de ordens, ao lado da captura que o faz
                    html.Span(id="ord-selo", className="ord-selo"),
                    html.Button("Sincronizar com MT5", id="btn-mt5-sync",
                                n_clicks=0, className="btn-ghost"),
                    html.Span(id="mt5-sync-status", className="mt5-sync-status"),
                    # o aviso antes do botão: o botão de pânico fica sempre
                    # no mesmo lugar, no canto, e não anda quando o aviso muda
                    html.Span(id="ord-zerar-aviso", className="ord-zerar-aviso"),
                    html.Button(
                        "⏻ Zerar tudo e desligar envio", id="ord-zerar",
                        n_clicks=0, className="ord-zerar",
                        title="Encerra todas as posições da automação e "
                              "desliga o Envio de ordens de todas as contas. "
                              "Posições abertas fora da automação não são "
                              "tocadas. Clique duas vezes para confirmar."),
                ],
                className="mt5-sync-wrap",
            ),
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

            estrategias_panel.painel(),

            portfolio_panel.painel(),
            ao_vivo_panel.painel(),
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
            # qual portfolio esta aberto na tela de Portfólio - sobrevive
            # entre re-renders de Adicionar/Remover variante
            dcc.Store(id="store-portfolio-aberto"),
            # so pulsa enquanto a mineracao corre; ver callbacks.pulso
            dcc.Interval(id="tick", interval=800, disabled=True),
            # selo da captura no topo: 30 s bastam para "parada há N min"
            dcc.Interval(id="captura-intervalo", interval=30_000),
            # a última conferência do dia que o calendário já viu
            dcc.Store(id="captura-conferencia-vista"),
            # parte 4: o selo das ordens e o alarme leem o estado.json a cada
            # 2 s em QUALQUER aba — um chamado não pode esperar 30 s
            dcc.Interval(id="ord-intervalo", interval=2000),
            # o primeiro clique do "Zerar tudo" arma; o segundo, em 5 s, faz
            # (guarda a HORA do primeiro clique: o servidor recusa confirmar
            # um armado de mais de 6 s)
            dcc.Store(id="ord-armado", data=None),
            # o alarme: `assets/alarme.js` observa estes atributos (bipe por
            # chamado novo e título da aba piscando). Na raiz do layout para
            # valer em qualquer aba.
            html.Div(id="ord-alarme", style={"display": "none"},
                     **{"data-alarme": "0", "data-chaves": ""}),
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
