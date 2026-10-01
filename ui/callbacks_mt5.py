"""Callback do botão de sincronização com o MT5.

Em arquivo próprio, no mesmo padrão de callbacks_candidata.py — um lugar
pequeno e focado para o teste de ciclo apontar se algo travar aqui.
"""
from __future__ import annotations

from datetime import datetime

from dash import Input, Output, State, no_update

from core import db_manager as db
from core import mt5_source as src

from . import data as D
from .components import pregao_panel as PP


def motivo_bloqueio() -> str | None:
    """Por que o botão não pode sincronizar agora, ou None.

    Com a captura ativa ela é a dona da gravação: um segundo escritor
    disputaria o banco com ela e não traria nada que ela já não traga."""
    if PP.captura_ativa(D.estado_captura(), datetime.now()):
        return PP.MOTIVO_CAPTURA
    return None


def executar_sincronizacao(ativo):
    if not ativo:
        return no_update, no_update, no_update, no_update, no_update
    # o botão já vem desligado pelo selo, mas o selo só olha a cada 30 s
    motivo = motivo_bloqueio()
    if motivo:
        return motivo, "mt5-sync-status", no_update, no_update, no_update

    try:
        inst = db.load_instrument_yaml(ativo)
        with db.connect_write() as con:
            resultado = src.sincronizar(
                con, ativo, price_decimals=inst.get("price_decimals", 0)
            )
    except src.MT5Error as erro:
        return str(erro), "mt5-sync-status falha", no_update, no_update, no_update
    except Exception as erro:  # noqa: BLE001 - mensagem de tela, nao stack trace
        return (f"erro inesperado: {erro}", "mt5-sync-status falha",
                no_update, no_update, no_update)

    ing = resultado.ingest
    texto = (
        f"ok — {ing.rows_inserted} barras novas, "
        f"{ing.rows_updated} revisadas, "
        f"{resultado.trading_days} pregões, "
        f"{resultado.rollovers} rolagens"
    )
    _, fim = D.span(ativo)
    return texto, "mt5-sync-status ok", fim.date(), fim.date(), fim.date()


def register(app):
    @app.callback(
        Output("mt5-sync-status", "children"),
        Output("mt5-sync-status", "className"),
        # O período (Período > de/até) é calculado UMA VEZ, na subida do
        # servidor (`D.span` em `ui/app.py:build`) — sincronizar não reinicia
        # o processo, então sem isto o calendário ficaria travado na data
        # antiga mesmo com barra nova gravada no banco.
        Output("d-ate", "date"),
        Output("d-ate", "max_date_allowed"),
        Output("d-de", "max_date_allowed"),
        Input("btn-mt5-sync", "n_clicks"),
        State("ativo", "value"),
        prevent_initial_call=True,
    )
    def sincronizar_mt5(n_clicks, ativo):
        return executar_sincronizacao(ativo)
