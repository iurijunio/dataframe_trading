"""Reconciliação (spec §5.1): uma linha da tabela, um teste."""
from datetime import date, datetime, timedelta

from core import corretora as K
from core.diario_ordens import Diario
from core.ordens import Acao, planejar
from core.papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado

T = datetime(2026, 10, 9, 10, 1)            # entrada do papel
D = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)


def pos(ticket, lig=4, lado=1, sl=188_800, tp=189_400, aberta=T):
    return K.Posicao(ticket=ticket, magic=K.magic(lig) if lig else 0, ligacao_id=lig,
                     simbolo="WINV26", lado=lado, volume=2, preco=189_005, sl=sl,
                     tp=tp, resultado=0.0, aberta_em=aberta)


def foto(posicoes=(), ordens=(), negocios=()):
    return K.Fotografia(posicoes=list(posicoes), ordens=list(ordens),
                        negocios=list(negocios), login=1, servidor="s",
                        hedging=True, margem_livre=1e4, algo_ligado=True)


def plan(tmp_path, desejados, f, agora=T + timedelta(seconds=1), disponivel=True,
         conectado=60.0, diario=None):
    d = diario or Diario(tmp_path, date(2026, 10, 9))
    return planejar(desejados, disponivel, f, d, agora, 5, conectado)


def tipos(acoes):
    return [(a.tipo, a.ligacao_id, a.ticket) for a in acoes]


def test_entra_dentro_dos_30_s(tmp_path):
    assert tipos(plan(tmp_path, {4: D}, foto())) == [("entrar", 4, None)]


