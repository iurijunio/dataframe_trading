"""O motor em camadas tem de dar os mesmos trades do motor de antes.

O gabarito (`tests/dados/motor_camadas.json`) foi gravado com o motor antigo,
por `scripts/gabarito_motor.py`; cada caso é um hash dos trades.
"""
import json

import numpy as np

import pytest

from core import db_manager as db
from scripts.gabarito_motor import ARQUIVO, assinatura, casos


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        db.read_bars_parquet("MES", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


precisa_parquet = pytest.mark.skipif(not _tem_parquet(),
                                     reason="sem espelho Parquet do WIN/MES")


@pytest.fixture(scope="module")
def todos_os_casos():
    return list(casos())


@precisa_parquet
def test_motor_bate_com_o_gabarito(todos_os_casos):
    from core.engine.execution import run_strategy

    gabarito = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    assert len(gabarito) == len(todos_os_casos)
    for chave, bars, mod, params, perfil, inst, va in todos_os_casos:
        res = run_strategy(bars, mod, params, perfil, inst, vela_aberta=va)
        assert assinatura(res) == gabarito[chave], chave


# ------------------------------------------------------------ camadas
def _chave_prep(mod, params, perfil, inst, va):
    return (inst.get("symbol"), mod.name, tuple(sorted(params.items())),
            perfil.timeframe, va)


@precisa_parquet
def test_preparado_compartilhado_bate_com_o_gabarito(todos_os_casos):
    """Um Preparado servindo todos os perfis do mesmo sinal (o que a busca
    faz) tem de dar os trades do motor antigo: o cache não pode vazar de um
    perfil para outro."""
    from core.engine.execution import executar, preparar

    gabarito = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    preps = {}
    for chave, bars, mod, params, perfil, inst, va in todos_os_casos:
        k = _chave_prep(mod, params, perfil, inst, va)
        if k not in preps:
            preps[k] = preparar(bars, mod, params, perfil.timeframe, inst,
                                vela_aberta=va)
        assert assinatura(executar(preps[k], perfil)) == gabarito[chave], chave
    # o compartilhamento existiu de fato
    assert len(preps) < len(todos_os_casos) / 3


@precisa_parquet
def test_executar_recusa_outro_timeframe(todos_os_casos):
    from core.engine.execution import ExecutionProfile, executar, preparar

    _, bars, mod, params, _, inst, _ = todos_os_casos[0]
    prep = preparar(bars, mod, params, "M5", inst)
    with pytest.raises(ValueError):
        executar(prep, ExecutionProfile(timeframe="M1"))


@precisa_parquet
def test_executar_nao_muda_o_preparado(todos_os_casos):
    from core.engine.execution import ExecutionProfile, executar, preparar

    _, bars, mod, params, _, inst, _ = todos_os_casos[0]
    prep = preparar(bars, mod, params, "M5", inst)
    antes = {k: np.array(v, copy=True) for k, v in vars(prep.sinais).items()
             if isinstance(v, np.ndarray)}
    barras = {k: np.array(v, copy=True) for k, v in prep.bars.items()}
    for p in (ExecutionProfile(timeframe="M5", stop_tipo="atr", stop_atr_mult=1.0,
                               filtro_adx="tendencia", adx_periodo=14, adx_limiar=20),
              ExecutionProfile(timeframe="M5", entrada_inicio="10:00",
                               entrada_fim="11:00", dias_semana=(2,))):
        executar(prep, p)
    for k, v in antes.items():
        assert np.array_equal(getattr(prep.sinais, k), v), k
    for k, v in barras.items():
        assert np.array_equal(prep.bars[k], v), k


@precisa_parquet
def test_vela_aberta_recua_a_ultima_vela(todos_os_casos):
    from core.engine.execution import preparar

    _, bars, mod, params, _, inst, _ = todos_os_casos[0]
    a = preparar(bars, mod, params, "M5", inst)
    b = preparar(bars, mod, params, "M5", inst, vela_aberta=True)
    assert b.fechada[-1] == a.fechada[-1] - 1
    assert np.array_equal(b.fechada[:-1], a.fechada[:-1])


@precisa_parquet
def test_cache_tem_limite(todos_os_casos):
    """Milhares de perfis num Preparado não podem acumular ATR/ADX sem fim:
    com 20 núcleos a memória estoura."""
    from core.engine.execution import ExecutionProfile, executar, preparar

    _, bars, mod, params, _, inst, _ = todos_os_casos[0]
    prep = preparar(bars, mod, params, "M5", inst)
    for p in range(5, 25):
        executar(prep, ExecutionProfile(timeframe="M5", stop_tipo="atr",
                                        stop_atr_periodo=p, filtro_adx="rango",
                                        adx_periodo=p, adx_limiar=20))
    assert set(prep.cache) == {("relogio",), *[("atr", p) for p in range(21, 25)],
                               *[("adx", p) for p in range(21, 25)]}


def test_memo_descarta_o_usado_ha_mais_tempo():
    from core.engine.execution import _memo

    cache = {}
    for p in (1, 2, 3, 4):
        _memo(cache, ("atr", p), lambda: np.zeros(3))
    _memo(cache, ("atr", 1), lambda: pytest.fail("devia vir do cache"))
    _memo(cache, ("atr", 5), lambda: np.zeros(3))
    assert ("atr", 1) in cache and ("atr", 2) not in cache


def test_cache_travado_contra_escrita():
    from core.engine.execution import _memo

    cache = {}
    a = _memo(cache, ("atr", 3), lambda: np.zeros(3))
    b, c = _memo(cache, ("adx", 3), lambda: (np.zeros(3), np.zeros(3)))
    for x in (a, b, c):
        with pytest.raises(ValueError):
            x[0] = 1


@precisa_parquet
def test_periodos_diferentes_no_mesmo_preparado(todos_os_casos):
    """ATR e ADX de períodos diferentes, um depois do outro, no mesmo
    Preparado: cada um igual ao de um Preparado novo."""
    from core.engine.execution import ExecutionProfile, executar, preparar

    _, bars, mod, params, _, inst, _ = todos_os_casos[0]
    prep = preparar(bars, mod, params, "M5", inst)
    perfis = [ExecutionProfile(timeframe="M5", filtro_adx="tendencia",
                               adx_periodo=p, adx_limiar=20, stop_tipo="atr",
                               stop_atr_periodo=p, stop_atr_mult=m)
              for p, m in ((14, 1.5), (7, 1.5), (14, 2.5), (7, 1.0))]
    for perf in perfis:
        novo = executar(preparar(bars, mod, params, "M5", inst), perf)
        assert assinatura(executar(prep, perf)) == assinatura(novo)
