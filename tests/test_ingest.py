"""Testes da camada de dados.

O que estes testes protegem, em uma frase: a base e um arquivo permanente de
historico que o MT5 nao devolve mais, entao importar duas vezes, importar
fora de ordem ou perder o .duckdb nao podem estragar nada.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import calendar as cal  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from core import rollovers as roll  # noqa: E402

SYMBOL = "TEST$N"
HEADER = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"


def write_export(path: Path, bars: list[tuple[datetime, int, int, int, int]]) -> Path:
    linhas = [HEADER]
    for ts, o, h, lo, c in bars:
        linhas.append(
            f"{ts:%Y.%m.%d}\t{ts:%H:%M:%S}\t{o}\t{h}\t{lo}\t{c}\t100\t500\t5"
        )
    path.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return path


def serie(inicio: datetime, n: int, base: int = 100000, passo: int = 0):
    """n barras de um minuto, comecando em `inicio`."""
    out = []
    for i in range(n):
        px = base + i * passo
        out.append((inicio + timedelta(minutes=i), px, px + 50, px - 50, px + 10))
    return out


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "t.duckdb")
    db.init_schema(c)
    yield c
    c.close()


# ------------------------------------------------------------------ leitura
def test_recusa_coluna_faltando(tmp_path):
    p = tmp_path / "ruim.csv"
    p.write_text("<DATE>\t<TIME>\t<OPEN>\n2026.01.02\t09:00:00\t100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="colunas ausentes"):
        ing.read_mt5_export(p)


def test_recusa_ohlc_incoerente(tmp_path):
    p = tmp_path / "ruim.csv"
    write_export(p, [(datetime(2026, 1, 2, 9, 0), 100, 90, 95, 98)])  # high < low
    with pytest.raises(ValueError, match="OHLC incoerente"):
        ing.read_mt5_export(p)


def test_recusa_timestamp_duplicado(tmp_path):
    p = tmp_path / "ruim.csv"
    ts = datetime(2026, 1, 2, 9, 0)
    write_export(p, [(ts, 100, 110, 90, 105), (ts, 100, 110, 90, 105)])
    with pytest.raises(ValueError, match="duplicados"):
        ing.read_mt5_export(p)


def test_recusa_preco_nao_inteiro(tmp_path):
    p = tmp_path / "ruim.csv"
    p.write_text(
        HEADER + "\n2026.01.02\t09:00:00\t100.5\t110\t90\t105\t1\t1\t5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="nao inteiros"):
        ing.read_mt5_export(p, price_decimals=0)


# ------------------------------------------------------------------- merge
def test_importar_duas_vezes_nao_muda_nada(con, tmp_path):
    p = write_export(tmp_path / "a.csv", serie(datetime(2026, 1, 2, 9, 0), 60, passo=5))

    r1 = ing.ingest_csv(con, p, SYMBOL)
    assert r1.rows_inserted == 60

    antes = con.execute("SELECT count(*), sum(close) FROM bars_m1").fetchone()
    r2 = ing.ingest_csv(con, p, SYMBOL)
    depois = con.execute("SELECT count(*), sum(close) FROM bars_m1").fetchone()

    assert (r2.rows_inserted, r2.rows_updated, r2.rows_identical) == (0, 0, 60)
    assert antes == depois


def test_exportacoes_sobrepostas_se_somam(con, tmp_path):
    a = write_export(tmp_path / "a.csv", serie(datetime(2026, 1, 2, 9, 0), 60))
    b = write_export(tmp_path / "b.csv", serie(datetime(2026, 1, 2, 9, 30), 60))

    ing.ingest_csv(con, a, SYMBOL)
    r = ing.ingest_csv(con, b, SYMBOL)

    # 30 minutos de sobreposicao, 30 minutos novos.
    assert r.rows_identical == 30
    assert r.rows_inserted == 30
    assert con.execute("SELECT count(*) FROM bars_m1").fetchone()[0] == 90


def test_exportacao_mais_recente_vence_conflito(con, tmp_path):
    inicio = datetime(2026, 1, 2, 9, 0)
    velha = write_export(tmp_path / "velha.csv", serie(inicio, 30, base=100000))
    # Mesmo periodo mais 30 minutos, com precos revisados.
    nova = write_export(tmp_path / "nova.csv", serie(inicio, 60, base=200000))

    ing.ingest_csv(con, velha, SYMBOL)
    r = ing.ingest_csv(con, nova, SYMBOL)

    assert r.rows_updated == 30       # divergencias em que a nova venceu
    assert r.rows_rejected == 0
    assert len(r.conflicts) == 5      # amostra registrada, nunca engolida
    primeiro = con.execute(
        "SELECT open FROM bars_m1 ORDER BY ts LIMIT 1"
    ).fetchone()[0]
    assert primeiro == 200000


def test_ordem_de_importacao_nao_importa(tmp_path):
    """A garantia central: 'mais recente vence' e resolvido pela data do
    arquivo, nao pela ordem em que voce lembrou de importar."""
    inicio = datetime(2026, 1, 2, 9, 0)
    velha = write_export(tmp_path / "velha.csv", serie(inicio, 30, base=100000))
    nova = write_export(tmp_path / "nova.csv", serie(inicio, 60, base=200000))

    def rodar(ordem, nome):
        c = db.connect(tmp_path / nome)
        db.init_schema(c)
        for p in ordem:
            ing.ingest_csv(c, p, SYMBOL)
        out = c.execute(
            "SELECT ts, open, high, low, close FROM bars_m1 ORDER BY ts"
        ).fetchall()
        c.close()
        return out

    assert rodar([velha, nova], "x.duckdb") == rodar([nova, velha], "y.duckdb")


def test_falha_no_meio_nao_deixa_rastro(con, tmp_path):
    p = write_export(tmp_path / "a.csv", serie(datetime(2026, 1, 2, 9, 0), 10))
    ing.ingest_csv(con, p, SYMBOL)
    n_log = con.execute("SELECT count(*) FROM ingest_log").fetchone()[0]

    # Forca uma falha depois do registro em ingest_log ter sido escrito.
    import polars as pl

    quebrado = pl.DataFrame({"ts": [1], "nao_existe": [1]})
    with pytest.raises(Exception):
        ing._merge(con, p, SYMBOL, quebrado)

    con.execute("ROLLBACK") if False else None
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == n_log


# -------------------------------------------------------------- derivadas
def test_trading_days_marca_sessao_parcial(con, tmp_path):
    bars = []
    for dia in (2, 5, 6, 7):  # 3 pregoes cheios
        bars += serie(datetime(2026, 1, dia, 9, 0), 100)
    bars += serie(datetime(2026, 1, 8, 13, 0), 20)  # e um curto
    ing.ingest_csv(con, write_export(tmp_path / "a.csv", bars), SYMBOL)

    n = cal.rebuild_trading_days(con, SYMBOL)
    assert n == 5
    parciais = con.execute(
        "SELECT date FROM trading_days WHERE is_partial ORDER BY date"
    ).fetchall()
    assert [r[0] for r in parciais] == [date(2026, 1, 8)]


def test_quarta_mais_proxima_do_dia_15():
    """Datas conferidas contra os gaps reais do historico do WIN."""
    esperado = {
        (2026, 2): date(2026, 2, 18),
        (2025, 12): date(2025, 12, 17),
        (2025, 10): date(2025, 10, 15),
        (2025, 8): date(2025, 8, 13),
        (2025, 6): date(2025, 6, 18),
        (2025, 4): date(2025, 4, 16),
        (2025, 2): date(2025, 2, 12),
        (2024, 12): date(2024, 12, 18),
    }
    for (ano, mes), d in esperado.items():
        assert roll.wednesday_nearest_15(ano, mes) == d
        assert d.weekday() == roll.WEDNESDAY


def test_apenas_meses_pares():
    dts = roll.expected_rollover_dates(date(2025, 1, 1), date(2025, 12, 31))
    assert [d.month for d in dts] == [2, 4, 6, 8, 10, 12]


# ----------------------------------------------------------------- parquet
def test_banco_e_descartavel(con, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    p = write_export(tmp_path / "a.csv", serie(datetime(2026, 1, 2, 9, 0), 200, passo=3))
    ing.ingest_csv(con, p, SYMBOL)

    antes = con.execute(
        "SELECT count(*), sum(open), sum(high), sum(low), sum(close) FROM bars_m1"
    ).fetchone()
    db.export_parquet(con, SYMBOL)
    db.rebuild_from_parquet(con, SYMBOL)
    depois = con.execute(
        "SELECT count(*), sum(open), sum(high), sum(low), sum(close) FROM bars_m1"
    ).fetchone()

    assert antes == depois
