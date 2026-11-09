"""Operação: tabela de operações e marcadores no gráfico."""
from __future__ import annotations

from datetime import datetime

from dash import html

from ...data import to_epoch
from .. import ordens_panel as OR
from .. import pregao_panel as PP
from ..cartao import dica, inteiro, nome_curto

from .base import CINZA, _ROTULOS_MAX, _SAIU_POR, _TITULO_MAX, _hora, _preco, _rs, _sinal, amostra, cor, forma


# -------------------------------------------------------------- operações
def _cel(conteudo, classe="", title=None):
    kw = {"title": title} if title else {}
    return html.Td(conteudo, className=classe, **kw)


# situação de uma "aberta" do banco que não é posição de agora (ver
# `core.papel_leitura.operacoes_do_dia`) -> texto da coluna Saída
_ABERTA_PARADA = {"nao_conferido": "não conferida",
                  "nao_atualizada": "não atualizada",
                  "congelada": "congelada"}


def linha_operacao(o: dict) -> html.Tr:
    sit = o.get("situacao")
    compra = int(o["side"]) == 1
    pts = int(o.get("points") or 0)
    # a coluna Saída diz a hora e por onde saiu ("11:20 alvo", rascunho
    # v4); na aberta, o stop e o alvo de agora
    if sit == "aberta":
        saida = [html.Span("aberta", className="acc"),
                 html.Span(f" · stop {_preco(o.get('stop_px'))} · alvo "
                           f"{_preco(o.get('alvo_px'))}", className="acc")]
        marcado = int(o["entry_px"]) + int(o["side"]) * pts
        preco_saida = _cel(_preco(marcado), "n acc",
                           "preço marcado no último candle calculado")
    elif sit in _ABERTA_PARADA:
        # aberta no banco, mas não é posição de agora: o stop/alvo gravado
        # é de quando o motor parou, mostrá-lo seria dizer que ainda vale
        rotulo = _ABERTA_PARADA[sit]
        if sit == "congelada" and o.get("nota"):
            rotulo = f"{rotulo} — {o['nota']}"
        saida = html.Span(rotulo, className="aviso",
                          title=o.get("nota") or rotulo)
        preco_saida = _cel("—", "n")
    else:
        saiu = _SAIU_POR.get(o.get("reason"))
        saida = _hora(o.get("exit_ts")) + (f" {saiu}" if saiu else "")
        preco_saida = _cel(_preco(o.get("exit_px")), "n")
    nome = o.get("variante") or "—"
    var = [html.Div([amostra(o.get("cor"), o.get("conta", True)),
                     html.Span(nome_curto(nome), className="op-nome-tab",
                               title=nome)],
                    className="op-var-cel")]
    if not o.get("conta", True):
        var.append(html.Span("fora do período ligado", className="op-fora-txt"))
    resultado = [_rs(o.get("liquido"))]
    if o.get("provisorio"):
        resultado.append(html.Span(" provisório", className="op-prov"))
    classe = "op-linha"
    if sit == "aberta":
        classe += " op-aberta"
    if sit in _ABERTA_PARADA:
        classe += " op-preso"
    if not o.get("conta", True):
        classe += " op-fora"
    return html.Tr([
        _cel(_hora(o.get("entry_ts"))),
        _cel(saida),
        _cel(var, "t"),
        _cel(html.Span("COMPRA" if compra else "VENDA",
                       className="op-lado " + ("op-c" if compra else "op-v"))),
        _cel(f"{o.get('contratos')} / {_ctr_demo(o.get('real'))} / "
             f"{_ctr_demo(o.get('demo'))}", "n"),
        _cel(_preco(o.get("entry_px")), "n"),
        preco_saida,
        _cel(("+" if pts > 0 else "-" if pts < 0 else "") + inteiro(abs(pts)),
             "n " + (_sinal(pts) or "")),
        _cel(resultado, "n " + (_sinal(o.get("liquido")) or "")),
        _papel_x_demo(o.get("demo")),
        _papel_x_demo(o.get("real")),
    ], className=classe)


def _ctr_demo(d) -> str:
    if not d or d.get("contratos") is None:
        return "—"
    return OR._decimal(d["contratos"])


def _papel_x_demo(d):
    """Derrapagem além do plano da mesma operação na demo, por ponta
    (entrada · saída), em ticks; sem a demo nela, "—"."""
    if not d:
        return _cel("—", "n mut")
    e, s = d.get("derrapagem_entrada"), d.get("derrapagem_saida")
    if e is None and s is None:
        return _cel("não executada" if d.get("preco_entrada") is None else "—",
                    "n mut")

    f = OR._decimal
    pior = max(x for x in (e, s) if x is not None)
    return _cel(f"{f(e)} · {f(s)} ticks", "n" + (" aviso" if pior > 2 else ""))


