"""Tela Ao vivo: seletor no topo entre duas sub-telas.

- Estratégias — o que está (ou vai estar) rodando. Spec:
  docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md §5.
- Pregão — o serviço de captura e o gráfico do dia ao vivo; desenhada em
  `pregao_panel.py`. Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6.
- Operação — o papel do portfólio ao vivo; desenhada em
  `operacao_panel.py`. Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

Só desenha — quem lê o banco é `ui/callbacks_ao_vivo.py` (Estratégias) e
`ui/callbacks_pregao.py` (Pregão). As outras sub-telas (Conta, Histórico)
só entram quando a parte delas existir: tela vazia confunde.

Desenho: cada bloco mostra primeiro o nome e a situação (etiqueta
colorida), depois os detalhes como rótulo → valor. Cores das etiquetas,
iguais na tela inteira: verde = ligado/liberada, cinza = desligado/parada,
âmbar = atenção, rosa = problema.
"""
from __future__ import annotations

from datetime import date

from dash import dcc, html

from core import plano as _plano

from . import ficha as FI
from . import operacao_panel as OP
from . import pregao_panel as PG
from .cartao import brl, dica, etiqueta_mesmo_assim

FASES = {"papel": "papel", "demo": "demo", "real_minimo": "real mínimo",
         "real": "real"}


# ------------------------------------------------------------ peças comuns
def _secao(titulo, nota, *filhos):
    return html.Section([
        html.Div([html.H3(titulo, className="panel-title av-sec-titulo"),
                  html.P(nota, className="av-sec-nota")],
                 className="av-sec-head"),
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


def _passo(n, titulo, texto):
    return html.Li([html.Span(str(n), className="av-passo-n"),
                    html.Div([html.Strong(titulo), html.Span(texto)],
                             className="av-passo-txt")],
                   className="av-passo")


# ------------------------------------------------------------------ painel
def painel():
    return html.Div([
        # um número que sobe a cada ação: é ele que manda redesenhar
        dcc.Store(id="av-versao", data=0),
        # o botão que está pedindo confirmação (segundo clique executa)
        dcc.Store(id="av-armado", data=None),
        # a variante com a ficha aberta
        dcc.Store(id="av-aberta", data=None),
        html.Section([
            html.Div([html.H2("Ao vivo", className="panel-title av-titulo"),
                      dcc.RadioItems(
                          id="av-subtela", value="estrategias",
                          persistence=True, persistence_type="local",
                          className="av-subtelas",
                          options=[{"label": "Estratégias",
                                    "value": "estrategias"},
                                   {"label": "Pregão", "value": "pregao"},
                                   {"label": "Operação",
                                    "value": OP.SUBTELA}])],
                     className="panel-head"),
        ], className="panel av-topo"),
        html.Div(_estrategias(), id="av-bloco-estrategias",
                 className="av-bloco"),
        PG.bloco(),
        OP.bloco(),
    ], id="painel-aovivo", className="modo-bloco", style={"display": "none"})


def _estrategias() -> list:
    """Sub-tela Estratégias: portfólios, variantes, contas e arrumação."""
    return [
        html.Section([
            html.Div([
                html.Ol([
                    _passo(1, "Cadastre a conta do MT5",
                           "Seção Contas, lá embaixo. Ela só passa a ser "
                           "usada na fase demo."),
                    _passo(2, "Ligue o portfólio",
                           "Seção Portfólios. As variantes dele ficam "
                           "liberadas."),
                    _passo(3, "Confira as variantes",
                           "Verde = liberada para o papel. Em “Ver ficha” "
                           "você vê de onde veio o plano."),
                ], className="av-passos"),
                html.Div(id="av-resumo", className="av-resumo"),
                html.Div(id="av-aviso", className="av-aviso"),
            ], className="av-corpo"),
        ], className="panel"),
        _secao("Portfólios", "Ligar um portfólio libera as variantes dele "
               "para o papel.",
               html.Div(id="av-portfolios", className="av-lista")),
        _secao("Variantes", "Cada variante de cada portfólio. Verde pode "
               "rodar; cinza está parada e diz por quê.",
               html.Div(id="av-variantes", className="av-lista-col")),
        _secao("Contas", "Contas do MT5 onde as ordens vão cair a partir da "
               "fase demo.",
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
                       html.Div(html.Button("Puxar do MT5",
                                            id="av-btn-mt5-puxar",
                                            n_clicks=0,
                                            className="btn-ghost btn-sm av-btn-sec"),
                                className="av-campo-botao"),
                       html.Div(id="av-mt5-aviso", className="av-aviso-mt5"),
                   ], className="av-form-linha"),
                   html.Div(html.Button("Criar conta",
                                        id="av-btn-conta-criar", n_clicks=0,
                                        className="btn-ghost av-btn-principal"),
                            className="av-campo-botao"),
               ], className="av-form"),
               html.Div(id="av-contas", className="av-lista-col")),
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


