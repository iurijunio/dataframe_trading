from datetime import datetime
from types import SimpleNamespace as NS

from core import corretora as K
from tests.mt5_falso import MT5Ordens, _epoch

DIA = datetime(2026, 10, 9)


def test_fotografia_separa_por_magic_e_le_a_conta():
    mt5 = MT5Ordens()
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.abrir_manual(-1)                                   # à mão
    f = K.fotografar(mt5, DIA)
    assert [p.ligacao_id for p in f.posicoes] == [4, None]
    assert f.posicoes[0].lado == 1 and f.posicoes[1].lado == -1
    assert f.hedging and f.algo_ligado and f.login == 1193398927
    assert len(f.negocios) == 2 and f.negocios[0].entrada


def test_none_com_erro_e_volta_perdida():
    mt5 = MT5Ordens()
    mt5.erro_leitura = True
    assert K.fotografar(mt5, DIA) is None


def test_none_com_res_s_ok_vale_como_lista_vazia(monkeypatch):
    # a documentação não garante o que volta sem posição; com
    # last_error() == RES_S_OK (1) o None é "nenhuma"
    mt5 = MT5Ordens()
    monkeypatch.setattr(mt5, "orders_get", lambda **k: None)
    f = K.fotografar(mt5, DIA)
    assert f is not None and f.ordens == []


def test_none_do_historico_de_ordens_com_erro_e_volta_perdida(monkeypatch):
    mt5 = MT5Ordens()
    monkeypatch.setattr(mt5, "history_orders_get", lambda de, ate, **k: None)
    monkeypatch.setattr(mt5, "last_error", lambda: (-10004, "IPC"))
    assert K.fotografar(mt5, DIA) is None


def test_negocio_que_nao_e_compra_nem_venda_e_ignorado():
    mt5 = MT5Ordens()
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.negocios.append(NS(ticket=1, order=0, time=_epoch(mt5.agora), type=2,
                           entry=0, magic=0, position_id=0, reason=0, volume=0.0,
                           price=0.0, commission=0.0, swap=0.0, fee=0.0,
                           profit=5000.0, symbol=""))      # depósito
    f = K.fotografar(mt5, DIA)
    assert len(f.negocios) == 1 and f.negocios[0].resultado == 0.0


def test_ordens_pendentes_e_historico_trazem_a_hora_e_o_magic():
    mt5 = MT5Ordens()
    mt5.roteiro = [10008]
    req = K.pedido_entrada(mt5, simbolo="WINV26", lado=1, volume=1, preco=189_000,
                           magic_=K.magic(4), comentario="x", desvio=10,
                           preenchimento=2)
    mt5.order_send(req)
    f = K.fotografar(mt5, DIA)
    assert f.ordens[0]["ligacao_id"] == 4 and f.ordens[0]["quando"] == mt5.agora
    assert f.historico_ordens == [{"ticket": f.ordens[0]["ticket"],
                                   "magic": K.magic(4), "ligacao_id": 4,
                                   "quando": mt5.agora}]
    assert f.posicoes == []


def test_entrada_sem_sl_tp_abre_posicao_sem_protecao():
    mt5 = MT5Ordens()
    req = K.pedido_entrada(mt5, simbolo="WINV26", lado=1, volume=1, preco=189_000,
                           magic_=K.magic(4), comentario="x", desvio=10,
                           preenchimento=1)
    mt5.order_send(req)
    p = K.fotografar(mt5, DIA).posicoes[0]
    assert p.sl == 0.0 and p.tp == 0.0
    assert len(K.fotografar(mt5, DIA).historico_ordens) == 1
