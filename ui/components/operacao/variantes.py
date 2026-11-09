"""Operação: cartões das variantes, por conta (REAL/DEMO), e a legenda."""
from __future__ import annotations

from dash import html

from ..cartao import FASES, dica, etiqueta_mesmo_assim, inteiro, nome_curto
from ..icones import icone

from .base import _etiqueta, _rotulo, _rs, _sinal, amostra
from .kpis import _barra


# -------------------------------------------------------------- variantes
_STATUS = {"pulado": ("pregão pulado", "rosa"),
           "interrompido": ("interrompido", "rosa"),
           "nao_conferido": ("não conferido", "ambar"),
           "falha": ("falha no cálculo", "rosa"),
           None: ("sem papel hoje", "cinza")}
_APAGADO = ("pulado", "interrompido", "nao_conferido", "falha")


# (rótulo, classe) de cada botão de ação. Num lugar só porque são duas as
# mãos que os desenham: o redesenho que lê o banco e o callback leve que só
# troca o rótulo para "Confirmar?" no primeiro clique. O ícone vem da
# classe (`op-bt-*`, máscara no CSS) e não do filho: o callback leve troca
# os filhos por texto puro e um ícone filho sumiria no primeiro clique.
#
# Rótulo vazio = botão só de ícone (rascunho v4): o nome dele fica no
# `title` e no `aria-label`; armado, mostra "Confirmar?" ao lado do ícone.
_BOTOES = {
    "membro-desligar": ("", "btn-ghost op-bt op-bt-ic op-bt-mini op-bt-pause"),
    "membro-ligar": ("", "btn-ghost op-bt op-bt-ic op-bt-mini op-bt-play"),
    "pf-desligar": ("", "btn-ghost op-bt op-bt-ic op-bt-power"),
    "pf-ligar": ("Ligar portfólio", "btn-ghost op-bt op-bt-principal op-bt-power"),
    # os interruptores do Envio de ordens (protótipo v2): sem texto de
    # ligado/desligado — a cor e a bolinha dizem; a classe `op-tg-*` desenha
    # a chave (CSS), e o rótulo é só o nome da conta
    "envio-desligar": ("Demo", "btn-ghost op-tg op-tg-demo op-tg-on"),
    "envio-ligar": ("Demo", "btn-ghost op-tg op-tg-demo"),
    "envio-real-desligar": ("Real", "btn-ghost op-tg op-tg-real op-tg-on"),
    "envio-real-ligar": ("Real", "btn-ghost op-tg op-tg-real"),
}
# o nome de cada botão para o mouse e o leitor de tela
_NOMES_BOTAO = {"membro-desligar": "Pausar variante",
                "membro-ligar": "Ligar variante",
                "pf-desligar": "Desligar portfólio",
                "pf-ligar": "Ligar portfólio",
                "envio-desligar": "Envio de ordens da conta demo ligado",
                "envio-ligar": "Envio de ordens da conta demo desligado",
                "envio-real-desligar": "Envio de ordens da conta real ligado",
                "envio-real-ligar": "Envio de ordens da conta real desligado"}


def estado_botao(acao, alvo, armado) -> tuple[str, str]:
    """(rótulo, classe) do botão, armado ou não."""
    rotulo, classe = _BOTOES[acao]
    if armado == f"{acao}:{alvo}":
        # o interruptor do Envio mantém o nome da conta no rótulo; o
        # "Confirmar?" sai ao lado dele pelo CSS (`.av-armado`), como no v2
        if acao.startswith("envio-"):
            return rotulo, classe + " av-armado"
        return "Confirmar?", classe + " av-armado"
    return rotulo, classe


def _botao(acao, alvo, armado, title=""):
    rotulo, classe = estado_botao(acao, alvo, armado)
    nome = _NOMES_BOTAO[acao]
    return html.Button(rotulo, n_clicks=0, title=f"{nome}: {title}" if title else nome,
                       className=classe, **{"aria-label": nome},
                       id={"type": "av-op-acao", "acao": acao, "id": alvo})


