"""Camada 4 - execucao. O que e do operador, nao da estrategia.

Tempo grafico, janela de entrada, horario de fechamento, gestao (stop e alvo),
protecoes, limites diarios, custos e dimensionamento. Identico para toda
estrategia, aplicado pelo motor.

Duas decisoes de desenho valem ser ditas:

TEMPO GRAFICO. A estrategia le barras do timeframe escolhido, mas a EXECUCAO
roda sempre em M1. Um sinal fechado numa barra de 5 minutos e conhecido no
minuto do fechamento dela e executa no minuto seguinte - que e o que um robo
de verdade faz, e nao esperar a abertura do proximo candle de 5 minutos.
Isso preserva a precisao intrabarra do stop mesmo operando em M15 ou H1.

STOP E ALVO SAO DA CAMADA 4. No MQL5 sao inputs como qualquer outro, mas
quanto arriscar e como proteger e decisao do operador, nao da matematica do
setup - do mesmo jeito que horario e custo. A estrategia pode sobrepor por
sinal quando quiser stop dinamico proprio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numba import njit

from . import kernel as K

TIMEFRAMES = {"M1": 1, "M2": 2, "M3": 3, "M5": 5, "M7": 7, "M9": 9,
              "M10": 10, "M11": 11, "M13": 13, "M15": 15, "M17": 17,
              "M20": 20, "M30": 30, "H1": 60, "H2": 120, "H4": 240}


def _minutes(hhmm: str) -> int:
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- perfil
@dataclass
class ExecutionProfile:
    timeframe: str = "M1"

    # janela
    entrada_inicio: str = "09:00"
    entrada_fim: str = "17:00"
    fechamento: str = "17:30"
    dias_semana: tuple[int, ...] = (1, 2, 3, 4, 5)
    direcao: str = "ambas"
    # horas sem ENTRADA nova ("13:00" = nada entra das 13:00 às 13:59).
    # Stop, alvo e fechamento da posicao aberta continuam agindo.
    sem_entrada1: str = ""
    sem_entrada2: str = ""
    sem_entrada3: str = ""

    # gestao: pontos fixos, multiplo de ATR ou multiplicador do stop
    alvo_tipo: str = "pontos"           # pontos | atr | multiplicador
    alvo_pontos: int = 600
    alvo_atr_periodo: int = 20
    alvo_atr_mult: float = 3.0
    alvo_razao: float = 2.0             # alvo / stop quando tipo = multiplicador

    stop_tipo: str = "pontos"
    stop_pontos: int = 300
    stop_atr_periodo: int = 20
    stop_atr_mult: float = 1.5

    # filtro de mercado (ADX) - camada 4, vale para toda estrategia.
    # 0 em periodo OU limiar desliga o filtro por completo, e o zero ser
    # mineravel e o que deixa comparar ligado x desligado na mesma varredura.
    filtro_adx: str = "tendencia"   # tendencia | rango
    adx_periodo: int = 0            # 0 = desligado
    adx_limiar: int = 0             # 0 tambem desliga
    adx_filtro_di: int = 0          # tendencia: DI+ > DI- na compra
    adx_subindo: int = 0            # tendencia: adx[i] > adx[i-1]

    # protecoes, em % do alvo (0 = desligado) - como no robo MQL5
    breakeven_pct: float = 0.0
    step_gatilho_pct: float = 0.0
    step_distancia_pct: float = 0.0
    trailing_pontos: int = 0
    max_barras: int = 0

    # limites diarios
    limite_ganho_contrato: float = 0.0   # R$ por contrato, 0 = desligado
    limite_perda_contrato: float = 0.0   # R$ por contrato, valor positivo
    max_trades_dia: int = 0
    max_prejuizos_dia: int = 0

    # custos
    corretagem_por_contrato: float = 0.0
    emolumentos_por_contrato: float = 0.0
    slippage_ticks: int = 1

    # posicao
    modo_posicao: str = "contratos_fixos"
    contratos: int = 1
    risco_por_trade: float | None = None
    capital_inicial: float = 10_000.0

    # filtro de mineracao
    min_operacoes: int = 0

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "ExecutionProfile":
        plano = {}
        for bloco in cfg.values():
            if isinstance(bloco, dict):
                plano.update(bloco)
        campos = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in plano.items() if k in campos})

    def to_config(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["dias_semana"] = list(self.dias_semana)
        return d


# ------------------------------------------------------------- timeframe
def resample(bars: dict, minutos: int):
    """Agrega M1 no timeframe pedido.

    Devolve as barras agregadas e, para cada barra M1, o indice da ultima
    barra do timeframe JA FECHADA naquele minuto (-1 antes da primeira).
    E esse mapa que impede look-ahead ao passar de M15 para M1.
    """
    ts = bars["ts"]
    dias = ts.astype("datetime64[D]").astype(np.int64)
    minuto = ts.astype("datetime64[m]").astype(np.int64) % 1440
    chave = dias * 10_000 + (minuto // minutos)

    inicio = np.flatnonzero(np.append(True, chave[1:] != chave[:-1]))
    fim = np.append(inicio[1:] - 1, len(chave) - 1)

    agregado = {
        "ts": ts[fim],
        "open": bars["open"][inicio],
        "high": np.maximum.reduceat(bars["high"], inicio),
        "low": np.minimum.reduceat(bars["low"], inicio),
        "close": bars["close"][fim],
        "tick_volume": np.add.reduceat(bars["tick_volume"], inicio),
    }
    # barra de tf k so e conhecida a partir do minuto fim[k]
    fechada = np.searchsorted(fim, np.arange(len(ts)), side="right") - 1
    return agregado, fechada, fim


def expand_signal(sinal: np.ndarray, fim: np.ndarray, n: int) -> np.ndarray:
    """Leva um sinal do timeframe da estrategia para o indice M1.

    O sinal da barra de tf k so existe no minuto em que ela FECHA, e o kernel
    executa na barra seguinte. Como as barras do timeframe sao contiguas, a
    barra seguinte ao fechamento de um candle de 15 minutos e a primeira do
    proximo candle de 15 - ou seja, ordem a mercado na abertura do candle
    novo, que e o comportamento de um robo de verdade.
    """
    out = np.zeros(n, dtype=np.bool_)
    out[fim] = sinal
    return out


def run_strategy(bars, estrategia, params, profile: "ExecutionProfile",
                 instrument: dict, vela_aberta: bool = False) -> "BacktestResult":
    """Caminho completo: agrega no timeframe, gera sinais, executa em M1.

    `vela_aberta` é do papel ao vivo: a última barra M1 é de uma vela do
    timeframe que o relógio ainda não fechou. `resample` a daria por
    fechada naquela barra (é a última do dado), e o stop/alvo por ATR — ou
    o nível da estratégia — de uma entrada naquele minuto sairia da vela
    pela metade. No histórico inteiro a mesma barra enxerga a vela
    ANTERIOR; com a flag, ao vivo também. O sinal da vela parcial não muda
    nada: ele cai na última barra, e não há barra seguinte para executar.
    """
    from strategies.base import Signals

    n = len(bars["open"])
    passo = TIMEFRAMES.get(profile.timeframe, 1)
    if passo == 1:
        bars_tf, fechada, fim = bars, np.arange(n), np.arange(n)
    else:
        bars_tf, fechada, fim = resample(bars, passo)
        if vela_aberta and n:
            fechada = fechada.copy()
            fechada[n - 1] -= 1

    s = estrategia.signals(bars_tf, params)

    def nivel(v):
        if np.isscalar(v):
            return v
        out = np.zeros(n, dtype=np.int64)
        out[fim] = np.asarray(v, dtype=np.int64)
        seguro = np.clip(fechada, 0, len(fim) - 1)
        cheio = np.asarray(v, dtype=np.int64)[seguro]
        cheio[fechada < 0] = 0
        return cheio

    sig = Signals(
        entry_long=expand_signal(s.entry_long, fim, n),
        entry_short=expand_signal(s.entry_short, fim, n),
        exit_long=expand_signal(s.exit_long, fim, n),
        exit_short=expand_signal(s.exit_short, fim, n),
        sl_points=nivel(s.sl_points),
        tp_points=nivel(s.tp_points),
    )
    return backtest(bars, sig, profile, instrument, bars_tf, fechada)


def atr(bars: dict, periodo: int) -> np.ndarray:
    """ATR classico: media simples do True Range, como o iATR do MT5."""
    h, l, c = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    out = np.full(len(tr), np.nan)
    if periodo <= 0 or len(tr) < periodo:
        return out
    soma = np.cumsum(np.insert(tr.astype(np.float64), 0, 0.0))
    out[periodo - 1:] = (soma[periodo:] - soma[:-periodo]) / periodo
    return out


def adx(bars: dict, periodo: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ADX de Wilder com DI+ e DI-, barra a barra: (adx, di_pos, di_neg).

    DI comeca na barra periodo-1 e o ADX em 2*periodo-2 (media das
    primeiras period DX); antes disso e NaN, que a mascara de entrada le
    como "fora da regua". So olha barras ja fechadas do proprio timeframe
    da estrategia - o mesmo dado que a estrategia viu, sem look-ahead.
    """
    n = int(periodo)
    m = len(bars["close"])
    if n < 1 or m < n:
        vazio = np.full(m, np.nan)
        return vazio, vazio.copy(), vazio.copy()
    return _adx_wilder(
        np.ascontiguousarray(bars["high"], dtype=np.float64),
        np.ascontiguousarray(bars["low"], dtype=np.float64),
        np.ascontiguousarray(bars["close"], dtype=np.float64),
        n,
    )


