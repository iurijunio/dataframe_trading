"""Aba Detalhes: o que ajustar na estratégia.

A aba Robustez pergunta "isto é sorte?". Aqui a pergunta é operacional — e
cada bloco aponta para um campo da camada 4 ou para a lógica do sinal:

    Sequências            -> stop diário e pausa após derrotas
    Eficiência            -> o problema é a entrada ou a saída?
    Risco por trade       -> tamanho de posição, com número
    Exposição e ritmo     -> limite de operações por dia
    Diagnóstico do motor  -> quanto do resultado depende de suposição

Todo cartão traz o (?) com faixa de referência. O cálculo mora em
core/detalhes.py e não sabe que existe tela.
"""

from __future__ import annotations

from dash import dcc, html

from .cartao import brl, card, faixa, inteiro, num, secao, vazio


# ------------------------------------------------------------- sequências
def _sequencias(s):
    if not s:
        return None
    fora = [
        card("ganhos seguidos (média)", num(s["media_ganhos"], 1),
             "Quantos trades vencedores em fila, em média. Comparado com a "
             "média de perdas seguidas, mostra de que lado a estratégia tem "
             "inércia. Sozinho não é bom nem ruim — é o par que informa.",
             None,
             f"máx {s['max_ganhos']} · {inteiro(s['n_sequencias_ganho'])} séries"),
        card("perdas seguidas (média)", num(s["media_perdas"], 1),
             "O número que realmente dimensiona o drawdown. Um recorde de 13 "
             "derrotas assusta, mas se a média é 1,6 aquilo foi um evento "
             "isolado. Média acima de 3 significa que perder em bloco é o "
             "comportamento NORMAL do sistema — aí o stop diário deixa de ser "
             "exagero e vira parte do desenho.",
             faixa(s["media_perdas"], 2.0, 3.5),
             f"máx {s['max_perdas']} · {inteiro(s['n_sequencias_perda'])} séries"),
        card("perdas seguidas (máx)", inteiro(s["max_perdas"]),
             "A pior sequência de derrotas do backtest inteiro. Multiplique "
             "pela perda média para saber o mergulho que você precisa "
             "aguentar sem desligar o robô — e lembre que o futuro pode "
             "trazer uma sequência maior que a observada.",
             "warn" if s["max_perdas"] >= 8 else None,
             f"× perda média = o buraco a suportar"),
        card("ganhos seguidos (máx)", inteiro(s["max_ganhos"]),
             "A maior sequência de vitórias. Serve de contrapeso: se for "
             "muito maior que a de perdas, a curva sobe em degraus — o que a "
             "aba Robustez confirma no teste de sequência."),
    ]

    for k, d in sorted(s.get("depois_de", {}).items()):
        delta = d["expectativa"] - s["expectativa_geral"]
        fora.append(card(
            f"depois de {k} perda{'s' if k > 1 else ''}", brl(d["expectativa"]),
            "A expectativa do PRÓXIMO trade, olhando só as vezes em que "
            f"{k} operação{'ões' if k > 1 else ''} anterior"
            f"{'es fecharam' if k > 1 else ' fechou'} no prejuízo. Se cair "
            "bem abaixo da expectativa geral, perda puxa perda: pausar o dia "
            "depois dessa sequência melhora o resultado. Se ficar parecida, "
            "as perdas são independentes e pausar só tira trades bons — a "
            "intuição de 'está ruim hoje' custa dinheiro.",
            "neg" if delta < 0 else "pos",
            f"geral {brl(s['expectativa_geral'])} · {inteiro(d['n'])} casos",
            largo=True))

    return secao(
        "Sequências", "Como ganhos e perdas se agrupam no tempo. Responde a "
        "duas decisões concretas: vale ligar stop diário, e vale parar de "
        "operar depois de N derrotas seguidas.", fora)


