"""A "Ordem de teste" na tela Operação: o botão de dois cliques (arma e
expira em 6 s, conferido no servidor), o comando-arquivo, o texto ao lado
do botão e o Diário do dia. Só strings como filhos: um dicionário como
filho quebra o desenho do Dash e devolve o menu à aba anterior.
"""
from datetime import datetime

from dash import html, no_update

from core import comandos
from ui import callbacks_operacao as CO
from ui.components import operacao_panel as OP
from ui.components import ordens_panel as OR


def _filhos_sao_componentes_ou_texto(c):
    """Nenhum dict/objeto estranho em lugar nenhum da árvore."""
    if c is None or isinstance(c, (str, int, float)):
        return
    if isinstance(c, (list, tuple)):
        for x in c:
            _filhos_sao_componentes_ou_texto(x)
        return
    assert hasattr(c, "_namespaces") or hasattr(c, "to_plotly_json"), repr(c)
    _filhos_sao_componentes_ou_texto(getattr(c, "children", None))


# ------------------------------------------------------------------ botão
def test_botao_ao_lado_do_envio_so_com_conta_demo():
    pf = {"portfolio_id": 1, "ligado": True}
    b = OP.botoes_portfolio(pf, None, conta_id=2, envio=False)
    ids = [x.id for x in b]
    assert ids[0]["acao"] == "envio-ligar"
    assert ids[1] == {"type": "av-op-teste", "id": 2}
    assert b[1].children == "Ordem de teste"
    sem = OP.botoes_portfolio(pf, None, conta_id=None, envio=None)
    assert all(getattr(x, "id", {}).get("type") != "av-op-teste" for x in sem)


def test_estado_do_botao_armado():
    assert OP.estado_teste(2, "teste:2")[0] == "Confirmar?"
    assert OP.estado_teste(2, None)[0] == "Ordem de teste"
    assert OP.estado_teste(2, "teste:3")[0] == "Ordem de teste"


# ------------------------------------------------------ dois cliques, 6 s
def test_primeiro_clique_arma_sem_escrever_comando():
    armado, enviado, aviso = CO.acao_teste(2, None, 1000.0)
    assert armado == {"chave": "teste:2", "em": 1000.0}
    assert enviado is no_update and "clique de novo" in aviso
    assert comandos.consumir(comandos.PASTA) == []


def test_segundo_clique_em_6_s_escreve_o_comando():
    armado, _, _ = CO.acao_teste(2, None, 1000.0)
    armado2, enviado, aviso = CO.acao_teste(2, armado, 1005.9)
    assert armado2 is None and "pedida" in aviso
    lidos = comandos.consumir(comandos.PASTA)
    assert len(lidos) == 1 and lidos[0]["tipo"] == "ordem_teste"
    assert lidos[0]["conta_id"] == 2 and lidos[0]["id"] == enviado["id"]
    assert enviado["em"] == 1005.9


def test_segundo_clique_depois_de_6_s_so_arma_de_novo():
    armado, _, _ = CO.acao_teste(2, None, 1000.0)
    armado2, enviado, _ = CO.acao_teste(2, armado, 1006.5)
    assert armado2 == {"chave": "teste:2", "em": 1006.5} and enviado is no_update
    assert comandos.consumir(comandos.PASTA) == []


def test_armado_de_outra_acao_nao_confirma_o_teste():
    _, enviado, _ = CO.acao_teste(2, {"chave": "encerrar:55", "em": 1000.0}, 1001.0)
    assert enviado is no_update and comandos.consumir(comandos.PASTA) == []


