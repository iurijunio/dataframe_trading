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

from core.ordem_teste import ETAPAS as ETAPAS_TESTE
from core.ordem_teste import texto_falhou as texto_teste_falhou
from core.ordens import ZERAR_DESCARTADO
from core.papel_leitura import checagem_ensaio

from .cartao import dica, inteiro, nome_curto, num

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
                       "conta_travada", "teste_falhou"})
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
    """1 → "1", 1.3 → "1,3", -2.0 → "-2", -0.04 → "0" (sem ",0" sobrando).

    Arredonda ANTES de olhar zero e inteiro: -0,04 testado cru não é
    inteiro e saía "-0,0"; 2,96 saía "3,0". `round` devolve -0.0, que é
    igual a 0, então o zero perde o sinal aqui."""
    if v is None:
        return "—"
    r = round(float(v), casas)
    if r == 0:
        return "0"
    if r == int(r):
        return str(int(r))
    return num(r, casas)


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


def subtitulo(titulo, explica=None, *direita):
    """Subtítulo dentro de uma aba da Operação (Demo, Papel, Eventos...),
    com o (?) e os controles do bloco à direita."""
    return html.Div([
        html.H4([titulo] + ([dica(explica)] if explica else []),
                className="op-sub-t"),
        *([html.Div(list(direita), className="op-sub-dir")] if direita else []),
    ], className="op-sub")


def _vazio(texto, explica):
    """Estado vazio curto: o rótulo na tela, o porquê no (?)."""
    return html.P([texto, dica(explica)], className="op-vazio-txt")


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


def _nome_tab(nome, classe="op-nome-tab") -> html.Span:
    """O nome curto da variante numa tabela; o inteiro no `title`."""
    nome = nome or "—"
    return html.Span(nome_curto(nome), className=classe, title=nome)


# ============================================================ faixa de saúde
# cada coluna da faixa: (rótulo, explicação do (?)) — os (?) são os de sempre
_COLUNAS_SAUDE = (
    ("MT5", "A automação lê a conta pelo MetaTrader 5 aberto neste computador. "
            "Bom: conectado. Ruim: fora do ar no pregão — nada entra nem sai pela "
            "automação (o stop e o alvo seguem na corretora)."),
    ("Algo Trading", "O botão Algo Trading do MT5 precisa estar ligado para a "
                     "automação enviar ordens. Bom: ligado. Ruim: desligado — vira "
                     "um chamado."),
    ("Conta", "A conta em que o MT5 está logado agora. Bom: a conta cadastrada "
              "no portfólio. Ruim: outra conta — a automação não manda nada nela."),
    ("Margem livre", "Dinheiro livre na conta para abrir posição. Bom: folgado "
                     "para os contratos de todas as variantes. Ruim: perto de zero "
                     "— a corretora recusa a entrada (sem margem)."),
    ("Ordem (média)", "Tempo médio de hoje entre a abertura do minuto do sinal e a "
                      "corretora confirmar a entrada. Bom: abaixo de 1 s. Ruim: "
                      "acima de 2 s (âmbar) — a entrada sai longe do preço do papel."),
)
_EXPLICA_VIDA = ("Há quanto tempo a captura fez a última volta das ordens. Bom: até "
                 "10 s. Ruim: mais de 1 min — a captura parou (o stop e o alvo "
                 "seguem na corretora).")
_EXPLICA_CANDLE = ("O último candle de 1 minuto gravado. Bom: o minuto que acabou de "
                   "fechar. Ruim: parado no pregão — a captura não está recebendo "
                   "preço.")


def real_parada(bloco: dict | None, agora: datetime | None) -> bool:
    """A conta real não publica há mais de `SEM_VIDA_S` (ou nunca publicou):
    o que ela mostra não vale mais — nem chamado, nem saúde."""
    idade = _idade_s((bloco or {}).get("vivo_em"), agora) if bloco else None
    return idade is None or idade > SEM_VIDA_S


