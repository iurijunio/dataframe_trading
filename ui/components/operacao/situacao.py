"""Operação: faixa de situação, alertas, papel × esperado e comparativo."""
from __future__ import annotations

from datetime import datetime, time

from dash import html

from ... import theme as T
from ...data import to_epoch
from .. import ordens_panel as OR
from .. import pregao_panel as PP
from ..cartao import dica, inteiro, nome_curto, num, pct

from .base import _FAIXAS, _etiqueta, _rotulo, _rs
from .variantes import legenda


# --------------------------------------------------------------- situação
def _sep(texto="·"):
    return html.Span(texto, className="op-sep")


def _seg(filhos, explica=None, classe="", title=None):
    """Um trecho da linha do portfólio (rascunho v4: "WINZ26 · demo Clear ·
    R$ 10.000 · 2/2 operando"), sem rótulo de campo; o (?) logo depois."""
    kw = {"title": title} if title else {}
    return html.Span(list(filhos) + ([dica(explica)] if explica else []),
                     className=("op-seg " + classe).strip(), **kw)


def faixa_situacao(estado: dict | None, agora: datetime) -> list:
    """A captura (mesma `situacao` do Pregão) e o papel: quando foi
    calculado, se ficou para trás, se falhou.

    Etiquetas na linha do cabeçalho, com o que fazer no (?): problema
    (rosa/âmbar) fica sempre à vista, só a frase de ação vai para o (?)."""
    sit = PP.situacao(estado, agora)
    papel = (estado or {}).get("papel") or {}
    em = PP._data(papel.get("calculado_em"))
    erros = papel.get("erros") or {}
    explica = ("Hora em que a captura calculou o papel pela última vez. Ela "
               "recalcula a cada candle novo de 1 minuto; a tela relê as "
               "operações só quando esse horário muda. Bom: no pregão, menos "
               "de 2 minutos atrás.")
    if em is None:
        valor = "—"
        explica += " Ainda não calculado desde que a captura abriu."
    elif em.date() == agora.date():
        valor = f"{em:%H:%M:%S}"
    else:
        valor = f"{em:%d/%m %H:%M}"
    # o "papel HH:MM:SS" fecha a linha do portfólio; as etiquetas de
    # problema vêm depois dele
    out = [_sep(), _seg([f"papel {valor}"], explica, "op-seg-papel")]
    if sit["tom"] in ("rosa", "ambar"):
        texto = sit["texto"]
        if not sit["ativa"] and em:
            texto += f" — papel congelado em {em:%H:%M}"
        out.append(_etiqueta(texto, sit["tom"], sit["acao"]))
    elif not sit["pregao"]:
        out.append(_etiqueta("mercado fechado", "cinza",
                             "Fora do horário do pregão: a tela mostra o "
                             "último pregão calculado."))
    if erros.get("calculo"):
        out.append(_etiqueta("papel de hoje não foi calculado", "rosa",
                             "Falhou na última volta da captura; ela tenta de "
                             f"novo no próximo candle. Erro: {erros['calculo']}"))
    if erros.get("conferencia"):
        out.append(_etiqueta("conferência do papel falhou", "ambar",
                             "A captura tenta de novo na próxima janela de "
                             f"conferência. Erro: {erros['conferencia']}"))
    if papel.get("pendente"):
        out.append(_etiqueta("papel atrasado: banco ocupado", "ambar",
                             "Uma mineração está gravando no banco; o papel é "
                             "refeito na próxima volta da captura."))
    return out


_TIPO_ALERTA = {"mesmo_assim": ("gravado mesmo assim", "ambar"),
                "pulado": ("pregão pulado", "rosa"),
                "interrompido": ("interrompido", "rosa"),
                "nao_conferido": ("não conferido", "ambar"),
                "falha": ("falha no cálculo", "rosa"),
                "divergencia": ("candles mudaram", "ambar")}


