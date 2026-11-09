"""Ordens: posições abertas e os três números do dia."""
from __future__ import annotations

from datetime import datetime

from dash import html

from ..cartao import dica, inteiro, num

from .base import ATENCAO_PCT, PERIGO_PCT, TRAVA_PCT, _etiqueta, _hora, _idade_s, _int_sinal, _lado, _ligacoes, _mmss, _nome, _nome_tab, _preco, _reais, _rs, _sinal
from .saude import real_parada


# ========================================================= posições abertas
def _situacao_posicao(l: dict, p: dict, agora) -> tuple[str, str]:
    """(texto, tom): confere | saída pendente — tentando (Nª) · m:ss |
    indisponível | diferente."""
    desde = p.get("saida_desde")
    if desde:
        idade = _idade_s(desde, agora) or 0
        n = int(p.get("tentativas") or 0)
        return (f"saída pendente — tentando ({max(n, 1)}ª) · {_mmss(idade)}",
                "ambar")
    if l.get("desejado") == "indisponivel":
        return "indisponível", "ambar"
    if (l.get("desejado") == "posicao" and int(l.get("lado") or 0) == int(p.get("lado") or 0)
            and float(p.get("volume") or 0) == float(l.get("contratos") or 0)):
        return "confere", "verde"
    return "diferente", "rosa"


def _posicoes(ordens, ligacoes) -> list[tuple[int, dict, dict]]:
    ligs = _ligacoes(ordens)
    quero = set(ligacoes) if ligacoes is not None else set(ligs)
    return [(lig, l, p) for lig, l in sorted(ligs.items()) if lig in quero
            for p in l.get("posicoes") or []]


def _th(texto, explica=None, n=False):
    return html.Th([texto] + ([dica(explica)] if explica else []),
                   className="n" if n else "")


def _chip_conta(origem: str) -> html.Span:
    """"real" (laranja) ou "demo" (ciano): a conta de onde é a posição."""
    return html.Span(origem, className=f"ord-conta ord-conta-{origem}")


