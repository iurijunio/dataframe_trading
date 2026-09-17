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
from . import metrics
from .engine.execution import TIMEFRAMES, run_strategy


class EntradaAleatoria:
    name = "entrada_aleatoria"
    params_schema: dict = {}

    def __init__(self, n_sinais: int, horarios: dict | None,
                 p_compra: float, semente: int,
                 janela_valida: tuple[np.datetime64, np.datetime64] | None = None):
        self.n_sinais = int(n_sinais)
        self.horarios = self._normalizar_horarios(horarios)
        self.p_compra = float(p_compra)
        self.semente = int(semente)
        # (de, ate): quando dado, só sorteia (e portanto só abre trade) em
        # barras cuja EXECUÇÃO cai em [de, ate) — é o que permite fatiar com
        # uma margem de aquecimento de indicador ANTES da janela OOS sem que
        # o sorteio vaze entradas para dentro dessa margem (ver
        # `rodador_do_motor`, correção da rodada 1).
        self.janela_valida = janela_valida

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

        # `bars["ts"]` é o RÓTULO da barra do timeframe da estratégia —
        # `execution.resample` carimba com o FIM do período (uma M15 fecha
        # aos 14/29/44/59 do minuto). O kernel só abre posição na barra M1
        # SEGUINTE ao sinal (kernel.py, "sinais desta barra, para a
        # próxima"), então uma barra rotulada 09:59 entra às 10:00. É essa
        # hora de EXECUÇÃO — não a do rótulo — que estratifica o histograma
        # E que decide se a barra cai dentro de `janela_valida`.
        execucao = bars["ts"] + np.timedelta64(1, "m")

        if self.janela_valida is not None:
            de, ate = self.janela_valida
            valido = (execucao >= de) & (execucao < ate)
        else:
            valido = np.ones(n, dtype=np.bool_)

        if self.horarios:
            horas = execucao.astype("datetime64[h]").astype(object)
            horas = np.array([h.hour for h in horas])
            idx = self._sorteio_estratificado(horas, valido, rng)
        else:
            universo = np.flatnonzero(valido)
            idx = rng.choice(universo, size=min(self.n_sinais, len(universo)),
                             replace=False)

        compra = rng.random(len(idx)) < self.p_compra
        el = np.zeros(n, dtype=np.bool_)
        es = np.zeros(n, dtype=np.bool_)
        el[idx[compra]] = True
        es[idx[~compra]] = True
        return Signals(entry_long=el, entry_short=es,
                       exit_long=np.zeros(n, dtype=np.bool_),
                       exit_short=np.zeros(n, dtype=np.bool_))

    def _sorteio_estratificado(self, horas: np.ndarray, valido: np.ndarray,
                               rng: np.random.Generator) -> np.ndarray:
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
            cand = np.flatnonzero((horas == h) & valido)
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


def teste_janelas(rodar_janela, janelas, alvos, lucro_real: float,
                  n: int = 1000, semente: int = 7, progresso=None,
                  parar=None) -> dict:
    """Portão 3, janela a janela: a curva OOS real bate o sorteio?

    `rodar_janela(janela, n_sinais, semente) -> (n_trades, lucro)` é
    injetado — em produção é `rodador_do_motor(...)` ligando ao motor de
    verdade; nos testes, uma função falsa.

    A calibração roda UMA VEZ por janela, com a `semente` fixa recebida
    aqui — nunca dentro do laço de repetições. Calibrar a cada repetição
    trocaria (tentativas + repetições) chamadas ao motor por (tentativas x
    repetições), e é exatamente essa multiplicação que estoura o tempo
    disponível (ver decisão 1 do brief da tarefa 5).

    Cada repetição soma o lucro sorteado de TODAS as janelas antes de
    comparar com `lucro_real` — a curva OOS real também é a soma das
    janelas, não uma janela isolada. Repetições usam sementes
    `semente + 1, semente + 2, ...`, nunca a `semente` da calibração, para
    não confundir uma chamada de calibração com uma chamada de repetição.
    """
    if len(janelas) != len(alvos):
        raise ValueError(
            "janelas e alvos precisam ter o mesmo tamanho — um alvo de "
            "trades por janela."
        )

    sinais_por_janela: list[int] = []
    trades_obtidos: list[int] = []
    for janela, alvo in zip(janelas, alvos):
        vistos: dict[int, tuple[int, float]] = {}

        def rodar(n_sinais: int, janela=janela, vistos=vistos) -> int:
            resultado = rodar_janela(janela, n_sinais, semente)
            vistos[n_sinais] = resultado
            return resultado[0]

        n_sinais = calibrar(rodar, alvo)
        if n_sinais in vistos:
            n_trades = vistos[n_sinais][0]
        else:
            # só acontece com `tentativas` fora do padrão de `calibrar` — o
            # `n` devolvido não foi necessariamente testado; confere de novo
            # em vez de assumir um valor que nunca foi visto.
            n_trades, _ = rodar_janela(janela, n_sinais, semente)
        sinais_por_janela.append(int(n_sinais))
        trades_obtidos.append(int(n_trades))

    tolerancia = 0.05
    calibracao_ok = all(
        abs(t - a) <= a * tolerancia for t, a in zip(trades_obtidos, alvos)
    )

    sorteados = np.empty(n, dtype=float)
    for rep in range(n):
        if parar is not None and parar():
            return {}
        semente_rep = semente + 1 + rep
        soma = 0.0
        for janela, n_sig in zip(janelas, sinais_por_janela):
            _, lucro = rodar_janela(janela, n_sig, semente_rep)
            soma += lucro
        sorteados[rep] = soma
        if progresso is not None:
            progresso(rep + 1, n)

    return {
        "p": p_valor(lucro_real, sorteados),
        "sorteados": sorteados,
        "lucro_real": lucro_real,
        "sinais_por_janela": sinais_por_janela,
        "trades_obtidos": trades_obtidos,
        "alvos": list(alvos),
        "calibracao_ok": calibracao_ok,
    }


