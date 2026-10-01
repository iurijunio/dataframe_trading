"""O espelho Parquet nunca fica pela metade nem com ano órfão: a mineração
lê dele enquanto a captura reexporta depois da conferência do dia."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from tests.test_ingest import serie, write_export  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    con = db.connect(tmp_path / "t.duckdb"); db.init_schema(con)
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv",
                   serie(datetime(2025, 12, 31, 9, 0), 2) + serie(datetime(2026, 1, 2, 9, 0), 3)), "WIN$N")
    yield con, tmp_path
    con.close()


def test_export_nao_deixa_ano_orfao_nem_pasta_de_sobra(base):
    con, tmp = base
    db.export_parquet(con, "WIN$N")
    con.execute("DELETE FROM bars_m1 WHERE year(ts) = 2025")

    out = db.export_parquet(con, "WIN$N")

    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 3
    assert sorted(p.name for p in (tmp / "parquet").iterdir()) == [out.name]


def test_falha_na_troca_devolve_a_copia_antiga(base, monkeypatch):
    con, tmp = base
    db.export_parquet(con, "WIN$N")
    con.execute("DELETE FROM bars_m1 WHERE year(ts) = 2025")
    real = Path.rename

    def rename_que_falha(self, alvo):
        if self.name.endswith(".novo"):
            raise PermissionError("pasta em uso")
        return real(self, alvo)

    monkeypatch.setattr(Path, "rename", rename_que_falha)
    with pytest.raises(PermissionError):
        db.export_parquet(con, "WIN$N")
    monkeypatch.setattr(Path, "rename", real)

    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 5   # a cópia antiga voltou
