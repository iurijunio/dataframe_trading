"""Portfólio na moeda do ativo: recusa de moedas misturadas, risco com a
escala do ativo, capital digitado no formato brasileiro e telas em US$."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import variantes  # noqa: E402

MSG = ("O portfólio mistura R$ e US$: variantes de moedas diferentes não "
       "podem ficar no mesmo portfólio.")


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _plano(run_id, variante_id, wfa_id, symbol):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, "rompimento_canal", "2026-01-01", 10,
             "concluida", variante_id])
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, "rompimento_canal"])
    plano.salvar(
        wfa_id=wfa_id, run_id=run_id, symbol=symbol, strategy="rompimento_canal",
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})


def _variante(nome, wfa_id, symbol):
    vid = variantes.criar(nome, "rompimento_canal")
    _plano(wfa_id, vid, wfa_id, symbol)
    return vid


def _trades(wfa_id, n=30):
    base = datetime(2026, 1, 2, 10, 0)
    with db.connect_write() as con:
        for i in range(n):
            ent = base + timedelta(days=i)
            liq = float((i % 5) - 2) * 10 or -5.0
            con.execute(
                "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, mae, "
                "contratos, liquido, custo) VALUES (?,?,?,?,?,?,?,?)",
                [wfa_id, i, ent, ent + timedelta(minutes=30), 100, 1, liq, 1.0])


# ------------------------------------------------------------- ao adicionar
def test_win_e_mes_no_mesmo_portfolio_recusa_e_nao_grava(banco):
    pid = P.criar("p")
    win = _variante("win", 10, "WIN$N")
    mes = _variante("mes", 11, "MES")
    P.adicionar_variante(pid, win)
    with pytest.raises(P.MoedaMista) as e:
        P.adicionar_variante(pid, mes)
    assert str(e.value) == MSG
    assert [m["variante_id"] for m in P.membros(pid)] == [win]


def test_moeda_mista_nao_e_value_error():
    assert not issubclass(P.MoedaMista, ValueError)


def test_mes_e_mnq_aceita_e_moeda_e_usd(banco):
    pid = P.criar("p")
    P.adicionar_variante(pid, _variante("mes", 10, "MES"))
    P.adicionar_variante(pid, _variante("mnq", 11, "MNQ"))
    assert len(P.membros(pid)) == 2
    assert P.moeda(pid) == "USD"


def test_moeda_win_e_brl_e_vazio_e_none(banco):
    pid = P.criar("p")
    assert P.moeda(pid) is None
    P.adicionar_variante(pid, _variante("win", 10, "WIN$N"))
    assert P.moeda(pid) == "BRL"


def test_membro_sem_plano_nao_bloqueia(banco):
    pid = P.criar("p")
    P.adicionar_variante(pid, _variante("mes", 10, "MES"))
    sem = variantes.criar("sem plano", "rompimento_canal")
    P.adicionar_variante(pid, sem)
    assert len(P.membros(pid)) == 2
    assert P.moeda(pid) == "USD"
    # e o contrário: o sem plano entra antes, e o WIN entra depois
    pid2 = P.criar("p2")
    P.adicionar_variante(pid2, sem)
    P.adicionar_variante(pid2, _variante("win", 11, "WIN$N"))
    assert P.moeda(pid2) == "BRL"


def test_membros_traz_o_symbol(banco):
    pid = P.criar("p")
    P.adicionar_variante(pid, _variante("mes", 10, "MES"))
    P.adicionar_variante(pid, variantes.criar("sem", "rompimento_canal"))
    por = {m["nome"]: m for m in P.membros(pid)}
    assert por["mes"]["symbol"] == "MES"
    assert por["sem"]["symbol"] is None


def test_adicionar_variante_win_continua_rapido(banco):
    """Sem leitura aberta dentro da escrita: no DuckDB isso trava ~15 s."""
    pid = P.criar("p")
    P.adicionar_variante(pid, _variante("a", 10, "WIN$N"))
    b = _variante("b", 11, "WIN$N")
    t0 = time.perf_counter()
    P.adicionar_variante(pid, b)
    assert time.perf_counter() - t0 < 2.0
    assert len(P.membros(pid)) == 2


# ------------------------------------- plano ativo muda de ativo depois
@pytest.fixture
def misto(banco):
    """`a` (WIN) e `b` entram com plano WIN; depois o plano ativo de `b` vira
    MES (uma mineração nova do mesmo nome)."""
    pid = P.criar("p")
    P.definir_capital(pid, 50_000.0)
    a = _variante("a", 10, "WIN$N")
    b = _variante("b", 11, "WIN$N")
    P.adicionar_variante(pid, a)
    P.adicionar_variante(pid, b)
    _trades(10)
    _trades(11)
    _plano(20, b, 20, "MES")
    _trades(20)
    return pid


def test_moeda_de_portfolio_misto_levanta(misto):
    with pytest.raises(P.MoedaMista):
        P.moeda(misto)


@pytest.mark.parametrize("chamada", [
    lambda pid: P.correlacao(pid),
    lambda pid: P.curvas(pid),
    lambda pid: P.resumo(pid),
    lambda pid: P.resumo_membros(pid),
    lambda pid: P.simulacao_capital(pid),
    lambda pid: P.simular_crescimento(pid, 10_000.0, 1.0, 50, n_simulacoes=20),
], ids=["correlacao", "curvas", "resumo", "resumo_membros",
        "simulacao_capital", "simular_crescimento"])
def test_contas_de_portfolio_misto_levantam(misto, chamada):
    with pytest.raises(P.MoedaMista) as e:
        chamada(misto)
    assert str(e.value) == MSG


# -------------------------------------------------------------------- risco
def test_risco_usa_a_escala_do_ativo(banco):
    with db.connect_write() as con:
        db.upsert_instrument(con, db.load_instrument_yaml("MES"))
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
                    "VALUES (30, 30, 'MES', 'rompimento_canal')")
        con.execute(
            "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, mae, "
            "contratos, liquido) VALUES (30, 0, ?, ?, 1000, 1, -10.0)",
            [datetime(2026, 1, 2, 10), datetime(2026, 1, 2, 11)])
    [t] = P._trades_para_risco(30)
    assert t["mae_reais"] == pytest.approx(50.0)


def test_risco_sem_instrumento_continua_um_para_um(banco):
    with db.connect_write() as con:
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
                    "VALUES (31, 31, 'MES', 'rompimento_canal')")
        con.execute(
            "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, mae, "
            "contratos, liquido) VALUES (31, 0, ?, ?, 1000, 2, -10.0)",
            [datetime(2026, 1, 2, 10), datetime(2026, 1, 2, 11)])
    [t] = P._trades_para_risco(31)
    assert t["mae_reais"] == pytest.approx(2000.0)


# ----------------------------------------------------------- capital digitado
@pytest.mark.parametrize("texto, valor", [
    ("10.000", 10000.0),
    ("R$ 10.000", 10000.0),
    ("US$ 10000", 10000.0),
    ("US$ 10.000,00", 10000.0),
    ("1.234.567,8", 1234567.8),
    ("2500,50", 2500.5),
    ("200000", 200000.0),
    ("200.000,50", 200000.5),
    ("0.500", 0.5),
    ("1.500", 1500.0),
])
def test_parse_capital_formato_brasileiro(texto, valor):
    from ui import callbacks_portfolio as CP
    assert CP._parse_capital(texto) == valor


@pytest.mark.parametrize("texto", [None, "", "   ", "abc", "R$", "1,2,3",
                                   "10.00.0"])
def test_parse_capital_invalido_continua_none(texto):
    from ui import callbacks_portfolio as CP
    assert CP._parse_capital(texto) is None


def test_parse_capital_grupo_inicial_com_zero_nao_e_milhar():
    from ui import callbacks_portfolio as CP
    assert CP._parse_capital("012.345") != 12345.0


# ----------------------------------------------------------------- callbacks
def _callbacks(monkeypatch):
    """As funções dos callbacks de portfólio, registradas num app à parte."""
    import dash
    from ui import callbacks_portfolio as CP
    app = dash.Dash(__name__)
    CP.register(app)
    fns = {}
    for cb in app.callback_map.values():
        f = cb["callback"]
        fns[f.__name__] = getattr(f, "__wrapped__", f)
    return CP, fns


def _ctx(monkeypatch, CP, gatilho, valor=1):
    monkeypatch.setattr(CP, "ctx", SimpleNamespace(
        triggered_id=gatilho, triggered=[{"value": valor}]))


def _texto(componente) -> str:
    import json
    return json.dumps(componente.to_plotly_json() if hasattr(
        componente, "to_plotly_json") else componente, default=str,
        ensure_ascii=False)


def test_abrir_detalhe_com_adicao_recusada_avisa_e_desenha_sem_o_membro(
        banco, monkeypatch):
    pid = P.criar("p")
    win = _variante("win", 10, "WIN$N")
    mes = _variante("mes", 11, "MES")
    P.adicionar_variante(pid, win)
    CP, fns = _callbacks(monkeypatch)
    _ctx(monkeypatch, CP, "pf-btn-add")
    saida = fns["abrir_detalhe"]([], 1, [], 0, mes, "10000", pid)
    avisos, membros = saida[10], saida[7]
    assert MSG in _texto(avisos)
    assert "mes ·" not in _texto(membros) and "win ·" in _texto(membros)
    assert [m["variante_id"] for m in P.membros(pid)] == [win]
    # placeholders na moeda do portfólio (WIN)
    assert saida[12] == "capital do portfólio (R$)"
    assert saida[13] == "capital inicial (R$)"


def test_abrir_detalhe_usd_usa_us_nos_placeholders(banco, monkeypatch):
    pid = P.criar("p")
    P.adicionar_variante(pid, _variante("mes", 10, "MES"))
    CP, fns = _callbacks(monkeypatch)
    _ctx(monkeypatch, CP, {"type": "pf-cartao", "portfolio_id": pid})
    saida = fns["abrir_detalhe"]([1], 0, [], 0, None, "10000", pid)
    assert saida[12] == "capital do portfólio (US$)"
    assert saida[13] == "capital inicial (US$)"


def test_abrir_detalhe_sem_portfolio_nao_mexe_nos_placeholders(banco, monkeypatch):
    from dash import no_update
    CP, fns = _callbacks(monkeypatch)
    _ctx(monkeypatch, CP, "pf-btn-add")
    saida = fns["abrir_detalhe"]([], 1, [], 0, None, "10000", None)
    assert saida[0] == {"display": "none"}
    assert saida[12] is no_update and saida[13] is no_update


def test_abrir_detalhe_de_portfolio_misto_avisa(misto, monkeypatch):
    CP, fns = _callbacks(monkeypatch)
    _ctx(monkeypatch, CP, {"type": "pf-cartao", "portfolio_id": misto})
    saida = fns["abrir_detalhe"]([1], 0, [], 0, None, "10000", misto)
    assert saida[0] == {"display": "block"}
    assert MSG in _texto(saida[10])


def test_simular_crescimento_misto_mostra_a_moeda(misto, monkeypatch):
    CP, fns = _callbacks(monkeypatch)
    _ctx(monkeypatch, CP, "pf-cresc-btn")
    fig, resumo = fns["simular_crescimento"](1, "10000", "1", "50", misto)
    texto = fig.to_json()
    assert "R$ e US$" in texto
    assert "números positivos" not in texto
    assert resumo is None


# --------------------------------------------------------------------- tela
def test_renders_do_painel_em_usd():
    from ui.components import portfolio_panel as PP
    res = {"capital_inicial": 10_000.0, "lucro_liquido": 1234.5,
           "max_drawdown": -300.0, "max_drawdown_pct_capital": 3.0,
           "fator_recuperacao": 4.1, "profit_factor": 1.5, "win_rate": 55.0,
           "sharpe": 1.2, "trades": 40}
    assert "US$ 1.234,50" in _texto(PP.tabela_comparativa(
        [("a", res, False)], moeda="USD"))
    assert "R$" not in _texto(PP.tabela_comparativa(
        [("a", res, False)], moeda="USD"))
    assert "US$ 12,00" in _texto(PP.linha_membro(
        1, "a", "e", False, {"retorno": 12.0, "trades": 3}, moeda="USD"))
    assert "-US$ 80,00" in _texto(PP.card_risco(
        {"p90": -80.0, "pior_dia": "2026-01-02"}, moeda="USD"))
    sim = {"kelly_pct": 10.0, "kelly_meio_pct": 5.0, "kelly_indefinido": False,
           "capital_atual": 1.0, "prob_ruina_meio_kelly_pct": 2.0,
           "risco_recomendado_pct": 3.0, "limiar_dd_pct": 40.0,
           "prob_max_pct": 10.0}
    card = _texto(PP.card_simulacao(sim, moeda="USD"))
    assert "US$ 100.000" in card and "R$" not in card
    cres = {"p10": [1.0, 2.0], "p50": [1.0, 3.0], "p90": [1.0, 4.0],
            "capital_final_mediana": 3.0, "prob_dobrar_pct": 1.0,
            "prob_zerar_pct": 0.0}
    fig = PP.figura_crescimento(cres, moeda="USD").to_json()
    assert "US$ %{y" in fig and "R$" not in fig
    assert '"tickprefix":"US$ "' in fig
    assert "US$ 3,00" in _texto(PP.resumo_crescimento(cres, moeda="USD"))
    series = {"a": {"capital_inicial": 10.0, "pontos": [
        {"ts": datetime(2026, 1, 2), "capital": 11.0}]}}
    comb = {"capital_inicial": 10.0, "pontos": [
        {"ts": datetime(2026, 1, 2), "capital": 11.0}]}
    fig = PP.figura_curva(series, comb, moeda="USD").to_json()
    assert "US$ %{y" in fig and "R$" not in fig
    assert '"tickprefix":"US$ "' in fig
