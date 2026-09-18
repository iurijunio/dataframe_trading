"""Testes do dimensionamento (etapa 3 da tela Candidata).

A disciplina de sempre: cada caso tem a resposta conhecida de antemão.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import tamanho  # noqa: E402

# 100 pregões: 5 de prejuízo (a cauda) e 95 de lucro miúdo.
CAUDA_5 = np.array([-100.0, -99.0, -98.0, -97.0, -96.0])
CURVA = np.concatenate([CAUDA_5, np.full(95, 10.0)])
PERFIL = {"stop_tipo": "pontos", "stop_pontos": 300, "max_trades_dia": 3}


def test_por_contrato_divide_pelo_tamanho_do_backtest():
    """O backtest rodou com 2 contratos; a conta de tamanho precisa da perda
    de UM contrato, senão dimensionar em cima dela conta o mesmo contrato
    duas vezes."""
    pnl = np.array([-200.0, 100.0, -50.0])
    assert list(tamanho.por_contrato(pnl, 2)) == [-100.0, 50.0, -25.0]


def test_por_contrato_com_zero_nao_divide_por_zero():
    """Perfil sem contratos gravados (registro antigo) não pode virar inf."""
    assert list(tamanho.por_contrato(np.array([-200.0]), 0)) == [-200.0]


# ----------------------------------------------------------------- a cauda
def test_cvar_pregao_e_a_media_dos_piores_nao_o_pior():
    """Em 100 dias, os 5 piores valendo -100 a -96: a média deles é -98, não
    -100. Usar o pior aqui seria outra conta, e a tela promete a média."""
    assert tamanho.cvar_pregao(CURVA)["valor"] == pytest.approx(-98.0)


def test_cvar_pregao_diz_a_fracao_que_realmente_usou():
    """67 pregões: 5% arredondado para cima são 4 dias, que são 6%. Escrever
    '5%' na tela quando a conta usou 6% é prometer o que não foi feito."""
    r = tamanho.cvar_pregao(np.arange(67, dtype=float) - 40.0)
    assert r["quantos"] == 4
    assert r["fracao"] == pytest.approx(4 / 67)


def test_cvar_pregao_com_amostra_curta_recusa_em_vez_de_virar_o_pior():
    """Com 20 pregões, 5% arredondado para cima ainda é UM dia: a 'média dos
    piores' seria o pior, e a tela estaria mentindo sobre a própria conta.
    21 é o primeiro tamanho em que a cauda tem dois dias."""
    assert tamanho.cvar_pregao(np.full(20, -10.0))["valor"] is None
    r = tamanho.cvar_pregao(np.full(21, -10.0))
    assert r["valor"] == pytest.approx(-10.0) and r["quantos"] == 2


def test_cvar_pregao_sem_dado_nao_inventa():
    assert tamanho.cvar_pregao(np.array([]))["valor"] is None


def test_cvar_pregao_com_dia_sem_valor_recusa_e_explica():
    """NaN some em silêncio dentro de média e de mínimo, e ainda vaza para a
    tela como 'nan' — que nem é JSON válido."""
    x = np.concatenate([CURVA, [np.nan]])
    r = tamanho.cvar_pregao(x)
    assert r["valor"] is None and "sem valor" in r["motivo"]


# -------------------------------------------------- quantos stops no dia
def test_stops_do_dia_vale_o_menor_limite_ligado():
    """Num dia só de stops toda operação é perdedora, então os dois limites
    contam a mesma coisa e o motor para no que vier primeiro. Preferir o
    teto de prejuízos por ser mais específico inflava a referência: com 6
    prejuízos e 2 operações, o dia acaba em 2."""
    assert tamanho.stops_do_dia({"max_prejuizos_dia": 2, "max_trades_dia": 6}) == 2
    assert tamanho.stops_do_dia({"max_prejuizos_dia": 6, "max_trades_dia": 2}) == 2


def test_stops_do_dia_zero_e_desligado_nao_e_um():
    """Zero significa SEM limite no motor. Tratar como 1 faria o perfil mais
    perigoso receber a referência de risco mais branda de todas."""
    perfil = {"max_prejuizos_dia": 0, "max_trades_dia": 0}
    assert tamanho.stops_do_dia(perfil) is None
    assert tamanho.stops_do_dia(perfil, observado=5) == 5


# ------------------------------------------------ o dia ruim de execução
def test_dia_ruim_usa_todos_os_stops_e_dobra_o_ultimo():
    """3 stops de 300 pontos a R$ 0,20 por ponto = R$ 60 cada. Dois cheios
    mais um com o dobro: 60 × 4 = 240."""
    assert tamanho.dia_ruim(PERFIL, 0.20) == pytest.approx(240.0)


def test_dia_ruim_soma_o_custo_dos_giros():
    """Os outros candidatos são líquidos de custo; este precisa ser também,
    senão compara bruto com líquido."""
    assert tamanho.dia_ruim(PERFIL, 0.20, custo_por_trade=3.0) == \
        pytest.approx(249.0)


def test_dia_ruim_respeita_o_limite_de_perda_do_dia():
    """O motor para o pregão quando a perda do dia bate o limite; só o
    estouro do trade que o atingiu passa. Sem isso, a referência ignora a
    trava que o próprio perfil já tem."""
    perfil = {**PERFIL, "max_trades_dia": 10, "limite_perda_contrato": 100.0}
    assert tamanho.dia_ruim(perfil, 0.20) == pytest.approx(220.0)


def test_dia_ruim_sem_limite_nenhum_usa_o_que_a_curva_mostrou():
    perfil = {"stop_tipo": "pontos", "stop_pontos": 300, "max_trades_dia": 0}
    assert tamanho.dia_ruim(perfil, 0.20) is None
    assert tamanho.dia_ruim(perfil, 0.20, trades_no_dia=2) == \
        pytest.approx(180.0)


def test_dia_ruim_com_stop_por_atr_nao_e_medido():
    """Stop em múltiplo de ATR não tem tamanho fixo em reais: sem medida,
    devolve nada em vez de fingir que o campo em pontos vale."""
    assert tamanho.dia_ruim({**PERFIL, "stop_tipo": "atr"}, 0.20) is None


def test_dia_ruim_sem_valor_do_ponto_nao_e_medido():
    assert tamanho.dia_ruim(PERFIL, None) is None


def test_trava_do_indice_e_aviso_de_tela_com_a_conta_do_leilao():
    """Índice em 130.000 pontos, trava de 10% a R$ 0,20 por ponto:
    R$ 2.600 por contrato. Dez vezes o dia ruim de execução — por isso ela
    avisa e não dimensiona."""
    assert tamanho.trava_do_indice(130_000.0, 0.20) == pytest.approx(2600.0)
    assert tamanho.trava_do_indice(None, 0.20) is None


# ------------------------------------------------- a perda de referência
def test_perda_referencia_vale_o_pior_dos_dois_candidatos():
    """Cauda de R$ 98 contra dia ruim de R$ 240: dimensiona pelo dia ruim.
    Escolher o mais confortável dos dois seria escolher o número bonito."""
    r = tamanho.perda_referencia(CURVA, 1, PERFIL, 0.20)
    assert r["valor"] == pytest.approx(240.0)
    assert r["de_onde"].startswith("um dia ruim de execução")


def test_perda_referencia_pode_vir_da_cauda():
    """Cauda funda (R$ 500) contra dia ruim raso (R$ 240): agora manda a
    cauda. É o candidato que o desenho elegeu, e ele precisa poder ganhar."""
    curva = np.concatenate([np.full(5, -500.0), np.full(95, 10.0)])
    r = tamanho.perda_referencia(curva, 1, PERFIL, 0.20)
    assert r["valor"] == pytest.approx(500.0)
    assert r["de_onde"] == "a média dos 5% piores pregões"


def test_pior_dia_e_leitura_e_nao_dimensiona():
    """Um dia isolado de -900 é pior que tudo, e mesmo assim não manda no
    tamanho: ele é um recorde, piora sozinho conforme o histórico cresce e
    um registro torto passaria a decidir a posição. Decisão de 18/09/2026."""
    curva = np.concatenate([[-900.0], CAUDA_5[1:], np.full(95, 10.0)])
    r = tamanho.perda_referencia(curva, 1, PERFIL, 0.20)
    assert r["pior_dia"] == pytest.approx(-900.0)
    # o recorde entra na média da cauda (900+99+98+97+96)/5 = 258 e pesa por
    # ali — o que não acontece é ele dimensionar sozinho, com os R$ 900
    assert r["valor"] == pytest.approx(258.0)
    assert r["de_onde"] == "a média dos 5% piores pregões"


def test_perda_referencia_desconta_os_contratos_do_backtest():
    """A curva veio de 2 contratos: a referência é a de 1. Sem stop em
    pontos, quem responde é a cauda — e ela cai pela metade."""
    curva = np.concatenate([np.full(5, -1000.0), np.full(95, 20.0)])
    r = tamanho.perda_referencia(curva, 2, {}, 0.20)
    assert r["valor"] == pytest.approx(500.0)


def test_perda_referencia_recusa_curva_de_posicao_variavel():
    """No modo de risco fixo a quantidade muda a cada trade: dividir por um
    número fixo de contratos infla a referência sem avisar."""
    r = tamanho.perda_referencia(CURVA, 1, {"modo_posicao": "risco_fixo"},
                                 0.20)
    assert r["valor"] is None and "posição variável" in r["motivo"]


def test_perda_referencia_sem_pregao_nenhum_nao_e_medida():
    r = tamanho.perda_referencia(np.array([]), 1, {}, 0.20)
    assert r["valor"] is None and r["motivo"]


def test_perda_referencia_sem_nenhum_dia_de_prejuizo_nao_e_medida():
    """Curva sem cauda negativa e sem stop em pontos: não há referência, e
    inventar zero faria a conta de contratos explodir."""
    r = tamanho.perda_referencia(np.full(50, 10.0), 1, {}, 0.20)
    assert r["valor"] is None and "cauda de prejuízo" in r["motivo"]


def test_recusar_dimensionar_nao_apaga_as_leituras_que_existem():
    """Curva curta demais para a cauda: não se dimensiona, mas o pior dia e
    o dia ruim de execução continuam medidos — o dia ruim nem sai da curva.
    Apagá-los faria a tela escrever 'não medido' sobre número medido."""
    r = tamanho.perda_referencia(np.full(10, -50.0), 1, PERFIL, 0.20)
    assert r["valor"] is None and r["motivo"]
    assert r["pior_dia"] == pytest.approx(-50.0)
    assert r["dia_ruim"] == pytest.approx(240.0)


def test_perda_referencia_minuscula_e_recusada_pelo_piso():
    """Uma cauda de um centavo daria 100.000 contratos com 1% de risco em
    R$ 100.000. Abaixo do menor movimento do instrumento, não se mede."""
    curva = np.concatenate([np.full(5, -0.01), np.full(95, 10.0)])
    r = tamanho.perda_referencia(curva, 1, {}, 0.20, piso=1.0)
    assert r["valor"] is None and "sem sentido" in r["motivo"]


# ------------------------------------------------------ quantos contratos
def test_contratos_pelo_risco_arredonda_para_baixo():
    """R$ 100.000 com 1% são R$ 1.000 de risco; perda de referência de
    R$ 300 por contrato dá 3,33 — operam-se 3, nunca 4."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0)
    assert r["n"] == 3 and r["por_risco"] == 3 and r["limite"] == "risco"
    # e 3,75 também são 3: arredondar para o mais perto passaria do risco
    # pedido, que é justamente o número que não pode ser ultrapassado
    assert tamanho.contratos(100_000.0, 1.0, 266.67)["n"] == 3