def lista_alertas(alertas: list[dict], nomes: dict | None = None) -> list:
    """Os alertas do papel como linhas em destaque (âmbar ou rosa) no topo
    da tabela do Diário: Hora | Variante | O que aconteceu, as mesmas
    colunas das linhas do diário logo abaixo. Sem alerta, nada."""
    nomes = nomes or {}
    out = []
    for a in alertas or []:
        rot, tom = _TIPO_ALERTA.get(a.get("tipo"), ("atenção", "ambar"))
        nome = nomes.get(a.get("ligacao_id"))
        texto = a.get("texto") or ""
        # o core escreve "nome: ..." — o nome já está na coluna Variante
        if nome and texto.startswith(f"{nome}: "):
            texto = texto[len(nome) + 2:]
        quando = a.get("quando")
        hora = f"{quando:%H:%M:%S}" if isinstance(quando, datetime) else "—"
        quem = nome_curto(nome) if nome else "—"
        out.append(html.Div([
            html.Span(hora, className="ord-ev-h"),
            html.Span(quem, className="ord-ev-quem", title=nome or ""),
            html.Span([_etiqueta(rot, tom), " ", texto], className="ord-ev-t"),
        ], className=f"ord-ev op-alerta op-alerta-{tom}"))
    return out


# ---------------------------------------------------------- papel × esperado
def _epoch_dia(d) -> int:
    return to_epoch(datetime.combine(d, time()))


def _linha(ident, tempos, valores, cor_, largura=1, estilo=0, ultimo=False):
    pts = [{"time": t, "value": round(float(v), 2)}
           for t, v in zip(tempos, valores) if v is not None]
    return {"id": ident, "type": "line", "data": pts,
            "options": {"color": cor_, "lineWidth": largura, "lineStyle": estilo,
                        "priceLineVisible": False, "lastValueVisible": ultimo,
                        "pointMarkersVisible": len(pts) < 3,
                        "priceFormat": {"type": "price", "precision": 0,
                                        "minMove": 1}},
            "pane": 0}


def curva_series(c: dict) -> list[dict]:
    """Papel acumulado com a faixa (p10/p90 pontilhados) e a mediana
    tracejada. Linha em vez de área entre p10 e p90: o gráfico não pinta
    entre duas séries, e uma área com valor negativo pintaria até o zero."""
    tempos = [_epoch_dia(d) for d in c.get("dias") or []]
    if not tempos:
        return []
    faixa = "rgba(34,228,255,.55)"
    out = []
    if c.get("p90") and c.get("p10"):
        out.append(_linha("p90", tempos, c["p90"], faixa, 1, 1))
        out.append(_linha("p10", tempos, c["p10"], faixa, 1, 1))
    if c.get("mediana"):
        out.append(_linha("mediana", tempos, c["mediana"], T.MUTED, 1, 2))
    papel = _linha("papel", tempos, c.get("papel") or [], T.POS, 2, 0, True)
    papel["priceLines"] = [{"price": 0, "color": T.LINE, "lineWidth": 1,
                            "lineStyle": 0, "axisLabelVisible": False,
                            "title": ""}]
    out.append(papel)
    return out


def curva_nota(c: dict) -> str:
    n = len(c.get("dias") or [])
    if not n:
        return "ainda nenhum pregão de papel com o plano em vigor"
    partes = [f"{n} {'pregão' if n == 1 else 'pregões'} desde o plano em vigor"]
    if c.get("faixa_atual"):
        partes.append(f"hoje {_FAIXAS[c['faixa_atual']]}")
    elif c.get("diferenca_mediana") is not None:
        d = c["diferenca_mediana"]
        partes.append(f"{_rs(d)} {'acima' if d >= 0 else 'abaixo'} da mediana")
    if c.get("aviso"):
        partes.append(c["aviso"])
    return " · ".join(partes)


# -------------------------------------------------------------- comparativo
def _fator(v):
    if v is None:
        return "—"
    if v == float("inf"):
        return "sem perdas"
    return num(v, 2)


