"""Schema da tela Ao vivo e a migração dos portfólios que já existem."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from tests._cadeia import banco, mineracao, wfa  # noqa: E402,F401


def _q(sql, args=()):
    with db.connect(read_only=True) as con:
        return con.execute(sql, list(args)).fetchall()


def _reiniciar():
    with db.connect() as con:
        db.init_schema(con)


def _pv(portfolio_id, variante_id):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (?,?,?) ON CONFLICT DO NOTHING",
                    [portfolio_id, f"p{portfolio_id}", datetime(2026, 9, 1)])
        con.execute("INSERT INTO portfolio_variantes VALUES (?,?,?)",
                    [portfolio_id, variante_id, datetime(2026, 9, 2)])


def test_tabelas_e_colunas_novas_existem(banco):
    for t in ("contas", "portfolio_membros", "ao_vivo_eventos"):
        assert _q(f"SELECT count(*) FROM {t}") == [(0,)]
    cols = {r[0] for r in _q(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'planos_operacao'")}
    assert {"variante_id", "vale_a_partir", "aposentado_em",
            "codigo_hash"} <= cols
    assert "codigo_hash" in {r[0] for r in _q(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'wfa_runs'")}


def test_portfolio_novo_nasce_desligado(banco):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (1, 'x', now())")
    assert _q("SELECT ligado FROM portfolios") == [(False,)]


def test_migracao_vira_membro_no_papel_ligado(banco):
    _pv(1, 7)
    _reiniciar()
    r = _q("SELECT portfolio_id, variante_id, fase, ligada, fase_desde, "
           "removido_em FROM portfolio_membros")
    assert r == [(1, 7, "papel", True, datetime(2026, 9, 2), None)]


def test_migracao_rodar_duas_vezes_nao_duplica(banco):
    _pv(1, 7)
    _reiniciar()
    _reiniciar()
    assert _q("SELECT count(*) FROM portfolio_membros") == [(1,)]


def test_remover_e_reiniciar_nao_ressuscita(banco):
    """Sem contar os removidos, a variante tirada do portfólio voltaria a
    cada subida do app — portfolio_variantes nunca é apagada."""
    _pv(1, 7)
    _reiniciar()
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET removido_em = now()")
    _reiniciar()
    assert _q("SELECT count(*) FROM portfolio_membros") == [(1,)]


def test_migracao_preenche_variante_do_plano_pela_mineracao(banco):
    mineracao(5, variante_id=3)
    wfa(9, 5)
    with db.connect_write() as con:
        con.execute("INSERT INTO planos_operacao (plano_id, wfa_id, run_id, "
                    "estado) VALUES (1, 9, 5, 'ativo')")
    _reiniciar()
    assert _q("SELECT variante_id FROM planos_operacao") == [(3,)]
