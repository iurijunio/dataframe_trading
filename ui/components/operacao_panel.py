"""Sub-tela Ao vivo › Operação: o papel do portfólio, ao vivo.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6–§7.

Só desenha. Quem lê é `ui/callbacks_operacao.py`: o estado.json a cada 2 s
(situação e candle em formação) e o banco, via `core.papel_leitura`, só
quando a captura recalcula o papel. Por isso tudo aqui recebe dicionários
no formato do core — dá para testar cada frase sem banco.

Muitas variantes (spec §6.4) é o caso normal, não o raro: um portfólio de
clusters passa fácil de dez. Daí as regras do desenho — nome numa linha só
com reticências e o nome inteiro no `title`; a coluna de variantes e a
tabela rolam por dentro, sem empurrar o resto da tela; a legenda é uma
fileira de chips que rola de lado e esconde a variante no gráfico.
"""
from __future__ import annotations

from datetime import date, datetime, time

import dash_tvlwc
from dash import dcc, html

from .. import theme as T
from ..data import to_epoch
from . import ordens_panel as OR
from . import pregao_panel as PP
from .cartao import FASES, dica, etiqueta_mesmo_assim, inteiro, nome_curto, num, pct
from .icones import icone

CINZA = T.CINZA_FORA
SUBTELA = "operacao"

# códigos de saída do kernel (core/engine/kernel.py), na língua da mesa
_SAIU_POR = {0: "stop", 1: "alvo", 2: "sinal contrário",
             3: "horário de fechamento", 4: "tempo máximo",
             5: "fim dos dados"}

_FAIXAS = {"abaixo_p10": "abaixo do p10", "p10_p50": "entre p10 e p50",
           "p50_p90": "entre p50 e p90", "acima_p90": "acima do p90"}

# título da linha de stop/alvo no eixo de preço: nome longo cobriria o gráfico
_TITULO_MAX = 22
# posições abertas visíveis até onde stop/alvo ganham rótulo no eixo
_ROTULOS_MAX = 2

# curva por pregão: um ponto por dia, sem hora no eixo
CHART_CURVA = {**T.CHART_OPTIONS,
               "timeScale": {**T.CHART_OPTIONS["timeScale"],
                             "timeVisible": False, "rightOffset": 2},
               "rightPriceScale": {**T.CHART_OPTIONS["rightPriceScale"],
                                   "scaleMargins": {"top": .12, "bottom": .12}}}


# ------------------------------------------------------------- cores e forma
def cor(i: int | None) -> str:
    return T.CORES_VARIANTE[(i or 0) % len(T.CORES_VARIANTE)]


