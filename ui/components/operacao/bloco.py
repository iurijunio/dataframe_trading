"""Operação: cabeçalho e o bloco inteiro da sub-tela."""
from __future__ import annotations

from datetime import date, datetime

import dash_tvlwc
from dash import dcc, html

from ... import theme as T
from .. import ordens_panel as OR
from ..cartao import dica, inteiro
from ..icones import icone

from .base import CHART_CURVA
from .variantes import _CHAVE, _botao
from .situacao import _seg, _sep


# --------------------------------------------------------------- cabeçalho
_TITULO_ENVIO = {
    "demo": {"desligar": "Desliga o envio de ordens desta conta: a automação "
                         "encerra as posições dela e para de mandar ordens (o "
                         "papel continua). Clique duas vezes para confirmar.",
             "ligar": "Liga o envio de ordens desta conta: as variantes na fase "
                      "demo passam a operar de verdade na conta demo. Precisa do "
                      "limite de perda do dia cadastrado. Clique duas vezes."},
    "real": {"desligar": "Desliga o envio de ordens da conta real: a automação "
                         "encerra as posições reais e para de mandar ordens (o "
                         "papel e a demo continuam). Clique duas vezes.",
             "ligar": "Liga o envio de ordens da conta real: as variantes na fase "
                      "real passam a operar de verdade na conta real. Clique "
                      "duas vezes para confirmar."},
}


def interruptor_envio(conta_id, envio: bool | None, armado, tipo: str = "demo"):
    """O Envio de ordens de uma conta (chave real laranja ou demo ciano), com
    a confirmação de dois cliques: desligar encerra as posições da automação
    dela. Sem conta: nada. O `tipo` escolhe a ação (`envio-real-*` ou
    `envio-*`) e a pasta de comandos."""
    if conta_id is None or envio is None:
        return None
    pre = "envio-real-" if tipo == "real" else "envio-"
    titulos = _TITULO_ENVIO[tipo]
    if envio:
        return _botao(f"{pre}desligar", conta_id, armado, titulos["desligar"])
    return _botao(f"{pre}ligar", conta_id, armado, titulos["ligar"])


def cabecalho(pf: dict, resumo: dict, *, contrato=None, dia=None) -> list:
    """Etiqueta ligado/desligado e os pares rótulo → valor da linha do
    portfólio. `dia` é o pregão que a tela mostra: antes da abertura é o de
    ontem, e sem ele nada na tela diz isso."""
    contas = resumo.get("contas") or {}
    demo, real = contas.get("demo"), contas.get("real")
    cap = resumo.get("capital")
    n, op = resumo.get("n_variantes", 0), resumo.get("n_operando", 0)
    # o estado da captura traz o contrato do dia como dicionário: um dict
    # como filho quebra o desenho e o Dash devolve o menu à aba anterior
    if isinstance(contrato, dict):
        contrato = contrato.get("simbolo")
    if not isinstance(contrato, str):
        contrato = None
    pregao = f"{dia:%d/%m}" if isinstance(dia, (date, datetime)) else "—"
    nome_demo = str(demo["nome"]) if demo and demo.get("nome") else None
    nome_real = str(real["nome"]) if real and real.get("nome") else None
    ligado = bool(pf.get("ligado"))
    return [
        # ponto verde + "ligado" (cinza + "desligado"), como no rascunho v4
        html.Span("ligado" if ligado else "desligado",
                  className="op-st " + ("op-st-on" if ligado else "op-st-off")),
        html.Div([
            _sep("|"),
            _seg([html.B(contrato or "—", className="mono")],
                 "O contrato do mês em que a demo manda as ordens hoje (o "
                 "gráfico mostra o WIN$N, a série contínua). Troca sozinho na "
                 "rolagem."),
            _sep(),
            # a conta real só aparece com ela cadastrada no portfólio
            *([_seg(["real ", html.B(_conta_curta(nome_real))],
                    "A conta real onde as variantes na fase real mandam ordens. "
                    "Antes de ligar o envio dela, confira o MT5 e o limite de "
                    "perda do dia.",
                    title=f"conta real {nome_real}"), _sep()] if nome_real else []),
            _seg(["demo ", html.B(_conta_curta(nome_demo) if nome_demo else "—")],
                 "A conta demo onde as variantes na fase demo mandam ordens.",
                 title=f"conta demo {nome_demo}" if nome_demo else None),
            _sep(),
            _seg([html.B("—" if cap is None
                         else f"R$ {inteiro(int(round(cap)))}")],
                 title="capital do portfólio"),
            _sep(),
            _seg([html.B(f"{op}/{n}"), " operando"],
                 "Variantes com o papel rodando hoje (variante e portfólio "
                 "ligados), sobre o total de variantes do portfólio."),
            _sep(),
            _seg([f"pregão {pregao}"],
                 "O pregão que a tela mostra. Antes da abertura é o de ontem "
                 "(o do último candle gravado).", "op-seg-pregao"),
        ], className="op-meta"),
    ]


