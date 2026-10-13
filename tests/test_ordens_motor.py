"""Executor (spec §5.2–5.4, §6): cada caso com o MT5 falso e o diário em tmp_path.

Os testes rodam `planejar` + `Motor.executar` como a captura vai rodar
(uma "volta"), e conferem o que foi ao MT5 (`mt5.enviados`), o que ficou
na conta (`mt5.posicoes`/`mt5.ordens`) e o que o diário gravou.
"""
from datetime import date, datetime, timedelta

import pytest

from core import corretora as K
from core.ordens import Acao, Motor, planejar
from core.papel_vivo import POSICAO, ZERADO, Desejado
from tests.mt5_falso import MT5Ordens

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
AG = T + timedelta(seconds=1)
D = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)
INST = {"tick_size": 5, "point_value": 0.2}


def volta(m, mt5, desejados, agora=AG, envio=True, pode=lambda a: (True, None),
          disponivel=True, simbolo="WINV26"):
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar(desejados, disponivel, foto, m.diario(DIA), agora, 5, 60.0)
    m.executar(mt5, acoes, foto=foto, agora_srv=agora, simbolo=simbolo, desvio=10,
               pode_entrar=pode, envio=envio, conta_id=2)
    return [e["tipo"] for e in m.diario(DIA).eventos]


def evs(m, tipo):
    return [e for e in m.diario(DIA).eventos if e["tipo"] == tipo]


def acoes_de(mt5, acao):
    return [r for r in mt5.enviados if r["action"] == acao]


# ------------------------------------------------------------------ entrada
def test_entrada_registra_antes_de_enviar_e_grava_o_ticket(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    tipos = volta(m, mt5, {4: D})
    assert tipos == ["enviando", "executada", "protecao_enviando", "protecao"]
    req, prot = mt5.enviados
    assert "sl" not in req and "tp" not in req and req["magic"] == K.magic(4)
    assert req["type_filling"] == mt5.ORDER_FILLING_IOC      # máscara 3 -> IOC primeiro
    assert req["deviation"] == 10 and req["price"] == 189_005   # compra no ask
    assert prot["action"] == 6 and prot["sl"] == 188_800 and prot["tp"] == 189_400
    ev = evs(m, "executada")[0]
    assert ev["ticket"] in mt5.posicoes and ev["atraso_ms"] == 1000
    assert ev["preco_papel"] == 189_000 and ev["conta_id"] == 2
    assert volta(m, mt5, {4: D}) == tipos                    # nada a mais


def test_enviando_esta_no_diario_no_instante_do_envio(tmp_path):
    # escrita adiantada: no order_send da entrada o arquivo já tem "enviando"
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    vistos = []
    orig = mt5.order_send

    def espiao(req):
        if req["action"] == 1 and "position" not in req:
            vistos.append([e["tipo"] for e in m.diario(DIA).eventos])
        return orig(req)
    mt5.order_send = espiao
    volta(m, mt5, {4: D})
    assert vistos == [["enviando"]]
    ev = evs(m, "enviando")[0]
    assert (ev["ligacao_id"], ev["entry_ts"], ev["lado"], ev["contratos"],
            ev["simbolo"]) == (4, T, 1, 2, "WINV26")


def test_atraso_e_medido_com_o_relogio_depois_da_resposta(tmp_path):
    mt5 = MT5Ordens()
    m = Motor(tmp_path, INST, relogio=lambda: T + timedelta(milliseconds=2500))
    volta(m, mt5, {4: D})
    assert evs(m, "executada")[0]["atraso_ms"] == 2500


def test_eventos_gravam_lado_stop_alvo_e_contratos_arredondados(tmp_path):
    # stop por ATR fora do tick: o diário guarda o valor ENVIADO (arredondado
    # para longe da entrada), que é o que protecao_registrada devolve
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    atr = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_803,
                   alvo_px=189_401, contratos=2)
    volta(m, mt5, {4: atr})
    for tipo in ("executada", "protecao"):
        ev = evs(m, tipo)[0]
        assert (ev["lado"], ev["stop_px"], ev["alvo_px"], ev["contratos"]) == \
            (1, 188_800, 189_405, 2), tipo
    t = evs(m, "executada")[0]["ticket"]
    assert m.diario(DIA).protecao_registrada(t) == (1, 188_800, 189_405)
    assert mt5.posicoes[t].sl == 188_800 and mt5.posicoes[t].tp == 189_405


