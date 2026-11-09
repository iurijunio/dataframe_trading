"""Estratégias: peças comuns e o painel."""
from __future__ import annotations

from datetime import date

from dash import dcc, html

from core import plano as _plano

from .. import operacao_panel as OP
from .. import pregao_panel as PG
from ..cartao import brl, dica
from ..icones import icone


# ------------------------------------------------------------ peças comuns
def _secao(titulo, nota, *filhos):
    """Título da seção; a explicação dela vai no (?), sem frase visível."""
    cab = [html.H3(titulo, className="panel-title av-sec-titulo")]
    if nota:
        cab.append(dica(nota))
    return html.Section([
        html.Div(cab, className="av-sec-head"),
        html.Div(list(filhos), className="av-corpo"),
    ], className="panel")


def _etiqueta(texto, tom="cinza", explica=None):
    """Pílula de situação. tom: verde, cinza, ambar, rosa, info."""
    filhos = [texto] + ([dica(explica)] if explica else [])
    return html.Span(filhos, className=f"av-tag av-tag-{tom}")


def _kv(pares, linhas=False):
    """Grade de rótulo → valor. `linhas=True`: um par por linha (rótulo à
    esquerda, valor à direita), para os mini cartões da ficha."""
    itens = []
    for par in pares:
        rotulo, valor = par[0], par[1]
        explica = par[2] if len(par) > 2 else None
        r = [rotulo] + ([dica(explica)] if explica else [])
        itens.append(html.Div([html.Span(r, className="av-kv-r"),
                               html.Span(valor, className="av-kv-v")],
                              className="av-kv-item"))
    return html.Div(itens, className="av-kv-linhas" if linhas else "av-kv")


def _rotulado(rotulo, campo, explica=None, classe=""):
    """Campo de formulário com rótulo visível (placeholder não é rótulo)."""
    r = [rotulo] + ([dica(explica)] if explica else [])
    return html.Div([html.Label(r, className="av-campo-rot"), campo],
                    className=("av-campo " + classe).strip())


def _plural(n, um, varios):
    return f"{n} {um if n == 1 else varios}"


def _chip(texto, tipo):
    """Chip de identidade da conta ou da fase: laranja = real, ciano = demo,
    violeta = papel. Não é estado (verde/cinza/âmbar/rosa): é quem é."""
    return html.Span(texto, className=f"av-chip av-chip-{tipo}")


# ------------------------------------------------------------------ painel
def painel():
    return html.Div([
        # um número que sobe a cada ação: é ele que manda redesenhar
        dcc.Store(id="av-versao", data=0),
        # o botão que está pedindo confirmação (segundo clique executa)
        dcc.Store(id="av-armado", data=None),
        # a hora (time.time) em que o primeiro clique armou: a confirmação
        # vale poucos segundos
        dcc.Store(id="av-armado-em", data=None),
        # a variante com a ficha aberta
        dcc.Store(id="av-aberta", data=None),
        html.Section([
            html.Div([html.H2("Ao vivo", className="panel-title av-titulo"),
                      dcc.RadioItems(
                          id="av-subtela", value="estrategias",
                          className="av-subtelas",
                          options=[{"label": "Estratégias",
                                    "value": "estrategias"},
                                   {"label": "Pregão", "value": "pregao"},
                                   {"label": "Operação",
                                    "value": OP.SUBTELA}]),
                      # saída do pulso da Operação; o CSS só a mostra nela
                      html.Div(id="av-op-ord-saude",
                               className="ord-saude-caixa")],
                     className="panel-head"),
        ], className="panel av-topo"),
        html.Div(_estrategias(), id="av-bloco-estrategias",
                 className="av-bloco"),
        PG.bloco(),
        OP.bloco(),
    ], id="painel-aovivo", className="modo-bloco", style={"display": "none"})


