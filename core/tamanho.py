"""Quantos contratos operar, e quando reduzir ou desligar.

Separado de `candidata.py` de propósito. Lá moram os portões, que respondem
uma pergunta fechada — a estratégia passa ou não. Aqui mora o
dimensionamento, que só faz sentido DEPOIS de aprovada e que tem dial: o
usuário escolhe quanto aceita perder num pregão ruim e informa a garantia
que a corretora exige por contrato.

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

# Quanto do capital pode virar garantia na corretora. Usar 100% deixa a conta
# sem folga para o prejuízo do próprio dia — a garantia fica presa enquanto a
# posição está aberta, e é nela que o prejuízo do dia é debitado.
USO_MARGEM = 50.0


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


# Com que frequência cada nível pode disparar numa estratégia SADIA. É este
# o número que se escolhe — não o percentil. Desligar à toa em 5% dos ciclos
# é o preço aceito pelo disjuntor; reduzir posição é barato e reversível, por
# isso pode ser mais frequente. O limite em reais sai daqui, e não o
# contrário: assim a pergunta "e se eu apertar o limite?" tem resposta.
ALARME_REDUZIR = 20.0
ALARME_DESLIGAR = 5.0


def limite_por_alarme(quedas, alarme_pct: float) -> float | None:
    """A queda que só `alarme_pct` dos caminhos sadios atingem.

    Sorteados 2.000 caminhos de uma estratégia que continua funcionando como
    funcionou, `alarme_pct = 5` devolve a queda que 5% deles encostam: parar
    ali desliga uma estratégia viva em 5% dos ciclos.
    """
    q = np.asarray((quedas if quedas is not None else []), dtype=float)
    if not len(q) or not 0 < alarme_pct < 100:
        return None
    return float(np.percentile(q, 100.0 - alarme_pct))


def disjuntor(leitura: dict, capital: float, n_contratos: int, perfil: dict,
              alarme_reduzir: float = ALARME_REDUZIR,
              alarme_desligar: float = ALARME_DESLIGAR) -> dict:
    """Quando reduzir a posição e quando desligar a estratégia.

    Dois níveis, porque gatilho único é mau detector: parando só na queda
    ruim, desliga-se uma estratégia **sadia** em 5% dos ciclos, e uma morta
    só depois de um quinto do capital ter ido.

    | nível | gatilho | ação |
    |---|---|---|
    | 1 | a queda passa do limite de reduzir, a sequência de dias perdendo passa do p95, ou o acumulado sai por baixo da faixa esperada | reduzir para 1 contrato |
    | 2 | a queda chega ao limite de desligar | desligar e reotimizar |

    **Escolhe-se a taxa de alarme falso, não o percentil.** Antes o nível 2
    era o p95 do sorteio e a "chance de desligar à toa" era calculada contra
    o mesmo sorteio: dava 5% sempre, por construção, e um número que não
    varia não calibra nada. Agora o caminho é o inverso — a taxa aceita
    define o limite em reais — e mexer no dial muda os dois de verdade. Pelo
    mesmo motivo o nível 1 saiu da queda típica: metade dos caminhos de uma
    estratégia sadia passa dela, e reduzir posição viraria cara ou coroa a
    cada ciclo.

    Tudo **multiplicado pelos contratos escolhidos**, porque o sorteio mede
    um contrato. As quedas vêm do recorte (curva inteira ou últimos 12 meses)
    que tiver a queda ruim maior, para os dois níveis saírem da mesma régua.
    Já "dias perdendo seguidos" e "dias sem novo topo" valem o pior recorte
    **daquela métrica**, que é a regra do bloco 1: são leituras
    independentes, não limites que precisam ficar em ordem entre si.

    Os limites do dia saem da camada 4 multiplicados pelos contratos. Zero
    significa desligado no motor — vira `None`, "não definido", porque
    mostrar "R$ 0" prometeria uma trava que não existe.
    """
    from . import candidata

    vazio = {"nivel1": {"queda": None, "perdas_seguidas": None,
                        "lucro_no_prazo": None, "faixa_por_pregao": None,
                        "alarme_pct": alarme_reduzir,
                        "acao": "reduzir para 1 contrato"},
             "nivel2": {"queda": None, "pct": None,
                        "acao": "desligar e reotimizar",
                        "alarme_pct": alarme_desligar,
                        "risco_de_desligar_pct": None},
             "recorte": None, "dias_sem_topo": None, "limite_dia_reais": None,
             "limite_dia_trades": None, "horizonte": None}
    if not n_contratos or int(n_contratos) <= 0:
        return {**vazio, "motivo": ("sem número de contratos não há limite "
                                    "de desligamento para calcular")}
    boot = leitura.get("boot") or {}
    if not boot:
        return {**vazio, "motivo": ("a curva é curta demais para sortear "
                                    "caminhos; sem eles não há limite")}

    pior = candidata.pior_dos_recortes(leitura)
    recorte = pior["dd_p95"]["recorte"]
    b = ((leitura.get("boot_12m") if recorte == "últimos 12 meses" else boot)
         or boot)
    quedas = b.get("quedas")
    if quedas is None or not len(np.asarray(quedas)):
        return {**vazio, "motivo": ("o sorteio não guardou as quedas; sem "
                                    "elas não dá para calibrar o limite")}

    n = int(n_contratos)
    reduzir = (limite_por_alarme(quedas, alarme_reduzir) or 0.0) * n
    desligar = (limite_por_alarme(quedas, alarme_desligar) or 0.0) * n
    faixa = b.get("envelope_p10")
    faixa = [float(v) * n for v in faixa] if faixa is not None and len(faixa) \
        else None
    lim_reais = float((perfil or {}).get("limite_perda_contrato") or 0.0) * n
    trades_dia = int((perfil or {}).get("max_trades_dia") or 0)
    return {
        "nivel1": {
            "queda": reduzir or None,
            "perdas_seguidas": int(round(
                pior["perdas_seguidas_p95"]["valor"])) or None,
            # o acumulado esperado no pior décimo, pregão a pregão: é com ele
            # que se compara o resultado de hoje, sem esperar o prazo acabar
            "faixa_por_pregao": faixa,
            "lucro_no_prazo": (faixa[-1] if faixa else None),
            "alarme_pct": alarme_reduzir,
            "acao": "reduzir para 1 contrato"},
        "nivel2": {
            "queda": desligar or None,
            "pct": (desligar / capital * 100 if capital and desligar
                    else None),
            "acao": "desligar e reotimizar",
            "alarme_pct": alarme_desligar,
            "risco_de_desligar_pct": (
                candidata.risco_de_desligar(b, desligar / n)
                if desligar else None)},
        "recorte": recorte,
        "dias_sem_topo": int(round(pior["submerso_p95"]["valor"])) or None,
        "limite_dia_reais": lim_reais or None,
        "limite_dia_trades": trades_dia or None,
        "horizonte": int(boot.get("horizonte") or 0) or None,
        "motivo": None,
    }


def contratos(capital, risco_pct, perda_ref, margem=None,
              uso_margem_pct: float = USO_MARGEM) -> dict:
    """Quantos contratos operar: o menor entre três contas.

    1. **risco**: o risco que você aceita perder num PREGÃO ruim dividido
       pela perda de referência de um contrato;
    2. **margem**: quanto do capital pode virar garantia, dividido pela
       garantia de um contrato;
    3. **garantia mais prejuízo do dia**: o capital precisa pagar as duas
       coisas ao mesmo tempo — `capital ≥ n × (margem + perda de um dia
       ruim)`. Sem esta, nada impede a garantia comer 45% do capital e o
       prejuízo do mesmo dia pedir mais do que os 55% que sobraram.

    `risco_pct` é **por pregão, não por operação**. A perda de referência é
    de um dia inteiro (a média dos 5% piores pregões, ou um dia ruim de
    execução com todos os stops), então quem digita 1% está aceitando 1% no
    dia. Chamar isso de "risco por trade" — como o desenho chamava — faz
    quem opera três vezes por dia achar que aceitou o triplo.

    Sempre **piso inteiro**, e todas as contas seguintes usam esse inteiro:
    entre 1 e 2 contratos o risco dobra, e guardar o fracionário faria "1%"
    virar ficção. Por isso o risco efetivo do inteiro volta junto e vai para
    a tela ao lado do pedido.

    `n = 0` não é erro: é **reprovação por capital insuficiente**, e o
    `motivo` diz quais contas zeraram — senão o usuário mexe num dial e não
    resolve, porque o outro também zerou. Margem em branco é dado que falta,
    não garantia de graça: as contas 2 e 3 ficam de fora, voltam `None`, e a
    tela avisa que a garantia não foi conferida.
    """
    base = {"por_risco": None, "por_margem": None, "por_folga": None,
            "limite": None, "risco_pedido_pct": float(risco_pct or 0.0),
            "risco_efetivo_pct": None, "perda_ref": perda_ref,
            "margem": margem or None, "uso_margem_pct": uso_margem_pct}
    if not perda_ref or perda_ref <= 0:
        return {**base, "n": 0,
                "motivo": ("sem perda de referência não dá para dizer "
                           "quantos contratos cabem")}
    if not capital or capital <= 0 or not risco_pct or risco_pct <= 0:
        return {**base, "n": 0,
                "motivo": ("sem capital e risco por pregão informados não "
                           "dá para dimensionar")}
    if margem is not None and margem < 0:
        return {**base, "n": 0,
                "motivo": "a garantia por contrato não pode ser negativa"}
    if not 0 < uso_margem_pct <= 100:
        return {**base, "n": 0,
                "motivo": ("a parte do capital reservada para garantia "
                           "precisa estar entre 0% e 100%")}

    contas = {"risco": int(capital * float(risco_pct) / 100.0 // perda_ref)}
    if margem:
        contas["margem"] = int(capital * uso_margem_pct / 100.0 // margem)
        contas["garantia mais prejuízo do dia"] = int(
            capital // (float(margem) + perda_ref))
    n = min(contas.values())
    # empate manda junto: dizer só "risco" quando a margem também travou faz
    # o usuário subir o risco e não ver contrato nenhum a mais, sem explicação
    limite = " e ".join(k for k, v in contas.items() if v == n)
    motivo = None
    if n <= 0:
        zeradas = [k for k, v in contas.items() if v <= 0]
        motivo = ("o capital não comporta nem 1 contrato: "
                  + " e ".join(_POR_QUE_ZEROU[k] for k in zeradas))
    return {**base, "n": max(n, 0), "por_risco": contas["risco"],
            "por_margem": contas.get("margem"),
            "por_folga": contas.get("garantia mais prejuízo do dia"),
            "limite": limite,
            "risco_efetivo_pct": (n * perda_ref / capital * 100
                                  if n > 0 else None),
            "motivo": motivo}


_POR_QUE_ZEROU = {
    "risco": "1 contrato já arrisca mais do que o limite pedido",
    "margem": ("a garantia exigida por contrato é maior que a parte do "
               "capital reservada para ela"),
    "garantia mais prejuízo do dia": ("o capital não paga a garantia e o "
                                      "prejuízo de um dia ruim ao mesmo "
                                      "tempo"),
}


def perda_referencia(pnl_dia, contratos_backtest, perfil, point_value, *,
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

    um = por_contrato(pnl_dia, contratos_backtest)
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
