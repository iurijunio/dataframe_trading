"""Rompimento de canal (Donchian) com filtro de volatilidade.

Segunda estratégia do projeto, e ela existe por dois motivos: é um setup
real e diferente do primeiro, e serve de prova de que a plataforma não foi
escrita em volta de médias móveis. Os parâmetros aqui não têm nada a ver com
os do cruzamento — período do canal, folga em ticks, filtro de amplitude —
e mesmo assim a tela, a mineração e o motor funcionam sem uma linha de ajuste.

Compra no rompimento da máxima das últimas N barras, vende no rompimento da
mínima. O filtro de volatilidade descarta rompimentos em mercado parado, que
é onde esse tipo de setup mais se machuca.

Como toda estratégia, isto aqui não sabe o que é horário, custo, stop, alvo
ou tamanho de posição — tudo isso é camada 4, do operador.
"""

from __future__ import annotations

import numpy as np

from .base import Signals

name = "rompimento_canal"
label = "Rompimento de canal"

params_schema = {
    # min/max sao limites DUROS: a mineracao recorta a faixa da tela para
    # caber aqui. Se quiser varrer alem, e este numero que muda.
    "periodo_canal": {"label": "Período do canal", "default": 20,
                      "min": 3, "max": 400, "step": 1, "tipo": "int"},
    "folga_ticks": {"label": "Folga do rompimento (ticks)", "default": 1,
                    "min": 0, "max": 40, "step": 1, "tipo": "int"},
    "filtro_amplitude": {"label": "Amplitude mínima do canal (pontos)",
                         "default": 0, "min": 0, "max": 3000, "step": 50,
                         "tipo": "int"},
}

TICK = 5  # pontos; o WIN anda de 5 em 5


def _janela(x: np.ndarray, periodo: int, func) -> np.ndarray:
    """Máximo/mínimo das `periodo` barras ANTERIORES a cada posição.

    O deslocamento de uma barra não é detalhe: incluir a barra corrente
    faria o canal enxergar o próprio rompimento, e todo sinal nasceria
    olhando o futuro.
    """
    n = len(x)
    out = np.full(n, np.nan)
    if periodo <= 0 or n <= periodo:
        return out
    vistas = np.lib.stride_tricks.sliding_window_view(x, periodo)
    out[periodo:] = func(vistas, axis=1)[:-1]
    return out


def signals(bars: dict, params: dict) -> Signals:
    periodo = int(params["periodo_canal"])
    folga = int(params["folga_ticks"]) * TICK
    minimo = int(params["filtro_amplitude"])

    high, low, close = bars["high"], bars["low"], bars["close"]

    teto = _janela(high, periodo, np.max)
    piso = _janela(low, periodo, np.min)
    valido = ~(np.isnan(teto) | np.isnan(piso))

    # canal estreito demais: rompimento em mercado parado é ruído caro
    largo = np.where(valido, (teto - piso) >= minimo, False)

    rompe_cima = valido & largo & (close > teto + folga)
    rompe_baixo = valido & largo & (close < piso - folga)

    # só o primeiro fechamento fora do canal conta; enquanto seguir fora,
    # não é rompimento novo
    def primeiro(sinal):
        anterior = np.roll(sinal, 1)
        anterior[0] = False
        return sinal & ~anterior

    entrada_cima = primeiro(rompe_cima)
    entrada_baixo = primeiro(rompe_baixo)

    return Signals(
        entry_long=entrada_cima,
        entry_short=entrada_baixo,
        exit_long=entrada_baixo,    # rompimento contrário encerra
        exit_short=entrada_cima,
    )
