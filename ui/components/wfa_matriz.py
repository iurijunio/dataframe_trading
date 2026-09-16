"""A Matriz de Otimização em abas: o Consenso e uma aba por inteligência.

A pergunta da matriz nunca foi "qual configuração rendeu mais". É **de que
tamanho de janela esta estratégia precisa** — e, com sete inteligências, se
o MÉTODO de escolher parâmetro funciona independentemente de quem escolhe.

    Consenso            12 configurações × 6 inteligências, mapa de calor do
                        WFE rolante, ✓ onde os seis portões aprovam, e a
                        ordem: consenso → WFE mediano → pior caso.
    uma por inteligência a tabela de sempre, rolante e ancorado lado a lado,
                        mais o veredito dos seis portões.

É uma grade só: a aba escolhe as colunas e as linhas. O cálculo das sete
matrizes acontece uma vez por varredura (e por estado do holdout) no
servidor; trocar de aba não recalcula nada.
"""

from __future__ import annotations

from dash import dcc, html

from core import wfa

from .cartao import dica

BRL = {"function": "params.value == null ? '' : params.value.toLocaleString('pt-BR',"
                   "{minimumFractionDigits:2,maximumFractionDigits:2})"}
# pt-BR: "104,3%" como nos cartões, e não "104.3%"
_LOC = "toLocaleString('pt-BR',{minimumFractionDigits:%d,maximumFractionDigits:%d})"
PCT100 = {"function": "params.value == null ? '—' : (params.value*100)." + _LOC % (1, 1) + " + '%'"}
PCT0 = {"function": "params.value == null ? '—' : params.value." + _LOC % (0, 0) + " + '%'"}
N2 = {"function": "params.value == null ? '—' : params.value." + _LOC % (2, 2)}

CONSENSO = "consenso"
ROTULOS_CURTOS = {"moda": "Moda", "sharpe": "Sharpe", "centroide_media": "Centroid média",
                  "centroide_mediana": "Centroid mediana", "ulcer": "Drawdown",
                  "alpha": "Alpha", "vizinhanca": "Platô pessimista",
                  "conselho": "Conselho"}
ABAS = [(CONSENSO, "Consenso")] + [(q, ROTULOS_CURTOS.get(q, r))
                                   for r, q in wfa.INTELIGENCIAS]

