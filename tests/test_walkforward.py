"""Testes do walk-forward e do espaco de busca.

O que estes testes protegem: que o holdout fique realmente lacrado, que
treino e teste nao se misturem, e que um pico isolado de sorte nao suba no
ranking so por ser alto.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import walkforward as wf  # noqa: E402
from core.optimizer import combinacoes, montar_espaco  # noqa: E402

DIA = np.timedelta64(1, "D")
INICIO = np.datetime64("2021-03-16", "s")
FIM = np.datetime64("2026-03-13", "s")


# ------------------------------------------------------------------ janelas
def test_folds_deslizam_e_nao_invadem_o_holdout():
    j = wf.montar_janelas(INICIO, FIM, treino_meses=12, teste_meses=3,
                          passo_meses=3, holdout_meses=12)

    assert len(j.folds) >= 10
    for f in j.folds:
        assert f.treino_de < f.treino_ate == f.teste_de < f.teste_ate
        # nada, em nenhum fold, encosta no holdout
        assert f.teste_ate <= j.holdout_de

    # o passo e mesmo o pedido
    passo = j.folds[1].treino_de - j.folds[0].treino_de
    assert passo == 3 * wf.MESES


def test_sem_holdout_usa_a_serie_inteira():
    com = wf.montar_janelas(INICIO, FIM, holdout_meses=12)
    sem = wf.montar_janelas(INICIO, FIM, holdout_meses=0)
    assert sem.holdout_de is None
    assert len(sem.folds) > len(com.folds)


def test_periodo_curto_nao_gera_fold():
    j = wf.montar_janelas(INICIO, INICIO + 60 * DIA, treino_meses=12,
                          teste_meses=3, holdout_meses=12)
    assert j.folds == []


# ---------------------------------------------------- reparticao dos trades
def test_holdout_fica_fora_da_otimizacao():
    """O trade do holdout nao pode contaminar nenhuma metrica da varredura."""
    j = wf.montar_janelas(INICIO, FIM)
    f0 = j.folds[0]

    entradas = np.array([f0.treino_de + 10 * DIA,
                         f0.teste_de + 10 * DIA,
                         j.holdout_de + 10 * DIA])
    liq = np.array([100.0, 50.0, 999_999.0])   # o do holdout e absurdo de proposito

    a = wf.avaliar(entradas, liq, j, capital=10_000.0)

    assert a["geral"]["trades"] == 2           # so os dois de antes do holdout
    assert a["geral"]["lucro"] == pytest.approx(150.0)
    # o holdout existe, mas guardado - e nunca soma no que a varredura ordena
    assert a["holdout"]["lucro"] == pytest.approx(999_999.0)
    assert a["score"] != pytest.approx(999_999.0)


def test_consistencia_prefere_quem_repete():
    """Ganhar sempre um pouco vence ganhar muito uma vez so."""
    j = wf.montar_janelas(INICIO, FIM)

    # A: lucra em todas as janelas de teste
    ent_a, liq_a = [], []
    for f in j.folds:
        ent_a += [f.teste_de + 1 * DIA, f.teste_de + 2 * DIA]
        liq_a += [60.0, -20.0]

    # B: uma janela explode de lucro, as outras sangram
    ent_b, liq_b = [], []
    for k, f in enumerate(j.folds):
        ent_b += [f.teste_de + 1 * DIA, f.teste_de + 2 * DIA]
        liq_b += ([4000.0, -20.0] if k == 0 else [-30.0, -20.0])

    a = wf.avaliar(np.array(ent_a), np.array(liq_a), j, 10_000.0)
    b = wf.avaliar(np.array(ent_b), np.array(liq_b), j, 10_000.0)

    assert a["consistencia"] == 1.0
    assert b["consistencia"] < 0.2
    assert b["geral"]["lucro"] > a["geral"]["lucro"]   # B lucra mais no total
    assert a["score"] > b["score"]                     # e mesmo assim perde


def test_resumo_de_fatia_vazia_nao_quebra():
    r = wf.resumo(np.empty(0), 10_000.0)
    assert r["trades"] == 0 and r["lucro"] == 0.0


def test_resumo_calcula_drawdown_certo():
    # +100, -300, +50  ->  pico 10100, fundo 9800, drawdown 300
    r = wf.resumo(np.array([100.0, -300.0, 50.0]), 10_000.0)
    assert r["lucro"] == pytest.approx(-150.0)
    assert r["max_dd"] == pytest.approx(300.0)
    assert r["profit_factor"] == pytest.approx(150 / 300)


def test_filtro_de_minimo_de_operacoes():
    j = wf.montar_janelas(INICIO, FIM)
    f0 = j.folds[0]
    entradas = np.array([f0.teste_de + 1 * DIA, f0.teste_de + 2 * DIA])
    a = wf.avaliar(entradas, np.array([10.0, 10.0]), j, 10_000.0, min_operacoes=50)
    assert not a["passa_filtro"]
    assert a["score"] == float("-inf")


def test_combinacao_que_so_opera_em_dois_periodos_e_descartada():
    """Presenca em poucas janelas nao e estrategia, e coincidencia."""
    j = wf.montar_janelas(INICIO, FIM)
    ent, liq = [], []
    for f in j.folds[:2]:
        ent += [f.teste_de + 1 * DIA] * 100
        liq += [50.0] * 100
    a = wf.avaliar(np.array(ent), np.array(liq), j, 10_000.0)
    assert not a["passa_filtro"]
    assert a["score"] == float("-inf")


# ------------------------------------------------------ score de vizinhanca
def test_pico_isolado_perde_para_regiao_boa():
    """Um acidente cercado de prejuízo nao pode ganhar de um platô."""
    trials = []
    for a in (1, 2, 3, 4, 5):
        for b in (1, 2):
            # platô consistente em a=4..5; pico solitario em a=1
            if a == 1 and b == 1:
                score = 100.0
            elif a >= 4:
                score = 10.0
            else:
                score = -5.0
            trials.append({"params": {"a": a, "b": b}, "score": score})

    wf.score_vizinhanca(trials, ["a", "b"])

    pico = next(t for t in trials if t["params"] == {"a": 1, "b": 1})
    plato = next(t for t in trials if t["params"] == {"a": 5, "b": 1})

    assert pico["score"] > plato["score"]            # cru, o pico ganha
    assert pico["score_robusto"] < plato["score_robusto"]  # robusto, perde


# ------------------------------------------------------- espaco de busca
def test_espaco_respeita_o_interruptor():
    schema = {"a": {"default": 9, "step": 1, "tipo": "int"},
              "b": {"default": 21, "step": 1, "tipo": "int"}}
    espaco = montar_espaco(schema, {
        "a": {"on": True, "de": 5, "passo": 5, "ate": 20, "valor": 9},
        "b": {"on": False, "valor": 30},
    })
    assert espaco["a"] == [5, 10, 15, 20]
    assert espaco["b"] == [30]          # desligado: so o valor da tela
    assert len(combinacoes(espaco)) == 4


def test_faixa_invalida_cai_no_valor_atual():
    schema = {"a": {"default": 9, "step": 1, "tipo": "int"}}
    for ruim in ({"on": True, "de": 20, "ate": 5, "valor": 9},
                 {"on": True, "de": None, "ate": 10, "valor": 9},
                 {"on": True, "de": 1, "ate": 10, "passo": 0, "valor": 9}):
        assert montar_espaco(schema, {"a": ruim})["a"] == [9]


# --------------------------------------------- limites duros do schema
def test_faixa_nao_fura_o_maximo_declarado():
    """A faixa da tela é recortada pelos limites da estratégia.

    Sem isto, digitar 'até 300' num parâmetro cujo schema diz max=200
    varria valores que a estratégia nunca declarou aceitar — e o resultado
    parecia legítimo na tabela.
    """
    schema = {"media_lenta": {"default": 21, "min": 3, "max": 200,
                              "step": 1, "tipo": "int"}}
    espaco = montar_espaco(schema, {
        "media_lenta": {"on": True, "de": 100, "passo": 50, "ate": 400,
                        "valor": 21},
    })
    assert max(espaco["media_lenta"]) <= 200
    assert espaco["media_lenta"] == [100, 150, 200]


def test_faixa_nao_fura_o_minimo_declarado():
    schema = {"p": {"default": 10, "min": 5, "max": 100, "step": 1, "tipo": "int"}}
    espaco = montar_espaco(schema, {
        "p": {"on": True, "de": 1, "passo": 4, "ate": 13, "valor": 10},
    })
    assert min(espaco["p"]) >= 5
    assert espaco["p"] == [5, 9, 13]


def test_faixa_inteiramente_fora_cai_no_valor_atual():
    schema = {"p": {"default": 10, "min": 5, "max": 100, "step": 1, "tipo": "int"}}
    espaco = montar_espaco(schema, {
        "p": {"on": True, "de": 300, "passo": 10, "ate": 400, "valor": 10},
    })
    assert espaco["p"] == [10]
