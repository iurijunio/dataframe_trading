"""Projeções do mapa e da lista."""
import json

import pytest

from core import db_manager as db
from core.busca import banco as B
from core.busca import projecao as P
from core.busca.espaco import Combinacao, Espaco


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


def test_rotulo_dias():
    assert P.rotulo_dias((2,)) == "ter"
    assert P.rotulo_dias((2, 3, 4)) == "ter–qui"
    assert P.rotulo_dias((2, 3, 4), curto=False) == "ter a qui"
    assert P.rotulo_dias((1, 3, 5), curto=False) == "seg, qua e sex"
    assert P.rotulo_dias((2, 4), curto=False) == "ter e qui"
    assert P.rotulo_dias((1, 2, 3, 4, 5)) == "seg–sex"


def test_cor_continua_e_pontas():
    assert P.cor("fr", -3) == "#B8345F" and P.cor("fr", 99) == "#8AF3FF"
    assert P.cor("fr", float("inf")) == "#8AF3FF"
    assert P.cor("fr", 1.5) == "#262A30"
    meio = P.cor("fr", 2.25)
    assert meio not in ("#262A30", "#0C5F6E") and meio.startswith("#")
    assert P.cor("fr", None) is None


# ----------------------------------------------------- com um banco montado
def _esp():
    return Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                  faixas={"timeframe": {"ligados": ["M5", "M15"]}})


def _comb(esp, tf, ini, fim, dias=(2, 3), direcao="compra"):
    x = esp.decodificar([0.0] * esp.n_genes)
    return Combinacao(**{**x.__dict__, "timeframe": tf, "ini": ini, "fim": fim,
                         "dias": dias, "direcao": direcao})


@pytest.fixture
def busca():
    esp = _esp()
    bid = B.criar({"simbolo": "WIN$N", "estrategia": "adx_direcao",
                   "espaco": esp.para_json(), "criterio": "fr"})
    elites = []
    for c, obj, valida, trades in [
            (_comb(esp, "M5", "10:00", "11:00"), 3.5, True, 500),
            (_comb(esp, "M5", "10:00", "12:00"), 2.0, True, 900),      # mesma projeção
            (_comb(esp, "M5", "11:00", "12:00", direcao="venda"), -1e9 + 120, False, 120),
            (_comb(esp, "M15", "09:30", "10:30", dias=(1, 2, 3, 4, 5)), float(1e6), True, 450)]:
        elites.append({"casa": json.dumps(list(esp.casa(c))), "combo": c.chave(),
                       "objetivo": obj, "valida": valida, "trades": trades,
                       "lucro": 1.0, "pf": 1.3, "dd": 1.0,
                       "fr": None if obj == 1e6 else obj, "achado_em": 1})
    B.gravar_lote(bid, 1, [], elites,
                  [{"casa": elites[0]["casa"], "teste_n": 10, "objetivo": 1.0},
                   {"casa": elites[0]["casa"], "teste_n": 50, "objetivo": 3.5}],
                  {"distintos": 100})
    B.gravar_grupos(bid, 1, [{"grupo_id": 1, "lider_casa": elites[0]["casa"],
                              "lider": elites[0], "casas": [elites[0]["casa"], elites[1]["casa"]],
                              "membros": [], "mediana_obj": 2.8, "n_membros": 17}])
    return bid, esp


def test_mapa_projecao_pela_melhor(busca):
    bid, esp = busca
    m = P.mapa(bid, "horario", "fr")
    assert m["linhas"] == ["M5", "M15"] and m["colunas"] == list(esp.inicios)
    nc = len(m["colunas"])
    casa = m["casas"][0 * nc + m["colunas"].index("10:00")]
    assert casa["estado"] == "ok" and casa["valor"] == 3.5
    assert casa["membros"] == 17 and casa["mediana"] == 2.8
    assert ("Horário", "10:00 a 11:00") not in casa["dims"]       # o eixo já diz
    assert ("Direção", "compra") in casa["dims"]


def test_poucos_e_vazia(busca):
    bid, _ = busca
    m = P.mapa(bid, "horario", "fr")
    nc = len(m["colunas"])
    poucos = m["casas"][0 * nc + m["colunas"].index("11:00")]
    assert poucos["estado"] == "poucos" and poucos["trades"] == 120
    assert m["casas"][0 * nc + m["colunas"].index("13:00")]["estado"] == "vazia"


def test_infinito_vai_para_a_ponta_e_e_o_melhor(busca):
    bid, _ = busca
    m = P.mapa(bid, "horario", "fr")
    assert m["melhor"]["valor"] == float("inf") and m["melhor"]["cor"] == "#8AF3FF"
    assert m["n_com_resultado"] == 2 and m["bons"] == 2


def test_trocar_o_eixo_so_muda_a_projecao(busca):
    bid, _ = busca
    d = P.mapa(bid, "dias", "trades")
    assert len(d["colunas"]) == 31 and d["colunas"][:5] == ["seg", "ter", "qua", "qui", "sex"]
    casa = [c for c in d["casas"] if c["estado"] == "ok" and c["linha"] == 0][0]
    assert casa["valor"] == 500 and d["colunas"][casa["coluna"]] == "ter, qua"
    r = P.mapa(bid, "direcao", "pf")
    assert r["colunas"] == ["compra", "venda", "as duas"]
    assert r["casas"][1]["estado"] == "poucos"


def test_lista_e_evolucao(busca):
    bid, _ = busca
    lst = P.lista(bid, "horario", "fr")
    assert [x["tf"] for x in lst] == ["M15", "M5"]
    assert lst[1]["evolucao"][-1] == 3.5 and lst[1]["evolucao"][0] == 1.0
    assert len(lst[1]["evolucao"]) <= 10


@pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")
def test_com_uma_busca_real():
    from tests import _busca_pequena

    bid = _busca_pequena.rodar(3)
    m = P.mapa(bid, "horario", "fr")
    assert m["n_com_resultado"] > 0
    assert sum(c["estado"] != "vazia" for c in m["casas"]) >= m["n_com_resultado"]
