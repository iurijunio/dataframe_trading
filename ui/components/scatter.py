"""Dispersão dos parâmetros minerados.

É aqui que o Plotly ganha: WebGL aguenta ~100 mil pontos e o clickData volta
para o callback sem código de cola. O problema dele nunca foi dispersão — era
candlestick.

A leitura que a nuvem entrega e a tabela não: **onde fica a região boa**. Um
ponto verde cercado de vermelho é sorte; uma mancha verde contígua é
parâmetro robusto. Por isso a cor padrão é o score robusto (mediana dos
vizinhos), e não o lucro.
"""

from __future__ import annotations

import plotly.graph_objects as go
from dash import dcc, html

from .. import theme as T

METRICAS = [
    # o MT5 usa fator de recuperacao como criterio padrao de otimizacao;
    # aqui ele e o padrao do eixo Y e da cor pelo mesmo motivo
    ("fator de recuperação", "fr"),
    ("score robusto", "robusto"),
    ("score", "score"),
    ("consistência %", "consistencia"),
    ("mediana por período", "mediana_fold"),
    ("lucro total", "lucro"),
    ("profit factor", "pf"),
    ("drawdown", "dd"),
]

LAYOUT = dict(
    paper_bgcolor=T.SURFACE,
    plot_bgcolor=T.SURFACE,
    font=dict(family="JetBrains Mono, monospace", size=11, color=T.MUTED),
    margin=dict(l=8, r=8, t=8, b=8),
    hoverlabel=dict(bgcolor=T.SURFACE_2, bordercolor=T.ACCENT_DIM,
                    font=dict(color=T.INK, family="JetBrains Mono, monospace")),
    showlegend=False,
)
EIXO = dict(gridcolor=T.LINE_SOFT, zerolinecolor=T.LINE,
            linecolor=T.LINE, tickfont=dict(color=T.MUTED))


def vazio(mensagem="Rode uma mineração para ver a nuvem de parâmetros."):
    fig = go.Figure()
    fig.update_layout(**LAYOUT, xaxis=dict(visible=False), yaxis=dict(visible=False),
                      annotations=[dict(text=mensagem, showarrow=False,
                                        font=dict(color=T.MUTED, size=13))])
    return fig


def _tamanhos(trials, chave="trades", menor=7, maior=22):
    vals = [t.get(chave) or 0 for t in trials]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return [12] * len(vals)
    return [menor + (v - lo) / (hi - lo) * (maior - menor) for v in vals]


def valor(t: dict, chave: str):
    """Um eixo pode ser um parâmetro varrido ou uma métrica do resultado.
    Numa varredura de um parâmetro só, o natural é parâmetro no X e métrica
    no Y - plotar o mesmo parâmetro nos dois eixos dá uma diagonal e nada
    mais."""
    if chave in t["params"]:
        return t["params"][chave]
    return t.get(chave)


def figura(trials: list[dict], eixo_x: str, eixo_y: str, eixo_z: str | None,
           metrica: str) -> go.Figure:
    if not trials or not eixo_x or not eixo_y:
        return vazio()

    def tem(m):
        return [t for t in trials
                if t.get(m) is not None
                and valor(t, eixo_x) is not None and valor(t, eixo_y) is not None]

    validos = tem(metrica)
    provisorio = False
    # o score de vizinhança só existe com a grade completa; enquanto a
    # varredura corre, colore pelo score cru em vez de mostrar tela vazia
    if not validos and metrica == "robusto":
        validos, provisorio = tem("score"), True
        metrica = "score"
    if not validos:
        return vazio("Nenhuma combinação com esta métrica.")

    x = [valor(t, eixo_x) for t in validos]
    y = [valor(t, eixo_y) for t in validos]
    cor = [t[metrica] for t in validos]
    tam = _tamanhos(validos)
    ids = [t["trial_id"] for t in validos]

    hover = [
        f"<b>{t['params_txt']}</b><br>"
        f"score robusto {t['robusto']}<br>"
        f"períodos + {t['folds']} ({t['consistencia']}%)<br>"
        f"mediana/período R$ {t['mediana_fold']:,.0f}<br>"
        f"lucro R$ {t['lucro']:,.0f} · {t['trades']} trades<extra></extra>"
        for t in validos
    ]

    rotulo = metrica + (" (bruto)" if provisorio else "")
    barra = dict(title=dict(text=rotulo, font=dict(color=T.MUTED, size=10)),
                 thickness=10, outlinewidth=0,
                 tickfont=dict(color=T.MUTED, size=10))
    # RdYlGn como o PRD pede, mas ANCORADO NO ZERO (cmid=0).
    #
    # Sem isso a escala se normaliza pelo lote: numa varredura em que tudo é
    # ruim, a menos ruim sai verde-vivo. Você clica no ponto verde e o
    # backtest é péssimo — a cor estava dizendo "melhor destas", não "boa".
    # Com o zero fixo no amarelo, verde é lucro e vermelho é prejuízo, sempre,
    # e uma nuvem inteiramente amarelo-alaranjada diz a verdade: não há nada.
    marcador = dict(size=tam, color=cor, colorscale="RdYlGn", cmid=0,
                    showscale=True, colorbar=barra,
                    line=dict(width=0.5, color=T.LINE))

    if eixo_z:
        z = [valor(t, eixo_z) for t in validos]
        fig = go.Figure(go.Scatter3d(
            x=x, y=y, z=z, mode="markers", marker=marcador,
            customdata=ids, hovertemplate=hover, text=hover))
        cena = dict(bgcolor=T.SURFACE,
                    xaxis=dict(title=eixo_x, **EIXO, backgroundcolor=T.SURFACE),
                    yaxis=dict(title=eixo_y, **EIXO, backgroundcolor=T.SURFACE),
                    zaxis=dict(title=eixo_z, **EIXO, backgroundcolor=T.SURFACE))
        fig.update_layout(**LAYOUT, scene=cena)
    else:
        fig = go.Figure(go.Scattergl(
            x=x, y=y, mode="markers", marker=marcador,
            customdata=ids, hovertemplate=hover, text=hover))
        fig.update_layout(**LAYOUT,
                          xaxis=dict(title=eixo_x, **EIXO),
                          yaxis=dict(title=eixo_y, **EIXO))
    return fig


def corpo():
    """Controles e nuvem. Vive dentro da aba Dispersão do painel de análise —
    por isso não traz cabeçalho próprio."""
    dd = lambda i, ph: dcc.Dropdown(id=i, options=[], placeholder=ph,
                                    className="dd dd-sm")
    return [
        html.Div(
            [dd("sc-x", "eixo X"), dd("sc-y", "eixo Y"), dd("sc-z", "eixo Z (3D)"),
             dcc.Dropdown(id="sc-metrica", className="dd dd-sm",
                          value="fr", clearable=False,
                          options=[{"label": r, "value": v} for r, v in METRICAS])],
            className="aba-tools",
        ),
        dcc.Graph(id="scatter", figure=vazio(), className="graph",
                  config={"displayModeBar": False, "responsive": True}),
    ]