def posicoes_abertas(ordens: dict | None, nomes: dict, tick: int, *,
                     ponto: float = 0.2, agora: datetime | None = None,
                     real: dict | None = None):
    """O que está na corretora agora, de ESTE portfólio (`nomes` = as
    ligações dele), conferido com o que o papel quer. A coluna Conta diz
    de qual conta é cada posição: as da demo (`ordens`) e, se `real` vier
    (a conta real está viva), as da real, na mesma tabela."""
    cab = html.Tr([
        _th("Conta"), _th("Variante"), _th("Lado"),
        _th("Contr.", "Contratos na corretora; entre parênteses o que o papel "
            "quer, quando difere. Bom: iguais. Ruim: diferentes — vira "
            "\"diferente\" e a automação corrige.", True),
        _th("Entrada", n=True),
        _th("Stop", "Stop gravado NA corretora (✓) e a distância do preço de "
            "agora até ele, em ticks (1 tick = 5 pontos). Bom: stop e alvo "
            "presentes, stop longe. Atenção: perto de zero. Ruim: sem stop — "
            "a automação encerra a posição em 2 s.", True),
        _th("Alvo", "Alvo gravado na corretora e a distância do preço de "
            "agora até ele, em ticks.", True),
        _th("Resultado aberto", "Resultado da posição agora, em ticks e em R$ "
            "(antes dos custos). Bom: positivo.", True),
        _th("Situação", "confere = a corretora tem o que o papel quer; saída "
            "pendente = a automação está tentando sair (passa de 2 min, vira "
            "chamado); indisponível = sem o papel agora, a automação só protege; "
            "diferente = a corretora tem outra coisa."),
    ])
    pos = [("demo", *x) for x in _posicoes(ordens, list(nomes))]
    if real is not None:
        pos += [("real", *x) for x in _posicoes(real, list(nomes))]
    if not pos:
        o = ordens or {}
        if o.get("n_demo") == 0:
            explica = ("Nenhuma variante na fase demo: tudo segue no papel e "
                       "nada vai à corretora.")
        elif not o:
            explica = ("As ordens ainda não têm estado: a captura não publicou "
                       "a primeira volta.")
        else:
            explica = "Nenhuma posição da automação aberta na corretora agora."
        # a tabela fica, com o cabeçalho e uma linha só (rascunho v4)
        vazia = html.Tr(html.Td(["nenhuma na corretora", dica(explica)],
                                colSpan=9, className="op-td-vazio"))
        return html.Table([html.Thead(cab), html.Tbody(vazia)],
                          className="op-tabela ord-tabela")
    tick = int(tick or 1)
    linhas = []
    for origem, lig, l, p in pos:
        lado = int(p.get("lado") or 0)
        vol = float(p.get("volume") or 0)
        preco = float(p.get("preco") or 0)
        res = p.get("resultado")
        # o preço de agora sai do resultado aberto da própria corretora
        # (o WIN$N do gráfico é a série contínua, não o contrato da posição)
        atual = (preco + lado * float(res) / (vol * ponto)
                 if res is not None and vol and ponto else None)
        sl, tp = float(p.get("sl") or 0), float(p.get("tp") or 0)

        def ate(alvo):
            if atual is None or not alvo:
                return ""
            return f" · {inteiro(int(round(abs(alvo - atual) / tick)))} ticks"
        if sl:
            cel_stop = html.Td([html.Span("✓ ", className="ord-prot"), _preco(sl),
                                html.Span(ate(sl), className="mut")], className="n")
        else:
            cel_stop = html.Td(html.Span("sem stop", className="neg"), className="n")
        if tp:
            cel_alvo = html.Td([_preco(tp), html.Span(ate(tp), className="mut")],
                               className="n")
        else:
            cel_alvo = html.Td("sem alvo", className="n mut")
        esperado = l.get("contratos") if l.get("desejado") == "posicao" else 0
        ctr = [inteiro(int(round(vol)))]
        if esperado is not None and float(esperado) != vol:
            ctr.append(html.Span(f" (esperado {inteiro(int(round(float(esperado))))})",
                                 className="mut"))
        ticks_abertos = (None if atual is None
                         else round((atual - preco) * lado / tick))
        sit, tom = _situacao_posicao(l, p, agora)
        linhas.append(html.Tr([
            html.Td(_chip_conta(origem), className="t"),
            html.Td(_nome_tab(_nome(nomes, lig)), className="t"),
            html.Td(_lado(lado)),
            html.Td(ctr, className="n" + (" neg" if len(ctr) > 1 else "")),
            html.Td(_preco(preco), className="n"),
            cel_stop,
            cel_alvo,
            html.Td(f"{_int_sinal(ticks_abertos)} ticks · {_rs(res)}",
                    className="n " + _sinal(res)),
            html.Td(_etiqueta(sit, tom) if tom != "ambar"
                    else html.Span(sit, className="ord-pend")),
        ]))
    return html.Table([html.Thead(cab), html.Tbody(linhas)],
                      className="op-tabela ord-tabela")


# ============================================================ três números
def _kpi(rotulo, explica, valor, nota=None, sinal="", extra=None, title=None):
    filhos = [html.Span([rotulo, dica(explica)], className="op-kpi-r"),
              html.Span(valor, className="op-kpi-v" + (f" {sinal}" if sinal else ""))]
    if extra is not None:
        filhos.append(extra)
    if nota is not None:
        filhos.append(html.Span(nota, className="op-kpi-n", title=title or ""))
    return html.Div(filhos, className="op-kpi")


def tom_da_perda(pct: float) -> str:
    """Cinza abaixo de 60% do limite, âmbar de 60 a 85%, rosa de 85% em
    diante (a trava é a 90%)."""
    if pct >= PERIGO_PCT:
        return "rosa"
    if pct >= ATENCAO_PCT:
        return "ambar"
    return "cinza"


def _parte(v: float) -> str:
    """Uma parte da perda do dia: perda "R$ 100", ganho "ganho R$ 30" (na
    quebra um ganho vem negativo; sem o rótulo pareceria perda)."""
    if v < 0 and round(v) != 0:
        return f"ganho {_reais(-v)}"
    return _reais(v)


def _quebra(perda: dict, portfolio_id) -> tuple[float, float, float]:
    """(este portfólio, outros portfólios, fora da automação), com sinal (um
    ganho entra negativo): a soma é o que a corretora mostra."""
    por = perda.get("por_portfolio") or {}
    este = 0.0
    for k, v in por.items():
        if str(k) == str(portfolio_id):
            este = float(v or 0)
    automacao = float(perda.get("este") or 0) + float(perda.get("outros") or 0)
    return este, automacao - este, float(perda.get("fora") or 0)


