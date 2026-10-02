"""Testes da camada de dados.

O que estes testes protegem, em uma frase: a base e um arquivo permanente de
historico que o MT5 nao devolve mais, entao importar duas vezes, importar
fora de ordem ou perder o .duckdb nao podem estragar nada.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
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


def test_falha_no_meio_nao_deixa_rastro(con, monkeypatch):
    ts = datetime(2026, 3, 9, 9, 0)
    ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)]), SYMBOL, "a", "sa")
    lotes, barras = (con.execute("SELECT count(*) FROM ingest_log").fetchone()[0],
                     _barras(con))

    def boom(*a, **k):
        raise RuntimeError("falha proposital depois do INSERT no ingest_log")

    monkeypatch.setattr(ing.json, "dumps", boom)  # roda só quando há divergência
    with pytest.raises(RuntimeError, match="proposital"):
        ing.ingest_df(con, _df([(ts, 100, 120, 90, 105)]), SYMBOL, "b", "sb",
                      source_max_ts=datetime(2026, 3, 10))

    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == lotes
    assert _barras(con) == barras


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


# ------------------------------------------------------------- ingest_df
def _df(linhas):
    return pl.DataFrame(
        [(ts, o, h, lo, c, 100, 500, 5) for ts, o, h, lo, c in linhas],
        schema=["ts", "open", "high", "low", "close", "tick_volume", "volume", "spread"],
        orient="row")


def _barras(con):
    return con.execute("SELECT ts, open, high, low, close, tick_volume, volume, "
                       "spread FROM bars_m1 ORDER BY ts").fetchall()


def test_ingest_df_da_o_mesmo_que_ingest_csv(tmp_path):
    linhas = serie(datetime(2026, 3, 9, 9, 0), 5, passo=10)
    a = db.connect(tmp_path / "a.duckdb"); db.init_schema(a)
    b = db.connect(tmp_path / "b.duckdb"); db.init_schema(b)
    ing.ingest_csv(a, write_export(tmp_path / "x.tsv", linhas), "WIN$N")
    ing.ingest_df(b, _df(linhas), "WIN$N", "captura://1@srv", "sha-x")
    assert _barras(a) == _barras(b)
    a.close(); b.close()


def test_ingest_df_aceita_preco_float_inteiro_do_mt5(con):
    df = _df(serie(datetime(2026, 3, 9, 9, 0), 2)).with_columns(
        [pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close")])
    r = ing.ingest_df(con, df, "WIN$N", "captura://1@srv", "sha")
    assert r.rows_inserted == 2


def test_ingest_df_recusa_ohlc_incoerente_e_duplicata(con):
    ts = datetime(2026, 3, 9, 9, 0)
    with pytest.raises(ValueError, match="incoerente"):
        ing.ingest_df(con, _df([(ts, 100, 90, 95, 100)]), "WIN$N", "o", "s")
    with pytest.raises(ValueError, match="duplicados"):
        ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)] * 2), "WIN$N", "o", "s")
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 0


def test_source_max_ts_informado_vence_versao_do_mesmo_minuto(con):
    """A conferência do dia relê o mesmo minuto que a captura gravou: o
    `source_max_ts` dela (hora em que rodou) é o que a faz vencer."""
    ts = datetime(2026, 3, 9, 9, 0)
    ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)]), "WIN$N", "captura://", "b")
    r = ing.ingest_df(con, _df([(ts, 100, 120, 90, 105)]), "WIN$N",
                      "conferencia://2026-03-09", "a",
                      source_max_ts=datetime(2026, 3, 9, 18, 30))
    assert r.rows_updated == 1
    assert con.execute("SELECT high, close FROM bars_m1").fetchone() == (120, 105)
    assert con.execute("SELECT max(source_max_ts) FROM ingest_log").fetchone()[0] == datetime(2026, 3, 9, 18, 30)


# ------------------------------------------------------ tick_volume ignorado
def _com(df, **cols):
    return df.with_columns([pl.lit(v).alias(c) for c, v in cols.items()])


def test_diferenca_so_no_tick_volume_e_barra_identica(con):
    """tick_volume é contagem de atualizações de cotação, não de negócios, e
    a corretora o revisa de madrugada: barra que só difere nele não é
    correção — fica a gravada, com a proveniência dela."""
    ts = datetime(2026, 3, 9, 9, 0)
    ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)]), "WIN$N", "captura://", "a")
    dono = con.execute("SELECT src_ingest_id FROM bars_m1").fetchone()[0]
    r = ing.ingest_df(con, _com(_df([(ts, 100, 110, 90, 100)]), tick_volume=999),
                      "WIN$N", "conferencia://2026-03-09", "b",
                      source_max_ts=datetime(2026, 3, 9, 18, 30))
    assert (r.rows_identical, r.rows_updated, r.rows_rejected) == (1, 0, 0)
    assert con.execute("SELECT src_ingest_id, tick_volume FROM bars_m1").fetchone() == (dono, 100)


def test_diferenca_no_volume_ainda_e_revisao(con):
    # volume são contratos negociados (da B3): esse continua comparado
    ts = datetime(2026, 3, 9, 9, 0)
    ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)]), "WIN$N", "captura://", "a")
    r = ing.ingest_df(con, _com(_df([(ts, 100, 110, 90, 100)]), volume=24212),
                      "WIN$N", "conferencia://2026-03-09", "b",
                      source_max_ts=datetime(2026, 3, 9, 18, 30))
    assert r.rows_updated == 1
    assert con.execute("SELECT volume FROM bars_m1").fetchone()[0] == 24212
