"""Walk-forward: separar o que a combinacao viu do que ela nao viu.

Optuna varrendo cinco anos de M1 encontra ruido com precisao cirurgica. Uma
curva de capital linda que descreve o passado nao vale nada; o que interessa
e o que sobra FORA da amostra. Por isso nenhuma linha da tabela de mineracao
nasce sem metrica dentro e fora lado a lado.

Como funciona aqui:

  |---- treino 12m ----|- teste 3m -|
            |---- treino 12m ----|- teste 3m -|
                      |---- treino 12m ----|- teste 3m -|
                                    ... passo de 3 meses ...
  [--------------- otimizacao ---------------][--- holdout lacrado ---]

Uma escolha que vale explicar: cada combinacao roda UMA vez sobre o periodo
inteiro, e os trades sao depois repartidos entre as janelas de treino e de
teste. Nao e atalho - e mais correto. Rodar cada fold isolado zeraria o
aquecimento dos indicadores no inicio de cada janela, coisa que nao acontece
ao vivo, onde a media movel de hoje conhece o mes passado.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MESES = np.timedelta64(30, "D")


@dataclass(frozen=True)
class Fold:
    treino_de: np.datetime64
    treino_ate: np.datetime64
    teste_de: np.datetime64
    teste_ate: np.datetime64


@dataclass
class Janelas:
    folds: list[Fold]
    holdout_de: np.datetime64 | None
    fim_otimizacao: np.datetime64


def montar_janelas(inicio, fim, treino_meses=12, teste_meses=3,
                   passo_meses=3, holdout_meses=12) -> Janelas:
    """Folds deslizantes, com os ultimos meses lacrados fora de tudo."""
    inicio = np.datetime64(inicio, "s")
    fim = np.datetime64(fim, "s")

    holdout_de = fim - holdout_meses * MESES if holdout_meses else None
    limite = holdout_de if holdout_de is not None else fim

    folds: list[Fold] = []
    treino_de = inicio
    while True:
        treino_ate = treino_de + treino_meses * MESES
        teste_ate = treino_ate + teste_meses * MESES
        if teste_ate > limite:
            break
        folds.append(Fold(treino_de, treino_ate, treino_ate, teste_ate))
        treino_de = treino_de + passo_meses * MESES

    return Janelas(folds, holdout_de, limite)


def _mascara(entradas: np.ndarray, janelas: list[tuple]) -> np.ndarray:
    """Trades cuja ENTRADA cai em alguma das janelas."""
    m = np.zeros(len(entradas), dtype=bool)
    for de, ate in janelas:
        m |= (entradas >= de) & (entradas < ate)
    return m


def resumo(liquido: np.ndarray, capital: float) -> dict:
    """Metricas de uma fatia de trades. Enxuto de proposito: isto roda uma
    vez por combinacao por janela, milhares de vezes."""
    n = len(liquido)
    if n == 0:
        return {"trades": 0, "lucro": 0.0, "profit_factor": 0.0,
                "max_dd": 0.0, "fator_recuperacao": 0.0, "expectativa": 0.0}

    lucro = float(liquido.sum())
    ganhos = float(liquido[liquido > 0].sum())
    perdas = float(-liquido[liquido < 0].sum())

    equity = capital + np.cumsum(liquido)
    pico = np.maximum.accumulate(np.concatenate(([capital], equity)))
    dd = float((np.concatenate(([capital], equity)) - pico).min())
    max_dd = -dd

    return {
        "trades": n,
        "lucro": lucro,
        "profit_factor": (ganhos / perdas) if perdas else (float("inf") if ganhos else 0.0),
        "max_dd": max_dd,
        "fator_recuperacao": (lucro / max_dd) if max_dd else (lucro and float("inf") or 0.0),
        "expectativa": lucro / n,
    }


def avaliar(entry_ts: np.ndarray, liquido: np.ndarray, janelas: Janelas,
            capital: float, min_operacoes: int = 0) -> dict:
    """Avalia uma combinação de parâmetros.

    Uma correção conceitual que vale explicar, porque a versão ingênua deste
    módulo estava errada:

    Aqui os parâmetros são FIXOS - a mesma combinação roda em todos os folds.
    Ninguém reotimiza por janela. Então chamar as janelas de teste de "fora da
    amostra" seria mentira: o otimizador enxerga todas elas igualmente ao
    escolher o vencedor, e as janelas de treino de um fold se sobrepõem às de
    teste do fold anterior. Rotular isso de OOS produziria um número que
    parece validação e não é.

    O que de fato existe aqui são duas coisas diferentes:

      CONSISTÊNCIA - a combinação ganha dinheiro em quantos dos períodos, ou
      só num que puxou a média? É isto que os folds medem, e é o que entra
      no score.

      HOLDOUT - os últimos meses, que nenhuma combinação enxergou. Fica
      calculado mas guardado: exibir o holdout de mil combinações e escolher
      a melhor é destruí-lo. Ele é para uma olhada só, na hora de decidir.
    """
    otim = entry_ts < janelas.fim_otimizacao
    geral = resumo(liquido[otim], capital)

    por_fold = []
    for f in janelas.folds:
        m = (entry_ts >= f.teste_de) & (entry_ts < f.teste_ate)
        por_fold.append(resumo(liquido[m], capital))

    com_trades = [p for p in por_fold if p["trades"] > 0]
    positivos = sum(1 for p in com_trades if p["lucro"] > 0)
    fr = [p["fator_recuperacao"] for p in com_trades if np.isfinite(p["fator_recuperacao"])]
    mediana_fr = float(np.median(fr)) if fr else 0.0
    mediana_lucro = float(np.median([p["lucro"] for p in com_trades])) if com_trades else 0.0

    passa = geral["trades"] >= min_operacoes if min_operacoes else True
    # exige também presença em quase todos os períodos: uma combinação que só
    # opera em 2 de 12 janelas não é estratégia, é coincidência
    if len(com_trades) < max(1, len(por_fold) * 0.6):
        passa = False

    holdout = resumo(liquido[~otim], capital) if janelas.holdout_de is not None else None

    return {
        "geral": geral,
        "folds": {"n": len(por_fold), "com_trades": len(com_trades),
                  "positivos": positivos, "mediana_fr": mediana_fr,
                  "mediana_lucro": mediana_lucro},
        "consistencia": positivos / len(com_trades) if com_trades else 0.0,
        "holdout": holdout,          # guardado, não exibido durante a varredura
        "passa_filtro": passa,
        # mediana entre períodos, não soma: prêmio para quem repete, não para
        # quem acertou uma vez grande
        "score": mediana_fr if passa else float("-inf"),
    }


def score_vizinhanca(trials: list[dict], nomes: list[str]) -> None:
    """Substitui o score de cada ponto pela MEDIANA dos vizinhos na grade.

    Pico isolado cercado de prejuizo e ruido, nao estrategia. Isto e o que
    separa uma regiao robusta de um acidente - e e barato, porque so olha o
    que ja foi calculado. Escreve `score_robusto` em cada trial.
    """
    if not trials:
        return

    eixos = {}
    for nome in nomes:
        eixos[nome] = sorted({t["params"][nome] for t in trials})
    indice = {nome: {v: i for i, v in enumerate(vals)} for nome, vals in eixos.items()}

    por_coord = {}
    for t in trials:
        coord = tuple(indice[n][t["params"][n]] for n in nomes)
        t["_coord"] = coord
        por_coord[coord] = t

    for t in trials:
        vizinhos = [t["score"]]
        for eixo in range(len(nomes)):
            for passo in (-1, 1):
                c = list(t["_coord"])
                c[eixo] += passo
                v = por_coord.get(tuple(c))
                if v is not None:
                    vizinhos.append(v["score"])
        finitos = [s for s in vizinhos if np.isfinite(s)]
        t["score_robusto"] = float(np.median(finitos)) if finitos else float("-inf")
        t.pop("_coord", None)
