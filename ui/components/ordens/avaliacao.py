"""Ordens: avaliação papel × demo, selo do backtest e editor de contratos."""
from __future__ import annotations

from datetime import date

from dash import dcc, html

from ..cartao import dica, inteiro, num

from .base import _decimal, _etiqueta, _int_sinal, _reais, _vazio, subtitulo


# ================================================================ avaliação
def selo_backtest(sit: dict | None):
    """"papel = backtest ✓ (N pregões, M operações)" | "K diferenças" (com a
    lista) | "ainda sem pregão conferido"."""
    s = sit or {}
    if not s.get("pregoes"):
        return _etiqueta("ainda sem pregão conferido", "cinza",
                         "Toda manhã a captura roda o backtest do plano nos "
                         "pregões do papel e compara operação por operação. Ainda "
                         "não há pregão conferido.")
    explica = ("Backtest e papel usam o mesmo motor e os mesmos candles: devem "
               "bater operação por operação (hora, lado, preços, motivo da "
               "saída). Bom: ✓. Ruim: qualquer diferença — a variante não pode "
               "subir para a demo até resolver.")
    if s.get("ok"):
        return _etiqueta(f"papel = backtest ✓ ({s['pregoes']} "
                         f"{'pregão' if s['pregoes'] == 1 else 'pregões'}, "
                         f"{s.get('operacoes', 0)} "
                         f"{'operação' if s.get('operacoes') == 1 else 'operações'})",
                         "verde", explica)
    n = int(s.get("diferencas") or 0) or len(s.get("lista") or [])
    lista = "; ".join(
        f"{d.get('nome')} · {d['dia']:%d/%m} ({d.get('n')})"
        if isinstance(d.get("dia"), date) else f"{d.get('nome')} · {d.get('dia')}"
        for d in s.get("lista") or [])
    return html.Span([
        _etiqueta(f"{n} {'diferença' if n == 1 else 'diferenças'}", "rosa", explica),
        html.Span(f" {lista}", className="ord-dif-lista") if lista else None,
    ])


def _fator(v):
    if v is None:
        return "—"
    if v == float("inf"):
        return "sem perdas"
    return num(v, 2)


