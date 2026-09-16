"""Aba Robustez: a peneira do candidato.

Cada cartão traz um **(?)** com o que a métrica é e que valores são bons ou
ruins. Não é enfeite: número sem faixa de referência não sustenta decisão —
"Ulcer 8,4" só vira informação quando se sabe que abaixo de 5 é confortável.

O texto do (?) mora aqui, junto do cartão que ele explica, e não num
dicionário distante: assim mudar a métrica e esquecer a explicação fica
difícil. O molde do cartão e do balão vem de cartao.py.
"""

from __future__ import annotations

from dash import dash_table, html

from .. import theme as T
from .cartao import brl, dica as _dica, faixa as _faixa, inteiro, num
from .cartao import card as _card
from .cartao import vazio as _vazio


def vazio(msg="Rode um backtest para avaliar a robustez."):
    return _vazio(msg)


# ------------------------------------------------------------------ blocos
def _sequencia(mc):
    if not mc:
        return []
    pior = mc["dd_p95"] / mc["dd_observado"] if mc["dd_observado"] else 0
    return [
        _card("drawdown p95 (simulado)", brl(mc["dd_p95"]),
              "Reembaralhando a ordem dos mesmos trades "
              f"{inteiro(mc['n'])} vezes, em 5% das vezes o drawdown passou "
              "deste valor. É para ELE que o capital precisa estar "
              "preparado, não para o que aconteceu. Se for mais que o dobro "
              "do observado, você teve sorte de ordenação.",
              "neg" if pior > 2 else None,
              # o multiplicador e formatado ANTES: literais adjacentes se
              # concatenam primeiro, e o .replace pegava tambem o separador
              # de milhar do valor em reais
              f"observado {brl(mc['dd_observado'])} · "
              f"{num(pior, 1)}× o que você viu"),
        _card("sorte na ordem", f"{num(mc['percentil_do_observado'], 0)}%",
              "Onde o seu drawdown cai na distribuição dos reembaralhamentos. "
              "20% quer dizer que 80% das ordens possíveis foram PIORES que a "
              "sua — resultado com sorte. Perto de 50% é típico; acima de 80% "
              "você pegou uma sequência ruim e a estratégia é melhor que "
              "parece.",
              _faixa(mc["percentil_do_observado"], 60, 15),
              "menor = mais sorte"),
        _card("pior caso simulado", brl(mc["dd_max"]),
              "O maior drawdown que apareceu em todas as simulações. É o "
              "limite do que esses mesmos trades conseguem fazer contra você "
              "numa ordem infeliz.", None,
              f"p99 {brl(mc['dd_p99'])}"),
    ]


def _significancia(sig, runs, lr):
    fora = []
    if sig:
        conclusivo = sig["p"] < 0.05
        positiva = sig["media"] > 0
        if not conclusivo:
            texto, cor = "inconclusivo", "warn"
        elif positiva:
            texto, cor = f"positiva · {num(sig['confianca'], 1)}%", "pos"
        else:
            # o teste é bicaudal: ele diz que difere de zero, não que é boa.
            # Sem esta distinção a tela mostrava "99,8% de confiança" em
            # verde numa estratégia que perde dinheiro com consistência.
            texto, cor = f"negativa · {num(sig['confianca'], 1)}%", "neg"
        p_fmt = f"{sig['p']:.4f}".replace(".", ",")
        fora.append(_card(
            "expectativa é real?", texto,
            "Confiança de que a expectativa por trade é diferente de zero, e "
            "não ruído. Acima de 95% é significativo — mas atenção ao sinal: "
            "significativa e NEGATIVA quer dizer que a estratégia perde de "
            "forma consistente, o que é uma conclusão tão sólida quanto a "
            "boa. Amostra pequena quase nunca conclui nada.",
            cor,
            (f"p = {p_fmt} · média {brl(sig['media'])}" if conclusivo
             else (f"precisa de ~{inteiro(sig['n_necessario'])} trades"
                   if sig.get("n_necessario") else None)),
            largo=True, texto=True))
    if runs:
        estado = ("perdas agrupadas" if runs["agrupadas"]
                  else "alternadas demais" if runs["alternadas"]
                  else "independentes")
        fora.append(_card(
            "sequência dos trades", estado,
            "Trades independentes produzem um número previsível de "
            "sequências de ganhos e perdas. MENOS sequências que o esperado "
            "significa perdas em bloco: o drawdown real fica pior que "
            "qualquer conta feita supondo independência, e o stop diário "
            "passa a valer a pena. 'Independentes' é o resultado saudável.",
            "neg" if runs["agrupadas"] else None,
            f"z = {num(runs['z'])} · {runs['corridas']} de "
            f"{num(runs['esperado'], 0)} esperadas", texto=True))
    if lr:
        fora.append(_card(
            "curva é reta?", num(lr["correlacao"], 3),
            "Correlação da curva de capital com uma linha reta. Acima de "
            "0,95 é subida constante — o lucro vem do método. Abaixo de 0,80 "
            "a curva sobe num degrau e fica de lado: o lucro veio de um "
            "período específico, e isso costuma não se repetir. Valor "
            "NEGATIVO é queda constante: −1,00 é uma reta descendente "
            "perfeita, o pior resultado possível aqui.",
            _faixa(lr["correlacao"], 0.95, 0.80),
            "1,00 = subida perfeita · −1,00 = queda perfeita"))
    return fora


