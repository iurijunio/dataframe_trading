"""Stop e alvo vigentes na saida de cada operacao.

A tela de papel mostra o stop de uma posicao aberta ja com breakeven e stop
movel aplicados; so o kernel sabe esse valor, entao ele o devolve por trade.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine.execution import ExecutionProfile, backtest  # noqa: E402
from strategies.base import Signals, empty_like  # noqa: E402
from tests.test_engine import WIN, cenario, perfil  # noqa: E402


def _barras(ohlc):
    n = len(ohlc)
    a = np.asarray(ohlc, dtype=np.int64)
    return {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": a[:, 0].copy(), "high": a[:, 1].copy(),
        "low": a[:, 2].copy(), "close": a[:, 3].copy(),
    }


def _compra_na_barra_0(n):
    s = empty_like(n)
    s["entry_long"][0] = True
    return Signals(**s)


def _perfil(**kw) -> ExecutionProfile:
    base = dict(entrada_inicio="09:00", entrada_fim="09:05", fechamento="09:05",
                slippage_ticks=0, stop_pontos=100, alvo_pontos=200)
    base.update(kw)
    return ExecutionProfile(**base)


# entra em 100000 na barra 1; nenhuma barra toca stop (99900) nem alvo (100200)
SOBE = [
    (100000, 100010, 99990, 100000),
    (100000, 100120, 100000, 100100),
    (100100, 100150, 100090, 100120),
    (100120, 100130, 100110, 100120),
    (100120, 100130, 100110, 100120),
    (100120, 100130, 100110, 100120),
]


def test_sem_protecao_stop_e_alvo_ficam_nos_niveis_da_entrada():
    r = backtest(_barras(SOBE), _compra_na_barra_0(len(SOBE)), _perfil(), WIN)
    assert r.n_trades == 1
    assert r.trades["stop_fim"][0] == 100000 - 100
    assert r.trades["alvo_fim"][0] == 100000 + 200


def test_breakeven_aplicado_move_o_stop_para_a_entrada():
    # gatilho em 50% do alvo = 100 pontos; a barra 1 chega a +120
    r = backtest(_barras(SOBE), _compra_na_barra_0(len(SOBE)),
                 _perfil(breakeven_pct=50.0), WIN)
    assert r.trades["stop_fim"][0] == r.trades["entry_px"][0] == 100000


def test_stop_movel_acompanha_o_melhor_preco_menos_a_distancia():
    # melhor preco = 100150 (barra 2); distancia 50 -> stop em 100100
    r = backtest(_barras(SOBE), _compra_na_barra_0(len(SOBE)),
                 _perfil(trailing_pontos=50, alvo_pontos=300), WIN)
    assert r.trades["stop_fim"][0] == 100100
    assert r.trades["alvo_fim"][0] == 100300


def test_sem_stop_nem_alvo_devolve_zero():
    r = backtest(_barras(SOBE), _compra_na_barra_0(len(SOBE)),
                 _perfil(stop_pontos=0, alvo_pontos=0), WIN)
    assert r.trades["stop_fim"][0] == 0
    assert r.trades["alvo_fim"][0] == 0


def test_colunas_antigas_nao_mudam_e_niveis_novos_batem_a_mao():
    """Cenario de 4 trades do test_engine. Os valores antigos foram gravados
    da versao anterior ao `stop_fim`; os novos sao stop/alvo da entrada (sem
    protecoes) conferidos a mao."""
    bars, sinais = cenario()
    t = backtest(bars, sinais, perfil(), WIN).trades
    assert t["entry_i"].tolist() == [1, 4, 7, 9]
    assert t["exit_i"].tolist() == [2, 5, 7, 10]
    assert t["side"].tolist() == [1, -1, 1, 1]
    assert t["entry_px"].tolist() == [100000, 100300, 100500, 100600]
    assert t["exit_px"].tolist() == [100300, 100500, 100300, 100650]
    assert t["reason"].tolist() == [1, 0, 0, 3]
    assert t["mae"].tolist() == [-50, -250, -250, -50]
    assert t["mfe"].tolist() == [350, 50, 350, 100]
    assert t["points"].tolist() == [300, -200, -200, 50]
    assert t["stop_fim"].tolist() == [99800, 100500, 100300, 100400]
    assert t["alvo_fim"].tolist() == [100300, 100000, 100800, 100900]
    assert t["stop_fim"].dtype == np.int64 and t["alvo_fim"].dtype == np.int64
