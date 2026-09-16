"""Triagem de candidato: quanto deste resultado é sorte?

O painel de métricas diz quanto rendeu. Este módulo responde a outra
pergunta, que é a que decide se vale levar a estratégia adiante:

    monte_carlo      -> o drawdown que eu vi foi sorte de ordenação?
    drawdowns        -> quanto tempo eu passaria no vermelho?
    significancia    -> a expectativa é distinguível de zero?
    teste_runs       -> as perdas vêm agrupadas?
    correlacao_lr    -> a curva é uma reta ou um degrau?
    concentracao     -> o lucro vem de muitos trades ou de cinco?
    ulcer_mar        -> como este candidato se ordena contra os outros?
    meses_positivos  -> eu aguentaria operar isto?
    custo_que_zera   -> quanta corretagem a estratégia suporta?

Quem molda parâmetro é a mineração com walk-forward. Aqui é peneira: o que
reprova rápido vem primeiro, e nada depende de rodar backtest de novo — tudo
sai dos trades que o kernel já devolveu.

Sem scipy de propósito: o p-valor usa a aproximação normal, que para as
centenas de trades desta escala é indistinguível do t exato.
"""

from __future__ import annotations

import math

import numpy as np

DIAS_ANO = 252


# --------------------------------------------------------------- sequência
def monte_carlo(liquido: np.ndarray, capital: float, n: int = 2000,
                semente: int = 7) -> dict:
    """Reembaralha a ORDEM dos mesmos trades, n vezes.

    O drawdown observado é um sorteio: os mesmos trades em outra ordem dão
    outro fundo. O que interessa não é o que aconteceu, e sim o que estava
    no baralho — se o p95 do drawdown é o dobro do que você viu, é para ele
    que o capital precisa estar preparado.

    O lucro final não muda com a ordem; o que muda é o caminho. Por isso
    aqui só o drawdown e o tempo submerso variam.
    """
    if len(liquido) < 10:
        return {}

    rng = np.random.default_rng(semente)
    quedas = np.empty(n)
    submerso = np.empty(n)
    for i in range(n):
        eq = capital + np.cumsum(rng.permutation(liquido))
        pico = np.maximum.accumulate(np.concatenate(([capital], eq)))
        eqc = np.concatenate(([capital], eq))
        quedas[i] = float((pico - eqc).max())
        submerso[i] = float((eqc < pico).mean() * 100)

    eq_real = capital + np.cumsum(liquido)
    pico_real = np.maximum.accumulate(np.concatenate(([capital], eq_real)))
    dd_real = float((pico_real - np.concatenate(([capital], eq_real))).max())

    p = np.percentile(quedas, [50, 95, 99])
    return {
        "n": n,
        "dd_observado": dd_real,
        "dd_p50": float(p[0]), "dd_p95": float(p[1]), "dd_p99": float(p[2]),
        "dd_max": float(quedas.max()),
        "submerso_p50": float(np.percentile(submerso, 50)),
        # onde o SEU drawdown cai na distribuição: 20% quer dizer que 80%
        # dos reembaralhamentos foram piores - você teve sorte
        "percentil_do_observado": float((quedas < dd_real).mean() * 100),
        "lucro_final": float(liquido.sum()),
    }


def drawdowns(entry_ts: np.ndarray, liquido: np.ndarray, capital: float,
              quantos: int = 5) -> list[dict]:
    """Os maiores mergulhos, com quanto tempo levaram para se recuperar.

    O max drawdown diz quanto se perde. Não diz que você passaria sete meses
    no vermelho esperando voltar — e é isso que faz gente abandonar
    estratégia boa no pior momento possível.
    """
    if not len(liquido):
        return []

    eq = capital + np.cumsum(liquido)
    pico = capital
    inicio = 0
    eventos = []
    fundo_v, fundo_i = None, None

    for i, v in enumerate(eq):
        if v >= pico:
            if fundo_v is not None:
                eventos.append((inicio, fundo_i, i, pico - fundo_v))
                fundo_v, fundo_i = None, None
            pico, inicio = v, i
        elif fundo_v is None or v < fundo_v:
            fundo_v, fundo_i = v, i
    if fundo_v is not None:                       # ainda submerso no fim
        eventos.append((inicio, fundo_i, None, pico - fundo_v))

    eventos.sort(key=lambda e: e[3], reverse=True)
    dias = entry_ts.astype("datetime64[D]")

    out = []
    for ini, fundo, recup, prof in eventos[:quantos]:
        d_ini, d_fundo = dias[min(ini, len(dias) - 1)], dias[fundo]
        d_rec = dias[recup] if recup is not None else None
        out.append({
            "inicio": str(d_ini),
            "fundo": str(d_fundo),
            "recuperacao": str(d_rec) if d_rec is not None else None,
            "profundidade": float(prof),
            "dias_ate_o_fundo": int((d_fundo - d_ini).astype(int)),
            "dias_para_recuperar": (int((d_rec - d_fundo).astype(int))
                                    if d_rec is not None else None),
            "trades": int((recup if recup is not None else len(eq)) - ini),
        })
    return out


