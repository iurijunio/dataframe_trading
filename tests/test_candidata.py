"""Testes da tela Candidata (passo 10 da metodologia).

A disciplina de sempre: cada caso tem a resposta conhecida de antemão.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata  # noqa: E402

CAP = 10_000.0


def test_chave_iguala_float_e_int_do_mesmo_ponto_da_grade():
    """O DEPLOY vem do JSON como 78.0; mining_trials gravou 78. Sem
    normalizar, a vizinhança não acha vizinho nenhum e não dá erro."""
    assert candidata.chave({"periodo_canal": 78.0, "folga": 9.0}) == \
        candidata.chave({"folga": 9, "periodo_canal": 78})


def test_chave_preserva_texto_e_booleano():
    k = dict(candidata.chave({"lado": "compra", "usa_trail": True, "n": 3.0}))
    assert k["lado"] == "compra" and k["usa_trail"] is True and k["n"] == 3.0


def test_por_pregao_enche_os_dias_parados_com_zero():
    """Quem opera pouco tinha Sharpe inflado: a série precisa dos zeros."""
    saida = np.array(["2024-03-04T15:00", "2024-03-06T10:00"],
                     dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([100.0, -40.0]))
    assert len(dias) == 3                       # 04, 05 e 06 de março
    assert list(pnl) == [100.0, 0.0, -40.0]


def test_por_pregao_soma_os_trades_do_mesmo_dia_e_pula_fim_de_semana():
    saida = np.array(["2024-03-08T10:00", "2024-03-08T16:00",
                      "2024-03-11T10:00"], dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([10.0, 5.0, -3.0]))
    assert len(dias) == 2                       # sexta e segunda
    assert list(pnl) == [15.0, -3.0]


def test_por_pregao_respeita_o_recorte_pedido():
    saida = np.array(["2024-03-04T10:00", "2024-04-01T10:00"],
                     dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([10.0, 20.0]),
                                     de="2024-03-01", ate="2024-04-01")
    assert pnl.sum() == 10.0                    # abril ficou fora
    assert len(dias) == 21


def test_risco_de_desligar_le_a_distribuicao_do_bootstrap():
    boot = {"quedas": np.array([100.0, 200.0, 300.0, 400.0])}
    assert candidata.risco_de_desligar(boot, 250.0) == pytest.approx(50.0)
    assert candidata.risco_de_desligar(boot, 1000.0) == 0.0
    assert candidata.risco_de_desligar({}, 100.0) is None


def test_limite_no_p95_deixa_cerca_de_cinco_por_cento_de_falso_desligamento():
    """É a razão de o número existir: desligar no p95 desliga uma estratégia
    sadia em 5% dos ciclos, e isso precisa estar escrito no plano."""
    rng = np.random.default_rng(5)
    dia = rng.normal(10, 100, 400)
    from core import robustez
    b = robustez.bootstrap(dia, 10_000.0, n=600, semente=8)
    assert candidata.risco_de_desligar(b, b["dd_p95"]) == pytest.approx(5.0, abs=1.5)
