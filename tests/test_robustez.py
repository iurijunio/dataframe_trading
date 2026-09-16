"""Testes da peneira de candidato.

Cada um monta um caso com resposta conhecida: uma estratégia que só vive de
cinco trades, uma cujas perdas vêm em bloco, uma cuja curva é degrau. Se a
tela disser outra coisa, o erro está no desenho — não na conta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import robustez as rb  # noqa: E402

CAP = 10_000.0


def ts_diarios(n, inicio="2022-01-03"):
    return (np.datetime64(inicio, "s")
            + np.arange(n) * np.timedelta64(1, "D")).astype("datetime64[s]")


# ---------------------------------------------------------------- sequência
def test_monte_carlo_situa_a_ordem_observada():
    """Ganhos primeiro e perdas depois é o pior arranjo possível: sobe ao
    topo e cai tudo de uma vez. Quase toda outra ordem é melhor, então o
    percentil do observado tem que ser alto."""
    liq = np.concatenate([np.full(40, 100.0), np.full(40, -80.0)])
    mc = rb.monte_carlo(liq, CAP, n=400)

    assert mc["percentil_do_observado"] > 80
    assert mc["dd_observado"] >= mc["dd_p50"]
    assert mc["dd_max"] >= mc["dd_p99"] >= mc["dd_p95"] >= mc["dd_p50"]


def test_monte_carlo_revela_risco_que_a_ordem_escondeu():
    """O caso que importa: a ordem observada foi boazinha e o baralho tem
    arranjos bem piores guardados."""
    rng = np.random.default_rng(11)
    liq = rng.normal(8, 120, 400)
    mc = rb.monte_carlo(liq, CAP, n=500)
    assert mc["dd_p95"] > mc["dd_p50"]
    assert 0 <= mc["percentil_do_observado"] <= 100


def test_monte_carlo_nao_muda_o_lucro_final():
    """Reembaralhar muda o caminho, nunca o destino."""
    rng = np.random.default_rng(1)
    liq = rng.normal(5, 100, 300)
    mc = rb.monte_carlo(liq, CAP, n=200)
    assert mc["lucro_final"] == pytest.approx(liq.sum())


def test_monte_carlo_e_reprodutivel():
    liq = np.random.default_rng(2).normal(3, 90, 200)
    a = rb.monte_carlo(liq, CAP, n=300)
    b = rb.monte_carlo(liq, CAP, n=300)
    assert a["dd_p95"] == pytest.approx(b["dd_p95"])


def test_poucos_trades_nao_simulam():
    assert rb.monte_carlo(np.array([1.0, 2.0]), CAP) == {}


# --------------------------------------------------------------- drawdowns
def test_drawdown_mede_profundidade_e_recuperacao():
    #     +100  -300  -200  +600   -> fundo em -500, recupera no 4º trade
    liq = np.array([100.0, -300.0, -200.0, 600.0])
    d = rb.drawdowns(ts_diarios(4), liq, CAP)[0]

    assert d["profundidade"] == pytest.approx(500.0)
    assert d["dias_ate_o_fundo"] == 2
    assert d["recuperacao"] is not None
    assert d["dias_para_recuperar"] == 1


def test_drawdown_ainda_submerso_no_fim():
    """Backtest que termina no vermelho não pode fingir recuperação."""
    liq = np.array([100.0, -400.0, -100.0])
    d = rb.drawdowns(ts_diarios(3), liq, CAP)[0]
    assert d["recuperacao"] is None
    assert d["dias_para_recuperar"] is None


def test_drawdowns_vem_do_maior_para_o_menor():
    liq = np.array([-100.0, 200.0, -900.0, 1000.0, -50.0, 100.0])
    lista = rb.drawdowns(ts_diarios(6), liq, CAP)
    fundos = [d["profundidade"] for d in lista]
    assert fundos == sorted(fundos, reverse=True)


# ------------------------------------------------------------ significância
def test_expectativa_forte_e_conclusiva():
    liq = np.random.default_rng(3).normal(50, 40, 400)   # média muito > ruído
    s = rb.significancia(liq)
    assert s["p"] < 0.001 and s["confianca"] > 99


def test_expectativa_fraca_pede_mais_trades():
    """O útil aqui não é dizer 'não deu': é dizer quantos trades faltam."""
    liq = np.random.default_rng(4).normal(1.0, 100, 120)
    s = rb.significancia(liq)
    assert s["p"] > 0.05
    assert s["n_necessario"] > len(liq)


# ------------------------------------------------------------- teste de runs
def test_perdas_em_bloco_sao_detectadas():
    """40 ganhos seguidos e 40 perdas seguidas: duas corridas, não ~40."""
    liq = np.concatenate([np.full(40, 10.0), np.full(40, -10.0)])
    r = rb.teste_runs(liq)
    assert r["corridas"] == 2
    assert r["agrupadas"] and not r["alternadas"]


def test_alternancia_perfeita_tambem_e_anomalia():
    liq = np.tile([10.0, -10.0], 40)
    r = rb.teste_runs(liq)
    assert r["alternadas"] and not r["agrupadas"]


def test_serie_aleatoria_parece_independente():
    """Ruído puro não pode ser acusado de agrupar. O teste usa 95% de
    confiança, então ~5% das amostras acusam por acaso: a checagem é sobre a
    maioria, não sobre uma semente escolhida a dedo."""
    acusadas = 0
    for semente in range(20):
        liq = np.random.default_rng(semente).normal(2, 50, 500)
        r = rb.teste_runs(liq)
        acusadas += bool(r["agrupadas"] or r["alternadas"])
    assert acusadas <= 3


# ------------------------------------------------------------ curva é reta?
def test_curva_constante_tem_correlacao_alta():
    liq = np.full(200, 25.0)
    assert rb.correlacao_lr(liq, CAP)["correlacao"] > 0.999


def test_curva_em_degrau_tem_correlacao_baixa():
    """Sobe tudo no começo e fica de lado: lucro veio de um período."""
    liq = np.concatenate([np.full(30, 300.0), np.zeros(270)])
    assert rb.correlacao_lr(liq, CAP)["correlacao"] < 0.8


# ------------------------------------------------------------- fragilidade
def test_estrategia_que_vive_de_cinco_trades_e_reprovada():
    liq = np.concatenate([np.full(5, 5_000.0), np.full(300, -50.0)])
    c = rb.concentracao(liq)
    assert c["total"] > 0                 # o total engana...
    assert c["sem"][5] < 0                # ...mas sem os cinco, vira prejuízo
    assert not c["sobrevive_sem_5"]
    assert c["peso_do_maior"] > 40


def test_estrategia_distribuida_sobrevive():
    liq = np.random.default_rng(6).normal(30, 25, 500)
    c = rb.concentracao(liq)
    assert c["sobrevive_sem_5"] and c["sem"][20] > 0
    assert c["peso_do_maior"] < 5


# --------------------------------------------------------------- ranqueamento
def test_ulcer_pune_quem_fica_muito_tempo_no_fundo():
    """Mesmo drawdown, tempos submersos diferentes."""
    rapido = np.concatenate([[-1000.0, 1000.0], np.zeros(98)])
    demorado = np.concatenate([[-1000.0], np.zeros(98), [1000.0]])
    a = rb.ulcer_mar(rapido, CAP, 365)
    b = rb.ulcer_mar(demorado, CAP, 365)
    assert a["max_dd"] == pytest.approx(b["max_dd"])
    assert b["ulcer"] > a["ulcer"] * 5


def test_mar_relaciona_retorno_e_drawdown():
    liq = np.full(252, 20.0)               # sobe sempre, drawdown zero
    um = rb.ulcer_mar(liq, CAP, 365)
    assert um["cagr"] > 0
    assert um["mar"] is None               # sem drawdown, a razão não existe


# ------------------------------------------------------------ meses positivos
def test_conta_meses_e_a_pior_sequencia():
    entradas, liq = [], []
    # jan+ fev- mar- abr- mai+ jun+
    for mes, v in zip(range(1, 7), [100.0, -50.0, -50.0, -50.0, 100.0, 100.0]):
        entradas.append(np.datetime64(f"2023-{mes:02d}-10", "s"))
        liq.append(v)
    m = rb.meses_positivos(np.array(entradas), np.array(liq))

    assert m["meses"] == 6 and m["positivos"] == 3
    assert m["pct"] == pytest.approx(50.0)
    assert m["pior_sequencia"] == 3


# ------------------------------------------------------------------- custo
def test_custo_que_zera_e_a_folga():
    # bruto 1.000, 100 contratos -> 200 pontas -> empata a R$ 5,00 por ponta
    c = rb.custo_que_zera(1_000.0, np.full(100, 1), custo_atual_por_contrato=1.0)
    assert c["limite_por_contrato"] == pytest.approx(5.0)
    assert c["folga"] == pytest.approx(4.0)
    assert c["folga_pct"] == pytest.approx(400.0)


def test_custo_sem_contratos_nao_quebra():
    assert rb.custo_que_zera(100.0, np.array([]), 1.0) == {}


# --------------------------------------------------------- tamanho do bloco
def test_bloco_medio_e_um_em_serie_independente():
    """Sem dependência entre dias, o bootstrap em blocos tem que degenerar
    para o sorteio dia a dia."""
    rng = np.random.default_rng(3)
    assert rb.bloco_medio(rng.normal(10, 100, 500)) == 1


def test_bloco_medio_cresce_quando_os_dias_andam_juntos():
    """Volatilidade agrupada: bons e maus vêm em sequência, que é o que
    produz drawdown de verdade."""
    rng = np.random.default_rng(3)
    base = rng.normal(10, 100, 100)
    agrupada = np.repeat(base, 5)               # cada valor dura 5 pregões
    assert rb.bloco_medio(agrupada) >= 4


def test_bloco_medio_nao_quebra_com_serie_curta_ou_constante():
    assert rb.bloco_medio(np.array([1.0, 2.0])) == 1
    assert rb.bloco_medio(np.zeros(200)) == 1


def test_bloco_medio_guarda_serie_curta_com_dependencia():
    """Amostra pequena (< 30) não sustenta estimativa confiável de dependência.
    Sem a guarda, uma série de 15 pontos com agrupamento forte daria bloco > 1,
    violando o princípio de que bootstrap em blocos sem amostra não faz sentido."""
    rng = np.random.default_rng(42)
    base = rng.normal(10, 50, 5)
    agrupada_curta = np.repeat(base, 3)  # 15 pontos: cada valor dura 3 pregões
    assert rb.bloco_medio(agrupada_curta) == 1


# ------------------------------------------------------ bootstrap estacionario
def test_bootstrap_faz_o_lucro_final_variar():
    """A diferença que motivou a troca: na permutação o lucro final é
    constante, então a incerteza que mais importa fica de fora."""
    rng = np.random.default_rng(1)
    dia = rng.normal(20, 150, 400)
    b = rb.bootstrap(dia, 10_000.0, n=300, semente=5)
    assert b["final_p10"] < b["final_p50"] < b["final_p90"]
    perm = rb.monte_carlo(dia, 10_000.0, n=300)
    assert perm["lucro_final"] == pytest.approx(float(dia.sum()))


def test_bootstrap_com_bloco_1_fica_perto_da_permutacao():
    """Sem dependência, os dois métodos medem a mesma coisa — a diferença
    toda vem do bloco e da reposição."""
    rng = np.random.default_rng(2)
    dia = rng.normal(15, 100, 600)
    b = rb.bootstrap(dia, 10_000.0, n=800, semente=4, bloco=1)
    p = rb.monte_carlo(dia, 10_000.0, n=800)
    assert b["dd_p95"] == pytest.approx(p["dd_p95"], rel=0.25)


def test_bootstrap_em_serie_agrupada_acha_drawdown_maior():
    """O que a permutação escondia: dias ruins vindo juntos afundam mais."""
    rng = np.random.default_rng(7)
    base = rng.normal(10, 120, 120)
    dia = np.repeat(base, 5)
    b = rb.bootstrap(dia, 10_000.0, n=500, semente=9)
    p = rb.monte_carlo(dia, 10_000.0, n=500)
    assert b["dd_p95"] > p["dd_p95"]


def test_bootstrap_com_horizonte_curto_reduz_o_drawdown():
    """O disjuntor precisa de horizonte: o p95 de cinco anos não é o p95 de
    três meses, e desligar pelo primeiro é desligar estratégia sadia."""
    rng = np.random.default_rng(11)
    dia = rng.normal(10, 100, 1000)
    inteiro = rb.bootstrap(dia, 10_000.0, n=400, semente=2)
    curto = rb.bootstrap(dia, 10_000.0, n=400, semente=2, horizonte=60)
    assert curto["dd_p95"] < inteiro["dd_p95"]
    assert curto["horizonte"] == 60


def test_bootstrap_conta_perdas_seguidas_e_tempo_submerso_em_pregoes():
    dia = np.array([-10.0] * 7 + [100.0] * 30)
    b = rb.bootstrap(dia, 10_000.0, n=200, semente=3, bloco=1)
    assert b["perdas_seguidas_p95"] >= 1
    assert b["submerso_p95"] >= 1


def test_bootstrap_com_serie_curta_devolve_vazio():
    assert rb.bootstrap(np.zeros(5), 10_000.0) == {}
