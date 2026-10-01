"""Serviço de captura: as contas (core/captura.py), com MT5 e relógio falsos."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import captura as C  # noqa: E402


def barras(*horas, base=100000):
    """Um candle por horário 'HH:MM' de 01/10/2026."""
    ts = [datetime(2026, 10, 1, int(h[:2]), int(h[3:])) for h in horas]
    n = len(ts)
    return pl.DataFrame({
        "ts": ts, "open": [base] * n, "high": [base + 50] * n,
        "low": [base - 50] * n, "close": [base + 10] * n,
        "tick_volume": [100] * n, "volume": [500] * n, "spread": [5] * n,
    })


def test_fechados_nunca_devolve_o_candle_em_formacao():
    b = barras("10:00", "10:01", "10:02")
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 30))["ts"].to_list() == b["ts"].to_list()[:2]


def test_fechados_ultimo_vira_fechado_65s_depois_do_inicio():
    b = barras("10:00", "10:01")
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 4)).height == 1
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 5)).height == 2


def test_fechados_sem_hora_do_servidor_nunca_grava_o_ultimo():
    assert C.fechados(barras("10:00", "10:01"), None).height == 1


def test_apos_queda_de_3h_devolve_tudo_menos_o_em_formacao():
    horas = [f"{h:02d}:{m:02d}" for h in range(10, 13) for m in range(60)]
    b = barras(*horas, "13:00")
    assert C.fechados(b, datetime(2026, 10, 1, 13, 0, 20)).height == 180


def test_fechados_sem_barras_devolve_vazio():
    assert C.fechados(barras("10:00").head(0), datetime(2026, 10, 1, 10, 5)).height == 0


# ------------------------------------------------------- relógio do servidor
T = datetime(2026, 10, 1, 10, 1, 29)


def test_relogio_soma_o_tempo_decorrido_desde_que_o_tick_mudou():
    r = C.RelogioServidor()
    r.observar(T, mono=100.0)
    r.observar(T, mono=130.0)            # mesmo tick: não reinicia a contagem
    assert r.agora(mono=140.0) == T + timedelta(seconds=40)
    r.observar(T + timedelta(seconds=45), mono=145.0)
    assert r.agora(mono=146.0) == T + timedelta(seconds=46)


def test_pc_adiantado_3_min_nao_deixa_passar_o_em_formacao():
    # o PC marca 10:04:29; a hora real (e o tick) é 10:01:29
    r = C.RelogioServidor()
    r.observar(T, mono=0.0)
    b = barras("10:00", "10:01")
    assert C.fechados(b, r.agora(mono=1.0))["ts"].to_list() == b["ts"].to_list()[:1]
    assert r.desvio_s(datetime(2026, 10, 1, 10, 4, 29), mono=1.0) == pytest.approx(179, abs=1)


def test_mercado_parado_fecha_o_ultimo_pelo_tempo_decorrido():
    r = C.RelogioServidor()
    r.observar(datetime(2026, 10, 1, 10, 1, 10), mono=0.0)   # último negócio
    b = barras("10:00", "10:01")
    assert C.fechados(b, r.agora(mono=50.0)).height == 1     # 10:02:00
    assert C.fechados(b, r.agora(mono=56.0)).height == 2     # 10:02:06


def test_relogio_sem_tick_nao_sabe_a_hora():
    r = C.RelogioServidor()
    r.observar(None, mono=0.0)
    assert r.agora(mono=5.0) is None and r.desvio_s(T, mono=5.0) is None
