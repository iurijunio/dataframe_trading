"""O teste de muitas tentativas: a melhor combinação minerada ainda ganha de
não operar depois de descontar que dezenas foram testadas?

Minerar parâmetros é testar muitas combinações e ficar com a melhor. Mesmo
sem edge nenhum, a melhor de quarenta sorteios de ruído sai positiva só por
sorte de ordenação — é o mesmo viés de seleção do "melhor fundo dos últimos
5 anos". A Superior Predictive Ability de Hansen (2005) mede isso: reamostra
o histórico muitas vezes, cada vez comparando a melhor coluna DAQUELA
reamostragem contra a referência, e o p-valor é a fração das reamostragens
em que o sorteio superou o que se observou de verdade. Sobra pouco espaço
para "a melhor ganhou só porque eram muitas".

Sem scipy de propósito, como o resto de `core/`.
"""

from __future__ import annotations

import math

import numpy as np

from . import robustez

LOTE = 100


def teste(matriz: np.ndarray, n: int = 1000, semente: int = 7,
         bloco: int | None = None) -> dict:
    """SPA de Hansen (2005), versão consistente (studentized, com
    recentragem).

    `matriz` tem uma linha por pregão e uma coluna por candidata (cada
    combinação minerada, mais a curva do walk-forward); a referência é zero
    (não operar). Passo a passo:

    1. `T` pregões, média `d_k` de cada coluna.
    2. `n` reamostragens ESTACIONÁRIAS DAS LINHAS — o mesmo sorteio de
       pregões vale para todas as colunas ao mesmo tempo, porque colunas que
       operam o mesmo mercado andam juntas e é essa correlação que decide
       quanto a melhor de todas se destaca só por sorte. Sortear índices
       diferentes por coluna jogaria fora essa correlação e inflaria o
       p-valor (mais "sorte" aparente do que a de verdade existe entre
       colunas que sobem e descem juntas). Com elas, estima-se o desvio
       `w_k` de `sqrt(T)·média` de cada coluna.
    3. Estatística observada: `max(0, max_k sqrt(T)·d_k / w_k)`.
    4. Recentragem: `g_k = d_k` para quem ainda parece competitiva
       (`sqrt(T)·d_k/w_k ≥ −sqrt(2·log(log(T)))`), senão `g_k = 0`. Sem
       isso, toda coluna claramente ruim entraria nas reamostragens
       centrada na PRÓPRIA média (e não em zero) — competindo pelo máximo
       como se fosse tão boa quanto qualquer outra. Isso INFLA a
       distribuição de referência (o `T*_b` fica maior, não menor) e o
       p-valor sai ALTO demais, escondendo um ganho real atrás de
       concorrência artificial de coluna ruim (a mutação provada em
       `tests/test_spa.py` leva um caso de `p=0.01` a `p=0.99`).
    5. Em cada reamostragem `b`: `Z_k = sqrt(T)·(média*_k − g_k)/w_k`;
       `T*_b = max(0, max_k Z_k)`.
    6. `p = média(T*_b ≥ observada)`.

    Colunas com desvio `w_k = 0` (sem variação nenhuma entre reamostragens,
    caso de uma coluna constante) saem da conta; se não sobrar nenhuma, ou
    se faltar dado para medir (menos de 30 pregões, `n` insuficiente),
    devolve `{"erro": "<motivo>"}` em vez de `{}` — para quem chama saber
    POR QUE, não só que não deu.

    Memória: nunca materializa o array `(n, T, K)` inteiro — os índices
    sorteados são só `(n, T)` (um sorteio de linha, não um valor por
    célula), e as médias reamostradas por coluna são acumuladas em lotes de
    `LOTE` reamostragens de cada vez.
    """
    if bloco is not None and bloco < 1:
        raise ValueError("bloco tem que ser um inteiro >= 1")
    m = np.asarray(matriz, dtype=float)
    if m.ndim != 2 or m.shape[1] < 1:
        return {"erro": "matriz sem colunas para medir"}
    T, K = m.shape
    if T < 30:
        return {"erro": f"menos de 30 pregões para medir ({T})"}
    if n < 2:
        return {"erro": "número de reamostragens insuficiente (n < 2)"}
    d = m.mean(axis=0)
    # um bloco só para a matriz inteira: a reamostragem sorteia LINHAS (o
    # mesmo pregão para todas as colunas), então o comprimento de dependência
    # sai da série que representa o conjunto — a média entre as colunas.
    # `bloco_medio` sozinho arredonda pra 1 com correlação entre dias de até
    # ~0,2 (a fórmula (1+ρ)/(1−ρ) fica abaixo de 1,5 nessa faixa), e bloco 1
    # sorteia dias soltos, subestimando a oscilação da média e deixando o
    # teste aprovar sorte com dependência real (medido pelo revisor: 21,5% a
    # 30,5% de rejeição a 10% com ruído puro dependente, contra a meta de
    # 16%). O piso `T**(1/3)` é a ordem de grandeza recomendada para o
    # tamanho de bloco do bootstrap da média (Politis & Romano); usar o
    # MAIOR dos dois nunca deixa o bloco cair abaixo desse piso.
    if bloco is not None:
        L = int(bloco)
    else:
        L = max(robustez.bloco_medio(m.mean(axis=1)), math.ceil(T ** (1 / 3)))

    rng = np.random.default_rng(semente)
    idx = robustez.indices_estacionarios(T, T, n, L, rng)   # (n, T), não (n, T, K)

    medias = np.empty((n, K))
    for ini in range(0, n, LOTE):
        fim = min(ini + LOTE, n)
        # (lote, T, K) só para este lote — nunca os n de uma vez
        medias[ini:fim] = m[idx[ini:fim]].mean(axis=1)

    raiz_t = math.sqrt(T)
    w = medias.std(axis=0, ddof=1) * raiz_t
    validas = w > 0
    if not validas.any():
        return {"erro": "nenhuma coluna com desvio para medir (todas constantes)"}
    indices_originais = np.flatnonzero(validas)
    d, w, medias = d[validas], w[validas], medias[:, validas]

    razao_obs = raiz_t * d / w
    melhor_local = int(razao_obs.argmax())
    melhor = int(indices_originais[melhor_local])
    estatistica = float(max(0.0, razao_obs.max()))

    limiar = -math.sqrt(2 * math.log(math.log(T)))
    g = np.where(razao_obs >= limiar, d, 0.0)

    z = raiz_t * (medias - g) / w
    t_estrela = np.maximum(0.0, z.max(axis=1))
    p = float((t_estrela >= estatistica).mean())

    return {"p": p, "estatistica": estatistica, "melhor": melhor, "n": n}
