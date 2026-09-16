"""Walk-Forward Analysis, no sentido do Pardo: reotimizando a cada janela.

A diferença para `core/walkforward.py` é a que decide tudo. Lá os parâmetros
são FIXOS em todas as janelas, e o que se mede é **consistência**: esta
combinação funcionou em vários períodos? Aqui a combinação **muda a cada
janela**, escolhida só com o que estava visível até ali, e o que se mede é o
**processo de escolher**. O WFA não valida um número; valida o método.

    montar_janelas   -> a escadinha IS/OOS, rolante ou ancorada
    metricas         -> o que uma fatia de trades vale
    escolher         -> as sete inteligências de seleção
    rodar            -> percorre as janelas e devolve os passos
    agregar          -> a linha da matriz WFM

**Nada aqui roda backtest.** Recebe, por combinação, os arrays de `entry_ts`
e `liquido` de UMA execução sobre o histórico inteiro, e cada janela vira uma
máscara sobre eles. É a mesma técnica que `walkforward.avaliar` usa nos
folds, e é o que torna 135 janelas viáveis: 135 varreduras virariam 675 mil
backtests com um espaço de 5 mil combinações; fatiando, é uma varredura só.

Fatiar é correto, e não uma aproximação:

  - as janelas caem em fronteiras de MÊS e os limites diários (máx.
    trades/dia, stop diário) zeram por pregão — nenhum estado atravessa;
  - o trade pertence à janela da sua ENTRADA, então nada é contado duas vezes;
  - o indicador entra na janela já aquecido, que é o que aconteceria na vida
    real — rodar a janela isolada é que criaria um artefato de warm-up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

DIAS_ANO = 252
MESES_ANO = 12.0

# Pardo: ~120 trades na primeira janela de otimização. Abaixo disto a janela
# roda mesmo assim, mas sai marcada - a decisão foi "roda e marca", não pula.
MIN_TRADES_IS = 120

# Os critérios de aceite que fazem sentido DENTRO de uma janela IS. Ficam de
# fora "janelas positivas" e "mediana por período": dentro de uma única
# janela não existem folds para medir consistência.
CRITERIOS_IS = ("trades", "pf", "fr", "dd", "lucro")

# As doze configurações IS/OOS que o operador roda em lote. Pardo recomenda
# IS de 4 a 6 vezes o OOS e de 10 a 30 janelas; esta lista varre de 2× (IS:6/
# OOS:3) a 4× (IS:24/OOS:6) de propósito — comparar configurações fora da
# faixa recomendada é o que mostra ONDE a recomendação passa a valer.
CONFIGS = [(6, 3), (9, 3), (12, 3), (8, 4), (12, 4), (16, 4),
           (10, 5), (15, 5), (12, 6), (20, 5), (18, 6), (24, 6)]

INTELIGENCIAS = [
    ("Moda (Estabilidade)", "moda"),
    ("Sharpe (Eficiência)", "sharpe"),
    ("Centroid (Platô) Média", "centroide_media"),
    ("Centroid (Platô) Mediana", "centroide_mediana"),
    ("Estabilidade de Drawdown", "ulcer"),
    ("Probabilidade do Alpha", "alpha"),
    ("Platô Pessimista", "vizinhanca"),
    ("Conselho de Notáveis", "conselho"),
]
# as que votam no Conselho — ele próprio fora, para não votar em si
VOTANTES = [c for _, c in INTELIGENCIAS if c != "conselho"]

# Como fator de recuperação e drawdown escalam com o tamanho da janela (ver
# `criterios_por_janela`). FR = lucro ÷ DD: lucro ∝ f¹, DD ∝ f^0,3 → FR ∝ f^0,7.
EXP_DD = 0.3
EXP_FR = 0.7

# Piso de trades para uma combinação ser CANDIDATA dentro de uma janela IS.
# Abaixo disto a métrica é ruído: dois trades de +50 têm desvio zero, e
# desvio zero virava estatística t e fator de recuperação infinitos — a
# combinação de 2 trades vencia seis das sete inteligências.
MIN_TRADES_JANELA = 30

# decil superior, mas nunca com menos que isto: com 8 candidatos o decil tem
# 1 elemento, e Moda e Centroides viravam escolha de pico
TOPO_MIN = 3

# Platô Pessimista
PLATO_RAIO_PCT = 0.05      # raio da vizinhança, em fração dos valores do parâmetro
PLATO_QUANTIL = 0.25       # a nota é o pior quarto dos vizinhos
PLATO_COBERTURA = 0.5      # vizinhança com menos da metade da caixa não recebe nota


# --------------------------------------------------------------- janelas
@dataclass(frozen=True)
class Janela:
    """Uma linha da escadinha. `deploy` é a última: otimiza e não tem OOS,
    porque o OOS dela é o futuro — é a configuração que se colocaria para
    operar hoje."""
    step: int
    is_de: np.datetime64
    is_ate: np.datetime64
    oos_de: np.datetime64
    oos_ate: np.datetime64
    deploy: bool = False

    @property
    def is_anos(self) -> float:
        return _meses(self.is_de, self.is_ate) / MESES_ANO

    @property
    def oos_anos(self) -> float:
        return _meses(self.oos_de, self.oos_ate) / MESES_ANO


def _mes(d) -> np.datetime64:
    return np.datetime64(d, "M")


def _meses(a, b) -> int:
    return int((_mes(b) - _mes(a)).astype(int))


def montar_janelas(inicio, fim, is_meses: int, oos_meses: int,
                   ancorada: bool = False) -> list[Janela]:
    """A escadinha IS/OOS.

        steps = floor((meses_totais − IS) ÷ OOS)

    Rolante: a janela IS anda junto, sempre do mesmo tamanho — é a
    preferência do Pardo, e adapta-se a mudança de regime. Ancorada: o começo
    fica preso no primeiro dia e a janela IS cresce, usando toda a história
    disponível. Rodar as duas e comparar já diz quanto o edge depende do
    passado remoto.

    As bordas são alinhadas ao início do mês. A primeira janela IS pode
    nascer alguns dias mais curta que o nominal (se a base começa no meio do
    mês), o que é irrelevante para uma janela de 6+ meses e mantém a grade
    limpa e comparável entre configurações.
    """
    if is_meses < 1 or oos_meses < 1:
        raise ValueError("IS e OOS precisam de pelo menos 1 mês.")

    t0, t1 = _mes(inicio), _mes(fim)
    total = int((t1 - t0).astype(int))
    steps = (total - is_meses) // oos_meses
    if steps < 1:
        return []
    # A escadinha é alinhada pelo FIM da base: os meses que sobram da divisão
    # ficam no começo (o primeiro IS rolante começa um pouco depois; o
    # ancorado cresce um pouco antes). Alinhada pelo começo, a sobra ia para
    # o fim — e o DEPLOY, a otimização "para operar hoje", treinava com até
    # OOS−1 meses de atraso: IS10/OOS5 terminava em maio com dados até
    # setembro.
    sobra = (total - is_meses) % oos_meses

    def um(k: int, deploy: bool) -> Janela:
        if ancorada:
            is_de = t0
            is_ate = t0 + np.timedelta64(sobra + is_meses + k * oos_meses, "M")
        else:
            is_de = t0 + np.timedelta64(sobra + k * oos_meses, "M")
            is_ate = is_de + np.timedelta64(is_meses, "M")
        oos_de = is_ate
        return Janela(k + 1, is_de.astype("datetime64[s]"),
                      is_ate.astype("datetime64[s]"),
                      oos_de.astype("datetime64[s]"),
                      (oos_de + np.timedelta64(oos_meses, "M")).astype("datetime64[s]"),
                      deploy)

    # a linha DEPLOY é um passo a mais: o OOS dela ainda não aconteceu
    return [um(k, False) for k in range(steps)] + [um(steps, True)]


# --------------------------------------------------------------- métricas
def pregoes(de, ate) -> int:
    """Dias úteis em [de, ate). Não desconta feriados da B3 (~9 por ano,
    ~3,5%): erro pequeno perto do que corrige, que é ignorar TODOS os dias
    sem trade."""
    return int(np.busday_count(np.datetime64(de, "D"), np.datetime64(ate, "D")))


def sharpe_diario(por_dia: np.ndarray, n_pregoes: int | None) -> float:
    """Sharpe anualizado de uma série diária, contando os pregões SEM trade.

    Os dias parados entram como retorno zero. Calcular só nos dias operados
    inflava quem opera pouco: quatro trades num ano davam Sharpe 129; com os
    pregões parados, 4. A conta não precisa materializar os zeros — média e
    variância saem das somas.
    """
    k = len(por_dia)
    n = max(int(n_pregoes or 0), k)
    if n < 2:
        return 0.0
    media = float(por_dia.sum()) / n
    var = (float((por_dia ** 2).sum()) - n * media ** 2) / (n - 1)
    # variância que é só arredondamento de uma série constante não é risco
    if var <= 1e-12 * max(media ** 2, 1e-18):
        return 0.0
    return float(media / math.sqrt(var) * math.sqrt(DIAS_ANO))


def metricas(liquido: np.ndarray, dias: np.ndarray, capital: float,
             n_pregoes: int | None = None) -> dict:
    """O que uma fatia de trades vale — tudo que as inteligências consultam.

    `dias` são as datas de ENTRADA em resolução de dia, usadas para agrupar
    o resultado diário do Sharpe. A janela é atribuída pela entrada, então
    agrupar pela entrada mantém a conta coerente com o recorte.
    `n_pregoes` é o tamanho da janela em dias úteis: os dias sem trade
    entram no Sharpe como zero.
    """
    n = len(liquido)
    if n == 0:
        return {"trades": 0, "lucro": 0.0, "pf": 0.0, "dd": 0.0, "fr": 0.0,
                "sharpe": 0.0, "ulcer": float("inf"), "t": 0.0,
                "expectativa": 0.0}

    lucro = float(liquido.sum())
    ganhos = float(liquido[liquido > 0].sum())
    perdas = float(-liquido[liquido < 0].sum())

    # o capital entra como primeiro ponto: sem ele, uma janela que abre
    # perdendo teria drawdown zero até fazer o primeiro topo
    eq = np.concatenate(([capital], capital + np.cumsum(liquido)))
    pico = np.maximum.accumulate(eq)
    dd = float((pico - eq).max())
    queda_pct = (eq - pico) / np.where(pico > 0, pico, 1) * 100
    ulcer = float(np.sqrt((queda_pct ** 2).mean()))

    desvio = float(liquido.std(ddof=1)) if n > 1 else 0.0
    media = float(liquido.mean())
    # sem variação não há como medir se o edge se distingue de ruído: t = 0,
    # e não infinito. E "sem variação" com TOLERÂNCIA: 35 trades de R$ 36,56
    # dão desvio de 7e-15 pelo arredondamento, e não zero — o teste `> 0`
    # deixava passar e o t saía 3e16
    t = (media / (desvio / math.sqrt(n))
         if desvio > 1e-9 * max(abs(media), 1.0) else 0.0)

    # Sharpe sobre retorno DIÁRIO, como no resto da plataforma
    unicos, inv = np.unique(dias, return_inverse=True)
    por_dia = np.zeros(len(unicos))
    np.add.at(por_dia, inv, liquido)
    ret = por_dia / capital if capital else por_dia
    sharpe = sharpe_diario(ret, n_pregoes)

    return {
        "trades": n,
        "lucro": lucro,
        "pf": (ganhos / perdas) if perdas else (float("inf") if ganhos else 0.0),
        "dd": dd,
        "fr": (lucro / dd) if dd else (float("inf") if lucro > 0 else 0.0),
        "sharpe": sharpe,
        "ulcer": ulcer,
        "t": float(t),
        "expectativa": media,
    }


def criterios_por_janela(base: dict | None, meses_base: float,
                         min_trades: int = MIN_TRADES_JANELA):
    """Os critérios da mineração, trazidos para o tamanho de cada janela IS.

    A mineração julga o período inteiro (anos); a janela IS tem meses. Um
    critério de CONTAGEM não pode entrar cru: "300 trades" em 5 anos são 60
    numa janela de 12 meses. Por isso:

      trades   proporcional ao tempo, com piso de `min_trades`;
      lucro    proporcional ao tempo (o piso em R$ encolhe junto);
      dd       × f^0,3 — o pior mergulho cresce BEM mais devagar que o tempo:
               o de 5 anos não é 5× o de 1 ano, porque uma estratégia com
               expectativa positiva tende a sair do buraco antes de ele ficar
               fundo (o máximo cresce perto de log t, e não de t);
      fr       × f^0,7 — é lucro ÷ drawdown, então sobe como f¹ ÷ f^0,3.
               Medido por Monte Carlo com parâmetros do WIN: expoente entre
               0,6 e 0,75. A raiz (0,5) reprovava metade das combinações que
               estavam exatamente no limiar; o linear (1,0) aprovava demais;
      pf       como está: é uma razão entre somas que crescem juntas.

    Devolve uma função da janela: na ancorada o IS cresce a cada passo, e o
    critério cresce junto.
    """
    base = dict(base or {})

    def para(j: "Janela") -> dict:
        f = min(1.0, (j.is_anos * MESES_ANO) / meses_base) if meses_base else 1.0
        out = {"trades": (max(min_trades, math.ceil(base["trades"] * f))
                          if base.get("trades") is not None else min_trades)}
        if base.get("lucro") is not None:
            out["lucro"] = float(base["lucro"]) * f
        if base.get("fr") is not None:
            out["fr"] = float(base["fr"]) * f ** EXP_FR
        if base.get("dd") is not None:
            out["dd"] = float(base["dd"]) * f ** EXP_DD
        if base.get("pf") is not None:
            out["pf"] = float(base["pf"])
        return out

    para.base, para.meses_base = base, meses_base
    return para


def _limiares(criterios, j) -> dict | None:
    return criterios(j) if callable(criterios) else criterios


def passa_criterios(m: dict, limiares: dict | None) -> bool:
    """Os critérios de aceite aplicados DENTRO da janela IS.

    O vencedor de cada janela precisa ser alguém que você teria aprovado
    naquele momento — é o que aproxima a simulação do seu processo real. Um
    limiar ausente ou None desliga aquele critério; valor não-finito (fator
    de recuperação com drawdown zero) não reprova por falta de dado.
    """
    if not limiares:
        return True
    for chave in CRITERIOS_IS:
        lim = limiares.get(chave)
        if lim is None:
            continue
        v = m.get(chave)
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            continue
        if chave == "dd":
            if v > lim:
                return False
        elif v < lim:
            return False
    return True


# --------------------------------------------- inteligências de seleção
def _k(v: float) -> float:
    """Chave de ordem sem o ruído da 16ª casa decimal. Dois Sharpe iguais na
    matemática saem diferentes no ponto flutuante, e essa diferença decidia a
    escolha antes de o desempate por lucro ser consultado."""
    return round(float(v), 9)


def _finito(indices, mets: list[dict], chave: str):
    """A métrica com os infinitos trazidos para dentro da escala.

    Fator de recuperação com drawdown zero é infinito. Como NÚMERO ele não
    mente, mas como CHAVE DE ORDEM ele atropela tudo: qualquer combinação sem
    mergulho ia para o topo do decil, por menor que fosse o lucro. Aqui o
    +inf vale o maior valor finito da janela (e o −inf, o menor) — continua
    entre os melhores, e o desempate por lucro decide.
    """
    finitos = [mets[i][chave] for i in indices if np.isfinite(mets[i][chave])]
    teto = max(finitos) if finitos else 0.0
    piso = min(finitos) if finitos else 0.0

    def valor(i):
        v = mets[i][chave]
        return v if np.isfinite(v) else (teto if v > 0 else piso)
    return valor


def _topo(indices: list[int], mets: list[dict], quantos_pct: float = 0.10) -> list[int]:
    """O decil superior por fator de recuperação, com desempate por lucro.

    Nunca menor que `TOPO_MIN`: com poucos candidatos o decil tinha um
    elemento, e as inteligências de platô viravam escolha de pico.
    """
    fr = _finito(indices, mets, "fr")
    k = max(min(TOPO_MIN, len(indices)), math.ceil(len(indices) * quantos_pct))
    return sorted(indices, key=lambda i: (_k(fr(i)), mets[i]["lucro"]),
                  reverse=True)[:k]


def _ancorar(alvo: dict, candidatos: list[int], params: list[dict],
             mets: list[dict]) -> int:
    """A combinação REAL mais próxima de um vetor de parâmetros imaginário.

    Procura só entre os `candidatos` — o decil que produziu o alvo. Antes
    procurava entre todas as aprovadas, e o centro de duas boas podia cair
    exatamente em cima de uma perdedora que estava no meio delas.

    A distância é normalizada por parâmetro, pela amplitude que ele tem entre
    os candidatos. Sem isso um stop de 320 pontos dominaria um desvio de
    2,75. Empate de distância: vence o maior fator de recuperação, e não a
    que vier primeiro na grade.
    """
    nomes = list(alvo)
    escalas = {}
    for nome in nomes:
        vals = [float(params[i][nome]) for i in candidatos]
        amp = max(vals) - min(vals)
        escalas[nome] = amp if amp > 0 else 1.0

    fr = _finito(candidatos, mets, "fr")

    def chave(i: int):
        d = sum(((float(params[i][n]) - alvo[n]) / escalas[n]) ** 2 for n in nomes)
        return (_k(d), -_k(fr(i)), -mets[i]["lucro"])

    return min(candidatos, key=chave)


def _numericos(params: list[dict], indices) -> list[str]:
    """Os parâmetros que dá para somar e tirar mediana. Texto e bool ficam de
    fora da conta do centro (e entram na vizinhança por igualdade)."""
    nomes = list(params[indices[0]])
    return [n for n in nomes
            if all(isinstance(params[i][n], (int, float, np.number))
                   and not isinstance(params[i][n], bool) for i in indices)]


def _centroide(indices: list[int], params: list[dict], mets: list[dict],
               agregar) -> int:
    topo = _topo(indices, mets)
    alvo = {n: float(agregar([float(params[i][n]) for i in topo]))
            for n in _numericos(params, topo)}
    return _ancorar(alvo, topo, params, mets)


def _moda(indices: list[int], params: list[dict], mets: list[dict]) -> int:
    """O valor que mais se REPETE no decil superior, parâmetro a parâmetro.

    Numa grade discreta, se a região boa é um platô o mesmo valor aparece
    muitas vezes no topo. A moda encontra o centro da parte densa — que é
    coisa diferente do centro geométrico, e costuma ser mais estável quando o
    platô é torto.
    """
    topo = _topo(indices, mets)
    alvo = {}
    for nome in _numericos(params, topo):
        vals = [float(params[i][nome]) for i in topo]
        únicos, contagem = np.unique(vals, return_counts=True)
        # empate na contagem: fica com o valor do meio, não com o primeiro
        maior = contagem.max()
        candidatos = únicos[contagem == maior]
        alvo[nome] = float(np.median(candidatos))
    return _ancorar(alvo, topo, params, mets)


_GRADE: dict = {}


def _grade(params: list[dict], indices):
    """A estrutura da grade para o Platô Pessimista, calculada uma vez por
    lista de parâmetros (a mesma em todas as janelas de uma configuração):
    posição de cada combinação em cada eixo numérico, raio, tamanho do eixo e
    o grupo dos parâmetros de texto. None quando não há eixo numérico."""
    if _GRADE.get("ref") is params and _GRADE.get("n") == len(params):
        return _GRADE["dados"]
    n = len(params)
    nomes = list(params[indices[0]])
    eixos, textos = [], []
    for nome in nomes:
        vals = [params[k].get(nome) for k in range(n)]
        if all(isinstance(v, (int, float, np.number)) and not isinstance(v, bool)
               for v in vals):
            unicos = sorted({float(v) for v in vals})
            if len(unicos) > 1:
                eixos.append((nome, unicos))
        elif len({str(v) for v in vals}) > 1:
            textos.append(nome)
    if not eixos:
        dados = None
    else:
        pos = {nome: {v: r for r, v in enumerate(u)} for nome, u in eixos}
        R = np.array([[pos[nome][float(params[k][nome])] for nome, _ in eixos]
                      for k in range(n)], dtype=np.int32)
        tam = np.array([len(u) for _, u in eixos])
        raio = np.array([max(1, round(PLATO_RAIO_PCT * len(u))) for _, u in eixos])
        grupo = (np.unique([tuple(str(params[k].get(t)) for t in textos)
                            for k in range(n)], axis=0, return_inverse=True)[1].ravel()
                 if textos else np.zeros(n, dtype=int))
        # Endereço de cada combinação na grade (posições × grupo de texto) e
        # os deslocamentos da caixa de vizinhança. Com isso, os vizinhos de
        # uma candidata são LIDOS pelo endereço — algumas dezenas — em vez de
        # comparados contra a grade inteira. Grades enormes (endereçamento
        # acima de ~20 milhões) ficam sem mapa e usam a comparação em bloco.
        passo = np.cumprod(np.concatenate(([1], tam[:-1]))).astype(np.int64)
        celulas = int(np.prod(tam)) * int(grupo.max() + 1)
        caixa = int(np.prod(2 * raio + 1))
        mapa = offsets = None
        if celulas <= 20_000_000 and caixa <= 4096:
            mapa = np.full(celulas, -1, dtype=np.int64)
            mapa[(R @ passo) + grupo * int(np.prod(tam))] = np.arange(n)
            offsets = np.array(np.meshgrid(*[np.arange(-r, r + 1) for r in raio],
                                           indexing="ij")).reshape(len(raio), -1).T
        dados = (R, raio, tam, grupo, passo, mapa, offsets)
    _GRADE.update(ref=params, n=n, dados=dados)
    return dados


def _plato_pessimista(indices: list[int], params: list[dict],
                      mets: list[dict]) -> tuple[int, dict]:
    """A nota de cada combinação é o PIOR QUARTO dos vizinhos dela na grade.

    Um pico cercado de prejuízo perde para um ponto bom cercado de pontos
    bons. Diferente das Centroides — que olham só o decil superior e acham o
    centro dele —, a vizinhança mede a superfície no próprio ponto: não cai no
    vale entre duas ilhas boas e enxerga o penhasco logo ao lado.

      coordenada  a POSIÇÃO do valor na lista ordenada de cada parâmetro, o
                  que resolve passo irregular (40, 45, 60…);
      raio        5% dos valores de cada parâmetro, no mínimo 1;
      vizinhança  a caixa de raio em volta, com igualdade exata nos
                  parâmetros de texto; parâmetro de um valor só não restringe;
      nota        quantil 25% do fator de recuperação na vizinhança —
                  inclusive vizinhos REPROVADOS nos critérios, que são
                  justamente o penhasco;
      cobertura   vizinhança com menos de max(3, metade da caixa) não recebe
                  nota; se ninguém receber, vale a Centroide Mediana.

    Referências: a preferência de Pardo por regiões largas; a seleção por
    "ilhas" em walk-forward (Eng. Proc. 2024, futuro de índice de Taiwan).
    A evidência é coerente, não conclusiva — por isso ela concorre com as
    outras na aba Consenso em vez de substituí-las.
    """
    n = len(params)
    grade = _grade(params, indices)
    if grade is None:
        return _centroide(indices, params, mets, np.median), {"plato": False}
    R, raio, tam, grupo, passo, mapa, offsets = grade

    fr = _finito(range(n), mets, "fr")
    nota_base = np.array([0.0 if mets[k]["trades"] == 0 else fr(k) for k in range(n)])
    aprovado = np.zeros(n, dtype=bool)
    aprovado[indices] = True

    # Todas as candidatas de uma vez, em blocos: a vizinhança de cada uma é
    # uma linha de uma matriz candidatas × grade. O laço por candidata era
    # O(candidatas × grade) em Python e dominava o tempo da matriz inteira.
    cand = np.asarray(indices)
    notas = {}
    if mapa is not None:
        # vizinhos pelo endereço: candidatas × deslocamentos da caixa
        bloco = max(1, 4_000_000 // max(1, len(offsets) * R.shape[1]))
        largura = int(np.prod(tam))
        for ini in range(0, len(cand), bloco):
            c = cand[ini:ini + bloco]
            coord = R[c][:, None, :] + offsets[None, :, :]
            valido = np.all((coord >= 0) & (coord < tam), axis=2)
            ender = np.where(valido, coord @ passo + grupo[c][:, None] * largura, 0)
            idx = np.where(valido, mapa[ender], -1)
            dentro = idx >= 0
            cont = dentro.sum(axis=1)
            ok = cont >= np.maximum(3, np.ceil(PLATO_COBERTURA * valido.sum(axis=1)))
            if not ok.any():
                continue
            seguros = np.where(dentro[ok], idx[ok], 0)
            vals = np.where(dentro[ok], nota_base[seguros], np.nan)
            q = np.nanquantile(vals, PLATO_QUANTIL, axis=1)
            med = np.nanmedian(vals, axis=1)
            frac = (dentro[ok] & aprovado[seguros]).sum(axis=1) / cont[ok]
            for i, qi, mi, ci, fi in zip(c[ok], q, med, cont[ok], frac):
                notas[int(i)] = (float(qi), float(mi), float(nota_base[i]),
                                 int(ci), float(fi))
    else:
        bloco = max(1, 3_000_000 // max(1, n * R.shape[1]))
        for ini in range(0, len(cand), bloco):
            c = cand[ini:ini + bloco]
            dentro = (np.all(np.abs(R[None, :, :] - R[c][:, None, :]) <= raio, axis=2)
                      & (grupo[None, :] == grupo[c][:, None]))
            cont = dentro.sum(axis=1)
            caixa = np.prod(np.minimum(R[c] + raio, tam - 1)
                            - np.maximum(R[c] - raio, 0) + 1, axis=1)
            ok = cont >= np.maximum(3, np.ceil(PLATO_COBERTURA * caixa))
            if not ok.any():
                continue
            vals = np.where(dentro[ok], nota_base[None, :], np.nan)
            q = np.nanquantile(vals, PLATO_QUANTIL, axis=1)
            med = np.nanmedian(vals, axis=1)
            frac = (dentro[ok] & aprovado[None, :]).sum(axis=1) / cont[ok]
            for i, qi, mi, ci, fi in zip(c[ok], q, med, cont[ok], frac):
                notas[int(i)] = (float(qi), float(mi), float(nota_base[i]),
                                 int(ci), float(fi))

    if not notas:
        return (_centroide(indices, params, mets, np.median),
                {"plato": False})
    i = max(notas, key=lambda k: (_k(notas[k][0]), _k(notas[k][1]),
                                  _k(notas[k][2]), mets[k]["lucro"]))
    return i, {"plato": True, "nota": notas[i][0], "vizinhos": notas[i][3],
               "vizinhos_aprovados": notas[i][4]}


def escolher(qual: str, indices: list[int], params: list[dict],
             mets: list[dict], memo: dict | None = None) -> tuple[int, dict]:
    """Aplica uma das sete inteligências. Devolve (índice, detalhe).

    `indices` já vem filtrado pelos critérios de aceite. Se estiver vazio,
    quem chama decide — e a decisão desta plataforma é ficar fora do mercado.
    """
    if not indices:
        raise ValueError("nenhum candidato aprovado nesta janela")
    if memo is not None:
        if qual not in memo:
            memo[qual] = escolher(qual, indices, params, mets)  if qual != "conselho" \
                else _conselho(indices, params, mets, memo)
        return memo[qual]

    # os desempates são pelo lucro, e não pela ordem da grade: Ulcer zero
    # em duas combinações escolhia a primeira da lista, com lucro de R$ 2
    # contra outra de R$ 301 mil
    if qual == "sharpe":
        return max(indices, key=lambda i: (_k(mets[i]["sharpe"]), mets[i]["lucro"])), {}
    if qual == "ulcer":
        return min(indices, key=lambda i: (_k(mets[i]["ulcer"]), -mets[i]["lucro"])), {}
    if qual == "alpha":
        t = _finito(indices, mets, "t")
        return max(indices, key=lambda i: (_k(t(i)), mets[i]["lucro"])), {}
    if qual == "vizinhanca":
        return _plato_pessimista(indices, params, mets)
    if qual == "moda":
        return _moda(indices, params, mets), {}
    if qual == "centroide_media":
        return _centroide(indices, params, mets, np.mean), {}
    if qual == "centroide_mediana":
        return _centroide(indices, params, mets, np.median), {}
    if qual == "conselho":
        return _conselho(indices, params, mets)
    raise ValueError(f"inteligência desconhecida: {qual!r}")


def _conselho(indices: list[int], params: list[dict],
              mets: list[dict], memo: dict | None = None) -> tuple[int, dict]:
    """As outras votam (`VOTANTES`); vence quem tiver mais indicações.

    Quando a região é um platô de verdade, elas convergem e o voto é quase
    unânime. Quando cada uma aponta para um lado, isso É a informação: a
    região não tem centro claro, e o consenso (o centroide mediano dos
    indicados) vale mais que a opinião de qualquer uma delas isolada.

    O detalhe devolvido carrega o placar, que vai para a tela.
    """
    votos: dict[int, list[str]] = {}
    for v in VOTANTES:
        i, _ = escolher(v, indices, params, mets, memo)
        votos.setdefault(i, []).append(v)

    maior = max(len(v) for v in votos.values())
    empatados = [i for i, v in votos.items() if len(v) == maior]

    if len(empatados) == 1:
        vencedor = empatados[0]
    else:
        # QUALQUER empate no topo (2-2-2, 3-3, ou todos diferentes) vai para
        # o centroide mediano dos indicados — como diz a documentação. Antes
        # só o empate total ia; um 2-2-2 era decidido pelo fator de
        # recuperação, o que dava ao pico a última palavra.
        # Ancorado ENTRE OS INDICADOS: o vencedor sempre tem voto — antes a
        # mediana podia cair numa combinação que ninguém escolheu, e a tela
        # mostrava "0 de 6".
        indicados = list(votos)
        alvo = {n: float(np.median([float(params[i][n]) for i in indicados]))
                for n in _numericos(params, indicados)}
        vencedor = (_ancorar(alvo, indicados, params, mets) if alvo
                    else max(empatados, key=_finito(empatados, mets, "fr")))

    return vencedor, {
        "votos": len(votos.get(vencedor, [])),
        "votantes": len(VOTANTES),
        "por_quem": votos.get(vencedor, []),
        "unanime": len(votos) == 1,
    }


# -------------------------------------------------------------------- WFE
def wfe(is_lucro: float, is_anos: float, oos_lucro: float,
        oos_anos: float) -> float | None:
    """Walk-Forward Efficiency: desempenho anualizado OOS ÷ IS.

    Devolve None — e não zero, e não infinito — quando o IS não lucrou. A
    razão simplesmente não existe aí: dividir um OOS positivo por um IS
    negativo daria um número negativo que se leria como "péssimo" quando o
    fato é "a janela de otimização não achou nada para degradar".
    """
    if is_anos <= 0 or oos_anos <= 0 or is_lucro <= 0:
        return None
    return (oos_lucro / oos_anos) / (is_lucro / is_anos)


def _razao(oos: float, ins: float) -> float | None:
    """WFE de uma métrica já normalizada (PF, fator de recuperação): não se
    anualiza o que já é razão."""
    if not np.isfinite(ins) or not np.isfinite(oos) or ins <= 0:
        return None
    return oos / ins


# ------------------------------------------------------------------ passos
@dataclass
class Passo:
    janela: Janela
    escolhida: int | None
    params: dict = field(default_factory=dict)
    is_: dict = field(default_factory=dict)
    oos: dict = field(default_factory=dict)
    wfe_lucro: float | None = None
    wfe_fr: float | None = None
    wfe_pf: float | None = None
    candidatos: int = 0
    poucos_trades: bool = False
    fora_do_mercado: bool = False
    detalhe: dict = field(default_factory=dict)


def preparar(combos: list[dict], janelas: list[Janela], capital: float,
             criterios: dict | None = None) -> dict:
    """As métricas IS de cada combinação em cada janela, e quem passou.

    É a parte cara do walk-forward — ~90% do tempo, medido na #40 — e é
    IDÊNTICA para todas as inteligências: o lucro de uma combinação numa
    janela não depende de quem vai escolher. Calcular uma vez e entregar às
    sete é o que faz a aba de Consenso custar pouco mais que uma matriz só.
    """
    params = [c["params"] for c in combos]
    dias = [c["entry_ts"].astype("datetime64[D]") for c in combos]
    fatia = [_fatiador(c["entry_ts"]) for c in combos]
    por_janela = []
    for j in janelas:
        lim = _limiares(criterios, j)
        n_pregoes = pregoes(j.is_de, j.is_ate)
        m_is, aprovados = [], []
        for i, c in enumerate(combos):
            sel = fatia[i](j.is_de, j.is_ate)
            m = metricas(c["liquido"][sel], dias[i][sel], capital, n_pregoes)
            m_is.append(m)
            if m["trades"] > 0 and passa_criterios(m, lim):
                aprovados.append(i)
        por_janela.append((m_is, aprovados))
    # `memo` guarda, por janela, a escolha de cada inteligência: o Conselho
    # consulta as votantes que a matriz acabou de calcular em vez de refazê-las
    return {"params": params, "dias": dias, "fatia": fatia,
            "janelas": por_janela, "memo": [dict() for _ in janelas]}


def _fatiador(entry_ts: np.ndarray):
    """Uma função (de, ate) → recorte dos trades com entrada em [de, ate).

    Os trades vêm do backtest em ordem de entrada: com o array ordenado, o
    recorte é uma busca binária (fatia contígua) em vez de uma máscara sobre o
    array inteiro para cada combinação × janela. Se não estiver ordenado,
    cai na máscara — o resultado é o mesmo, só mais lento.
    """
    if len(entry_ts) < 2 or bool(np.all(entry_ts[1:] >= entry_ts[:-1])):
        def recorte(de, ate):
            a = int(np.searchsorted(entry_ts, de, "left"))
            b = int(np.searchsorted(entry_ts, ate, "left"))
            return slice(a, b)
    else:
        def recorte(de, ate):
            return (entry_ts >= de) & (entry_ts < ate)
    return recorte


def rodar(combos: list[dict], janelas: list[Janela], capital: float,
          inteligencia: str = "centroide_mediana",
          criterios: dict | None = None,
          min_trades_is: int = MIN_TRADES_IS,
          preparado: dict | None = None) -> list[Passo]:
    """Percorre a escadinha. Cada `combo` é
    `{"params": {...}, "entry_ts": array, "liquido": array}`.

    O trade pertence à janela da sua ENTRADA. Nenhuma combinação é rodada de
    novo: tudo é máscara sobre os arrays que já vieram.

    `preparado` (de `preparar`, com as MESMAS janelas e critérios) poupa a
    parte cara quando várias inteligências percorrem a mesma escadinha.
    """
    if not combos or not janelas:
        return []

    prep = preparado or preparar(combos, janelas, capital, criterios)
    params, dias = prep["params"], prep["dias"]
    fatia = prep.get("fatia") or [_fatiador(c["entry_ts"]) for c in combos]
    memos = prep.get("memo") or [None] * len(janelas)

    passos = []
    for j, (m_is, aprovados), memo in zip(janelas, prep["janelas"], memos):

        if not aprovados:
            # ninguém aprovado: fica fora do mercado neste OOS. É a decisão
            # honesta, e o WFA precisa poder dizer "neste trimestre eu não
            # teria operado".
            passos.append(Passo(janela=j, escolhida=None, candidatos=0,
                                fora_do_mercado=True))
            continue

        i, detalhe = escolher(inteligencia, aprovados, params, m_is, memo)
        ins = m_is[i]

        if j.deploy:
            # o OOS da última janela é o futuro: não existe resultado
            passos.append(Passo(janela=j, escolhida=i, params=params[i],
                                is_=ins, oos={}, candidatos=len(aprovados),
                                poucos_trades=ins["trades"] < min_trades_is,
                                detalhe=detalhe))
            continue

        c = combos[i]
        fora = fatia[i](j.oos_de, j.oos_ate)
        oos = metricas(c["liquido"][fora], dias[i][fora], capital,
                       pregoes(j.oos_de, j.oos_ate))

        passos.append(Passo(
            janela=j, escolhida=i, params=params[i], is_=ins, oos=oos,
            wfe_lucro=wfe(ins["lucro"], j.is_anos, oos["lucro"], j.oos_anos),
            wfe_fr=_razao(oos["fr"], ins["fr"]),
            wfe_pf=_razao(oos["pf"], ins["pf"]),
            candidatos=len(aprovados),
            poucos_trades=ins["trades"] < min_trades_is,
            detalhe=detalhe))
    return passos


def trades_oos_campos(combos: list[dict], passos: list[Passo],
                      campos=("entry_ts", "liquido")) -> dict[str, np.ndarray]:
    """Qualquer campo do cache, recortado nas janelas OOS e em ordem.

    Os campos voltam alinhados entre si — o i-ésimo `exit_ts` é do mesmo
    trade que o i-ésimo `liquido` — mais `step`, a janela que escolheu o
    parâmetro de cada um. O trade pertence à janela pela ENTRADA, então
    nenhum é contado duas vezes.
    """
    # a entrada vem sempre: é por ela que se ordena, mesmo que não se peça
    pedacos = {c: [] for c in ("entry_ts", *campos, "step")}
    for p in passos:
        if p.escolhida is None or p.janela.deploy:
            continue
        c = combos[p.escolhida]
        m = (c["entry_ts"] >= p.janela.oos_de) & (c["entry_ts"] < p.janela.oos_ate)
        for campo in pedacos:
            if campo != "step":
                pedacos[campo].append(c[campo][m])
        pedacos["step"].append(np.full(int(m.sum()), p.janela.step))

    pedidos = (*campos, "step")
    if not pedacos["step"]:
        return {c: np.array([], dtype="datetime64[s]" if c.endswith("_ts")
                            else int if c == "step" else float)
                for c in pedidos}
    ordem = np.argsort(np.concatenate(pedacos["entry_ts"]), kind="stable")
    return {c: np.concatenate(pedacos[c])[ordem] for c in pedidos}


def trades_oos(combos: list[dict], passos: list[Passo]):
    """Os trades OOS colados em ordem — a curva que interessa.

    É a coisa mais próxima de um track record que se constrói do passado:
    em nenhum ponto dela o otimizador tinha visto o dado que estava operando.
    """
    t = trades_oos_campos(combos, passos, ("entry_ts", "liquido"))
    return t["entry_ts"], t["liquido"], t["step"]


# ------------------------------------------------------- linha da matriz
def semestres_oos(passos: list[Passo], entrada: np.ndarray,
                  liquido: np.ndarray) -> dict:
    """Quantos SEMESTRES CIVIS (jan–jun, jul–dez) da curva OOS lucraram.

    É a régua do portão de "períodos positivos". Contar por janela punia os
    OOS curtos por estatística, não por mérito: uma janela de 3 meses tem
    ~25 trades e fecha negativa por puro acaso bem mais vezes que uma de 6
    meses com ~60. Com o mesmo bloco de 6 meses para todas as configurações,
    a comparação entre elas volta a ser justa — e a janela curta com poucos
    trades fica "juntada" com as vizinhas dentro do semestre.

    Regras:
      - só entram semestres INTEIRAMENTE cobertos pelo calendário OOS (um
        semestre que o OOS pega pela metade não é comparável);
      - semestre em que a estratégia ficou fora do mercado o tempo todo NÃO
        conta — nem como positivo nem como negativo: ficar de fora foi a
        estratégia dizendo "este regime não é para mim", e isso não é
        prejuízo;
      - positivo = soma do resultado dos trades com ENTRADA no semestre > 0.
    """
    cobertos = meses_oos(passos)
    operados = meses_oos([p for p in passos if not p.fora_do_mercado])
    if not len(cobertos):
        return {"n": 0, "positivos": 0, "pct": None, "fora": 0}

    def semestre(meses):
        m = np.asarray(meses, dtype="datetime64[M]").astype(int)   # meses desde 1970
        return m // 6

    s_cob, n_cob = np.unique(semestre(cobertos), return_counts=True)
    inteiros = set(s_cob[n_cob == 6].tolist())
    s_oper = set(semestre(operados).tolist())
    validos = sorted(x for x in inteiros if x in s_oper)
    if not validos:
        return {"n": 0, "positivos": 0, "pct": None,
                "fora": len(inteiros)}
    sem_trade = semestre(np.asarray(entrada).astype("datetime64[M]")) if len(entrada) \
        else np.array([], dtype=int)
    soma = {x: 0.0 for x in validos}
    for sx, v in zip(sem_trade.tolist(), np.asarray(liquido).tolist()):
        if sx in soma:
            soma[sx] += v
    positivos = sum(1 for v in soma.values() if v > 0)
    return {"n": len(validos), "positivos": positivos,
            "pct": float(positivos / len(validos) * 100),
            "fora": len(inteiros) - len(validos)}


def agregar(passos: list[Passo], capital: float,
            liquido_oos: np.ndarray | None = None,
            entrada_oos: np.ndarray | None = None,
            saida_oos: np.ndarray | None = None) -> dict:
    """A linha da matriz WFM para uma configuração IS/OOS.

    O **WFE global** é o número principal: soma os OOS e soma os IS antes de
    dividir, então uma janela com IS minúsculo não desequilibra nada. A
    **mediana** das janelas é o secundário. A média não aparece: na
    referência há janelas com WFE de 337% e de −35%, e uma média contaminada
    por elas não descreve coisa alguma.
    """
    reais = [p for p in passos if not p.janela.deploy]
    if not reais:
        return {}

    oos_l = sum(p.oos.get("lucro", 0.0) for p in reais)
    is_l = sum(p.is_.get("lucro", 0.0) for p in reais)

    # Duas contagens de tempo, e a diferença entre elas importa:
    #
    #   OPERADO   - só as janelas em que houve combinação aprovada. É a base
    #               do WFE, porque a janela sem ninguém aprovado também não
    #               tem IS para degradar: excluir dos dois lados é simétrico.
    #   CALENDÁRIO- todas as janelas. É a base do lucro por mês, porque esses
    #               meses passaram do mesmo jeito. Dividir o lucro só pelos
    #               meses operados infla o resultado de quem ficou metade do
    #               tempo fora - exatamente o contrário do que a métrica
    #               deveria dizer.
    oos_a = sum(p.janela.oos_anos for p in reais if not p.fora_do_mercado)
    is_a = sum(p.janela.is_anos for p in reais if not p.fora_do_mercado)
    oos_calendario = sum(p.janela.oos_anos for p in reais)

    definidos = [p.wfe_lucro for p in reais if p.wfe_lucro is not None]
    com_trades = [p for p in reais if not p.fora_do_mercado]
    positivas = sum(1 for p in com_trades if p.oos.get("lucro", 0.0) > 0)

    def acima(x):
        return (float(sum(1 for w in definidos if w * 100 >= x)
                      / len(definidos) * 100) if definidos else 0.0)

    mediana = float(np.median(definidos)) if definidos else None
    desvio = float(np.std(definidos, ddof=1)) if len(definidos) > 1 else 0.0

    dd_oos = 0.0
    if liquido_oos is not None and len(liquido_oos):
        eq = np.concatenate(([capital], capital + np.cumsum(liquido_oos)))
        dd_oos = float((np.maximum.accumulate(eq) - eq).max())

    # o Sharpe da curva concatenada, para a dispersão entre configurações
    # alimentar o Sharpe Deflacionado da tela Candidata. Pela SAÍDA, como
    # `metrics.resumo` e `wfa_store.serie_diaria` — é quando o resultado se
    # realiza; cair para a entrada só serve às chamadas antigas que ainda
    # não têm a saída em mãos.
    # a agregação diária é duplicada aqui em vez de chamar `metrics.resumo`
    # porque metrics já importa wfa (usa sharpe_diario) — importar metrics
    # daqui fecharia um ciclo.
    sharpe = None
    referencia = saida_oos if saida_oos is not None else entrada_oos
    if liquido_oos is not None and len(liquido_oos) and referencia is not None:
        dia = np.asarray(referencia, dtype="datetime64[D]")
        ordem = np.argsort(dia, kind="stable")
        d, por_dia = np.unique(dia[ordem], return_index=True)
        soma = np.add.reduceat(np.asarray(liquido_oos)[ordem], por_dia)
        sharpe = sharpe_diario(soma, pregoes(reais[0].janela.oos_de,
                                            reais[-1].janela.oos_ate))

    sem = (semestres_oos(passos, entrada_oos, liquido_oos)
           if entrada_oos is not None and liquido_oos is not None
           else {"n": 0, "positivos": 0, "pct": None, "fora": 0})

    return {
        "steps": len(reais),
        # o mergulho da curva CONCATENADA, e nao a soma dos mergulhos por
        # janela: e a curva inteira que se opera, nao os pedacos
        "dd_oos": dd_oos,
        "sharpe": sharpe,
        "semestres": sem["n"], "semestres_positivos": sem["positivos"],
        "semestres_fora": sem["fora"],
        # a régua do portão; sem nenhum semestre inteiro, vale a de janelas
        "periodos_positivos": sem["pct"],
        "janelas_operadas": len(com_trades),
        "fora_do_mercado": sum(1 for p in reais if p.fora_do_mercado),
        "poucos_trades": sum(1 for p in reais if p.poucos_trades),
        "oos_lucro": oos_l,
        "oos_meses": oos_calendario * MESES_ANO,
        "oos_meses_operados": oos_a * MESES_ANO,
        "lucro_mes_oos": (oos_l / (oos_calendario * MESES_ANO)
                          if oos_calendario > 0 else 0.0),
        "oos_trades": sum(p.oos.get("trades", 0) for p in reais),
        "is_lucro": is_l,
        # o principal: soma antes de dividir
        "wfe_global": wfe(is_l, is_a, oos_l, oos_a),
        "wfe_mediana": mediana,
        "wfe_desvio": desvio,
        # dispersão sobre a MEDIANA, não sobre a média — para não reintroduzir
        # pela porta dos fundos a média que decidimos não usar
        "wfe_cv": (desvio / abs(mediana)) if mediana else None,
        "wfe_indefinidos": len(reais) - len(definidos),
        "consistencia_lucro": (float(positivas / len(com_trades) * 100)
                               if com_trades else 0.0),
        "wfe_acima_50": acima(50), "wfe_acima_70": acima(70),
        "wfe_acima_90": acima(90),
    }


# ------------------------------------------------------------- matriz WFM
def matriz(combos: list[dict], inicio, fim, capital: float,
           inteligencia: str = "centroide_mediana",
           criterios: dict | None = None,
           configs: list[tuple[int, int]] | None = None,
           min_trades_is: int = MIN_TRADES_IS) -> list[dict]:
    """A matriz de UMA inteligência. Ver `matrizes`."""
    return matrizes(combos, inicio, fim, capital, [inteligencia], criterios,
                    configs, min_trades_is)[inteligencia]


def matrizes(combos: list[dict], inicio, fim, capital: float,
             inteligencias: list[str] | None = None,
             criterios: dict | None = None,
             configs: list[tuple[int, int]] | None = None,
             min_trades_is: int = MIN_TRADES_IS,
             limiares: dict | None = None,
             progresso=None) -> dict[str, list[dict]]:
    """Uma linha por configuração IS/OOS — a Matriz de Otimização.

    A pergunta que ela responde não é "qual configuração rendeu mais", e sim
    **de que tamanho de janela esta estratégia precisa**. Uma que só funciona
    com IS de 24 meses depende de memória longa; uma que funciona em todas é
    robusta de verdade. E uma que só funciona numa configuração específica não
    tem edge — tem coincidência.

    Cada linha traz o WFE **rolante** e o **ancorado** lado a lado. Rolante
    esquece o passado remoto e se adapta a regime; ancorado usa toda a
    história. Quando o ancorado é muito melhor, o edge é estrutural e antigo;
    quando o rolante ganha, o mercado mudou e a estratégia precisa acompanhar.

    Custo: nenhum backtest. Cada configuração é fatiamento sobre o cache, e
    as métricas das janelas (`preparar`) são calculadas uma vez por
    configuração e divididas entre todas as inteligências pedidas.

    Cada linha traz também o veredito dos **seis portões** — os mesmos da
    tela de detalhe, com a curva OOS de verdade (sem ela o portão de
    drawdown passaria sempre).
    """
    qs = list(inteligencias or [v for _, v in INTELIGENCIAS])
    fora: dict[str, list[dict]] = {q: [] for q in qs}
    lista = list(configs or CONFIGS)
    # o PERÍODO COMUM: do OOS que começa mais tarde até o fim. Cada
    # configuração começa a operar numa data (IS6/OOS3 em 2021-09, IS24/OOS6
    # em 2023-03); comparar lucro/mês de períodos diferentes compara mercados
    # diferentes
    inicios = [montar_janelas(inicio, fim, a, b)[0].oos_de for a, b in lista
               if montar_janelas(inicio, fim, a, b)]
    comum = max(inicios) if inicios else None
    for k, (is_m, oos_m) in enumerate(lista):
        # sem o DEPLOY: a matriz só agrega janelas com OOS, e o DEPLOY custava
        # uma janela inteira de métricas e escolhas por configuração
        js = [j for j in montar_janelas(inicio, fim, is_m, oos_m) if not j.deploy]
        if not js:
            continue
        anc = [j for j in montar_janelas(inicio, fim, is_m, oos_m, ancorada=True)
               if not j.deploy]
        prep = preparar(combos, js, capital, criterios)
        prep_anc = preparar(combos, anc, capital, criterios)

        for q in qs:
            passos = rodar(combos, js, capital, q, criterios, min_trades_is,
                           preparado=prep)
            # a saída entra à parte: o Sharpe da linha agrega por ela (é
            # quando o resultado se realiza), mas o "comum" abaixo continua
            # cortando pela entrada
            campos = trades_oos_campos(combos, passos,
                                       ("entry_ts", "exit_ts", "liquido"))
            ts, saida, liq = campos["entry_ts"], campos["exit_ts"], campos["liquido"]
            ag = agregar(passos, capital, liq, ts, saida)
            if not ag:
                continue
            if comum is not None:
                meses = int((_mes(js[-1].oos_ate) - _mes(comum)).astype(int))
                ag["lucro_mes_comum"] = (float(liq[ts >= comum].sum()) / meses
                                         if meses > 0 else None)
            ver = portoes_wfa(ag, passos, capital, limiares)
            ag_anc = agregar(rodar(combos, anc, capital, q, criterios,
                                   min_trades_is, preparado=prep_anc), capital)
            fora[q].append(_linha_matriz(is_m, oos_m, ag, ag_anc, ver))
        if progresso:
            progresso(k + 1, len(lista))
    return fora


def _linha_matriz(is_m, oos_m, ag, ag_anc, ver) -> dict:
    return {
            "config": f"IS:{is_m} / OOS:{oos_m}",
            "is_meses": is_m, "oos_meses": oos_m,
            "steps": ag["steps"],
            "lucro_mes": ag["lucro_mes_oos"],
            "oos_lucro": ag["oos_lucro"],
            "oos_trades": ag["oos_trades"],
            "wfe": ag["wfe_global"],
            "sharpe": ag.get("sharpe"),
            "wfe_ancorado": ag_anc.get("wfe_global"),
            "wfe_mediana": ag["wfe_mediana"],
            "wfe_desvio": ag["wfe_desvio"],
            "cv": ag["wfe_cv"],
            "consistencia": ag["consistencia_lucro"],
            "semestres_pct": ag.get("periodos_positivos"),
            "semestres": ag.get("semestres", 0),
            "lucro_mes_comum": ag.get("lucro_mes_comum"),
            "a50": ag["wfe_acima_50"], "a70": ag["wfe_acima_70"],
            "a90": ag["wfe_acima_90"],
            "fora_do_mercado": ag["fora_do_mercado"],
            "indefinidos": ag["wfe_indefinidos"],
            "estado": ver.get("estado", "reprovado"),
            "portoes_ok": ver.get("n_ok", 0),
            "n_portoes": ver.get("n_portoes", 0),
    }


def consenso(por_inteligencia: dict[str, list[dict]],
             votantes: list[str] | None = None, top: int = 5) -> list[dict]:
    """Quantas inteligências concordam com cada configuração IS/OOS.

    O walk-forward valida o MÉTODO de escolher parâmetro. Uma configuração que
    só uma inteligência aprova não mostra método funcionando — mostra a
    tentativa mais sortuda de várias. Por isso a ordem não é pelo maior WFE,
    e sim:

      1. quantas das inteligências votantes aprovam (veredito dos seis portões);
      2. o WFE mediano entre elas — o centro, não o pico;
      3. o pior WFE entre elas — o piso que se aceita.

    O Conselho de Notáveis fica fora da contagem: ele é a votação das outras
    votantes, e contá-lo seria contar os mesmos votos duas vezes. O maior WFE
    continua na linha, como informação.
    """
    vs = list(votantes or VOTANTES)
    por_config: dict[str, dict] = {}
    for q in vs:
        for r in por_inteligencia.get(q, []):
            linha = por_config.setdefault(r["config"], {
                "config": r["config"], "is_meses": r["is_meses"],
                "oos_meses": r["oos_meses"], "_wfes": []})
            linha[f"wfe_{q}"] = r["wfe"]
            linha[f"est_{q}"] = r["estado"]
            if r["wfe"] is not None:
                linha["_wfes"].append(r["wfe"])

    fora = []
    for linha in por_config.values():
        wfes = linha.pop("_wfes")
        linha["aprovam"] = sum(1 for q in vs
                               if linha.get(f"est_{q}", "reprovado") != "reprovado")
        linha["votantes"] = len(vs)
        linha["wfe_mediano"] = float(np.median(wfes)) if wfes else None
        linha["pior_wfe"] = min(wfes) if wfes else None
        linha["melhor_wfe"] = max(wfes) if wfes else None
        fora.append(linha)

    def chave(r):
        return (-r["aprovam"],
                -(r["wfe_mediano"] if r["wfe_mediano"] is not None else -1e9),
                -(r["pior_wfe"] if r["pior_wfe"] is not None else -1e9))

    fora.sort(key=chave)
    for pos, r in enumerate(fora, start=1):
        r["posicao"] = pos
        r["top"] = pos <= top and r["aprovam"] > 0
        r["recomendada"] = pos == 1 and r["aprovam"] > 0
    return fora


# --------------------------------------------------- deriva dos parâmetros
DRIFT_ESTAVEL = 0.05     # desvio ≤ 5% da faixa minerada
DRIFT_TRANSICAO = 0.15   # desvio ≤ 15% da faixa; acima, instável


def drift(passos: list[Passo], espaco: dict | None = None) -> list[dict]:
    """Como cada parâmetro escolhido mudou de janela em janela.

    É o painel que quase ninguém constrói e o que mais denuncia. Linha plana
    significa que a região boa fica no mesmo lugar ano após ano — o edge tem
    endereço. Serrote significa que o otimizador persegue ruído: a cada
    trimestre ele acha um ótimo diferente, e nenhum deles descreve o mercado.

    Pardo diz o mesmo com outras palavras: se os parâmetros disparam em
    janelas isoladas e falham nas outras, a estratégia é frágil.

    A volatilidade é o desvio dos valores escolhidos dividido pela FAIXA
    QUE A MINERAÇÃO TESTOU (máximo − mínimo do espaço). A pergunta é "o
    otimizador ficou num canto da região ou passeou por ela inteira?".
    Dividir pela média, como antes, dependia de onde fica o zero da escala: um
    parâmetro minerado de 1.000 a 1.010 parecia estável pulando de ponta a
    ponta (5 ÷ 1.005), e o `periodo_canal` da #40, que percorreu 72% da faixa
    40→80, saía "em transição" (16%) quando pela faixa é "instável" (24%).

    Faixas: até 5% da faixa, estável; até 15%, em transição; acima,
    instável. Para referência, um parâmetro sorteado ao acaso em toda a faixa
    tem desvio de ~29% dela. Sem o espaço minerado (ou com um valor só nele),
    cai na régua antiga, desvio ÷ média.
    """
    com_escolha = [p for p in passos if p.params]
    if len(com_escolha) < 2:
        return []

    fora = []
    for nome in _numericos([p.params for p in com_escolha],
                           range(len(com_escolha))):
        vals = [float(p.params[nome]) for p in com_escolha]
        media = float(np.mean(vals))
        desvio = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
        minerados = sorted({float(x) for x in (espaco or {}).get(nome, [])
                            if isinstance(x, (int, float)) and not isinstance(x, bool)})
        faixa = (minerados[-1] - minerados[0]) if len(minerados) > 1 else 0.0
        if faixa > 0:
            vol, referencia = desvio / faixa, "faixa"
            percurso = (max(vals) - min(vals)) / faixa
            limites = (DRIFT_ESTAVEL, DRIFT_TRANSICAO)
        else:
            # régua antiga: média zero com oscilação (breakeven 0 ↔ 20) não é
            # "estável" — mede contra a maior magnitude escolhida
            escala = abs(media) if media else max(abs(x) for x in vals)
            vol, referencia, percurso = (desvio / escala if escala else 0.0), "media", None
            limites = (0.05, 0.20)
        trocas = sum(1 for a, b in zip(vals, vals[1:]) if a != b)

        if vol <= limites[0]:
            estado = "estável"
        elif vol <= limites[1]:
            estado = "em transição"
        else:
            estado = "instável"

        fora.append({
            "nome": nome,
            "rotulos": ["DEPLOY" if p.janela.deploy else f"Step {p.janela.step}"
                        for p in com_escolha],
            "valores": vals,
            "media": media, "desvio": desvio, "volatilidade": vol,
            "referencia": referencia, "percurso": percurso,
            "faixa_de": minerados[0] if faixa > 0 else None,
            "faixa_ate": minerados[-1] if faixa > 0 else None,
            "minimo": min(vals), "maximo": max(vals),
            "trocas": trocas, "janelas": len(vals),
            "estado": estado,
            # um parâmetro que nunca mudou não tem deriva: a mineração varreu
            # um valor só, e o gráfico dele seria uma reta sem conteúdo
            "fixo": len(set(vals)) == 1,
        })
    return fora


# ---------------------------------------------------------------- portões
LIMIARES_WFA = {
    "min_trades_oos": 300,      # Pardo: ~30 por janela OOS, dez janelas
    "min_janelas_positivas": 70.0,
    "min_wfe": 0.70,            # a literatura usa 50%; o operador exigiu 70%
    "max_dd_relativo": 1.5,
}


def _portao_wfa(nome, ok, critico, valor, exigido, dica) -> dict:
    return {"nome": nome, "ok": bool(ok), "critico": critico,
            "valor": valor, "exigido": exigido, "dica": dica}


def _positivos(ag: dict) -> float:
    pp = ag.get("periodos_positivos")
    return pp if pp is not None else ag.get("consistencia_lucro", 0.0)


def portoes_wfa(ag: dict, passos: list[Passo], capital: float,
                lim: dict | None = None) -> dict:
    """O veredito sobre o walk-forward inteiro.

    Mesma gramática da Porteira da mineração: portões **críticos** barram,
    **alertas** passam com ressalva. A diferença é o que está sendo julgado —
    lá, a região do espaço de parâmetros; aqui, o processo de escolher dentro
    dela, medido no único dado que o otimizador nunca viu.
    """
    if not ag:
        return {}
    L = {**LIMIARES_WFA, **(lim or {})}

    reais = [p for p in passos if not p.janela.deploy and not p.fora_do_mercado]
    dd_is = max((p.is_.get("dd", 0.0) for p in reais), default=0.0)
    dd_oos = ag.get("dd_oos", 0.0)
    razao = (dd_oos / dd_is) if dd_is > 0 else None
    wfe = ag.get("wfe_global")

    ps = [
        _portao_wfa(
            "lucro OOS total", ag["oos_lucro"] > 0, True,
            ag["oos_lucro"], "> 0",
            "A soma de todos os pedaços fora da amostra. Se for negativa, o "
            "processo de escolher parâmetro não funciona — e não adianta "
            "trocar de combinação, porque foi justamente escolhendo que se "
            "chegou aqui. Um backtest otimizado lucrativo com OOS negativo é "
            "a definição de sobreajuste."),
        _portao_wfa(
            ("semestres OOS positivos" if ag.get("periodos_positivos") is not None
             else "janelas OOS positivas"),
            _positivos(ag) >= L["min_janelas_positivas"], True,
            _positivos(ag), f"≥ {L['min_janelas_positivas']:.0f}%",
            "Percentual dos SEMESTRES CIVIS da curva fora da amostra que "
            "fecharam no azul — o teste de repetição: lucrar no total ganhando "
            "em 2 de 8 períodos é ter vivido de um. Medido em semestres, e não "
            "por janela, para que um OOS de 3 meses (poucos trades, muito "
            "ruído) não seja reprovado por estatística. Semestre parcial não "
            "entra; semestre todo fora do mercado não conta contra. Sem nenhum "
            "semestre inteiro, vale a contagem por janela."),
        _portao_wfa(
            "WFE global", (wfe or 0) >= L["min_wfe"], True,
            wfe, f"≥ {L['min_wfe'] * 100:.0f}%",
            "Quanto do desempenho otimizado sobrevive em dado novo. A "
            "literatura usa 50% como piso — alguma degradação é esperada e "
            "normal. Aqui o piso é 70%, por decisão do operador. Acima de "
            "100% o fora da amostra superou o de dentro, o que costuma "
            "significar que a janela de otimização pegou um período difícil."),
        _portao_wfa(
            "trades OOS somados", ag["oos_trades"] >= L["min_trades_oos"], True,
            ag["oos_trades"], f"≥ {L['min_trades_oos']}",
            "Tamanho da amostra fora da amostra. Pardo pede cerca de 30 "
            "trades por janela OOS e dez janelas — daí os 300. Abaixo disso a "
            "curva concatenada é curta demais para separar edge de sorte, por "
            "mais bonita que pareça."),
        _portao_wfa(
            "drawdown OOS ÷ IS",
            razao is None or razao <= L["max_dd_relativo"], False,
            razao, f"≤ {L['max_dd_relativo']:.1f}×",
            "O mergulho da curva fora da amostra comparado ao pior mergulho "
            "que a otimização viu. Acima de 1,5× o backtest estava escondendo "
            "risco: você dimensionou posição por um drawdown que não é o que "
            "acontece quando o parâmetro encontra dado novo. Fica vazio "
            "quando nenhuma janela IS teve drawdown."),
        _portao_wfa(
            "janelas fora do mercado", ag["fora_do_mercado"] == 0, False,
            ag["fora_do_mercado"], "= 0",
            "Janelas em que nenhuma combinação passou nos critérios de aceite "
            "e a estratégia não teria operado. Não é defeito — é honestidade, "
            "e ficar de fora costuma ser melhor que forçar. Mas muitas "
            "janelas assim significam que a estratégia só existe em certos "
            "regimes, e o lucro por mês precisa ser lido sobre o calendário "
            "inteiro, não sobre os meses operados."),
    ]

    criticos = [p for p in ps if p["critico"] and not p["ok"]]
    ressalvas = [p for p in ps if not p["critico"] and not p["ok"]]
    if criticos:
        estado, cor = "reprovado", "neg"
    elif ressalvas:
        estado, cor = "aprovado com ressalva", "warn"
    else:
        estado, cor = "aprovado", "pos"

    return {"portoes": ps, "estado": estado, "cor": cor,
            "n_ok": sum(1 for p in ps if p["ok"]), "n_portoes": len(ps),
            "reprovados": criticos, "ressalvas": ressalvas,
            "dd_oos": dd_oos, "dd_is": dd_is, "dd_razao": razao}


# ------------------------------------------- reotimizar vale a pena?
def faixa_fixas(combos: list[dict], janelas: list[Janela], capital: float,
                quantis=(10, 25, 50, 75, 90)) -> dict:
    """A distribuição das curvas de TODAS as combinações fixas, no mesmo
    intervalo da curva do walk-forward.

    É o contrafactual honesto de "reotimizar vale a pena?". A versão anterior
    comparava o WFA com UMA combinação — a escolhida na primeira janela e
    nunca mais trocada. Era um sorteio: na #40 ela sugeria que reotimizar
    ajudava (R$ 3.498 contra R$ 4.240), mas 66% das 41 combinações fixas
    batiam o WFA no mesmo período. Com a faixa, a leitura é direta: se a
    curva do WFA passeia dentro dela, reotimizar não está acrescentando nada
    além de escolher uma combinação qualquer da região.

    Devolve, por dia útil do intervalo, os quantis do capital acumulado, e o
    lucro final de cada combinação (para o percentil do WFA).
    """
    reais = [j for j in janelas if not j.deploy]
    if not combos or not reais:
        return {}
    ini, fim = reais[0].oos_de, reais[-1].oos_ate
    dias = np.arange(np.datetime64(ini, "D"), np.datetime64(fim, "D"))
    dias = dias[np.is_busday(dias)]
    if not len(dias):
        return {}
    curvas = np.zeros((len(combos), len(dias)))
    for k, c in enumerate(combos):
        sel = _fatiador(c["entry_ts"])(ini, fim)
        e = c["entry_ts"][sel].astype("datetime64[D]")
        if not len(e):
            continue
        pos = np.clip(np.searchsorted(dias, e, "left"), 0, len(dias) - 1)
        curvas[k] = np.cumsum(np.bincount(pos, weights=c["liquido"][sel],
                                          minlength=len(dias)))
    q = np.percentile(curvas, quantis, axis=0)
    return {"dias": dias, "quantis": {int(p): capital + q[i] for i, p in enumerate(quantis)},
            "finais": curvas[:, -1], "n": len(combos)}


def percentil_na_faixa(faixa: dict, lucro_wfa: float) -> float | None:
    """Em que percentil das combinações fixas o WFA terminou (0 a 100)."""
    finais = (faixa or {}).get("finais")
    if finais is None or not len(finais):
        return None
    return float((finais < lucro_wfa).mean() * 100)


# ---------------------------------------------- eficiência temporal (OOS)
def meses_oos(passos: list["Passo"]) -> np.ndarray:
    """Todos os meses de calendário cobertos pelas janelas OOS, com trade ou
    sem — inclusive os das janelas em que a estratégia ficou fora do mercado."""
    meses = [np.arange(_mes(p.janela.oos_de), _mes(p.janela.oos_ate))
             for p in passos if not p.janela.deploy]
    if not meses:
        return np.array([], dtype="datetime64[M]")
    return np.unique(np.concatenate(meses))


def mensal(entry_ts: np.ndarray, liquido: np.ndarray,
           calendario: np.ndarray | None = None) -> dict:
    """O resultado mês a mês da curva fora da amostra.

    O total anual esconde a experiência de operar. Duas estratégias com o
    mesmo lucro, uma que entrega todo mês e outra que passa sete meses no
    vermelho e recupera em dois, são coisas diferentes na cadeira — e é a
    segunda que faz gente desligar o robô no pior momento possível.

    `tempo_medio_recuperacao` conta em MESES quanto leva, em média, para
    voltar ao topo anterior depois de um mês negativo — só os mergulhos que
    JÁ se recuperaram; o que ainda está em curso vai em `sub_topo_em_curso`.
    `maior_sub_topo` é o pior período submerso, em curso ou não.

    `calendario`: os meses de calendário das janelas OOS (`meses_oos`). Os
    meses sem trade entram com zero — sem eles, "meses positivos" contava só
    os meses operados (53% em vez de 40% na IS6/OOS3 da #40) e um trimestre
    parado com a curva submersa sumia do "maior período sem novo topo".
    """
    if not len(liquido):
        return {}

    meses = entry_ts.astype("datetime64[M]")
    unicos = np.unique(meses)
    if calendario is not None and len(calendario):
        unicos = np.unique(np.concatenate([np.asarray(calendario,
                                                      dtype="datetime64[M]"),
                                           unicos]))
    pos = np.searchsorted(unicos, meses)
    soma = np.zeros(len(unicos))
    np.add.at(soma, pos, liquido)

    positivos = soma[soma > 0]
    negativos = soma[soma < 0]

    # tempo submerso, em meses, sobre a curva MENSAL acumulada — começando no
    # ZERO: sem esse ponto, um primeiro mês negativo não contava como mergulho
    acum = np.cumsum(soma)
    pico = np.maximum.accumulate(np.concatenate(([0.0], acum)))[1:]
    submerso = acum < pico

    episodios, atual = [], 0
    for sub in submerso:
        if sub:
            atual += 1
        elif atual:
            episodios.append(atual)
            atual = 0
    em_curso = atual

    lucro_bruto = float(positivos.sum())
    perda_bruta = float(-negativos.sum())
    dd_mensal = float((pico - acum).max()) if len(acum) else 0.0
    # os meses parados fora do mercado contam como meses que PASSARAM

    return {
        "rotulos": [str(m) for m in unicos],
        "valores": soma.tolist(),
        "meses": int(len(unicos)),
        "positivos": int(len(positivos)),
        "negativos": int(len(negativos)),
        "pct_positivos": float(len(positivos) / len(unicos) * 100),
        "media_lucro": float(positivos.mean()) if len(positivos) else 0.0,
        "media_prejuizo": float(negativos.mean()) if len(negativos) else 0.0,
        "media": float(soma.mean()),
        "melhor": float(soma.max()),
        "pior": float(soma.min()),
        # lucro total dividido pelo maior mergulho da curva MENSAL
        "fator_recuperacao": (float(acum[-1] / dd_mensal)
                              if dd_mensal > 0 else None),
        "profit_factor": ((lucro_bruto / perda_bruta) if perda_bruta
                          else (float("inf") if lucro_bruto else 0.0)),
        "tempo_medio_recuperacao": (float(np.mean(episodios))
                                    if episodios else 0.0),
        "maior_sub_topo": int(max(episodios + [em_curso])),
        "sub_topo_em_curso": int(em_curso),
        "n_episodios": len(episodios),
    }
