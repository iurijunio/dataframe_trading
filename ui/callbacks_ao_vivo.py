"""Callbacks da tela Ao vivo. Dois callbacks só: `agir` (todo clique vai
ao core e sobe `av-versao`) e `desenhar` (lê o banco e redesenha). Um
redesenho único evita um callback por botão escrevendo nas mesmas
saídas — que é como se chega a ciclo e a tela congelada sem erro."""
from __future__ import annotations

import re
import time

import duckdb
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import db_manager as db
from core import mt5_source
from core import papel_backtest as PB
from core import plano as PL
from core import portfolio as P
from core import variantes as V
from strategies import registry

from . import callbacks_operacao as OPC
from . import data as D
from .callbacks_ordens import ARMADO_VALE_S, TENTATIVAS_BANCO
from .components import ao_vivo_panel as AP


def _modulo(estrategia):
    try:
        return registry.carregar(estrategia)
    except Exception:           # arquivo sumiu ou não carrega: a ficha avisa
        return None


# o segundo clique confirma: ligar põe estratégia para rodar, aposentar e
# arquivar não se desfazem pela tela. Desligar/pausar são imediatos — o
# caminho seguro não pede confirmação.
_DUPLO = {"pf-ligar": "confirme: clique de novo para LIGAR o portfólio",
          "plano-aposentar": "confirme: clique de novo para aposentar o plano "
                             "(ele sai de vigor no próximo pregão)",
          "conta-arquivar": "confirme: clique de novo para arquivar a conta",
          "vincular": "confirme: clique de novo para vincular — o plano que "
                      "não ficar será aposentado no próximo pregão",
          "fase-demo": "confirme: clique de novo para PROMOVER a variante à "
                       "fase demo",
          "fase-papel": "confirme: clique de novo para VOLTAR ao papel — isso "
                        "encerra a posição aberta, se houver",
          "envio-ligar": "confirme: clique de novo para LIGAR o envio de "
                         "ordens na conta demo",
          "envio-desligar": "confirme: clique de novo para DESLIGAR o envio "
                            "de ordens"}


_ERRO_LIMITE = ("limite de perda diária inválido: digite só o valor "
                "em reais (ex.: 500 ou 1.500,00)")


def _numero(texto):
    """Limite em reais: "1.500,50", "1500,5", "1500.5", "1500" ou vazio
    (None). Só aceita formas sem ambiguidade — "1,500.50" poderia ser lido
    como 1,5 e um limite de mesa errado é dinheiro real. Não-número e
    zero/negativo viram recusa; nunca 'sem limite' por engano."""
    if texto is None or not str(texto).strip():
        return None
    limpo = str(texto).replace("R$", "").replace(" ", "")
    if re.fullmatch(r"\d+", limpo) or re.fullmatch(r"\d+\.\d{1,2}", limpo):
        valor = float(limpo)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", limpo) or re.fullmatch(r"\d+,\d{1,2}", limpo):
        valor = float(limpo.replace(".", "").replace(",", "."))
    else:
        raise ValueError(_ERRO_LIMITE)
    if valor <= 0:
        raise ValueError("o limite de perda diária precisa ser maior que zero")
    return valor


_ERRO_LOGIN = "número da conta deve ter só números"


def _login(texto):
    """Número da conta digitado: só dígitos. Vazio vira None."""
    if texto is None or not str(texto).strip():
        return None
    t = str(texto).strip()
    if not t.isascii() or not t.isdigit():
        raise ValueError(_ERRO_LOGIN)
    return int(t)


def puxar(terminal, nome_atual):
    """Lê a conta do MT5 aberto. Devolve (login, servidor, tipo, nome, aviso);
    em falha, no_update nos campos e a mensagem no aviso. MT5Error é
    RuntimeError, mas não é 'banco ocupado': por isso é tratado aqui."""
    try:
        d = mt5_source.ler_conta((terminal or "").strip() or None)
    except mt5_source.MT5Error as e:
        return no_update, no_update, no_update, no_update, str(e)
    nome = (no_update if (nome_atual or "").strip()
            else f"{d['corretora'] or d['servidor']} {d['tipo']} {d['login']}")
    return (str(d["login"]), d["servidor"], d["tipo"], nome,
            f"lido do MT5: conta {d['login']} ({d['tipo']}, informado pela "
            "corretora) — confira e clique em Criar conta")


