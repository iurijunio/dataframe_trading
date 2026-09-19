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
           motivo=None, parametro=None, eixos=None) -> dict:
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
            "parametro": parametro, "eixos": eixos or []}


def _eixo_do_plato(trials: list[dict], grade: list, deploy: dict,
                   nome: str, outros: list[str]) -> dict:
    """O perfil de UM parâmetro, com os outros presos no valor escolhido.

    Fixar os outros é o que torna a leitura honesta numa mineração com vários
    parâmetros: "andar um passo no stop" só quer dizer algo se o resto do
    conjunto continuar o mesmo. Combinação que não casa com o DEPLOY nos
    outros parâmetros pertence a outra fatia da superfície e não entra.
    """
    fixos = {k: _valor(deploy[k]) for k in outros if k in deploy}
    achados = {}
    for t in trials:
        par = t.get("params") or {}
        if nome not in par:
            continue
        if any(_valor(par.get(k, float("nan"))) != v for k, v in fixos.items()):
            continue
        v = _valor(par[nome])
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
                       motivo="o valor escolhido não está na faixa minerada",
                       parametro=nome)
    centro_fr = centro["fr"]
    if centro_fr is None:
        return _perfil(pontos=pontos, ausentes=ausentes, abstem=True,
                       motivo=("o valor escolhido está na faixa, mas a "
                               "mineração não gravou a maior queda dele "
                               "para calcular o fator de recuperação"),
                       parametro=nome)
    if centro_fr <= 0:
        return _perfil(pontos=pontos, centro_fr=centro_fr, ausentes=ausentes,
                       abstem=True,
                       motivo=("o valor escolhido dá prejuízo na mineração; "
                               "não faz sentido medir região em volta de "
                               "uma perda"),
                       parametro=nome)

    piso = centro_fr * PLATO_PISO
    i = pontos.index(centro)

    def anda(passo):
        n, k = 0, i + passo
        while 0 <= k < len(pontos) and pontos[k]["fr"] is not None \
                and pontos[k]["fr"] >= piso:
            n += 1
            k += passo
        # por que a caminhada parou: a faixa acabou ("borda"), o próximo
        # valor não foi minerado ("buraco") ou foi minerado e caiu abaixo do
        # piso ("queda") — só esta última é reprovação de verdade
        if not (0 <= k < len(pontos)):
            motivo = "borda"
        elif pontos[k]["fr"] is None:
            motivo = "buraco"
        else:
            motivo = "queda"
        return n, motivo

    largura_esq, parada_esq = anda(-1)
    largura_dir, parada_dir = anda(1)
    furada = ausentes * 3 > len(pontos)
    return _perfil(
        pontos=pontos, centro_fr=centro_fr, ausentes=ausentes,
        largura_esq=largura_esq, largura_dir=largura_dir,
        borda_esq=parada_esq == "borda", borda_dir=parada_dir == "borda",
        parada_esq=parada_esq, parada_dir=parada_dir, abstem=furada,
        motivo=("mais de um terço dos valores desta faixa não foi minerado, "
                "e medir região em faixa furada não diz nada"
                ) if furada else None,
        parametro=nome)


def _pior_eixo(perfis: list[dict], passos_min: int = 2) -> dict:
    """Entre os eixos medidos, o que aguenta menos.

    A pergunta do portão é sobre o conjunto de parâmetros: basta um deles ser
    um pico para a combinação inteira ser frágil. Queda de verdade pesa mais
    que faixa que acabou — falta de medição não pode parecer defeito.
    """
    medidos = [p for p in perfis if not p["abstem"]]
    if not medidos:
        return perfis[0]

    def chave(p):
        estreito = min(p["largura_esq"], p["largura_dir"])
        tem_queda = any(
            n < passos_min and m == "queda"
            for n, m in ((p["largura_esq"], p["parada_esq"]),
                         (p["largura_dir"], p["parada_dir"])))
        return (0 if tem_queda else 1, estreito)

    return min(medidos, key=chave)


