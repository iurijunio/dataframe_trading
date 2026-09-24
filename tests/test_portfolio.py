from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _mineracao_com_plano_ativo(run_id, variante_id, wfa_id,
                               symbol="WIN$N", strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, "2026-01-01", 10, "concluida", variante_id])
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])
    plano.salvar(
        wfa_id=wfa_id, run_id=run_id, symbol=symbol, strategy=strategy,
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})


def test_criar_e_listar(banco):
    pid = P.criar("meu portfólio")
    ps = P.listar()
    assert [p["portfolio_id"] for p in ps] == [pid]
    assert ps[0]["nome"] == "meu portfólio"
    assert ps[0]["n_membros"] == 0


def test_adicionar_e_remover_membro(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert [m["variante_id"] for m in ms] == [vid]
    assert P.listar()[0]["n_membros"] == 1

    P.remover_variante(pid, vid)
    assert P.membros(pid) == []
    assert P.listar()[0]["n_membros"] == 0


def test_membro_sem_plano_ativo_e_sinalizado(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is True
    assert ms[0]["wfa_id"] is None


def test_membro_com_plano_ativo_traz_o_wfa_id(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is False
    assert ms[0]["wfa_id"] == 10


def test_adicionar_a_mesma_variante_duas_vezes_nao_duplica(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)
    P.adicionar_variante(pid, vid)
    assert len(P.membros(pid)) == 1