def _contratos_txt(v: dict) -> str:
    """"contratos: papel 3 · demo 1 · plano #5" — no `title` da etiqueta
    da fase e do lápis. Na fase demo sem número gravado valem os do plano."""
    fase = v.get("fase") or "papel"
    ctr = v.get("contratos")
    proprio = v.get("contratos_demo")
    if proprio is not None:
        demo = f"demo {proprio}"
    elif fase == "demo" and ctr is not None:
        demo = f"demo {ctr} (do plano)"
    else:
        demo = "demo — (nada vai à conta)"
    plano = f"plano #{v['plano_id']}" if v.get("plano_id") else "sem plano"
    return (f"contratos: papel {'—' if ctr is None else ctr} · {demo} · "
            f"{plano}")


def _fase(v: dict) -> html.Span:
    """A etiqueta da fase logo depois do nome ("demo" em ciano, "papel" em
    cinza), como no rascunho v4; os contratos ficam no `title`."""
    fase = v.get("fase") or "papel"
    nome_fase = FASES.get(fase, fase)
    return html.Span(nome_fase,
                     className="op-var-fase" + (" op-var-fase-demo"
                                                if fase == "demo" else ""),
                     title=f"fase {nome_fase} · {_contratos_txt(v)}")


def _lapis(v: dict) -> html.Button:
    """O lápis que abre o editor dos contratos da demo."""
    return html.Button(icone("pencil", pequeno=True), n_clicks=0,
                       className="ord-ctr-editar op-bt-mini",
                       id={"type": "av-op-ord-ctr", "id": v["ligacao_id"]},
                       **{"aria-label": "Mudar contratos na demo"},
                       title="Mudar os contratos desta variante na conta demo "
                             f"(o papel segue com os do plano) · {_contratos_txt(v)}")


def _acerto(txt) -> tuple[str, str]:
    """"2/3" → ("67%", "2 de 3 fechadas ganharam"); sem fechada, "—"."""
    try:
        g, n = (int(x) for x in str(txt).split("/"))
    except (TypeError, ValueError):
        return "—", ""
    if n <= 0:
        return "—", ""
    return f"{round(g / n * 100)}%", f"{g} de {n} fechadas ganharam"


def _seta_posicao(p: int):
    """Seta verde (comprado) ou azul (vendido) com os contratos; zerado
    não mostra nada — a linha fica limpa."""
    if not p:
        return None
    compra = p > 0
    return html.Span([icone("arrow-up" if compra else "arrow-down", pequeno=True),
                      str(abs(p))],
                     className="op-var-pos " + ("op-var-pos-c" if compra
                                                else "op-var-pos-v"),
                     title=f"{'comprado' if compra else 'vendido'} {abs(p)}")


def cartao_variante(v: dict, armado) -> html.Div:
    """Uma linha da tabela de variantes, numa linha só: ponto, nome curto,
    fase e etiquetas; Hoje, Op., Acerto, Acumulado; e, no fim, os botões só
    de ícone (pausar/ligar e o lápis dos contratos). Grade de divs com o
    mesmo `grid-template-columns` do cabeçalho (`cabecalho_colunas`)."""
    lig = v["ligacao_id"]
    nome = v["nome"]
    status = v.get("status")
    if v.get("ligada"):
        botao = _botao("membro-desligar", lig, armado,
                       "as operações dela deixam de contar a partir de agora "
                       "(o papel segue calculando, em cinza). Clique duas "
                       "vezes para confirmar.")
    else:
        botao = _botao("membro-ligar", lig, armado,
                       "as operações dela voltam a contar. Clique duas vezes "
                       "para confirmar.")

    tags = []
    if not v.get("ligada", True):
        tags.append(_etiqueta("pausada", "cinza"))
    if status in _STATUS:
        rot, tom = _STATUS[status]
        # o motivo (frase) mora no (?) da etiqueta, não solto na linha
        motivo = v.get("motivo") if status in _APAGADO else None
        tags.append(_etiqueta(rot, tom, motivo))
    if v.get("gravado_mesmo_assim"):
        tags.append(etiqueta_mesmo_assim(v.get("pendencias")))

    nome_cel = html.Div([amostra(v.get("cor"), v.get("ligada", True)),
                         html.Span(nome_curto(nome), className="op-nome",
                                   title=nome),
                         _fase(v), *tags,
                         _seta_posicao(int(v.get("posicao") or 0))],
                        className="op-var-c-nome")

    acerto, acerto_title = _acerto(v.get("acerto"))
    linha = html.Div([
        nome_cel,
        html.Span(_rs(v.get("hoje")), className="op-var-v "
                  + (_sinal(v.get("hoje")) or "")),
        html.Span(str(v.get("n_ops") or 0), className="op-var-v"),
        html.Span(acerto, className="op-var-v", title=acerto_title),
        html.Span(_rs(v.get("acumulado")), className="op-var-v "
                  + (_sinal(v.get("acumulado")) or "")),
        html.Div([botao, _lapis(v)], className="op-var-c-acao"),
    ], className="op-var-linha")

    classe = "op-var"
    if not v.get("ligada", True):
        classe += " op-var-off"
    if status in _APAGADO:
        classe += " op-var-apagada"
    return html.Div(linha, className=classe)


