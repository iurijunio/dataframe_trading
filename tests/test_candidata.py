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


# ------------------------------------- rodada de correção final: I2(b)


def test_leitura_robustez_repassa_horizonte_aos_dois_bootstraps():
    """Um dos dois bootstraps ficar sem o horizonte pedido destrava o
    disjuntor: o cartão mostraria o p95 do comprimento INTEIRO do recorte
    em vez do prazo até a próxima reotimização, e ninguém notaria porque o
    número ainda aparece na tela — só que calibrado para o prazo errado."""
    t = _trades_falsos()
    r = candidata.leitura_robustez(t, CAP, horizonte_pregoes=60)
    assert r["boot"]["horizonte"] == 60
    assert r["boot_12m"]["horizonte"] == 60


# ------------------------------------------- rodada de correção final: M4


def test_leitura_robustez_usa_limites_da_curva_quando_fornecidos():
    """Sem limites, a Candidata conta do primeiro ao último TRADE. O cartão
    do WFA e o Sharpe da matriz contam a extensão das JANELAS OOS reais,
    ignorando a linha DEPLOY — as duas contas só combinam quando todo
    pregão da janela teve trade, o que a mineração real não garante (no #3
    a diferença foi de 1.041 contra 1.044 pregões). Alargar de/ate além do
    primeiro e do último trade tem que aumentar a contagem de pregões."""
    t = _trades_falsos()
    datas = [np.datetime64(x["exit_ts"], "D") for x in t]
    de = str(min(datas) - np.timedelta64(5, "D"))
    ate = str(max(datas) + np.timedelta64(6, "D"))
    sem = candidata.leitura_robustez(t, CAP)
    com = candidata.leitura_robustez(t, CAP, de=de, ate=ate)
    assert com["pregoes"] > sem["pregoes"]


def test_limites_oos_ignora_a_linha_deploy():
    """O `oos_de`/`oos_ate` da linha DEPLOY é o futuro — ainda não
    aconteceu. Usá-los como limite da curva puxaria o fim do recorte para
    além do último trade real."""
    passos = [
        {"step": 1, "oos_de": "2023-01-02", "oos_ate": "2023-07-01"},
        {"step": 2, "oos_de": "2023-07-01", "oos_ate": "2024-01-01"},
        {"step": "DEPLOY", "oos_de": "2024-01-01", "oos_ate": "2024-07-01"},
    ]
    assert candidata.limites_oos(passos) == ("2023-01-02", "2024-01-01")


def test_limites_oos_sem_passos_devolve_none():
    assert candidata.limites_oos([]) == (None, None)
    assert candidata.limites_oos(None) == (None, None)
    assert candidata.limites_oos(
        [{"step": "DEPLOY", "oos_de": "x", "oos_ate": "y"}]) == (None, None)


# ------------------------------------------- rodada de correção final: I2(c)


def test_calcula_horizonte_com_deploy_usa_a_janela_projetada():
    d = {"deploy": {"oos_de": "2024-01-01", "oos_ate": "2024-04-01"},
        "oos_meses": 3}
    assert candidata.calcula_horizonte(d) == wfa.pregoes("2024-01-01",
                                                         "2024-04-01")


def test_calcula_horizonte_sem_deploy_aproxima_por_oos_meses():
    assert candidata.calcula_horizonte({"deploy": None, "oos_meses": 8}) == 168


def test_calcula_horizonte_sem_deploy_e_sem_oos_meses_usa_piso_de_seis_meses():
    assert candidata.calcula_horizonte({"deploy": None, "oos_meses": None}) \
        == 126


# ------------------------------------------- rodada de correção final: I1


def test_pior_dos_recortes_escolhe_por_metrica_nao_por_recorte_inteiro():
    """O bug que motivou a correção: só 'drawdown esperado' comparava os
    dois recortes; 'perdas seguidas' e 'pregões abaixo do topo' liam sempre
    `boot`. Aqui cada métrica tem o pior valor num recorte diferente — uma
    implementação que escolhesse um único "recorte vencedor" (por exemplo,
    pelo pior dd_p95) e aplicasse a mesma escolha às três métricas erraria
    pelo menos uma. Os números de perdas seguidas são os do walk-forward #3
    citados na correção: 15 na curva inteira, 17 nos últimos 12 meses."""
    leitura = {
        "boot": {"dd_p95": 500.0, "perdas_seguidas_p95": 15.0,
                "submerso_p95": 80.0},
        "boot_12m": {"dd_p95": 300.0, "perdas_seguidas_p95": 17.0,
                    "submerso_p95": 40.0},
    }
    r = candidata.pior_dos_recortes(leitura)
    assert r["dd_p95"] == {"valor": 500.0, "recorte": "curva inteira"}
    assert r["perdas_seguidas_p95"] == \
        {"valor": 17.0, "recorte": "últimos 12 meses"}
    assert r["submerso_p95"] == {"valor": 80.0, "recorte": "curva inteira"}


