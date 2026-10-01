"""Callbacks da tela Portfólio — portfólios, membros, correlação e risco."""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, html, no_update

from core import portfolio as P
from core import variantes as V

from .components import portfolio_panel as PP

_CAPITAL_PADRAO = "10000"


def _parse_capital(texto) -> float | None:
    """Aceita "200000", "200.000,50" (formato BR) ou "200000.50" - digitado
    livre, sem os botões de +/- que o navegador desenha em <input
    type=number> (achado real do usuário: queria digitar direto, sem
    stepper)."""
    if texto is None:
        return None
    limpo = str(texto).strip().replace("R$", "").replace(" ", "")
    if not limpo:
        return None
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


def _fmt_capital(v: float) -> str:
    return f"{v:.0f}" if v == int(v) else str(v)


def register(app):
    @app.callback(
        Output("pf-lista", "children"),
        Input("modo", "value"),
        Input("pf-btn-criar", "n_clicks"),
        State("pf-novo-nome", "value"),
        prevent_initial_call=False,
    )
    def listar_portfolios(modo, n_criar, nome_novo):
        if ctx.triggered_id == "pf-btn-criar" and (nome_novo or "").strip():
            P.criar(nome_novo.strip())
        if modo != "portfolio":
            return no_update
        return [PP.cartao_portfolio(p["portfolio_id"], p["nome"], p["n_membros"])
                for p in P.listar()]

    @app.callback(
        Output("pf-add-variante", "options"),
        Input("modo", "value"),
    )
    def opcoes_variantes(modo):
        if modo != "portfolio":
            return no_update
        return [{"label": f"{v['nome']} ({v['estrategia']})",
                 "value": v["variante_id"]} for v in V.listar()]

    @app.callback(
        Output("pf-detalhe", "style"),
        Output("pf-detalhe-titulo", "children"),
        Output("pf-capital", "value"),
        Output("pf-capital-msg", "children"),
        Output("pf-curva", "figure"),
        Output("pf-tabela", "children"),
        Output("pf-simulacao", "children"),
        Output("pf-membros", "children"),
        Output("pf-heatmap", "children"),
        Output("pf-risco", "children"),
        Output("pf-avisos", "children"),
        Output("store-portfolio-aberto", "data"),
        Input({"type": "pf-cartao", "portfolio_id": ALL}, "n_clicks"),
        Input("pf-btn-add", "n_clicks"),
        Input({"type": "pf-btn-remover", "variante_id": ALL}, "n_clicks"),
        Input("pf-btn-salvar-capital", "n_clicks"),
        State("pf-add-variante", "value"),
        State("pf-capital", "value"),
        State("store-portfolio-aberto", "data"),
        prevent_initial_call=True,
    )
    def abrir_detalhe(_cliques_cartao, _add, _remover, _salvar_capital,
                       variante_add, capital_digitado, pid):
        # Input de padrao-matching (ALL) dispara so por um cartao NOVO
        # aparecer no DOM (n_clicks=0, nunca clicado de verdade) - sem o
        # `valor_disparo`, criar um segundo portfolio "roubava" a tela de
        # quem estava vendo outro (achado na revisao do agente).
        gatilho = ctx.triggered_id
        valor_disparo = ctx.triggered[0]["value"] if ctx.triggered else None
        aviso_remover = None
        if (isinstance(gatilho, dict) and gatilho.get("type") == "pf-cartao"
                and valor_disparo):
            pid = gatilho["portfolio_id"]
        elif gatilho == "pf-btn-add" and pid is not None and variante_add:
            P.adicionar_variante(pid, variante_add)
        elif (isinstance(gatilho, dict) and gatilho.get("type") == "pf-btn-remover"
              and valor_disparo and pid is not None):
            try:
                P.remover_variante(pid, gatilho["variante_id"])
            except ValueError as e:
                aviso_remover = str(e)
            except RuntimeError:
                aviso_remover = "banco ocupado, tente de novo"
        elif isinstance(gatilho, dict) and not valor_disparo:
            # cartao/botao novo so apareceu no DOM - nao e navegacao nenhuma,
            # so re-renderiza o que ja estava aberto (ou nada, se pid None)
            pass

        if pid is None:
            return ({"display": "none"}, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update, no_update,
                    no_update, no_update, pid)

        capital_msg = None
        if gatilho == "pf-btn-salvar-capital" and valor_disparo:
            try:
                P.definir_capital(pid, _parse_capital(capital_digitado))
                capital_msg = "capital salvo."
            except (ValueError, TypeError):
                capital_msg = "capital inválido - digite um valor positivo."

        p_atual = next((p for p in P.listar() if p["portfolio_id"] == pid), None)
        nome = p_atual["nome"] if p_atual else ""
        if capital_msg == "capital inválido - digite um valor positivo.":
            capital_valor = capital_digitado
        elif p_atual and p_atual["capital"] is not None:
            capital_valor = _fmt_capital(p_atual["capital"])
        else:
            capital_valor = _CAPITAL_PADRAO
        ms = P.membros(pid)

        curvas = P.curvas(pid)
        series = curvas["series"]
        linhas_membros = [
            PP.linha_membro(
                m["variante_id"], m["nome"], m["estrategia"],
                m["sem_plano_ativo"],
                resumo=_resumo_membro(series.get(m["nome"])),
                gravado_mesmo_assim=m.get("gravado_mesmo_assim", False),
                pendencias=m.get("pendencias"))
            for m in ms
        ] or [html.P("nenhuma variante neste portfólio ainda.")]

        r = P.correlacao(pid)
        # "sem plano ativo" já sai de correlacao() E de curvas() para o
        # mesmo membro - junta sem duplicar a linha na lista de avisos
        avisos_txt = list(dict.fromkeys(
            ([aviso_remover] if aviso_remover else [])
            + r["avisos"] + curvas["avisos"]))
        avisos = html.Ul([html.Li(a) for a in avisos_txt]) if avisos_txt else None

        capital_definido = bool(p_atual) and p_atual["capital"] is not None
        linhas_tabela = [
            (nome_m, res, False)
            for nome_m, res in P.resumo_membros(pid).items()
        ]
        resumo_pf = P.resumo(pid)
        if resumo_pf is not None:
            linhas_tabela.append((
                "Portfólio (combinado)",
                {"capital_inicial": p_atual["capital"], **resumo_pf},
                True))
        tabela = PP.tabela_comparativa(linhas_tabela,
                                       capital_definido=capital_definido)
        simulacao = PP.card_simulacao(P.simulacao_capital(pid))

        return ({"display": "block"}, nome, capital_valor, capital_msg,
                PP.figura_curva(series, curvas["combinada"]), tabela,
                simulacao, linhas_membros,
                PP.heatmap(r["variantes"], r["matriz"]),
                PP.card_risco(r["risco_diario"]), avisos, pid)

    def _resumo_membro(dados: dict | None) -> dict | None:
        if not dados or not dados["pontos"]:
            return None
        return {"retorno": dados["pontos"][-1]["capital"] - dados["capital_inicial"],
                "trades": len(dados["pontos"])}

    @app.callback(
        Output("pf-cresc-grafico", "figure"),
        Output("pf-cresc-resumo", "children"),
        Input("pf-cresc-btn", "n_clicks"),
        State("pf-cresc-capital", "value"),
        State("pf-cresc-risco", "value"),
        State("pf-cresc-trades", "value"),
        State("store-portfolio-aberto", "data"),
        prevent_initial_call=True,
    )
    def simular_crescimento(_n, capital_txt, risco_txt, trades_txt, pid):
        if pid is None:
            return no_update, no_update

        capital = _parse_capital(capital_txt)
        risco = _parse_capital(risco_txt)
        n_trades = _parse_capital(trades_txt)
        try:
            n_trades = int(n_trades) if n_trades is not None else None
            sim = P.simular_crescimento(pid, capital_inicial=capital,
                                        risco_pct=risco, n_trades=n_trades)
        except (ValueError, TypeError):
            return (PP.figura_crescimento_vazia(
                        "capital, risco e nº de trades precisam ser "
                        "números positivos."),
                    None)

        if sim is None:
            return (PP.figura_crescimento_vazia(
                        "adicione trades com pelo menos uma perda real "
                        "(sem perda não dá pra medir o tamanho de \"1R\" "
                        "pra simular)."),
                    None)

        return PP.figura_crescimento(sim), PP.resumo_crescimento(sim)