def test_risco_efetivo_e_do_inteiro_nao_do_fracionario():
    """3 contratos × R$ 300 = R$ 900, que são 0,9% do capital. Mostrar o 1%
    pedido seria mentira confortável: entre 1 e 2 contratos o risco dobra."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0)
    assert r["risco_efetivo_pct"] == pytest.approx(0.9)
    assert r["risco_pedido_pct"] == 1.0


def test_margem_pode_ser_o_limite_e_a_tela_precisa_saber_qual_foi():
    """O risco daria 3 contratos; com metade de R$ 100.000 disponível para
    garantia e margem de R$ 20.000 por contrato, só cabem 2."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=20_000.0)
    assert r["n"] == 2 and r["por_margem"] == 2 and r["limite"] == "margem"
    assert r["risco_efetivo_pct"] == pytest.approx(0.6)


def test_margem_nao_informada_nao_vira_zero_nem_bloqueia():
    """Margem em branco é dado que falta, não garantia de graça: o limite
    passa a ser o risco, e a tela avisa que a margem não foi conferida."""
    for vazia in (None, 0.0):
        r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=vazia)
        assert r["por_margem"] is None and r["n"] == 3
        assert r["limite"] == "risco"


def test_folga_de_margem_e_metade_do_capital_por_padrao():
    """Usar 100% do capital como garantia deixa a conta sem folga para o
    prejuízo do próprio dia. Com margem de R$ 25.000, cabem 2, não 4."""
    r = tamanho.contratos(100_000.0, 5.0, 300.0, margem=25_000.0)
    assert r["por_margem"] == 2
    r_cheio = tamanho.contratos(100_000.0, 5.0, 300.0, margem=25_000.0,
                                uso_margem_pct=100.0)
    assert r_cheio["por_margem"] == 4