def _conta_demo(pid) -> dict | None:
    """A conta demo (não arquivada) do portfólio, com o limite e o Envio, ou
    None. Espera pouco pelo banco: ocupado vira RuntimeError."""
    with db.connect(read_only=True, tentativas=TENTATIVAS_BANCO) as con:
        r = con.execute(
            "SELECT c.conta_id, c.nome, c.limite_perda_dia, "
            "coalesce(c.envio_ligado, false) FROM portfolios p JOIN contas c "
            "ON c.conta_id = p.conta_demo_id WHERE p.portfolio_id = ? "
            "AND c.arquivada_em IS NULL", [pid]).fetchone()
    return None if r is None else dict(zip(
        ("conta_id", "nome", "limite", "envio"), r))


def _executar(nome, alvo, campos) -> str:
    c = lambda campo: campos.get((campo, alvo))
    if nome in ("fase-demo", "fase-papel"):
        fase = "demo" if nome == "fase-demo" else "papel"
        AV.mudar_fase(alvo, fase, tentativas=TENTATIVAS_BANCO)
        return ("variante promovida para a demo — as ordens saem quando o "
                "Envio de ordens do portfólio estiver ligado"
                if fase == "demo" else
                "variante de volta ao papel — a posição aberta, se houver, "
                "é encerrada pela captura")
    if nome == "contratos-salvar":
        gravou, msg = OPC.salvar_editor(alvo, c("contratos"))
        if not gravou:
            raise ValueError(msg)
        return msg
    if nome == "pf-limite":
        conta = _conta_demo(alvo)
        if conta is None:
            raise ValueError("escolha a conta demo do portfólio antes de "
                             "definir o limite")
        limite = _numero(c("pf-limite"))
        if limite is None and conta["envio"]:
            # tirar o limite desliga o envio no core, e isso encerra posições
            # sem os dois cliques: aqui o caminho é o botão Desligar envio
            raise ValueError("para tirar o limite, desligue o envio de "
                             "ordens antes")
        AV.editar_conta(conta["conta_id"], tentativas=TENTATIVAS_BANCO,
                        limite_perda_dia=limite)
        return "limite de perda do dia salvo"
    if nome == "pf-ligar":
        AV.ligar_portfolio(alvo)
        return ("portfólio ligado — as variantes ficam liberadas para o papel "
                "(o robô de papel ainda não existe)")
    if nome == "pf-desligar":
        AV.desligar_portfolio(alvo)
        return "portfólio desligado"
    if nome == "pf-contas":
        AV.definir_contas(alvo, c("conta-demo"), c("conta-real"))
        return "contas do portfólio salvas"
    if nome == "membro-ligar":
        AV.ligar_membro(alvo)
        return "variante ligada"
    if nome == "membro-desligar":
        AV.desligar_membro(alvo)
        return "variante pausada"
    if nome == "conta-criar":
        AV.criar_conta(c("conta-nome"), c("conta-tipo"),
                       _numero(c("conta-limite")), login=_login(c("conta-login")),
                       servidor=c("conta-servidor"),
                       terminal=c("conta-terminal"))
        return "conta criada"
    if nome == "conta-salvar":
        AV.editar_conta(alvo, nome=c("conta-nome"),
                        limite_perda_dia=_numero(c("conta-limite")),
                        login=_login(c("conta-login")),
                        servidor=c("conta-servidor"),
                        terminal=c("conta-terminal"))
        return "conta salva"
    if nome == "conta-arquivar":
        AV.arquivar_conta(alvo)
        return "conta arquivada"
    if nome == "plano-aposentar":
        if not PL.aposentar(alvo):
            raise ValueError(f"plano #{alvo} não existe")
        d = PL.detalhes(alvo)
        return f"plano #{alvo} sai de vigor em {d['aposentado_em']:%d/%m/%Y}"
    if nome == "renomear":
        V.renomear(alvo, c("renomear"))
        return "variante renomeada"
    if nome == "vincular":
        var = c("vincular-variante")
        if var is None:
            raise ValueError("escolha a variante antes de vincular")
        manter = c("vincular-manter")
        AV.vincular_plano(alvo, int(var),
                          manter_plano_id=int(manter) if manter else None)
        return f"mineração #{alvo} vinculada à variante"
    raise ValueError(f"ação desconhecida: {nome}")


