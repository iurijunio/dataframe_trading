"""Portfólio: agrupar variantes, ver membros, correlação e risco diário.

Só a fatia de portfólio e correlação (projeto D, parte 2) — alocação de
capital por variante e gatilho automático de reotimização ficam de fora,
ver docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md §2.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import dcc, html

from .. import theme as T
from . import stats_cards
from .cartao import brl, card

# uma cor por variante, na ordem em que entram no portfolio - ciano e
# violeta primeiro (as duas cores de marca), o resto so para diferenciar
_PALETA = [T.ACCENT, T.ACCENT_2, T.WARN, T.POS, T.NEG, T.INK_2]


def painel():
    return html.Div(
        [
            html.Section([
                html.H2("Portfólio", className="panel-title"),
                html.Div([
                    dcc.Input(id="pf-novo-nome", type="text", className="inp",
                              placeholder="nome do novo portfólio",
                              debounce=True),
                    html.Button("Criar", id="pf-btn-criar", n_clicks=0,
                                className="btn-ghost"),
                ], className="acoes"),
                html.Div(id="pf-lista", className="est-lista"),
            ], className="panel"),
            html.Section(
                id="pf-detalhe", className="panel", style={"display": "none"},
                children=[
                    html.H3(id="pf-detalhe-titulo"),
                    html.Div([
                        dcc.Input(id="pf-capital", type="text",
                                  inputMode="numeric", className="inp",
                                  value="10000",
                                  placeholder="capital do portfólio (R$)"),
                        html.Button("Salvar capital", id="pf-btn-salvar-capital",
                                    n_clicks=0, className="btn-ghost"),
                        dcc.Loading(
                            html.Span(id="pf-capital-msg", className="panel-note"),
                            type="circle", className="pf-capital-loading"),
                    ], className="acoes"),
                    # a curva manda: é a leitura principal, mesma filosofia
                    # do Backtest e do Walk-Forward - o resto é apoio
                    html.Div(
                        [html.H4("Curva de capital", className="panel-title"),
                         html.Span("uma linha por variante (capital do "
                                   "plano ativo + trades OOS reais) + a "
                                   "linha branca combinada, a partir do "
                                   "capital do portfólio",
                                   className="panel-note")],
                        className="panel-head",
                    ),
                    dcc.Graph(id="pf-curva", figure=figura_curva_vazia(),
                              className="graph pf-graph",
                              config={"displayModeBar": False, "responsive": True}),

                    html.Div(id="pf-metricas", className="cards pf-metricas"),

                    html.Div([
                        html.Div(id="pf-heatmap", className="pf-col"),
                        html.Div(id="pf-risco", className="pf-col"),
                    ], className="pf-grid-2"),

                    html.Div([
                        dcc.Dropdown(id="pf-add-variante", className="dd dd-sm",
                                    placeholder="adicionar variante…",
                                    options=[]),
                        html.Button("Adicionar", id="pf-btn-add", n_clicks=0,
                                    className="btn-ghost"),
                    ], className="acoes"),
                    html.Div(id="pf-membros", className="pf-membros"),
                    html.Div(id="pf-avisos"),
                ],
            ),
        ],
        id="painel-portfolio", className="modo-bloco",
        style={"display": "none"},
    )


def cartao_portfolio(portfolio_id: int, nome: str, n_membros: int) -> html.Div:
    return html.Div(
        [html.Span(nome, className="est-cartao-nome"),
         html.Span(f"{n_membros} variante(s)", className="est-cartao-nota")],
        id={"type": "pf-cartao", "portfolio_id": portfolio_id},
        className="est-cartao", n_clicks=0,
    )


def linha_membro(variante_id: int, nome: str, estrategia: str,
                 sem_plano_ativo: bool, resumo: dict | None = None) -> html.Div:
    nota = "sem plano ativo" if sem_plano_ativo else "plano ativo"
    filhos = [
        html.Span(f"{nome} · {estrategia}", className="est-variante-nome"),
        html.Span(nota, className="est-variante-nota"
                  + (" pf-sem-plano" if sem_plano_ativo else "")),
    ]
    if resumo is not None:
        sinal = "pf-pos" if resumo["retorno"] >= 0 else "pf-neg"
        filhos.append(html.Span(
            f"{brl(resumo['retorno'])} · {resumo['trades']} trade(s)",
            className=f"est-variante-resumo {sinal}"))
    filhos.append(html.Button("remover", id={"type": "pf-btn-remover",
                                             "variante_id": variante_id},
                              className="btn-ghost btn-sm", n_clicks=0))
    return html.Div(filhos, className="est-variante")


def cartoes_metricas(m: dict | None, capital_definido: bool = True) -> list:
    """Fator de recuperação, drawdown, sharpe etc. do portfólio COMBINADO
    (todos os trades de todas as variantes ativas juntos) - mesma régua
    de `core.metrics.resumo` que o Backtest e o Walk-Forward usam, via
    `stats_cards.cartoes` (mesmos cartões, mesmo texto do (?))."""
    if m is None:
        if not capital_definido:
            return [html.P("defina o capital do portfólio para ver as "
                           "métricas.")]
        return [html.P("adicione pelo menos uma variante com plano ativo "
                       "e trades para ver as métricas do portfólio.")]
    return list(stats_cards.cartoes(m).values())


def card_risco(risco: dict | None) -> html.Div:
    if risco is None:
        return html.P("adicione pelo menos duas variantes com plano ativo "
                      "e trades no mesmo dia para ver o risco combinado.")
    sinal = "neg" if risco["p90"] < 0 else "pos"
    return card("drawdown diário combinado (p90)", brl(risco["p90"]),
                explica="Estimativa por simulação: o valor só é "
                        "ultrapassado em 10% dos cenários simulados — não "
                        "é o pior caso absoluto.",
                sinal=sinal, nota=f"pior dia: {risco['pior_dia']}")


def _cor_celula(r: float | None) -> str:
    if r is None:
        return "rgba(255,255,255,.03)"
    alpha = min(abs(r), 1.0)
    cor = "255,77,125" if r >= 0 else "0,245,160"
    return f"rgba({cor},{alpha:.2f})"


def _leitura_correlacao(r: float | None) -> str:
    """0,00 e 1,00 na diagonal não tem leitura (mesma variante vs. ela
    mesma) - fora dela, quanto mais perto de zero, mais a variante ajuda a
    diversificar o portfólio; perto de 1 ela é redundante (some junto);
    perto de -1 ela compensa (uma cai quando a outra sobe)."""
    if r is None:
        return ""
    a = abs(r)
    if a < 0.3:
        return "baixa - boa diversificação"
    if a < 0.6:
        return "moderada"
    return "alta - redundante" if r > 0 else "alta - compensa bem"


def heatmap(nomes: list[str], matriz: list[list]) -> html.Div:
    if len(nomes) < 2:
        return html.P("adicione pelo menos duas variantes com plano ativo "
                      "para ver a correlação.")
    n = len(nomes)
    cabecalho = [html.Div("", className="pf-heat-canto")] + [
        html.Div(nome, className="pf-heat-rotulo") for nome in nomes]
    linhas = [cabecalho]
    for i in range(n):
        linha = [html.Div(nomes[i], className="pf-heat-rotulo")]
        for j in range(n):
            v = matriz[i][j]
            texto = f"{v:.2f}" if v is not None else "—"
            titulo = _leitura_correlacao(v) if i != j else ""
            linha.append(html.Div(
                texto, className="pf-heat-cel", title=titulo,
                style={"backgroundColor": _cor_celula(v)}))
        linhas.append(linha)
    return html.Div(
        [html.Div(
            [html.Div(linha, className="pf-heat-linha") for linha in linhas],
            className="pf-heatmap",
            style={"gridTemplateColumns": f"auto repeat({n}, 1fr)"},
        ),
         html.Span("passe o mouse sobre um valor: até 0,3 é baixa "
                   "correlação (bom p/ diversificar) · 0,3–0,6 moderada · "
                   "acima de 0,6 alta (redundante)",
                   className="panel-note pf-heat-legenda")],
    )


def figura_curva_vazia(mensagem="adicione variantes com plano ativo para "
                                "ver a curva de capital.") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=T.SURFACE, plot_bgcolor=T.SURFACE,
        margin=dict(l=8, r=8, t=8, b=8),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text=mensagem, showarrow=False,
                          font=dict(color=T.MUTED, size=13))],
    )
    return fig


def figura_curva(series: dict, combinada: dict | None = None) -> go.Figure:
    """Uma linha por variante (fina, colorida) mais a linha COMBINADA do
    portfólio (grossa, branca, por cima das outras) - capital do plano
    ativo + trades OOS reais, acumulados em R$. Mesma leitura da curva do
    walk-forward, só que sobrepondo as variantes do portfólio em vez de
    uma janela só."""
    if not series:
        return figura_curva_vazia()

    fig = go.Figure()
    for i, (nome, dados) in enumerate(series.items()):
        pontos = dados["pontos"]
        if not pontos:
            # plano ativo mas nenhum trade OOS ainda - sem timestamp
            # nenhum para ancorar um ponto, não tem curva pra desenhar
            # (achado real: x/y de tamanho diferente quebrava o Scatter)
            continue
        cor = _PALETA[i % len(_PALETA)]
        xs = [pontos[0]["ts"]] + [p["ts"] for p in pontos]
        ys = [dados["capital_inicial"]] + [p["capital"] for p in pontos]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=nome,
            line=dict(color=cor, width=1.4),
            hovertemplate=f"%{{x|%d/%m/%Y}}<br>{nome}: R$ %{{y:,.2f}}<extra></extra>",
        ))

    if not fig.data and not (combinada and combinada["pontos"]):
        return figura_curva_vazia(
            "nenhuma variante com trades OOS ainda para desenhar a curva.")

    if combinada and combinada["pontos"]:
        pontos = combinada["pontos"]
        xs = [pontos[0]["ts"]] + [p["ts"] for p in pontos]
        ys = [combinada["capital_inicial"]] + [p["capital"] for p in pontos]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name="Portfólio (combinado)",
            line=dict(color=T.INK, width=2.6),
            hovertemplate="%{x|%d/%m/%Y}<br>combinado: R$ %{y:,.2f}<extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor=T.SURFACE, plot_bgcolor=T.SURFACE,
        font=dict(family="JetBrains Mono, monospace", size=11, color=T.MUTED),
        margin=dict(l=8, r=8, t=28, b=8),
        hoverlabel=dict(bgcolor=T.SURFACE_2, bordercolor=T.ACCENT_DIM,
                        font=dict(color=T.INK, family="JetBrains Mono, monospace")),
        legend=dict(orientation="h", y=1.14, font=dict(color=T.MUTED)),
        xaxis=dict(gridcolor=T.LINE_SOFT, linecolor=T.LINE,
                  tickfont=dict(color=T.MUTED)),
        yaxis=dict(gridcolor=T.LINE_SOFT, linecolor=T.LINE,
                  tickfont=dict(color=T.MUTED), tickprefix="R$ "),
    )
    return fig
