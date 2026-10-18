"""Virar a mão na demo (`strategies/saida.py`, modo 2).

No minuto da virada o papel passa de "comprado na operação A" para
"vendido na operação B". A conta é hedging: mandar a venda de B com A ainda
aberta deixaria as duas posições vivas ao mesmo tempo. A regra: A sai
antes; B só entra com A fora da conta — e B não pode se perder por isso.
"""
from datetime import date, datetime, timedelta

from core import corretora as K
from core.ordens import Motor, planejar
from core.papel_vivo import POSICAO, Desejado
from tests.mt5_falso import MT5Ordens

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
TB = T + timedelta(minutes=5)
A = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)
B = Desejado(POSICAO, lado=-1, entry_ts=TB, entry_px=189_100, stop_px=189_300,
             alvo_px=188_700, contratos=2)
INST = {"tick_size": 5, "point_value": 0.2}


def volta(m, mt5, desejados, agora):
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar(desejados, True, foto, m.diario(DIA), agora, 5, 60.0)
    m.executar(mt5, acoes, foto=foto, agora_srv=agora, simbolo="WINV26", desvio=10,
               pode_entrar=lambda a: (True, None), envio=True, conta_id=2,
               conectado_ha_s=60.0)
    return acoes


def _comprado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: A}, T + timedelta(seconds=1))
    (ta,) = mt5.posicoes
    mt5.agora = TB
    return mt5, m, ta


def _lados(mt5):
    return sorted(p.type for p in mt5.posicoes.values())


def _vigiar(mt5):
    """Registra, a cada envio, quantas posições da ligação estão abertas."""
    picos = []
    orig = mt5.order_send

    def espiao(req):
        r = orig(req)
        picos.append(len(mt5.posicoes))
        return r
    mt5.order_send = espiao
    return picos


def test_virada_sai_de_a_e_entra_em_b_na_mesma_volta(tmp_path):
    mt5, m, ta = _comprado(tmp_path)
    picos = _vigiar(mt5)
    acoes = volta(m, mt5, {4: B}, TB + timedelta(seconds=1))
    assert [a.tipo for a in acoes][:2] == ["sair", "entrar"]
    assert ta not in mt5.posicoes
    (tb,) = mt5.posicoes
    p = mt5.posicoes[tb]
    assert p.type == mt5.ORDER_TYPE_SELL and p.volume == 2
    assert max(picos) == 1                       # nunca A e B ao mesmo tempo
    ev = [e for e in m.diario(DIA).eventos if e["tipo"] == "executada"]
    assert [(e["entry_ts"], e["lado"], e["contratos"]) for e in ev] == \
        [(T, 1, 2), (TB, -1, 2)]


def test_saida_sem_resposta_segura_a_entrada_ate_a_sair(tmp_path):
    mt5, m, ta = _comprado(tmp_path)
    picos = _vigiar(mt5)
    mt5.roteiro = [None]                          # a saída de A fica sem resposta
    volta(m, mt5, {4: B}, TB + timedelta(seconds=1))
    assert _lados(mt5) == [mt5.ORDER_TYPE_BUY]    # B não foi junto
    # volta seguinte, antes do intervalo da nova saída: também não entra
    volta(m, mt5, {4: B}, TB + timedelta(seconds=1, milliseconds=500))
    assert _lados(mt5) == [mt5.ORDER_TYPE_BUY]
    # a saída sai na tentativa seguinte e B entra, dentro da janela
    volta(m, mt5, {4: B}, TB + timedelta(seconds=3))
    assert ta not in mt5.posicoes
    assert _lados(mt5) == [mt5.ORDER_TYPE_SELL]
    assert max(picos) == 1


def test_saida_recusada_nao_deixa_b_entrar_na_mesma_volta(tmp_path):
    mt5, m, ta = _comprado(tmp_path)
    mt5.roteiro = [10004]                          # requote na saída
    volta(m, mt5, {4: B}, TB + timedelta(seconds=1))
    assert list(mt5.posicoes) == [ta]
    volta(m, mt5, {4: B}, TB + timedelta(seconds=2, milliseconds=100))
    assert _lados(mt5) == [mt5.ORDER_TYPE_SELL]


def test_planejar_nao_pede_entrada_com_a_saida_da_anterior_em_espera(tmp_path):
    # a saída de A foi enviada há 0,5 s (intervalo de 1 s): o plano não
    # repete a saída e, por isso mesmo, não pode pedir a entrada de B
    mt5, m, ta = _comprado(tmp_path)
    m.diario(DIA).registrar("saida_enviando", quando=TB + timedelta(seconds=1),
                            ligacao_id=4, ticket=ta)
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar({4: B}, True, foto, m.diario(DIA),
                     TB + timedelta(seconds=1, milliseconds=500), 5, 60.0)
    assert [a.tipo for a in acoes] == []


# ------------------------------------------- sem virada: contrária na conta
# A (compra) segue na corretora — a saída dela foi tentada há meio segundo
# e espera o intervalo entre tentativas — quando o papel pede B (venda) como
# operação nova. A regra da virada vale igual: B não entra com A na conta.

def _tipos(m, mt5, agora):
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    return [a.tipo for a in planejar({4: B}, True, foto, m.diario(DIA), agora,
                                     5, 60.0)]


def _saida_em_espera(m, ta, agora):
    m.diario(DIA).registrar("saida_enviando",
                            quando=agora - timedelta(milliseconds=500),
                            ligacao_id=4, ticket=ta)


def test_contraria_na_conta_segura_a_entrada_ate_ela_sair(tmp_path):
    mt5, m, ta = _comprado(tmp_path)
    agora = TB + timedelta(seconds=1)
    _saida_em_espera(m, ta, agora)
    assert _tipos(m, mt5, agora) == []           # nem sai de novo, nem entra
    mt5.stopar(ta)                               # A sai pelo stop na corretora
    assert "entrar" in _tipos(m, mt5, TB + timedelta(seconds=10))


def test_contraria_que_nao_sai_deixa_a_entrada_perdida_apos_30_s(tmp_path):
    mt5, m, ta = _comprado(tmp_path)
    agora = TB + timedelta(seconds=29)
    _saida_em_espera(m, ta, agora)
    assert _tipos(m, mt5, agora) == []
    agora = TB + timedelta(seconds=31)
    _saida_em_espera(m, ta, agora)
    # passou a janela: B se perde mesmo com A presa na conta, em vez de
    # ficar "segurada" para sempre e entrar fora de hora quando A sair
    assert _tipos(m, mt5, agora) == ["perdida"]
