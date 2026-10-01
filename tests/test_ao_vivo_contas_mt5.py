"""Conta com os dados de conexão do MT5 (número, servidor, pasta)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV, db_manager as db  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401


def test_criar_com_login_servidor_terminal_e_ler(banco):
    AV.criar_conta("Demo", "demo", login=123456, servidor=" Clear-DEMO ",
                   terminal="  C:\\MT5\\terminal64.exe ")
    [c] = AV.listar_contas()
    assert c["login"] == 123456
    assert c["servidor"] == "Clear-DEMO"
    assert c["terminal"] == "C:\\MT5\\terminal64.exe"


def test_sem_dados_do_mt5_continua_valendo(banco):
    AV.criar_conta("Velha", "demo", servidor="  ", terminal="")
    [c] = AV.listar_contas()
    assert c["login"] is None and c["servidor"] is None and c["terminal"] is None


def test_mesmo_login_no_mesmo_servidor_recusa(banco):
    AV.criar_conta("A", "demo", login=1, servidor="S")
    with pytest.raises(ValueError, match=r"a conta 1 em S já está cadastrada como 'A'"):
        AV.criar_conta("B", "demo", login=1, servidor="S")
    assert len(AV.listar_contas()) == 1


def test_mesmo_login_em_servidor_diferente_aceita(banco):
    AV.criar_conta("A", "demo", login=1, servidor="S1")
    AV.criar_conta("B", "real", login=1, servidor="S2")
    assert len(AV.listar_contas()) == 2


def test_arquivar_libera_o_par(banco):
    cid = AV.criar_conta("A", "demo", login=1, servidor="S")
    AV.arquivar_conta(cid)
    AV.criar_conta("B", "demo", login=1, servidor="S")
    assert [c["nome"] for c in AV.listar_contas()] == ["B"]


@pytest.mark.parametrize("ruim", [0, -5, "abc", 1.5, True])
def test_login_invalido_recusa(banco, ruim):
    with pytest.raises(ValueError, match="número da conta"):
        AV.criar_conta("A", "demo", login=ruim, servidor="S")
    assert AV.listar_contas() == []


def test_editar_login_gera_evento_com_de_para(banco):
    cid = AV.criar_conta("A", "demo", login=1, servidor="S")
    AV.editar_conta(cid, login=2)
    with db.connect(read_only=True) as con:
        ev = con.execute("SELECT de, para FROM ao_vivo_eventos WHERE tipo = "
                         "'conta_editada' AND motivo = 'login'").fetchall()
    assert ev == [("1", "2")]
    assert AV.listar_contas()[0]["login"] == 2


def test_editar_para_par_ocupado_recusa(banco):
    AV.criar_conta("A", "demo", login=1, servidor="S")
    cid = AV.criar_conta("B", "demo", login=2, servidor="S")
    with pytest.raises(ValueError, match="já está cadastrada como 'A'"):
        AV.editar_conta(cid, login=1)
    assert [c["login"] for c in AV.listar_contas()] == [1, 2]


def test_editar_servidor_e_terminal(banco):
    cid = AV.criar_conta("A", "demo", login=1, servidor="S")
    AV.editar_conta(cid, servidor=" S2 ", terminal="C:\\x.exe")
    [c] = AV.listar_contas()
    assert c["servidor"] == "S2" and c["terminal"] == "C:\\x.exe"
    AV.editar_conta(cid, terminal="")
    assert AV.listar_contas()[0]["terminal"] is None


def test_editar_sem_mexer_no_resto_nao_gera_evento(banco):
    cid = AV.criar_conta("A", "demo", login=1, servidor="S")
    AV.editar_conta(cid, nome="A2")
    with db.connect(read_only=True) as con:
        n = con.execute("SELECT count(*) FROM ao_vivo_eventos WHERE tipo = "
                        "'conta_editada'").fetchone()[0]
    assert n == 1
