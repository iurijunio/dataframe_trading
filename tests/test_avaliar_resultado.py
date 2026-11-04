"""A conta da Varredura como função: a busca automática avalia cada
combinação com `avaliar_resultado`, e o número tem de ser o mesmo da linha
da Varredura (`optimizer._uma`)."""
import math

import numpy as np
import pytest

from core import db_manager as db
from core import optimizer, walkforward as wf
from core.engine.execution import ExecutionProfile, executar, preparar

PERIODO = ("2024-01-01", "2024-12-31")


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")


def _iguais(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_iguais(a[k], b[k]) for k in a)
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or a == b
    return a == b


@pytest.fixture(scope="module")
def contexto():
    optimizer._init("WIN$N", *PERIODO, "setup_cruzamento")
    janelas = wf.montar_janelas(*PERIODO, 4, 2, 2, 2)
    return janelas


@pytest.mark.parametrize("params,campos", [
    ({"media_rapida": 9, "media_lenta": 34}, {}),
    ({"media_rapida": 5, "media_lenta": 144}, {"stop_pontos": 150, "alvo_pontos": 450}),
    # janela de um minuto num só dia: nenhum trade, o ramo vazio do _uma
    ({"media_rapida": 13, "media_lenta": 55}, {}),
])
def test_avaliar_resultado_igual_ao_uma(contexto, params, campos):
    janelas = contexto
    base = ExecutionProfile(timeframe="M5", min_operacoes=50).to_config()
    if params["media_rapida"] == 13:
        base.update(entrada_inicio="09:00", entrada_fim="09:00", dias_semana=[6])
    esperado = optimizer._uma((7, params, campos, base, janelas))

    perfil = ExecutionProfile(**{**base, **campos})
    prep = preparar(optimizer._BARS, optimizer._ESTRATEGIA, params, perfil.timeframe,
                    optimizer._INST)
    obtido = optimizer.avaliar_resultado(executar(prep, perfil), perfil, janelas, 7,
                                         {**params, **campos})
    assert esperado["erro"] is None
    assert _iguais(obtido, esperado)


def test_ramo_sem_trades_tem_holdout_vazio(contexto):
    base = ExecutionProfile(timeframe="M5", entrada_inicio="09:00",
                            entrada_fim="09:00", dias_semana=(6,))
    prep = preparar(optimizer._BARS, optimizer._ESTRATEGIA,
                    {"media_rapida": 9, "media_lenta": 34}, "M5", optimizer._INST)
    r = optimizer.avaliar_resultado(executar(prep, base), base, contexto, 1, {})
    assert r["geral"]["trades"] == 0 and r["holdout"]["trades"] == 0
    assert r["score"] == float("-inf") and r["passa_filtro"] is False
    assert np.isfinite(r["consistencia"])