# ------------------------------------------------------------- eficiência
def _eficiencia(e):
    if not e:
        return None
    fora = [
        card("eficiência da entrada",
             f"{num(e['entrada'], 1)}%" if e["entrada"] is not None else "—",
             "De todo o caminho que o preço percorreu enquanto o trade estava "
             "aberto (a favor MAIS contra), quanto foi a favor. Baixo "
             "significa que você entra e o preço vai contra antes de virar: o "
             "gatilho está adiantado, ou falta um filtro. Acima de 60% é bom; "
             "abaixo de 40% a entrada é o gargalo.",
             faixa(e["entrada"], 60, 40), "quanto do movimento veio a favor"),
        card("eficiência da saída",
             f"{num(e['saida'], 1)}%" if e["saida"] is not None else "—",
             "Do melhor ponto que o trade alcançou, quanto sobrou no "
             "fechamento. Baixo significa que o lucro apareceu e você "
             "devolveu: o alvo está longe demais, ou falta trailing / "
             "breakeven. Acima de 60% é bom; abaixo de 30% você está "
             "entregando de volta a maior parte do que ganhou. NEGATIVO "
             "significa que o trade típico não só devolveu o pico como fechou "
             "abaixo da entrada — o movimento a favor apareceu e virou "
             "prejuízo. A média sai só dos trades que TIVERAM pico a devolver: "
             "quem nunca andou a favor não tem denominador, e a nota ao lado "
             "diz sobre quantos a conta foi feita.",
             faixa(e["saida"], 60, 30),
             f"sobre {inteiro(e['n_saida'])} de {inteiro(e['n_trades'])} trades"),
        card("MFE ÷ MAE", num(e["razao_mfe_mae"], 2) if e["razao_mfe_mae"] else "—",
             "Quanto o trade médio anda a favor para cada ponto que anda "
             "contra, ANTES de qualquer decisão de saída. É o potencial cru "
             "do sinal: acima de 1,5 há espaço de sobra para trabalhar stop e "
             "alvo; abaixo de 1,0 o sinal não oferece assimetria e nenhuma "
             "gestão conserta isso.",
             faixa(e["razao_mfe_mae"], 1.5, 1.0),
             f"a favor {num(e['mfe_medio'], 0)} pts · "
             f"contra {num(e['mae_medio'], 0)} pts"),
        card("alvo tocado e não pago", f"{num(e['pct_devolvido'], 0)}%",
             "Trades que chegaram a encostar na distância do alvo mas saíram "
             "por outro motivo — ou seja, o lucro esteve na mão e escapou. "
             "Acima de 25% é sinal claro de que falta proteger o ganho "
             "(breakeven ou trailing). Zero pode significar que o alvo é "
             "perto demais e você está cortando trades cedo.",
             faixa(e["pct_devolvido"], 10, 25),
             f"{inteiro(e['tocou_e_nao_saiu'])} de "
             f"{inteiro(e['tocou_alvo'])} que tocaram", largo=True),
    ]
    return secao(
        "Eficiência da operação", "Separa o mérito da ENTRADA do mérito da "
        "SAÍDA. É a leitura que diz qual dos dois lados consertar primeiro — "
        "mexer no alvo quando o problema é o gatilho não leva a lugar nenhum.",
        fora)


