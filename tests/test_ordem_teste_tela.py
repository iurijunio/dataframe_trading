"""A "Ordem de teste" no Diário do dia (o botão está fora da tela; o motor
continua). Só strings como filhos: um dicionário como filho quebra o
desenho do Dash.
"""
from datetime import datetime

from dash import html

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
    # a linha do chamado: etiqueta, chip de conta, texto, botões
    botoes = [b for b in f.children[0].children[3].children
              if isinstance(b, html.Button)]
    assert [b.id["acao"] for b in botoes] == ["manter"]
