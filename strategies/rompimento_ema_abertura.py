"""Rompimento com duas médias exponenciais e referência à abertura diária.

Compra quando uma barra positiva fecha acima das duas médias, depois de a
barra anterior ter testado abaixo da média curta, e supera a máxima anterior.
A distância mínima desde a abertura do pregão filtra rompimentos próximos ao
preço de abertura. A venda aplica as mesmas condições no sentido contrário.

A estratégia só define entradas. Horário, stop, alvo e tamanho pertencem ao
perfil de execução (camada 4).
"""

from __future__ import annotations

import numpy as np
from numba import njit

from .base import Signals

name = "rompimento_ema_abertura"
label = "Rompimento das médias na abertura"

params_schema = {
    "ema_curta": {"label": "Período da média exponencial curta", "default": 9,
                  "min": 2, "max": 200, "step": 1, "tipo": "int"},
    "ema_longa": {"label": "Período da média exponencial longa", "default": 21,
                  "min": 3, "max": 600, "step": 1, "tipo": "int"},
    "distancia_abertura": {"label": "Distância mínima da abertura do dia (pontos)",
                            "default": 0, "min": 0, "max": 3000,
                            "step": 50, "tipo": "int"},
}


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


def aquecimento_barras(params: dict) -> int:
    """Dá vinte períodos para o ponto inicial da EMA cair abaixo da precisão prática."""
    return 20 * max(int(params["ema_curta"]), int(params["ema_longa"]))


def signals(bars: dict, params: dict) -> Signals:
    curta_periodo = int(params["ema_curta"])
    longa_periodo = int(params["ema_longa"])
    distancia = int(params["distancia_abertura"])
    if curta_periodo >= longa_periodo:
        raise ValueError("O período da média curta precisa ser menor que o da longa.")

    abertura = np.asarray(bars["open"], dtype=np.float64)
    maxima = np.asarray(bars["high"], dtype=np.float64)
    minima = np.asarray(bars["low"], dtype=np.float64)
    fechamento = np.asarray(bars["close"], dtype=np.float64)
    n = len(fechamento)
    vazio = np.zeros(n, dtype=np.bool_)
    if n == 0:
        return Signals(vazio, vazio.copy(), vazio.copy(), vazio.copy())

    media_curta = _ema(fechamento, curta_periodo)
    media_longa = _ema(fechamento, longa_periodo)

    dia = np.asarray(bars["ts"]).astype("datetime64[D]")
    _, inicio_dia = np.unique(dia, return_index=True)
    abertura_dia = np.repeat(abertura[inicio_dia], np.diff(np.append(inicio_dia, n)))

    anterior_valido = np.zeros(n, dtype=np.bool_)
    anterior_valido[1:] = dia[1:] == dia[:-1]
    minima_anterior = np.roll(minima, 1)
    maxima_anterior = np.roll(maxima, 1)
    curta_anterior = np.roll(media_curta, 1)

    compra = (anterior_valido & (fechamento > abertura)
              & (fechamento > media_curta) & (fechamento > media_longa)
              & (minima_anterior < curta_anterior)
              & (fechamento > maxima_anterior)
              & (fechamento - abertura_dia >= distancia))
    venda = (anterior_valido & (fechamento < abertura)
             & (fechamento < media_curta) & (fechamento < media_longa)
             & (maxima_anterior > curta_anterior)
             & (fechamento < minima_anterior)
             & (abertura_dia - fechamento >= distancia))

    return Signals(
        entry_long=compra,
        entry_short=venda,
        exit_long=vazio,
        exit_short=vazio.copy(),
    )