def test_pior_dos_recortes_usa_boot_quando_12m_vazio():
    leitura = {"boot": {"dd_p95": 500.0, "perdas_seguidas_p95": 4.0,
                       "submerso_p95": 80.0}, "boot_12m": {}}
    r = candidata.pior_dos_recortes(leitura)
    assert all(v["recorte"] == "curva inteira" for v in r.values())
    assert r["dd_p95"]["valor"] == 500.0


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


# ------------------------------------------- rodada de correção 1: bordas


def test_perfil_plato_borda_dir_quando_a_grade_acaba_sem_queda():
    """#40 em miniatura: FR se mantém alto até a última combinação
    minerada. `largura_dir == 2` sozinho parece "platô confirmado à
    direita", mas a caminhada só parou porque a grade acabou em 80 — não
    porque o FR caiu. `borda_dir` existe para separar essas duas histórias:
    sem ele, o portão da próxima fase confundiria "não testamos mais longe"
    com "testamos e resistiu"."""
    trials = _trials([40, 50, 60, 70, 80],
                     [3000.0, 3200.0, 3400.0, 3600.0, 3300.0])
    espaco = {"periodo_canal": [40, 50, 60, 70, 80]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 60})
    assert p["largura_dir"] == 2 and p["borda_dir"] is True
    assert p["largura_esq"] == 2 and p["borda_esq"] is True


def test_perfil_plato_borda_falsa_quando_ha_queda_real_antes_da_borda():
    """Mesma grade, mas agora o FR desmorona ANTES de chegar na borda: a
    caminhada para por causa da queda, não da grade acabando —
    `borda_dir` tem que vir `False`."""
    trials = _trials([40, 50, 60, 70, 80],
                     [3000.0, 3200.0, 3400.0, 500.0, 3300.0])
    espaco = {"periodo_canal": [40, 50, 60, 70, 80]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 60})
    assert p["largura_dir"] == 0 and p["borda_dir"] is False


# --------------------------------- rodada de correção 1: motivo diferente


def test_perfil_plato_motivo_diferencia_deploy_ausente_de_fr_indefinido():
    """`centro_fr is None` acontece por dois motivos bem diferentes: o
    DEPLOY não está na grade, ou está na grade mas o trial gravado não tem
    drawdown (dd <= 0) para calcular o fator de recuperação. Confundir os
    dois faz o motivo mentir — "o DEPLOY não está na grade" quando ele
    está."""
    fora = candidata.perfil_plato(_trials([40, 50], [1.0, 2.0]),
                                  {"periodo_canal": [40, 50]},
                                  {"periodo_canal": 99})
    sem_dd = [{"params": {"periodo_canal": 40}, "lucro": 100.0, "dd": 500.0},
              {"params": {"periodo_canal": 50}, "lucro": 200.0, "dd": 0.0}]
    presente = candidata.perfil_plato(sem_dd, {"periodo_canal": [40, 50]},
                                      {"periodo_canal": 50})
    assert fora["centro_fr"] is None and fora["abstem"]
    assert presente["centro_fr"] is None and presente["abstem"]
    assert "não está na grade" in fora["motivo"]
    assert "não está na grade" not in presente["motivo"]
    assert "fator de recuperação" in presente["motivo"]
    assert fora["motivo"] != presente["motivo"]


# --------------------------------- rodada de correção 1: FR negativo


def test_perfil_plato_abstem_quando_o_centro_da_prejuizo():
    """FR negativo inverte a régua: `piso = centro_fr * 0.6` fica ACIMA do
    centro (ex.: centro -0.4, piso -0.24), e vizinhos com FR melhor que o
    centro passam a contar como "abaixo do piso" — a função devolveria
    larguras com cara de válidas para uma região que é, na verdade, uma
    perda. Medir platô em torno de prejuízo não faz sentido: o portão tem
    que se abster, não inventar uma largura."""
    trials = _trials([40, 50, 60], [100.0, -200.0, 150.0])
    espaco = {"periodo_canal": [40, 50, 60]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 50})
    assert p["abstem"] is True
    assert p["centro_fr"] == pytest.approx(-0.4)
    assert "prejuízo" in p["motivo"]