def test_depois_de_30_s_registra_perdida_uma_vez(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    a = plan(tmp_path, {4: D}, foto(), agora=T + timedelta(seconds=31), diario=d)
    assert tipos(a) == [("perdida", 4, None)]
    assert a[0].motivo == "automação fora do ar"
    d.registrar("perdida", quando=T, ligacao_id=4, entry_ts=T)
    assert plan(tmp_path, {4: D}, foto(), agora=T + timedelta(seconds=40), diario=d) == []


def test_sem_entrada_nos_5_s_apos_reconectar(tmp_path):
    assert plan(tmp_path, {4: D}, foto(), conectado=2.0) == []


def test_posicao_com_o_ticket_e_protecao_certa_nao_faz_nada(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    assert plan(tmp_path, {4: D}, foto([pos(10)]), diario=d) == []


def test_stop_do_papel_mudou_pede_protecao(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    a = plan(tmp_path, {4: D}, foto([pos(10, sl=188_700)]), diario=d)
    assert tipos(a) == [("proteger", 4, 10)]


def test_stop_fora_do_tick_nao_vira_modificacao_por_volta(tmp_path):
    # caso 22: stop por ATR 188_803 -> corretora com 188_800 (arredondado)
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    atr = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_803,
                   alvo_px=189_400, contratos=2)
    assert plan(tmp_path, {4: atr}, foto([pos(10, sl=188_800)]), diario=d) == []


def test_zerado_com_posicao_sai(tmp_path):
    a = plan(tmp_path, {4: Desejado(ZERADO)}, foto([pos(10)]))
    assert tipos(a) == [("sair", 4, 10)]


def test_ligacao_fora_do_retrato_com_posicao_sai(tmp_path):
    # removida/fase papel/Envio desligado: o universo inclui a posição pelo magic
    assert tipos(plan(tmp_path, {}, foto([pos(10, lig=9)]))) == [("sair", 9, 10)]


def test_indisponivel_nao_entra_nem_sai(tmp_path):
    # caso 6: reinício antes do primeiro cálculo, com posições abertas
    assert plan(tmp_path, {}, foto([pos(10), pos(11, lig=5)]), disponivel=False) == []
    assert plan(tmp_path, {4: Desejado(INDISPONIVEL)}, foto([pos(10)])) == []


def test_posicao_a_mao_nunca_e_tocada(tmp_path):
    assert plan(tmp_path, {}, foto([pos(10, lig=None)])) == []


def test_ordem_em_transito_espera_e_a_velha_e_cancelada(tmp_path):
    em = {"ticket": 99, "magic": K.magic(4), "ligacao_id": 4, "simbolo": "WINV26",
          "volume": 2.0, "quando": T}
    assert plan(tmp_path, {4: D}, foto(ordens=[em])) == []
    # resto de parcial / PLACED esquecido há mais de 5 s: cancela
    a = plan(tmp_path, {4: D}, foto(ordens=[em]), agora=T + timedelta(seconds=6))
    assert tipos(a) == [("cancelar", 4, 99)]
    # papel zerado: cancela na hora (não pode prender o "Zerar tudo")
    a = plan(tmp_path, {4: Desejado(ZERADO)}, foto(ordens=[em]))
    assert tipos(a) == [("cancelar", 4, 99)]


def test_resposta_perdida_adota_a_posicao_em_vez_de_reenviar(tmp_path):
    # caso 3: executou, a resposta não chegou
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    a = plan(tmp_path, {4: D}, foto([pos(10)]), diario=d)
    assert tipos(a) == [("adotar", 4, 10)]


def saida(ticket, motivo=4, quando=T + timedelta(seconds=30)):
    return K.Negocio(ticket=900 + ticket, posicao=ticket, magic=K.magic(4),
                     ligacao_id=4, simbolo="WINV26", entrada=False, lado=-1,
                     volume=2, preco=188_800, resultado=-80.0, motivo=motivo,
                     quando=quando)


def test_ja_saiu_na_corretora_nao_reentra(tmp_path):
    # SL do servidor antes do papel, ou o usuário fechou à mão (caso 12)
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    a = plan(tmp_path, {4: D}, foto(negocios=[saida(10)]), diario=d)
    assert tipos(a) == [("saiu_antes", 4, 10)]
    d.registrar("saiu_antes", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    assert plan(tmp_path, {4: D}, foto(negocios=[saida(10)]), diario=d) == []


def test_lista_vazia_logo_apos_reconectar_nao_vira_saiu_antes(tmp_path):
    # I2: a posição está viva; o MT5 só não sincronizou — espera
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    assert plan(tmp_path, {4: D}, foto(), diario=d, conectado=1.0) == []
    # e sem negócio de saída, também não (pode ser só atraso da lista)
    assert plan(tmp_path, {4: D}, foto(), diario=d) == []


def test_executou_pelo_historico_mesmo_sem_ticket_nao_reentra(tmp_path):
    entrada = K.Negocio(ticket=1, posicao=10, magic=K.magic(4), ligacao_id=4,
                        simbolo="WINV26", entrada=True, lado=1, volume=2,
                        preco=189_005, resultado=0, motivo=3,
                        quando=T + timedelta(milliseconds=500))
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    a = plan(tmp_path, {4: D}, foto(negocios=[entrada, saida(10)]), diario=d)
    assert tipos(a) == [("saiu_antes", 4, 10)]


def test_papel_zerado_registra_a_saida_pelo_servidor(tmp_path):
    # I14 (caso 2): às 10:02 o papel já zerou e a posição saiu pelo SL
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    a = plan(tmp_path, {4: Desejado(ZERADO)}, foto(negocios=[saida(10)]), diario=d)
    assert tipos(a) == [("saiu_antes", 4, 10)]


def test_perdida_nao_volta_a_tentar_dentro_da_janela(tmp_path):
    # I3: sem margem -> perdida + chamado; nada de 300 order_check em 30 s
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    d.registrar("perdida", quando=T, ligacao_id=4, entry_ts=T, motivo="sem margem")
    assert plan(tmp_path, {4: D}, foto(), diario=d) == []


def test_intervalo_minimo_de_1_s_entre_tentativas(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T + timedelta(seconds=1), ligacao_id=4, entry_ts=T)
    d.registrar("recusada", quando=T + timedelta(seconds=1), ligacao_id=4, entry_ts=T)
    assert plan(tmp_path, {4: D}, foto(), diario=d,
                agora=T + timedelta(seconds=1, milliseconds=500)) == []
    assert tipos(plan(tmp_path, {4: D}, foto(), diario=d,
                      agora=T + timedelta(seconds=2))) == [("entrar", 4, None)]


def test_incerta_espera_3_s_e_nao_reenvia_se_o_historico_tem_a_ordem(tmp_path):
    # C2: timeout/None — a ordem pode ter executado
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    d.registrar("incerta", quando=T, ligacao_id=4, entry_ts=T)
    assert plan(tmp_path, {4: D}, foto(), diario=d, agora=T + timedelta(seconds=2)) == []
    hist = {"ticket": 77, "magic": K.magic(4), "ligacao_id": 4,
            "quando": T + timedelta(milliseconds=200)}
    f = foto()
    f.historico_ordens = [hist]
    assert plan(tmp_path, {4: D}, f, diario=d, agora=T + timedelta(seconds=4)) == []
    assert tipos(plan(tmp_path, {4: D}, foto(), diario=d,
                      agora=T + timedelta(seconds=4))) == [("entrar", 4, None)]


def test_posicao_sem_protecao_ha_mais_de_2_s_e_encerrada(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    nua = pos(10, sl=0.0, tp=0.0)
    assert tipos(plan(tmp_path, {4: D}, foto([nua]), diario=d)) == [("proteger", 4, 10)]
    a = plan(tmp_path, {4: D}, foto([nua]), diario=d, agora=T + timedelta(seconds=3))
    assert tipos(a) == [("sair", 4, 10)]


def test_operacao_anterior_que_nao_saiu_sai_e_a_nova_entra(tmp_path):
    # caso 9: a de 10:00 foi stopada no papel mas não no servidor; a nova,
    # do mesmo lado, é de 10:01 — casa por ticket, não por lado
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T - timedelta(minutes=1), ligacao_id=4,
                entry_ts=T - timedelta(minutes=1), ticket=10)
    velha = pos(10, aberta=T - timedelta(minutes=1))
    a = plan(tmp_path, {4: D}, foto([velha]), diario=d)
    assert tipos(a) == [("sair", 4, 10), ("entrar", 4, None)]


def test_sem_relogio_nao_entra(tmp_path):
    assert plan(tmp_path, {4: D}, foto(), agora=None) == []


def test_exatamente_30_s_ainda_entra(tmp_path):
    # fronteira da janela: 30 s cravados ainda é dentro (<=), 30,001 s já é perdida
    a = plan(tmp_path, {4: D}, foto(), agora=T + timedelta(seconds=30))
    assert tipos(a) == [("entrar", 4, None)]
    a = plan(tmp_path, {4: D}, foto(), agora=T + timedelta(seconds=30, milliseconds=1))
    assert tipos(a) == [("perdida", 4, None)]