def _total(v) -> str:
    """O total desde o plano em vigor, com centavos: "+R$ 147,00"."""
    if v is None:
        return "—"
    corpo = num(abs(float(v)), 2)
    if round(float(v), 2) == 0:
        return f"R$ {corpo}"
    return f"{'+' if v > 0 else '-'}R$ {corpo}"


def _celula_conta(origem: str, rotulo_extra: str, valor: str, sinal: str,
                  explica: str, nota: list, ordem: int) -> html.Div:
    """Uma célula da tira de números de uma conta: a etiqueta REAL/DEMO, o
    valor grande e a linha de baixo (`nota`, já com os trechos coloridos)."""
    rot = html.Span([html.Span(origem.upper(), className=f"op-acc op-acc-{origem}"),
                     f" {rotulo_extra}", dica(explica)], className="op-kpi-r")
    return html.Div([rot,
                     html.Span(valor, className="op-kpi-v" + (f" {sinal}" if sinal else "")),
                     html.Span(nota, className="op-kpi-n")],
                    className="op-kpi op-kpi-conta", style={"order": ordem})


def _cel_hoje(origem, resultado, total, ordem, explica, sem=None) -> html.Div:
    """REAL hoje / DEMO hoje: o resultado do dia da conta (fechadas mais a
    aberta) e, embaixo, o total desde o plano em vigor."""
    if sem is not None:
        valor, nota = "—", [sem]
        sinal = ""
    else:
        valor = _rs(resultado)
        sinal = _sinal(resultado)
        nota = ["total ", html.B(_total(total), className=_sinal(total))]
    return _celula_conta(origem, "hoje", valor, sinal, explica, nota, ordem)


def perda_do_dia(o: dict | None, portfolio_id=None, *, origem: str = "demo",
                 ordem: int = 5, extra: str | None = None,
                 parada: bool = False) -> html.Div:
    """Perda do dia DA CONTA × o limite (D2), a barra até a trava. `o` é o
    bloco `ordens` da conta (demo: o estado.json; real: estado_real.json).
    `extra` vai para o (?) (ex.: o pior momento do dia)."""
    o = o or {}
    perda = o.get("perda") or {}
    limite = o.get("limite")
    explica_perda = (
        "Perda do dia da CONTA inteira (o que a corretora mostra: fechadas mais "
        "abertas), contra o limite de perda do dia cadastrado. A 90% a automação "
        "encerra tudo e não entra mais até amanhã. Bom: abaixo de 60% (cinza). "
        "Atenção: 60–85% (âmbar). Ruim: 85% ou mais (rosa).")
    if extra:
        explica_perda += f" {extra}"
    rot = html.Span([html.Span(origem.upper(), className=f"op-acc op-acc-{origem}"),
                     " · perda do dia", dica(explica_perda)], className="op-kpi-r")
    if parada:
        return html.Div([rot, html.Span("—", className="op-kpi-v"),
                         html.Span("conta parada", className="op-kpi-n")],
                        className="op-kpi op-kpi-conta", style={"order": ordem})
    if not perda:
        return html.Div([rot, html.Span("—", className="op-kpi-v"),
                         html.Span("sem leitura da conta", className="op-kpi-n")],
                        className="op-kpi op-kpi-conta", style={"order": ordem})
    total = float(perda.get("total") or 0)
    este, outros, fora = _quebra(perda, portfolio_id)
    abertura = (f"este portfólio {_parte(este)} · outros portfólios "
                f"{_parte(outros)} · fora da automação {_parte(fora)}")
    if este + outros + fora < 0:
        abertura += " · dia no ganho: a barra conta só perdas"
    # a quebra é frase longa: vai para o (?) e para o title da nota
    explica = f"{explica_perda} Agora: {abertura}."
    if limite:
        pct = total / float(limite) * 100
        barra = html.Div([
            html.Span(className=f"ord-barra-uso ord-barra-{tom_da_perda(pct)}",
                      style={"width": f"{min(100, round(pct))}%"}),
            html.Span(className="ord-barra-marca", style={"left": f"{TRAVA_PCT}%"}),
        ], className="ord-barra")
        # "R$ 0 / 500", como no rascunho v4
        valor = [_reais(total), html.Span(f" / {inteiro(int(round(float(limite))))}",
                                          className="ord-kpi-de",
                                          title=f"de {_reais(limite)}")]
        nota = f"{round(pct)}% · trava em {TRAVA_PCT}%"
        explica += (f" A trava encerra tudo em "
                    f"{_reais(float(limite) * TRAVA_PCT / 100)}.")
    else:
        barra = None
        valor = _reais(total)
        nota = "sem limite cadastrado"
    rot = html.Span([html.Span(origem.upper(), className=f"op-acc op-acc-{origem}"),
                     " · perda do dia", dica(explica)], className="op-kpi-r")
    filhos = [rot, html.Span(valor, className="op-kpi-v"),
              html.Span(nota, className="op-kpi-n", title=abertura)]
    if barra is not None:
        filhos.append(barra)
    return html.Div(filhos, className="op-kpi op-kpi-conta", style={"order": ordem})


