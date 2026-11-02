"""Painel de controle (o menu da esquerda).

Topo fixo (ativo, estratégia, período, tempo gráfico, holdout) e, abaixo,
cinco abas: Entrada, Saída, Filtros, Risco e Períodos. Aba com um grupo só
mostra os campos direto; aba com dois ou mais põe cada grupo numa gaveta que
abre e fecha e, fechada, mostra um resumo curto (`callbacks.resumos`).

Cada grupo é uma função (`grupo_*`): `abas_menu` monta as abas com elas e
`execucao` devolve todos os grupos juntos, como sempre devolveu — os testes e
a referência das telas leem a camada 4 por ela.

Campos mineraveis trazem embaixo a faixa de otimizacao no mesmo formato da
tela do MT5 - de / passo / ate, com um interruptor para incluir ou nao o
parametro na varredura.
"""

from __future__ import annotations

from dash import dcc, html

from core.engine.execution import TIMEFRAMES
from strategies import registry

from .cartao import dica
from .catalogo import DIAS, opcoes

# (valor, de, passo, ate, step) de stop, alvo e trailing em pontos no WIN; os
# micros trocam pela faixa da ficha do ativo (`aplicar_perfil_do_ativo`)
PADRAO_C4 = {"alvo_pontos": (600, 200, 100, 1200, 10),
             "stop_pontos": (300, 100, 50, 600, 10),
             "trailing_pontos": (0, 0, 50, 500, 10)}

# as abas do menu, na ordem da tela
ABAS_MENU = ["entrada", "saida", "filtros", "risco", "periodos"]
ROTULOS_ABA = {"entrada": "Entrada", "saida": "Saída", "filtros": "Filtros",
               "risco": "Risco", "periodos": "Períodos"}


def _num(id_, value, step=1, minimo=None, maximo=None, placeholder=None):
    return dcc.Input(id=id_, type="number", value=value, step=step, min=minimo,
                     max=maximo, placeholder=placeholder, className="inp", debounce=True)


def _rotulo(label, hint=None):
    """O rótulo e, se houver explicação, o (?) AO LADO dele — nunca dentro do
    html.Label: quem lê o texto do rótulo não pode encontrar o "?" ali."""
    if not hint:
        return html.Label(label, className="fld-label")
    return html.Span([html.Label(label, className="fld-label"), dica(hint)],
                     className="fld-rot")


