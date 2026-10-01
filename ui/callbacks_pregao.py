"""Callbacks do serviço de captura na tela: o selo do topo (todas as telas)
e o calendário do Backtest depois da conferência do dia.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6.
Os dois só ouvem o `captura-intervalo` (30 s) — nenhum escreve algo que
outro callback ouça como Input, então não há como fechar ciclo.
"""
from __future__ import annotations

from datetime import datetime

from dash import Input, Output, State, no_update

from . import data as D
from .components import pregao_panel as PP


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