def _estrategias() -> list:
    """Sub-tela Estratégias: números do topo, portfólios, variantes, contas e
    arrumação. Sem passo a passo nem frases-subtítulo: a explicação de cada
    seção está no (?) do título."""
    return [
        html.Section([
            html.Div([
                html.Div(id="av-resumo", className="av-resumo"),
                html.Div(id="av-aviso", className="av-aviso"),
            ], className="av-corpo"),
        ], className="panel av-topo-est"),
        _secao("Portfólios", "Ligar um portfólio libera as variantes dele "
               "para o papel. Verde = ligado; cinza = desligado.",
               html.Div(id="av-portfolios", className="av-lista")),
        _secao("Variantes", "Cada variante de cada portfólio. Verde pode "
               "rodar; cinza está parada e diz por quê. Em “Ver ficha” você "
               "vê de onde veio o plano.",
               html.Div(id="av-variantes", className="av-lista-col")),
        _secao("Contas", "Contas do MT5 onde as ordens vão cair a partir da "
               "fase demo. Na fase papel nada é enviado.",
               html.Div(id="av-contas", className="av-lista-col"),
               # Nova conta (abre o formulário) e Puxar do MT5 lado a lado, abaixo
               # da tabela, como no v2. O aviso do Puxar fica fora do formulário:
               # dentro dele sumiria com o formulário fechado.
               html.Div([
                   html.Details([
                       html.Summary([icone("plus", pequeno=True), "Nova conta"],
                                    className="btn-ghost btn-sm av-btn-sec av-nova-conta-btn"),
                       html.Div([
                           html.Div([
                               _rotulado("Nome da conta", dcc.Input(
                                   id="av-conta-nome", type="text", className="inp",
                                   placeholder="ex.: Demo XP"), classe="av-campo-nome"),
                               _rotulado("Tipo", dcc.Dropdown(
                                   id="av-conta-tipo", className="dd av-dd-tipo",
                                   clearable=False, value="demo", searchable=False,
                                   options=[{"label": "demo", "value": "demo"},
                                            {"label": "real", "value": "real"}])),
                               _rotulado("Limite de perda diária (R$)", dcc.Input(
                                   id="av-conta-limite", type="text",
                                   inputMode="numeric", className="inp",
                                   placeholder="opcional"),
                                   explica="O limite diário da mesa proprietária. "
                                           "Deixe vazio se a conta não tiver.",
                                   classe="av-campo-limite"),
                           ], className="av-form-linha"),
                           html.Div([
                               _rotulado("Número da conta", dcc.Input(
                                   id="av-conta-login", type="text",
                                   inputMode="numeric", className="inp",
                                   placeholder="ex.: 1234567"),
                                   explica="O número que aparece no MT5, no topo da "
                                           "janela. A senha não é guardada: você faz "
                                           "login no próprio MT5.",
                                   classe="av-campo-limite"),
                               _rotulado("Servidor", dcc.Input(
                                   id="av-conta-servidor", type="text",
                                   className="inp",
                                   placeholder="ex.: ClearInvestimentos-DEMO"),
                                   classe="av-campo-nome"),
                               _rotulado("Pasta do MT5", dcc.Input(
                                   id="av-conta-terminal", type="text",
                                   className="inp", placeholder="opcional"),
                                   explica="Só se você tiver mais de um MT5 "
                                           "instalado: aponte o terminal64.exe desta "
                                           "conta.",
                                   classe="av-campo-largo"),
                           ], className="av-form-linha"),
                           html.Div(html.Button("Criar conta",
                                                id="av-btn-conta-criar", n_clicks=0,
                                                className="btn-ghost av-btn-principal"),
                                    className="av-campo-botao"),
                       ], className="av-form"),
                   ], className="av-nova-conta"),
                   html.Button([icone("download", pequeno=True), "Puxar do MT5"],
                               id="av-btn-mt5-puxar", n_clicks=0,
                               className="btn-ghost btn-sm av-btn-sec av-btn-puxar"),
                   html.Div(id="av-mt5-aviso", className="av-aviso-mt5"),
               ], className="av-acoes-contas"),
               ),
        _secao("Arrumação", "Planos gravados que ainda não pertencem a "
               "nenhuma variante. Vincule para poder usá-los num portfólio.",
               html.Div(id="av-arrumacao", className="av-lista-col")),
    ]


def resumo_topo(n_pf, n_pf_lig, n_var, n_var_lib, n_arrumar,
                n_contas) -> list:
    """A linha de números do topo: onde a pessoa está no passo a passo."""
    def item(valor, rotulo, tom=""):
        return html.Div([html.Span(valor, className="av-resumo-v"),
                         html.Span(rotulo, className="av-resumo-r")],
                        className=("av-resumo-item " + tom).strip())
    return [
        item(f"{n_pf_lig} de {n_pf}", "portfólios ligados",
             "av-ok" if n_pf_lig else ""),
        item(f"{n_var_lib} de {n_var}", "variantes liberadas",
             "av-ok" if n_var_lib else ""),
        item(str(n_contas), "conta cadastrada" if n_contas == 1
             else "contas cadastradas"),
        item(str(n_arrumar), "plano para arrumar" if n_arrumar == 1
             else "planos para arrumar", "av-atencao" if n_arrumar else ""),
    ]


