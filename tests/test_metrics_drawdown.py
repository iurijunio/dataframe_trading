"""Testes do drawdown — os três percentuais e a duração.

Existiam zero testes sobre `_drawdown`, e é ali que mora a distinção que mais
confunde: o MT5 reporta o *Balance Drawdown Maximal* (o maior mergulho em
dinheiro, com o percentual daquele ponto) e o *Balance Drawdown Relative* (o
maior mergulho em percentual, que pode estar em outro ponto da curva).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.metrics import _drawdown  # noqa: E402

CAP = 10_000.0


def test_o_maior_em_reais_nao_e_o_maior_em_percentual():
    """O caso que separa as duas métricas do MT5.

    A curva sobe a 11.000, cai para 9.000 (−18,2% do pico), dispara para
    20.000 e recua para 17.000 (−15,0% do pico, mas −3.000 em dinheiro).
    O mergulho MAIOR em reais é o segundo; o mais doloroso em percentual é o
    primeiro. Confundir um com o outro subestima o sofrimento da curva.
    """
    abs_, pct, pct_cap, rel, _ = _drawdown(
        np.array([11_000.0, 9_000.0, 20_000.0, 17_000.0]), CAP)

    assert abs_ == pytest.approx(3_000.0)          # o maior em dinheiro
    assert pct == pytest.approx(15.0)              # o % DAQUELE ponto
    assert rel == pytest.approx(2_000 / 11_000 * 100)   # o maior % da curva
    assert rel > pct
    assert pct_cap == pytest.approx(30.0)          # sobre o capital inicial


def test_os_tres_coincidem_quando_o_fundo_e_o_comeco():
    """Estratégia que só perde: pico é o capital inicial, e aí as três bases
    de percentual descrevem o mesmo ponto."""
    abs_, pct, pct_cap, rel, _ = _drawdown(np.array([9_000.0, 8_000.0]), CAP)
    assert abs_ == pytest.approx(2_000.0)
    assert pct == pytest.approx(20.0) == pytest.approx(pct_cap)
    assert rel == pytest.approx(20.0)


def test_mergulho_inicial_nao_fica_invisivel():
    """O capital entra como primeiro ponto da curva. Sem ele, uma estratégia
    que abre perdendo teria drawdown zero até fazer o primeiro topo."""
    abs_, pct, _, _, _ = _drawdown(np.array([9_500.0, 9_800.0]), CAP)
    assert abs_ == pytest.approx(500.0)
    assert pct == pytest.approx(5.0)


def test_curva_que_so_sobe_nao_tem_drawdown():
    abs_, pct, pct_cap, rel, dur = _drawdown(
        np.array([10_100.0, 10_400.0, 11_000.0]), CAP)
    assert (abs_, pct, pct_cap, rel, dur) == (0.0, 0.0, 0.0, 0.0, 0)


def test_duracao_e_a_maior_sequencia_sem_novo_topo():
    #        topo    ---- submerso 3 pontos ----   novo topo
    eq = np.array([11_000.0, 10_500.0, 10_200.0, 10_800.0, 12_000.0])
    *_, dur = _drawdown(eq, CAP)
    assert dur == 3


def test_capital_zero_nao_divide_por_zero():
    abs_, pct, pct_cap, rel, _ = _drawdown(np.array([-100.0, -200.0]), 0.0)
    assert pct_cap == 0.0 and np.isfinite(rel)


def test_curva_vazia():
    assert _drawdown(np.array([]), CAP) == (0.0, 0.0, 0.0, 0.0, 0)
