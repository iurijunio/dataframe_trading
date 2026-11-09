"""Estratégias: cartão da variante e ficha de rastreio."""
from __future__ import annotations

from datetime import date

from dash import dcc, html

from .. import ficha as FI
from .. import ordens_panel as OR
from ..cartao import FASES, dica, etiqueta_mesmo_assim, num

from .base import _EVENTOS, _botao, _campo_txt, _data, _data_iso, _disjuntor_texto, _etiqueta, _kv, _metodo, _num, _pct, _plural, _reais, _rotulado, _vale_legado


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


def selo_papel_backtest(sit: dict | None) -> html.Span:
    """Papel × backtest para a promoção: ✓ N pregões | K diferenças | ainda
    sem pregão conferido. As diferenças vêm primeiro: com uma delas o `ok`
    já é falso, mas a frase que importa é a que barra a subida."""
    s = sit or {}
    n, dif = int(s.get("pregoes") or 0), int(s.get("diferencas") or 0)
    explica = ("Toda manhã a captura roda o backtest do plano nos pregões do "
               "papel e compara operação por operação. Bom: ✓ (bateu). Ruim: "
               "qualquer diferença — a variante não sobe para a demo até "
               "resolver. Sem pregão conferido ainda não há prova nem a "
               "favor nem contra.")
    if dif > 0:
        return _etiqueta(f"{dif} {'diferença' if dif == 1 else 'diferenças'} — "
                         "não pode subir para a demo", "rosa", explica)
    if s.get("ok") and n:
        return _etiqueta(f"✓ {n} {'pregão' if n == 1 else 'pregões'}", "verde",
                         explica)
    return _etiqueta("ainda sem pregão conferido", "cinza", explica)


def selo_ordens_backtest(sit: dict | None) -> html.Span:
    """Ordens × backtest para a promoção, no estilo do selo do papel:
    ✓ N pregões | N pregões, K diferenças | ainda sem pregão conferido."""
    s = sit or {}
    n, dif = int(s.get("pregoes") or 0), int(s.get("diferencas") or 0)
    explica = ("Toda manhã a captura compara as ordens que a conta executou "
               "(real e demo à parte) com o backtest do plano: entrada no "
               "mesmo minuto, mesmo lado e com saída no dia. Bom: ✓ (bateu). "
               "Ruim: qualquer diferença — a variante não sobe até resolver. "
               "Só entram os pregões em que a conta operou a variante.")
    pregoes = f"{n} {'pregão' if n == 1 else 'pregões'}"
    if dif > 0:
        return _etiqueta(f"{pregoes}, {dif} "
                         f"{'diferença' if dif == 1 else 'diferenças'} — "
                         "não pode subir", "rosa", explica)
    if s.get("ok") and n:
        return _etiqueta(f"✓ {pregoes}", "verde", explica)
    return _etiqueta("ainda sem pregão conferido", "cinza", explica)


def _trilha(fase):
    """papel → demo → real, com a fase atual acesa e as outras apagadas."""
    partes = []
    for i, cod in enumerate(("papel", "demo", "real")):
        if i:
            partes.append(html.Span("→", className="av-trilha-seta"))
        partes.append(html.Span(cod, className=f"av-chip av-chip-{cod} "
                                + ("av-trilha-on" if cod == fase else "av-trilha-off")))
    return html.Div(partes, className="av-trilha")


def _tick(v) -> str:
    if v is None:
        return "—"
    return ("+" if v > 0 else "") + num(v, 1) + " tick"


def _demo_ate_agora(d: dict | None):
    """Números que a demo fez nesta variante até agora (`ordens_da_ficha`)."""
    d = d or {}
    return _kv([
        ("Operações", _num(d.get("operacoes"))),
        ("Derrapagem média", _tick(d.get("derrapagem")),
         "Quanto a demo pagou a mais que o papel, em ticks, por ponta (entrada "
         "e saída). Positivo = pior que o papel. Perto de zero é o bom."),
        ("Rejeitadas", _num(d.get("rejeitadas")),
         "Ordens que a corretora recusou na demo. Zero é o bom."),
        ("Chamados sem solução", _num(d.get("chamados")),
         "Pedidos de atenção que a automação abriu para esta variante na demo e "
         "que ainda não foram fechados. Zero é o bom."),
    ])


def _linha_contratos(lig, campo, acao, custo_tipo, rot, explica, valor, plano,
                     armado):
    """Uma linha de contratos (real ou demo): campo, Salvar e a prévia do custo
    de um stop em % do limite da conta. Os ids são próprios desta ficha."""
    return [
        html.Div([rot, dica(explica)], className="av-ord-rot"),
        html.Div([
            html.Div([
                dcc.Input(id={"type": "av-campo", "campo": campo, "id": lig},
                          type="text", inputMode="numeric", debounce=True,
                          value="" if valor is None else str(valor),
                          placeholder="plano", className="inp av-ord-ctr",
                          autoComplete="off"),
                _botao("Salvar contratos", acao, lig, armado,
                       "btn-ghost btn-sm av-btn-sec"),
                html.Span(OR.contratos_antes(valor, plano), className="mut"),
            ], className="av-ord-ctr-linha"),
            html.Div(id={"type": custo_tipo, "id": lig}, className="av-texto"),
        ], className="av-ord-val"),
    ]


