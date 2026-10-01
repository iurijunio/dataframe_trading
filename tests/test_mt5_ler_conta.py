"""mt5_source.ler_conta com o MetaTrader5 falso."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core import mt5_source as M  # noqa: E402


def _falso(monkeypatch, *, init=True, info="padrao", trade_mode=0):
    chamadas = {"initialize": [], "shutdown": 0}
    if info == "padrao":
        info = SimpleNamespace(login=555, server="Clear-DEMO", name="Fulano",
                               company="Clear", trade_mode=trade_mode)

    def initialize(**kw):
        chamadas["initialize"].append(kw)
        return init

    def shutdown():
        chamadas["shutdown"] += 1

    fake = SimpleNamespace(initialize=initialize, shutdown=shutdown,
                           account_info=lambda: info,
                           last_error=lambda: (-1, "boom"))
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return chamadas


def test_demo(monkeypatch):
    _falso(monkeypatch, trade_mode=0)
    assert M.ler_conta() == {"login": 555, "servidor": "Clear-DEMO",
                             "tipo": "demo", "titular": "Fulano",
                             "corretora": "Clear"}


def test_real(monkeypatch):
    _falso(monkeypatch, trade_mode=2)
    assert M.ler_conta()["tipo"] == "real"


def test_contest_vira_demo(monkeypatch):
    _falso(monkeypatch, trade_mode=1)
    assert M.ler_conta()["tipo"] == "demo"


def test_initialize_falha(monkeypatch):
    c = _falso(monkeypatch, init=False)
    with pytest.raises(M.MT5Error, match="não foi possível conectar ao MT5"):
        M.ler_conta()
    assert c["shutdown"] == 1


def test_sem_login(monkeypatch):
    c = _falso(monkeypatch, info=None)
    with pytest.raises(M.MT5Error, match="não está logado em nenhuma conta"):
        M.ler_conta()
    assert c["shutdown"] == 1


def test_path_repassado(monkeypatch):
    c = _falso(monkeypatch)
    M.ler_conta("C:\\MT5\\terminal64.exe")
    assert c["initialize"] == [{"path": "C:\\MT5\\terminal64.exe"}]


def test_sem_path_nao_passa_nada(monkeypatch):
    c = _falso(monkeypatch)
    M.ler_conta()
    assert c["initialize"] == [{}]


def test_shutdown_no_caminho_feliz(monkeypatch):
    c = _falso(monkeypatch)
    M.ler_conta()
    assert c["shutdown"] == 1


def test_shutdown_mesmo_se_account_info_estoura(monkeypatch):
    c = _falso(monkeypatch)
    sys.modules["MetaTrader5"].account_info = lambda: 1 / 0
    with pytest.raises(ZeroDivisionError):
        M.ler_conta()
    assert c["shutdown"] == 1