def perfil_plato(trials: list[dict], espaco: dict, deploy: dict,
                 passos_min: int = 2) -> dict:
    """A região em volta dos parâmetros escolhidos é larga, ou é um pico?

    Para cada parâmetro que a mineração varreu, a plataforma caminha pela
    faixa dele — um passo de cada vez, para os dois lados — com os outros
    parâmetros presos nos valores escolhidos, e conta quantos passos
    continuam dando pelo menos 60% do resultado do centro. O resultado de
    cada valor é medido por fator de recuperação (lucro dividido pela maior
    queda), não por lucro: lucro perto de zero faz a razão explodir, e o que
    interessa é lucro por unidade de mergulho.

    O retorno é o **pior** eixo, no mesmo formato de sempre, com a lista de
    todos em `eixos`. Um parâmetro frágil basta para a combinação ser
    frágil, e é por isso que vale o pior — a mineração de hoje varre dois
    parâmetros de uma vez, e olhar só um deles esconderia metade da
    superfície.

    `parada_esq`/`parada_dir` dizem POR QUE a caminhada parou daquele lado:
    `"borda"` quando a faixa minerada acabou, `"buraco"` quando o valor
    seguinte não foi minerado, `"queda"` quando ele foi minerado e caiu
    abaixo do piso — a única razão que reprova de verdade. Confundir
    "buraco" ou "borda" com "queda" faria falta de medição reprovar a
    estratégia.
    """
    varridos = [k for k, v in espaco.items() if len(set(v)) > 1]
    if not varridos:
        return _perfil(abstem=True,
                       motivo="a mineração não varreu nenhum parâmetro")

    perfis = []
    for nome in varridos:
        grade = sorted({_valor(v) for v in espaco[nome]})
        outros = [k for k in varridos if k != nome]
        perfis.append(_eixo_do_plato(trials, grade, deploy, nome, outros))

    escolhido = _pior_eixo(perfis, passos_min)
    resumo = [{"parametro": p["parametro"], "largura_esq": p["largura_esq"],
               "largura_dir": p["largura_dir"], "parada_esq": p["parada_esq"],
               "parada_dir": p["parada_dir"], "abstem": p["abstem"],
               "motivo": p["motivo"]} for p in perfis]
    return {**escolhido, "eixos": resumo}


# Como o selo escreve o valor de cada portão. Mora no PORTÃO, e não numa
# tabela da tela indexada pelo nome dele: com a tabela, renomear uma pergunta
# ("O parâmetro está..." virou "Os parâmetros estão...") fazia o número cair
# na regra genérica em silêncio — 0,03 aparecendo como "0,0%".
REAIS = "reais"
NUMERO = "numero"
FRACAO_PCT = "fracao_em_porcento"


def portao(nome, ok, critico, valor, exigido, dica, formato=None) -> dict:
    """A forma comum de todo portão da tela Candidata: nome do teste, se
    passou, se reprova a estratégia (ou é só alerta), o valor medido, o que
    era exigido e a dica de por que isso importa — tudo em português simples
    para quem lê a tela sem saber o jargão por trás da conta.

    `formato` diz ao selo como escrever `valor` quando ele é número: em
    reais, como número com duas casas, ou como fração que vira porcento.
    Sem ele, vale a regra genérica da tela."""
    return {"nome": nome, "ok": ok, "critico": critico, "valor": valor,
            "exigido": exigido, "dica": dica, "formato": formato}


# o segundo portão do platô sai por dois caminhos (medido ou abstido); com o
# texto escrito nos dois, uma edição num só já fez o mesmo portão aparecer
# com dois nomes na tela, conforme o dado
COBERTURA = "A faixa minerada cobre a região?"


