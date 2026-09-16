"""Gráficos de diagnóstico do backtest.

Só figuras: o cálculo mora em core/analytics.py e não sabe que existe tela.

Uma convenção que vale em todos: **barra colorida pelo sinal, não pela
categoria**. Verde é lucro, vermelho é prejuízo, sempre — assim a leitura é
imediata e não depende de legenda. Onde há duas medidas (total e expectativa
por trade), a expectativa vira linha sobre as barras, porque é ela que decide
um corte: um horário com 400 trades e −R$ 2 cada sangra mais que um com 3
trades e −R$ 90.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from dash import dcc, html

from .. import theme as T

BASE = dict(
    paper_bgcolor=T.SURFACE, plot_bgcolor=T.SURFACE,
    font=dict(family="JetBrains Mono, monospace", size=11, color=T.MUTED),
    margin=dict(l=10, r=10, t=28, b=10), showlegend=False,
    # vírgula decimal e ponto de milhar em hovers e eixos: "1.234,56", e não
    # "1,234.56" — o formato `%{y:,.2f}` segue estes separadores
    separators=",.",
    hoverlabel=dict(bgcolor=T.SURFACE_2, bordercolor=T.ACCENT_DIM,
                    font=dict(color=T.INK, family="JetBrains Mono, monospace")),
)
EIXO = dict(gridcolor=T.LINE_SOFT, zerolinecolor=T.LINE, linecolor=T.LINE,
            tickfont=dict(color=T.MUTED))
TITULO = dict(font=dict(color=T.INK_2, size=12.5, family="Archivo"), x=0, xanchor="left")


def _vazio(msg="Rode um backtest."):
    fig = go.Figure()
    fig.update_layout(**BASE, xaxis=dict(visible=False), yaxis=dict(visible=False),
                      annotations=[dict(text=msg, showarrow=False,
                                        font=dict(color=T.MUTED, size=12))])
    return fig


def _cores(vals):
    return [T.POS if v > 0 else T.NEG for v in vals]


def barras(dados: dict, titulo: str, com_expectativa=True) -> go.Figure:
    if not dados or not dados["chaves"]:
        return _vazio()

    hover = [f"<b>{k}</b><br>líquido R$ {v:,.0f}<br>{n} trades<br>"
             f"R$ {e:,.1f}/trade · {w:.0f}% acerto<extra></extra>"
             for k, v, n, e, w in zip(dados["chaves"], dados["liquido"],
                                      dados["trades"], dados["expectativa"],
                                      dados["win_rate"])]
    fig = go.Figure(go.Bar(
        x=dados["chaves"], y=dados["liquido"],
        marker=dict(color=_cores(dados["liquido"]), line=dict(width=0)),
        hovertemplate=hover, opacity=.9,
    ))
    if com_expectativa:
        fig.add_trace(go.Scatter(
            x=dados["chaves"], y=dados["expectativa"], yaxis="y2",
            mode="lines+markers", line=dict(color=T.ACCENT, width=1.5),
            marker=dict(size=5), hoverinfo="skip",
        ))
    fig.update_layout(
        **BASE, title={**TITULO, "text": titulo},
        xaxis=dict(**EIXO, type="category"),
        yaxis=dict(**EIXO, title=dict(text="R$", font=dict(size=10))),
        yaxis2=dict(overlaying="y", side="right", showgrid=False,
                    tickfont=dict(color=T.ACCENT, size=9),
                    title=dict(text="R$/trade", font=dict(size=9, color=T.ACCENT))),
        bargap=.25,
    )
    return fig


def ganho_perda(dados: dict, titulo: str) -> go.Figure:
    """Ganho bruto ao lado do prejuízo bruto, por grupo.

    O saldo sozinho engana: um horário que fecha em zero pode ter girado
    R$ 20 mil de cada lado — muito trade, muito custo, nenhum resultado. As
    duas barras mostram a rotatividade; a linha do saldo diz o que sobrou.
    """
    if not dados or not dados["chaves"]:
        return _vazio()

    hover = [f"<b>{k}</b><br>ganho R$ {g:,.0f} · prejuízo R$ {p:,.0f}"
             f"<br>saldo R$ {v:,.0f} · {n} trades<br>{w:.0f}% acerto<extra></extra>"
             for k, g, p, v, n, w in zip(dados["chaves"], dados["ganhos"],
                                         dados["perdas"], dados["liquido"],
                                         dados["trades"], dados["win_rate"])]
    fig = go.Figure([
        go.Bar(x=dados["chaves"], y=dados["ganhos"], name="ganho",
               marker=dict(color=T.POS, line=dict(width=0)),
               hovertemplate=hover, opacity=.85),
        # prejuízo também cresce para cima: as duas barras ficam na mesma
        # base e a comparação vira altura contra altura, que o olho lê de
        # imediato. A cor já diz o sinal; espelhar para baixo só obrigava a
        # medir dois lados de um eixo.
        go.Bar(x=dados["chaves"], y=dados["perdas"], name="prejuízo",
               marker=dict(color=T.NEG, line=dict(width=0)),
               hovertemplate=hover, opacity=.85),
        go.Scatter(x=dados["chaves"], y=dados["liquido"], name="saldo",
                   mode="lines+markers", line=dict(color=T.ACCENT, width=1.5),
                   marker=dict(size=5), hoverinfo="skip"),
    ])
    fig.update_layout(
        **BASE, title={**TITULO, "text": titulo}, barmode="group", bargap=.22,
        xaxis=dict(**EIXO, type="category"),
        yaxis=dict(**EIXO, title=dict(text="R$", font=dict(size=10))),
    )
    return fig


def escala_no_zero(valores) -> tuple[list, float, float]:
    """Vermelho abaixo de zero, verde acima — sem amarelo no meio.

    `RdYlGn` com `zmid=0` pinta o zero de amarelo, e amarelo lê-se como
    "morno", não como "empatou ou perdeu". Aqui a virada é seca no zero:
    negativos são tons de vermelho, positivos tons de verde, e um mês de
    prejuízo nunca se disfarça de neutro.
    """
    finitos = [v for linha in valores for v in linha
               if v is not None and v == v]           # descarta NaN
    if not finitos:
        return "RdYlGn", None, None
    lo, hi = min(finitos), max(finitos)
    if lo >= 0:
        return [[0, "#0B3B2A"], [1, T.POS]], 0, max(hi, 1)
    if hi <= 0:
        return [[0, T.NEG], [1, "#4A1526"]], min(lo, -1), 0
    t = (0 - lo) / (hi - lo)          # onde o zero cai na escala normalizada
    return ([[0.0, "#7A0B25"], [max(t - 1e-4, 0.0), T.NEG],
             [min(t + 1e-4, 1.0), "#7BE8B6"], [1.0, T.POS]], lo, hi)


def calendario(dados: dict, titulo="Lucro por mês") -> go.Figure:
    if not dados or not dados["anos"]:
        return _vazio()
    escala, lo, hi = escala_no_zero(dados["valores"])
    fig = go.Figure(go.Heatmap(
        z=dados["valores"], x=dados["meses"], y=dados["anos"],
        colorscale=escala, zmin=lo, zmax=hi, xgap=2, ygap=2,
        hovertemplate="%{y} %{x}<br>R$ %{z:,.0f}<extra></extra>",
        colorbar=dict(thickness=8, outlinewidth=0,
                      tickfont=dict(color=T.MUTED, size=9)),
    ))
    fig.update_layout(**BASE, title={**TITULO, "text": titulo},
                      xaxis=dict(**EIXO, side="top"),
                      yaxis=dict(**EIXO, autorange="reversed"))
    return fig


def histograma(dados: dict, titulo="Distribuição dos resultados") -> go.Figure:
    """Quantos trades caíram em cada faixa de resultado.

    Barras coladas (bargap 0) e largura de balde redonda: assim a silhueta da
    distribuição aparece como uma forma, e não como um serrilhado de colunas
    soltas.

    Duas escolhas que este gráfico já não faz mais, porque numa célula de 430
    por 290 pixels elas o tornavam ilegível: as marcações de mediana e média
    eram rótulos escritos DENTRO da área do gráfico, e caíam uma por cima da
    outra sempre que os dois valores ficavam próximos — que é o caso comum.
    Agora as linhas continuam, os rótulos foram para o topo em uma linha só.
    E como estratégia com stop e alvo fixos produz uma distribuição de picos
    (quase todo trade termina exatamente no stop ou exatamente no alvo), a
    curva acumulada foi para o eixo da direita: ela lê bem justamente onde as
    barras não leem, e responde de imediato "quantos por cento dos trades
    perderam dinheiro".
    """
    if not dados or not dados["centros"]:
        return _vazio()

    total = sum(dados["contagem"]) or 1
    hover = [f"R$ {c:,.0f} a R$ {c + dados['largura']:,.0f}"
             f"<br>{n} trades · {n / total * 100:.1f}%<extra></extra>"
             for c, n in zip(dados["centros"], dados["contagem"])]

    acumulado = (np.cumsum(dados["contagem"]) / total * 100).tolist()
    fig = go.Figure([
        go.Bar(x=dados["centros"], y=dados["contagem"], width=dados["largura"],
               marker=dict(color=_cores(dados["centros"]), line=dict(width=0)),
               hovertemplate=hover),
        go.Scatter(x=dados["centros"], y=acumulado, yaxis="y2", mode="lines",
                   line=dict(color=T.ACCENT, width=1.4),
                   hovertemplate="até R$ %{x:,.0f}<br>%{y:.0f}% dos trades"
                                 "<extra></extra>"),
    ])
    # so quando o zero cai DENTRO da faixa: fora dela, a linha estica o eixo
    # e espreme os dados num canto - numa varredura em que tudo lucra, dois
    # tercos do grafico viravam vazio
    if min(dados["centros"]) <= 0 <= max(dados["centros"]):
        fig.add_vline(x=0, line=dict(color=T.LINE, width=1))
    for valor, cor in ((dados["mediana"], T.ACCENT), (dados["media"], T.ACCENT_2)):
        fig.add_vline(x=valor, line=dict(color=cor, width=1, dash="dot"))

    legenda = (f"<span style='color:{T.ACCENT}'>mediana</span> "
               f"R$ {dados['mediana']:,.0f} · "
               f"<span style='color:{T.ACCENT_2}'>média</span> "
               f"R$ {dados['media']:,.0f}")
    fora = dados["fora_esq"] + dados["fora_dir"]
    if fora:
        legenda += f" · {fora} fora da faixa"

    fig.update_layout(
        # margem superior maior: a legenda mora acima da área de plotagem,
        # onde nao disputa espaco com as barras
        **{**BASE, "margin": dict(l=10, r=10, t=44, b=10)},
        title={**TITULO, "text": titulo}, bargap=0,
        xaxis=dict(**EIXO, title=dict(
            text=f"resultado do trade · baldes de R$ {dados['largura']:,.0f}",
            font=dict(size=10))),
        yaxis=dict(**EIXO, title=dict(text="trades", font=dict(size=10))),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[0, 100],
                    ticksuffix="%", tickfont=dict(color=T.ACCENT, size=9)),
        annotations=[dict(text=legenda, showarrow=False, xref="paper",
                          yref="paper", x=0, y=1.11, xanchor="left",
                          font=dict(color=T.MUTED, size=10))],
    )
    return fig


def mae_mfe(diag: dict, stop: int, alvo: int) -> go.Figure:
    """MAE × MFE, um ponto por trade.

    As linhas de stop e alvo cortam o gráfico: pontos à direita da linha de
    stop são trades que encostaram nele; acima da de alvo, os que chegaram
    lá. É onde se vê, de um golpe, se o stop está no lugar errado.
    """
    if not diag or not diag["mae"]:
        return _vazio()

    cor = [T.POS if g else T.NEG for g in diag["ganhou"]]
    fig = go.Figure(go.Scattergl(
        x=diag["mae"], y=diag["mfe"], mode="markers",
        marker=dict(size=5, color=cor, opacity=.55, line=dict(width=0)),
        customdata=diag["liquido"],
        hovertemplate="contra %{x:.0f} pts · a favor %{y:.0f} pts"
                      "<br>R$ %{customdata:,.2f}<extra></extra>",
    ))
    if stop:
        fig.add_vline(x=stop, line=dict(color=T.NEG, width=1, dash="dash"),
                      annotation_text="stop", annotation_position="top",
                      annotation_font=dict(color=T.NEG, size=9))
    if alvo:
        fig.add_hline(y=alvo, line=dict(color=T.POS, width=1, dash="dash"),
                      annotation_text="alvo", annotation_position="right",
                      annotation_font=dict(color=T.POS, size=9))
    fig.update_layout(
        **BASE, title={**TITULO, "text": "Excursão de cada trade (MAE × MFE)"},
        xaxis=dict(**EIXO, title=dict(text="pontos contra (MAE)", font=dict(size=10))),
        yaxis=dict(**EIXO, title=dict(text="pontos a favor (MFE)", font=dict(size=10))),
    )
    return fig


# ------------------------------------------------------------------ layout
def _graf(id_):
    return dcc.Graph(id=id_, figure=_vazio(), className="graf-diag",
                     config={"displayModeBar": False, "responsive": True})


def abas(operacoes=None):
    """Cartões e curva de capital continuam sempre visíveis; o diagnóstico
    fica em abas para não virar uma parede de gráficos."""
    return dcc.Tabs(
        id="abas-diag", value="operacoes", className="abas",
        parent_className="abas-wrap",
        # sem content_className o div que o Dash cria fica sem altura definida
        # e o conteúdo transborda o painel, sem rolagem
        content_className="abas-corpo", children=[
            dcc.Tab(label="Operações", value="operacoes",
                    className="aba", selected_className="aba-on",
                    children=html.Div(operacoes, id="aba-operacoes",
                                      className="aba-corpo")),
            dcc.Tab(label="Tempo", value="tempo",
                    className="aba", selected_className="aba-on",
                    children=html.Div(
                        [_graf("g-hora"), _graf("g-dia"),
                         _graf("g-mes"), _graf("g-calendario")],
                        className="aba-corpo grade-diag")),
            dcc.Tab(label="Detalhes", value="detalhes",
                    className="aba", selected_className="aba-on",
                    children=html.Div(id="aba-detalhes",
                                      className="aba-corpo")),
            dcc.Tab(label="Robustez", value="robustez",
                    className="aba", selected_className="aba-on",
                    children=html.Div(id="aba-robustez",
                                      className="aba-corpo")),
            dcc.Tab(label="Gestão", value="gestao",
                    className="aba", selected_className="aba-on",
                    children=html.Div(
                        [html.Div(id="diag-sugestoes", className="sugestoes"),
                         _graf("g-maemfe"), _graf("g-duracao"),
                         _graf("g-motivo"), _graf("g-distribuicao")],
                        className="aba-corpo grade-diag")),
        ])
