"""Testes das leituras da aba Detalhes.

Mesma disciplina dos outros: cada caso é montado com a resposta conhecida de
antemão — uma estratégia que entra cedo demais, outra que devolve o lucro,
outra cujas perdas vêm em bloco. Se a tela disser outra coisa, o erro está
no desenho, não na conta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import detalhes as D  # noqa: E402

STOP, ALVO = 0, 1


def ts_diarios(n, inicio="2023-01-02"):
    return (np.datetime64(inicio, "s")
            + np.arange(n) * np.timedelta64(1, "D")).astype("datetime64[s]")


# -------------------------------------------------------------- sequências
def test_media_de_sequencias_separa_evento_de_regra():
    """Uma corrida de 10 perdas no meio de trades alternados: o MÁXIMO
    assusta, a MÉDIA revela que aquilo foi um evento isolado."""
    liq = np.concatenate([np.tile([10.0, -10.0], 30), np.full(10, -10.0),
                          np.tile([10.0, -10.0], 30)])
    s = D.sequencias(liq)

    assert s["max_perdas"] == 11        # as 10 emendam na perda anterior
    assert s["media_perdas"] < 2.0
    assert s["media_ganhos"] == pytest.approx(1.0)


def test_depois_de_perdas_expoe_dependencia():
    """Série montada com dependência de verdade: depois de 3 derrotas o
    próximo trade SEMPRE perde. É o caso que justifica pausar o dia.

    Nota de quem escreveu: uma série periódica (4 perdas, 4 ganhos) não
    serve aqui. Nela o conjunto 'trades que vêm depois de 3 derrotas' acaba
    contendo tanto a última perda do bloco quanto o primeiro ganho do
    seguinte, e a média volta a bater com a geral — o teste passaria a medir
    o período do padrão, não a dependência.
    """
    rng = np.random.default_rng(5)
    liq, seguidas = [], 0
    for _ in range(1_200):
        v = -30.0 if seguidas >= 3 else (40.0 if rng.random() < 0.55 else -20.0)
        liq.append(v)
        seguidas = seguidas + 1 if v < 0 else 0
    s = D.sequencias(np.array(liq))

    assert s["depois_de"][3]["expectativa"] == pytest.approx(-30.0)
    assert s["depois_de"][3]["expectativa"] < s["expectativa_geral"]
    assert s["depois_de"][3]["n"] >= 20


def test_perdas_independentes_nao_acusam_dependencia():
    """O contraponto: em série sem memória, a expectativa depois de duas
    derrotas fica junto da geral. Sem este caso, o cartão poderia acusar
    dependência em qualquer ruído e mandar pausar o dia à toa."""
    liq = np.random.default_rng(9).normal(20, 200, 3_000)
    s = D.sequencias(liq)
    assert abs(s["depois_de"][2]["expectativa"] - s["expectativa_geral"]) < 30


def test_sequencias_pede_amostra_minima():
    assert D.sequencias(np.array([1.0, -1.0, 1.0])) == {}


# -------------------------------------------------------------- eficiência
def test_entrada_ruim_e_saida_boa():
    """O preço anda 90 contra antes de andar 10 a favor, e o trade leva tudo
    o que ficou disponível: entrada péssima, saída perfeita."""
    n = 50
    mae = np.full(n, -90); mfe = np.full(n, 10); pontos = np.full(n, 10)
    e = D.eficiencia(mae, mfe, pontos, np.full(n, 999), np.full(n, STOP), ALVO)

    assert e["entrada"] == pytest.approx(10.0)
    assert e["saida"] == pytest.approx(100.0)


def test_saida_ruim_devolve_o_lucro():
    """Chega a 100 a favor e fecha em 20: a entrada achou o movimento, a
    gestão o entregou de volta."""
    n = 50
    e = D.eficiencia(np.full(n, -10), np.full(n, 100), np.full(n, 20),
                     np.full(n, 999), np.full(n, STOP), ALVO)

    assert e["entrada"] > 90
    assert e["saida"] == pytest.approx(20.0)
    assert e["razao_mfe_mae"] == pytest.approx(10.0)


def test_alvo_tocado_e_nao_pago_e_contado():
    """Metade dos trades encosta no alvo de 100 e sai por outro motivo."""
    mfe = np.concatenate([np.full(20, 120), np.full(20, 120)])
    motivo = np.concatenate([np.full(20, ALVO), np.full(20, STOP)])
    e = D.eficiencia(np.full(40, -10), mfe, np.full(40, 10),
                     np.full(40, 100), motivo, ALVO)

    assert e["tocou_alvo"] == 40
    assert e["tocou_e_nao_saiu"] == 20
    assert e["pct_devolvido"] == pytest.approx(50.0)


def test_saida_sem_denominador_e_indisponivel_e_nao_zero():
    """MFE zero não tem denominador. Devolver 0.0 pintava o cartão de
    vermelho — lia-se "eficiência péssima" onde o certo é "indisponível"."""
    e = D.eficiencia(np.full(30, -50), np.zeros(30, dtype=int), np.full(30, -50),
                     np.full(30, 100), np.full(30, STOP), ALVO)
    assert e["saida"] is None
    assert e["entrada"] == pytest.approx(0.0)      # houve amplitude (o MAE)
    assert e["n_saida"] == 0 and e["n_trades"] == 30


def test_sem_amplitude_nenhuma_entrada_tambem_e_indisponivel():
    """Trades que não andaram para lado nenhum: não há fração a medir."""
    e = D.eficiencia(np.zeros(20, dtype=int), np.zeros(20, dtype=int),
                     np.zeros(20, dtype=int), np.full(20, 100),
                     np.full(20, STOP), ALVO)
    assert e["entrada"] is None and e["saida"] is None


def test_saida_informa_sobre_quantos_trades_a_media_foi_feita():
    """Metade dos trades nunca andou a favor — e são os piores. A média sai
    dos outros, mas a tela precisa saber disso: sem `n_saida`, 80% parecia a
    eficiência da amostra inteira quando era a de metade dela."""
    mfe = np.array([0] * 5 + [100] * 5)
    pontos = np.array([-200] * 5 + [80] * 5)
    e = D.eficiencia(np.full(10, -50), mfe, pontos, np.full(10, 300),
                     np.zeros(10), ALVO)
    assert e["saida"] == pytest.approx(80.0)
    assert e["n_saida"] == 5 and e["n_trades"] == 10


# ------------------------------------------------------------------- risco
def test_cvar_e_pior_que_o_var():
    liq = np.concatenate([np.full(90, 50.0), np.full(10, -500.0)])
    r = D.risco_trade(liq, np.zeros(100), np.zeros(100), np.zeros(100), STOP)

    assert r["cvar95"] <= r["var95"] < 0
    assert r["maior_perda"] == pytest.approx(-500.0)


def test_cvar_nao_se_dilui_com_empates_no_percentil():
    """O caso real: com stop fixo em pontos, dezenas de trades fecham
    EXATAMENTE no mesmo valor, e ele calha de ser o percentil 5.

    A versão antiga pegava `liquido <= var` e arrastava os 31 empatados para
    a cauda — a "média dos 5% piores" saía de 31% da amostra, puxada na
    direção do VaR. O erro era para o lado otimista, no número que dimensiona
    posição. Agora a cauda são os k piores, k = 5% arredondado para cima.
    """
    liq = np.concatenate([[-1000.0], np.full(30, -500.0), np.full(69, 200.0)])
    r = D.risco_trade(liq, np.zeros(100), np.zeros(100), np.zeros(100), STOP)

    assert r["n_cauda"] == 5
    assert r["cvar95"] == pytest.approx(-600.0)    # (-1000 + 4×-500) / 5
    assert r["cvar95"] < r["var95"]                # a cauda dói mais que o corte


def test_cauda_tem_pelo_menos_um_trade():
    liq = np.concatenate([np.full(19, 10.0), [-90.0]])
    r = D.risco_trade(liq, np.zeros(20), np.zeros(20), np.zeros(20), STOP)
    assert r["n_cauda"] == 1 and r["cvar95"] == pytest.approx(-90.0)


def test_cauda_gorda_aparece_na_razao_pior_sobre_media():
    liq = np.concatenate([np.full(60, 40.0), np.full(39, -40.0), [-1200.0]])
    r = D.risco_trade(liq, np.zeros(100), np.zeros(100), np.zeros(100), STOP)
    assert r["razao_pior_media"] > 5


def test_slippage_configurado_nao_vira_stop_furado():
    """Todo stop fecha 5 pontos além por slippage. Sem a folga, 100% dos
    stops seriam acusados de furados e a métrica não diria nada."""
    n = 100
    liq = np.full(n, -100.0)
    pontos = np.full(n, -105)
    sl = np.full(n, 100)
    motivo = np.full(n, STOP)

    assert D.risco_trade(liq, pontos, sl, motivo, STOP, folga=0)["pct_furados"] == 100.0
    assert D.risco_trade(liq, pontos, sl, motivo, STOP, folga=5)["stops_furados"] == 0


def test_gap_real_e_acusado_mesmo_com_folga():
    n = 100
    pontos = np.full(n, -105)
    pontos[:10] = -400                       # dez gaps de verdade
    r = D.risco_trade(np.full(n, -100.0), pontos, np.full(n, 100),
                      np.full(n, STOP), STOP, folga=5)

    assert r["stops_furados"] == 10
    assert r["excesso_medio"] == pytest.approx(295.0)


# ------------------------------------------------------------------- ritmo
def test_exposicao_e_seletividade():
    """20 trades em 20 pregões distintos, de um período de 100 pregões."""
    liq = np.full(20, 10.0)
    r = D.ritmo(ts_diarios(20), liq, barras_em_posicao=500,
                barras_totais=10_000, pregoes_totais=100)

    assert r["exposicao_pct"] == pytest.approx(5.0)
    assert r["pregoes_operados"] == 20
    assert r["pct_pregoes"] == pytest.approx(20.0)
    assert r["trades_por_dia"] == pytest.approx(1.0)


def test_dias_positivos_somam_o_pregao_inteiro():
    """Dois trades no mesmo dia, +30 e −10: o dia é positivo, ainda que um
    dos trades tenha perdido."""
    ts = np.array([np.datetime64("2023-05-02T10:00", "s"),
                   np.datetime64("2023-05-02T14:00", "s"),
                   np.datetime64("2023-05-03T10:00", "s")])
    r = D.ritmo(ts, np.array([30.0, -10.0, -5.0]), 10, 100, 2)

    assert r["pregoes_operados"] == 2
    assert r["dias_positivos"] == 1
    assert r["melhor_dia"] == pytest.approx(20.0)
    assert r["pior_dia"] == pytest.approx(-5.0)
    assert r["max_trades_dia"] == 2


# ---------------------------------------------------- resultado por volume
def test_dia_agitado_aparece_separado_do_dia_calmo():
    """Dias de 1 trade ganham; dias de 8 trades perdem. É a leitura que
    justifica um limite de operações por dia."""
    ts, liq = [], []
    for d in range(1, 11):                      # 10 pregoes calmos
        ts.append(np.datetime64(f"2023-03-{d:02d}T10:00", "s"))
        liq.append(100.0)
    for d in range(13, 23):                     # 10 pregoes agitados
        for h in range(8):
            ts.append(np.datetime64(f"2023-03-{d:02d}T{10 + h:02d}:00", "s"))
            liq.append(-50.0)

    v = D.resultado_por_volume(np.array(ts), np.array(liq))
    por_faixa = dict(zip(v["chaves"], v["liquido"]))

    assert por_faixa["1"] == pytest.approx(1_000.0)
    assert por_faixa["6–10"] == pytest.approx(-4_000.0)
    assert dict(zip(v["chaves"], v["win_rate"]))["1"] == pytest.approx(100.0)
    assert dict(zip(v["chaves"], v["trades"]))["6–10"] == 80


def test_faixas_nao_repetem_o_mesmo_numero():
    """(1,2,3,5,10) tem que virar 1 / 2 / 3 / 4–5 / 6–10 / 11+, e não
    rótulos como '2–2'."""
    ts = np.array([np.datetime64("2023-04-03T10:00", "s")] * 4)
    v = D.resultado_por_volume(ts, np.full(4, 10.0))
    assert v["chaves"] == ["4–5"]
