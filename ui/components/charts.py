"""Os dois graficos.

Preco: candles da janela visivel, com setas de compra e venda e, quando um
trade esta selecionado, as linhas de entrada, stop e alvo.

Capital: a curva inteira do backtest, em paines empilhados - equity em cima,
underwater embaixo, dividindo o mesmo eixo de tempo.

Nenhum dos dois recebe as 688 mil barras. O de preco recebe a janela agregada;
o de capital recebe um ponto por pregao operado.
"""

from __future__ import annotations

import numpy as np

from core import ativo

from .. import theme as T
from ..data import to_epoch


def opcoes_candle(simbolo: str | None) -> dict:
    """As opcoes do candle com o formato de preco do ativo (MES mostra
    centavos). Sem simbolo, ou no WIN, devolve o tema como sempre foi."""
    if not simbolo:
        return T.CANDLE_OPTIONS
    f = ativo.ficha(simbolo)
    passo = f.tick_size
    if float(passo).is_integer():
        passo = int(passo)
    fmt = {"type": "price", "precision": f.price_decimals, "minMove": passo}
    if fmt == T.CANDLE_OPTIONS["priceFormat"]:
        return T.CANDLE_OPTIONS
    return {**T.CANDLE_OPTIONS, "priceFormat": fmt}


def price_series(dados: dict, markers: list | None = None,
                 price_lines: list | None = None,
                 simbolo: str | None = None) -> list[dict]:
    return [
        {
            "id": "preco",
            "type": "candlestick",
            "data": dados["candles"],
            "options": opcoes_candle(simbolo),
            "markers": markers or [],
            "priceLines": price_lines or [],
            "pane": 0,
        },
        {
            "id": "volume",
            "type": "histogram",
            "data": dados["volume"],
            "options": {
                "priceFormat": {"type": "volume"},
                "priceLineVisible": False,
                "lastValueVisible": False,
            },
            "priceScaleOptions": {"scaleMargins": {"top": 0.1, "bottom": 0}},
            "pane": 1,
        },
    ]


def trade_markers(trades: dict, t0: int, t1: int, limite: int = 400, f=None) -> list[dict]:
    """Setas de entrada e saida dos trades que caem na janela visivel.

    Com a ficha do ativo, tempo e pontos saem na mesma unidade dos candles.
    """
    if not trades or not len(trades["entry_i"]):
        return []
    trades = ativo.trades_para_exibir(trades, f)

    ent = np.array([to_epoch(t) for t in trades["entry_ts"]])
    sai = np.array([to_epoch(t) for t in trades["exit_ts"]])
    dentro = np.flatnonzero((sai >= t0) & (ent <= t1))
    if dentro.size > limite:
        dentro = dentro[:limite]

    out = []
    for i in dentro:
        comprado = trades["side"][i] == 1
        pts = trades["points"][i]
        pts = int(pts) if f is None or f.escala == 1 else round(float(pts), f.price_decimals)
        out.append({
            "time": int(ent[i]),
            "position": "belowBar" if comprado else "aboveBar",
            "color": T.ACCENT if comprado else T.ACCENT_2,
            "shape": "arrowUp" if comprado else "arrowDown",
            "text": "C" if comprado else "V",
        })
        out.append({
            "time": int(sai[i]),
            "position": "aboveBar" if comprado else "belowBar",
            "color": T.POS if pts > 0 else T.NEG,
            "shape": "circle",
            "text": f"{pts:+d}" if isinstance(pts, int) else f"{pts:+.{f.price_decimals}f}",
        })
    out.sort(key=lambda m: m["time"])
    return out


def _arred(v, f):
    return v if f is None or f.escala == 1 else round(v, f.price_decimals)


def trade_price_lines(res, i: int, f=None) -> list[dict]:
    """Entrada, stop, alvo e saida do trade selecionado.

    Stop e alvo saem dos valores CONGELADOS na barra de entrada, nao dos
    parametros atuais da tela: com stop em ATR eles mudam a cada barra, e
    desenhar o valor de hoje sobre um trade de 2023 seria mentira.
    """
    trades = res.trades
    if i is None or i >= len(trades["entry_i"]):
        return []
    lado = int(trades["side"][i])
    entrada = int(trades["entry_px"][i])
    stop = int(res.sl_at_entry[i])
    alvo = int(res.tp_at_entry[i])
    saida = int(trades["exit_px"][i])
    if f is not None and f.escala != 1:
        # tudo guardado em unidades de preco: volta para pontos antes de desenhar
        entrada, stop, alvo, saida = (ativo.preco_para_exibir(v, f)
                                      for v in (entrada, stop, alvo, saida))

    linhas = [
        {"price": entrada, "color": T.ACCENT, "lineWidth": 2, "lineStyle": 0,
         "axisLabelVisible": True, "title": "entrada"},
        {"price": saida, "color": T.ACCENT_2, "lineWidth": 1,
         "lineStyle": 3, "axisLabelVisible": True, "title": "saída"},
    ]
    if stop > 0:
        linhas.append({"price": _arred(entrada - lado * stop, f), "color": T.NEG,
                       "lineWidth": 1, "lineStyle": 2,
                       "axisLabelVisible": True, "title": "stop"})
    if alvo > 0:
        linhas.append({"price": _arred(entrada + lado * alvo, f), "color": T.POS,
                       "lineWidth": 1, "lineStyle": 2,
                       "axisLabelVisible": True, "title": "alvo"})
    return linhas


def equity_series(trades: dict, liquido: np.ndarray, capital: float) -> list[dict]:
    """Curva de capital por pregao, com o underwater num paine proprio."""
    if not len(liquido):
        return []

    dias = trades["exit_ts"].astype("datetime64[D]")
    unicos, inv = np.unique(dias, return_inverse=True)
    por_dia = np.zeros(len(unicos))
    np.add.at(por_dia, inv, liquido)

    equity = capital + np.cumsum(por_dia)
    pico = np.maximum.accumulate(equity)
    under = equity - pico

    tempos = [int(np.datetime64(d, "s").astype("int64")) for d in unicos]

    return [
        {
            "id": "equity",
            "type": "area",
            "data": [{"time": t, "value": round(float(v), 2)}
                     for t, v in zip(tempos, equity)],
            "options": {
                "lineColor": T.ACCENT,
                "topColor": "rgba(138,162,255,.22)",
                "bottomColor": "rgba(138,162,255,.01)",
                "lineWidth": 2,
                "priceLineVisible": False,
            },
            "priceLines": [{"price": round(capital, 2), "color": T.LINE,
                            "lineWidth": 1, "lineStyle": 2,
                            "axisLabelVisible": False, "title": "capital inicial"}],
            "pane": 0,
        },
        {
            "id": "underwater",
            "type": "area",
            "data": [{"time": t, "value": round(float(v), 2)}
                     for t, v in zip(tempos, under)],
            "options": {
                "lineColor": T.NEG,
                "topColor": "rgba(229,128,110,.02)",
                "bottomColor": "rgba(229,128,110,.30)",
                "lineWidth": 1,
                "priceLineVisible": False,
                "lastValueVisible": False,
                "invertScale": False,
            },
            "pane": 1,
        },
    ]