def risco_dia(resumo: dict) -> html.Div:
    demo = (resumo.get("contas") or {}).get("demo")
    limite = resumo.get("limite_dia")
    usado = max(0.0, -((resumo.get("pior_momento") or {}).get("valor") or 0.0))
    rot = _rotulo("Risco do dia na conta demo",
                  "Quanto do limite de perda diária da conta demo o pior "
                  "momento de hoje usou. Bom: abaixo de 50%. Ruim: acima de "
                  "80%. Na fase papel nada vai para a conta; o número mostra "
                  "o que teria acontecido.", "op-risco-r")
    if demo is None:
        corpo = [html.P("Portfólio sem conta demo — escolha uma em Ao vivo › "
                        "Estratégias › Contas deste portfólio.",
                        className="op-risco-n")]
    elif not limite:
        corpo = [html.P(f"R$ {inteiro(int(round(usado)))} no pior momento · "
                        f"conta {demo['nome']} sem limite de perda cadastrado",
                        className="op-risco-n")]
    else:
        uso = usado / limite * 100
        corpo = [html.Div([html.Span(f"R$ {inteiro(int(round(usado)))} de "
                                     f"R$ {inteiro(int(round(limite)))}",
                                     className="op-risco-v"),
                           html.Span(f"{round(uso)}%", className="op-risco-pct")],
                          className="op-risco-linha"),
                 _barra(uso)]
    return html.Div([rot, *corpo], className="op-risco")


def coluna_variantes(vs: list[dict], armado, resumo: dict) -> list:
    """Cabeçalho das colunas (uma vez, com os (?)), a lista que rola e o
    risco do dia preso embaixo."""
    if not vs:
        return [_SEM_VARIANTES]
    return [cabecalho_colunas(),
            html.Div(cartoes(vs, armado), className="op-var-lista"),
            risco_dia(resumo)]


_SEM_VARIANTES = html.P(["nenhuma variante neste portfólio",
                         dica("Adicione variantes ao portfólio na tela "
                              "Portfólio e ligue-as em Ao vivo › Estratégias.")],
                        className="av-vazio op-vazio")


def cartoes(vs: list[dict], armado) -> list:
    """Só os cartões: a caixa que rola fica fixa no layout (ver `bloco`)."""
    return [cartao_variante(v, armado) for v in vs] if vs else [_SEM_VARIANTES]


# ---------------------------------------- variantes em duas partes (REAL/DEMO)
_ST_VAZIO = {"hoje": 0.0, "n": 0, "acerto": None, "total": None}


def estatisticas(ops: list[dict], total: dict | None, ligs: list) -> dict[int, dict]:
    """Por variante, numa conta: Hoje (fechadas mais a aberta provisória), Op.
    (executadas hoje), Acerto (ganhadoras sobre as fechadas de hoje) e Total
    (desde o plano em vigor, de `papel_leitura.total_por_ligacao`). Variante
    sem nada hoje aparece com zeros."""
    cont: dict[int, dict] = {}
    for o in ops or []:
        s = cont.setdefault(o["ligacao_id"], {"hoje": 0.0, "n": 0, "g": 0, "f": 0})
        if o.get("situacao") in ("fechada", "aberta"):
            s["n"] += 1
        if o.get("resultado") is not None:
            s["hoje"] += float(o["resultado"])
        if o.get("situacao") == "fechada":
            s["f"] += 1
            s["g"] += int(float(o.get("resultado") or 0) > 0)
    out = {}
    for lig in ligs:
        s = cont.get(lig, {"hoje": 0.0, "n": 0, "g": 0, "f": 0})
        t = (total or {}).get(lig)
        out[lig] = {"hoje": s["hoje"], "n": s["n"],
                    "acerto": f"{s['g']}/{s['f']}" if s["f"] else None,
                    "total": t["total"] if t else None}
    return out