def portoes_plato(perfil: dict, passos_min: int = 2) -> list[dict]:
    """A região dos parâmetros é larga? Só reprova com queda de verdade perto
    do centro: faixa que acaba ou valor não minerado são falta de medição, e
    falta de medição vira alerta, não reprovação."""
    nome = "Os parâmetros estão numa região larga?"
    eixos = perfil.get("eixos") or []
    quantos = len(eixos) or 1
    dica = (f"Para cada parâmetro minerado ({quantos} nesta mineração), "
            "a plataforma anda pela faixa dele, um valor por vez para cada "
            "lado, com os outros parâmetros parados no valor escolhido, e "
            "conta quantos passos continuam dando pelo menos 60% do "
            "resultado do centro (lucro dividido pela maior queda). Precisa "
            f"de pelo menos {passos_min} de cada lado. Um parâmetro que só "
            "funciona num valor exato é sorte, não estratégia — por isso "
            "vale o pior parâmetro, não a média.")
    if perfil.get("abstem"):
        # falta de MEDIÇÃO não é reprovação nem aprovação: alerta, para o
        # selo não mostrar visto verde sobre o que ninguém mediu
        motivo = perfil.get("motivo") or "não foi possível medir"
        return [portao(nome, False, False, motivo, f"≥ {passos_min} por lado",
                       dica),
                portao(COBERTURA, False, False,
                       motivo, "cobre",
                       "Este aviso acompanha o teste acima: sem faixa "
                       "minerada em volta do valor escolhido, não há como "
                       "saber se a região continua boa. Amplie a mineração "
                       "para medir.")]

    lados = [(perfil["largura_esq"], perfil["parada_esq"]),
             (perfil["largura_dir"], perfil["parada_dir"])]
    queda = any(n < passos_min and m == "queda" for n, m in lados)
    faltou = [m for n, m in lados if n < passos_min and m != "queda"]
    par = perfil.get("parametro") or "parâmetro"
    valor = (f"{par}: {perfil['largura_esq']} à esquerda · "
             f"{perfil['largura_dir']} à direita")
    if quantos > 1:
        valor += f" (o mais frágil de {quantos})"
    critico = portao(nome, not queda, True, valor, f"≥ {passos_min} por lado",
                     dica)
    alerta = portao(
        COBERTURA, not faltou, False,
        ("a faixa termina perto do valor escolhido" if "borda" in faltou
         else "há valores não minerados perto" if faltou else "sim"),
        "cobre",
        f"Quando a faixa minerada de {par} termina (ou tem buracos) a menos "
        f"de {passos_min} passos do valor escolhido, não dá para saber se a "
        "região continua boa daquele lado. Amplie a mineração para "
        "confirmar.")
    return [critico, alerta]


def alerta_vizinho(perfil: dict, raio: int = 2) -> dict:
    """Algum valor a até `raio` passos do escolhido dá prejuízo?"""
    dica = (f"Valores do parâmetro a até {raio} passos do escolhido que "
            "deram prejuízo na mineração. Um vizinho no vermelho não reprova, "
            "mas diz que um pequeno erro de ajuste já custa dinheiro.")
    pontos = perfil.get("pontos") or []
    i = next((k for k, p in enumerate(pontos) if p.get("atual")), None)
    if i is None:
        # C2: sem ponto para examinar (lista vazia, ou o parâmetro do
        # DEPLOY fora da grade minerada) não há vizinho nenhum olhado — o
        # comportamento antigo (`ok=True`, "nenhum") dizia "nenhum vizinho
        # deu prejuízo" quando na verdade nenhum foi sequer checado.
        return portao("Algum vizinho dá prejuízo?", None, False,
                      "não medido", "nenhum", dica)
    ruins = [p for p in pontos[max(0, i - raio): i + raio + 1]
             if p.get("lucro") is not None and p["lucro"] < 0]
    return portao(
        "Algum vizinho dá prejuízo?", not ruins, False,
        f"{len(ruins)} com prejuízo" if ruins else "nenhum", "nenhum", dica)


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
    nome = "O lucro não é acaso?"
    # vírgula, não ponto: o resto da tela é pt-BR e "≥ 2.0" lê como outro
    # número para quem está acostumado com "2,0"
    exigido = "≥ " + f"{minimo:.1f}".replace(".", ",")
    dica = ("Compara o ganho médio por dia com o quanto o resultado diário "
            "oscila. Abaixo de 2, a média ainda pode ser zero e o lucro "
            "visto ser sorte. Conta os dias parados como zero.")
    if len(np.asarray(pnl)) < 30:
        # I1: `t_diario` devolve 0.0 com menos de 30 pregões — o jeito da
        # própria função dizer "não dá para afirmar nada aqui". Sem este
        # desvio, 0.0 virava a MEDIDA na tela e reprovava mostrando "0,00",
        # como se fosse um resultado ruim de verdade em vez de falta de
        # pregão — os portões irmãos (poucos dias, capital) já seguem esta
        # régua de "não medido" em vez de reprovar por falta de dado.
        return portao(nome, None, True, "poucos pregões para medir", exigido, dica)
    t = t_diario(pnl)
    return portao(nome, t >= minimo, True, round(t, 2), exigido, dica,
                  formato=NUMERO)


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
        exigido, dica, formato=REAIS)


