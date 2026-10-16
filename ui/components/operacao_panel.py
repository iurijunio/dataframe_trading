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

from datetime import datetime, time

import dash_tvlwc
from dash import dcc, html

from .. import theme as T
from ..data import to_epoch
from . import ordens_panel as OR
from . import pregao_panel as PP
from .cartao import FASES, dica, etiqueta_mesmo_assim, inteiro, num, pct

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
         nota_title=None):
    filhos = [_rotulo(rotulo, explica, "op-kpi-r"),
              html.Span(valor, className="op-kpi-v"
                        + (f" {sinal}" if sinal else ""))]
    if nota:
        filhos.append(html.Span(nota, className="op-kpi-n",
                                title=nota_title or ""))
    if barra is not None:
        filhos.append(barra)
    return html.Div(filhos, className="op-kpi")


def _barra(uso_pct: float):
    tom = "ok" if uso_pct < 50 else ("atencao" if uso_pct < 80 else "perigo")
    largura = f"{min(100, round(uso_pct))}%"
    return html.Div(html.Span(className=f"op-barra-uso op-barra-{tom}",
                              style={"width": largura}),
                    className="op-barra")


def kpis(resumo: dict, ops: list[dict], esperado: dict,
         nomes: dict | None = None) -> list:
    """Os seis indicadores do topo (spec §6.2). `ops` é a tabela do dia
    (para contar); `esperado` = {"diferenca": papel − soma das medianas,
    "faixas": faixa atual de cada variante}; `nomes` = ligação → nome."""
    nomes = nomes or {}
    contam = [o for o in ops if o.get("conta")]
    abertas = sum(1 for o in contam if o.get("situacao") == "aberta")
    n = len(contam)
    nota_hoje = f"papel · {n} {'operação' if n == 1 else 'operações'}"
    if abertas:
        nota_hoje += f" · {abertas} aberta{'s' if abertas > 1 else ''}"
    hoje = resumo.get("resultado_hoje") or 0.0

    pos = resumo.get("posicao") or {}
    liq = int(pos.get("liquida") or 0)
    lado, _ = _lado_pos(liq)
    quem = [f"{nomes.get(l, f'#{l}')} {p:+d}"
            for l, p in (pos.get("por_ligacao") or {}).items() if p]
    nota_pos = f"papel {abs(liq)} · demo — contratos"
    if quem:
        nota_pos = " · ".join(quem) + " · " + nota_pos

    pior = resumo.get("pior_momento") or {}
    valor_pior = pior.get("valor")
    limite = resumo.get("limite_dia")
    demo = (resumo.get("contas") or {}).get("demo")
    partes_pior = ([f"às {_hora(pior.get('quando'))}"]
                   if pior.get("quando") else [])
    barra = None
    if limite:
        uso = max(0.0, -(valor_pior or 0.0)) / limite * 100
        partes_pior.append(f"limite do dia R$ {inteiro(int(round(limite)))}")
        barra = _barra(uso)
    elif demo:
        partes_pior.append("conta demo sem limite cadastrado")
    else:
        partes_pior.append("portfólio sem conta demo")
    nota_pior = " · ".join(partes_pior)

    acum = resumo.get("acumulado") or {}
    nota_acum = (f"{acum.get('pregoes', 0)} pregões · "
                 f"{acum.get('operacoes', 0)} operações · desde o plano em vigor")

    dif = (esperado or {}).get("diferenca")
    faixas = [f for f in (esperado or {}).get("faixas") or [] if f]
    if dif is None:
        valor_esp, sinal_esp = "—", None
        nota_esp = (esperado or {}).get("aviso") or "plano sem expectativa gravada"
    else:
        valor_esp, sinal_esp = _rs(dif), _sinal(dif)
        nota_esp = f"{'acima' if dif >= 0 else 'abaixo'} da mediana"
        if faixas:
            dentro = sum(1 for f in faixas if f in ("p10_p50", "p50_p90"))
            nota_esp += f" · {dentro} de {len(faixas)} dentro da faixa"
            baixo = faixas.count("abaixo_p10")
            alto = faixas.count("acima_p90")
            if baixo:
                nota_esp += f" · {baixo} abaixo do p10"
            if alto:
                nota_esp += f" · {alto} acima do p90"

    return [
        _kpi("Resultado hoje",
             "Soma do papel de hoje das variantes: operações fechadas mais a "
             "aberta pelo preço do último candle (provisório). Operação fora "
             "do período em que a variante estava ligada não entra. Bom: "
             "positivo. Ruim: perto do limite de perda do dia.",
             _rs(hoje), nota_hoje, _sinal(hoje)),
        _kpi("Posição agora",
             "Contratos em aberto agora, somando as variantes (comprado "
             "soma, vendido subtrai). Bom: no máximo a soma dos contratos "
             "dos planos. Atenção: variantes em lados opostos se anulam "
             "aqui — veja quem está posicionado no texto de baixo.",
             lado, nota_pos, "acc" if liq else None,
             nota_title=nota_pos),
        _kpi("Pior momento hoje",
             "O ponto mais baixo do resultado de hoje, minuto a minuto "
             "(fechadas mais a aberta pelo preço de cada minuto), contra o "
             "limite de perda diária da conta demo. Bom: abaixo de 50% do "
             "limite. Ruim: acima de 80% — a mesa encerraria o dia.",
             _rs(valor_pior), nota_pior, _sinal(valor_pior), barra),
        _kpi("Acumulado no papel",
             "Tudo o que o papel fez desde que o plano atual de cada variante "
             "passou a valer (recomeça quando o plano muda). Inclui a "
             "operação aberta pelo valor provisório. Bom: dentro ou acima da "
             "faixa esperada. Ruim: abaixo do p10.",
             _rs(acum.get("valor")), nota_acum, _sinal(acum.get("valor"))),
        _kpi("Contra o esperado",
             "Papel acumulado menos a soma das medianas que a Candidata "
             "prometeu para o mesmo número de pregões. Por variante, a faixa "
             "em que ela está: p10 = em 10% dos sorteios da Candidata o "
             "resultado ficou abaixo disso. Bom: entre p10 e p90. Ruim: "
             "abaixo do p10 — o papel está pior que 9 em 10 cenários.",
             valor_esp, nota_esp, "aviso" if "abaixo_p10" in faixas
             else sinal_esp),
        _kpi("Papel × demo hoje",
             "Diferença por contrato entre o papel e a conta demo nas mesmas "
             "operações — quanto a execução de verdade custa. Bom: perto de "
             "zero (até 1 tick de derrapagem por ponta). Ruim: demo pior "
             "todo dia.",
             "—", "veja Avaliação › Papel × demo"),
    ]