def _valores_conta(o: dict, agora: datetime | None) -> dict:
    """Os valores de UMA conta (o bloco `ordens` dela) nas quatro colunas
    de conta: MT5, Algo Trading, Conta, Margem livre. Pares (texto, tom)."""
    conta = o.get("conta") or {}
    tem_foto = o.get("foto") in ("ok", "parcial")

    if o.get("erro"):
        mt5, mt5_tom = "erro nas ordens", "rosa"
    elif o.get("parado"):
        mt5 = o["parado"]
        mt5_tom = "rosa" if "MT5" in str(o["parado"]) else "cinza"
    elif o.get("foto") == "falhou":
        mt5, mt5_tom = "sem leitura", "ambar"
    elif o.get("foto") == "parcial":
        mt5, mt5_tom = "leitura parcial", "ambar"
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
    return {"mt5": (mt5, mt5_tom), "algo": (algo, algo_tom),
            "conta": (logada, logada_tom), "margem": (_reais(margem), "")}


def _celula(valor, tom="") -> html.Span:
    return html.Span(valor, className="ord-saude-v" + (f" {tom}" if tom else ""))


def _linha_conta(origem: str, cols: list[tuple[str, str]]) -> html.Div:
    """Uma linha da faixa: a etiqueta REAL/DEMO e as colunas da conta."""
    return html.Div([html.Span(origem.upper(), className=f"ord-conta ord-conta-{origem}")]
                    + [_celula(v, t) for v, t in cols], className="ord-saude-linha")


def faixa_saude(ordens: dict | None, *, ultimo_candle=None, atraso_ms=None,
                agora: datetime | None = None, real: dict | None = None,
                com_real: bool = False) -> html.Div:
    """Duas linhas (REAL, quando há conta real; DEMO) com MT5, Algo Trading,
    conta, margem livre e a ordem média; embaixo, o sinal de vida e o último
    candle, comuns às duas. `real` é o bloco `ordens` da conta real
    (`estado_real.json`); `com_real` diz que há conta real cadastrada, mesmo
    sem o arquivo — aí a linha REAL aparece como "parado". `agora` na hora do
    servidor (a mesma dos carimbos do estado), para a idade não herdar o
    atraso do PC."""
    o = ordens or {}
    v = _valores_conta(o, agora)
    if atraso_ms is None:
        atraso, atraso_tom = "—", ""
    else:
        atraso = f"{num(atraso_ms / 1000, 1)} s"
        atraso_tom = "ambar" if atraso_ms > ATRASO_LENTO_MS else ""

    cabecalho = html.Div(
        [html.Span("", className="ord-saude-k")]
        + [html.Span([rot, dica(exp)], className="ord-saude-k")
           for rot, exp in _COLUNAS_SAUDE],
        className="ord-saude-linha ord-saude-cab")
    linhas = [cabecalho]
    if com_real or real is not None:
        if real_parada(real, agora):
            # parada: nada da conta real vale; só o MT5 diz "parado"
            cols = [("parado", "rosa"), ("—", ""), ("—", ""), ("—", ""), ("—", "")]
        else:
            r = _valores_conta(real, agora)
            cols = [r["mt5"], r["algo"], r["conta"], r["margem"], ("—", "")]
        linhas.append(_linha_conta("real", cols))
    linhas.append(_linha_conta("demo", [v["mt5"], v["algo"], v["conta"], v["margem"],
                                        (atraso, atraso_tom)]))

    idade = _idade_s(o.get("vivo_em"), agora)
    if idade is None:
        vida, vida_tom = "—", ""
    else:
        idade = max(0, idade)
        vida = f"há {round(idade)} s" if idade < 120 else f"há {round(idade / 60)} min"
        vida_tom = "ok" if idade <= SEM_VIDA_S else ("ambar" if idade <= 60 else "rosa")
    comum = html.Div([
        html.Span(["sinal de vida ", dica(_EXPLICA_VIDA)], className="ord-saude-k"),
        _celula(vida, vida_tom),
        html.Span(["último candle ", dica(_EXPLICA_CANDLE)], className="ord-saude-k"),
        _celula(_hora(ultimo_candle), "ok" if ultimo_candle else ""),
    ], className="ord-saude-comum")
    return html.Div(linhas + [comum], className="ord-saude")