def _envio(nome, alvo, armado, posicoes) -> tuple[str | None, str]:
    """Ligar/desligar o Envio da conta demo do portfólio `pid`. O texto dos
    dois cliques e as recusas são os da tela Operação (`OPC.acao`): um aviso
    só, em qualquer das duas telas. Devolve (armado, aviso)."""
    pid, cid = (int(x) for x in str(alvo).split(":"))
    if nome == "envio-ligar":
        # ligar precisa do banco de qualquer jeito; desligar NÃO lê nada
        # antes de escrever o comando (o banco ocupado é justo quando importa)
        conta = _conta_demo(pid)
        if conta is None or conta["conta_id"] != cid:
            return None, ("escolha a conta demo do portfólio antes de mexer "
                          "no envio")
        if not (conta["limite"] or 0) > 0:
            # antes de armar: não adianta pedir confirmação de algo que o
            # core recusa
            return None, "cadastre o limite antes de ligar o envio de ordens"
    chave = f"{nome}:{alvo}"
    novo, aviso, _ = OPC.acao(nome, cid, f"{nome}:{cid}" if armado == chave
                              else None, posicoes)
    return (chave if novo else None), aviso


def acao(nome, alvo, campos, armado, aberta, *, posicoes=None,
         armado_em=None, agora_s=None):
    """Um clique da tela. Devolve (armado, aberta, aviso).

    `armado_em`/`agora_s`: a confirmação vale `ARMADO_VALE_S` s, conferida no
    SERVIDOR (como nas outras telas): um "Confirmar?" esquecido não executa.
    `posicoes`: as da automação (estado.json), para o aviso do desligar."""
    if nome == "abrir":
        return None, (None if aberta == alvo else alvo), ""
    chave = f"{nome}:{alvo}"
    if (armado_em is not None and agora_s is not None
            and not 0 <= agora_s - float(armado_em) <= ARMADO_VALE_S):
        armado = None
    if nome in ("envio-ligar", "envio-desligar"):
        try:
            novo, aviso = _envio(nome, alvo, armado, posicoes)
        except (duckdb.Error, RuntimeError):
            return None, aberta, "banco ocupado, tente de novo"
        return novo, aberta, aviso
    if nome in _DUPLO and armado != chave:
        return chave, aberta, _DUPLO[nome]
    try:
        aviso = _executar(nome, alvo, campos)
    except ValueError as e:
        aviso = str(e)
    except (RuntimeError, duckdb.Error):    # connect_write desistiu: mineração gravando
        aviso = "banco ocupado, tente de novo"
    return None, aberta, aviso


def ordens_da_ficha(lig) -> dict | None:
    """O que a ficha mostra das ordens: contratos da demo, o selo papel ×
    backtest e o que barra (ou merece atenção) na promoção. None = banco
    ocupado: a ficha avisa em vez de congelar a tela."""
    try:
        with db.connect(read_only=True, tentativas=TENTATIVAS_BANCO) as con:
            r = con.execute("SELECT contratos_demo FROM portfolio_membros "
                            "WHERE ligacao_id = ?", [lig]).fetchone()
            situacao = PB.situacao(con, lig)
        restricoes = AV.restricoes_para_demo(lig, tentativas=TENTATIVAS_BANCO)
    except (duckdb.Error, RuntimeError):
        return None
    return {"contratos_demo": None if r is None or r[0] is None else int(r[0]),
            "situacao": situacao, "restricoes": restricoes}


def custo_ficha(lig, valor):
    """A prévia do custo de um stop com os contratos digitados: a mesma da
    tela Operação (`OPC.custo_editor`)."""
    return OPC.custo_editor(lig, valor)


def _envio_das_contas() -> dict[int, bool]:
    try:
        with db.connect(read_only=True, tentativas=TENTATIVAS_BANCO) as con:
            return {int(i): bool(e) for i, e in con.execute(
                "SELECT conta_id, coalesce(envio_ligado, false) FROM contas"
            ).fetchall()}
    except (duckdb.Error, RuntimeError):
        return {}


