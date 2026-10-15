"""Limite do dia, trava a 90%, teto D1, Envio de ordens e comandos (spec §4,
§5.4, §5.7, §5.8, §6.2; decisões D1, D2, 6a, 6b).

`Motor.passo` é a volta inteira das ordens, como a captura vai rodar: cada
teste confere o que foi ao MT5 falso (`mt5.enviados`), o que ficou na conta
e o que o diário gravou.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta

from core import comandos
from core import corretora as K
from core.ordens import Motor, checar_entrada, perda_do_dia, risco_entrada
from core.papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado, LigacaoViva, Retrato
from tests.mt5_falso import MT5Ordens, _epoch

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
AG = T + timedelta(seconds=1)
D = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)
VENDA = Desejado(POSICAO, lado=-1, entry_ts=T, entry_px=189_000, stop_px=189_200,
                 alvo_px=188_600, contratos=2)
INST = {"tick_size": 5, "point_value": 0.2}
LOGIN, SERVIDOR = 1193398927, "ClearInvestimentos-DEMO"


# ------------------------------------------------------------- montagem
def conta(login=LOGIN, limite=500.0, envio=True, servidor=SERVIDOR):
    return {"login": login, "servidor": servidor, "limite": limite, "envio": envio}


def lig(lid, conta_id=2, pf=1, desvio=10, fase="demo"):
    return LigacaoViva(ligacao_id=lid, portfolio_id=pf, status="rodando", motivo=None,
                       plano=None, modulo=None, fase=fase, conta_id=conta_id,
                       ligada=True, desvio=desvio)


def retrato(ligs=(4,), contas=None, lido_em=AG):
    vivas = [x if isinstance(x, LigacaoViva) else lig(x) for x in ligs]
    ligacoes = {v.ligacao_id: v for v in vivas}
    return Retrato(dia=DIA, lido_em=lido_em, ligacoes=ligacoes,
                   contas=contas if contas is not None else {2: conta()},
                   portfolio_de={l: v.portfolio_id for l, v in ligacoes.items()})


def passo(m, mt5, desejados, ret=None, agora=AG, comandos=None, disponivel=True,
          contrato_ok=True, conectado=60.0, simbolo="WINV26", **kw):
    return m.passo(mt5, agora_srv=agora, retrato=ret or retrato(), desejados=desejados,
                   disponivel=disponivel, comandos=comandos or [], simbolo=simbolo,
                   contrato_ok=contrato_ok, conectado_ha_s=conectado, **kw)


def evs(m, tipo, dia=DIA):
    return [e for e in m.diario(dia).eventos if e["tipo"] == tipo]


def entradas(mt5, magic=None):
    return [r for r in mt5.enviados if r["action"] == 1 and "position" not in r
            and (magic is None or r["magic"] == magic)]


def saidas(mt5):
    return [r for r in mt5.enviados if r["action"] == 1 and "position" in r]


# ------------------------------------------------------------ perda_do_dia
def _pos(ticket, lig, resultado, sl=0.0):
    return K.Posicao(ticket=ticket, magic=K.magic(lig) if lig else 0, ligacao_id=lig,
                     simbolo="WINV26", lado=1, volume=1.0, preco=189_000.0, sl=sl,
                     tp=0.0, resultado=resultado, aberta_em=T)


def _neg(ticket, lig, resultado, entrada=False):
    return K.Negocio(ticket=ticket, posicao=ticket, magic=K.magic(lig) if lig else 0,
                     ligacao_id=lig, simbolo="WINV26", entrada=entrada, lado=1,
                     volume=1.0, preco=189_000.0, resultado=resultado, motivo=3,
                     quando=T)


def _foto_tres_origens(este_aberto=-100.0):
    # portfólio 1: ligações 4 e 5; portfólio 2: ligação 7; 9 tem magic mas
    # já não está em portfólio nenhum (removida); None = à mão
    return K.Fotografia(
        posicoes=[_pos(1, 4, este_aberto), _pos(2, 7, -30.0), _pos(3, None, -40.0)],
        negocios=[_neg(10, 5, -50.0), _neg(11, 4, -2.0, entrada=True),
                  _neg(12, 7, 10.0), _neg(13, 9, -5.0), _neg(14, None, -8.0)],
        login=LOGIN, servidor=SERVIDOR, hedging=True, algo_ligado=True)


PORTFOLIO_DE = {4: 1, 5: 1, 7: 2}


def test_perda_do_dia_separa_as_tres_origens_e_soma_o_total():
    p = perda_do_dia(_foto_tres_origens(), PORTFOLIO_DE, 1)
    assert p["este"] == 152.0                 # 100 aberto + 50 + 2 de custo
    assert p["outros"] == 25.0                # 30 − 10 + 5 (magic sem portfólio)
    assert p["fora"] == 48.0                  # 40 aberto + 8 realizado
    assert p["total"] == 225.0 == p["este"] + p["outros"] + p["fora"]
    assert p["por_portfolio"] == {1: 152.0, 2: 20.0}


def test_perda_do_dia_ganho_conta_zero_no_total_e_com_sinal_na_quebra():
    p = perda_do_dia(_foto_tres_origens(este_aberto=300.0), PORTFOLIO_DE, 1)
    assert p["este"] == -248.0               # ganho: negativo na quebra
    assert p["outros"] == 25.0 and p["fora"] == 48.0
    assert p["total"] == 0.0                 # −248 + 25 + 48 < 0 → 0


def test_perda_do_dia_sem_portfolio_poe_toda_automacao_em_outros():
    p = perda_do_dia(_foto_tres_origens(), PORTFOLIO_DE, None)
    assert p["este"] == 0.0 and p["outros"] == 177.0 and p["fora"] == 48.0
    assert p["total"] == 225.0


def test_perda_do_dia_de_outro_portfolio():
    p = perda_do_dia(_foto_tres_origens(), PORTFOLIO_DE, 2)
    assert p["este"] == 20.0 and p["outros"] == 157.0 and p["total"] == 225.0


# ------------------------------------------------------- risco e checagem
def test_risco_entrada_soma_distancia_ao_stop_e_custos_de_ida_e_volta():
    r = risco_entrada(D, 189_005, {"corretagem": 0.5, "emolumentos": 0.25}, 0.2)
    assert r == 205 * 2 * 0.2 + 2 * 2 * 0.75 == 85.0
    assert risco_entrada(VENDA, 189_000, {}, 0.2) == 200 * 2 * 0.2


def test_risco_entrada_usa_o_stop_arredondado_como_enviado():
    # stop por ATR fora do tick: a compra manda 188.800 (para longe), a venda 189.205
    atr = replace(D, stop_px=188_803)
    assert risco_entrada(atr, 189_005, {}, 0.2, tick=5) == 205 * 2 * 0.2
    assert risco_entrada(atr, 189_005, {}, 0.2) == 202 * 2 * 0.2
    v = replace(VENDA, stop_px=189_201)
    assert risco_entrada(v, 189_000, {}, 0.2, tick=5) == 205 * 2 * 0.2


def test_checar_entrada_passa():
    assert checar_entrada(D, 189_005, 0.0, 500.0, 82.0) == (True, None)
    assert checar_entrada(VENDA, 189_000, 0.0, 500.0, 80.0) == (True, None)


def test_checar_entrada_sem_limite():
    for limite in (None, 0, 0.0):
        assert checar_entrada(D, 189_005, 0.0, limite, 82.0) == \
            (False, "conta sem limite de perda do dia")


def test_checar_entrada_sem_stop():
    assert checar_entrada(replace(D, stop_px=None), 189_005, 0.0, 500.0, 0.0) == \
        (False, "plano sem stop")


def test_checar_entrada_preco_alem_do_stop_ou_do_alvo():
    alem = (False, "preço já além do stop/alvo do papel")
    assert checar_entrada(D, 188_800, 0.0, 500.0, 0.0) == alem       # no stop
    assert checar_entrada(D, 189_400, 0.0, 500.0, 0.0) == alem       # no alvo
    assert checar_entrada(VENDA, 189_200, 0.0, 500.0, 0.0) == alem   # espelhado
    assert checar_entrada(VENDA, 188_600, 0.0, 500.0, 0.0) == alem
    assert checar_entrada(VENDA, 188_905, 0.0, 500.0, 0.0)[0] is True   # 295 do stop


def test_checar_entrada_sem_alvo_nao_compara_alvo():
    assert checar_entrada(replace(D, alvo_px=None), 189_005, 0.0, 500.0, 82.0) == \
        (True, None)


def test_checar_entrada_preco_longe_demais_do_stop():
    # distância do plano 200 → teto 1,5× = 300
    assert checar_entrada(D, 189_100, 0.0, 5000.0, 0.0) == (True, None)
    assert checar_entrada(D, 189_101, 0.0, 5000.0, 0.0) == \
        (False, "preço longe demais do stop do papel")
    assert checar_entrada(VENDA, 188_899, 0.0, 5000.0, 0.0) == \
        (False, "preço longe demais do stop do papel")


def test_checar_entrada_passaria_da_trava():
    # 90% de 500 = 450: 368 + 82 = 450 ainda entra; 369 + 82 não
    assert checar_entrada(D, 189_005, 368.0, 500.0, 82.0) == (True, None)
    assert checar_entrada(D, 189_005, 369.0, 500.0, 82.0) == \
        (False, "passaria da trava do dia")


def test_checar_entrada_stop_ou_alvo_perto_demais_pela_corretora():
    perto = (False, "stop ou alvo perto demais do preço (regra da corretora)")
    # stop a 205, alvo a 395 do preço
    assert checar_entrada(D, 189_005, 0.0, 500.0, 82.0, stops_level=205) == (True, None)
    assert checar_entrada(D, 189_005, 0.0, 500.0, 82.0, stops_level=206) == perto
    assert checar_entrada(replace(D, alvo_px=189_100), 189_005, 0.0, 500.0, 82.0,
                          stops_level=100) == perto


def test_checar_entrada_contrato_so_encerramento():
    assert checar_entrada(D, 189_005, 0.0, 500.0, 82.0, so_encerrar=True) == \
        (False, "contrato só aceita encerramento")


# ---------------------------------------------------------------- trava
def test_trava_a_90_por_cento_zera_registra_e_nao_entra_mais(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    mt5.posicoes[t].profit = -449.0                       # 89,8%: ainda não
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2))
    assert not evs(m, "conta_travada") and t in mt5.posicoes
    mt5.posicoes[t].profit = -450.0                       # 90%: trava
    est = passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=4))
    trava = evs(m, "conta_travada")
    assert len(trava) == 1
    assert (trava[0]["conta_id"], trava[0]["perda"], trava[0]["limite"]) == (2, 450.0, 500.0)
    assert t not in mt5.posicoes
    assert evs(m, "saida_executada")[0]["motivo"] == "conta travada"
    assert est["travada"]["perda"] == 450.0 and est["envio"] is False
    assert est["ligacoes"][4]["desejado"] == ZERADO
    # o papel abre outra operação: nada entra, e a trava não se repete
    n = len(mt5.enviados)
    t2 = T + timedelta(minutes=5)
    passo(m, mt5, {4: replace(D, entry_ts=t2)}, agora=t2 + timedelta(seconds=1))
    assert len(mt5.enviados) == n and len(evs(m, "conta_travada")) == 1


def test_reinicio_depois_da_trava_continua_travada(tmp_path):
    # caso 16: Motor novo no mesmo diário; a perda até voltou abaixo de 90%
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    mt5.posicoes[t].profit = -480.0
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2))
    assert evs(m, "conta_travada") and t not in mt5.posicoes
    for n in mt5.negocios:
        n.profit = 0.0
    novo = Motor(tmp_path, INST)
    t2 = T + timedelta(minutes=5)
    antes = len(mt5.enviados)
    est = novo.passo(mt5, agora_srv=t2 + timedelta(seconds=1), retrato=retrato(),
                     desejados={4: replace(D, entry_ts=t2)}, disponivel=True,
                     comandos=[], simbolo="WINV26", contrato_ok=True, conectado_ha_s=60.0)
    assert len(mt5.enviados) == antes and est["travada"] is not None
    assert est["perda"]["total"] == 0.0


def test_trava_com_saida_pendente_trava_e_a_saida_segue(tmp_path):
    # caso 15
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(4))
    mt5.roteiro = [10004, 10004]
    est = passo(m, mt5, {4: Desejado(ZERADO)})
    assert evs(m, "saida_recusada") and t in mt5.posicoes
    pos = est["ligacoes"][4]["posicoes"][0]
    assert pos["ticket"] == t and pos["saida_desde"] == AG and pos["tentativas"] == 1
    mt5.posicoes[t].profit = -470.0
    passo(m, mt5, {4: Desejado(ZERADO)}, agora=AG + timedelta(seconds=2))
    assert len(evs(m, "conta_travada")) == 1
    assert len(evs(m, "saida_enviando")) == 2 and t in mt5.posicoes
    passo(m, mt5, {4: Desejado(ZERADO)}, agora=AG + timedelta(seconds=4))
    assert t not in mt5.posicoes and len(evs(m, "conta_travada")) == 1


def test_conta_sem_limite_nao_trava_e_nao_entra(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    est = passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(limite=None)}))
    assert not entradas(mt5) and not evs(m, "conta_travada")
    assert evs(m, "nao_entrou")[0]["motivo"] == "conta sem limite de perda do dia"
    assert est["limite"] is None


# ------------------------------------------------------ conta e terminal
def test_conta_errada_logada_nenhuma_ordem_e_chamado_que_fecha_sozinho(tmp_path):
    mt5, m = MT5Ordens(login=999), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(5))     # nem a saída sai
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)))
    assert mt5.enviados == [] and t in mt5.posicoes
    assert m.chamados["conta_errada"]["tipo"] == "conta_errada"
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)),
          agora=AG + timedelta(seconds=1))
    assert len(evs(m, "chamado")) == 1 and mt5.enviados == []
    mt5.login = LOGIN
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)),
          agora=AG + timedelta(seconds=2))
    assert "conta_errada" not in m.chamados
    assert [e["motivo"] for e in evs(m, "chamado_fechado")] == ["conta_errada"]
    assert t not in mt5.posicoes and len(entradas(mt5, K.magic(4))) == 1


def test_conta_errada_sem_ligacao_em_demo_nao_chama(tmp_path):
    mt5, m = MT5Ordens(login=999), Motor(tmp_path, INST)
    passo(m, mt5, {}, ret=retrato([lig(4, fase="papel")]))
    assert mt5.enviados == [] and not m.chamados


def test_conta_nao_hedging_nenhum_envio_e_chamado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.hedging = False
    t = mt5.abrir_manual(1, magic=K.magic(5))
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)))
    assert mt5.enviados == [] and t in mt5.posicoes
    assert m.chamados["nao_hedging"]["texto"] == "conta não é hedging"
    mt5.hedging = True
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)),
          agora=AG + timedelta(seconds=2))
    assert "nao_hedging" not in m.chamados and t not in mt5.posicoes
    assert entradas(mt5, K.magic(4))


def test_algo_desligado_nenhum_envio_e_chamado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.algo = False
    t = mt5.abrir_manual(1, magic=K.magic(5))
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)))
    assert mt5.enviados == [] and t in mt5.posicoes
    assert "algo_desligado" in m.chamados
    mt5.algo = True
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)),
          agora=AG + timedelta(seconds=2))
    assert "algo_desligado" not in m.chamados and t not in mt5.posicoes
    assert entradas(mt5, K.magic(4))


def test_foto_que_falha_nao_faz_nada(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.erro_leitura = True
    est = passo(m, mt5, {4: D})
    assert est["foto"] == "falhou" and mt5.enviados == [] and m.diario(DIA).eventos == []


def test_ligacao_de_outro_portfolio_nunca_opera_na_conta_logada(tmp_path):
    # C4: portfólio 1 (conta 3, login 555) em demo; o MT5 está logado na
    # conta 2, do portfólio 2 — nenhuma ordem do portfólio 1 aqui
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato([lig(4, conta_id=3, pf=1), lig(5, conta_id=2, pf=2)],
                  contas={2: conta(), 3: conta(login=555)})
    est = passo(m, mt5, {4: D, 5: D}, ret=ret)
    assert not entradas(mt5, K.magic(4)) and len(entradas(mt5, K.magic(5))) == 1
    assert est["ligacoes"][4]["desejado"] == ZERADO
    assert est["ligacoes"][4]["motivo"] == "conta de outro portfólio"
    assert est["ligacoes"][4]["papel"] == POSICAO


def test_ligacao_sem_conta_tambem_nao_opera(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D, 5: D}, ret=retrato([lig(4, conta_id=None), lig(5)]))
    assert not entradas(mt5, K.magic(4)) and entradas(mt5, K.magic(5))


# ---------------------------------------------------------------- envio
def test_envio_desligado_registra_seria_enviada_sem_order_send(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    est = passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}))
    assert mt5.enviados == [] and est["envio"] is False
    s = evs(m, "seria_enviada")
    assert len(s) == 1
    ped = s[0]["pedido"]
    assert (ped["magic"], ped["volume"], ped["type"], ped["symbol"], ped["price"]) == \
        (K.magic(4), 2.0, 0, "WINV26", 189_005.0)
    assert s[0]["stop_px"] == 188_800 and s[0]["alvo_px"] == 189_400
    # a volta seguinte não repete
    passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}),
          agora=AG + timedelta(seconds=2))
    assert len(evs(m, "seria_enviada")) == 1 and mt5.enviados == []


def test_envio_desligado_nao_registra_entrada_velha(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}),
          agora=T + timedelta(seconds=31))
    assert not evs(m, "seria_enviada") and mt5.enviados == []


def test_envio_desligado_com_checagem_que_barra_registra_o_motivo(tmp_path):
    # o ensaio mostra por que a entrada NÃO iria: mesma régua da entrada real
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}),
          contrato_ok=False)
    assert not evs(m, "seria_enviada") and mt5.enviados == []
    assert evs(m, "nao_entrou")[0]["motivo"] == "sem contrato operável hoje"


def test_envio_desligado_com_posicao_aberta_sai(tmp_path):
    # caso 14
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    est = passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}),
                agora=AG + timedelta(seconds=2))
    assert t not in mt5.posicoes
    assert evs(m, "saida_executada")[0]["motivo"] == "envio desligado"
    assert len(entradas(mt5)) == 1 and not evs(m, "seria_enviada")
    assert est["ligacoes"][4]["desejado"] == ZERADO and est["ligacoes"][4]["papel"] == POSICAO


def test_comando_envio_desliga_antes_do_banco_e_sobrevive_a_reinicio(tmp_path):
    pasta = tmp_path / "cmd"
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    comandos.escrever(pasta, "envio", conta_id=2, ligado=False)
    est = passo(m, mt5, {4: D}, comandos=pasta)      # retrato ainda com envio ligado
    assert mt5.enviados == [] and evs(m, "seria_enviada") and est["envio"] is False
    assert [e["motivo"] for e in evs(m, "comando")] == ["envio"]
    assert evs(m, "comando")[0]["conta_id"] == 2 and evs(m, "comando")[0]["ligado"] is False
    assert not list(pasta.glob("*.json"))
    # reinício: vem do diário
    novo = Motor(tmp_path, INST)
    t2 = T + timedelta(minutes=5)
    est = passo(novo, mt5, {4: replace(D, entry_ts=t2)}, agora=t2 + timedelta(seconds=1))
    assert mt5.enviados == [] and est["envio"] is False
    # o retrato relido concorda (desligado): o forçado acaba; religado no banco, entra
    passo(novo, mt5, {}, ret=retrato(contas={2: conta(envio=False)},
                                     lido_em=t2 + timedelta(seconds=2)),
          agora=t2 + timedelta(seconds=2))
    t3 = T + timedelta(minutes=10)
    est = passo(novo, mt5, {4: replace(D, entry_ts=t3)},
                ret=retrato(lido_em=t3), agora=t3 + timedelta(seconds=1))
    assert est["envio"] is True and len(entradas(mt5, K.magic(4))) == 1


def test_comando_envio_nao_concorda_com_retrato_lido_antes_dele(tmp_path):
    # retrato desligado mas lido ANTES do comando: não prova que o banco gravou
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    cmd = [{"tipo": "envio", "conta_id": 2, "ligado": False, "id": "a"}]
    passo(m, mt5, {}, ret=retrato(contas={2: conta(envio=False)},
                                  lido_em=AG - timedelta(seconds=10)), comandos=cmd)
    est = passo(m, mt5, {4: D}, ret=retrato(lido_em=AG + timedelta(seconds=1)),
                agora=AG + timedelta(seconds=1))
    assert est["envio"] is False and not entradas(mt5)


def test_comando_envio_ligado_nao_liga_o_que_o_banco_desliga(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    cmd = [{"tipo": "envio", "conta_id": 2, "ligado": True, "id": "a"}]
    est = passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}), comandos=cmd)
    assert est["envio"] is False and mt5.enviados == []


def test_comando_envio_ligado_solta_o_desligar_forcado_anterior(tmp_path):
    # desligou e religou antes de a captura reler o banco: o religar (banco
    # ligado) não fica preso no desligar forçado até o fim do dia
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {}, comandos=[{"tipo": "envio", "conta_id": 2, "ligado": False, "id": "a"}])
    est = passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=1),
                comandos=[{"tipo": "envio", "conta_id": 2, "ligado": True, "id": "b"}])
    assert est["envio"] is True and len(entradas(mt5)) == 1


def test_comando_envio_de_outra_conta_nao_desliga_esta(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    cmd = [{"tipo": "envio", "conta_id": 3, "ligado": False, "id": "a"}]
    est = passo(m, mt5, {4: D}, comandos=cmd)
    assert est["envio"] is True and len(entradas(mt5)) == 1


# ---------------------------------------------------------------- zerar
def test_zerar_tudo_encerra_as_da_automacao_e_nada_entra_depois(tmp_path):
    pasta = tmp_path / "cmd"
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t4 = mt5.abrir_manual(1, magic=K.magic(4))
    t5 = mt5.abrir_manual(-1, magic=K.magic(5))
    mao = mt5.abrir_manual(1, magic=0)
    comandos.escrever(pasta, "zerar_tudo")
    est = passo(m, mt5, {4: D, 5: VENDA}, ret=retrato((4, 5)), comandos=pasta)
    assert t4 not in mt5.posicoes and t5 not in mt5.posicoes and mao in mt5.posicoes
    assert not entradas(mt5) and {r["position"] for r in saidas(mt5)} == {t4, t5}
    assert est["zerar"] is True and est["envio"] is False
    assert [c["tipo"] for c in est["comandos"]] == ["zerar_tudo"]
    assert [e["motivo"] for e in evs(m, "comando")] == ["zerar_tudo"]
    assert not list(pasta.glob("*.json"))
    assert [p["ticket"] for p in est["posicao_fora"]] == [mao]
    # nova operação do papel: não entra, nem depois de reiniciar
    t2 = T + timedelta(minutes=5)
    passo(m, mt5, {4: replace(D, entry_ts=t2)}, ret=retrato((4, 5)),
          agora=t2 + timedelta(seconds=1))
    novo = Motor(tmp_path, INST)
    est = passo(novo, mt5, {4: replace(D, entry_ts=t2)}, ret=retrato((4, 5)),
                agora=t2 + timedelta(seconds=2))
    assert not entradas(mt5) and est["zerar"] is True


def test_zerar_vale_ate_o_retrato_mostrar_envio_desligado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {}, comandos=[{"tipo": "zerar_tudo", "id": "z"}])
    t2 = T + timedelta(minutes=5)
    est = passo(m, mt5, {}, ret=retrato(contas={2: conta(envio=False)}, lido_em=t2),
                agora=t2)
    assert est["zerar"] is False
    # o usuário religa o envio (banco): volta a operar, o zerar não ressuscita
    t3 = T + timedelta(minutes=10)
    est = passo(m, mt5, {4: replace(D, entry_ts=t3)}, ret=retrato(lido_em=t3),
                agora=t3 + timedelta(seconds=1))
    assert est["zerar"] is False and len(entradas(mt5)) == 1


def test_comando_repetido_nao_roda_de_novo(tmp_path):
    # o arquivo que não apagou (Windows) volta: o "zerar" já cumprido não zera de novo
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    z = {"tipo": "zerar_tudo", "id": "z1"}
    passo(m, mt5, {}, comandos=[z])
    t2 = T + timedelta(minutes=5)
    passo(m, mt5, {}, ret=retrato(contas={2: conta(envio=False)}, lido_em=t2), agora=t2)
    t3 = T + timedelta(minutes=10)
    est = passo(m, mt5, {4: replace(D, entry_ts=t3)}, ret=retrato(lido_em=t3),
                agora=t3 + timedelta(seconds=1), comandos=[dict(z)])
    assert est["zerar"] is False and est["comandos"] == []
    assert [e["motivo"] for e in evs(m, "comando")] == ["zerar_tudo", "zerar_tudo_cumprido"]
    assert len(entradas(mt5)) == 1


def test_comando_repetido_na_pasta_sai_sem_rodar(tmp_path):
    pasta = tmp_path / "cmd"
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    comandos.escrever(pasta, "zerar_tudo")
    arq = next(pasta.glob("*.json"))
    conteudo = arq.read_text(encoding="utf-8")
    passo(m, mt5, {}, comandos=pasta)
    arq.write_text(conteudo, encoding="utf-8")          # o unlink "falhou"
    est = passo(m, mt5, {}, comandos=pasta, agora=AG + timedelta(seconds=1))
    assert est["comandos"] == [] and len(evs(m, "comando")) == 1
    assert not list(pasta.glob("*.json"))


def test_retorno_antecipado_mostra_o_zerar_desta_volta(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    assert passo(m, mt5, {}, comandos=[{"tipo": "zerar_tudo", "id": "z"}])["zerar"] is True
    mt5.login = 999                                      # conta errada: retorno antecipado
    t2 = T + timedelta(minutes=5)
    est = passo(m, mt5, {}, ret=retrato(contas={2: conta(envio=False)}, lido_em=t2),
                agora=t2)
    assert est["zerar"] is False and est["conta"]["confere"] is False


def test_encerrar_posicao_encerra_so_aquele_ticket_da_automacao(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    mao = mt5.abrir_manual(1, magic=0)
    mt5.roteiro = [10004]                   # a 1ª tentativa falha: segue tentando
    cmd = [{"tipo": "encerrar_posicao", "ticket": t, "id": "a"},
           {"tipo": "encerrar_posicao", "ticket": mao, "id": "b"}]
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2), comandos=cmd)
    assert t in mt5.posicoes and evs(m, "saida_recusada")
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=4))
    assert t not in mt5.posicoes and mao in mt5.posicoes
    assert {r["position"] for r in saidas(mt5)} == {t}
    assert {e["ticket"] for e in evs(m, "saida_enviando")} == {t}
    assert "ordens_falhou" not in m.chamados
    assert evs(m, "saida_executada")[0]["motivo"] == "encerrada pelo usuário"
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=6))
    assert len(entradas(mt5)) == 1                     # não reentra


# ------------------------------------------------- entrada: régua da volta
def test_entradas_aprovadas_na_volta_somam_no_risco(tmp_path):
    # limite 100 → trava 90; cada entrada arrisca 205 × 2 × 0,2 = 82
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D, 5: D}, ret=retrato((4, 5), contas={2: conta(limite=100.0)}))
    assert len(entradas(mt5, K.magic(4))) == 1 and not entradas(mt5, K.magic(5))
    ev = evs(m, "nao_entrou")
    assert [(e["ligacao_id"], e["motivo"]) for e in ev] == [(5, "passaria da trava do dia")]


def test_posicao_aberta_da_automacao_soma_o_risco_ate_o_stop(tmp_path):
    # posição da ligação 7 (papel indisponível: fica) com stop 200 abaixo do
    # bid: 200 × 1 × 0,2 = 40; 82 + 40 = 122 > 108 (90% de 120)
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(7))
    mt5.posicoes[t].sl = 188_800.0
    ret = retrato((4, 7), contas={2: conta(limite=120.0)})
    passo(m, mt5, {4: D, 7: Desejado(INDISPONIVEL)}, ret=ret)
    assert not entradas(mt5) and t in mt5.posicoes
    assert evs(m, "nao_entrou")[0]["motivo"] == "passaria da trava do dia"
    # sem a posição, a mesma entrada cabe
    mt5b, mb = MT5Ordens(), Motor(tmp_path / "b", INST)
    passo(mb, mt5b, {4: D, 7: Desejado(INDISPONIVEL)}, ret=ret)
    assert len(entradas(mt5b)) == 1


def test_posicao_sem_sl_na_corretora_soma_o_stop_da_operacao(tmp_path):
    # revisão, cenário A: a proteção da 4 foi recusada (SL 0 na corretora);
    # meio segundo depois a 5 quer entrar. Risco da 4 = 200 × 2 × 0,2 = 80
    # (stop gravado na executada) + 82 da 5 > 90 (90% de 100)
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [10009, 10004, 10004, 10004]
    passo(m, mt5, {4: D}, ret=ret)
    assert [p.sl for p in mt5.posicoes.values()] == [0.0]
    passo(m, mt5, {4: D, 5: D}, ret=ret, agora=AG + timedelta(milliseconds=500))
    assert not entradas(mt5, K.magic(5))
    assert [(e["ligacao_id"], e["motivo"]) for e in evs(m, "nao_entrou")] == \
        [(5, "passaria da trava do dia")]


def test_entrada_aguardando_a_bolsa_soma_no_risco(tmp_path):
    # revisão, cenário B: a 4 ficou PLACED (sem posição ainda): 205 × 2 × 0,2
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [10008]
    passo(m, mt5, {4: D}, ret=ret)
    assert len(mt5.ordens) == 1
    passo(m, mt5, {4: D, 5: D}, ret=ret, agora=AG + timedelta(milliseconds=500))
    assert not entradas(mt5, K.magic(5))
    assert [(e["ligacao_id"], e["motivo"]) for e in evs(m, "nao_entrou")] == \
        [(5, "passaria da trava do dia")]


def test_entrada_aceita_soma_mesmo_sem_a_ordem_na_lista(tmp_path):
    # a lista de ordens atrasa (a PLACED ainda não aparece): o diário basta
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [10008]
    passo(m, mt5, {4: D}, ret=ret)
    mt5.ordens.clear()
    passo(m, mt5, {4: D, 5: D}, ret=ret, agora=AG + timedelta(milliseconds=500))
    assert not entradas(mt5, K.magic(5))
    assert evs(m, "nao_entrou")[0]["motivo"] == "passaria da trava do dia"


def test_entrada_sem_desfecho_soma_no_risco(tmp_path):
    # timeout: a ordem pode ter executado — conta como se estivesse aberta
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [None]
    passo(m, mt5, {4: D}, ret=ret)
    assert evs(m, "incerta") and not mt5.posicoes
    passo(m, mt5, {4: D, 5: D}, ret=ret, agora=AG + timedelta(milliseconds=500))
    assert not entradas(mt5, K.magic(5))
    assert evs(m, "nao_entrou")[0]["motivo"] == "passaria da trava do dia"


def test_entrada_incerta_com_o_papel_zerado_deixa_de_somar(tmp_path):
    # revisão X3: timeout na 4, o papel zera a 4; 5 min depois a 5 cabe
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [None]
    passo(m, mt5, {4: D}, ret=ret)
    passo(m, mt5, {4: Desejado(ZERADO)}, ret=ret, agora=AG + timedelta(seconds=10))
    t2 = T + timedelta(minutes=5)
    passo(m, mt5, {4: Desejado(ZERADO), 5: replace(D, entry_ts=t2)}, ret=ret,
          agora=t2 + timedelta(seconds=1))
    assert len(entradas(mt5, K.magic(5))) == 1 and not evs(m, "nao_entrou")


def test_entrada_aceita_cancelada_com_o_papel_zerado_deixa_de_somar(tmp_path):
    # revisão X4: PLACED, papel zera, a ordem é cancelada (o cancelamento não
    # tem entry_ts: não fecha a operação no diário)
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [10008]
    passo(m, mt5, {4: D}, ret=ret)
    passo(m, mt5, {4: Desejado(ZERADO)}, ret=ret, agora=AG + timedelta(seconds=2))
    assert not mt5.ordens and evs(m, "cancelada")
    t2 = T + timedelta(minutes=5)
    passo(m, mt5, {4: Desejado(ZERADO), 5: replace(D, entry_ts=t2)}, ret=ret,
          agora=t2 + timedelta(seconds=1))
    assert len(entradas(mt5, K.magic(5))) == 1 and not evs(m, "nao_entrou")


def test_entrada_incerta_antes_de_um_zerar_deixa_de_somar(tmp_path):
    # revisão X5: timeout na 4, zerar tudo, Envio religado: a 5 entra
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [None]
    passo(m, mt5, {4: D}, ret=ret)
    passo(m, mt5, {4: D}, ret=ret, agora=AG + timedelta(seconds=2),
          comandos=[{"tipo": "zerar_tudo", "id": "z"}])
    t2 = T + timedelta(minutes=2)
    passo(m, mt5, {4: D}, ret=retrato((4, 5), contas={2: conta(limite=100.0, envio=False)},
                                      lido_em=t2), agora=t2)
    t3 = T + timedelta(minutes=10)
    est = passo(m, mt5, {5: replace(D, entry_ts=t3)},
                ret=retrato((4, 5), contas={2: conta(limite=100.0)}, lido_em=t3),
                agora=t3 + timedelta(seconds=1))
    assert est["zerar"] is False
    assert len(entradas(mt5, K.magic(5))) == 1 and not evs(m, "nao_entrou")


def _regua_isolada(tmp_path, desejados, agora, limite=100.0, preparar=None, incerta_em=AG):
    """A régua sozinha, com o diário montado à mão: separa as condições de
    "entrada em trânsito viva" que o passo não deixa ver uma por uma (a
    perdida das 30 s fecha a operação antes)."""
    from core.ordens import Acao
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    dia = m.diario(DIA)
    dia.registrar("enviando", quando=AG, ligacao_id=4, entry_ts=T, lado=1, contratos=2,
                  simbolo="WINV26", preco_papel=189_000, stop_px=188_800, alvo_px=189_400)
    dia.registrar("incerta", quando=incerta_em, ligacao_id=4, entry_ts=T,
                  motivo="sem resposta")
    if preparar:
        preparar(mt5, dia)
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    ret = retrato((4, 5), contas={2: conta(limite=limite)})
    perda = perda_do_dia(foto, ret.portfolio_de, None)
    pode = m._regua(mt5, foto, ret, perda, limite, "WINV26", True, dia, desejados, agora)
    return pode(Acao("entrar", 5, desejado=D))


def test_entrada_em_transito_so_soma_enquanto_viva(tmp_path):
    trava = (False, "passaria da trava do dia")
    # viva: o papel quer esta operação e está na janela → 82 + 82 > 90
    assert _regua_isolada(tmp_path / "a", {4: D}, AG + timedelta(seconds=1)) == trava
    assert _regua_isolada(tmp_path / "b", {4: D}, AG + timedelta(seconds=35)) == trava
    # passou da janela + 5 s
    assert _regua_isolada(tmp_path / "c", {4: D}, AG + timedelta(seconds=36)) == (True, None)
    # a janela conta do último evento da tentativa (a incerta chegou 10 s depois)
    assert _regua_isolada(tmp_path / "g", {4: D}, AG + timedelta(seconds=40),
                          incerta_em=AG + timedelta(seconds=10)) == trava
    # zerado, mesmo carregando a chave da operação, não a mantém viva
    assert _regua_isolada(tmp_path / "h", {4: Desejado(ZERADO, entry_ts=T)},
                          AG + timedelta(seconds=1)) == (True, None)
    # o papel zerou / já está em outra operação
    assert _regua_isolada(tmp_path / "d", {4: Desejado(ZERADO)},
                          AG + timedelta(seconds=1)) == (True, None)
    assert _regua_isolada(tmp_path / "e", {4: replace(D, entry_ts=T + timedelta(minutes=1))},
                          AG + timedelta(seconds=1)) == (True, None)
    assert _regua_isolada(tmp_path / "f", {}, AG + timedelta(seconds=1)) == (True, None)


def test_posicao_sem_sl_usa_o_stop_da_propria_operacao(tmp_path):
    # a posição (aberta às 10:01:01) é da operação das 10:01 (stop 188.800:
    # 200 × 1 × 0,2 = 40), não da das 10:05 (stop 188.500: seria 100).
    # limite 150 → 135: 82 + 40 cabe; 82 + 100 não
    t2 = T + timedelta(minutes=4)

    def preparar(mt5, dia):
        mt5.abrir_manual(1, magic=K.magic(4))          # sem SL e sem ticket no diário
        dia.registrar("enviando", quando=t2, ligacao_id=4, entry_ts=t2, lado=1,
                      contratos=1, simbolo="WINV26", stop_px=188_500)
    assert _regua_isolada(tmp_path, {}, AG + timedelta(seconds=1), limite=150.0,
                          preparar=preparar) == (True, None)


def test_ordem_pendente_usa_o_stop_da_operacao_da_ordem(tmp_path):
    # ordem 900 é da operação das 10:01 (aceita com ordem=900, stop 188.800):
    # 205 × 2 × 0,2 = 82; com o stop da operação das 10:05 (188.500) seria
    # 505 × 2 × 0,2 = 202. limite 200 → 180: 82 + 82 cabe; 82 + 202 não
    from types import SimpleNamespace as NS
    t2 = T + timedelta(minutes=4)

    def preparar(mt5, dia):
        dia.registrar("aceita", quando=AG, ligacao_id=4, entry_ts=T, ordem=900)
        dia.registrar("enviando", quando=t2, ligacao_id=4, entry_ts=t2, lado=1,
                      contratos=2, simbolo="WINV26", stop_px=188_500)
        mt5.ordens[900] = NS(ticket=900, magic=K.magic(4), symbol="WINV26",
                             volume_current=2.0, time_setup=_epoch(t2) + 60,
                             type=0, req={})
    assert _regua_isolada(tmp_path, {}, AG + timedelta(seconds=1), limite=200.0,
                          preparar=preparar) == (True, None)


def test_entrada_recusada_nao_soma_no_risco(tmp_path):
    # controle: a recusa não deixou ordem viva — a 5 cabe
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato((4, 5), contas={2: conta(limite=100.0)})
    mt5.roteiro = [10004]
    passo(m, mt5, {4: D}, ret=ret)
    passo(m, mt5, {5: D}, ret=ret, agora=AG + timedelta(milliseconds=500))
    assert len(entradas(mt5, K.magic(5))) == 1


def test_ordem_pendente_com_o_magic_soma_no_risco(tmp_path):
    # uma ordem viva da ligação 7 (sem entrada no diário) com o stop do papel:
    # 205 × 2 × 0,2 = 82; + 82 da 4 > 90
    from types import SimpleNamespace as NS
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.ordens[900] = NS(ticket=900, magic=K.magic(7), symbol="WINV26", volume_current=2.0,
                         time_setup=_epoch(AG), type=0, req={})
    ret = retrato((4, 7), contas={2: conta(limite=100.0)})
    passo(m, mt5, {4: D, 7: replace(D, entry_ts=T - timedelta(minutes=5))}, ret=ret)
    assert not entradas(mt5, K.magic(4))
    assert evs(m, "nao_entrou")[0]["motivo"] == "passaria da trava do dia"


def test_limite_apagado_no_meio_do_dia_desliga_o_envio(tmp_path):
    # revisão, cenário C (§5.7): sem limite o Envio não liga; a posição aberta
    # sai e a entrada nova não vai (a régua diz por quê)
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    sem = retrato(contas={2: conta(limite=None)})
    est = passo(m, mt5, {4: D}, ret=sem, agora=AG + timedelta(seconds=2))
    assert est["envio"] is False and t not in mt5.posicoes
    assert evs(m, "saida_executada")[0]["motivo"] == "envio desligado"
    t2 = T + timedelta(minutes=5)
    passo(m, mt5, {4: replace(D, entry_ts=t2)}, ret=sem, agora=t2 + timedelta(seconds=1))
    assert len(entradas(mt5)) == 1
    assert evs(m, "nao_entrou")[0]["motivo"] == "conta sem limite de perda do dia"


def test_sem_cotacao_e_passageira_e_tenta_de_novo(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.symbol_info_tick = lambda s: None
    passo(m, mt5, {4: D})
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=1))
    assert mt5.enviados == [] and not evs(m, "nao_entrou")
    rec = evs(m, "recusada")
    assert len(rec) == 1 and rec[0]["motivo"] == "sem cotação do contrato"
    del mt5.symbol_info_tick
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2))
    assert len(entradas(mt5)) == 1 and evs(m, "executada")


def test_sem_contrato_operavel_nao_entra(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D}, contrato_ok=False)
    assert mt5.enviados == []
    assert evs(m, "nao_entrou")[0]["motivo"] == "sem contrato operável hoje"


def test_stops_level_da_corretora_barra_a_entrada(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.stops_level = 300                       # stop a 205 do ask
    passo(m, mt5, {4: D})
    assert mt5.enviados == []
    assert evs(m, "nao_entrou")[0]["motivo"] == \
        "stop ou alvo perto demais do preço (regra da corretora)"


def test_teto_d1_no_passo_usa_o_preco_corrente(tmp_path):
    mt5, m = MT5Ordens(preco=189_100), Motor(tmp_path, INST)   # ask 189.105: 305 do stop
    passo(m, mt5, {4: D})
    assert mt5.enviados == []
    assert evs(m, "nao_entrou")[0]["motivo"] == "preço longe demais do stop do papel"


def test_desvio_por_ligacao(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    ret = retrato([lig(4, desvio=15), lig(5, desvio=25)], contas={2: conta(limite=5000.0)})
    passo(m, mt5, {4: D, 5: D}, ret=ret)
    assert entradas(mt5, K.magic(4))[0]["deviation"] == 15
    assert entradas(mt5, K.magic(5))[0]["deviation"] == 25


def test_executar_com_desvio_em_dicionario_usa_dois_ticks_na_falta(tmp_path):
    from core.ordens import planejar
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar({4: D, 5: D}, True, foto, m.diario(DIA), AG, 5, 60.0)
    m.executar(mt5, acoes, foto=foto, agora_srv=AG, simbolo="WINV26", desvio={4: 35},
               pode_entrar=lambda a: (True, None), envio=True, conta_id=2,
               conectado_ha_s=60.0)
    assert entradas(mt5, K.magic(4))[0]["deviation"] == 35
    assert entradas(mt5, K.magic(5))[0]["deviation"] == 10


# ------------------------------------------------ falhas e chamados
def test_erro_nas_entradas_nao_impede_as_saidas_e_chama(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(5))

    def quebra(req):
        raise RuntimeError("terminal travou")
    mt5.order_check = quebra
    passo(m, mt5, {4: D, 5: Desejado(ZERADO)}, ret=retrato((4, 5)))   # não sobe
    assert t not in mt5.posicoes and not entradas(mt5)
    assert m.chamados["ordens_falhou"]["tipo"] == "ordens_falhou"
    del mt5.order_check
    passo(m, mt5, {4: D}, ret=retrato((4, 5)), agora=AG + timedelta(seconds=5))
    assert "ordens_falhou" not in m.chamados and len(entradas(mt5)) == 1


def test_papel_parado_mais_de_3_min_chama_e_fecha_quando_volta(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {}, disponivel=False)
    passo(m, mt5, {}, disponivel=False, agora=AG + timedelta(seconds=180))
    assert "papel_parado" not in m.chamados
    passo(m, mt5, {}, disponivel=False, agora=AG + timedelta(seconds=181))
    assert m.chamados["papel_parado"]["tipo"] == "papel_parado"
    passo(m, mt5, {}, disponivel=True, agora=AG + timedelta(seconds=182))
    assert "papel_parado" not in m.chamados


def test_papel_parado_fora_do_pregao_nao_chama(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {}, disponivel=False, no_pregao=False)
    passo(m, mt5, {}, disponivel=False, no_pregao=False, agora=AG + timedelta(seconds=400))
    assert not m.chamados


# --------------------------------------------------------------- estado
def test_estado_da_volta(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mao = mt5.abrir_manual(-1, magic=0)
    mt5.posicoes[mao].profit = -40.0
    ret = retrato([lig(4, pf=1), lig(7, pf=2)], contas={2: conta()})
    passo(m, mt5, {4: D, 7: Desejado(ZERADO)}, ret=ret)
    t = evs(m, "executada")[0]["ticket"]
    mt5.posicoes[t].profit = -60.0
    depois = AG + timedelta(seconds=20)
    est = passo(m, mt5, {4: D, 7: Desejado(ZERADO)}, ret=ret, agora=depois)
    assert est["vivo_em"] == depois
    assert est["ordens_em"] == m.diario(DIA).eventos[-1]["quando"] == AG   # nada novo
    assert est["conta"]["conta_id"] == 2 and est["conta"]["confere"] is True
    assert est["perda"]["total"] == 100.0 and est["perda"]["fora"] == 40.0
    assert est["perda"]["por_portfolio"] == {1: 60.0}
    assert est["limite"] == 500.0 and est["travada"] is None and est["envio"] is True
    l4 = est["ligacoes"][4]
    assert l4["desejado"] == POSICAO and l4["entry_ts"] == T and l4["tentativas"] == 1
    assert l4["posicoes"][0]["ticket"] == t and l4["posicoes"][0]["sl"] == 188_800
    assert l4["posicoes"][0]["saida_desde"] is None
    assert est["ligacoes"][7]["desejado"] == ZERADO
    assert [p["ticket"] for p in est["posicao_fora"]] == [mao]
    assert est["chamados"] == [] and est["comandos"] == []


# ------------------------------------------- n_demo (selo do topo, tarefa 14)
def test_n_demo_conta_as_ligacoes_na_fase_demo_em_toda_forma_do_estado(tmp_path):
    """A tela decide o "Sem demo" por este número, nunca pela lista de
    ligações (vazia quando o papel está indisponível)."""
    ret = retrato([lig(4), lig(5), lig(6, fase="papel")])
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    assert passo(m, mt5, {}, ret=ret, disponivel=False)["n_demo"] == 2
    # retornos antecipados: conta errada, sem hedging, foto que falha
    mt5.login = 999
    assert passo(m, mt5, {}, ret=ret)["n_demo"] == 2
    mt5.login, mt5.hedging = LOGIN, False
    assert passo(m, mt5, {}, ret=ret)["n_demo"] == 2
    mt5.hedging, mt5.erro_leitura = True, True
    est = passo(m, mt5, {}, ret=ret)
    assert est["foto"] == "falhou" and est["n_demo"] == 2


def test_n_demo_zero_e_sem_retrato_none(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    assert passo(m, mt5, {}, ret=retrato([lig(4, fase="papel")]))["n_demo"] == 0
    est = m.passo(mt5, agora_srv=AG, retrato=None, desejados={}, disponivel=False,
                  comandos=[], simbolo="WINV26", contrato_ok=True, conectado_ha_s=60.0)
    assert est["n_demo"] is None


# ================================================ correção final (09/10)
from types import SimpleNamespace as NS  # noqa: E402

from core import ordens as O  # noqa: E402
from core.papel_leitura import checagem_ensaio  # noqa: E402


# ---------------------------------------------------------------- I1
def test_zerar_de_ontem_lido_hoje_e_descartado(tmp_path):
    # clicado ontem à noite fora do pregão, sem posição: o arquivo só é
    # lido na manhã seguinte — não pode desligar o envio do dia inteiro
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    z = {"tipo": "zerar_tudo", "id": "z", "criado_em": "2026-10-08T19:30:00"}
    est = passo(m, mt5, {4: D}, comandos=[z])
    assert est["zerar"] is False and est["envio"] is True   # segue o retrato
    assert est["comandos"] == []
    [ev] = evs(m, "comando")
    assert ev["motivo"] == O.ZERAR_DESCARTADO and ev["comando_id"] == "z"
    assert len(entradas(mt5)) == 1
    # o mesmo arquivo de volta (unlink falhou) não roda nem registra de novo
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2), comandos=[dict(z)])
    assert len(evs(m, "comando")) == 1 and m.zerar is False


def test_zerar_de_hoje_antes_da_abertura_vale(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    z = {"tipo": "zerar_tudo", "id": "z", "criado_em": "2026-10-09T08:40:00"}
    est = passo(m, mt5, {4: D}, comandos=[z])
    assert est["zerar"] is True and est["envio"] is False and not entradas(mt5)
    assert [e["motivo"] for e in evs(m, "comando")] == ["zerar_tudo"]


# ---------------------------------------------------------------- I2
def test_foto_parcial_no_passo_sai_da_posicao_com_papel_zerado(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    mt5.falhar = {"history_deals_get", "history_orders_get"}
    est = passo(m, mt5, {4: Desejado(ZERADO)}, agora=AG + timedelta(seconds=2))
    assert est["foto"] == "parcial" and t not in mt5.posicoes
    assert evs(m, "saida_executada")[0]["ticket"] == t


def test_foto_parcial_no_passo_nao_entra_nem_ensaia(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.falhar = {"history_deals_get"}
    est = passo(m, mt5, {4: D})
    assert not entradas(mt5) and est["foto"] == "parcial"
    assert est["envio"] is True                 # o interruptor não muda na tela
    passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}),
          agora=AG + timedelta(seconds=2))
    assert not evs(m, "seria_enviada") and mt5.checados == []


def test_foto_parcial_sem_a_conta_usa_a_da_mesma_conexao(tmp_path):
    # account_info falhou: a última conta lida numa foto completa vale se a
    # conexão não caiu desde então; sem ela, nada sai
    mono = [100.0]
    mt5, m = MT5Ordens(), Motor(tmp_path, INST, mono=lambda: mono[0])
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    mt5.falhar = {"account_info"}
    mono[0] = 102.0
    # reconectou há 1 s (depois da última foto completa): não se sabe a conta
    passo(m, mt5, {4: Desejado(ZERADO)}, agora=AG + timedelta(seconds=2), conectado=1.0)
    assert t in mt5.posicoes and "conta_errada" not in m.chamados
    # mesma conexão: a conta de antes vale e a saída sai
    passo(m, mt5, {4: Desejado(ZERADO)}, agora=AG + timedelta(seconds=3), conectado=60.0)
    assert t not in mt5.posicoes


def test_chamado_sem_leitura_abre_depois_de_30_s_e_fecha_ao_voltar(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.falhar = {"history_deals_get"}
    passo(m, mt5, {}, agora=AG)
    passo(m, mt5, {}, agora=AG + timedelta(seconds=30))
    assert "sem_leitura" not in m.chamados
    est = passo(m, mt5, {}, agora=AG + timedelta(seconds=31))
    c = m.chamados["sem_leitura"]
    assert "leitura parcial" in c["texto"] and "negócios do dia" in c["texto"]
    assert [x["chave"] for x in est["chamados"]] == ["sem_leitura"]
    mt5.falhar = set()
    passo(m, mt5, {}, agora=AG + timedelta(seconds=32))
    assert "sem_leitura" not in m.chamados
    assert [e["tipo"] for e in m.diario(DIA).eventos
            if e["tipo"].startswith("chamado")] == ["chamado", "chamado_fechado"]


def test_chamado_sem_leitura_na_hora_com_posicao_aberta_e_nem_foto_parcial(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    mt5.falhar = {"positions_get"}
    est = passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=1))
    assert est["foto"] == "falhou"
    assert "posições" in m.chamados["sem_leitura"]["texto"]
    assert [c["chave"] for c in est["chamados"]] == ["sem_leitura"]


def test_chamado_sem_leitura_nao_abre_fora_do_pregao(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.falhar = {"history_deals_get"}
    passo(m, mt5, {}, agora=AG, no_pregao=False)
    passo(m, mt5, {}, agora=AG + timedelta(seconds=40), no_pregao=False)
    assert "sem_leitura" not in m.chamados


# ---------------------------------------------------------------- I3
def _ensaio(m, mt5):
    passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}))
    [s] = evs(m, "seria_enviada")
    return s


def test_ensaio_confere_o_pedido_no_order_check_e_grava_o_retcode(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    s = _ensaio(m, mt5)
    assert mt5.enviados == []                    # nunca envia
    assert mt5.checados == [s["pedido"]]         # o MESMO request
    assert s["retcode"] == 0 and s["comment"] == "Done"
    assert s["pedido"]["type_filling"] == mt5.ORDER_FILLING_IOC
    assert checagem_ensaio(s) is None


def test_ensaio_recusado_mostra_seria_recusada(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.check_retcode, mt5.check_comment = 10019, "No money"
    s = _ensaio(m, mt5)
    assert s["retcode"] == 10019 and s["comment"] == "No money"
    assert checagem_ensaio(s) == "seria recusada: No money"
    assert mt5.enviados == []


def test_ensaio_sem_resposta_grava_o_last_error(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.erro_check = (-10005, "IPC timeout")
    s = _ensaio(m, mt5)
    assert s["last_error"] == [-10005, "IPC timeout"] and "retcode" not in s
    assert "sem resposta do MT5" in checagem_ensaio(s)


def test_ensaio_usa_o_modo_de_preenchimento_que_o_caminho_real_usaria(tmp_path):
    # IOC recusado (10030): como na entrada de verdade, passa ao FOK
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    real = mt5.order_check

    def check(req):
        r = real(req)
        return NS(retcode=10030, comment="Unsupported filling mode") \
            if req["type_filling"] == mt5.ORDER_FILLING_IOC else r
    mt5.order_check = check
    s = _ensaio(m, mt5)
    assert s["pedido"]["type_filling"] == mt5.ORDER_FILLING_FOK and s["retcode"] == 0
    assert [r["type_filling"] for r in mt5.checados] == [mt5.ORDER_FILLING_IOC,
                                                         mt5.ORDER_FILLING_FOK]


def test_ensaio_com_order_check_que_estoura_registra_e_nao_repete(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)

    def quebra(req):
        raise RuntimeError("terminal caiu")
    mt5.order_check = quebra
    s = _ensaio(m, mt5)
    assert "terminal caiu" in s["last_error"][1]
    passo(m, mt5, {4: D}, ret=retrato(contas={2: conta(envio=False)}),
          agora=AG + timedelta(seconds=2))
    assert len(evs(m, "seria_enviada")) == 1


# ---------------------------------------------------------------- M1
def test_sem_contrato_por_um_instante_tenta_de_novo_e_entra(tmp_path):
    # 09:00:00: WIN$N com último 0, contrato ainda não escolhido; a volta
    # seguinte escolhe — a entrada sai, não vira "não entrou" para sempre
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D}, simbolo=None, contrato_ok=False,
          contrato_motivo=O.SEM_CONTRATO)
    assert not evs(m, "nao_entrou")
    assert evs(m, "recusada")[0]["motivo"] == O.SEM_CONTRATO
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2))
    assert len(entradas(mt5)) == 1 and evs(m, "executada")


def test_vencimento_hoje_e_final(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D}, simbolo=None, contrato_ok=False,
          contrato_motivo="vencimento do WINV26: sem entradas hoje")
    assert evs(m, "nao_entrou")[0]["motivo"] == "vencimento do WINV26: sem entradas hoje"
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2))
    assert not entradas(mt5)


def test_guarda_de_preco_tem_texto_proprio(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D}, contrato_ok=False, contrato_motivo=O.GUARDA_PRECO)
    assert evs(m, "nao_entrou")[0]["motivo"] == \
        "preço do contrato não confere com o WIN$N"


# ---------------------------------------------------------------- M2
def test_encerrar_posicao_da_automacao_nao_registra_saiu_antes(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    passo(m, mt5, {4: D})
    t = evs(m, "executada")[0]["ticket"]
    cmd = [{"tipo": "encerrar_posicao", "ticket": t, "id": "a"}]
    passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=2), comandos=cmd)
    assert t not in mt5.posicoes and evs(m, "saida_executada")
    for s in (4, 6, 8):
        passo(m, mt5, {4: D}, agora=AG + timedelta(seconds=s))
    assert not evs(m, "saiu_antes") and len(entradas(mt5)) == 1