def _conta_curta(nome: str) -> str:
    """"ClearInvestimentos-DEMO" → "ClearInvestimentos": o "demo" já vem
    escrito antes do nome. O nome inteiro fica no `title`."""
    if nome.upper().endswith("-DEMO") and len(nome) > 5:
        return nome[:-5]
    # "ClearContaReal-1014062283" → "ClearContaReal" (o número fica no title)
    base, _, sufixo = nome.rpartition("-")
    if base and sufixo.isdigit():
        return base
    return nome


def botoes_portfolio(pf: dict, armado, *, conta_id=None, envio=None,
                     real_id=None, envio_real=None) -> list:
    """A direita da linha do portfólio: Envio (?), a chave Real (só com conta
    real no portfólio), a chave Demo, um separador e o power. O power para
    o papel das duas contas (o title diz isso)."""
    pid = pf["portfolio_id"]
    chaves = [interruptor_envio(real_id, envio_real, armado, tipo="real"),
              interruptor_envio(conta_id, envio, armado)]
    chaves = [c for c in chaves if c is not None]
    antes = []
    if chaves:
        antes = [html.Span(["Envio", dica("Envio de ordens por conta. Ligado: a "
                                          "automação manda ordens nesta conta para "
                                          "as variantes na fase dela. Desligado: só "
                                          "o papel. Bom: ligado nas contas em uso. "
                                          "Ruim: ligado sem limite de perda do dia "
                                          "cadastrado (a automação não liga).")],
                           className="op-envlb"), *chaves,
                 html.Span(className="op-vsep")]
    if pf.get("ligado"):
        return antes + [_botao("pf-desligar", pid, armado,
                               "para o papel de todas as variantes deste portfólio "
                               "(real e demo param junto). Dois cliques.")]
    return antes + [_botao("pf-ligar", pid, armado,
                           "Libera as variantes ligadas do portfólio para o papel. "
                           "Clique duas vezes para confirmar.")]


# -------------------------------------------------------------------- bloco
def _sec_head(titulo, explica=None, *direita, classe="", ic=None):
    """Título da seção, com ícone. Nenhuma frase visível embaixo dele: a
    explicação, quando há, mora no (?) ao lado do título."""
    return html.Div([
        html.Div(html.H3(([icone(ic)] if ic else []) + [titulo]
                         + ([dica(explica)] if explica else []),
                         className="panel-title av-sec-titulo")),
        *([html.Div(list(direita), className="pg-barra")] if direita else []),
    ], className=("av-sec-head op-head " + classe).strip())


