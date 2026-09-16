"""Painel de controle.

A separacao visual nao e decoracao: o bloco de cima e a matematica do setup,
o de baixo e configuracao do operador, igual para toda estrategia. Quem olha
a tela precisa saber em qual dos dois esta mexendo.

Campos mineraveis trazem embaixo a faixa de otimizacao no mesmo formato da
tela do MT5 - de / passo / ate, com um interruptor para incluir ou nao o
parametro na varredura.
"""

from __future__ import annotations

from dash import dcc, html

from core.engine.execution import TIMEFRAMES
from strategies import registry

from .catalogo import DIAS, opcoes


def _num(id_, value, step=1, minimo=None, maximo=None, placeholder=None):
    return dcc.Input(id=id_, type="number", value=value, step=step, min=minimo,
                     max=maximo, placeholder=placeholder, className="inp", debounce=True)


def _field(label, component, hint=None):
    return html.Div(
        [html.Label(label, className="fld-label"), component,
         html.Span(hint, className="fld-hint") if hint else None],
        className="fld",
    )


def _opt(pid, label, valor, de, passo, ate, step=1, minimo=None, hint=None,
         ligado=False):
    """Campo com faixa de otimizacao, no formato da tela do MT5."""
    def cell(rotulo, chave, v, mn=None):
        return html.Div([
            html.Span(rotulo, className="opt-k"),
            dcc.Input(id={"type": "opt", "p": pid, "k": chave}, type="number",
                      value=v, step=step, min=mn, className="inp", debounce=True),
        ])

    return html.Div(
        [
            html.Div(
                [html.Label(label, className="fld-label"),
                 dcc.Checklist(id={"type": "opt-on", "p": pid},
                               options=[{"label": "minerar", "value": "on"}],
                               value=["on"] if ligado else [],
                               className="opt-toggle")],
                className="fld-top",
            ),
            # ou o valor fixo, ou a faixa - nunca os dois: quem vai minerar
            # nao usa o valor unico, e ve-lo ali so confunde
            html.Div(
                dcc.Input(id={"type": "val", "p": pid}, type="number", value=valor,
                          step=step, min=minimo, className="inp", debounce=True),
                id={"type": "valwrap", "p": pid},
            ),
            html.Span(hint, className="fld-hint") if hint else None,
            html.Div([cell("de", "de", de, minimo), cell("passo", "passo", passo),
                      cell("até", "ate", ate)],
                     id={"type": "optrow", "p": pid}, className="opt",
                     style={"display": "none"}),
        ],
        className="fld",
    )


def _section(titulo, children, **kw):
    cabecalho = (html.Div(html.H2(titulo, className="sec-title"),
                          className="sec-head") if titulo else None)
    return html.Section(
        [cabecalho, html.Div(children, className="sec-body")],
        className="sec", **kw,
    )


# ------------------------------------------------------------------ blocos
def periodo(inicio, fim):
    return _section(
        "Período",
        [
            html.Div([
                _field("de", dcc.DatePickerSingle(
                    id="d-de", date=inicio.date(), display_format="DD/MM/YYYY",
                    min_date_allowed=inicio.date(), max_date_allowed=fim.date())),
                _field("até", dcc.DatePickerSingle(
                    id="d-ate", date=fim.date(), display_format="DD/MM/YYYY",
                    min_date_allowed=inicio.date(), max_date_allowed=fim.date())),
            ], className="grid-2"),
            _field("tempo gráfico", dcc.Dropdown(
                id="e-timeframe", value="M5", clearable=False, className="dd",
                options=[{"label": k, "value": k} for k in TIMEFRAMES])),
            # Recorta o fim SEM mexer nas datas. A versão anterior escrevia a
            # data final do backtest, e a mineração seguinte partia dali:
            # cada rodada comia mais 12 meses até não sobrar período.
            dcc.Checklist(
                id="excluir-holdout", className="chk chk-holdout", value=[],
                options=[{"label": "excluir holdout (igual à mineração)",
                          "value": "on"}],
            ),
            html.Div(
                html.Button("Rodar backtest", id="btn-run", n_clicks=0,
                            className="btn-primary"),
                id="acao-backtest",
            ),
        ],
    )


def campos_da_estrategia(mod=None, faixas: dict | None = None):
    """Os campos de parâmetro são montados a partir do schema da estratégia
    ativa — por isso trocar de estratégia troca a seção inteira.

    `faixas` vem de uma mineração salva. Os valores entram já embutidos nos
    componentes, e não por callback depois: reconstruir a seção apagaria
    qualquer valor escrito em seguida, e a corrida entre as duas coisas era
    o que fazia a estratégia carregada aparecer com os campos da anterior.
    """
    mod = mod or registry.atual()
    faixas = faixas or {}
    campos = []
    for nome, meta in mod.params_schema.items():
        f = faixas.get(nome) or {}
        d = f.get("valor", meta["default"])
        campos.append(_opt(nome, meta["label"], d,
                           de=f.get("de", meta["min"]),
                           passo=f.get("passo", meta["step"]),
                           ate=f.get("ate", min(meta["max"], d * 3)),
                           step=meta["step"], minimo=meta["min"],
                           ligado=bool(f.get("on"))))
    return campos


def seletor_estrategia():
    disponiveis = registry.descobrir()
    return _section(
        "Estratégia",
        [
            dcc.Dropdown(
                id="estrategia", className="dd", clearable=False,
                value=registry.nome_atual(),
                options=[{"label": e["label"], "value": e["modulo"]}
                         for e in disponiveis],
            ),
            html.P(id="estrategia-nota", className="fld-hint solo"),
        ],
    )