def _botao(rotulo, acao, alvo, armado, classe="btn-ghost btn-sm"):
    armado_aqui = armado == f"{acao}:{alvo}"
    return html.Button("Confirmar?" if armado_aqui else rotulo,
                       id={"type": "av-acao", "acao": acao, "id": alvo},
                       n_clicks=0,
                       className=classe + (" av-armado" if armado_aqui else ""))


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


# -------------------------------------------------------------- portfólios
def cartao_portfolio(p: dict, contas: list[dict], armado,
                     n_liberadas: int | None = None) -> html.Div:
    # conta arquivada ainda gravada no portfólio continua na lista, marcada:
    # senão salvar apagaria a escolha sem ninguém perceber
    def opcoes(tipo):
        return [{"label": c["nome"] + (" (arquivada)" if c.get("arquivada_em")
                                       else ""), "value": c["conta_id"]}
                for c in contas if c["tipo"] == tipo
                and (not c.get("arquivada_em")
                     or c["conta_id"] in (p["conta_demo_id"], p["conta_real_id"]))]
    demo, real = opcoes("demo"), opcoes("real")
    pid = p["portfolio_id"]
    n = p["n_membros"]
    if p["ligado"]:
        estado = _etiqueta("ligado", "verde")
        interruptor = _botao("Desligar portfólio", "pf-desligar", pid, armado,
                             "btn-ghost av-btn-sec")
        explica = "Ligado: as variantes dele que estão ligadas podem rodar."
    else:
        estado = _etiqueta("desligado", "cinza")
        interruptor = _botao("Ligar portfólio", "pf-ligar", pid, armado,
                             "btn-ghost av-btn-principal")
        explica = "Desligado: nenhuma variante dele roda. Ligue para liberar."
    qtd = (_plural(n, "variante", "variantes") if n else "nenhuma variante")
    corpo = [
        html.Div([
            html.Div([html.Span(p["nome"], className="av-nome-fixo"), estado],
                     className="av-cab-esq"),
            interruptor,
        ], className="av-cab"),
        html.P([html.Span(qtd, className="av-qtd"), " · ", explica],
               className="av-texto"),
    ]
    if not n:
        corpo.append(html.P("Este portfólio está vazio. Adicione variantes "
                            "nele na tela Portfólio.", className="av-vazio"))
    if p["ligado"] and n_liberadas == 0:
        corpo.append(html.P("⚠ nenhuma variante deste portfólio está rodando "
                            "— veja o motivo em Variantes",
                            className="av-alerta"))
    corpo.append(html.Div([
        html.Div([html.Span("Contas deste portfólio", className="av-sub-titulo"),
                  dica("Só importam a partir da fase demo: é nelas que as "
                       "ordens vão cair. Na fase papel nada é enviado.")],
                 className="av-sub-head"),
        html.Div([
            _rotulado("Conta demo", _campo_dd(
                "conta-demo", pid, p["conta_demo_id"], demo,
                "escolha…" if demo else "nenhuma conta demo")),
            _rotulado("Conta real", _campo_dd(
                "conta-real", pid, p["conta_real_id"], real,
                "escolha…" if real else "nenhuma conta real")),
            html.Div(_botao("Salvar contas", "pf-contas", pid, armado,
                            "btn-ghost av-btn-sec"),
                     className="av-campo-botao"),
        ], className="av-form-linha"),
    ], className="av-sub"))
    return html.Div(corpo, className="av-cartao av-cartao-pf"
                    + (" av-ligado" if p["ligado"] else ""))


