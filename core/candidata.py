"""A tela Candidata: o passo 10 da metodologia sobre a curva que o
otimizador nunca viu.

Aqui ficam as contas puras — sem Dash, sem banco. Quem lê o banco é o
callback; quem decide é o portão; quem calcula é este módulo.
"""

from __future__ import annotations

import numpy as np


def _valor(v):
    """Normaliza um valor de parâmetro para comparação de grade.

    Único lugar com a regra de arredondamento — `chave` e `perfil_plato`
    chamam este helper para que 78.0 (do JSON) e 78 (da mineração) sejam
    sempre o mesmo ponto, sem duas cópias da regra podendo divergir.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v
    return round(float(v), 6)


def chave(params: dict) -> tuple:
    """Endereço canônico de uma combinação na grade.

    `wfa_runs.deploy` volta do JSON com 78.0 e `mining_trials` gravou 78:
    comparar dicionários direto devolve "nenhum vizinho encontrado" sem
    levantar erro nenhum — o pior tipo de defeito.
    """
    return tuple((nome, _valor(params[nome])) for nome in sorted(params))


def por_pregao(saida_ts, liquido, de=None, ate=None):
    """O resultado por pregão, com os dias parados valendo zero.

    O trade entra no dia da SAÍDA, que é quando o resultado se realiza.
    Contar só os dias operados inflava quem opera pouco — quatro trades num
    ano davam Sharpe 129. E é o pregão, não o trade, a unidade em que a
    camada 4 impõe limite e em que o risco se materializa.
    """
    d = np.asarray(saida_ts, dtype="datetime64[D]")
    liq = np.asarray(liquido, dtype=float)
    if not len(d):
        return np.array([], dtype="datetime64[D]"), np.array([])
    ini = np.datetime64(de, "D") if de is not None else d.min()
    fim = np.datetime64(ate, "D") if ate is not None else d.max() + np.timedelta64(1, 'D')
    dias = np.arange(ini, fim)
    dias = dias[np.is_busday(dias)]
    if not len(dias):
        return dias, np.array([])
    pos = np.searchsorted(dias, d)
    # trade fora de `dias` (fim de semana/feriado, ou fora do recorte de/ate)
    # cai fora de `dentro` e é descartado em silêncio — de propósito: é o
    # mesmo mecanismo que faz o corte de/ate funcionar, não um bug
    dentro = (pos < len(dias)) & (dias[np.clip(pos, 0, len(dias) - 1)] == d)
    pnl = np.bincount(pos[dentro], weights=liq[dentro], minlength=len(dias))
    return dias, pnl


MIN_TRADES = 100


def leitura_robustez(trades: list[dict], capital: float,
                     horizonte_pregoes: int | None = None) -> dict:
    """O bloco 1: a robustez medida na curva que o otimizador nunca viu.

    Dois recortes sempre: a curva inteira e os últimos 12 meses. O mini
    índice foi de 96 mil a 197 mil pontos dentro da própria amostra — stop e
    alvo em pontos não significam a mesma coisa nas duas pontas, e o risco do
    regime atual não é a média de cinco anos. Vale o pior dos dois.
    """
    if len(trades) < MIN_TRADES:
        return {"erro": f"menos de {MIN_TRADES} trades fora da amostra"}

    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liq = np.array([t["liquido"] for t in trades], dtype=float)
    custo = np.array([t.get("custo", 0.0) for t in trades], dtype=float)
    dias, pnl = por_pregao(saida, liq)
    corte = dias[-1] - np.timedelta64(365, "D")
    # unidade explícita: somar int puro a datetime64 está deprecado no numpy
    ate12 = dias[-1] + np.timedelta64(1, "D")
    _, pnl12 = por_pregao(saida, liq, de=str(corte), ate=str(ate12))

    from . import metrics, robustez
    return {
        "resumo": metrics.resumo(liq, custo, saida, capital, len(dias)),
        "boot": robustez.bootstrap(pnl, capital, horizonte=horizonte_pregoes),
        "boot_12m": robustez.bootstrap(pnl12, capital,
                                       horizonte=horizonte_pregoes),
        # a permutação sobrevive como o que ela realmente mede: e se a mesma
        # sequência de resultados tivesse vindo noutra ordem
        "ordenacao": robustez.monte_carlo(liq, capital),
        "concentracao": robustez.concentracao(liq),
        "pregoes": len(dias),
        # a régua de comparação do p95 simulado: quantos pregões operados
        # perdedores seguidos a curva real, sem sorteio nenhum, já teve
        "perdas_seguidas_reais": robustez.perdas_seguidas_operadas(pnl),
    }


def risco_de_desligar(boot: dict, limite: float) -> float | None:
    """Chance de bater o limite de desligamento ESTANDO a estratégia viva.

    O bootstrap simula trajetórias de uma estratégia que continua funcionando
    como funcionou. Se X% delas encostam no limite, esse é o preço do
    disjuntor: desligar na hora errada X% das vezes. Sem este número, o
    limite não está calibrado — está chutado.
    """
    quedas = (boot or {}).get("quedas")
    if quedas is None or not len(quedas):
        return None
    return float((np.asarray(quedas) >= limite).mean() * 100)


PLATO_PISO = 0.6            # o vizinho segura 60% do FR do centro


def _perfil(pontos=None, centro_fr=None, ausentes=0, largura_esq=0,
           largura_dir=0, borda_esq=False, borda_dir=False, abstem=False,
           motivo=None, parametro=None) -> dict:
    """Monta o retorno de `perfil_plato` com o contrato sempre completo.

    A próxima fase liga um portão neste dicionário. Ramo que devolve um
    subconjunto de chaves empurra o `KeyError` para quem consome — e quem
    consome só devia precisar checar `abstem` antes de olhar o resto.
    """
    return {"pontos": pontos or [], "centro_fr": centro_fr,
            "ausentes": ausentes, "largura_esq": largura_esq,
            "largura_dir": largura_dir, "borda_esq": borda_esq,
            "borda_dir": borda_dir, "abstem": abstem, "motivo": motivo,
            "parametro": parametro}


def perfil_plato(trials: list[dict], espaco: dict, deploy: dict) -> dict:
    """O perfil do parâmetro varrido, com o DEPLOY marcado.

    A pergunta é o FORMATO da superfície: o ponto escolhido está num platô ou
    num pico? Medimos por fator de recuperação, não por lucro — lucro perto de
    zero faz a razão explodir, e o que interessa é lucro por unidade de
    mergulho.

    A largura é contada em PASSOS da grade para cada lado, parando no
    primeiro ponto que não segura 60% do centro. Combinação que perde metade
    do FR com um passo de diferença não é candidata, é coincidência. A
    mineração real (#40) varia só um parâmetro por vez: com dois vizinhos,
    "2k vizinhos" vira duas amostras — por isso o perfil olha a faixa
    inteira, não uma vizinhança fixa.

    `borda_esq`/`borda_dir` dizem POR QUE a caminhada parou daquele lado:
    `True` quando parou porque a grade acabou (nenhum ponto caiu abaixo do
    piso, só faltou mineração mais longe), `False` quando parou porque um
    ponto caiu abaixo do piso ou está ausente. Sem essa distinção, uma
    mineração que parou cedo (a #40 termina em 80, e o DEPLOY testado fica a
    só dois passos dali) parece "platô confirmado até a borda" para quem lê
    só o número — quando o correto é "não testamos mais longe". Largura
    grande com borda batida é região não explorada, não região comprovada.

    O centro pode ficar sem fator de recuperação por dois motivos que o
    motivo do retorno precisa distinguir: o DEPLOY não está na grade
    minerada (nenhum ponto casa com ele), ou está na grade mas o trial
    gravado não tem drawdown (`dd <= 0`) para calcular a razão. Tratar os
    dois como "não está na grade" faria a mensagem mentir no segundo caso.

    Fator de recuperação negativo no centro também exige abstenção: o piso
    é `centro_fr * 0.6`, e com `centro_fr` negativo o piso fica ACIMA do
    centro — a régua se inverte e vizinhos melhores passariam a contar como
    "fora do platô". Medir a forma de um platô em torno de uma combinação
    que dá prejuízo não tem sentido nenhum: o gate se abstém.
    """
    varridos = [k for k, v in espaco.items() if len(set(v)) > 1]
    if len(varridos) != 1:
        return _perfil(abstem=True,
                       motivo="perfil só existe com um parâmetro varrido")
    nome = varridos[0]
    grade = sorted({_valor(v) for v in espaco[nome]})

    achados = {}
    for t in trials:
        v = _valor(t["params"][nome])
        dd = float(t.get("dd") or 0.0)
        lucro = float(t.get("lucro") or 0.0)
        achados[v] = {"valor": v, "lucro": lucro,
                      "fr": (lucro / dd) if dd > 0 else None}

    alvo = _valor(deploy.get(nome, float("nan")))
    pontos = [dict(achados.get(v, {"valor": v, "lucro": None, "fr": None}),
                   atual=(v == alvo)) for v in grade]
    ausentes = sum(1 for p in pontos if p["fr"] is None)

    centro = next((p for p in pontos if p["atual"]), None)
    if centro is None:
        return _perfil(pontos=pontos, ausentes=ausentes, abstem=True,
                       motivo="o DEPLOY não está na grade minerada",
                       parametro=nome)

    centro_fr = centro["fr"]
    if centro_fr is None:
        return _perfil(pontos=pontos, ausentes=ausentes, abstem=True,
                       motivo=("o DEPLOY está na grade, mas o trial gravado "
                               "não tem drawdown para calcular o fator de "
                               "recuperação (dd <= 0 ou ausente)"),
                       parametro=nome)

    if centro_fr <= 0:
        return _perfil(pontos=pontos, centro_fr=centro_fr, ausentes=ausentes,
                       abstem=True,
                       motivo=("o DEPLOY dá prejuízo na mineração (fator de "
                               "recuperação <= 0); medir platô em torno de "
                               "uma perda não faz sentido"),
                       parametro=nome)

    piso = centro_fr * PLATO_PISO
    i = pontos.index(centro)

    def anda(passo):
        n, k = 0, i + passo
        while 0 <= k < len(pontos) and pontos[k]["fr"] is not None \
                and pontos[k]["fr"] >= piso:
            n += 1
            k += passo
        # k saiu do intervalo da grade sem nunca falhar o piso: a caminhada
        # não provou platô até a borda, só ficou sem grade para continuar
        borda = not (0 <= k < len(pontos))
        return n, borda

    largura_esq, borda_esq = anda(-1)
    largura_dir, borda_dir = anda(1)
    abstem_buraco = ausentes * 3 > len(pontos)
    return _perfil(
        pontos=pontos, centro_fr=centro_fr, ausentes=ausentes,
        largura_esq=largura_esq, largura_dir=largura_dir,
        borda_esq=borda_esq, borda_dir=borda_dir, abstem=abstem_buraco,
        motivo=("buraco grande demais na grade minerada: mais de um terço "
                "dos pontos não tem fator de recuperação, e portão que "
                "decide sobre grade furada decide sobre nada"
                ) if abstem_buraco else None,
        parametro=nome)