def test_sem_papel_repoe_o_stop_gravado_na_executada(tmp_path):
    # a proteção da entrada falhou (passageira); o papel ficou indisponível:
    # o stop que volta para a corretora é o que a "executada" gravou
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10009, 10018]
    volta(m, mt5, {4: D})
    assert evs(m, "protecao_recusada") and not evs(m, "protecao")
    t = evs(m, "executada")[0]["ticket"]
    assert mt5.posicoes[t].sl == 0
    volta(m, mt5, {}, agora=T + timedelta(seconds=2), disponivel=False)
    assert mt5.enviados[-1]["action"] == 6 and mt5.enviados[-1]["sl"] == 188_800
    assert mt5.posicoes[t].sl == 188_800 and evs(m, "protecao")


def test_adotada_grava_lado_stop_alvo_e_contratos(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = ["executou_sem_resposta"]
    volta(m, mt5, {4: D})
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=4))
    ev = evs(m, "adotada")[0]
    assert (ev["ligacao_id"], ev["entry_ts"], ev["lado"], ev["stop_px"],
            ev["alvo_px"], ev["contratos"]) == (4, T, 1, 188_800, 189_400, 2)
    tipos = [e["tipo"] for e in m.diario(DIA).eventos]
    assert tipos.index("adotada") < tipos.index("protecao")


def test_saida_usa_o_contrato_da_posicao_nao_o_do_dia(tmp_path):
    # I12: posição em WINV26, contrato do dia já é WINZ26
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(4), simbolo="WINV26")
    volta(m, mt5, {4: Desejado(ZERADO)}, simbolo="WINZ26")
    sai = mt5.enviados[-1]
    assert sai["symbol"] == "WINV26" and sai["position"] == t and t not in mt5.posicoes
    assert sai["price"] == 189_000              # venda (saída de compra) no bid
    assert evs(m, "saida_executada")[0]["ticket"] == t


def test_passageira_tenta_de_novo_ate_30_s_e_depois_perdida(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10004, 10018]
    volta(m, mt5, {4: D})
    assert evs(m, "recusada")[0]["retcode"] == 10004
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=20))
    assert len(mt5.enviados) == 2 and not mt5.posicoes
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=31))
    assert tipos[-1] == "perdida" and len(mt5.enviados) == 2
    assert evs(m, "perdida")[0]["motivo"] == "mercado fechado (leilão)"


def test_incerta_nao_reenvia_na_mesma_volta_nem_antes_de_3_s(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [None]
    assert volta(m, mt5, {4: D}) == ["enviando", "incerta"]
    assert len(mt5.enviados) == 1
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=3))
    assert len(mt5.enviados) == 1
    # sem ordem no histórico, depois dos 3 s tenta de novo
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    assert len(acoes_de(mt5, 1)) == 2 and len(mt5.posicoes) == 1


def test_timeout_que_executou_nao_duplica(tmp_path):
    # caso 3
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = ["executou_sem_resposta"]
    assert volta(m, mt5, {4: D})[-1] == "incerta"
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=3))
    assert len(acoes_de(mt5, 1)) == 1
    assert len(mt5.posicoes) == 1 and "adotada" in tipos


def test_queda_entre_enviando_e_o_envio_tenta_de_novo_na_janela(tmp_path):
    # caso 5: o diário tem "enviando", a corretora não tem nada (o envio
    # não chegou a sair) -> passados 3 s, dentro dos 30 s, tenta de novo, uma vez
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    m.diario(DIA).registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=4))
    assert len(acoes_de(mt5, 1)) == 1
    assert len(mt5.posicoes) == 1


def test_placed_espera_e_nao_reenvia(tmp_path):
    # caso 4
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10008]
    assert volta(m, mt5, {4: D})[-1] == "aceita"
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=2))
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    assert len(mt5.enviados) == 1
    mt5.executar_pendente(next(iter(mt5.ordens)))
    assert "adotada" in volta(m, mt5, {4: D}, agora=T + timedelta(seconds=6))


def test_parcial_cancela_o_resto_e_protege(tmp_path):
    # caso 20
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10010]
    tipos = volta(m, mt5, {4: D})
    assert "parcial" in tipos and "cancelada" in tipos and not mt5.ordens
    assert acoes_de(mt5, 8)
    ev = evs(m, "parcial")[0]
    assert ev["contratos"] == 1 and ev["stop_px"] == 188_800
    assert mt5.posicoes[ev["ticket"]].sl == 188_800


def test_preenchimento_recusado_tenta_o_proximo_modo(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10030, 10009]
    volta(m, mt5, {4: D})
    assert [r["type_filling"] for r in acoes_de(mt5, 1)] == [1, 0]
    assert len(evs(m, "enviando")) == 1 and evs(m, "executada")


def test_todo_preenchimento_recusado_perde_e_chama(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10030, 10030, 10030]
    tipos = volta(m, mt5, {4: D})
    assert [r["type_filling"] for r in acoes_de(mt5, 1)] == [1, 0, 2]
    assert tipos[-2:] == ["chamado", "perdida"]
    assert any(c["texto"] == "modo de preenchimento recusado" for c in m.chamados.values())


