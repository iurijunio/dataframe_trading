"""Entrada aleatória: o mérito é do sinal ou da gestão de saída?

A camada 2 diz que uma estratégia devolve APENAS sinais — stop, alvo,
horário, custo e limites do dia são do kernel. Então este teste é uma
estratégia falsa que sorteia as barras de entrada e herda toda a gestão da
real, sem tocar no motor.

Duas decisões que fazem a comparação ser honesta (ver PLANO-CANDIDATA §6.1):
o sorteio é estratificado pelo histograma de horário das entradas reais, e o
número de sinais é calibrado até o número de TRADES bater — porque sinal não
vira trade quando já há posição aberta ou o limite do dia bloqueou.
"""

from __future__ import annotations

import numpy as np

from strategies.base import Signals


class EntradaAleatoria:
    name = "entrada_aleatoria"
    params_schema: dict = {}

    def __init__(self, n_sinais: int, horarios: dict | None,
                 p_compra: float, semente: int):
        self.n_sinais = int(n_sinais)
        self.horarios = self._normalizar_horarios(horarios)
        self.p_compra = float(p_compra)
        self.semente = int(semente)

    @staticmethod
    def _normalizar_horarios(horarios: dict | None) -> dict | None:
        """Aceita peso como fração OU como contagem bruta do histograma real
        (ex.: "40 entradas às 9h, 60 às 10h") — normalizar pela soma evita
        que quem chama tenha que fazer a conta, e sem isso um dict de
        contagens (que não soma 1) sortearia milhares de sinais em vez de
        `n_sinais`."""
        if not horarios:
            return None
        if any(p < 0 for p in horarios.values()):
            raise ValueError(
                "horarios: peso negativo não faz sentido — pesos são "
                "fração (ou contagem) de sinais, nunca negativos."
            )
        soma = sum(horarios.values())
        if soma <= 0:
            raise ValueError(
                "horarios: soma dos pesos é zero; não há como distribuir "
                "nenhum sinal entre as horas pedidas."
            )
        return {h: p / soma for h, p in horarios.items()}

    def signals(self, bars: dict, params: dict) -> Signals:
        n = len(bars["close"])
        rng = np.random.default_rng(self.semente)

        if self.horarios:
            # `bars["ts"]` é o RÓTULO da barra do timeframe da estratégia —
            # `execution.resample` carimba com o FIM do período (uma M15
            # fecha aos 14/29/44/59 do minuto). O kernel só abre posição na
            # barra M1 SEGUINTE ao sinal (kernel.py, "sinais desta barra,
            # para a próxima"), então uma barra rotulada 09:59 entra às
            # 10:00. Estratificar pelo rótulo estratificaria pela hora
            # ERRADA sempre que o rótulo cair no último minuto da hora — e
            # em H1 isso desloca o histograma inteiro em uma hora. O
            # histograma real (`entry_ts`) mede a hora de EXECUÇÃO, não a
            # do rótulo, então é isso que tem que bater aqui.
            execucao = bars["ts"] + np.timedelta64(1, "m")
            horas = execucao.astype("datetime64[h]").astype(object)
            horas = np.array([h.hour for h in horas])
            idx = self._sorteio_estratificado(horas, rng)
        else:
            idx = rng.choice(n, size=min(self.n_sinais, n), replace=False)

        compra = rng.random(len(idx)) < self.p_compra
        el = np.zeros(n, dtype=np.bool_)
        es = np.zeros(n, dtype=np.bool_)
        el[idx[compra]] = True
        es[idx[~compra]] = True
        return Signals(entry_long=el, entry_short=es,
                       exit_long=np.zeros(n, dtype=np.bool_),
                       exit_short=np.zeros(n, dtype=np.bool_))

    def _sorteio_estratificado(self, horas: np.ndarray, rng: np.random.Generator
                               ) -> np.ndarray:
        """Cota por hora via maior resto (Hamilton), não arredondamento cru.

        `int(round(n_sinais * peso))` somado hora a hora quase nunca fecha
        `n_sinais` (3 horas de peso 1/3 e 10 sinais dão 3+3+3=9) — o maior
        resto dá a cada hora o piso da sua cota e distribui as unidades que
        sobram para quem tem o maior resto fracionário, até a soma bater
        exatamente. Se uma hora não tiver barras candidatas suficientes para
        a cota dela, a cota encolhe e o total sai menor que `n_sinais` — não
        há candidato para inventar, e é `calibrar` quem compensa isso
        pedindo mais sinais na tentativa seguinte.
        """
        horas_pedidas = list(self.horarios)
        brutos = {h: self.n_sinais * self.horarios[h] for h in horas_pedidas}
        cotas = {h: int(np.floor(v)) for h, v in brutos.items()}
        falta = self.n_sinais - sum(cotas.values())
        restos = sorted(horas_pedidas, key=lambda h: brutos[h] - cotas[h],
                        reverse=True)
        for h in restos[:falta]:
            cotas[h] += 1

        escolhidas = []
        for h in horas_pedidas:
            cand = np.flatnonzero(horas == h)
            quantas = min(cotas[h], len(cand))
            if quantas > 0:
                escolhidas.append(rng.choice(cand, size=quantas, replace=False))
        return np.concatenate(escolhidas) if escolhidas else np.array([], dtype=int)


