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