def _atraso(ms) -> str:
    return f"{inteiro(int(round(ms)))} ms" if ms < 1000 else f"{num(ms / 1000, 1)} s"


# linhas de execução: só existem na conta (a demo, por ora); papel e
# esperado não mandam ordem
_SO_CONTA = ("mesmo_minuto", "derrapagem_extra", "atraso_ms", "rejeitadas")


def _tom_execucao(chave: str, m: dict | None, esp: dict | None) -> str | None:
    """bom | atencao | ruim da linha, pelas faixas da spec §5.2 (no (?) de
    cada linha): derrapagem ≤1 tick bom, ≤2 atenção; mesmo minuto ≥95% bom,
    ≥80% atenção; atraso ≤300 ms bom, ≤1000 atenção; rejeitadas 0 bom, ≤2
    atenção; fator de lucro e acerto ≥ o esperado bom, ≥80% dele atenção."""
    v = (m or {}).get(chave)
    if v is None:
        return None
    if chave == "mesmo_minuto":
        return "bom" if v >= .95 else "atencao" if v >= .80 else "ruim"
    if chave == "derrapagem_extra":
        return "bom" if v <= 1 else "atencao" if v <= 2 else "ruim"
    if chave == "atraso_ms":
        return "bom" if v <= 300 else "atencao" if v <= 1000 else "ruim"
    if chave == "rejeitadas":
        return "bom" if v == 0 else "atencao" if v <= 2 else "ruim"
    if chave in ("fator_lucro", "acerto"):
        ref = (esp or {}).get(chave)
        if ref is None:
            return None
        if v >= ref:
            return "bom"
        return "atencao" if v >= 0.8 * ref else "ruim"
    return None


_TOM_ETIQUETA = {"bom": ("bom", "verde"), "atencao": ("atenção", "ambar"),
                 "ruim": ("ruim", "rosa")}


