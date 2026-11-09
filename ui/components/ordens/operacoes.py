"""Ordens: operações da demo e diário do dia."""
from __future__ import annotations

from dash import html

from core.ordem_teste import ETAPAS as ETAPAS_TESTE
from core.ordem_teste import texto_falhou as texto_teste_falhou
from core.ordens import ZERAR_DESCARTADO
from core.papel_leitura import checagem_ensaio

from ..cartao import dica, num

from .base import PROBLEMAS, _COMANDOS_INTERNOS, _INTERNOS, _decimal, _etiqueta, _hora, _int_sinal, _lado, _nome, _nome_tab, _preco, _reais, _rs, _sinal, _vazio
from .posicoes import _chip_conta, _th


# ====================================================== operações da demo
_SITUACOES = {
    "seria_enviada": ("seria enviada", "cinza",
                      "Envio de ordens desligado: a automação calculou a ordem e "
                      "não mandou (ensaio). Confira lado, contratos, stop e alvo "
                      "contra o papel."),
    "recusada_perdida": ("entrada recusada · perdida", "ambar",
                         "A corretora recusou a entrada e a janela de 30 s passou. "
                         "A variante segue; só esta operação ficou de fora."),
    "fora_do_ar": ("não executada · automação fora do ar", "ambar",
                   "Na hora do sinal a automação estava parada (captura ou MT5 "
                   "fora). A operação ficou só no papel."),
    "perdida": ("entrada perdida", "ambar",
                "A entrada não saiu dentro da janela de 30 s."),
    "nao_entrou": ("não entrou", "ambar",
                   "A automação barrou a entrada antes de enviar (limite do dia, "
                   "preço longe do stop do papel...)."),
    "recusada": ("recusada · tentando", "ambar", None),
    "enviando": ("enviando", "info", None),
    "aberta": ("aberta", "info", None),
}


def _situacao_demo(l: dict):
    sit = l.get("situacao")
    if sit == "fechada":
        # por onde saiu já está na coluna Saída ("11:20 alvo"); aqui só a nota
        filhos = [] if l.get("nota") else [html.Span("—", className="mut")]
    else:
        rot, tom, explica = _SITUACOES.get(sit, (sit or "—", "cinza", None))
        if sit in ("perdida", "nao_entrou") and l.get("nota"):
            explica = f"{explica} Motivo: {l['nota']}."
        filhos = [_etiqueta(rot, tom, explica)]
    if sit == "seria_enviada" and l.get("pedido"):
        filhos.append(html.Span(f" {l['pedido']}", className="mut"))
    if sit == "seria_enviada" and l.get("checagem"):
        filhos.append(html.Span(f" · {l['checagem']}", className="ord-pend"))
    elif sit == "fechada" and l.get("nota"):
        filhos.append(html.Span(l["nota"], className="ord-pend"))
    return filhos


def _saida_demo(l: dict) -> str:
    """"11:20 alvo": a hora e por onde saiu, numa célula (rascunho v4)."""
    hora = _hora(l.get("exit_ts"))
    if l.get("situacao") == "fechada":
        motivo = str(l.get("saida_motivo") or "").replace(" na corretora", "")
        return f"{hora} {motivo}".strip()
    return hora


def _tom_derrap(l: dict) -> str:
    """Âmbar acima de 2 ticks numa ponta; verde quando a demo executou
    melhor que o papel (nenhuma ponta pior e alguma melhor)."""
    pontas = [x for x in (l.get("derrapagem_entrada"), l.get("derrapagem_saida"))
              if x is not None]
    if not pontas:
        return ""
    if max(pontas) > 2:
        return " aviso"
    if max(pontas) <= 0 and min(pontas) < 0:
        return " pos"
    return ""


def _derrap(l: dict) -> str:
    e, s = l.get("derrapagem_entrada"), l.get("derrapagem_saida")
    if e is None and s is None:
        return "—"
    return f"{_decimal(e)} · {_decimal(s)}"


