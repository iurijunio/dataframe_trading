"""Quantos contratos operar, e quando reduzir ou desligar.

Separado de `candidata.py` de propósito. Lá moram os portões, que respondem
uma pergunta fechada — a estratégia passa ou não. Aqui mora o
dimensionamento, que só faz sentido DEPOIS de aprovada e que tem dial: o
usuário escolhe o risco por trade e informa a margem da corretora.

Nada aqui importa Dash.
"""

from __future__ import annotations

import numpy as np

# O último stop do dia ruim sai com o DOBRO do tamanho, porque não havia
# preço no stop. É um dia ruim de EXECUÇÃO — não é leilão de volatilidade,
# que no índice custaria umas dez vezes mais (ver `trava_do_indice`).
FATOR_ESTOURO = 2.0

# A cauda que vira referência de risco: os 5% piores pregões.
CAUDA = 0.05

# Abaixo disto a cauda tem observações demais de menos para virar média: com
# 20 pregões, 5% arredondado para cima ainda é UM dia, e a "média dos piores"
# seria o pior. 21 é o primeiro tamanho em que a cauda tem dois dias.
#
# Isto não é a recusa de amostra pequena do desenho (§5 do PLANO-CANDIDATA,
# 100 operações fora da amostra): essa conta operações e mora em quem chama.
# Aqui é só a guarda contra entrada degenerada.
MIN_PREGOES = 21


def por_contrato(pnl_dia, contratos: int):
    """O resultado diário de UM contrato.

    O backtest pode ter rodado com mais de um; dimensionar em cima do
    resultado cheio contaria o mesmo contrato duas vezes, e o número de
    contratos sairia pela metade.
    """
    return np.asarray(pnl_dia, dtype=float) / max(int(contratos or 1), 1)


def cvar_pregao(pnl_contrato, fracao: float = CAUDA) -> dict:
    """A média dos pregões da cauda ruim — não o pior deles.

    É a unidade certa porque o dia empilha perdas: a camada 4 impõe limite
    por pregão, e é no pregão que o risco se materializa. E é média, não
    teto: metade das perdas da cauda será maior que este número, e o (?) da
    tela precisa dizer isso.

    Devolve também `quantos` e `fracao` de verdade: `k` é arredondado para
    cima, então em 67 pregões os "5% piores" são 4 dias, que são 6%. Escrever
    "5%" na tela quando a conta usou 6% é prometer o que não foi feito.
    """
    x = np.asarray(pnl_contrato, dtype=float)
    vazio = {"valor": None, "quantos": 0, "fracao": None}
    if not len(x):
        return {**vazio, "motivo": "a curva não tem pregão nenhum"}
    if not np.isfinite(x).all():
        # dia sem valor não é dia bom: some em silêncio de `min` e de `mean`
        # e sairia `nan` para a tela (que nem é JSON válido)
        return {**vazio, "motivo": "a curva tem pregões sem valor gravado"}
    if len(x) < MIN_PREGOES:
        return {**vazio,
                "motivo": (f"a curva tem só {len(x)} pregões; com menos de "
                           f"{MIN_PREGOES} a média dos piores vira o pior")}
    k = max(1, int(np.ceil(len(x) * fracao)))
    return {"valor": float(np.sort(x)[:k].mean()), "quantos": k,
            "fracao": k / len(x), "motivo": None}


def stops_do_dia(perfil: dict, observado: int | None = None) -> int | None:
    """Quantos stops cabem num dia, segundo a camada 4.

    Vale o **menor** dos dois limites ligados, não o primeiro deles. Num dia
    só de stops toda operação é perdedora, então `max_trades_dia` e
    `max_prejuizos_dia` contam a mesma coisa, e o motor para no que vier
    primeiro. Preferir `max_prejuizos_dia` por ser o campo mais específico
    dava referência inflada: com teto de 6 prejuízos e 2 operações, o dia
    acaba em 2.

    **Zero significa DESLIGADO no motor** (o kernel só testa o limite quando
    é maior que zero), e não "um trade": tratar zero como um faria o perfil
    mais perigoso — o que não tem trava nenhuma no dia — receber a referência
    de risco mais branda de todas. Sem limite nenhum, resta o que a própria
    curva mostrou: o maior número de operações que um pregão teve.
    """
    p = perfil or {}
    limites = [int(p.get(c) or 0) for c in ("max_prejuizos_dia", "max_trades_dia")]
    ligados = [v for v in limites if v > 0]
    if ligados:
        return min(ligados)
    return int(observado) if observado and observado > 0 else None