# ---------------------------------------------------------- risco por trade
def _risco(r):
    if not r:
        return None
    fora = [
        card("VaR 95%", brl(r["var95"]),
             "A perda que apenas 5% dos trades superam. Lê-se assim: em 19 de "
             "cada 20 operações, o prejuízo não passa disto. É o número que "
             "costuma ser usado para dimensionar posição — e é justamente o "
             "que ignora a cauda que quebra conta, por isso vem acompanhado "
             "do CVaR.",
             "neg", "19 de cada 20 trades ficam acima disto"),
        card("CVaR 95%", brl(r["cvar95"]),
             "A perda MÉDIA daqueles 5% piores: quanto dói quando passa da "
             "linha do VaR. Se o CVaR for muito maior que o VaR, a cauda é "
             "gorda e o tamanho de posição precisa ser calibrado por ele, não "
             "pelo VaR. Divida seu capital por este número para saber quantos "
             "trades ruins seguidos você aguenta. A conta usa os N piores "
             "trades (5% da amostra, arredondado para cima) e não 'todos "
             "abaixo do VaR': com stop fixo dezenas de trades empatam "
             "exatamente no valor do percentil, e incluí-los todos diluiria a "
             "cauda justamente para o lado otimista.",
             "neg", f"média dos {inteiro(r['n_cauda'])} piores · VaR {brl(r['var95'])}"),
        card("pior ÷ perda média", num(r["razao_pior_media"], 1)
             if r["razao_pior_media"] else "—",
             "Quantas perdas médias cabem na maior perda do backtest. Até 3× "
             "é uma distribuição controlada — o stop está funcionando. Acima "
             "de 5× existe um evento que passou por cima do stop (gap, "
             "leilão, mercado fino), e ele vai se repetir.",
             faixa(r["razao_pior_media"], 3, 5),
             f"maior {brl(r['maior_perda'])} · média {brl(r['perda_media'])}"),
        card("stops furados", f"{num(r['pct_furados'], 1)}%",
             "Saídas por stop que fecharam PIOR do que o stop mandava, já "
             "descontado o slippage configurado. É gap ou barra que abriu "
             "atravessada. Abaixo de 2% é ruído normal; acima de 10% o risco "
             "real por trade é maior que o que você acha que está correndo, e "
             "toda conta de dimensionamento está otimista.",
             faixa(r["pct_furados"], 2, 10),
             f"{inteiro(r['stops_furados'])} trades · excesso médio "
             f"{num(r['excesso_medio'], 0)} pts", largo=True),
        card("desvio por trade", brl(r["desvio"]),
             "O tamanho típico da oscilação de um resultado individual. "
             "Comparado com a expectativa, diz quanto ruído existe em volta "
             "do lucro médio: desvio dez vezes maior que a expectativa "
             "significa que só uma amostra grande revela o sinal — é a mesma "
             "conta que a aba Robustez usa para dizer se o resultado é real."),
    ]
    return secao(
        "Risco por trade", "O tamanho do risco de UMA operação, em reais. É "
        "daqui que sai o número de contratos: não do lucro que a estratégia "
        "promete, e sim da perda que ela é capaz de entregar.", fora)


# ------------------------------------------------------------ exposição
def _ritmo(r, fig_volume):
    if not r:
        return None
    fora = [
        card("exposição", f"{num(r['exposicao_pct'], 1)}%",
             "Percentual do tempo de mercado com posição aberta. É o contexto "
             "que falta a todo Sharpe: o mesmo número com 3% ou com 60% de "
             "exposição descreve estratégias que não se parecem em nada. "
             "Exposição baixa com bom retorno é o melhor dos mundos — menos "
             "tempo exposto a evento inesperado.",
             None, "do tempo total com posição aberta"),
        card("pregões operados", f"{num(r['pct_pregoes'], 0)}%",
             "Em quantos dias do período a estratégia achou pelo menos um "
             "sinal. Abaixo de 30% ela é seletiva (ou o filtro está apertado "
             "demais); perto de 100% ela opera todo dia, o que costuma vir "
             "junto de mais custo e mais trade ruim.",
             None,
             f"{inteiro(r['pregoes_operados'])} de "
             f"{inteiro(r['pregoes_totais'])} pregões"),
        card("trades por pregão", num(r["trades_por_dia"], 1),
             "A média de operações num dia operado. Compare com o máximo ao "
             "lado: se o máximo for muitas vezes a média, existem dias de "
             "mercado picado em que a estratégia dispara sinais — e o gráfico "
             "abaixo mostra se esses dias dão ou tomam dinheiro.",
             None, f"máximo {inteiro(r['max_trades_dia'])} num só dia"),
        card("dias positivos", f"{num(r['pct_dias_positivos'], 0)}%",
             "Percentual de pregões operados que fecharam no azul. Acima de "
             "55% é confortável de operar no dia a dia. Abaixo de 45% o "
             "lucro vem de poucos dias grandes, e a rotina é de perder mais "
             "vezes do que ganhar — sustentável na planilha, difícil na "
             "cadeira.",
             faixa(r["pct_dias_positivos"], 55, 45),
             f"{inteiro(r['dias_positivos'])} de "
             f"{inteiro(r['pregoes_operados'])} pregões"),
        card("melhor e pior dia", brl(r["melhor_dia"]),
             "Os extremos diários. O pior dia é o teste do limite de perda "
             "diária: se ele for muito maior que o seu limite mental, o "
             "backtest está contando com uma tolerância que você não tem — e "
             "o campo 'limite de perda por contrato' existe justamente para "
             "cortar isso.",
             "pos", f"pior dia {brl(r['pior_dia'])}", largo=True),
    ]
    bloco = secao(
        "Exposição e ritmo", "Quanto tempo a estratégia fica no mercado e com "
        "que cadência opera. Duas curvas de capital idênticas com exposições "
        "diferentes são estratégias diferentes — inclusive no risco.", fora)
    if fig_volume is not None:
        bloco.children.append(
            dcc.Graph(figure=fig_volume, className="graf-detalhe",
                      config={"displayModeBar": False, "responsive": True}))
    return bloco


