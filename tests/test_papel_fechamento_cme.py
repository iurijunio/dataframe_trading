"""Corte do papel: `perfil.fechamento` é hora humana (NY) e as barras estão no
relógio de pregão (NY + 360 min); a comparação tem de ser no mesmo relógio."""
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np

from core import papel
from strategies.base import Signals

DIA = date(2026, 10, 9)
MNQ = {"symbol": "MNQ", "currency": "USD", "timezone": "America/New_York",
       "price_decimals": 2, "tick_size": 0.25, "point_value": 2.0,
       "tick_value": 0.5, "sessao_abertura": "18:00",
       "abertura_referencia": "09:30"}
WIN = {"symbol": "WIN$N", "tick_size": 5, "point_value": 0.2, "tick_value": 1.0}


def _plano(entrada_inicio, entrada_fim, fechamento):
    return {"plano_id": 1, "contratos": 1, "params": {},
            "profile": {"timeframe": "M1", "entrada_inicio": entrada_inicio,
                        "entrada_fim": entrada_fim, "fechamento": fechamento,
                        "stop_tipo": "pontos", "stop_pontos": 200,
                        "alvo_tipo": "pontos", "alvo_pontos": 400,
                        "dias_semana": [1, 2, 3, 4, 5]}}


def _mod(sinal: datetime):
    def signals(bars, params):
        n = len(bars["close"])
        el = bars["ts"] == np.datetime64(sinal, "ns")
        z = np.zeros(n, dtype=bool)
        return Signals(el, z, z.copy(), z.copy())
    return SimpleNamespace(signals=signals)


def _barras(inicio: datetime, fim: datetime, base_px: int):
    ts = np.arange(np.datetime64(inicio, "ns"),
                   np.datetime64(fim, "ns") + np.timedelta64(1, "m"),
                   np.timedelta64(1, "m"))
    base = np.full(len(ts), base_px, dtype=np.int64)
    zero = np.zeros(len(ts), np.int64)
    return {"ts": ts, "open": base, "high": base + 1, "low": base - 1,
            "close": base, "tick_volume": zero, "volume": zero}


def _cme(fechamento_hhmm=None):
    # relógio de pregão: 00:00 = 18:00 NY; última barra 17:30 = 11:30 NY,
    # antes do fechamento 16:50 NY (= 22:50 no relógio de pregão)
    sinal = datetime(2026, 10, 9, 15, 0)
    barras = _barras(datetime(2026, 10, 9, 0, 0), datetime(2026, 10, 9, 17, 30),
                     2_000_000)
    plano = _plano("18:00", "16:30", "16:50")
    return papel.calcular(barras, DIA, plano, _mod(sinal), MNQ,
                          fechamento_hhmm=fechamento_hhmm)


def _win(fechamento_hhmm=None):
    sinal = datetime(2026, 10, 9, 10, 0)
    barras = _barras(datetime(2026, 10, 9, 9, 0), datetime(2026, 10, 9, 11, 30),
                     189_000)
    plano = _plano("09:00", "17:00", "17:50")
    return papel.calcular(barras, DIA, plano, _mod(sinal), WIN,
                          fechamento_hhmm=fechamento_hhmm)


def test_cme_operacao_aberta_antes_do_fechamento_ny_segue_aberta():
    ops = _cme()
    assert len(ops) == 1 and ops[0]["aberta"]


def test_win_sem_deslocamento_segue_aberta():
    ops = _win()
    assert len(ops) == 1 and ops[0]["aberta"]


def test_fechamento_explicito_nao_e_convertido():
    # já no relógio de pregão: 17:00 < última barra 17:30 => corte vencido
    assert not _cme("17:00")[0]["aberta"]
    # 23:00 de pregão (17:00 NY) ainda não chegou => segue aberta
    assert _cme("23:00")[0]["aberta"]
