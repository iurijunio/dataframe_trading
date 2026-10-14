"""Ao vivo › Operação com a demo (spec ordens §8, rascunho v2).

Construtores puros: recebem o bloco `ordens` do estado.json (o que
`core.ordens.Motor.passo` publica) ou as leituras de `core.papel_leitura`
e devolvem componentes. Quem lê é `ui/callbacks_operacao.py`: o estado a
cada 2 s (saúde, chamados, posições, os três números) e o banco só quando
`ordens_em` ou o papel mudam (operações, diário, avaliação).

Duas regras de cor atravessam o arquivo: rosa é PROBLEMA — nunca o lado
da venda (venda é azul, compra verde, em contorno); e toda métrica nova
leva um (?) com a faixa boa e a ruim, porque o usuário decide olhando a
tela, não lendo código.

Sem demo ainda (tudo no papel), cada bloco aparece vazio e explicando o
porquê — nunca quebrado nem com "None".
"""
from __future__ import annotations

from datetime import date, datetime

from dash import dcc, html

from .cartao import dica, inteiro, num

# trava da conta (core.ordens.TRAVA): a marca na barra da perda do dia
TRAVA_PCT = 90
# faixas da barra da perda do dia da conta (controller): cinza, âmbar, rosa
ATENCAO_PCT, PERIGO_PCT = 60, 85
# atraso médio da ordem acima disto pinta de âmbar
ATRASO_LENTO_MS = 2000
# captura sem sinal de vida além disto: o comando da tela fica esperando
SEM_VIDA_S = 10

# Os eventos que o "Só problemas" mostra (controller).
PROBLEMAS = frozenset({"recusada", "perdida", "nao_entrou", "chamado",
                       "saida_recusada", "protecao_recusada", "incerta",
                       "conta_travada"})
# Passos internos do motor: a escrita adiantada (`*_enviando`) e o
# cancelamento de resto de ordem são o "como", não o "o quê" — o diário da
# tela mostra problemas e desfechos.
_INTERNOS = frozenset({"enviando", "saida_enviando", "protecao_enviando",
                       "cancelar_enviando", "cancelar_recusada"})
_COMANDOS_INTERNOS = frozenset({"zerar_tudo_cumprido", "envio_cumprido"})