# -------------------------------------------------------------- variantes
_STATUS = {"pulado": ("pregão pulado", "rosa"),
           "interrompido": ("interrompido", "rosa"),
           "nao_conferido": ("não conferido", "ambar"),
           "falha": ("falha no cálculo", "rosa"),
           None: ("sem papel hoje", "cinza")}
_APAGADO = ("pulado", "interrompido", "nao_conferido", "falha")


# (rótulo, classe) de cada botão de ação. Num lugar só porque são duas as
# mãos que os desenham: o redesenho que lê o banco e o callback leve que só
# troca o rótulo para "Confirmar?" no primeiro clique.
_BOTOES = {
    "membro-desligar": ("Pausar", "btn-ghost btn-sm av-btn-sec op-var-botao"),
    "membro-ligar": ("Ligar", "btn-ghost btn-sm av-btn-principal op-var-botao"),
    "pf-desligar": ("Desligar portfólio", "btn-ghost av-btn-sec"),
    "pf-ligar": ("Ligar portfólio", "btn-ghost av-btn-principal"),
    # o interruptor do Envio de ordens da conta demo (o rótulo diz o estado)
    "envio-desligar": ("● Envio de ordens ligado", "btn-ghost ord-envio ord-envio-on"),
    "envio-ligar": ("○ Envio de ordens desligado", "btn-ghost ord-envio"),
}


def estado_botao(acao, alvo, armado) -> tuple[str, str]:
    """(rótulo, classe) do botão, armado ou não."""
    rotulo, classe = _BOTOES[acao]
    if armado == f"{acao}:{alvo}":
        return "Confirmar?", classe + " av-armado"
    return rotulo, classe


def _botao(acao, alvo, armado, title=""):
    rotulo, classe = estado_botao(acao, alvo, armado)
    return html.Button(rotulo, n_clicks=0, title=title, className=classe,
                       id={"type": "av-op-acao", "acao": acao, "id": alvo})


