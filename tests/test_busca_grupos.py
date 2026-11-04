"""Grupos: campeões parecidos viram um só."""
import json

import pytest

from core.busca.espaco import Combinacao, Espaco
from core.busca.grupos import agrupar, parecidas


@pytest.fixture(scope="module")
def esp():
    return Espaco("adx_direcao", "WIN$N", fechamento="17:30")


def _c(esp, **kw):
    base = dict(timeframe="M5", ini="10:00", fim="11:30", dias=(2, 3, 4), direcao="compra",
                stop_tipo="atr", stop_valor=1.5, alvo_tipo="multiplicador", alvo_valor=2.0,
                params=(("adx_suavizacao", 14), ("amplitude_max", 1000),
                        ("di_periodo", 14), ("saida", 1)))
    params = dict(base["params"])
    params.update(kw.pop("p", {}))
    base["params"] = tuple(sorted(params.items()))
    return Combinacao(**{**base, **kw})


def _linha(esp, c, obj, valida=True, h=None):
    return {"combo": c.chave(), "casa": json.dumps(list(esp.casa(c))), "objetivo": obj,
            "valida": valida, "trades": 500, "lucro": obj, "pf": 1.2, "dd": 1.0, "fr": obj,
            "trades_hash": h or c.chave()}


def test_parecidas_regras(esp):
    a = _c(esp)
    assert parecidas(a, _c(esp, ini="10:30"), esp)                 # 1 degrau
    assert not parecidas(a, _c(esp, ini="11:00"), esp)             # 2 degraus
    assert parecidas(a, _c(esp, dias=(2, 3)), esp)                 # 1 dia a menos
    assert not parecidas(a, _c(esp, dias=(2,)), esp)               # 2 dias
    assert not parecidas(a, _c(esp, timeframe="M10"), esp)
    assert not parecidas(a, _c(esp, direcao="ambas"), esp)
    assert not parecidas(a, _c(esp, stop_tipo="pontos", stop_valor=300), esp)
    assert parecidas(a, _c(esp, stop_valor=2.0), esp)              # 2 degraus de 0,25
    assert not parecidas(a, _c(esp, stop_valor=2.25), esp)         # 3 degraus
    i = esp.params_vals["di_periodo"].index(14)
    dois, tres = esp.params_vals["di_periodo"][i + 2], esp.params_vals["di_periodo"][i + 3]
    assert parecidas(a, _c(esp, p={"di_periodo": dois}), esp)
    assert not parecidas(a, _c(esp, p={"di_periodo": tres}), esp)


def test_trinta_variacoes_do_mesmo_ponto_viram_um_grupo(esp):
    """O anti-objetivo do desenho: a lista não pode ser 30 cópias."""
    variacoes = [_c(esp, ini=i, fim=f, dias=d)
                 for i in ("09:30", "10:00", "10:30")
                 for f in ("11:00", "11:30", "12:00")
                 for d in ((2, 3, 4), (2, 3), (3, 4))]
    elites = [_linha(esp, c, 5.0 - n * 0.01) for n, c in enumerate(variacoes)]
    grupos = agrupar(elites, elites, esp)
    # o líder (10:00? não: o 1º, 09:30-11:00) junta quem está a 1 degrau dele
    assert len(grupos) < len(variacoes) / 3
    assert grupos[0]["lider"]["objetivo"] == 5.0


def test_tempos_graficos_diferentes_nao_se_juntam(esp):
    a, b = _c(esp), _c(esp, timeframe="M10")
    g = agrupar([_linha(esp, a, 3.0), _linha(esp, b, 2.0)],
                [_linha(esp, a, 3.0), _linha(esp, b, 2.0)], esp)
    assert len(g) == 2


def test_membros_contam_trades_iguais_uma_vez(esp):
    lider = _c(esp)
    copia1 = _c(esp, p={"amplitude_max": 1005})
    copia2 = _c(esp, p={"amplitude_max": 1010})
    outro = _c(esp, ini="10:30")
    combos = [_linha(esp, lider, 4.0), _linha(esp, copia1, 3.0, h="H"),
              _linha(esp, copia2, 3.5, h="H"), _linha(esp, outro, 2.0)]
    g = agrupar([combos[0]], combos, esp)[0]
    assert g["n_membros"] == 3
    assert [m["objetivo"] for m in g["membros"]] == [4.0, 3.5, 2.0]
    assert g["mediana_obj"] == 3.5


def test_invalida_nunca_e_membro_nem_lider(esp):
    a, b = _c(esp), _c(esp, ini="10:30")
    combos = [_linha(esp, a, 4.0), _linha(esp, b, -1e9 + 300, valida=False)]
    g = agrupar([combos[0], combos[1]], combos, esp)
    assert len(g) == 1 and g[0]["n_membros"] == 1


def test_elite_entra_no_grupo_do_lider_e_guarda_a_casa(esp):
    a, b = _c(esp), _c(esp, ini="10:30")
    la, lb = _linha(esp, a, 4.0), _linha(esp, b, 3.0)
    g = agrupar([lb, la], [la, lb], esp)
    assert len(g) == 1 and g[0]["lider_casa"] == la["casa"]
    assert set(g[0]["casas"]) == {la["casa"], lb["casa"]}