# ------------------------------------------------------------- os (?)
DESCRICOES = {
    CONSENSO: (
        "Quantas das sete inteligências aprovam cada configuração IS/OOS. "
        "Cada célula é o WFE ROLANTE daquela inteligência, colorido por faixa; "
        "✓ quando os seis portões aprovam, ⚠ quando aprovam com ressalva. A "
        "ordem não é pelo maior WFE: é por quantas aprovam, depois pelo WFE "
        "MEDIANO entre elas (o centro), depois pelo PIOR WFE (o piso). O "
        "walk-forward valida o método de escolher parâmetro — uma "
        "configuração que só uma inteligência aprova mostra a tentativa mais "
        "sortuda, não método funcionando. O maior WFE fica na última coluna, "
        "como informação. O Conselho de Notáveis não entra na contagem: ele é "
        "a votação das outras sete, e contá-lo seria contar os mesmos votos "
        "duas vezes. As cinco primeiras ficam destacadas; a primeira é a "
        "recomendada."),
    "moda": (
        "MODA (Estabilidade). Pega o decil superior das combinações da janela, "
        "ordenado por fator de recuperação, e escolhe o valor que mais se "
        "REPETE em cada parâmetro — depois ancora na combinação existente mais "
        "próxima. Acha o centro da parte densa do platô. Bom quando a região "
        "boa é larga; fraco quando o decil é pequeno demais para ter moda."),
    "sharpe": (
        "SHARPE (Eficiência). Escolhe a combinação de maior Sharpe na janela "
        "(retorno diário anualizado sobre a volatilidade). É a métrica ajustada "
        "ao risco que Pardo recomenda — mas é escolha de PICO: pega o melhor "
        "ponto, e o melhor ponto é o que mais sofre com sobreajuste. Serve de "
        "régua para comparar as inteligências de platô."),
    "centroide_media": (
        "CENTROID (Platô) · Média. Pega o decil superior e usa a MÉDIA de cada "
        "parâmetro, ancorada na combinação existente mais próxima. É o centro "
        "geométrico da região boa. Uma combinação boa e distante ARRASTA o "
        "centro na direção dela — compare com a Mediana para ver se isso "
        "aconteceu."),
    "centroide_mediana": (
        "CENTROID (Platô) · Mediana. Igual à Média, com a MEDIANA de cada "
        "parâmetro — imune a uma combinação boa e distante que puxaria o "
        "centro. Escolhe o meio do platô, onde um pequeno erro de parâmetro "
        "custa pouco. É o padrão sugerido da plataforma."),
    "ulcer": (
        "ESTABILIDADE DE DRAWDOWN. Escolhe o menor Ulcer Index entre as "
        "aprovadas. O Ulcer pune a PROFUNDIDADE e o TEMPO submerso da curva ao "
        "mesmo tempo: dois drawdowns de 5% que duram meses pesam mais que um "
        "de 8% que se recupera em dias. Escolhe a curva mais fácil de operar, "
        "não a mais lucrativa."),
    "alpha": (
        "PROBABILIDADE DO ALPHA. Escolhe a maior estatística t: média do trade "
        "dividida por (desvio ÷ √n). Prefere o edge mais distinguível de ruído, "
        "e o √n pune de propósito a combinação de poucos trades — um resultado "
        "bonito em 20 operações perde para um modesto em 400."),
    "vizinhanca": (
        "PLATÔ PESSIMISTA. Dá nota a cada combinação pelo PIOR QUARTO dos "
        "vizinhos dela na grade, e não pelo resultado dela sozinha — um pico "
        "cercado de prejuízo perde para um ponto bom cercado de pontos bons. "
        "Diferente das Centroides, não cai no vale entre duas ilhas boas e "
        "enxerga o penhasco ao lado, inclusive os vizinhos reprovados nos "
        "critérios. Escolhe onde errar um pouco o parâmetro ainda custa pouco. "
        "Vizinhança: 5% dos valores de cada parâmetro para cada lado. Com um "
        "parâmetro minerado só, a vizinhança é uma linha; o ganho aparece com "
        "dois ou mais variando juntos."),
    "conselho": (
        "CONSELHO DE NOTÁVEIS. As outras sete votam; vence a combinação com "
        "mais indicações, e QUALQUER empate no topo vai para o centroide "
        "mediano das indicadas — nunca para uma que ninguém indicou. Quando a "
        "região é platô, as sete concordam e o Conselho "
        "é firme. A discordância entre elas é informação — a aba Consenso "
        "mostra o mesmo raciocínio no nível da configuração."),
}

# as colunas que confundem, explicadas uma vez, na faixa acima da grade
DICA_ROLANTE = (
    "ROLANTE: a janela de otimização ANDA junto com o tempo, sempre do mesmo "
    "tamanho. Com IS de 12 meses, cada reotimização olha só os últimos 12 "
    "meses e esquece o resto. Adapta-se a mudança de regime — é a preferida "
    "do Pardo.")
DICA_ANCORADO = (
    "ANCORADO: a janela de otimização começa SEMPRE no primeiro dia da base e "
    "vai crescendo. Na última reotimização ela usa toda a história. É mais "
    "estável, mas demora a perceber que o mercado mudou. Comparar os dois diz "
    "de onde vem o edge: ancorado muito melhor → edge estrutural e antigo; "
    "rolante melhor → o mercado mudou e a estratégia precisa acompanhar.")
DICA_MEDIANA = (
    "MEDIANA: o WFE da janela do meio, quando se ordenam os WFE de todas as "
    "janelas. É o secundário, ao lado do global. A média nunca aparece: uma "
    "janela com IS minúsculo produz WFE de 300% ou de −40% e contamina a média "
    "inteira; a mediana nem se mexe.")
DICA_DISPERSAO = (
    "DISPERSÃO: o desvio dos WFE das janelas dividido pela mediana — quanto o "
    "resultado oscila de janela para janela. Cuidado ao ler: com janelas de 3 "
    "a 6 meses o lucro de UMA janela já varia muito só por amostra, e valores "
    "entre 1 e 5 aparecem mesmo numa estratégia sem degradação nenhuma "
    "(simulado com o edge da #40). Use para COMPARAR configurações entre si, "
    "não contra um número fixo.")