def tabela_operacoes(ops: list[dict]):
    if not ops:
        return html.P(["nenhuma operação no papel neste pregão",
                       dica("O papel ainda não deu sinal hoje (ou o filtro "
                            "escolheu uma variante sem operação).")],
                      className="op-vazio-txt")

    def th(texto, explica=None, n=False):
        return html.Th([texto] + ([dica(explica)] if explica else []),
                       className="n" if n else "")
    cab = html.Tr([
        th("Entrada"), th("Saída"), th("Variante"), th("Lado"),
        th("Contr. papel / real / demo", "Contratos da operação em cada "
           "lugar: papel, conta real e conta demo. O papel usa os do plano. "
           "Bom: os três iguais ao plano. Ruim: real ou demo com mais "
           "contratos que o plano (risco maior que o medido).", True),
        th("Preço entrada", n=True), th("Preço saída", n=True),
        th("Pontos", "Pontos a favor (+) ou contra (−) por contrato, já com a "
           "derrapagem do plano. Bom: ganhos maiores que as perdas na média "
           "do dia. Ruim: perdas no tamanho do stop seguidas.", True),
        th("Resultado", "Resultado do papel em reais, com os contratos e os "
           "custos do plano. Na aberta é provisório: o preço do último "
           "candle. Bom: a média por operação do plano ou mais.", True),
        th("Papel × demo", "Derrapagem da demo além da que o plano supõe, na "
           "mesma operação, por ponta (entrada · saída), em ticks. Bom: perto "
           "de 0. Ruim: acima de 2 ticks (âmbar). \"não executada\" = a demo "
           "não entrou nesta operação.", True),
        th("Papel × real", "Derrapagem da conta real além da que o plano supõe, "
           "na mesma operação, por ponta (entrada · saída), em ticks. Bom: perto "
           "de 0. Ruim: acima de 2 ticks (âmbar). \"não executada\" = a real "
           "não entrou nesta operação.", True),
    ])
    # sem a caixa que rola: ela fica fixa no layout (`av-op-operacoes`),
    # senão cada releitura a recriava e a rolagem voltava ao topo
    return html.Table([html.Thead(cab),
                       html.Tbody([linha_operacao(o) for o in ops])],
                      className="op-tabela")


# ---------------------------------------------------------------- gráfico
def marcadores_tela(dados: dict, ocultas, tf: str) -> tuple[list, list]:
    """(markers, priceLines) do gráfico, a partir de `papel_leitura.marcadores`.

    Pinta pela cor da variante (cinza quando a operação não conta), troca o
    círculo da saída por quadrado quando a cor repete e põe o marcador no
    início do candle de 5/15 min — o gráfico só desenha marcador em cima de
    um candle que existe. Leva só as chaves que o gráfico conhece."""
    ocultas = set(ocultas or [])
    passo = PP.MINUTOS_TF.get(tf, 1) * 60
    mk = []
    for m in dados.get("marcadores") or []:
        if m.get("ligacao_id") in ocultas:
            continue
        forma_m = m["shape"]
        if forma_m == "circle":
            forma_m = forma(m.get("cor"))
        mk.append({"time": int(m["time"]) - int(m["time"]) % passo,
                   "position": m["position"], "shape": forma_m,
                   "color": cor(m.get("cor")) if m.get("conta", True) else CINZA,
                   "text": m.get("text", "")})
    mk.sort(key=lambda x: x["time"])
    visiveis = [l for l in dados.get("linhas_abertas") or []
                if l.get("ligacao_id") not in ocultas]
    # Com mais de 2 posições abertas os rótulos no eixo empilhavam
    # ("stop stop stop… alvo") e cobriam o preço: ficam só as linhas, e a
    # legenda esconde as outras variantes para ler uma de cada vez.
    rotulos = len({l.get("ligacao_id") for l in visiveis}) <= _ROTULOS_MAX
    linhas = []
    for l in visiveis:
        # só "stop"/"alvo": a cor já diz de quem é
        titulo = (l.get("tipo") or l.get("title") or "")[:_TITULO_MAX]
        linhas.append({"price": int(l["price"]), "lineWidth": 1, "lineStyle": 2,
                       "color": cor(l.get("cor")) if l.get("conta", True) else CINZA,
                       "axisLabelVisible": rotulos,
                       "title": titulo if rotulos else ""})
    return mk, linhas


def tick_operacao(estado: dict | None, tf: str, base: dict | None,
                  agora: datetime) -> dict | None:
    """O candle em formação para o `tick`, sem abrir o banco.

    O Pregão lê do banco os M1 já fechados do balde de 5/15 min; aqui o
    pulso não pode ler o banco, e nem precisa: o último candle que a série
    desenhou (`base`, guardado quando ela foi montada) já é esse balde. Se
    o minuto em formação abriu um balde novo, o candle é só ele."""
    if not PP.captura_ativa(estado, agora):
        return None
    f = (estado or {}).get("em_formacao")
    ts = PP._data((f or {}).get("ts"))
    if ts is None:
        return None
    t0 = to_epoch(PP.inicio_balde(ts, tf))
    if tf != "M1" and base and base.get("time") == t0:
        bar = {"time": t0, "open": base["open"],
               "high": max(base["high"], f["high"]),
               "low": min(base["low"], f["low"]), "close": f["close"]}
    else:
        bar = {"time": t0, "open": f["open"], "high": f["high"],
               "low": f["low"], "close": f["close"]}
    return {"id": "preco", "bar": bar}
