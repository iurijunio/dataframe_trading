"""Callbacks da tela Candidata.

Em arquivo próprio: `ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são
do walk-forward. Arquivo focado é o que permite o teste de ciclo apontar
para um lugar pequeno quando algo trava.
"""

from __future__ import annotations

from dash import Input, Output, State, no_update

from core import candidata, wfa_store

from .components import candidata_panel as CP


def _texto_resumo(d: dict) -> str:
    """O resumo do cabeçalho, extraído para poder ser testado sem o app Dash.

    Os walk-forwards #3 e #8 foram salvos com `holdout=True`: a base incluía
    o holdout lacrado quando a mineração e o WFA rodaram. Isso importa aqui
    porque o recorte de "últimos 12 meses" do bloco 1 (usado sempre que ele
    é o pior — ver `candidata.pior_dos_recortes`) é, na prática, os seis
    meses do holdout mais os seis anteriores: sem avisar, a tela sugeriria
    um número medido em dado nunca visto quando metade do recorte já
    influenciou, indiretamente, quando a mineração parou.
    """
    base = (f"{d.get('strategy', '—')} · {d.get('symbol', '—')} · "
            f"IS{d.get('is_meses')}/OOS{d.get('oos_meses')} · "
            f"{d.get('inteligencia', '—')}")
    return base + (" · holdout incluído" if d.get("holdout") else "")


def register(app):
    @app.callback(
        Output("cand-wfa", "options"),
        Output("cand-wfa", "value"),
        Input("modo", "value"),
        Input("store-wfa-lista", "data"),
        State("cand-wfa", "value"),
    )
    def cand_opcoes(qual, _lista, atual):
        """Busca só ao entrar no modo — não a cada troca de aba.

        `store-wfa-lista` é o aviso de que um walk-forward foi salvo ou
        excluído (ver `wfa_guardar`/exclusão em `ui/callbacks.py`); sem ele a
        lista só se atualizaria reabrindo o modo.

        Também limpa `cand-wfa.value` quando o WFA selecionado saiu da lista
        (foi excluído na aba Walk-Forward enquanto a Candidata ficava aberta
        ao lado): sem isto, o valor antigo continuava selecionado e o
        recálculo dizia "salvo antes desta tela" — mentira, o registro nem
        existe mais.
        """
        if qual != "candidata":
            return no_update, no_update
        opcoes = [{"label": w["rotulo"], "value": w["wfa_id"]}
                 for w in wfa_store.listar()]
        ainda_existe = any(o["value"] == atual for o in opcoes)
        valor = atual if (atual is None or ainda_existe) else None
        return opcoes, valor

    @app.callback(
        Output("cand-resumo", "children"),
        Input("cand-wfa", "value"),
    )
    def cand_resumo(wfa_id):
        if not wfa_id:
            return "escolha um walk-forward salvo"
        d = wfa_store.detalhes(int(wfa_id)) or {}
        return _texto_resumo(d)

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
        # o disjuntor vale até a próxima reotimização: `calcula_horizonte`
        # tira isso do DEPLOY gravado (ou aproxima por oos_meses em registro
        # antigo). `limites_oos` alinha a contagem de pregões com a do WFA —
        # a extensão das janelas reais, não do primeiro ao último trade.
        horizonte = candidata.calcula_horizonte(d)
        de, ate = candidata.limites_oos(d.get("passos"))
        leitura = candidata.leitura_robustez(trades, capital, horizonte,
                                             de=de, ate=ate)
        return CP.bloco_robustez(leitura, capital,
                                 holdout=bool(d.get("holdout")))
