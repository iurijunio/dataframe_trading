# tests/test_protecao.py
"""Nada que opera ou pode operar é apagado ou aposentado em silêncio."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario, plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = datetime(2026, 10, 1, 14, 0)


def _cadeia(run_id=1, wfa_id=1, com_variante=True, nome="v"):
    v = variantes.criar(nome, "rompimento_canal") if com_variante else None
    mineracao(run_id, variante_id=v)
    wfa(wfa_id, run_id)
    pid = plano.salvar(**campos_plano(wfa_id=wfa_id, run_id=run_id),
                       agora=datetime(2026, 9, 1, 10))
    return v, pid


def _membro(variante_id, removido=False):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (1, 'pf-teste', now()) ON CONFLICT DO NOTHING")
        con.execute(
            "INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
            "variante_id, adicionado_em, removido_em, fase, fase_desde, "
            "ligada) VALUES (nextval('seq_ligacao_id'), 1, ?, now(), ?, "
            "'papel', now(), false)",
            [variante_id, datetime(2026, 9, 5) if removido else None])


def _motivo(pids, hoje=date(2026, 10, 1)):
    with db.connect(read_only=True) as con:
        return plano.motivo_protecao(con, pids, hoje)


def test_ativo_e_protegido(banco):
    _, pid = _cadeia()
    assert "está ativo" in _motivo([pid])


def test_aposentado_ainda_em_vigor_e_protegido(banco):
    _, pid = _cadeia()
    plano.aposentar(pid, agora=QUI)          # sai de vigor na sexta
    assert "até" in _motivo([pid], hoje=date(2026, 10, 1))
    assert _motivo([pid], hoje=date(2026, 10, 2)) is None


def test_variante_em_portfolio_protege_mesmo_aposentado(banco):
    v, pid = _cadeia()
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    _membro(v)
    assert "pf-teste" in _motivo([pid])


def test_membro_removido_nao_protege(banco):
    v, pid = _cadeia()
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    _membro(v, removido=True)
    assert _motivo([pid]) is None


def test_lista_vazia_nao_protege(banco):
    assert _motivo([]) is None


def test_aposentar_vale_no_proximo_pregao_e_registra(banco):
    _, pid = _cadeia()
    assert plano.aposentar(pid, agora=QUI) is True
    d = plano.detalhes(pid)
    assert d["estado"] == "aposentado" and d["aposentado_em"] == date(2026, 10, 2)
    [e] = diario.eventos(tipo="plano_aposentado", plano_id=pid)
    assert e["origem"] == "usuario"


def test_aposentar_nao_estica_vigencia_ja_marcada(banco):
    """Aposentar o que já sai de vigor antes não pode prolongá-lo: min()."""
    _, pid = _cadeia()
    plano.aposentar(pid, agora=QUI)                       # sai na sexta
    plano.aposentar(pid, agora=datetime(2026, 10, 7, 10))  # seria quinta que vem
    assert plano.detalhes(pid)["aposentado_em"] == date(2026, 10, 2)


def test_aposentar_o_novo_antes_de_valer_nao_ressuscita_o_velho(banco):
    v, velho = _cadeia()
    novo = plano.salvar(**campos_plano(), agora=QUI)      # vale sexta
    plano.aposentar(novo, agora=QUI)                      # também sexta
    assert variantes.plano_em_vigor(v, date(2026, 10, 1))["plano_id"] == velho
    assert variantes.plano_em_vigor(v, date(2026, 10, 2)) is None


def test_excluir_plano_protegido_recusa_e_nao_apaga(banco):
    _, pid = _cadeia()
    with pytest.raises(ValueError, match="está ativo"):
        plano.excluir(pid)
    assert plano.detalhes(pid) is not None


def test_excluir_plano_livre_apaga(banco):
    _, pid = _cadeia(com_variante=False)
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    assert plano.excluir(pid) is True and plano.detalhes(pid) is None
