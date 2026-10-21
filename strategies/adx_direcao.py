"""ADX direção: candle a favor do movimento e ADX subindo ou caindo.

Compra quando o candle fecha em alta (`close > open`) e o ADX está subindo em
relação à barra anterior: a tendência ganhou força e o candle confirma o lado.
Vende no espelho: candle de baixa com o ADX caindo. Doji (`close == open`)
não gera sinal nenhum.

O período dos DIs (`adx_periodo`) e a suavização da linha do ADX
(`adx_media`) são separados: o DX sai dos DIs de `adx_periodo` e é suavizado
por Wilder com `adx_media`. O filtro `amplitude_max` barra candles grandes
demais (amplitude em pontos acima do limite); 0 desliga o filtro.

Como toda estratégia, isto aqui só define entradas. Horário, stop, alvo e
tamanho pertencem à camada 4, e a saída por sinal vem de `saida.py`.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from core.engine.execution import adx as adx_di
from . import saida as opcao_saida
from .base import Signals

name = "adx_direcao"
label = "ADX direção"

params_schema = {
    # min/max sao limites DUROS: a mineracao recorta a faixa da tela para
    # caber aqui. Se quiser varrer alem, e este numero que muda.
    "adx_periodo": {"label": "Período do DI+ e DI−", "default": 14,
                    "min": 2, "max": 100, "step": 1, "tipo": "int"},
    "adx_media": {"label": "Suavização da linha do ADX", "default": 14,
                  "min": 1, "max": 100, "step": 1, "tipo": "int"},
    "amplitude_max": {"label": "Amplitude máxima do candle (pontos; 0 desliga)",
                      "default": 1000, "min": 0, "max": 10000, "step": 5,
                      "tipo": "int"},
    **opcao_saida.parametro(opcao_saida.NAO_SAIR),
}


def _dx(di_pos: np.ndarray, di_neg: np.ndarray) -> np.ndarray:
    """DX = 100 * |DI+ - DI-| / (DI+ + DI-). Sem movimento (soma zero) vale 0;
    antes do aquecimento dos DIs continua NaN."""
    soma = di_pos + di_neg
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = np.where(soma > 0.0, 100.0 * np.abs(di_pos - di_neg) / soma, 0.0)
    dx[np.isnan(di_pos) | np.isnan(di_neg)] = np.nan
    return dx


@njit(cache=True)
def _suaviza_wilder(dx: np.ndarray, media: int) -> np.ndarray:
    """ADX = Wilder sobre o DX. A primeira média é a média simples das
    `media` primeiras barras válidas; depois, (anterior*(m-1) + dx) / m.
    Antes dessa semente fica NaN, que a estratégia lê como sem sinal."""
    n = len(dx)
    out = np.full(n, np.nan)
    if media < 1:
        return out
    inicio = -1
    for i in range(n):
        if not np.isnan(dx[i]):
            inicio = i
            break
    if inicio < 0:
        return out
    semente = inicio + media - 1
    if semente >= n:
        return out
    soma = 0.0
    for i in range(inicio, semente + 1):
        soma += dx[i]
    out[semente] = soma / media
    for i in range(semente + 1, n):
        out[i] = (out[i - 1] * (media - 1) + dx[i]) / media
    return out


def signals(bars: dict, params: dict) -> Signals:
    periodo = int(params["adx_periodo"])
    media = int(params["adx_media"])
    amplitude_max = int(params["amplitude_max"])

    _, di_pos, di_neg = adx_di(bars, periodo)
    adx = _suaviza_wilder(_dx(di_pos, di_neg), media)

    anterior = np.roll(adx, 1)
    anterior[0] = np.nan
    # comparacao com NaN e falsa: sem aquecimento nao ha sinal
    subindo = adx > anterior
    caindo = adx < anterior

    abertura, alta_max = bars["open"], bars["high"]
    minima, fechamento = bars["low"], bars["close"]
    positivo = fechamento > abertura
    negativo = fechamento < abertura

    if amplitude_max == 0:
        filtro = np.ones(len(fechamento), dtype=np.bool_)
    else:
        filtro = (alta_max - minima) <= amplitude_max

    return opcao_saida.aplicar(Signals(
        entry_long=positivo & subindo & filtro,
        entry_short=negativo & caindo & filtro,
        exit_long=np.zeros(len(fechamento), dtype=np.bool_),   # reescrito por `aplicar`
        exit_short=np.zeros(len(fechamento), dtype=np.bool_),
    ), opcao_saida.modo(params, params_schema))
