"""A tela Candidata: o passo 10 da metodologia sobre a curva que o
otimizador nunca viu.

Aqui ficam as contas puras — sem Dash, sem banco. Quem lê o banco é o
callback; quem decide é o portão; quem calcula é este módulo.
"""

from __future__ import annotations

import numpy as np

from . import wfa


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
                     horizonte_pregoes: int | None = None,
                     de=None, ate=None) -> dict:
    """O bloco 1: a robustez medida na curva que o otimizador nunca viu.

    Dois recortes sempre: a curva inteira e os últimos 12 meses. O mini
    índice foi de 96 mil a 197 mil pontos dentro da própria amostra — stop e
    alvo em pontos não significam a mesma coisa nas duas pontas, e o risco do
    regime atual não é a média de cinco anos. Vale o pior dos dois.

    `de`/`ate` são os limites da curva fora da amostra segundo o WFA (a
    extensão das janelas reais, sem a linha DEPLOY — ver `limites_oos`), não
    o primeiro e o último TRADE. As duas contas divergem sempre que algum
    pregão da janela não teve trade nenhum: no walk-forward #3 a diferença
    foi de 1.041 contra 1.044 pregões. Sem eles, cai no comportamento de
    sempre — do primeiro ao último trade.
    """
    if len(trades) < MIN_TRADES:
        return {"erro": f"menos de {MIN_TRADES} trades fora da amostra"}

    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liq = np.array([t["liquido"] for t in trades], dtype=float)
    custo = np.array([t.get("custo", 0.0) for t in trades], dtype=float)
    dias, pnl = por_pregao(saida, liq, de=de, ate=ate)
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


_METRICAS_RISCO = ("dd_p95", "perdas_seguidas_p95", "submerso_p95")


def pior_dos_recortes(leitura: dict) -> dict:
    """Para cada métrica de risco, o PIOR valor entre os dois recortes — e de
    qual recorte ele veio.

    O desenho (§4.1 do PLANO-CANDIDATA) manda TODAS as contas de risco
    rodarem nos dois recortes — curva inteira e últimos 12 meses — valendo o
    pior. Antes desta função só "drawdown esperado" comparava os dois;
    "perdas seguidas" e "pregões abaixo do topo" liam sempre `boot`, e
    ficavam otimistas sempre que o recorte de 12 meses fosse o pior daquela
    métrica específica — no walk-forward #3 o recorte de 12 meses dá 17
    perdas seguidas no p95 contra 15 na curva inteira, e a tela mostrava 15.

    A escolha é POR MÉTRICA, não por recorte inteiro: o recorte de 12 meses
    pode ser pior em uma métrica e melhor em outra na mesma leitura, e usar
    um único "recorte vencedor" para as três esconderia a pior das duas em
    quem perdeu a disputa geral. Em empate, vale a curva inteira.

    `boot_12m` vazio (menos de 30 pregões no recorte) faz as três métricas
    caírem para `boot` — não há o que comparar.
    """
    boot = leitura.get("boot") or {}
    boot12 = leitura.get("boot_12m") or {}
    out = {}
    for m in _METRICAS_RISCO:
        v_total = float(boot.get(m, 0.0))
        if not boot12:
            out[m] = {"valor": v_total, "recorte": "curva inteira"}
            continue
        v_12m = float(boot12.get(m, 0.0))
        if v_12m > v_total:
            out[m] = {"valor": v_12m, "recorte": "últimos 12 meses"}
        else:
            out[m] = {"valor": v_total, "recorte": "curva inteira"}
    return out


def calcula_horizonte(detalhes: dict) -> int:
    """Pregões até a próxima reotimização — o horizonte que calibra o
    bootstrap do bloco 1.

    Extraída do callback para poder ser testada sem montar o app Dash, e
    porque quebrar o cálculo do horizonte pelo DEPLOY é justamente uma das
    mutações que os 432 testes antigos não pegavam (I2 do plano de
    correção). Com DEPLOY gravado, o horizonte é a extensão real da janela
    que ele projeta — `wfa.pregoes`, o mesmo contador que o resto da
    plataforma usa, não a aproximação de 21 pregões úteis por mês. Sem
    DEPLOY (registro salvo antes desta tela), cai na aproximação; `oos_meses`
    pode vir `None`, daí o piso de 6 meses antes de multiplicar.
    """
    deploy = detalhes.get("deploy") or {}
    if deploy.get("oos_de") and deploy.get("oos_ate"):
        return wfa.pregoes(deploy["oos_de"], deploy["oos_ate"])
    return int((detalhes.get("oos_meses") or 6) * 21)


