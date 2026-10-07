"""Testes da estratégia de rompimento com médias exponenciais."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies import rompimento_ema_abertura as R  # noqa: E402


def _barras(registros):
    ts, abertura, maxima, minima, fechamento = [], [], [], [], []
    for dia, barras in enumerate(registros):
        base = np.datetime64(f"2026-03-{4 + dia:02d}T09:00", "m")
        for i, (o, h, l, c) in enumerate(barras):
            ts.append(base + np.timedelta64(i, "m"))
            abertura.append(o)
            maxima.append(h)
            minima.append(l)
            fechamento.append(c)
    return {"ts": np.asarray(ts), "open": np.asarray(abertura),
            "high": np.asarray(maxima), "low": np.asarray(minima),
            "close": np.asarray(fechamento)}


def _params(**troca):
    p = {"ema_curta": 2, "ema_longa": 3, "distancia_abertura": 0}
    p.update(troca)
    return p


def test_compra_quando_todas_as_condicoes_ocorrem():
    barras = _barras([[(100, 101, 99, 100), (100, 101, 99, 100),
                       (100, 101, 99, 100), (100, 101, 99, 100),
                       (100, 101, 99, 100), (100, 111, 99, 110)]])
    s = R.signals(barras, _params())
    assert s.entry_long[-1] and not s.entry_short[-1]


def test_venda_e_o_espelho_da_compra():
    barras = _barras([[(100, 101, 99, 100), (100, 101, 99, 100),
                       (100, 101, 99, 100), (100, 101, 99, 100),
                       (100, 101, 99, 100), (100, 101, 89, 90)]])
    s = R.signals(barras, _params())
    assert s.entry_short[-1] and not s.entry_long[-1]


def test_abertura_do_dia_reinicia_no_proximo_pregao():
    dia1 = [(100, 101, 99, 100)] * 5 + [(100, 111, 99, 110)]
    dia2 = [(200, 201, 199, 200)] * 5 + [(200, 201, 189, 190)]
    s = R.signals(_barras([dia1, dia2]), _params())
    assert s.entry_long[5]
    assert s.entry_short[11]


def test_distancia_minima_da_abertura_e_usada():
    barras = _barras([[(100, 101, 99, 100)] * 5 + [(100, 106, 99, 105)]])
    s = R.signals(barras, _params(distancia_abertura=10))
    assert not s.entry_long[-1]


def test_nao_compra_se_faltar_condicao_de_reteste_da_media_curta():
    barras = _barras([[(100, 101, 100, 100)] * 5 + [(100, 111, 100, 110)]])
    s = R.signals(barras, _params())
    assert not s.entry_long[-1]


def test_nao_vende_se_faltar_condicao_de_reteste_da_media_curta():
    barras = _barras([[(100, 100, 99, 100)] * 5 + [(100, 100, 89, 90)]])
    s = R.signals(barras, _params())
    assert not s.entry_short[-1]


def test_parametros_sao_os_tres_gatilhos_mineraveis():
    assert set(R.params_schema) == {"ema_curta", "ema_longa", "distancia_abertura"}
    for meta in R.params_schema.values():
        assert {"label", "default", "min", "max", "step", "tipo"} <= set(meta)


def test_periodo_curto_precisa_ser_menor_que_o_longo():
    barras = _barras([[(100, 101, 99, 100)] * 6])
    try:
        R.signals(barras, _params(ema_curta=4, ema_longa=3))
    except ValueError as erro:
        assert "curta" in str(erro).lower()
    else:
        raise AssertionError("esperava validação da ordem dos períodos")


def test_estrategia_nao_define_saidas_stop_ou_alvo():
    barras = _barras([[(100, 101, 99, 100)] * 5 + [(100, 111, 99, 110)]])
    s = R.signals(barras, _params())
    assert s.sl_points == 0 and s.tp_points == 0
    assert not s.exit_long.any() and not s.exit_short.any()



def test_papel_recebe_aquecimento_suficiente_para_as_duas_emas():
    assert R.aquecimento_barras({"ema_curta": 9, "ema_longa": 21}) == 420
    assert R.aquecimento_barras({"ema_curta": 200, "ema_longa": 600}) == 12000


def test_distancia_exatamente_no_limite_gera_sinal():
    barras = _barras([[(100, 101, 99, 100)] * 5 + [(100, 111, 99, 110)]])
    s = R.signals(barras, _params(distancia_abertura=10))
    assert s.entry_long[-1]


def test_primeira_barra_do_dia_nao_usa_a_barra_anterior_de_ontem():
    ontem = [(100, 101, 99, 100)] * 5
    hoje = [(200, 211, 199, 210)]
    s = R.signals(_barras([ontem, hoje]), _params(distancia_abertura=10))
    assert not s.entry_long[len(ontem)]

