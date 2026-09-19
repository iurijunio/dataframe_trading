"""Reversão à média pelo RSI curto — o setup de Larry Connors.

Terceira estratégia do projeto, e a primeira de PERFIL OPOSTO às duas
primeiras. O cruzamento de médias e o rompimento de canal ganham pouco
muitas vezes e perdem muito de vez em quando? Não: é o contrário. Eles são
setups de tendência, que erram bastante e acertam grande. Este aqui acerta
muito e erra grande — e é por isso que ele existe aqui: para a plataforma
ser testada nos dois perfis.

A ideia: mesmo um mercado que sobe passa por quedas curtas de realização.
Comprar essas quedas, dentro de uma tendência de alta, acerta com muita
frequência. Connors mede acerto acima de 70% em ações.

**O preço disso está na cauda.** Alvo curto com stop largo significa que a
taxa de acerto alta não é mérito: sem vantagem nenhuma, acertar é
`stop ÷ (stop + alvo)` por pura geometria. Com alvo de 100 e stop de 300,
acerta-se 75% das vezes sem estratégia alguma — e empata-se. É por isso que
esta estratégia é a que mais precisa dos testes da tela Candidata: a
dependência de poucos dias, o dia ruim de execução e a sequência de perdas
seguidas medem exatamente o que a taxa de acerto esconde.

Como toda estratégia daqui, ela não sabe o que é stop, alvo, horário, custo
ou tamanho de posição. O alvo mais curto que o stop — a característica que
motivou trazê-la — é configuração da camada 4, e é isso que permite à
mineração varrer essa razão em vez de recebê-la pronta.

Fontes: Larry Connors e Cesar Alvarez, "Short Term Trading Strategies That
Work"; as regras e o resultado medido estão resumidos em
https://www.quantifiedstrategies.com/rsi-2-strategy/ e a adaptação
intradiária em https://www.mql5.com/en/articles/17636.
"""

from __future__ import annotations

import numpy as np

from .base import Signals

name = "reversao_rsi"
label = "Reversão à média (RSI curto)"

params_schema = {
    # min/max sao limites DUROS: a mineracao recorta a faixa da tela para
    # caber aqui. Se quiser varrer alem, e este numero que muda.
    "periodo_rsi": {"label": "Período do RSI", "default": 2,
                    "min": 2, "max": 30, "step": 1, "tipo": "int"},
    "limite_extremo": {"label": "Extremo do RSI (compra abaixo / venda acima "
                                "do espelho)", "default": 10,
                       "min": 1, "max": 45, "step": 1, "tipo": "int"},
    "periodo_tendencia": {"label": "Filtro de tendência (0 desliga)",
                          "default": 200, "min": 0, "max": 600, "step": 10,
                          "tipo": "int"},
    "periodo_saida": {"label": "Média curta de saída", "default": 5,
                      "min": 2, "max": 60, "step": 1, "tipo": "int"},
}


def _media(x: np.ndarray, periodo: int) -> np.ndarray:
    """Média simples. As primeiras `periodo-1` posições ficam indefinidas —
    é o que impede sinal com janela incompleta."""
    out = np.full(len(x), np.nan)
    if periodo <= 0 or len(x) < periodo:
        return out
    soma = np.cumsum(np.insert(np.asarray(x, dtype=np.float64), 0, 0.0))
    out[periodo - 1:] = (soma[periodo:] - soma[:-periodo]) / periodo
    return out


def rsi(close: np.ndarray, periodo: int) -> np.ndarray:
    """O RSI: quanto das últimas `periodo` barras foi de alta, em escala de
    0 a 100. Perto de 0 é queda seguida; perto de 100, alta seguida.

    Usa média SIMPLES das altas e das baixas (a variante de Cutler), não a
    exponencial de Wilder. Com período 2 — que é o caso de Connors, e o
    padrão daqui — as duas praticamente coincidem, e a simples é uma conta
    vetorizada: a mineração roda milhares de combinações, e uma recursão em
    Python por combinação custaria mais que o resto do backtest somado.

    Mercado parado (nenhuma alta e nenhuma baixa na janela) vale 50: não é
    nem sobrecomprado nem sobrevendido. Só altas vale 100, e a divisão por
    zero que isso produziria é tratada em vez de virar `inf`.
    """
    n = len(close)
    out = np.full(n, np.nan)
    if periodo < 1 or n <= periodo:
        return out
    delta = np.diff(np.asarray(close, dtype=np.float64))
    altas = _media(np.maximum(delta, 0.0), periodo)
    baixas = _media(np.maximum(-delta, 0.0), periodo)
    soma = altas + baixas
    with np.errstate(invalid="ignore", divide="ignore"):
        valor = np.where(soma > 0, 100.0 * altas / soma, 50.0)
    # `delta` tem uma posição a menos que `close`: o RSI da barra i usa as
    # diferenças ATÉ ela, nunca a seguinte
    out[1:] = np.where(np.isnan(altas), np.nan, valor)
    return out


def signals(bars: dict, params: dict) -> Signals:
    periodo = int(params["periodo_rsi"])
    limite = float(params["limite_extremo"])
    tendencia = int(params["periodo_tendencia"])
    saida = int(params["periodo_saida"])

    close = np.asarray(bars["close"])
    r = rsi(close, periodo)
    curta = _media(close, saida)

    # o espelho do limite: comprar abaixo de 10 e vender acima de 90 é a
    # mesma régua dos dois lados, e poupa um parâmetro na mineração — cada
    # parâmetro a mais multiplica o tamanho da varredura
    baixo = r <= limite
    alto = r >= (100.0 - limite)

    if tendencia > 0:
        longa = _media(close, tendencia)
        de_alta = close > longa
        de_baixa = close < longa
    else:
        # filtro desligado: opera os dois lados sempre. Serve para MEDIR o
        # quanto o filtro vale, em vez de supor que vale
        de_alta = np.ones(len(close), dtype=bool)
        de_baixa = np.ones(len(close), dtype=bool)

    def primeiro(sinal):
        """Só a primeira barra do extremo conta.

        Enquanto o RSI segue lá embaixo não é uma queda nova — é a mesma. Sem
        isto, cada barra do mesmo mergulho vira uma entrada assim que a
        anterior fecha, e o número de operações (e de custo) explode sem que
        exista sinal novo nenhum. É a mesma regra do rompimento de canal.
        """
        anterior = np.roll(sinal, 1)
        anterior[0] = False
        return sinal & ~anterior

    entrada_compra = primeiro(np.nan_to_num(baixo, nan=False) & de_alta)
    entrada_venda = primeiro(np.nan_to_num(alto, nan=False) & de_baixa)

    # A saída de Connors não é alvo em pontos: é o preço voltar para cima da
    # média curta, o que fecha rápido e com ganho pequeno. O alvo e o stop
    # em pontos continuam valendo por cima disso — quem chegar primeiro
    # encerra —, e é essa combinação que produz o perfil de alvo curto com
    # stop largo.
    volta_de_alta = np.nan_to_num(close > curta, nan=False)
    volta_de_baixa = np.nan_to_num(close < curta, nan=False)

    return Signals(
        entry_long=entrada_compra,
        entry_short=entrada_venda,
        exit_long=volta_de_alta,
        exit_short=volta_de_baixa,
    )