def _contratos_demo(v: dict) -> html.Span:
    """"demo 2 ✎": os contratos na conta demo, com o lápis que abre o
    editor. Sem número gravado a demo usa os do plano — na fase demo isso
    se diz; no papel fica "—" (nada vai à conta)."""
    proprio = v.get("contratos_demo")
    if proprio is not None:
        texto = f"demo {proprio}"
    elif v.get("fase") == "demo" and v.get("contratos") is not None:
        texto = f"demo {v['contratos']} (do plano)"
    else:
        texto = "demo —"
    return html.Span([
        html.B(texto, className="op-var-ctr"),
        html.Button("✎", n_clicks=0, className="ord-ctr-editar",
                    id={"type": "av-op-ord-ctr", "id": v["ligacao_id"]},
                    title="Mudar os contratos desta variante na conta demo "
                          "(o papel segue com os do plano)"),
    ], className="ord-ctr")


def cartao_variante(v: dict, armado) -> html.Div:
    lig = v["ligacao_id"]
    nome = v["nome"]
    status = v.get("status")
    pos_txt, pos_tom = _lado_pos(int(v.get("posicao") or 0))
    if v.get("ligada"):
        botao = _botao("membro-desligar", lig, armado,
                       "Pausar esta variante: as operações dela deixam de "
                       "contar a partir de agora (o papel segue calculando, "
                       "em cinza). Clique duas vezes para confirmar.")
    else:
        botao = _botao("membro-ligar", lig, armado,
                       "Ligar esta variante: as operações dela voltam a "
                       "contar. Clique duas vezes para confirmar.")
    cab = html.Div([
        amostra(v.get("cor"), v.get("ligada", True)),
        html.Span(nome, className="op-nome", title=nome),
        _etiqueta(pos_txt, pos_tom),
        botao,
    ], className="op-var-cab")

    acerto = v.get("acerto")
    valores = html.Div([
        html.Span(_rs(v.get("hoje")), className="op-var-v "
                  + (_sinal(v.get("hoje")) or "")),
        html.Span(str(v.get("n_ops") or 0), className="op-var-v"),
        html.Span("—" if not acerto or acerto.endswith("/0") else acerto,
                  className="op-var-v"),
        html.Span(_rs(v.get("acumulado")), className="op-var-v "
                  + (_sinal(v.get("acumulado")) or "")),
    ], className="op-var-grade")

    ctr = v.get("contratos")
    tags = []
    if not v.get("ligada", True):
        tags.append(_etiqueta("pausada", "cinza"))
    if status in _STATUS:
        tags.append(_etiqueta(*_STATUS[status]))
    if v.get("gravado_mesmo_assim"):
        tags.append(etiqueta_mesmo_assim(v.get("pendencias")))
    rodape = html.Div([
        html.Span(["contratos ",
                   html.B(f"papel {'—' if ctr is None else ctr}",
                          className="op-var-ctr"), " · ",
                   _contratos_demo(v)]),
        html.Span(f"plano #{v['plano_id']}" if v.get("plano_id")
                  else "sem plano", className="op-var-plano"),
        html.Span(FASES.get(v.get("fase") or "papel", v.get("fase")),
                  className="op-var-fase"),
        *tags,
    ], className="op-var-rodape")

    filhos = [cab, valores, rodape]
    if status in _APAGADO and v.get("motivo"):
        filhos.append(html.P(v["motivo"], className="op-var-motivo"))
    classe = "op-var"
    if not v.get("ligada", True):
        classe += " op-var-off"
    if status in _APAGADO:
        classe += " op-var-apagada"
    return html.Div(filhos, className=classe)


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


_SEM_VARIANTES = html.P("Este portfólio não tem variantes — adicione em "
                        "Portfólio e ligue em Ao vivo › Estratégias.",
                        className="av-vazio op-vazio")


def cartoes(vs: list[dict], armado) -> list:
    """Só os cartões: a caixa que rola fica fixa no layout (ver `bloco`)."""
    return [cartao_variante(v, armado) for v in vs] if vs else [_SEM_VARIANTES]


def cabecalho_colunas():
    return html.Div([
        _rotulo("Hoje", "Resultado de hoje da variante (fechadas mais a "
                "aberta provisória). Bom: positivo. Ruim: perda maior que a "
                "perda média do plano."),
        _rotulo("Operações", "Operações de hoje que contam. Bom: perto da "
                "média de operações por pregão do plano. Atenção: muito acima "
                "(a estratégia está girando demais) ou zero num dia com "
                "movimento (confira se o papel está calculando)."),
        _rotulo("Acerto", "Ganhadoras sobre fechadas hoje. Bom: perto do "
                "acerto esperado (veja o Comparativo; acima de 40–50% na "
                "maioria das estratégias). Ruim: bem abaixo dele por vários "
                "pregões. Um dia sozinho diz pouco."),
        _rotulo("Acumulado", "Papel desde o plano em vigor desta variante. "
                "Bom: dentro da faixa esperada (veja Papel × esperado, Por "
                "variante). Ruim: abaixo do p10."),
    ], className="op-var-cols")