def _histograma_horario_execucao(trades: list[dict]) -> dict[int, int] | None:
    """Conta as entradas reais por hora de EXECUÇÃO.

    `entry_ts` de um trade real já É a hora de execução (ao contrário do
    rótulo de barra, que `EntradaAleatoria` corrige internamente somando 1
    minuto) — aqui não há correção nenhuma para fazer, só contar.

    Sem trades reais não há histograma para estratificar: `None` volta pro
    sorteio uniforme de `EntradaAleatoria` em vez de quebrar por falta de
    dado (janela sem trade real não deveria chegar aqui, mas não é motivo
    para propagar exceção numa varredura de 1.000 repetições).
    """
    if not trades:
        return None
    contagem: dict[int, int] = {}
    for t in trades:
        hora = int(np.datetime64(t["entry_ts"]).astype("datetime64[h]")
                  .astype(object).hour)
        contagem[hora] = contagem.get(hora, 0) + 1
    return contagem


def _proporcao_compra(trades: list[dict]) -> float:
    """Fração de compra (`side == +1`) nas entradas reais da janela.

    Sem trades reais, 50/50 — não há proporção real para herdar, e não é
    motivo para quebrar (ver `_histograma_horario_execucao`).
    """
    if not trades:
        return 0.5
    compras = sum(1 for t in trades if t["side"] > 0)
    return compras / len(trades)


# Piso da margem de aquecimento do ATR: pelo menos um pregão inteiro (24h em
# barras M1), mesmo quando `periodo_atr x timeframe x 3` dá um número menor —
# um piso curto demais deixaria o ATR de janelas com timeframe pequeno
# aquecer com poucas barras de verdade (ver correção 1, rodada 1).
PISO_MARGEM_ATR_M1 = 1440