def portao_custo(lucro_liquido: float, contratos, tick_value: float | None) -> dict:
    nome = "Aguenta custo maior?"
    exigido = "> 0 com +1 tick por ponta"
    dica = ("O lucro depois de pagar 1 tick a mais na entrada e na saída de "
            "cada trade. No mini índice 1 tick vale mais que a corretagem "
            "inteira, e ordem a mercado na hora da pressa costuma escorregar "
            "isso. Se o lucro some, a estratégia vive no limite do custo.")
    if tick_value is None:
        # menor: sem `tick_value` no YAML do instrumento, o chamador não
        # pode fingir tick zero (custo extra some e o portão passa à toa) —
        # sem o dado, o portão fica pendente, não aprovado
        return portao(nome, None, True, "não medido", exigido, dica)
    extra = 2.0 * float(np.sum(contratos)) * tick_value
    sobra = float(lucro_liquido - extra)
    return portao(nome, sobra > 0, True, round(sobra, 2), exigido, dica,
                  formato=REAIS)


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
    if perda_esperada is None:
        # sem caminhos sorteados não há perda esperada — e ler 0,0 no lugar
        # dela aprovava o portão em verde com "0% do capital"
        return portao("O capital comporta 1 contrato?", None, True,
                      "curva curta demais para sortear caminhos", exigido,
                      dica)
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
        "reprova, mas diz que o resultado mora em poucas operações.",
        formato=REAIS)