def legenda(vs: list[dict], ocultas) -> html.Div:
    """Um chip por variante (clicar esconde/mostra no gráfico) e a chave
    dos símbolos, embaixo."""
    return html.Div([html.Div(chips(vs, ocultas), className="op-chips"),
                     _CHAVE], className="op-legenda-in")


_CHAVE = html.Span("▲ compra · ▼ venda · ● saída (■ quando a cor repete) · "
                   "tracejado = stop/alvo da posição aberta · cinza = fora do "
                   "período ligado", className="op-legenda-chave")


def chips(vs: list[dict], ocultas) -> list:
    """Só os chips: a fileira que rola fica fixa no layout."""
    ocultas = set(ocultas or [])
    out = []
    for v in sorted(vs, key=lambda x: x.get("cor") or 0):
        off = v["ligacao_id"] in ocultas
        out.append(html.Button(
            [amostra(v.get("cor")), html.Span(v["nome"], className="op-chip-nome")],
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
    if sit == "aberta":
        saida = html.Span("aberta", className="acc")
        marcado = int(o["entry_px"]) + int(o["side"]) * pts
        preco_saida = _cel(_preco(marcado), "n acc",
                           "preço marcado no último candle calculado")
        saiu = f"stop {_preco(o.get('stop_px'))} · alvo {_preco(o.get('alvo_px'))}"
        saiu_cls = "t acc"
    elif sit in _ABERTA_PARADA:
        # aberta no banco, mas não é posição de agora: o stop/alvo gravado
        # é de quando o motor parou, mostrá-lo seria dizer que ainda vale
        rotulo = _ABERTA_PARADA[sit]
        if sit == "congelada" and o.get("nota"):
            rotulo = f"{rotulo} — {o['nota']}"
        saida = html.Span(rotulo, className="aviso",
                          title=o.get("nota") or rotulo)
        preco_saida = _cel("—", "n")
        saiu, saiu_cls = "—", "t mut"
    else:
        saida = _hora(o.get("exit_ts"))
        preco_saida = _cel(_preco(o.get("exit_px")), "n")
        saiu = _SAIU_POR.get(o.get("reason"), "—")
        saiu_cls = "t mut"
    nome = o.get("variante") or "—"
    var = [html.Div([amostra(o.get("cor"), o.get("conta", True)),
                     html.Span(nome, className="op-nome-tab", title=nome)],
                    className="op-var-cel")]
    if not o.get("conta", True):
        var.append(html.Span("fora do período ligado", className="op-fora-txt"))
    resultado = [_rs(o.get("liquido"), 2)]
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
        _cel(f"{o.get('contratos')} / {_ctr_demo(o.get('demo'))}", "n"),
        _cel(_preco(o.get("entry_px")), "n"),
        preco_saida,
        _cel(("+" if pts > 0 else "-" if pts < 0 else "") + inteiro(abs(pts)),
             "n " + (_sinal(pts) or "")),
        _cel(resultado, "n " + (_sinal(o.get("liquido")) or "")),
        _cel(saiu, saiu_cls),
        _papel_x_demo(o.get("demo")),
    ], className=classe)


def _ctr_demo(d) -> str:
    if not d or d.get("contratos") is None:
        return "—"
    c = float(d["contratos"])
    return str(int(c)) if c == int(c) else num(c, 1)


def _papel_x_demo(d):
    """Derrapagem além do plano da mesma operação na demo, por ponta
    (entrada · saída), em ticks; sem a demo nela, "—"."""
    if not d:
        return _cel("—", "n mut")
    e, s = d.get("derrapagem_entrada"), d.get("derrapagem_saida")
    if e is None and s is None:
        return _cel("não executada" if d.get("preco_entrada") is None else "—",
                    "n mut")

    def f(v):
        if v is None:
            return "—"
        return str(int(round(v))) if abs(v - round(v)) < 1e-9 else num(v, 1)
    pior = max(x for x in (e, s) if x is not None)
    return _cel(f"{f(e)} · {f(s)} ticks", "n" + (" aviso" if pior > 2 else ""))