def montar(armado, aberta, hoje=None, com_resumo=False):
    """As quatro seções da tela, lidas do banco agora. `com_resumo=True`
    devolve antes delas a linha de números do topo."""
    contas = AV.listar_contas(incluir_arquivadas=True)
    ativas = [c for c in contas if not c.get("arquivada_em")]
    envios = _envio_das_contas()
    contas_pf = [{**c, "envio_ligado": envios.get(c["conta_id"], False)}
                 for c in contas]
    pfs = P.listar()
    linhas = AV.em_operacao(hoje)
    liberadas = {}
    for l in linhas:
        liberadas[l["portfolio_id"]] = (liberadas.get(l["portfolio_id"], 0)
                                        + (1 if l["roda"] else 0))
    portfolios = ([AP.cartao_portfolio(p, contas_pf, armado,
                                       liberadas.get(p["portfolio_id"], 0))
                   for p in pfs]
                  or [html.P("nenhum portfólio ainda — crie na tela Portfólio",
                             className="av-vazio")])

    blocos = []
    for rep in AV.repetidas(linhas):
        blocos.append(html.P(
            f"⚠ {rep['variante_nome']} está em {len(rep['portfolios'])} "
            f"portfólios ligados ({', '.join(rep['portfolios'])}) — os "
            "contratos somam na conta", className="av-alerta"))
    atual = None
    for l in linhas:
        if l["portfolio_nome"] != atual:
            atual = l["portfolio_nome"]
            blocos.append(html.Div(
                [html.Span("Portfólio", className="av-grupo-rot"),
                 html.Span(atual, className="av-grupo-nome"),
                 html.Span("ligado" if l["portfolio_ligado"] else "desligado",
                           className="av-tag av-tag-"
                           + ("verde" if l["portfolio_ligado"] else "cinza"))],
                className="av-grupo"))
        ficha = None
        if aberta == l["ligacao_id"]:
            r = AV.rastreio(l["ligacao_id"], hoje)
            ficha = AP.ficha_rastreio(r, _modulo(l["estrategia"]), armado, hoje,
                                      com_ordens=True,
                                      ordens=ordens_da_ficha(l["ligacao_id"]))
        blocos.append(AP.cartao_variante(l, armado, ficha))
    variantes = blocos or [html.P("nenhuma variante em portfólio ainda — "
                                  "adicione variantes na tela Portfólio",
                                  className="av-vazio")]

    contas_div = ([AP.linha_conta(c, armado) for c in ativas]
                  or [html.P("nenhuma conta cadastrada", className="av-vazio")])

    orfaos = AV.planos_sem_variante()
    arruma = []
    # uma linha por mineração: os ids dos campos são o run_id, e dois planos
    # da mesma mineração repetiriam o id (Dash quebra)
    por_run = {}
    for o in orfaos:
        if o["run_id"] in por_run:
            por_run[o["run_id"]]["plano_ids"].append(o["plano_id"])
        else:
            por_run[o["run_id"]] = {**o, "plano_ids": [o["plano_id"]]}
    for o in por_run.values():
        mesmas = V.listar(o["strategy"])
        op_var = [{"label": v["nome"], "value": v["variante_id"]} for v in mesmas]
        ativos = [p for p in PL.listar(apenas_ativos=True)
                  if p["strategy"] == o["strategy"]]
        nomes = {v["variante_id"]: v["nome"] for v in mesmas}

        def rotulo(p, o=o, nomes=nomes):
            if p["variante_id"] is not None:
                origem = ("atual da variante "
                          + nomes.get(p["variante_id"], f"#{p['variante_id']}"))
            elif p["run_id"] == o["run_id"]:
                origem = "desta mineração"
            else:
                origem = "de outra mineração sem variante"
            return (f"plano #{p['plano_id']} · {origem} · gravado "
                    f"{p['created_at']:%d/%m}")
        op_manter = [{"label": rotulo(p), "value": p["plano_id"]}
                     for p in ativos]
        arruma.append(AP.linha_orfao(o, op_var, op_manter, armado))
    arruma = arruma or [html.P("nada a arrumar", className="av-vazio")]
    if not com_resumo:
        return portfolios, variantes, contas_div, arruma
    resumo = AP.resumo_topo(
        n_pf=len(pfs), n_pf_lig=sum(1 for p in pfs if p["ligado"]),
        n_var=len(linhas), n_var_lib=sum(1 for l in linhas if l["roda"]),
        n_arrumar=len(orfaos), n_contas=len(ativas))
    return resumo, portfolios, variantes, contas_div, arruma