def _parte_titulo(origem: str, texto: str) -> html.Div:
    """O título de uma parte do painel: REAL, DEMO ou PAPEL, na cor da conta."""
    return html.Div(html.Span(texto, className=f"op-acc op-acc-{origem}"),
                    className="op-var-parte")


def _lapis_conta(v: dict, origem: str) -> html.Button:
    """O ✎ da parte: a conta real tem id próprio (`av-op-ctr-real`) para não
    repetir o da demo quando a variante aparece nas duas partes."""
    if origem == "demo":
        return _lapis(v)
    return html.Button(icone("pencil", pequeno=True), n_clicks=0,
                       className="ord-ctr-editar op-bt-mini",
                       id={"type": "av-op-ctr-real", "id": v["ligacao_id"]},
                       **{"aria-label": "Mudar contratos na real"},
                       title="Mudar os contratos desta variante na conta real "
                             "(o papel segue com os do plano) · contratos real: "
                             f"{v.get('contratos_real') or 'do plano'}")


def linha_da_conta(v: dict, origem: str, st: dict, armado) -> html.Div:
    """Uma linha de uma parte (REAL, DEMO ou PAPEL): o resultado DA CONTA
    (`st`), não o do papel. Pausar só na parte da fase da variante (a real
    pausa a variante inteira); o ✎ muda os contratos daquela conta."""
    lig = v["ligacao_id"]
    fase = v.get("fase") or "papel"
    ligada = bool(v.get("ligada", True))
    acoes = []
    if fase == origem:
        if ligada:
            acoes.append(_botao("membro-desligar", lig, armado,
                                "as operações dela deixam de contar a partir de "
                                "agora (o papel segue calculando, em cinza). "
                                "Clique duas vezes para confirmar."))
        else:
            acoes.append(_botao("membro-ligar", lig, armado,
                                "as operações dela voltam a contar. Clique duas "
                                "vezes para confirmar."))
    if origem in ("real", "demo"):
        acoes.append(_lapis_conta(v, origem))
    nome = v["nome"]
    nome_cel = html.Div([amostra(v.get("cor"), ligada),
                         html.Span(nome_curto(nome), className="op-nome", title=nome),
                         *([_etiqueta("pausada", "cinza")] if not ligada else [])],
                        className="op-var-c-nome")
    acerto, acerto_title = _acerto(st.get("acerto"))
    return html.Div([
        nome_cel,
        html.Span(_rs(st.get("hoje")), className="op-var-v "
                  + (_sinal(st.get("hoje")) or "")),
        html.Span(str(st.get("n") or 0), className="op-var-v"),
        html.Span(acerto, className="op-var-v", title=acerto_title),
        html.Span(_rs(st.get("total")) if st.get("total") is not None else "—",
                  className="op-var-v " + (_sinal(st.get("total")) or "")),
        html.Div(acoes, className="op-var-c-acao"),
    ], className="op-var-linha" + ("" if ligada else " op-var-off"))


def cartoes_por_conta(vs: list[dict], armado, estat: dict) -> list:
    """O painel de variantes em partes: REAL (em cima), DEMO e, se houver
    variante só no papel, PAPEL. Variante em fase real aparece na REAL e na
    DEMO, cada uma com o resultado da própria conta (`estat`, de
    `estatisticas`); na parte PAPEL o resultado é o do papel."""
    if not vs:
        return [_SEM_VARIANTES]
    out = []
    partes = (
        ("real", "REAL", lambda v: v.get("fase") == "real",
         "nenhuma variante na fase real"),
        ("demo", "DEMO", lambda v: v.get("fase") in ("demo", "real"),
         "nenhuma variante na fase demo"),
        ("papel", "PAPEL", lambda v: (v.get("fase") or "papel") == "papel", None),
    )
    for origem, titulo, filtro, vazio in partes:
        linhas = [v for v in vs if filtro(v)]
        if not linhas and vazio is None:
            continue
        out.append(_parte_titulo(origem, titulo))
        if not linhas:
            out.append(html.P(vazio, className="op-vazio-txt"))
        for v in linhas:
            if origem == "papel":
                st = {"hoje": v.get("hoje"), "n": v.get("n_ops"),
                      "acerto": v.get("acerto"), "total": v.get("acumulado")}
            else:
                st = (estat.get(origem) or {}).get(v["ligacao_id"], _ST_VAZIO)
            out.append(linha_da_conta(v, origem, st, armado))
    return out


