"""Os cartões da aba Distribuição: a saúde da REGIÃO varrida.

Estes quatro números respondem o passo 5 da metodologia. Nenhum deles fala
da melhor combinação — de propósito. O campeão você já vê na tabela; o que
falta saber é se ele representa a região ou se é a exceção dela.
"""

from __future__ import annotations

from dash import html

from .cartao import brl, card, faixa, inteiro, num, vazio


def cards(r: dict, msg: str = "Rode uma mineração para ver a região.") -> html.Div:
    if not r:
        return vazio(msg)

    razao = r.get("razao_melhor_mediana")
    return html.Div(
        [
            card("combinações lucrativas", f"{num(r['pct_lucrativas'], 0)}%",
                 "Quantas combinações da região fecham no azul. É o número "
                 "que mais diz se você achou um platô ou um acidente: acima "
                 "de 70%, quase qualquer ponto ali dentro funciona e errar a "
                 "escolha sai barato. Abaixo de 30%, a região é ruim e o "
                 "campeão é a sorte dentro dela — mesmo que o número dele "
                 "seja bonito.",
                 faixa(r["pct_lucrativas"], 70, 30),
                 f"{inteiro(r['n_lucrativas'])} de {inteiro(r['n'])}",
                 largo=True),
            card("mediana da região", brl(r["mediana"]),
                 "O resultado da combinação do meio. É a expectativa honesta "
                 "de escolher um ponto qualquer da região — bem mais realista "
                 "do que o do campeão, porque no futuro você não sabe qual "
                 "ponto será o melhor. Mediana negativa com campeão positivo "
                 "significa que a região perde dinheiro e você está prestes a "
                 "escolher a exceção.",
                 "pos" if r["mediana"] > 0 else "neg",
                 f"média {brl(r['media'])}", largo=True),
            card("melhor ÷ mediana", num(razao, 1) if razao else "—",
                 "Quantas vezes o campeão supera o meio da região. É o cartão "
                 "mais desconfortável e o mais útil: até 3× o campeão ainda "
                 "pertence à região. Acima de 10× ele não a representa — é o "
                 "ponto que mais se ajustou ao passado, e é exatamente o tipo "
                 "de coisa que não se repete fora da amostra. Fica vazio "
                 "quando a mediana é negativa, porque aí a razão inverte de "
                 "sinal e diria o contrário do que parece.",
                 faixa(razao, 3, 10) if razao else None,
                 f"melhor {brl(r['melhor'])}"),
            card("meio da região", brl(r["p25"]),
                 "O intervalo onde caem metade das combinações — do primeiro "
                 "ao terceiro quartil. Faixa estreita e acima de zero é "
                 "região homogênea: os vizinhos valem quase o mesmo. Faixa "
                 "larga significa que o resultado depende muito de qual ponto "
                 "você escolheu, o que é outro nome para instabilidade.",
                 None, f"até {brl(r['p75'])} · metade delas", largo=True),
        ]
        + ([card("janelas positivas ≥ 60%",
                 f"{num(r['pct_consistentes'], 0)}%",
                 "Percentual das combinações que lucraram em pelo menos 60% "
                 "das janelas de teste do walk-forward. Mede consistência da "
                 "REGIÃO no tempo, não de um ponto: região que só passa nisto "
                 "em 5% das combinações rendeu por período, não por método.",
                 faixa(r["pct_consistentes"], 50, 20),
                 "da região inteira")]
           if r.get("pct_consistentes") is not None else []),
        className="cards cards-regiao",
    )