def tabela_papel_demo(cmp: dict | None, origem: str = "demo"):
    """Papel × Demo (ou Papel × Real, com `origem="real"`) por contrato, nos
    mesmos pregões. A conta real usa a mesma tabela e a mesma régua."""
    c = cmp or {}
    p, d = c.get("papel"), c.get("demo")
    nome = "real" if origem == "real" else "demo"
    if not c.get("pregoes") or d is None:
        return _vazio(f"nenhum pregão na {nome} ainda",
                      "Quando uma variante for para a "
                      f"{nome}, esta tabela compara a execução da {nome} com o "
                      "papel, por contrato.")
    p = p or {}

    def dif(a, b, fmt):
        if a is None or b is None:
            return "—"
        return fmt(b - a)

    pn, dn = int(p.get("n") or 0), int(d.get("n") or 0)
    perdidas = int(d.get("perdidas") or 0)
    mm = int(d.get("mesmo_minuto") or 0)

    def mais(v, casas):
        # o "+" olha o número arredondado, como o _decimal: 0,04 é "0"
        return ("+" if round(v, casas) > 0 else "") + _decimal(v, casas)

    linhas = [
        ("Operações", "Operações fechadas em cada lado. Diferença = entradas que "
         "a demo perdeu (recusa, automação fora do ar). Bom: zero perdidas. Ruim: "
         "perder mais de 1 em 10.", inteiro(pn), inteiro(dn),
         f"{perdidas} {'perdida' if perdidas == 1 else 'perdidas'}" if perdidas
         else "—", "aviso" if perdidas else "mut"),
        ("Pontos por operação", "Pontos médios por operação, por contrato. Bom: "
         "demo a poucos pontos do papel. Ruim: demo bem abaixo — a execução está "
         "custando a vantagem.",
         _int_sinal(p.get("pontos_por_operacao")),
         _int_sinal(d.get("pontos_por_operacao")),
         dif(p.get("pontos_por_operacao"), d.get("pontos_por_operacao"),
             lambda v: _int_sinal(v)), ""),
        ("Fator de lucro", "Pontos ganhos divididos pelos perdidos. Bom: acima de "
         "1,3 e perto do papel. Ruim: abaixo de 1.", _fator(p.get("fator_lucro")),
         _fator(d.get("fator_lucro")),
         dif(p.get("fator_lucro"), d.get("fator_lucro"),
             lambda v: mais(v, 2)) if None not in (p.get("fator_lucro"),
                                                   d.get("fator_lucro"))
         and float("inf") not in (p.get("fator_lucro"), d.get("fator_lucro"))
         else "—", ""),
        ("Sinal no mesmo minuto", "Entradas executadas no mesmo minuto do sinal do "
         "papel, sobre as operações do papel. Bom: 100%. Ruim: abaixo de 90%.",
         "—", f"{num(mm / pn * 100, 1)}%" if pn else "—",
         f"{mm} de {pn}" if pn else "—", "mut"),
        ("Derrapagem média por ponta", "Ticks por ponta. Papel = a derrapagem "
         "que o plano supõe (o backtest e o papel já a descontam). Demo = a que "
         "a demo teve de fato (a do plano mais o que passou dela). Diferença = "
         "o que passou do plano. Bom: diferença perto de 0. Ruim: acima de 1 "
         "tick por ponta — o backtest está otimista.",
         "—" if p.get("derrapagem") is None else f"{_decimal(p['derrapagem'])} tick",
         "—" if d.get("derrapagem") is None else f"{_decimal(d['derrapagem'])} tick",
         mais(d["derrapagem_extra"], 1) if d.get("derrapagem_extra") is not None
         else dif(p.get("derrapagem"), d.get("derrapagem"), lambda v: mais(v, 1)),
         ""),
        ("Recusadas · resolvidas sozinha · chamados", "Entradas que a corretora "
         "recusou, quantas delas a automação resolveu sozinha tentando de novo, e "
         "os chamados que pediram você. Recusadas conta operações: uma por "
         "operação com a entrada recusada, mesmo que a recusa se repita. Ordens "
         "rejeitadas, no Esperado × Papel × Demo, conta cada recusa da corretora "
         "(entrada, saída, proteção) e por isso pode dar mais. Bom: zero "
         "chamados. Ruim: recusas todo dia.", "—", f"{d.get('recusadas', 0)} · {d.get('resolvidas', 0)} · "
         f"{d.get('chamados', 0)}", "—", "mut"),
    ]
    corpo = []
    for rot, explica, vp, vd, vdif, tom in linhas:
        corpo.append(html.Tr([
            html.Td(html.Span([rot, dica(explica)], className="op-rot"), className="k"),
            html.Td(vp, className="n"), html.Td(vd, className="n"),
            html.Td(vdif, className="n" + (f" {tom}" if tom else "")),
        ]))
    cab = html.Tr([html.Th(""), html.Th("Papel", className="n"),
                   html.Th(nome.capitalize(), className="n"),
                   html.Th("Diferença", className="n")])
    return html.Table([html.Thead(cab), html.Tbody(corpo)],
                      className="op-tabela op-cmp")


def avaliacao(situacao_backtest: dict | None, comparativo_demo: dict | None,
              curva=None, comparativo=None,
              comparativo_real: dict | None = None) -> html.Section:
    """A aba Avaliação: Esperado × Papel × Demo × Real (`comparativo`, a
    caixa que o redesenho preenche), a curva Papel × esperado, as tabelas
    Papel × real e Papel × demo por contrato e o selo papel = backtest.
    Dois por linha, na ordem de leitura."""
    def bloco(*filhos):
        return html.Div(list(filhos), className="op-aval-bloco")
    return html.Section(html.Div([
        bloco(subtitulo("Esperado (WFA) × Papel × Demo × Real",
                        "Por contrato e só operações fechadas: o que o "
                        "walk-forward prometeu contra o que o papel e as contas "
                        "fizeram. Cada linha tem o (?) com a faixa boa e a ruim."),
              comparativo if comparativo is not None else []),
        bloco(curva if curva is not None else []),
        bloco(subtitulo("Papel × real", "Mesmos pregões, por contrato, com a "
                        "conta real: quanto a execução de verdade custa contra "
                        "o papel."),
              html.Div(tabela_papel_demo(comparativo_real, "real"),
                       id="av-op-ord-cmp-real", className="op-cmp-caixa")),
        bloco(subtitulo("Papel × demo", "Mesmos pregões, por contrato: quanto a "
                        "execução de verdade custa contra o papel."),
              html.Div(tabela_papel_demo(comparativo_demo), id="av-op-ord-cmp",
                       className="op-cmp-caixa")),
        bloco(subtitulo("Papel × backtest", "Toda manhã a captura roda o "
                        "backtest do plano nos pregões do papel e compara "
                        "operação por operação. Qualquer diferença impede a "
                        "variante de subir para a demo."),
              html.Div(selo_backtest(situacao_backtest), id="av-op-ord-selo",
                       className="ord-selo-bt")),
    ], className="op-aval-grade"),
        id="av-op-ord-avaliacao", className="op-pane op-pane-avaliacao")