# --------------------------------------------------------------- variantes
def _tom_motivo(motivo) -> str:
    if motivo in ("portfólio desligado", "pausada por você"):
        return "cinza"
    if motivo == "sem plano em vigor":
        return "ambar"
    return "rosa"            # disjuntor, código mudou, código não encontrado


def _aviso_tag(a: str):
    if a.startswith("código não conferido"):
        return _etiqueta("código não conferido", "cinza",
                         "Plano gravado antes de 30/09/2026, quando o app "
                         "ainda não guardava a impressão do código da "
                         "estratégia. Não dá para saber se o código mudou "
                         "depois — isso não impede de rodar.")
    if " — " in a:
        curto = a.split(" — ")[0]
        return _etiqueta(curto, "ambar", a)
    return _etiqueta(a, "ambar")


def cartao_variante(l: dict, armado, ficha=None) -> html.Div:
    lig = l["ligacao_id"]
    plano = l["plano"]
    aberta = ficha is not None
    if l["roda"]:
        situacao = [_etiqueta("liberada", "verde")]
    else:
        situacao = [_etiqueta("parada", _tom_motivo(l["motivo"])),
                    html.Span(l["motivo"], className="av-motivo-peq")]
    if l["ligada"]:
        explica = (None if l.get("portfolio_ligado", True) else
                   "O portfólio está desligado, então ela já está parada. "
                   "Pausar aqui faz ela continuar parada quando você ligar o "
                   "portfólio.")
        interruptor = html.Span(
            [_botao("Pausar variante", "membro-desligar", lig, armado,
                    "btn-ghost btn-sm av-btn-sec")]
            + ([dica(explica)] if explica else []), className="av-com-dica")
    else:
        interruptor = _botao("Ligar variante", "membro-ligar", lig, armado,
                             "btn-ghost btn-sm av-btn-principal")
    ver = html.Button("Fechar ficha ▴" if aberta else "Ver ficha ▾",
                      id={"type": "av-acao", "acao": "abrir", "id": lig},
                      n_clicks=0, className="btn-ghost btn-sm av-btn-ficha"
                      + (" av-aberta" if aberta else ""))
    dias = l["dias_na_fase"]
    pares = [("Estratégia", l["estrategia"]),
             ("Ativo", (plano or {}).get("symbol") or "—"),
             ("Fase", f"{FASES.get(l['fase'], l['fase'])} há "
                      f"{_plural(dias, 'dia', 'dias')}")]
    if plano:
        pares += [("Plano em vigor", f"#{plano['plano_id']}"),
                  ("Pregões com este plano", str(l["pregoes_com_plano"])),
                  ("Reotimizar até", _data(plano["reotimizar_em"]))]
    else:
        pares += [("Plano em vigor", "nenhum")]
    filhos = [
        html.Div([
            html.Div([html.Span(l["variante_nome"], className="av-nome-fixo"),
                      *situacao,
                      # do plano EM VIGOR (`em_operacao`): é ele que opera
                      *([etiqueta_mesmo_assim(plano.get("pendencias"))]
                        if plano and plano.get("gravado_mesmo_assim") else [])],
                     className="av-cab-esq"),
            html.Div([interruptor, ver], className="av-cab-dir"),
        ], className="av-cab"),
        _kv(pares),
    ]
    if l["avisos"]:
        filhos.append(html.Div([html.Span("Avisos", className="av-avisos-rot"),
                                *[_aviso_tag(a) for a in l["avisos"]]],
                               className="av-avisos"))
    if aberta:
        filhos.append(ficha)
    return html.Div(filhos, className="av-cartao av-cartao-var"
                    + (" av-roda" if l["roda"] else "")
                    + (" av-com-ficha" if aberta else ""))


