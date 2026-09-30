"""Ajudantes para montar mineração -> WFA -> plano direto no banco de teste.

Os testes da tela Ao vivo testam a CADEIA (quem protege quem, quem vale
quando), não o conteúdo de uma mineração ou de um WFA.
"""
from __future__ import annotations

import pytest

from core import db_manager as db


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def mineracao(run_id, variante_id=None, strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, "WIN$N", strategy, "2026-01-01", 10, "concluida",
             variante_id])


def wfa(wfa_id, run_id, strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
                    "VALUES (?,?,?,?)", [wfa_id, run_id, "WIN$N", strategy])


def campos_plano(**extra) -> dict:
    base = dict(
        wfa_id=1, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={"periodo_canal": 78}, profile={"contratos": 1},
        capital=100_000.0, contratos=1, risco_pedido_pct=1.0,
        risco_efetivo_pct=0.9, perda_referencia=300.0, de_onde="teste",
        margem=None, uso_margem_pct=50.0, camada4_travada=True,
        disjuntor={}, expectativa={}, reotimizacao={}, definicoes={},
        regua={})
    base.update(extra)
    return base