# ------------------------------------------------------------ significância
def _p_bicaudal(z: float) -> float:
    """Normal, não t: com centenas de trades a diferença é invisível."""
    return math.erfc(abs(z) / math.sqrt(2))


def significancia(liquido: np.ndarray) -> dict:
    """A expectativa é distinguível de zero, ou é ruído com sorte?

    Também devolve quantos trades faltariam para o resultado atual virar
    conclusivo — que é a resposta útil quando ainda não é.
    """
    n = len(liquido)
    if n < 5:
        return {}
    media = float(liquido.mean())
    desvio = float(liquido.std(ddof=1))
    if desvio == 0:
        return {"n": n, "media": media, "t": float("inf"), "p": 0.0,
                "n_necessario": n}

    t = media / (desvio / math.sqrt(n))
    necessario = int(math.ceil((1.96 * desvio / media) ** 2)) if media else None
    return {
        "n": n, "media": media, "desvio": desvio,
        "t": float(t), "p": float(_p_bicaudal(t)),
        "confianca": float((1 - _p_bicaudal(t)) * 100),
        "n_necessario": necessario,
    }


def teste_runs(liquido: np.ndarray) -> dict:
    """As perdas se agrupam ou se espalham?

    Trades independentes produzem um número previsível de sequências. Menos
    sequências que o esperado significa perdas em bloco — e drawdown pior do
    que qualquer conta feita supondo independência. É o caso em que o stop
    diário deixa de ser paranoia.
    """
    sinais = liquido > 0
    n = len(sinais)
    n1 = int(sinais.sum())
    n2 = n - n1
    if n1 < 2 or n2 < 2:
        return {}

    corridas = 1 + int((sinais[1:] != sinais[:-1]).sum())
    esperado = 2 * n1 * n2 / n + 1
    var = (2 * n1 * n2 * (2 * n1 * n2 - n)) / (n * n * (n - 1))
    if var <= 0:
        return {}
    z = (corridas - esperado) / math.sqrt(var)
    return {
        "corridas": corridas, "esperado": float(esperado), "z": float(z),
        "p": float(_p_bicaudal(z)),
        "agrupadas": bool(z < -1.96),      # menos corridas = blocos
        "alternadas": bool(z > 1.96),
    }


def correlacao_lr(liquido: np.ndarray, capital: float) -> dict:
    """Quão reta é a curva de capital — a mesma leitura do MT5.

    Correlação perto de 1 é subida constante. Curva que sobe num degrau e
    fica de lado tem correlação baixa mesmo lucrando: o lucro veio de um
    período, não do método.
    """
    n = len(liquido)
    if n < 3:
        return {}
    eq = capital + np.cumsum(liquido)
    x = np.arange(n, dtype=float)
    r = float(np.corrcoef(x, eq)[0, 1])
    a, b = np.polyfit(x, eq, 1)
    residuo = eq - (a * x + b)
    return {"correlacao": r, "erro_padrao": float(residuo.std(ddof=2)),
            "inclinacao": float(a)}