def test_zero_contratos_pelo_risco_e_reprovacao_explicita():
    """R$ 5.000 com 1% são R$ 50, contra perda de referência de R$ 300: nem
    o contrato mínimo cabe. Não é erro, é reprovação por capital."""
    r = tamanho.contratos(5_000.0, 1.0, 300.0)
    assert r["n"] == 0 and r["risco_efetivo_pct"] is None
    assert "1 contrato já arrisca" in r["motivo"]


def test_zero_contratos_pela_margem_diz_que_foi_a_garantia():
    """O risco comportaria 3; a garantia exigida é maior que a parte do
    capital reservada para ela. O motivo precisa dizer qual das duas contas
    zerou, senão o usuário mexe no dial errado."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=60_000.0)
    assert r["n"] == 0 and "garantia" in r["motivo"]


def test_capital_precisa_pagar_garantia_e_prejuizo_do_dia_juntos():
    """R$ 100.000, garantia de R$ 8.000 e perda de referência de R$ 2.000:
    risco (5%) daria 2, margem daria 6, mas 2 contratos pedem R$ 16.000 de
    garantia mais R$ 4.000 de prejuízo — cabe. Com garantia de R$ 45.000, as
    duas contas separadas ainda dariam 1, e o capital não paga os dois."""
    r = tamanho.contratos(100_000.0, 5.0, 2_000.0, margem=8_000.0)
    assert r["por_folga"] == 10 and r["n"] == 2
    apertado = tamanho.contratos(100_000.0, 60.0, 60_000.0, margem=45_000.0)
    assert apertado["por_risco"] == 1 and apertado["por_margem"] == 1
    assert apertado["n"] == 0 and "ao mesmo tempo" in apertado["motivo"]


def test_empate_entre_as_contas_aparece_no_limite():
    """Dizer só 'risco' quando a margem também travou faz o usuário subir o
    risco e não ver contrato nenhum a mais, sem explicação."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=16_000.0)
    assert r["por_risco"] == 3 and r["por_margem"] == 3
    assert "risco" in r["limite"] and "margem" in r["limite"]


