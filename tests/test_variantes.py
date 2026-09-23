from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def test_criar_devolve_id_e_listar_encontra(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    achadas = variantes.listar("rompimento_canal")
    assert [v["variante_id"] for v in achadas] == [vid]
    assert achadas[0]["nome"] == "conservadora"


def test_listar_sem_filtro_devolve_todas_as_estrategias(banco):
    variantes.criar("conservadora", "rompimento_canal")
    variantes.criar("padrao", "reversao_rsi")
    achadas = variantes.listar()
    assert {v["nome"] for v in achadas} == {"conservadora", "padrao"}


def test_nome_duplicado_na_mesma_estrategia_e_recusado(banco):
    variantes.criar("conservadora", "rompimento_canal")
    with pytest.raises(ValueError, match="já existe"):
        variantes.criar("conservadora", "rompimento_canal")


def test_nome_duplicado_em_estrategias_diferentes_e_aceito(banco):
    a = variantes.criar("conservadora", "rompimento_canal")
    b = variantes.criar("conservadora", "reversao_rsi")
    assert a != b