@njit(cache=True)
def _adx_wilder(h, l, c, n):
    m = len(c)
    tr = np.empty(m)
    pdm = np.empty(m)
    ndm = np.empty(m)
    tr[0] = h[0] - l[0]
    pdm[0] = 0.0
    ndm[0] = 0.0
    for i in range(1, m):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0.0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0.0) else 0.0
        pc = c[i - 1]
        tr[i] = max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc))

    dip = np.full(m, np.nan)
    dim = np.full(m, np.nan)
    da = np.full(m, np.nan)
    if m < n:
        return da, dip, dim

    str_ = 0.0
    sp = 0.0
    sn = 0.0
    for i in range(n):
        str_ += tr[i]
        sp += pdm[i]
        sn += ndm[i]

    # suavizacao de Wilder: a media anterior menos 1/n dela, mais o valor
    # novo - igual a formula classica do ADX
    dx = np.zeros(m)
    for i in range(n - 1, m):
        if i > n - 1:
            str_ = str_ - str_ / n + tr[i]
            sp = sp - sp / n + pdm[i]
            sn = sn - sn / n + ndm[i]
        p = 100.0 * sp / str_ if str_ > 0.0 else 0.0
        q = 100.0 * sn / str_ if str_ > 0.0 else 0.0
        dip[i] = p
        dim[i] = q
        den = p + q
        dx[i] = 100.0 * abs(p - q) / den if den > 0.0 else 0.0

    if m >= 2 * n - 1:
        soma = 0.0
        for i in range(n - 1, 2 * n - 1):
            soma += dx[i]
        da[2 * n - 2] = soma / n
        for i in range(2 * n - 1, m):
            da[i] = (da[i - 1] * (n - 1) + dx[i]) / n
    return da, dip, dim


