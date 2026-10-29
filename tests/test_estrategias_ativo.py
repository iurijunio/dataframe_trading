"""Estrategias leem o tick e a abertura de referencia das barras (MES/MNQ)."""
import numpy as np

from core import db_manager as db
from core.engine.execution import ExecutionProfile, run_strategy
from strategies import (adx_direcao, rompimento_abertura, rompimento_canal,
                        rompimento_ema_abertura)

MES = db.load_instrument_yaml("MES")
WIN = db.load_instrument_yaml("WIN$N")
DIAS = np.array(["2026-10-26", "2026-10-27"], dtype="datetime64[D]")
BASE = 500_000  # unidades guardadas (MES: preco x 100)


def _hhmm(h, m=0):
    return h * 60 + m


class _Capta:
    """Embrulha uma estrategia e guarda barras e sinais do timeframe dela."""

    def __init__(self, mod):
        self.mod = mod
        self.name = mod.name
        self.params_schema = mod.params_schema
        self.sinais = None
        self.barras = None

    def signals(self, bars, params):
        self.barras = bars
        self.sinais = self.mod.signals(bars, params)
        return self.sinais


def _perfil(tf="M1"):
    return ExecutionProfile(timeframe=tf, entrada_inicio="09:00",
                            entrada_fim="15:00", fechamento="16:00",
                            stop_pontos=10, alvo_pontos=1000, slippage_ticks=0)


def _minutos(d, ini=14 * 60, fim=22 * 60 + 30):
    return (d.astype("datetime64[m]") + np.arange(ini, fim + 1)).astype("datetime64[ns]")


def _barras_planas(ajuste=None):
    """Dois pregoes 14:00-22:30 (relogio de pregao), preco parado em BASE."""
    ts = np.concatenate([_minutos(d) for d in DIAS])
    n = len(ts)
    minuto = ts.astype("datetime64[m]").astype(np.int64) % 1440
    o = np.full(n, BASE, dtype=np.int64)
    h, l, c = o.copy(), o.copy(), o.copy()
    if ajuste:
        ajuste(minuto, o, h, l, c)
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": np.ones(n, dtype=np.int64),
            "volume": np.ones(n, dtype=np.int64)}, minuto


def _sinal_min(capta, minuto, tipo="entry_long"):
    return minuto[np.flatnonzero(getattr(capta.sinais, tipo))]


def _passeio(seed, base, passo, n_dias=3):
    rng = np.random.default_rng(seed)
    dias = np.array(["2026-10-26", "2026-10-27", "2026-10-28"][:n_dias],
                    dtype="datetime64[D]")
    ts = np.concatenate([_minutos(d) for d in dias])
    n = len(ts)
    c = base + np.cumsum(rng.integers(-3, 4, n)) * passo
    o = np.concatenate(([c[0]], c[:-1]))
    h = np.maximum(o, c) + rng.integers(0, 3, n) * passo
    l = np.minimum(o, c) - rng.integers(0, 3, n) * passo
    return {"ts": ts, "open": o.astype(np.int64), "high": h.astype(np.int64),
            "low": l.astype(np.int64), "close": c.astype(np.int64),
            "tick_volume": np.ones(n, dtype=np.int64),
            "volume": np.ones(n, dtype=np.int64)}


def test_abertura_m1_usa_o_range_das_09h30_ny():
    def ajuste(minuto, o, h, l, c):
        # janela "errada" (primeiras 6 barras do dia) larga, e um pico as 14:30
        h[(minuto >= _hhmm(14)) & (minuto < _hhmm(14, 6))] = BASE + 10_000
        c[minuto == _hhmm(14, 30)] = BASE + 10_050
        h[minuto == _hhmm(14, 30)] = BASE + 10_050
        # janela certa 15:30-15:35: range estreito [BASE, BASE+100]
        h[(minuto >= _hhmm(15, 30)) & (minuto < _hhmm(15, 36))] = BASE + 100
        # rompimento as 15:40
        c[minuto == _hhmm(15, 40)] = BASE + 300
        h[minuto == _hhmm(15, 40)] = BASE + 300

    barras, minuto = _barras_planas(ajuste)
    e = _Capta(rompimento_abertura)
    run_strategy(barras, e, {"barras_abertura": 6, "folga_ticks": 1,
                             "filtro_amplitude": 0}, _perfil(), MES)
    m = _sinal_min(e, minuto)
    assert len(m) == 2 and (m == _hhmm(15, 40)).all()
    assert not e.sinais.entry_short.any()


def test_abertura_h1_usa_a_barra_que_comeca_depois_das_09h30():
    # barras H1: 15:00-15:59 (inicio 900, ts 15:59) e 16:00-16:59 (inicio 960).
    # A de abertura e a de inicio 960, nao a de ts 15:59.
    def ajuste(minuto, o, h, l, c):
        h[(minuto >= _hhmm(14)) & (minuto < _hhmm(16))] = BASE + 5000
        h[(minuto >= _hhmm(16)) & (minuto < _hhmm(17))] = BASE + 100
        c[minuto == _hhmm(19, 59)] = BASE + 400
        h[minuto == _hhmm(19, 59)] = BASE + 400

    barras, _ = _barras_planas(ajuste)
    e = _Capta(rompimento_abertura)
    run_strategy(barras, e, {"barras_abertura": 1, "folga_ticks": 1,
                             "filtro_amplitude": 0}, _perfil("H1"), MES)
    ts = e.barras["ts"].astype("datetime64[m]").astype(np.int64) % 1440
    inicio = e.barras["inicio_min"]
    assert inicio[np.flatnonzero(ts == _hhmm(15, 59))[0]] == 900
    idx = np.flatnonzero(e.sinais.entry_long)
    assert len(idx) == 2                      # um por dia
    assert (ts[idx] == _hhmm(19, 59)).all()   # range [BASE, BASE+100] rompido


