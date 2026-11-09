"""Operação: constantes, cores e formatação usadas por todas as partes."""
from __future__ import annotations

from datetime import datetime

from dash import html

from ... import theme as T
from ..cartao import dica, inteiro, num


CINZA = T.CINZA_FORA
SUBTELA = "operacao"

# códigos de saída do kernel (core/engine/kernel.py), na língua da mesa
_SAIU_POR = {0: "stop", 1: "alvo", 2: "sinal contrário",
             3: "horário de fechamento", 4: "tempo máximo",
             5: "fim dos dados"}

_FAIXAS = {"abaixo_p10": "abaixo do p10", "p10_p50": "entre p10 e p50",
           "p50_p90": "entre p50 e p90", "acima_p90": "acima do p90"}

# título da linha de stop/alvo no eixo de preço: nome longo cobriria o gráfico
_TITULO_MAX = 22
# posições abertas visíveis até onde stop/alvo ganham rótulo no eixo
_ROTULOS_MAX = 2

# curva por pregão: um ponto por dia, sem hora no eixo
CHART_CURVA = {**T.CHART_OPTIONS,
               "timeScale": {**T.CHART_OPTIONS["timeScale"],
                             "timeVisible": False, "rightOffset": 2},
               "rightPriceScale": {**T.CHART_OPTIONS["rightPriceScale"],
                                   "scaleMargins": {"top": .12, "bottom": .12}}}


# ------------------------------------------------------------- cores e forma
def cor(i: int | None) -> str:
    return T.CORES_VARIANTE[(i or 0) % len(T.CORES_VARIANTE)]


def forma(i: int | None) -> str:
    """Marcador de saída: círculo nas 8 primeiras cores, quadrado quando a
    cor repete — a 9ª variante tem a cor da 1ª e precisa de outro sinal."""
    return "square" if ((i or 0) // len(T.CORES_VARIANTE)) % 2 else "circle"


def amostra(i, ativa=True):
    quadrado = forma(i) == "square"
    return html.Span(className="op-amostra"
                     + (" op-amostra-quadrado" if quadrado else ""),
                     style={"background": cor(i) if ativa else CINZA})


# --------------------------------------------------------------- formatação
def _rs(v, casas=0) -> str:
    """Dinheiro com sinal: "+R$ 286", "-R$ 164", "R$ 0"."""
    if v is None:
        return "—"
    if casas:
        corpo = num(abs(v), casas)
    else:
        corpo = inteiro(int(round(abs(v))))
    if round(v, casas) == 0:
        return f"R$ {corpo}"
    return f"{'+' if v > 0 else '-'}R$ {corpo}"


def _sinal(v) -> str | None:
    if v is None or round(v, 2) == 0:
        return None
    return "pos" if v > 0 else "neg"


def _hora(ts) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return "—"
    return f"{ts:%H:%M}"


def _preco(v) -> str:
    return "—" if v is None else inteiro(int(v))


def _etiqueta(texto, tom="cinza", explica=None):
    return html.Span([texto] + ([dica(explica)] if explica else []),
                     className=f"av-tag av-tag-{tom}")


def _rotulo(texto, explica=None, classe="op-rot"):
    return html.Span([texto] + ([dica(explica)] if explica else []),
                     className=classe)


def _lado_pos(p: int) -> tuple[str, str]:
    if p > 0:
        return f"comprado {p}", "info"
    if p < 0:
        return f"vendido {abs(p)}", "info"
    return "zerado", "cinza"