def tabela_comparativo(c: dict):
    """Esperado (WFA) × Papel × Demo × Real, por contrato (spec §6.7 e §5.2).
    Nas colunas de conta, cada linha de execução leva a etiqueta bom/atenção/
    ruim contra a faixa da spec (o (?) da linha diz a faixa). Cores das
    colunas: cinza esperado, violeta papel, ciano demo, laranja real."""
    cols = [c.get("esperado_wfa"), c.get("papel"), c.get("demo"), c.get("real")]
    contas = (False, False, True, True)
    esperado = cols[0]

    def val(m, chave, fmt, conta):
        if m is None or chave in _SO_CONTA and not conta:
            return "—"
        # a execução tem número antes de a primeira operação fechar
        if not m.get("n") and chave not in ("n", *_SO_CONTA):
            return "—"
        v = m.get(chave)
        return "—" if v is None else fmt(v)

    linhas = [
        ("Tamanho", None),
        ("Contratos por operação", "contratos_por_operacao",
         lambda v: num(v, 1),
         "Média de contratos por operação. O papel usa os do plano; o "
         "walk-forward, os do backtest — por isso o resto compara por "
         "contrato. Bom: papel e demo iguais aos contratos do plano. Ruim: "
         "demo/real acima do plano (risco maior que o medido)."),
        ("Resultado por contrato", None),
        ("Operações", "n", lambda v: inteiro(int(v)),
         "Quantas operações fechadas entram na conta. Poucas (menos de 30) "
         "ainda dizem pouco."),
        ("Resultado médio por contrato", "resultado_por_contrato",
         lambda v: _rs(v, 2),
         "Resultado médio de uma operação, por contrato, já sem os custos "
         "do plano (a demo também). A tabela de operações da demo e o "
         "Resultado hoje na demo mostram antes dos custos; por isso os números não batem. Bom: "
         "papel perto do esperado. Ruim: papel bem abaixo por muitos pregões."),
        ("Pontos por operação", "pontos_por_operacao",
         lambda v: ("+" if v > 0 else "") + num(v, 0),
         "Pontos médios por operação. Bom: papel perto do esperado ou "
         "acima. Ruim: negativo, ou menos da metade do esperado depois de "
         "30 operações."),
        ("Fator de lucro", "fator_lucro", _fator,
         "Ganhos divididos pelas perdas. Bom: igual ou acima do esperado. "
         "Atenção: entre 80% do esperado e o esperado. Ruim: abaixo de 80% "
         "do esperado (ou abaixo de 1: perde mais do que ganha)."),
        ("Acerto", "acerto", lambda v: pct(v * 100, 0),
         "Operações ganhadoras sobre o total. Bom: igual ou acima do "
         "esperado. Atenção: entre 80% do esperado e o esperado. Ruim: abaixo "
         "de 80% do esperado depois de 30 operações. O valor sozinho não diz "
         "se a estratégia é boa."),
        ("Resultado total", "total", lambda v: _rs(v, 2),
         "Soma com o tamanho real de cada operação. Só fechadas: pode ser "
         "menor que o Acumulado lá em cima, que inclui a aberta."),
        ("Execução", None),
        ("Sinal no mesmo minuto", "mesmo_minuto",
         lambda v: pct(v * 100, 0),
         "Entradas executadas no mesmo minuto do sinal do papel, sobre as "
         "executadas desde o plano em vigor. Bom: 95% ou mais. Atenção: de "
         "80% a 95%. Ruim: abaixo de 80%."),
        ("Derrapagem média", "derrapagem_extra",
         lambda v: ("+" if round(v, 1) > 0 else "") + OR._decimal(v) + " tick",
         "Ticks por ponta além do preço do papel (que já desconta a "
         "derrapagem do plano). Negativo = executou melhor que o papel. Bom: "
         "até 1 tick. Atenção: de 1 a 2 ticks. Ruim: acima de 2 ticks — o "
         "backtest está otimista."),
        ("Atraso médio da ordem", "atraso_ms", _atraso,
         "Tempo entre mandar a entrada e a corretora executar. Bom: até 300 ms. "
         "Atenção: até 1 s. Ruim: acima de 1 s."),
        ("Ordens rejeitadas", "rejeitadas", lambda v: inteiro(int(v)),
         "Ordens que a corretora recusou (entrada, saída, proteção). Conta "
         "cada recusa: uma operação pode somar várias. Recusadas, em Papel × "
         "demo, conta operações e por isso pode dar menos. Bom: zero. "
         "Atenção: até 2. Ruim: mais de 2."),
    ]
    corpo = []
    for linha in linhas:
        if linha[1] is None and len(linha) == 2:
            corpo.append(html.Tr(html.Td(linha[0], colSpan=5),
                                 className="op-cmp-grupo"))
            continue
        rot, chave, fmt, explica = linha
        celulas = [html.Td(_rotulo(rot, explica), className="k")]
        for m, conta in zip(cols, contas):
            texto = val(m, chave, fmt, conta)
            filhos = [texto]
            tom = _tom_execucao(chave, m, esperado) if conta and texto != "—" else None
            if tom:
                rot_tom, cor_tom = _TOM_ETIQUETA[tom]
                filhos.append(_etiqueta(rot_tom, cor_tom))
            celulas.append(html.Td(filhos if tom else texto,
                                   className="n" + ("" if texto != "—" else " mut")))
        corpo.append(html.Tr(celulas))
    cab = html.Tr([html.Th(""), html.Th("Esperado (WFA)", className="n c-esp"),
                   html.Th("Papel", className="n c-pap"),
                   html.Th("Demo", className="n c-dem"),
                   html.Th("Real", className="n c-rea")])
    legenda = html.Div([
        _etiqueta("bom", "verde"), _etiqueta("atenção", "ambar"),
        _etiqueta("ruim", "rosa"),
        html.Span("— faixas no (?) de cada linha; comparação contra o Esperado",
                  className="mut"),
    ], className="op-cmp-leg")
    return html.Div([html.Table([html.Thead(cab), html.Tbody(corpo)],
                                className="op-tabela op-cmp"), legenda],
                    className="op-cmp-wrap")