def operacoes_demo(linhas: list[dict], origem: str = "demo"):
    """A tabela "Operações do dia" da conta (demo, ou real com
    `origem="real"`; a mesma régua nas duas). A derrapagem vai por ponta
    (entrada · saída), em ticks, ALÉM da que o plano supõe (o preço do papel
    já a inclui), positivo = pior."""
    if not linhas:
        nome = "real" if origem == "real" else "demo"
        return _vazio(f"nenhuma operação na {nome} hoje",
                      "Com as variantes só no papel esta tabela fica vazia; as "
                      "operações do papel estão logo abaixo, em Papel.")
    corpo = []
    for l in linhas:
        executou = l.get("preco_entrada") is not None
        corpo.append(html.Tr([
            html.Td(_hora(l.get("entry_ts"))),
            html.Td(_saida_demo(l)),
            html.Td(_nome_tab(l.get("variante")), className="t"),
            html.Td(_lado(l.get("lado"))),
            html.Td(_decimal(l.get("contratos")) if executou else "—", className="n"),
            html.Td(_preco(l.get("preco_entrada")), className="n"),
            html.Td(_preco(l.get("preco_saida")), className="n"),
            html.Td(_derrap(l), className="n" + _tom_derrap(l)),
            html.Td(_int_sinal(l.get("pontos")), className="n " + _sinal(l.get("pontos"))),
            html.Td(_rs(l.get("resultado")) if l.get("resultado") is not None else "—",
                    className="n " + _sinal(l.get("resultado"))),
            html.Td(_situacao_demo(l), className="t"),
        ], className="op-linha" + (" op-aberta" if l.get("situacao") == "aberta" else "")))
    cab = html.Tr([
        _th("Entrada"), _th("Saída"), _th("Variante"), _th("Lado"),
        _th("Contr.", "Contratos executados na demo.", True),
        _th("Preço entrada", n=True), _th("Preço saída", n=True),
        _th("Derrapagem", "Em ticks, além do plano: quanto a demo derrapou A MAIS "
            "do que o plano já supõe, em cada ponta (entrada · saída), em ticks "
            "(1 tick = 5 pontos). O preço do papel já inclui a derrapagem do "
            "plano: 0 = a demo derrapou o que o plano previu. Positivo = pior; "
            "negativo = melhor (verde). Bom: perto de 0. Ruim: acima de 2 ticks (âmbar) "
            "com frequência — o backtest está otimista.", True),
        _th("Pontos", "Pontos a favor (+) ou contra (−) por contrato, nos preços "
            "da demo.", True),
        _th("Resultado", "Em R$, antes dos custos (corretagem e emolumentos). "
            "A tabela Esperado × Papel × Demo, na Avaliação, mostra a demo já "
            "sem os custos; por isso os números não batem.", True),
        _th("Situação", "Por onde a operação saiu (stop/alvo na corretora, sinal "
            "do papel) está em Saída. Aqui: o que fugiu do normal — recusada, "
            "perdida, aberta, ou \"seria enviada\" com o Envio desligado — e "
            "as notas da saída."),
    ])
    return html.Table([html.Thead(cab), html.Tbody(corpo)],
                      className="op-tabela ord-tabela")


# ============================================================ diário do dia
def _texto_teste(e: dict) -> tuple[str, str]:
    """A "Ordem de teste" no diário: cada etapa, com preço e tempo do envio,
    e o desfecho. Só textos (str): nada de dicionário como filho."""
    tipo, motivo = e.get("tipo"), str(e.get("motivo") or "")
    if tipo == "teste_ok":
        return motivo or "Teste ok", ""
    etapa = e.get("etapa")
    if tipo == "teste_falhou":
        try:
            n = int(etapa or 0)
        except (TypeError, ValueError):
            n = 0
        return texto_teste_falhou(n, motivo), "ambar"
    if etapa == "encerrar":
        return f"Ordem de teste · encerramento: {motivo}", ""
    try:
        n = int(etapa or 0)
    except (TypeError, ValueError):
        n = 0
    if not n:
        return f"Ordem de teste: {motivo}", ""
    extra = []
    if e.get("preco"):
        extra.append(f"a {_preco(e.get('preco'))}")
    if e.get("stop_px") is not None and e.get("alvo_px") is not None:
        extra.append(f"stop {_preco(e.get('stop_px'))} · alvo {_preco(e.get('alvo_px'))}")
    if e.get("atraso_ms") is not None:
        extra.append(f"{e['atraso_ms']} ms")
    nome = ETAPAS_TESTE.get(n, "")
    return (f"Ordem de teste · etapa {n} ({nome}): {motivo}"
            + (f" · {' · '.join(extra)}" if extra else "")), ""


