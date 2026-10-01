"""Correção da base com hora deslocada (spec captura §0)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario  # noqa: E402
from core import ingest as ing  # noqa: E402
from core import reparo_base as R  # noqa: E402
from core import calendar as cal  # noqa: E402
from tests.test_ingest import serie, write_export  # noqa: E402


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "t.duckdb")
    db.init_schema(c)
    yield c
    c.close()


def _semear_cadeia(con):
    con.execute("INSERT INTO estrategia_variantes VALUES (1, 'x', 'v', NULL, now())")
    con.execute("INSERT INTO mining_runs (run_id, variante_id) VALUES (1, 1)")
    con.execute("INSERT INTO mining_trials (run_id, trial_id) VALUES (1, 1)")
    con.execute("INSERT INTO wfa_runs (wfa_id, run_id) VALUES (1, 1)")
    con.execute("INSERT INTO wfa_trades (wfa_id, n) VALUES (1, 1)")
    con.execute("INSERT INTO planos_operacao (plano_id, wfa_id, run_id) VALUES (1, 1, 1)")
    con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) VALUES (1, 'p', now())")
    con.execute("INSERT INTO portfolio_variantes VALUES (1, 1, now())")
    con.execute("INSERT INTO portfolio_membros (ligacao_id, portfolio_id, variante_id, "
                "adicionado_em, fase, fase_desde, ligada) VALUES (1, 1, 1, now(), 'papel', now(), true)")
    con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em) VALUES (1, 'c', 'demo', now())")
    diario.registrar(con, "conta_criada", "usuario", conta_id=1)


def test_apagar_derivados_esvazia_a_cadeia_e_poupa_contas_diario_e_barras(con, tmp_path):
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", serie(datetime(2026, 3, 9, 9, 0), 3)), "WIN$N")
    _semear_cadeia(con)

    apagadas = R.apagar_derivados(con)

    for t in R.TABELAS_DERIVADAS:
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
    assert apagadas["mining_runs"] == 1 and apagadas["portfolios"] == 1
    assert con.execute("SELECT count(*) FROM contas").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM ao_vivo_eventos").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM bars_m1").fetchone()[0] == 3


def test_apagar_lotes_so_apaga_as_barras_daqueles_lotes(con, tmp_path):
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", serie(datetime(2026, 3, 9, 9, 0), 3)), "WIN$N")
    ing.ingest_csv(con, write_export(tmp_path / "b.tsv", serie(datetime(2026, 3, 16, 6, 0), 4)), "WIN$N")

    assert R.apagar_lotes(con, "WIN$N", (2,)) == 4
    assert con.execute("SELECT count(*), min(src_ingest_id) FROM bars_m1").fetchone() == (3, 1)


def test_sessoes_suspeitas_acusa_pregao_das_06h_e_poupa_o_normal(con, tmp_path):
    bom = serie(datetime(2026, 3, 9, 9, 0), 2) + serie(datetime(2026, 3, 9, 18, 23), 2)
    torto = serie(datetime(2026, 3, 16, 6, 0), 2) + serie(datetime(2026, 3, 16, 15, 23), 2)
    # o formato real de 09–13/03 hoje: manhã do lote errado, tarde do CSV
    misto = serie(datetime(2026, 3, 10, 6, 0), 2) + serie(datetime(2026, 3, 10, 18, 23), 2)
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", bom + torto + misto), "WIN$N")
    cal.rebuild_trading_days(con, "WIN$N")

    suspeitas = R.sessoes_suspeitas(con, "WIN$N", date(2026, 3, 1))

    assert [s["dia"] for s in suspeitas] == [date(2026, 3, 10), date(2026, 3, 16)]
    assert suspeitas[1]["abre"] == "06:00" and suspeitas[1]["fecha"] == "15:24"


def test_diario_aceita_base_corrigida():
    assert "base_corrigida" in diario.TIPOS
