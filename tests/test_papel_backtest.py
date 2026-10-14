"""Conferência diária papel × backtest (spec ao-vivo-ordens §8).

O papel conferido de um dia tem de ser, operação por operação, o backtest
do mesmo plano rodado sobre o histórico inteiro até o fim do dia. Os testes
gravam o papel de verdade (`papel.conferir`) e mexem nele à mão para ver a
diferença aparecer."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario, papel  # noqa: E402
from core import papel_backtest as PB  # noqa: E402
from core import portfolio as P  # noqa: E402
from core.captura import PREFIXO_RECONFERENCIA  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401
from core.engine.execution import ExecutionProfile  # noqa: E402
from tests.fabrica_ao_vivo import (barras_sinteticas, inserir_barras,  # noqa: E402
                                   ligacao_com_plano)

SIMB = "WIN$N"
PARAMS = {"periodo_canal": 20, "folga_ticks": 0, "filtro_amplitude": 0,
          "stop_pontos": 123}
PERFIL = ExecutionProfile(timeframe="M5", stop_pontos=300, alvo_pontos=400,
                          corretagem_por_contrato=0.5,
                          emolumentos_por_contrato=0.25).to_config()
CONTRATOS = 2


@pytest.fixture(autouse=True)
def sem_recarga(monkeypatch):
    """`papel._modulo` recarrega a estratégia que já está importada; de
    verdade, isso trocaria a classe `Signals` no meio da suíte."""
    monkeypatch.setattr(papel.importlib, "reload", lambda mod: mod)


@pytest.fixture
def mundo(banco):
    b, dias = barras_sinteticas()
    with db.connect() as con:
        inserir_barras(con, b, symbol=SIMB)
    f = ligacao_com_plano("romp-pb", params=PARAMS, profile=PERFIL,
                          contratos=CONTRATOS, portfolio_id=P.criar("pf"))
    return SimpleNamespace(barras=b, dias=dias, lig=f.lig, pf=f.pf, v=f.v,
                           plano_id=f.plano_id)


def _as(dia: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(dia, time(hh, mm))


def _conferir_papel(con, dia):
    papel.conferir(con, dia, _as(dia, 19), {})
    st = con.execute("SELECT status FROM papel_pregoes WHERE dia = ?",
                     [dia]).fetchone()
    assert st == ("conferido",)


def _marca_reconferencia(con, dia, quando):
    """A marca que a reconferência da manhã grava no ingest_log
    (`captura.reconferir_dia`): `source_max_ts` = hora da captura."""
    n = con.execute("SELECT count(*) FROM ingest_log").fetchone()[0]
    con.execute(
        "INSERT INTO ingest_log (ingest_id, symbol, source_file, "
        "source_max_ts, ingested_at) VALUES (?, ?, ?, ?, ?)",
        [1000 + n, SIMB, f"{PREFIXO_RECONFERENCIA}{dia:%Y-%m-%d}", quando,
         quando])


def _ops(con, lig, dia):
    return con.execute(
        "SELECT op_id, entry_ts, exit_px, conta FROM papel_operacoes "
        "WHERE ligacao_id = ? AND dia = ? ORDER BY entry_ts",
        [lig, dia]).fetchall()


def _gravado(con, lig, dia):
    r = con.execute("SELECT ok, n_papel, n_backtest, diferencas, "
                    "conferido_em FROM papel_backtest WHERE ligacao_id = ? "
                    "AND dia = ?", [lig, dia]).fetchone()
    if r is None:
        return None
    return {"ok": r[0], "n_papel": r[1], "n_backtest": r[2],
            "diferencas": json.loads(r[3]), "conferido_em": r[4]}


def _resultado(**campos):
    """O formato de `conferir`: sempre as mesmas chaves."""
    return {"ok": None, "n_papel": 0, "n_backtest": 0, "diferencas": [],
            "checksum_mudou": False, "outra_versao": False,
            "outro_codigo": False, **campos}


def _situacao(**campos):
    return {"pregoes": 0, "operacoes": 0, "diferencas": 0, "ok": None,
            "outra_versao": 0, "outro_codigo": 0, **campos}


def _operacao_extra(con, m, dia, entry_ts, conta=True):
    con.execute(
        "INSERT INTO papel_operacoes (op_id, ligacao_id, plano_id, dia, "
        "entry_ts, exit_ts, side, contratos, entry_px, exit_px, points, "
        "bruto, custo, liquido, reason, aberta, conta, calculado_em) VALUES "
        "(nextval('seq_papel_op'), ?, ?, ?, ?, ?, 1, 2, 120000, 120100, 100, "
        "40, 3, 37, 2, false, ?, ?)",
        [m.lig, m.plano_id, dia, entry_ts, _as(dia, 18, 10), conta,
         _as(dia, 19)])


# ------------------------------------------------------------- conferir
def test_papel_igual_ao_backtest(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        n_ops = len(_ops(con, mundo.lig, dia))
        r = PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
        g = _gravado(con, mundo.lig, dia)
    assert n_ops > 0, "o dia escolhido precisa ter operação"
    assert r == _resultado(ok=True, n_papel=n_ops, n_backtest=n_ops)
    assert g["ok"] is True
    assert g["diferencas"] == {"checksum_mudou": False, "operacoes": []}
    assert (g["n_papel"], g["n_backtest"]) == (n_ops, n_ops)


def test_operacao_a_mais_no_papel_vira_diferenca(mundo):
    dia = mundo.dias[30]
    extra = _as(dia, 17, 57)
    with db.connect() as con:
        _conferir_papel(con, dia)
        n_ops = len(_ops(con, mundo.lig, dia))
        assert extra not in [o[1] for o in _ops(con, mundo.lig, dia)]
        _operacao_extra(con, mundo, dia, extra)
        r = PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
        g = _gravado(con, mundo.lig, dia)
    assert r["ok"] is False
    assert (r["n_papel"], r["n_backtest"]) == (n_ops + 1, n_ops)
    assert r["diferencas"] == [{
        "entry_ts": extra,
        "papel": (extra, 1, 120000, _as(dia, 18, 10), 120100, 2),
        "backtest": None}]
    assert g["ok"] is False and len(g["diferencas"]["operacoes"]) == 1
    assert g["diferencas"]["operacoes"][0]["backtest"] is None


def test_operacao_que_nao_conta_fica_fora_da_comparacao(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        _operacao_extra(con, mundo, dia, _as(dia, 17, 57), conta=False)
        r = PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
    assert r["ok"] is True and r["diferencas"] == []


def test_preco_de_saida_diferente_e_diferenca(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        op_id, entry_ts, exit_px, _ = _ops(con, mundo.lig, dia)[0]
        con.execute("UPDATE papel_operacoes SET exit_px = exit_px + 5 "
                    "WHERE op_id = ?", [op_id])
        r = PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
    assert r["ok"] is False
    [d] = r["diferencas"]
    assert d["entry_ts"] == entry_ts
    assert d["papel"][4] == exit_px + 5 and d["backtest"][4] == exit_px
    assert d["papel"][:4] == d["backtest"][:4]


def test_backtest_usa_os_mesmos_periodos_ligados(mundo):
    # desligada às 11h: o papel marca as entradas depois disso como "não
    # conta", e o backtest não pode cobrá-las
    dia = mundo.dias[30]
    with db.connect() as con:
        diario.registrar(con, "membro_desligado", "usuario",
                         portfolio_id=mundo.pf, ligacao_id=mundo.lig,
                         variante_id=mundo.v, quando=_as(dia, 11))
        con.execute("UPDATE portfolio_membros SET ligada = false")
        _conferir_papel(con, dia)
        ops = _ops(con, mundo.lig, dia)
        r = PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
    contam = sum(1 for o in ops if o[3])
    assert 0 < contam < len(ops), "precisa de operação dos dois lados das 11h"
    assert r == _resultado(ok=True, n_papel=contam, n_backtest=contam)


def test_conferir_de_novo_atualiza_a_linha(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        _operacao_extra(con, mundo, dia, _as(dia, 17, 57))
        PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
        con.execute("DELETE FROM papel_operacoes WHERE entry_ts = ?",
                    [_as(dia, 17, 57)])
        PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23, 30))
        n = con.execute("SELECT count(*) FROM papel_backtest").fetchone()[0]
        g = _gravado(con, mundo.lig, dia)
    assert n == 1
    assert g["ok"] is True and g["conferido_em"] == _as(dia, 23, 30)


def test_pregao_nao_conferido_nao_se_confere(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), {}),
                     _as(dia, 12))
        with pytest.raises(ValueError, match="não está conferido"):
            PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))


def test_ligacao_que_nao_existe_diz_isso(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        with pytest.raises(ValueError, match=f"ligação #{mundo.lig + 99} "
                                             "não existe"):
            PB.conferir(con, mundo.lig + 99, dia, {}, _as(dia, 23))


def test_plano_sem_estrategia_usa_a_da_variante(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        con.execute("UPDATE planos_operacao SET strategy = NULL")
        _marca_reconferencia(con, dia, _as(mundo.dias[31], 8))
        assert PB.pendentes(con, SIMB) == [(mundo.lig, dia)]
        r = PB.conferir(con, mundo.lig, dia, {}, _as(mundo.dias[31], 9))
    assert r["ok"] is True and r["n_papel"] > 0


def test_candles_mudados_depois_do_papel_ficam_marcados(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        _conferir_papel(con, dia)
        con.execute("UPDATE bars_m1 SET close = close + 5 WHERE ts = ?",
                    [_as(dia, 9, 30)])
        r = PB.conferir(con, mundo.lig, dia, {}, _as(dia, 23))
        g = _gravado(con, mundo.lig, dia)
    assert r["checksum_mudou"] is True
    assert g["diferencas"]["checksum_mudou"] is True


# ------------------------------------------------------------- versão do motor
def test_papel_de_outra_versao_do_motor_nao_e_falha(mundo):
    # o papel calculado com o motor antigo não é comparável com o backtest
    # do motor de hoje: não entra na fila nem grava falha
    dia = mundo.dias[30]
    seguinte = mundo.dias[31]
    with db.connect() as con:
        _conferir_papel(con, dia)
        con.execute("UPDATE papel_pregoes SET motor_versao = '2026.01.01'")
        _marca_reconferencia(con, dia, _as(seguinte, 8))
        assert PB.pendentes(con, SIMB) == []
        r = PB.conferir(con, mundo.lig, dia, {}, _as(seguinte, 9))
        assert r == _resultado(n_papel=r["n_papel"], outra_versao=True)
        assert _gravado(con, mundo.lig, dia) is None
        s = PB.situacao(con, mundo.lig)
    assert s == _situacao(outra_versao=1)


def test_papel_de_outro_codigo_nao_e_falha(mundo):
    # o código da estratégia mudou depois do pregão: o backtest rodaria o
    # código novo contra o papel do antigo (e `papel.reabriveis` não reabre)
    dia = mundo.dias[30]
    seguinte = mundo.dias[31]
    with db.connect() as con:
        _conferir_papel(con, dia)
        con.execute("UPDATE papel_pregoes SET codigo_hash = 'antigo'")
        _marca_reconferencia(con, dia, _as(seguinte, 8))
        assert PB.pendentes(con, SIMB) == []
        r = PB.conferir(con, mundo.lig, dia, {}, _as(seguinte, 9))
        assert r == _resultado(n_papel=r["n_papel"], outro_codigo=True)
        assert _gravado(con, mundo.lig, dia) is None
        s = PB.situacao(con, mundo.lig)
    assert s == _situacao(outro_codigo=1)


# ------------------------------------------------------------- pendentes
def test_pendentes_so_depois_da_reconferencia(mundo):
    dia = mundo.dias[30]
    seguinte = mundo.dias[31]
    with db.connect() as con:
        # rodando: ainda não
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), {}),
                     _as(dia, 12))
        _marca_reconferencia(con, dia, _as(seguinte, 8))
        assert PB.pendentes(con, SIMB) == []
        con.execute("DELETE FROM ingest_log")
        # conferido, sem reconferência: ainda não
        _conferir_papel(con, dia)
        assert PB.pendentes(con, SIMB) == []
        # reconferência de OUTRO dia não vale
        _marca_reconferencia(con, mundo.dias[29], _as(dia, 8))
        assert PB.pendentes(con, SIMB) == []
        _marca_reconferencia(con, dia, _as(seguinte, 8))
        assert PB.pendentes(con, SIMB) == [(mundo.lig, dia)]
        # outro símbolo não traz
        assert PB.pendentes(con, "WDO$N") == []
        PB.conferir(con, mundo.lig, dia, {}, _as(seguinte, 9))
        assert PB.pendentes(con, SIMB) == []
        # reconferência posterior à checagem: confere de novo
        _marca_reconferencia(con, dia, _as(seguinte, 10))
        assert PB.pendentes(con, SIMB) == [(mundo.lig, dia)]


def test_pendentes_volta_quando_o_papel_e_refeito_depois_da_checagem(mundo):
    # a checagem rodou depois da marca mas ANTES de reabrir + conferir o
    # papel: a linha gravada fala de um papel que não existe mais
    dia = mundo.dias[30]
    seguinte = mundo.dias[31]
    with db.connect() as con:
        _conferir_papel(con, dia)
        _marca_reconferencia(con, dia, _as(seguinte, 8))
        PB.conferir(con, mundo.lig, dia, {}, _as(seguinte, 8, 1))
        assert PB.pendentes(con, SIMB) == []
        con.execute("UPDATE papel_pregoes SET calculado_em = ?",
                    [_as(seguinte, 8, 2)])
        assert PB.pendentes(con, SIMB) == [(mundo.lig, dia)]
        PB.conferir(con, mundo.lig, dia, {}, _as(seguinte, 8, 3))
        assert PB.pendentes(con, SIMB) == []


# ------------------------------------------------------------- situação
def test_situacao_agrega(mundo):
    d1, d2 = mundo.dias[30], mundo.dias[31]
    with db.connect() as con:
        assert PB.situacao(con, mundo.lig) == _situacao()
        _conferir_papel(con, d1)
        papel.conferir(con, d2, _as(d2, 19), {})
        r1 = PB.conferir(con, mundo.lig, d1, {}, _as(d2, 9))
        assert PB.situacao(con, mundo.lig)["ok"] is True
        _operacao_extra(con, mundo, d2, _as(d2, 17, 57))
        r2 = PB.conferir(con, mundo.lig, d2, {}, _as(d2, 23))
        s = PB.situacao(con, mundo.lig)
        assert PB.situacao(con, mundo.lig + 99)["ok"] is None
    assert s == _situacao(pregoes=2, operacoes=r1["n_papel"] + r2["n_papel"],
                          diferencas=1, ok=False)
