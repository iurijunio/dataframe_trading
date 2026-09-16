"""Aba Porteira: a varredura inteira passa, ou não passa?

Duas partes, e a ordem importa:

1. **O veredito** — um selo grande, com os portões que reprovaram. É o que
   se lê primeiro e, na maioria das vezes, o único que se precisa ler.
2. **Os números** — total, positivos, negativos, média, desvio, Z-score e o
   limite de três desvios. É onde se olha quando o veredito surpreende.

Cada número tem o seu **(?)**: sem faixa de referência, "Z = 1,8" não
sustenta decisão nenhuma.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from dash import dcc, html

from .. import theme as T
from .analytics_charts import BASE, EIXO, TITULO, _vazio
from .cartao import brl, card, dica, faixa, inteiro, num


def vazio(msg="Rode uma mineração para passar pela porteira."):
    return html.Div(html.P(msg, className="empty"), className="cards")


# como formatar o valor de cada portão — pelo id, e não adivinhando pelo
# nome ou pelo `is_integer()` do valor (que fazia um cv de exatamente 2,0
# imprimir "2" e uma assimetria de 0,0 imprimir "0")
FORMATO = {
    "amostra da varredura": "n",
    "média da região": "R$",
    "combinações lucrativas": "%",
    "Z-score da região": "num",
    "campeão dentro da região": "x",
    "dispersão (σ ÷ média)": "num",
    "assimetria da distribuição": "num",
    "combinações com amostra fraca": "%",
}


def _fmt(p) -> str:
    v = p["valor"]
    if v is None:
        return "—"
    if isinstance(v, float) and not np.isfinite(v):
        return "∞" if v > 0 else "−∞"
    # o portão dos N desvios tem o N no nome, então casa pelo prefixo
    tipo = FORMATO.get(p["nome"], "R$" if "desvios" in p["nome"] else "num")
    if tipo == "R$":
        return brl(v)
    if tipo == "%":
        return f"{num(v, 1)}%"
    if tipo == "x":
        return f"{num(v, 1)}×"
    if tipo == "n":
        return inteiro(int(v))
    return num(v, 2)


# ------------------------------------------------------------------ veredito
def selo(av: dict, truncada: int = 0) -> html.Div:
    """O carimbo. Verde passa, amarelo passa com ressalva, vermelho barra."""
    estado, cor = av["estado"], av["cor"]
    reprovados = av["reprovados"]
    ressalvas = av["ressalvas"]

    if reprovados:
        motivo = "reprovada em: " + " · ".join(p["nome"] for p in reprovados)
    elif ressalvas:
        motivo = "ressalvas em: " + " · ".join(p["nome"] for p in ressalvas)
    else:
        motivo = "passou em todos os portões"
    if truncada > 0:
        # a tabela abaixo mostra as 5.000 melhores; a porteira usou todas
        motivo += (f" · estatística sobre as {inteiro(av['estatisticas']['avaliadas'])} "
                   f"combinações, {inteiro(truncada)} a mais que a tabela exibe")

    return html.Div(
        [
            html.Div([
                html.Span([
                    "veredito da varredura",
                    dica("O carimbo da porteira. **Reprovada** significa que "
                         "algum portão crítico falhou — não vale seguir para "
                         "os testes de robustez, porque o problema não está "
                         "no ponto escolhido e sim na região inteira. "
                         "**Aprovada com ressalva** passa nos críticos mas "
                         "falha em algum alerta: dá para seguir sabendo onde "
                         "está a fragilidade. **Aprovada** passou em tudo. "
                         "Reprovar por não atingir três sigma seria reprovar "
                         "quase toda varredura real — por isso esse portão é "
                         "ressalva, e não crítico."),
                ], className="card-label"),
                html.Span(estado, className=f"selo-valor {cor}"),
                html.Span(motivo, className="selo-motivo"),
            ], className="selo-texto"),
            html.Div(f"{av['n_ok']}/{av['n_portoes']}", className=f"selo-nota {cor}"),
        ],
        className=f"selo selo-{cor}",
    )


def tabela_portoes(av: dict) -> html.Div:
    linhas = []
    for p in av["portoes"]:
        marca = "✓" if p["ok"] else ("✕" if p["critico"] else "!")
        classe = "ok" if p["ok"] else ("falha" if p["critico"] else "alerta")
        linhas.append(html.Div(
            [
                html.Span(marca, className=f"portao-marca {classe}"),
                html.Span([p["nome"], dica(p["dica"])], className="portao-nome"),
                html.Span(_fmt(p), className=f"portao-valor {classe}"),
                html.Span(p["exigido"], className="portao-exigido"),
                html.Span("crítico" if p["critico"] else "alerta",
                          className=f"portao-tipo {'crit' if p['critico'] else ''}"),
            ],
            className="portao",
        ))
    return html.Div([
        html.Div([html.H3("Portões", className="grp"),
                  dica("Os portões críticos barram a varredura: falhar num "
                       "deles significa que a região não serve, e insistir no "
                       "ponto escolhido é escolher o sobreajuste. Os alertas "
                       "não barram — apontam onde a varredura é frágil, para "
                       "você seguir sabendo do que.")],
                 className="secao-head"),
        html.Div(linhas, className="portoes"),
    ], className="bloco-portoes")


# ----------------------------------------------------------------- os números
def numeros(e: dict) -> html.Div:
    # o Z pode ser infinito nos DOIS sentidos: sem dispersão, uma região toda
    # positiva dá +inf e uma toda negativa dá −inf
    z_fin = e["z"] if np.isfinite(e["z"]) else None
    z_txt = num(z_fin, 2) if z_fin is not None else ("∞" if e["z"] > 0 else "−∞")
    return html.Div(
        [
            card("total de resultados", inteiro(e["avaliadas"]),
                 "Quantas combinações a varredura produziu com resultado "
                 "válido. É o N de toda a estatística desta aba. Abaixo de 30 "
                 "nada aqui descreve uma 'região' — descreve meia dúzia de "
                 "pontos soltos.",
                 None,
                 (f"{inteiro(e['sem_trades'])} sem operações · "
                  f"{inteiro(e['amostra_fraca'])} com amostra fraca")
                 if (e["sem_trades"] or e["amostra_fraca"]) else "combinações válidas",
                 largo=True),
            card("resultados positivos", inteiro(e["positivos"]),
                 "Combinações que fecharam no azul. Junto com o percentual ao "
                 "lado, é a medida mais direta de platô: região em que a "
                 "maioria dos pontos funciona é região em que errar a escolha "
                 "sai barato.",
                 "pos" if e["positivos"] else None,
                 f"{num(e['pct_positivas'], 1)}% do total"),
            card("resultados negativos", inteiro(e["negativos"]),
                 "Combinações que fecharam no vermelho. Uma região saudável "
                 "tem alguns — parâmetro nas bordas da faixa costuma não "
                 "funcionar, e isso é normal. O que preocupa é a maioria "
                 "estar aqui enquanto o campeão brilha.",
                 "neg" if e["negativos"] else None,
                 f"{num(100 - e['pct_positivas'] - (e['zerados'] / max(e['avaliadas'], 1) * 100), 1)}%"
                 + (f" · {inteiro(e['zerados'])} em zero" if e["zerados"] else "")),
            card("média", brl(e["media"]),
                 "O resultado médio de TODAS as combinações — não o do "
                 "campeão. É a expectativa de escolher um ponto qualquer da "
                 "região, que é a situação real quando o mercado andar e o "
                 "seu ponto ótimo de hoje deixar de ser o ótimo. Média "
                 "negativa com campeão positivo é o retrato de região ruim "
                 "com uma sorte dentro.",
                 "pos" if e["media"] > 0 else "neg",
                 f"mediana {brl(e['mediana'])}", largo=True),
            card("desvio padrão", brl(e["desvio"]),
                 "O espalhamento dos resultados em torno da média. Sozinho "
                 "não é bom nem ruim: o que importa é o tamanho dele "
                 "COMPARADO à média, que é exatamente o que o Z-score faz. "
                 "Desvio pequeno com média boa é platô; desvio grande "
                 "significa que o resultado depende de qual ponto você pegou.",
                 None, f"{num(e['dentro_1s'], 0)}% ficam a 1σ da média",
                 largo=True),
            card("Z-score", z_txt,
                 "Média ÷ desvio padrão: **quantos desvios separam a média de "
                 "zero**. Abaixo de 1,0 a região é frouxa — o resultado "
                 "típico está a menos de um desvio do prejuízo. Acima de 3,0 "
                 "é região sólida. "
                 "Ele responde de uma vez a pergunta dos 'três desvios', "
                 "porque média − 3σ > 0 e Z > 3 são a MESMA conta: uma escrita "
                 "em reais, a outra em desvios. "
                 "E note o que ele NÃO faz: não multiplica por √N como o SQN "
                 "de Van Tharp. Lá o N são trades, e mais trades é mais "
                 "evidência; aqui o N são as combinações que você escolheu "
                 "testar — testar mais não prova nada, e inflaria o número de "
                 "graça.",
                 faixa(z_fin, 3.0, 1.0),
                 "desvios entre a média e o zero"),
            card("média − 3σ",
                 brl(e["media_menos_3s"]),
                 "O que sobra da média depois de um choque de três desvios "
                 "padrão — o critério 'três sigma'. Positivo significa que "
                 "mesmo num cenário bem pior que o observado a região ainda "
                 "lucra. É idêntico a exigir Z ≥ 3; a diferença é só a "
                 "unidade. Negativo não condena a varredura: exigir três "
                 "sigma de um espaço de parâmetros é exigência de sistema "
                 "excepcional, e por isso este é um alerta, não um portão "
                 "crítico.",
                 "pos" if e["media_menos_3s"] > 0 else "warn",
                 f"a 1σ: {brl(e['media_menos_1s'])}", largo=True),
            card("dispersão relativa",
                 num(e["cv"], 2) if e["cv"] is not None else "—",
                 "Coeficiente de variação: o desvio padrão dividido pela "
                 "média, em vezes. Abaixo de 0,5 a região é homogênea e os "
                 "vizinhos valem quase o mesmo. Acima de 1,0 o desvio é maior "
                 "que a própria média — o resultado depende mais de qual "
                 "ponto você escolheu do que da estratégia. É o Z-score de "
                 "cabeça para baixo, e serve para ler a mesma coisa em "
                 "'quantas vezes' em vez de 'quantos desvios'.",
                 faixa(e["cv"], 0.5, 1.0) if e["cv"] is not None else None,
                 "σ ÷ média"),
            card("assimetria", num(e["assimetria"], 2),
                 "O quanto a distribuição pende para um lado. Perto de zero é "
                 "simétrica — o caso saudável. Positiva e alta é cauda longa "
                 "à direita: a maioria das combinações rende pouco e um "
                 "punhado rende muito, que é a assinatura de região "
                 "sustentada por poucos pontos mesmo quando a média parece "
                 "boa. Negativa é o contrário: a maioria rende bem e algumas "
                 "afundam, o que costuma ser borda de faixa.",
                 faixa(abs(e["assimetria"]), 0.5, 1.5),
                 f"curtose {num(e['curtose'], 2)}"),
        ],
        className="cards cards-porteira",
    )


# -------------------------------------------------------------------- gráfico
def grafico(e: dict) -> go.Figure:
    """A régua dos desvios: onde o zero cai em relação à média.

    O mesmo Z-score do cartão, desenhado. Quando a marca do zero fica dentro
    da faixa cinza (±1σ), a região está a um passo do prejuízo — e isso se vê
    antes de ler qualquer número.
    """
    if not e or not e["desvio"]:
        return _vazio("Sem dispersão para desenhar.")

    m, s = e["media"], e["desvio"]
    faixas = [(3, "±3σ", "rgba(34,228,255,.06)"), (2, "±2σ", "rgba(34,228,255,.09)"),
              (1, "±1σ", "rgba(34,228,255,.14)")]

    fig = go.Figure()
    for k, _rot, cor in faixas:
        fig.add_shape(type="rect", x0=m - k * s, x1=m + k * s, y0=0, y1=1,
                      yref="paper", fillcolor=cor, line=dict(width=0), layer="below")
    for k in (1, 2, 3):
        for lado in (-1, 1):
            fig.add_vline(x=m + lado * k * s,
                          line=dict(color=T.LINE_SOFT, width=1, dash="dot"))

    fig.add_vline(x=m, line=dict(color=T.ACCENT, width=2),
                  annotation_text="média", annotation_position="top",
                  annotation_font=dict(color=T.ACCENT, size=10))
    fig.add_vline(x=0, line=dict(color=T.NEG, width=2),
                  annotation_text="zero", annotation_position="bottom",
                  annotation_font=dict(color=T.NEG, size=10))

    # a nuvem de resultados por cima, para a régua não ficar abstrata
    fig.add_trace(go.Scatter(
        x=[e["pior"], e["melhor"]], y=[0.5, 0.5], mode="markers",
        marker=dict(size=9, color=[T.NEG, T.POS], symbol="diamond"),
        hovertemplate="%{x:,.0f}<extra></extra>",
    ))

    z_txt = f"{e['z']:.2f}" if e["z"] != float("inf") else "∞"
    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=10, t=40, b=28)},
        title={**TITULO, "text": f"Régua dos desvios — Z = {z_txt}"},
        xaxis=dict(**EIXO, title=dict(text="resultado da combinação (R$)",
                                      font=dict(size=10))),
        yaxis=dict(visible=False, range=[0, 1]),
    )
    return fig


def painel(av: dict, truncada: int = 0) -> html.Div:
    if not av:
        return vazio()
    return html.Div(
        [selo(av, truncada), numeros(av["estatisticas"]),
         dcc.Graph(figure=grafico(av["estatisticas"]), className="graf-porteira",
                   config={"displayModeBar": False, "responsive": True}),
         tabela_portoes(av)],
        className="aba-porteira",
    )