def calibrar(rodar, alvo_trades: int, tentativas: int = 8,
             tolerancia: float = 0.05) -> int:
    """Quantos sinais sortear para sair o número de trades da estratégia real.

    Busca por bisseção: `rodar(n)` devolve quantos trades saíram com n
    sinais. Sem isto, o sorteio opera menos (ou mais) que a real e a
    comparação vira teste de frequência, não de sinal.

    O `for` é limitado a `tentativas` de propósito: uma real tão ativa que
    nem 4x o alvo em sinais entrega o número de trades pedido (o motor
    satura, por exemplo pelo limite diário) nunca vai convergir — a função
    tem que devolver o melhor `n` já visto em vez de girar sem parar.

    A assinatura continua `int` mesmo nesse caso de não convergência — não
    há um segundo valor de retorno avisando "não bati o alvo". Por isso:
    QUEM CHAMA `calibrar` TEM QUE CONFERIR o número de trades que `n`
    produziu contra `alvo_trades` antes de usar o sorteio na comparação. Um
    `n` que fica muito aquém do alvo silenciosamente faz o aleatório operar
    menos que a real, o que empurra a comparação a favor da real por um
    motivo que não é o sinal.
    """
    baixo, alto = alvo_trades, max(alvo_trades * 4, alvo_trades + 10)
    melhor, erro_melhor = alto, float("inf")
    for _ in range(tentativas):
        meio = (baixo + alto) // 2
        saiu = rodar(meio)
        erro = abs(saiu - alvo_trades)
        if erro < erro_melhor:
            melhor, erro_melhor = meio, erro
        if erro <= alvo_trades * tolerancia:
            return meio
        if saiu < alvo_trades:
            baixo = meio
        else:
            alto = meio
    return melhor


def p_valor(real: float, sorteados: np.ndarray) -> float:
    """P-valor de permutação: (1 + quantos batem o real) / (1 + B).

    O percentil empírico cru daria zero quando nenhum sorteio bate o real —
    e "probabilidade zero" não é uma conclusão que B sorteios sustentam.

    Não-finito é tratado sempre do lado que NÃO favorece a aprovação: um
    REAL não finito (métrica indefinida, ex.: Sharpe com desvio zero) não
    prova mérito nenhum e devolve o pior p-valor (1.0), nunca o melhor. Um
    SORTEIO não finito (aquela repetição quebrou) conta como se tivesse
    BATIDO o real — do contrário, sorteios que falharam desapareceriam da
    contagem e inflariam a aparência de significância artificialmente.
    """
    if not np.isfinite(real):
        return 1.0
    s = np.asarray(sorteados, dtype=float)
    bate = ~np.isfinite(s) | (s >= real)
    return float((1 + int(bate.sum())) / (1 + len(s)))
