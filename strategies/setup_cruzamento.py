"""Cruzamento de medias moveis.

Primeira estrategia do projeto, escolhida por ser simples o bastante para
conferir os trades a mao numa serie sintetica: se o motor errar, o erro
aparece num setup auditavel linha por linha.

Compra quando a media rapida cruza a lenta para cima, vende no cruzamento
para baixo. Nada aqui sabe de horario, custo, stop, alvo ou tamanho de
posicao - isso e tudo camada 4.
"""

from __future__ import annotations

import numpy as np

from .base import Signals

name = "setup_cruzamento"
label = "Cruzamento de médias"

params_schema = {
    # min/max sao limites DUROS: a mineracao recorta a faixa da tela para
    # caber aqui. Se quiser varrer alem, e este numero que muda.
    "media_rapida": {"label": "Média rápida", "default": 9,
                     "min": 2, "max": 200, "step": 1, "tipo": "int"},
    "media_lenta": {"label": "Média lenta", "default": 21,
                    "min": 3, "max": 600, "step": 1, "tipo": "int"},
}


def sma(x: np.ndarray, periodo: int) -> np.ndarray:
    """Media movel simples. As primeiras `periodo-1` posicoes ficam NaN -
    e o que impede sinal com janela incompleta."""
    out = np.full(len(x), np.nan)
    if periodo <= 0 or len(x) < periodo:
        return out
    soma = np.cumsum(np.insert(x.astype(np.float64), 0, 0.0))
    out[periodo - 1:] = (soma[periodo:] - soma[:-periodo]) / periodo
    return out


def signals(bars: dict, params: dict) -> Signals:
    if params["media_rapida"] >= params["media_lenta"]:
        raise ValueError("A média rápida precisa ser menor que a lenta.")

    close = bars["close"]
    rapida = sma(close, int(params["media_rapida"]))
    lenta = sma(close, int(params["media_lenta"]))

    acima = rapida > lenta
    valido = ~(np.isnan(rapida) | np.isnan(lenta))
    anterior = np.roll(acima, 1)
    anterior[0] = acima[0]
    formado = valido & np.roll(valido, 1)
    formado[0] = False

    cruza_cima = acima & ~anterior & formado
    cruza_baixo = ~acima & anterior & formado

    return Signals(
        entry_long=cruza_cima,
        entry_short=cruza_baixo,
        exit_long=cruza_baixo,   # o cruzamento contrario encerra a posicao
        exit_short=cruza_cima,
    )
