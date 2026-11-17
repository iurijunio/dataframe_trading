"""Testes da tendência pelas três médias com distância da abertura do dia."""

from __future__ import annotations

import numpy as np

from strategies import tendencia_medias_abertura

PARADO = (100, 101, 99, 100)
A_COMPRA = (100, 112, 100, 111)   # fecha 11 acima da abertura (100)
B_COMPRA = (111, 116, 110, 115)   # fecha acima da máxima de A (112)
SEGUE_COMPRA = (115, 118, 114, 116)
A_VENDA = (100, 100, 88, 89)
B_VENDA = (89, 90, 84, 85)        # fecha abaixo da mínima de A (88)


def _barras(*dias):
    ts, o, h, l, c = [], [], [], [], []
    for k, barras in enumerate(dias):
        base = np.datetime64(f"2026-03-{4 + k:02d}T09:00", "m")
        for i, (ab, ma, mi, fe) in enumerate(barras):
            ts.append(base + np.timedelta64(i, "m"))
            o.append(ab)
            h.append(ma)
            l.append(mi)
            c.append(fe)
    return {"ts": np.asarray(ts), "open": np.asarray(o), "high": np.asarray(h),
            "low": np.asarray(l), "close": np.asarray(c)}


def _params(**troca):
    p = {"ema_rapida": 2, "ema_intermediaria": 3, "ema_lenta": 4,
         "unidade_distancia": tendencia_medias_abertura.EM_PONTOS, "distancia_pontos": 10,
         "distancia_centesimos_pct": 0}
    p.update(troca)
    return p


def _sinais(*dias, **troca):
    return tendencia_medias_abertura.signals(_barras(*dias), _params(**troca))


def test_compra_no_candle_que_confirma_o_de_referencia():
    s = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA])
    assert list(np.flatnonzero(s.entry_long)) == [6]
    assert not s.entry_short.any()


def test_sem_romper_a_maxima_de_a_nao_compra():
    nao_rompe = (111, 112, 110, 112)  # fecha NA máxima de A, não acima
    s = _sinais([PARADO] * 5 + [A_COMPRA, nao_rompe])
    assert not s.entry_long.any()


def test_confirmacao_precisa_seguir_longe_da_abertura():
    perto = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA], distancia_pontos=16)
    assert not perto.entry_long.any()


def test_confirmacao_precisa_estar_acima_das_tres_medias():
    # o 1º fechamento alto prende a média de 40 lá em cima; as curtas voltam
    barras = [(100, 131, 99, 130)] + [PARADO] * 4 + [A_COMPRA, B_COMPRA]
    assert list(np.flatnonzero(_sinais(barras).entry_long)) == [6]
    assert not _sinais(barras, ema_lenta=40).entry_long.any()


def test_venda_e_o_espelho_da_compra():
    s = _sinais([PARADO] * 5 + [A_VENDA, B_VENDA])
    assert list(np.flatnonzero(s.entry_short)) == [6]
    assert not s.entry_long.any()


def test_fica_armada_enquanto_a_condicao_se_mantem():
    s = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA, SEGUE_COMPRA, SEGUE_COMPRA])
    assert list(np.flatnonzero(s.entry_long)) == [6, 7, 8]


def test_desarma_quando_volta_para_perto_da_abertura():
    volta = (116, 116, 104, 105)  # distância 5, abaixo dos 10
    s = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA, volta, SEGUE_COMPRA])
    # a barra 8 voltaria a atender, mas sem um par A-B novo não arma
    assert list(np.flatnonzero(s.entry_long)) == [6]


def test_desarma_quando_cruza_uma_media():
    # longe da abertura, mas sob a EMA 2; a máxima alta impede que ele
    # sirva de novo candle A para o seguinte
    abaixo_da_rapida = (115, 120, 110, 111)
    s = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA, abaixo_da_rapida, SEGUE_COMPRA])
    assert list(np.flatnonzero(s.entry_long)) == [6]


def test_virada_do_dia_desarma():
    dia1 = [PARADO] * 5 + [A_COMPRA, B_COMPRA]
    # 1º candle do dia 2: 30 acima da abertura dele e acima das médias,
    # mas sem candle anterior no pregão não há par A-B
    dia2 = [(100, 130, 100, 130), (130, 135, 129, 134)]
    s = _sinais(dia1, dia2)
    assert not s.entry_long[7]
    assert s.entry_long[8]


def test_abertura_do_dia_e_a_do_primeiro_candle_de_cada_pregao():
    dia1 = [PARADO] * 5 + [A_COMPRA, B_COMPRA]
    dia2 = [(200, 201, 199, 200)] * 5 + [(200, 200, 188, 189), (189, 190, 184, 185)]
    s = _sinais(dia1, dia2)
    assert list(np.flatnonzero(s.entry_long)) == [6]
    assert list(np.flatnonzero(s.entry_short)) == [13]


def test_distancia_em_centesimos_de_porcento_da_abertura():
    barras = [PARADO] * 5 + [A_COMPRA, B_COMPRA]
    # 1000 centésimos = 10% de 100 = 10 pontos: igual ao caso em pontos
    dez = _sinais(barras, unidade_distancia=tendencia_medias_abertura.EM_PORCENTO,
                  distancia_pontos=999, distancia_centesimos_pct=1000)
    longe = _sinais(barras, unidade_distancia=tendencia_medias_abertura.EM_PORCENTO,
                    distancia_centesimos_pct=1600)
    assert list(np.flatnonzero(dez.entry_long)) == [6]
    assert not longe.entry_long.any()


def test_em_pontos_ignora_o_campo_de_porcento():
    s = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA], distancia_centesimos_pct=5000)
    assert list(np.flatnonzero(s.entry_long)) == [6]


def test_ordem_dos_periodos_nao_importa():
    barras = [PARADO] * 5 + [A_COMPRA, B_COMPRA, SEGUE_COMPRA]
    a = _sinais(barras)
    b = _sinais(barras, ema_rapida=4, ema_lenta=2)
    assert np.array_equal(a.entry_long, b.entry_long)


def test_sem_saida_propria_por_padrao():
    s = _sinais([PARADO] * 5 + [A_COMPRA, B_COMPRA])
    assert not s.exit_long.any() and not s.exit_short.any() and not s.virar


def test_barras_vazias():
    s = tendencia_medias_abertura.signals(_barras([]), _params())
    assert len(s.entry_long) == 0


def test_aquecimento_cobre_a_media_mais_longa():
    assert tendencia_medias_abertura.aquecimento_barras(_params(ema_intermediaria=50)) == 20 * 50


def test_porcento_usa_a_abertura_de_cada_pregao():
    # dia 1 abre em 200, dia 2 em 100: 10% do dia 2 são 10 pontos (A fecha
    # 11 acima). Com a abertura do 1º dia, x seria 20 e não entraria
    dia1 = [(200, 201, 199, 200)] * 5
    dia2 = [PARADO] * 5 + [A_COMPRA, B_COMPRA]
    s = _sinais(dia1, dia2, unidade_distancia=tendencia_medias_abertura.EM_PORCENTO,
                distancia_centesimos_pct=1000)
    assert list(np.flatnonzero(s.entry_long)) == [11]


def test_candle_a_perto_da_abertura_nao_arma():
    a_perto = (100, 105, 100, 104)    # só 4 acima da abertura
    b_longe = (104, 116, 104, 115)    # rompe A e fica 15 acima
    s = _sinais([PARADO] * 5 + [a_perto, b_longe])
    assert not s.entry_long.any()
