"""run_strategy e o ponto unico de conversao humano -> unidades guardadas."""
from dataclasses import replace

import numpy as np

from core import ativo
from core import db_manager as db
from core.engine.execution import (ExecutionProfile, backtest, run_strategy)
from strategies.base import Signals

MES_INST = db.load_instrument_yaml("MES")
WIN_INST = db.load_instrument_yaml("WIN$N")


def _barras(base, passo):
    """3 dias, 14:00-22:30 (relogio de pregao), preco caindo `passo` por minuto."""
    dias = np.array(["2026-10-26", "2026-10-27", "2026-10-28"], dtype="datetime64[D]")
    ts = np.concatenate([
        (d.astype("datetime64[m]") + np.arange(14 * 60, 22 * 60 + 31)) for d in dias
    ]).astype("datetime64[ns]")
    n = len(ts)
    minuto_do_dia = (ts.astype("datetime64[m]").astype(np.int64) % 1440) - 14 * 60
    abre = (base - passo * minuto_do_dia).astype(np.int64)
    fecha = abre - passo
    return {
        "ts": ts, "open": abre, "high": abre.copy(), "low": fecha.copy(),
        "close": fecha, "tick_volume": np.ones(n, dtype=np.int64),
        "volume": np.ones(n, dtype=np.int64),
    }


class _Estrategia:
    name = "teste"
    params_schema = {"k": {"tipo": "int", "default": 30, "min": 1, "max": 1000, "step": 1}}

    def __init__(self):
        self.visto = None

    def signals(self, bars, params):
        self.visto = bars
        n = len(bars["open"])
        entrada = np.zeros(n, dtype=bool)
        entrada[:: int(params["k"])] = True
        z = np.zeros(n, dtype=bool)
        return Signals(entry_long=entrada, entry_short=z.copy(),
                       exit_long=z.copy(), exit_short=z.copy())


def _perfil(**kw):
    base = dict(entrada_inicio="09:00", entrada_fim="15:00", fechamento="16:00",
                stop_pontos=10, alvo_pontos=1000, slippage_ticks=0)
    base.update(kw)
    return ExecutionProfile(**base)


def _mes():
    return _barras(500_000, 100)


def test_unidades_stop_em_pontos_vira_unidades_guardadas():
    perfil = _perfil()
    res = run_strategy(_mes(), _Estrategia(), {"k": 30}, perfil, MES_INST)
    assert res.n_trades > 0
    assert (res.sl_at_entry[res.sl_at_entry > 0] == 1000).all()
    assert res.profile is perfil and perfil.stop_pontos == 10
    assert res.instrument["tick_size"] == 25


def test_chamada_dupla_da_trades_iguais():
    perfil, barras = _perfil(), _mes()
    a = run_strategy(barras, _Estrategia(), {"k": 30}, perfil, MES_INST)
    b = run_strategy(barras, _Estrategia(), {"k": 30}, perfil, MES_INST)
    assert a.trades.keys() == b.trades.keys()
    for k in a.trades:
        assert np.array_equal(a.trades[k], b.trades[k])


def test_instrumento_ja_convertido_nao_converte_de_novo():
    perfil, barras = _perfil(), _mes()
    a = run_strategy(barras, _Estrategia(), {"k": 30}, perfil, MES_INST)
    # instrumento guardado => o par (perfil, instrumento) ja esta em unidades
    # guardadas: nada e convertido de novo (100x seria 100000)
    guardado = replace(perfil, stop_pontos=1000, alvo_pontos=100_000, entrada_inicio="15:00",
                      entrada_fim="21:00", fechamento="22:00")
    b = run_strategy(barras, _Estrategia(), {"k": 30}, guardado, a.instrument)
    assert np.array_equal(a.sl_at_entry, b.sl_at_entry)
    assert (b.sl_at_entry[b.sl_at_entry > 0] == 1000).all()


def test_chaves_extras_em_m1_e_h1_sem_sujar_o_dict_do_chamador():
    barras = _mes()
    chaves = set(barras)
    e = _Estrategia()
    run_strategy(barras, e, {"k": 30}, _perfil(timeframe="M1"), MES_INST)
    assert e.visto["tick"] == 25 and e.visto["abertura_min"] == 930
    assert np.array_equal(e.visto["inicio_min"],
                          barras["ts"].astype("datetime64[m]").astype(np.int64) % 1440)
    assert set(barras) == chaves

    e = _Estrategia()
    run_strategy(barras, e, {"k": 2}, _perfil(timeframe="H1"), MES_INST)
    v = e.visto
    assert v["tick"] == 25 and v["abertura_min"] == 930
    assert len(v["inicio_min"]) == len(v["ts"])
    assert set(barras) == chaves
    i = int(np.flatnonzero(v["ts"].astype("datetime64[m]").astype(np.int64) % 1440 == 15 * 60 + 59)[0])
    assert v["inicio_min"][i] == 900
    assert v["inicio_min"][0] == 14 * 60


def test_janela_de_horario_em_hora_de_nova_york():
    perfil = _perfil(entrada_inicio="09:30", entrada_fim="10:00")
    res = run_strategy(_mes(), _Estrategia(), {"k": 15}, perfil, MES_INST)
    assert res.n_trades > 0
    minuto = res.trades["entry_ts"].astype("datetime64[m]").astype(np.int64) % 1440
    assert ((minuto >= 15 * 60 + 30) & (minuto <= 16 * 60)).all()


def _por_dia(res):
    dias = res.trades["entry_ts"].astype("datetime64[D]")
    return np.unique(dias, return_counts=True)[1]


def test_limite_diario_em_dinheiro_usa_valor_por_unidade():
    barras = _mes()
    livre = run_strategy(barras, _Estrategia(), {"k": 30}, _perfil(), MES_INST)
    um = run_strategy(barras, _Estrategia(), {"k": 30},
                      _perfil(limite_perda_contrato=50.0), MES_INST)
    dois = run_strategy(barras, _Estrategia(), {"k": 30},
                        _perfil(limite_perda_contrato=100.0), MES_INST)
    assert _por_dia(livre).max() > 2
    assert (_por_dia(um) == 1).all()
    assert (_por_dia(dois) == 2).all()


def test_win_e_identidade():
    barras = _barras(150_000, 100)
    perfil = _perfil(entrada_inicio="09:00", entrada_fim="15:00", fechamento="16:00",
                     stop_pontos=1000, alvo_pontos=10_000)
    e = _Estrategia()
    res = run_strategy(barras, e, {"k": 30}, perfil, WIN_INST)
    assert e.visto["tick"] == 5 and e.visto["abertura_min"] is None
    assert res.instrument is WIN_INST and res.profile is perfil

    n = len(barras["open"])
    s = _Estrategia().signals(barras, {"k": 30})
    sig = Signals(entry_long=s.entry_long, entry_short=s.entry_short,
                  exit_long=s.exit_long, exit_short=s.exit_short,
                  sl_points=0, tp_points=0, virar=False)
    ref = backtest(barras, sig, perfil, WIN_INST, barras, np.arange(n))
    assert ref.n_trades == res.n_trades > 0
    for k in ref.trades:
        assert np.array_equal(ref.trades[k], res.trades[k])
    assert np.array_equal(ref.sl_at_entry, res.sl_at_entry)
