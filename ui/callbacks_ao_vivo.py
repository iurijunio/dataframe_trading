"""Callbacks da tela Ao vivo. Dois callbacks só: `agir` (todo clique vai
ao core e sobe `av-versao`) e `desenhar` (lê o banco e redesenha). Um
redesenho único evita um callback por botão escrevendo nas mesmas
saídas — que é como se chega a ciclo e a tela congelada sem erro."""
from __future__ import annotations

from dash import Input, Output, html, no_update
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import plano as PL
from core import portfolio as P
from core import variantes as V
from strategies import registry

from .components import ao_vivo_panel as AP


def _modulo(estrategia):
    try:
        return registry.carregar(estrategia)
    except Exception:           # arquivo sumiu ou não carrega: a ficha avisa
        return None


def montar(armado, aberta, hoje=None):
    """As quatro seções da tela, lidas do banco agora."""
    contas = AV.listar_contas(incluir_arquivadas=True)
    ativas = [c for c in contas if not c.get("arquivada_em")]
    pfs = P.listar()
    portfolios = ([AP.cartao_portfolio(p, contas, armado) for p in pfs]
                  or [html.P("nenhum portfólio ainda — crie na tela Portfólio",
                             className="av-nota")])

    linhas = AV.em_operacao(hoje)
    blocos = []
    for rep in AV.repetidas(linhas):
        blocos.append(html.P(
            f"⚠ {rep['variante_nome']} está em {len(rep['portfolios'])} "
            f"portfólios ligados ({', '.join(rep['portfolios'])}) — os "
            "contratos somam na conta", className="av-motivo"))
    atual = None
    for l in linhas:
        if l["portfolio_nome"] != atual:
            atual = l["portfolio_nome"]
            blocos.append(html.H4(atual, className="panel-title"))
        ficha = None
        if aberta == l["ligacao_id"]:
            r = AV.rastreio(l["ligacao_id"], hoje)
            ficha = AP.ficha_rastreio(r, _modulo(l["estrategia"]), armado, hoje)
        blocos.append(AP.cartao_variante(l, armado, ficha))
    variantes = blocos or [html.P("nenhuma variante em portfólio ainda",
                                  className="av-nota")]

    contas_div = ([AP.linha_conta(c, armado) for c in ativas]
                  or [html.P("nenhuma conta cadastrada", className="av-nota")])

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
        op_manter = [{"label": f"plano #{p['plano_id']}", "value": p["plano_id"]}
                     for p in ativos]
        arruma.append(AP.linha_orfao(o, op_var, op_manter, armado))
    arruma = arruma or [html.P("nada a arrumar", className="av-nota")]
    return portfolios, variantes, contas_div, arruma


def register(app):
    @app.callback(
        Output("av-portfolios", "children"), Output("av-variantes", "children"),
        Output("av-contas", "children"), Output("av-arrumacao", "children"),
        Input("modo", "value"), Input("av-versao", "data"),
        Input("av-armado", "data"), Input("av-aberta", "data"),
    )
    def desenhar(modo, _versao, armado, aberta):
        if modo != "aovivo":
            raise PreventUpdate
        return montar(armado, aberta)