def rodador_do_motor(bars: dict, estrategia_real, perfil, instrumento: dict,
                     trades_reais: list[dict]):
    """Liga `EntradaAleatoria` ao motor de verdade para UMA janela do WFA.

    Devolve uma função no formato que `teste_janelas` espera de
    `rodar_janela`: `(janela, n_sinais, semente) -> (n_trades, lucro)`.

    `bars` é o histórico INTEIRO — carregado uma vez só por quem chama, e
    reusado ao montar o `rodador_do_motor` de cada janela do walk-forward
    (ver decisão 1 do brief da tarefa 5: ler o Parquet ou rodar o motor
    sobre 1,2 milhão de barras em cada uma das milhares de chamadas não cabe
    no tempo). Cada chamada de `rodar_janela` fatia `bars` por índice
    (`np.searchsorted` em `ts`, O(log n) e sem cópia de dado fora da fatia)
    e roda o motor só sobre essa fatia pequena.

    MARGEM DE AQUECIMENTO DO ATR (correção 1, rodada 1). A fatia não começa
    exatamente em `janela.oos_de`: quando o perfil usa stop ou alvo por ATR,
    as primeiras barras de uma fatia que começasse ali teriam ATR ainda não
    aquecido (`execution.atr` só produz valor depois de `periodo` barras), e
    ATR não aquecido vira 0 — 0 significa "sem stop e sem alvo" em
    `execution._nivel`, uma gestão que a estratégia REAL nunca operou com.
    A fatia então começa `periodo_atr x barras_do_timeframe x 3` barras M1
    antes de `oos_de` (arredondado para trás até a meia-noite do dia, para
    o `resample` de qualquer timeframe fechar grupos inteiros exatamente
    como fecharia no histórico completo), com piso de `PISO_MARGEM_ATR_M1`
    (um pregão inteiro). `execution.atr` é média móvel SIMPLES — uma vez
    aquecido, o valor em cada barra só depende das `periodo` barras
    anteriores a ela, nunca de barras mais antigas — então essa margem
    reproduz EXATAMENTE o ATR que o histórico completo daria a partir de
    `oos_de`, não uma aproximação. Perfil só em pontos (`stop_tipo` e
    `alvo_tipo` != "atr") não precisa de margem nenhuma: pontos fixos não
    aquecem.

    A margem é só para o INDICADOR aquecer: o sorteio em si (`EntradaAleatoria
    .janela_valida`) só abre entrada com EXECUÇÃO dentro de
    `[janela.oos_de, janela.oos_ate)`, e os trades contados/somados aqui são
    filtrados pela mesma regra — a margem nunca contribui um trade.

    CONFERE A JANELA (correção 2, rodada 1; aperto na rodada 2). Este
    `rodar_janela` foi montado com o perfil e os `trades_reais` de UMA
    janela (o `step` deles). Chamá-lo com o `janela` de outro step aplicaria
    o perfil e o histograma ERRADOS sem aviso nenhum — por isso
    `rodar_janela` primeiro confere `janela.step` contra o step de
    `trades_reais` e recusa com `ValueError` se não bater. Essa checagem só
    protege de verdade se o campo existir: `trades_reais` sem `step` em
    algum trade é recusado já na MONTAGEM (não em silêncio, assumindo "sem
    step para conferir") — `wfa_store.trades(wfa_id)` sempre grava o step,
    então a ausência dele indica que quem chamou não filtrou os dados
    direito.

    `estrategia_real` não entra na chamada a `run_strategy`: quem gera o
    sinal aqui é sempre `EntradaAleatoria`, nunca a estratégia real. O
    parâmetro fica na assinatura para quem chama poder registrar contra
    qual estratégia real este sorteio está competindo (ex.: mensagem de
    erro, log) — não é usado para gerar sinal nem gestão.

    O histograma de hora de execução e a proporção compra/venda vêm dos
    `trades_reais` DAQUELA janela (campo `entry_ts` e `side`, como devolve
    `wfa_store.trades(wfa_id)` filtrado pelo `step`) e são calculados uma
    vez só, na montagem — não a cada chamada de `rodar_janela`.
    """
    horarios = _histograma_horario_execucao(trades_reais)
    p_compra = _proporcao_compra(trades_reais)

    sem_step = [t for t in trades_reais if "step" not in t]
    if sem_step:
        raise ValueError(
            f"{len(sem_step)} trade(s) real(is) sem o campo 'step' — "
            "trades_reais precisa vir de wfa_store.trades(wfa_id), que "
            "sempre grava o step. Sem ele, rodar_janela não tem como "
            "conferir se recebeu a janela certa (correção 2, rodada 1)."
        )
    steps = {t["step"] for t in trades_reais}
    if len(steps) > 1:
        raise ValueError(
            f"trades_reais mistura mais de um step ({sorted(steps)}) — "
            "rodador_do_motor serve UMA janela; filtre por step antes de "
            "montar."
        )
    step_esperado = next(iter(steps), None)

    periodo_atr = 0
    if perfil.stop_tipo == "atr":
        periodo_atr = max(periodo_atr, int(perfil.stop_atr_periodo))
    if perfil.alvo_tipo == "atr":
        periodo_atr = max(periodo_atr, int(perfil.alvo_atr_periodo))
    minutos_tf = TIMEFRAMES.get(perfil.timeframe, 1)
    margem_m1 = (max(periodo_atr * minutos_tf * 3, PISO_MARGEM_ATR_M1)
                if periodo_atr > 0 else 0)

    def rodar_janela(janela, n_sinais: int, semente: int) -> tuple[int, float]:
        if step_esperado is not None and janela.step != step_esperado:
            raise ValueError(
                f"rodador_do_motor foi montado com os trades reais do step "
                f"{step_esperado!r}, mas recebeu a janela do step "
                f"{janela.step!r} — cada rodador serve UMA janela só; "
                "monte um rodador por janela e despache pelo próprio "
                "objeto `janela`, não reuse este para outra."
            )

        ts = bars["ts"]
        de = np.datetime64(janela.oos_de).astype(ts.dtype)
        ate = np.datetime64(janela.oos_ate).astype(ts.dtype)

        if margem_m1:
            de_com_margem = de - np.timedelta64(int(margem_m1), "m")
            # trunca pro início do dia: garante que o `resample` desta
            # fatia fecha os mesmos grupos de timeframe que o histórico
            # completo fecharia a partir daí — cortar no MEIO de um grupo
            # deixaria esse grupo com open/high/low incompletos, e o ATR
            # dele (e dos `periodo_atr` seguintes) sairia diferente do
            # histórico completo.
            de_com_margem = de_com_margem.astype("datetime64[D]").astype(ts.dtype)
        else:
            de_com_margem = de

        i0 = int(np.searchsorted(ts, de_com_margem))
        i1 = int(np.searchsorted(ts, ate))
        barras_janela = {k: v[i0:i1] for k, v in bars.items()}

        estrategia = EntradaAleatoria(n_sinais, horarios, p_compra, semente,
                                      janela_valida=(de, ate))
        res = run_strategy(barras_janela, estrategia, {}, perfil, instrumento)
        if res.n_trades == 0:
            return 0, 0.0

        dentro = (res.trades["entry_ts"] >= de) & (res.trades["entry_ts"] < ate)
        if not np.any(dentro):
            return 0, 0.0
        liquido = metrics.monetize(res)["liquido"][dentro]
        return int(dentro.sum()), float(liquido.sum())

    return rodar_janela
