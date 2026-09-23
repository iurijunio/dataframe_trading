"""Callback do botão de sincronização com o MT5.

Em arquivo próprio, no mesmo padrão de callbacks_candidata.py — um lugar
pequeno e focado para o teste de ciclo apontar se algo travar aqui.
"""
from __future__ import annotations

from dash import Input, Output, State, no_update

from core import db_manager as db
from core import mt5_source as src


def register(app):
    @app.callback(
        Output("mt5-sync-status", "children"),
        Output("mt5-sync-status", "className"),
        Input("btn-mt5-sync", "n_clicks"),
        State("ativo", "value"),
        prevent_initial_call=True,
    )
    def sincronizar_mt5(n_clicks, ativo):
        if not ativo:
            return no_update, no_update

        try:
            inst = db.load_instrument_yaml(ativo)
            with db.connect_write() as con:
                resultado = src.sincronizar(
                    con, ativo, price_decimals=inst.get("price_decimals", 0)
                )
        except src.MT5Error as erro:
            return str(erro), "mt5-sync-status falha"
        except Exception as erro:  # noqa: BLE001 - mensagem de tela, nao stack trace
            return f"erro inesperado: {erro}", "mt5-sync-status falha"

        ing = resultado.ingest
        texto = (
            f"ok — {ing.rows_inserted} barras novas, "
            f"{ing.rows_updated} revisadas, "
            f"{resultado.trading_days} pregões, "
            f"{resultado.rollovers} rolagens"
        )
        return texto, "mt5-sync-status ok"