def _fragilidade(conc):
    if not conc:
        return []
    sem5 = conc["sem"].get(5)
    fora = [_card(
        "lucro sem os 5 melhores",
        brl(sem5) if sem5 is not None else "—",
        "O lucro total descontando os cinco maiores ganhos. Se virar "
        "prejuízo, a estratégia não é um sistema: é um punhado de acidentes "
        "felizes que não se repetem. Um bom candidato continua positivo — "
        "de preferência ainda com folga.",
        "pos" if conc["sobrevive_sem_5"] else "neg",
        f"total {brl(conc['total'])}", largo=True)]
    if conc.get("peso_do_maior") is not None:
        fora.append(_card(
            "peso do maior trade", f"{num(conc['peso_do_maior'], 1)}%",
            "Quanto do lucro total veio de um único trade. Abaixo de 5% o "
            "resultado está bem distribuído. Acima de 20%, o backtest está "
            "apoiado num evento — e eventos não se agendam.",
            _faixa(conc["peso_do_maior"], 5, 20),
            brl(conc["maior_trade"])))
    if conc["sem"].get(20) is not None:
        fora.append(_card(
            "sem os 20 melhores", brl(conc["sem"][20]),
            "O mesmo teste, mais severo. Sobreviver a isto é sinal de "
            "estratégia com muitos trades pequenos e consistentes, que é o "
            "tipo que costuma resistir fora da amostra.",
            "pos" if conc["sem"][20] > 0 else "neg",
            f"sem 10: {brl(conc['sem'].get(10, 0))}"))
    return fora


def _ranking(um, sqn=None):
    if not um:
        return []
    fora = []
    if sqn:
        fora.append(_card(
            "SQN", num(sqn["sqn"], 2),
            "System Quality Number, de Van Tharp: √N × média ÷ desvio padrão "
            "dos resultados dos trades. Junta numa nota só a expectativa, a "
            "regularidade e o tamanho da amostra — quanto mais regular o "
            "resultado por trade, mais fácil é dimensionar posição em cima "
            "dele. Faixas do próprio Tharp: abaixo de 1,6 é difícil de "
            "operar; 1,6–1,9 abaixo da média; 2,0–2,4 média; 2,5–2,9 bom; "
            "3,0–5,0 excelente; acima de 7,0 é excepcional — e, na prática, "
            "motivo para conferir o backtest antes de comemorar. O N é "
            "limitado a 100 por regra de Tharp: sem o teto, dez mil trades "
            "medíocres bateriam quinhentos excelentes só pelo volume. "
            "Ressalva: Tharp define o SQN sobre R-múltiplos (resultado ÷ "
            "risco de cada trade), e aqui ele sai dos reais. Com stop fixo e "
            "contratos fixos dá no mesmo; com stop por ATR o risco varia de "
            "trade para trade e os dois números divergem — o suficiente, às "
            "vezes, para cruzar a fronteira de uma faixa.",
            _faixa(sqn["sqn"], 2.5, 1.6), 
            f"{sqn['faixa']}" + (f" · N limitado a {sqn['n_efetivo']} de "
                                 f"{inteiro(sqn['n'])}" if sqn["limitado"] else ""),
            largo=True, texto=False))
    return fora + [
        _card("ulcer index", num(um["ulcer"], 2),
              "Junta profundidade E duração do drawdown num número só. Dois "
              "sistemas com o mesmo max drawdown — um que afunda e volta "
              "rápido, outro que fica meses no fundo — têm Ulcer bem "
              "diferentes. Abaixo de 5 é confortável; acima de 15, doloroso "
              "de operar.",
              _faixa(um["ulcer"], 5, 15), "menor é melhor"),
        _card("MAR", num(um["mar"], 2) if um.get("mar") else "—",
              "Retorno anualizado dividido pelo drawdown máximo, em "
              "percentual. É o número que a indústria usa para ORDENAR "
              "sistemas entre si. Abaixo de 0,5 é fraco; acima de 1,0 é bom; "
              "acima de 2,0 é raro e merece desconfiança de overfitting.",
              _faixa(um.get("mar"), 1.0, 0.5),
              f"CAGR {num(um['cagr'], 1)}% · DD {num(um['max_dd_pct'], 1)}%"),
    ]


