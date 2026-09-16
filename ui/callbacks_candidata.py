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
    """O cabeçalho ao lado do seletor, em palavras de quem opera.

    Avisa quando o walk-forward foi salvo com o holdout incluído: a curva
    que a tela analisa contém esses meses.
    """
    base = (f"{d.get('strategy', '—')} · {d.get('symbol', '—')} · "
            f"IS {d.get('is_meses')} meses / OOS {d.get('oos_meses')} meses · "
            f"inteligência {d.get('inteligencia', '—')}")
    return base + (" · holdout incluído" if d.get("holdout") else "")


def _rotulo_curto(w: dict) -> str:
    """Só o que identifica o walk-forward. WFE e janelas positivas já estão
    na aba Walk-Forward, e o holdout aparece no resumo ao lado."""
    quando = w.get("quando")
    data = f" · {quando:%d/%m}" if quando else ""
    return (f"#{w['wfa_id']} · {w.get('nome') or 'sem nome'} · "
            f"IS {w['is_meses']} / OOS {w['oos_meses']}{data}")


def _valor_do_seletor(atual, ids: set, aberto_no_wfa, padrao=None):
    """O que fica selecionado depois de a lista ser refeita — vale para o
    seletor de estratégia e para o de walk-forward.

    - a escolha atual continua valendo enquanto existir;
    - sem escolha (ou com uma que sumiu), herda a da aba Walk-Forward, se
      ela estiver na lista;
    - senão, o padrão (a primeira estratégia, no seletor de estratégia).
    """
    if atual in ids:
        return atual
    if aberto_no_wfa in ids:
        return aberto_no_wfa
    return padrao


def register(app):
    @app.callback(
        Output("cand-estrategia", "options"),
        Output("cand-estrategia", "value"),
        Input("modo", "value"),
        Input("store-wfa-lista", "data"),
        State("cand-estrategia", "value"),
        State("wfa-estrategia", "value"),
    )
    def cand_estrategias(qual, _lista, atual, na_aba_wfa):
        """Só as estratégias que têm walk-forward salvo — as outras abririam
        uma lista vazia. Começa pela estratégia aberta na aba Walk-Forward.

        O valor só é reescrito quando muda: devolver o mesmo valor faria o
        Dash recalcular a tela inteira a cada entrada no modo.
        """
        if qual != "candidata":
            return no_update, no_update
        nomes = wfa_store.estrategias()
        valor = _valor_do_seletor(atual, set(nomes), na_aba_wfa,
                                  padrao=nomes[0] if nomes else None)
        return ([{"label": n, "value": n} for n in nomes],
                no_update if valor == atual else valor)

    @app.callback(
        Output("cand-wfa", "options"),
        Output("cand-wfa", "value"),
        Input("cand-estrategia", "value"),
        Input("store-wfa-lista", "data"),
        State("cand-wfa", "value"),
        State("wfa-salvos", "value"),
    )
    def cand_opcoes(estrategia, _lista, atual, aberto):
        """Os walk-forwards salvos da estratégia escolhida, refeitos também
        quando um é salvo ou excluído na aba Walk-Forward."""
        salvos = wfa_store.listar(estrategia) if estrategia else []
        opcoes = [{"label": _rotulo_curto(w), "value": w["wfa_id"]}
                  for w in salvos]
        valor = _valor_do_seletor(atual, {w["wfa_id"] for w in salvos}, aberto)
        return opcoes, (no_update if valor == atual else valor)

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
        # a perda esperada vale até a próxima reotimização; a contagem de
        # pregões segue a extensão das janelas, igual à aba Walk-Forward
        horizonte = candidata.calcula_horizonte(d)
        de, ate = candidata.limites_oos(d.get("passos"))
        leitura = candidata.leitura_robustez(trades, capital, horizonte,
                                             de=de, ate=ate)
        return CP.bloco_robustez(leitura, capital,
                                 holdout=bool(d.get("holdout")),
                                 de=de, ate=ate)
