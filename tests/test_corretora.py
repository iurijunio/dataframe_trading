"""Tabela de retornos do MT5, pedidos e arredondamento (spec §5.2–5.4, §6)."""
from types import SimpleNamespace as NS

import pytest

from core import corretora as K
from tests.mt5_falso import MT5Ordens

# um teste por código: a classificação decide se a automação tenta de novo,
# espera, desiste ou chama o usuário — errar aqui é ordem duplicada ou perdida
CASOS = [
    (10004, K.PASSAGEIRA), (10006, K.PASSAGEIRA), (10007, K.PASSAGEIRA),
    (10008, K.ACEITA), (10009, K.OK), (10010, K.PARCIAL),
    (10011, K.PASSAGEIRA), (10012, K.INCERTA), (10013, K.USUARIO),
    (10014, K.USUARIO), (10015, K.USUARIO), (10016, K.STOPS_INVALIDOS),
    (10017, K.USUARIO), (10018, K.PASSAGEIRA), (10019, K.USUARIO),
    (10020, K.PASSAGEIRA), (10021, K.PASSAGEIRA), (10022, K.USUARIO),
    (10023, K.PASSAGEIRA), (10024, K.PASSAGEIRA), (10025, K.SEM_MUDANCA),
    (10026, K.USUARIO), (10027, K.USUARIO), (10028, K.PASSAGEIRA),
    (10029, K.PASSAGEIRA), (10030, K.PREENCHIMENTO), (10031, K.PASSAGEIRA),
    (10032, K.USUARIO), (10033, K.USUARIO), (10034, K.USUARIO),
    (10035, K.USUARIO), (10036, K.JA_SAIU), (10038, K.VOLUME_FECHAMENTO),
    (10039, K.SAIDA_EM_TRANSITO), (10040, K.USUARIO), (10041, K.PASSAGEIRA),
    (10042, K.USUARIO), (10043, K.USUARIO), (10044, K.USUARIO),
    (10045, K.USUARIO), (10046, K.USUARIO),
]


@pytest.mark.parametrize("codigo,classe", CASOS)
def test_cada_codigo_tem_classe(codigo, classe):
    assert K.classificar(NS(retcode=codigo)) == classe


def test_toda_a_documentacao_esta_na_tabela():
    # 10004..10046 menos 10005 e 10037, que a documentação não lista
    esperados = set(range(10004, 10047)) - {10005, 10037}
    assert set(K.RETORNOS) == esperados
    assert set(K.TEXTOS) == esperados


def test_none_e_incerta_e_codigo_estranho_e_desconhecido():
    # sem resposta: a ordem pode ter executado — reenviar sem conferir duplica
    assert K.classificar(None) == K.INCERTA
    assert K.classificar(NS(retcode=12345)) == K.DESCONHECIDO


def test_magic_ida_e_volta_e_fora_da_faixa():
    assert K.magic(4) == 7_000_004
    assert K.ligacao_do_magic(7_000_004) == 4
    assert K.ligacao_do_magic(0) is None            # ordem à mão
    assert K.ligacao_do_magic(7_000_000) is None
    assert K.ligacao_do_magic(8_000_000) is None


def test_preenchimento_pela_mascara_de_bits():
    mt5 = MT5Ordens()
    # a máscara NÃO é o valor de ORDER_FILLING_*: 3 = FOK|IOC
    assert K.modos_preenchimento(3, mt5) == [1, 0, 2]
    assert K.modos_preenchimento(2, mt5) == [1, 2]
    assert K.modos_preenchimento(1, mt5) == [0, 2]
    assert K.modos_preenchimento(0, mt5) == [2]     # RETURN sempre vale na bolsa


@pytest.mark.parametrize("lado,stop,alvo,esperado", [
    (1, 188_642, 189_663, (188_640, 189_665)),     # compra: stop p/ baixo, alvo p/ cima
    (-1, 188_642, 187_663, (188_645, 187_660)),    # venda: stop p/ cima, alvo p/ baixo
    (1, 188_640, 189_665, (188_640, 189_665)),     # já no tick: não mexe
    (1, None, 189_663, (None, 189_665)),
])
def test_protecao_arredonda_para_longe_da_entrada(lado, stop, alvo, esperado):
    assert K.protecao(lado, stop, alvo, 5) == esperado


def test_pedidos_tem_os_campos_da_documentacao():
    mt5 = MT5Ordens()
    e = K.pedido_entrada(mt5, simbolo="WINV26", lado=1, volume=2, preco=189_010,
                         magic_=7_000_004, comentario="df 10:01 4 " + "x" * 40,
                         desvio=10, preenchimento=1)
    assert e["action"] == 1 and e["type"] == 0 and e["volume"] == 2.0
    # execução em bolsa: sl/tp não são campos garantidos da ordem a mercado
    assert "sl" not in e and "tp" not in e and e["magic"] == 7_000_004
    assert len(e["comment"]) <= 31 and e["type_filling"] == 1 and e["type_time"] == 0
    s = K.pedido_saida(mt5, simbolo="WINV26", lado_posicao=1, volume=2, preco=189_245,
                       ticket=55, magic_=7_000_004, desvio=10, preenchimento=1)
    assert s["type"] == 1 and s["position"] == 55 and "sl" not in s
    p = K.pedido_protecao(mt5, simbolo="WINV26", ticket=55, sl=188_645, tp=None,
                          magic_=7_000_004)
    assert p == {"action": 6, "symbol": "WINV26", "position": 55, "sl": 188_645.0,
                 "tp": 0.0, "magic": 7_000_004}
    assert K.pedido_cancelar(mt5, ordem=99) == {"action": 8, "order": 99}