# ------------------------------------------------------------- fragilidade
def concentracao(liquido: np.ndarray, cortes=(5, 10, 20)) -> dict:
    """O lucro vem de muitos trades ou de cinco bilhetes premiados?

    Tirar os melhores é o teste de fragilidade mais barato que existe: se a
    estratégia vira prejuízo sem os cinco maiores ganhos, ela não é um
    sistema — é um acidente feliz que não se repete.
    """
    if not len(liquido):
        return {}
    total = float(liquido.sum())
    ordenado = np.sort(liquido)[::-1]
    sem = {}
    for k in cortes:
        if k < len(ordenado):
            sem[k] = float(total - ordenado[:k].sum())
    maior = float(ordenado[0])
    return {
        "total": total, "sem": sem, "maior_trade": maior,
        "peso_do_maior": float(maior / total * 100) if total > 0 else None,
        "sobrevive_sem_5": bool(sem.get(5, total) > 0),
    }


def ulcer_mar(liquido: np.ndarray, capital: float, dias_corridos: int) -> dict:
    """Dois números para RANQUEAR candidatos entre si.

    Ulcer Index junta profundidade e duração do drawdown: dois sistemas com
    o mesmo max DD, um que afunda e volta e outro que fica meses no fundo,
    têm Ulcer bem diferente. MAR é retorno anualizado sobre max DD, o padrão
    da indústria para ordenar sistemas.
    """
    if not len(liquido) or capital <= 0:
        return {}
    # o capital inicial entra como primeiro ponto: sem ele o pico comeca
    # DEPOIS do primeiro trade, e uma estrategia que abre perdendo tem
    # drawdown zero - o mergulho inicial fica invisivel
    eq = np.concatenate(([capital], capital + np.cumsum(liquido)))
    pico = np.maximum.accumulate(eq)
    queda_pct = (eq - pico) / pico * 100
    ulcer = float(np.sqrt((queda_pct ** 2).mean()))

    max_dd = float((pico - eq).max())
    max_dd_pct = float((-queda_pct).max())

    anos = max(dias_corridos / 365.25, 1e-9)
    final = float(eq[-1])
    cagr = ((final / capital) ** (1 / anos) - 1) * 100 if final > 0 else -100.0
    return {
        "ulcer": ulcer,
        "max_dd": max_dd, "max_dd_pct": max_dd_pct,
        "cagr": float(cagr), "anos": float(anos),
        "mar": float(cagr / max_dd_pct) if max_dd_pct > 0 else None,
    }


def meses_positivos(entry_ts: np.ndarray, liquido: np.ndarray) -> dict:
    """Quantos meses fecham no azul, e o pior período seguido de vermelho.

    A mesma taxa de meses positivos com dois ou com sete meses ruins
    seguidos são estratégias diferentes na prática: uma você opera, a outra
    você abandona no meio.
    """
    if not len(liquido):
        return {}
    meses = entry_ts.astype("datetime64[M]")
    unicos, inv = np.unique(meses, return_inverse=True)
    soma = np.zeros(len(unicos))
    np.add.at(soma, inv, liquido)

    positivos = int((soma > 0).sum())
    pior, atual = 0, 0
    for v in soma:
        atual = atual + 1 if v <= 0 else 0
        pior = max(pior, atual)
    return {
        "meses": len(unicos), "positivos": positivos,
        "pct": float(positivos / len(unicos) * 100),
        "pior_sequencia": pior,
        "melhor": float(soma.max()), "pior": float(soma.min()),
    }


def custo_que_zera(lucro_bruto: float, contratos: np.ndarray,
                   custo_atual_por_contrato: float) -> dict:
    """Quanta corretagem a estratégia aguenta antes de empatar.

    Custo é cobrado por contrato e por ponta. Se a estratégia morre com
    R$ 1,20 e você paga R$ 0,77, a margem é fina — e vale saber antes de
    trocar de corretora ou aumentar o lote.
    """
    pontas = float(np.sum(contratos) * 2)
    if pontas <= 0:
        return {}
    limite = lucro_bruto / pontas
    return {
        "limite_por_contrato": float(limite),
        "atual_por_contrato": float(custo_atual_por_contrato),
        "folga": float(limite - custo_atual_por_contrato),
        "folga_pct": (float((limite / custo_atual_por_contrato - 1) * 100)
                      if custo_atual_por_contrato > 0 else None),
        "pontas": pontas,
    }
