"""Callbacks da sub-tela Ao vivo › Operação.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

O caminho é o do Pregão, com uma trava a mais: a tela não abre o banco a
cada 2 s. O pulso (`av-op-intervalo`) lê SÓ o estado.json e escreve três
coisas — a situação, o candle em formação (`tick`) e duas marcas:
`av-op-versao` (o `papel.calculado_em`) e `av-op-ultimo` (o último candle
gravado). Quem lê o banco ouve essas marcas, o seletor e os filtros, e
nunca o pulso: com a captura recalculando o papel uma vez por minuto, a
tela relê uma vez por minuto, não trinta. `test_operacao_tela` confere.

Ações (ligar/pausar variante, ligar/desligar portfólio) são as da seção 1
(`core.ao_vivo`), com o segundo clique confirmando. Ids próprios
(`av-op-acao`): repetir o `av-acao` da Estratégias duplicaria ids na
página.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import duckdb
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import db_manager as db
from core import papel_leitura as PL

from . import data as D
from .callbacks_pregao import janela_inicial, juntar, voltar_para_agora
from .components import charts
from .components import operacao_panel as OP

SIMBOLO = "WIN$N"

# o que o pulso pode escrever — tudo sai do estado.json
SAIDAS_DO_PULSO = ("av-op-situacao.children", "av-op-versao.data",
                   "av-op-ultimo.data", "av-op-grafico.tick")

_ACOES = {
    "membro-desligar": (AV.desligar_membro,
                        "variante pausada — as operações dela deixam de "
                        "contar a partir de agora"),
    "membro-ligar": (AV.ligar_membro,
                     "variante ligada — as operações dela voltam a contar"),
    "pf-desligar": (AV.desligar_portfolio,
                    "portfólio desligado — nenhuma operação conta a partir "
                    "de agora"),
    "pf-ligar": (AV.ligar_portfolio,
                 "portfólio ligado — as variantes ligadas voltam a contar"),
}
_CONFIRME = {
    "membro-desligar": "confirme: clique de novo em Confirmar? para PAUSAR a variante",
    "membro-ligar": "confirme: clique de novo em Confirmar? para LIGAR a variante",
    "pf-desligar": "confirme: clique de novo em Confirmar? para DESLIGAR o portfólio",
    "pf-ligar": "confirme: clique de novo em Confirmar? para LIGAR o portfólio",
}


def _visivel(qual, modo) -> bool:
    return qual == OP.SUBTELA and modo == "aovivo"


def pulso(estado: dict | None, visto_versao, visto_ultimo, tf: str,
          base: dict | None, agora: datetime) -> tuple:
    """(situação, versão, último candle, tick) — só a partir do estado.json.

    A versão e o último candle só mudam quando mudam de verdade: escrever o
    mesmo valor dispararia a releitura do banco à toa."""
    papel = (estado or {}).get("papel") or {}
    versao = papel.get("calculado_em")
    ultimo = (estado or {}).get("ultimo_salvo")
    t = OP.tick_operacao(estado, tf or "M1", base, agora)
    return (OP.faixa_situacao(estado, agora),
            no_update if versao is None or versao == visto_versao else versao,
            no_update if ultimo is None or ultimo == visto_ultimo else ultimo,
            t if t is not None else no_update)


def acao(nome, alvo, armado) -> tuple[str | None, str, bool]:
    """Um clique. Devolve (armado, aviso, executou)."""
    chave = f"{nome}:{alvo}"
    if armado != chave:
        return chave, _CONFIRME[nome], False
    funcao, texto = _ACOES[nome]
    try:
        funcao(alvo)
    except ValueError as e:
        return None, str(e), False
    except RuntimeError:
        return None, "banco ocupado, tente de novo", False
    return None, texto, True


def _ler(fn):
    with db.connect(read_only=True, tentativas=4) as con:
        return fn(con)


def montar(pid, armado, filtro_atual, curva_atual) -> tuple:
    """As partes da tela que leem o banco por portfólio. Onze saídas, na
    ordem do callback `desenhar_op`."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)

    def ler(con):
        pfs = PL.portfolios_com_papel(con)
        pf = next((p for p in pfs if p["portfolio_id"] == pid), None)
        if pf is None:
            return pfs, None, None, None, None, None, None, None, None
        res = PL.resumo(con, pid, dia)
        vs = PL.variantes(con, pid, dia)
        ops = PL.operacoes_do_dia(con, pid, dia)
        alertas = PL.alertas(con, pid, dia)
        comp = PL.comparativo(con, pid)
        c_pf = PL.curva_vs_esperado(con, pid)
        faixas = [PL.curva_vs_esperado(con, pid, v["ligacao_id"])["faixa_atual"]
                  for v in vs]
        return pfs, pf, res, vs, ops, alertas, comp, c_pf, faixas

    pfs, pf, res, vs, ops, alertas, comp, c_pf, faixas = _ler(ler)
    if pf is None:
        msg = ("nenhum portfólio ainda — crie um na tela Portfólio e ligue em "
               "Ao vivo › Estratégias" if not pfs else "escolha um portfólio")
        vazio = [html.P(msg, className="av-vazio op-vazio")]
        return ([], [], vazio, [], [], [], [], _opcoes_filtro([]), "todas",
                [], None)

    cab = OP.cabecalho(pf, res)
    botoes = OP.botoes_portfolio(pf, armado)
    nomes = {v["ligacao_id"]: v["nome"] for v in vs}
    vars_ = [{"ligacao_id": v["ligacao_id"], "nome": v["nome"], "cor": v["cor"]}
             for v in vs]
    filtro = filtro_atual if filtro_atual in [str(l) for l in nomes] else "todas"
    curva = curva_atual if curva_atual in nomes else (vs[0]["ligacao_id"]
                                                      if vs else None)
    if not vs:
        kpis = [html.P("Este portfólio não tem variantes — adicione variantes "
                       "nele na tela Portfólio e ligue em Ao vivo › "
                       "Estratégias.", className="av-vazio op-vazio")]
    else:
        esperado = {"diferenca": c_pf.get("diferenca_mediana"),
                    "faixas": faixas, "aviso": c_pf.get("aviso")}
        kpis = OP.kpis(res, ops, esperado, nomes)
    return (cab, botoes, kpis, OP.coluna_variantes(vs, armado, res),
            OP.lista_alertas(alertas), OP.tabela_comparativo(comp), vars_,
            _opcoes_filtro(vars_), filtro,
            [{"label": v["nome"], "value": v["ligacao_id"]} for v in vars_],
            curva)


