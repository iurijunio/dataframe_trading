# tests/test_ao_vivo_arrumacao.py
"""Arrumar a cadeia pela tela: vincular plano órfão e renomear variante.
Caso real: plano #3 (mineração #50, sem variante) × variante 7, que já
tem o plano #4 ativo."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import diario, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = datetime(2026, 10, 1, 14, 0)


def _orfa_e_destino():
    v = variantes.criar("v7", "rompimento_canal")
    mineracao(53, variante_id=v)
    wfa(24, 53)
    p4 = plano.salvar(**campos_plano(wfa_id=24, run_id=53),
                      agora=datetime(2026, 9, 28, 10))
    mineracao(50)                       # sem variante
    wfa(18, 50)
    p2 = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                      agora=datetime(2026, 9, 25, 10))
    p3 = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                      agora=datetime(2026, 9, 25, 11))
    return v, p2, p3, p4


def test_sem_escolha_com_dois_ativos_recusa(banco):
    v, p2, p3, p4 = _orfa_e_destino()
    with pytest.raises(ValueError, match="escolha"):
        AV.vincular_plano(50, v, agora=QUI)
    assert plano.detalhes(p3)["variante_id"] is None


def test_vincular_leva_mineracao_e_todos_os_planos(banco):
    v, p2, p3, p4 = _orfa_e_destino()
    AV.vincular_plano(50, v, manter_plano_id=p4, agora=QUI)
    assert all(plano.detalhes(p)["variante_id"] == v for p in (p2, p3))
    assert plano.detalhes(p3)["estado"] == "aposentado"
    assert plano.detalhes(p3)["aposentado_em"] == date(2026, 10, 2)
    assert plano.detalhes(p4)["estado"] == "ativo"
    assert len(diario.eventos(tipo="plano_vinculado")) == 2
    with pytest.raises(ValueError, match="já é da variante"):
        AV.vincular_plano(50, v, manter_plano_id=p4, agora=QUI)


def test_vincular_manter_o_orfao_aposenta_o_do_destino(banco):
    v, p2, p3, p4 = _orfa_e_destino()
    AV.vincular_plano(50, v, manter_plano_id=p3, agora=QUI)
    assert plano.detalhes(p4)["estado"] == "aposentado"
    assert plano.detalhes(p3)["estado"] == "ativo"


def test_vincular_estrategia_diferente_recusa(banco):
    v = variantes.criar("outra", "setup_cruzamento")
    mineracao(50)
    with pytest.raises(ValueError, match="estratégia"):
        AV.vincular_plano(50, v)


def test_renomear(banco):
    a = variantes.criar("a", "rompimento_canal")
    variantes.criar("b", "rompimento_canal")
    with pytest.raises(ValueError, match="já existe"):
        variantes.renomear(a, "b")
    variantes.renomear(a, "romp-abert-m15")
    assert {x["nome"] for x in variantes.listar()} == {"romp-abert-m15", "b"}
    [e] = diario.eventos(tipo="variante_renomeada", variante_id=a)
    assert (e["de"], e["para"]) == ("a", "romp-abert-m15")


def test_orfao_que_fica_so_passa_a_valer_quando_o_outro_sai(banco):
    # plano antigo tem vale_a_partir vazio ("desde sempre"): sem acerto ele
    # esconderia o plano em vigor hoje e contaria pregões desde a gravação
    v, p2, p3, p4 = _orfa_e_destino()
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET vale_a_partir = NULL "
                    "WHERE plano_id = ?", [p3])
    AV.vincular_plano(50, v, manter_plano_id=p3, agora=QUI)
    assert plano.detalhes(p3)["vale_a_partir"] == date(2026, 10, 2)
    lig = P.adicionar_variante(P.criar("pf"), v)
    [hoje] = [l for l in AV.em_operacao(date(2026, 10, 1))
              if l["ligacao_id"] == lig]
    assert hoje["plano"]["plano_id"] == p4
    assert hoje["plano_futuro"] == {"plano_id": p3,
                                    "vale_a_partir": date(2026, 10, 2)}
    [amanha] = [l for l in AV.em_operacao(date(2026, 10, 2))
                if l["ligacao_id"] == lig]
    assert amanha["plano"]["plano_id"] == p3
    assert amanha["pregoes_com_plano"] == 1
