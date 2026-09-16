"""Gráficos da varredura: a região, não o campeão.

Os três respondem perguntas diferentes sobre o mesmo conjunto de
combinações:

    histograma -> onde está a massa dos resultados?
    curva      -> platô ou precipício?
    funil      -> qual critério está cortando?

Só figuras: a conta mora em core/mineracao_stats.py.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .. import theme as T
from .analytics_charts import BASE, EIXO, TITULO, _vazio


def _fmt(v: float, moeda: bool) -> str:
    return f"R$ {v:,.0f}" if moeda else f"{v:,.2f}".rstrip("0").rstrip(".")


def histograma(dados: dict, rotulo: str, moeda: bool) -> go.Figure:
    """Quantas combinações caíram em cada faixa de resultado.

    A leitura que decide não é a altura das barras — é **de que lado do zero
    está o corpo da distribuição**. Corpo à direita: região boa, e escolher o
    ponto dentro dela é detalhe. Corpo colado no zero com uma cauda longa à
    direita: região ruim com dois bilhetes premiados, e o campeão é um deles.

    A curva acumulada no eixo da direita responde de imediato quantos por
    cento das combinações ficaram abaixo de qualquer valor — inclusive o zero.
    """
    if not dados or not dados.get("centros"):
        return _vazio("Rode uma mineração.")

    total = sum(dados["contagem"]) or 1
    hover = [f"{_fmt(c, moeda)} a {_fmt(c + dados['largura'], moeda)}"
             f"<br>{n} combinações · {n / total * 100:.1f}%<extra></extra>"
             for c, n in zip(dados["centros"], dados["contagem"])]
    acumulado = (np.cumsum(dados["contagem"]) / total * 100).tolist()

    fig = go.Figure([
        go.Bar(x=dados["centros"], y=dados["contagem"], width=dados["largura"],
               marker=dict(color=[T.POS if c > 0 else T.NEG
                                  for c in dados["centros"]],
                           line=dict(width=0)),
               hovertemplate=hover),
        go.Scatter(x=dados["centros"], y=acumulado, yaxis="y2", mode="lines",
                   line=dict(color=T.ACCENT, width=1.4),
                   hovertemplate="até %{x:,.0f}<br>%{y:.0f}% das combinações"
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
               f"{_fmt(dados['mediana'], moeda)} · "
               f"<span style='color:{T.ACCENT_2}'>média</span> "
               f"{_fmt(dados['media'], moeda)}")
    fora = dados["fora_esq"] + dados["fora_dir"]
    if fora:
        legenda += f" · {fora} fora da faixa"

    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=10, t=44, b=10)},
        title={**TITULO, "text": f"Distribuição — {rotulo}"}, bargap=0,
        xaxis=dict(**EIXO, title=dict(text=rotulo, font=dict(size=10))),
        yaxis=dict(**EIXO, title=dict(text="combinações", font=dict(size=10))),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[0, 100],
                    ticksuffix="%", tickfont=dict(color=T.ACCENT, size=9)),
        annotations=[dict(text=legenda, showarrow=False, xref="paper",
                          yref="paper", x=0, y=1.11, xanchor="left",
                          font=dict(color=T.MUTED, size=10))],
    )
    return fig


def curva(dados: dict, rotulo: str, moeda: bool) -> go.Figure:
    """As combinações ordenadas da melhor para a pior.

    Aqui a FORMA é a informação, não o valor. Descida suave é platô: os
    vizinhos valem quase o mesmo e errar o ponto sai barato. Queda seca nos
    primeiros por cento é precipício: um punhado de combinações carrega a
    região, e escolher entre elas é escolher qual sorte levar para o live.
    """
    if not dados or not dados.get("valores"):
        return _vazio("Rode uma mineração.")

    v = dados["valores"]
    positivos = [x for x in v if x > 0]
    corte = len(positivos) / len(v) * 100 if v else 0

    fig = go.Figure(go.Scatter(
        x=dados["pct"], y=v, mode="lines",
        line=dict(color=T.ACCENT, width=1.8),
        fill="tozeroy", fillcolor="rgba(34,228,255,.09)",
        hovertemplate="melhores %{x:.0f}%<br>%{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=T.LINE, width=1))
    fig.add_hline(y=dados["mediana"],
                  line=dict(color=T.ACCENT_2, width=1, dash="dot"))
    if 0 < corte < 100:
        # onde a curva cruza o zero: a esquerda dele esta a fatia da regiao
        # que lucra, e a largura dessa fatia e a leitura do passo 5
        fig.add_vline(x=corte, line=dict(color=T.POS, width=1, dash="dash"))

    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=10, t=44, b=10)},
        title={**TITULO, "text": f"Ordenadas — {rotulo}"},
        xaxis=dict(**EIXO, title=dict(text="% das combinações, da melhor para a pior",
                                      font=dict(size=10)),
                   range=[0, 100], ticksuffix="%"),
        yaxis=dict(**EIXO, title=dict(text=rotulo, font=dict(size=10))),
        annotations=[dict(
            text=(f"<span style='color:{T.POS}'>{corte:.0f}% acima de zero</span>"
                  f" · <span style='color:{T.ACCENT_2}'>mediana</span> "
                  f"{_fmt(dados['mediana'], moeda)}"),
            showarrow=False, xref="paper", yref="paper", x=0, y=1.11,
            xanchor="left", font=dict(color=T.MUTED, size=10))],
    )
    return fig


def funil(avaliacao: dict) -> go.Figure:
    """Quantos por cento das combinações passam em CADA critério, isolado.

    Cumulativo esconderia o que interessa: com os critérios aplicados em
    sequência, o primeiro sempre parece o mais duro. Isolado, a barra mais
    curta é o critério que realmente manda na seleção — e afrouxá-lo ou
    aceitar menos candidatas vira uma decisão explícita, em vez de um
    resultado que aparece pronto.
    """
    if not avaliacao or not avaliacao.get("por_criterio"):
        return _vazio("Rode uma mineração.")

    # `avaliavel` de fora: um critério ligado que ninguém tinha o dado para
    # responder virava barra vermelha em 0% ao lado de um "todos juntos" em
    # 100% — dizia que estava cortando tudo quando não cortou ninguém
    ativos = [c for c in avaliacao["por_criterio"]
              if c["ativo"] and c.get("avaliavel", True)]
    if not ativos:
        return _vazio("Nenhum critério ligado.")

    rotulos = [c["rotulo"] for c in ativos] + ["<b>todos juntos</b>"]
    valores = [c["pct"] for c in ativos] + [avaliacao["pct"]]
    passam = [c["passam"] for c in ativos] + [avaliacao["n_aprovadas"]]
    gargalo = avaliacao.get("gargalo") or {}

    cores = [T.NEG if c["id"] == gargalo.get("id") else T.ACCENT_DIM
             for c in ativos] + [T.POS if avaliacao["n_aprovadas"] else T.NEG]

    fig = go.Figure(go.Bar(
        x=valores, y=rotulos, orientation="h",
        marker=dict(color=cores, line=dict(width=0)),
        text=[f"{n:,}".replace(",", ".") for n in passam],
        textposition="outside", textfont=dict(color=T.MUTED, size=10),
        hovertemplate="%{y}<br>%{x:.1f}% passam<extra></extra>",
    ))
    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=54, t=34, b=10)},
        title={**TITULO, "text": "Quem passa em cada critério"},
        xaxis=dict(**EIXO, range=[0, 108], ticksuffix="%"),
        yaxis=dict(**EIXO, autorange="reversed"),
        bargap=.35,
    )
    return fig
