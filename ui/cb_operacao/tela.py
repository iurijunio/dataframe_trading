"""Operação: callbacks do papel (pulso, gráfico, curva, legenda)."""
from __future__ import annotations

import time
from datetime import datetime

import duckdb
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from core import papel_leitura as PL

from .. import data as D
from ..callbacks_pregao import janela_inicial, voltar_para_agora
from ..components import operacao_panel as OP

from .dados import _ler, _visivel, acao, pulso, pulso_ordens
from .montagem import juntar_demo, ler_curva, montar, serie_do_dia


def register(app):
    @app.callback(
        Output("av-op-situacao", "children"),
        Output("av-op-versao", "data"),
        Output("av-op-ultimo", "data"),
        Output("av-op-grafico", "tick"),
        Output("av-op-ord-saude", "children"),
        Output("av-op-ord-chamados", "children"),
        Output("av-op-ord-posicoes", "children"),
        Output("av-op-ord-numeros", "children"),
        Output("av-op-ord-versao", "data"),
        Input("av-op-intervalo", "n_intervals"),
        State("av-op-versao", "data"),
        State("av-op-ultimo", "data"),
        State("av-op-tf", "value"),
        State("av-op-base", "data"),
        State("av-op-ord-versao", "data"),
        State("av-op-vars", "data"),
        State("av-op-portfolio", "value"),
        State("av-op-ord-dados", "data"),
        State("av-op-ord-escondidos", "data"),
        State("av-op-ord-enviados", "data"),
        State("av-op-ord-armado", "data"),
    )
    def pulso_op(_n, versao, ultimo, tf, base, ordens_em, vars_, pid, dados,
                 escondidos, enviados, armado):
        # um pulso só (o teste exige um único ouvinte do intervalo): o
        # papel e as ordens saem da MESMA leitura do estado.json
        estado = D.estado_captura()
        agora = datetime.now()
        return (*pulso(estado, versao, ultimo, tf, base, agora),
                *pulso_ordens(estado, ordens_em, vars_, pid, dados, escondidos,
                              enviados, armado, agora, time.time(),
                              real=D.estado_real()))

    @app.callback(
        Output("av-op-portfolio", "options"),
        Output("av-op-portfolio", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
        Input("av-op-acao-versao", "data"),
        State("av-op-portfolio", "value"),
    )
    def portfolios_op(qual, modo, _v, atual):
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            pfs = _ler(PL.portfolios_com_papel)
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        ops = [{"label": p["nome"] + ("" if p["ligado"] else " (desligado)"),
                "value": p["portfolio_id"]} for p in pfs]
        ids = [p["portfolio_id"] for p in pfs]
        if atual in ids:
            return ops, no_update
        ligados = [p["portfolio_id"] for p in pfs if p["ligado"]]
        return ops, (ligados or ids or [None])[0]

    @app.callback(
        Output("av-op-cabecalho", "children"),
        Output("av-op-botoes", "children"),
        Output("av-op-kpis", "children"),
        Output("av-op-var-cab", "children"),
        Output("av-op-var-lista", "children"),
        Output("av-op-risco", "children"),
        Output("av-op-alertas", "children"),
        Output("av-op-comparativo", "children"),
        Output("av-op-vars", "data"),
        Output("av-op-filtro", "options"),
        Output("av-op-filtro", "value"),
        Output("av-op-curva-variante", "options"),
        Output("av-op-curva-variante", "value"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-acao-versao", "data"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
        # State, não Input: armar um botão só troca o rótulo (`rotulos_op`);
        # o armado entra aqui para um redesenho no meio do caminho não
        # mostrar "Pausar" num botão que já está pedindo confirmação
        State("av-op-armado", "data"),
        State("av-op-filtro", "value"),
        State("av-op-curva-variante", "value"),
    )
    def desenhar_op(_versao, pid, _acoes, qual, modo, armado, filtro, curva):
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            return montar(pid, armado, filtro, curva)
        except (duckdb.Error, RuntimeError) as e:
            motivo = ("banco ocupado" if isinstance(e, RuntimeError)
                      else "erro ao ler o banco")
            sem = (no_update,) * 13
            return (*sem[:6], [html.P(
                f"não foi possível ler agora: {motivo} — a tela tenta de novo "
                "no próximo cálculo do papel", className="av-alerta")],
                *sem[7:])

    @app.callback(
        Output("av-op-operacoes", "children"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-filtro", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def operacoes_op(_versao, pid, filtro, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        lig = None if filtro in (None, "todas") else int(filtro)
        dia = D.dia_do_pregao(D.estado_captura())
        try:
            ops, demo, real = _ler(lambda con: (
                PL.operacoes_do_dia(con, pid, dia, lig),
                PL.operacoes_demo(con, pid, dia),
                PL.operacoes_demo(con, pid, dia, origem="real")))
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        return OP.tabela_operacoes(juntar_demo(juntar_demo(ops, demo), real, "real"))

    @app.callback(
        Output("av-op-curva", "series"),
        Output("av-op-curva-nota", "children"),
        Output("av-op-curva-variante", "disabled"),
        Output("av-op-curva-enquadrar", "data"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-curva-modo", "value"),
        Input("av-op-curva-variante", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def curva_op(_versao, pid, modo_curva, lig, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        por_variante = modo_curva == "variante"
        if por_variante and lig is None:
            return [], "escolha a variante ao lado", False, no_update
        try:
            c = ler_curva(pid, lig if por_variante else None)
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        # poucos pregões ficavam espremidos num canto: enquadra a curva
        # inteira, depois de desenhada (ver o callback do navegador abaixo)
        return (OP.curva_series(c), OP.curva_nota(c), not por_variante,
                time.time())

    @app.callback(
        Output("av-op-grafico", "series"),
        Output("av-op-grafico", "timeScaleAction"),
        Output("av-op-grafico", "visibleLogicalRange"),
        Output("av-op-base", "data"),
        Output("av-op-enquadrar", "data"),
        Input("av-op-ultimo", "data"),
        Input("av-op-versao", "data"),
        Input("av-op-tf", "value"),
        Input("av-subtela", "value"),
        Input("av-op-agora", "n_clicks"),
        Input("av-op-portfolio", "value"),
        Input("av-op-ocultas", "data"),
        Input("modo", "value"),
    )
    def serie_op(_ultimo, _versao, tf, qual, _cliques, pid, ocultas, modo):
        # dados e posição no mesmo callback, como no Pregão: separados, a
        # posição podia chegar antes dos dados e ser desfeita por eles
        quem = ctx.triggered_id
        if quem == "av-op-agora":
            return no_update, voltar_para_agora(), no_update, no_update, no_update
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            series, base = serie_do_dia(pid, tf or "M1", ocultas,
                                        datetime.now())
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        if quem in ("av-op-ultimo", "av-op-versao", "av-op-ocultas"):
            # candle novo, papel novo ou legenda: o usuário pode estar
            # olhando a manhã — a posição fica. Trocar de portfólio (e a
            # escolha automática dele ao abrir a tela) reenquadra.
            return series, no_update, no_update, base, no_update
        janela = janela_inicial(len(series[0]["data"]))
        return series, no_update, janela, base, janela

    @app.callback(
        Output("av-op-armado", "data"),
        Output("av-op-acao-versao", "data"),
        Output("av-op-aviso", "children"),
        Output("av-versao", "data", allow_duplicate=True),
        Input({"type": "av-op-acao", "acao": ALL, "id": ALL}, "n_clicks"),
        State("av-op-armado", "data"),
        State("av-op-acao-versao", "data"),
        State("av-versao", "data"),
        prevent_initial_call=True,
    )
    def acao_op(_cliques, armado, versao, versao_av):
        # botão recém-desenhado chega com n_clicks=0: só clique de verdade
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        posicoes = None
        if gat["acao"] == "envio-desligar":
            posicoes = D.ordens_do_estado(D.estado_captura())["posicoes"]
        elif gat["acao"] == "envio-real-desligar":
            posicoes = D.posicoes_real(D.estado_real())
        armado, aviso, feito = acao(gat["acao"], gat["id"], armado, posicoes)
        if not feito:
            return armado, no_update, aviso, no_update
        # a sub-tela Estratégias também mostra ligado/pausado: redesenha
        return armado, (versao or 0) + 1, aviso, (versao_av or 0) + 1

    @app.callback(
        Output({"type": "av-op-acao", "acao": ALL, "id": ALL}, "children"),
        Output({"type": "av-op-acao", "acao": ALL, "id": ALL}, "className"),
        Input("av-op-armado", "data"),
        prevent_initial_call=True,
    )
    def rotulos_op(armado):
        # sem banco: só "Confirmar?" no botão armado e o rótulo normal nos
        # outros (inclusive o que deixou de estar armado)
        estados = [OP.estado_botao(o["id"]["acao"], o["id"]["id"], armado)
                   for o in ctx.outputs_list[0]]
        return [e[0] for e in estados], [e[1] for e in estados]

    # O botão armado desarma sozinho depois de 5 s: um "Confirmar?"
    # esquecido viraria uma ação por engano no próximo clique, minutos depois.
    app.clientside_callback(
        """function (armado) {
            window._avOpArmado = armado || null;
            if (armado) {
                setTimeout(function () {
                    if (window._avOpArmado === armado) {
                        window._avOpArmado = null;
                        window.dash_clientside.set_props('av-op-armado', {data: null});
                        window.dash_clientside.set_props('av-op-aviso', {children: ''});
                    }
                }, 5000);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-aviso", "role"),
        Input("av-op-armado", "data"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("av-op-ocultas", "data"),
        Input({"type": "av-op-chip", "id": ALL}, "n_clicks"),
        State("av-op-ocultas", "data"),
        prevent_initial_call=True,
    )
    def chip_op(_cliques, ocultas):
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        ocultas = list(ocultas or [])
        lig = gat["id"]
        if lig in ocultas:
            ocultas.remove(lig)
        else:
            ocultas.append(lig)
        return ocultas

    @app.callback(
        Output("av-op-chips", "children"),
        Input("av-op-vars", "data"),
        Input("av-op-ocultas", "data"),
    )
    def legenda_op(vars_, ocultas):
        return OP.chips(vars_ or [], ocultas)

    # Enquadrar de novo um instante depois. A sub-tela nasce escondida: o
    # gráfico ainda tem largura zero quando a primeira posição chega, e ao
    # crescer mantém o espaçamento das barras daquela largura — os candles
    # ficavam espremidos à direita com a metade esquerda vazia.
    app.clientside_callback(
        """function (janela) {
            if (janela) {
                // + 0,001: o Dash ignora um valor igual ao que o servidor
                // acabou de mandar, e o gráfico não reaplicaria
                setTimeout(function () {
                    window.dash_clientside.set_props('av-op-grafico',
                        {visibleLogicalRange: {from: janela.from,
                                               to: janela.to + 0.001}});
                }, 350);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-grafico-caixa", "role"),
        Input("av-op-enquadrar", "data"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        """function (nonce) {
            if (nonce) {
                setTimeout(function () {
                    window.dash_clientside.set_props('av-op-curva',
                        {timeScaleAction: {action: 'fitContent', nonce: nonce}});
                }, 350);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-curva-caixa", "role"),
        Input("av-op-curva-enquadrar", "data"),
        prevent_initial_call=True,
    )

    # As abas Operações | Diário | Avaliação: as três ficam montadas e só a
    # classe do contêiner diz qual aparece (dcc.Tabs desmontaria a fechada,
    # recriaria a curva e perderia a rolagem). Ao abrir a Avaliação a curva
    # é enquadrada de novo: desenhada com a aba fechada, as barras ficavam
    # espremidas. Só navegador: não lê o banco nem ouve o pulso.
    app.clientside_callback(
        """function (aba) {
            var qual = aba || 'operacoes';
            if (qual === 'avaliacao') {
                setTimeout(function () {
                    window.dash_clientside.set_props('av-op-curva',
                        {timeScaleAction: {action: 'fitContent',
                                           nonce: Date.now()}});
                }, 50);
            }
            return 'op-abas-corpo op-aba-' + qual;
        }""",
        Output("av-op-abas", "className"),
        Input("av-op-aba", "value"),
    )

    app.clientside_callback(
        """function (n) {
            if (n) {
                var caixa = document.getElementById('av-op-grafico-caixa');
                if (caixa && caixa.requestFullscreen) { caixa.requestFullscreen(); }
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-grafico-caixa", "title"),
        Input("av-op-cheia", "n_clicks"),
        prevent_initial_call=True,
    )