# ======================================================== faixa de chamados
_SUBTEXTO = {
    "saida_pendente": "A automação segue tentando sair. O stop e o alvo seguem "
                      "na corretora.",
    "sem_stop": "Posição sem stop na corretora: encerre ou acompanhe de perto.",
    "papel_parado": "Sem o papel a automação só protege e sai por comando "
                    "(Zerar tudo, Encerrar posição, trava): nada entra.",
    "sem_leitura": "A corretora não responde a leitura completa. Com a leitura "
                   "parcial a automação só sai e protege; sem nenhuma, nada sai "
                   "(o stop e o alvo seguem na corretora).",
    "conta_errada": "Nada é enviado enquanto o MT5 estiver em outra conta.",
    "algo_desligado": "Ligue o Algo Trading no MT5; nada sai até lá.",
    "mt5_fora": "O stop e o alvo seguem na corretora.",
    "teste_preso": "Posição da Ordem de teste (magic 7000000). A captura segue "
                   "tentando encerrar a cada 1 s.",
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
        # a conta de origem do chamado: "real" (laranja) ou "demo" (ciano)
        origem = c.get("origem") or "demo"
        linhas.append(html.Div([
            _etiqueta("precisa de você", "rosa"),
            html.Span(origem, className=f"ord-conta ord-conta-{origem}"),
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


def tabela_papel_demo(cmp: dict | None, origem: str = "demo"):
    """Papel × Demo (ou Papel × Real, com `origem="real"`) por contrato, nos
    mesmos pregões. A conta real usa a mesma tabela e a mesma régua."""
    c = cmp or {}
    p, d = c.get("papel"), c.get("demo")
    nome = "real" if origem == "real" else "demo"
    if not c.get("pregoes") or d is None:
        return _vazio(f"nenhum pregão na {nome} ainda",
                      "Quando uma variante for para a "
                      f"{nome}, esta tabela compara a execução da {nome} com o "
                      "papel, por contrato.")
    p = p or {}

    def dif(a, b, fmt):
        if a is None or b is None:
            return "—"
        return fmt(b - a)

    pn, dn = int(p.get("n") or 0), int(d.get("n") or 0)
    perdidas = int(d.get("perdidas") or 0)
    mm = int(d.get("mesmo_minuto") or 0)

    def mais(v, casas):
        # o "+" olha o número arredondado, como o _decimal: 0,04 é "0"
        return ("+" if round(v, casas) > 0 else "") + _decimal(v, casas)

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
        ("Derrapagem média por ponta", "Ticks por ponta. Papel = a derrapagem "
         "que o plano supõe (o backtest e o papel já a descontam). Demo = a que "
         "a demo teve de fato (a do plano mais o que passou dela). Diferença = "
         "o que passou do plano. Bom: diferença perto de 0. Ruim: acima de 1 "
         "tick por ponta — o backtest está otimista.",
         "—" if p.get("derrapagem") is None else f"{_decimal(p['derrapagem'])} tick",
         "—" if d.get("derrapagem") is None else f"{_decimal(d['derrapagem'])} tick",
         mais(d["derrapagem_extra"], 1) if d.get("derrapagem_extra") is not None
         else dif(p.get("derrapagem"), d.get("derrapagem"), lambda v: mais(v, 1)),
         ""),
        ("Recusadas · resolvidas sozinha · chamados", "Entradas que a corretora "
         "recusou, quantas delas a automação resolveu sozinha tentando de novo, e "
         "os chamados que pediram você. Recusadas conta operações: uma por "
         "operação com a entrada recusada, mesmo que a recusa se repita. Ordens "
         "rejeitadas, no Esperado × Papel × Demo, conta cada recusa da corretora "
         "(entrada, saída, proteção) e por isso pode dar mais. Bom: zero "
         "chamados. Ruim: recusas todo dia.", "—", f"{d.get('recusadas', 0)} · {d.get('resolvidas', 0)} · "
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
                   html.Th(nome.capitalize(), className="n"),
                   html.Th("Diferença", className="n")])
    return html.Table([html.Thead(cab), html.Tbody(corpo)],
                      className="op-tabela op-cmp")


def avaliacao(situacao_backtest: dict | None, comparativo_demo: dict | None,
              curva=None, comparativo=None,
              comparativo_real: dict | None = None) -> html.Section:
    """A aba Avaliação: Esperado × Papel × Demo × Real (`comparativo`, a
    caixa que o redesenho preenche), a curva Papel × esperado, as tabelas
    Papel × real e Papel × demo por contrato e o selo papel = backtest.
    Dois por linha, na ordem de leitura."""
    def bloco(*filhos):
        return html.Div(list(filhos), className="op-aval-bloco")
    return html.Section(html.Div([
        bloco(subtitulo("Esperado (WFA) × Papel × Demo × Real",
                        "Por contrato e só operações fechadas: o que o "
                        "walk-forward prometeu contra o que o papel e as contas "
                        "fizeram. Cada linha tem o (?) com a faixa boa e a ruim."),
              comparativo if comparativo is not None else []),
        bloco(curva if curva is not None else []),
        bloco(subtitulo("Papel × real", "Mesmos pregões, por contrato, com a "
                        "conta real: quanto a execução de verdade custa contra "
                        "o papel."),
              html.Div(tabela_papel_demo(comparativo_real, "real"),
                       id="av-op-ord-cmp-real", className="op-cmp-caixa")),
        bloco(subtitulo("Papel × demo", "Mesmos pregões, por contrato: quanto a "
                        "execução de verdade custa contra o papel."),
              html.Div(tabela_papel_demo(comparativo_demo), id="av-op-ord-cmp",
                       className="op-cmp-caixa")),
        bloco(subtitulo("Papel × backtest", "Toda manhã a captura roda o "
                        "backtest do plano nos pregões do papel e compara "
                        "operação por operação. Qualquer diferença impede a "
                        "variante de subir para a demo."),
              html.Div(selo_backtest(situacao_backtest), id="av-op-ord-selo",
                       className="ord-selo-bt")),
    ], className="op-aval-grade"),
        id="av-op-ord-avaliacao", className="op-pane op-pane-avaliacao")


# ================================================== contratos da demo (✎)
def ler_contratos(texto) -> int | None:
    """O campo do editor: vazio volta aos contratos do plano (None); fora
    disso, inteiro de 1 em diante — o resto é ValueError com a frase da
    tela."""
    t = str(texto or "").strip()
    if not t:
        return None
    # isdigit() aceita "²" e dígitos de outras escritas, que int() recusa
    if not (t.isascii() and t.isdigit()) or int(t) < 1:
        raise ValueError("digite um número inteiro de contratos (1 ou mais), ou "
                         "deixe vazio para usar os do plano")
    return int(t)


def contratos_antes(proprio, plano) -> str:
    """"antes: 2 · papel segue com 3 (plano)": o que vale hoje na demo e no
    papel, para quem vai mexer no campo (o editor da Operação e a ficha)."""
    if proprio is not None:
        return f"antes: {proprio} · papel segue com {plano or '—'} (plano)"
    return f"hoje: os do plano ({plano or '—'}) · o papel segue com eles"


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
        if pct > 100:
            partes += [html.Br(), html.Span(
                "Atenção: um stop sozinho passa do limite do dia — a trava "
                "barraria a entrada. Dá para salvar, mas reveja.",
                className="aviso")]
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
            # debounce: a prévia (que lê o banco) roda ao sair do campo
            # ou no Enter, não a cada tecla
            dcc.Input(id="av-op-ord-ctr-valor", type="text", inputMode="numeric",
                      debounce=True, placeholder="plano",
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
