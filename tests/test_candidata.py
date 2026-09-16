"""Testes da tela Candidata (passo 10 da metodologia).

A disciplina de sempre: cada caso tem a resposta conhecida de antemão.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata, wfa  # noqa: E402

CAP = 10_000.0


def test_chave_iguala_float_e_int_do_mesmo_ponto_da_grade():
    """O DEPLOY vem do JSON como 78.0; mining_trials gravou 78. Sem
    normalizar, a vizinhança não acha vizinho nenhum e não dá erro."""
    assert candidata.chave({"periodo_canal": 78.0, "folga": 9.0}) == \
        candidata.chave({"folga": 9, "periodo_canal": 78})


def test_chave_preserva_texto_e_booleano():
    k = dict(candidata.chave({"lado": "compra", "usa_trail": True, "n": 3.0}))
    assert k["lado"] == "compra" and k["usa_trail"] is True and k["n"] == 3.0


def test_por_pregao_enche_os_dias_parados_com_zero():
    """Quem opera pouco tinha Sharpe inflado: a série precisa dos zeros."""
    saida = np.array(["2024-03-04T15:00", "2024-03-06T10:00"],
                     dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([100.0, -40.0]))
    assert len(dias) == 3                       # 04, 05 e 06 de março
    assert list(pnl) == [100.0, 0.0, -40.0]


def test_por_pregao_soma_os_trades_do_mesmo_dia_e_pula_fim_de_semana():
    saida = np.array(["2024-03-08T10:00", "2024-03-08T16:00",
                      "2024-03-11T10:00"], dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([10.0, 5.0, -3.0]))
    assert len(dias) == 2                       # sexta e segunda
    assert list(pnl) == [15.0, -3.0]


def test_por_pregao_respeita_o_recorte_pedido():
    saida = np.array(["2024-03-04T10:00", "2024-04-01T10:00"],
                     dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([10.0, 20.0]),
                                     de="2024-03-01", ate="2024-04-01")
    assert pnl.sum() == 10.0                    # abril ficou fora
    assert len(dias) == 21


def test_risco_de_desligar_le_a_distribuicao_do_bootstrap():
    boot = {"quedas": np.array([100.0, 200.0, 300.0, 400.0])}
    assert candidata.risco_de_desligar(boot, 250.0) == pytest.approx(50.0)
    assert candidata.risco_de_desligar(boot, 1000.0) == 0.0
    assert candidata.risco_de_desligar({}, 100.0) is None
    # Igualdade importa: robô que encosta no limite foi desligado, não escapou
    assert candidata.risco_de_desligar(boot, 200.0) == pytest.approx(75.0)


def _trades_falsos(n=400, semente=1):
    rng = np.random.default_rng(semente)
    dias = np.arange(np.datetime64("2024-01-01"), np.datetime64("2025-12-31"))
    dias = dias[np.is_busday(dias)]
    escolha = np.sort(rng.choice(len(dias), size=n, replace=True))
    return [{"exit_ts": dias[i].astype("datetime64[s]").item(),
             "entry_ts": dias[i].astype("datetime64[s]").item(),
             "liquido": float(v), "custo": 3.5, "contratos": 1}
            for i, v in zip(escolha, rng.normal(15, 120, n))]


def test_leitura_robustez_usa_o_bootstrap_e_nao_a_permutacao():
    t = _trades_falsos()
    r = candidata.leitura_robustez(t, CAP)
    assert r["boot"]["dd_p95"] > 0
    assert r["boot"]["bloco"] >= 1
    # a permutação continua, mas como leitura à parte
    assert r["ordenacao"]["dd_p95"] > 0
    # o que discrimina permutação de bootstrap: SEM reposição, o lucro final
    # não muda — trocar `ordenacao` por outro bootstrap passaria pelas
    # asserções de cima (ambas têm "dd_p95") mas falharia aqui, porque
    # bootstrap faz o lucro final VARIAR entre trajetórias.
    liq_total = sum(x["liquido"] for x in t)
    assert r["ordenacao"]["lucro_final"] == pytest.approx(liq_total)
    assert r["resumo"]["trades"] == len(t)


def test_leitura_robustez_traz_o_recorte_de_12_meses():
    """O índice dobrou de escala dentro da amostra: o risco do regime atual
    não é o risco médio de cinco anos.

    `<=` deixava passar uma implementação que usasse a curva inteira nos
    dois recortes (os dois horizontes empatam em 519 pregões nos trades
    falsos daqui) — só o `<` estrito acusa que o corte de 12 meses foi
    esquecido. Mas `<` sozinho também deixa passar um recorte de 6 meses no
    lugar de 12 (também seria menor que o total): por isso comparamos com o
    número de pregões que `wfa.pregoes` — o mesmo contador que o resto da
    plataforma usa — dá para uma janela de exatamente um ano, com uma folga
    pequena para a borda do calendário.
    """
    t = _trades_falsos()
    r = candidata.leitura_robustez(t, CAP)
    assert r["boot_12m"]["horizonte"] < r["boot"]["horizonte"]

    ultimo = max(np.datetime64(x["exit_ts"], "D") for x in t)
    corte = ultimo - np.timedelta64(365, "D")
    esperado = wfa.pregoes(str(corte), str(ultimo + np.timedelta64(1, "D")))
    assert abs(r["boot_12m"]["horizonte"] - esperado) <= 2


def test_leitura_robustez_recusa_amostra_pequena():
    """Rótulo de 'amostra pequena' ao lado de um número preciso perde para o
    número — abaixo de 100 trades a tela não calcula."""
    assert candidata.leitura_robustez(_trades_falsos(n=80), CAP) == \
        {"erro": "menos de 100 trades fora da amostra"}


def test_limite_no_p95_deixa_cerca_de_cinco_por_cento_de_falso_desligamento():
    """É a razão de o número existir: desligar no p95 desliga uma estratégia
    sadia em 5% dos ciclos, e isso precisa estar escrito no plano."""
    rng = np.random.default_rng(5)
    dia = rng.normal(10, 100, 400)
    from core import robustez
    b = robustez.bootstrap(dia, 10_000.0, n=600, semente=8)
    assert candidata.risco_de_desligar(b, b["dd_p95"]) == pytest.approx(5.0, abs=1.5)


# ------------------------------------------------------- perfil do platô


def _trials(valores, lucros, dd=500.0):
    # a chave real de mining_trials é "dd" (via optimizer.carregar_salva),
    # não "max_dd" — usar o nome errado faz o fator de recuperação sair
    # sempre None e o portão se abster em silêncio
    return [{"params": {"periodo_canal": v}, "lucro": l, "dd": dd}
            for v, l in zip(valores, lucros)]


def test_perfil_plato_mede_a_largura_em_torno_do_deploy():
    """Platô largo: os vizinhos seguram o fator de recuperação. É isto que
    distingue região fértil de pico de sorte.

    Há um segundo pico isolado depois do buraco de cada lado (30 e 90): a
    contagem tem que PARAR no primeiro ponto que não segura o piso, não
    pular o buraco e continuar — senão um pico de sorte distante infla a
    largura do platô central, que é exatamente o erro que este bloco existe
    para não cometer.
    """
    trials = _trials([30, 40, 50, 60, 70, 80, 90],
                     [1000.0, 100.0, 100.0, 1000.0, 1000.0, 100.0, 1000.0])
    espaco = {"periodo_canal": [30, 40, 50, 60, 70, 80, 90]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 60.0})
    assert p["largura_esq"] == 0 and p["largura_dir"] == 1
    assert [x["atual"] for x in p["pontos"]] == \
        [False, False, False, True, False, False, False]


def test_perfil_plato_acha_o_deploy_mesmo_vindo_em_float():
    """78.0 do JSON tem que casar com o 78 gravado na mineração."""
    trials = _trials([76, 78, 80], [500.0, 600.0, 550.0])
    p = candidata.perfil_plato(trials, {"periodo_canal": [76, 78, 80]},
                               {"periodo_canal": 78.0})
    assert p["centro_fr"] == pytest.approx(600.0 / 500.0)


def test_perfil_plato_casa_deploy_com_ruido_de_ponto_flutuante():
    """78 + 1e-9 chega assim quando o valor atravessa uma conta de ponto
    flutuante a montante; sem arredondar o DEPLOY na mesma régua da grade
    (a mesma regra de `_valor` usada em `chave`), o casamento falha e o
    portão se abstém à toa, mesmo com o parâmetro batendo com a grade."""
    trials = _trials([76, 78, 80], [500.0, 600.0, 550.0])
    p = candidata.perfil_plato(trials, {"periodo_canal": [76, 78, 80]},
                               {"periodo_canal": 78.0 + 1e-9})
    assert p["centro_fr"] == pytest.approx(600.0 / 500.0)


def test_perfil_plato_abstem_quando_falta_um_terco_da_grade():
    """Mineração interrompida abre buraco no meio da grade, não só na borda
    — e portão que decide sobre grade furada decide sobre nada."""
    trials = _trials([40, 50], [100.0, 900.0])
    espaco = {"periodo_canal": [40, 50, 60, 70, 80]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 50})
    assert p["ausentes"] == 3 and p["abstem"]


def test_perfil_plato_sem_o_deploy_na_grade_nao_quebra():
    p = candidata.perfil_plato(_trials([40, 50], [1.0, 2.0]),
                               {"periodo_canal": [40, 50]},
                               {"periodo_canal": 99})
    assert p["centro_fr"] is None and p["abstem"]
