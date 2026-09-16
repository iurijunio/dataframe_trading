"""Testes da entrada aleatória (portão 3).

O teste é desconfortável de propósito: se o sorteio vai tão bem quanto o
sinal, o mérito é da gestão de saída, não da estratégia.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import aleatorio  # noqa: E402


def _bars(n=2000):
    ts = np.arange(np.datetime64("2024-01-02T09:00", "s"),
                   np.datetime64("2024-01-02T09:00", "s") + np.timedelta64(n, "m"),
                   np.timedelta64(1, "m"))
    return {"ts": ts, "open": np.ones(n), "high": np.ones(n),
            "low": np.ones(n), "close": np.ones(n)}


def test_sorteia_o_numero_pedido_de_sinais():
    bars = _bars()
    e = aleatorio.EntradaAleatoria(n_sinais=50, horarios=None,
                                   p_compra=1.0, semente=3)
    s = e.signals(bars, {})
    assert int(s.entry_long.sum()) == 50
    assert int(s.entry_short.sum()) == 0


def test_mesma_semente_da_o_mesmo_sorteio():
    bars = _bars()
    a = aleatorio.EntradaAleatoria(30, None, 1.0, 7).signals(bars, {})
    b = aleatorio.EntradaAleatoria(30, None, 1.0, 7).signals(bars, {})
    assert np.array_equal(a.entry_long, b.entry_long)


def test_respeita_a_proporcao_de_lado():
    s = aleatorio.EntradaAleatoria(100, None, 0.7, 1).signals(_bars(), {})
    assert 60 <= int(s.entry_long.sum()) <= 80
    assert int(s.entry_long.sum()) + int(s.entry_short.sum()) == 100


def test_estratifica_pelo_histograma_de_horario():
    """Sorteio uniforme mede a volatilidade em U do WIN, não o sinal: se a
    estratégia real só entra na abertura, o sorteio também tem que entrar."""
    bars = _bars()
    horarios = {9: 1.0}                      # tudo na primeira hora
    s = aleatorio.EntradaAleatoria(40, horarios, 1.0, 5).signals(bars, {})
    hora = bars["ts"][s.entry_long].astype("datetime64[h]").astype(object)
    assert {h.hour for h in hora} == {9}


def test_calibrar_acha_o_numero_de_sinais_que_da_o_alvo_de_trades():
    """600 sinais deram 497 trades e 3.000 deram 1.885 — a taxa não é fixa,
    então o número de sinais tem que ser procurado."""
    def rodar(n):                            # 70% dos sinais viram trade
        return int(n * 0.7)
    assert abs(aleatorio.calibrar(rodar, 700) - 1000) <= 50


def test_p_valor_de_permutacao_nunca_e_zero():
    """(1+k)/(1+B): com B sorteios, zero não é uma evidência possível."""
    sorteados = np.array([1.0, 2.0, 3.0, 4.0])
    assert aleatorio.p_valor(10.0, sorteados) == pytest.approx(1 / 5)
    assert aleatorio.p_valor(2.5, sorteados) == pytest.approx(3 / 5)


# --------------------------------------------------------- cuidado 1: rateio
def test_sorteio_estratificado_soma_exatamente_quando_ha_candidatos_de_sobra():
    """3 horas de peso 1/3 e 10 sinais dariam 3+3+3=9 num arredondamento
    ingênuo. A sobra tem que ir para alguma hora até o total bater — desde
    que existam candidatos de sobra em cada hora, o que aqui existe (60
    barras por hora, ver `_bars`)."""
    bars = _bars()
    horarios = {9: 1 / 3, 10: 1 / 3, 11: 1 / 3}
    s = aleatorio.EntradaAleatoria(10, horarios, 1.0, 2).signals(bars, {})
    assert int(s.entry_long.sum()) + int(s.entry_short.sum()) == 10


def test_sorteio_estratificado_encolhe_quando_a_hora_nao_tem_candidatos_suficientes():
    """Quando a hora pedida tem menos barras do que a cota, o sorteio não
    pode inventar barra: o total encolhe, e é `calibrar` (pedindo mais
    sinais na próxima tentativa) quem corrige o número de trades."""
    bars = _bars(n=5)                        # só 5 barras, todas às 9h
    s = aleatorio.EntradaAleatoria(10, {9: 1.0}, 1.0, 2).signals(bars, {})
    total = int(s.entry_long.sum()) + int(s.entry_short.sum())
    assert total == 5


# --------------------------------------------------- cuidado 2: sem convergir
def test_calibrar_termina_mesmo_quando_o_alvo_nunca_e_alcancado():
    """Uma estratégia real tão ativa que nem 4x o alvo em sinais entrega o
    número de trades pedido (ex.: o motor satura por causa do limite diário)
    não pode girar para sempre: `calibrar` tem que parar em `tentativas`
    chamadas e devolver o melhor que já viu."""
    chamadas = []

    def rodar(n):
        chamadas.append(n)
        return min(int(n * 0.1), 50)          # nunca chega a 700 trades

    resultado = aleatorio.calibrar(rodar, 700, tentativas=8)
    assert len(chamadas) == 8
    assert isinstance(resultado, int)