def register(app):
    @app.callback(
        Output("av-resumo", "children"),
        Output("av-portfolios", "children"), Output("av-variantes", "children"),
        Output("av-contas", "children"), Output("av-arrumacao", "children"),
        Input("modo", "value"), Input("av-versao", "data"),
        Input("av-armado", "data"), Input("av-aberta", "data"),
    )
    def desenhar(modo, _versao, armado, aberta):
        if modo != "aovivo":
            raise PreventUpdate
        try:
            return montar(armado, aberta, com_resumo=True)
        except (RuntimeError, ValueError) as e:
            # banco ocupado ou dado que não lê: a tela avisa em vez de
            # ficar congelada sem explicação
            motivo = ("banco ocupado" if isinstance(e, RuntimeError)
                      else str(e))
            return (no_update, no_update, [html.P(
                f"não foi possível ler agora: {motivo} — tente de novo",
                className="av-alerta")], no_update, no_update)

    @app.callback(
        Output("av-versao", "data"), Output("av-armado", "data"),
        Output("av-aberta", "data"), Output("av-aviso", "children"),
        Output("av-armado-em", "data"),
        Input({"type": "av-acao", "acao": ALL, "id": ALL}, "n_clicks"),
        Input("av-btn-conta-criar", "n_clicks"),
        State({"type": "av-campo", "campo": ALL, "id": ALL}, "value"),
        State("av-conta-nome", "value"), State("av-conta-tipo", "value"),
        State("av-conta-limite", "value"), State("av-conta-login", "value"),
        State("av-conta-servidor", "value"),
        State("av-conta-terminal", "value"),
        State("av-versao", "data"), State("av-armado", "data"),
        State("av-aberta", "data"), State("av-armado-em", "data"),
        prevent_initial_call=True,
    )
    def agir(_cliques, _criar, _campos, nome, tipo, limite, login, servidor,
             terminal, versao, armado, aberta, armado_em):
        # botão recém-desenhado aparece com n_clicks=0 e dispara o Input de
        # padrão sem ninguém ter clicado: só vale clique de verdade
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        campos = {(s["id"]["campo"], s["id"]["id"]): s.get("value")
                  for s in ctx.states_list[0]}
        if gat == "av-btn-conta-criar":
            campos.update({("conta-nome", 0): nome, ("conta-tipo", 0): tipo,
                           ("conta-limite", 0): limite,
                           ("conta-login", 0): login,
                           ("conta-servidor", 0): servidor,
                           ("conta-terminal", 0): terminal})
            nome_acao, alvo = "conta-criar", 0
        else:
            nome_acao, alvo = gat["acao"], gat["id"]
        agora_s = time.time()
        posicoes = None
        if nome_acao == "envio-desligar":
            posicoes = D.ordens_do_estado(D.estado_captura())["posicoes"]
        armado, aberta, aviso = acao(nome_acao, alvo, campos, armado, aberta,
                                     posicoes=posicoes, armado_em=armado_em,
                                     agora_s=agora_s)
        return ((versao or 0) + 1, armado, aberta, aviso,
                agora_s if armado else None)

    @app.callback(
        Output({"type": "av-ficha-custo", "id": ALL}, "children"),
        Input({"type": "av-campo", "campo": "contratos", "id": ALL}, "value"),
    )
    def prever_custo(_valores):
        """A prévia do custo de um stop, ao sair do campo de contratos."""
        entradas = ctx.inputs_list[0]
        valores = {e["id"]["id"]: e.get("value") for e in entradas}
        return [custo_ficha(o["id"]["id"], valores.get(o["id"]["id"]))
                for o in ctx.outputs_list]

    @app.callback(
        Output("av-conta-login", "value"), Output("av-conta-servidor", "value"),
        Output("av-conta-tipo", "value"), Output("av-conta-nome", "value"),
        Output("av-mt5-aviso", "children"),
        Input("av-btn-mt5-puxar", "n_clicks"),
        State("av-conta-terminal", "value"), State("av-conta-nome", "value"),
        prevent_initial_call=True,
    )
    def puxar_mt5(cliques, terminal, nome):
        if not cliques:
            raise PreventUpdate
        return puxar(terminal, nome)
