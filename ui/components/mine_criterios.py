"""Aba Critérios: o filtro que você definiu antes de olhar o resultado.

O ponto do passo 7 não é ter números bonitos — é ter números **fixos**. Sem
eles a régua estica para acomodar a combinação de que você gostou, e a
seleção deixa de ser seleção.

A tela tem três partes: os limiares à esquerda, o veredito em cartões, e a
lista das aprovadas — que é clicável, porque o que se faz depois de aprovar é
carregar a combinação e olhar o backtest dela.
"""

from __future__ import annotations

import dash_ag_grid as dag
from dash import dcc, html

from core.mineracao_stats import CRITERIOS

from .cartao import brl, card, dica, inteiro, num

BRL = {"function": "params.value == null ? '' : params.value.toLocaleString('pt-BR',"
                   "{minimumFractionDigits:2,maximumFractionDigits:2})"}
N2 = {"function": "params.value == null ? '—' : params.value.toFixed(2)"}

COLUNAS = [
    {"field": "n", "headerName": "#", "width": 62, "pinned": "left"},
    {"field": "params_txt", "headerName": "combinação", "flex": 1,
     "minWidth": 200, "pinned": "left", "cellClass": "col-params"},
    {"field": "robusto", "headerName": "score robusto", "width": 122,
     "type": "numericColumn", "valueFormatter": N2,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "consistencia", "headerName": "janelas +", "width": 100,
     "type": "numericColumn"},
    {"field": "fr", "headerName": "fator recup.", "width": 112,
     "type": "numericColumn", "valueFormatter": N2},
    {"field": "pf", "headerName": "PF", "width": 78,
     "type": "numericColumn", "valueFormatter": N2},
    {"field": "lucro", "headerName": "lucro total", "width": 118,
     "type": "numericColumn", "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "dd", "headerName": "drawdown", "width": 110,
     "type": "numericColumn", "valueFormatter": BRL},
    {"field": "trades", "headerName": "trades", "width": 92,
     "type": "numericColumn"},
]


def campos():
    """Os limiares. Cada um com o (?) dizendo o que é e de onde vem a faixa."""
    linhas = []
    for c in CRITERIOS:
        rotulo = c["rotulo"] + (f" ({c['sufixo']})" if c["sufixo"] else "")
        linhas.append(html.Div(
            [
                html.Label([rotulo, dica(c["dica"])], className="fld-label"),
                # debounce em SEGUNDOS (o Dash conta em segundos, nao em
                # milissegundos): meio segundo depois da ultima tecla o
                # filtro se aplica sozinho. Com `debounce=True` o valor so
                # ia embora ao perder o foco, e digitar o limiar sem clicar
                # fora deixava a tela mostrando o veredito do numero
                # anterior - pior que nao filtrar, porque parece filtrado.
                dcc.Input(id=f"crit-{c['id']}", type="number", value=c["padrao"],
                          step=c["passo"], className="inp", debounce=0.5),
                html.Span("≥" if c["maior"] else "≤", className="crit-op"),
            ],
            className="crit-linha",
        ))
    return html.Div(
        [
            html.Div([html.H3("Critérios de aceite", className="grp"),
                      dica("Os números mínimos que uma combinação precisa "
                           "atingir para virar candidata. Definidos ANTES de "
                           "olhar o resultado: é isso que impede a régua de "
                           "esticar depois, para acomodar a combinação de que "
                           "você gostou. Deixe um campo vazio para desligar "
                           "aquele critério.")],
                     className="secao-head"),
            html.Div(linhas, className="crit-campos"),
        ],
        className="crit-form",
    )


def vazio(msg="Rode uma mineração para aplicar os critérios."):
    return html.Div(html.P(msg, className="empty"), className="cards")