# --------------------------------- rodada de correção 1: contrato de retorno


CHAVES_PERFIL = {"pontos", "centro_fr", "ausentes", "largura_esq",
                 "largura_dir", "borda_esq", "borda_dir", "parada_esq",
                 "parada_dir", "abstem", "motivo", "parametro"}


def test_perfil_plato_devolve_sempre_o_mesmo_conjunto_de_chaves():
    """A próxima fase liga um portão neste dicionário: se um ramo esquece
    uma chave, o consumidor que não checar `abstem` primeiro toma
    KeyError. Todo ramo devolve o mesmo contrato, com None nos campos que
    não fazem sentido naquele ramo."""
    casos = [
        # mais de um parâmetro varrido
        candidata.perfil_plato(_trials([40, 50], [1.0, 2.0]),
                               {"periodo_canal": [40, 50], "folga": [1, 2]},
                               {"periodo_canal": 40, "folga": 1}),
        # DEPLOY fora da grade
        candidata.perfil_plato(_trials([40, 50], [1.0, 2.0]),
                               {"periodo_canal": [40, 50]},
                               {"periodo_canal": 99}),
        # DEPLOY na grade, fr indefinido (dd <= 0)
        candidata.perfil_plato(
            [{"params": {"periodo_canal": 50}, "lucro": 200.0, "dd": 0.0}],
            {"periodo_canal": [40, 50]}, {"periodo_canal": 50}),
        # centro com prejuízo
        candidata.perfil_plato(_trials([40, 50, 60], [100.0, -200.0, 150.0]),
                               {"periodo_canal": [40, 50, 60]},
                               {"periodo_canal": 50}),
        # buraco grande na grade
        candidata.perfil_plato(_trials([40, 50], [100.0, 900.0]),
                               {"periodo_canal": [40, 50, 60, 70, 80]},
                               {"periodo_canal": 50}),
        # caso normal, sem abstenção
        candidata.perfil_plato(_trials([40, 50, 60, 70, 80],
                                       [100.0, 900.0, 1000.0, 950.0, 120.0]),
                               {"periodo_canal": [40, 50, 60, 70, 80]},
                               {"periodo_canal": 60.0}),
    ]
    for p in casos:
        assert set(p.keys()) == CHAVES_PERFIL
        # contrato explícito: motivo só é None quando não há abstenção
        assert (p["motivo"] is None) == (not p["abstem"])


# --------------------------------- rodada de correção 2: platô e vizinho


def _perfil_com(fr, deploy_idx, ausentes=()):
    valores = list(range(40, 40 + len(fr)))
    trials = [{"params": {"p": v}, "lucro": f * 100.0, "dd": 100.0}
              for i, (v, f) in enumerate(zip(valores, fr)) if i not in ausentes]
    return candidata.perfil_plato(trials, {"p": valores},
                                  {"p": float(valores[deploy_idx])})


def test_parada_distingue_queda_borda_e_buraco():
    p = _perfil_com([1, 5, 5, 5, 5], deploy_idx=3, ausentes=(1,))
    assert p["parada_dir"] == "borda"
    assert p["parada_esq"] == "buraco"
    q = _perfil_com([5, 1, 5, 5, 5, 5], deploy_idx=3)
    assert q["parada_esq"] == "queda"


def test_plato_reprova_so_por_queda_real():
    """Queda a um passo do centro reprova. Fim da faixa testada e ponto não
    minerado não reprovam — viram alerta."""
    queda = candidata.portoes_plato(_perfil_com([5, 1, 5, 5, 5, 5], 3))
    assert queda[0]["critico"] and queda[0]["ok"] is False
    borda = candidata.portoes_plato(_perfil_com([5, 5, 5, 5, 5], 3))
    assert borda[0]["ok"] is True
    assert borda[1]["critico"] is False and borda[1]["ok"] is False


def test_plato_largo_dos_dois_lados_passa_sem_alerta():
    p = candidata.portoes_plato(_perfil_com([5] * 9, 4))
    assert p[0]["ok"] is True and p[1]["ok"] is True


def test_alerta_vizinho_com_prejuizo():
    p = _perfil_com([5, 5, 5, -1, 5, 5, 5], 4)
    assert candidata.alerta_vizinho(p)["ok"] is False
    assert candidata.alerta_vizinho(_perfil_com([5] * 7, 3))["ok"] is True


