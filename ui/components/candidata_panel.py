"""O quarto modo: a candidata.

Recebe um walk-forward salvo e pergunta quanto daquilo sobrevive fora do
cenário perfeito. Ver docs/PLANO-CANDIDATA.md.
"""

from __future__ import annotations

from dash import dcc, html

from . import cartao, stats_cards
from .cartao import brl, inteiro, pct
from .wfa_panel import DICAS_OOS


def vazio(mensagem):
    return cartao.vazio(mensagem)


def bloco_robustez(leitura: dict, capital: float):
    """Os cartões da curva fora da amostra.

    Ficaram de fora, de propósito: MAR e CAGR (compõem uma curva que é
    aditiva — o dimensionamento é de contratos fixos), SQN (é o t-stat com
    outro nome) e meses positivos (o portão de semestres do WFA já responde,
    e por uma régua melhor).

    As dicas do resumo são as MESMAS do card OOS do modo Walk-Forward
    (`wfa_panel.DICAS_OOS`) — é a mesma curva, a mesma pergunta.
    """
    if leitura.get("erro"):
        return vazio(leitura["erro"])

    b, o = leitura["boot"], leitura["ordenacao"]
    b12 = leitura.get("boot_12m") or {}
    dd, dd12 = b.get("dd_p95", 0.0), b12.get("dd_p95", 0.0)
    # vale o pior dos dois recortes — ver leitura_robustez
    pior, janela_pior = ((dd, "curva inteira") if dd >= dd12
                         else (dd12, "últimos 12 meses"))
    pior_pct = pior / capital * 100 if capital else 0.0

    resumo = html.Div(
        list(stats_cards.cartoes(leitura["resumo"], DICAS_OOS).values()),
        className="cards cards-wfa",
    )

    extras = cartao.secao(
        "Robustez (bootstrap em blocos)",
        "Duas mil trajetórias possíveis para os MESMOS pregões, sorteadas "
        "com reposição em blocos que preservam o agrupamento de ganhos e "
        "perdas — o que a permutação ao lado, no 'risco de ordenação', não "
        "faz. Mede a incerteza de que o edge medido não seja o verdadeiro, "
        "não só o azar da ordem em que os trades vieram.",
        [
            cartao.card(
                "drawdown esperado", brl(pior),
                explica="O p95 de 2.000 trajetórias sorteadas em blocos de "
                        "pregão, com reposição — o lucro final varia entre "
                        "trajetórias, então a incerteza do próprio edge "
                        "entra na conta. Vale o pior entre a curva inteira e "
                        "os últimos 12 meses. Bom: até 10% do capital. Ruim: "
                        "acima de 20%.",
                sinal=cartao.faixa(pior_pct, 10, 20),
                nota=f"{pct(pior_pct, 1)} do capital · {janela_pior} · "
                     f"blocos de {inteiro(int(b.get('bloco', 1)))} pregões"),
            cartao.card(
                "perdas seguidas",
                inteiro(int(round(b.get("perdas_seguidas_p95", 0.0)))),
                explica="O p95 da maior sequência de pregões negativos "
                        "seguidos e do maior tempo abaixo do topo anterior, "
                        "nas mesmas trajetórias sorteadas. É o que você vai "
                        "viver antes de o disjuntor disparar. Até 5 pregões "
                        "seguidos é tolerável; acima de 10, vale perguntar "
                        "se você aguentaria operar até lá.",
                nota=f"{inteiro(int(round(b.get('submerso_p95', 0.0))))} "
                     "pregões no fundo"),
            cartao.card(
                "risco de ordenação", brl(o.get("dd_p95", 0.0)),
                explica="Os MESMOS trades embaralhados: o lucro final não "
                        "muda, só o caminho. Mede azar de sequência, não "
                        "incerteza do resultado — por isso não é o "
                        "disjuntor. Se for bem menor que o drawdown esperado "
                        "ao lado, a diferença entre os dois é a incerteza de "
                        "o edge medido não ser o verdadeiro.",
                nota="mesma carteira, outra ordem"),
        ],
    )

    return html.Div([resumo, extras])


def painel():
    return html.Div(
        [
            html.Div(
                [
                    # nasce vazio: um WFA salvo depois de o processo subir só
                    # apareceria reiniciando o servidor. Quem preenche é o
                    # callback `cand_opcoes`, em `ui/callbacks_candidata.py`
                    # — o mesmo padrão de `wfa-salvos` em `wfa_panel.py`.
                    dcc.Dropdown(id="cand-wfa", className="dd dd-wfa",
                                 placeholder="walk-forward salvo…",
                                 options=[], value=None),
                    html.Span(id="cand-resumo", className="cand-resumo"),
                ],
                className="cand-topo",
            ),
            html.Div(id="cand-portoes", className="cand-portoes"),
            html.Div(id="cand-blocos", className="cand-blocos"),
        ],
        # escondido de saída: sem isto o Dash serve o primeiro HTML com este
        # painel VISÍVEL (`.modo-bloco` é display:flex) empilhado embaixo do
        # Backtest, até o callback `modo` resolver no cliente — mesma
        # armadilha que `painel-mineracao` e `painel-wfa` já evitam em
        # `ui/app.py`.
        id="painel-candidata", className="modo-bloco cand",
        style={"display": "none"},
    )
