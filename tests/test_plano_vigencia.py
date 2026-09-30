# tests/test_plano_vigencia.py
"""Gravar plano: o novo só vale no próximo pregão, o antigo vale até lá, e
reotimizar com mineração nova não deixa dois planos ativos na variante."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import diario, plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = datetime(2026, 10, 1, 14, 0)


@pytest.mark.parametrize("dia,esperado", [
    (date(2026, 9, 30), date(2026, 10, 1)),   # qua -> qui
    (date(2026, 10, 1), date(2026, 10, 2)),   # qui -> sex
    (date(2026, 10, 2), date(2026, 10, 5)),   # sex -> seg
    (date(2026, 10, 3), date(2026, 10, 5)),   # sáb -> seg
    (date(2026, 10, 4), date(2026, 10, 5)),   # dom -> seg
])
def test_proximo_dia_util(dia, esperado):
    assert plano.proximo_dia_util(dia) == esperado


def _var(nome="v"):
    return variantes.criar(nome, "rompimento_canal")


def test_grava_variante_vigencia_e_impressao(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(codigo_hash="abc"), agora=QUI)
    d = plano.detalhes(pid)
    assert d["variante_id"] == v
    assert d["vale_a_partir"] == date(2026, 10, 2)
    assert d["aposentado_em"] is None and d["codigo_hash"] == "abc"
    assert d["estado"] == "ativo"


def test_reotimizar_com_mineracao_nova_aposenta_o_da_variante(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    velho = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    mineracao(2, variante_id=v)
    wfa(2, 2)
    novo = plano.salvar(**campos_plano(wfa_id=2, run_id=2), agora=QUI)
    d = plano.detalhes(velho)
    assert d["estado"] == "aposentado"
    assert d["aposentado_em"] == date(2026, 10, 2)   # vale até o novo valer
    assert plano.detalhes(novo)["estado"] == "ativo"


def test_nao_toca_plano_de_outra_variante(banco):
    a, b = _var("a"), _var("b")
    mineracao(1, variante_id=a)
    wfa(1, 1)
    mineracao(2, variante_id=b)
    wfa(2, 2)
    pa = plano.salvar(**campos_plano(), agora=QUI)
    plano.salvar(**campos_plano(wfa_id=2, run_id=2), agora=QUI)
    assert plano.detalhes(pa)["estado"] == "ativo"


def test_sem_variante_mantem_a_regra_por_wfa(banco):
    wfa(1, 1)   # sem mineração com variante
    wfa(2, 2)
    p1 = plano.salvar(**campos_plano(), agora=QUI)
    p2 = plano.salvar(**campos_plano(wfa_id=2, run_id=2), agora=QUI)
    p3 = plano.salvar(**campos_plano(), agora=QUI)
    assert plano.detalhes(p1)["estado"] == "aposentado"
    assert plano.detalhes(p2)["estado"] == "ativo"
    assert plano.detalhes(p3)["estado"] == "ativo"


def test_eventos_de_gravar_e_aposentar(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    velho = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    novo = plano.salvar(**campos_plano(), agora=QUI)
    [g] = diario.eventos(tipo="plano_gravado", plano_id=novo)
    assert g["origem"] == "usuario" and g["variante_id"] == v
    [a] = diario.eventos(tipo="plano_aposentado", plano_id=velho)
    assert a["origem"] == "sistema"
    assert a["motivo"] == f"substituído pelo plano #{novo}"


def test_montar_leva_a_impressao_do_wfa(banco):
    # `banco` é obrigatório: montar lê o banco (retrato_da_base), e sem a
    # fixture leria data/database.duckdb
    campos = plano.montar(1, {"codigo_hash": "h1", "symbol": "WIN$N"}, {}, {},
                          {}, {}, {})
    assert campos["codigo_hash"] == "h1"


def test_evento_de_quem_ja_estava_aposentado_diz_de_aposentado(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    p1 = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    plano.salvar(**campos_plano(), agora=QUI)            # p1 sai em 02/10
    # regravar na quarta (vale 01/10): p1 ainda está em vigor, já aposentado
    plano.salvar(**campos_plano(), agora=datetime(2026, 9, 30, 10))
    des = [e["de"] for e in diario.eventos(tipo="plano_aposentado",
                                           plano_id=p1)]
    assert sorted(des) == ["aposentado", "ativo"]


def test_aposentar_duas_vezes_na_mesma_data_grava_um_evento(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    assert plano.aposentar(pid, agora=QUI) is True
    assert plano.aposentar(pid, agora=QUI) is True
    assert len(diario.eventos(tipo="plano_aposentado", plano_id=pid)) == 1