def _curva_papel_esperado():
    """A curva Papel × esperado — mora na aba Avaliação."""
    return html.Div([
        OR.subtitulo("Papel × esperado", "Acumulado do papel desde o plano em "
                     "vigor, contra a faixa que a Candidata prometeu. Bom: a "
                     "linha verde entre os pontilhados (p10 e p90). Ruim: "
                     "abaixo do p10 por vários pregões.",
                     dcc.RadioItems(
                         id="av-op-curva-modo", value="portfolio",
                         className="pg-tf op-tfs",
                         options=[{"label": "Portfólio",
                                   "value": "portfolio"},
                                  {"label": "Por variante",
                                   "value": "variante"}]),
                     dcc.Dropdown(id="av-op-curva-variante",
                                  clearable=False, disabled=True,
                                  className="dd op-dd-curva",
                                  placeholder="variante…")),
        html.P(id="av-op-curva-nota", className="op-curva-nota"),
        html.Div(dash_tvlwc.Tvlwc(id="av-op-curva", series=[],
                                  chartOptions=CHART_CURVA,
                                  height="100%"),
                 id="av-op-curva-caixa", className="op-curva"),
        html.Div([
            html.Span([html.I(className="op-traco",
                              style={"borderColor": T.POS}), "papel"]),
            html.Span([html.I(className="op-traco op-traco-ponto",
                              style={"borderColor": "rgba(34,228,255,.55)"}),
                       "faixa p10–p90 (por variante)"]),
            html.Span([html.I(className="op-traco op-traco-tracejado",
                              style={"borderColor": T.MUTED}),
                       "mediana esperada"]),
        ], className="op-curva-legenda"),
    ], className="op-aval-curva")


# as abas de baixo: (valor, rótulo, ícone)
ABAS = (("operacoes", "Operações", "list"), ("diario", "Diário", "scroll-text"),
        ("avaliacao", "Avaliação", "scale"))


def _aba_operacoes():
    """Três tabelas, nessa ordem (protótipo v2): Real, Demo e Papel. A real
    e a demo vêm do banco pelo mesmo callback (`ordens_op`); o papel tem o
    filtro de variante."""
    return html.Section([
        OR.subtitulo("Real", "Operações do dia na conta real, com a mesma régua "
                     "da demo. Derrapagem = diferença para o preço do papel, por "
                     "ponta, em ticks."),
        html.Div(id="av-op-real-operacoes", className="op-tabela-caixa ord-caixa"),
        OR.subtitulo("Demo", "Operações do dia na conta demo. Derrapagem = "
                     "diferença para o preço do papel, por ponta, em ticks."),
        html.Div(id="av-op-ord-operacoes", className="op-tabela-caixa ord-caixa"),
        OR.subtitulo("Papel", "Operações do dia no papel, de todas as "
                     "variantes, ligadas ou não.",
                     dcc.Dropdown(id="av-op-filtro", value="todas",
                                  clearable=False, className="dd op-dd-filtro",
                                  options=[{"label": "Todas as variantes",
                                            "value": "todas"}])),
        html.Div(id="av-op-operacoes", className="op-operacoes op-tabela-caixa"),
    ], className="op-pane op-pane-operacoes")


def _aba_diario():
    """Uma tabela só (rascunho v4): Hora | Variante | O que aconteceu. Os
    alertas do papel, quando há, entram no topo dela em âmbar ou rosa; o
    filtro "Só problemas" fica acima, à direita."""
    return html.Section([
        html.Div([
            html.Span([html.I(className="op-dia-amostra"), "alerta do papel",
                       dica("Linhas em âmbar ou rosa no topo da tabela: "
                            "pregões pulados, interrompidos, não conferidos, "
                            "planos gravados mesmo assim e candles que "
                            "mudaram. Bom: nenhuma. Ruim: o mesmo alerta "
                            "vários dias.")],
                      className="op-dia-legenda"),
            dcc.RadioItems(
                id="av-op-ord-diario-filtro", value="tudo",
                className="pg-tf op-tfs",
                options=[{"label": "Tudo", "value": "tudo"},
                         {"label": "Só problemas", "value": "problemas"}]),
        ], className="op-dia-barra"),
        html.Div([
            html.Div([html.Span("Hora"), html.Span("Conta · variante"),
                      html.Span(["O que aconteceu",
                                 dica("Tudo o que a automação fez hoje na "
                                      "conta demo, do mais novo para o mais "
                                      "antigo.")])],
                     className="ord-ev op-dia-cab"),
            html.Div(id="av-op-alertas", className="op-alertas"),
            html.Div(id="av-op-ord-diario", className="op-dia-linhas"),
        ], className="ord-diario"),
    ], className="op-pane op-pane-diario")


