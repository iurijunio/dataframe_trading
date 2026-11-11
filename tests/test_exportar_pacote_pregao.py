"""Exportar sem dia explícito: o plano é validado só no pregão, não no dia provisório do calendário."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import exportar_pacote as ex  # noqa: E402
from core import plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402

SABADO = date(2026, 11, 14)
SEXTA = datetime(2026, 11, 13, 10, 0)  # um plano gravado aqui vale na segunda, 16/11
SABADO_UTC = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def git_limpo(monkeypatch):
    saida = subprocess.CompletedProcess([], 0, stdout="abc123\n", stderr="")
    monkeypatch.setattr(ex, "rodar_git", lambda args: saida if args[0] != "status" else
                        subprocess.CompletedProcess(args, 0, stdout="", stderr=""))


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _congela(monkeypatch, agora_utc: datetime, hoje_local: date) -> None:
    monkeypatch.setattr(ex, "agora_utc", lambda: agora_utc)
    monkeypatch.setattr(ex, "hoje_local", lambda: hoje_local)


def _nova_variante(n: int, symbol: str) -> int:
    vid = variantes.criar(f"v{n}", "rompimento_canal")
    with db.connect_write() as con:
        con.execute("INSERT INTO mining_runs (run_id, symbol, strategy, created_at, n_combinacoes, "
                    "status, variante_id) VALUES (?,?,?,?,?,?,?)",
                    [n, symbol, "rompimento_canal", "2026-01-01", 10, "concluida", vid])
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) VALUES (?,?,?,?)",
                    [n, n, symbol, "rompimento_canal"])
    return vid


def _grava_plano(n: int, symbol: str, agora: datetime) -> int:
    return plano.salvar(
        wfa_id=n, run_id=n, symbol=symbol, strategy="rompimento_canal", nome="p",
        params={"periodo": 20, "stop_pontos": 100}, profile={"timeframe": "M15", "fechamento": "17:30"},
        capital=100_000.0, contratos=2, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="t", margem=None, uso_margem_pct=50.0,
        camada4_travada=True, disjuntor={}, expectativa={}, reotimizacao={},
        definicoes={}, regua={}, agora=agora)


def _portfolio(vid: int) -> int:
    pf = P.criar("mesa")
    P.definir_capital(pf, 50_000.0)
    P.adicionar_variante(pf, vid)
    return pf


def _estraga_hash(plano_id: int) -> None:
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET codigo_hash = 'antigo' WHERE plano_id = ?", [plano_id])


def test_sabado_plano_velho_com_hash_ruim_nao_barra_o_plano_novo_de_segunda(banco, monkeypatch):
    _congela(monkeypatch, SABADO_UTC, SABADO)
    vid = _nova_variante(1, "WIN$N")
    velho = _grava_plano(1, "WIN$N", datetime(2026, 1, 1))
    _estraga_hash(velho)
    novo = _grava_plano(1, "WIN$N", SEXTA)

    pacote = ex.montar_pacote(_portfolio(vid))

    assert pacote.session_date == date(2026, 11, 16)
    assert pacote.variants[0].plan_id == novo


def test_sabado_variante_nova_com_primeiro_plano_na_segunda_e_exportada(banco, monkeypatch):
    _congela(monkeypatch, SABADO_UTC, SABADO)
    vid = _nova_variante(1, "WIN$N")
    primeiro = _grava_plano(1, "WIN$N", SEXTA)

    pacote = ex.montar_pacote(_portfolio(vid))

    assert pacote.session_date == date(2026, 11, 16)
    assert pacote.variants[0].plan_id == primeiro


def test_cme_terca_19h_de_ny_valida_o_plano_de_quarta(banco, monkeypatch):
    # 00:00 UTC de quarta = 19:00 de terça em NY: o pregão é o de quarta, 11/11
    _congela(monkeypatch, datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc), date(2026, 11, 10))
    vid = _nova_variante(1, "MES")
    velho = _grava_plano(1, "MES", datetime(2026, 1, 1))
    _estraga_hash(velho)
    novo = _grava_plano(1, "MES", datetime(2026, 11, 10, 10, 0))  # vale em quarta

    pacote = ex.montar_pacote(_portfolio(vid))

    assert pacote.session_date == date(2026, 11, 11)
    assert pacote.variants[0].plan_id == novo


def test_ativo_que_muda_no_pregao_e_recusado(banco, monkeypatch):
    _congela(monkeypatch, SABADO_UTC, SABADO)
    vid = _nova_variante(1, "WIN$N")
    _grava_plano(1, "WIN$N", datetime(2026, 1, 1))
    _grava_plano(1, "MES", SEXTA)  # na segunda a variante passa a operar o MES

    with pytest.raises(ex.ExportacaoRecusada, match="ativo muda de WIN.N para MES"):
        ex.montar_pacote(_portfolio(vid))