def cabecalho_colunas_conta():
    """O cabeçalho do painel em partes: Variante · Hoje · Op. · Acerto · Total
    · ações (o Total é desde o plano em vigor, da conta da parte)."""
    return html.Div([
        _rotulo("Variante", "Ordem: posição aberta primeiro, depois o "
                "resultado do dia. O ponto é a cor da variante no gráfico. Ao "
                "lado do nome, a fase. No fim da linha: pausar ou ligar (dois "
                "cliques), na parte da fase da variante, e o ✎, que muda os "
                "contratos daquela conta."),
        _rotulo("Hoje", "Resultado de hoje desta conta (fechadas mais a aberta "
                "provisória). Bom: positivo. Ruim: perda maior que a perda "
                "média do plano."),
        _rotulo("Op.", "Operações executadas hoje nesta conta. Bom: perto da "
                "média por pregão do plano. Atenção: zero num dia com movimento."),
        _rotulo("Acerto", "Ganhadoras sobre fechadas hoje, em % (o mouse em cima "
                "mostra quantas de quantas). Um dia sozinho diz pouco."),
        _rotulo("Total", "Resultado desde o plano em vigor, só operações fechadas, "
                "líquido dos custos do plano. Bom: positivo e subindo. Ruim: "
                "negativo e abaixo da faixa esperada."),
        html.Span(),
    ], className="op-var-cols")


def cabecalho_colunas():
    return html.Div([
        _rotulo("Variante", "Ordem: posição aberta primeiro, depois o "
                "resultado do dia. O ponto é a cor da variante no gráfico; a "
                "seta, a posição aberta (verde comprado, azul vendido). Ao "
                "lado do nome, a fase (o mouse em cima mostra os contratos). "
                "No fim da linha: pausar ou ligar a variante (dois cliques) e "
                "o lápis, que muda os contratos na conta demo."),
        _rotulo("Hoje", "Resultado de hoje da variante (fechadas mais a "
                "aberta provisória). Bom: positivo. Ruim: perda maior que a "
                "perda média do plano."),
        _rotulo("Op.", "Operações de hoje que contam. Bom: perto da "
                "média de operações por pregão do plano. Atenção: muito acima "
                "(a estratégia está girando demais) ou zero num dia com "
                "movimento (confira se o papel está calculando)."),
        _rotulo("Acerto", "Ganhadoras sobre fechadas hoje, em % (o mouse em "
                "cima mostra quantas de quantas). Bom: perto do "
                "acerto esperado (veja o Comparativo; acima de 40–50% na "
                "maioria das estratégias). Ruim: bem abaixo dele por vários "
                "pregões. Um dia sozinho diz pouco."),
        _rotulo("Acumulado", "Papel desde o plano em vigor desta variante. "
                "Bom: dentro da faixa esperada (veja Papel × esperado, Por "
                "variante). Ruim: abaixo do p10."),
        html.Span(),
    ], className="op-var-cols")


def legenda(vs: list[dict], ocultas) -> html.Div:
    """Um chip por variante: clicar esconde/mostra no gráfico. A chave dos
    símbolos fica no (?) do título do gráfico."""
    return html.Div(html.Div(chips(vs, ocultas), className="op-chips"),
                    className="op-legenda-in")


# a chave dos símbolos do gráfico: no (?) do título, não solta na tela
_CHAVE = ("Marcadores: ▲ compra, ▼ venda, ● saída (■ quando a cor da "
          "variante repete). Tracejado = stop e alvo da posição aberta. Cinza "
          "= operação fora do período em que a variante estava ligada. Os "
          "botões embaixo do gráfico escondem ou mostram cada variante.")


def chips(vs: list[dict], ocultas) -> list:
    """Só os chips: a fileira que rola fica fixa no layout."""
    ocultas = set(ocultas or [])
    out = []
    for v in sorted(vs, key=lambda x: x.get("cor") or 0):
        off = v["ligacao_id"] in ocultas
        out.append(html.Button(
            [amostra(v.get("cor")), html.Span(nome_curto(v["nome"]),
                                              className="op-chip-nome")],
            id={"type": "av-op-chip", "id": v["ligacao_id"]}, n_clicks=0,
            title=f"{v['nome']} — clique para "
                  f"{'mostrar' if off else 'esconder'} no gráfico",
            className="op-chip" + (" op-chip-off" if off else "")))
    return out