def dia_ruim(perfil: dict, point_value: float | None,
             custo_por_trade: float = 0.0,
             trades_no_dia: int | None = None) -> float | None:
    """A perda de um contrato num dia ruim de execução.

    Todos os stops que o dia permite batem, e o último sai com o dobro do
    tamanho porque não havia preço. Custa `stop × (n - 1 + 2)`, mais o custo
    de cada giro — os outros candidatos são líquidos de custo, e comparar
    bruto com líquido compararia coisas diferentes.

    O bootstrap sorteia dias que já aconteceram; um dia assim pode não ter
    acontecido na amostra e ainda assim acontecer amanhã. É por isso que ele
    existe.

    Devolve `None` quando não dá para medir: stop em múltiplo de ATR não tem
    tamanho fixo em reais, e sem limite de operações nem curva não há como
    saber quantos stops cabem no dia.
    """
    p = perfil or {}
    if not point_value or p.get("stop_tipo") != "pontos":
        return None
    stop = float(p.get("stop_pontos") or 0.0)
    if stop <= 0:
        return None
    n = stops_do_dia(p, trades_no_dia)
    if not n:
        return None
    stop_reais = stop * float(point_value)
    custo = float(custo_por_trade or 0.0)
    valor = stop_reais * (n - 1 + FATOR_ESTOURO) + n * custo
    # O limite de perda do dia (camada 4) para o pregão quando é atingido: o
    # motor confere depois que um trade fecha e bloqueia ENTRADA nova, nunca
    # fecha posição aberta — então o trade que estoura passa inteiro. É cota
    # superior, não a conta exata do motor, que ainda mede o limite em pontos
    # brutos enquanto aqui tudo já é líquido.
    limite = float(p.get("limite_perda_contrato") or 0.0)
    if limite > 0:
        valor = min(valor, limite + stop_reais * FATOR_ESTOURO + custo)
    return valor


def trava_do_indice(preco_indice: float | None, point_value: float | None,
                    pct: float = 10.0) -> float | None:
    """Quanto um contrato perde se o índice travar no leilão de volatilidade.

    **Não dimensiona nada** — é aviso de tela. Dimensionar por ela deixaria
    quase todo capital em 1 contrato ou em nenhum, e a estratégia é
    intradiária: o motor fecha a posição no fim do pregão, então o risco é o
    do dia travado, não o de carregar a posição para o dia seguinte.
    """
    if not preco_indice or not point_value:
        return None
    return float(preco_indice) * pct / 100.0 * float(point_value)


def perda_referencia(pnl_dia, contratos, perfil, point_value, *,
                     piso: float | None = None,
                     custo_por_trade: float = 0.0,
                     trades_no_dia: int | None = None) -> dict:
    """A perda de um contrato que dimensiona a posição.

    Vale o PIOR entre dois candidatos:

    1. a média dos 5% piores pregões: o dia ruim típico, medido;
    2. um dia ruim de execução, que a amostra pode nunca ter visto.

    O pior pregão que já aconteceu vem junto, mas **como leitura, não como
    candidato**: ele é sempre pior que a média da cauda (uma média nunca
    passa do pior do grupo), e deixá-lo concorrer desligaria o candidato 1.
    Além disso ele é um recorde: quanto mais longo o histórico, pior ele
    fica, e um único registro torto passaria a decidir sozinho o tamanho da
    posição. Decisão do usuário, 18/09/2026.

    Recusa medir, com motivo, quando: a curva veio de posição variável (aí
    dividir por um número fixo de contratos não vale), não há pregão, há
    pregão sem valor, ou a referência sai menor que `piso` — um centavo de
    referência viraria dezenas de milhares de contratos.
    """
    p = perfil or {}
    modo = p.get("modo_posicao") or "contratos_fixos"
    vazio = {"valor": None, "de_onde": None, "cvar": None, "quantos": 0,
             "fracao": None, "pior_dia": None, "dia_ruim": None}
    if modo != "contratos_fixos":
        return {**vazio,
                "motivo": ("o backtest rodou com posição variável: a perda "
                           "de um contrato não sai de uma divisão simples")}

    um = por_contrato(pnl_dia, contratos)
    c = cvar_pregao(um)
    ruim = dia_ruim(p, point_value, custo_por_trade, trades_no_dia)
    # o pior pregão e o dia ruim continuam valendo mesmo quando a cauda é
    # recusada: o dia ruim nem sai da curva, e apagar leitura que existe faz
    # a tela escrever "não medido" sobre número medido
    pior = float(um.min()) if len(um) and np.isfinite(um).all() else None
    base = {"cvar": c["valor"], "quantos": c["quantos"], "fracao": c["fracao"],
            "pior_dia": pior, "dia_ruim": ruim}
    if c["valor"] is None:
        return {**base, "valor": None, "de_onde": None, "motivo": c["motivo"]}
    candidatos = [
        (abs(c["valor"]) if c["valor"] < 0 else None,
         "a média dos 5% piores pregões"),
        (ruim, "um dia ruim de execução, com todos os stops do dia"),
    ]
    validos = [(v, d) for v, d in candidatos if v]
    if not validos:
        return {**base, "valor": None, "de_onde": None,
                "motivo": ("a curva não tem cauda de prejuízo e o stop não "
                           "tem tamanho fixo em reais: não há referência de "
                           "risco para dimensionar")}
    valor, de_onde = max(validos)
    if piso and valor < float(piso):
        return {**base, "valor": None, "de_onde": None,
                "motivo": ("a perda de referência ficou menor que o menor "
                           "movimento do instrumento; dimensionar por ela "
                           "daria um número de contratos sem sentido")}
    return {**base, "valor": valor, "de_onde": de_onde, "motivo": None}
