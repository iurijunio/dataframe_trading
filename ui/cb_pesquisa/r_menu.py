"""Pesquisa: callbacks do menu (abas, faixas, espaço, troca de estratégia e ativo)."""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, no_update

from ..components import controls

from .menu import ENTRADAS_RESUMO, OCULTO, VISIVEL, VISIVEL_GRADE, _COMBOS, _combinacoes, _por_campo, menu_abas, pontinhos, resumos, rotulos_moeda
from .base import CAMPOS_PERFIL
from .ativo import SAIDAS_C4, SAIDAS_C4_STEP, _estrategia_ou_mineracao, _perfil_do_ativo, _periodo_do_ativo


def register(app):
    # ------------------------------------------------------ modal do grafico
    @app.callback(
        Output("modal", "className"),
        Input("btn-chart", "n_clicks"),
        Input("grid-trades", "selectedRows"),
        Input("btn-close", "n_clicks"),
        Input("modal-fundo", "n_clicks"),
        prevent_initial_call=True,
    )
    def abrir_fechar(_a, selecionadas, _c, _d):
        gatilho = ctx.triggered_id
        if gatilho in ("btn-close", "modal-fundo"):
            return "modal"
        if gatilho == "grid-trades" and not selecionadas:
            return no_update
        return "modal aberto"

    # --------------------------- so o bloco do tipo escolhido fica na tela
    @app.callback(
        Output("blk-alvo-pontos", "style"), Output("blk-alvo-atr", "style"),
        Output("blk-alvo-razao", "style"), Output("blk-alvo-pct", "style"),
        Output("blk-stop-pontos", "style"), Output("blk-stop-atr", "style"),
        Output("blk-stop-pct", "style"),
        Input("e-alvo-tipo", "value"), Input("e-stop-tipo", "value"),
    )
    def tipos(alvo, stop):
        # os blocos de ATR são `.grid-2`: "block" no style inline venceria a
        # classe e empilharia período e multiplicador
        return (VISIVEL if alvo == "pontos" else OCULTO,
                VISIVEL_GRADE if alvo == "atr" else OCULTO,
                VISIVEL if alvo == "multiplicador" else OCULTO,
                VISIVEL if alvo == "percentual" else OCULTO,
                OCULTO if stop in ("atr", "percentual") else VISIVEL,
                VISIVEL_GRADE if stop == "atr" else OCULTO,
                VISIVEL if stop == "percentual" else OCULTO)

    # ------------------------------------------------- backtest ou mineração
    @app.callback(
        Output("painel-backtest", "style"), Output("painel-mineracao", "style"),
        Output("painel-wfa", "style"), Output("painel-candidata", "style"),
        Output("painel-estrategias", "style"), Output("painel-portfolio", "style"),
        Output("painel-aovivo", "style"),
        Output("acao-backtest", "style"), Output("sec-mineracao", "style"),
        Output("sidebar", "style"), Output("mine-bloco-varredura", "style"),
        Output("mine-bloco-busca", "style"),
        Input("modo", "value"), Input("mine-subtela", "value"),
    )
    def modo(qual, subtela):
        """Três atividades diferentes, não três abas do mesmo painel.

        Mineração: existe região boa no espaço? Milhares de conjuntos, nuvem
        e ranking (subtela Varredura). A subtela Backtest abre UM conjunto
        — curva de capital, trade a trade — para ver se a estratégia faz o
        que você desenhou.
        Walk-Forward: o meu PROCESSO de escolher parâmetro funciona? Aqui a
        combinação muda a cada janela, e o que se vê é a curva que o
        otimizador nunca enxergou. Misturar as três na mesma tela era o que
        confundia.
        """
        # flex, nao block: `display:block` sobrescreve o `display:flex` da
        # classe .modo-bloco e os paineis filhos perdem a altura - foi o que
        # deixava a tabela de mineracao invisivel, com altura zero.
        BLOCO = {"display": "flex"}
        v = lambda cond: BLOCO if cond else OCULTO
        # A barra lateral inteira sai no Walk-Forward E na Candidata: nos
        # dois os parâmetros não são escolhidos à mão. No WFA eles MUDAM a
        # cada janela, escolhidos pela inteligência de seleção; na Candidata
        # vêm do walk-forward salvo escolhido no topo do próprio painel.
        # Deixar os campos da barra lateral na tela convidaria a editá-los
        # achando que mudam alguma coisa.
        mineracao = qual == "mineracao"
        backtest = mineracao and subtela == "backtest"
        return (v(backtest), v(mineracao), v(qual == "wfa"),
                v(qual == "candidata"), v(qual == "estrategias"),
                v(qual == "portfolio"), v(qual == "aovivo"),
                VISIVEL if backtest else OCULTO,
                VISIVEL if mineracao and not backtest else OCULTO,
                # BLOCK, e não flex: a barra lateral é um <aside> comum com
                # largura fixa. Devolvê-la como flex a transformava em
                # container de LINHA, e as seções (Período, Estratégia,
                # Parâmetros, Execução) se enfileiravam na horizontal — só a
                # primeira cabia, e o resto sumia no corte do overflow.
                OCULTO if qual in ("wfa", "candidata", "estrategias", "portfolio",
                            "aovivo")
                else {"display": "block"},
                v(mineracao and subtela not in ("backtest", "busca")),
                v(mineracao and subtela == "busca"))

    # ---------------------------- menu: aba visível, pontinho e resumos
    # Único dono de `menu-aba`: trocar de estratégia ou de ativo (quem
    # reconstrói `params-body`) não mexe na aba escolhida.
    app.callback(
        Output("menu-aba", "value"), Output("menu-aba", "options"),
        *[Output({"type": "menu-pane", "aba": a}, "style")
          for a in controls.ABAS_MENU],
        Output({"type": "gaveta", "g": "filtro-mineracao"}, "style"),
        Input("menu-aba", "value"),
        Input("modo", "value"), Input("mine-subtela", "value"),
    )(menu_abas)

    app.callback(
        Output("menu-aba", "className"),
        Input({"type": "opt-on", "p": ALL}, "value"),
        State({"type": "opt-on", "p": ALL}, "id"),
        Input("modo", "value"), Input("mine-subtela", "value"),
    )(pontinhos)

    app.callback(
        [Output({"type": "gaveta-resumo", "g": g}, "children")
         for g in controls.GRUPOS_GAVETA],
        [Input(i, p) for i, p in ENTRADAS_RESUMO],
    )(resumos)

    # A curva de capital é desenhada com a subtela Backtest escondida (o
    # primeiro `rodar` e o clique numa linha da Varredura): sem largura, ela
    # ficava espremida. Ao aparecer, é enquadrada de novo — o nonce muda a
    # cada vez, senão o componente ignoraria o comando repetido. Espera o
    # painel ficar visível: quem o mostra é `modo`, no servidor.
    app.clientside_callback(
        """function (qual, sub) {
            if (qual === 'mineracao' && sub === 'backtest') {
                var tentativas = 0;
                var enquadrar = function () {
                    var p = document.getElementById('painel-backtest');
                    if (p && p.offsetParent !== null) {
                        window.dash_clientside.set_props('chart-capital',
                            {timeScaleAction: {action: 'fitContent',
                                               nonce: Date.now()}});
                    } else if (tentativas++ < 40) {
                        setTimeout(enquadrar, 50);
                    }
                };
                setTimeout(enquadrar, 50);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("painel-backtest", "role"),
        Input("modo", "value"), Input("mine-subtela", "value"),
    )

    # ---- ou o valor fixo, ou a faixa de/passo/até - nunca os dois na tela
    @app.callback(
        Output({"type": "optrow", "p": ALL}, "style"),
        Output({"type": "valwrap", "p": ALL}, "style"),
        Output({"type": "opt-on", "p": ALL}, "style"),
        Input({"type": "opt-on", "p": ALL}, "value"),
        Input("modo", "value"), Input("mine-subtela", "value"),
    )
    def faixas(ligados, qual, subtela):
        minerando = qual == "mineracao" and subtela == "varredura"
        # na subtela Backtest não existe faixa nem interruptor: só o valor
        marcar = [bool(v) and minerando for v in ligados]
        return ([VISIVEL if m else OCULTO for m in marcar],
                [OCULTO if m else VISIVEL for m in marcar],
                [VISIVEL if minerando else OCULTO] * len(ligados))

    # -------------------------------------- tamanho do espaco de mineracao
    @app.callback(
        Output("espaco-busca", "children"),
        Input({"type": "opt-on", "p": ALL}, "value"),
        Input({"type": "opt", "p": ALL, "k": ALL}, "value"),
        State({"type": "opt-on", "p": ALL}, "id"),
        State({"type": "opt", "p": ALL, "k": ALL}, "id"),
    )
    def espaco(ligados, faixas, ids_on, ids_faixa):
        campos = _por_campo(ids_faixa, faixas)
        for ident, v in zip(ids_on, ligados):
            campos.setdefault(ident["p"], {})["on"] = bool(v)
        marcados = [p for p, r in campos.items() if r.get("on")]
        if not marcados:
            return "nenhum parâmetro marcado para minerar"
        n = _combinacoes(campos)
        _COMBOS["n"] = n     # lido por `pode_minerar`
        return (f"{len(marcados)} parâmetro(s) · "
                f"{n:,}".replace(",", ".") + " combinações na varredura")

    # ------------------------- trocar estratégia / carregar mineração salva
    @app.callback(
        [Output("estrategia", "value"),
         Output("mine-carregar", "value"),
         Output("params-body", "children"),
         Output("estrategia-nota", "children"),
         Output("grid-mine", "rowData", allow_duplicate=True),
         Output("scatter", "figure", allow_duplicate=True),
         Output("cards", "children", allow_duplicate=True),
         Output("grid-trades", "rowData", allow_duplicate=True),
         Output("chart-capital", "series", allow_duplicate=True),
         Output({"type": "val", "p": ALL}, "value", allow_duplicate=True),
         Output({"type": "opt", "p": ALL, "k": ALL}, "value"),
         Output({"type": "opt-on", "p": ALL}, "value"),
         Output("mine-info", "children", allow_duplicate=True),
         Output("wf-treino", "value"), Output("wf-teste", "value"),
         Output("wf-passo", "value"), Output("wf-holdout", "value")]
        + [Output(cid, "value", allow_duplicate=True) for cid, _ in CAMPOS_PERFIL]
        # o `step` de stop, alvo e trailing ao carregar uma mineração salva;
        # duplica o de `aplicar_perfil_do_ativo` (ids específicos)
        + [Output(ident, prop, allow_duplicate=True)
           for ident, prop, _chave in SAIDAS_C4_STEP],
        Input("estrategia", "value"),
        Input("mine-carregar", "value"),
        Input("ativo", "value"),
        Input("arranque", "n_intervals"),
        State({"type": "val", "p": ALL}, "id"),
        State({"type": "opt", "p": ALL, "k": ALL}, "id"),
        State({"type": "opt-on", "p": ALL}, "id"),
        prevent_initial_call=True,
    )
    def estrategia_ou_mineracao(nome, run_id, simbolo, _arranque, ids_val,
                                ids_faixa, ids_on):
        """Único dono de `estrategia` e `mine-carregar`: um mexe no outro.

        Eram dois callbacks — trocar a estratégia limpava o seletor, carregar
        do seletor trocava a estratégia — e cada um era Input do outro. O
        Dash retém um callback enquanto um Input dele é Output de outro
        pendente; se os dois disparassem juntos, os dois esperariam para
        sempre, sem erro nenhum (foi assim que a barra do walk-forward
        congelou). Um callback só nunca espera por si mesmo: o renderer
        desconta dos Inputs as próprias Outputs, e escrever `estrategia`
        daqui não o dispara de novo.

        O `ativo` entra aqui pelo mesmo motivo: as faixas dos parâmetros vêm
        da ficha dele, e um segundo dono de `params-body` reabriria a corrida.
        """
        return _estrategia_ou_mineracao(ctx.triggered_id, nome, run_id,
                                        simbolo, ids_val, ids_faixa, ids_on)

    # ------------------- perfil padrao do ativo preenche a camada 4
    @app.callback(
        Output("e-ent-ini", "value", allow_duplicate=True),
        Output("e-ent-fim", "value", allow_duplicate=True),
        Output("e-fechamento", "value", allow_duplicate=True),
        Output("e-corretagem", "value", allow_duplicate=True),
        Output("e-emolumentos", "value", allow_duplicate=True),
        Output("e-slippage", "value", allow_duplicate=True),
        *[Output(ident, prop, allow_duplicate=True)
          for ident, prop, _chave in SAIDAS_C4],
        Input("ativo", "value"),
        prevent_initial_call=True,
    )
    def aplicar_perfil_do_ativo(simbolo):
        """Único callback da camada 4 disparado pelo ativo: horários e custos
        do perfil padrão, e stop, alvo e trailing (`_camada4_do_ativo`)."""
        return _perfil_do_ativo(simbolo)

    # ------------------------- o calendário segue a base do ativo escolhido
    @app.callback(
        Output("d-de", "date", allow_duplicate=True),
        Output("d-de", "min_date_allowed", allow_duplicate=True),
        Output("d-de", "max_date_allowed", allow_duplicate=True),
        Output("d-ate", "date", allow_duplicate=True),
        Output("d-ate", "min_date_allowed", allow_duplicate=True),
        Output("d-ate", "max_date_allowed", allow_duplicate=True),
        Input("ativo", "value"),
        prevent_initial_call=True,
    )
    def periodo_do_ativo(simbolo):
        return _periodo_do_ativo(simbolo)

    @app.callback(
        Output({"type": "moeda-c4", "i": ALL}, "children"),
        Input("ativo", "value"),
    )
    def rotulos_moeda_c4(simbolo):
        return rotulos_moeda(simbolo, len(ctx.outputs_list))