def test_sem_margem_perde_e_chama(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.margem_livre = 0
    tipos = volta(m, mt5, {4: D})
    assert tipos == ["enviando", "chamado", "perdida"]
    assert not mt5.enviados                                  # parou no order_check
    assert any(c["tipo"] == "usuario" and c["ligacao_id"] == 4
               for c in m.chamados.values())


def test_so_encerramento_para_as_entradas_naquele_contrato(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10044]
    assert volta(m, mt5, {4: D})[-1] == "perdida"
    assert m.so_encerrar.get("WINV26")
    d2 = Desejado(POSICAO, lado=1, entry_ts=T + timedelta(minutes=1), entry_px=189_000,
                  stop_px=188_800, alvo_px=189_400, contratos=2)
    volta(m, mt5, {4: d2}, agora=T + timedelta(minutes=1, seconds=1))
    assert len(mt5.enviados) == 1
    assert evs(m, "nao_entrou")[-1]["motivo"] == "só encerramento (vencimento)"


def test_entrada_sem_protecao_na_corretora_e_encerrada(tmp_path):
    # SLTP recusado com stop inválido (preço já passou do stop) -> sai na hora
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10009, 10016]
    tipos = volta(m, mt5, {4: D})
    assert not mt5.posicoes
    assert tipos == ["enviando", "executada", "protecao_enviando", "protecao_recusada",
                     "saida_enviando", "saida_executada"]


def test_stop_movido_com_stop_invalido_sai_a_mercado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    novo = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=189_100,
                    alvo_px=189_400, contratos=2)
    mt5.roteiro = [10016]
    tipos = volta(m, mt5, {4: novo}, agora=T + timedelta(seconds=30))
    assert tipos[-4:] == ["protecao_enviando", "protecao_recusada",
                          "saida_enviando", "saida_executada"]
    assert not mt5.posicoes


def test_sem_papel_stop_invalido_tambem_sai(tmp_path):
    # ruling T7 C2: só acontece com o preço além do stop gravado
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10009, 10018]                   # proteção da entrada não pegou
    volta(m, mt5, {4: D})
    mt5.roteiro = [10016]
    volta(m, mt5, {}, agora=T + timedelta(seconds=2), disponivel=False)
    assert not mt5.posicoes and evs(m, "saida_executada")


def test_protecao_sem_mudanca_conta_como_protecao(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10009, 10025]
    volta(m, mt5, {4: D})
    assert evs(m, "protecao") and not evs(m, "protecao_recusada")


