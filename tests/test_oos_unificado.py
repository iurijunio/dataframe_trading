"""Testes da régua única: as métricas de trade medem igual em qualquer curva.

Antes, o Backtest calculava Sharpe, payoff e drawdown dentro de `compute`, e
o Walk-Forward refazia uma parte à mão sobre a curva fora da amostra — dois
cartões "drawdown" na plataforma, duas contas. Agora `metrics.resumo` recebe
arrays e serve às duas telas; o WFA só acrescenta o que é dele (WFE, janelas
positivas, lucro por mês).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import metrics, wfa  # noqa: E402
from ui.components import stats_cards as SC  # noqa: E402
from ui.components import wfa_panel as WP  # noqa: E402

CAP = 1_000.0


def _dia(d, h=10):
    return np.datetime64(f"2024-03-{d:02d}T{h:02d}:00", "s")


# ------------------------------------------------------- metrics.resumo
def test_resumo_com_a_resposta_feita_a_mao():
    liq = np.array([100.0, -50.0, 30.0])
    custo = np.array([2.0, 2.0, 2.0])
    saida = np.array([_dia(4), _dia(4, 15), _dia(5)])
    m = metrics.resumo(liq, custo, saida, CAP)

    assert m["trades"] == 3
    assert m["lucro_liquido"] == pytest.approx(80.0)
    assert m["custo_total"] == pytest.approx(6.0)
    assert m["lucro_bruto"] == pytest.approx(86.0)
    assert m["profit_factor"] == pytest.approx(130 / 50)
    assert m["win_rate"] == pytest.approx(200 / 3)
    assert m["payoff"] == pytest.approx(65 / 50)
    # 1.100 → 1.050: o único mergulho
    assert m["max_drawdown"] == pytest.approx(50.0)
    assert m["fator_recuperacao"] == pytest.approx(80 / 50)
    # dois trades saíram no mesmo pregão: são um ponto só da série diária
    assert m["pregoes_operados"] == 2
    assert m["trades_por_dia"] == pytest.approx(1.5)


def test_resumo_agrega_o_sharpe_pelo_dia_da_saida():
    """Um trade que entra num dia e sai no outro pertence ao dia em que o
    resultado se realiza. Agregar pela entrada mudaria o Sharpe."""
    liq = np.array([40.0, -10.0, 25.0])
    entradas = np.array([_dia(4), _dia(5), _dia(6)])
    saidas = np.array([_dia(5), _dia(5, 16), _dia(6)])   # os dois primeiros no dia 5

    pela_saida = metrics.resumo(liq, None, saidas, CAP)
    pela_entrada = metrics.resumo(liq, None, entradas, CAP)
    assert pela_saida["pregoes_operados"] == 2
    assert pela_entrada["pregoes_operados"] == 3
    assert pela_saida["sharpe"] != pytest.approx(pela_entrada["sharpe"])


def test_resumo_sem_custo_trata_como_zero_e_sem_trade_nao_quebra():
    m = metrics.resumo(np.array([10.0, -5.0]), None,
                       np.array([_dia(4), _dia(5)]), CAP)
    assert m["custo_total"] == 0.0 and m["lucro_bruto"] == pytest.approx(5.0)
    assert metrics.resumo(np.array([]), None, np.array([]), CAP) == {"trades": 0}


# ------------------------------------------------ wfa.trades_oos_campos
def _combo(params, valores_por_dia):
    ts = np.array([np.datetime64("2022-01-03T10:00", "s") + np.timedelta64(k, "D")
                   for k in range(len(valores_por_dia))])
    liq = np.array(valores_por_dia, dtype=float)
    return {"params": params, "entry_ts": ts,
            "exit_ts": ts + np.timedelta64(3, "h"),
            "liquido": liq, "custo": np.full(len(liq), 1.5)}


def test_campos_voltam_alinhados_com_o_trades_oos():
    """O i-ésimo custo tem que ser do mesmo trade que o i-ésimo líquido — se
    desalinhar, o cartão de bruto e o Sharpe ficam errados sem aviso."""
    dias = 1500
    combos = [_combo({"p": 1}, [10.0] * dias),
              _combo({"p": 2}, [(-5.0 if k % 3 else 20.0) for k in range(dias)])]
    js = wfa.montar_janelas("2022-01-01", "2026-01-01", 12, 6)
    passos = wfa.rodar(combos, js, 10_000.0, "sharpe")

    ts, liq, step = wfa.trades_oos(combos, passos)
    t = wfa.trades_oos_campos(combos, passos,
                              ("entry_ts", "exit_ts", "liquido", "custo"))

    assert np.array_equal(t["entry_ts"], ts)
    assert np.array_equal(t["liquido"], liq)
    assert np.array_equal(t["step"], step)
    assert np.all(t["exit_ts"] - t["entry_ts"] == np.timedelta64(3, "h"))
    assert np.all(t["custo"] == 1.5)


def test_campos_sem_janela_operada_voltam_vazios_e_tipados():
    t = wfa.trades_oos_campos([], [], ("exit_ts", "custo"))
    assert set(t) == {"exit_ts", "custo", "step"}
    assert t["exit_ts"].dtype == np.dtype("datetime64[s]")
    assert len(t["custo"]) == 0


# ------------------------------------------------------------ os cartões
def test_cartoes_trocam_so_a_dica_pedida():
    m = metrics.resumo(np.array([10.0, -4.0]), None,
                       np.array([_dia(4), _dia(5)]), CAP)
    padrao = SC.cartoes(m)
    trocado = SC.cartoes(m, {"sharpe": "texto novo"})

    assert list(padrao) == list(trocado)          # mesmos cartões, mesma ordem
    assert "texto novo" in str(trocado["sharpe"])
    assert "texto novo" not in str(padrao["sharpe"])
    assert str(padrao["payoff"]) == str(trocado["payoff"])


def test_kpis_do_wfa_juntam_os_do_backtest_e_os_proprios():
    janela = wfa.Janela(1, np.datetime64("2022-01-01", "s"),
                        np.datetime64("2023-01-01", "s"),
                        np.datetime64("2023-01-01", "s"),
                        np.datetime64("2023-07-01", "s"), False)
    passos = [wfa.Passo(janela=janela, escolhida=0, params={"p": 1})]
    ts = np.array([_dia(4), _dia(5), _dia(6)])
    div = WP.kpis(passos, ts, np.array([50.0, -20.0, 30.0]),
                  {"wfe_global": 0.9, "consistencia_lucro": 100.0}, 10_000.0,
                  custo=np.array([1.0, 1.0, 1.0]), saida=ts)
    texto = str(div)

    for rotulo in ("período", "lucro líquido", "WFE global",
                   "semestres positivos", "max drawdown", "lucro por mês",
                   "profit factor", "win rate", "payoff", "expectativa",
                   "fator recuperação", "sharpe", "trades"):
        assert f"'{rotulo}'" in texto, rotulo
    assert "01/01/2023 → 01/07/2023" in texto      # o período é o OOS
    assert "fora da amostra" in texto               # a dica OOS entrou


# ------------------------------------------------------- holdout na curva
def test_curva_destaca_o_holdout_quando_estendido():
    """O trecho do holdout ganha traço, faixa e rótulo próprios. O rótulo já
    sumiu uma vez, apagado por um update_layout posterior."""
    janela = wfa.Janela(1, np.datetime64("2023-09-01", "s"),
                        np.datetime64("2024-03-01", "s"),
                        np.datetime64("2024-03-01", "s"),
                        np.datetime64("2024-04-01", "s"), False)
    passos = [wfa.Passo(janela=janela, escolhida=0, params={"p": 1})]
    ts = np.array([_dia(4), _dia(12), _dia(20), _dia(28)])
    liq = np.array([50.0, -20.0, 30.0, 10.0])

    com = WP.curva(ts, liq, np.ones(4, dtype=int), passos, 10_000.0,
                   holdout_de="2024-03-15 00:00:00")
    assert "holdout" in [t.name for t in com.data]
    assert any("HOLDOUT" in a.text for a in com.layout.annotations)

    sem = WP.curva(ts, liq, np.ones(4, dtype=int), passos, 10_000.0)
    assert "holdout" not in [t.name for t in sem.data]
    assert not any("HOLDOUT" in a.text for a in sem.layout.annotations)


# ------------------------------------------------------ matriz em abas
def test_abas_da_matriz_consenso_e_uma_por_inteligencia():
    from ui.components import wfa_matriz as WM
    valores = [v for v, _ in WM.ABAS]
    assert valores[0] == WM.CONSENSO
    assert valores[1:] == [q for _, q in wfa.INTELIGENCIAS]
    # toda aba tem o seu (?)
    assert all(WM.DESCRICOES.get(v) for v in valores)


def test_linha_atual_no_consenso_e_na_aba_da_inteligencia():
    from ui.components import wfa_matriz as WM
    r = {"config": "IS:12 / OOS:6", "is_meses": 12, "oos_meses": 6,
         "estado": "aprovado", "portoes_ok": 6, "n_portoes": 6, "wfe": 1.0}
    dados = {"por_q": {"sharpe": [r]}, "consenso": [dict(r)]}

    assert WM.linhas(WM.CONSENSO, dados, 12, 6, "ulcer")[0]["atual"]
    # mesma IS/OOS em outra inteligência não é a configuração aberta
    assert not WM.linhas("sharpe", dados, 12, 6, "ulcer")[0]["atual"]
    l = WM.linhas("sharpe", dados, "12", "6", "sharpe")[0]
    assert l["atual"] and l["portoes_txt"] == "✓ 6/6"
    assert WM.linhas("sharpe", None, 12, 6, "sharpe") == []


def test_colunas_do_consenso_tem_todas_as_votantes_e_o_resumo():
    from ui.components import wfa_matriz as WM
    campos = [c["field"] for c in WM.colunas(WM.CONSENSO)]
    assert [f for f in campos if f.startswith("wfe_") and f != "wfe_mediano"] == \
        [f"wfe_{q}" for q in wfa.VOTANTES]
    for f in ("aprovam", "wfe_mediano", "pior_wfe", "melhor_wfe"):
        assert f in campos
    assert "wfe_ancorado" in [c["field"] for c in WM.colunas("sharpe")]


def test_mapa_de_calor_do_wfe_usa_corte_em_fracao():
    """O bug antigo: cortes 90/70 num WFE que vem em fração (1,04) — o mapa
    nunca pintava."""
    from ui.components import wfa_matriz as WM
    col = next(c for c in WM.colunas("sharpe") if c["field"] == "wfe")
    conds = [x["condition"] for x in col["cellStyle"]["styleConditions"]]
    assert ">= 0.9" in conds[0] and ">= 0.3" in conds[-1]



def test_curva_desenha_a_faixa_das_fixas_com_o_percentil():
    js = wfa.montar_janelas("2022-01-01", "2024-01-01", 6, 3)
    passos = [wfa.Passo(janela=j, escolhida=0, params={"p": 1}) for j in js[:-1]]
    dias = np.arange(np.datetime64("2022-07-01"), np.datetime64("2023-12-01"))
    q = {p: np.full(len(dias), 10_000.0 + p) for p in (10, 25, 50, 75, 90)}
    fixas = {"dias": dias, "quantis": q, "finais": np.array([10.0, 50.0, 500.0])}
    ts = np.array(["2022-08-01", "2023-02-01"], dtype="datetime64[s]")
    fig = WP.curva(ts, np.array([30.0, 30.0]), np.ones(2, dtype=int), passos,
                   10_000.0, fixas)
    assert "mediana das fixas" in [t.name for t in fig.data]
    assert any(a.text.strip() == "p67" for a in fig.layout.annotations)
    assert fig.data[-1].name != "mediana das fixas"      # a faixa fica atrás