def _opcoes_filtro(vars_):
    # o valor é texto: "todas" e o id da ligação convivem no mesmo campo
    return ([{"label": "Todas as variantes", "value": "todas"}]
            + [{"label": v["nome"], "value": str(v["ligacao_id"])}
               for v in vars_])


def serie_do_dia(pid, tf, ocultas, agora) -> tuple[list, dict | None]:
    """(series, último candle do banco) do gráfico do dia, com os
    marcadores do papel."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)
    inicio = datetime.combine(dia, datetime.min.time())
    dados = D.candles(SIMBOLO, inicio, inicio + timedelta(hours=23, minutes=59),
                      tf)
    base = dados["candles"][-1] if dados["candles"] else None
    t = OP.tick_operacao(estado, tf, base, agora)
    dados["candles"] = juntar(dados["candles"], t["bar"] if t else None)
    mk, linhas = [], []
    if pid is not None:
        m = _ler(lambda con: PL.marcadores(con, pid, dia))
        mk, linhas = OP.marcadores_tela(m, ocultas, tf)
    return charts.price_series(dados, mk, linhas), base


def register(app):
    @app.callback(
        Output("av-op-situacao", "children"),
        Output("av-op-versao", "data"),
        Output("av-op-ultimo", "data"),
        Output("av-op-grafico", "tick"),
        Input("av-op-intervalo", "n_intervals"),
        State("av-op-versao", "data"),
        State("av-op-ultimo", "data"),
        State("av-op-tf", "value"),
        State("av-op-base", "data"),
    )
    def pulso_op(_n, versao, ultimo, tf, base):
        return pulso(D.estado_captura(), versao, ultimo, tf, base,
                     datetime.now())

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
        Output("av-op-variantes", "children"),
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
        Input("av-op-armado", "data"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
        State("av-op-filtro", "value"),
        State("av-op-curva-variante", "value"),
    )
    def desenhar_op(_versao, pid, _acoes, armado, qual, modo, filtro, curva):
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            return montar(pid, armado, filtro, curva)
        except (duckdb.Error, RuntimeError) as e:
            motivo = ("banco ocupado" if isinstance(e, RuntimeError)
                      else "erro ao ler o banco")
            sem = (no_update,) * 11
            return (*sem[:4], [html.P(
                f"não foi possível ler agora: {motivo} — a tela tenta de novo "
                "no próximo cálculo do papel", className="av-alerta")],
                *sem[5:])

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
            ops = _ler(lambda con: PL.operacoes_do_dia(con, pid, dia, lig))
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        return OP.tabela_operacoes(ops)

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
            c = _ler(lambda con: PL.curva_vs_esperado(
                con, pid, lig if por_variante else None))
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
        armado, aviso, feito = acao(gat["acao"], gat["id"], armado)
        if not feito:
            return armado, no_update, aviso, no_update
        # a sub-tela Estratégias também mostra ligado/pausado: redesenha
        return armado, (versao or 0) + 1, aviso, (versao_av or 0) + 1

    @app.callback(
        Output("av-subtela", "value"),
        Input("av-op-ficha", "n_clicks"),
        prevent_initial_call=True,
    )
    def ver_ficha_op(n):
        if not n:
            raise PreventUpdate
        return "estrategias"

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
        Output("av-op-legenda", "children"),
        Input("av-op-vars", "data"),
        Input("av-op-ocultas", "data"),
    )
    def legenda_op(vars_, ocultas):
        return OP.legenda(vars_ or [], ocultas)

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