# --------------------------------------------------------------- formatação
def _data(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _rs(v) -> str:
    """"+R$ 94", "-R$ 150", "R$ 0", "—"."""
    if v is None:
        return "—"
    corpo = inteiro(int(round(abs(v))))
    if round(v) == 0:
        return f"R$ {corpo}"
    return f"{'+' if v > 0 else '-'}R$ {corpo}"


def _reais(v) -> str:
    return "—" if v is None else f"R$ {inteiro(int(round(v)))}"


def _sinal(v) -> str:
    if v is None or round(v, 2) == 0:
        return ""
    return "pos" if v > 0 else "neg"


def _preco(v) -> str:
    return "—" if v is None else inteiro(int(round(float(v))))


def _hora(v, segundos=False) -> str:
    ts = _data(v)
    if ts is None:
        return "—"
    return f"{ts:%H:%M:%S}" if segundos else f"{ts:%H:%M}"


def _decimal(v, casas=1) -> str:
    """1 → "1", 1.3 → "1,3", -2.0 → "-2" (sem ",0" sobrando)."""
    if v is None:
        return "—"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return num(v, casas)


def _int_sinal(v) -> str:
    if v is None:
        return "—"
    v = int(round(v))
    return ("+" if v > 0 else "-" if v < 0 else "") + inteiro(abs(v))


def _idade_s(desde, agora) -> float | None:
    d = _data(desde)
    if d is None or agora is None:
        return None
    return (agora - d).total_seconds()


def _mmss(seg) -> str:
    seg = max(0, int(seg))
    return f"{seg // 60}:{seg % 60:02d}"


def _etiqueta(texto, tom="cinza", explica=None):
    return html.Span([texto] + ([dica(explica)] if explica else []),
                     className=f"av-tag av-tag-{tom}")


def _lado(lado) -> html.Span:
    """Compra verde, venda azul — em contorno. Rosa é problema, e vender
    não é problema."""
    compra = (lado or 0) > 0
    return html.Span("COMPRA" if compra else "VENDA",
                     className="ord-lado " + ("ord-lado-c" if compra
                                              else "ord-lado-v"))


def _ligacoes(ordens: dict) -> dict[int, dict]:
    """`ligacoes` do estado, com a chave de volta a inteiro (o JSON a
    devolve como texto)."""
    out = {}
    for k, v in ((ordens or {}).get("ligacoes") or {}).items():
        try:
            out[int(k)] = v or {}
        except (TypeError, ValueError):
            continue
    return out


def _nome(nomes, lig) -> str:
    if lig is None:
        return "automação"
    return (nomes or {}).get(lig) or f"#{lig}"


# ============================================================ faixa de saúde
def _item_saude(rotulo, valor, explica, tom=""):
    return html.Div([
        html.Span([rotulo, dica(explica)], className="ord-saude-k"),
        html.Span(valor, className="ord-saude-v" + (f" {tom}" if tom else "")),
    ], className="ord-saude-i")


def faixa_saude(ordens: dict | None, *, ultimo_candle=None, atraso_ms=None,
                agora: datetime | None = None) -> html.Div:
    """MT5, Algo Trading, conta logada, margem livre, sinal de vida, último
    candle e atraso médio da ordem. `agora` na hora do servidor (a mesma
    dos carimbos do estado), para a idade não herdar o atraso do PC."""
    o = ordens or {}
    conta = o.get("conta") or {}
    tem_foto = o.get("foto") == "ok"

    if o.get("erro"):
        mt5, mt5_tom = "erro nas ordens", "rosa"
    elif o.get("parado"):
        mt5 = o["parado"]
        mt5_tom = "rosa" if "MT5" in str(o["parado"]) else "cinza"
    elif o.get("foto") == "falhou":
        mt5, mt5_tom = "sem leitura", "ambar"
    elif tem_foto:
        mt5, mt5_tom = "conectado", "ok"
    elif not o:
        # captura antiga (sem o caminho das ordens) ou antes da 1ª volta
        mt5, mt5_tom = "ordens sem estado", "cinza"
    else:
        mt5, mt5_tom = "—", ""

    if tem_foto and "algo" in conta:
        algo, algo_tom = ("ligado", "ok") if conta.get("algo") else ("desligado", "rosa")
    else:
        algo, algo_tom = "—", ""

    login = conta.get("login")
    if tem_foto and login is not None:
        nome = f"{login}"
        if conta.get("conta_id") is None:
            logada, logada_tom = f"{nome} · não cadastrada", "ambar"
        else:
            logada, logada_tom = nome, "ok"
    else:
        logada, logada_tom = "—", ""

    margem = conta.get("margem_livre") if tem_foto else None

    idade = _idade_s(o.get("vivo_em"), agora)
    if idade is None:
        vida, vida_tom = "—", ""
    else:
        idade = max(0, idade)
        vida = f"há {round(idade)} s" if idade < 120 else f"há {round(idade / 60)} min"
        vida_tom = "ok" if idade <= SEM_VIDA_S else ("ambar" if idade <= 60 else "rosa")

    if atraso_ms is None:
        atraso, atraso_tom = "—", ""
    else:
        atraso = f"{num(atraso_ms / 1000, 1)} s"
        atraso_tom = "ambar" if atraso_ms > ATRASO_LENTO_MS else ""

    return html.Div([
        _item_saude("MT5", mt5, "A automação lê a conta pelo MetaTrader 5 aberto "
                    "neste computador. Bom: conectado. Ruim: fora do ar no pregão "
                    "— nada entra nem sai pela automação (o stop e o alvo seguem "
                    "na corretora).", mt5_tom),
        _item_saude("Algo Trading", algo, "O botão Algo Trading do MT5 precisa "
                    "estar ligado para a automação enviar ordens. Bom: ligado. "
                    "Ruim: desligado — vira um chamado.", algo_tom),
        _item_saude("Conta logada", logada, "A conta em que o MT5 está logado "
                    "agora. Bom: a conta demo cadastrada no portfólio. Ruim: "
                    "outra conta — a automação não manda nada nela.", logada_tom),
        _item_saude("Margem livre", _reais(margem), "Dinheiro livre na conta para "
                    "abrir posição. Bom: folgado para os contratos de todas as "
                    "variantes. Ruim: perto de zero — a corretora recusa a "
                    "entrada (sem margem)."),
        _item_saude("Sinal de vida", vida, "Há quanto tempo a captura fez a última "
                    "volta das ordens. Bom: até 10 s. Ruim: mais de 1 min — a "
                    "captura parou (o stop e o alvo seguem na corretora).",
                    vida_tom),
        _item_saude("Último candle", _hora(ultimo_candle), "O último candle de 1 "
                    "minuto gravado. Bom: o minuto que acabou de fechar. Ruim: "
                    "parado no pregão — a captura não está recebendo preço.",
                    "ok" if ultimo_candle else ""),
        _item_saude("Ordem (média)", atraso, "Tempo médio de hoje entre a abertura "
                    "do minuto do sinal e a corretora confirmar a entrada. Bom: "
                    "abaixo de 1 s. Ruim: acima de 2 s (âmbar) — a entrada sai "
                    "longe do preço do papel.", atraso_tom),
    ], className="ord-saude")


# ======================================================== faixa de chamados
_SUBTEXTO = {
    "saida_pendente": "A automação segue tentando sair. O stop e o alvo seguem "
                      "na corretora.",
    "sem_stop": "Posição sem stop na corretora: encerre ou acompanhe de perto.",
    "papel_parado": "Sem o papel a automação só protege: não entra nem sai.",
    "conta_errada": "Nada é enviado enquanto o MT5 estiver em outra conta.",
    "algo_desligado": "Ligue o Algo Trading no MT5; nada sai até lá.",
    "mt5_fora": "O stop e o alvo seguem na corretora.",
}


def chave_chamado(c: dict) -> str:
    """Identifica o chamado pela hora em que abriu: um chamado que fecha e
    reabre é outro, e volta a aparecer mesmo se o anterior foi escondido."""
    return f"{c.get('chave')}@{c.get('desde')}"


def rotulo_botao(acao, alvo, armado) -> tuple[str, str]:
    """(rótulo, classe) de um botão da faixa de chamados, armado ou não —
    o callback leve que só troca o rótulo usa o mesmo molde."""
    if acao == "encerrar":
        base = ("Encerrar posição", "btn-ghost ord-btn-perigo")
    else:
        base = ("Manter e acompanhar", "btn-ghost av-btn-sec")
    if armado == f"{acao}:{alvo}":
        return "Confirmar: encerra agora", base[1] + " av-armado"
    return base


def faixa_chamados(ordens: dict | None, nomes: dict | None = None, *,
                   escondidos=(), armado=None, esperando=False):
    """Uma linha por chamado aberto ("precisa de você"), com "Encerrar
    posição" (dois cliques; só com ticket) e "Manter e acompanhar" (só
    esconde aqui na tela). None quando não há nada a mostrar."""
    escondidos = set(escondidos or [])
    linhas = []
    for c in (ordens or {}).get("chamados") or []:
        if not isinstance(c, dict) or chave_chamado(c) in escondidos:
            continue
        lig = c.get("ligacao_id")
        ticket = c.get("ticket")
        texto = [html.B(_nome(nomes, lig)), " · ", c.get("texto") or "chamado",
                 html.Br(),
                 html.Span(_SUBTEXTO.get(c.get("tipo"),
                                         "O stop e o alvo seguem na corretora."),
                           className="mut")]
        acoes = []
        if ticket is not None:
            r, cl = rotulo_botao("encerrar", ticket, armado)
            acoes.append(html.Button(
                r, n_clicks=0, className=cl,
                title="Encerra esta posição a mercado na próxima volta da "
                      "captura. Clique duas vezes para confirmar.",
                id={"type": "av-op-ord-acao", "acao": "encerrar", "id": ticket}))
        r, cl = rotulo_botao("manter", chave_chamado(c), armado)
        acoes.append(html.Button(
            r, n_clicks=0, className=cl,
            title="Esconde este aviso aqui na tela. A automação continua como "
                  "está; se o chamado fechar e abrir de novo, ele volta.",
            id={"type": "av-op-ord-acao", "acao": "manter",
                "id": chave_chamado(c)}))
        linhas.append(html.Div([
            _etiqueta("precisa de você", "rosa"),
            html.Div(texto, className="ord-chamado-txt"),
            html.Div(acoes, className="ord-chamado-acoes"),
        ], className="ord-chamado"))
    if esperando:
        linhas.append(html.Div([
            _etiqueta("esperando", "ambar"),
            html.Div("comando enviado, esperando a captura — o stop e o alvo "
                     "seguem na corretora", className="ord-chamado-txt"),
        ], className="ord-chamado ord-chamado-espera"))
    return html.Div(linhas, className="ord-chamados") if linhas else None


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


def posicoes_abertas(ordens: dict | None, nomes: dict, tick: int, *,
                     ponto: float = 0.2, agora: datetime | None = None):
    """O que está na corretora agora, de ESTE portfólio (`nomes` = as
    ligações dele), conferido com o que o papel quer."""
    pos = _posicoes(ordens, list(nomes))
    if not pos:
        o = ordens or {}
        if o.get("n_demo") == 0:
            msg = ("nenhuma posição — nenhuma variante na fase demo; tudo segue "
                   "no papel")
        elif not o:
            msg = "nenhuma posição conhecida — as ordens ainda não têm estado"
        else:
            msg = "nenhuma posição da automação aberta na corretora"
        return html.P(msg, className="av-vazio op-vazio")
    tick = int(tick or 1)
    linhas = []
    for lig, l, p in pos:
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
                return "—"
            return f"{inteiro(int(round(abs(alvo - atual) / tick)))} ticks"
        if sl and tp:
            prot = [html.Span("✓", className="ord-prot"),
                    html.Span(f" stop {_preco(sl)} · alvo {_preco(tp)}",
                              className="mut")]
        elif sl:
            prot = [html.Span("✓", className="ord-prot"),
                    html.Span(f" stop {_preco(sl)} · sem alvo", className="mut")]
        else:
            prot = [html.Span("sem stop", className="neg")]
        esperado = l.get("contratos") if l.get("desejado") == "posicao" else 0
        ctr = [inteiro(int(round(vol)))]
        if esperado is not None and float(esperado) != vol:
            ctr.append(html.Span(f" (esperado {inteiro(int(round(float(esperado))))})",
                                 className="mut"))
        ticks_abertos = (None if atual is None
                         else round((atual - preco) * lado / tick))
        sit, tom = _situacao_posicao(l, p, agora)
        nome = _nome(nomes, lig)
        linhas.append(html.Tr([
            html.Td(html.Span(nome, className="op-nome-tab", title=nome), className="t"),
            html.Td(_lado(lado)),
            html.Td(ctr, className="n" + (" neg" if len(ctr) > 1 else "")),
            html.Td(_preco(preco), className="n"),
            html.Td(prot),
            html.Td(ate(sl), className="n"),
            html.Td(ate(tp), className="n"),
            html.Td(f"{_int_sinal(ticks_abertos)} ticks · {_rs(res)}",
                    className="n " + _sinal(res)),
            html.Td(_etiqueta(sit, tom) if tom != "ambar"
                    else html.Span(sit, className="ord-pend")),
        ]))
    cab = html.Tr([
        _th("Variante"), _th("Lado"),
        _th("Contratos", "Contratos na corretora; entre parênteses o que o papel "
            "quer, quando difere. Bom: iguais. Ruim: diferentes — vira "
            "\"diferente\" e a automação corrige.", True),
        _th("Preço", n=True),
        _th("Proteção na corretora", "Stop e alvo gravados NA corretora (✓). "
            "Bom: os dois presentes. Ruim: sem stop — a automação encerra a "
            "posição em 2 s."),
        _th("Até o stop", "Distância do preço de agora até o stop, em ticks "
            "(1 tick = 5 pontos). Bom: longe. Atenção: perto de zero.", True),
        _th("Até o alvo", "Distância do preço de agora até o alvo, em ticks.",
            True),
        _th("Resultado aberto", "Resultado da posição agora, em ticks e em R$ "
            "(antes dos custos). Bom: positivo.", True),
        _th("Situação", "confere = a corretora tem o que o papel quer; saída "
            "pendente = a automação está tentando sair (passa de 2 min, vira "
            "chamado); indisponível = sem o papel agora, a automação só protege; "
            "diferente = a corretora tem outra coisa."),
    ])
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


def numeros(ordens: dict | None, resultado_portfolio: float,
            papel_portfolio: float, *, portfolio_id=None,
            ligacoes=None) -> html.Div:
    """Resultado hoje na demo (deste portfólio), perda do dia DA CONTA × o
    limite (D2) e as posições abertas deste portfólio."""
    o = ordens or {}
    tem = bool(o) and o.get("n_demo") != 0
    resultado = _kpi(
        "Resultado hoje na demo",
        "Fechadas na demo hoje mais o resultado aberto das posições, só deste "
        "portfólio, antes dos custos. Embaixo, o papel das mesmas operações. "
        "Bom: perto do papel (a execução custa pouco). Ruim: bem abaixo do papel "
        "todo dia.",
        _rs(resultado_portfolio) if tem else "—",
        f"papel {_rs(papel_portfolio)}" if tem else "sem demo hoje",
        _sinal(resultado_portfolio) if tem else "")

    perda = o.get("perda") or {}
    limite = o.get("limite")
    explica_perda = (
        "Perda do dia da CONTA inteira (o que a corretora mostra: fechadas mais "
        "abertas), contra o limite de perda do dia cadastrado. A 90% a automação "
        "encerra tudo e não entra mais até amanhã. Bom: abaixo de 60% (cinza). "
        "Atenção: 60–85% (âmbar). Ruim: 85% ou mais (rosa).")
    if not perda:
        bloco_perda = _kpi("Perda do dia da conta × limite", explica_perda, "—",
                           "sem leitura da conta agora")
    else:
        total = float(perda.get("total") or 0)
        este, outros, fora = _quebra(perda, portfolio_id)
        abertura = (f"este portfólio {_reais(este)} · outros portfólios "
                    f"{_reais(outros)} · fora da automação {_reais(fora)}")
        if limite:
            pct = total / float(limite) * 100
            barra = html.Div([
                html.Span(className=f"ord-barra-uso ord-barra-{tom_da_perda(pct)}",
                          style={"width": f"{min(100, round(pct))}%"}),
                html.Span(className="ord-barra-marca", style={"left": f"{TRAVA_PCT}%"}),
            ], className="ord-barra")
            valor = [_reais(total), html.Span(f" de {_reais(limite)}",
                                              className="ord-kpi-de")]
            nota = (f"{round(pct)}% · trava tudo em {TRAVA_PCT}% "
                    f"({_reais(float(limite) * TRAVA_PCT / 100)}) · {abertura}")
        else:
            barra = None
            valor = _reais(total)
            nota = f"conta demo sem limite cadastrado · {abertura}"
        bloco_perda = _kpi("Perda do dia da conta × limite", explica_perda, valor,
                           nota, extra=barra, title=abertura)

    pos = _posicoes(o, ligacoes)
    conferem = sum(1 for _, l, p in pos
                   if _situacao_posicao(l, p, None)[0] == "confere")
    if pos:
        diferentes = len(pos) - conferem
        nota_pos = [html.Span(f"{conferem} confere" + ("m" if conferem > 1 else ""),
                              className="pos")]
        if diferentes:
            nota_pos += [" · ", html.Span(f"{diferentes} pede"
                                          + ("m" if diferentes > 1 else "")
                                          + " atenção", className="aviso")]
    else:
        nota_pos = "nenhuma na corretora" if tem else "sem demo hoje"
    posicoes = _kpi("Posições abertas", "Posições da automação deste portfólio "
                    "na corretora agora, e quantas batem com o papel. Bom: todas "
                    "conferem. Ruim: alguma diferente ou com a saída pendente.",
                    str(len(pos)) if o else "—", nota_pos)
    return html.Div([resultado, bloco_perda, posicoes], className="ord-numeros")


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
        filhos = [_etiqueta(l.get("saida_motivo") or "fechada", "cinza")]
    else:
        rot, tom, explica = _SITUACOES.get(sit, (sit or "—", "cinza", None))
        if sit in ("perdida", "nao_entrou") and l.get("nota"):
            explica = f"{explica} Motivo: {l['nota']}."
        filhos = [_etiqueta(rot, tom, explica)]
    if sit == "seria_enviada" and l.get("pedido"):
        filhos.append(html.Span(f" {l['pedido']}", className="mut"))
    elif sit == "fechada" and l.get("nota"):
        filhos.append(html.Span(f" {l['nota']}", className="ord-pend"))
    return filhos


def _derrap(l: dict) -> str:
    e, s = l.get("derrapagem_entrada"), l.get("derrapagem_saida")
    if e is None and s is None:
        return "—"
    return f"{_decimal(e)} · {_decimal(s)}"


def operacoes_demo(linhas: list[dict]):
    """A tabela "Operações do dia" da demo. A derrapagem vai por ponta
    (entrada · saída), em ticks, positivo = pior que o papel."""
    if not linhas:
        return html.P("nenhuma operação na demo hoje — com as variantes no papel, "
                      "esta tabela fica vazia; o papel está na tabela de baixo",
                      className="av-vazio op-vazio")
    corpo = []
    for l in linhas:
        pior = max([x for x in (l.get("derrapagem_entrada"),
                                l.get("derrapagem_saida")) if x is not None],
                   default=None)
        executou = l.get("preco_entrada") is not None
        nome = l.get("variante") or "—"
        corpo.append(html.Tr([
            html.Td(_hora(l.get("entry_ts"))),
            html.Td(_hora(l.get("exit_ts"))),
            html.Td(html.Span(nome, className="op-nome-tab", title=nome), className="t"),
            html.Td(_lado(l.get("lado"))),
            html.Td(_decimal(l.get("contratos")) if executou else "—", className="n"),
            html.Td(_preco(l.get("preco_entrada")), className="n"),
            html.Td(_preco(l.get("preco_saida")), className="n"),
            html.Td(_derrap(l), className="n" + (" aviso" if pior is not None
                                                 and pior > 2 else "")),
            html.Td(_int_sinal(l.get("pontos")), className="n " + _sinal(l.get("pontos"))),
            html.Td(_rs(l.get("resultado")) if l.get("resultado") is not None else "—",
                    className="n " + _sinal(l.get("resultado"))),
            html.Td(_situacao_demo(l), className="t"),
        ], className="op-linha" + (" op-aberta" if l.get("situacao") == "aberta" else "")))
    cab = html.Tr([
        _th("Entrada"), _th("Saída"), _th("Variante"), _th("Lado"),
        _th("Contr.", "Contratos executados na demo.", True),
        _th("Preço entrada", n=True), _th("Preço saída", n=True),
        _th("Derrapagem (ticks)", "Diferença para o preço do papel em cada ponta "
            "(entrada · saída), em ticks (1 tick = 5 pontos). Positivo = pior "
            "que o papel; negativo = melhor. Bom: até 1 tick por ponta. Ruim: "
            "acima de 2 ticks (âmbar) com frequência.", True),
        _th("Pontos", "Pontos a favor (+) ou contra (−) por contrato, nos preços "
            "da demo.", True),
        _th("Resultado", "Em R$, antes dos custos (corretagem e emolumentos).",
            True),
        _th("Situação", "Como a operação terminou: stop/alvo na corretora, sinal "
            "do papel, recusada, perdida, ou \"seria enviada\" com o Envio "
            "desligado."),
    ])
    return html.Table([html.Thead(cab), html.Tbody(corpo)],
                      className="op-tabela ord-tabela")


# ============================================================ diário do dia
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
        if motivo == "encerrar_posicao":
            return f"Encerrar posição pedido na tela (ticket {e.get('ticket')})", "ambar"
        if motivo == "envio":
            return ("Envio de ordens " + ("ligado" if e.get("ligado")
                                          else "desligado") + " na tela"), ""
        return f"comando da tela: {motivo}", ""
    if tipo in ("executada", "parcial"):
        atraso = e.get("atraso_ms")
        em = f" em {num(atraso / 1000, 1)} s" if atraso is not None else ""
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
        "seria_enviada": (f"seria enviada (Envio desligado): {lado}{ctr_t}{sim}", ""),
        "adotada": (f"posição adotada a {_preco(e.get('preco'))} ({motivo})"
                    if motivo else "posição adotada", ""),
        "saiu_antes": (f"saiu na corretora a {_preco(e.get('preco'))}: {motivo}"
                       if motivo else "saiu na corretora", ""),
        "saida_executada": (f"saída executada a {_preco(e.get('preco'))}"
                            + (f" ({motivo})" if motivo else ""), ""),
        "saida_parcial": (f"saída executada em parte a {_preco(e.get('preco'))}", ""),
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
        quem = _nome(nomes, e.get("ligacao_id"))
        linhas.append(html.Div([
            html.Span(_hora(e.get("quando"), segundos=True), className="ord-ev-h"),
            html.Span(quem, className="ord-ev-quem", title=quem),
            html.Span(texto, className="ord-ev-t" + (f" {tom}" if tom else "")),
        ], className="ord-ev" + (" ord-ev-problema" if e.get("tipo") in PROBLEMAS
                                 else "")))
    if not linhas:
        msg = ("nenhum problema hoje" if so_problemas else
               "nada no diário hoje — sem variante na demo, a automação não "
               "manda ordens")
        return html.Div(html.P(msg, className="av-vazio op-vazio"))
    return html.Div(linhas)


# ================================================================ avaliação
def selo_backtest(sit: dict | None):
    """"papel = backtest ✓ (N pregões, M operações)" | "K diferenças" (com a
    lista) | "ainda sem pregão conferido"."""
    s = sit or {}
    if not s.get("pregoes"):
        return _etiqueta("ainda sem pregão conferido", "cinza",
                         "Toda manhã a captura roda o backtest do plano nos "
                         "pregões do papel e compara operação por operação. Ainda "
                         "não há pregão conferido.")
    explica = ("Backtest e papel usam o mesmo motor e os mesmos candles: devem "
               "bater operação por operação (hora, lado, preços, motivo da "
               "saída). Bom: ✓. Ruim: qualquer diferença — a variante não pode "
               "subir para a demo até resolver.")
    if s.get("ok"):
        return _etiqueta(f"papel = backtest ✓ ({s['pregoes']} "
                         f"{'pregão' if s['pregoes'] == 1 else 'pregões'}, "
                         f"{s.get('operacoes', 0)} "
                         f"{'operação' if s.get('operacoes') == 1 else 'operações'})",
                         "verde", explica)
    n = int(s.get("diferencas") or 0) or len(s.get("lista") or [])
    lista = "; ".join(
        f"{d.get('nome')} · {d['dia']:%d/%m} ({d.get('n')})"
        if isinstance(d.get("dia"), date) else f"{d.get('nome')} · {d.get('dia')}"
        for d in s.get("lista") or [])
    return html.Span([
        _etiqueta(f"{n} {'diferença' if n == 1 else 'diferenças'}", "rosa", explica),
        html.Span(f" {lista}", className="ord-dif-lista") if lista else None,
    ])


def _fator(v):
    if v is None:
        return "—"
    if v == float("inf"):
        return "sem perdas"
    return num(v, 2)


def tabela_papel_demo(cmp: dict | None):
    """Papel × Demo por contrato, nos mesmos pregões."""
    c = cmp or {}
    p, d = c.get("papel"), c.get("demo")
    if not c.get("pregoes") or d is None:
        return html.P("nenhum pregão na demo ainda — quando uma variante for para "
                      "a demo, esta tabela compara a execução com o papel",
                      className="av-vazio op-vazio")
    p = p or {}

    def dif(a, b, fmt):
        if a is None or b is None:
            return "—"
        return fmt(b - a)

    pn, dn = int(p.get("n") or 0), int(d.get("n") or 0)
    perdidas = int(d.get("perdidas") or 0)
    mm = int(d.get("mesmo_minuto") or 0)

    def mais(v, casas):
        return ("+" if v > 0 else "") + _decimal(v, casas)

    linhas = [
        ("Operações", "Operações fechadas em cada lado. Diferença = entradas que "
         "a demo perdeu (recusa, automação fora do ar). Bom: zero perdidas. Ruim: "
         "perder mais de 1 em 10.", inteiro(pn), inteiro(dn),
         f"{perdidas} {'perdida' if perdidas == 1 else 'perdidas'}" if perdidas
         else "—", "aviso" if perdidas else "mut"),
        ("Pontos por operação", "Pontos médios por operação, por contrato. Bom: "
         "demo a poucos pontos do papel. Ruim: demo bem abaixo — a execução está "
         "custando a vantagem.",
         _int_sinal(p.get("pontos_por_operacao")),
         _int_sinal(d.get("pontos_por_operacao")),
         dif(p.get("pontos_por_operacao"), d.get("pontos_por_operacao"),
             lambda v: _int_sinal(v)), ""),
        ("Fator de lucro", "Pontos ganhos divididos pelos perdidos. Bom: acima de "
         "1,3 e perto do papel. Ruim: abaixo de 1.", _fator(p.get("fator_lucro")),
         _fator(d.get("fator_lucro")),
         dif(p.get("fator_lucro"), d.get("fator_lucro"),
             lambda v: mais(v, 2)) if None not in (p.get("fator_lucro"),
                                                   d.get("fator_lucro"))
         and float("inf") not in (p.get("fator_lucro"), d.get("fator_lucro"))
         else "—", ""),
        ("Sinal no mesmo minuto", "Entradas executadas no mesmo minuto do sinal do "
         "papel, sobre as operações do papel. Bom: 100%. Ruim: abaixo de 90%.",
         "—", f"{num(mm / pn * 100, 1)}%" if pn else "—",
         f"{mm} de {pn}" if pn else "—", "mut"),
        ("Derrapagem média por ponta", "Média, por ponta, da diferença entre o "
         "preço da demo e o do papel, em ticks; no papel, a derrapagem que o plano "
         "supõe. Bom: demo até o que o plano supõe. Ruim: demo acima — o "
         "backtest está otimista.",
         "—" if p.get("derrapagem") is None else f"{_decimal(p['derrapagem'])} tick",
         "—" if d.get("derrapagem") is None else f"{_decimal(d['derrapagem'])} tick",
         dif(p.get("derrapagem"), d.get("derrapagem"), lambda v: mais(v, 1)), ""),
        ("Recusadas · resolvidas sozinha · chamados", "Entradas que a corretora "
         "recusou, quantas delas a automação resolveu sozinha tentando de novo, e "
         "os chamados que pediram você. Bom: zero chamados. Ruim: recusas todo "
         "dia.", "—", f"{d.get('recusadas', 0)} · {d.get('resolvidas', 0)} · "
         f"{d.get('chamados', 0)}", "—", "mut"),
    ]
    corpo = []
    for rot, explica, vp, vd, vdif, tom in linhas:
        corpo.append(html.Tr([
            html.Td(html.Span([rot, dica(explica)], className="op-rot"), className="k"),
            html.Td(vp, className="n"), html.Td(vd, className="n"),
            html.Td(vdif, className="n" + (f" {tom}" if tom else "")),
        ]))
    cab = html.Tr([html.Th(""), html.Th("Papel", className="n"),
                   html.Th("Demo", className="n"),
                   html.Th("Diferença", className="n")])
    return html.Table([html.Thead(cab), html.Tbody(corpo)],
                      className="op-tabela op-cmp")


def avaliacao(situacao_backtest: dict | None, comparativo_demo: dict | None,
              curva=None) -> html.Details:
    """A Avaliação recolhível: selo papel = backtest, a curva Papel ×
    esperado (que já existia) e a tabela Papel × demo por contrato."""
    return html.Details([
        html.Summary([
            html.H3("Avaliação", className="panel-title av-sec-titulo"),
            html.Span("papel × backtest, papel × esperado e papel × demo, por "
                      "contrato · clique para recolher", className="av-sec-nota"),
            html.Div(selo_backtest(situacao_backtest), id="av-op-ord-selo",
                     className="ord-selo-bt"),
        ], className="ord-aval-sum"),
        html.Div([
            html.Div(curva if curva is not None else [], className="ord-aval-curva"),
            html.Section([
                html.Div([html.H3("Papel × demo", className="panel-title av-sec-titulo"),
                          html.P("mesmos pregões, por contrato",
                                 className="av-sec-nota")],
                         className="av-sec-head op-head"),
                html.Div(tabela_papel_demo(comparativo_demo), id="av-op-ord-cmp",
                         className="op-cmp-caixa"),
            ], className="panel"),
        ], className="op-grade2 ord-aval-corpo"),
    ], open=True, id="av-op-ord-avaliacao", className="panel ord-aval")


# ================================================== contratos da demo (✎)
def ler_contratos(texto) -> int | None:
    """O campo do editor: vazio volta aos contratos do plano (None); fora
    disso, inteiro de 1 em diante — o resto é ValueError com a frase da
    tela."""
    t = str(texto or "").strip()
    if not t:
        return None
    if not t.isdigit() or int(t) < 1:
        raise ValueError("digite um número inteiro de contratos (1 ou mais), ou "
                         "deixe vazio para usar os do plano")
    return int(t)


def custo_stop_texto(contratos, custo: dict | None):
    """"Um stop com 3 contratos = R$ 180 = 36% do limite do dia." —
    `custo` é o de `core.ao_vivo.custo_de_um_stop`."""
    c = custo or {}
    if c.get("reais") is None:
        return html.Span("Custo de um stop desconhecido: o plano usa stop por "
                         "ATR e o papel ainda não operou com ele.", className="mut")
    partes = [f"Um stop com {contratos} "
              f"{'contrato' if contratos == 1 else 'contratos'} = ",
              html.B(_reais(c["reais"]))]
    if c.get("pct_limite") is not None:
        pct = c["pct_limite"]
        partes += [" = ", html.B(f"{_decimal(pct, 0) if pct >= 10 else num(pct, 1)}%"),
                   " do limite do dia."]
    else:
        partes.append(" (conta demo sem limite cadastrado).")
    return html.Span(partes)


def editor_contratos() -> html.Div:
    """O popover do ✎ dos cartões, fixo no layout (um só para todas as
    variantes): o callback mostra, preenche e esconde."""
    return html.Div([
        html.H4("Contratos na demo", id="av-op-ord-ctr-titulo",
                className="ord-pop-t"),
        html.Div([
            dcc.Input(id="av-op-ord-ctr-valor", type="text", inputMode="numeric",
                      debounce=False, placeholder="plano",
                      className="ord-pop-inp", autoComplete="off"),
            html.Span(id="av-op-ord-ctr-antes", className="mut"),
        ], className="ord-pop-linha"),
        html.Div(id="av-op-ord-ctr-custo", className="ord-pop-custo"),
        html.P("A mudança vale a partir da próxima operação. Vazio = os "
               "contratos do plano.", className="ord-pop-nota"),
        html.P(id="av-op-ord-ctr-erro", className="ord-pop-erro"),
        html.Div([
            html.Button("Cancelar", id="av-op-ord-ctr-cancelar", n_clicks=0,
                        className="btn-ghost av-btn-sec"),
            html.Button("Salvar", id="av-op-ord-ctr-salvar", n_clicks=0,
                        className="btn-ghost av-btn-principal"),
        ], className="ord-pop-botoes"),
    ], id="av-op-ord-ctr-pop", className="ord-pop", style={"display": "none"})