def parametros():
    return _section("Parâmetros",
                    html.Div(campos_da_estrategia(), id="params-body"))


def execucao():
    return _section(
        None,
        [
            html.H3("Janela", className="grp"),
            html.Div([
                _field("entradas de", dcc.Input(id="e-ent-ini", value="09:00",
                                                type="text", className="inp")),
                _field("entradas até", dcc.Input(id="e-ent-fim", value="17:00",
                                                 type="text", className="inp")),
            ], className="grid-2"),
            _field("fechar posições às",
                   dcc.Input(id="e-fechamento", value="17:30", type="text",
                             className="inp")),
            _field("dias da semana", dcc.Checklist(
                id="e-dias", options=[{"label": n, "value": v} for n, v in DIAS],
                value=[1, 2, 3, 4, 5], className="chk", inline=True)),
            _field("direção", dcc.Dropdown(
                id="e-direcao", value="ambas", clearable=False, className="dd",
                options=opcoes("direcao"))),

            html.H3("Gestão", className="grp"),
            _field("tipo de alvo", dcc.Dropdown(
                id="e-alvo-tipo", value="pontos", clearable=False, className="dd",
                options=opcoes("alvo_tipo"))),
            # so um dos dois blocos aparece, conforme o tipo escolhido
            html.Div(_opt("alvo_pontos", "Alvo (pontos)", 600, 200, 100, 1200, 10, 0),
                     id="blk-alvo-pontos"),
            html.Div([
                _field("ATR período", _num("e-alvo-atr-per", 20, 1, 2)),
                _field("ATR multiplicador", _num("e-alvo-atr-mult", 3.0, 0.1, 0.1)),
            ], className="grid-2", id="blk-alvo-atr", style={"display": "none"}),

            _field("tipo de stop", dcc.Dropdown(
                id="e-stop-tipo", value="pontos", clearable=False, className="dd",
                options=opcoes("stop_tipo"))),
            html.Div(_opt("stop_pontos", "Stop (pontos)", 300, 100, 50, 600, 10, 0),
                     id="blk-stop-pontos"),
            html.Div([
                _field("ATR período", _num("e-stop-atr-per", 20, 1, 2)),
                _field("ATR multiplicador", _num("e-stop-atr-mult", 1.5, 0.1, 0.1)),
            ], className="grid-2", id="blk-stop-atr", style={"display": "none"}),

            html.H3("Proteções", className="grp"),
            _opt("breakeven_pct", "Breakeven — gatilho (% do alvo)", 0, 0, 10, 100,
                 5, 0, "0 desliga"),
            _opt("step_gatilho_pct", "Stop móvel — gatilho (% do alvo)", 0, 0, 10, 100,
                 5, 0, "0 desliga"),
            _opt("step_distancia_pct", "Stop móvel — trava (% do alvo)", 0, 0, 10, 100,
                 5, 0, "onde o stop vai parar, a favor"),
            _opt("trailing_pontos", "Trailing (pontos)", 0, 0, 50, 500, 10, 0, "0 desliga"),
            _field("tempo máximo (barras)", _num("e-max-barras", 0, 10, 0), "0 desliga"),

            html.H3("Limites diários", className="grp"),
            html.Div([
                _field("ganho máx. R$/contrato", _num("e-lim-ganho", 0.0, 50.0, 0)),
                _field("perda máx. R$/contrato", _num("e-lim-perda", 0.0, 50.0, 0)),
                _field("máx. operações", _num("e-max-trades", 0, 1, 0)),
                _field("máx. prejuízos", _num("e-max-loss", 0, 1, 0)),
            ], className="grid-2"),
            html.P("0 desliga o limite. Ao bater, o dia para.", className="fld-hint solo"),

            html.H3("Custos", className="grp"),
            html.Div([
                _field("corretagem/contrato", _num("e-corretagem", 0.50, 0.01, 0)),
                _field("emolumentos/contrato", _num("e-emolumentos", 0.27, 0.01, 0)),
                _field("slippage (ticks)", _num("e-slippage", 1, 1, 0, 20)),
            ], className="grid-2"),
            html.P("cobrado por ponta: entrada e saída", className="fld-hint solo"),

            html.H3("Posição", className="grp"),
            html.Div([
                _field("modo", dcc.Dropdown(
                    id="e-modo", value="contratos_fixos", clearable=False, className="dd",
                    options=opcoes("modo_posicao"))),
                _field("contratos", _num("e-contratos", 1, 1, 1)),
                _field("risco/trade R$", _num("e-risco", 200.0, 10.0, 0)),
                _field("capital inicial R$", _num("e-capital", 10000.0, 1000.0, 0)),
            ], className="grid-2"),

            html.H3("Filtro de mineração", className="grp"),
            _field("mínimo de operações", _num("e-min-ops", 0, 10, 0),
                   "combinação com menos que isso é descartada"),
        ],
    )


# campos da camada 4 que tambem aceitam faixa de otimizacao. Os da estrategia
# entram antes destes e mudam conforme a estrategia ativa.
CAMPOS_EXECUCAO = ["alvo_pontos", "stop_pontos", "breakeven_pct",
                   "step_gatilho_pct", "step_distancia_pct", "trailing_pontos"]


def opt_fields(mod=None):
    return list((mod or registry.atual()).params_schema) + CAMPOS_EXECUCAO