def numeros(ordens: dict | None, resultado_portfolio: float,
            papel_portfolio: float, *, portfolio_id=None,
            ligacoes=None, real: dict | None = None, com_real: bool = False,
            real_parada: bool = False, resultado_real: float | None = None,
            total_demo: float | None = None, total_real: float | None = None,
            pior: dict | None = None) -> html.Div:
    """As células de conta da tira de números (spec parte 5, Operação):
    REAL hoje e Perda do dia · real (só com conta real cadastrada), DEMO
    hoje e Perda do dia · demo. A ordem vem no `style` (1 a 5) e o CSS as
    põe lado a lado com o PAPEL hoje e o Contra o esperado da faixa de
    cima. A demo hoje é deste portfólio (fechadas mais a aberta, antes dos
    custos); o total embaixo é desde o plano em vigor. `pior` (o pior
    momento do dia) vai para o (?) da perda da demo. `ligacoes` fica na
    assinatura porque o pulso a passa (é dele o filtro das posições)."""
    o = ordens or {}
    tem = bool(o) and o.get("n_demo") != 0
    celulas = []
    if com_real:
        if real_parada or not real:
            celulas.append(_cel_hoje("real", None, None, 1,
                                     "Fechadas na conta real hoje mais o "
                                     "resultado aberto. Vazio quando a captura "
                                     "da conta real parou.",
                                     sem="conta real parada"))
        else:
            celulas.append(_cel_hoje(
                "real", resultado_real, total_real, 1,
                "Fechadas na conta real hoje mais o resultado aberto das "
                "posições, só deste portfólio, antes dos custos. Embaixo, o "
                "total desde o plano em vigor, líquido dos custos do plano. "
                "Bom: positivo. Ruim: perda perto do limite de perda do dia."))
    explica_demo = (
        "Fechadas na demo hoje mais o resultado aberto das posições, só deste "
        "portfólio, antes dos custos. Embaixo, o total desde o plano em vigor. "
        "O papel das mesmas operações executadas fica no (?) da linha de "
        "Papel × demo, na Avaliação. Bom: perto do papel (a execução custa "
        "pouco). Ruim: bem abaixo do papel todo dia.")
    if tem:
        celulas.append(_cel_hoje("demo", resultado_portfolio, total_demo, 2,
                                 explica_demo + f" Hoje o papel no mesmo "
                                 f"tamanho: {_rs(papel_portfolio)}."))
    else:
        celulas.append(_cel_hoje("demo", None, None, 2, explica_demo,
                                 sem="sem demo hoje"))
    if com_real:
        celulas.append(perda_do_dia(real, portfolio_id, origem="real", ordem=4,
                                    parada=real_parada or not real))
    texto_pior = None
    if pior and pior.get("valor") is not None:
        quando = pior.get("quando")
        hora = f" às {_hora(quando)}" if quando else ""
        texto_pior = (f"Pior momento de hoje: {_rs(pior['valor'])}{hora}.")
    celulas.append(perda_do_dia(o, portfolio_id, origem="demo", ordem=5,
                                extra=texto_pior))
    return html.Div(celulas, className="ord-numeros")
