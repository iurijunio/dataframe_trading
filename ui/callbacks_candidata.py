"""Callbacks da tela Candidata.

Em arquivo próprio: `ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são
do walk-forward. Arquivo focado é o que permite o teste de ciclo apontar
para um lugar pequeno quando algo trava.
"""

from __future__ import annotations

from dash import Input, Output, no_update

from core import candidata, wfa, wfa_store

from .components import candidata_panel as CP


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

    @app.callback(
        Output("cand-blocos", "children"),
        Input("cand-wfa", "value"),
    )
    def cand_blocos(wfa_id):
        if not wfa_id:
            return CP.vazio("escolha um walk-forward salvo para analisar")
        d = wfa_store.detalhes(int(wfa_id)) or {}
        capital = d.get("capital")
        if capital is None:
            return CP.vazio("este walk-forward foi salvo antes desta tela: "
                            "não tem capital nem perfil gravados. Rode e "
                            "salve o walk-forward de novo para analisá-lo.")
        trades = wfa_store.trades(int(wfa_id))
        # o disjuntor vale até a próxima reotimização, não até o fim dos
        # tempos: o horizonte é o OOS da configuração escolhida. Preferimos
        # os pregões ÚTEIS de verdade (`wfa.pregoes`, o mesmo que o resto da
        # plataforma usa) à aproximação de 21 pregões/mês — a janela OOS real
        # tem 129 a 132 pregões, não os 126 que a conta aproximada dava. Sem
        # `deploy` gravado (registro antigo), caímos na aproximação; e
        # `oos_meses` pode vir `None`, daí o `or 6` antes de multiplicar.
        deploy = d.get("deploy") or {}
        if deploy.get("oos_de") and deploy.get("oos_ate"):
            horizonte = wfa.pregoes(deploy["oos_de"], deploy["oos_ate"])
        else:
            horizonte = int((d.get("oos_meses") or 6) * 21)
        return CP.bloco_robustez(
            candidata.leitura_robustez(trades, capital, horizonte), capital)
