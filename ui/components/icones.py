"""Ícones Lucide locais (ui/assets/icones), desenhados por máscara CSS.

O ícone é um `html.Span` vazio: o desenho vem do SVG pela máscara e a cor
vem do texto em volta, então ele acompanha a cor da etiqueta ou do botão
sem regra extra. Nada de rede: o `dash-iconify` buscaria cada desenho na
API do Iconify na hora de desenhar a tela, em pleno pregão.
"""

from dash import html

# Um nome aqui exige o SVG em ui/assets/icones/<nome>.svg e a regra
# .ic-<nome> em ui/assets/icones.css (tests/test_icones.py confere).
ICONES = frozenset({
    "arrow-down", "arrow-up", "briefcase", "chart-candlestick", "circle-help",
    "crosshair", "external-link", "layers", "list", "maximize-2", "pause",
    "pencil", "play", "power", "scale", "scroll-text", "send", "skip-forward",
    "triangle-alert",
})


def icone(nome: str, pequeno: bool = False, classe: str = "") -> html.Span:
    """`icone("send")` → ícone de 15 px; `pequeno=True` → 13 px.

    Nome desconhecido é erro na hora: um ícone com nome errado não aparece
    e ninguém percebe na tela.
    """
    if nome not in ICONES:
        raise ValueError(f"ícone desconhecido: {nome!r}")
    classes = ["ic", f"ic-{nome}"]
    if pequeno:
        classes.append("ic-sm")
    if classe:
        classes.append(classe)
    return html.Span(className=" ".join(classes), **{"aria-hidden": "true"})
