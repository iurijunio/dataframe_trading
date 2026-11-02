"""Listas salvas de um ativo só: Mineração, Walk-Forward e Candidata.

Uma mineração do MES na lista do WIN abriria faixas e custos de outra escala;
um walk-forward do MES na Candidata do WIN mediria o dinheiro na moeda errada.
O ativo de um walk-forward é o da mineração dele (`mining_runs.symbol`).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
from dash import no_update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import optimizer, wfa_store  # noqa: E402
from core.wfa_runner import VARREDURA  # noqa: E402
from ui import callbacks as CB  # noqa: E402
from ui.app import build  # noqa: E402

ATIVOS = ("WIN$N", "MES")


def _mineracao(run_id, symbol, strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, nome) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, datetime(2026, 10, 1, 10, run_id), 10,
             "concluida", f"m{run_id}"])


def _wfa(wfa_id, run_id, strategy="rompimento_canal", symbol="WIN$N"):
    """`symbol` é o da própria linha: só vale quando a mineração sumiu."""
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy, "
            "created_at, nome, is_meses, oos_meses, inteligencia, holdout, "
            "wfe_global, consistencia, oos_lucro, veredito) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [wfa_id, run_id, symbol, strategy, datetime(2026, 10, 2, 10, wfa_id),
             f"w{wfa_id}", 12, 6, "ulcer", False, 0.5, 60.0, 100.0, "boa"])


@pytest.fixture
def base(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
    _mineracao(1, "WIN$N")
    _mineracao(2, "MES")
    _mineracao(3, "MES", strategy="setup_cruzamento")
    _wfa(10, 1)
    _wfa(11, 2)
    _wfa(12, 3, strategy="setup_cruzamento")


# ------------------------------------------------------------------- core
def test_listar_salvas_filtra_pelo_ativo(base):
    assert [r["run_id"] for r in optimizer.listar_salvas(
        "rompimento_canal", simbolo="WIN$N")] == [1]
    assert [r["run_id"] for r in optimizer.listar_salvas(
        "rompimento_canal", simbolo="MES")] == [2]
    assert [r["run_id"] for r in optimizer.listar_salvas(simbolo="MES")] == [3, 2]
    # sem ativo, como antes
    assert [r["run_id"] for r in optimizer.listar_salvas("rompimento_canal")] == [2, 1]
    assert optimizer.simbolo_salva(2) == "MES"
    assert optimizer.simbolo_salva(99) is None


def test_wfa_listar_pelo_ativo_da_mineracao(base):
    """A linha do WFA 11 diz WIN$N, mas a mineração dele é do MES: vale a
    mineração."""
    ids = lambda **k: [w["wfa_id"] for w in wfa_store.listar(**k)]  # noqa: E731
    assert ids(strategy="rompimento_canal", symbol="WIN$N") == [10]
    assert ids(strategy="rompimento_canal", symbol="MES") == [11]
    assert ids(symbol="MES") == [12, 11]
    assert ids(strategy="rompimento_canal") == [11, 10]
    assert wfa_store.listar(symbol="MES")[0]["symbol"] == "MES"
    assert wfa_store.simbolo(11) == "MES"
    assert wfa_store.estrategias("MES") == ["rompimento_canal", "setup_cruzamento"]
    assert wfa_store.estrategias("WIN$N") == ["rompimento_canal"]
    assert wfa_store.estrategias() == ["rompimento_canal", "setup_cruzamento"]


def test_wfa_de_mineracao_excluida_fica_no_ativo_da_propria_linha(base):
    _wfa(13, 77, symbol="MES")             # a mineração 77 não existe
    assert 13 in [w["wfa_id"] for w in wfa_store.listar(symbol="MES")]
    assert 13 not in [w["wfa_id"] for w in wfa_store.listar(symbol="WIN$N")]
    assert wfa_store.simbolo(13) == "MES"


# -------------------------------------------------------------- callbacks
@pytest.fixture
def fns(base):
    with db.connect_write() as con:
        for s in ATIVOS:
            con.execute("INSERT INTO instruments (symbol, description) "
                        "VALUES (?, 'teste')", [s])
            for i in range(3):
                con.execute(
                    "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES (?, TIMESTAMP '2026-01-05 09:00:00' "
                    f"+ INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)", [s])
    app = build()
    saida = {}
    for v in app.callback_map.values():
        if "callback" not in v:            # os do navegador (clientside)
            continue
        f = getattr(v["callback"], "__wrapped__", v["callback"])
        saida[f.__name__] = f
    return saida


@pytest.fixture
def sem_varredura(monkeypatch):
    monkeypatch.setattr(VARREDURA, "estado", {**VARREDURA.estado,
                                              "run_id": None, "simbolo": None})


def _valores(opts):
    return [o["value"] for o in opts]


def test_mineracao_lista_so_o_ativo_do_menu(fns, monkeypatch):
    monkeypatch.setattr(CB.registry, "nome_atual", lambda: "rompimento_canal")
    f = fns["listar_salvas"]
    assert _valores(f(0, 0, "mineracao", "rompimento_canal", "WIN$N")) == [1]
    assert _valores(f(0, 0, "mineracao", "rompimento_canal", "MES")) == [2]


def test_wfa_ativo_ao_entrar_vem_do_menu(fns, sem_varredura):
    f = fns["wfa_ativo_ao_entrar"]
    opts, valor = f("wfa", "MES", None, None)
    assert set(_valores(opts)) == set(ATIVOS)
    assert valor == "MES"
    # já está nele: não reescreve (o Dash refaria as listas à toa)
    assert f("wfa", "MES", None, "MES")[1] is no_update
    # fora do modo, nada
    assert f("backtest", "MES", None, None) == (no_update, no_update)


def test_wfa_ativo_segue_a_varredura_na_memoria(fns, monkeypatch):
    """Depois de um F5 a lista prefere a mineração na memória: o seletor
    abre no ativo DELA, em vez de escondê-la atrás do ativo do menu."""
    monkeypatch.setattr(VARREDURA, "estado", {**VARREDURA.estado,
                                              "run_id": 2, "simbolo": "MES"})
    f = fns["wfa_ativo_ao_entrar"]
    assert f("wfa", "WIN$N", None, None)[1] == "MES"        # F5: nada aberto
    assert f("wfa", "WIN$N", 2, None)[1] == "MES"           # aberta = memória
    # outra mineração só escolhida (sem varredura dela): vale o menu
    assert f("wfa", "WIN$N", 1, None)[1] == "WIN$N"


def test_wfa_listas_filtram_pelo_ativo(fns, sem_varredura, monkeypatch):
    opts, valor = fns["wfa_mineracoes"]("rompimento_canal", "MES", None)
    assert (_valores(opts), valor) == ([2], 2)
    opts, valor = fns["wfa_mineracoes"]("rompimento_canal", "WIN$N", 2)
    assert (_valores(opts), valor) == ([1], 1)
    assert fns["wfa_mineracoes"]("rompimento_canal", None, None) == ([], None)

    monkeypatch.setattr(CB, "ctx", type("C", (), {"triggered_id": "wfa-ativo"}))
    opts, _aviso, _rot = fns["wfa_guardar"](0, None, "rompimento_canal", None,
                                            "MES", "")
    assert _valores(opts) == [11]
    opts, *_ = fns["wfa_guardar"](0, None, "rompimento_canal", None,
                                  "WIN$N", "")
    assert _valores(opts) == [10]


def test_cand_ativo_ao_entrar(fns):
    f = fns["cand_ativo_ao_entrar"]
    # nada aberto: o do menu
    opts, valor = f("candidata", "WIN$N", None, None, None)
    assert set(_valores(opts)) == set(ATIVOS) and valor == "WIN$N"
    # walk-forward aberto aqui é do MES: o seletor vai para o MES
    assert f("candidata", "WIN$N", 11, None, None)[1] == "MES"
    # sem nenhum aqui, herda o aberto na aba Walk-Forward
    assert f("candidata", "WIN$N", None, 12, None)[1] == "MES"
    assert f("candidata", "WIN$N", 11, None, "MES")[1] is no_update
    assert f("wfa", "WIN$N", None, None, None) == (no_update, no_update)


def test_cand_listas_filtram_pelo_ativo(fns):
    opts, valor = fns["cand_estrategias"]("candidata", None, "WIN$N", None, None)
    assert (_valores(opts), valor) == (["rompimento_canal"], "rompimento_canal")
    opts, valor = fns["cand_estrategias"]("candidata", None, "MES",
                                          None, "setup_cruzamento")
    assert _valores(opts) == ["rompimento_canal", "setup_cruzamento"]
    assert valor == "setup_cruzamento"

    # sem nada aberto, nada escolhido (None == None: não reescreve)
    opts, valor = fns["cand_opcoes"]("rompimento_canal", None, "MES", None, None)
    assert (_valores(opts), valor) == ([11], no_update)
    # o aberto na aba Walk-Forward continua herdado quando é deste ativo
    opts, valor = fns["cand_opcoes"]("rompimento_canal", None, "MES", None, 11)
    assert valor == 11
    # e o que é de outro ativo não entra
    opts, valor = fns["cand_opcoes"]("rompimento_canal", None, "WIN$N", 11, None)
    assert (_valores(opts), valor) == ([10], None)