def _botao(rotulo, acao, alvo, armado, classe="btn-ghost btn-sm", prefixo=None,
           so_icone=False):
    """Botão de ação com dois cliques. `prefixo`: enfeite antes do texto (a
    chave do Envio, o ícone do power). `so_icone`: sem texto, só o `prefixo`,
    com o nome completo no `title`; ao pedir confirmação mostra "Confirmar?"."""
    armado_aqui = armado == f"{acao}:{alvo}"
    texto = "Confirmar?" if armado_aqui else rotulo
    if so_icone and not armado_aqui:
        filhos = prefixo
    else:
        filhos = [prefixo, texto] if prefixo is not None and not armado_aqui else texto
    extra = {"title": rotulo} if so_icone else {}
    return html.Button(filhos,
                       id={"type": "av-acao", "acao": acao, "id": alvo},
                       n_clicks=0,
                       className=classe + (" av-armado" if armado_aqui else "")
                       + (" av-so-icone" if so_icone else ""),
                       **extra)


def _campo_dd(campo, alvo, valor, opcoes, placeholder, classe="dd av-dd"):
    return dcc.Dropdown(id={"type": "av-campo", "campo": campo, "id": alvo},
                        value=valor, options=opcoes, placeholder=placeholder,
                        className=classe, clearable=True)


def _campo_txt(campo, alvo, valor, placeholder, numerico=False):
    return dcc.Input(id={"type": "av-campo", "campo": campo, "id": alvo},
                     value=valor, placeholder=placeholder, type="text",
                     className="inp", **({"inputMode": "numeric"} if numerico else {}))


def _reais(v):
    return "—" if v is None else brl(v)


def _pct(v):
    return "—" if v is None else f"{v:.2f}".replace(".", ",") + "%"


def _disjuntor_texto(d) -> str:
    """O freio do plano em palavras. Aceita campo faltando ou nulo."""
    d = d or {}
    n1, n2 = d.get("nivel1") or {}, d.get("nivel2") or {}
    n = n1.get("perdas_seguidas")
    return (f"reduz para 1 contrato se cair {_reais(n1.get('queda'))} ou após "
            f"{'—' if n is None else n} perdas seguidas · desliga se cair "
            f"{_reais(n2.get('queda'))}")


_EVENTOS = {
    "plano_gravado": "plano gravado", "membro_desligado": "variante pausada",
    "membro_ligado": "variante ligada", "portfolio_ligado": "portfólio ligado",
    "fase_mudou": "mudou de fase", "conta_editada": "conta editada",
    "plano_aposentado": "plano aposentado",
    "plano_vinculado": "plano vinculado",
    "variante_renomeada": "variante renomeada",
    "membro_adicionado": "entrou no portfólio",
    "membro_removido": "saiu do portfólio",
    "portfolio_desligado": "portfólio desligado",
    "portfolio_conta_mudou": "contas do portfólio mudaram",
    "conta_criada": "conta criada", "conta_arquivada": "conta arquivada",
}


_METODOS = {"centroide_mediana": "centroide (mediana)",
            "centroide_media": "centroide (média)", "vizinhanca": "vizinhança",
            "ulcer": "Ulcer", "sharpe": "Sharpe", "drawdown": "drawdown",
            "moda": "moda", "alpha": "alpha",
            "plato_pessimista": "platô pessimista", "consenso": "consenso"}


def _metodo(cod) -> str:
    if not cod:
        return "—"
    return _METODOS.get(cod, str(cod).replace("_", " "))


def _data_iso(v) -> str:
    """Data guardada como texto AAAA-MM-DD, mostrada como DD/MM/AAAA; se não
    for esse formato, mostra o texto como veio."""
    if not v:
        return "—"
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(v)


def _vale_legado(p, prefixo) -> str:
    """Plano antigo sem data de início vale desde o primeiro pregão depois
    de gravado — dizer isso em vez de um travessão."""
    if p.get("vale_a_partir"):
        return f"{prefixo} {_data(p['vale_a_partir'])}"
    if p.get("created_at"):
        return (f"desde {_data(_plano.proximo_dia_util(p['created_at'].date()))}"
                " (primeiro pregão após a gravação)")
    return f"{prefixo} —"


def _data(d, fmt="%d/%m/%Y"):
    return d.strftime(fmt) if d else "—"


def _num(v):
    return "—" if v is None else str(v)
