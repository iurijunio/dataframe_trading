"""Ordens: faixa de saúde da automação e faixa de chamados."""
from __future__ import annotations

from datetime import datetime

from dash import html

from ..cartao import dica, num

from .base import ATRASO_LENTO_MS, SEM_VIDA_S, _etiqueta, _hora, _idade_s, _nome, _reais


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
    # regra da tela: nada de frase explicativa visível; o texto do chamado
    # (e o diário) já dizem tudo
    "divergencia_papel": None,
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
        sub = _SUBTEXTO.get(c.get("tipo"), "O stop e o alvo seguem na corretora.")
        texto = [html.B(_nome(nomes, lig)), " · ", c.get("texto") or "chamado"]
        if sub:
            texto += [html.Br(), html.Span(sub, className="mut")]
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
