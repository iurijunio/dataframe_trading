"""Tendência pelas três médias, com o preço já longe da abertura do dia.

Opera a favor do movimento do dia. Um candle A fecha pelo menos x acima da
abertura; o candle B, logo depois, confirma: fecha acima da máxima de A,
ainda pelo menos x acima da abertura e acima das três médias exponenciais.
A compra sai na abertura do candle seguinte a B. A venda é o espelho.

**Armada.** Depois da confirmação, a estratégia segue armada enquanto a
condição se mantém (distância ≥ x e fechamento do lado certo das três
médias). O sinal de entrada fica ligado em toda barra armada: posicionado,
o motor o ignora; zerado por stop ou alvo, ele entra de novo na abertura do
candle seguinte, sem nova confirmação. Quebrou a condição ou virou o dia,
desarma: só um par A-B novo arma de novo.

A abertura do dia é a do primeiro candle do pregão (09:00 no WIN, início
da sessão no CME). Stop, alvo e horário de encerramento são do perfil de
execução (camada 4); a estratégia não tem saída própria.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from . import saida as opcao_saida
from .base import Signals

name = "tendencia_medias_abertura"
label = "Tendência pelas médias com distância da abertura"

EM_PONTOS = 0
EM_PORCENTO = 1

params_schema = {
    "ema_rapida": {"label": "Período da média exponencial rápida", "default": 9,
                   "min": 2, "max": 200, "step": 1, "tipo": "int"},
    "ema_intermediaria": {"label": "Período da média exponencial intermediária",
                          "default": 21, "min": 2, "max": 400, "step": 1, "tipo": "int"},
    "ema_lenta": {"label": "Período da média exponencial longa", "default": 50,
                  "min": 2, "max": 600, "step": 1, "tipo": "int"},
    "unidade_distancia": {"label": "Unidade da distância · 0 pontos · 1 % da abertura",
                          "default": EM_PONTOS, "min": 0, "max": 1, "step": 1,
                          "tipo": "int"},
    # dois campos, um por unidade: a conversão de pontos do CME (×escala) só
    # pode valer para o campo que é de fato pontos. Minere um de cada vez: o
    # da outra unidade não muda nada, e cópia na mineração cria platô falso
    "distancia_pontos": {"label": "Distância mínima da abertura (pontos; vale "
                                  "com unidade 0)",
                         "default": 300, "min": 0, "max": 5000, "step": 50,
                         "tipo": "int", "unidade": "pontos"},
    "distancia_centesimos_pct": {"label": "Distância mínima da abertura "
                                        "(centésimos de %: 20 = 0,20%; vale "
                                        "com unidade 1)",
                                 "default": 20, "min": 0, "max": 300, "step": 5,
                                 "tipo": "int"},
    **opcao_saida.parametro(opcao_saida.NAO_SAIR),
}

_PERIODOS = ("ema_rapida", "ema_intermediaria", "ema_lenta")


@njit(cache=True)
def _ema(valores: np.ndarray, periodo: int) -> np.ndarray:
    """EMA recursiva, iniciada no primeiro fechamento disponível."""
    n = len(valores)
    saida = np.empty(n, dtype=np.float64)
    if n == 0:
        return saida
    alpha = 2.0 / (periodo + 1.0)
    saida[0] = valores[0]
    for i in range(1, n):
        saida[i] = alpha * valores[i] + (1.0 - alpha) * saida[i - 1]
    return saida


@njit(cache=True)
def _armada(referencia: np.ndarray, rompe: np.ndarray, condicao: np.ndarray,
            mesmo_dia: np.ndarray) -> np.ndarray:
    """Barras em que o lado está armado.

    Arma no candle B: o anterior (A, do mesmo pregão) foi referência, B rompe
    o extremo de A e atende à condição. Segue armado enquanto a condição vale
    e o pregão é o mesmo; quebrou, só um par A-B novo arma de novo.
    """
    n = len(condicao)
    out = np.zeros(n, dtype=np.bool_)
    armado = False
    for i in range(n):
        if armado:
            armado = condicao[i] and mesmo_dia[i]
        else:
            armado = mesmo_dia[i] and referencia[i - 1] and rompe[i] and condicao[i]
        out[i] = armado
    return out


def aquecimento_barras(params: dict) -> int:
    """Vinte períodos da média mais longa: o ponto inicial da EMA some."""
    return 20 * max(int(params[k]) for k in _PERIODOS)


def abertura_do_dia(abertura: np.ndarray, dia: np.ndarray) -> np.ndarray:
    """A abertura do primeiro candle de cada pregão, repetida no pregão todo."""
    if len(dia) == 0:
        return np.empty(0, dtype=np.float64)
    novo = np.ones(len(dia), dtype=np.bool_)
    novo[1:] = dia[1:] != dia[:-1]
    inicio = np.flatnonzero(novo)
    tamanho = np.diff(np.append(inicio, len(dia)))
    return np.repeat(np.asarray(abertura, dtype=np.float64)[inicio], tamanho)


def distancia_minima(abertura_dia: np.ndarray, params: dict) -> np.ndarray | float:
    """O x da regra, em unidade de preço: pontos fixos ou % da abertura."""
    if int(params["unidade_distancia"]) == EM_PORCENTO:
        return abertura_dia * float(params["distancia_centesimos_pct"]) / 10_000.0
    return float(params["distancia_pontos"])


def _lados(bars: dict, params: dict) -> tuple[np.ndarray, np.ndarray]:
    """Entradas de compra e de venda: as barras armadas de cada lado."""
    fechamento = np.asarray(bars["close"], dtype=np.float64)
    maxima = np.asarray(bars["high"], dtype=np.float64)
    minima = np.asarray(bars["low"], dtype=np.float64)
    dia = np.asarray(bars["ts"]).astype("datetime64[D]")
    ab = abertura_do_dia(np.asarray(bars["open"]), dia)
    x = distancia_minima(ab, params)

    medias = [_ema(fechamento, int(params[k])) for k in _PERIODOS]
    acima = np.logical_and.reduce([fechamento > m for m in medias])
    abaixo = np.logical_and.reduce([fechamento < m for m in medias])

    mesmo_dia = np.zeros(len(dia), dtype=np.bool_)
    mesmo_dia[1:] = dia[1:] == dia[:-1]
    # a 1ª barra não tem anterior: `mesmo_dia[0]` é falso e o roll nunca conta
    max_ant, min_ant = np.roll(maxima, 1), np.roll(minima, 1)

    longe_acima = fechamento - ab >= x
    longe_abaixo = ab - fechamento >= x
    compra = _armada(longe_acima, fechamento > max_ant, longe_acima & acima, mesmo_dia)
    venda = _armada(longe_abaixo, fechamento < min_ant, longe_abaixo & abaixo, mesmo_dia)
    return compra, venda


def signals(bars: dict, params: dict) -> Signals:
    n = len(bars["close"])
    vazio = np.zeros(n, dtype=np.bool_)
    if n == 0:
        compra, venda = vazio, vazio.copy()
    else:
        compra, venda = _lados(bars, params)
    return opcao_saida.aplicar(Signals(
        entry_long=compra,
        entry_short=venda,
        exit_long=vazio.copy(),
        exit_short=vazio.copy(),
    ), opcao_saida.modo(params, params_schema))
