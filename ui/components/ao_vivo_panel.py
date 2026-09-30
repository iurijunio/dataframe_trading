"""Tela Ao vivo › Estratégias: o que está (ou vai estar) rodando.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md §5.
Só desenha — quem lê o banco é `ui/callbacks_ao_vivo.py`. As outras
sub-telas (Pregão, Conta, Histórico) só entram quando a parte delas
existir: tela vazia confunde.
"""
from __future__ import annotations

from datetime import date

from dash import dcc, html

from . import ficha as FI
from .cartao import brl

FASES = {"papel": "papel", "demo": "demo", "real_minimo": "real mínimo",
         "real": "real"}


def _secao(titulo, nota, *filhos):
    return html.Section([
        html.Div([html.H3(titulo, className="panel-title"),
                  html.Span(nota, className="panel-note")],
                 className="panel-head"),
        *filhos,
    ], className="panel")


def painel():
    return html.Div([
        # um número que sobe a cada ação: é ele que manda redesenhar
        dcc.Store(id="av-versao", data=0),
        # o botão que está pedindo confirmação (segundo clique executa)
        dcc.Store(id="av-armado", data=None),
        # a variante com a ficha aberta
        dcc.Store(id="av-aberta", data=None),
        html.Section([
            html.Div([html.H2("Ao vivo", className="panel-title"),
                      html.Span("Estratégias", className="chip av-subtela")],
                     className="panel-head"),
            html.Div(id="av-aviso", className="av-aviso"),
        ], className="panel"),
        _secao("Portfólios", "ligue o portfólio para as variantes dele rodarem "
               "(por enquanto só no papel, sem enviar ordem)",
               html.Div(id="av-portfolios", className="av-lista")),
        _secao("Variantes", "clique no nome para abrir a ficha: de onde veio o "
               "plano, o que ele opera e o que já mudou",
               html.Div(id="av-variantes", className="av-lista-col")),
        _secao("Contas", "contas do MT5 onde as ordens vão cair a partir da "
               "fase demo — o limite de perda diária é da mesa",
               html.Div([
                   dcc.Input(id="av-conta-nome", type="text", className="inp",
                             placeholder="nome da conta (ex.: Demo XP)"),
                   dcc.Dropdown(id="av-conta-tipo", className="dd dd-sm",
                                clearable=False, value="demo",
                                options=[{"label": "demo", "value": "demo"},
                                         {"label": "real", "value": "real"}]),
                   dcc.Input(id="av-conta-limite", type="text",
                             inputMode="numeric", className="inp",
                             placeholder="limite de perda diária (R$, opcional)"),
                   html.Button("Criar conta", id="av-btn-conta-criar",
                               n_clicks=0, className="btn-ghost"),
               ], className="acoes"),
               html.Div(id="av-contas", className="av-lista-col")),
        _secao("Arrumação", "planos ativos que não pertencem a nenhuma "
               "variante — só entram em portfólio depois de vinculados",
               html.Div(id="av-arrumacao", className="av-lista-col")),
    ], id="painel-aovivo", className="modo-bloco", style={"display": "none"})


def _botao(rotulo, acao, alvo, armado, classe="btn-ghost btn-sm"):
    armado_aqui = armado == f"{acao}:{alvo}"
    return html.Button("Confirmar?" if armado_aqui else rotulo,
                       id={"type": "av-acao", "acao": acao, "id": alvo},
                       n_clicks=0, className=classe)


def _campo_dd(campo, alvo, valor, opcoes, placeholder):
    return dcc.Dropdown(id={"type": "av-campo", "campo": campo, "id": alvo},
                        value=valor, options=opcoes, placeholder=placeholder,
                        className="dd dd-sm", clearable=True)


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


def _data(d, fmt="%d/%m/%Y"):
    return d.strftime(fmt) if d else "—"


