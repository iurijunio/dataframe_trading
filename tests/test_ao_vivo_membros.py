# tests/test_ao_vivo_membros.py
"""A ligação variante × portfólio: nunca apagada, com fase e interruptor."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import diario, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401


def _pv():
    return P.criar("p"), variantes.criar("v", "rompimento_canal")


def _linha(lig):
    with db.connect(read_only=True) as con:
        return con.execute(
            "SELECT fase, ligada, removido_em, desligada_por "
            "FROM portfolio_membros WHERE ligacao_id = ?", [lig]).fetchone()


def test_adicionar_entra_ligada_no_papel(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    assert _linha(lig) == ("papel", True, None, None)
    [m] = P.membros(pid)
    assert (m["ligacao_id"], m["fase"], m["ligada"]) == (lig, "papel", True)
    assert diario.eventos(tipo="membro_adicionado", ligacao_id=lig)


def test_adicionar_duas_vezes_nao_faz_nada(banco):
    pid, vid = _pv()
    a = P.adicionar_variante(pid, vid)
    assert P.adicionar_variante(pid, vid) == a
    assert len(diario.eventos(tipo="membro_adicionado")) == 1


def test_remover_com_portfolio_ligado_recusa(banco):
    pid, vid = _pv()
    P.adicionar_variante(pid, vid)
    AV.ligar_portfolio(pid)
    with pytest.raises(ValueError, match="desligue"):
        P.remover_variante(pid, vid)
    assert len(P.membros(pid)) == 1


def test_remover_com_portfolio_desligado_marca_e_gera_dois_eventos(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    P.remover_variante(pid, vid)
    assert P.membros(pid) == [] and P.listar()[0]["n_membros"] == 0
    assert _linha(lig)[2] is not None            # continua no banco
    assert [e["tipo"] for e in diario.eventos(ligacao_id=lig)] == [
        "membro_adicionado", "membro_desligado", "membro_removido"]


def test_readicionar_cria_ligacao_nova_no_papel(banco):
    pid, vid = _pv()
    a = P.adicionar_variante(pid, vid)
    P.remover_variante(pid, vid)
    b = P.adicionar_variante(pid, vid)
    assert b != a and _linha(b) == ("papel", True, None, None)


def test_desligar_e_ligar(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    AV.desligar_membro(lig)
    assert _linha(lig)[1:] == (False, None, "usuario")
    AV.desligar_membro(lig)                         # já desligada: nada
    AV.ligar_membro(lig)
    assert _linha(lig)[1] is True and _linha(lig)[3] is None
    assert [e["tipo"] for e in diario.eventos(ligacao_id=lig)] == [
        "membro_adicionado", "membro_desligado", "membro_ligado"]


def test_religar_depois_do_disjuntor_e_livre_e_registrado(banco):
    """Decisão do usuário (30/09/2026): religa a qualquer momento."""
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    AV.desligar_membro(lig, por="disjuntor")
    AV.ligar_membro(lig)
    [e] = diario.eventos(tipo="membro_ligado", ligacao_id=lig)
    assert e["motivo"] == "religada após disjuntor"


def test_ligacao_removida_nao_liga(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    P.remover_variante(pid, vid)
    with pytest.raises(ValueError, match="removida"):
        AV.ligar_membro(lig)


def test_por_invalido_recusa(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    with pytest.raises(ValueError):
        AV.desligar_membro(lig, por="robo")


def test_religar_registra_o_plano_em_vigor(banco):
    from datetime import datetime

    from core import plano
    from tests._cadeia import campos_plano, mineracao, wfa
    pid, vid = _pv()
    mineracao(1, vid)
    wfa(1, 1)
    plano_id = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    lig = P.adicionar_variante(pid, vid)
    AV.desligar_membro(lig)
    AV.ligar_membro(lig)
    [e] = diario.eventos(tipo="membro_ligado", ligacao_id=lig)
    assert e["plano_id"] == plano_id
