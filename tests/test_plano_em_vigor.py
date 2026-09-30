"""Qual plano vale NAQUELE pregão — que pode não ser o último gravado."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI, SEX, SEG = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)


def _variante_com_dois_planos():
    v = variantes.criar("v", "rompimento_canal")
    mineracao(1, variante_id=v)
    wfa(1, 1)
    p1 = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    p2 = plano.salvar(**campos_plano(), agora=datetime(2026, 10, 1, 14))
    return v, p1, p2


def _vigor(v, dia):
    r = variantes.plano_em_vigor(v, dia)
    return r and r["plano_id"]


def test_antes_de_valer_devolve_o_anterior(banco):
    v, p1, p2 = _variante_com_dois_planos()
    assert _vigor(v, QUI) == p1


def test_no_dia_devolve_o_novo(banco):
    v, p1, p2 = _variante_com_dois_planos()
    assert _vigor(v, SEX) == p2 and _vigor(v, SEG) == p2


def test_dois_no_mesmo_dia_o_do_meio_nunca_vale(banco):
    v, p1, p2 = _variante_com_dois_planos()
    p3 = plano.salvar(**campos_plano(), agora=datetime(2026, 10, 1, 16))
    assert _vigor(v, QUI) == p1
    assert _vigor(v, SEX) == p3


def test_sem_plano_devolve_none(banco):
    v = variantes.criar("v", "rompimento_canal")
    assert variantes.plano_em_vigor(v, QUI) is None


def test_plano_antigo_sem_datas_e_o_desempate_por_id(banco):
    """Planos anteriores a esta versão: vigência nula = vale desde sempre;
    dois ativos (caso antigo) desempatam pelo maior id."""
    v = variantes.criar("v", "rompimento_canal")
    with db.connect_write() as con:
        con.execute("INSERT INTO planos_operacao (plano_id, estado, "
                    "variante_id) VALUES (1,'ativo',?), (2,'ativo',?), "
                    "(3,'aposentado',?)", [v, v, v])
    assert _vigor(v, QUI) == 2


def test_aceita_conexao_do_chamador(banco):
    v, p1, p2 = _variante_com_dois_planos()
    with db.connect_write() as con, db.transacao(con):
        assert variantes.plano_em_vigor(v, SEX, con=con)["plano_id"] == p2


def test_no_dia_da_aposentadoria_ja_nao_vale(banco):
    """Sozinho, sem plano mais novo para mascarar: no próprio dia de
    aposentado_em o plano já não vale."""
    v = variantes.criar("v", "rompimento_canal")
    with db.connect_write() as con:
        con.execute("INSERT INTO planos_operacao (plano_id, estado, "
                    "variante_id, vale_a_partir, aposentado_em) "
                    "VALUES (1, 'aposentado', ?, ?, ?)", [v, date(2026, 9, 1), SEX])
    assert _vigor(v, QUI) == 1
    assert variantes.plano_em_vigor(v, SEX) is None
