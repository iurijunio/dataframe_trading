"""Subtela Mineração › Busca automática (contrato: layout B, 03/11/2026).

A tela inteira — faixa de andamento, mapa de nichos, lista, espaço de busca,
trilho de controle, gaveta do nicho e confirmação — é desenhada por
`ui/assets/busca.js` dentro de `busca-raiz`, a partir do comportamento do
protótipo aprovado. O Dash só leva DADOS para lá e traz CLIQUES de volta:

  busca-dados    servidor -> tela   estado, mapas, lista, trilho, espaço
  busca-detalhe  servidor -> tela   o detalhe do nicho aberto na gaveta
  busca-acao     tela -> servidor   iniciar, pausar, núcleos, excluir…
  busca-pedido   tela -> servidor   abrir o detalhe de uma casa
  busca-ir       tela -> servidor   abrir o campeão no Backtest / minerar a região

Por que assim: o protótipo já resolveu teclado, foco preso, tooltip, pulso da
casa nova e a gaveta; refazer isso em componentes do Dash seria reescrever o
contrato e arriscar desvio. `busca-raiz` nunca é Output de callback — o React
não toca no que o JS desenhou lá dentro.
"""

from __future__ import annotations

from dash import dcc, html

INTERVALO_MS = 2000


def painel() -> html.Div:
    return html.Div(
        [
            dcc.Interval(id="busca-relogio", interval=INTERVALO_MS),
            dcc.Store(id="busca-sel"),          # a busca aberta (None = a ativa/última)
            dcc.Store(id="busca-dados"),
            dcc.Store(id="busca-detalhe"),
            dcc.Store(id="busca-acao"),
            dcc.Store(id="busca-pedido"),
            dcc.Store(id="busca-ir"),
            dcc.Store(id="busca-feito"),        # conta ações atendidas: força leitura
            html.Div(id="busca-raiz", className="busca", role="region",
                     **{"aria-label": "Busca automática"}),
        ],
        className="busca-wrap",
    )
