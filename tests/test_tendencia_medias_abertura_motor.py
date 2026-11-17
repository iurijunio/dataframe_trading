"""A reentrada da tendência pelas médias passando pelo motor de verdade."""

from __future__ import annotations

import numpy as np

from core import db_manager
from core.engine.execution import ExecutionProfile, run_strategy
from strategies import tendencia_medias_abertura
from strategies.base import defaults

WIN = db_manager.load_instrument_yaml("WIN$N")
B = 100_000
FLAT = (B, B + 10, B - 10, B)
A = (B, B + 420, B, B + 410)
CONFIRMA = (B + 410, B + 460, B + 400, B + 450)
STOPA = (B + 450, B + 470, B + 330, B + 460)   # bate o stop de 100 e fecha longe
SEGUE = (B + 460, B + 480, B + 455, B + 470)
VOLTA = (B + 470, B + 470, B + 100, B + 150)  # perto da abertura: desarma


def _barras(seq, inicio="2026-03-04T09:00"):
    n = len(seq)
    o, h, l, c = (np.asarray(col, dtype=np.int64) for col in zip(*seq))
    ts = (np.datetime64(inicio, "m") + np.arange(n)).astype("datetime64[ns]")
    um = np.ones(n, dtype=np.int64)
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": um, "volume": um.copy()}


def _rodar(seq, timeframe="M1"):
    perfil = ExecutionProfile(timeframe=timeframe, entrada_inicio="09:00", entrada_fim="15:00",
                              fechamento="16:00", stop_pontos=100,
                              alvo_pontos=10_000, slippage_ticks=0)
    params = defaults(tendencia_medias_abertura.params_schema) | {
        "ema_rapida": 2, "ema_intermediaria": 3, "ema_lenta": 4, "distancia_pontos": 300}
    return run_strategy(_barras(seq), tendencia_medias_abertura, params, perfil, WIN)


def test_stopada_e_ainda_armada_entra_de_novo_no_candle_seguinte():
    res = _rodar([FLAT] * 5 + [A, CONFIRMA, STOPA] + [SEGUE] * 5)
    assert list(res.trades["entry_i"][:res.n_trades]) == [7, 8]
    assert res.trades["exit_i"][0] == 7


def test_stopada_e_desarmada_nao_entra_de_novo():
    res = _rodar([FLAT] * 5 + [A, CONFIRMA, VOLTA] + [SEGUE] * 5)
    assert list(res.trades["entry_i"][:res.n_trades]) == [7]


def _em_minutos(candle):
    """Cinco M1 que agregam no candle: abre, vai à máxima, à mínima, fecha."""
    o, h, l, c = candle
    return [(o, o, o, o), (o, h, o, h), (h, h, l, l),
            (l, max(l, c), min(l, c), c), (c, c, c, c)]


def test_em_m5_reentra_na_abertura_do_candle_seguinte_ao_stop():
    candles = [FLAT] * 5 + [A, CONFIRMA, STOPA] + [SEGUE] * 3
    minutos = [m for candle in candles for m in _em_minutos(candle)]
    res = _rodar(minutos, timeframe="M5")
    # entra na abertura do candle 7 (minuto 35), stopa no minuto da mínima
    # (37) e volta na abertura do candle 8 (minuto 40)
    assert list(res.trades["entry_i"][:res.n_trades]) == [35, 40]
    assert res.trades["exit_i"][0] == 37


def test_mes_converte_os_pontos_e_mantem_a_porcentagem():
    mes = db_manager.load_instrument_yaml("MES")
    base = 500_000  # 5000,00 guardado em centésimos
    seq = [(base, base + 100, base - 100, base)] * 5 + [
        (base, base + 2200, base, base + 2100),          # A: 21,00 pts acima
        (base + 2100, base + 2300, base + 2000, base + 2250),  # B: 22,50 pts
    ] + [(base + 2250, base + 2300, base + 2200, base + 2275)] * 3

    def entradas(**p):
        perfil = ExecutionProfile(entrada_inicio="00:00", entrada_fim="16:00",
                                  fechamento="16:30", stop_pontos=8,
                                  alvo_pontos=1000, slippage_ticks=0)
        params = defaults(tendencia_medias_abertura.params_schema) | {
            "ema_rapida": 2, "ema_intermediaria": 3, "ema_lenta": 4} | p
        r = run_strategy(_barras(seq, "2026-03-04T10:00"), tendencia_medias_abertura,
                         params, perfil, mes)
        return list(r.trades["entry_i"][:r.n_trades])

    assert entradas(distancia_pontos=20) == [7]
    assert entradas(distancia_pontos=22) == []
    # 40 centésimos de 5000 = 20 pts; 45 = 22,5 pts
    pct = tendencia_medias_abertura.EM_PORCENTO
    assert entradas(unidade_distancia=pct, distancia_centesimos_pct=40) == [7]
    assert entradas(unidade_distancia=pct, distancia_centesimos_pct=45) == []
