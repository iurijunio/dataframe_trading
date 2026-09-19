"""Testes da reversão à média pelo RSI curto (Connors).

A disciplina de sempre: séries montadas à mão, com a resposta conhecida
antes de rodar. Aqui isso importa dobrado — é uma estratégia que acerta
muito e erra grande, e um sinal nascido olhando o futuro ficaria escondido
atrás de uma taxa de acerto bonita.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies import reversao_rsi as R  # noqa: E402


def _barras(close):
    c = np.asarray(close, dtype=np.int64)
    return {"open": c, "high": c, "low": c, "close": c,
            "ts": (np.datetime64("2024-03-04T09:00", "m")
                   + np.arange(len(c)))}


def _params(**troca):
    p = {"periodo_rsi": 2, "limite_extremo": 10, "periodo_tendencia": 5,
         "periodo_saida": 3}
    p.update(troca)
    return p


# ------------------------------------------------------------------- RSI
def test_rsi_de_alta_pura_e_cem_e_de_baixa_pura_e_zero():
    """Sem nenhuma barra de queda não há o que dividir: o RSI é 100. É o
    caso que estoura a conta se a divisão não for tratada."""
    subindo = R.rsi(np.arange(100, 120, dtype=np.int64), 2)
    assert subindo[-1] == pytest.approx(100.0)
    caindo = R.rsi(np.arange(120, 100, -1, dtype=np.int64), 2)
    assert caindo[-1] == pytest.approx(0.0)


def test_rsi_de_mercado_parado_fica_no_meio():
    """Preço que não anda não é nem sobrecomprado nem sobrevendido."""
    assert R.rsi(np.full(20, 100, dtype=np.int64), 2)[-1] == pytest.approx(50.0)


def test_rsi_comeca_indefinido_ate_ter_janela_inteira():
    """Sinal com janela incompleta é sinal inventado."""
    r = R.rsi(np.array([100, 101, 102, 101], dtype=np.int64), 2)
    assert np.isnan(r[0]) and np.isnan(r[1])
    assert not np.isnan(r[2])


def test_rsi_de_caso_conhecido_no_papel():
    """Duas altas de 10 e uma baixa de 5, com período 2: a média das altas
    na última janela é 5, a das baixas é 2,5, então o RSI é 100 × 5/7,5."""
    r = R.rsi(np.array([100, 110, 120, 115], dtype=np.int64), 2)
    assert r[-1] == pytest.approx(100 * 5 / 7.5)


# --------------------------------------------------------------- sinais
def test_compra_no_extremo_de_baixa_dentro_da_tendencia_de_alta():
    """A regra de Connors: só compra a queda curta quando a tendência longa
    é de alta. A série sobe 10 por barra e dá duas quedas de 1 — queda curta
    o bastante para zerar o RSI sem derrubar a tendência."""
    close = list(range(100, 500, 10)) + [489, 488]
    s = R.signals(_barras(close), _params(periodo_tendencia=10))
    assert s.entry_long[-1] and not s.entry_short[-1]


def test_nao_compra_a_queda_contra_a_tendencia_de_baixa():
    """O mesmo extremo de RSI, com a tendência longa para baixo, não vira
    compra — é justamente aí que a reversão à média quebra."""
    close = list(range(500, 100, -10)) + [99, 98]
    s = R.signals(_barras(close), _params(periodo_tendencia=10))
    assert not s.entry_long[-1]


def test_vende_no_extremo_de_alta_dentro_da_tendencia_de_baixa():
    """O espelho: cai 10 por barra e repica 1 duas vezes."""
    close = list(range(500, 100, -10)) + [111, 112]
    s = R.signals(_barras(close), _params(periodo_tendencia=10))
    assert s.entry_short[-1] and not s.entry_long[-1]


def test_sem_filtro_de_tendencia_opera_os_dois_lados():
    """`periodo_tendencia = 0` desliga o filtro — é o que permite medir,
    na mineração, quanto ele vale."""
    # mercado parado e uma única barra de queda: é a primeira do extremo,
    # então ela entra mesmo sem tendência de alta nenhuma
    close = [100] * 20 + [99]
    s = R.signals(_barras(close), _params(periodo_tendencia=0))
    assert s.entry_long[-1]


def test_limite_mais_apertado_da_menos_sinal():
    """O limite é o dial principal: 10 é o Connors clássico, 1 quase não
    dispara. Se apertar não reduzir, o parâmetro não está sendo usado."""
    rng = np.random.default_rng(11)
    close = 100_000 + np.cumsum(rng.integers(-50, 51, 400)).astype(np.int64)
    solto = R.signals(_barras(close), _params(limite_extremo=40,
                                              periodo_tendencia=0))
    apertado = R.signals(_barras(close), _params(limite_extremo=1,
                                                 periodo_tendencia=0))
    assert solto.entry_long.sum() > apertado.entry_long.sum() > 0


def test_saida_e_a_volta_para_a_media_curta():
    """A saída de Connors não é alvo em pontos: é o preço voltar acima da
    média curta. Fecha rápido, com ganho pequeno — o perfil que faz o alvo
    ser mais curto que o stop."""
    close = [100] * 10 + [90, 92, 99, 101]
    s = R.signals(_barras(close), _params(periodo_saida=3,
                                          periodo_tendencia=0))
    assert s.exit_long[-1]
    assert not s.exit_long[11]          # ainda abaixo da média curta


def test_nenhum_sinal_olha_o_futuro():
    """O teste que mais importa nesta estratégia: cortar a série no meio
    não pode mudar nenhum sinal já emitido. Se mudar, algum indicador está
    lendo barra que ainda não aconteceu."""
    rng = np.random.default_rng(7)
    close = 100_000 + np.cumsum(rng.integers(-50, 51, 300)).astype(np.int64)
    inteiro = R.signals(_barras(close), _params(periodo_tendencia=20))
    cortado = R.signals(_barras(close[:200]), _params(periodo_tendencia=20))
    for campo in ("entry_long", "entry_short", "exit_long", "exit_short"):
        assert np.array_equal(getattr(inteiro, campo)[:200],
                              getattr(cortado, campo)), campo


def test_a_estrategia_nao_decide_stop_nem_alvo():
    """Stop e alvo são camada 4, do operador — é lá que o alvo curto e o
    stop largo desta estratégia são configurados. A estratégia que os
    definisse impediria a mineração de varrer essa razão."""
    s = R.signals(_barras(list(range(100, 140))), _params())
    assert s.sl_points == 0 and s.tp_points == 0


def test_contrato_da_estrategia():
    assert R.name and R.label
    assert set(R.params_schema) == {"periodo_rsi", "limite_extremo",
                                    "periodo_tendencia", "periodo_saida"}
    for meta in R.params_schema.values():
        assert {"label", "default", "min", "max", "step", "tipo"} <= set(meta)


def test_so_a_primeira_barra_do_extremo_entra():
    """Enquanto o RSI segue lá embaixo não é uma queda nova: é a mesma. Sem
    esta regra, cada barra do mesmo mergulho vira entrada assim que a
    anterior fecha, e o custo explode sem sinal novo nenhum."""
    # sobe forte e depois cai 1 ponto por barra, quatro vezes seguidas: o
    # RSI fica no chão nas quatro, mas o mergulho é um só
    close = list(range(100, 500, 10)) + [489, 488, 487, 486]
    s = R.signals(_barras(close), _params(periodo_tendencia=10))
    # o mergulho tem quatro barras e o RSI fica no chão em três delas
    assert s.entry_long.sum() == 1
    assert s.entry_long[-3] and not s.entry_long[-2:].any()
