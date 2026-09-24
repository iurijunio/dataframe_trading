from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _mineracao_com_plano_ativo(run_id, variante_id, wfa_id,
                               symbol="WIN$N", strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, "2026-01-01", 10, "concluida", variante_id])
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])
    plano.salvar(
        wfa_id=wfa_id, run_id=run_id, symbol=symbol, strategy=strategy,
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})


def test_criar_e_listar(banco):
    pid = P.criar("meu portfólio")
    ps = P.listar()
    assert [p["portfolio_id"] for p in ps] == [pid]
    assert ps[0]["nome"] == "meu portfólio"
    assert ps[0]["n_membros"] == 0


def test_adicionar_e_remover_membro(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert [m["variante_id"] for m in ms] == [vid]
    assert P.listar()[0]["n_membros"] == 1

    P.remover_variante(pid, vid)
    assert P.membros(pid) == []
    assert P.listar()[0]["n_membros"] == 0


def test_membro_sem_plano_ativo_e_sinalizado(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is True
    assert ms[0]["wfa_id"] is None


def test_membro_com_plano_ativo_traz_o_wfa_id(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is False
    assert ms[0]["wfa_id"] == 10


def test_adicionar_a_mesma_variante_duas_vezes_nao_duplica(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)
    P.adicionar_variante(pid, vid)
    assert len(P.membros(pid)) == 1


# --------------------------------------------------------------- correlacao
from datetime import datetime, timedelta


def _gravar_trades(wfa_id, dias_e_liquidos):
    """dias_e_liquidos: [(offset_dias, liquido), ...] a partir de 2026-01-01."""
    base = datetime(2026, 1, 1)
    with db.connect_write() as con:
        for n, (offset, liquido) in enumerate(dias_e_liquidos):
            ts = base + timedelta(days=offset)
            con.execute(
                "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, "
                "liquido, mae, contratos) VALUES (?,?,?,?,?,?,?)",
                [wfa_id, n, ts, ts, liquido, 100, 1])


def _membro_pronto(pid, nome, wfa_id, dias_e_liquidos):
    vid = variantes.criar(nome, "rompimento_canal")
    _mineracao_com_plano_ativo(wfa_id, vid, wfa_id=wfa_id)
    P.adicionar_variante(pid, vid)
    _gravar_trades(wfa_id, dias_e_liquidos)
    return vid


def test_correlacao_de_series_identicas_e_proxima_de_um(banco):
    pid = P.criar("p1")
    serie = [(i, float((i % 5) - 2)) for i in range(30)]
    _membro_pronto(pid, "a", 10, serie)
    _membro_pronto(pid, "b", 11, serie)

    r = P.correlacao(pid)

    assert r["variantes"] == ["a", "b"]
    assert r["matriz"][0][1] == pytest.approx(1.0, abs=1e-6)
    assert r["avisos"] == []


def test_correlacao_de_series_opostas_e_proxima_de_menos_um(banco):
    pid = P.criar("p1")
    serie_a = [(i, float((i % 5) - 2)) for i in range(30)]
    serie_b = [(i, -v) for i, v in serie_a]
    _membro_pronto(pid, "a", 10, serie_a)
    _membro_pronto(pid, "b", 11, serie_b)

    r = P.correlacao(pid)
    assert r["matriz"][0][1] == pytest.approx(-1.0, abs=1e-6)


def test_periodo_sem_intersecao_suficiente_vira_aviso(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 1.0) for i in range(30)])
    _membro_pronto(pid, "b", 11, [(i, 1.0) for i in range(200, 210)])

    r = P.correlacao(pid)
    assert r["matriz"][0][1] is None
    assert "período curto demais" in r["avisos"][0]


def test_serie_com_variancia_zero_vira_aviso_nao_nan(banco):
    """Retorno constante no periodo faz corrcoef dar 0/0 = nan - um numero
    "real" sem sentido nenhum se deixado passar direto pra matriz."""
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 5.0) for i in range(30)])  # sempre +5
    _membro_pronto(pid, "b", 11, [(i, float((i % 5) - 2)) for i in range(30)])

    r = P.correlacao(pid)
    assert r["matriz"][0][1] is None
    assert "variação suficiente" in r["avisos"][0]


def test_membro_sem_plano_ativo_fica_de_fora_da_matriz(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 1.0) for i in range(30)])
    vid_b = variantes.criar("b", "rompimento_canal")
    P.adicionar_variante(pid, vid_b)

    r = P.correlacao(pid)
    assert r["variantes"] == ["a"]
    assert any("sem plano ativo" in a for a in r["avisos"])
