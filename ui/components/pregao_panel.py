"""Situação do serviço de captura, como a tela a mostra.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6–7.

Só desenha: quem lê o `estado.json` é `ui/data.py`. Por isso `situacao`
recebe o estado e a hora — dá para testar cada frase com um dicionário
montado à mão. O selo do topo e a sub-tela Ao vivo › Pregão (cartões de
estado, gráfico do dia, placar) partem da mesma `situacao`: as duas nunca
discordam sobre se a captura está de pé.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import dash_tvlwc
from dash import dcc, html

from core import captura as CAP

from .. import theme as T
from ..data import to_epoch
from .cartao import dica as _dica

# O serviço publica a cada volta (segundos no pregão, ~30 s fora dele).
# Um minuto sem publicar é processo morto ou travado, não volta lenta.
FRESCO = timedelta(seconds=60)
# Hora gravada à frente da do PC: o relógio do Windows voltou depois da
# última volta. Uns segundos são a corrida entre a captura gravar e a tela
# ler; além disso o estado não prova que o serviço está vivo.
FUTURO_TOLERADO = timedelta(seconds=5)
# Uma mineração grava em lotes de dezenas de segundos; abaixo de 2 min o
# serviço só está esperando a vez, e a fila dele não perde candle.
BANCO_OCUPADO = timedelta(minutes=2)
# O desvio do relógio oscila com a rajada de negócios; abaixo disso é ruído.
DESVIO_RELOGIO_S = 30
# Antes das 10:00 um dia útil sem candle ainda pode abrir atrasado (leilão
# estendido); depois disso o mais provável é feriado da B3.
SEM_PREGAO_DEPOIS = time(10, 0)

MOTIVO_CAPTURA = "a captura ao vivo já mantém a base em dia"


def _data(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _idade(estado: dict | None, agora: datetime) -> timedelta | None:
    feito = _data((estado or {}).get("atualizado_em"))
    return None if feito is None else agora - feito


def captura_ativa(estado: dict | None, agora: datetime) -> bool:
    idade = _idade(estado, agora)
    return idade is not None and -FUTURO_TOLERADO < idade < FRESCO


def _fechamento(estado: dict) -> time:
    try:
        return time.fromisoformat(str(estado.get("fechamento_esperado")))
    except ValueError:
        return CAP.FECHAMENTO_PADRAO


def _sit(tom, texto, acao, ativa, pregao) -> dict:
    return {"tom": tom, "texto": texto, "acao": acao, "ativa": ativa,
            "pregao": pregao}


def situacao(estado: dict | None, agora: datetime) -> dict:
    """A primeira regra que casar decide o selo: do problema que para tudo
    para o aviso que só pede atenção."""
    if estado is None:
        return _sit("ambar", "Captura nunca rodou neste computador",
                    "abra pelo iniciar.bat", False, False)

    ativa = captura_ativa(estado, agora)
    # com o serviço parado, o "em_pregao" gravado é de quando ele morreu
    pregao = (bool(estado.get("em_pregao")) if ativa
              else CAP.em_pregao(agora, _fechamento(estado)))
    erro = estado.get("erro")

    if not ativa:
        if erro:
            # erro de configuração (código 3): o serviço grava a frase e sai,
            # e a janela dele fica minimizada — sem isto ninguém a lê
            return _sit("rosa", f"Captura parada: {erro}",
                        "corrija e abra de novo pelo iniciar.bat", False, pregao)
        if not pregao:
            return _sit("cinza", "Captura parada (fora do pregão)", None,
                        False, False)
        idade = _idade(estado, agora)
        texto = ("Captura parada" if idade is None
                 else f"Captura parada há {int(idade.total_seconds() // 60)} min")
        return _sit("rosa", texto,
                    "confira a janela “Dataframe - Captura” "
                    "ou abra pelo iniciar.bat", False, True)

    if erro:
        return _sit("rosa", str(erro),
                    "detalhes na janela “Dataframe - Captura”", True, pregao)

    mt5 = estado.get("mt5")
    if mt5 == "fechado":
        return _sit("rosa", "MT5 fechado",
                    "abra e faça login; a captura recupera o período sozinha",
                    True, pregao)
    if mt5 == "sem_conexao":
        desde = _data(estado.get("mt5_desde"))
        texto = "Sem conexão com a corretora" + (
            f" desde {desde:%H:%M}" if desde else "")
        return _sit("ambar", texto,
                    "confira a internet e o login no MT5; a captura recupera "
                    "o período sozinha", True, pregao)

    ocupado = _data(estado.get("banco_ocupado_desde"))
    if ocupado and agora - ocupado > BANCO_OCUPADO:
        minutos = int((agora - ocupado).total_seconds() // 60)
        return _sit("ambar", f"Banco ocupado há {minutos} min",
                    "uma mineração está gravando; nada se perde", True, pregao)

    desvio = estado.get("relogio_desvio_s")
    if desvio is not None and abs(desvio) > DESVIO_RELOGIO_S:
        lado = "adiantado" if desvio > 0 else "atrasado"
        return _sit("ambar", f"Relógio do PC {lado} {round(abs(desvio))} s",
                    "acerte a hora do Windows (Configurações › Hora › "
                    "Sincronizar agora)", True, pregao)

    primeiro = _data(estado.get("primeiro_candle_hoje"))
    if agora.weekday() < 5 and (primeiro is None or primeiro.date() != agora.date()):
        # sem alarme: a B3 tem feriados que o código não conhece (12/10, 02/11…)
        if agora.time() < SEM_PREGAO_DEPOIS:
            return _sit("cinza", "Aguardando a abertura", None, True, pregao)
        return _sit("cinza", "Sem pregão hoje (feriado?)", None, True, pregao)

    if pregao:
        return _sit("verde", "Captura ativa", None, True, True)
    return _sit("verde", "Captura ativa — mercado fechado", None, True, False)


def selo(sit: dict) -> tuple:
    """(children, className, style) do selo do topo. Cinza some: fora do
    pregão com a captura parada não há nada a fazer, e um selo apagado
    em toda tela vira ruído."""
    if sit["tom"] == "cinza":
        return [], "captura-selo", {"display": "none"}
    return ([html.Span("●", className="captura-selo-ponto"),
             html.Span(sit["texto"], className="captura-selo-texto")],
            f"captura-selo captura-selo-{sit['tom']}", {})


def dica(sit: dict) -> str:
    """Texto ao passar o mouse: a frase inteira (o selo corta as longas) e
    o que fazer."""
    return sit["texto"] + (f" — {sit['acao']}" if sit["acao"] else "")


# ================================================================ Pregão
# Último candle: o M1 fecha 60 s depois do horário dele e a captura publica
# em ~1 s. Até 90 s é o normal (a corretora às vezes atrasa o fechamento);
# 3 min sem candle novo no pregão é captura parada ou MT5 sem dados.
IDADE_VERDE_S = 90
IDADE_AMBAR_S = 180
MINUTOS_TF = {"M1": 1, "M5": 5, "M15": 15}


def idade_tom(segundos: float, pregao: bool) -> str:
    """Cor do "Último candle". Fora do pregão a idade só cresce e não quer
    dizer nada — cinza, nunca alarme."""
    if not pregao:
        return "cinza"
    if segundos <= IDADE_VERDE_S:
        return "verde"
    if segundos <= IDADE_AMBAR_S:
        return "ambar"
    return "rosa"


def _quanto(segundos: float) -> str:
    s = max(0, int(segundos))
    if s < 120:
        return f"há {s} s"
    if s < 2 * 3600:
        return f"há {s // 60} min"
    return f"há {s // 3600} h"


def _cartao(rotulo, valor, nota="", tom="cinza", explica=None):
    r = [rotulo] + ([_dica(explica)] if explica else [])
    return html.Div([
        html.Span(r, className="pg-cartao-r"),
        html.Span(valor, className="pg-cartao-v"),
        html.Span(nota or "", className="pg-cartao-n"),
    ], className=f"pg-cartao pg-tom-{tom}")


def cartao_captura(estado: dict | None, agora: datetime, sit: dict) -> dict:
    if estado is None:
        return {"valor": "nunca rodou", "nota": "abra pelo iniciar.bat",
                "tom": "ambar"}
    if sit["ativa"]:
        return {"valor": "em operação", "tom": "verde",
                "nota": "mercado aberto" if sit["pregao"] else "mercado fechado"}
    feito = _data(estado.get("atualizado_em"))
    if feito is None:
        nota = ""
    elif feito.date() == agora.date():
        nota = "sem sinal " + _quanto((agora - feito).total_seconds())
    else:
        nota = f"sem sinal desde {feito:%d/%m %H:%M}"
    return {"valor": "parada", "nota": nota,
            "tom": "rosa" if sit["pregao"] or estado.get("erro") else "cinza"}


def cartao_mt5(estado: dict | None, sit: dict) -> dict:
    if not sit["ativa"]:
        # o "mt5" gravado é de quando a captura parou: mostrá-lo seria chute
        return {"valor": "—", "nota": "só se sabe com a captura rodando",
                "tom": "cinza"}
    mt5 = estado.get("mt5")
    if mt5 == "conectado":
        conta = (estado.get("conta") or {}).get("login")
        return {"valor": "conectado", "tom": "verde",
                "nota": f"conta {conta}" if conta else ""}
    if mt5 == "sem_conexao":
        desde = _data(estado.get("mt5_desde"))
        return {"valor": "sem conexão", "tom": "ambar",
                "nota": f"desde {desde:%H:%M}" if desde else ""}
    if mt5 == "fechado":
        return {"valor": "fechado", "nota": "abra e faça login", "tom": "rosa"}
    return {"valor": "—", "nota": "", "tom": "cinza"}


def cartao_ultimo(estado: dict | None, agora: datetime) -> dict:
    """O candle de hoje mede a idade; o de ontem nunca é alarme — é só o
    pregão que ainda não abriu (mesma regra 8 de `situacao`)."""
    sit = situacao(estado, agora)
    ultimo = _data((estado or {}).get("ultimo_salvo"))
    if ultimo is None:
        return {"valor": "—", "nota": "nenhum candle gravado", "tom": "cinza"}
    if ultimo.date() != agora.date():
        if not sit["pregao"]:
            nota = "mercado fechado"
        elif agora.time() < SEM_PREGAO_DEPOIS:
            nota = "aguardando a abertura"
        else:
            nota = "sem pregão hoje (feriado?)"
        return {"valor": f"{ultimo:%d/%m %H:%M}", "nota": nota, "tom": "cinza"}
    # o candle das 09:58 só existe depois que fechou, às 09:59
    idade = (agora - ultimo - timedelta(minutes=1)).total_seconds()
    tom = idade_tom(idade, sit["pregao"])
    return {"valor": f"{ultimo:%H:%M}", "tom": tom,
            "nota": _quanto(idade) if sit["pregao"] else "mercado fechado"}


def cartao_lacunas(estado: dict | None, sit: dict) -> dict:
    if estado is None:
        return {"valor": "—", "nota": "", "tom": "cinza"}
    lac = estado.get("lacunas_hoje") or []
    n = lac if isinstance(lac, int) else len(lac)
    if n == 0:
        return {"valor": "0", "nota": "nenhum minuto faltando",
                "tom": "verde" if sit["ativa"] and sit["pregao"] else "cinza"}
    unidade = "minuto" if n == 1 else "minutos"
    return {"valor": str(n), "tom": "ambar",
            "nota": f"{n} {unidade} faltando — a captura recupera sozinha"}


def _banda(tom, texto, acao):
    filhos = [html.Strong(texto, className="pg-alerta-t")]
    if acao:
        filhos.append(html.Span(acao, className="pg-alerta-a"))
    return html.Div(filhos, className=f"pg-alerta pg-alerta-{tom}")


def faixa(estado: dict | None, agora: datetime) -> list:
    """Os 4 cartões de estado e, acima deles, uma frase quando há algo a
    dizer: o problema e o que fazer, ou que o mercado está fechado."""
    sit = situacao(estado, agora)
    c = cartao_captura(estado, agora, sit)
    m = cartao_mt5(estado, sit)
    u = cartao_ultimo(estado, agora)
    lac = cartao_lacunas(estado, sit)
    cartoes = html.Div([
        _cartao("Captura", c["valor"], c["nota"], c["tom"]),
        _cartao("MT5", m["valor"], m["nota"], m["tom"]),
        _cartao("Último candle", u["valor"], u["nota"], u["tom"],
                "O último minuto fechado que entrou no banco. No pregão: "
                "verde até 90 s depois de fechar, âmbar até 3 min, rosa "
                "depois disso (a captura não está gravando)."),
        _cartao("Lacunas hoje", lac["valor"], lac["nota"], lac["tom"],
                "Minutos que o MT5 tem e o banco não. Bom: 0. Uma lacuna "
                "aparece quando a internet ou o MT5 caem; a captura busca "
                "sozinha os minutos que faltam."),
    ], className="pg-cartoes")
    if sit["tom"] in ("rosa", "ambar"):
        banda = _banda(sit["tom"], sit["texto"], sit["acao"])
    elif not sit["pregao"]:
        banda = _banda("cinza", "Mercado fechado",
                       "o gráfico mostra o último pregão gravado")
    elif sit["tom"] == "cinza":
        banda = _banda("cinza", sit["texto"],
                       "o gráfico mostra o último pregão gravado")
    else:
        banda = None
    return ([banda] if banda else []) + [cartoes]


CONFERENCIA_EXPLICA = (
    "Depois do fechamento a captura compara o dia inteiro com o MT5 e "
    "corrige o que estiver diferente. Até ela terminar, o dia de hoje fica "
    "fora da Mineração, do Walk-Forward e da Candidata, que leem o Parquet. "
    "Bom: concluída na mesma noite. Ruim: falhou várias vezes seguidas.")


def _conferencia(conf: dict) -> tuple[str, str, str]:
    """(valor, nota, tom) do cartão da conferência do dia."""
    status = conf.get("status")
    em = _data(conf.get("em"))
    dias = ", ".join(f"{d[8:10]}/{d[5:7]}" for d in conf.get("dias") or []
                     if isinstance(d, str) and len(d) >= 10)
    if status == "concluida":
        return ((f"concluída às {em:%H:%M}" if em else "concluída"),
                f"conferiu {dias}" if dias else "", "verde")
    if status == "falhou":
        # o erro vem cru do DuckDB/MT5, muitas vezes em inglês: fica no (?)
        return ("falhou — tenta de novo em 5 min",
                "detalhes na janela “Dataframe - Captura”", "ambar")
    return "pendente", "roda depois do fechamento", "cinza"


def placar(estado: dict | None) -> list:
    """O que a captura fez hoje. Recuperados e correções recomeçam do zero
    quando a captura reabre — é placar da tela, não auditoria."""
    e = estado or {}

    def n(chave):
        v = e.get(chave)
        return "—" if v is None else f"{int(v):,}".replace(",", ".")
    conf_d = e.get("conferencia") or {}
    conf = (("—", "", "cinza") if estado is None else _conferencia(conf_d))
    explica = CONFERENCIA_EXPLICA
    if conf_d.get("status") == "falhou" and conf_d.get("erro"):
        explica += f" Último erro: {conf_d['erro']}"
    return [
        _cartao("Gravados hoje", n("gravados_hoje"),
                "candles de 1 min salvos no banco", "info",
                "Candles de 1 minuto que a captura salvou hoje. Pregão "
                "completo: cerca de 555 (até 18:24) ou 525 (até 17:54). "
                "Bem abaixo disso com o pregão já encerrado quer dizer que "
                "a captura ficou parada parte do dia."),
        _cartao("Recuperados", n("recuperados_hoje"), "lacunas preenchidas",
                "info",
                "Minutos que a captura buscou depois, por terem faltado na "
                "hora. Bom: 0. Alguns depois de uma queda da internet ou do "
                "MT5 é normal. Muitos: a captura ficou fora do ar."),
        _cartao("Correções da corretora", n("revisados_hoje"),
                "candles que mudaram depois", "info",
                "A corretora às vezes corrige um candle já fechado (um "
                "negócio que chegou atrasado); a captura regrava o candle "
                "com o valor novo. Alguns por dia é normal; dezenas pedem "
                "atenção."),
        _cartao("Conferência do dia", conf[0], conf[1], conf[2], explica),
    ]


def inicio_balde(ts: datetime, tf: str) -> datetime:
    """Começo do candle de 5/15 min que contém `ts` — o mesmo corte que o
    `time_bucket` do banco faz (múltiplos a partir da meia-noite)."""
    passo = MINUTOS_TF[tf]
    ts = ts.replace(second=0, microsecond=0)
    return ts - timedelta(minutes=ts.minute % passo)


def tick_formacao(estado: dict | None, tf: str,
                  balde: list[dict]) -> dict | None:
    """O candle em formação no tempo gráfico da tela, no formato do `tick`.

    Em 5/15 min o candle da tela é o balde inteiro: os M1 já fechados dele
    (`balde`, vindos do banco) mais o minuto em formação. Mandar só o
    minuto em formação apagaria a máxima e a mínima dos minutos anteriores.
    """
    f = (estado or {}).get("em_formacao")
    ts = _data((f or {}).get("ts"))
    if ts is None:
        return None
    inicio = inicio_balde(ts, tf)
    fechados = [b for b in balde if inicio <= b["ts"] < ts] if tf != "M1" else []
    todas = fechados + [f]
    return {"id": "preco", "bar": {
        "time": to_epoch(inicio),
        "open": todas[0]["open"],
        "high": max(b["high"] for b in todas),
        "low": min(b["low"] for b in todas),
        "close": f["close"],
    }}


def bloco():
    """A sub-tela inteira; começa escondida (Estratégias é a padrão)."""
    return html.Div([
        # o pulso só liga com a sub-tela aberta: ninguém lê o estado.json a
        # cada 2 s com o Backtest na frente
        dcc.Interval(id="av-pg-intervalo", interval=2000, disabled=True),
        # o último candle gravado já desenhado: só um candle NOVO refaz a
        # série — o resto entra pelo `tick` e o zoom fica onde está
        dcc.Store(id="av-pg-ultimo"),
        html.Section([
            html.Div([html.H3("Situação da captura", className="panel-title av-sec-titulo")],
                     className="av-sec-head"),
            html.Div(id="av-pg-faixa", className="av-corpo"),
        ], className="panel"),
        html.Section([
            html.Div([
                html.Div([html.H3("WIN$N ao vivo", className="panel-title av-sec-titulo")]),
                html.Div([
                    dcc.RadioItems(
                        id="av-pg-tf", value="M1", className="pg-tf",
                        options=[{"label": "1 min", "value": "M1"},
                                 {"label": "5 min", "value": "M5"},
                                 {"label": "15 min", "value": "M15"}]),
                    html.Button("Voltar para agora", id="av-pg-agora",
                                n_clicks=0, className="btn-ghost btn-sm"),
                    html.Button("Tela cheia", id="av-pg-cheia", n_clicks=0,
                                className="btn-ghost btn-sm"),
                ], className="pg-barra"),
            ], className="av-sec-head pg-grafico-head"),
            html.Div(dash_tvlwc.Tvlwc(id="av-pg-grafico", series=[],
                                      chartOptions=T.CHART_OPTIONS,
                                      height="100%"),
                     id="av-pg-grafico-caixa", className="pg-grafico"),
        ], className="panel"),
        html.Section([
            html.Div([html.H3("Placar do dia",
                              className="panel-title av-sec-titulo"),
                      html.P("O que a captura gravou e corrigiu hoje.",
                             className="av-sec-nota")],
                     className="av-sec-head"),
            html.Div(html.Div(id="av-pg-placar", className="pg-cartoes"),
                     className="av-corpo"),
        ], className="panel"),
    ], id="av-bloco-pregao", className="pg-bloco", style={"display": "none"})
