"""Situação do serviço de captura, como a tela a mostra.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6–7.

Só desenha: quem lê o `estado.json` é `ui/data.py`. Por isso `situacao`
recebe o estado e a hora — dá para testar cada frase com um dicionário
montado à mão. Nesta parte há só o selo do topo; a sub-tela Pregão
reaproveita a mesma `situacao`.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from dash import html

from core import captura as CAP

# O serviço publica a cada volta (segundos no pregão, ~30 s fora dele).
# Um minuto sem publicar é processo morto ou travado, não volta lenta.
FRESCO = timedelta(seconds=60)
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
    return idade is not None and idade < FRESCO


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