# ------------------------------------------------------ diagnóstico do motor
def _motor(m):
    saidas = m.get("saidas", {})
    saidas_txt = " · ".join(f"{k} {inteiro(v)}" for k, v in saidas.items())
    fora = [
        card("saídas por motivo", saidas_txt or "—",
             "Como cada operação terminou. É o raio-x da gestão: muita saída "
             "por 'tempo máximo' significa que o alvo não é alcançado e o "
             "trade morre de velho; muita por 'fechamento' significa que a "
             "estratégia depende do encerramento do pregão, não do sinal. "
             "Stop e alvo em proporção parecida com o payoff é o esperado.",
             None, None, largo=True, fluido=True),
        card("barras ambíguas", inteiro(m["barras_ambiguas"]),
             "Barras em que stop e alvo foram tocados dentro do MESMO candle. "
             "Sem dados de tick não há como saber qual veio primeiro, e o "
             "motor assume o pior caso (stop). É uma medida de quanto o "
             "resultado depende dessa suposição: abaixo de 0,5% das barras é "
             "irrelevante; acima disso, o backtest está sendo decidido por "
             "uma convenção e não pela estratégia.",
             "warn" if m["barras_ambiguas_pct"] > 0.5 else None,
             f"{num(m['barras_ambiguas_pct'], 3)}% das barras · assume stop"),
    ]
    if m.get("dias_bloqueados"):
        fora.append(card(
            "dias interrompidos", inteiro(m["dias_bloqueados"]),
            "Quantas vezes um limite diário (perda máxima, ganho máximo, "
            "número de trades) encerrou o dia antes da hora. Se for alto, os "
            "limites da camada 4 estão moldando o resultado tanto quanto a "
            "estratégia — e mudá-los muda tudo.",
            "warn", "por limite de perda, ganho ou nº de trades"))
    return secao(
        "Diagnóstico do motor", "Quanto do resultado vem da estratégia e "
        "quanto vem de suposições da simulação. Números altos aqui não "
        "invalidam o backtest, mas dizem onde ele é frágil.", fora)


# ------------------------------------------------------------------ render
def render(m, seq, ef, risco, rit, fig_volume=None) -> html.Div:
    if not m or not m.get("trades"):
        return vazio("Rode um backtest para ver os detalhes.")
    blocos = [b for b in (_sequencias(seq), _eficiencia(ef), _risco(risco),
                          _ritmo(rit, fig_volume), _motor(m)) if b]
    return html.Div(blocos, className="aba-detalhes")
