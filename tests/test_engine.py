"""Testes do motor.

O teste central e `test_serie_sintetica_bate_a_mao`: 11 barras montadas para
que os quatro trades sejam conferiveis com papel e caneta. Se o motor errar
qualquer regra de execucao - look-ahead, gap, ambiguidade, encerramento de
janela - este teste quebra num cenario que da para auditar linha por linha.

Cenario (janela 09:00-09:10, stop 200, alvo 300, sem slippage nem custo):

  i   hora    O       H       L       C       o que acontece
  0   09:00   100000  100010  99990   100000  sinal de COMPRA
  1   09:01   100000  100100  99950   100050  entra 100000 (stop 99800 alvo 100300)
  2   09:02   100050  100350  100000  100300  alvo tocado -> sai 100300   = +300
  3   09:03   100300  100320  100280  100300  sinal de VENDA
  4   09:04   100300  100400  100250  100350  entra 100300 (stop 100500 alvo 100000)
  5   09:05   100350  100550  100300  100500  stop tocado -> sai 100500   = -200
  6   09:06   100500  100510  100490  100500  sinal de COMPRA
  7   09:07   100500  100850  100250  100600  stop E alvo na mesma barra   = -200
                                              -> pessimista: stop, 1 barra ambigua
  8   09:08   100600  100610  100590  100600  sinal de COMPRA
  9   09:09   100600  100650  100550  100620  entra 100600 (stop 100400 alvo 100900)
 10   09:10   100620  100700  100600  100650  fim da janela -> sai no fechamento = +50

  total: +300 -200 -200 +50 = -50 pontos, 4 trades, 1 barra ambigua
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import metrics  # noqa: E402
from core.engine import kernel as K  # noqa: E402
from core.engine.execution import ExecutionProfile, backtest, run_strategy  # noqa: E402
from strategies.base import Signals, empty_like  # noqa: E402

WIN = {"tick_size": 5, "point_value": 0.20, "symbol": "TEST"}

OHLC = [
    (100000, 100010,  99990, 100000),
    (100000, 100100,  99950, 100050),
    (100050, 100350, 100000, 100300),
    (100300, 100320, 100280, 100300),
    (100300, 100400, 100250, 100350),
    (100350, 100550, 100300, 100500),
    (100500, 100510, 100490, 100500),
    (100500, 100850, 100250, 100600),
    (100600, 100610, 100590, 100600),
    (100600, 100650, 100550, 100620),
    (100620, 100700, 100600, 100650),
]
SINAIS_COMPRA = (0, 6, 8)
SINAIS_VENDA = (3,)


def cenario():
    n = len(OHLC)
    a = np.asarray(OHLC, dtype=np.int64)
    bars = {
        "ts": np.array(
            [np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]
        ),
        "open": a[:, 0].copy(), "high": a[:, 1].copy(),
        "low": a[:, 2].copy(), "close": a[:, 3].copy(),
    }
    s = empty_like(n)
    for i in SINAIS_COMPRA:
        s["entry_long"][i] = True
    for i in SINAIS_VENDA:
        s["entry_short"][i] = True
    return bars, Signals(**s)


def perfil(**kw) -> ExecutionProfile:
    """Janela de entrada e fechamento coincidem, para manter o cenario
    escrito a mao igual ao da rev. anterior."""
    base = dict(entrada_inicio="09:00", entrada_fim="09:10", fechamento="09:10",
                slippage_ticks=0, corretagem_por_contrato=0.0,
                emolumentos_por_contrato=0.0, contratos=1,
                capital_inicial=10_000.0, stop_pontos=200, alvo_pontos=300)
    base.update(kw)
    return ExecutionProfile(**base)


# ============================================================ criterio de aceite
def test_serie_sintetica_bate_a_mao():
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(stop_pontos=200, alvo_pontos=300), WIN)

    assert r.n_trades == 4
    assert r.ambiguous_bars == 1

    t = r.trades
    assert t["entry_i"].tolist() == [1, 4, 7, 9]
    assert t["exit_i"].tolist() == [2, 5, 7, 10]
    assert t["side"].tolist() == [1, -1, 1, 1]
    assert t["entry_px"].tolist() == [100000, 100300, 100500, 100600]
    assert t["exit_px"].tolist() == [100300, 100500, 100300, 100650]
    assert t["points"].tolist() == [300, -200, -200, 50]
    assert t["reason"].tolist() == [
        K.EXIT_TARGET, K.EXIT_STOP, K.EXIT_STOP, K.EXIT_CLOSE_TIME
    ]
    assert int(t["points"].sum()) == -50

    m = metrics.compute(r)
    assert m["pontos_liquidos"] == -50
    assert m["lucro_liquido"] == pytest.approx(-50 * 0.20)  # -R$ 10,00
    assert m["custo_total"] == 0.0
    assert m["trades"] == 4
    assert m["win_rate"] == pytest.approx(50.0)


# ==================================================== regras de execucao, uma a uma
def test_sinal_nunca_executa_na_propria_barra():
    """A trava de look-ahead e do motor. Toda entrada abre na barra SEGUINTE."""
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(stop_pontos=200, alvo_pontos=300), WIN)
    for entrada in r.trades["entry_i"]:
        assert entrada - 1 in (*SINAIS_COMPRA, *SINAIS_VENDA)
        assert r.trades["entry_px"][r.trades["entry_i"] == entrada][0] == \
            bars["open"][entrada]


def test_ambiguidade_intrabarra_e_pessimista_e_contada():
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(stop_pontos=200, alvo_pontos=300), WIN)
    # a barra 7 comporta stop e alvo; o motor assume o stop
    i = list(r.trades["exit_i"]).index(7)
    assert r.trades["reason"][i] == K.EXIT_STOP
    assert r.trades["points"][i] == -200
    assert r.ambiguous_bars == 1


def test_slippage_e_sempre_contra():
    """1 tick = 5 pontos, sempre desfavoravel.

    Detalhe que importa: stop e alvo sao ancorados no preco EFETIVO de
    entrada, nao no preco teorico. Quem entra 5 pontos pior tem stop e alvo
    5 pontos deslocados junto, entao a distancia em pontos e preservada e so
    a ponta de saida cobra o pedagio. Saidas a mercado (fim de janela, sinal)
    pagam as duas pontas.
    """
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(slippage_ticks=1), WIN)

    # compra: entra 100005, alvo vai para 100305, sai com -5 = 100300
    assert r.trades["entry_px"][0] == 100005
    assert r.trades["exit_px"][0] == 100300
    assert r.trades["points"][0] == 295  # 300 - 5 da saida

    # venda: entra 100295, stop vai para 100495, sai com +5 = 100500
    assert r.trades["entry_px"][1] == 100295
    assert r.trades["exit_px"][1] == 100500
    assert r.trades["points"][1] == -205  # -200 - 5 da saida

    # saida a mercado no fim da janela paga as duas pontas
    sem = backtest(bars, sig, perfil(), WIN)
    assert r.trades["points"][-1] == sem.trades["points"][-1] - 10


def test_gap_atravessa_o_stop_e_preenche_na_abertura():
    """Um stop de 200 pontos nao protege contra um gap de 500."""
    n = 3
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": np.array([100000, 100000, 99000], dtype=np.int64),
        "high": np.array([100010, 100100, 99100], dtype=np.int64),
        "low": np.array([99990, 99950, 98900], dtype=np.int64),
        "close": np.array([100000, 100050, 99000], dtype=np.int64),
    }
    s = empty_like(n)
    s["entry_long"][0] = True
    r = backtest(bars, Signals(**s, sl_points=200, tp_points=300), perfil(entrada_fim="09:02", fechamento="09:02"), WIN)

    assert r.trades["reason"][0] == K.EXIT_STOP
    # stop estava em 99800, mas a barra abriu em 99000
    assert r.trades["exit_px"][0] == 99000
    assert r.trades["points"][0] == -1000


def test_encerra_no_fim_da_janela():
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(stop_pontos=200, alvo_pontos=300), WIN)
    assert r.trades["reason"][-1] == K.EXIT_CLOSE_TIME
    assert r.trades["exit_i"][-1] == 10

    # janela mais curta: o ultimo trade nem chega a abrir
    curta = backtest(bars, sig, perfil(entrada_fim="09:08", fechamento="09:08"), WIN)
    assert curta.n_trades == 3


def test_janela_muda_o_resultado_sem_tocar_na_estrategia():
    """O que a camada 4 promete: mudar configuracao de execucao altera o
    resultado sem uma linha de estrategia mudar."""
    bars, sig = cenario()
    a = backtest(bars, sig, perfil(stop_pontos=200, alvo_pontos=300), WIN)
    b = backtest(bars, sig, perfil(entrada_inicio="09:04"), WIN)
    assert a.n_trades != b.n_trades


def test_direcao_permitida():
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(direcao="compra"), WIN)
    assert set(r.trades["side"].tolist()) == {1}
    assert r.n_trades == 3


def test_max_trades_por_dia():
    bars, sig = cenario()
    r = backtest(bars, sig, perfil(max_trades_dia=2), WIN)
    assert r.n_trades == 2


def test_stop_diario_bloqueia_o_resto_do_dia():
    bars, sig = cenario()
    # apos +300 e -200 o acumulado e +100; um stop diario de -100 so dispara
    # depois do terceiro trade (-200 -> acumulado -100)
    r = backtest(bars, sig, perfil(limite_perda_contrato=100 * 0.20), WIN)
    assert r.n_trades == 3
    assert int(r.trades["points"].sum()) == -100


def test_dias_da_semana():
    bars, sig = cenario()  # 2026-01-05 e uma segunda-feira
    assert backtest(bars, sig, perfil(dias_semana=(1,)), WIN).n_trades == 4
    assert backtest(bars, sig, perfil(dias_semana=(2, 3, 4, 5)), WIN).n_trades == 0


def test_breakeven_protege_a_operacao():
    n = 4
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": np.array([100000, 100000, 100000, 100000], dtype=np.int64),
        "high": np.array([100010, 100150, 100100, 100050], dtype=np.int64),
        "low": np.array([99990, 99950, 99900, 99900], dtype=np.int64),
        "close": np.array([100000, 100100, 100000, 99950], dtype=np.int64),
    }
    s = empty_like(n)
    s["entry_long"][0] = True
    p = perfil(entrada_fim="09:03", fechamento="09:03", alvo_pontos=900, stop_pontos=300, breakeven_pct=100/9)
    r = backtest(bars, Signals(**s, sl_points=300, tp_points=900), p, WIN)

    # a barra 1 subiu 150 pontos e acionou o breakeven; a barra 2 voltou ao
    # preco de entrada e encerrou no zero a zero em vez de -300
    assert r.trades["reason"][0] == K.EXIT_STOP
    assert r.trades["points"][0] == 0


# ================================================================ dimensionamento
def test_custos_por_ponta_e_por_contrato():
    bars, sig = cenario()
    p = perfil(corretagem_por_contrato=1.50, emolumentos_por_contrato=0.30, contratos=2)
    m = metrics.compute(backtest(bars, sig, p, WIN))
    # (1,50 + 0,30) x 2 contratos x 2 pontas x 4 trades
    assert m["custo_total"] == pytest.approx(1.80 * 2 * 2 * 4)
    assert m["lucro_bruto"] == pytest.approx(-50 * 0.20 * 2)
    assert m["lucro_liquido"] == pytest.approx(m["lucro_bruto"] - m["custo_total"])


def test_dois_modos_saem_do_mesmo_conjunto_de_trades():
    bars, sig = cenario()
    p = perfil(modo_posicao="contratos_fixos", contratos=1, risco_por_trade=200.0)
    r = backtest(bars, sig, p, WIN)

    lado_a_lado = metrics.compare_sizing(r)
    assert set(lado_a_lado) == {"contratos_fixos", "risco_fixo"}
    # mesmos trades, mesmos pontos - so o dinheiro muda
    assert lado_a_lado["contratos_fixos"]["trades"] == lado_a_lado["risco_fixo"]["trades"]
    assert (lado_a_lado["contratos_fixos"]["pontos_liquidos"]
            == lado_a_lado["risco_fixo"]["pontos_liquidos"])

    # risco de R$ 200 com stop de 200 pontos a R$ 0,20 = R$ 40 por contrato -> 5
    assert metrics.contracts_for(r, "risco_fixo").tolist() == [5, 5, 5, 5]
    assert lado_a_lado["risco_fixo"]["lucro_bruto"] == pytest.approx(-50 * 0.20 * 5)


# ==================================================================== estrategia
def test_cruzamento_de_medias_gera_sinais_coerentes():
    from strategies import setup_cruzamento as st
    from strategies.base import validate

    n = 300
    t = np.arange(n)
    # periodo de ~63 barras -> ~5 ciclos completos na amostra
    close = (100000 + 2000 * np.sin(t / 10)).astype(np.int64)
    bars = {"close": close}

    p = validate(st.params_schema, {"media_rapida": 5, "media_lenta": 20})
    sig = st.signals(bars, p)

    assert sig.entry_long.sum() >= 4
    assert sig.entry_short.sum() >= 4
    # nenhum sinal antes das duas medias estarem formadas
    assert not sig.entry_long[:20].any()
    assert not sig.entry_short[:20].any()
    # compra e venda nunca na mesma barra
    assert not (sig.entry_long & sig.entry_short).any()


def test_media_rapida_precisa_ser_menor():
    from strategies import setup_cruzamento as st

    with pytest.raises(ValueError, match="menor"):
        st.signals({"close": np.arange(50, dtype=np.int64)},
                   {"media_rapida": 20, "media_lenta": 10,
                    "stop_pontos": 200, "alvo_pontos": 300})


def test_parametro_fora_do_range_e_recusado():
    from strategies import setup_cruzamento as st
    from strategies.base import validate

    with pytest.raises(ValueError, match="acima do máximo"):
        validate(st.params_schema, {"media_lenta": 5000})
    with pytest.raises(ValueError, match="abaixo do mínimo"):
        validate(st.params_schema, {"media_rapida": 1})
    with pytest.raises(ValueError, match="desconhecido"):
        validate(st.params_schema, {"nao_existe": 3})


# ==================================================== janela x fechamento
def test_entrada_fecha_antes_da_posicao():
    """Janela de ENTRADA e horario de FECHAMENTO sao coisas diferentes:
    depois que as entradas param, a posicao aberta segue viva."""
    bars, sig = cenario()
    # entradas so ate 09:05; sinais de 09:06 e 09:08 nao abrem nada
    r = backtest(bars, sig, perfil(entrada_fim="09:05", fechamento="09:10"), WIN)
    assert r.n_trades == 2
    assert r.trades["entry_i"].tolist() == [1, 4]


def test_posicao_sobrevive_ao_fim_das_entradas():
    n = 9
    px = 100000
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": np.full(n, px, dtype=np.int64),
        "high": np.full(n, px + 20, dtype=np.int64),
        "low": np.full(n, px - 20, dtype=np.int64),
        "close": np.full(n, px + 10, dtype=np.int64),
    }
    s = empty_like(n)
    s["entry_long"][0] = True
    r = backtest(bars, Signals(**s),
                 perfil(entrada_fim="09:03", fechamento="09:08",
                        stop_pontos=5000, alvo_pontos=5000), WIN)
    assert r.n_trades == 1
    assert r.trades["entry_i"][0] == 1        # abriu dentro da janela
    assert r.trades["exit_i"][0] == 8         # e so encerrou no fechamento
    assert r.trades["reason"][0] == K.EXIT_CLOSE_TIME


# ============================================================== timeframe
def test_resample_agrega_certo_e_nao_olha_o_futuro():
    from core.engine.execution import resample

    n = 20
    o = np.arange(100000, 100000 + n * 10, 10, dtype=np.int64)
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": o, "high": o + 30, "low": o - 30, "close": o + 5,
        "tick_volume": np.ones(n, dtype=np.int64),
    }
    tf, fechada, fim = resample(bars, 5)

    assert len(tf["open"]) == 4
    assert fim.tolist() == [4, 9, 14, 19]
    assert tf["open"][0] == bars["open"][0]
    assert tf["close"][0] == bars["close"][4]
    assert tf["high"][0] == bars["high"][:5].max()
    assert tf["low"][0] == bars["low"][:5].min()
    assert tf["tick_volume"][0] == 5

    # antes do primeiro fechamento de M5 nao existe barra conhecida
    assert fechada[:4].tolist() == [-1, -1, -1, -1]
    assert fechada[4] == 0    # a primeira M5 fecha no minuto 4
    assert fechada[9] == 1


def test_sinal_de_m5_executa_no_minuto_seguinte():
    """Um robo em M5 nao espera a abertura do proximo candle de 5 minutos:
    ele manda a ordem no minuto seguinte ao fechamento da barra."""
    from core.engine.execution import expand_signal, resample

    n = 20
    o = np.full(n, 100000, dtype=np.int64)
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": o, "high": o + 30, "low": o - 30, "close": o,
        "tick_volume": np.ones(n, dtype=np.int64),
    }
    _tf, fechada, fim = resample(bars, 5)

    sinal_tf = np.zeros(4, dtype=bool)
    sinal_tf[1] = True                        # segunda barra de M5, fecha no minuto 9
    em_m1 = expand_signal(sinal_tf, fim, n)
    assert np.flatnonzero(em_m1).tolist() == [9]

    s = empty_like(n)
    s["entry_long"] = em_m1
    r = backtest(bars, Signals(**s),
                 perfil(entrada_fim="09:19", fechamento="09:19",
                        stop_pontos=5000, alvo_pontos=5000), WIN)
    assert r.trades["entry_i"][0] == 10       # minuto seguinte, nao o proximo M5


# ================================================================ gestao ATR
def test_stop_em_atr_varia_com_a_volatilidade():
    from core.engine.execution import atr

    n = 60
    rng = np.random.default_rng(7)
    passo = rng.integers(-40, 41, n).cumsum()
    close = (100000 + passo).astype(np.int64)
    amp = np.where(np.arange(n) < 30, 50, 250)     # volatilidade dobra na metade
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open": close.copy(), "high": close + amp, "low": close - amp,
        "close": close, "tick_volume": np.ones(n, dtype=np.int64),
    }
    s = empty_like(n)
    s["entry_long"][10] = True
    s["entry_long"][50] = True

    p = perfil(entrada_fim="09:59", fechamento="09:59", stop_tipo="atr",
               stop_atr_periodo=5, stop_atr_mult=2.0, alvo_pontos=100000)
    r = backtest(bars, Signals(**s), p, WIN)

    esperado = atr(bars, 5) * 2.0
    assert r.n_trades >= 1
    for k, i in enumerate(r.trades["entry_i"]):
        assert r.sl_at_entry[k] == int(esperado[i])
    # o stop do segundo trade, na parte volatil, e bem maior
    if r.n_trades == 2:
        assert r.sl_at_entry[1] > r.sl_at_entry[0] * 2


# =============================================================== protecoes
def test_stop_movel_trava_lucro():
    """Gatilho a 50% do alvo, trava a 20% do alvo a favor."""
    n = 6
    bars = {
        "ts": np.array([np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]),
        "open":  np.array([100000, 100000, 100100, 100400, 100300, 100200], dtype=np.int64),
        "high":  np.array([100010, 100100, 100450, 100500, 100350, 100250], dtype=np.int64),
        "low":   np.array([99990,  99950,  100050, 100250, 100100, 100000], dtype=np.int64),
        "close": np.array([100000, 100050, 100400, 100300, 100150, 100050], dtype=np.int64),
    }
    s = empty_like(n)
    s["entry_long"][0] = True
    p = perfil(entrada_fim="09:05", fechamento="09:05", stop_pontos=300,
               alvo_pontos=900, step_gatilho_pct=50, step_distancia_pct=20)
    r = backtest(bars, Signals(**s), p, WIN)

    # entra 100000; gatilho = 450 pontos (tocado na barra 3, high 100500);
    # o stop pula para 100000 + 180 = 100180 e e acionado na barra 5
    assert r.trades["reason"][0] == K.EXIT_STOP
    assert r.trades["exit_px"][0] == 100180
    assert r.trades["points"][0] == 180


# ========================================================= limites diarios
def test_limite_de_prejuizos_para_o_dia():
    bars, sig = cenario()
    # os trades sao +300, -200, -200, +50: o primeiro prejuizo encerra o dia
    r = backtest(bars, sig, perfil(max_prejuizos_dia=1), WIN)
    assert r.n_trades == 2
    assert int(r.trades["points"].sum()) == 100
    assert r.bloqueios == 1


def test_limite_de_ganho_para_o_dia():
    bars, sig = cenario()
    # R$ 50 por contrato a R$ 0,20/ponto = 250 pontos; o primeiro trade faz 300
    r = backtest(bars, sig, perfil(limite_ganho_contrato=50.0), WIN)
    assert r.n_trades == 1
    assert int(r.trades["points"].sum()) == 300


def test_filtro_minimo_de_operacoes():
    bars, sig = cenario()
    assert metrics.compute(backtest(bars, sig, perfil(min_operacoes=3), WIN))["passa_filtro"]
    assert not metrics.compute(
        backtest(bars, sig, perfil(min_operacoes=99), WIN))["passa_filtro"]


# =========================================================== espaco de busca
def test_grid_monta_o_espaco_de_busca():
    from strategies.base import grid

    schema = {"a": {"default": 5, "min": 1, "max": 100, "step": 1, "tipo": "int"},
              "b": {"default": 2, "min": 1, "max": 9, "step": 1, "tipo": "int"}}
    espaco = grid(schema, {"a": {"on": True, "de": 10, "passo": 5, "ate": 30},
                           "b": {"on": False, "valor": 7}})
    assert espaco["a"] == [10, 15, 20, 25, 30]
    assert espaco["b"] == [7]          # desligado: so o valor atual