def cartao_portfolio(p: dict, contas: list[dict], armado) -> html.Div:
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
    estado = (html.Span("ligado", className="av-roda") if p["ligado"]
              else html.Span("desligado", className="av-nota"))
    interruptor = (_botao("Desligar", "pf-desligar", pid, armado) if p["ligado"]
                   else _botao("Ligar", "pf-ligar", pid, armado))
    return html.Div([
        html.Div([html.Span(p["nome"], className="av-nome"), estado,
                  html.Span(f"{p['n_membros']} variante(s)", className="av-nota"),
                  interruptor], className="av-linha"),
        html.Div([_campo_dd("conta-demo", pid, p["conta_demo_id"], demo,
                            "conta demo"),
                  _campo_dd("conta-real", pid, p["conta_real_id"], real,
                            "conta real"),
                  _botao("Salvar contas", "pf-contas", pid, armado)],
                 className="av-linha"),
    ], className="av-cartao" + (" av-ligado" if p["ligado"] else ""))


def cartao_variante(l: dict, armado, ficha=None) -> html.Div:
    lig = l["ligacao_id"]
    plano = l["plano"]
    situacao = (html.Span("roda", className="av-roda") if l["roda"]
                else html.Span(l["motivo"], className="av-motivo"))
    interruptor = (_botao("Pausar", "membro-desligar", lig, armado) if l["ligada"]
                   else _botao("Ligar", "membro-ligar", lig, armado))
    partes = [l["estrategia"],
              (plano or {}).get("symbol") or "—",
              f"Fase: {FASES.get(l['fase'], l['fase'])} há {l['dias_na_fase']} dia(s)",
              (f"plano #{plano['plano_id']} · {l['pregoes_com_plano']} pregão(ões) "
               f"com este plano · reotimizar até {_data(plano['reotimizar_em'])}"
               if plano else "sem plano em vigor")]
    filhos = [html.Div([
        html.Span(l["variante_nome"], className="av-nome",
                  id={"type": "av-acao", "acao": "abrir", "id": lig}, n_clicks=0),
        html.Span(" · ".join(partes), className="av-nota"),
        situacao, interruptor], className="av-linha")]
    if l["avisos"]:
        filhos.append(html.Ul([html.Li(a) for a in l["avisos"]],
                              className="av-avisos"))
    if ficha is not None:
        filhos.append(ficha)
    return html.Div(filhos, className="av-cartao")