# ------------------------------------------------------ texto ao lado
def test_texto_esperando_resultado_e_captura_parada():
    env = {"id": "abc", "em": 1000.0}
    assert "esperando a captura" in CO.texto_teste({}, env, 1010.0)
    assert "não respondeu" in CO.texto_teste({}, env, 1100.0)
    ok = {"teste": {"id": "abc", "situacao": "ok", "pedidos": ["abc"],
                    "texto": "Teste ok — entrada 85 ms, proteção 40 ms, saída 90 ms"}}
    assert CO.texto_teste(ok, env, 1010.0).startswith("Teste ok — entrada 85 ms")
    # sem pedido desta tela: o último resultado do dia
    assert CO.texto_teste(ok, None, 1010.0).startswith("Teste ok")
    assert CO.texto_teste(None, None, 0.0) == ""
    # lixo no estado nunca vira filho que não seja texto
    assert CO.texto_teste({"teste": {"texto": {"x": 1}}}, None, 0.0) == ""
    assert CO.texto_teste({"teste": "x"}, None, 0.0) == ""


def test_pulso_tem_a_saida_do_teste():
    assert "av-op-teste-res.children" in CO.SAIDAS_DO_PULSO


def test_layout_tem_o_texto_e_os_stores():
    bloco = OP.bloco()
    ids = set()

    def andar(c):
        if isinstance(c, (list, tuple)):
            for x in c:
                andar(x)
            return
        if getattr(c, "id", None) is not None and isinstance(c.id, str):
            ids.add(c.id)
        ch = getattr(c, "children", None)
        if ch is not None and not isinstance(ch, str):
            andar(ch)
    andar(bloco)
    assert {"av-op-teste-res", "av-op-teste-armado", "av-op-teste-enviado"} <= ids


# ------------------------------------------------------- Diário do dia
Q = datetime(2026, 10, 15, 10, 1, 2)


def _ev(tipo, **k):
    return dict({"tipo": tipo, "quando": Q, "ligacao_id": None}, **k)


def test_diario_mostra_cada_etapa_e_o_desfecho_so_com_texto():
    evs = [
        _ev("comando", motivo="ordem_teste"),
        _ev("teste", etapa=1, motivo="executada", preco=189_000, atraso_ms=85,
            retcode=10009),
        _ev("teste", etapa=2, motivo="executada", stop_px=188_900, alvo_px=189_100,
            atraso_ms=40),
        _ev("teste", etapa="encerrar", motivo="posição de teste encerrada"),
        _ev("teste_ok", motivo="Teste ok — entrada 85 ms, proteção 40 ms, saída 90 ms"),
        _ev("teste_falhou", etapa=2, motivo="recusada pela corretora", retcode=10006),
        _ev("teste_falhou", etapa=0, motivo="fora do pregão"),
    ]
    d = OR.diario_do_dia(evs, {})
    _filhos_sao_componentes_ou_texto(d)
    txt = " | ".join(str(linha.children[2].children) for linha in d.children)
    assert "Ordem de teste pedida na tela" in txt
    assert "etapa 1 (compra a mercado): executada · a 189.000 · 85 ms" in txt
    assert "stop 188.900 · alvo 189.100" in txt
    assert "Teste ok — entrada 85 ms" in txt
    assert "Teste falhou na etapa 2: recusada pela corretora" in txt
    assert "Teste recusado: fora do pregão" in txt
    so = OR.diario_do_dia(evs, {}, so_problemas=True)
    assert len(so.children) == 2      # as duas falhas


def test_chamado_teste_preso_sem_botao_encerrar():
    o = {"chamados": [{"tipo": "teste_preso", "texto": "posição de teste não fecha "
                       "— encerre no MT5", "ticket": None, "chave": "teste_preso"}]}
    f = OR.faixa_chamados(o, {})
    _filhos_sao_componentes_ou_texto(f)
    botoes = [b for b in f.children[0].children[2].children
              if isinstance(b, html.Button)]
    assert [b.id["acao"] for b in botoes] == ["manter"]


def test_redesenho_mantem_o_botao_armado():
    pf = {"portfolio_id": 1, "ligado": True}
    b = OP.botoes_portfolio(pf, None, conta_id=2, envio=False, teste_armado="teste:2")
    assert b[1].children == "Confirmar?" and "av-armado" in b[1].className

