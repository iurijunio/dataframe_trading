from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def test_criar_devolve_id_e_listar_encontra(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    achadas = variantes.listar("rompimento_canal")
    assert [v["variante_id"] for v in achadas] == [vid]
    assert achadas[0]["nome"] == "conservadora"


def test_listar_sem_filtro_devolve_todas_as_estrategias(banco):
    variantes.criar("conservadora", "rompimento_canal")
    variantes.criar("padrao", "reversao_rsi")
    achadas = variantes.listar()
    assert {v["nome"] for v in achadas} == {"conservadora", "padrao"}


def test_nome_duplicado_na_mesma_estrategia_e_recusado(banco):
    variantes.criar("conservadora", "rompimento_canal")
    with pytest.raises(ValueError, match="já existe"):
        variantes.criar("conservadora", "rompimento_canal")


def test_nome_duplicado_em_estrategias_diferentes_e_aceito(banco):
    a = variantes.criar("conservadora", "rompimento_canal")
    b = variantes.criar("conservadora", "reversao_rsi")
    assert a != b


def _mineracao_no_banco(run_id, variante_id, symbol="WIN$N",
                        strategy="rompimento_canal", criado_em=None):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, criado_em or datetime.now(),
             10, "concluida", variante_id])


def _wfa_no_banco(wfa_id, run_id, symbol="WIN$N",
                  strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])


def test_linha_do_tempo_em_ordem_cronologica(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid, criado_em=datetime(2026, 1, 1))
    _mineracao_no_banco(2, vid, criado_em=datetime(2026, 6, 1))

    linha = variantes.linha_do_tempo(vid)

    assert [l["run_id"] for l in linha] == [1, 2]
    assert linha[0]["wfa_id"] is None and linha[0]["plano_id"] is None


def test_linha_do_tempo_traz_wfa_e_plano_quando_existem(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid)
    _wfa_no_banco(10, 1)
    plano.salvar(
        wfa_id=10, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})

    linha = variantes.linha_do_tempo(vid)

    assert linha[0]["wfa_id"] == 10
    assert linha[0]["plano_estado"] == "ativo"


def test_linha_do_tempo_nao_duplica_quando_wfa_tem_dois_planos_aposentados(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid)
    _wfa_no_banco(10, 1)
    kwargs = dict(
        wfa_id=10, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})
    plano.salvar(**kwargs)
    segundo_id = plano.salvar(**kwargs)  # aposenta o primeiro
    plano.aposentar(segundo_id)  # agora os dois estao aposentados

    linha = variantes.linha_do_tempo(vid)

    assert len(linha) == 1
    assert linha[0]["plano_id"] == segundo_id
    assert linha[0]["plano_estado"] == "aposentado"


def test_linha_do_tempo_so_traz_minerações_desta_variante(banco):
    vid_a = variantes.criar("conservadora", "rompimento_canal")
    vid_b = variantes.criar("agressiva", "rompimento_canal")
    _mineracao_no_banco(1, vid_a)
    _mineracao_no_banco(2, vid_b)

    linha = variantes.linha_do_tempo(vid_a)

    assert [l["run_id"] for l in linha] == [1]