def _field(label, component, hint=None, classe="fld"):
    return html.Div([_rotulo(label, hint), component], className=classe)


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
                [_rotulo(label, hint),
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
            # o lugar onde a explicação ficava visível (hoje vai no (?) do
            # rótulo): mantido vazio para os campos da estratégia
            # continuarem idênticos à referência (telas_win/parametros.json)
            None,
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


# inteiro com até tantos valores é categoria (ex.: `saida`, 0 a 2): o
# padrão × 3 cortaria modos — com padrão 0, a faixa virava 0 a 0
POUCOS_VALORES = 10


def _ate_padrao(meta: dict, valor):
    """O "até" que a faixa de mineração sugere antes de o usuário mexer."""
    if meta.get("tipo") == "int" and meta.get("step"):
        valores = round((meta["max"] - meta["min"]) / meta["step"]) + 1
        if valores <= POUCOS_VALORES:
            return meta["max"]
    return min(meta["max"], valor * 3)


def campos_da_estrategia(mod=None, faixas: dict | None = None,
                         faixas_ativo: dict | None = None):
    """Os campos de parâmetro são montados a partir do schema da estratégia
    ativa — por isso trocar de estratégia troca a seção inteira.

    `faixas` vem de uma mineração salva. Os valores entram já embutidos nos
    componentes, e não por callback depois: reconstruir a seção apagaria
    qualquer valor escrito em seguida, e a corrida entre as duas coisas era
    o que fazia a estratégia carregada aparecer com os campos da anterior.

    `faixas_ativo` (`ativo.faixas_do_ativo`) é a escala do ativo: o filtro de
    50 em 50 pontos do WIN não serve para um MES de 5 mil pontos. Vale chave
    por chave, abaixo da mineração e acima do schema. Com faixa do ativo o
    `step` do input é 1: os micros andam em pontos inteiros, e no Dash um
    valor fora do passo vira None.
    """
    mod = mod or registry.atual()
    faixas = faixas or {}
    faixas_ativo = faixas_ativo or {}
    campos = []
    for nome, meta in mod.params_schema.items():
        f = faixas.get(nome) or {}
        a = faixas_ativo.get(nome) or {}

        def chave(k, padrao):
            for fonte in (f, a):
                if fonte.get(k) is not None:
                    return fonte[k]
            return padrao

        d = chave("valor", meta["default"])
        ate = chave("ate", None)
        campos.append(_opt(nome, meta["label"], d,
                           de=chave("de", meta["min"]),
                           passo=chave("passo", meta["step"]),
                           ate=_ate_padrao(meta, d) if ate is None else ate,
                           step=1 if a else meta["step"], minimo=meta["min"],
                           ligado=bool(f.get("on"))))
    return campos


# ------------------------------------------------------------- topo fixo
def topo_menu(simbolo, inicio, fim, ativos=None):
    """O que vale para a aba inteira e não rola: ativo e estratégia lado a
    lado; de, até e tempo gráfico; o holdout; e as abas.

    `ativos`: os símbolos do seletor (o app lê do banco; quem monta o menu
    sem banco, como `scripts/campos_menu.py`, passa a lista).
    """
    if ativos is None:
        from ui import data as D
        ativos = [i["symbol"] for i in D.instrumentos()]
    return html.Div(
        [
            html.Div([
                _field("ativo", dcc.Dropdown(
                    id="ativo", value=simbolo, clearable=False, className="dd",
                    options=[{"label": s, "value": s} for s in ativos]),
                    classe="fld fld-ativo"),
                _field("estratégia", dcc.Dropdown(
                    id="estrategia", className="dd", clearable=False,
                    value=registry.nome_atual(),
                    options=[{"label": e["label"], "value": e["modulo"]}
                             for e in registry.descobrir()]),
                    classe="fld fld-estrategia"),
            ], className="menu-linha"),
            # estado (o que a troca de estratégia ou a mineração carregada
            # fez), não explicação: fica visível
            html.P(id="estrategia-nota", className="fld-hint solo"),
            html.Div([
                _field("de", dcc.DatePickerSingle(
                    id="d-de", date=inicio.date(), display_format="DD/MM/YYYY",
                    min_date_allowed=inicio.date(), max_date_allowed=fim.date())),
                _field("até", dcc.DatePickerSingle(
                    id="d-ate", date=fim.date(), display_format="DD/MM/YYYY",
                    min_date_allowed=inicio.date(), max_date_allowed=fim.date())),
                _field("tempo gráfico", dcc.Dropdown(
                    id="e-timeframe", value="M5", clearable=False, className="dd",
                    options=[{"label": k, "value": k} for k in TIMEFRAMES]),
                    classe="fld fld-tempo"),
            ], className="menu-linha"),
            # Recorta o fim SEM mexer nas datas. A versão anterior escrevia a
            # data final do backtest, e a mineração seguinte partia dali:
            # cada rodada comia mais 12 meses até não sobrar período.
            dcc.Checklist(
                id="excluir-holdout", className="chk chk-holdout", value=[],
                options=[{"label": "excluir holdout (igual à mineração)",
                          "value": "on"}],
            ),
            # "Rodar backtest" (`acao-backtest`) mora na barra do alto da
            # subtela Backtest da Mineração (ui/app.py, `barra_backtest`).
            # A aba escolhida fica enquanto o app está aberto: ninguém além
            # de `callbacks.menu_abas` a escreve (trocar estratégia ou ativo
            # não mexe nela).
            dcc.RadioItems(
                id="menu-aba", value="entrada", className="menu-abas",
                options=[{"label": ROTULOS_ABA[a], "value": a} for a in ABAS_MENU]),
        ],
        className="menu-topo",
    )


# ------------------------------------------------------------------ grupos
def grupo_parametros(mod=None, faixas_ativo=None):
    """Os campos da estratégia: `params-body` é reconstruído ao trocar de
    estratégia, de ativo ou ao carregar uma mineração."""
    return html.Div(campos_da_estrategia(mod, None, faixas_ativo),
                    id="params-body", className="params-body")


def grupo_direcao():
    return _field("direção", dcc.Dropdown(
        id="e-direcao", value="ambas", clearable=False, className="dd",
        options=opcoes("direcao")))


def grupo_sem_entradas():
    return html.Div([
        _field("sem entradas · 1", dcc.Dropdown(
            id="e-sem-ent1", value="", clearable=False, className="dd",
            options=opcoes("hora"))),
        _field("sem entradas · 2", dcc.Dropdown(
            id="e-sem-ent2", value="", clearable=False, className="dd",
            options=opcoes("hora"))),
        _field("sem entradas · 3", dcc.Dropdown(
            id="e-sem-ent3", value="", clearable=False, className="dd",
            options=opcoes("hora"))),
    ], className="grid-3")


def grupo_filtro_mercado():
    # antes de decidir QUANDO entrar (Janela), o operador decide se o
    # mercado deixa entrar
    return [
        _field("régua (ADX)", dcc.Dropdown(
            id="e-filtro-adx", value="tendencia", clearable=False,
            className="dd", options=opcoes("filtro_adx")),
            "Em tendência, só entra com ADX no limiar ou acima; em rango, só "
            "com ADX abaixo. 0 em período ou limiar desliga o filtro — e é o "
            "que deixa minerar ligado x desligado na mesma varredura."),
        html.Div([
            _opt("adx_periodo", "ADX · período", 0, 5, 1, 40, 1, 0, "0 desliga"),
            _opt("adx_limiar", "ADX · limiar", 0, 10, 5, 40, 5, 0, "0 desliga"),
        ], className="grid-2"),
        html.Div([
            _opt("adx_filtro_di", "DI confirma o lado", 0, 0, 1, 1, 1, 0,
                 "só na tendência: compra com DI+ acima de DI−, e o "
                 "contrário na venda"),
            _opt("adx_subindo", "ADX subindo", 0, 0, 1, 1, 1, 0,
                 "só na tendência: barra atual acima da anterior"),
        ], className="grid-2"),
    ]


def grupo_janela():
    return [
        html.Div([
            _field("entradas de", dcc.Input(id="e-ent-ini", value="09:00",
                                            type="text", className="inp")),
            _field("entradas até", dcc.Input(id="e-ent-fim", value="17:00",
                                             type="text", className="inp")),
            _field("fechar posições às",
                   dcc.Input(id="e-fechamento", value="17:30", type="text",
                             className="inp")),
        ], className="grid-3"),
        _field("dias da semana", dcc.Checklist(
            id="e-dias", options=[{"label": n, "value": v} for n, v in DIAS],
            value=[1, 2, 3, 4, 5], className="chk", inline=True)),
    ]


def grupo_gestao():
    return [
        html.Div([
            _field("tipo de stop", dcc.Dropdown(
                id="e-stop-tipo", value="pontos", clearable=False, className="dd",
                options=opcoes("stop_tipo"))),
            _field("tipo de alvo", dcc.Dropdown(
                id="e-alvo-tipo", value="pontos", clearable=False, className="dd",
                options=opcoes("alvo_tipo"))),
        ], className="grid-2"),
        # stop, alvo e trailing na mesma linha. Só um bloco de cada tipo
        # aparece (`callbacks.tipos`); os de ATR ocupam a linha inteira
        html.Div([
            html.Div(_opt("stop_pontos", "stop", *PADRAO_C4["stop_pontos"], 0),
                     id="blk-stop-pontos"),
            html.Div([
                _opt("stop_atr_periodo", "ATR período", 20, 5, 1, 60, 1, 2),
                _opt("stop_atr_mult", "ATR multiplicador", 1.5, 1.0, 0.1,
                     4.0, 0.1, 0.1),
            ], className="grid-2 blk-largo", id="blk-stop-atr",
                style={"display": "none"}),
            html.Div(_opt("stop_pct", "Stop (%)", 0.5, 0.25, 0.25, 2.0, 0.01, 0),
                     id="blk-stop-pct", style={"display": "none"}),

            html.Div(_opt("alvo_pontos", "alvo", *PADRAO_C4["alvo_pontos"], 0),
                     id="blk-alvo-pontos"),
            html.Div([
                _opt("alvo_atr_periodo", "ATR período", 20, 5, 1, 60, 1, 2),
                _opt("alvo_atr_mult", "ATR multiplicador", 3.0, 1.0, 0.1,
                     6.0, 0.1, 0.1),
            ], className="grid-2 blk-largo", id="blk-alvo-atr",
                style={"display": "none"}),
            html.Div(_opt("alvo_razao", "Alvo · vezes o stop", 2.0, 1.0, 0.5,
                          5.0, 0.1, 0.1,
                          "risco:retorno — 2,0 = alvo a duas vezes o stop"),
                     id="blk-alvo-razao", style={"display": "none"}),
            html.Div(_opt("alvo_pct", "Alvo (%)", 1.0, 0.5, 0.5, 3.0, 0.01, 0),
                     id="blk-alvo-pct", style={"display": "none"}),

            _opt("trailing_pontos", "trailing", *PADRAO_C4["trailing_pontos"],
                 0, "0 desliga"),
        ], className="grid-3 linha-saida"),
    ]


def grupo_protecoes():
    return [
        _opt("breakeven_pct", "Breakeven — gatilho (% do alvo)", 0, 0, 10, 100,
             5, 0, "0 desliga"),
        _opt("step_gatilho_pct", "Stop móvel — gatilho (% do alvo)", 0, 0, 10, 100,
             5, 0, "0 desliga"),
        _opt("step_distancia_pct", "Stop móvel — trava (% do alvo)", 0, 0, 10, 100,
             5, 0, "onde o stop vai parar, a favor"),
        _field("tempo máximo (barras)", _num("e-max-barras", 0, 10, 0), "0 desliga"),
    ]


def grupo_limites():
    return [
        html.Div([
            _field(["ganho máx. ", html.Span("R$", id={"type": "moeda-c4", "i": "lim-ganho"}), "/contrato"], _num("e-lim-ganho", 0.0, 50.0, 0)),
            _field(["perda máx. ", html.Span("R$", id={"type": "moeda-c4", "i": "lim-perda"}), "/contrato"], _num("e-lim-perda", 0.0, 50.0, 0)),
            _field("máx. operações", _num("e-max-trades", 0, 1, 0)),
            _field("máx. prejuízos", _num("e-max-loss", 0, 1, 0)),
        ], className="grid-2"),
    ]


def grupo_custos():
    return [
        html.Div([
            _field("corretagem/contrato", _num("e-corretagem", 0.50, 0.01, 0)),
            _field("emolumentos/contrato", _num("e-emolumentos", 0.27, 0.01, 0)),
            _field("slippage (ticks)", _num("e-slippage", 1, 1, 0, 20)),
        ], className="grid-3"),
    ]


def grupo_posicao():
    return [
        html.Div([
            _field("modo", dcc.Dropdown(
                id="e-modo", value="contratos_fixos", clearable=False, className="dd",
                options=opcoes("modo_posicao"))),
            _field("contratos", _num("e-contratos", 1, 1, 1)),
            _field(["risco/trade ", html.Span("R$", id={"type": "moeda-c4", "i": "risco"})], _num("e-risco", 200.0, 10.0, 0)),
            _field(["capital inicial ", html.Span("R$", id={"type": "moeda-c4", "i": "capital"})], _num("e-capital", 10000.0, 1000.0, 0)),
        ], className="grid-2"),
    ]


def grupo_filtro_mineracao():
    return [_field("mínimo de operações", _num("e-min-ops", 0, 10, 0),
                   "combinação com menos que isso é descartada")]


# (id da gaveta, título, função do grupo, explicação do título) por aba
GAVETAS = {
    "saida": [("gestao", "Gestão", grupo_gestao, None),
              ("protecoes", "Proteções", grupo_protecoes, None)],
    "filtros": [("filtro-mercado", "Filtro de mercado", grupo_filtro_mercado, None),
                ("janela", "Janela", grupo_janela, None),
                ("filtro-mineracao", "Filtro de mineração",
                 grupo_filtro_mineracao, None)],
    "risco": [("limites", "Limites diários", grupo_limites,
               "0 desliga o limite. Ao bater, o dia para."),
              ("custos", "Custos", grupo_custos,
               "cobrado por ponta: entrada e saída"),
              ("posicao", "Posição", grupo_posicao, None)],
}
GRUPOS_GAVETA = [g for gs in GAVETAS.values() for g, *_ in gs]

# a aba de cada campo mineravel da camada 4 (o pontinho na aba); os campos da
# estrategia ficam todos na Entrada
ABA_DO_CAMPO = {
    **{p: "saida" for p in ("alvo_pontos", "stop_pontos", "trailing_pontos",
                            "breakeven_pct", "step_gatilho_pct",
                            "step_distancia_pct", "alvo_razao",
                            "alvo_atr_periodo", "alvo_atr_mult", "alvo_pct",
                            "stop_atr_periodo", "stop_atr_mult", "stop_pct")},
    **{p: "filtros" for p in ("adx_periodo", "adx_limiar", "adx_filtro_di",
                              "adx_subindo")},
}


def gaveta(grupo, titulo, corpo, aberta=False, hint=None):
    """Grupo que abre e fecha. Fechada, a linha do título traz o resumo do
    que está dentro (`callbacks.resumos` o escreve)."""
    cab = [html.Span(titulo, className="gaveta-titulo")]
    if hint:
        cab.append(dica(hint))
    return html.Details(
        [html.Summary([html.Span(cab, className="gaveta-cab"),
                       html.Span(id={"type": "gaveta-resumo", "g": grupo},
                                 className="gaveta-resumo")],
                      className="gaveta-sum"),
         html.Div(corpo, className="gaveta-corpo")],
        open=aberta, id={"type": "gaveta", "g": grupo}, className="gaveta",
    )


def abas_menu(mod=None, faixas_ativo=None):
    """Um painel por aba; só o da aba escolhida aparece (`menu_abas`).
    Ao abrir o app: aba Entrada e a primeira gaveta de cada aba abertas."""
    from . import mining

    def pane(aba, filhos):
        return html.Div(filhos, id={"type": "menu-pane", "aba": aba},
                        className="menu-pane",
                        style=None if aba == "entrada" else {"display": "none"})

    def gavetas(aba):
        return [gaveta(g, t, f(), aberta=i == 0, hint=h)
                for i, (g, t, f, h) in enumerate(GAVETAS[aba])]

    return html.Div(
        [
            # um grupo só: campos direto. `params-body` some na grade da
            # Entrada (display:contents) e a direção cai na célula seguinte
            pane("entrada", [
                html.Div([grupo_parametros(mod, faixas_ativo), grupo_direcao()],
                         className="grid-2 entrada-grade"),
                grupo_sem_entradas(),
            ]),
            pane("saida", gavetas("saida")),
            pane("filtros", gavetas("filtros")),
            pane("risco", gavetas("risco")),
            pane("periodos", mining.controles()),
        ],
        className="menu-abas-corpo",
    )


def execucao():
    """Toda a camada 4, grupo por grupo (os mesmos grupos das abas)."""
    def grp(titulo):
        return html.H3(titulo, className="grp")

    return _section(
        None,
        [grp("Filtro de mercado"), *grupo_filtro_mercado(),
         grp("Janela"), *grupo_janela(), grupo_direcao(), grupo_sem_entradas(),
         grp("Gestão"), *grupo_gestao(),
         grp("Proteções"), *grupo_protecoes(),
         grp("Limites diários"), *grupo_limites(),
         grp("Custos"), *grupo_custos(),
         grp("Posição"), *grupo_posicao(),
         grp("Filtro de mineração"), *grupo_filtro_mineracao()],
    )


# campos da camada 4 que tambem aceitam faixa de otimizacao. Os da estrategia
# entram antes destes e mudam conforme a estrategia ativa.
CAMPOS_EXECUCAO = ["alvo_pontos", "stop_pontos", "breakeven_pct",
                   "step_gatilho_pct", "step_distancia_pct", "trailing_pontos",
                   "alvo_razao", "alvo_atr_periodo", "alvo_atr_mult",
                   "alvo_pct", "stop_atr_periodo", "stop_atr_mult", "stop_pct",
                   "adx_periodo", "adx_limiar", "adx_filtro_di",
                   "adx_subindo"]


def opt_fields(mod=None):
    return list((mod or registry.atual()).params_schema) + CAMPOS_EXECUCAO
