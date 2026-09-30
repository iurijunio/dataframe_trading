"""Isolamento global: nenhum teste pode alcancar o data/database.duckdb real.

Por que autouse: basta um teste esquecer a fixture `banco` (ou importar
`ui.app.build`, que roda init_schema e saneamento) para gravar no banco do
usuario, onde moram contas, ligacoes e o diario. Aqui so o DB_PATH e desviado;
PARQUET_DIR fica como esta porque testes leem barras reais do espelho.
"""
import pytest

from core import db_manager as db


@pytest.fixture(autouse=True)
def _banco_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "isolado.duckdb")