DICA_PORTOES = (
    "PORTÕES: os seis do veredito, calculados para cada configuração com a "
    "curva fora da amostra de verdade. ✓ aprovado · ⚠ aprovado com ressalva "
    "(só alertas falharam: drawdown OOS acima de 1,5× o IS ou janelas fora "
    "do mercado) · ✗ reprovado. Um único portão CRÍTICO reprovado basta para "
    "o ✗ — por isso existe '✗ 5/6': lucro OOS, janelas positivas, WFE e "
    "número de trades não se compensam entre si.")


# ------------------------------------------------------------- colunas
def _calor(cortes, tons=("rgba(0,229,160,.30)", "rgba(0,229,160,.20)",
                         "rgba(0,229,160,.11)", "rgba(0,229,160,.05)")):
    """Heatmap verde por FAIXA — 62% e 64% são a mesma coisa.

    Os cortes precisam estar na escala do valor: WFE vem em fração (1,04),
    percentuais em 0–100. A versão anterior usava 90/70/50/30 para o WFE, que
    é fração, e o mapa nunca pintava célula nenhuma.
    """
    return {"styleConditions": [
        {"condition": f"params.value != null && params.value >= {c}",
         "style": {"backgroundColor": t}} for c, t in zip(cortes, tons)]}


WFE_CORTES = (0.9, 0.7, 0.5, 0.3)
PCT_CORTES = (90, 70, 50, 30)

REGRAS_LINHA = {
    "linha-atual": "params.data && params.data.atual",
    "linha-top": "params.data && params.data.top",
    "linha-recomendada": "params.data && params.data.recomendada",
}