def test_quando_as_duas_contas_zeram_o_motivo_fala_das_duas():
    """Culpar só a garantia manda o usuário mexer num dial que não resolve,
    porque o risco também zerou."""
    r = tamanho.contratos(5_000.0, 1.0, 300.0, margem=60_000.0)
    assert r["n"] == 0
    assert "arrisca mais" in r["motivo"] and "garantia" in r["motivo"]


def test_garantia_negativa_e_recusada_em_vez_de_virar_numero():
    """Entrada inválida produzia 'por_margem: -500' na tela."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=-100.0)
    assert r["n"] == 0 and r["por_margem"] is None
    assert "negativa" in r["motivo"]


def test_folga_de_garantia_fora_da_faixa_e_recusada():
    """Com 0% a conta da margem zera e a mensagem culparia a corretora,
    quando a culpa é do dial."""
    for pct in (0.0, 120.0):
        r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=1_000.0,
                              uso_margem_pct=pct)
        assert r["n"] == 0 and "entre 0% e 100%" in r["motivo"]


def test_risco_efetivo_nunca_passa_do_pedido():
    """Invariante que pega uma classe inteira de erro: o inteiro é piso, e
    piso nunca ultrapassa o limite pedido."""
    for perda in (37.0, 300.0, 1_234.56, 4_999.0):
        for pedido in (0.5, 1.0, 2.5):
            r = tamanho.contratos(100_000.0, pedido, perda)
            if r["n"] > 0:
                assert r["risco_efetivo_pct"] <= pedido + 1e-9


# ----------------------------------------------- quando reduzir e desligar
def _leitura(quedas=None, seguidas=8.0, submerso=30.0, h=126, boot12=None):
    """Uma leitura de robustez como a produção monta: os percentis saem da
    distribuição de quedas, não são números soltos ao lado dela.

    `quedas` de 0 a 2.000 em 1.001 passos: o limite de 5% de alarme falso é
    R$ 1.900, o de 20% é R$ 1.600, e a conta é conferível no papel.
    """
    q = np.linspace(0, 2000, 1001) if quedas is None else np.asarray(quedas)
    boot = {"dd_p50": float(np.percentile(q, 50)),
            "dd_p95": float(np.percentile(q, 95)),
            "perdas_seguidas_p95": seguidas, "submerso_p95": submerso,
            "horizonte": h, "quedas": q,
            # a faixa do acumulado, pregão a pregão, no pior décimo
            "envelope_p10": np.linspace(-10.0, -200.0, h)}
    return {"boot": boot, "boot_12m": boot12 or {}}


def _boot12(quedas, seguidas=12.0, submerso=40.0, h=126):
    q = np.asarray(quedas)
    return {"dd_p50": float(np.percentile(q, 50)),
            "dd_p95": float(np.percentile(q, 95)),
            "perdas_seguidas_p95": seguidas, "submerso_p95": submerso,
            "horizonte": h, "quedas": q,
            "envelope_p10": np.linspace(-50.0, -900.0, h)}


def test_limite_sai_da_taxa_de_alarme_falso_escolhida():
    """Escolhe-se com que frequência o disjuntor pode disparar numa
    estratégia sadia; o valor em reais é consequência. O contrário — fixar o
    percentil e depois medir a chance contra o mesmo sorteio — dava sempre
    o mesmo número e não calibrava nada."""
    q = np.linspace(0, 2000, 1001)
    assert tamanho.limite_por_alarme(q, 5.0) == pytest.approx(1900.0)
    assert tamanho.limite_por_alarme(q, 20.0) == pytest.approx(1600.0)
    assert tamanho.limite_por_alarme([], 5.0) is None
    assert tamanho.limite_por_alarme(q, 0.0) is None


def test_disjuntor_escala_com_os_contratos():
    """O sorteio mede 1 contrato. Operando 3, os limites são 3× — senão o
    disjuntor dispara no primeiro tropeço."""
    d = tamanho.disjuntor(_leitura(), 100_000.0, 3, {})
    assert d["nivel2"]["queda"] == pytest.approx(5700.0)     # 1.900 × 3
    assert d["nivel2"]["pct"] == pytest.approx(5.7)
    assert d["nivel1"]["queda"] == pytest.approx(4800.0)     # 1.600 × 3
    assert d["nivel1"]["faixa_por_pregao"][-1] == pytest.approx(-600.0)


def test_apertar_o_alarme_aperta_o_limite_de_verdade():
    """O dial precisa mexer no número: com 1% de alarme falso o limite sobe,
    com 40% desce. Era isso que o desenho antigo não conseguia mostrar."""
    solto = tamanho.disjuntor(_leitura(), 100_000.0, 1, {},
                              alarme_desligar=1.0)
    apertado = tamanho.disjuntor(_leitura(), 100_000.0, 1, {},
                                 alarme_desligar=40.0)
    assert solto["nivel2"]["queda"] > apertado["nivel2"]["queda"]
    assert solto["nivel2"]["risco_de_desligar_pct"] == pytest.approx(1.0, abs=0.5)
    assert apertado["nivel2"]["risco_de_desligar_pct"] == pytest.approx(40.0, abs=0.5)


def test_reduzir_dispara_antes_de_desligar():
    """Reduzir é barato e reversível, desligar não: o nível 1 tem que vir
    antes, e com alarme falso mais frequente."""
    d = tamanho.disjuntor(_leitura(), 100_000.0, 2, {})
    assert d["nivel1"]["queda"] < d["nivel2"]["queda"]
    assert d["nivel1"]["alarme_pct"] > d["nivel2"]["alarme_pct"]


def test_os_dois_limites_saem_do_mesmo_recorte():
    """Tirar o limite de reduzir de um recorte e o de desligar do outro pode
    inverter os níveis. Aqui o recorte de 12 meses é o pior, e é dele que os
    DOIS limites e a faixa por pregão têm de vir."""
    d = tamanho.disjuntor(_leitura(boot12=_boot12(np.linspace(0, 3000, 1001))),
                          100_000.0, 1, {})
    assert d["recorte"] == "últimos 12 meses"
    assert d["nivel2"]["queda"] == pytest.approx(2850.0)     # 95% de 3.000
    assert d["nivel1"]["queda"] == pytest.approx(2400.0)     # 80% de 3.000
    assert d["nivel1"]["faixa_por_pregao"][-1] == pytest.approx(-900.0)


def test_leituras_independentes_valem_o_pior_recorte_de_cada_uma():
    """'Dias perdendo seguidos' e 'dias sem novo topo' não são limites que
    precisam ficar em ordem entre si: valem o pior de cada métrica, que é a
    regra do bloco 1 — mesmo quando a queda ruim veio do outro recorte."""
    boot12 = _boot12(np.linspace(0, 500, 1001), seguidas=12.0, submerso=40.0)
    d = tamanho.disjuntor(_leitura(boot12=boot12), 100_000.0, 1, {})
    assert d["recorte"] == "curva inteira"      # a queda ruim veio daqui
    assert d["nivel1"]["perdas_seguidas"] == 12  # e estas, do outro recorte
    assert d["dias_sem_topo"] == 40


def test_limites_do_dia_zerados_no_perfil_viram_nao_definido():
    """Zero é limite desligado no motor: mostrar 'R$ 0' faria a tela prometer
    uma trava que não existe."""
    perfil = {"limite_perda_contrato": 0.0, "max_trades_dia": 0}
    d = tamanho.disjuntor(_leitura(), 100_000.0, 2, perfil)
    assert d["limite_dia_reais"] is None and d["limite_dia_trades"] is None


def test_limites_do_dia_multiplicam_pelos_contratos():
    perfil = {"limite_perda_contrato": 150.0, "max_trades_dia": 3}
    d = tamanho.disjuntor(_leitura(), 100_000.0, 2, perfil)
    assert d["limite_dia_reais"] == pytest.approx(300.0)
    assert d["limite_dia_trades"] == 3


def test_sem_contratos_nao_ha_disjuntor():
    """Zero e negativo: número de contratos inválido produzia limite
    negativo, ou seja, 'desligar quando ganhar'."""
    for n in (0, -3):
        d = tamanho.disjuntor(_leitura(), 100_000.0, n, {})
        assert d["nivel2"]["queda"] is None and d["motivo"]


def test_sem_sorteio_nao_inventa_limite():
    """Leitura sem bootstrap (curva curta demais): não há limite para
    calcular, e zero seria desligar antes de começar."""
    d = tamanho.disjuntor({"boot": {}, "boot_12m": {}}, 100_000.0, 2, {})
    assert d["nivel2"]["queda"] is None and d["motivo"]


def test_sorteio_sem_as_quedas_guardadas_tambem_recusa():
    leitura = {"boot": {"dd_p95": 1000.0, "horizonte": 126}, "boot_12m": {}}
    d = tamanho.disjuntor(leitura, 100_000.0, 2, {})
    assert d["nivel2"]["queda"] is None and "quedas" in d["motivo"]


def test_quedas_todas_zero_nao_viram_limite_zero():
    """Curva sem queda nenhuma no sorteio: prometer 'desligar quando a queda
    chegar a R$ 0' é desligar antes do primeiro trade."""
    d = tamanho.disjuntor(_leitura(quedas=np.zeros(100)), 100_000.0, 2, {})
    assert d["nivel2"]["queda"] is None and d["nivel2"]["pct"] is None
    assert d["nivel2"]["risco_de_desligar_pct"] is None


def test_disjuntor_sem_capital_nao_divide_por_zero():
    d = tamanho.disjuntor(_leitura(), 0.0, 2, None)
    assert d["nivel2"]["queda"] is not None and d["nivel2"]["pct"] is None


def test_sem_perda_de_referencia_nao_inventa_contratos():
    r = tamanho.contratos(100_000.0, 1.0, None)
    assert r["n"] == 0 and r["risco_efetivo_pct"] is None and r["motivo"]


def test_sem_capital_ou_sem_risco_pedido_nao_mede():
    assert tamanho.contratos(0.0, 1.0, 300.0)["n"] == 0
    assert tamanho.contratos(100_000.0, 0.0, 300.0)["motivo"]
    assert tamanho.contratos(100_000.0, -1.0, 300.0)["n"] == 0