# -------------------------------------------------------------------- ficha
def _etapa(n, titulo, ident, corpo, classe=""):
    cab = [html.Div([html.Span(str(n), className="av-etapa-n"),
                     html.H4(titulo, className="av-etapa-tit")],
                    className="av-etapa-cab")]
    if ident:
        cab.append(html.P(ident, className="av-etapa-id"))
    return html.Div(cab + list(corpo),
                    className=("av-etapa " + classe).strip())


def _sem(texto):
    return html.P(texto, className="av-vazio")


def ficha_rastreio(r: dict, estrategia_mod, armado, hoje=None) -> html.Div:
    hoje = hoje or date.today()
    l, det, mina, w = r["ligacao"], r["plano"], r["mineracao"], r["wfa"]
    vid = l["variante_id"]

    acoes = html.Div([
        html.Span("Ações", className="av-sub-titulo"),
        html.Div([
            _rotulado("Novo nome da variante",
                      _campo_txt("renomear", vid, l["variante_nome"],
                                 "novo nome da variante"),
                      classe="av-campo-nome"),
            html.Div(_botao("Renomear", "renomear", vid, armado,
                            "btn-ghost btn-sm av-btn-sec"),
                     className="av-campo-botao"),
            *([html.Div(html.Span([
                _botao("Aposentar plano", "plano-aposentar", det["plano_id"],
                       armado, "btn-ghost btn-sm av-btn-perigo"),
                dica("Tira o plano de vigor. A variante fica sem plano até "
                     "você gravar outro.")], className="av-com-dica"),
                className="av-campo-botao")]
              if det and det["estado"] == "ativo" else []),
        ], className="av-form-linha"),
    ], className="av-ficha-acoes")

    cab = html.Div([
        html.Div([html.H4("Ficha da variante", className="av-ficha-tit"),
                  html.P("De onde veio o plano, o que ele opera e o que já "
                         "mudou.", className="av-texto")]),
        acoes,
    ], className="av-ficha-cab")
    blocos = [cab]

    alcance = {"plano": None,
               "walk-forward": "chegou até o walk-forward — ainda sem plano gravado",
               "mineração": "chegou até a mineração — ainda sem walk-forward",
               "nada": "ainda não foi minerada"}[r["alcance"]]
    if alcance:
        blocos.append(html.P("⚠ " + alcance, className="av-alerta"))

    etapas = []
    # 1. origem
    if mina:
        etapas.append(_etapa(1, "Origem — mineração",
                             f"mineração #{mina['run_id']} · "
                             f"{mina['nome'] or 'sem nome'}",
                             [_kv([("Data", _data(mina["created_at"])),
                                   ("Combinações testadas",
                                    _num(mina["n_combinacoes"])),
                                   ("Dados reservados a partir de",
                                    _data_iso(mina.get("holdout_de")),
                                    "Período guardado fora da otimização, "
                                    "para o teste final.")], linhas=True)]))
    else:
        etapas.append(_etapa(1, "Origem — mineração", None,
                             [_sem("mineração apagada ou anterior às variantes")]))
    # 2. walk-forward
    if w:
        etapas.append(_etapa(2, "Walk-Forward",
                             f"walk-forward #{w['wfa_id']} · "
                             f"{w['nome'] or 'sem nome'}",
                             [_kv([("Meses de otimização", _num(w["is_meses"])),
                                   ("Meses de teste", _num(w["oos_meses"])),
                                   ("Método de escolha", _metodo(w["inteligencia"])),
                                   ("Lucro fora da amostra", _reais(w["oos_lucro"])),
                                   ("Trades fora da amostra", _num(w["oos_trades"])),
                                   ("Queda máx.", _reais(w["dd_oos"])),
                                   ("Veredito", w["veredito"] or "—")],
                                  linhas=True)]))
    else:
        etapas.append(_etapa(2, "Walk-Forward", None, [_sem("sem walk-forward")]))
    # 3. candidata
    reg = r["candidata"] or {}
    portoes = reg.get("portoes") or []
    n_ok = sum(1 for p in portoes if p.get("ok"))
    lista = html.Div([
        html.Div([html.Span("✔" if p.get("ok") else "✖",
                            className="av-ok" if p.get("ok") else "av-nok"),
                  html.Span(p.get("nome") or "—"),
                  *([html.Span("crítico", className="av-critico")]
                    if p.get("critico") else [])],
                 className="av-portao")
        for p in portoes], className="av-portoes") if portoes else _sem(
            "nenhuma verificação registrada")
    forcado = []
    if det and det.get("gravado_mesmo_assim"):
        forcado = [html.Div(etiqueta_mesmo_assim(det.get("pendencias")))]
    etapas.append(_etapa(3, "Candidata", None, [
        _kv([("Veredito no dia da gravação", reg.get("veredito") or "—")],
            linhas=True),
        *forcado,
        *([html.P(f"{n_ok} de {len(portoes)} verificações aprovadas",
                  className="av-portoes-res "
                  + ("av-ok" if n_ok == len(portoes) else "av-atencao"))]
          if portoes else []),
        lista,
    ]))
    # 4. plano em vigor
    if det:
        cod = r["codigo"]
        conf = ("código confere" if cod["confere"] else
                "⚠ código mudou desde o plano" if cod["confere"] is False else
                "código não conferido (plano anterior a 30/09/2026)")
        vale = det["vale_a_partir"]
        titulo = ("Plano" if not vale or vale <= hoje else
                  f"Plano (ainda não vale — entra em {_data(vale, '%d/%m')})")
        corpo = [
            _kv([("Capital", _reais(det["capital"])),
                 ("Contratos", _num(det["contratos"])),
                 ("Risco por pregão", _pct(det["risco_efetivo_pct"])),
                 ("Em vigor", _vale_legado(det, "a partir de")),
                 ("Reotimizar até", _data(det["reotimizar_em"])),
                 ("Código", conf)]),
            html.Div([
                html.Div([html.Span("Freio do plano", className="av-freio-tit"),
                          dica("É o que reduz ou desliga a estratégia sozinho "
                               "quando ela perde demais.")],
                         className="av-sub-head"),
                html.P(_disjuntor_texto(det.get("disjuntor")),
                       className="av-freio-txt"),
            ], className="av-freio"),
        ]
        if estrategia_mod is not None:
            corpo.append(FI.ficha(estrategia=estrategia_mod,
                                  params=det["params"], perfil=det["profile"],
                                  espaco=(mina or {}).get("espaco") or {}))
        else:
            corpo.append(html.P("código da estratégia não encontrado",
                                className="av-alerta"))
        etapas.append(_etapa(4, titulo, f"plano #{det['plano_id']}", corpo,
                             "av-etapa-larga"))
    # 5. histórico
    def _tom_estado(e):
        return {"ativo": "verde", "aposentado": "cinza"}.get(e, "ambar")
    planos = [html.Div([
        html.Span(f"plano #{p['plano_id']}", className="av-hist-id"),
        _etiqueta(p["estado"], _tom_estado(p["estado"])),
        html.Span(f"gravado {_data(p['created_at'])} · "
                  f"{_vale_legado(p, 'vale de')}"
                  + (f" até {_data(p['aposentado_em'])}"
                     if p['aposentado_em'] else ""), className="av-texto"),
    ], className="av-hist-linha") for p in r["planos"]] or [
        _sem("nenhum plano ainda")]
    eventos = [html.Div([
        html.Span(_data(e["quando"], "%d/%m/%Y %H:%M"), className="av-hist-data"),
        html.Span(_EVENTOS.get(e["tipo"], e["tipo"].replace("_", " "))
                  + (f" · {e['motivo']}" if e["motivo"] else "")),
    ], className="av-hist-linha") for e in r["eventos"][:30]] or [
        _sem("nenhum evento ainda")]
    etapas.append(_etapa(5, "Histórico", None, [
        html.Div([
            html.Div([html.Span("Planos", className="av-sub-titulo"), *planos],
                     className="av-hist-col"),
            html.Div([html.Span("O que aconteceu", className="av-sub-titulo"),
                      *eventos], className="av-hist-col"),
        ], className="av-hist"),
    ], "av-etapa-larga"))
    blocos.append(html.Div(etapas, className="av-etapas"))
    return html.Div(blocos, className="av-ficha")