def tabela_operacoes(ops: list[dict]):
    if not ops:
        return html.P("nenhuma operação de papel neste pregão até agora",
                      className="av-vazio op-vazio")

    def th(texto, explica=None, n=False):
        return html.Th([texto] + ([dica(explica)] if explica else []),
                       className="n" if n else "")
    cab = html.Tr([
        th("Entrada"), th("Saída"), th("Variante"), th("Lado"),
        th("Contr. papel / demo", "Contratos da operação no papel (os do "
           "plano) e na demo (a demo tem a tabela própria, acima). Bom: os dois iguais ao plano. Ruim: "
           "demo com mais contratos que o plano (risco maior que o medido).",
           True),
        th("Preço entrada", n=True), th("Preço saída", n=True),
        th("Pontos", "Pontos a favor (+) ou contra (−) por contrato, já com a "
           "derrapagem do plano. Bom: ganhos maiores que as perdas na média "
           "do dia. Ruim: perdas no tamanho do stop seguidas.", True),
        th("Resultado papel", "Em reais, com os contratos e os custos do "
           "plano. Na aberta é provisório: o preço do último candle. Bom: a "
           "média por operação do plano ou mais.", True),
        th("Saiu por"),
        th("Papel × demo", "Derrapagem da demo além da que o plano supõe, na "
           "mesma operação, por ponta (entrada · saída), em ticks. Bom: perto "
           "de 0. Ruim: acima de 2 ticks (âmbar). \"não executada\" = a demo "
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
def _banda(tom, texto, acao=None, explica=None):
    filhos = [html.Strong(texto, className="pg-alerta-t")]
    if acao:
        filhos.append(html.Span(acao, className="pg-alerta-a"))
    if explica:
        filhos.append(dica(explica))
    return html.Div(filhos, className=f"pg-alerta pg-alerta-{tom}")


def faixa_situacao(estado: dict | None, agora: datetime) -> list:
    """A captura (mesma `situacao` do Pregão) e o papel: quando foi
    calculado, se ficou para trás, se falhou."""
    sit = PP.situacao(estado, agora)
    papel = (estado or {}).get("papel") or {}
    em = PP._data(papel.get("calculado_em"))
    erros = papel.get("erros") or {}
    out = []
    if sit["tom"] in ("rosa", "ambar"):
        texto = sit["texto"]
        if not sit["ativa"] and em:
            texto += f" — papel congelado em {em:%H:%M}"
        out.append(_banda(sit["tom"], texto, sit["acao"]))
    elif not sit["pregao"]:
        out.append(_banda("cinza", "Mercado fechado",
                          "a tela mostra o último pregão calculado"))
    if erros.get("calculo"):
        out.append(_banda("rosa", "O papel de hoje não foi calculado na última "
                          "volta", "a captura tenta de novo no próximo candle",
                          f"Erro: {erros['calculo']}"))
    if erros.get("conferencia"):
        out.append(_banda("ambar", "A conferência do papel falhou",
                          "tenta de novo na próxima janela de conferência",
                          f"Erro: {erros['conferencia']}"))
    if papel.get("pendente"):
        out.append(_banda("ambar", "Papel atrasado: banco ocupado",
                          "uma mineração está gravando; o papel é refeito na "
                          "próxima volta"))
    linha = (f"papel calculado às {em:%H:%M:%S} de {em:%d/%m}" if em
             else "papel ainda não calculado desde que a captura abriu")
    out.append(html.P([linha, dica(
        "A captura recalcula o papel a cada candle novo de 1 minuto; a "
        "tela relê as operações só quando esse horário muda. Bom: no "
        "pregão, menos de 2 minutos atrás.")], className="op-calculado"))
    return out


_TIPO_ALERTA = {"mesmo_assim": ("gravado mesmo assim", "ambar"),
                "pulado": ("pregão pulado", "rosa"),
                "interrompido": ("interrompido", "rosa"),
                "nao_conferido": ("não conferido", "ambar"),
                "falha": ("falha no cálculo", "rosa"),
                "divergencia": ("candles mudaram", "ambar")}


def lista_alertas(alertas: list[dict]) -> list:
    if not alertas:
        return [html.P("nada pede atenção neste portfólio",
                       className="op-alerta-vazio")]
    out = []
    for a in alertas:
        rot, tom = _TIPO_ALERTA.get(a.get("tipo"), ("atenção", "ambar"))
        out.append(html.Div([_etiqueta(rot, tom),
                             html.Span(a.get("texto") or "", className="op-alerta-t")],
                            className=f"op-alerta op-alerta-{tom}"))
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


def tabela_comparativo(c: dict):
    """Esperado (WFA) × Papel × Demo × Real, por contrato (spec §6.7)."""
    cols = [c.get("esperado_wfa"), c.get("papel"), c.get("demo"), c.get("real")]
    contas = (False, False, True, True)

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
         "do plano (a demo também). Bom: papel perto do esperado. Ruim: "
         "papel bem abaixo por muitos pregões."),
        ("Pontos por operação", "pontos_por_operacao",
         lambda v: ("+" if v > 0 else "") + num(v, 0),
         "Pontos médios por operação. Bom: papel perto do esperado ou "
         "acima. Ruim: negativo, ou menos da metade do esperado depois de "
         "30 operações."),
        ("Fator de lucro", "fator_lucro", _fator,
         "Ganhos divididos pelas perdas. Bom: acima de 1,3. Ruim: abaixo "
         "de 1 (perde mais do que ganha)."),
        ("Acerto", "acerto", lambda v: pct(v * 100, 0),
         "Operações ganhadoras sobre o total. Bom: papel a até 5 pontos "
         "percentuais do esperado. Ruim: 10 pontos ou mais abaixo do "
         "esperado depois de 30 operações. O valor sozinho não diz se a "
         "estratégia é boa."),
        ("Resultado total", "total", lambda v: _rs(v, 2),
         "Soma com o tamanho real de cada operação. Só fechadas: pode ser "
         "menor que o Acumulado lá em cima, que inclui a aberta."),
        ("Execução", None),
        ("Sinal no mesmo minuto", "mesmo_minuto",
         lambda v: pct(v * 100, 0),
         "Entradas executadas no mesmo minuto do sinal do papel, sobre as "
         "executadas desde o plano em vigor. Bom: 100%. Ruim: abaixo de 90%."),
        ("Derrapagem média", "derrapagem_extra",
         lambda v: ("+" if round(v, 1) > 0 else "") + num(v, 1) + " tick",
         "Ticks por ponta além do preço do papel (que já desconta a "
         "derrapagem do plano). Negativo = executou melhor que o papel. Bom: "
         "perto de 0. Ruim: acima de 1 tick — o backtest está otimista."),
        ("Atraso médio da ordem", "atraso_ms", _atraso,
         "Tempo entre mandar a entrada e a corretora executar. Bom: menos "
         "de 1 s. Ruim: acima de 2 s."),
        ("Ordens rejeitadas", "rejeitadas", lambda v: inteiro(int(v)),
         "Ordens que a corretora recusou (entrada, saída, proteção). Bom: "
         "zero. Ruim: recusa todo dia."),
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
            celulas.append(html.Td(texto,
                                   className="n" + ("" if texto != "—" else " mut")))
        corpo.append(html.Tr(celulas))
    cab = html.Tr([html.Th(""), html.Th("Esperado (WFA)", className="n"),
                   html.Th("Papel", className="n"), html.Th("Demo", className="n"),
                   html.Th("Real", className="n")])
    return html.Table([html.Thead(cab), html.Tbody(corpo)],
                      className="op-tabela op-cmp")


# --------------------------------------------------------------- cabeçalho
def interruptor_envio(conta_id, envio: bool | None, armado):
    """O Envio de ordens da conta demo, com a confirmação de dois cliques
    (desligar encerra as posições da automação). Sem conta demo: nada."""
    if conta_id is None or envio is None:
        return None
    if envio:
        return _botao("envio-desligar", conta_id, armado,
                      "Desliga o envio de ordens desta conta: a automação "
                      "encerra as posições dela e para de mandar ordens (o "
                      "papel continua). Clique duas vezes para confirmar.")
    return _botao("envio-ligar", conta_id, armado,
                  "Liga o envio de ordens desta conta: as variantes na fase "
                  "demo passam a operar de verdade na conta demo. Precisa do "
                  "limite de perda do dia cadastrado. Clique duas vezes.")


def cabecalho(pf: dict, resumo: dict, *, contrato=None) -> list:
    contas = resumo.get("contas") or {}
    demo, real = contas.get("demo"), contas.get("real")
    cap = resumo.get("capital")

    def item(rot, valor):
        return html.Span([rot + " ", html.B(valor)], className="op-meta-i")
    n, op = resumo.get("n_variantes", 0), resumo.get("n_operando", 0)
    # o estado da captura traz o contrato do dia como dicionário: um dict
    # como filho quebra o desenho e o Dash devolve o menu à aba anterior
    if isinstance(contrato, dict):
        contrato = contrato.get("simbolo")
    return [
        _etiqueta("ligado", "verde") if pf.get("ligado")
        else _etiqueta("desligado", "cinza"),
        html.Div([
            html.Span(["opera ", html.B(contrato or "—", className="mono"),
                       dica("O contrato do mês em que a demo manda as ordens "
                            "hoje (o gráfico mostra o WIN$N, a série "
                            "contínua). Troca sozinho na rolagem.")],
                      className="op-meta-i"),
            item("Ativo", "WIN$N"),
            item("Conta demo", demo["nome"] if demo else "—"),
            item("Conta real", real["nome"] if real else "—"),
            item("Capital", "—" if cap is None else f"R$ {inteiro(int(round(cap)))}"),
            html.Span([f"{n} {'variante' if n == 1 else 'variantes'} · ",
                       html.B(f"{op} operando"),
                       dica("Operando = papel rodando hoje, com a variante e o "
                            "portfólio ligados.")],
                      className="op-meta-i"),
        ], className="op-meta"),
    ]


def botoes_portfolio(pf: dict, armado, *, conta_id=None, envio=None) -> list:
    pid = pf["portfolio_id"]
    sw = interruptor_envio(conta_id, envio, armado)
    antes = [sw] if sw is not None else []
    if pf.get("ligado"):
        return antes + [_botao("pf-desligar", pid, armado,
                               "Para o portfólio inteiro: as operações deixam de "
                               "contar a partir de agora. Clique duas vezes.")]
    return antes + [_botao("pf-ligar", pid, armado,
                           "Libera as variantes ligadas do portfólio para o papel. "
                           "Clique duas vezes.")]


# -------------------------------------------------------------------- bloco
def _sec_head(titulo, nota, *direita, classe=""):
    return html.Div([
        html.Div([html.H3(titulo, className="panel-title av-sec-titulo"),
                  html.P(nota, className="av-sec-nota")]),
        *([html.Div(list(direita), className="pg-barra")] if direita else []),
    ], className=("av-sec-head op-head " + classe).strip())


def _curva_papel_esperado():
    """A curva Papel × esperado — mora dentro da Avaliação (rascunho v2)."""
    return html.Section([
        _sec_head("Papel × esperado", "Acumulado desde que o plano em "
                  "vigor passou a valer, contra a faixa que a "
                  "Candidata prometeu.",
                  dcc.RadioItems(
                      id="av-op-curva-modo", value="portfolio",
                      className="pg-tf",
                      options=[{"label": "Portfólio",
                                "value": "portfolio"},
                               {"label": "Por variante",
                                "value": "variante"}]),
                  dcc.Dropdown(id="av-op-curva-variante",
                               clearable=False, disabled=True,
                               className="dd op-dd-curva",
                               placeholder="variante…"),
                  classe="pg-grafico-head"),
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
    ], className="panel")


def bloco():
    """A sub-tela inteira; começa escondida.

    Ordem (spec ordens §8, rascunho v2): saúde, chamados, cabeçalho, os
    três números da demo (e os do papel), Posições abertas, variantes |
    gráfico, Operações do dia (demo e papel), Diário do dia, Avaliação."""
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
        html.Div(id="av-op-ord-saude", className="ord-saude-caixa"),
        html.Div(id="av-op-ord-chamados", className="ord-chamados-caixa"),
        html.Section([
            html.Div([
                html.Div([
                    html.Label("Portfólio", className="op-pf-rot"),
                    html.Div([
                        dcc.Dropdown(id="av-op-portfolio", clearable=False,
                                     searchable=False, persistence=True,
                                     persistence_type="local",
                                     className="dd op-dd-pf",
                                     placeholder="escolha o portfólio…"),
                        html.Div(id="av-op-cabecalho", className="op-cab-info"),
                    ], className="op-pf-linha"),
                ], className="op-cab-esq"),
                html.Div([
                    html.Div(id="av-op-botoes", className="op-botoes"),
                    html.Button("Abrir em Estratégias", id="av-op-ficha",
                                n_clicks=0, className="btn-ghost av-btn-sec",
                                title="Abre Ao vivo › Estratégias, onde ficam "
                                      "o portfólio, as contas e a ficha de "
                                      "cada variante"),
                ], className="op-cab-dir"),
            ], className="op-cab"),
            html.Div(id="av-op-situacao", className="op-situacao"),
            html.Div(id="av-op-aviso", className="av-aviso"),
        ], className="panel op-topo"),
        html.Div(id="av-op-ord-numeros", className="ord-numeros-caixa"),
        html.Div(id="av-op-kpis", className="op-kpis"),
        html.Section([
            _sec_head("Posições abertas", "O que está na corretora agora, "
                      "conferido com o que o papel quer."),
            html.Div(id="av-op-ord-posicoes", className="op-tabela-caixa ord-caixa"),
        ], className="panel"),
        html.Div([
            html.Section([
                _sec_head("Variantes", "Posição aberta primeiro, depois o "
                          "resultado do dia."),
                html.Div([html.Div(id="av-op-var-cab"),
                          html.Div(id="av-op-var-lista", className="op-var-lista"),
                          html.Div(id="av-op-risco")],
                         id="av-op-variantes", className="op-variantes"),
                OR.editor_contratos(),
            ], className="panel op-painel-var"),
            html.Section([
                _sec_head("WIN$N ao vivo", "Entradas e saídas de cada "
                          "variante. Role para dar zoom; arraste para voltar "
                          "no dia.",
                          dcc.RadioItems(
                              id="av-op-tf", value="M1", className="pg-tf",
                              options=[{"label": "1 min", "value": "M1"},
                                       {"label": "5 min", "value": "M5"},
                                       {"label": "15 min", "value": "M15"}]),
                          html.Button("Voltar para agora", id="av-op-agora",
                                      n_clicks=0, className="btn-ghost btn-sm"),
                          html.Button("Tela cheia", id="av-op-cheia",
                                      n_clicks=0, className="btn-ghost btn-sm"),
                          classe="pg-grafico-head"),
                html.Div(dash_tvlwc.Tvlwc(id="av-op-grafico", series=[],
                                          chartOptions=T.CHART_OPTIONS,
                                          height="100%"),
                         id="av-op-grafico-caixa", className="pg-grafico op-grafico"),
                # As caixas que rolam (chips, cartões, tabela) são fixas no
                # layout e só o conteúdo delas é trocado: recriadas a cada
                # releitura do papel (uma por minuto), a rolagem voltava ao
                # topo no meio da leitura.
                html.Div(html.Div([html.Div(id="av-op-chips",
                                            className="op-chips"), _CHAVE],
                                  className="op-legenda-in"),
                         id="av-op-legenda", className="op-legenda"),
            ], className="panel op-painel-grafico"),
        ], className="op-grade"),
        html.Section([
            _sec_head("Operações do dia na demo", "Na conta demo · derrapagem = "
                      "diferença para o preço do papel, por ponta."),
            html.Div(id="av-op-ord-operacoes", className="op-tabela-caixa ord-caixa"),
        ], className="panel"),
        html.Section([
            _sec_head("Operações do dia no papel", "Todas as variantes, ligadas "
                      "ou não. A demo está na tabela de cima.",
                      dcc.Dropdown(id="av-op-filtro", value="todas",
                                   clearable=False, className="dd op-dd-filtro",
                                   options=[{"label": "Todas as variantes",
                                             "value": "todas"}]),
                      classe="pg-grafico-head"),
            html.Div(id="av-op-operacoes", className="op-operacoes op-tabela-caixa"),
        ], className="panel"),
        html.Section([
            _sec_head("Diário do dia", "Tudo o que a automação fez, com hora.",
                      dcc.RadioItems(
                          id="av-op-ord-diario-filtro", value="tudo",
                          className="pg-tf",
                          options=[{"label": "Tudo", "value": "tudo"},
                                   {"label": "Só problemas",
                                    "value": "problemas"}]),
                      classe="pg-grafico-head"),
            html.Div(id="av-op-ord-diario", className="ord-diario"),
        ], className="panel"),
        OR.avaliacao(None, None, curva=_curva_papel_esperado()),
        html.Section([
            _sec_head("Esperado (WFA) × Papel × Demo × Real", "Por "
                      "contrato, para comparar mesmo com tamanhos "
                      "diferentes. Só operações fechadas."),
            html.Div(id="av-op-comparativo", className="op-cmp-caixa"),
        ], className="panel"),
        html.Section([
            _sec_head("Alertas", "O que pede atenção neste portfólio."),
            html.Div(id="av-op-alertas", className="av-corpo op-alertas"),
        ], className="panel"),
    ], id="av-bloco-operacao", className="op-bloco", style={"display": "none"})