def _nivel(bars_tf, fechada, tipo, pontos, periodo, mult, n_m1) -> np.ndarray:
    """Stop ou alvo em pontos, por barra M1."""
    if tipo == "pontos":
        return np.full(n_m1, max(0, int(pontos)), dtype=np.int64)
    valores = atr(bars_tf, int(periodo)) * float(mult)
    valores = np.nan_to_num(valores, nan=0.0)
    seguro = np.clip(fechada, 0, len(valores) - 1)
    fora = fechada < 0
    out = valores[seguro].astype(np.int64)
    out[fora] = 0
    return out


# ------------------------------------------------------------- sessao
@dataclass
class SessionArrays:
    in_entry_window: np.ndarray   # pode ENTRAR neste minuto (bloqueios aplicados)
    arm_window: np.ndarray        # janela sem os bloqueios: sinal pode nascer aqui
    is_close_time: np.ndarray
    day_id: np.ndarray


def build_session_arrays(ts: np.ndarray, profile: ExecutionProfile) -> SessionArrays:
    """Janela de ENTRADA e horario de FECHAMENTO sao coisas diferentes.

    Entre o fim das entradas e o fechamento a posicao segue viva, mas nenhuma
    nova e aberta. O fechamento nao precisa de calendario de feriado: como
    nenhum pregao do historico fecha antes das 17:54, qualquer horario ate
    ali e sempre alcancado.
    """
    dias = ts.astype("datetime64[D]").astype(np.int64)
    minuto = ts.astype("datetime64[m]").astype(np.int64) % 1440
    dow_iso = ((dias + 3) % 7) + 1  # 1970-01-01 foi quinta

    permitidos = np.zeros(8, dtype=bool)
    for d in profile.dias_semana:
        permitidos[int(d)] = True
    dia_ok = permitidos[dow_iso]

    ini, fim = _minutes(profile.entrada_inicio), _minutes(profile.entrada_fim)
    fech = _minutes(profile.fechamento)

    arm = (minuto >= ini) & (minuto <= fim) & dia_ok
    in_entry = arm.copy()

    # horas sem entrada: mascaram so a ENTRADA. O sinal pode nascer dentro
    # da hora bloqueada, desde que caia para fora (13:59 -> entra 14:00);
    # pendencia que executaria DENTRO da hora cai - o kernel so arma o sinal
    # se a barra seguinte estiver liberada.
    for b in (profile.sem_entrada1, profile.sem_entrada2,
              profile.sem_entrada3):
        if b:
            h = _minutes(b)
            in_entry &= ~((minuto >= h) & (minuto < h + 60))

    is_close = np.zeros(len(ts), dtype=bool)

    # a barra de fechamento e a PRIMEIRA do dia com minuto >= horario
    apos = np.flatnonzero(dia_ok & (minuto >= fech))
    dias_com_fechamento = np.empty(0, dtype=np.int64)
    if apos.size:
        d = dias[apos]
        primeira = np.flatnonzero(np.append(True, d[1:] != d[:-1]))
        is_close[apos[primeira]] = True
        dias_com_fechamento = d[primeira]

    # pregao que acabou antes do horario: a ultima barra dele faz o papel
    operaveis = np.flatnonzero(dia_ok)
    if operaveis.size:
        d = dias[operaveis]
        ultima = np.flatnonzero(np.append(d[1:] != d[:-1], True))
        alvo = operaveis[ultima]
        sem = ~np.isin(dias[alvo], dias_com_fechamento)
        is_close[alvo[sem]] = True

    return SessionArrays(in_entry, arm, is_close, dias)