def bloco_ordens_ficha(l: dict, ordens: dict | None, armado) -> html.Div:
    """Fase (trilha com o próximo passo e o de voltar), selo papel × backtest,
    o que a demo fez até agora e os contratos da real e da demo, cada um com a
    prévia do custo de um stop. `ordens` é o que `callbacks_ao_vivo.
    ordens_da_ficha` leu (None = banco ocupado). Os ids do campo de contratos
    são próprios (`av-campo`/`av-ficha-custo*`): os `av-op-ord-ctr-*` são do
    popover da tela Operação."""
    lig = l["ligacao_id"]
    titulo = html.Div([html.Span("Ordens nas contas", className="av-sub-titulo"),
                       dica("Onde a variante está no caminho até o dinheiro "
                            "real e o que a conta dela já fez.")],
                      className="av-sub-head")
    if ordens is None:
        return html.Div([titulo, html.P(
            "Não foi possível ler agora: banco ocupado — feche e abra a ficha "
            "de novo.", className="av-alerta")], className="av-ficha-acoes")
    fase = l["fase"]
    direto = None
    if fase == "papel":
        proximo = _botao("Promover para demo", "fase-demo", lig, armado,
                         "btn-ghost btn-sm av-btn-principal")
        direto = _botao("Promover para real", "fase-real", lig, armado,
                        "btn-ghost btn-sm av-btn-principal")
        voltar = None
    elif fase == "demo":
        proximo = _botao("Promover para real", "fase-real", lig, armado,
                         "btn-ghost btn-sm av-btn-principal")
        voltar = _botao("Voltar para papel", "fase-papel", lig, armado,
                        "btn-ghost btn-sm av-btn-sec")
    else:
        proximo = None
        voltar = _botao("Voltar para demo", "fase-voltar-demo", lig, armado,
                        "btn-ghost btn-sm av-btn-sec")
    restr = ordens.get("restricoes") or {}
    motivos = restr.get("motivos") or []
    avisos = restr.get("avisos") or []
    # o que barra a subida ao demo aparece na fase papel; a real vem do core
    # como erro ao clicar (`mudar_fase`), que a tela mostra no aviso do topo
    linhas_restr = [] if fase != "papel" else (
        [html.P("✖ " + m, className="av-alerta") for m in motivos]
        + [html.P("⚠ " + a, className="av-texto") for a in avisos])
    acoes = [a for a in (voltar, proximo, direto) if a is not None]
    contratos_demo = ordens.get("contratos_demo")
    contratos_real = ordens.get("contratos_real")
    plano = ordens.get("contratos_plano")
    grade = [
        html.Div([html.Span("Fase", className="av-ord-rot-txt"),
                  dica("Papel: só simula, nada é enviado. Demo: manda ordens à "
                       "conta demo quando o Envio de ordens do portfólio estiver "
                       "ligado. Real: manda ordens à conta real quando o Envio "
                       "dela estiver ligado. Voltar encerra a posição "
                       "aberta, se houver.")], className="av-ord-rot"),
        html.Div([_trilha(fase), html.Div(acoes, className="av-ord-acoes"),
                  *linhas_restr], className="av-ord-val"),
        html.Div([html.Span("Papel × backtest", className="av-ord-rot-txt")],
                 className="av-ord-rot"),
        html.Div(selo_papel_backtest(ordens.get("situacao")),
                 className="av-ord-val"),
        html.Div([html.Span("Ordens × backtest", className="av-ord-rot-txt")],
                 className="av-ord-rot"),
        html.Div(selo_ordens_backtest(ordens.get("ordens_backtest")),
                 className="av-ord-val"),
        html.Div([html.Span("Na demo até agora", className="av-ord-rot-txt"),
                  dica("Só o que a demo fez nesta variante, nos pregões em que "
                       "ela tentou operar. Ensaio com o Envio desligado não "
                       "conta.")], className="av-ord-rot"),
        html.Div(_demo_ate_agora(ordens.get("demo_ate_agora")),
                 className="av-ord-val"),
        *_linha_contratos(
            lig, "contratos-real", "contratos-real-salvar",
            "av-ficha-custo-real",
            html.Span("Contratos na real", className="av-ord-rot-txt"),
            "Quantos contratos a conta real opera. Vazio = os do plano. A "
            "mudança vale a partir da próxima operação.",
            contratos_real, plano, armado),
        *_linha_contratos(
            lig, "contratos", "contratos-salvar", "av-ficha-custo",
            html.Span("Contratos na demo", className="av-ord-rot-txt"),
            "Quantos contratos a demo opera. Vazio = os do plano (o papel segue "
            "sempre com os do plano). A mudança vale a partir da próxima "
            "operação.",
            contratos_demo, plano, armado),
    ]
    return html.Div([titulo, html.Div(grade, className="av-ord-grade")],
                    className="av-ficha-acoes")


def ficha_rastreio(r: dict, estrategia_mod, armado, hoje=None,
                   com_ordens=False, ordens=None) -> html.Div:
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
    if com_ordens:
        blocos.append(bloco_ordens_ficha(
            l, None if ordens is None else
            {**ordens, "contratos_plano": (det or {}).get("contratos")}, armado))

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