def limites_oos(passos: list[dict] | None) -> tuple:
    """Início e fim da curva fora da amostra segundo o WFA: o `oos_de` da
    primeira janela REAL e o `oos_ate` da última, ignorando a linha DEPLOY
    (cujo OOS é o futuro, ainda não aconteceu).

    Contar do primeiro ao último TRADE (o que `leitura_robustez` fazia sem
    estes limites) e contar a extensão das JANELAS (o que o cartão do WFA e
    o Sharpe da matriz fazem) dão números diferentes sempre que algum
    pregão da janela não teve trade — no #3 a diferença foi de 1.041 contra
    1.044 pregões. Sem `passos` (ou só a linha DEPLOY), devolve `(None,
    None)` e quem chama cai no comportamento antigo.
    """
    reais = [p for p in (passos or []) if p.get("step") != "DEPLOY"]
    if not reais:
        return None, None
    return reais[0]["oos_de"], reais[-1]["oos_ate"]


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
           largura_dir=0, borda_esq=False, borda_dir=False,
           parada_esq=None, parada_dir=None, abstem=False,
           motivo=None, parametro=None) -> dict:
    """Monta o retorno de `perfil_plato` com o contrato sempre completo.

    A próxima fase liga um portão neste dicionário. Ramo que devolve um
    subconjunto de chaves empurra o `KeyError` para quem consome — e quem
    consome só devia precisar checar `abstem` antes de olhar o resto.
    """
    return {"pontos": pontos or [], "centro_fr": centro_fr,
            "ausentes": ausentes, "largura_esq": largura_esq,
            "largura_dir": largura_dir, "borda_esq": borda_esq,
            "borda_dir": borda_dir, "parada_esq": parada_esq,
            "parada_dir": parada_dir, "abstem": abstem, "motivo": motivo,
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

    `parada_esq`/`parada_dir` dizem POR QUE a caminhada parou daquele lado:
    `"borda"` quando a grade acabou (nenhum ponto caiu abaixo do piso, só
    faltou mineração mais longe), `"buraco"` quando o próximo ponto não foi
    minerado (`fr is None`), `"queda"` quando o próximo ponto foi minerado e
    caiu abaixo do piso — a única razão que reprova de verdade. Confundir
    "buraco" ou "borda" com "queda" faz um ponto nunca medido reprovar a
    estratégia por falta de dado, não por resultado ruim. `borda_esq` e
    `borda_dir` continuam existindo como atalho (`parada == "borda"`) para
    quem só quer saber se a grade acabou. Sem essa distinção, uma mineração
    que parou cedo (a #40 termina em 80, e o DEPLOY testado fica a só dois
    passos dali) parece "platô confirmado até a borda" para quem lê só o
    número — quando o correto é "não testamos mais longe". Largura grande
    com borda batida é região não explorada, não região comprovada.

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
        # por que a caminhada parou: grade acabou ("borda"), o próximo ponto
        # não foi minerado ("buraco") ou foi minerado e caiu abaixo do piso
        # ("queda") — só esta última é reprovação de verdade
        if not (0 <= k < len(pontos)):
            motivo = "borda"
        elif pontos[k]["fr"] is None:
            motivo = "buraco"
        else:
            motivo = "queda"
        return n, motivo

    largura_esq, parada_esq = anda(-1)
    largura_dir, parada_dir = anda(1)
    abstem_buraco = ausentes * 3 > len(pontos)
    return _perfil(
        pontos=pontos, centro_fr=centro_fr, ausentes=ausentes,
        largura_esq=largura_esq, largura_dir=largura_dir,
        borda_esq=parada_esq == "borda", borda_dir=parada_dir == "borda",
        parada_esq=parada_esq, parada_dir=parada_dir, abstem=abstem_buraco,
        motivo=("buraco grande demais na grade minerada: mais de um terço "
                "dos pontos não tem fator de recuperação, e portão que "
                "decide sobre grade furada decide sobre nada"
                ) if abstem_buraco else None,
        parametro=nome)


def portao(nome, ok, critico, valor, exigido, dica) -> dict:
    """A forma comum de todo portão da tela Candidata: nome do teste, se
    passou, se reprova a estratégia (ou é só alerta), o valor medido, o que
    era exigido e a dica de por que isso importa — tudo em português simples
    para quem lê a tela sem saber o jargão por trás da conta."""
    return {"nome": nome, "ok": ok, "critico": critico, "valor": valor,
            "exigido": exigido, "dica": dica}


def portoes_plato(perfil: dict, passos_min: int = 2) -> list[dict]:
    """A região do parâmetro é larga? Só reprova com queda de verdade perto
    do centro: faixa testada que acaba ou ponto não minerado são falta de
    medição, e falta de medição vira alerta, não reprovação."""
    nome = "O parâmetro está numa região larga?"
    dica = ("Mede quantos valores vizinhos do parâmetro escolhido, para cada "
            "lado, continuam dando pelo menos 60% do resultado dele (lucro "
            "dividido pela maior queda). Precisa de pelo menos 2 de cada "
            "lado: um parâmetro que só funciona num valor exato é sorte, não "
            "estratégia.")
    if perfil.get("abstem"):
        return [portao(nome, True, True, "não medido", f"≥ {passos_min} por lado", dica),
                portao("A região foi medida por inteiro?", False, False,
                       perfil.get("motivo") or "não foi possível medir", "medida",
                       "Sem dados suficientes da mineração para medir a região.")]
    lados = [(perfil["largura_esq"], perfil["parada_esq"]),
             (perfil["largura_dir"], perfil["parada_dir"])]
    queda = any(n < passos_min and m == "queda" for n, m in lados)
    faltou = [m for n, m in lados if n < passos_min and m != "queda"]
    valor = f"{perfil['largura_esq']} à esquerda · {perfil['largura_dir']} à direita"
    critico = portao(nome, not queda, True, valor, f"≥ {passos_min} por lado", dica)
    alerta = portao(
        "A faixa testada cobre a região?", not faltou, False,
        ("termina perto do parâmetro" if "borda" in faltou
         else "há valores não minerados perto" if faltou else "sim"),
        "cobre",
        "Quando a faixa minerada termina (ou tem buracos) a menos de 2 passos "
        "do parâmetro escolhido, não dá para saber se a região continua boa "
        "daquele lado. Amplie a mineração para confirmar.")
    return [critico, alerta]


def alerta_vizinho(perfil: dict, raio: int = 2) -> dict:
    """Algum valor a até `raio` passos do escolhido dá prejuízo?"""
    pontos = perfil.get("pontos") or []
    i = next((k for k, p in enumerate(pontos) if p.get("atual")), None)
    ruins = [] if i is None else [
        p for p in pontos[max(0, i - raio): i + raio + 1]
        if p.get("lucro") is not None and p["lucro"] < 0]
    return portao(
        "Algum vizinho dá prejuízo?", not ruins, False,
        f"{len(ruins)} com prejuízo" if ruins else "nenhum", "nenhum",
        "Valores do parâmetro a até 2 passos do escolhido que deram prejuízo "
        "na mineração. Um vizinho no vermelho não reprova, mas diz que um "
        "pequeno erro de ajuste já custa dinheiro.")


# --------------------------------------- portões que saem dos dados salvos


def t_diario(pnl: np.ndarray) -> float:
    """Média diária dividida pelo seu erro, contando os dias parados. É o
    teste do resultado por DIA, e não por trade: trades do mesmo pregão
    andam juntos, e contá-los como independentes infla a firmeza."""
    x = np.asarray(pnl, dtype=float)
    if len(x) < 30:
        return 0.0
    desvio = float(x.std(ddof=1))
    return float(x.mean() / (desvio / np.sqrt(len(x)))) if desvio > 0 else 0.0


def portao_acaso(pnl, minimo: float = 2.0) -> dict:
    t = t_diario(pnl)
    return portao(
        "O lucro não é acaso?", t >= minimo, True, round(t, 2), f"≥ {minimo:.1f}",
        "Compara o ganho médio por dia com o quanto o resultado diário oscila. "
        "Abaixo de 2, a média ainda pode ser zero e o lucro visto ser sorte. "
        "Conta os dias parados como zero.")


def portao_poucos_dias(pnl, quantos: int = 5) -> dict:
    x = np.asarray(pnl, dtype=float)
    dica = (f"O lucro total tirando os {quantos} melhores dias. Se ficar "
            "negativo, a estratégia viveu de alguns dias de sorte — que "
            "podem não se repetir.")
    exigido = f"> 0 sem os {quantos} melhores"
    if len(x) <= quantos:
        # tirar "os N melhores" de uma amostra com N dias ou menos zera a
        # amostra inteira: reprovaria por falta de dado, não por resultado
        # ruim, então o portão fica pendente em vez de reprovado
        return portao("O lucro não depende de poucos dias?", None, True,
                      "poucos pregões para medir", exigido, dica)
    sobra = float(x.sum() - np.sort(x)[::-1][:quantos].sum())
    return portao(
        "O lucro não depende de poucos dias?", sobra > 0, True, round(sobra, 2),
        exigido, dica)


def portao_custo(lucro_liquido: float, contratos, tick_value: float) -> dict:
    extra = 2.0 * float(np.sum(contratos)) * tick_value
    sobra = float(lucro_liquido - extra)
    return portao(
        "Aguenta custo maior?", sobra > 0, True, round(sobra, 2),
        "> 0 com +1 tick por ponta",
        "O lucro depois de pagar 1 tick a mais na entrada e na saída de cada "
        "trade. No mini índice 1 tick vale mais que a corretagem inteira, e "
        "ordem a mercado na hora da pressa costuma escorregar isso. Se o lucro "
        "some, a estratégia vive no limite do custo.")


def portao_capital(perda_esperada: float, contratos_por_trade: float,
                   capital: float, teto_pct: float = 20.0) -> dict:
    exigido = f"≤ {teto_pct:.0f}% do capital"
    dica = ("A perda esperada operando só 1 contrato, em % do capital. Se "
            "nem o mínimo cabe, não é a estratégia que está errada — é o "
            "capital que não comporta o instrumento.")
    if capital <= 0:
        # capital <= 0 faria a % virar `inf` (nem é JSON válido, e a tela
        # mostraria "inf% do capital"); sem capital informado não dá para
        # medir, então o portão fica pendente, não reprovado
        return portao("O capital comporta 1 contrato?", None, True,
                      "capital não informado", exigido, dica)
    por_contrato = perda_esperada / max(float(contratos_por_trade), 1.0)
    pct_ = por_contrato / capital * 100
    return portao(
        "O capital comporta 1 contrato?", pct_ <= teto_pct, True,
        round(pct_, 1), exigido, dica)


def alerta_poucos_trades(liquido, fracao: float = 0.01) -> dict:
    x = np.sort(np.asarray(liquido, dtype=float))[::-1]
    k = max(1, int(np.ceil(len(x) * fracao)))
    sobra = float(x.sum() - x[:k].sum())
    return portao(
        "Depende do 1% melhor dos trades?", sobra > 0, False, round(sobra, 2),
        "> 0 sem eles",
        "O lucro tirando o 1% de trades que mais ganharam. Negativo não "
        "reprova, mas diz que o resultado mora em poucas operações.")


def portao_holdout(dias, pnl, corte, capital, n: int = 2000,
                   semente: int = 7) -> dict:
    """O holdout confirma? Compara o que a estratégia fez nos meses do holdout
    com o que a curva ANTES do corte fazia esperar para o mesmo número de
    dias. Só o lado ruim reprova."""
    from . import robustez
    d = np.asarray(dias, dtype="datetime64[D]")
    x = np.asarray(pnl, dtype=float)
    c = np.datetime64(corte, "D")
    antes, depois = x[d < c], x[d >= c]
    nome = "O holdout confirma?"
    dica = ("O holdout são os meses finais que ficaram de fora da mineração. "
            "A plataforma simula 2.000 caminhos do mesmo tamanho usando só o "
            "que a estratégia fez antes deles, e olha onde o resultado real do "
            "holdout caiu. Reprova se ficar entre os 10% piores caminhos. "
            "Resultado melhor que o esperado passa.")
    base = {"lucro_mes_antes": None, "lucro_mes_holdout": None,
            "esperado_p10": None, "pregoes_holdout": int(len(depois))}
    if not len(depois):
        return {**portao(nome, False, True,
                         "sem holdout na curva — salve o walk-forward com o "
                         "holdout marcado", "dentro do esperado", dica), **base}
    boot = robustez.bootstrap(antes, capital, n=n, semente=semente,
                              horizonte=len(depois))
    if not boot:
        return {**portao(nome, None, True, "histórico curto demais",
                         "dentro do esperado", dica), **base}
    real = float(depois.sum())
    p10 = float(boot["final_p10"])
    return {**portao(nome, real >= p10, True, round(real, 2),
                     "fora dos 10% piores caminhos", dica),
            "lucro_mes_antes": float(antes.sum()) / max(len(antes) / 21, 1e-9),
            "lucro_mes_holdout": real / max(len(depois) / 21, 1e-9),
            "esperado_p10": p10, "pregoes_holdout": int(len(depois))}


def portao_tentativas(resultado_spa: dict, maximo: float = 0.05) -> dict:
    """O portão 6: aguenta o desconto por muitas tentativas?

    Recebe o dicionário de `spa.teste` (a Superior Predictive Ability de
    Hansen, 2005, aplicada às combinações mineradas). Sem resultado (dado
    faltando, ou `spa.teste` devolveu `{"erro": ...}` porque faltou pregão,
    reamostragem ou coluna com desvio para medir) o portão fica pendente,
    não reprovado — falta de dado não é a mesma coisa que resultado ruim, e
    o motivo vem no `valor` para a tela explicar por que não mediu.

    `maximo` default é 0,05, não 0,10: com dependência entre dias o sorteio
    em blocos rejeita acima do nível nominal (o bloco mínimo precisa de um
    piso — ver `spa.teste` — e isso custa precisão). Medido com 200
    simulações (matriz 600×20, sem ganho nenhum real): o nível nominal de
    10% deixava passar sorte em 16,5%–18% das vezes para φ ≤ 0,2; pedindo
    5% nominal, a passagem de sorte cai para 7,5%–9,5% — perto do "até
    cerca de 1 em 10" que a regra pretendia."""
    nome = "Aguenta o desconto por muitas tentativas?"
    dica = (f"Foram testadas muitas combinações; alguma sempre sai bem por "
            f"sorte. Este teste mede se a melhor delas continua sendo "
            f"melhor que não operar depois de descontar isso. Reprova "
            f"acima de {maximo:.0%}.")
    exigido = f"até {maximo:.0%} de chance de ser sorte"
    if not resultado_spa or "erro" in resultado_spa:
        motivo = resultado_spa["erro"] if resultado_spa else "não foi possível medir"
        return portao(nome, None, True, motivo, exigido, dica)
    p = resultado_spa["p"]
    return portao(nome, p <= maximo, True, p, exigido, dica)


def veredito(portoes: list[dict]) -> dict:
    """Crítico reprovado reprova. Crítico ainda não medido impede aprovar.
    Alerta reprovado aprova com ressalva."""
    reprovados = [p for p in portoes if p["critico"] and p["ok"] is False]
    pendentes = [p for p in portoes if p["critico"] and p["ok"] is None]
    ressalvas = [p for p in portoes if not p["critico"] and p["ok"] is False]
    if reprovados:
        estado, cor = "reprovada", "neg"
    elif pendentes or not portoes:
        # lista vazia é o mesmo problema que um pendente: nenhum portão
        # mediu nada, então a tela não pode aprovar em verde uma estratégia
        # que não foi testada em nada
        estado, cor = "aguardando testes completos", "warn"
    elif ressalvas:
        estado, cor = "aprovada com ressalva", "warn"
    else:
        estado, cor = "aprovada", "pos"
    return {"portoes": portoes, "estado": estado, "cor": cor,
            "n_ok": sum(1 for p in portoes if p["ok"] is True),
            "n_portoes": len(portoes), "reprovados": reprovados,
            "ressalvas": ressalvas, "pendentes": pendentes}
