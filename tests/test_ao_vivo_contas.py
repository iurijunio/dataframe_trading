# tests/test_ao_vivo_contas.py
"""Contas (demo/real, mesa) e o interruptor do portfólio."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import diario  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401


def test_criar_e_listar(banco):
    cid = AV.criar_conta("Demo XP", "demo", 500.0)
    [c] = AV.listar_contas()
    assert c["conta_id"] == cid and c["tipo"] == "demo"
    assert c["limite_perda_dia"] == 500.0
    assert diario.eventos(tipo="conta_criada", conta_id=cid)


@pytest.mark.parametrize("nome,tipo", [("", "demo"), ("X", "papel")])
def test_criar_invalido_recusa(banco, nome, tipo):
    with pytest.raises(ValueError):
        AV.criar_conta(nome, tipo)


def test_nome_unico_so_entre_nao_arquivadas(banco):
    a = AV.criar_conta("Mesa A", "real")
    with pytest.raises(ValueError, match="já existe"):
        AV.criar_conta("Mesa A", "real")
    AV.arquivar_conta(a)
    AV.criar_conta("Mesa A", "real")          # arquivada libera o nome
    assert len(AV.listar_contas(incluir_arquivadas=True)) == 2


def test_editar_registra_de_para_por_campo(banco):
    cid = AV.criar_conta("Mesa A", "real", 500.0)
    AV.editar_conta(cid, limite_perda_dia=400.0, nome="Mesa A1")
    ev = {e["motivo"]: e for e in diario.eventos(tipo="conta_editada")}
    assert (ev["limite_perda_dia"]["de"], ev["limite_perda_dia"]["para"]) == (
        "500.0", "400.0")
    assert ev["nome"]["para"] == "Mesa A1"
    AV.editar_conta(cid, limite_perda_dia=None)     # limite é opcional
    assert AV.listar_contas()[0]["limite_perda_dia"] is None


def test_nenhuma_funcao_apaga_conta():
    assert not [n for n in dir(AV) if "conta" in n and
                any(p in n for p in ("excluir", "apagar", "remover"))]


def test_ligar_e_desligar_portfolio_com_eventos(banco):
    pid = P.criar("p")
    AV.ligar_portfolio(pid)
    assert P.listar()[0]["ligado"] is True
    AV.ligar_portfolio(pid)                   # já ligado: não duplica evento
    AV.desligar_portfolio(pid)
    assert [e["tipo"] for e in diario.eventos(portfolio_id=pid)] == [
        "portfolio_ligado", "portfolio_desligado"]


def test_definir_contas_valida_tipo_e_arquivada(banco):
    pid = P.criar("p")
    demo, real = AV.criar_conta("D", "demo"), AV.criar_conta("R", "real")
    with pytest.raises(ValueError, match="demo"):
        AV.definir_contas(pid, real, None)
    AV.definir_contas(pid, demo, real)
    p = P.listar()[0]
    assert (p["conta_demo_id"], p["conta_real_id"]) == (demo, real)
    AV.arquivar_conta(demo)
    with pytest.raises(ValueError, match="arquivada"):
        AV.definir_contas(pid, demo, real)


def test_evento_falho_desfaz_a_mudanca(banco, monkeypatch):
    """Estado e evento na mesma transação: ou os dois, ou nenhum."""
    pid = P.criar("p")

    def quebra(*a, **k):
        raise RuntimeError("falhou no meio")
    monkeypatch.setattr(AV.diario, "registrar", quebra)
    with pytest.raises(RuntimeError):
        AV.ligar_portfolio(pid)
    assert P.listar()[0]["ligado"] is False