# -------------------------------------------------------------------- saída
def test_saida_pendente_vira_chamado_apos_120_s_e_continua(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.roteiro = [10018] * 10
    z = {4: Desejado(ZERADO)}
    volta(m, mt5, z, agora=T + timedelta(minutes=1))
    assert not m.chamados
    volta(m, mt5, z, agora=T + timedelta(minutes=3, seconds=1))
    assert any(c["tipo"] == "saida_pendente" for c in m.chamados.values())
    mt5.roteiro = []
    volta(m, mt5, z, agora=T + timedelta(minutes=3, seconds=2))
    assert not mt5.posicoes and not m.chamados
    assert evs(m, "chamado_fechado")


def test_saida_nunca_desiste(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(4))
    mt5.roteiro = [10018] * 15
    z = {4: Desejado(ZERADO)}
    for i in range(16):
        volta(m, mt5, z, agora=AG + timedelta(seconds=2 * i))
    assert len(evs(m, "saida_enviando")) == 16
    assert evs(m, "saida_enviando")[-1]["tentativa"] == 16
    assert t not in mt5.posicoes and evs(m, "saida_executada")


def test_saida_ja_encerrada_so_registra(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.roteiro = [10036]
    volta(m, mt5, {4: Desejado(ZERADO)})
    assert evs(m, "saida_executada")[0]["motivo"] == "já encerrada"


def test_saida_sem_resposta_registra_e_nao_repete_na_volta(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.roteiro = [None]
    volta(m, mt5, {4: Desejado(ZERADO)})
    assert evs(m, "saida_recusada")[0]["motivo"] == "sem resposta"
    assert len(mt5.enviados) == 1


# ------------------------------------------------------------ cancelar
def test_cancelar_envia_remove_e_registra_cancelada(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10008]
    volta(m, mt5, {4: D})
    o = next(iter(mt5.ordens))
    tipos = volta(m, mt5, {4: Desejado(ZERADO)}, agora=T + timedelta(seconds=2))
    assert mt5.enviados[-1] == {"action": 8, "order": o}
    assert tipos[-2:] == ["cancelar_enviando", "cancelada"] and not mt5.ordens
    assert evs(m, "cancelada")[0]["ticket"] == o


# ------------------------------------------------------------- registros
def test_envio_desligado_registra_seria_enviada_sem_mandar(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    tipos = volta(m, mt5, {4: D}, envio=False)
    assert tipos == ["seria_enviada"] and not mt5.enviados
    assert evs(m, "seria_enviada")[0]["pedido"]["magic"] == K.magic(4)
    assert volta(m, mt5, {4: D}, envio=False) == ["seria_enviada"]


def test_pode_entrar_falso_registra_o_motivo_uma_vez(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    pode = lambda a: (False, "preço longe demais do stop do papel")
    volta(m, mt5, {4: D}, pode=pode)
    tipos = volta(m, mt5, {4: D}, pode=pode)
    assert tipos == ["nao_entrou"] and not mt5.enviados
    assert evs(m, "nao_entrou")[0]["motivo"] == "preço longe demais do stop do papel"


def test_sl_do_servidor_e_movimento_do_stop_no_mesmo_minuto(tmp_path):
    # caso 10: a posição saiu pelo SL; o papel ainda manda proteger
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.stopar(next(iter(mt5.posicoes)))
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    assert tipos[-1] == "saiu_antes"
    ev = m.diario(DIA).eventos[-1]
    assert ev["motivo"] == "stop na corretora" and ev["entry_ts"] == T


def test_alvo_do_servidor_registra_alvo_na_corretora(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.stopar(next(iter(mt5.posicoes)), motivo=5)
    volta(m, mt5, {4: Desejado(ZERADO)}, agora=T + timedelta(seconds=5))
    assert evs(m, "saiu_antes")[0]["motivo"] == "alvo na corretora"


# ------------------------------------------------- chamados e sem relógio
def _sem_stop_sem_registro(mt5):
    t = mt5.abrir_manual(1, magic=K.magic(4))
    return t


def test_chamar_de_planejar_abre_um_chamado_so(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = _sem_stop_sem_registro(mt5)
    for i in range(3):
        volta(m, mt5, {}, agora=AG + timedelta(seconds=i), disponivel=False)
    assert len(m.chamados) == 1 and len(evs(m, "chamado")) == 1
    c = next(iter(m.chamados.values()))
    assert c["ticket"] == t and c["ligacao_id"] == 4
    # a posição sumiu: o chamado fecha
    mt5.posicoes.clear()
    volta(m, mt5, {}, agora=AG + timedelta(seconds=5), disponivel=False)
    assert not m.chamados and len(evs(m, "chamado_fechado")) == 1


def test_sem_relogio_nao_repete_protecao_antes_de_1_s(tmp_path):
    relogio_local = [100.0]
    mt5 = MT5Ordens()
    m = Motor(tmp_path, INST, mono=lambda: relogio_local[0])
    mt5.roteiro = [10009, 10018]               # entra; proteção não pega
    volta(m, mt5, {4: D})
    mt5.roteiro = [10018] * 5

    def sem_relogio():
        foto = K.fotografar(mt5, datetime(2026, 10, 9))
        acoes = planejar({}, False, foto, m.diario(DIA), None, 5, 60.0)
        assert [a.tipo for a in acoes] == ["proteger"]
        m.executar(mt5, acoes, foto=foto, agora_srv=None, simbolo="WINV26",
                   desvio=10, pode_entrar=lambda a: (True, None), envio=True,
                   conta_id=2)
    antes = len(acoes_de(mt5, 6))
    relogio_local[0] += 1.0
    sem_relogio()
    relogio_local[0] += 0.5
    sem_relogio()
    assert len(acoes_de(mt5, 6)) == antes + 1
    relogio_local[0] += 0.6
    sem_relogio()
    assert len(acoes_de(mt5, 6)) == antes + 2
    # sem relógio o evento usa a última hora do servidor + o tempo local
    assert evs(m, "protecao_enviando")[-1]["quando"] == AG + timedelta(seconds=2.1)


def test_falha_numa_acao_nao_impede_as_outras(tmp_path):
    # a saída da ligação 5 estoura no MT5; a entrada da 4 sai mesmo assim e o
    # erro sobe no fim (a captura registra e chama)
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.abrir_manual(1, magic=K.magic(5))
    orig = mt5.order_send

    def quebra(req):
        if "position" in req and req["action"] == 1:
            raise RuntimeError("IPC")
        return orig(req)
    mt5.order_send = quebra
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar({4: D, 5: Desejado(ZERADO)}, True, foto, m.diario(DIA), AG, 5, 60.0)
    assert sorted(a.tipo for a in acoes) == ["entrar", "sair"]
    with pytest.raises(RuntimeError):
        m.executar(mt5, acoes, foto=foto, agora_srv=AG, simbolo="WINV26", desvio=10,
                   pode_entrar=lambda a: (True, None), envio=True, conta_id=2)
    assert evs(m, "saida_enviando") and evs(m, "executada")