# ================================================== contratos da demo (✎)
def ler_contratos(texto) -> int | None:
    """O campo do editor: vazio volta aos contratos do plano (None); fora
    disso, inteiro de 1 em diante — o resto é ValueError com a frase da
    tela."""
    t = str(texto or "").strip()
    if not t:
        return None
    # isdigit() aceita "²" e dígitos de outras escritas, que int() recusa
    if not (t.isascii() and t.isdigit()) or int(t) < 1:
        raise ValueError("digite um número inteiro de contratos (1 ou mais), ou "
                         "deixe vazio para usar os do plano")
    return int(t)


def contratos_antes(proprio, plano) -> str:
    """"antes: 2 · papel segue com 3 (plano)": o que vale hoje na demo e no
    papel, para quem vai mexer no campo (o editor da Operação e a ficha)."""
    if proprio is not None:
        return f"antes: {proprio} · papel segue com {plano or '—'} (plano)"
    return f"hoje: os do plano ({plano or '—'}) · o papel segue com eles"


def custo_stop_texto(contratos, custo: dict | None):
    """"Um stop com 3 contratos = R$ 180 = 36% do limite do dia." —
    `custo` é o de `core.ao_vivo.custo_de_um_stop`."""
    c = custo or {}
    if c.get("reais") is None:
        return html.Span("Custo de um stop desconhecido: o plano usa stop por "
                         "ATR e o papel ainda não operou com ele.", className="mut")
    partes = [f"Um stop com {contratos} "
              f"{'contrato' if contratos == 1 else 'contratos'} = ",
              html.B(_reais(c["reais"]))]
    if c.get("pct_limite") is not None:
        pct = c["pct_limite"]
        partes += [" = ", html.B(f"{_decimal(pct, 0) if pct >= 10 else num(pct, 1)}%"),
                   " do limite do dia."]
        if pct > 100:
            partes += [html.Br(), html.Span(
                "Atenção: um stop sozinho passa do limite do dia — a trava "
                "barraria a entrada. Dá para salvar, mas reveja.",
                className="aviso")]
    else:
        partes.append(" (conta demo sem limite cadastrado).")
    return html.Span(partes)


def editor_contratos() -> html.Div:
    """O popover do ✎ dos cartões, fixo no layout (um só para todas as
    variantes): o callback mostra, preenche e esconde."""
    return html.Div([
        html.H4("Contratos na demo", id="av-op-ord-ctr-titulo",
                className="ord-pop-t"),
        html.Div([
            # debounce: a prévia (que lê o banco) roda ao sair do campo
            # ou no Enter, não a cada tecla
            dcc.Input(id="av-op-ord-ctr-valor", type="text", inputMode="numeric",
                      debounce=True, placeholder="plano",
                      className="ord-pop-inp", autoComplete="off"),
            html.Span(id="av-op-ord-ctr-antes", className="mut"),
        ], className="ord-pop-linha"),
        html.Div(id="av-op-ord-ctr-custo", className="ord-pop-custo"),
        html.P("A mudança vale a partir da próxima operação. Vazio = os "
               "contratos do plano.", className="ord-pop-nota"),
        html.P(id="av-op-ord-ctr-erro", className="ord-pop-erro"),
        html.Div([
            html.Button("Cancelar", id="av-op-ord-ctr-cancelar", n_clicks=0,
                        className="btn-ghost av-btn-sec"),
            html.Button("Salvar", id="av-op-ord-ctr-salvar", n_clicks=0,
                        className="btn-ghost av-btn-principal"),
        ], className="ord-pop-botoes"),
    ], id="av-op-ord-ctr-pop", className="ord-pop", style={"display": "none"})
