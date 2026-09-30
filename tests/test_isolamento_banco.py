from core import db_manager as db


def test_db_path_nunca_e_o_banco_real(tmp_path):
    assert db.DB_PATH != db.DATA / "database.duckdb"
    assert tmp_path in db.DB_PATH.parents
