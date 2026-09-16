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
    horizonte = int(b.get("horizonte") or 1)

    # o "risco de ordenação" embaralha os 551 trades da curva INTEIRA
    # (~4 anos) — prazo diferente do bootstrap, que roda no horizonte da
    # próxima reotimização. Comparar os dois números direto é comparar
    # drawdown de 6 meses com drawdown de 4 anos: o achado que motivou este
    # bloco de correção. Cada cartão agora diz o prazo que mede.
    pregoes_total = int(leitura.get("pregoes", 0))
    ordenacao_pct = (o.get("dd_p95", 0.0) / capital * 100) if capital else 0.0

    perdas_reais = int(leitura.get("perdas_seguidas_reais", 0))
    submerso_p95 = b.get("submerso_p95", 0.0)
    submerso_pct = (submerso_p95 / horizonte * 100) if horizonte else 0.0

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
                        "pregão, com reposição, no horizonte da próxima "
                        "reotimização — o lucro final varia entre "
                        "trajetórias, então a incerteza do próprio edge "
                        "entra na conta. Vale o pior entre a curva inteira e "
                        "os últimos 12 meses. Bom: até 10% do capital. Ruim: "
                        "acima de 20%.",
                sinal=cartao.faixa(pior_pct, 10, 20),
                nota=f"{pct(pior_pct, 1)} do capital · {janela_pior} · "
                     f"horizonte de {inteiro(horizonte)} pregões, vale até a "
                     f"próxima reotimização · blocos de "
                     f"{inteiro(int(b.get('bloco', 1)))} pregões"),
            cartao.card(
                "perdas seguidas",
                inteiro(int(round(b.get("perdas_seguidas_p95", 0.0)))),
                explica="O p95 da maior sequência de pregões OPERADOS e "
                        "negativos seguidos, nas mesmas trajetórias "
                        "sorteadas — pregão sem trade não conta nem corta a "
                        "sequência. É o que você vai viver antes de o "
                        "disjuntor disparar. Compare com a sequência real ao "
                        "lado: se o p95 simulado for bem maior que ela, a "
                        "curva real teve sorte — o azar ainda não apareceu.",
                nota=f"curva real: {inteiro(perdas_reais)} pregões "
                     "perdedores seguidos"),
            cartao.card(
                "pregões abaixo do topo",
                inteiro(int(round(submerso_p95))),
                explica="O p95 do maior tempo, em pregões, que a trajetória "
                        "simulada passa abaixo do topo anterior antes de "
                        "fazer um novo topo — não é 'no fundo', é qualquer "
                        "ponto ainda devendo o pico. Até 50% do horizonte é "
                        "tolerável; acima de 90%, a estratégia tipicamente "
                        "não recupera o topo dentro do próprio horizonte.",
                sinal=cartao.faixa(submerso_pct, 50, 90),
                nota=(f"{pct(submerso_pct, 0)} do horizonte de "
                      f"{inteiro(horizonte)} pregões"
                      + (" · tipicamente não recupera o topo dentro do "
                         "horizonte" if submerso_pct > 90 else ""))),
            cartao.card(
                "risco de ordenação", brl(o.get("dd_p95", 0.0)),
                explica="Os MESMOS trades embaralhados, na curva INTEIRA "
                        "(não no horizonte do cartão de drawdown esperado — "
                        "os dois medem prazos diferentes e não se comparam "
                        "diretamente). O lucro final não muda, só o "
                        "caminho: mede azar de sequência, não incerteza do "
                        "resultado — por isso não é o disjuntor. Bom: até "
                        "10% do capital. Ruim: acima de 20%.",
                sinal=cartao.faixa(ordenacao_pct, 10, 20),
                nota=f"mesma carteira, outra ordem · curva inteira · "
                     f"{inteiro(pregoes_total)} pregões"),
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
