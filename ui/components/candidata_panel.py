"""O quarto modo: a candidata.

Recebe um walk-forward salvo e pergunta quanto daquilo sobrevive fora do
cenário perfeito. Ver docs/PLANO-CANDIDATA.md.
"""

from __future__ import annotations

from dash import dcc, html

from core import candidata

from . import cartao, stats_cards
from .cartao import brl, inteiro, pct
from .wfa_panel import DICAS_OOS


def vazio(mensagem):
    return cartao.vazio(mensagem)


def _boot_do_recorte(leitura: dict, recorte: str) -> dict:
    """O dicionário de bootstrap por trás de um nome de recorte de
    `candidata.pior_dos_recortes` — para ler campos que não entram na
    escolha do pior (o p50, por exemplo) mas pertencem ao mesmo recorte."""
    if recorte == "curva inteira":
        return leitura.get("boot") or {}
    return leitura.get("boot_12m") or {}


def _nota_recorte(recorte: str, holdout: bool) -> str:
    """O aviso de holdout só faz sentido no recorte que o contém: os
    'últimos 12 meses' dos WFAs #3 e #8 são metade holdout, metade dado
    anterior a ele — ver `_texto_resumo` em `ui/callbacks_candidata.py`."""
    if holdout and recorte == "últimos 12 meses":
        return f"{recorte} (inclui o holdout)"
    return recorte


def bloco_robustez(leitura: dict, capital: float, holdout: bool = False):
    """Os cartões da curva fora da amostra.

    Ficaram de fora, de propósito: MAR e CAGR (compõem uma curva que é
    aditiva — o dimensionamento é de contratos fixos), SQN (é o t-stat com
    outro nome) e meses positivos (o portão de semestres do WFA já responde,
    e por uma régua melhor).

    As dicas do resumo são as MESMAS do card OOS do modo Walk-Forward
    (`wfa_panel.DICAS_OOS`) — é a mesma curva, a mesma pergunta.

    Cada métrica de risco (drawdown, perdas seguidas, tempo submerso) vale o
    PIOR entre os dois recortes — curva inteira e últimos 12 meses — e não
    necessariamente o mesmo recorte para as três: `pior_dos_recortes` decide
    métrica a métrica (ver o módulo `core.candidata`). `holdout` avisa
    quando o recorte de 12 meses, se for o pior de alguma métrica, contém o
    holdout lacrado.
    """
    if leitura.get("erro"):
        return vazio(leitura["erro"])

    b, o = leitura["boot"], leitura["ordenacao"]
    pior = candidata.pior_dos_recortes(leitura)
    horizonte = int(b.get("horizonte") or 1)

    dd_pior = pior["dd_p95"]["valor"]
    dd_recorte = pior["dd_p95"]["recorte"]
    dd_pct = dd_pior / capital * 100 if capital else 0.0

    seguidas_pior = pior["perdas_seguidas_p95"]["valor"]
    seguidas_recorte = pior["perdas_seguidas_p95"]["recorte"]

    submerso_pior = pior["submerso_p95"]["valor"]
    submerso_recorte = pior["submerso_p95"]["recorte"]
    submerso_pct = (submerso_pior / horizonte * 100) if horizonte else 0.0
    # o p50 do MESMO recorte que perdeu no p95 — não faz sentido comparar o
    # pior caso de um recorte com o caso típico do outro
    submerso_p50 = _boot_do_recorte(leitura, submerso_recorte).get(
        "submerso_p50", 0.0)

    # o "risco de ordenação" embaralha os 551 trades da curva INTEIRA
    # (~4 anos) — prazo diferente do bootstrap, que roda no horizonte da
    # próxima reotimização. Comparar os dois números direto é comparar
    # drawdown de 6 meses com drawdown de 4 anos: o achado que motivou este
    # bloco de correção. Cada cartão agora diz o prazo que mede.
    pregoes_total = int(leitura.get("pregoes", 0))
    ordenacao_pct = (o.get("dd_p95", 0.0) / capital * 100) if capital else 0.0

    perdas_reais = int(leitura.get("perdas_seguidas_reais", 0))

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
                "drawdown esperado", brl(dd_pior),
                explica="O p95 de 2.000 trajetórias sorteadas em blocos de "
                        "pregão, com reposição, no horizonte da próxima "
                        "reotimização — o lucro final varia entre "
                        "trajetórias, então a incerteza do próprio edge "
                        "entra na conta. Vale o pior entre a curva inteira e "
                        "os últimos 12 meses. Bom: até 10% do capital. Ruim: "
                        "acima de 20%.",
                sinal=cartao.faixa(dd_pct, 10, 20),
                nota=f"{pct(dd_pct, 1)} do capital · "
                     f"{_nota_recorte(dd_recorte, holdout)} · "
                     f"horizonte de {inteiro(horizonte)} pregões, vale até a "
                     f"próxima reotimização · blocos de "
                     f"{inteiro(int(b.get('bloco', 1)))} pregões"),
            cartao.card(
                "perdas seguidas",
                inteiro(int(round(seguidas_pior))),
                explica="O p95 da maior sequência de pregões OPERADOS e "
                        "negativos seguidos, nas mesmas trajetórias "
                        "sorteadas — pregão sem trade não conta nem corta a "
                        "sequência. É o que você vai viver antes de o "
                        "disjuntor disparar. Vale o pior entre a curva "
                        "inteira e os últimos 12 meses. Compare com a "
                        "sequência real ao lado: se o p95 simulado for bem "
                        "maior que ela, a curva real teve sorte — o azar "
                        "ainda não apareceu.",
                nota=f"{_nota_recorte(seguidas_recorte, holdout)} · "
                     f"curva real: {inteiro(perdas_reais)} pregões "
                     "perdedores seguidos"),
            cartao.card(
                "pregões abaixo do topo",
                inteiro(int(round(submerso_pior))),
                explica="O p95 do maior tempo, em pregões, que a trajetória "
                        "simulada passa abaixo do topo anterior antes de "
                        "fazer um novo topo — não é 'no fundo', é qualquer "
                        "ponto ainda devendo o pico. Vale o pior entre a "
                        "curva inteira e os últimos 12 meses. Até 50% do "
                        "horizonte é tolerável; acima de 90% é o que "
                        "acontece NOS PIORES 5% DAS TRAJETÓRIAS — não é o "
                        "caso típico, e a mediana ao lado mostra o típico "
                        "de verdade.",
                sinal=cartao.faixa(submerso_pct, 50, 90),
                nota=(f"{pct(submerso_pct, 0)} do horizonte de "
                      f"{inteiro(horizonte)} pregões · "
                      f"{_nota_recorte(submerso_recorte, holdout)} · "
                      f"mediana das trajetórias: "
                      f"{inteiro(int(round(submerso_p50)))} pregões"
                      + (" · nos piores 5% das trajetórias, não recupera o "
                         "topo dentro do horizonte" if submerso_pct > 90
                         else ""))),
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