def portao_holdout(dias, pnl, corte, capital, n: int = 2000,
                   semente: int = 7) -> dict:
    """O holdout confirma? Compara o que a estratégia fez nos meses do holdout
    com o que a curva ANTES do corte fazia esperar para o mesmo número de
    dias. Só o lado ruim reprova.

    Três jeitos de não medir, cada um com o motivo certo — e só dois deles
    bloqueiam de verdade. `corte=None` é a MINERAÇÃO nunca ter marcado
    holdout: não há corte nenhum para comparar, e não existe "rodar de novo"
    que resolva — mas ainda assim é uma lacuna real da candidata (crítico).
    Sem pregão nenhum DEPOIS do corte é este WALK-FORWARD específico não ter
    sido salvo com "estender ao holdout" — resalvar com a caixa marcada
    resolve, então continua crítico. Histórico ANTES do corte curto demais
    para o bootstrap (`boot` vazio) é o único dos três que TAMBÉM não tem
    conserto (a base é a que é, rodar os testes completos de novo não muda
    isso) — por isso vira ALERTA (`ok=False`, `critico=False`), não
    `ok=None`: um crítico pendente para sempre travava o veredito em
    "aguardando testes completos" pra sempre, e falta de medição que nada
    resolve segue a mesma régua do platô (`portoes_plato`): não é
    reprovação, mas também não fica pendurada feito pendente eterno.
    """
    from . import robustez
    nome = "O holdout confirma?"
    dica = ("O holdout são os meses finais que ficaram de fora da mineração. "
            "A plataforma simula 2.000 caminhos do mesmo tamanho usando só o "
            "que a estratégia fez antes deles, e olha onde o resultado real do "
            "holdout caiu. Reprova se ficar entre os 10% piores caminhos. "
            "Resultado melhor que o esperado passa.")
    base = {"lucro_mes_antes": None, "lucro_mes_holdout": None,
            "esperado_p10": None, "pregoes_holdout": 0}
    if corte is None:
        return {**portao(nome, False, True,
                         "esta mineração não tem holdout separado",
                         "dentro do esperado", dica), **base}
    d = np.asarray(dias, dtype="datetime64[D]")
    x = np.asarray(pnl, dtype=float)
    c = np.datetime64(corte, "D")
    antes, depois = x[d < c], x[d >= c]
    base["pregoes_holdout"] = int(len(depois))
    if not len(depois):
        return {**portao(nome, False, True,
                         "sem holdout na curva — salve o walk-forward com o "
                         "holdout marcado", "dentro do esperado", dica), **base}
    boot = robustez.bootstrap(antes, capital, n=n, semente=semente,
                              horizonte=len(depois))
    if not boot:
        return {**portao(nome, False, False,
                         "histórico antes do corte curto demais para comparar",
                         "dentro do esperado", dica), **base}
    real = float(depois.sum())
    p10 = float(boot["final_p10"])
    return {**portao(nome, real >= p10, True, round(real, 2),
                     "fora dos 10% piores caminhos", dica, formato=REAIS),
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
    return portao(nome, p <= maximo, True, p, exigido, dica,
                  formato=FRACAO_PCT)


def portao_aleatorio(resultado: dict, maximo: float = 0.05) -> dict:
    """O portão 2: ganha de entradas sorteadas ao acaso?

    Recebe o dicionário de `aleatorio.teste_janelas` — troca as entradas da
    estratégia por entradas sorteadas ao acaso (mesmo horário, mesma
    proporção compra/venda), mantendo toda a gestão de saída da estratégia
    real, janela a janela do walk-forward. Se o resultado real não se
    destaca do sorteio, o mérito é da gestão de saída, não do sinal.

    Sem resultado (a thread foi interrompida antes de terminar e
    `teste_janelas` devolveu `{}`, ou faltou algum dado) o portão fica
    pendente, com o motivo no lugar do valor — falta de dado não é
    reprovação.

    A calibração (quantos sinais sortear até o número de trades bater o da
    real, dentro de 5%) precisa ter dado certo em TODAS as janelas. Se
    alguma não bateu, o sorteio operou mais ou menos que a real por um
    motivo que não é o sinal, e o p-valor não serve para nada — o portão
    fica pendente mesmo que `p` exista.
    """
    nome = "Ganha de entradas sorteadas ao acaso?"
    exigido = f"até {maximo:.0%} de chance de o sorteio ter ganhado à toa"
    dica = ("Troca as entradas da estratégia por entradas sorteadas ao "
            "acaso, no mesmo horário, e deixa toda a gestão de saída (stop, "
            "alvo e as demais regras) exatamente como a real. Se o "
            "resultado real não se destacar do sorteio, quem está ganhando "
            f"é a gestão, não o sinal de entrada. Reprova acima de "
            f"{maximo:.0%} de chance de o sorteio ter ganhado por acaso.")
    if not resultado or "erro" in resultado:
        motivo = resultado.get("erro") if resultado else "não foi possível medir"
        return portao(nome, None, True, motivo, exigido, dica)
    if not resultado.get("calibracao_ok", False):
        return portao(
            nome, None, True,
            "o sorteio não conseguiu imitar o número de trades em alguma janela",
            exigido, dica)
    p = resultado["p"]
    return portao(nome, p <= maximo, True, p, exigido, dica,
                  formato=FRACAO_PCT)


def alerta_reotimizar(percentil: float | None, motivo: str | None = None) -> dict:
    """O alerta: reotimizar a cada janela compensou?

    Compara a curva do walk-forward (que troca de parâmetros a cada janela)
    com o resultado de ter deixado cada combinação minerada FIXA do início
    ao fim do mesmo período (`wfa.faixa_fixas` + `wfa.percentil_na_faixa`).
    Passa a partir do percentil 50: abaixo disso, mais da metade das
    combinações fixas — escolhidas sem nenhuma inteligência, só por estarem
    na grade — teriam feito melhor que o walk-forward, e o trabalho de
    reotimizar não se pagou.

    `percentil None` (walk-forward sem combinações fixas suficientes para
    montar a faixa de comparação, OU a fase que calcularia o percentil não
    chegou a rodar) deixa o alerta pendente — falta de dado, não reprovação.
    `motivo` troca a mensagem padrão "não foi possível medir" por uma mais
    específica (ex.: "não rodou: <erro>", quando é `core/candidata_runner.py`
    quem publica um alerta pendente por causa de uma exceção numa fase
    anterior, não pela falta natural de combinações fixas).
    """
    nome = "Reotimizar compensou?"
    exigido = "percentil 50 ou mais entre as combinações fixas"
    dica = ("Compara a curva do walk-forward, que troca de parâmetros a "
            "cada janela, com o resultado de ter deixado cada combinação "
            "minerada fixa do início ao fim do mesmo período. Se o "
            "walk-forward termina abaixo de metade dessas combinações "
            "fixas, escolher uma delas ao acaso teria feito melhor na "
            "maioria das vezes — reotimizar não valeu o trabalho.")
    if percentil is None:
        return portao(nome, None, False, motivo or "não foi possível medir",
                      exigido, dica)
    return portao(nome, percentil >= 50, False, round(percentil, 1), exigido, dica)


def portoes_rapidos(trades: list[dict], leitura: dict, trials: list[dict],
                    espaco: dict, deploy: dict, corte, tick_value: float | None,
                    capital: float, de=None, ate=None) -> list[dict]:
    """Os portões e alertas que respondem NA HORA, ao escolher o
    walk-forward — tudo o que não depende dos três testes demorados
    (aleatório, tentativas, reotimizar compensou), que vivem em
    `candidata_runner.TestesCompletos` e levam cerca de um minuto.

    Recebe os TRADES crus, não só `leitura`: o portão de custo e o de
    capital precisam de CONTRATOS por trade, número que `leitura_robustez`
    não carrega adiante (ela vira pregão a pregão e o trade individual some).
    `de`/`ate` são os limites da curva fora da amostra segundo o WFA
    (`limites_oos`) — os MESMOS que produziram `leitura`, para o pregão a
    pregão calculado aqui bater com o `pior_dos_recortes` que lê de lá.
    Primeiro/último trade em vez das janelas já divergiu em pregões noutro
    lugar desta tela (ver o comentário de `por_pregao`).

    Ordem fixa, decidida na tarefa 7: platô (crítico e alerta de faixa),
    acaso, poucos dias, custo, capital, holdout, alerta de vizinho, alerta
    de 1% dos trades. Os três testes demorados entram depois desta lista —
    este módulo não sabe (e não precisa saber) se eles já rodaram.
    """
    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liquido = np.array([t["liquido"] for t in trades], dtype=float)
    contratos = np.array([t.get("contratos") or 1 for t in trades], dtype=float)
    dias, pnl = por_pregao(saida, liquido, de=de, ate=ate)

    perfil = perfil_plato(trials, espaco, deploy)
    pior = pior_dos_recortes(leitura)
    # sem sorteio nos dois recortes, `pior_dos_recortes` devolve 0,0 — que é
    # "não medido", não "perda zero"
    perda_esperada = (pior["dd_p95"]["valor"]
                      if (leitura.get("boot") or leitura.get("boot_12m"))
                      else None)
    contratos_por_trade = float(np.median(contratos)) if len(contratos) else 1.0
    lucro_liquido = float((leitura.get("resumo") or {}).get("lucro_liquido", 0.0))

    return [
        *portoes_plato(perfil),
        portao_acaso(pnl),
        portao_poucos_dias(pnl),
        portao_custo(lucro_liquido, contratos, tick_value),
        portao_capital(perda_esperada, contratos_por_trade, capital),
        # `corte=None` (mineração sem holdout marcado) vai direto para
        # `portao_holdout`, que sabe dizer "esta mineração não tem holdout
        # separado" — sem sentinela de data aqui
        portao_holdout(dias, pnl, corte, capital),
        alerta_vizinho(perfil),
        alerta_poucos_trades(liquido),
    ]


def portoes_pendentes() -> list[dict]:
    """Os três portões demorados, com `ok=None` e valor "aguardando",
    enquanto `candidata_runner.TESTES` não tem resultado para este
    walk-forward.

    Usa as próprias funções de produção com entrada vazia — elas já
    devolvem `ok=None` sozinhas (dado faltando não reprova); só o `valor`
    troca pelo texto que a tela mostra igual para os três, no lugar do
    motivo específico de "sem dado" que cada uma escreveria por conta
    própria (motivo que aqui nunca se aplica: os dados existem, só não
    rodaram ainda).
    """
    return [{**p, "valor": "aguardando"}
            for p in (portao_aleatorio({}), portao_tentativas({}),
                     alerta_reotimizar(None))]


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