# ------------------------------------------------------------ resultado
@dataclass
class BacktestResult:
    trades: dict[str, np.ndarray]
    n_trades: int
    ambiguous_bars: int
    bloqueios: int
    n_bars: int
    sl_at_entry: np.ndarray
    tp_at_entry: np.ndarray
    profile: ExecutionProfile
    instrument: dict = field(default_factory=dict)
    bars_tf: dict | None = None


def _override(base: np.ndarray, custom, n: int) -> np.ndarray:
    """A estrategia pode sobrepor stop/alvo por sinal. Se nao sobrepuser,
    vale o que a camada 4 mandou."""
    if custom is None:
        return base
    if np.isscalar(custom):
        return np.full(n, int(custom), dtype=np.int64) if custom else base
    arr = np.asarray(custom, dtype=np.int64)
    return np.where(arr > 0, arr, base)


def backtest(bars, signals, profile: ExecutionProfile, instrument: dict,
             bars_tf=None, fechada=None) -> BacktestResult:
    n = len(bars["open"])
    sess = build_session_arrays(bars["ts"], profile)

    if bars_tf is None:
        passo = TIMEFRAMES.get(profile.timeframe, 1)
        if passo == 1:
            bars_tf, fechada = bars, np.arange(n)
        else:
            bars_tf, fechada, _ = resample(bars, passo)

    sl = _nivel(bars_tf, fechada, profile.stop_tipo, profile.stop_pontos,
                profile.stop_atr_periodo, profile.stop_atr_mult, n)
    sl = _override(sl, signals.sl_points, n)
    tick = int(instrument.get("tick_size", 1)) or 1
    if profile.alvo_tipo == "multiplicador":
        # o alvo e o stop VIGENTE x razao, por barra; stop 0 nao ha o que
        # multiplicar, e o kernel ja trata alvo 0 como 'sem alvo'.
        # Arredonda ao tick mais proximo: 200 x 2,3 da 459,999... em ponto
        # flutuante, e cortar as casas punha o alvo num preco que o WIN
        # nao negocia (1 ponto a menos em cada ganho)
        tp = (np.rint(sl * float(profile.alvo_razao) / tick)
              * tick).astype(np.int64)
    else:
        tp = _nivel(bars_tf, fechada, profile.alvo_tipo, profile.alvo_pontos,
                    profile.alvo_atr_periodo, profile.alvo_atr_mult, n)
    tp = _override(tp, signals.tp_points, n)

    # protecoes em % do alvo -> pontos, por barra
    pct = lambda v: (tp * (float(v) / 100.0)).astype(np.int64) if v else np.zeros(n, np.int64)
    be = pct(profile.breakeven_pct)
    step_t = pct(profile.step_gatilho_pct)
    step_d = pct(profile.step_distancia_pct)
    trail = np.full(n, max(0, int(profile.trailing_pontos)), dtype=np.int64)

    ponto = float(instrument.get("point_value", 1.0)) or 1.0
    stop_dia = -int(round(profile.limite_perda_contrato / ponto)) if profile.limite_perda_contrato else 0
    meta_dia = int(round(profile.limite_ganho_contrato / ponto)) if profile.limite_ganho_contrato else 0

    # regua de mercado (ADX): so corta ENTRADA, nunca saida nem stop.
    # 0 em periodo ou limiar = filtro morto, identico a nao ter filtro.
    # O ADX e calculado nas barras do timeframe que gerou o sinal (ou
    # proprio M1); fechada leva do minuto ao indice daquela barra, e NaN
    # do aquecimento cai como False. Os sinais do chamador nao sao
    # tocados: so uma copia local vai para o kernel.
    el, es = signals.entry_long, signals.entry_short
    # int() antes do teste: 0.5 passaria em `> 0` mas viraria periodo 0
    # dentro de adx(), e ai o filtro morto bloquearia tudo em silencio
    if (profile.filtro_adx in ("tendencia", "rango")
            and int(profile.adx_periodo or 0) > 0
            and int(profile.adx_limiar or 0) > 0):
        va, dip, dim = adx(bars_tf, int(profile.adx_periodo))
        if profile.filtro_adx == "rango":
            # DI e "subindo" pedem direcao/aceleracao - quem procura rango
            # nao quer isso, entao valem so no modo tendencia
            base_tf = va < float(profile.adx_limiar)
            l_tf = s_tf = base_tf
        else:
            base_tf = va >= float(profile.adx_limiar)
            if profile.adx_subindo:
                anterior = np.empty_like(va)
                anterior[0] = np.nan
                anterior[1:] = va[:-1]
                base_tf = base_tf & (va > anterior)
            # o DI e POR LADO: compra quer DI+ acima de DI-, venda o contrario
            if profile.adx_filtro_di:
                l_tf = base_tf & (dip > dim)
                s_tf = base_tf & (dim > dip)
            else:
                l_tf = s_tf = base_tf

        def na_barra(tf):
            ok = np.zeros(n, dtype=bool)
            tem = fechada >= 0
            ok[tem] = tf[fechada[tem]]
            return ok

        el = el & na_barra(l_tf)
        es = es & na_barra(s_tf)

    out = K.allocate_outputs(n)

    n_trades, ambiguous, bloqueios = K.run(
        bars["open"], bars["high"], bars["low"], bars["close"],
        sess.in_entry_window, sess.arm_window, sess.is_close_time,
        sess.day_id,
        el, es,
        signals.exit_long, signals.exit_short,
        sl, tp, be, step_t, step_d, trail,
        profile.direcao in ("ambas", "compra"),
        profile.direcao in ("ambas", "venda"),
        int(profile.max_trades_dia or 0), int(profile.max_prejuizos_dia or 0),
        stop_dia, meta_dia,
        int(profile.max_barras or 0), int(profile.slippage_ticks * tick),
        out["entry_i"], out["exit_i"], out["side"], out["entry_px"],
        out["exit_px"], out["reason"], out["mae"], out["mfe"], out["points"],
        out["stop_fim"], out["alvo_fim"],
    )

    trades = {k: v[:n_trades].copy() for k, v in out.items()}
    trades["entry_ts"] = bars["ts"][trades["entry_i"]]
    trades["exit_ts"] = bars["ts"][trades["exit_i"]]
    trades["bars_held"] = trades["exit_i"] - trades["entry_i"]

    return BacktestResult(
        trades=trades, n_trades=n_trades, ambiguous_bars=int(ambiguous),
        bloqueios=int(bloqueios), n_bars=n,
        sl_at_entry=sl[trades["entry_i"]] if n_trades else np.empty(0, np.int64),
        tp_at_entry=tp[trades["entry_i"]] if n_trades else np.empty(0, np.int64),
        profile=profile, instrument=instrument, bars_tf=bars_tf,
    )


def prepare_bars(con, symbol: str, start=None, end=None) -> dict[str, np.ndarray]:
    where = ["symbol = ?"]
    args: list = [symbol]
    if start:
        where.append("ts >= ?")
        args.append(start)
    if end:
        where.append("ts <= ?")
        args.append(end)

    d = con.execute(
        f"SELECT ts, open, high, low, close, tick_volume, volume "
        f"FROM bars_m1 WHERE {' AND '.join(where)} ORDER BY ts",
        args,
    ).fetchnumpy()

    return {
        "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
        "open": np.ascontiguousarray(d["open"], dtype=np.int64),
        "high": np.ascontiguousarray(d["high"], dtype=np.int64),
        "low": np.ascontiguousarray(d["low"], dtype=np.int64),
        "close": np.ascontiguousarray(d["close"], dtype=np.int64),
        "tick_volume": np.ascontiguousarray(d["tick_volume"], dtype=np.int64),
        "volume": np.ascontiguousarray(d["volume"], dtype=np.int64),
    }
