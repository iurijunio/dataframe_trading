"""Serviço de captura: as contas (core/captura.py), com MT5 e relógio falsos."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import captura as C  # noqa: E402


def barras(*horas, base=100000):
    """Um candle por horário 'HH:MM' de 01/10/2026."""
    ts = [datetime(2026, 10, 1, int(h[:2]), int(h[3:])) for h in horas]
    n = len(ts)
    return pl.DataFrame({
        "ts": ts, "open": [base] * n, "high": [base + 50] * n,
        "low": [base - 50] * n, "close": [base + 10] * n,
        "tick_volume": [100] * n, "volume": [500] * n, "spread": [5] * n,
    })


def test_fechados_nunca_devolve_o_candle_em_formacao():
    b = barras("10:00", "10:01", "10:02")
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 30))["ts"].to_list() == b["ts"].to_list()[:2]


def test_fechados_ultimo_vira_fechado_65s_depois_do_inicio():
    b = barras("10:00", "10:01")
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 4)).height == 1
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 5)).height == 2


def test_fechados_sem_hora_do_servidor_nunca_grava_o_ultimo():
    assert C.fechados(barras("10:00", "10:01"), None).height == 1


def test_apos_queda_de_3h_devolve_tudo_menos_o_em_formacao():
    horas = [f"{h:02d}:{m:02d}" for h in range(10, 13) for m in range(60)]
    b = barras(*horas, "13:00")
    assert C.fechados(b, datetime(2026, 10, 1, 13, 0, 20)).height == 180


def test_fechados_sem_barras_devolve_vazio():
    assert C.fechados(barras("10:00").head(0), datetime(2026, 10, 1, 10, 5)).height == 0


# ------------------------------------------------------- relógio do servidor
T = datetime(2026, 10, 1, 10, 1, 29)


def test_relogio_soma_o_tempo_decorrido_desde_que_o_tick_mudou():
    r = C.RelogioServidor()
    r.observar(T, mono=100.0)
    r.observar(T, mono=130.0)            # mesmo tick: não reinicia a contagem
    assert r.agora(mono=140.0) == T + timedelta(seconds=40)
    r.observar(T + timedelta(seconds=45), mono=145.0)
    assert r.agora(mono=146.0) == T + timedelta(seconds=46)


def test_pc_adiantado_3_min_nao_deixa_passar_o_em_formacao():
    # o PC marca 10:04:29; a hora real (e o tick) é 10:01:29
    r = C.RelogioServidor()
    r.observar(T, mono=0.0)
    b = barras("10:00", "10:01")
    assert C.fechados(b, r.agora(mono=1.0))["ts"].to_list() == b["ts"].to_list()[:1]
    assert r.desvio_s(datetime(2026, 10, 1, 10, 4, 29), mono=1.0) == pytest.approx(179, abs=1)


def test_mercado_parado_fecha_o_ultimo_pelo_tempo_decorrido():
    r = C.RelogioServidor()
    r.observar(datetime(2026, 10, 1, 10, 1, 10), mono=0.0)   # último negócio
    b = barras("10:00", "10:01")
    assert C.fechados(b, r.agora(mono=50.0)).height == 1     # 10:02:00
    assert C.fechados(b, r.agora(mono=56.0)).height == 2     # 10:02:06


def test_relogio_sem_tick_nao_sabe_a_hora():
    r = C.RelogioServidor()
    r.observar(None, mono=0.0)
    assert r.agora(mono=5.0) is None and r.desvio_s(T, mono=5.0) is None


from datetime import date, time  # noqa: E402
import json  # noqa: E402
from core import calendar as cal  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "t.duckdb")
    db.init_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------- gravar
def test_gravar_insere_e_registra_a_origem(con):
    r = C.gravar(con, "WIN$N", barras("10:00", "10:01"), "captura://1@srv")
    assert r == {"inseridos": 2, "revisados": 0}
    assert con.execute("SELECT source_file FROM ingest_log").fetchone()[0] == "captura://1@srv"


def test_gravar_repetido_nao_grava_nem_cria_lote(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    r = C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    assert r == {"inseridos": 0, "revisados": 0}
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 1


def test_gravar_candle_diferente_vira_revisao(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    r = C.gravar(con, "WIN$N", barras("10:00", "10:01", base=100020), "captura://1@srv")
    assert r == {"inseridos": 1, "revisados": 1}


def test_gravar_reenvio_perdedor_nao_cria_lote(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00", base=100020),
                   agora=datetime(2026, 10, 1, 18, 30))
    lotes = con.execute("SELECT count(*) FROM ingest_log").fetchone()[0]
    for _ in range(3):
        assert C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv") == {
            "inseridos": 0, "revisados": 0}
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == lotes
    assert con.execute("SELECT open FROM bars_m1").fetchone()[0] == 100020


def test_gravar_com_os_tipos_reais_do_mt5_nao_repete_lote(con):
    b = pl.DataFrame({
        "ts": pl.Series([datetime(2026, 10, 1, 10, 0), datetime(2026, 10, 1, 10, 1)],
                        dtype=pl.Datetime("ns")),
        "open": [100000.0, 100010.0], "high": [100050.0] * 2,
        "low": [99950.0] * 2, "close": [100010.0] * 2,
        "tick_volume": pl.Series([100, 200], dtype=pl.UInt64),
        "volume": pl.Series([500, 600], dtype=pl.UInt64),
        "spread": pl.Series([5, 5], dtype=pl.Int32)})
    assert C.gravar(con, "WIN$N", b, "captura://1@srv") == {"inseridos": 2, "revisados": 0}
    assert C.gravar(con, "WIN$N", b, "captura://1@srv") == {"inseridos": 0, "revisados": 0}
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 1


# --------------------------------------------------------------- lacunas
def test_lacunas_so_o_que_o_mt5_tem_e_o_banco_nao():
    m = lambda *h: barras(*h)["ts"].to_list()  # noqa: E731
    assert C.lacunas(m("09:03", "09:04", "09:05"), m("09:03", "09:04", "09:05")) == []
    assert C.lacunas(m("09:03", "09:04", "09:05"), m("09:03", "09:05")) == m("09:04")
    # minuto que ninguém tem (leilão 09:00–09:02, mercado parado) não é lacuna
    assert C.lacunas(m("09:03", "09:06"), m("09:03", "09:06")) == []
    # minuto que só o banco tem não é lacuna (não é a diferença simétrica)
    assert C.lacunas(m("09:03"), m("09:03", "09:04")) == []


# --------------------------------------------- fechamento e horário de pregão
def _dia(con, d, fecha):
    df = barras("09:00", fecha).with_columns(
        pl.col("ts").dt.replace(year=d.year, month=d.month, day=d.day))
    ing.ingest_df(con, df, "WIN$N", f"t{d}", f"s{d}")


def test_fechamento_esperado_e_o_mais_frequente_dos_ultimos_10(con):
    for i in range(1, 9):
        _dia(con, date(2026, 9, i), "17:54")
    _dia(con, date(2026, 9, 9), "18:24")
    cal.rebuild_trading_days(con, "WIN$N")
    assert C.fechamento_esperado(con, "WIN$N") == time(17, 54)


def test_fechamento_esperado_sem_historico_e_18_24(con):
    assert C.fechamento_esperado(con, "WIN$N") == time(18, 24)


def test_em_pregao():
    f = time(17, 54)
    assert C.em_pregao(datetime(2026, 10, 1, 9, 0), f)          # quinta
    assert C.em_pregao(datetime(2026, 10, 1, 17, 59), f)        # folga de 6 min
    assert not C.em_pregao(datetime(2026, 10, 1, 18, 1), f)
    assert not C.em_pregao(datetime(2026, 10, 1, 8, 50), f)
    assert not C.em_pregao(datetime(2026, 10, 3, 10, 0), f)     # sábado


# ------------------------------------------------------------ conferência
def test_conferencia_vence_a_captura_do_mesmo_minuto(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    r = C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00", "10:01", base=100020),
                       agora=datetime(2026, 10, 1, 18, 30))
    assert r == {"revisados": 1, "faltantes": 1}
    assert con.execute("SELECT DISTINCT open FROM bars_m1").fetchall() == [(100020,)]


def test_conferencia_vence_mesmo_com_a_captura_tendo_candle_mais_novo(con):
    # a captura chegou até 10:02; a conferência relê só até 10:01 e ainda assim
    # vence, porque o que conta é a hora em que ela rodou (source_max_ts)
    C.gravar(con, "WIN$N", barras("10:00", "10:01", "10:02"), "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00", "10:01", base=100020),
                   agora=datetime(2026, 10, 1, 18, 30))
    assert con.execute("SELECT open FROM bars_m1 WHERE ts = '2026-10-01 10:00'").fetchone()[0] == 100020


def test_exportacao_manual_posterior_vence_a_conferencia(con, tmp_path):
    from tests.test_ingest import write_export
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00"),
                   agora=datetime(2026, 10, 1, 18, 30))
    ing.ingest_csv(con, write_export(tmp_path / "m.tsv", [
        (datetime(2026, 10, 1, 10, 0), 99000, 99100, 98900, 99050),
        (datetime(2026, 10, 2, 18, 24), 99000, 99100, 98900, 99050)]), "WIN$N")
    assert con.execute("SELECT open FROM bars_m1 WHERE ts = '2026-10-01 10:00'").fetchone()[0] == 99000


def test_conferencia_sem_nada_novo_ainda_marca_o_dia(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00"),
                   agora=datetime(2026, 10, 1, 18, 30))
    assert C.dias_pendentes(con, "WIN$N", date(2026, 10, 2), fechou_hoje=False) == []


def test_conferencia_recusa_dia_sem_candle_do_mt5(con):
    with pytest.raises(ValueError, match="não devolveu"):
        C.conferir_dia(con, "WIN$N", date(2026, 10, 2), barras("10:00"),
                       agora=datetime(2026, 10, 2, 18, 30))


def test_recuperacao_de_3_dias_deixa_os_3_pendentes(con):
    for d in (date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)):
        df = barras("10:00").with_columns(pl.lit(datetime(d.year, d.month, d.day, 10, 0)).alias("ts"))
        C.gravar(con, "WIN$N", df, "captura://1@srv")
    hoje = date(2026, 10, 1)
    assert C.dias_pendentes(con, "WIN$N", hoje, fechou_hoje=False) == [
        date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]


def test_hoje_so_fica_pendente_depois_do_fechamento(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    hoje = date(2026, 10, 1)
    assert C.dias_pendentes(con, "WIN$N", hoje, fechou_hoje=False) == []
    assert C.dias_pendentes(con, "WIN$N", hoje, fechou_hoje=True) == [hoje]


# ----------------------------------------------------------------- estado
def test_estado_ida_e_volta(tmp_path):
    p = tmp_path / "ao_vivo" / "estado.json"
    C.escrever_estado(p, {"mt5": "conectado", "ultimo_salvo": datetime(2026, 10, 1, 10, 0)})
    assert C.ler_estado(p) == {"mt5": "conectado", "ultimo_salvo": "2026-10-01T10:00:00"}
    assert not p.with_suffix(".tmp").exists()


def test_estado_ilegivel_ou_ausente_devolve_none(tmp_path):
    p = tmp_path / "estado.json"
    assert C.ler_estado(p) is None
    p.write_text("{meio arquivo", encoding="utf-8")
    assert C.ler_estado(p) is None


def test_escrever_estado_tenta_de_novo_se_o_windows_recusar(tmp_path, monkeypatch):
    p = tmp_path / "estado.json"
    real = C.os.replace
    falhas = {"n": 0}

    def replace_teimoso(a, b):
        if falhas["n"] < 2:
            falhas["n"] += 1
            raise PermissionError("arquivo em uso")
        return real(a, b)

    monkeypatch.setattr(C.os, "replace", replace_teimoso)
    C.escrever_estado(p, {"ok": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": 1}


# ---- captura ativa: a trava dos comandos que reconstroem a base ----

def test_captura_ativa_em_pelo_estado_de_menos_de_60_s(tmp_path):
    p = tmp_path / "estado.json"
    agora = datetime(2026, 10, 1, 10, 0)
    assert C.captura_ativa_em(p, agora) is False          # nunca rodou
    p.write_text(json.dumps({"atualizado_em": "2026-10-01T09:59:05"}), encoding="utf-8")
    assert C.captura_ativa_em(p, agora) is True
    p.write_text(json.dumps({"atualizado_em": "2026-10-01T09:58:59"}), encoding="utf-8")
    assert C.captura_ativa_em(p, agora) is False
    p.write_text(json.dumps({"mt5": "fechado"}), encoding="utf-8")
    assert C.captura_ativa_em(p, agora) is False
    p.write_text("{meio arquivo", encoding="utf-8")
    assert C.captura_ativa_em(p, agora) is False


# ---------------------------------------------- tick_volume e reconferência
def test_gravar_reenvio_que_so_muda_tick_volume_nao_cria_lote(con):
    # a corretora revisa o tick_volume; sem ignorá-lo no anti-join, cada
    # volta de 1 s criaria um lote vazio no ingest_log
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    outro = barras("10:00").with_columns(pl.lit(1195).alias("tick_volume"))
    for _ in range(2):
        assert C.gravar(con, "WIN$N", outro, "captura://1@srv") == {
            "inseridos": 0, "revisados": 0}
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 1


def _leilao_separado(con):
    """O caso real de 01/10: a captura gravou o 18:24 antes do leilão e o
    leilão de fechamento como candle próprio às 18:31; a conferência das
    18:38 bateu com o MT5 daquela hora."""
    b = barras("18:23", "18:24", "18:31", base=187800)
    b = b.with_columns(
        pl.when(pl.col("ts").dt.minute() == 31).then(187760).otherwise(pl.col("open")).alias("open"),
        pl.when(pl.col("ts").dt.minute() == 31).then(187760).otherwise(pl.col("high")).alias("high"),
        pl.when(pl.col("ts").dt.minute() == 31).then(187760).otherwise(pl.col("low")).alias("low"),
        pl.when(pl.col("ts").dt.minute() == 31).then(187760).otherwise(pl.col("close")).alias("close"),
        pl.when(pl.col("ts").dt.minute() == 31).then(22355).otherwise(1857).alias("volume"))
    C.gravar(con, "WIN$N", b, "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), b, agora=datetime(2026, 10, 1, 18, 38))
    return b


def _consolidado(b):
    # o MT5 de madrugada: sem 18:31, o 18:24 fecha no leilão com o volume
    # somado, e o tick_volume dos minutos anteriores revisado
    return b.filter(pl.col("ts").dt.minute() != 31).with_columns(
        pl.when(pl.col("ts").dt.minute() == 24).then(187760).otherwise(pl.col("close")).alias("close"),
        pl.when(pl.col("ts").dt.minute() == 24).then(187760).otherwise(pl.col("low")).alias("low"),
        pl.when(pl.col("ts").dt.minute() == 24).then(24212).otherwise(pl.col("volume")).alias("volume"),
        pl.lit(1195).alias("tick_volume"))


def _outro_dia(con):
    df = barras("10:00").with_columns(pl.lit(datetime(2026, 9, 30, 18, 40)).alias("ts"))
    C.gravar(con, "WIN$N", df, "captura://1@srv")


def test_reconferencia_deixa_o_dia_igual_ao_mt5_consolidado(con):
    _outro_dia(con)
    b = _leilao_separado(con)
    r = C.reconferir_dia(con, "WIN$N", date(2026, 10, 1), _consolidado(b),
                         agora=datetime(2026, 10, 2, 8, 50))
    assert r == {"revisados": 1, "faltantes": 0, "removidos": 1}
    linhas = con.execute(
        "SELECT CAST(ts AS TIME), close, volume FROM bars_m1 "
        "WHERE CAST(ts AS DATE) = '2026-10-01' ORDER BY ts").fetchall()
    assert linhas == [(time(18, 23), 187810, 1857), (time(18, 24), 187760, 24212)]
    # o outro dia não é tocado
    assert con.execute("SELECT count(*) FROM bars_m1 WHERE CAST(ts AS DATE) = '2026-09-30'"
                       ).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM ingest_log WHERE source_file = "
                       "'reconferencia://2026-10-01'").fetchone()[0] == 1


def test_reconferencia_sem_candle_do_mt5_recusa_e_nao_apaga(con):
    _leilao_separado(con)
    antes = con.execute("SELECT * FROM bars_m1 ORDER BY ts").fetchall()
    lotes = con.execute("SELECT count(*) FROM ingest_log").fetchone()[0]
    vazio = barras("10:00").filter(pl.lit(False))
    with pytest.raises(ValueError, match="não devolveu"):
        C.reconferir_dia(con, "WIN$N", date(2026, 10, 1), vazio,
                         agora=datetime(2026, 10, 2, 8, 50))
    # o MT5 de outro dia também não serve: o filtro é pelo dia pedido
    with pytest.raises(ValueError, match="não devolveu"):
        C.reconferir_dia(con, "WIN$N", date(2026, 10, 1),
                         barras("10:00").with_columns(pl.lit(datetime(2026, 10, 2, 10)).alias("ts")),
                         agora=datetime(2026, 10, 2, 8, 50))
    assert con.execute("SELECT * FROM bars_m1 ORDER BY ts").fetchall() == antes
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == lotes


def test_dias_a_reconferir_so_passados_conferidos_e_uma_vez(con):
    b1 = _leilao_separado(con)                  # 01/10 conferido
    b2 = barras("10:00").with_columns(pl.lit(datetime(2026, 10, 2, 10)).alias("ts"))
    C.gravar(con, "WIN$N", b2, "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 2), b2, agora=datetime(2026, 10, 2, 18, 30))
    # dia sem conferência (exportação antiga) nunca é reconferido
    ing.ingest_df(con, barras("10:00").with_columns(
        pl.lit(datetime(2026, 3, 12, 10)).alias("ts")), "WIN$N", "antigo.csv", "s")
    assert C.dias_a_reconferir(con, "WIN$N", date(2026, 10, 2)) == [date(2026, 10, 1)]
    assert C.dias_a_reconferir(con, "WIN$N", date(2026, 10, 5)) == [
        date(2026, 10, 1), date(2026, 10, 2)]
    C.reconferir_dia(con, "WIN$N", date(2026, 10, 1), _consolidado(b1),
                     agora=datetime(2026, 10, 2, 8, 50))
    assert C.dias_a_reconferir(con, "WIN$N", date(2026, 10, 5)) == [date(2026, 10, 2)]


def test_gravar_reenvio_que_so_muda_spread_nao_cria_lote(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    outro = barras("10:00").with_columns(pl.lit(0).alias("spread"))
    assert C.gravar(con, "WIN$N", outro, "captura://1@srv") == {"inseridos": 0, "revisados": 0}
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 1


def _min(inicio, n, pular=()):
    return [inicio + timedelta(minutes=i) for i in range(n) if i not in pular]


def _barras_ts(ts):
    n = len(ts)
    return pl.DataFrame({"ts": ts, "open": [100000] * n, "high": [100050] * n,
                         "low": [99950] * n, "close": [100010] * n,
                         "tick_volume": [100] * n, "volume": [500] * n, "spread": [5] * n})


@pytest.mark.parametrize("caso", ["comeca_tarde", "remove_demais", "so_a_tarde"])
def test_reconferencia_com_dia_parcial_do_mt5_recusa_e_nao_apaga(con, caso):
    """O MT5 que devolve o dia pela metade (histórico ainda carregando)
    apagaria candles bons: só a falta de 1 a 3 minutos (o leilão) passa."""
    nove = datetime(2026, 10, 1, 9, 0)
    if caso == "comeca_tarde":
        # um minuto a menos no começo, mas o MT5 só começa 6 min depois
        banco, mt5 = [nove] + _min(nove + timedelta(minutes=10), 21), _min(nove + timedelta(minutes=6), 25)
    elif caso == "remove_demais":
        banco, mt5 = _min(nove, 20), _min(nove, 24, pular=(5, 6, 7, 8))
    else:
        banco, mt5 = _min(nove, 20) + _min(datetime(2026, 10, 1, 14, 0), 20), \
            _min(datetime(2026, 10, 1, 14, 0), 20)
    b = _barras_ts(banco)
    C.gravar(con, "WIN$N", b, "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), b, agora=datetime(2026, 10, 1, 18, 40))
    antes = con.execute("SELECT * FROM bars_m1 ORDER BY ts").fetchall()
    with pytest.raises(ValueError):
        C.reconferir_dia(con, "WIN$N", date(2026, 10, 1), _barras_ts(mt5),
                         agora=datetime(2026, 10, 2, 9, 0))
    assert con.execute("SELECT * FROM bars_m1 ORDER BY ts").fetchall() == antes
    assert C.dias_a_reconferir(con, "WIN$N", date(2026, 10, 2)) == [date(2026, 10, 1)]


def test_pode_reconferir_so_a_partir_da_abertura_do_dia_seguinte():
    d = date(2026, 10, 1)
    # logo depois da meia-noite a corretora ainda não consolidou
    assert not C.pode_reconferir(d, datetime(2026, 10, 2, 0, 10))
    assert not C.pode_reconferir(d, datetime(2026, 10, 2, 8, 54))
    assert C.pode_reconferir(d, datetime(2026, 10, 2, 8, 56))
    assert C.pode_reconferir(d, datetime(2026, 10, 2, 15, 0))
    assert C.pode_reconferir(d, datetime(2026, 10, 5, 0, 10))


def test_dia_mais_velho_que_5_pregoes_sai_da_reconferencia(con):
    dias = [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29),
            date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    for d in dias:
        b = _barras_ts([datetime(d.year, d.month, d.day, 10, 0)])
        C.gravar(con, "WIN$N", b, "captura://1@srv")
        C.conferir_dia(con, "WIN$N", d, b, agora=datetime(d.year, d.month, d.day, 18, 40))
    # hoje = 05/10: os 5 pregões anteriores são 28/09..02/10
    assert C.dias_a_reconferir(con, "WIN$N", date(2026, 10, 5)) == dias[2:]
    assert C.dias_abandonados(con, "WIN$N", date(2026, 10, 5)) == dias[:2]
