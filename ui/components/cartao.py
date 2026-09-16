"""O cartão de métrica e o (?) que o explica.

Três painéis desenham cartões (estatísticas, robustez, detalhes). O molde
mora aqui para que mudar a aparência de um mude a dos três — e para que o
**(?)** funcione igual em todos.

Sobre o (?): número sem faixa de referência não sustenta decisão. "Ulcer
8,4" só vira informação quando se sabe que abaixo de 5 é confortável. O
texto fica junto do cartão que ele explica, nunca num dicionário distante,
para que mudar a métrica e esquecer a explicação seja difícil.

O balão em si é montado por assets/dica.js num nó preso ao <body>: dentro de
uma aba com rolagem não existe CSS que faça um `::after` escapar do
recorte — ele era cortado nos cartões de cima e nos das laterais.
"""

from __future__ import annotations

from dash import html


# ------------------------------------------------------------- formatação
def brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def num(v: float, casas=2) -> str:
    return f"{v:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def inteiro(v: int) -> str:
    return f"{v:,}".replace(",", ".")


def pct(v: float, casas=1) -> str:
    return f"{num(v, casas)}%"


# ------------------------------------------------------------------ peças
def dica(texto: str):
    """O (?) ao lado do rótulo. O texto viaja no atributo; o JS o desenha."""
    # tabIndex: o (?) também abre pelo teclado (Tab), e não só com o mouse
    return html.Span("?", className="dica-mark", tabIndex="0", role="button",
                     **{"data-dica": texto, "aria-label": texto})


def _tamanho(valor, largo: bool) -> str:
    """Encolhe o corpo do cartão quando o valor não cabe.

    O painel corta com reticências o que transborda, e "-R$ 16.920,08" a
    22px não cabe numa coluna de 172px — o cartão mostrava "-R$ 16.920,0…",
    que é pior do que mostrar o número um ponto menor. Os limites saem da
    largura real: ~12 caracteres numa coluna, ~22 num cartão de duas.
    """
    if not isinstance(valor, str):
        return ""
    n = len(valor)
    curto, medio = (26, 22) if largo else (15, 12)
    return "vlr-xs" if n >= curto else ("vlr-sm" if n >= medio else "")


def card(rotulo, valor, explica=None, sinal=None, nota=None,
         largo=False, fluido=False, texto=False):
    """Um cartão.

    `texto=True` para valores que são palavras e não números: o corpo de 22px
    é feito para dígitos e engolia "independentes" num "independen…".
    """
    classes = "card" + (" card-wide" if largo else "") + (" card-flow" if fluido else "")
    return html.Div(
        [
            html.Span([rotulo, dica(explica)] if explica else rotulo,
                      className="card-label"),
            html.Span(valor, className=" ".join(
                x for x in ("card-value", "txt" if texto else _tamanho(valor, largo),
                            sinal) if x)),
            html.Span(nota, className="card-note") if nota else None,
        ],
        className=classes,
    )


def faixa(v, bom, ruim):
    """Verde quando bom, vermelho quando ruim, neutro no meio.

    Aceita faixa invertida (bom < ruim), como em Ulcer, onde menor é melhor.
    """
    if v is None:
        return None
    if (bom > ruim and v >= bom) or (bom < ruim and v <= bom):
        return "pos"
    if (bom > ruim and v <= ruim) or (bom < ruim and v >= ruim):
        return "neg"
    return None


def sinal_de(v, bom_alto=True, neutro=0):
    if v == neutro:
        return None
    return "pos" if (v > neutro) == bom_alto else "neg"


def secao(titulo, explica, filhos, className="cards"):
    """Um grupo de cartões com título — a aba Detalhes tem quatro deles."""
    return html.Section([
        html.Div([html.H3(titulo, className="grp"), dica(explica)],
                 className="secao-head"),
        html.Div(filhos, className=className),
    ], className="secao")


def vazio(mensagem):
    return html.Div(html.P(mensagem, className="empty"), className="cards")