# ------------------------------------------------------------------- contas
def limite_br(v) -> str:
    """Limite no formato que o campo aceita de volta, sem arredondar:
    1500.5 -> "1.500,50", 500.0 -> "500"."""
    if v is None:
        return ""
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def linha_conta(c: dict, armado) -> html.Div:
    cid = c["conta_id"]
    # sem número e servidor a automação não consegue conferir em qual conta o MT5
    # está logado, então não pode mandar ordem
    faltam = not c.get("login") or not c.get("servidor")
    return html.Div([
        html.Div([_etiqueta(c["tipo"], "ambar" if c["tipo"] == "real" else "info")]
                 + ([_etiqueta("faltam os dados do MT5 — não poderá receber "
                               "ordens", "ambar")] if faltam else []),
                 className="av-conta-tipo"),
        _rotulado("Nome", _campo_txt("conta-nome", cid, c["nome"], "nome"),
                  classe="av-campo-nome"),
        _rotulado("Limite de perda diária (R$)",
                  _campo_txt("conta-limite", cid,
                             limite_br(c["limite_perda_dia"]),
                             "sem limite", numerico=True),
                  classe="av-campo-limite"),
        _rotulado("Número da conta",
                  _campo_txt("conta-login", cid,
                             "" if c.get("login") is None else str(c["login"]),
                             "número no MT5", numerico=True),
                  classe="av-campo-limite"),
        _rotulado("Servidor",
                  _campo_txt("conta-servidor", cid, c.get("servidor") or "",
                             "servidor"),
                  classe="av-campo-nome"),
        _rotulado("Pasta do MT5",
                  _campo_txt("conta-terminal", cid, c.get("terminal") or "",
                             "opcional"),
                  classe="av-campo-largo"),
        html.Div([_botao("Salvar", "conta-salvar", cid, armado,
                         "btn-ghost btn-sm av-btn-sec"),
                  _botao("Arquivar", "conta-arquivar", cid, armado,
                         "btn-ghost btn-sm av-btn-perigo")],
                 className="av-campo-botao av-botoes"),
    ], className="av-form-linha av-conta")


