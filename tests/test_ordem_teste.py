"""A "Ordem de teste" (brief ordem-teste-brief.md): o caminho real de ordem
na conta demo, com o MT5 falso. `Motor.passo` é a volta inteira, como a
captura roda; o relógio monotônico do motor é controlado pelo teste (a
espera de 10 s é contada nele, nunca com sleep).
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from core import comandos
from core import corretora as K
from core import ordem_teste as OT
from core.ordens import Motor, planejar
from core.papel_vivo import POSICAO, ZERADO, Desejado, LigacaoViva, Retrato
from tests.mt5_falso import MT5Ordens

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
AG = T + timedelta(seconds=1)
PC = datetime(2026, 10, 9, 10, 0, 30)          # relógio do PC (atrás do servidor)
INST = {"tick_size": 5, "point_value": 0.2}
LOGIN, SERVIDOR = 1193398927, "ClearInvestimentos-DEMO"
D = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)


class Relogio:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def conta(envio=False, tipo="demo", limite=500.0):
    return {"login": LOGIN, "servidor": SERVIDOR, "limite": limite, "envio": envio,
            "tipo": tipo}


def retrato(contas=None, ligs=()):
    vivas = {l: LigacaoViva(ligacao_id=l, portfolio_id=1, status="rodando", motivo=None,
                            plano=None, modulo=None, fase="demo", conta_id=2,
                            ligada=True, desvio=10) for l in ligs}
    return Retrato(dia=DIA, lido_em=AG, ligacoes=vivas,
                   contas=contas if contas is not None else {2: conta()},
                   portfolio_de={l: 1 for l in ligs})


def pedido(cid=2, criado=PC, n=1):
    return {"id": f"teste{n}", "tipo": "ordem_teste", "conta_id": cid,
            "criado_em": criado.isoformat()}


class Cena:
    """Motor + MT5 falso + os dois relógios andando juntos."""

    def __init__(self, tmp_path, mt5=None, ms_envio=0.0):
        self.mt5 = mt5 or MT5Ordens()
        self.rel = Relogio()
        self.m = Motor(tmp_path, INST, mono=self.rel)
        self.m.teste.agora_pc = lambda: PC + timedelta(seconds=self.rel.t - 100.0)
        self.agora = AG
        if ms_envio:
            orig = self.mt5.order_send

            def lento(req):
                self.rel.t += ms_envio
                return orig(req)
            self.mt5.order_send = lento

    def passo(self, s=0.0, comandos_=None, ret=None, desejados=None, **kw):
        self.rel.t += s
        self.agora += timedelta(seconds=s)
        kw.setdefault("simbolo", "WINV26")
        kw.setdefault("contrato_ok", True)
        return self.m.passo(self.mt5, agora_srv=self.agora, retrato=ret or retrato(),
                            desejados=desejados or {}, disponivel=True,
                            comandos=comandos_ if comandos_ is not None else [],
                            conectado_ha_s=60.0, **kw)

    def evs(self, tipo):
        return [e for e in self.m.diario(DIA).eventos if e["tipo"] == tipo]

    def do_teste(self):
        return [r for r in self.mt5.enviados if r.get("magic") == K.MAGIC_TESTE]

    def posicoes_teste(self):
        return [p for p in self.mt5.posicoes.values() if p.magic == K.MAGIC_TESTE]


# ------------------------------------------------------------ caminho feliz
def test_caminho_feliz_uma_etapa_por_volta_e_teste_ok(tmp_path):
    c = Cena(tmp_path, ms_envio=0.120)
    # o Envio está DESLIGADO na conta: o teste independe dele
    est = c.passo(comandos_=[pedido()])
    ent = c.do_teste()
    assert len(ent) == 1
    e = ent[0]
    assert (e["action"], e["type"], e["volume"], e["magic"], e["comment"],
            e["symbol"]) == (1, 0, 1.0, 7_000_000, "df teste", "WINV26")
    assert e["type_filling"] == c.mt5.ORDER_FILLING_IOC and "sl" not in e
    assert c.mt5.checados and c.mt5.checados[-1]["magic"] == 7_000_000
    assert est["teste"]["situacao"] == "andamento"
    t = c.evs("teste")[-1]
    assert (t["etapa"], t["retcode"], t["preco"], t["atraso_ms"]) == (1, 10009, 189_000, 120)
    ticket = t["ticket"]
    assert ticket in c.mt5.posicoes

    c.passo(0.5)                                    # etapa 2: SL/TP a 100 pontos
    prot = c.do_teste()[-1]
    assert (prot["action"], prot["position"], prot["sl"], prot["tp"]) == \
        (6, ticket, 188_900, 189_100)
    assert c.evs("teste")[-1]["etapa"] == 2 and len(c.do_teste()) == 2

    c.passo(0.5)                                    # etapa 3: confere na posição
    assert c.evs("teste")[-1]["etapa"] == 3 and len(c.do_teste()) == 2

    c.passo(5.0)                                    # etapa 4: ainda esperando
    assert c.evs("teste")[-1]["etapa"] == 3 and ticket in c.mt5.posicoes
    c.passo(4.9)
    assert c.evs("teste")[-1]["etapa"] == 3
    c.passo(0.2)                                    # 10 s no relógio monotônico
    assert c.evs("teste")[-1]["etapa"] == 4 and len(c.do_teste()) == 2

    c.passo(0.1)                                    # etapa 5: sai pelo ticket
    sai = c.do_teste()[-1]
    assert (sai["action"], sai["position"], sai["type"], sai["magic"]) == \
        (1, ticket, 1, 7_000_000)
    assert ticket not in c.mt5.posicoes and c.evs("teste")[-1]["etapa"] == 5
    assert not c.evs("teste_ok")

    est = c.passo(0.1)                              # confere que sumiu
    ok = c.evs("teste_ok")
    assert len(ok) == 1 and not c.evs("teste_falhou")
    assert (ok[0]["entrada_ms"], ok[0]["protecao_ms"], ok[0]["saida_ms"]) == (120, 120, 120)
    assert est["teste"] == {"id": "teste1", "situacao": "ok", "etapa": 5,
                            "texto": "Teste ok — entrada 120 ms, proteção 120 ms, "
                                     "saída 120 ms", "quando": c.agora,
                            "pedidos": ["teste1"]}
    n = len(c.mt5.enviados)
    c.passo(1.0)
    assert len(c.mt5.enviados) == n                 # acabou: nada a mais


def test_comando_ordem_teste_vai_por_arquivo_e_passa_pelo_diario(tmp_path):
    c = Cena(tmp_path)
    pasta = tmp_path / "cmd"
    cid = comandos.escrever(pasta, "ordem_teste", conta_id=2)
    c.m.teste.agora_pc = datetime.now
    c.passo(comandos_=pasta)
    assert not list(pasta.glob("*.json"))
    cmd = [e for e in c.evs("comando") if e.get("motivo") == "ordem_teste"]
    assert len(cmd) == 1 and cmd[0]["comando_id"] == cid and cmd[0]["conta_id"] == 2
    assert len(c.do_teste()) == 1


# ----------------------------------------------------------- pré-condições
def _recusado(c, est, motivo):
    assert not c.do_teste(), "nenhuma ordem de teste pode sair"
    f = c.evs("teste_falhou")
    assert len(f) == 1 and f[0]["etapa"] == 0 and motivo in f[0]["motivo"]
    assert est["teste"]["situacao"] == "recusado"
    assert est["teste"]["texto"].startswith("Teste recusado: ")
    assert motivo in est["teste"]["texto"]


def test_recusa_conta_que_nao_e_demo_no_mt5(tmp_path):
    c = Cena(tmp_path)
    c.mt5.trade_mode = c.mt5.ACCOUNT_TRADE_MODE_REAL
    _recusado(c, c.passo(comandos_=[pedido()]), "não é DEMO")


def test_recusa_conta_de_competicao(tmp_path):
    c = Cena(tmp_path)
    c.mt5.trade_mode = c.mt5.ACCOUNT_TRADE_MODE_CONTEST
    _recusado(c, c.passo(comandos_=[pedido()]), "não é DEMO")


def test_recusa_conta_ilegivel_no_momento_do_teste(tmp_path):
    c = Cena(tmp_path)
    orig = c.mt5.account_info
    chamadas = []

    def segunda_falha():
        chamadas.append(1)
        return orig() if len(chamadas) == 1 else None   # a da foto lê; a do teste não
    c.mt5.account_info = segunda_falha
    _recusado(c, c.passo(comandos_=[pedido()]), "dados da conta ilegíveis")


def test_recusa_pedido_de_outra_conta(tmp_path):
    c = Cena(tmp_path)
    _recusado(c, c.passo(comandos_=[pedido(cid=3)]), "deste pedido")


def test_recusa_conta_cadastrada_como_real(tmp_path):
    c = Cena(tmp_path)
    _recusado(c, c.passo(comandos_=[pedido()], ret=retrato({2: conta(tipo="real")})),
              "cadastrada como demo")


def test_recusa_mt5_logado_em_outra_conta(tmp_path):
    c = Cena(tmp_path)
    c.mt5.login = 999
    _recusado(c, c.passo(comandos_=[pedido()]), "conta cadastrada")


def test_recusa_fora_do_pregao(tmp_path):
    c = Cena(tmp_path)
    _recusado(c, c.passo(comandos_=[pedido()], no_pregao=False), "fora do pregão")


def test_recusa_algo_trading_desligado(tmp_path):
    c = Cena(tmp_path)
    c.mt5.algo = False
    _recusado(c, c.passo(comandos_=[pedido()]), "Algo Trading desligado")


def test_recusa_conta_travada(tmp_path):
    c = Cena(tmp_path)
    c.m.diario(DIA).registrar("conta_travada", quando=T, conta_id=2, perda=460.0,
                              limite=500.0)
    _recusado(c, c.passo(comandos_=[pedido()]), "conta travada")


def test_recusa_sem_contrato_do_dia(tmp_path):
    c = Cena(tmp_path)
    _recusado(c, c.passo(comandos_=[pedido()], simbolo=None, contrato_ok=False),
              "contrato do dia")


def test_recusa_guarda_de_preco_presa(tmp_path):
    c = Cena(tmp_path)
    _recusado(c, c.passo(comandos_=[pedido()], contrato_ok=False), "guarda de preço")


def test_recusa_pedido_antigo(tmp_path):
    c = Cena(tmp_path)
    _recusado(c, c.passo(comandos_=[pedido(criado=PC - timedelta(seconds=61))]),
              "pedido antigo")


def test_recusa_segundo_teste_com_um_em_andamento(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    assert len(c.do_teste()) == 1
    est = c.passo(0.5, comandos_=[pedido(n=2)])
    f = c.evs("teste_falhou")
    assert len(f) == 1 and f[0]["teste_id"] == "teste2"
    assert "em andamento" in f[0]["motivo"]
    # o primeiro segue: a proteção dele saiu nesta volta, nenhuma 2ª entrada
    assert [r["action"] for r in c.do_teste()] == [1, 6]
    # a tela segue mostrando o teste em andamento, e sabe que o 2º chegou
    assert est["teste"]["id"] == "teste1" and est["teste"]["situacao"] == "andamento"
    assert est["teste"]["pedidos"] == ["teste1", "teste2"]


def test_recusa_pela_corretora_sem_leitura(tmp_path):
    c = Cena(tmp_path)
    c.mt5.erro_leitura = True
    est = c.passo(comandos_=[pedido()])
    _recusado(c, est, "sem leitura")


def test_envio_desligado_nao_impede_e_envio_ligado_tambem_roda(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()], ret=retrato({2: conta(envio=True)}))
    assert len(c.do_teste()) == 1 and not c.evs("teste_falhou")


# ------------------------------------------------------ falhas no meio
def test_sltp_recusado_falha_na_etapa_2_e_encerra(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.mt5.roteiro = [10016]                         # SLTP recusada (não passageira)
    est = c.passo(0.5)
    f = c.evs("teste_falhou")
    assert len(f) == 1 and f[0]["etapa"] == 2 and f[0]["retcode"] == 10016
    assert est["teste"]["texto"] == "Teste falhou na etapa 2: stop ou alvo inválido"
    assert ticket in c.mt5.posicoes                 # o encerramento vem na volta seguinte
    c.passo(0.5)
    sai = c.do_teste()[-1]
    assert sai["position"] == ticket and ticket not in c.mt5.posicoes
    assert c.evs("teste")[-1]["etapa"] == "encerrar"
    assert not c.evs("teste_ok")
    # limpo: depois do prazo da lista o teste termina e um novo pode rodar
    c.passo(5.0)
    assert c.m.teste.atual is None
    c.passo(0.1, comandos_=[pedido(n=2, criado=PC + timedelta(seconds=6))])
    assert sum(1 for r in c.do_teste() if r["action"] == 1 and "position" not in r) == 2


def test_saida_recusada_chama_depois_de_10_s_e_fecha_quando_some(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.passo(0.5)
    c.passo(0.5)
    c.passo(10.0)                                   # etapa 4 concluída
    c.mt5.roteiro = [10017] * 40                    # saída recusada sempre (não passageira)
    est = c.passo(0.1)
    assert c.evs("teste_falhou")[0]["etapa"] == 5
    assert est["teste"]["texto"].startswith("Teste falhou na etapa 5: ")
    envios_antes = len(c.do_teste())
    c.passo(0.5)                                    # menos de 1 s: não reenvia
    assert len(c.do_teste()) == envios_antes
    for _ in range(9):
        est = c.passo(1.0)
        assert not any(ch["tipo"] == "teste_preso" for ch in est["chamados"])
    assert len(c.do_teste()) == envios_antes + 9    # tentou a cada 1 s
    est = c.passo(1.0)                              # recusada há mais de 10 s
    preso = [ch for ch in est["chamados"] if ch["tipo"] == "teste_preso"]
    assert len(preso) == 1
    assert preso[0]["texto"] == "posição de teste não fecha — encerre no MT5"
    assert any(e.get("chave") == "teste_preso" for e in c.evs("chamado"))
    # recusas seguintes não enchem o diário
    assert sum(1 for e in c.evs("teste") if e.get("etapa") == "encerrar") == 0
    c.mt5.roteiro = []                              # a corretora volta a aceitar
    c.passo(1.0)
    assert ticket not in c.mt5.posicoes
    est = c.passo(1.0)
    assert not any(ch["tipo"] == "teste_preso" for ch in est["chamados"])
    assert any(e.get("motivo") == "teste_preso" for e in c.evs("chamado_fechado"))
    assert c.m.teste.atual is None


def test_entrada_recusada_falha_na_etapa_1_sem_posicao(tmp_path):
    c = Cena(tmp_path)
    c.mt5.roteiro = [10019]                         # sem margem
    est = c.passo(comandos_=[pedido()])
    assert est["teste"]["texto"] == "Teste falhou na etapa 1: sem margem"
    assert not c.posicoes_teste()


def test_checagem_recusada_nao_envia(tmp_path):
    c = Cena(tmp_path)
    c.mt5.check_retcode, c.mt5.check_comment = 10019, "No money"
    est = c.passo(comandos_=[pedido()])
    assert est["teste"]["texto"] == "Teste falhou na etapa 1: sem margem"
    assert not c.do_teste()
    assert c.evs("teste_falhou")[0]["comment"] == "No money"


def test_entrada_sem_resposta_que_executou_e_encerrada(tmp_path):
    c = Cena(tmp_path)
    c.mt5.roteiro = ["executou_sem_resposta"]
    c.passo(comandos_=[pedido()])
    assert c.evs("teste_falhou")[0]["etapa"] == 1
    assert len(c.posicoes_teste()) == 1
    c.passo(0.5)
    assert not c.posicoes_teste()


def test_posicao_sai_pelo_stop_durante_a_espera(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.passo(0.5)
    c.passo(0.5)
    c.mt5.stopar(ticket)
    est = c.passo(2.0)
    assert c.evs("teste_falhou")[0]["etapa"] == 4
    assert "antes do fim da espera" in est["teste"]["texto"]


def test_preenchimento_recusado_usa_o_modo_seguinte(tmp_path):
    c = Cena(tmp_path)
    c.mt5.roteiro = [10030, 10009]
    c.passo(comandos_=[pedido()])
    modos = [r["type_filling"] for r in c.do_teste()]
    assert modos == [c.mt5.ORDER_FILLING_IOC, c.mt5.ORDER_FILLING_FOK]
    assert c.evs("teste")[-1]["etapa"] == 1


# ------------------------------------------------------------- reinício
def test_reinicio_com_posicao_de_teste_encerra(tmp_path):
    mt5 = MT5Ordens()
    t = mt5.abrir_manual(1, magic=K.MAGIC_TESTE)
    c = Cena(tmp_path, mt5=mt5)                    # motor novo: nada em memória
    est = c.passo()
    assert t not in mt5.posicoes
    sai = c.do_teste()
    assert len(sai) == 1 and sai[0]["position"] == t
    assert any("sobrou" in (e.get("motivo") or "") for e in c.evs("teste"))
    # não é "posição fora da automação" na tela
    assert est["posicao_fora"] == []


def test_reinicio_fora_do_pregao_tambem_encerra(tmp_path):
    mt5 = MT5Ordens()
    t = mt5.abrir_manual(1, magic=K.MAGIC_TESTE)
    c = Cena(tmp_path, mt5=mt5)
    c.passo(no_pregao=False)
    assert t not in mt5.posicoes


def test_posicao_a_mao_nunca_e_tocada_pelo_teste(tmp_path):
    mt5 = MT5Ordens()
    t = mt5.abrir_manual(1, magic=0)
    c = Cena(tmp_path, mt5=mt5)
    c.passo()
    assert t in mt5.posicoes and not c.do_teste()


# ------------------------------------------ automação ignora o magic do teste
def test_magic_do_teste_fica_fora_da_faixa_das_ligacoes():
    assert K.MAGIC_TESTE == 7_000_000
    assert K.ligacao_do_magic(K.MAGIC_TESTE) is None
    assert K.ligacao_do_magic(K.MAGIC_TESTE + 1) == 1


def test_planejar_e_zerar_ignoram_a_posicao_de_teste(tmp_path):
    mt5 = MT5Ordens()
    t = mt5.abrir_manual(1, magic=K.MAGIC_TESTE)
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    c = Cena(tmp_path, mt5=mt5)
    dia = c.m.diario(DIA)
    for desejados in ({4: Desejado(ZERADO, motivo="zerar tudo")}, {4: D}, {}):
        acoes = planejar(desejados, True, foto, dia, AG, 5, 60.0)
        assert all(a.ticket != t for a in acoes), acoes
    # sem papel (só proteção): também nada
    assert all(a.ticket != t for a in planejar({}, False, foto, dia, AG, 5, 60.0))
    # "Encerrar posição" da tela só vale para o magic da automação
    assert c.m._encerrar_pedidos([], foto, {t}, dia, AG) == []


def test_zerar_tudo_no_meio_do_teste_falha_e_encerra(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.passo(0.5)                                    # protegida
    est = c.passo(0.5, comandos_=[{"id": "z", "tipo": "zerar_tudo",
                                   "criado_em": PC.isoformat()}])
    f = c.evs("teste_falhou")
    assert f and "Zerar tudo" in f[0]["motivo"]
    c.passo(1.0)
    assert ticket not in c.mt5.posicoes


# ------------------------------------- o teste não atrasa as estratégias
def test_estrategia_e_teste_na_mesma_volta_estrategia_primeiro(tmp_path):
    c = Cena(tmp_path)
    ret = retrato({2: conta(envio=True)}, ligs=(4,))
    c.passo(comandos_=[pedido()], ret=ret, desejados={4: D})
    magics = [r.get("magic") for r in c.mt5.enviados]
    # entrada e proteção da ligação 4 antes da entrada do teste
    assert magics[:2] == [K.magic(4), K.magic(4)]
    assert magics[2] == K.MAGIC_TESTE
    assert c.evs("executada") and c.evs("teste")


def test_teste_em_espera_nao_segura_a_entrada_da_estrategia(tmp_path):
    c = Cena(tmp_path)
    ret = retrato({2: conta(envio=True)}, ligs=(4,))
    c.passo(comandos_=[pedido()], ret=ret)
    c.passo(0.5, ret=ret)
    c.passo(0.5, ret=ret)                           # teste esperando os 10 s
    n = len(c.mt5.enviados)
    d = Desejado(POSICAO, lado=1, entry_ts=c.agora, entry_px=189_000,
                 stop_px=188_800, alvo_px=189_400, contratos=2)
    c.passo(0.2, ret=ret, desejados={4: d})
    novos = c.mt5.enviados[n:]
    assert [r["magic"] for r in novos] == [K.magic(4), K.magic(4)]


def test_nada_dorme_no_caminho_do_teste(monkeypatch, tmp_path):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: (_ for _ in ()).throw(
        AssertionError("sleep no caminho da ordem")))
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    for s in (0.5, 0.5, 10.0, 0.1, 0.1):
        c.passo(s)
    assert c.evs("teste_ok")


def test_erro_no_meio_falha_e_segue_para_o_encerramento(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    orig = c.mt5.order_send

    def quebra(req):
        if req["action"] == 6:
            raise RuntimeError("IPC caiu")
        return orig(req)
    c.mt5.order_send = quebra
    est = c.passo(0.5)
    assert c.evs("teste_falhou")[0]["etapa"] == 2
    assert "IPC caiu" in est["teste"]["texto"]
    c.passo(1.0)
    assert ticket not in c.mt5.posicoes


def test_textos_da_tela():
    assert OT.texto_ok({"entrada": 85, "protecao": 40, "saida": 90}) == \
        "Teste ok — entrada 85 ms, proteção 40 ms, saída 90 ms"
    assert OT.texto_falhou(3, "x") == "Teste falhou na etapa 3: x"
    assert OT.texto_falhou(0, "fora do pregão") == "Teste recusado: fora do pregão"


# ============================================ rodada 1: 10008 e passageiras
def _ate_a_saida(c):
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.passo(0.5)
    c.passo(0.5)
    c.passo(10.0)                                   # etapa 4 concluída
    return ticket


def test_entrada_aceita_10008_e_a_posicao_aparece_completa(tmp_path):
    c = Cena(tmp_path)
    c.mt5.roteiro = [10008]
    c.passo(comandos_=[pedido()])
    assert not c.evs("teste_falhou") and c.m.teste.atual["fase"] == "aguarda"
    ordem = next(iter(c.mt5.ordens))
    c.passo(1.0)                                    # ainda não executou: espera
    assert not c.evs("teste_falhou")
    c.mt5.executar_pendente(ordem)                  # a bolsa executou
    c.passo(1.0)
    assert c.m.teste.atual["fase"] == "protecao"
    for s in (0.5, 0.5, 10.0, 0.1, 0.1):
        c.passo(s)
    assert c.evs("teste_ok") and not c.evs("teste_falhou")
    assert not c.posicoes_teste()


def test_entrada_aceita_sem_posicao_em_10_s_cancela_a_ordem_e_falha_limpo(tmp_path):
    c = Cena(tmp_path)
    c.mt5.roteiro = [10008]
    c.passo(comandos_=[pedido()])
    ordem = next(iter(c.mt5.ordens))
    c.passo(9.0)
    assert not c.evs("teste_falhou")
    est = c.passo(1.5)                              # passou dos 10 s
    f = c.evs("teste_falhou")
    assert len(f) == 1 and f[0]["etapa"] == 1 and "10 s" in f[0]["motivo"]
    assert est["teste"]["texto"].startswith("Teste falhou na etapa 1: ")
    c.passo(0.5)
    cancel = [r for r in c.mt5.enviados if r["action"] == c.mt5.TRADE_ACTION_REMOVE]
    assert [r["order"] for r in cancel] == [ordem] and not c.mt5.ordens
    assert not c.posicoes_teste()
    c.passo(6.0)
    assert c.m.teste.atual is None and not c.evs("teste_ok")


def test_saida_aceita_10008_e_a_posicao_some_teste_ok(tmp_path):
    c = Cena(tmp_path)
    ticket = _ate_a_saida(c)
    c.mt5.roteiro = [10008]
    c.passo(0.1)                                    # saída aceita pela bolsa
    assert not c.evs("teste_falhou") and ticket in c.mt5.posicoes
    assert c.m.teste.atual["fase"] == "saida_confere"
    ordem = next(iter(c.mt5.ordens))
    c.passo(1.0)
    c.passo(5.5)                                    # aceita: espera além dos 5 s da lista
    assert not c.evs("teste_falhou")
    c.mt5.executar_pendente(ordem)
    est = c.passo(0.5)
    assert c.evs("teste_ok") and not c.evs("teste_falhou")
    assert est["teste"]["situacao"] == "ok"


def test_saida_ja_encerrada_10036_vai_conferir_e_nao_falha(tmp_path):
    c = Cena(tmp_path)
    ticket = _ate_a_saida(c)
    c.mt5.roteiro = [10036]
    c.passo(0.1)
    assert not c.evs("teste_falhou")
    c.mt5.stopar(ticket)
    c.passo(0.5)
    assert c.evs("teste_ok")


@pytest.mark.parametrize("rc", [10004, 10020, 10021, 10028, 10029])
def test_sltp_passageira_tenta_de_novo_e_completa(tmp_path, rc):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    c.mt5.roteiro = [rc, rc]
    c.passo(0.5)                                    # 1ª: passageira
    assert not c.evs("teste_falhou")
    n = len(c.do_teste())
    c.passo(0.5)                                    # < 1 s: não reenvia
    assert len(c.do_teste()) == n
    c.passo(0.6)                                    # 2ª: passageira de novo
    c.passo(1.0)                                    # 3ª: aceita
    assert [e["etapa"] for e in c.evs("teste")][-1] == 2
    for s in (0.5, 10.0, 0.1, 0.1):
        c.passo(s)
    assert c.evs("teste_ok") and not c.evs("teste_falhou")


def test_sltp_passageira_por_mais_de_5_s_falha_e_encerra(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.mt5.roteiro = [10020] * 10
    c.passo(0.5)
    for _ in range(5):
        c.passo(1.0)
    assert not c.evs("teste_falhou")
    c.passo(1.0)                                    # 6 s desde a 1ª
    f = c.evs("teste_falhou")
    assert len(f) == 1 and f[0]["etapa"] == 2 and "preço mudou" in f[0]["motivo"]
    c.mt5.roteiro = []
    c.passo(1.0)
    assert ticket not in c.mt5.posicoes


def test_sltp_sem_resposta_que_chegou_nao_reenvia(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    c.mt5.roteiro = ["executou_sem_resposta"]
    c.passo(0.5)
    n = len(c.do_teste())
    c.passo(1.0)
    assert len(c.do_teste()) == n                   # já estava na posição
    assert c.evs("teste")[-1]["etapa"] == 2


def test_saida_passageira_tenta_de_novo_e_completa(tmp_path):
    c = Cena(tmp_path)
    ticket = _ate_a_saida(c)
    c.mt5.roteiro = [10004]
    c.passo(0.1)
    assert not c.evs("teste_falhou") and ticket in c.mt5.posicoes
    c.passo(1.0)                                    # de novo: executa
    assert ticket not in c.mt5.posicoes
    c.passo(0.1)
    assert c.evs("teste_ok") and not c.evs("teste_falhou")


def test_saida_passageira_por_mais_de_5_s_falha_e_segue_encerrando(tmp_path):
    c = Cena(tmp_path)
    ticket = _ate_a_saida(c)
    c.mt5.roteiro = [10004] * 20
    c.passo(0.1)
    for _ in range(5):
        c.passo(1.0)
    assert not c.evs("teste_falhou")
    c.passo(1.0)
    assert c.evs("teste_falhou")[0]["etapa"] == 5
    c.mt5.roteiro = []
    c.passo(1.0)
    assert ticket not in c.mt5.posicoes


# ------------------------------------------------------ rodada 1: pequenos
def _pendente(mt5):
    mt5.ordens[555] = NS(ticket=555, magic=K.MAGIC_TESTE, symbol="WINV26",
                         volume_current=1.0, time_setup=0, type=0, req={})


def test_recusa_com_ordem_de_teste_pendente(tmp_path):
    c = Cena(tmp_path)
    _pendente(c.mt5)
    est = c.passo(comandos_=[pedido()])
    f = c.evs("teste_falhou")
    assert len(f) == 1 and "ordem de teste pendente" in f[0]["motivo"]
    assert not [r for r in c.do_teste() if r["action"] == 1]
    assert est["teste"]["situacao"] == "recusado"


def test_entrada_sem_resposta_segura_um_teste_novo_por_10_s(tmp_path):
    c = Cena(tmp_path)
    c.mt5.roteiro = [None]                          # sem resposta, não executou
    c.passo(comandos_=[pedido()])
    assert c.evs("teste_falhou")[0]["etapa"] == 1
    c.passo(6.0, comandos_=[pedido(n=2, criado=PC + timedelta(seconds=6))])
    assert "em andamento" in c.evs("teste_falhou")[-1]["motivo"]
    c.passo(5.0)                                    # 11 s sem nada: limpo
    assert c.m.teste.atual is None
    c.passo(0.1, comandos_=[pedido(n=3, criado=PC + timedelta(seconds=11))])
    entradas = [r for r in c.do_teste() if r["action"] == 1 and "position" not in r]
    assert len(entradas) == 2


def test_fora_do_pregao_nao_reenvia_a_cada_1_s_e_o_chamado_fica(tmp_path):
    mt5 = MT5Ordens()
    t = mt5.abrir_manual(1, magic=K.MAGIC_TESTE)
    c = Cena(tmp_path, mt5=mt5)
    mt5.roteiro = [10018] * 50                      # mercado fechado
    c.passo(no_pregao=False)
    assert len(c.do_teste()) == 1
    for _ in range(12):
        est = c.passo(1.0, no_pregao=False)
    assert len(c.do_teste()) == 1                   # nada de reenviar fechado
    assert any(ch["tipo"] == "teste_preso" for ch in est["chamados"])
    est = c.passo(30.0, no_pregao=False)
    assert any(ch["tipo"] == "teste_preso" for ch in est["chamados"])
    mt5.roteiro = []
    c.passo(1.0)                                    # no pregão: tenta de novo
    assert t not in mt5.posicoes


def test_ordem_pendente_que_nao_cancela_chama_depois_de_10_s(tmp_path):
    mt5 = MT5Ordens()
    _pendente(mt5)
    c = Cena(tmp_path, mt5=mt5)
    mt5.roteiro = [10017] * 30
    c.passo()
    for _ in range(10):
        est = c.passo(1.0)
        assert not any(ch["tipo"] == "teste_preso" for ch in est["chamados"])
    est = c.passo(1.0)
    assert any(ch["tipo"] == "teste_preso" for ch in est["chamados"])


def test_sobra_em_conta_nao_demo_nunca_e_tocada(tmp_path):
    mt5 = MT5Ordens()
    t = mt5.abrir_manual(1, magic=K.MAGIC_TESTE)
    mt5.trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    c = Cena(tmp_path, mt5=mt5)
    c.passo()
    c.passo(2.0)
    assert t in mt5.posicoes and not c.do_teste()


def test_encerramento_para_se_a_conta_deixa_de_ser_demo(tmp_path):
    c = Cena(tmp_path)
    c.passo(comandos_=[pedido()])
    ticket = c.evs("teste")[-1]["ticket"]
    c.mt5.roteiro = [10016]
    c.passo(0.5)                                    # falha na etapa 2
    c.mt5.trade_mode = c.mt5.ACCOUNT_TRADE_MODE_REAL
    n = len(c.do_teste())
    c.passo(1.0)
    assert len(c.do_teste()) == n and ticket in c.mt5.posicoes


def test_motor_real_recusa_ordem_de_teste_e_nao_envia_nada(tmp_path):
    # o processo da conta real nunca manda a ordem de teste, nem com a conta
    # real na mão: recusa com o motivo próprio, antes de qualquer pré-condição
    mt5 = MT5Ordens(trade_mode=2)
    c = Cena(tmp_path, mt5=mt5)
    c.m = Motor(tmp_path, INST, origem="real", mono=c.rel)
    c.m.teste.agora_pc = lambda: PC
    est = c.passo(comandos_=[pedido()], ret=retrato({2: conta(tipo="real")}))
    assert not c.do_teste() and not mt5.enviados
    assert [e["motivo"] for e in c.evs("teste_falhou")] == ["ordem de teste só na conta demo"]
    assert est["teste"]["situacao"] == "recusado"