def forma(i: int | None) -> str:
    """Marcador de saída: círculo nas 8 primeiras cores, quadrado quando a
    cor repete — a 9ª variante tem a cor da 1ª e precisa de outro sinal."""
    return "square" if ((i or 0) // len(T.CORES_VARIANTE)) % 2 else "circle"


def amostra(i, ativa=True):
    quadrado = forma(i) == "square"
    return html.Span(className="op-amostra"
                     + (" op-amostra-quadrado" if quadrado else ""),
                     style={"background": cor(i) if ativa else CINZA})


# --------------------------------------------------------------- formatação
def _rs(v, casas=0) -> str:
    """Dinheiro com sinal: "+R$ 286", "-R$ 164", "R$ 0"."""
    if v is None:
        return "—"
    if casas:
        corpo = num(abs(v), casas)
    else:
        corpo = inteiro(int(round(abs(v))))
    if round(v, casas) == 0:
        return f"R$ {corpo}"
    return f"{'+' if v > 0 else '-'}R$ {corpo}"


def _sinal(v) -> str | None:
    if v is None or round(v, 2) == 0:
        return None
    return "pos" if v > 0 else "neg"


def _hora(ts) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return "—"
    return f"{ts:%H:%M}"


def _preco(v) -> str:
    return "—" if v is None else inteiro(int(v))


def _etiqueta(texto, tom="cinza", explica=None):
    return html.Span([texto] + ([dica(explica)] if explica else []),
                     className=f"av-tag av-tag-{tom}")


def _rotulo(texto, explica=None, classe="op-rot"):
    return html.Span([texto] + ([dica(explica)] if explica else []),
                     className=classe)


def _lado_pos(p: int) -> tuple[str, str]:
    if p > 0:
        return f"comprado {p}", "info"
    if p < 0:
        return f"vendido {abs(p)}", "info"
    return "zerado", "cinza"


# ------------------------------------------------------------------- KPIs
def _kpi(rotulo, explica, valor, nota=None, sinal=None, barra=None,
         nota_title=None, ordem=None):
    filhos = [_rotulo(rotulo, explica, "op-kpi-r"),
              html.Span(valor, className="op-kpi-v"
                        + (f" {sinal}" if sinal else ""))]
    if nota:
        filhos.append(html.Span(nota, className="op-kpi-n",
                                title=nota_title or ""))
    if barra is not None:
        filhos.append(barra)
    # a ordem na tira de seis números (REAL, DEMO, PAPEL, perdas, esperado)
    estilo = {"order": ordem} if ordem is not None else None
    return html.Div(filhos, className="op-kpi", style=estilo)


def _barra(uso_pct: float):
    tom = "ok" if uso_pct < 50 else ("atencao" if uso_pct < 80 else "perigo")
    largura = f"{min(100, round(uso_pct))}%"
    return html.Div(html.Span(className=f"op-barra-uso op-barra-{tom}",
                              style={"width": largura}),
                    className="op-barra")


def kpis(resumo: dict, ops: list[dict], esperado: dict,
         nomes: dict | None = None) -> list:
    """Os dois números do papel na tira (protótipo v2, Operação): PAPEL hoje,
    com o total desde o plano em vigor embaixo, e Contra o esperado. Os
    números das contas (REAL e DEMO hoje, as perdas do dia) saem do pulso
    (`ordens_panel.numeros`) e entram na mesma tira pela ordem CSS.

    `esperado` = {"diferenca": papel − soma das medianas, "faixas": faixa
    atual de cada variante}. `ops` e `nomes` ficam na assinatura: o
    redesenho os passa e a tela usa só o resumo."""
    hoje = resumo.get("resultado_hoje") or 0.0
    acum = resumo.get("acumulado") or {}

    dif = (esperado or {}).get("diferenca")
    faixas = [f for f in (esperado or {}).get("faixas") or [] if f]
    if dif is None:
        valor_esp, sinal_esp = "—", None
        nota_esp = (esperado or {}).get("aviso") or "plano sem expectativa gravada"
        title_esp = nota_esp
    else:
        valor_esp, sinal_esp = _rs(dif), _sinal(dif)
        mediana = f"{'acima' if dif >= 0 else 'abaixo'} da mediana"
        nota_esp, partes = mediana, [mediana]
        if faixas:
            dentro = sum(1 for f in faixas if f in ("p10_p50", "p50_p90"))
            baixo = faixas.count("abaixo_p10")
            alto = faixas.count("acima_p90")
            partes.append(f"{dentro} de {len(faixas)} dentro da faixa")
            if baixo:
                partes.append(f"{baixo} abaixo do p10")
            if alto:
                partes.append(f"{alto} acima do p90")
            # na nota só o que mais importa: quem está abaixo do p10 primeiro
            nota_esp = (f"{baixo} abaixo do p10" if baixo
                        else f"{dentro} de {len(faixas)} dentro da faixa")
        title_esp = " · ".join(partes)

    total = acum.get("valor")
    pregoes = acum.get("pregoes", 0)
    operacoes = acum.get("operacoes", 0)
    explica_papel = (
        "Soma do papel de hoje das variantes: operações fechadas mais a aberta "
        "pelo preço do último candle (provisório). Operação fora do período em "
        "que a variante estava ligada não entra. Bom: positivo. Ruim: perto do "
        "limite de perda do dia. O total embaixo é o acumulado do papel desde o "
        "plano em vigor (recomeça quando o plano muda), com a operação aberta "
        "pelo valor provisório: "
        f"{pregoes} {'pregão' if pregoes == 1 else 'pregões'} e "
        f"{operacoes} {'operação' if operacoes == 1 else 'operações'}. Bom: "
        "dentro ou acima da faixa esperada. Ruim: abaixo do p10.")
    return [
        _kpi_papel(hoje, total, explica_papel),
        _kpi("Contra o esperado",
             "Papel acumulado menos a soma das medianas que a Candidata "
             "prometeu para o mesmo número de pregões. Por variante, a faixa "
             "em que ela está: p10 = em 10% dos sorteios da Candidata o "
             "resultado ficou abaixo disso. Bom: entre p10 e p90. Ruim: "
             "abaixo do p10 — o papel está pior que 9 em 10 cenários.",
             valor_esp, nota_esp, "aviso" if "abaixo_p10" in faixas
             else sinal_esp, nota_title=title_esp, ordem=6),
    ]


def _kpi_papel(hoje, total, explica) -> html.Div:
    """PAPEL hoje: o resultado do dia do papel e, embaixo, o total desde o
    plano em vigor (verde ou vermelho)."""
    rot = html.Span([html.Span("PAPEL", className="op-acc op-acc-papel"),
                     " hoje", dica(explica)], className="op-kpi-r")
    return html.Div([
        rot,
        html.Span(_rs(hoje), className="op-kpi-v"
                  + (f" {_sinal(hoje)}" if _sinal(hoje) else "")),
        html.Span(["total ", html.B(_rs(total, 2),
                                    className=_sinal(total) or "")],
                  className="op-kpi-n"),
    ], className="op-kpi op-kpi-conta", style={"order": 3})


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


# -------------------------------------------------------------- operações
def _cel(conteudo, classe="", title=None):
    kw = {"title": title} if title else {}
    return html.Td(conteudo, className=classe, **kw)


# situação de uma "aberta" do banco que não é posição de agora (ver
# `core.papel_leitura.operacoes_do_dia`) -> texto da coluna Saída
_ABERTA_PARADA = {"nao_conferido": "não conferida",
                  "nao_atualizada": "não atualizada",
                  "congelada": "congelada"}


def linha_operacao(o: dict) -> html.Tr:
    sit = o.get("situacao")
    compra = int(o["side"]) == 1
    pts = int(o.get("points") or 0)
    # a coluna Saída diz a hora e por onde saiu ("11:20 alvo", rascunho
    # v4); na aberta, o stop e o alvo de agora
    if sit == "aberta":
        saida = [html.Span("aberta", className="acc"),
                 html.Span(f" · stop {_preco(o.get('stop_px'))} · alvo "
                           f"{_preco(o.get('alvo_px'))}", className="acc")]
        marcado = int(o["entry_px"]) + int(o["side"]) * pts
        preco_saida = _cel(_preco(marcado), "n acc",
                           "preço marcado no último candle calculado")
    elif sit in _ABERTA_PARADA:
        # aberta no banco, mas não é posição de agora: o stop/alvo gravado
        # é de quando o motor parou, mostrá-lo seria dizer que ainda vale
        rotulo = _ABERTA_PARADA[sit]
        if sit == "congelada" and o.get("nota"):
            rotulo = f"{rotulo} — {o['nota']}"
        saida = html.Span(rotulo, className="aviso",
                          title=o.get("nota") or rotulo)
        preco_saida = _cel("—", "n")
    else:
        saiu = _SAIU_POR.get(o.get("reason"))
        saida = _hora(o.get("exit_ts")) + (f" {saiu}" if saiu else "")
        preco_saida = _cel(_preco(o.get("exit_px")), "n")
    nome = o.get("variante") or "—"
    var = [html.Div([amostra(o.get("cor"), o.get("conta", True)),
                     html.Span(nome_curto(nome), className="op-nome-tab",
                               title=nome)],
                    className="op-var-cel")]
    if not o.get("conta", True):
        var.append(html.Span("fora do período ligado", className="op-fora-txt"))
    resultado = [_rs(o.get("liquido"))]
    if o.get("provisorio"):
        resultado.append(html.Span(" provisório", className="op-prov"))
    classe = "op-linha"
    if sit == "aberta":
        classe += " op-aberta"
    if sit in _ABERTA_PARADA:
        classe += " op-preso"
    if not o.get("conta", True):
        classe += " op-fora"
    return html.Tr([
        _cel(_hora(o.get("entry_ts"))),
        _cel(saida),
        _cel(var, "t"),
        _cel(html.Span("COMPRA" if compra else "VENDA",
                       className="op-lado " + ("op-c" if compra else "op-v"))),
        _cel(f"{o.get('contratos')} / {_ctr_demo(o.get('real'))} / "
             f"{_ctr_demo(o.get('demo'))}", "n"),
        _cel(_preco(o.get("entry_px")), "n"),
        preco_saida,
        _cel(("+" if pts > 0 else "-" if pts < 0 else "") + inteiro(abs(pts)),
             "n " + (_sinal(pts) or "")),
        _cel(resultado, "n " + (_sinal(o.get("liquido")) or "")),
        _papel_x_demo(o.get("demo")),
        _papel_x_demo(o.get("real")),
    ], className=classe)


def _ctr_demo(d) -> str:
    if not d or d.get("contratos") is None:
        return "—"
    return OR._decimal(d["contratos"])


def _papel_x_demo(d):
    """Derrapagem além do plano da mesma operação na demo, por ponta
    (entrada · saída), em ticks; sem a demo nela, "—"."""
    if not d:
        return _cel("—", "n mut")
    e, s = d.get("derrapagem_entrada"), d.get("derrapagem_saida")
    if e is None and s is None:
        return _cel("não executada" if d.get("preco_entrada") is None else "—",
                    "n mut")

    f = OR._decimal
    pior = max(x for x in (e, s) if x is not None)
    return _cel(f"{f(e)} · {f(s)} ticks", "n" + (" aviso" if pior > 2 else ""))


def tabela_operacoes(ops: list[dict]):
    if not ops:
        return html.P(["nenhuma operação no papel neste pregão",
                       dica("O papel ainda não deu sinal hoje (ou o filtro "
                            "escolheu uma variante sem operação).")],
                      className="op-vazio-txt")

    def th(texto, explica=None, n=False):
        return html.Th([texto] + ([dica(explica)] if explica else []),
                       className="n" if n else "")
    cab = html.Tr([
        th("Entrada"), th("Saída"), th("Variante"), th("Lado"),
        th("Contr. papel / real / demo", "Contratos da operação em cada "
           "lugar: papel, conta real e conta demo. O papel usa os do plano. "
           "Bom: os três iguais ao plano. Ruim: real ou demo com mais "
           "contratos que o plano (risco maior que o medido).", True),
        th("Preço entrada", n=True), th("Preço saída", n=True),
        th("Pontos", "Pontos a favor (+) ou contra (−) por contrato, já com a "
           "derrapagem do plano. Bom: ganhos maiores que as perdas na média "
           "do dia. Ruim: perdas no tamanho do stop seguidas.", True),
        th("Resultado", "Resultado do papel em reais, com os contratos e os "
           "custos do plano. Na aberta é provisório: o preço do último "
           "candle. Bom: a média por operação do plano ou mais.", True),
        th("Papel × demo", "Derrapagem da demo além da que o plano supõe, na "
           "mesma operação, por ponta (entrada · saída), em ticks. Bom: perto "
           "de 0. Ruim: acima de 2 ticks (âmbar). \"não executada\" = a demo "
           "não entrou nesta operação.", True),
        th("Papel × real", "Derrapagem da conta real além da que o plano supõe, "
           "na mesma operação, por ponta (entrada · saída), em ticks. Bom: perto "
           "de 0. Ruim: acima de 2 ticks (âmbar). \"não executada\" = a real "
           "não entrou nesta operação.", True),
    ])
    # sem a caixa que rola: ela fica fixa no layout (`av-op-operacoes`),
    # senão cada releitura a recriava e a rolagem voltava ao topo
    return html.Table([html.Thead(cab),
                       html.Tbody([linha_operacao(o) for o in ops])],
                      className="op-tabela")


# ---------------------------------------------------------------- gráfico
def marcadores_tela(dados: dict, ocultas, tf: str) -> tuple[list, list]:
    """(markers, priceLines) do gráfico, a partir de `papel_leitura.marcadores`.

    Pinta pela cor da variante (cinza quando a operação não conta), troca o
    círculo da saída por quadrado quando a cor repete e põe o marcador no
    início do candle de 5/15 min — o gráfico só desenha marcador em cima de
    um candle que existe. Leva só as chaves que o gráfico conhece."""
    ocultas = set(ocultas or [])
    passo = PP.MINUTOS_TF.get(tf, 1) * 60
    mk = []
    for m in dados.get("marcadores") or []:
        if m.get("ligacao_id") in ocultas:
            continue
        forma_m = m["shape"]
        if forma_m == "circle":
            forma_m = forma(m.get("cor"))
        mk.append({"time": int(m["time"]) - int(m["time"]) % passo,
                   "position": m["position"], "shape": forma_m,
                   "color": cor(m.get("cor")) if m.get("conta", True) else CINZA,
                   "text": m.get("text", "")})
    mk.sort(key=lambda x: x["time"])
    visiveis = [l for l in dados.get("linhas_abertas") or []
                if l.get("ligacao_id") not in ocultas]
    # Com mais de 2 posições abertas os rótulos no eixo empilhavam
    # ("stop stop stop… alvo") e cobriam o preço: ficam só as linhas, e a
    # legenda esconde as outras variantes para ler uma de cada vez.
    rotulos = len({l.get("ligacao_id") for l in visiveis}) <= _ROTULOS_MAX
    linhas = []
    for l in visiveis:
        # só "stop"/"alvo": a cor já diz de quem é
        titulo = (l.get("tipo") or l.get("title") or "")[:_TITULO_MAX]
        linhas.append({"price": int(l["price"]), "lineWidth": 1, "lineStyle": 2,
                       "color": cor(l.get("cor")) if l.get("conta", True) else CINZA,
                       "axisLabelVisible": rotulos,
                       "title": titulo if rotulos else ""})
    return mk, linhas


def tick_operacao(estado: dict | None, tf: str, base: dict | None,
                  agora: datetime) -> dict | None:
    """O candle em formação para o `tick`, sem abrir o banco.

    O Pregão lê do banco os M1 já fechados do balde de 5/15 min; aqui o
    pulso não pode ler o banco, e nem precisa: o último candle que a série
    desenhou (`base`, guardado quando ela foi montada) já é esse balde. Se
    o minuto em formação abriu um balde novo, o candle é só ele."""
    if not PP.captura_ativa(estado, agora):
        return None
    f = (estado or {}).get("em_formacao")
    ts = PP._data((f or {}).get("ts"))
    if ts is None:
        return None
    t0 = to_epoch(PP.inicio_balde(ts, tf))
    if tf != "M1" and base and base.get("time") == t0:
        bar = {"time": t0, "open": base["open"],
               "high": max(base["high"], f["high"]),
               "low": min(base["low"], f["low"]), "close": f["close"]}
    else:
        bar = {"time": t0, "open": f["open"], "high": f["high"],
               "low": f["low"], "close": f["close"]}
    return {"id": "preco", "bar": bar}


# --------------------------------------------------------------- situação
def _sep(texto="·"):
    return html.Span(texto, className="op-sep")


def _seg(filhos, explica=None, classe="", title=None):
    """Um trecho da linha do portfólio (rascunho v4: "WINZ26 · demo Clear ·
    R$ 10.000 · 2/2 operando"), sem rótulo de campo; o (?) logo depois."""
    kw = {"title": title} if title else {}
    return html.Span(list(filhos) + ([dica(explica)] if explica else []),
                     className=("op-seg " + classe).strip(), **kw)


def faixa_situacao(estado: dict | None, agora: datetime) -> list:
    """A captura (mesma `situacao` do Pregão) e o papel: quando foi
    calculado, se ficou para trás, se falhou.

    Etiquetas na linha do cabeçalho, com o que fazer no (?): problema
    (rosa/âmbar) fica sempre à vista, só a frase de ação vai para o (?)."""
    sit = PP.situacao(estado, agora)
    papel = (estado or {}).get("papel") or {}
    em = PP._data(papel.get("calculado_em"))
    erros = papel.get("erros") or {}
    explica = ("Hora em que a captura calculou o papel pela última vez. Ela "
               "recalcula a cada candle novo de 1 minuto; a tela relê as "
               "operações só quando esse horário muda. Bom: no pregão, menos "
               "de 2 minutos atrás.")
    if em is None:
        valor = "—"
        explica += " Ainda não calculado desde que a captura abriu."
    elif em.date() == agora.date():
        valor = f"{em:%H:%M:%S}"
    else:
        valor = f"{em:%d/%m %H:%M}"
    # o "papel HH:MM:SS" fecha a linha do portfólio; as etiquetas de
    # problema vêm depois dele
    out = [_sep(), _seg([f"papel {valor}"], explica, "op-seg-papel")]
    if sit["tom"] in ("rosa", "ambar"):
        texto = sit["texto"]
        if not sit["ativa"] and em:
            texto += f" — papel congelado em {em:%H:%M}"
        out.append(_etiqueta(texto, sit["tom"], sit["acao"]))
    elif not sit["pregao"]:
        out.append(_etiqueta("mercado fechado", "cinza",
                             "Fora do horário do pregão: a tela mostra o "
                             "último pregão calculado."))
    if erros.get("calculo"):
        out.append(_etiqueta("papel de hoje não foi calculado", "rosa",
                             "Falhou na última volta da captura; ela tenta de "
                             f"novo no próximo candle. Erro: {erros['calculo']}"))
    if erros.get("conferencia"):
        out.append(_etiqueta("conferência do papel falhou", "ambar",
                             "A captura tenta de novo na próxima janela de "
                             f"conferência. Erro: {erros['conferencia']}"))
    if papel.get("pendente"):
        out.append(_etiqueta("papel atrasado: banco ocupado", "ambar",
                             "Uma mineração está gravando no banco; o papel é "
                             "refeito na próxima volta da captura."))
    return out


_TIPO_ALERTA = {"mesmo_assim": ("gravado mesmo assim", "ambar"),
                "pulado": ("pregão pulado", "rosa"),
                "interrompido": ("interrompido", "rosa"),
                "nao_conferido": ("não conferido", "ambar"),
                "falha": ("falha no cálculo", "rosa"),
                "divergencia": ("candles mudaram", "ambar")}


def lista_alertas(alertas: list[dict], nomes: dict | None = None) -> list:
    """Os alertas do papel como linhas em destaque (âmbar ou rosa) no topo
    da tabela do Diário: Hora | Variante | O que aconteceu, as mesmas
    colunas das linhas do diário logo abaixo. Sem alerta, nada."""
    nomes = nomes or {}
    out = []
    for a in alertas or []:
        rot, tom = _TIPO_ALERTA.get(a.get("tipo"), ("atenção", "ambar"))
        nome = nomes.get(a.get("ligacao_id"))
        texto = a.get("texto") or ""
        # o core escreve "nome: ..." — o nome já está na coluna Variante
        if nome and texto.startswith(f"{nome}: "):
            texto = texto[len(nome) + 2:]
        quando = a.get("quando")
        hora = f"{quando:%H:%M:%S}" if isinstance(quando, datetime) else "—"
        quem = nome_curto(nome) if nome else "—"
        out.append(html.Div([
            html.Span(hora, className="ord-ev-h"),
            html.Span(quem, className="ord-ev-quem", title=nome or ""),
            html.Span([_etiqueta(rot, tom), " ", texto], className="ord-ev-t"),
        ], className=f"ord-ev op-alerta op-alerta-{tom}"))
    return out


# ---------------------------------------------------------- papel × esperado
def _epoch_dia(d) -> int:
    return to_epoch(datetime.combine(d, time()))


def _linha(ident, tempos, valores, cor_, largura=1, estilo=0, ultimo=False):
    pts = [{"time": t, "value": round(float(v), 2)}
           for t, v in zip(tempos, valores) if v is not None]
    return {"id": ident, "type": "line", "data": pts,
            "options": {"color": cor_, "lineWidth": largura, "lineStyle": estilo,
                        "priceLineVisible": False, "lastValueVisible": ultimo,
                        "pointMarkersVisible": len(pts) < 3,
                        "priceFormat": {"type": "price", "precision": 0,
                                        "minMove": 1}},
            "pane": 0}


def curva_series(c: dict) -> list[dict]:
    """Papel acumulado com a faixa (p10/p90 pontilhados) e a mediana
    tracejada. Linha em vez de área entre p10 e p90: o gráfico não pinta
    entre duas séries, e uma área com valor negativo pintaria até o zero."""
    tempos = [_epoch_dia(d) for d in c.get("dias") or []]
    if not tempos:
        return []
    faixa = "rgba(34,228,255,.55)"
    out = []
    if c.get("p90") and c.get("p10"):
        out.append(_linha("p90", tempos, c["p90"], faixa, 1, 1))
        out.append(_linha("p10", tempos, c["p10"], faixa, 1, 1))
    if c.get("mediana"):
        out.append(_linha("mediana", tempos, c["mediana"], T.MUTED, 1, 2))
    papel = _linha("papel", tempos, c.get("papel") or [], T.POS, 2, 0, True)
    papel["priceLines"] = [{"price": 0, "color": T.LINE, "lineWidth": 1,
                            "lineStyle": 0, "axisLabelVisible": False,
                            "title": ""}]
    out.append(papel)
    return out


def curva_nota(c: dict) -> str:
    n = len(c.get("dias") or [])
    if not n:
        return "ainda nenhum pregão de papel com o plano em vigor"
    partes = [f"{n} {'pregão' if n == 1 else 'pregões'} desde o plano em vigor"]
    if c.get("faixa_atual"):
        partes.append(f"hoje {_FAIXAS[c['faixa_atual']]}")
    elif c.get("diferenca_mediana") is not None:
        d = c["diferenca_mediana"]
        partes.append(f"{_rs(d)} {'acima' if d >= 0 else 'abaixo'} da mediana")
    if c.get("aviso"):
        partes.append(c["aviso"])
    return " · ".join(partes)


# -------------------------------------------------------------- comparativo
def _fator(v):
    if v is None:
        return "—"
    if v == float("inf"):
        return "sem perdas"
    return num(v, 2)


def _atraso(ms) -> str:
    return f"{inteiro(int(round(ms)))} ms" if ms < 1000 else f"{num(ms / 1000, 1)} s"


# linhas de execução: só existem na conta (a demo, por ora); papel e
# esperado não mandam ordem
_SO_CONTA = ("mesmo_minuto", "derrapagem_extra", "atraso_ms", "rejeitadas")


def _tom_execucao(chave: str, m: dict | None, esp: dict | None) -> str | None:
    """bom | atencao | ruim da linha, pelas faixas da spec §5.2 (no (?) de
    cada linha): derrapagem ≤1 tick bom, ≤2 atenção; mesmo minuto ≥95% bom,
    ≥80% atenção; atraso ≤300 ms bom, ≤1000 atenção; rejeitadas 0 bom, ≤2
    atenção; fator de lucro e acerto ≥ o esperado bom, ≥80% dele atenção."""
    v = (m or {}).get(chave)
    if v is None:
        return None
    if chave == "mesmo_minuto":
        return "bom" if v >= .95 else "atencao" if v >= .80 else "ruim"
    if chave == "derrapagem_extra":
        return "bom" if v <= 1 else "atencao" if v <= 2 else "ruim"
    if chave == "atraso_ms":
        return "bom" if v <= 300 else "atencao" if v <= 1000 else "ruim"
    if chave == "rejeitadas":
        return "bom" if v == 0 else "atencao" if v <= 2 else "ruim"
    if chave in ("fator_lucro", "acerto"):
        ref = (esp or {}).get(chave)
        if ref is None:
            return None
        if v >= ref:
            return "bom"
        return "atencao" if v >= 0.8 * ref else "ruim"
    return None


_TOM_ETIQUETA = {"bom": ("bom", "verde"), "atencao": ("atenção", "ambar"),
                 "ruim": ("ruim", "rosa")}


def tabela_comparativo(c: dict):
    """Esperado (WFA) × Papel × Demo × Real, por contrato (spec §6.7 e §5.2).
    Nas colunas de conta, cada linha de execução leva a etiqueta bom/atenção/
    ruim contra a faixa da spec (o (?) da linha diz a faixa). Cores das
    colunas: cinza esperado, violeta papel, ciano demo, laranja real."""
    cols = [c.get("esperado_wfa"), c.get("papel"), c.get("demo"), c.get("real")]
    contas = (False, False, True, True)
    esperado = cols[0]

    def val(m, chave, fmt, conta):
        if m is None or chave in _SO_CONTA and not conta:
            return "—"
        # a execução tem número antes de a primeira operação fechar
        if not m.get("n") and chave not in ("n", *_SO_CONTA):
            return "—"
        v = m.get(chave)
        return "—" if v is None else fmt(v)

    linhas = [
        ("Tamanho", None),
        ("Contratos por operação", "contratos_por_operacao",
         lambda v: num(v, 1),
         "Média de contratos por operação. O papel usa os do plano; o "
         "walk-forward, os do backtest — por isso o resto compara por "
         "contrato. Bom: papel e demo iguais aos contratos do plano. Ruim: "
         "demo/real acima do plano (risco maior que o medido)."),
        ("Resultado por contrato", None),
        ("Operações", "n", lambda v: inteiro(int(v)),
         "Quantas operações fechadas entram na conta. Poucas (menos de 30) "
         "ainda dizem pouco."),
        ("Resultado médio por contrato", "resultado_por_contrato",
         lambda v: _rs(v, 2),
         "Resultado médio de uma operação, por contrato, já sem os custos "
         "do plano (a demo também). A tabela de operações da demo e o "
         "Resultado hoje na demo mostram antes dos custos; por isso os números não batem. Bom: "
         "papel perto do esperado. Ruim: papel bem abaixo por muitos pregões."),
        ("Pontos por operação", "pontos_por_operacao",
         lambda v: ("+" if v > 0 else "") + num(v, 0),
         "Pontos médios por operação. Bom: papel perto do esperado ou "
         "acima. Ruim: negativo, ou menos da metade do esperado depois de "
         "30 operações."),
        ("Fator de lucro", "fator_lucro", _fator,
         "Ganhos divididos pelas perdas. Bom: igual ou acima do esperado. "
         "Atenção: entre 80% do esperado e o esperado. Ruim: abaixo de 80% "
         "do esperado (ou abaixo de 1: perde mais do que ganha)."),
        ("Acerto", "acerto", lambda v: pct(v * 100, 0),
         "Operações ganhadoras sobre o total. Bom: igual ou acima do "
         "esperado. Atenção: entre 80% do esperado e o esperado. Ruim: abaixo "
         "de 80% do esperado depois de 30 operações. O valor sozinho não diz "
         "se a estratégia é boa."),
        ("Resultado total", "total", lambda v: _rs(v, 2),
         "Soma com o tamanho real de cada operação. Só fechadas: pode ser "
         "menor que o Acumulado lá em cima, que inclui a aberta."),
        ("Execução", None),
        ("Sinal no mesmo minuto", "mesmo_minuto",
         lambda v: pct(v * 100, 0),
         "Entradas executadas no mesmo minuto do sinal do papel, sobre as "
         "executadas desde o plano em vigor. Bom: 95% ou mais. Atenção: de "
         "80% a 95%. Ruim: abaixo de 80%."),
        ("Derrapagem média", "derrapagem_extra",
         lambda v: ("+" if round(v, 1) > 0 else "") + OR._decimal(v) + " tick",
         "Ticks por ponta além do preço do papel (que já desconta a "
         "derrapagem do plano). Negativo = executou melhor que o papel. Bom: "
         "até 1 tick. Atenção: de 1 a 2 ticks. Ruim: acima de 2 ticks — o "
         "backtest está otimista."),
        ("Atraso médio da ordem", "atraso_ms", _atraso,
         "Tempo entre mandar a entrada e a corretora executar. Bom: até 300 ms. "
         "Atenção: até 1 s. Ruim: acima de 1 s."),
        ("Ordens rejeitadas", "rejeitadas", lambda v: inteiro(int(v)),
         "Ordens que a corretora recusou (entrada, saída, proteção). Conta "
         "cada recusa: uma operação pode somar várias. Recusadas, em Papel × "
         "demo, conta operações e por isso pode dar menos. Bom: zero. "
         "Atenção: até 2. Ruim: mais de 2."),
    ]
    corpo = []
    for linha in linhas:
        if linha[1] is None and len(linha) == 2:
            corpo.append(html.Tr(html.Td(linha[0], colSpan=5),
                                 className="op-cmp-grupo"))
            continue
        rot, chave, fmt, explica = linha
        celulas = [html.Td(_rotulo(rot, explica), className="k")]
        for m, conta in zip(cols, contas):
            texto = val(m, chave, fmt, conta)
            filhos = [texto]
            tom = _tom_execucao(chave, m, esperado) if conta and texto != "—" else None
            if tom:
                rot_tom, cor_tom = _TOM_ETIQUETA[tom]
                filhos.append(_etiqueta(rot_tom, cor_tom))
            celulas.append(html.Td(filhos if tom else texto,
                                   className="n" + ("" if texto != "—" else " mut")))
        corpo.append(html.Tr(celulas))
    cab = html.Tr([html.Th(""), html.Th("Esperado (WFA)", className="n c-esp"),
                   html.Th("Papel", className="n c-pap"),
                   html.Th("Demo", className="n c-dem"),
                   html.Th("Real", className="n c-rea")])
    legenda = html.Div([
        _etiqueta("bom", "verde"), _etiqueta("atenção", "ambar"),
        _etiqueta("ruim", "rosa"),
        html.Span("— faixas no (?) de cada linha; comparação contra o Esperado",
                  className="mut"),
    ], className="op-cmp-leg")
    return html.Div([html.Table([html.Thead(cab), html.Tbody(corpo)],
                                className="op-tabela op-cmp"), legenda],
                    className="op-cmp-wrap")


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
