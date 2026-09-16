"""O quarto modo: a candidata.

Recebe um walk-forward salvo e responde, antes de arriscar dinheiro:
quanto a estratégia aguenta, se o resultado é mérito ou sorte, e com
quantos contratos operar. Ver docs/PLANO-CANDIDATA.md.

Os textos da tela são para quem opera, não para quem estuda estatística:
o nome do cartão diz a pergunta que ele responde, e o (?) explica em
palavras simples, com a faixa boa e a ruim.
"""

from __future__ import annotations

from dash import dcc, html

from core import candidata

from . import cartao, stats_cards
from .cartao import brl, inteiro, pct
from .wfa_panel import DICAS_OOS, _br


def vazio(mensagem):
    return cartao.vazio(mensagem)


def _boot_do_recorte(leitura: dict, recorte: str) -> dict:
    """A simulação do recorte que deu o pior número, para ler dela os campos
    que não entram na escolha do pior (o caso típico, por exemplo)."""
    if recorte == "curva inteira":
        return leitura.get("boot") or {}
    return leitura.get("boot_12m") or {}


def _de_onde(recorte: str, holdout: bool) -> str:
    """Frase para o (?) dizendo de qual trecho da curva veio o número."""
    if recorte == "últimos 12 meses":
        return (" Neste walk-forward, o número veio dos últimos 12 meses"
                + (", que incluem o holdout." if holdout else "."))
    return " Neste walk-forward, o número veio da curva inteira."


def _meses(pregoes: int) -> int:
    return max(1, round(pregoes / 21))


def bloco_robustez(leitura: dict, capital: float, holdout: bool = False,
                   de=None, ate=None):
    """Os cartões da tela: o resultado fora da amostra e quanto ele aguenta.

    Cada número de risco é calculado duas vezes — na curva inteira e só nos
    últimos 12 meses — e vale o pior dos dois, porque o comportamento
    recente pesa mais do que a média de quatro anos.
    """
    if leitura.get("erro"):
        return vazio(leitura["erro"])

    o = leitura["ordenacao"]
    pior = candidata.pior_dos_recortes(leitura)
    horizonte = int((leitura.get("boot") or {}).get("horizonte") or 1)
    meses = _meses(horizonte)

    perda, perda_rec = pior["dd_p95"]["valor"], pior["dd_p95"]["recorte"]
    perda_pct = perda / capital * 100 if capital else 0.0

    seguidas = pior["perdas_seguidas_p95"]["valor"]
    seguidas_rec = pior["perdas_seguidas_p95"]["recorte"]
    seguidas_reais = int(leitura.get("perdas_seguidas_reais", 0))

    topo_pior = pior["submerso_p95"]["valor"]
    topo_rec = pior["submerso_p95"]["recorte"]
    topo_tipico = _boot_do_recorte(leitura, topo_rec).get("submerso_p50", 0.0)
    topo_pct = topo_tipico / horizonte * 100 if horizonte else 0.0

    ordem = o.get("dd_p95", 0.0)
    ordem_pct = ordem / capital * 100 if capital else 0.0

    m = dict(leitura["resumo"])
    if de and ate:
        m["periodo"] = f"{_br(de)} → {_br(ate)}"
        m["periodo_nota"] = "fora da amostra, janela após janela"

    resultado = cartao.secao(
        "Resultado fora da amostra",
        "Os mesmos números da aba Walk-Forward: o que a estratégia fez nos "
        "meses que o otimizador não viu.",
        list(stats_cards.cartoes(m, DICAS_OOS).values()),
        className="cards cards-wfa",
    )

    aguenta = cartao.secao(
        "Quanto a estratégia aguenta",
        "A plataforma sorteia 2.000 caminhos possíveis para a estratégia, "
        "usando os dias reais que ela já operou em outra ordem e combinação. "
        "Os números abaixo dizem o que acontece nos caminhos ruins — não no "
        "que você viu, que é só um deles.",
        [
            cartao.card(
                f"perda esperada · {meses} meses", brl(perda),
                explica=("A maior queda a partir de um topo que você deve "
                         f"esperar nos próximos {meses} meses, até a próxima "
                         "reotimização. Só 5 de cada 100 caminhos sorteados "
                         "perdem mais do que isso. É a base para decidir "
                         "quando desligar o robô. Bom: até 10% do capital. "
                         "Ruim: acima de 20%."
                         + _de_onde(perda_rec, holdout)),
                sinal=cartao.faixa(perda_pct, 10, 20),
                nota=f"{pct(perda_pct, 1)} do capital",
                largo=True),
            cartao.card(
                "dias perdendo seguidos", inteiro(int(round(seguidas))),
                explica=("Quantos dias de operação seguidos fechando no "
                         "prejuízo você deve estar preparado para viver. Dia "
                         "sem operação não conta. Só 5 de cada 100 caminhos "
                         "têm sequência maior. Se este número for bem maior "
                         "que o da curva real, o passado teve sorte — o azar "
                         "ainda não apareceu."
                         + _de_onde(seguidas_rec, holdout)),
                nota=f"na curva real: {inteiro(seguidas_reais)}",
                largo=True),
            cartao.card(
                "dias até novo topo", inteiro(int(round(topo_tipico))),
                explica=("Quantos dias de pregão a estratégia costuma passar "
                         "abaixo do último topo antes de superá-lo. O número "
                         "grande é o caso típico; o pior caso fica na nota. "
                         f"O prazo é de {inteiro(horizonte)} pregões (até a "
                         "próxima reotimização). Bom: até metade do prazo. "
                         "Ruim: quase o prazo inteiro."
                         + _de_onde(topo_rec, holdout)),
                sinal=cartao.faixa(topo_pct, 50, 90),
                nota=(f"pior caso: {inteiro(int(round(topo_pior)))} de "
                      f"{inteiro(horizonte)} pregões"),
                largo=True),
            cartao.card(
                "perda com outra ordem", brl(ordem),
                explica=("Os MESMOS trades da curva, embaralhados: o lucro "
                         "final não muda, só a ordem. Mede o azar de os "
                         "prejuízos virem todos juntos, no período inteiro "
                         "(não nos próximos meses) — por isso é maior que a "
                         "perda esperada e não se compara direto com ela. "
                         "Bom: até 10% do capital. Ruim: acima de 20%."),
                sinal=cartao.faixa(ordem_pct, 10, 20),
                nota=f"{pct(ordem_pct, 1)} do capital · período inteiro",
                largo=True),
        ],
        className="cards cards-wfa",
    )

    return html.Div([resultado, aguenta], className="cand-secoes")


def painel():
    return html.Div(
        [
            html.Div(
                [
                    # os dois nascem vazios: quem preenche são os callbacks
                    # `cand_estrategias` e `cand_opcoes`
                    dcc.Dropdown(id="cand-estrategia", className="dd dd-cand-est",
                                 placeholder="estratégia…", clearable=False,
                                 options=[], value=None),
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
        # escondido de saída: sem isto o painel aparece embaixo do Backtest
        # até o callback `modo` resolver no navegador
        id="painel-candidata", className="modo-bloco cand",
        style={"display": "none"},
    )