# ---------------------------------------------------------------- arrumação
def _planos_txt(o):
    ids = o.get("plano_ids") or [o["plano_id"]]
    return ("plano " if len(ids) == 1 else "planos ") + ", ".join(f"#{i}" for i in ids)


def linha_orfao(o: dict, opcoes_variante: list[dict],
                opcoes_manter: list[dict], armado) -> html.Div:
    rid = o["run_id"]
    txt = _planos_txt(o)
    varios = len(o.get("plano_ids") or [o["plano_id"]]) > 1
    return html.Div([
        html.Div([html.Div([html.Span(txt[0].upper() + txt[1:],
                                      className="av-nome-fixo"),
                            _etiqueta("sem variante", "ambar")],
                           className="av-cab-esq")], className="av-cab"),
        html.P(("Estes planos não pertencem" if varios else
                "Este plano não pertence") + " a nenhuma variante.",
               className="av-texto"),
        _kv([("Estratégia", o["strategy"]),
             ("Mineração", f"#{rid} · {o['nome'] or 'sem nome'}")]),
        html.Div([
            _rotulado("1. Escolha a variante",
                      _campo_dd("vincular-variante", rid, None,
                                opcoes_variante, "escolha a variante…"),
                      classe="av-campo-largo"),
            _rotulado("2. Se ela já tiver um plano ativo, qual fica?",
                      _campo_dd("vincular-manter", rid, None, opcoes_manter,
                                "deixe vazio se ela não tiver"),
                      explica="Uma variante só pode ter um plano em vigor. "
                              "Escolha qual continua; o outro sai de vigor "
                              "no próximo pregão.",
                      classe="av-campo-largo"),
            html.Div(_botao("Vincular", "vincular", rid, armado,
                            "btn-ghost av-btn-principal"),
                     className="av-campo-botao"),
        ], className="av-form-linha"),
    ], className="av-cartao av-orfao")
