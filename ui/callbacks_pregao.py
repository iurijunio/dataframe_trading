"""Callbacks do serviço de captura na tela: o selo do topo (todas as telas),
o calendário do Backtest depois da conferência do dia e a sub-tela
Ao vivo › Pregão.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6.
O selo e o calendário só ouvem o `captura-intervalo` (30 s). Na Pregão o
caminho é de mão única: pulso (2 s) → `av-pg-ultimo` → série; nenhum deles
ouve o que a série escreve, então não há como fechar ciclo.

A regra que segura o zoom: só a `serie` escreve `series` (refaz o gráfico),
e só quando um candle novo foi gravado ou o tempo gráfico mudou. O pulso
mexe apenas no `tick`, que atualiza a última barra no lugar.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from dash import Input, Output, State, ctx, no_update

from . import data as D
from . import theme as T
from .components import charts
from .components import pregao_panel as PP

SIMBOLO = "WIN$N"
OCULTO = {"display": "none"}
BLOCO = {"display": "flex"}


def calendario(estado: dict | None, vista: str | None, simbolo: str):
    """(d-ate.date, d-ate.max, d-de.max, conferência vista).

    O período do Backtest é montado uma vez, na subida do servidor; a
    conferência do dia grava barras novas sem reiniciar nada. Só mexe quando
    a conferência muda — a cada 30 s seria desfazer a data que o usuário
    escolheu."""
    em = ((estado or {}).get("conferencia") or {}).get("em")
    if em is None or em == vista or not simbolo:
        return (no_update,) * 4
    _, fim = D.span(simbolo)
    if vista is None:
        # primeira olhada desde que a página abriu: a data escolhida fica,
        # só passa a deixar escolher até o último dia gravado
        return no_update, fim.date(), fim.date(), em
    return fim.date(), fim.date(), fim.date(), em


def register(app):
    @app.callback(
        Output("captura-selo", "children"),
        Output("captura-selo", "className"),
        Output("captura-selo", "style"),
        Output("captura-selo", "title"),
        Output("btn-mt5-sync", "disabled"),
        Output("btn-mt5-sync", "title"),
        Input("captura-intervalo", "n_intervals"),
    )
    def selo_captura(_n):
        sit = PP.situacao(D.estado_captura(), datetime.now())
        filhos, classe, estilo = PP.selo(sit)
        if sit["ativa"]:
            botao = f"Desligado: {PP.MOTIVO_CAPTURA}"
        else:
            botao = "Busca no MT5 os candles que faltam no banco"
        return filhos, classe, estilo, PP.dica(sit), sit["ativa"], botao

    @app.callback(
        Output("d-ate", "date", allow_duplicate=True),
        Output("d-ate", "max_date_allowed", allow_duplicate=True),
        Output("d-de", "max_date_allowed", allow_duplicate=True),
        Output("captura-conferencia-vista", "data"),
        Input("captura-intervalo", "n_intervals"),
        State("captura-conferencia-vista", "data"),
        State("ativo", "value"),
        prevent_initial_call=True,
    )
    def calendario_captura(_n, vista, simbolo):
        return calendario(D.estado_captura(), vista, simbolo)

    register_pregao(app)


# ------------------------------------------------------------ sub-tela Pregão
def tick_agora(estado: dict | None, tf: str, agora: datetime) -> dict | None:
    """O candle em formação pronto para o `tick`, ou None.

    Com a captura parada o `em_formacao` gravado é um retrato velho: ficaria
    desenhado como se o mercado estivesse parado naquele preço. Levanta
    RuntimeError se o banco estiver ocupado (só em 5/15 min)."""
    if not PP.captura_ativa(estado, agora):
        return None
    f = (estado or {}).get("em_formacao")
    ts = PP._data((f or {}).get("ts"))
    if ts is None:
        return None
    balde = ([] if tf == "M1"
             else D.m1_fechados(SIMBOLO, PP.inicio_balde(ts, tf), ts))
    return PP.tick_formacao(estado, tf, balde)


def juntar(candles: list[dict], barra: dict | None) -> list[dict]:
    """A série do banco com o candle em formação no fim.

    Escrever `series` substitui os dados inteiros — sem isto o candle em
    formação sumiria a cada minuto novo até o preço mexer de novo (um
    `tick` igual ao anterior não é reaplicado)."""
    if barra is None:
        return candles
    if candles and candles[-1]["time"] == barra["time"]:
        return candles[:-1] + [barra]
    if not candles or barra["time"] > candles[-1]["time"]:
        return candles + [barra]
    return candles          # mais velho que o último gravado: nada a juntar


def serie_do_dia(estado: dict | None, tf: str, agora: datetime) -> list[dict]:
    dia = datetime.combine(D.dia_do_pregao(estado), datetime.min.time())
    dados = D.candles(SIMBOLO, dia, dia + timedelta(hours=23, minutes=59), tf)
    try:
        t = tick_agora(estado, tf, agora)
    except RuntimeError:
        t = None
    dados["candles"] = juntar(dados["candles"], t["bar"] if t else None)
    return charts.price_series(dados)


def voltar_para_agora() -> dict:
    """Comando do gráfico para mostrar o candle mais novo, sem mexer no zoom.

    Sem animação de propósito: o `scrollToRealTime` da biblioteca anda
    quadro a quadro e, com a janela sem desenhar (minimizada, atrás de
    outra), a animação expira sem chegar. A posição é a mesma folga à
    direita do tema. O `nonce` muda a cada pedido — o gráfico ignora um
    comando igual ao anterior."""
    return {"action": "scrollToPosition", "animated": False,
            "position": T.CHART_OPTIONS["timeScale"]["rightOffset"],
            "nonce": time.time()}


# Ao abrir ou trocar o tempo gráfico: as últimas 2 h em 1 min; o dia
# inteiro em 5 e 15 min (até 112 barras). Menos de 40 de largura deixaria
# 13 candles de 15 min do tamanho de um dedo.
JANELA_MAX = 120
JANELA_MIN = 40


def janela_inicial(n: int) -> dict:
    """Intervalo visível (em número de barra) que termina no candle mais
    novo com a folga do tema à direita."""
    folga = T.CHART_OPTIONS["timeScale"]["rightOffset"]
    fim = n - 1 + folga
    inicio = min(max(0, n - JANELA_MAX), fim - JANELA_MIN)
    return {"from": inicio, "to": fim}


def register_pregao(app):
    @app.callback(
        Output("av-bloco-estrategias", "style"),
        Output("av-bloco-pregao", "style"),
        Output("av-pg-intervalo", "disabled"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def subtela(qual, modo):
        pregao = qual == "pregao"
        # o pulso de 2 s só roda com a sub-tela na frente
        return (OCULTO if pregao else BLOCO, BLOCO if pregao else OCULTO,
                not (pregao and modo == "aovivo"))

    @app.callback(
        Output("av-pg-faixa", "children"),
        Output("av-pg-placar", "children"),
        Output("av-pg-ultimo", "data"),
        Output("av-pg-grafico", "tick"),
        Input("av-pg-intervalo", "n_intervals"),
        State("av-pg-ultimo", "data"),
        State("av-pg-tf", "value"),
    )
    def pulso(_n, visto, tf):
        estado = D.estado_captura()
        agora = datetime.now()
        ultimo = (estado or {}).get("ultimo_salvo")
        try:
            t = tick_agora(estado, tf or "M1", agora)
        except RuntimeError:
            t = None        # banco ocupado: o candle em formação espera 2 s
        return (PP.faixa(estado, agora), PP.placar(estado),
                no_update if ultimo == visto else ultimo,
                t if t is not None else no_update)

    @app.callback(
        Output("av-pg-grafico", "series"),
        Output("av-pg-grafico", "timeScaleAction"),
        Output("av-pg-grafico", "visibleLogicalRange"),
        Input("av-pg-ultimo", "data"),
        Input("av-pg-tf", "value"),
        Input("av-subtela", "value"),
        Input("av-pg-agora", "n_clicks"),
    )
    def serie(_ultimo, tf, qual, _cliques):
        # Um callback só escreve dados e posição: o gráfico aplica `series`
        # antes dos comandos de posição quando chegam juntos. Separados, a
        # posição podia chegar antes dos dados novos e ser desfeita por eles
        # (trocar `series` devolve a posição que estava, em número de barra).
        quem = ctx.triggered_id
        if quem == "av-pg-agora":
            return no_update, voltar_para_agora(), no_update
        if qual != "pregao":
            return no_update, no_update, no_update   # escondida
        series = serie_do_dia(D.estado_captura(), tf or "M1", datetime.now())
        if quem == "av-pg-ultimo":
            # um candle novo gravado não mexe na posição: o usuário pode
            # estar olhando a manhã
            return series, no_update, no_update
        # Trocou o tempo gráfico (ou abriu a sub-tela): a posição guardada é
        # do tempo anterior — 190 barras de 1 min viram 13 de 15 min
        # espremidas num canto. Abre na janela padrão, terminando agora.
        return series, no_update, janela_inicial(len(series[0]["data"]))

    app.clientside_callback(
        """function (n) {
            if (n) {
                var caixa = document.getElementById('av-pg-grafico-caixa');
                if (caixa && caixa.requestFullscreen) { caixa.requestFullscreen(); }
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-pg-grafico-caixa", "title"),
        Input("av-pg-cheia", "n_clicks"),
        prevent_initial_call=True,
    )