def _texto_evento(e: dict) -> tuple[str, str] | None:
    """(texto, tom) de um evento do diário; None = interno, não aparece."""
    tipo = e.get("tipo")
    if tipo in _INTERNOS:
        return None
    motivo = e.get("motivo") or ""
    lado = "COMPRA" if (e.get("lado") or 0) > 0 else "VENDA"
    ctr = e.get("contratos")
    ctr_t = "" if ctr is None else f" {_decimal(float(ctr))}"
    sim = f" {e['simbolo']}" if e.get("simbolo") else ""
    if tipo == "comando":
        if motivo in _COMANDOS_INTERNOS:
            return None
        if motivo == "zerar_tudo":
            return "Zerar tudo pedido na tela", "ambar"
        if motivo == ZERAR_DESCARTADO:
            return ("Zerar tudo de outro dia descartado (o Envio já tinha sido "
                    "desligado no clique)"), ""
        if motivo == "encerrar_posicao":
            return f"Encerrar posição pedido na tela (ticket {e.get('ticket')})", "ambar"
        if motivo == "envio":
            return ("Envio de ordens " + ("ligado" if e.get("ligado")
                                          else "desligado") + " na tela"), ""
        if motivo == "ordem_teste":
            return "Ordem de teste pedida na tela", ""
        return f"comando da tela: {motivo}", ""
    if tipo in ("teste", "teste_ok", "teste_falhou"):
        return _texto_teste(e)
    if tipo in ("executada", "parcial"):
        atraso = e.get("atraso_ms")
        em = f" em {num(atraso / 1000, 2)} s" if atraso is not None else ""
        parte = " (em parte)" if tipo == "parcial" else ""
        return (f"{lado}{ctr_t}{sim} executada{parte} a {_preco(e.get('preco'))}{em}",
                "")
    textos = {
        "aceita": ("ordem aceita pela corretora, esperando a execução", ""),
        "recusada": (f"{lado} recusada pela corretora ({motivo}) · tentando de novo"
                     if motivo else f"{lado} recusada pela corretora", "ambar"),
        "perdida": (f"entrada perdida: {motivo}" if motivo else "entrada perdida",
                    "ambar"),
        "nao_entrou": (f"não entrou: {motivo}" if motivo else "não entrou", "ambar"),
        "seria_enviada": (f"seria enviada (Envio desligado): {lado}{ctr_t}{sim}"
                          + (f" · {checagem_ensaio(e)}" if checagem_ensaio(e) else ""),
                          "ambar" if checagem_ensaio(e) else ""),
        "adotada": (f"posição adotada a {_preco(e.get('preco'))} ({motivo})"
                    if motivo else "posição adotada", ""),
        # "saiu no alvo na corretora a 208.845", como no rascunho v4
        "saiu_antes": ((f"saiu no {motivo.replace(' (fora do mercado)', '')} "
                        f"a {_preco(e.get('preco'))} (fora do mercado — a corretora "
                        "executou sem negócio nesse preço)"
                        if e.get("fora_do_mercado")
                        else f"saiu no {motivo} a {_preco(e.get('preco'))}"
                        if motivo.endswith("na corretora")
                        else f"saiu a {_preco(e.get('preco'))}: {motivo}")
                       if motivo else "saiu na corretora", ""),
        "saida_executada": (f"saída executada a {_preco(e.get('preco'))}"
                            + (f" ({motivo})" if motivo else ""), ""),
        "saida_parcial": (f"saída executada em parte a {_preco(e.get('preco'))}", ""),
        "preco_confirmado": (("entrada" if e.get("ponta") == "entrada" else "saída")
                             + f" confirmada na corretora a {_preco(e.get('preco'))}",
                             ""),
        "saida_recusada": (f"saída recusada: {motivo} · tentando de novo"
                           if motivo else "saída recusada · tentando de novo",
                           "ambar"),
        "protecao": (f"stop e alvo na corretora: {_preco(e.get('stop_px'))} · "
                     f"{_preco(e.get('alvo_px'))}", ""),
        "protecao_recusada": (f"stop e alvo recusados: {motivo}" if motivo
                              else "stop e alvo recusados", "ambar"),
        "cancelada": ("ordem pendente cancelada", ""),
        "incerta": (f"sem resposta da corretora ({motivo}) · conferindo antes de "
                    "reenviar" if motivo else "sem resposta da corretora · "
                    "conferindo antes de reenviar", "ambar"),
        "chamado": (f"{motivo} → chamado aberto" if motivo else "chamado aberto",
                    "rosa"),
        "chamado_fechado": ("chamado resolvido", ""),
        "conta_travada": (f"conta travada: perda do dia {_reais(e.get('perda'))} de "
                          f"{_reais(e.get('limite'))} — posições encerradas, nada "
                          "entra até amanhã", "rosa"),
        "rolagem": (f"rolagem: {motivo}" if motivo else "rolagem de contrato", ""),
    }
    return textos.get(tipo, (tipo or "evento", ""))


def diario_do_dia(eventos: list[dict], nomes: dict | None, *,
                  so_problemas: bool = False) -> html.Div:
    """Hora, variante e texto de cada evento, do mais novo para o mais
    antigo. Passos internos do motor ficam de fora; "Só problemas" deixa
    recusas, perdas, chamados e a trava."""
    linhas = []
    for e in reversed(eventos or []):
        if so_problemas and e.get("tipo") not in PROBLEMAS:
            continue
        t = _texto_evento(e)
        if t is None:
            continue
        texto, tom = t
        # a coluna Conta: o chip real/demo vai antes do nome da variante
        linhas.append(html.Div([
            html.Span(_hora(e.get("quando"), segundos=True), className="ord-ev-h"),
            html.Span([_chip_conta(e.get("origem") or "demo"),
                       _nome_tab(_nome(nomes, e.get("ligacao_id")), "op-nome-tab")],
                      className="ord-ev-quem op-ev-conta"),
            html.Span(texto, className="ord-ev-t" + (f" {tom}" if tom else "")),
        ], className="ord-ev" + (" ord-ev-problema" if e.get("tipo") in PROBLEMAS
                                 else "")))
    if not linhas:
        # dentro da tabela: texto apagado no lugar das linhas, sem caixa
        if so_problemas:
            return html.Div(html.P(["nenhum problema hoje",
                                    dica("Nenhuma recusa, perda, chamado ou "
                                         "trava hoje. \"Tudo\" mostra o resto "
                                         "do dia.")], className="op-vazio-txt"))
        return html.Div(html.P(["nada no diário hoje",
                                dica("Sem variante na fase demo a automação não "
                                     "manda ordens, e o diário fica vazio.")],
                               className="op-vazio-txt"))
    return html.Div(linhas)
