# tests/test_papel_dados.py
"""Tabelas do papel (spec Ao vivo › papel §5) e a proteção que dão à cadeia."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import db_manager as db, optimizer, plano, wfa_store  # noqa: E402
from core import portfolio as P, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401


def _op(con, ligacao_id, plano_id, entry="2026-10-01 10:00:00"):
    con.execute(
        "INSERT INTO papel_operacoes (op_id, ligacao_id, plano_id, dia, "
        "entry_ts, side, contratos, entry_px, aberta, conta, calculado_em) "
        "VALUES (nextval('seq_papel_op'), ?, ?, '2026-10-01', ?, 1, 1, "
        "130000, true, true, '2026-10-01 10:05:00')",
        [ligacao_id, plano_id, entry])


def _pregao(con, ligacao_id, plano_id, dia, status):
    con.execute(
        "INSERT INTO papel_pregoes (ligacao_id, dia, plano_id, status) "
        "VALUES (?,?,?,?)", [ligacao_id, dia, plano_id, status])


@pytest.fixture
def cadeia(banco):
    """Plano aposentado há tempo e sem portfólio: apagável, não fosse o papel."""
    mineracao(1)
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET estado = 'aposentado', "
                    "aposentado_em = '2026-09-10' WHERE plano_id = ?", [pid])
    return pid


def test_init_schema_duas_vezes_cria_tabelas_e_sequencia(banco):
    with db.connect() as con:
        db.init_schema(con)
        db.init_schema(con)
        tabelas = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        assert {"papel_operacoes", "papel_pregoes"} <= tabelas
        assert con.execute("SELECT nextval('seq_papel_op')").fetchone()[0] == 1


def test_unicidade_ligacao_entrada(banco):
    with db.connect_write() as con:
        _op(con, 5, 1)
        with pytest.raises(Exception):
            _op(con, 5, 1)
        _op(con, 5, 1, entry="2026-10-01 10:01:00")


def test_sem_papel_a_cadeia_apaga_como_antes(cadeia):
    assert plano.excluir(cadeia) is True


def test_papel_protege_plano(cadeia):
    with db.connect_write() as con:
        _op(con, 7, cadeia)
    with pytest.raises(ValueError, match="operações de papel"):
        plano.excluir(cadeia)
    assert plano.detalhes(cadeia) is not None


def test_papel_protege_wfa(cadeia):
    with db.connect_write() as con:
        _op(con, 7, cadeia)
    with pytest.raises(ValueError, match="operações de papel"):
        wfa_store.excluir(1)


def test_papel_protege_mineracao(cadeia):
    with db.connect_write() as con:
        _op(con, 7, cadeia)
    with pytest.raises(ValueError, match="operações de papel"):
        optimizer.excluir_salva(1)


def test_pregoes_com_plano_conta_papel(banco):
    v = variantes.criar("v", "rompimento_canal")
    mineracao(1, variante_id=v)
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    lig = P.adicionar_variante(P.criar("pf"), v)
    hoje = date(2026, 10, 1)
    assert AV.em_operacao(hoje)[0]["pregoes_com_plano"] == 0
    with db.connect_write() as con:
        _pregao(con, lig, pid, "2026-09-30", "conferido")
        _pregao(con, lig, pid, "2026-10-01", "rodando")
        _pregao(con, lig, pid, "2026-09-29", "pulado")
        _pregao(con, lig, pid, "2026-09-28", "interrompido")
        _pregao(con, lig + 1, pid, "2026-09-30", "conferido")   # outra ligação
        _pregao(con, lig, pid + 1, "2026-09-27", "conferido")   # outro plano
    assert AV.em_operacao(hoje)[0]["pregoes_com_plano"] == 2