def test_canal_folga_em_ticks_usa_o_tick_do_ativo():
    def ajuste(minuto, o, h, l, c):
        # 16:00 fecha em teto + 50 (nao rompe); 17:00 em teto + 75 (rompe)
        for mm, v in ((_hhmm(16), 50), (_hhmm(17), 75)):
            c[minuto == mm] = BASE + v
            h[minuto == mm] = BASE + v

    barras, minuto = _barras_planas(ajuste)
    e = _Capta(rompimento_canal)
    run_strategy(barras, e, {"periodo_canal": 5, "folga_ticks": 2,
                             "filtro_amplitude": 0}, _perfil(), MES)
    m = _sinal_min(e, minuto)
    assert len(m) == 2 and (m == _hhmm(17)).all()


def test_canal_filtro_amplitude_em_pontos_vira_unidade_guardada():
    def ajuste(minuto, o, h, l, c):
        h[minuto == _hhmm(15, 55)] = BASE + 200   # canal de 2 pontos
        c[minuto == _hhmm(16)] = BASE + 300
        h[minuto == _hhmm(16)] = BASE + 300

    barras, minuto = _barras_planas(ajuste)
    p = {"periodo_canal": 5, "folga_ticks": 0}
    e = _Capta(rompimento_canal)
    run_strategy(barras, e, {**p, "filtro_amplitude": 2}, _perfil(), MES)
    assert _hhmm(16) in _sinal_min(e, minuto)          # 2 pontos = 200 <= 200
    run_strategy(barras, e, {**p, "filtro_amplitude": 3}, _perfil(), MES)
    assert _hhmm(16) not in _sinal_min(e, minuto)      # 3 pontos = 300 > 200


def test_ema_abertura_so_depois_das_09h30_e_distancia_do_open_das_09h30():
    barras = _passeio(7, BASE, 25)
    minuto = barras["ts"].astype("datetime64[m]").astype(np.int64) % 1440
    p = {"ema_curta": 3, "ema_longa": 8, "distancia_abertura": 0}

    # sem as chaves o codigo usa a 1a barra do dia: aqui ha sinal antes das 15:30
    antigo = rompimento_ema_abertura.signals(dict(barras), p)
    assert (antigo.entry_long | antigo.entry_short)[minuto < _hhmm(15, 30)].any()

    e0 = _Capta(rompimento_ema_abertura)
    run_strategy(barras, e0, p, _perfil(), MES)
    longa0, curta0 = e0.sinais.entry_long, e0.sinais.entry_short
    assert (longa0 | curta0).any()
    assert not (longa0 | curta0)[minuto < _hhmm(15, 30)].any()

    e3 = _Capta(rompimento_ema_abertura)
    run_strategy(barras, e3, {**p, "distancia_abertura": 3}, _perfil(), MES)
    dia = barras["ts"].astype("datetime64[D]")
    ab = np.zeros(len(minuto), dtype=np.int64)
    for d in np.unique(dia):
        i = np.flatnonzero((dia == d) & (minuto == _hhmm(15, 30)))[0]
        ab[dia == d] = barras["open"][i]
    cl = barras["close"]
    # 3 pontos viram 300 guardadas, medidas do open das 15:30
    assert np.array_equal(e3.sinais.entry_long, longa0 & (cl - ab >= 300))
    assert np.array_equal(e3.sinais.entry_short, curta0 & (ab - cl >= 300))
    assert e3.sinais.entry_long.any() or e3.sinais.entry_short.any()
    assert (e3.sinais.entry_long.sum() + e3.sinais.entry_short.sum()
            < longa0.sum() + curta0.sum())


def test_adx_amplitude_max_em_pontos_vira_unidade_guardada():
    barras = _passeio(3, BASE, 25)
    p = {"di_periodo": 5, "adx_suavizacao": 5}
    amp = barras["high"] - barras["low"]
    assert amp.max() > 100
    e = _Capta(adx_direcao)
    run_strategy(barras, e, {**p, "amplitude_max": 2}, _perfil(), MES)
    ligado = e.sinais.entry_long | e.sinais.entry_short
    assert not ligado[amp > 200].any()          # 2 pontos = 200 guardadas
    assert ligado[(amp > 100) & (amp <= 200)].any()
    run_strategy(barras, e, {**p, "amplitude_max": 0}, _perfil(), MES)
    assert (e.sinais.entry_long | e.sinais.entry_short)[amp > 100].any()


def test_win_sinais_identicos_aos_de_signals_sem_chaves():
    barras = _passeio(11, 150_000, 5)
    casos = [
        (rompimento_abertura, {"barras_abertura": 6, "folga_ticks": 2,
                               "filtro_amplitude": 0}),
        (rompimento_canal, {"periodo_canal": 10, "folga_ticks": 2,
                            "filtro_amplitude": 0}),
        (rompimento_ema_abertura, {"ema_curta": 3, "ema_longa": 8,
                                   "distancia_abertura": 50}),
        (adx_direcao, {"di_periodo": 5, "adx_suavizacao": 5,
                       "amplitude_max": 300}),
    ]
    for mod, p in casos:
        p = {**{k: v["default"] for k, v in mod.params_schema.items()}, **p}
        direto = mod.signals(dict(barras), p)
        e = _Capta(mod)
        run_strategy(barras, e, p, _perfil(), WIN)
        assert e.barras["abertura_min"] is None and e.barras["tick"] == 5
        for campo in ("entry_long", "entry_short", "exit_long", "exit_short"):
            assert np.array_equal(getattr(e.sinais, campo),
                                  getattr(direto, campo)), (mod.name, campo)
        assert (direto.entry_long | direto.entry_short).any(), mod.name