# ------------------------------------------- portões que saem dos dados


def test_t_diario_conta_os_dias_parados():
    """Dias sem trade entram como zero: sem eles quem opera pouco parece firme.

    `t_diario` só calcula com 30 dias ou mais (amostra menor devolve 0.0 —
    é o próprio jeito da função de dizer "não dá para afirmar nada aqui").
    Por isso os dias OPERADOS de referência precisam ser >= 30: com só 4
    (como no rascunho original), `so_operados` cairia nesse piso e voltaria
    0.0 sempre, e a comparação pedida (com zeros fica pior que sem eles)
    nunca teria como falhar de verdade. Repetimos o mesmo padrão de
    variação (10, 12, 9, 11) até ter amostra suficiente — sem inventar
    outros números."""
    base = np.array([10.0, 12.0, 9.0, 11.0])
    so_operados = np.tile(base, 8)                    # 32 dias operados
    com_parados = np.concatenate([so_operados, np.zeros(40)])
    assert candidata.t_diario(com_parados) < candidata.t_diario(so_operados)


def test_portao_acaso():
    firme = np.full(250, 10.0) + np.random.default_rng(1).normal(0, 5, 250)
    ruido = np.random.default_rng(2).normal(0, 50, 250)
    assert candidata.portao_acaso(firme)["ok"] is True
    assert candidata.portao_acaso(ruido)["ok"] is False


def test_portao_poucos_dias():
    """Lucro que vive de 5 dias bons não é um sistema."""
    dependente = np.array([-2.0] * 100 + [60.0] * 5)
    espalhado = np.array([3.0] * 100 + [10.0] * 5)
    assert candidata.portao_poucos_dias(dependente)["ok"] is False
    assert candidata.portao_poucos_dias(espalhado)["ok"] is True


def test_portao_custo_um_tick_por_ponta():
    """510 trades de 1 contrato, 1 tick = R$ 1: custo extra R$ 1.020."""
    contratos = np.ones(510)
    assert candidata.portao_custo(1500.0, contratos, 1.0)["ok"] is True
    assert candidata.portao_custo(1000.0, contratos, 1.0)["ok"] is False


def test_portao_capital_por_contrato():
    """Perda de R$ 3.000 operando 2 contratos = R$ 1.500 por contrato."""
    assert candidata.portao_capital(3000.0, 2.0, 10_000.0)["ok"] is True
    assert candidata.portao_capital(3000.0, 1.0, 10_000.0)["ok"] is False


def test_veredito_pendente_nao_aprova():
    ok = candidata.portao("a", True, True, 1, "", "")
    pend = candidata.portao("b", None, True, None, "", "")
    alerta = candidata.portao("c", False, False, 1, "", "")
    reprova = candidata.portao("d", False, True, 1, "", "")
    assert candidata.veredito([ok, pend])["estado"] == "aguardando testes completos"
    assert candidata.veredito([ok, pend, reprova])["estado"] == "reprovada"
    assert candidata.veredito([ok, alerta])["estado"] == "aprovada com ressalva"
    assert candidata.veredito([ok])["estado"] == "aprovada"


# ------------------------------------- rodada de correção 1 da tarefa 2


def test_veredito_lista_vazia_nao_aprova():
    """Se nenhum portão chegou ao veredito (falha no cálculo de algum
    bloco), a tela não pode mostrar "aprovada" para uma estratégia que não
    foi testada em nada."""
    v = candidata.veredito([])
    assert v["estado"] == "aguardando testes completos"
    assert v["cor"] == "warn"


def test_portao_capital_sem_capital_nao_mede():
    """Capital 0 (ou negativo) faria `pct_` virar `inf`, que nem é JSON
    válido — e a tela mostraria "inf% do capital". Sem capital informado
    não dá para medir, então o portão fica pendente, não reprovado."""
    r = candidata.portao_capital(3000.0, 1.0, 0.0)
    assert r["ok"] is None
    assert r["valor"] == "capital não informado"


def test_portao_poucos_dias_com_poucos_pregoes_nao_reprova():
    """Tirar "os 5 melhores" de uma amostra com 3 dias zera a amostra
    inteira e reprova por falta de dado, não por resultado ruim."""
    r = candidata.portao_poucos_dias(np.array([10.0, 20.0, 30.0]), quantos=5)
    assert r["ok"] is None
    assert r["valor"] == "poucos pregões para medir"
