"""Estratégia ADX direção (`strategies/adx_direcao.py`).

A referência aqui é um ADX de Wilder escrito à mão, em laço, sem reaproveitar
o código da estratégia: o teste confere a regra (candle + ADX subindo/caindo +
filtro de amplitude), não só que o código roda.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from strategies import adx_direcao, registry

NAN = float("nan")


# ------------------------------------------------------------- construtores
def _barras(o, h, l, c) -> dict:
    n = len(o)
    return {
        "open": np.asarray(o, dtype=np.int64),
        "high": np.asarray(h, dtype=np.int64),
        "low": np.asarray(l, dtype=np.int64),
        "close": np.asarray(c, dtype=np.int64),
    }


def _serie(n=1500, semente=3, doji_a_cada=None) -> dict:
    """Passeio com candles de corpo e pavio variados, em ticks de 5 pontos."""
    rng = np.random.default_rng(semente)
    o = 100_000 + np.cumsum(rng.integers(-3, 4, n)) * 5
    c = o + rng.integers(-6, 7, n) * 5
    if doji_a_cada:
        c[::doji_a_cada] = o[::doji_a_cada]
    h = np.maximum(o, c) + rng.integers(0, 8, n) * 5
    l = np.minimum(o, c) - rng.integers(0, 8, n) * 5
    return _barras(o, h, l, c)


def _ref_adx(bars: dict, periodo: int, media: int) -> list[float]:
    """ADX de Wilder em laço puro: DI pelo período, DX suavizado por `media`."""
    h = [float(x) for x in bars["high"]]
    l = [float(x) for x in bars["low"]]
    c = [float(x) for x in bars["close"]]
    n = len(c)
    tr = [0.0] * n
    pdm = [0.0] * n
    ndm = [0.0] * n
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    s_tr, s_p, s_n = sum(tr[:periodo]), sum(pdm[:periodo]), sum(ndm[:periodo])
    dx = [NAN] * n
    for i in range(periodo - 1, n):
        if i > periodo - 1:
            s_tr = s_tr - s_tr / periodo + tr[i]
            s_p = s_p - s_p / periodo + pdm[i]
            s_n = s_n - s_n / periodo + ndm[i]
        p = 100.0 * s_p / s_tr if s_tr > 0 else 0.0
        q = 100.0 * s_n / s_tr if s_tr > 0 else 0.0
        dx[i] = 100.0 * abs(p - q) / (p + q) if (p + q) > 0 else 0.0

    adx = [NAN] * n
    semente = (periodo - 1) + media - 1
    if semente < n:
        adx[semente] = sum(dx[periodo - 1:semente + 1]) / media
        for i in range(semente + 1, n):
            adx[i] = (adx[i - 1] * (media - 1) + dx[i]) / media
    return adx


def _esperado(bars: dict, periodo: int, media: int, amplitude: int):
    adx = _ref_adx(bars, periodo, media)
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    n = len(c)
    compra = np.zeros(n, dtype=bool)
    venda = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if math.isnan(adx[i]) or math.isnan(adx[i - 1]):
            continue
        if amplitude and (h[i] - l[i]) > amplitude:
            continue
        if c[i] > o[i] and adx[i] > adx[i - 1]:
            compra[i] = True
        if c[i] < o[i] and adx[i] < adx[i - 1]:
            venda[i] = True
    return compra, venda


def _params(**kw) -> dict:
    base = dict(adx_periodo=14, adx_media=14, amplitude_max=0)
    base.update(kw)
    return base


# ------------------------------------------------------------ regra
@pytest.mark.parametrize("periodo,media,amplitude", [
    (14, 14, 0), (7, 3, 0), (10, 5, 60), (14, 14, 150),
])
def test_compra_e_venda_batem_com_a_regra(periodo, media, amplitude):
    bars = _serie()
    sinal = adx_direcao.signals(bars, _params(
        adx_periodo=periodo, adx_media=media, amplitude_max=amplitude))
    compra, venda = _esperado(bars, periodo, media, amplitude)
    assert np.array_equal(sinal.entry_long, compra)
    assert np.array_equal(sinal.entry_short, venda)
    assert compra.any() and venda.any()


def test_candle_de_alta_com_adx_caindo_nao_compra():
    bars = _serie()
    adx = _ref_adx(bars, 14, 14)
    o, c = bars["open"], bars["close"]
    alvo = [i for i in range(1, len(c))
            if not math.isnan(adx[i]) and not math.isnan(adx[i - 1])
            and c[i] > o[i] and adx[i] < adx[i - 1]]
    assert alvo, "a série precisa ter alta com ADX caindo"
    sinal = adx_direcao.signals(bars, _params())
    assert not sinal.entry_long[alvo].any()


def test_candle_de_baixa_com_adx_subindo_nao_vende():
    bars = _serie()
    adx = _ref_adx(bars, 14, 14)
    o, c = bars["open"], bars["close"]
    alvo = [i for i in range(1, len(c))
            if not math.isnan(adx[i]) and not math.isnan(adx[i - 1])
            and c[i] < o[i] and adx[i] > adx[i - 1]]
    assert alvo
    sinal = adx_direcao.signals(bars, _params())
    assert not sinal.entry_short[alvo].any()


def test_doji_nao_entra():
    bars = _serie(doji_a_cada=4)
    o, c = bars["open"], bars["close"]
    doji = np.where(c == o)[0]
    assert len(doji) > 0
    sinal = adx_direcao.signals(bars, _params())
    assert not sinal.entry_long[doji].any()
    assert not sinal.entry_short[doji].any()


# ------------------------------------------------------------ filtro
def test_filtro_de_amplitude_barra_candle_grande():
    bars = _serie()
    h, l = bars["high"], bars["low"]
    semfiltro = adx_direcao.signals(bars, _params(amplitude_max=0))
    comfiltro = adx_direcao.signals(bars, _params(amplitude_max=60))
    grandes = (h - l) > 60
    assert grandes.any()
    assert not comfiltro.entry_long[grandes].any()
    assert not comfiltro.entry_short[grandes].any()
    assert (comfiltro.entry_long <= semfiltro.entry_long).all()
    assert (comfiltro.entry_short <= semfiltro.entry_short).all()


def test_amplitude_zero_desliga_o_filtro():
    bars = _serie()
    desligado = adx_direcao.signals(bars, _params(amplitude_max=0))
    enorme = adx_direcao.signals(bars, _params(amplitude_max=10_000))
    assert np.array_equal(desligado.entry_long, enorme.entry_long)
    assert np.array_equal(desligado.entry_short, enorme.entry_short)


# ------------------------------------------------------------ períodos
def test_periodo_do_di_muda_o_adx():
    bars = _serie()
    a = adx_direcao.signals(bars, _params(adx_periodo=14))
    b = adx_direcao.signals(bars, _params(adx_periodo=7))
    assert not np.array_equal(a.entry_long, b.entry_long)


def test_suavizacao_do_adx_muda_o_adx():
    bars = _serie()
    a = adx_direcao.signals(bars, _params(adx_media=14))
    b = adx_direcao.signals(bars, _params(adx_media=3))
    assert not np.array_equal(a.entry_long, b.entry_long)


def test_suavizacao_separada_do_periodo():
    """Com a mesma suavização, o ADX de Wilder bate com a referência."""
    bars = _serie(n=600)
    adx = np.asarray(_ref_adx(bars, 10, 4))
    from core.engine.execution import adx as adx_di
    _, p, q = adx_di(bars, 10)
    dx = adx_direcao._dx(p, q)
    ours = adx_direcao._suaviza_wilder(dx, 4)
    assert np.allclose(ours, adx, equal_nan=True)


# ------------------------------------------------------------ aquecimento
def test_sem_aquecimento_nao_ha_sinal():
    bars = _serie()
    periodo, media = 14, 14
    primeiro = (periodo - 1) + media   # ADX existe a partir daqui, e precisa do anterior
    sinal = adx_direcao.signals(bars, _params())
    assert not sinal.entry_long[:primeiro].any()
    assert not sinal.entry_short[:primeiro].any()


def test_serie_curta_demais_nao_levanta_e_nao_sinaliza():
    bars = _serie(n=10)
    sinal = adx_direcao.signals(bars, _params(adx_periodo=14))
    assert not sinal.entry_long.any()
    assert not sinal.entry_short.any()


# ------------------------------------------------------------ saída e registro
def test_saida_padrao_e_nao_sair():
    schema = adx_direcao.params_schema
    assert schema["saida"]["default"] == 1
    assert schema["saida"]["min"] == 0 and schema["saida"]["max"] == 2
    sinal = adx_direcao.signals(_serie(), _params())
    assert not sinal.exit_long.any()
    assert not sinal.exit_short.any()
    assert sinal.virar is False


def test_parametros_do_schema():
    schema = adx_direcao.params_schema
    assert schema["adx_periodo"]["default"] == 14
    assert (schema["adx_periodo"]["min"], schema["adx_periodo"]["max"]) == (2, 100)
    assert schema["adx_media"]["default"] == 14
    assert (schema["adx_media"]["min"], schema["adx_media"]["max"]) == (1, 100)
    assert schema["amplitude_max"]["default"] == 1000
    assert (schema["amplitude_max"]["min"], schema["amplitude_max"]["max"]) == (0, 10000)
    assert schema["amplitude_max"]["step"] == 5


def test_estrategia_esta_registrada():
    achadas = {e["modulo"]: e for e in registry.descobrir()}
    assert "adx_direcao" in achadas
    assert achadas["adx_direcao"]["label"] == "ADX direção"
    assert registry.carregar("adx_direcao").name == "adx_direcao"
