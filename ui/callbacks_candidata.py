"""Callbacks da tela Candidata.

Em arquivo próprio: `ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são
do walk-forward. Arquivo focado é o que permite o teste de ciclo apontar
para um lugar pequeno quando algo trava.
"""

from __future__ import annotations

from dash import Input, Output, no_update

from core import wfa_store


def register(app):
    @app.callback(
        Output("cand-wfa", "options"),
        Input("modo", "value"),
        Input("store-wfa-lista", "data"),
    )
    def cand_opcoes(qual, _lista):
        """Busca só ao entrar no modo — não a cada troca de aba.

        `store-wfa-lista` é o aviso de que um walk-forward foi salvo ou
        excluído (ver `wfa_guardar`/exclusão em `ui/callbacks.py`); sem ele a
        lista só se atualizaria reabrindo o modo.
        """
        if qual != "candidata":
            return no_update
        return [{"label": w["rotulo"], "value": w["wfa_id"]}
                for w in wfa_store.listar()]

    @app.callback(
        Output("cand-resumo", "children"),
        Input("cand-wfa", "value"),
    )
    def cand_resumo(wfa_id):
        if not wfa_id:
            return "escolha um walk-forward salvo"
        d = wfa_store.detalhes(int(wfa_id)) or {}
        return (f"{d.get('strategy', '—')} · {d.get('symbol', '—')} · "
                f"IS{d.get('is_meses')}/OOS{d.get('oos_meses')} · "
                f"{d.get('inteligencia', '—')}")