def resumo(av: dict, n_listadas: int | None = None) -> html.Div:
    """O veredito em três cartões.

    `n_listadas` é quantas aprovadas cabem na tabela clicável abaixo. Ele
    difere de `n_aprovadas` quando a varredura passa de 5.000 combinações: a
    contagem vale sobre todas, a lista só sobre as que a tabela carrega.
    """
    if not av:
        return vazio()

    gargalo = av.get("gargalo")
    sem_dado = av.get("sem_dado") or []
    n = av["n_aprovadas"]
    nota_lista = (f"de {inteiro(av['total'])} · {num(av['pct'], 1)}% da região")
    if n_listadas is not None and n_listadas != n:
        nota_lista += f" · {inteiro(n_listadas)} na lista abaixo"
    return html.Div(
        [
            card("combinações aprovadas", inteiro(n),
                 "Quantas combinações da varredura passam em TODOS os "
                 "critérios ligados ao mesmo tempo. Zero não significa "
                 "estratégia ruim — significa que esta região não atende ao "
                 "que você exigiu. Poucas aprovadas num universo grande é "
                 "sinal de que você está perto de escolher um ponto por "
                 "sorte; muitas aprovadas é platô.",
                 "pos" if n else "neg", nota_lista, largo=True),
            card("critério que mais corta",
                 gargalo["rotulo"] if gargalo else "nenhum reprova",
                 "O critério ligado com a menor taxa de aprovação — o que "
                 "realmente manda na seleção. Se ele sozinho já reprova quase "
                 "tudo, a decisão é sua e fica explícita: afrouxar o limiar, "
                 "ou aceitar que esta região não serve. Quando ninguém "
                 "reprova, os limiares estão frouxos para esta região — o que "
                 "é ótimo se a região for grande, e suspeito se ela for "
                 "pequena e você a escolheu depois de ver o resultado.",
                 "warn" if gargalo and gargalo["pct"] < 20 else None,
                 (f"só {num(gargalo['pct'], 0)}% passam nele" if gargalo
                  else ("sem dado: " + " · ".join(sem_dado) if sem_dado
                        else "todas passam em todos os limiares")),
                 largo=True, texto=True),
            card("aproveitamento", f"{num(av['pct'], 1)}%",
                 "Percentual da região que vira candidata. Não existe faixa "
                 "certa: o que ela informa é o tipo de achado. Aproveitamento "
                 "alto num universo grande é platô — bom sinal. "
                 "Aproveitamento de fração de por cento significa que as "
                 "aprovadas são exceções dentro da própria região, e exceção "
                 "não costuma se repetir fora da amostra.",
                 None, f"{inteiro(n)} de {inteiro(av['total'])}"),
        ],
        className="cards cards-crit",
    )


def tabela(aprovadas: list[dict]) -> html.Div:
    return html.Div(
        [
            html.Div([html.H3("Combinações aprovadas", className="grp"),
                      dica("As que passaram em todos os critérios, ordenadas "
                           "pelo score robusto (mediana dos vizinhos na "
                           "grade). Clicar numa linha carrega os parâmetros "
                           "nos campos e roda o backtest dela — que é o passo "
                           "seguinte: olhar a combinação de perto antes de "
                           "salvar a mineração.")],
                     className="secao-head"),
            dag.AgGrid(
                id="grid-aprovadas",
                columnDefs=COLUNAS,
                rowData=aprovadas,
                className="ag-theme-alpine-dark grid-trades",
                dashGridOptions={
                    "rowSelection": "single", "animateRows": False,
                    "rowHeight": 30, "headerHeight": 34, "suppressCellFocus": True,
                    "localeText": {"noRowsToShow":
                                   "Nenhuma combinação passa em todos os critérios."},
                },
                defaultColDef={"sortable": True, "filter": True, "resizable": True},
                style={"height": "100%", "width": "100%"},
            ),
        ],
        className="crit-tabela",
    )


def painel():
    """O layout fixo da aba. Os miolos vêm por callback."""
    return html.Div(
        [
            campos(),
            html.Div(
                [
                    html.Div(vazio(), id="crit-resumo"),
                    dcc.Graph(id="g-crit-funil", className="graf-crit",
                              config={"displayModeBar": False, "responsive": True}),
                    tabela([]),
                ],
                className="crit-saida",
            ),
        ],
        className="aba-criterios",
    )
