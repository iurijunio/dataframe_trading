"""Rompimento da abertura (Opening Range Breakout).

Terceira estratégia, e a primeira pensada especificamente pra day trade de
índice futuro: o range das primeiras barras do pregão vira o alvo do
primeiro rompimento do dia. Clássica, poucos parâmetros (3), sem média
móvel, sem RSI, sem indicador nenhum — só máximo e mínimo de uma janela
fixa no início de cada pregão.

Só um sinal por dia, de propósito: depois do primeiro rompimento, o range
já foi usado — repique ou fuga na mesma direção não é rompimento novo, é
continuação do mesmo movimento.

Sem saída própria: fecha no stop/alvo do perfil de execução, ou no fim do
pregão (camada 4) — igual a rompimento_canal, a estratégia só decide
ENTRADA.
"""

from __future__ import annotations

import numpy as np

from .base import Signals

name = "rompimento_abertura"
label = "Rompimento da abertura"

params_schema = {
    "barras_abertura": {"label": "Barras da abertura", "default": 6,
                        "min": 1, "max": 60, "step": 1, "tipo": "int"},
    "folga_ticks": {"label": "Folga do rompimento (ticks)", "default": 1,
                    "min": 0, "max": 500, "step": 1, "tipo": "int"},
    "filtro_amplitude": {"label": "Amplitude mínima da abertura (pontos)",
                         "default": 0, "min": 0, "max": 2000, "step": 50,
                         "tipo": "int"},
}

TICK = 5  # pontos; o WIN anda de 5 em 5


def signals(bars: dict, params: dict) -> Signals:
    barras_abertura = int(params["barras_abertura"])
    folga = int(params["folga_ticks"]) * TICK
    minimo = int(params["filtro_amplitude"])

    ts, high, low, close = bars["ts"], bars["high"], bars["low"], bars["close"]
    n = len(close)

    dia = ts.astype("datetime64[D]")
    dias_unicos, inicio_do_dia = np.unique(dia, return_index=True)
    n_dias = len(dias_unicos)

    # posicao da barra dentro do proprio pregao (0 = primeira barra do dia)
    fim_do_dia = np.append(inicio_do_dia[1:], n)
    pos_no_dia = np.arange(n) - np.repeat(inicio_do_dia,
                                           fim_do_dia - inicio_do_dia)

    # um pregao mais curto que `barras_abertura` ainda calcula teto/piso
    # de uma janela PARCIAL aqui embaixo - quem impede o range incompleto
    # de valer e o filtro `formado`, logo a seguir, nunca este calculo
    teto = np.full(n, np.nan)
    piso = np.full(n, np.nan)
    for ini, fim in zip(inicio_do_dia, fim_do_dia):
        limite = min(ini + barras_abertura, fim)
        teto[ini:fim] = high[ini:limite].max()
        piso[ini:fim] = low[ini:limite].min()

    # a propria janela de abertura nao pode romper o range que ela mesma
    # esta formando - so depois dela conta. tambem cobre pregao mais
    # curto que a janela: nenhuma barra chega a `formado`, entao o range
    # parcial calculado acima nunca vira sinal
    formado = pos_no_dia >= barras_abertura
    valido = formado & ~(np.isnan(teto) | np.isnan(piso))

    # abertura estreita demais: rompimento em mercado parado e ruido caro
    largo = np.where(valido, (teto - piso) >= minimo, False)

    rompe_cima = valido & largo & (close > teto + folga)
    rompe_baixo = valido & largo & (close < piso - folga)
    candidato = rompe_cima | rompe_baixo

    # so o PRIMEIRO rompimento (qualquer direcao) de cada dia conta
    primeiro_do_dia = np.zeros(n, dtype=np.bool_)
    for ini, fim in zip(inicio_do_dia, fim_do_dia):
        idx = np.flatnonzero(candidato[ini:fim])
        if idx.size:
            primeiro_do_dia[ini + idx[0]] = True

    entrada_cima = rompe_cima & primeiro_do_dia
    entrada_baixo = rompe_baixo & primeiro_do_dia

    vazio = np.zeros(n, dtype=np.bool_)
    return Signals(
        entry_long=entrada_cima,
        entry_short=entrada_baixo,
        exit_long=vazio,
        exit_short=vazio,
    )
