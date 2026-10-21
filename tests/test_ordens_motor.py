"""Executor (spec §5.2–5.4, §6): cada caso com o MT5 falso e o diário em tmp_path.

Os testes rodam `planejar` + `Motor.executar` como a captura vai rodar
(uma "volta"), e conferem o que foi ao MT5 (`mt5.enviados`), o que ficou
na conta (`mt5.posicoes`/`mt5.ordens`) e o que o diário gravou.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

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
          disponivel=True, simbolo="WINV26", conectado=60.0):
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar(desejados, disponivel, foto, m.diario(DIA), agora, 5, conectado)
    m.executar(mt5, acoes, foto=foto, agora_srv=agora, simbolo=simbolo, desvio=10,
               pode_entrar=pode, envio=envio, conta_id=2, conectado_ha_s=conectado)
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


def test_saida_ja_encerrada_nao_vira_saida_executada(tmp_path):
    # 10036: a saída real (preço, motivo, volume) vem do saiu_antes depois
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.roteiro = [10036]
    volta(m, mt5, {4: Desejado(ZERADO)})
    assert not evs(m, "saida_executada")
    ev = evs(m, "saida_recusada")[0]
    assert ev["motivo"] == "já encerrada na corretora" and ev["retcode"] == 10036


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
                   conta_id=2, conectado_ha_s=60.0)
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
                   pode_entrar=lambda a: (True, None), envio=True, conta_id=2,
                   conectado_ha_s=60.0)
    assert evs(m, "saida_enviando") and evs(m, "executada")


# ======================================================== rodada de correção 1
def _executar_direto(m, mt5, acoes, agora=AG, conectado=60.0):
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    m.executar(mt5, acoes, foto=foto, agora_srv=agora, simbolo="WINV26", desvio=10,
               pode_entrar=lambda a: (True, None), envio=True, conta_id=2,
               conectado_ha_s=conectado)


def test_saida_parcial_nao_fecha_o_ticket_e_o_stop_do_servidor_registra_o_resto(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    z = {4: Desejado(ZERADO)}
    mt5.roteiro = [10010]                       # sai 1 dos 2 contratos
    assert volta(m, mt5, z, agora=T + timedelta(seconds=10))[-1] == "saida_parcial"
    assert mt5.posicoes[t].volume == 1 and evs(m, "saida_parcial")[0]["contratos"] == 1
    dia = m.diario(DIA)
    assert dia.saida_desde(t) == T + timedelta(seconds=10)     # segue pendente
    assert (t, T) in dia.tickets_abertos(4)                    # ticket segue aberto
    mt5.stopar(t)                               # o SL do servidor leva o resto
    volta(m, mt5, z, agora=T + timedelta(seconds=11))
    sa = evs(m, "saiu_antes")
    assert [e["ticket"] for e in sa] == [t] and sa[0]["contratos"] == 1
    assert sa[0]["motivo"] == "stop na corretora"
    assert sum(e["contratos"] for e in evs(m, "saida_parcial") + sa) == 2


def test_saida_parcial_e_depois_total_somam_os_contratos(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    z = {4: Desejado(ZERADO)}
    mt5.roteiro = [10010]
    volta(m, mt5, z, agora=T + timedelta(seconds=10))
    volta(m, mt5, z, agora=T + timedelta(seconds=12))
    assert t not in mt5.posicoes
    assert [e["contratos"] for e in evs(m, "saida_parcial") + evs(m, "saida_executada")] \
        == [1, 1]
    assert m.diario(DIA).saida_desde(t) is None


def _esconde_a_nova(mt5, zerar_ordem):
    """A lista de posições ainda não tem a entrada nova (e, se pedido, a
    resposta vem sem `order`)."""
    escondidas = set()
    envia, lista = mt5.order_send, mt5.positions_get

    def send(req):
        r = envia(req)
        if r is not None and req["action"] == 1 and "position" not in req \
                and r.retcode == 10009:
            escondidas.add(r.order)
            if zerar_ordem:
                return NS(retcode=r.retcode, order=0, deal=r.deal, volume=r.volume,
                          price=r.price, comment="")
        return r
    mt5.order_send = send
    mt5.positions_get = lambda **k: tuple(p for p in lista(**k)
                                          if p.ticket not in escondidas)
    return escondidas


def _antiga_saindo(m, mt5):
    # caso 9: a operação anterior (mesmo lado) ainda está saindo
    t0 = T - timedelta(minutes=5)
    agora, mt5.agora = mt5.agora, t0 + timedelta(seconds=1)
    antiga = mt5.abrir_manual(1, volume=2, magic=K.magic(4))
    mt5.agora = agora
    m.diario(DIA).registrar("executada", quando=t0, ligacao_id=4, entry_ts=t0,
                            ticket=antiga, lado=1, stop_px=188_000, alvo_px=None,
                            contratos=2)
    mt5.roteiro = [10018]                       # a saída da antiga não pega agora
    return antiga


def test_ticket_vem_da_ordem_mesmo_sem_a_posicao_na_lista(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    antiga = _antiga_saindo(m, mt5)
    nova = _esconde_a_nova(mt5, zerar_ordem=False)
    volta(m, mt5, {4: D})
    ev = evs(m, "executada")[-1]
    assert ev["entry_ts"] == T and ev["ticket"] in nova and ev["ticket"] != antiga


def test_sem_ordem_na_resposta_nunca_pega_o_ticket_da_operacao_anterior(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    antiga = _antiga_saindo(m, mt5)
    _esconde_a_nova(mt5, zerar_ordem=True)
    volta(m, mt5, {4: D})
    ev = evs(m, "executada")[-1]
    assert ev["entry_ts"] == T and ev["ticket"] is None
    # e o stop da operação nova nunca vai para a posição antiga
    assert not [r for r in acoes_de(mt5, 6) if r["position"] == antiga]


def test_chamado_de_entrada_cai_depois_da_janela_com_desfecho(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.margem_livre = 0
    volta(m, mt5, {4: D})
    assert len(m.chamados) == 1
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=20))
    assert len(m.chamados) == 1                 # ainda na janela
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=31))
    assert not m.chamados and len(evs(m, "chamado_fechado")) == 1


def test_fechar_publico_e_virada_do_dia_limpam_os_chamados(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.margem_livre = 0
    volta(m, mt5, {4: D})
    chave = next(iter(m.chamados))
    assert m.fechar(chave, AG) and not m.chamados
    assert evs(m, "chamado_fechado")[0]["motivo"] == chave
    assert not m.fechar(chave, AG)
    d2 = Desejado(POSICAO, lado=1, entry_ts=T + timedelta(minutes=1), entry_px=189_000,
                  stop_px=188_800, alvo_px=189_400, contratos=2)
    volta(m, mt5, {4: d2}, agora=T + timedelta(minutes=1, seconds=1))
    assert m.chamados
    m.diario(DIA + timedelta(days=1))
    assert m.chamados == {} and m.so_encerrar == {}


def test_diario_fica_em_ordem_de_tempo_depois_das_respostas(tmp_path):
    passos = iter(range(2, 100))
    mt5 = MT5Ordens()
    m = Motor(tmp_path, INST, relogio=lambda: T + timedelta(seconds=next(passos)))
    mt5.roteiro = [10010, 10009, 10016]        # parcial; cancela; SLTP inválido -> sai
    volta(m, mt5, {4: D})
    eventos = m.diario(DIA).eventos
    assert [e["tipo"] for e in eventos] == [
        "enviando", "parcial", "cancelar_enviando", "cancelada", "protecao_enviando",
        "protecao_recusada", "saida_enviando", "saida_executada"]
    q = [e["quando"] for e in eventos]
    assert q == sorted(q) and q[2] > q[0]


def test_erro_antes_do_envio_registra_recusada_e_sobe(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)

    def quebra(req):
        raise RuntimeError("IPC")
    mt5.order_check = quebra
    with pytest.raises(RuntimeError):
        volta(m, mt5, {4: D})
    assert [e["tipo"] for e in m.diario(DIA).eventos] == ["enviando", "recusada"]
    assert evs(m, "recusada")[0]["motivo"] == "RuntimeError('IPC')"
    assert not mt5.enviados


def test_erro_no_proprio_envio_fica_sem_desfecho(tmp_path):
    # o order_send pode ter chegado à corretora: nunca "recusada"
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)

    def quebra(req):
        raise RuntimeError("IPC")
    mt5.order_send = quebra
    with pytest.raises(RuntimeError):
        volta(m, mt5, {4: D})
    assert [e["tipo"] for e in m.diario(DIA).eventos] == ["enviando"]
    assert m.diario(DIA).tentativa_sem_desfecho(4, T) == AG


def test_lista_instavel_nao_fecha_chamado_de_posicao(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.abrir_manual(1, magic=K.magic(4))       # sem stop e sem registro
    volta(m, mt5, {}, disponivel=False)
    assert len(m.chamados) == 1
    mt5.vazio_uma_vez = True                    # logo após reconectar: lista vazia
    volta(m, mt5, {}, agora=AG + timedelta(seconds=1), disponivel=False, conectado=2.0)
    assert len(m.chamados) == 1
    mt5.posicoes.clear()
    volta(m, mt5, {}, agora=AG + timedelta(seconds=2), disponivel=False, conectado=2.0)
    assert len(m.chamados) == 1                 # ainda instável: não confia
    volta(m, mt5, {}, agora=AG + timedelta(seconds=8), disponivel=False)
    assert not m.chamados


def test_sem_stop_abre_um_chamado_so_pelos_dois_caminhos(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(4))
    p = K.fotografar(mt5, datetime(2026, 10, 9)).posicoes[0]
    acoes = [Acao("chamar", 4, ticket=t, posicao=p,
                  motivo="posição sem stop e papel indisponível"),
             Acao("proteger", 4, ticket=t, posicao=p,
                  desejado=Desejado(POSICAO, lado=1, entry_ts=T))]
    _executar_direto(m, mt5, acoes)
    _executar_direto(m, mt5, acoes, agora=AG + timedelta(seconds=2))
    assert list(m.chamados) == [f"sem_stop:{t}"]
    assert len(evs(m, "chamado")) == 1 and not mt5.enviados


# ======================================================== rodada de correção 2
class _ListasAtrasadas:
    """Entrada que volta 10009 com `order` = 0, e positions_get /
    history_deals_get que ainda não mostram a posição nova (caso A)."""

    def __init__(self, mt5):
        self.escondidas, self.ativo = set(), True
        envia, pos, neg = mt5.order_send, mt5.positions_get, mt5.history_deals_get

        def send(req):
            r = envia(req)
            if r is not None and req["action"] == 1 and "position" not in req \
                    and r.retcode == 10009:
                self.escondidas.add(r.order)
                return NS(retcode=r.retcode, order=0, deal=r.deal, volume=r.volume,
                          price=r.price, comment="")
            return r
        mt5.order_send = send
        mt5.positions_get = lambda **k: tuple(
            p for p in pos(**k) if not (self.ativo and p.ticket in self.escondidas))
        mt5.history_deals_get = lambda de, ate, **k: tuple(
            n for n in neg(de, ate, **k)
            if not (self.ativo and n.position_id in self.escondidas))


def test_executada_sem_ticket_com_listas_atrasadas_nao_duplica(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    lag = _ListasAtrasadas(mt5)
    volta(m, mt5, {4: D})
    assert evs(m, "executada")[0]["ticket"] is None
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=3))     # listas ainda atrasadas
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    assert len(acoes_de(mt5, 1)) == 1                          # nenhum 2º DEAL
    lag.ativo = False
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=6))
    assert "adotada" in tipos and len(mt5.posicoes) == 1
    assert len(acoes_de(mt5, 1)) == 1


def test_executada_sem_confirmacao_vira_perdida_com_chamado_que_fica(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    _ListasAtrasadas(mt5)
    volta(m, mt5, {4: D})
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=31))
    assert tipos[-2:] == ["perdida", "chamado"]
    assert evs(m, "perdida")[0]["motivo"] == "executada sem confirmação da posição"
    assert len(acoes_de(mt5, 1)) == 1
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=40))
    assert [c["texto"] for c in m.chamados.values()] == \
        ["executada sem confirmação da posição"]


def test_ja_encerrada_depois_de_parcial_o_saiu_antes_registra_o_resto(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    z = {4: Desejado(ZERADO)}
    mt5.roteiro = [10010]
    volta(m, mt5, z, agora=T + timedelta(seconds=10))          # sai 1 de 2
    mt5.roteiro = [10036]                                      # o SL do servidor já levou
    volta(m, mt5, z, agora=T + timedelta(seconds=12))
    mt5.stopar(t)                                              # ... e aparece agora
    volta(m, mt5, z, agora=T + timedelta(seconds=13))
    assert not evs(m, "saida_executada")
    sa = evs(m, "saiu_antes")
    assert [e["ticket"] for e in sa] == [t] and sa[0]["contratos"] == 1
    assert sa[0]["motivo"] == "stop na corretora"
    assert sum(e["contratos"] for e in evs(m, "saida_parcial") + sa) == 2


def test_chamados_da_saida_usam_a_hora_de_depois_da_resposta(tmp_path):
    base = [T]
    mt5 = MT5Ordens()
    m = Motor(tmp_path, INST, relogio=lambda: base[0] + timedelta(milliseconds=500))
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.roteiro = [10018, 10018, 10013]
    z = {4: Desejado(ZERADO)}
    for seg in (1, 125, 127, 129):
        base[0] = T + timedelta(seconds=seg)
        volta(m, mt5, z, agora=base[0])
    eventos = m.diario(DIA).eventos
    tipos = [e["tipo"] for e in eventos]
    assert tipos.count("chamado") == 2 and tipos.count("chamado_fechado") == 2
    q = [e["quando"] for e in eventos]
    assert q == sorted(q)
    for e in eventos:
        if e["tipo"] in ("chamado", "chamado_fechado"):
            assert e["quando"].microsecond == 500_000     # depois da resposta


def test_ticket_sem_ordem_nao_pega_posicao_herdada_mais_antiga(tmp_path):
    # posição do mesmo lado e magic aberta antes desta operação, que o diário
    # de hoje não conhece (ex.: ficou de outra sessão)
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    agora, mt5.agora = mt5.agora, T - timedelta(hours=1)
    herdada = mt5.abrir_manual(1, volume=2, magic=K.magic(4))
    mt5.agora = agora
    _ListasAtrasadas(mt5)
    mt5.roteiro = [10018]                     # a saída da herdada não pega agora
    volta(m, mt5, {4: D})
    ev = evs(m, "executada")[-1]
    assert ev["entry_ts"] == T and ev["ticket"] is None
    assert not [r for r in acoes_de(mt5, 6) if r["position"] == herdada]


# ------------------------------------- foto parcial: a posição órfã (14/10)
# A entrada executou sem a resposta (incerta) e, na volta seguinte, o
# histórico não vem: a candidata não pode ser adotada, mas também não pode
# ficar sem stop enquanto a leitura seguir parcial.
HIST = {"history_deals_get", "history_orders_get"}
AG2 = T + timedelta(seconds=4)


def _orfa(tmp_path, d=D):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = ["executou_sem_resposta"]
    assert volta(m, mt5, {4: d})[-1] == "incerta"
    [t] = mt5.posicoes
    assert mt5.posicoes[t].sl == 0
    return mt5, m, t


def test_parcial_protege_a_orfa_com_o_stop_do_enviando(tmp_path):
    mt5, m, t = _orfa(tmp_path)
    mt5.falhar = set(HIST)
    # o papel recalculou o stop depois do envio: vale o que foi enviado
    outro = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_700,
                     alvo_px=189_600, contratos=2)
    volta(m, mt5, {4: outro}, agora=AG2)
    [prot] = acoes_de(mt5, 6)
    assert prot == K.pedido_protecao(mt5, simbolo="WINV26", ticket=t, sl=188_800,
                                     tp=189_400, magic_=K.magic(4))
    assert (mt5.posicoes[t].sl, mt5.posicoes[t].tp) == (188_800, 189_400)
    assert evs(m, "protecao")[0]["ticket"] == t
    # nada entra, nada é adotado, nada sai, nenhum "saiu antes"
    assert len(entradas_(mt5)) == 1 and len(evs(m, "enviando")) == 1
    for tipo in ("adotada", "saiu_antes", "saida_enviando", "perdida"):
        assert not evs(m, tipo), tipo
    assert not m.chamados
    # na volta seguinte, já protegida, nada a mais
    volta(m, mt5, {4: outro}, agora=AG2 + timedelta(seconds=2))
    assert len(acoes_de(mt5, 6)) == 1 and not evs(m, "adotada")


def test_parcial_protege_a_orfa_vendida_com_arredondamento_da_protecao(tmp_path):
    # stop do papel fora do tick: o enviando grava o arredondado e a
    # proteção da órfã manda o mesmo valor (nunca mais apertado)
    venda = Desejado(POSICAO, lado=-1, entry_ts=T, entry_px=189_000, stop_px=189_203,
                     alvo_px=188_602, contratos=2)
    mt5, m, t = _orfa(tmp_path, venda)
    sl, tp = K.protecao(-1, 189_203, 188_602, 5)
    assert (evs(m, "enviando")[0]["stop_px"], evs(m, "enviando")[0]["alvo_px"]) == (sl, tp)
    mt5.falhar = set(HIST)
    volta(m, mt5, {4: venda}, agora=AG2)
    [prot] = acoes_de(mt5, 6)
    assert (prot["sl"], prot["tp"]) == (float(sl), float(tp)) == (189_205.0, 188_600.0)


def test_parcial_com_duas_candidatas_chama_e_nao_protege(tmp_path):
    mt5, m, t = _orfa(tmp_path)
    t2 = mt5.abrir_manual(1, magic=K.magic(4))
    mt5.falhar = set(HIST)
    volta(m, mt5, {4: D}, agora=AG2)
    assert acoes_de(mt5, 6) == []
    assert {k for k in m.chamados} == {f"sem_stop:{t}", f"sem_stop:{t2}"}
    assert all(c["tipo"] == "sem_stop" for c in m.chamados.values())
    assert t in mt5.posicoes and t2 in mt5.posicoes
    assert not evs(m, "adotada") and len(entradas_(mt5)) == 1


def test_parcial_sem_stop_no_enviando_chama_e_nao_protege(tmp_path):
    sem = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=None,
                   alvo_px=189_400, contratos=2)
    mt5, m, t = _orfa(tmp_path, sem)
    assert evs(m, "enviando")[0]["stop_px"] is None
    mt5.falhar = set(HIST)
    # o papel agora tem stop, mas o que foi enviado não tinha: não se inventa
    volta(m, mt5, {4: D}, agora=AG2)
    assert acoes_de(mt5, 6) == []
    assert m.chamados[f"sem_stop:{t}"]["tipo"] == "sem_stop"
    assert not evs(m, "adotada") and len(entradas_(mt5)) == 1


def test_parcial_sem_candidata_nao_entra_nem_chama(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.falhar = set(HIST)
    volta(m, mt5, {4: D})
    assert mt5.enviados == [] and not m.chamados and m.diario(DIA).eventos == []


def test_foto_completa_com_a_orfa_segue_adotando(tmp_path):
    # a foto completa não muda: adota e protege com o stop do papel
    mt5, m, t = _orfa(tmp_path)
    outro = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_700,
                     alvo_px=189_600, contratos=2)
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar({4: outro}, True, foto, m.diario(DIA), AG2, 5, 60.0)
    assert [(a.tipo, a.ticket, a.desejado) for a in acoes] == [
        ("adotar", t, outro), ("proteger", t, outro)]
    volta(m, mt5, {4: outro}, agora=AG2)
    assert (mt5.posicoes[t].sl, mt5.posicoes[t].tp) == (188_700, 189_600)
    assert evs(m, "adotada")[0]["ticket"] == t and not m.chamados


def test_foto_completa_com_duas_candidatas_segue_sem_chamado(tmp_path):
    mt5, m, t = _orfa(tmp_path)
    t2 = mt5.abrir_manual(1, magic=K.magic(4))
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar({4: D}, True, foto, m.diario(DIA), AG2, 5, 60.0)
    assert sorted((a.tipo, a.ticket) for a in acoes) == [("sair", t), ("sair", t2)]


def entradas_(mt5):
    return [r for r in mt5.enviados if r["action"] == 1 and "position" not in r]


# ------------------------- rodada 1: órfã com o stop recusado (parcial)
def test_parcial_orfa_com_stop_recusado_encerra_depois_de_2_s_e_nunca_antes(tmp_path):
    from core.ordens import SEM_PROTECAO_S
    mt5, m, t = _orfa(tmp_path)
    mt5.falhar = set(HIST)
    mt5.roteiro = [10006] * 10                 # a corretora recusa o SLTP sempre
    inicio = AG2
    passos = [0, 1, 1.5, 2, SEM_PROTECAO_S]   # até SEM_PROTECAO_S: só tenta proteger
    for s in passos:
        volta(m, mt5, {4: D}, agora=inicio + timedelta(seconds=s))
        assert not evs(m, "saida_enviando") and t in mt5.posicoes, s
    assert len(acoes_de(mt5, 6)) >= 2
    assert evs(m, "protecao_recusada")
    mt5.roteiro = []                           # a saída pega
    volta(m, mt5, {4: D}, agora=inicio + timedelta(seconds=SEM_PROTECAO_S + 0.5))
    [s] = evs(m, "saida_enviando")
    assert s["ticket"] == t and s["motivo"] == "posição sem proteção na corretora"
    assert t not in mt5.posicoes and evs(m, "saida_executada")
    assert not evs(m, "adotada") and len(entradas_(mt5)) == 1


def test_parcial_orfa_com_stop_e_saida_recusados_chama_sem_stop(tmp_path):
    mt5, m, t = _orfa(tmp_path)
    mt5.falhar = set(HIST)
    mt5.roteiro = [10006] * 20                 # recusa o SLTP e a saída
    for s in (0, 1, 2, 3):
        volta(m, mt5, {4: D}, agora=AG2 + timedelta(seconds=s))
    assert evs(m, "saida_recusada") and f"sem_stop:{t}" not in m.chamados
    volta(m, mt5, {4: D}, agora=AG2 + timedelta(seconds=4))
    assert m.chamados[f"sem_stop:{t}"]["tipo"] == "sem_stop"
    # e segue tentando sair (nunca desiste), sem voltar ao SLTP
    n_prot = len(acoes_de(mt5, 6))
    assert len(evs(m, "saida_enviando")) == 2
    volta(m, mt5, {4: D}, agora=AG2 + timedelta(seconds=5))
    assert len(acoes_de(mt5, 6)) == n_prot and len(evs(m, "saida_enviando")) == 3


def test_parcial_orfa_usa_o_stop_da_tentativa_que_abriu_a_posicao(tmp_path):
    # tentativa 1 executou (10:01:01) sem resposta; a 2 saiu com outro stop
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    dia = m.diario(DIA)
    dia.registrar("enviando", quando=AG, ligacao_id=4, entry_ts=T, lado=1,
                  stop_px=188_800, alvo_px=189_400, tentativa=1)
    dia.registrar("incerta", quando=AG, ligacao_id=4, entry_ts=T)
    t = mt5.abrir_manual(1, volume=2.0, magic=K.magic(4))   # aberta 10:01:01
    dia.registrar("enviando", quando=T + timedelta(seconds=5), ligacao_id=4,
                  entry_ts=T, lado=1, stop_px=188_700, alvo_px=189_500, tentativa=2)
    dia.registrar("recusada", quando=T + timedelta(seconds=5), ligacao_id=4, entry_ts=T)
    mt5.falhar = set(HIST)
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=7))
    [prot] = acoes_de(mt5, 6)
    assert (prot["position"], prot["sl"], prot["tp"]) == (t, 188_800.0, 189_400.0)


# ------------------------------------------- execução fora do mercado (stop)
def test_stop_com_negocio_no_preco_nao_marca_fora_do_mercado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.stopar(next(iter(mt5.posicoes)), preco=188_790)   # negócio no próprio preço
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    ev = evs(m, "saiu_antes")[0]
    assert ev["motivo"] == "stop na corretora" and "fora_do_mercado" not in ev


def test_stop_sem_negocio_no_preco_marca_fora_do_mercado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.ticks = [189_300.0]                  # mercado 500 pontos acima do stop
    mt5.stopar(next(iter(mt5.posicoes)), preco=188_500)   # "executou" sem negócio
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    ev = evs(m, "saiu_antes")[0]
    assert ev["fora_do_mercado"] is True
    assert ev["motivo"] == "stop na corretora (fora do mercado)"


def test_alvo_sem_negocio_no_preco_marca_fora_do_mercado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.ticks = [188_700.0]                  # mercado abaixo do alvo 189_400
    mt5.stopar(next(iter(mt5.posicoes)), motivo=5, preco=189_400)
    volta(m, mt5, {4: Desejado(ZERADO)}, agora=T + timedelta(seconds=5))
    ev = evs(m, "saiu_antes")[0]
    assert ev["fora_do_mercado"] is True
    assert ev["motivo"] == "alvo na corretora (fora do mercado)"


def test_leitura_de_ticks_falhou_nao_marca(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.falhar = {"copy_ticks_range"}
    mt5.stopar(next(iter(mt5.posicoes)), preco=188_500)
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    ev = evs(m, "saiu_antes")[0]
    assert ev["motivo"] == "stop na corretora" and "fora_do_mercado" not in ev


def test_excecao_na_leitura_de_ticks_nao_derruba_a_volta(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    def estoura(*a, **k):
        raise RuntimeError("pacote caiu")
    mt5.copy_ticks_range = estoura
    mt5.stopar(next(iter(mt5.posicoes)), preco=188_500)
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    ev = evs(m, "saiu_antes")[0]
    assert ev["motivo"] == "stop na corretora" and "fora_do_mercado" not in ev