def ficha_rastreio(r: dict, estrategia_mod, armado, hoje=None) -> html.Div:
    hoje = hoje or date.today()
    l, det, mina, w = r["ligacao"], r["plano"], r["mineracao"], r["wfa"]
    vid = l["variante_id"]
    blocos = [html.Div([
        _campo_txt("renomear", vid, l["variante_nome"], "novo nome da variante"),
        _botao("Renomear", "renomear", vid, armado),
        *([_botao("Aposentar plano", "plano-aposentar", det["plano_id"], armado)]
          if det and det["estado"] == "ativo" else []),
    ], className="av-linha")]
    alcance = {"plano": None,
               "walk-forward": "chegou até o walk-forward — ainda sem plano gravado",
               "mineração": "chegou até a mineração — ainda sem walk-forward",
               "nada": "ainda não foi minerada"}[r["alcance"]]
    if alcance:
        blocos.append(html.P(alcance, className="av-motivo"))
    # 1. origem
    blocos.append(html.Div([
        html.H4("1. Origem — mineração"),
        html.P(f"mineração #{mina['run_id']} · {mina['nome'] or 'sem nome'} · "
               f"{_data(mina['created_at'])} · {mina['n_combinacoes']} "
               f"combinações testadas · dados reservados a partir de "
               f"{mina.get('holdout_de') or '—'}")
        if mina else html.P("mineração apagada ou anterior às variantes",
                            className="av-nota"),
    ]))
    # 2. walk-forward
    blocos.append(html.Div([
        html.H4("2. Walk-Forward"),
        html.P(f"walk-forward #{w['wfa_id']} · {w['nome'] or 'sem nome'} · "
               f"{w['is_meses'] if w['is_meses'] is not None else '—'} meses de otimização / "
               f"{w['oos_meses'] if w['oos_meses'] is not None else '—'} meses de teste · "
               f"{w['inteligencia'] or '—'} · lucro fora da amostra "
               f"{_reais(w['oos_lucro'])} em {w['oos_trades'] if w['oos_trades'] is not None else '—'} trades · "
               f"queda máx. {_reais(w['dd_oos'])} · veredito "
               f"{w['veredito'] or '—'}")
        if w else html.P("sem walk-forward", className="av-nota"),
    ]))
    # 3. candidata
    reg = r["candidata"] or {}
    blocos.append(html.Div([
        html.H4("3. Candidata"),
        html.P(f"veredito no dia da gravação: {reg.get('veredito') or '—'}"),
        html.Ul([html.Li([html.Span("✔ " if p.get("ok") else "✖ ",
                                    className="av-ok" if p.get("ok") else "av-nok"),
                          p.get("nome") or "—"])
                 for p in reg.get("portoes") or []], className="av-avisos"),
    ]))
    # 4. plano em vigor
    if det:
        cod = r["codigo"]
        conf = ("código confere" if cod["confere"] else
                "⚠ código mudou desde o plano" if cod["confere"] is False else
                "código não conferido (plano anterior a 30/09/2026)")
        corpo = [html.P(
            f"plano #{det['plano_id']} · capital {_reais(det['capital'])} · "
            f"{det['contratos'] if det['contratos'] is not None else '—'} "
            f"contrato(s) · risco por pregão "
            f"{_pct(det['risco_efetivo_pct'])} · vale a partir de "
            f"{_data(det['vale_a_partir'])} · reotimizar até "
            f"{_data(det['reotimizar_em'])} · {conf}")]
        corpo.append(html.P("freio: " + _disjuntor_texto(det.get("disjuntor"))))
        if estrategia_mod is not None:
            corpo.append(FI.ficha(estrategia=estrategia_mod,
                                  params=det["params"], perfil=det["profile"],
                                  espaco=(mina or {}).get("espaco") or {}))
        else:
            corpo.append(html.P("código da estratégia não encontrado",
                                className="av-motivo"))
        vale = det["vale_a_partir"]
        titulo = ("4. Plano" if not vale or vale <= hoje else
                  f"4. Plano (ainda não vale — entra em {_data(vale, '%d/%m')})")
        blocos.append(html.Div([html.H4(titulo), *corpo]))
    # 5. histórico
    blocos.append(html.Div([
        html.H4("5. Histórico"),
        html.Ul([html.Li(
            f"plano #{p['plano_id']} · {p['estado']} · gravado "
            f"{_data(p['created_at'])} · vale de {_data(p['vale_a_partir'])}"
            + (f" até {_data(p['aposentado_em'])}" if p['aposentado_em'] else ""))
            for p in r["planos"]] or [html.Li("nenhum plano ainda")],
            className="av-avisos"),
        html.Ul([html.Li(f"{_data(e['quando'], '%d/%m/%Y %H:%M')} · "
                         f"{_EVENTOS.get(e['tipo'], e['tipo'].replace('_', ' '))}"
                         + (f" · {e['motivo']}" if e['motivo'] else ""))
                 for e in r["eventos"][:30]], className="av-avisos"),
    ]))
    return html.Div(blocos, className="av-ficha")


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
    return html.Div([
        html.Span(c["tipo"], className="av-nota"),
        _campo_txt("conta-nome", cid, c["nome"], "nome"),
        _campo_txt("conta-limite", cid,
                   limite_br(c["limite_perda_dia"]),
                   "limite de perda diária (R$)", numerico=True),
        _botao("Salvar", "conta-salvar", cid, armado),
        _botao("Arquivar", "conta-arquivar", cid, armado),
    ], className="av-linha")


def _planos_txt(o):
    ids = o.get("plano_ids") or [o["plano_id"]]
    return ("plano " if len(ids) == 1 else "planos ") + ", ".join(f"#{i}" for i in ids)


def linha_orfao(o: dict, opcoes_variante: list[dict],
                opcoes_manter: list[dict], armado) -> html.Div:
    rid = o["run_id"]
    return html.Div([
        html.Span(f"{_planos_txt(o)} · {o['strategy']} · "
                  f"{o['nome'] or 'sem nome'} · mineração #{rid}",
                  className="av-nome"),
        _campo_dd("vincular-variante", rid, None, opcoes_variante,
                  "vincular a qual variante?"),
        _campo_dd("vincular-manter", rid, None, opcoes_manter,
                  "se a variante já tiver plano ativo: qual fica"),
        _botao("Vincular", "vincular", rid, armado),
    ], className="av-linha")
