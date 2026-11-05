"""Conferência diária ordens × backtest (a irmã da papel × backtest).

As ORDENS do dia (`ordens_eventos`, por origem: real e demo à parte) têm de
ser as entradas do backtest do plano no histórico inteiro: mesmo minuto de
entrada, mesmo lado, e cada uma com saída. Os testes gravam os eventos à
mão a partir do próprio backtest e mexem neles para a diferença aparecer."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario, papel  # noqa: E402
from core import ordens_backtest as OB  # noqa: E402
from core import papel_backtest as PB  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import plano as _plano  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401
from tests.fabrica_ao_vivo import (barras_sinteticas, inserir_barras,  # noqa: E402
                                   ligacao_com_plano)
from tests.test_papel_backtest import (CONTRATOS, PARAMS, PERFIL, SIMB,  # noqa: E402
                                       _as, _conferir_papel, _marca_reconferencia)


@pytest.fixture(autouse=True)
def sem_recarga(monkeypatch):
    monkeypatch.setattr(papel.importlib, "reload", lambda mod: mod)


@pytest.fixture
def mundo(banco):
    b, dias = barras_sinteticas()
    with db.connect() as con:
        inserir_barras(con, b, symbol=SIMB)
    f = ligacao_com_plano("romp-ob", params=PARAMS, profile=PERFIL,
                          contratos=CONTRATOS, portfolio_id=P.criar("pf"))
    with db.connect_write() as con:
        # na real desde muito antes dos pregões do teste
        con.execute("UPDATE portfolio_membros SET fase = 'real', fase_desde = ? "
                    "WHERE ligacao_id = ?", [datetime(2025, 12, 1, 9), f.lig])
    dia = dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        bt = PB._backtest(con, _plano.detalhes(f.plano_id, con=con),
                          papel._modulo("rompimento_canal", None, {}), dia, SIMB)
    assert bt, "o dia escolhido precisa ter operação no backtest"
    return SimpleNamespace(lig=f.lig, pf=f.pf, plano_id=f.plano_id, dia=dia,
                           bt=bt, dias=dias)


_N = [0]


def _evento(con, lig, tipo, quando, *, entry_ts=None, lado=None, ticket=None,
            origem="real"):
    _N[0] += 1
    con.execute(
        "INSERT INTO ordens_eventos (evento_id, quando, tipo, ligacao_id, "
        "entry_ts, lado, ticket, origem) VALUES (?,?,?,?,?,?,?,?)",
        [f"{origem}-t-{_N[0]}", quando, tipo, lig, entry_ts, lado, ticket, origem])


def _operar(con, m, ops, origem="real", *, sem_saida=(), lado_trocado=()):
    """Os eventos de uma automação que fez exatamente `ops` (tuplas do
    `_backtest`): enviando, executada e a saída pelo ticket."""
    for i, (ent, lado, _px, sai, *_r) in enumerate(ops):
        ticket = 9000 + i
        if ent in lado_trocado:
            lado = -lado
        _evento(con, m.lig, "enviando", ent, entry_ts=ent, lado=lado, origem=origem)
        _evento(con, m.lig, "executada", ent + timedelta(seconds=1), entry_ts=ent,
                lado=lado, ticket=ticket, origem=origem)
        if ent not in sem_saida:
            _evento(con, m.lig, "saida_executada", sai + timedelta(seconds=1),
                    ticket=ticket, origem=origem)


def _gravado(con, lig, dia, origem="real"):
    r = con.execute("SELECT ok, n_ordens, n_backtest, diferencas FROM "
                    "ordens_backtest WHERE ligacao_id = ? AND dia = ? AND "
                    "origem = ?", [lig, dia, origem]).fetchone()
    if r is None:
        return None
    return {"ok": r[0], "n_ordens": r[1], "n_backtest": r[2],
            "diferencas": json.loads(r[3])["operacoes"]}


def _tipos(g):
    return [d["tipo"] for d in g["diferencas"]]


# ------------------------------------------------------------- conferir
def test_ordens_iguais_ao_backtest(mundo):
    with db.connect() as con:
        _operar(con, mundo, mundo.bt)
        r = OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    n = len(mundo.bt)
    assert r["ok"] is True and (r["n_ordens"], r["n_backtest"]) == (n, n)
    assert g == {"ok": True, "n_ordens": n, "n_backtest": n, "diferencas": []}


def test_entrada_a_mais_e_diferenca(mundo):
    extra = _as(mundo.dia, 17, 57)
    assert extra not in [o[0] for o in mundo.bt]
    with db.connect() as con:
        _operar(con, mundo, mundo.bt)
        _operar(con, mundo, [(extra, 1, 0, extra + timedelta(minutes=1))])
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    assert g["ok"] is False and _tipos(g) == ["a_mais"]
    assert g["diferencas"][0]["entry_ts"].startswith(f"{extra:%Y-%m-%d %H:%M}")


def test_entrada_a_menos_e_diferenca(mundo):
    with db.connect() as con:
        _operar(con, mundo, mundo.bt[1:])
        # tentou e perdeu a primeira: a tentativa conta, a entrada não
        ent = mundo.bt[0][0]
        _evento(con, mundo.lig, "enviando", ent, entry_ts=ent, lado=mundo.bt[0][1])
        _evento(con, mundo.lig, "perdida", ent + timedelta(seconds=40), entry_ts=ent)
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    assert g["ok"] is False and _tipos(g) == ["a_menos"]
    assert g["diferencas"][0]["situacao"] == "perdida"
    assert g["n_ordens"] == len(mundo.bt) - 1


def test_lado_trocado_e_diferenca(mundo):
    ent = mundo.bt[0][0]
    with db.connect() as con:
        _operar(con, mundo, mundo.bt, lado_trocado={ent})
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    assert g["ok"] is False and _tipos(g) == ["lado"]
    d = g["diferencas"][0]
    assert (d["ordem"], d["backtest"]) == (-mundo.bt[0][1], mundo.bt[0][1])


def test_entrada_sem_saida_e_diferenca(mundo):
    ent = mundo.bt[0][0]
    with db.connect() as con:
        _operar(con, mundo, mundo.bt, sem_saida={ent})
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    assert _tipos(g) == ["sem_saida"]


def test_origens_separadas(mundo):
    with db.connect() as con:
        _operar(con, mundo, mundo.bt, origem="real")
        _operar(con, mundo, mundo.bt[1:], origem="demo")
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        OB.conferir(con, mundo.lig, mundo.dia, "demo", {}, _as(mundo.dia, 23))
        assert _gravado(con, mundo.lig, mundo.dia, "real")["ok"] is True
        assert _tipos(_gravado(con, mundo.lig, mundo.dia, "demo")) == ["a_menos"]


def test_so_ensaio_nao_e_comparado(mundo):
    # Envio desligado: só "seria enviada" — a conta não operou
    ent = mundo.bt[0][0]
    with db.connect() as con:
        _evento(con, mundo.lig, "seria_enviada", ent, entry_ts=ent, lado=1)
        r = OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        assert r["ok"] is None and r["sem_ordens"] is True
        assert _gravado(con, mundo.lig, mundo.dia) is None


def test_dia_sem_nenhuma_entrada_e_diferenca(mundo):
    # a automação deixou de entrar: nenhum evento, ligação na real e ligada
    with db.connect() as con:
        r = OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    assert r["ok"] is False
    assert g["n_ordens"] == 0 and g["n_backtest"] == len(mundo.bt)
    assert _tipos(g) == ["a_menos"] * len(mundo.bt)


def test_dia_fora_da_fase_sem_ordens_fica_fora(mundo):
    d = mundo.dia
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET fase = 'papel' "
                    "WHERE ligacao_id = ?", [mundo.lig])
        _marca_reconferencia(con, d, _as(d + timedelta(days=1), 8, 56))
        assert OB.pendentes(con, SIMB) == []
        r = OB.conferir(con, mundo.lig, d, "real", {}, _as(d, 23))
        assert r["ok"] is None and r["fora_da_fase"] is True
        assert _gravado(con, mundo.lig, d) is None


def test_fase_de_depois_do_dia_nao_vale_para_tras(mundo):
    # sem `fase_mudou` no diário: a fase de hoje só vale desde `fase_desde`
    d = mundo.dia
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET fase_desde = ? "
                    "WHERE ligacao_id = ?", [_as(d + timedelta(days=3), 9), mundo.lig])
        _marca_reconferencia(con, d, _as(d + timedelta(days=1), 8, 56))
        assert OB.pendentes(con, SIMB) == []


def test_desligada_o_dia_todo_fica_fora(mundo):
    d = mundo.dia
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET ligada = false "
                    "WHERE ligacao_id = ?", [mundo.lig])
        _marca_reconferencia(con, d, _as(d + timedelta(days=1), 8, 56))
        assert OB.pendentes(con, SIMB) == []
        assert OB.conferir(con, mundo.lig, d, "real", {}, _as(d, 23))["fora_da_fase"]


def test_entrada_antes_de_entrar_na_fase_nao_conta(mundo):
    # promovida à real depois da 1ª entrada do backtest: ela não é "a menos"
    primeira, segunda = mundo.bt[0][0], (mundo.bt[1][0] if len(mundo.bt) > 1 else None)
    with db.connect() as con:
        diario.registrar(con, "fase_mudou", "usuario", ligacao_id=mundo.lig,
                         de="papel", para="real",
                         quando=primeira + timedelta(seconds=30))
        _operar(con, mundo, mundo.bt[1:])
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        g = _gravado(con, mundo.lig, mundo.dia)
    assert g["ok"] is True and g["n_backtest"] == len(mundo.bt) - 1, segunda


def test_fase_demo_nao_vale_para_a_real(mundo):
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET fase = 'demo' "
                    "WHERE ligacao_id = ?", [mundo.lig])
        _operar(con, mundo, mundo.bt, origem="real")
        _operar(con, mundo, mundo.bt, origem="demo")
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        OB.conferir(con, mundo.lig, mundo.dia, "demo", {}, _as(mundo.dia, 23))
        # na real a ligação não estava: tudo o que a real fez é "a mais"
        assert set(_tipos(_gravado(con, mundo.lig, mundo.dia, "real"))) == {"a_mais"}
        assert _gravado(con, mundo.lig, mundo.dia, "demo")["ok"] is True


def test_pendentes_so_depois_da_reconferencia_e_com_ordens(mundo):
    d = mundo.dia
    with db.connect() as con:
        _operar(con, mundo, mundo.bt, origem="real")
        assert OB.pendentes(con, SIMB) == []
        _marca_reconferencia(con, d, _as(d + timedelta(days=1), 8, 56))
        # a demo também: real ⊃ demo, e a conta demo não fez nada
        assert OB.pendentes(con, SIMB) == [(mundo.lig, d, "real"),
                                           (mundo.lig, d, "demo")]
        for origem in ("real", "demo"):
            OB.conferir(con, mundo.lig, d, origem, {},
                        _as(d + timedelta(days=1), 8, 57))
        assert OB.pendentes(con, SIMB) == []
        assert set(_tipos(_gravado(con, mundo.lig, d, "demo"))) == {"a_menos"}


def test_situacao_agrega(mundo):
    with db.connect() as con:
        assert OB.situacao(con, mundo.lig) == {"pregoes": 0, "diferencas": 0,
                                               "ok": None}
        _operar(con, mundo, mundo.bt, origem="real")
        _operar(con, mundo, mundo.bt[1:], origem="demo")
        OB.conferir(con, mundo.lig, mundo.dia, "real", {}, _as(mundo.dia, 23))
        OB.conferir(con, mundo.lig, mundo.dia, "demo", {}, _as(mundo.dia, 23))
        assert OB.situacao(con, mundo.lig) == {"pregoes": 1, "diferencas": 1,
                                               "ok": False}


# --------------------------------------------------------------- puro
def test_comparar_puro():
    t = datetime(2026, 11, 5, 9, 45)
    u = datetime(2026, 11, 5, 10, 15)
    bt = [(t, -1, 0, t + timedelta(minutes=5), 0, 1)]
    ordens = {u: {"lado": 1, "entrou": True, "fechada": True, "situacao": "executada"}}
    difs = OB.comparar(ordens, bt)
    assert [(d["tipo"], d["entry_ts"]) for d in difs] == [("a_menos", t), ("a_mais", u)]
    assert OB.comparar({t: {"lado": -1, "entrou": True, "fechada": True,
                            "situacao": "executada"}}, bt) == []
