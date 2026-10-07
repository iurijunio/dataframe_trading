"""Espaço de busca da mineração: faixa decimal completa e sem cópias."""
from core import optimizer as O


def test_faixa_decimal_chega_ao_ultimo_valor():
    """(2,3 - 2,0) / 0,1 = 2,9999... em ponto flutuante: o int() cortava o
    2,3 que a tela prometia."""
    esp = O.montar_espaco({"r": {"tipo": "float", "step": 0.1}},
                          {"r": {"on": True, "de": 2.0, "ate": 2.3, "passo": 0.1}})
    assert esp["r"] == [2.0, 2.1, 2.2, 2.3]


def test_faixa_decimal_sem_resto_de_ponto_flutuante():
    esp = O.montar_espaco({"r": {"tipo": "float", "step": 0.1}},
                          {"r": {"on": True, "de": 0.1, "ate": 0.3, "passo": 0.1}})
    assert esp["r"] == [0.1, 0.2, 0.3]        # não 0.30000000000000004


def test_campo_do_tipo_nao_escolhido_sai_da_varredura():
    """Multiplicador de ATR marcado com alvo em pontos: a tela só esconde o
    bloco, mas varrê-lo dava cópias idênticas (platô falso)."""
    esp = {"alvo_pontos": [100, 200], "alvo_atr_mult": [1.0, 2.0, 3.0],
           "alvo_razao": [1.5, 2.0], "stop_pontos": [100, 150],
           "stop_atr_periodo": [10, 20]}
    util = O.espaco_util(esp, {"alvo_tipo": "pontos", "stop_tipo": "pontos"})
    assert util == {"alvo_pontos": [100, 200], "alvo_atr_mult": [1.0],
                    "alvo_razao": [1.5], "stop_pontos": [100, 150],
                    "stop_atr_periodo": [10]}
    util = O.espaco_util(esp, {"alvo_tipo": "multiplicador", "stop_tipo": "atr"})
    assert util["alvo_razao"] == [1.5, 2.0]
    assert util["alvo_pontos"] == [100] and util["stop_pontos"] == [100]
    assert util["stop_atr_periodo"] == [10, 20]


def test_perfil_antigo_sem_o_campo_usa_o_padrao_do_motor():
    # sem filtro_adx gravado vale o padrão "tendencia": DI continua varrido
    util = O.espaco_util({"adx_filtro_di": [0, 1]}, {})
    assert util["adx_filtro_di"] == [0, 1]


def test_rango_nao_varre_di_nem_subindo():
    esp = {"adx_filtro_di": [0, 1], "adx_subindo": [0, 1]}
    util = O.espaco_util(esp, {"filtro_adx": "rango"})
    assert util == {"adx_filtro_di": [0], "adx_subindo": [0]}


def test_adx_desligado_vira_uma_combinacao_so():
    """Período ou limiar 0 desliga o filtro: as variações dos outros campos
    do ADX dão o mesmo resultado e ficam uma vez só."""
    esp = {"canal": [10, 20], "adx_periodo": [0, 14], "adx_limiar": [0, 20, 25],
           "adx_filtro_di": [0, 1]}
    combos = O.combinacoes_uteis(esp)
    desligados = [c for c in combos
                  if not (c["adx_periodo"] > 0 and c["adx_limiar"] > 0)]
    ligados = [c for c in combos if c not in desligados]
    # um desligado por canal; ligados: 2 canais x 1 período x 2 limiares x 2 DI
    assert len(desligados) == 2
    assert {c["canal"] for c in desligados} == {10, 20}
    assert len(ligados) == 8
    assert len(combos) == 10                  # eram 2 x 2 x 3 x 2 = 24


def test_sem_campos_de_adx_nada_e_podado():
    esp = {"canal": [10, 20], "stop_pontos": [100, 200]}
    assert O.combinacoes_uteis(esp) == O.combinacoes(esp)
