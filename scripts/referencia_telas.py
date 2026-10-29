"""Referência das telas do WIN: prova de que a moeda não mudou o que o WIN mostra.

    python scripts/referencia_telas.py gravar      (grava tests/dados/telas_win/*.json)
    python scripts/referencia_telas.py conferir    (exit 1 se alguma saída diferir)

A foto do motor (`scripts/foto_win.py`) só cobre as contas; esta cobre o que a
TELA escreve — o texto de cada componente, o JSON de cada figura e as dicas dos
portões. Para o WIN, tudo tem que continuar idêntico depois que as funções de
tela passarem a receber a moeda.

Só entradas sintéticas e determinísticas: dicionários de métricas montados à
mão, trades de uma semente fixa e, para o portfólio, um DuckDB temporário
montado como o `tests/conftest.py` monta o do teste. Nunca o banco real, que
muda todo dia. A tabela `ENTRADAS` no fim é a lista do que é coberto: cada
linha é (nome do arquivo, função que devolve um dicionário nome -> valor
serializável em JSON).
Quem ganhar um parâmetro de moeda entra aqui chamando a função como o WIN a
chama — a referência tem que continuar passando.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

PASTA = RAIZ / "tests" / "dados" / "telas_win"
SIMBOLO = "WIN$N"
CAPITAL = 10_000.0


# ---------------------------------------------------------------- entradas
def _dia(i: int) -> np.datetime64:
    """Pregão número `i` a partir de 02/01/2023, às 10:00 (só dias úteis)."""
    d = np.busday_offset(np.datetime64("2023-01-02"), i)
    return np.datetime64(str(d) + "T10:00:00", "s")


def _resumo(**troca) -> dict:
    """As métricas de uma curva, escritas à mão (mesmas dos testes da tabela)."""
    m = {"trades": 510, "lucro_liquido": 5474.0, "lucro_bruto": 5984.0,
         "custo_total": 510.0, "max_drawdown": 791.0, "max_drawdown_pct": 6.3,
         "max_drawdown_pct_capital": 7.9, "max_drawdown_rel_pct": 6.3,
         "profit_factor": 1.44, "win_rate": 23.3, "payoff": 4.73,
         "expectativa": 10.73, "fator_recuperacao": 6.92, "sharpe": 1.27,
         "sortino": 3.74, "max_perdas_consecutivas": 12, "trades_por_dia": 1.49,
         "pregoes_operados": 342, "capital_inicial": CAPITAL,
         "periodo": "01/03/2022 → 01/03/2026",
         "periodo_nota": "base inteira, holdout incluído"}
    m.update(troca)
    return m


def _backtest(n: int = 80, semente: int = 7):
    """Um BacktestResult de mentira, mas com a forma exata do que o motor
    devolve: o que importa aqui é a tela, não o motor."""
    from core.engine import kernel as K
    from core.engine.execution import BacktestResult, ExecutionProfile

    rng = np.random.default_rng(semente)
    entry_ts = np.array([_dia(i) for i in range(n)], dtype="datetime64[s]")
    dur = rng.integers(1, 40, n)
    exit_ts = entry_ts + dur.astype("timedelta64[m]")
    points = rng.normal(15, 120, n).round().astype(np.int64)
    side = rng.choice([1, -1], n).astype(np.int64)
    entry_px = (120_000 + rng.integers(-2000, 2000, n) // 5 * 5).astype(np.int64)
    mae = -np.abs(rng.normal(60, 40, n)).round().astype(np.int64)
    mfe = np.abs(rng.normal(90, 60, n)).round().astype(np.int64)
    reason = rng.choice([K.EXIT_STOP, K.EXIT_TARGET, K.EXIT_SIGNAL,
                         K.EXIT_CLOSE_TIME], n).astype(np.int64)
    trades = {
        "entry_i": np.arange(n, dtype=np.int64) * 100,
        "exit_i": np.arange(n, dtype=np.int64) * 100 + dur,
        "side": side, "entry_px": entry_px, "exit_px": entry_px + points * side,
        "reason": reason, "mae": mae, "mfe": mfe, "points": points,
        "stop_fim": entry_px - 150 * side, "alvo_fim": entry_px + 300 * side,
        "entry_ts": entry_ts, "exit_ts": exit_ts, "bars_held": dur.astype(np.int64),
    }
    perfil = ExecutionProfile(timeframe="M5", capital_inicial=CAPITAL,
                              corretagem_por_contrato=0.5,
                              emolumentos_por_contrato=0.25, contratos=2)
    return BacktestResult(
        trades=trades, n_trades=n, ambiguous_bars=12, bloqueios=3, n_bars=n * 100,
        sl_at_entry=np.full(n, 150, dtype=np.int64),
        tp_at_entry=np.full(n, 300, dtype=np.int64),
        profile=perfil, instrument={"point_value": 0.2, "tick_size": 5})


def _corrida():
    """O backtest sintético já medido: res, dinheiro, métricas, perfil."""
    from core import metrics
    res = _backtest()
    return res, metrics.monetize(res), metrics.compute(res)


def _passos():
    """A escadinha do walk-forward (4 janelas + a de hoje), sem rodar nada."""
    from core import wfa
    js = wfa.montar_janelas("2022-01-01", "2024-01-01", 6, 3)
    return [wfa.Passo(janela=j, escolhida=0 if not j.deploy else None,
                      params={"p": 1}) for j in js]


def _oos():
    """Trades fora da amostra: datas, líquido, custo, saída e step."""
    n = 60
    ts = np.array([_dia(i * 3) for i in range(n)], dtype="datetime64[s]")
    rng = np.random.default_rng(3)
    liq = rng.normal(12, 90, n).round(2)
    return {"ts": ts, "liq": liq, "custo": np.full(n, 1.5),
            "saida": ts + np.timedelta64(30, "m"),
            "steps": (np.arange(n) // 15 + 1).astype(int)}


def _trials(n: int = 40) -> list[dict]:
    """Linhas da tabela de mineração, no formato de `core/mineracao_stats`."""
    rng = np.random.default_rng(5)
    out = []
    for i in range(n):
        lucro = float(round(rng.normal(900, 700), 2))
        out.append({
            "n": i, "trial_id": i, "params": {"a": 5 + i % 8, "b": 20 + i // 8 * 5},
            "params_txt": f"a={5 + i % 8} b={20 + i // 8 * 5}", "lucro": lucro,
            "fr": float(round(rng.uniform(0.5, 4), 2)),
            "pf": float(round(rng.uniform(0.8, 2), 2)),
            "dd": float(round(rng.uniform(300, 2500), 2)),
            "trades": int(rng.integers(60, 600)),
            "consistencia": float(round(rng.uniform(30, 90), 1)), "folds": 5,
            "mediana_fold": float(round(rng.normal(150, 120), 2)),
            "score": float(round(rng.normal(1, 0.5), 3)),
            "robusto": float(round(rng.normal(1, 0.4), 3)), "filtro": "ok"})
    return out


def _trades_rapidos(n=150, semente=11, contratos=1):
    rng = np.random.default_rng(semente)
    dias = np.busday_offset(np.datetime64("2024-01-02"), np.arange(n))
    liquido = rng.normal(12.0, 8.0, n)
    return [{"exit_ts": str(d) + "T15:00:00", "liquido": float(v),
             "contratos": contratos} for d, v in zip(dias, liquido)]


def _leitura(dd=831.0, seguidas=15.0, topo=125.0, topo50=57.0, ordem=1395.0):
    boot = {"horizonte": 131, "bloco": 1, "dd_p95": dd,
            "perdas_seguidas_p95": seguidas, "submerso_p95": topo,
            "submerso_p50": topo50}
    return {"resumo": _resumo(), "boot": boot, "boot_12m": {},
            "ordenacao": {"dd_p95": ordem}, "pregoes": 1044,
            "perdas_seguidas_reais": 11}


def _tamanho():
    dim = {"n": 3, "por_risco": 3, "por_margem": None, "por_folga": None,
           "limite": "risco", "risco_pedido_pct": 1.0, "risco_efetivo_pct": 0.9,
           "perda_ref": 300.0, "margem": None, "uso_margem_pct": 50.0,
           "motivo": None}
    zero = {**dim, "n": 0, "risco_efetivo_pct": None,
            "motivo": "o capital não comporta nem 1 contrato"}
    ref = {"valor": 300.0, "de_onde": "a média dos 5% piores pregões",
           "cvar": -300.0, "quantos": 53, "fracao": 0.051, "pior_dia": -128.0,
           "dia_ruim": 240.0, "motivo": None}
    disj = {"nivel1": {"queda": 1200.0, "perdas_seguidas": 15,
                       "lucro_no_prazo": -200.0, "faixa_por_pregao": [-10.0],
                       "alarme_pct": 20.0, "acao": "reduzir para 1 contrato"},
            "nivel2": {"queda": 1800.0, "pct": 18.0, "alarme_pct": 5.0,
                       "risco_de_desligar_pct": 5.0,
                       "acao": "desligar e reotimizar"},
            "recorte": "curva inteira", "dias_sem_topo": 125,
            "limite_dia_reais": 400.0, "limite_dia_trades": 6,
            "horizonte": 131, "motivo": None}
    return dim, zero, ref, disj


def _grade_plato(fr, deploy_idx):
    valores = list(range(40, 40 + len(fr)))
    trials = [{"params": {"p": v}, "lucro": f * 100.0, "dd": 100.0}
              for v, f in zip(valores, fr)]
    return trials, {"p": valores}, {"p": float(valores[deploy_idx])}


# ------------------------------------------------------------- componentes
def _figs(*figuras) -> list[str]:
    return [f.to_json() for f in figuras]


def _backtest_telas() -> dict:
    from ui.components import detalhes_cards as DC
    from ui.components import robustez_cards as RC
    from ui.components import stats_cards as SC
    from core import detalhes, porteira, robustez
    from core import ativo as ativo_mod
    from core.engine import kernel as K
    from ui.components import analytics_charts as AC
    from core import analytics

    res, din, m = _corrida()
    f = ativo_mod.ficha(SIMBOLO)
    liq, t = din["liquido"], res.trades
    ex = ativo_mod.trades_para_exibir(t, f)
    # as mesmas contas que ui/callbacks.py::_detalhes e ::_robustez montam
    tp_ent = ativo_mod.pontos_para_exibir(res.tp_at_entry, f)
    sl_ent = ativo_mod.pontos_para_exibir(res.sl_at_entry, f)
    folga = int(res.profile.slippage_ticks * int(res.instrument.get("tick_size", 1)))
    diag = analytics.calor_mae_mfe(ex["mae"], ex["mfe"], liq)
    dias = int((t["exit_ts"][-1] - t["entry_ts"][0]).astype("timedelta64[D]")
               .astype(int))
    pregoes = 80
    custo_ponta = (res.profile.corretagem_por_contrato
                   + res.profile.emolumentos_por_contrato)
    return {
        "stats_cards.render": str(SC.render(m)),
        "stats_cards.cartoes": {k: str(v) for k, v in SC.cartoes(m).items()},
        "stats_cards.itens": SC.itens(m),
        "stats_cards.cartoes_dica": {
            k: str(v) for k, v in SC.cartoes(m, {"sharpe": "texto novo"}).items()},
        "detalhes_cards.render": str(DC.render(
            m, detalhes.sequencias(liq),
            detalhes.eficiencia(ex["mae"], ex["mfe"], ex["points"], tp_ent,
                                ex["reason"], K.EXIT_TARGET),
            detalhes.risco_trade(liq, ex["points"], sl_ent, ex["reason"],
                                 K.EXIT_STOP, folga),
            detalhes.ritmo(t["entry_ts"], liq, int(ex["bars_held"].sum()),
                           res.n_bars, pregoes),
            AC.barras(detalhes.resultado_por_volume(t["entry_ts"], liq),
                      "Resultado por nº de trades no pregão"), casas=0)),
        "robustez_cards.render": str(RC.render(
            robustez.monte_carlo(liq, CAPITAL), robustez.significancia(liq),
            robustez.teste_runs(liq), robustez.correlacao_lr(liq, CAPITAL),
            robustez.concentracao(liq), robustez.ulcer_mar(liq, CAPITAL, dias),
            robustez.meses_positivos(t["entry_ts"], liq),
            robustez.custo_que_zera(float(din["bruto"].sum()), din["contratos"],
                                    custo_ponta),
            robustez.drawdowns(t["entry_ts"], liq, CAPITAL), porteira.sqn(liq))),
        "results_grid.rows": __import__(
            "ui.components.results_grid", fromlist=["rows"]).rows(t, din, f),
    }


def _analytics_telas() -> dict:
    from core import analytics
    from core import ativo as ativo_mod
    from core.engine import kernel as K
    from ui.components import analytics_charts as AC
    from ui.components import results_grid

    res, din, _m = _corrida()
    f = ativo_mod.ficha(SIMBOLO)
    liq, t = din["liquido"], res.trades
    ex = ativo_mod.trades_para_exibir(t, f)
    diag = analytics.calor_mae_mfe(ex["mae"], ex["mfe"], liq)
    return {
        "ganho_perda_hora": AC.ganho_perda(
            analytics.por_hora(t["entry_ts"], liq, f), "Lucro × prejuízo por hora").to_json(),
        "ganho_perda_dia": AC.ganho_perda(
            analytics.por_dia_semana(t["entry_ts"], liq), "Lucro × prejuízo por dia").to_json(),
        "ganho_perda_mes": AC.ganho_perda(
            analytics.por_mes(t["entry_ts"], liq), "Lucro × prejuízo por mês").to_json(),
        "calendario": AC.calendario(
            analytics.calendario_mensal(t["entry_ts"], liq)).to_json(),
        "mae_mfe": AC.mae_mfe(diag, 150, 300).to_json(),
        "barras_duracao": AC.barras(
            analytics.por_duracao(ex["bars_held"], liq, 5), "Lucro por tempo").to_json(),
        "barras_motivo": AC.barras(
            analytics.por_motivo(ex["reason"], liq, K.EXIT_LABELS),
            "Lucro por motivo de saída", com_expectativa=False).to_json(),
        "histograma": AC.histograma(analytics.distribuicao(liq)).to_json(),
        "sugestoes": analytics.sugestoes(diag, 150, 300),
        "colunas_grid": results_grid.COLUNAS,
    }


def _mineracao_telas() -> dict:
    from core import mineracao_stats as MS
    from core import analytics, porteira
    from ui.components import mine_charts as MC
    from ui.components import mine_porteira as MP
    from ui.components import mine_regiao as MR
    from ui.components import scatter

    trials = _trials()
    saida = {
        "mine_porteira.painel": str(MP.painel(porteira.avaliar(trials))),
        "mine_porteira.painel_truncada": str(MP.painel(porteira.avaliar(trials), 7)),
        "mine_regiao.cards": str(MR.cards(MS.resumo(trials))),
        "mine_regiao.cards_vazio": str(MR.cards({})),
        "scatter.figura": scatter.figura(trials, "a", "b", None, "robusto").to_json(),
        "scatter.figura_3d": scatter.figura(trials, "a", "b", "lucro", "lucro").to_json(),
        "scatter.figura_metrica_no_eixo": scatter.figura(
            trials, "a", "lucro", None, "robusto").to_json(),
    }
    for metrica, rotulo in (("lucro", "lucro"), ("fr", "fator de recuperação"),
                            ("dd", "drawdown")):
        valores = np.array([l[metrica] for l in trials], dtype=float)
        moeda = metrica in MS.DINHEIRO
        saida[f"mine_charts.histograma_{metrica}"] = MC.histograma(
            analytics.distribuicao(valores), rotulo, moeda).to_json()
        saida[f"mine_charts.curva_{metrica}"] = MC.curva(
            MS.curva(trials, metrica), rotulo, moeda).to_json()
    return saida


def _wfa_telas() -> dict:
    from core import candidata, wfa
    from core import ativo as ativo_mod
    from ui.components import wfa_panel as WP

    passos, o = _passos(), _oos()
    ts, liq, steps = o["ts"], o["liq"], o["steps"]
    ag = {"wfe_global": 0.9, "consistencia_lucro": 100.0}
    ver = candidata.veredito([
        candidata.portao("a", True, True, 1, "≥ 1", "dica a"),
        candidata.portao("b", False, False, 2, "≥ 3", "dica b")])
    trials, espaco, deploy = _grade_plato([5, 6, 8, 9, 10, 9, 8, 6, 5], 4)
    perfil = candidata.perfil_plato(trials, espaco, deploy)
    portoes = candidata.portoes_plato(perfil)
    mes = wfa.mensal(ts, liq, wfa.meses_oos(passos))
    fixas_dias = np.arange(np.datetime64("2022-07-01"), np.datetime64("2023-12-01"))
    fixas = {"dias": fixas_dias,
             "quantis": {p: np.full(len(fixas_dias), CAPITAL + p)
                         for p in (10, 25, 50, 75, 90)},
             "finais": np.array([10.0, 50.0, 500.0])}
    return {
        "curva": WP.curva(ts, liq, steps, passos, CAPITAL).to_json(),
        "curva_fixas_holdout": WP.curva(ts, liq, steps, passos, CAPITAL, fixas,
                                        holdout_de="2023-06-15 00:00:00").to_json(),
        "kpis": str(WP.kpis(passos, ts, liq, ag, CAPITAL, custo=o["custo"],
                            saida=o["saida"])),
        "selo": str(WP.selo(ver)),
        "selo_candidata": str(WP.selo(ver, titulo="a estratégia está pronta?")),
        "regiao_larga": str(WP.regiao_larga(perfil, portoes, run_id=1)),
        "fita": WP.fita(passos).to_json(),
        "cards_mensais": str(WP.cards_mensais(mes)),
        "mensal_fig": WP.mensal_fig(mes).to_json(),
        "linhas_trades": WP.linhas_trades(ts, liq, steps, CAPITAL,
                                          saida=o["saida"], custo=o["custo"],
                                          f=ativo_mod.ficha(SIMBOLO)),
    }


def _candidata_telas() -> dict:
    from core import candidata
    from ui.components import candidata_panel as CP

    leitura = _leitura()
    gate = {"pregoes_holdout": 42, "lucro_mes_holdout": 850.0,
            "lucro_mes_antes": 620.0}
    dim, zero, ref, disj = _tamanho()
    trials, espaco, deploy = _grade_plato([5] * 9, 4)
    tick = 1.0
    gates = candidata.portoes_rapidos(
        _trades_rapidos(), {"resumo": {"lucro_liquido": 1800.0},
                            "boot": {"dd_p95": 800.0, "perdas_seguidas_p95": 5.0,
                                     "submerso_p95": 20.0}, "boot_12m": {}},
        trials, espaco, deploy, corte="2024-06-01", tick_value=tick, capital=CAPITAL)
    return {
        "linhas": CP.linhas(leitura, CAPITAL),
        "linhas_oos": CP.linhas(leitura, CAPITAL, True, "2023-01-02", "2023-12-29", gate),
        "bloco_robustez": str(CP.bloco_robustez(leitura, CAPITAL)),
        "bloco_robustez_holdout": str(CP.bloco_robustez(
            leitura, CAPITAL, True, "2023-01-02", "2023-12-29", gate)),
        "linhas_tamanho": CP.linhas_tamanho(dim, ref, disj, CAPITAL),
        "linhas_tamanho_zero": CP.linhas_tamanho(zero, ref, disj, CAPITAL),
        "bloco_tamanho": str(CP.bloco_tamanho(dim, ref, disj, CAPITAL)),
        "portoes_rapidos": gates,
        "portao_custo_dica": candidata.portao_custo(1500.0, np.ones(510), tick)["dica"],
        "portao_custo": candidata.portao_custo(1500.0, np.ones(510), tick),
        "portao_custo_reprovado": candidata.portao_custo(1000.0, np.ones(510), tick),
        "portao_custo_sem_tick": candidata.portao_custo(1500.0, np.ones(510), None),
    }


def _ficha_telas() -> dict:
    from types import SimpleNamespace
    from ui.components import ficha as FI

    estrategia = SimpleNamespace(
        label="Rompimento de canal",
        params_schema={"periodo_canal": {"label": "Período do canal", "default": 20},
                       "folga_ticks": {"label": "Folga do rompimento (ticks)",
                                       "default": 1}})
    espaco = {"periodo_canal": [10, 20, 30, 40]}
    perfil = {"modo_posicao": "risco_fixo", "risco_por_trade": 200.0,
              "capital_inicial": 25_000.0, "corretagem_por_contrato": 0.5,
              "emolumentos_por_contrato": 0.25, "slippage_ticks": 1,
              "limite_ganho_contrato": 150.0, "limite_perda_contrato": 100.0}
    return {
        "ficha": str(FI.ficha(estrategia=estrategia,
                              params={"periodo_canal": 79, "folga_ticks": 9},
                              perfil=perfil, espaco=espaco,
                              geral={"ativo": "WIN$N", "mineração": "#1"})),
        "ficha_padrao": str(FI.ficha(estrategia=estrategia, params={},
                                     perfil={}, espaco={})),
    }


def _metricas_telas() -> dict:
    from core import metrics
    return {
        "format_panel": metrics.format_panel({
            **_resumo(), "barras_ambiguas": 1200, "barras_ambiguas_pct": 0.456,
            "saidas": {"stop": 300, "alvo": 210}}),
        "format_panel_vazio": metrics.format_panel({"trades": 0}),
        "format_panel_negativo": metrics.format_panel({
            **_resumo(lucro_liquido=-1234.5, expectativa=-2.5),
            "barras_ambiguas": 0, "barras_ambiguas_pct": 0.0, "saidas": {}}),
    }


# --------------------------------------------------------------- portfólio
def _montar_banco(destino: Path):
    """Um DuckDB temporário no formato do `tests/conftest.py`: caminho
    desviado antes de qualquer conexão, esquema criado, tudo dentro de `destino`.
    O banco real nunca é aberto. Quem chama devolve o `DB_PATH` original."""
    from core import db_manager as db
    db.DB_PATH = destino / "portfolio.duckdb"
    with db.connect() as con:
        db.init_schema(con)


def _portfolio_sintetico() -> tuple[int, int]:
    """Dois membros WIN com plano ativo e capital, trades de uma semente fixa.
    Devolve (portfolio_id, portfolio vazio)."""
    from datetime import datetime, timedelta
    from core import db_manager as db
    from core import plano, variantes
    from core import portfolio as P

    pid = P.criar("portfólio de referência")
    P.definir_capital(pid, 50_000.0)
    vazio = P.criar("sem membros")
    rng = np.random.default_rng(21)
    for wfa_id, nome in ((10, "alfa"), (11, "beta")):
        vid = variantes.criar(nome, "rompimento_canal")
        with db.connect_write() as con:
            con.execute(
                "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
                "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
                [wfa_id, SIMBOLO, "rompimento_canal", "2026-01-01", 10,
                 "concluida", vid])
            con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
                        "VALUES (?,?,?,?)", [wfa_id, wfa_id, SIMBOLO,
                                             "rompimento_canal"])
        plano.salvar(
            wfa_id=wfa_id, run_id=wfa_id, symbol=SIMBOLO,
            strategy="rompimento_canal", nome="teste", params={}, profile={},
            capital=20_000.0 + wfa_id, contratos=1, risco_pedido_pct=1.0,
            risco_efetivo_pct=0.9, perda_referencia=300.0, de_onde="teste",
            margem=None, uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
            expectativa={}, reotimizacao={}, definicoes={}, regua={})
        P.adicionar_variante(pid, vid)
        base = datetime(2026, 1, 2, 10, 0)
        with db.connect_write() as con:
            for n in range(70):
                ent = base + timedelta(days=n + wfa_id % 3, minutes=int(rng.integers(0, 60)))
                sai = ent + timedelta(minutes=int(rng.integers(5, 90)))
                liquido = float(round(rng.normal(25, 140), 2))
                con.execute(
                    "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, mae, "
                    "contratos, liquido, custo) VALUES (?,?,?,?,?,?,?,?)",
                    [wfa_id, n, ent, sai, int(abs(rng.normal(80, 40))),
                     1 + n % 2, liquido, 1.5])
    return pid, vazio


def _retorno(dados: dict | None) -> dict | None:
    """O resumo que `ui/callbacks_portfolio.py::_resumo_membro` monta."""
    if not dados or not dados["pontos"]:
        return None
    return {"retorno": dados["pontos"][-1]["capital"] - dados["capital_inicial"],
            "trades": len(dados["pontos"])}


def _portfolio_telas() -> dict:
    from core import db_manager as db
    original = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        try:
            return _portfolio_com_banco(Path(tmp))
        finally:
            db.DB_PATH = original


def _portfolio_com_banco(tmp: Path) -> dict:
    from core import portfolio as P
    from ui.components import portfolio_panel as PP

    _montar_banco(tmp)
    pid, vazio = _portfolio_sintetico()
    corr = P.correlacao(pid)
    curvas = P.curvas(pid)
    resumo = P.resumo(pid)
    membros = P.resumo_membros(pid)
    sim = P.simulacao_capital(pid)
    cres = P.simular_crescimento(pid, 50_000.0, 1.0, 200, n_simulacoes=300)
    ms = P.membros(pid)
    riscos = {m["nome"]: P._trades_para_risco(m["wfa_id"]) for m in ms}
    lig = [(n, {"capital_inicial": 20_000.0, **mm}, False)
           for n, mm in membros.items()]
    comparativo = PP.tabela_comparativa(
        [("portfólio", {"capital_inicial": 50_000.0, **resumo}, True)] + lig)
    telas = {
        "correlacao": corr, "curvas": curvas, "resumo": resumo,
        "resumo_membros": membros, "simulacao_capital": sim,
        "simular_crescimento": cres, "trades_para_risco": riscos,
        "vazio.correlacao": P.correlacao(vazio),
        "vazio.curvas": P.curvas(vazio), "vazio.resumo": P.resumo(vazio),
        "vazio.simulacao_capital": P.simulacao_capital(vazio),
        "painel": str(PP.painel()),
        "cartao_portfolio": str(PP.cartao_portfolio(pid, "portfólio", 2)),
        "linha_membro": [str(PP.linha_membro(
            m["variante_id"], m["nome"], m["estrategia"],
            m["sem_plano_ativo"], _retorno(curvas["series"].get(m["nome"])))) for m in ms],
        "tabela_comparativa": str(comparativo),
        "card_simulacao": str(PP.card_simulacao(sim)),
        "card_simulacao_vazio": str(PP.card_simulacao(None)),
        "card_risco": str(PP.card_risco(corr["risco_diario"])),
        "card_risco_vazio": str(PP.card_risco(None)),
        "heatmap": str(PP.heatmap(corr["variantes"], corr["matriz"])),
        "figura_curva_vazia": PP.figura_curva_vazia().to_json(),
        "figura_curva": PP.figura_curva(curvas["series"], curvas["combinada"]).to_json(),
        "figura_crescimento_vazia": PP.figura_crescimento_vazia().to_json(),
        "figura_crescimento": PP.figura_crescimento(cres).to_json(),
        "resumo_crescimento": str(PP.resumo_crescimento(cres)),
    }
    return telas


# ------------------------------------------------------------------ tabela
ENTRADAS = [
    ("backtest", _backtest_telas),
    ("analytics", _analytics_telas),
    ("mineracao", _mineracao_telas),
    ("wfa", _wfa_telas),
    ("candidata", _candidata_telas),
    ("ficha", _ficha_telas),
    ("metricas", _metricas_telas),
    ("portfolio", _portfolio_telas),
]


def _jsonavel(v):
    """Só para gravar: numpy, inf e datas viram texto estável."""
    return json.loads(json.dumps(v, ensure_ascii=False, default=_padrao,
                                 allow_nan=True))


def _padrao(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, (np.datetime64,)):
        return str(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def calcular() -> dict[str, dict]:
    """grupo -> {nome: valor}, tudo já em JSON."""
    out: dict[str, dict] = {}
    for grupo, fn in ENTRADAS:
        out[grupo] = _jsonavel(fn())
    return out


def _arquivo(grupo: str) -> Path:
    return PASTA / f"{grupo}.json"


def gravar() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    atual = calcular()
    for grupo, dados in atual.items():
        _arquivo(grupo).write_text(
            json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"gravado: {_arquivo(grupo).relative_to(RAIZ)} ({len(dados)} saídas)")


def _comparar(a, b, caminho: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        difs = []
        for k in sorted(set(a) | set(b)):
            sub = f"{caminho}/{k}" if caminho else str(k)
            if k not in a:
                difs.append(f"{sub}: ausente na referência")
            elif k not in b:
                difs.append(f"{sub}: ausente agora")
            else:
                difs += _comparar(a[k], b[k], sub)
        return difs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{caminho}: {len(a)} itens na referência, {len(b)} agora"]
        difs = []
        for i, (x, y) in enumerate(zip(a, b)):
            difs += _comparar(x, y, f"{caminho}[{i}]")
        return difs
    if a == b:
        return []
    ta, tb = str(a), str(b)
    # o primeiro ponto em que os textos divergem, com um pouco de contexto
    i = next((i for i, (x, y) in enumerate(zip(ta, tb)) if x != y),
             min(len(ta), len(tb)))
    return [f"{caminho}: difere perto de «{ta[max(0, i - 40):i + 60]}» "
            f"≠ «{tb[max(0, i - 40):i + 60]}»"]


def conferir() -> list[str]:
    """Diferenças entre o que as telas escrevem agora e o gravado; vazio = igual."""
    difs: list[str] = []
    agora = calcular()
    for grupo, dados in agora.items():
        arq = _arquivo(grupo)
        if not arq.exists():
            difs.append(f"{grupo}: sem referência gravada ({arq.name})")
            continue
        gravado = json.loads(arq.read_text(encoding="utf-8"))
        difs += _comparar(gravado, dados, grupo)
    return difs


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("gravar", "conferir"):
        print(__doc__)
        return 2
    if argv[1] == "gravar":
        gravar()
        return 0
    difs = conferir()
    if difs:
        print(f"{len(difs)} diferença(s) em relação à referência do WIN:")
        for d in difs:
            print("  " + d)
        return 1
    print("telas do WIN idênticas à referência.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