def _meses(m):
    if not m:
        return []
    return [
        _card("meses positivos", f"{num(m['pct'], 0)}%",
              "Percentual de meses que fecharam no azul. Acima de 60% é "
              "sólido; abaixo de 45% significa que a maior parte do tempo "
              "você está perdendo, mesmo que o total feche positivo.",
              _faixa(m["pct"], 60, 45),
              f"{m['positivos']} de {m['meses']} meses"),
        _card("pior sequência", f"{m['pior_sequencia']} meses",
              "A maior sequência de meses negativos seguidos. É a métrica de "
              "'eu aguentaria operar isto': dois meses ruins se atravessa, "
              "sete faz qualquer um desistir no pior momento possível. Até 3 "
              "é normal; acima de 6, pense se você seguiria.",
              _faixa(m["pior_sequencia"], 3, 6),
              f"melhor mês {brl(m['melhor'])} · pior {brl(m['pior'])}"),
    ]


def _custo(c):
    if not c:
        return []
    folga = c.get("folga_pct")
    if c["limite_por_contrato"] <= 0:
        return [_card(
            "custo que zera", "não se paga",
            "O resultado BRUTO já é negativo: a estratégia perde antes de "
            "qualquer custo. Não existe corretagem baixa o suficiente para "
            "salvá-la — o problema não é o custo.",
            "neg", f"você paga {brl(c['atual_por_contrato'])} por ponta",
            largo=True, texto=True)]
    return [_card(
        "custo que zera", brl(c["limite_por_contrato"]),
        "Quanto de corretagem + emolumentos por contrato, por ponta, faria a "
        "estratégia empatar. Compare com o que você paga hoje: folga abaixo "
        "de 50% é apertado — uma mudança de corretora ou de lote pode virar "
        "o resultado. Acima de 200% a estratégia é robusta a custo.",
        _faixa(folga, 200, 50),
        (f"você paga {brl(c['atual_por_contrato'])} · folga de "
         f"{num(folga, 0)}%" if folga is not None
         else f"você paga {brl(c['atual_por_contrato'])}"),
        largo=True)]


# ---------------------------------------------------------------- drawdowns
COLUNAS_DD = [
    {"name": "início", "id": "inicio"},
    {"name": "fundo", "id": "fundo"},
    {"name": "profundidade", "id": "prof"},
    {"name": "trades", "id": "trades"},
    {"name": "dias até o fundo", "id": "d_fundo"},
    {"name": "dias p/ recuperar", "id": "d_rec"},
]


def tabela_drawdowns(lista):
    if not lista:
        return html.Div()
    linhas = [{
        "inicio": d["inicio"], "fundo": d["fundo"],
        "prof": brl(d["profundidade"]), "trades": d["trades"],
        "d_fundo": d["dias_ate_o_fundo"],
        "d_rec": (d["dias_para_recuperar"] if d["dias_para_recuperar"] is not None
                  else "não recuperou"),
    } for d in lista]
    return html.Div([
        html.Div([html.H3("Maiores mergulhos", className="grp"),
                  _dica("Os cinco maiores drawdowns, com quanto tempo levaram "
                        "para voltar ao topo anterior. O max drawdown diz "
                        "quanto você perde; esta tabela diz por quanto tempo "
                        "você ficaria no vermelho esperando — que é o que "
                        "costuma fazer as pessoas abandonarem uma estratégia "
                        "boa na pior hora. 'Não recuperou' significa que o "
                        "backtest terminou ainda abaixo daquele topo.")],
                 className="dd-head"),
        dash_table.DataTable(
            columns=COLUNAS_DD, data=linhas,
            style_as_list_view=True,
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": T.SURFACE_2, "color": T.MUTED,
                          "border": "none", "fontFamily": "Archivo",
                          "fontSize": "11px", "textTransform": "uppercase",
                          "letterSpacing": ".08em", "fontWeight": "600"},
            style_cell={"backgroundColor": T.SURFACE, "color": T.INK_2,
                        "border": "none",
                        "borderBottom": f"1px solid {T.LINE_SOFT}",
                        "fontFamily": "JetBrains Mono, monospace",
                        "fontSize": "13px", "padding": "9px 14px",
                        "textAlign": "right"},
            style_cell_conditional=[
                {"if": {"column_id": c}, "textAlign": "left"}
                for c in ("inicio", "fundo")],
            style_data_conditional=[
                {"if": {"column_id": "prof"}, "color": T.NEG},
                {"if": {"filter_query": '{d_rec} = "não recuperou"',
                        "column_id": "d_rec"}, "color": T.WARN},
            ],
        ),
    ], className="bloco-dd")


def render(mc, sig, runs, lr, conc, um, mes, custo, lista_dd, sqn=None) -> html.Div:
    cartoes = (_significancia(sig, runs, lr) + _fragilidade(conc)
               + _sequencia(mc) + _ranking(um, sqn) + _meses(mes) + _custo(custo))
    if not cartoes:
        return vazio("Poucos trades para avaliar robustez.")
    return html.Div([html.Div(cartoes, className="cards cards-robustez"),
                     tabela_drawdowns(lista_dd)], className="aba-robustez")