def bloco():
    """A sub-tela inteira; começa escondida.

    Ordem (rascunho v4): saúde, chamados, a linha do portfólio, a faixa de
    sete números, variantes | gráfico, Posições abertas e as abas
    Operações | Diário | Avaliação. As três abas ficam sempre montadas e só
    o CSS mostra uma: `dcc.Tabs` desmontaria a fechada, recriaria a curva e
    perderia a rolagem das caixas fixas."""
    return html.Div([
        # pulso de 2 s, só com a sub-tela na frente: lê o estado.json
        dcc.Interval(id="av-op-intervalo", interval=2000, disabled=True),
        # `papel.calculado_em` já desenhado: só ele muda manda reler o banco
        dcc.Store(id="av-op-versao"),
        # `ordens.ordens_em` já desenhado: idem para o diário das ordens
        dcc.Store(id="av-op-ord-versao"),
        # o que o banco sabe da demo de hoje e o pulso usa nos números
        # (realizado, papel das mesmas operações, atraso médio)
        dcc.Store(id="av-op-ord-dados"),
        # "Encerrar posição" pedindo confirmação ({chave, em})
        dcc.Store(id="av-op-ord-armado", data=None),
        # chamados escondidos ("Manter e acompanhar"), só nesta tela
        dcc.Store(id="av-op-ord-escondidos", data=[], storage_type="local"),
        # hora (epoch) dos comandos "Encerrar posição" enviados
        dcc.Store(id="av-op-ord-enviados", data=[]),
        # variante cujo editor de contratos está aberto
        dcc.Store(id="av-op-ord-ctr-alvo"),
        # a conta do editor de contratos aberto ("demo" ou "real")
        dcc.Store(id="av-op-ord-ctr-conta", data="demo"),
        # o último candle gravado já desenhado (série refeita só com novo)
        dcc.Store(id="av-op-ultimo"),
        # o último candle da série, para o pulso montar o 5/15 min sem banco
        dcc.Store(id="av-op-base"),
        # ação pedindo confirmação (segundo clique executa)
        dcc.Store(id="av-op-armado", data=None),
        # sobe a cada ação: redesenha cabeçalho e variantes
        dcc.Store(id="av-op-acao-versao", data=0),
        # variantes escondidas no gráfico pela legenda
        dcc.Store(id="av-op-ocultas", data=[]),
        # nome e cor de cada variante, para a legenda sem reler o banco
        dcc.Store(id="av-op-vars", data=[]),
        # posição a reaplicar no gráfico do dia e na curva depois que eles
        # ganham largura (ver callbacks_operacao)
        dcc.Store(id="av-op-enquadrar"),
        dcc.Store(id="av-op-curva-enquadrar"),
        # a faixa de saúde (av-op-ord-saude) mora no cabeçalho de Ao vivo
        # (ao_vivo_panel.painel), junto do título e das sub-telas
        html.Div(id="av-op-ord-chamados", className="ord-chamados-caixa"),
        html.Section([
            html.Div([
                html.Div([
                    # a caixa do seletor (rascunho v4 `.sel`): pasta, nome e
                    # a seta, do tamanho do nome. Sem rótulo visível: o ícone
                    # faz o papel dele e "Portfólio" fica no title
                    html.Div([icone("briefcase", classe="op-pf-ic"),
                              dcc.Dropdown(id="av-op-portfolio", clearable=False,
                                           searchable=False, persistence=True,
                                           persistence_type="local",
                                           className="op-dd-pf",
                                           placeholder="escolha o portfólio…")],
                             className="op-sel", title="Portfólio"),
                    html.Div(id="av-op-cabecalho", className="op-cab-info"),
                    # saída do pulso: etiquetas de situação e a hora do papel
                    html.Div(id="av-op-situacao", className="op-situacao"),
                ], className="op-cab-esq"),
                html.Div([
                    html.Div(id="av-op-botoes", className="op-botoes"),
                ], className="op-cab-dir"),
            ], className="op-cab"),
            # retorno das ações (clique duplo): some quando vazio
            html.Div(id="av-op-aviso", className="av-aviso"),
        ], className="panel op-topo"),
        # uma faixa só com os seis números: as células dos dois callbacks
        # (demo pelo pulso, papel pelo redesenho) viram itens da mesma grade
        html.Div([
            html.Div(id="av-op-ord-numeros", className="ord-numeros-caixa"),
            html.Div(id="av-op-kpis", className="op-kpis"),
        ], className="panel op-tira"),
        html.Div([
            html.Section([
                _sec_head("Variantes", "As variantes deste portfólio: o "
                          "resultado de hoje e o acumulado do papel de cada "
                          "uma. O ponto é a cor dela no gráfico. No fim da "
                          "linha, pausar ou ligar a variante (dois cliques) "
                          "e o lápis dos contratos na conta demo.",
                          ic="layers"),
                html.Div([html.Div(id="av-op-var-cab"),
                          html.Div(id="av-op-var-lista", className="op-var-lista"),
                          # repete o Pior momento da faixa: escondido no CSS
                          # (a saída do redesenho continua)
                          html.Div(id="av-op-risco")],
                         id="av-op-variantes", className="op-variantes"),
                OR.editor_contratos(),
            ], className="panel op-painel-var"),
            html.Section([
                _sec_head("WIN$N ao vivo", "Role para dar zoom; arraste para "
                          "voltar no dia. " + _CHAVE,
                          dcc.RadioItems(
                              id="av-op-tf", value="M1", className="pg-tf op-tfs",
                              options=[{"label": "1 min", "value": "M1"},
                                       {"label": "5 min", "value": "M5"},
                                       {"label": "15 min", "value": "M15"}]),
                          # só ícone (rascunho v4); o nome no title
                          html.Button("", id="av-op-agora", n_clicks=0,
                                      title="Voltar para agora",
                                      className="btn-ghost op-bt op-bt-ic "
                                                "op-bt-agora",
                                      **{"aria-label": "Voltar para agora"}),
                          html.Button("", id="av-op-cheia", n_clicks=0,
                                      title="Tela cheia",
                                      className="btn-ghost op-bt op-bt-ic "
                                                "op-bt-cheia",
                                      **{"aria-label": "Tela cheia"}),
                          classe="pg-grafico-head", ic="chart-candlestick"),
                html.Div(dash_tvlwc.Tvlwc(id="av-op-grafico", series=[],
                                          chartOptions=T.CHART_OPTIONS,
                                          height="100%"),
                         id="av-op-grafico-caixa", className="pg-grafico op-grafico"),
                # As caixas que rolam (chips, linhas, tabelas) são fixas no
                # layout e só o conteúdo delas é trocado: recriadas a cada
                # releitura do papel (uma por minuto), a rolagem voltava ao
                # topo no meio da leitura.
                html.Div(html.Div(html.Div(id="av-op-chips", className="op-chips"),
                                  className="op-legenda-in"),
                         id="av-op-legenda", className="op-legenda"),
            ], className="panel op-painel-grafico"),
        ], className="op-grade"),
        html.Section([
            _sec_head("Posições abertas", "Posições na corretora agora, da conta "
                      "real e da demo (a coluna Conta diz qual), conferidas com o "
                      "que o papel quer. Posição agora = contratos em aberto "
                      "somando as variantes: comprado soma, vendido subtrai. "
                      "Variantes em lados opostos se anulam aqui.",
                      ic="crosshair"),
            html.Div(id="av-op-ord-posicoes", className="op-tabela-caixa ord-caixa"),
        ], className="panel op-painel-pos"),
        html.Section([
            dcc.RadioItems(id="av-op-aba", value="operacoes", persistence=True,
                           persistence_type="local", className="op-abas",
                           options=[{"label": html.Span([icone(ic), rot],
                                                        className="op-aba-rot"),
                                     "value": valor}
                                    for valor, rot, ic in ABAS]),
            html.Div([
                _aba_operacoes(),
                _aba_diario(),
                OR.avaliacao(None, None, curva=_curva_papel_esperado(),
                             comparativo=html.Div(id="av-op-comparativo",
                                                  className="op-cmp-caixa")),
            ], id="av-op-abas", className="op-abas-corpo op-aba-operacoes"),
        ], className="panel op-painel-abas"),
    ], id="av-bloco-operacao", className="op-bloco", style={"display": "none"})