def colunas_inteligencia() -> list[dict]:
    return [
        {"field": "config", "headerName": "config", "width": 150,
         "pinned": "left", "cellClass": "col-params"},
        {"field": "portoes_txt", "headerName": "portões", "width": 120,
         "cellClassRules": {"pos": "params.data && params.data.estado == 'aprovado'",
                            "warn": "params.data && params.data.estado == 'aprovado com ressalva'",
                            "neg": "params.data && params.data.estado == 'reprovado'"}},
        {"field": "steps", "headerName": "janelas", "width": 84,
         "type": "numericColumn"},
        {"field": "lucro_mes", "headerName": "lucro/mês", "width": 116,
         "type": "numericColumn", "valueFormatter": BRL,
         "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
        {"field": "lucro_mes_comum", "headerName": "lucro/mês comum", "width": 138,
         "type": "numericColumn", "valueFormatter": BRL,
         "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
        {"field": "wfe", "headerName": "WFE rolante", "width": 116,
         "type": "numericColumn", "valueFormatter": PCT100,
         "cellStyle": _calor(WFE_CORTES)},
        {"field": "wfe_ancorado", "headerName": "WFE ancorado", "width": 126,
         "type": "numericColumn", "valueFormatter": PCT100,
         "cellStyle": _calor(WFE_CORTES)},
        {"field": "wfe_mediana", "headerName": "mediana", "width": 100,
         "type": "numericColumn", "valueFormatter": PCT100},
        {"field": "cv", "headerName": "dispersão", "width": 100,
         "type": "numericColumn", "valueFormatter": N2},
        {"field": "semestres_pct", "headerName": "semestres +", "width": 110,
         "type": "numericColumn", "valueFormatter": PCT0,
         "cellStyle": _calor((100, 80, 60, 40))},
        {"field": "consistencia", "headerName": "janelas +", "width": 98,
         "type": "numericColumn", "valueFormatter": PCT0},
        {"field": "a50", "headerName": "WFE>50", "width": 84,
         "type": "numericColumn", "valueFormatter": PCT0, "cellStyle": _calor(PCT_CORTES)},
        {"field": "a70", "headerName": "WFE>70", "width": 84,
         "type": "numericColumn", "valueFormatter": PCT0, "cellStyle": _calor(PCT_CORTES)},
        {"field": "a90", "headerName": "WFE>90", "width": 84,
         "type": "numericColumn", "valueFormatter": PCT0, "cellStyle": _calor(PCT_CORTES)},
        {"field": "oos_trades", "headerName": "trades", "width": 88,
         "type": "numericColumn"},
        {"field": "fora_do_mercado", "headerName": "fora", "width": 74,
         "type": "numericColumn",
         "cellClassRules": {"warn": "params.value > 0"}},
    ]


def colunas_consenso() -> list[dict]:
    cols = [
        {"field": "posicao", "headerName": "#", "width": 70, "pinned": "left",
         "valueFormatter": {"function": "params.data && params.data.recomendada"
                                        " ? '★ ' + params.value : params.value"}},
        {"field": "config", "headerName": "config", "width": 150,
         "pinned": "left", "cellClass": "col-params"},
    ]
    for q in wfa.VOTANTES:
        est = f"params.data['est_{q}']"
        cols.append({
            "field": f"wfe_{q}", "headerName": ROTULOS_CURTOS[q], "width": 124,
            "type": "numericColumn",
            "valueFormatter": {"function": (
                f"params.value == null ? '—' : (params.value*100)." + (_LOC % (0, 0)) + " + '%'"
                f" + ({est} == 'aprovado' ? '  ✓' : {est} == 'aprovado com ressalva'"
                f" ? '  ⚠' : '')")},
            "cellStyle": _calor(WFE_CORTES)})
    cols += [
        {"field": "aprovam", "headerName": "aprovam", "width": 96,
         "type": "numericColumn",
         "valueFormatter": {"function": "params.value + '/' + params.data.votantes"},
         "cellClassRules": {"pos": "params.value == params.data.votantes",
                            "neg": "params.value == 0"}},
        {"field": "wfe_mediano", "headerName": "WFE mediano", "width": 120,
         "type": "numericColumn", "valueFormatter": PCT100,
         "cellStyle": _calor(WFE_CORTES)},
        {"field": "pior_wfe", "headerName": "pior WFE", "width": 104,
         "type": "numericColumn", "valueFormatter": PCT100},
        {"field": "melhor_wfe", "headerName": "maior WFE", "width": 108,
         "type": "numericColumn", "valueFormatter": PCT100,
         "cellClass": "col-info"},
    ]
    return cols


def colunas(aba: str) -> list[dict]:
    cols = colunas_consenso() if aba == CONSENSO else colunas_inteligencia()
    # a largura escrita vira a MÍNIMA: o grid estica as colunas até a borda
    # da tela, mas nunca as espreme abaixo do que cabe o cabeçalho
    return [{**c, "minWidth": c.get("width", 80)} for c in cols]


# -------------------------------------------------------------- linhas
def linhas(aba: str, dados: dict | None, is_m, oos_m, inteligencia) -> list[dict]:
    """As linhas da aba, com `atual` marcando a configuração aberta abaixo.

    `dados` = {"por_q": {q: [linhas]}, "consenso": [linhas]}. Na aba de uma
    inteligência, "atual" exige também que ela seja a inteligência aberta: a
    mesma configuração em outra aba é outra escolha de parâmetros.
    """
    if not dados:
        return []
    try:
        is_m, oos_m = int(is_m), int(oos_m)
    except (TypeError, ValueError):
        is_m = oos_m = None

    if aba == CONSENSO:
        base = dados.get("consenso", [])
        marca = lambda r: r["is_meses"] == is_m and r["oos_meses"] == oos_m
    else:
        base = dados.get("por_q", {}).get(aba, [])
        marca = lambda r: (r["is_meses"] == is_m and r["oos_meses"] == oos_m
                           and aba == inteligencia)
    fora = []
    for r in base:
        linha = {**r, "atual": bool(marca(r))}
        if aba != CONSENSO:
            linha["portoes_txt"] = (f"{'✓' if r['estado'] == 'aprovado' else '⚠' if r['estado'] == 'aprovado com ressalva' else '✗'} "
                                    f"{r['portoes_ok']}/{r['n_portoes']}")
        fora.append(linha)
    return fora


def sobre(aba: str) -> html.Div:
    """A faixa acima da grade: o que é esta aba, e as colunas que confundem."""
    rotulo = dict(ABAS).get(aba, aba)
    itens = [html.Span([html.Strong(rotulo), dica(DESCRICOES.get(aba, ""))],
                       className="mz-item")]
    if aba == CONSENSO:
        itens += [html.Span(["WFE rolante", dica(DICA_ROLANTE)], className="mz-item"),
                  html.Span(["✓ ⚠ portões", dica(DICA_PORTOES)], className="mz-item"),
                  html.Span("★ recomendada · destaque nas 5 primeiras",
                            className="mz-item mz-muted")]
    else:
        itens += [html.Span(["portões", dica(DICA_PORTOES)], className="mz-item"),
                  html.Span(["rolante", dica(DICA_ROLANTE)], className="mz-item"),
                  html.Span(["ancorado", dica(DICA_ANCORADO)], className="mz-item"),
                  html.Span(["mediana", dica(DICA_MEDIANA)], className="mz-item"),
                  html.Span(["dispersão", dica(DICA_DISPERSAO)], className="mz-item"),
                  html.Span(["lucro/mês", dica(
                      "Lucro fora da amostra dividido pelos meses de "
                      "CALENDÁRIO do OOS — inclusive os meses em que a "
                      "estratégia ficou fora do mercado.")], className="mz-item"),
                  html.Span(["lucro/mês comum", dica(
                      "O lucro/mês de cada configuração medido no MESMO "
                      "período para todas: do OOS que começa mais tarde "
                      "(normalmente o IS24/OOS6) até o fim. O lucro/mês ao "
                      "lado usa o período próprio de cada uma — IS6/OOS3 "
                      "começa a operar anos antes de IS24/OOS6 —, e comparar "
                      "períodos diferentes é comparar mercados diferentes.")],
                      className="mz-item"),
                  html.Span(["semestres + · janelas +", dica(
                      "SEMESTRES +: percentual dos semestres civis da curva "
                      "OOS que lucraram — é a régua do portão (≥ 70%), igual "
                      "para toda configuração. JANELAS +: a mesma conta por "
                      "janela, que fica como informação: com OOS de 3 meses "
                      "(poucos trades) ela reprova por acaso bem mais vezes "
                      "que com OOS de 6.")], className="mz-item"),
                  html.Span(["WFE>50/70/90", dica(
                      "Percentual das janelas cujo WFE passou de 50%, 70% e "
                      "90%. Mostra se o WFE global vem de muitas janelas "
                      "boas ou de poucas excelentes.")], className="mz-item"),
                  html.Span(["trades · fora", dica(
                      "Operações somadas no OOS (portão: ≥ 300) e janelas em "
                      "que nenhuma combinação passou nos critérios, ficando "
                      "fora do mercado.")], className="mz-item")]
    return html.Div(itens, className="mz-sobre")


def aberta(is_m, oos_m, inteligencia) -> list:
    """Qual configuração está aberta no detalhe de baixo — o que antes os
    campos IS, OOS e inteligência mostravam."""
    rotulo = next((r for r, q in wfa.INTELIGENCIAS if q == inteligencia),
                  inteligencia or "—")
    return [html.Span("aberta ", className="mz-muted"),
            html.Strong(f"IS {is_m} / OOS {oos_m} · {rotulo}"),
            html.Span(" · clique numa linha para trocar", className="mz-muted")]


# -------------------------------------------------------------- layout
def secao(grade, veus: list, cabeca_extra=None) -> html.Section:
    """A seção inteira. `grade` é o AgGrid (montado por quem tem os ids);
    `cabeca_extra` entra à direita das abas (o holdout)."""
    return html.Section([
        html.Div([
            html.H2("Matriz de otimização", className="panel-title"),
            dcc.Tabs(id="abas-matriz", value=CONSENSO, className="abas abas-matriz",
                     parent_className="abas-wrap abas-matriz-wrap",
                     children=[dcc.Tab(label=r, value=v, className="aba",
                                       selected_className="aba-on")
                               for v, r in ABAS]),
            cabeca_extra,
        ], className="panel-head mz-head"),
        html.Div([html.Div(sobre(CONSENSO), id="wfa-matriz-sobre"),
                  html.Span(id="wfa-matriz-aberta", className="mz-aberta")],
                 className="mz-faixa"),
        html.Div(grade, className="mz-grade"),
        *veus,
    ], className="panel panel-matriz")
