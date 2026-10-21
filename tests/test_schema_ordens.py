"""Schema da parte 4: colunas e tabelas das ordens, e a migração da fase."""
from datetime import datetime

from core import db_manager as db
from core import diario


def _con():
    con = db.connect_write()
    db.init_schema(con)
    return con


def test_colunas_novas_e_padroes():
    with _con() as con:
        con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em) "
                    "VALUES (1, 'demo', 'demo', ?)", [datetime(2026, 10, 9)])
        assert con.execute("SELECT envio_ligado FROM contas").fetchone()[0] is False
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'portfolio_membros'").fetchall()}
        assert {"contratos_demo", "contratos_real"} <= cols


def test_tabelas_novas_existem():
    with _con() as con:
        for t in ("ordens_eventos", "papel_backtest"):
            assert con.execute("SELECT count(*) FROM information_schema.tables "
                               "WHERE table_name = ?", [t]).fetchone()[0] == 1


def test_real_minimo_vira_real_e_e_idempotente():
    with _con() as con:
        con.execute("INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
                    "variante_id, adicionado_em, fase, fase_desde, ligada) "
                    "VALUES (1, 1, 1, ?, 'real_minimo', ?, true)",
                    [datetime(2026, 10, 1), datetime(2026, 10, 1)])
        db.init_schema(con)
        db.init_schema(con)
        assert con.execute("SELECT fase FROM portfolio_membros").fetchone()[0] == "real"


def test_tipos_novos_do_diario():
    assert {"contratos_alterados", "envio_ligado", "envio_desligado"} <= diario.TIPOS


def test_origem_migracao_idempotente_e_preenche_pelo_prefixo():
    with _con() as con:
        con.execute("INSERT INTO ordens_eventos (evento_id, quando, tipo) "
                    "VALUES ('demo-20261009-000001', ?, 'enviando')",
                    [datetime(2026, 10, 9, 10)])
        con.execute("INSERT INTO ordens_eventos (evento_id, quando, tipo) "
                    "VALUES ('real-20261009-000001', ?, 'enviando')",
                    [datetime(2026, 10, 9, 10)])
        db.init_schema(con)
        db.init_schema(con)
        linhas = con.execute("SELECT evento_id, origem FROM ordens_eventos "
                             "ORDER BY evento_id").fetchall()
    assert linhas == [("demo-20261009-000001", "demo"),
                      ("real-20261009-000001", "real")]
