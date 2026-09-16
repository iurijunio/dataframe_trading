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
from core.engine import execution as exe  # noqa: E402


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


def test_calibrar_devolve_o_melhor_ja_visto_quando_o_alvo_e_inatingivel():
    """Silencioso por design (a assinatura continua `-> int`, a parte 2
    depende disso): quando a real é tão ativa que nem a maior tentativa
    bate o alvo, quem chama `calibrar` tem que conferir o número de trades
    obtido contra o alvo (ver docstring). A garantia que a função dá é
    outra: em no máximo `tentativas` chamadas, devolve o `n` de menor erro
    absoluto entre os testados — nunca um `n` pior do que algum já visto."""
    vistos = {}

    def rodar(n):
        saiu = min(int(n * 0.1), 50)         # satura bem abaixo do alvo
        vistos[n] = saiu
        return saiu

    resultado = aleatorio.calibrar(rodar, 700, tentativas=8)
    erro_resultado = abs(vistos[resultado] - 700)
    assert len(vistos) <= 8
    assert all(erro_resultado <= abs(v - 700) for v in vistos.values())


# --------------------------------------------- rodada de correção 1: p_valor
def test_p_valor_real_nao_finito_e_o_pior_caso_possivel():
    """Real NaN não pode aprovar por acidente: sem valor real para comparar,
    a única leitura honesta é o pior p-valor (1.0), não o melhor."""
    sorteados = np.array([1.0, 2.0, 3.0])
    assert aleatorio.p_valor(float("nan"), sorteados) == 1.0
    assert aleatorio.p_valor(float("inf"), sorteados) == 1.0


def test_p_valor_sorteio_nao_finito_conta_como_batendo_a_real():
    """Um sorteio que quebrou (motor devolveu NaN naquela repetição) não
    pode contar a favor da real — do lado conservador ele conta como se
    tivesse batido, para não inflar significância com sorteios que na
    prática falharam em vez de perderem."""
    sorteados = np.array([float("nan"), 1.0, 2.0])
    # só o NaN "bate" os 10.0 reais: (1 + 1) / (1 + 3)
    assert aleatorio.p_valor(10.0, sorteados) == pytest.approx(0.5)


# -------------------------------------------- rodada de correção 1: horarios
def test_horarios_com_pesos_que_nao_somam_1_sao_normalizados():
    """Pesos podem vir como contagem bruta do histograma real (ex.: quantas
    entradas em cada hora) em vez de fração — a estratégia normaliza pela
    soma, então o total sorteado continua sendo `n_sinais`, não milhares."""
    bars = _bars()
    s = aleatorio.EntradaAleatoria(10, {9: 40, 10: 60}, 1.0, 4).signals(bars, {})
    total = int(s.entry_long.sum()) + int(s.entry_short.sum())
    assert total == 10


def test_horarios_com_peso_negativo_leva_a_erro():
    with pytest.raises(ValueError):
        aleatorio.EntradaAleatoria(10, {9: -1, 10: 2}, 1.0, 4)


def test_horarios_com_soma_zero_leva_a_erro():
    with pytest.raises(ValueError):
        aleatorio.EntradaAleatoria(10, {9: 0, 10: 0}, 1.0, 4)


# ------------------------------- rodada de correção 1: hora de execução
def _bars_m1_dias(n_dias=3):
    """Dias inteiros (00:00-23:59) para o `resample` fechar grupos M15/H1
    redondos, sem sobra de minuto na borda do dia atrapalhando a contagem."""
    n = n_dias * 1440
    ts = np.arange(np.datetime64("2024-01-02T00:00", "s"),
                   np.datetime64("2024-01-02T00:00", "s") + np.timedelta64(n, "m"),
                   np.timedelta64(1, "m"))
    return {"ts": ts, "open": np.ones(n), "high": np.ones(n),
            "low": np.ones(n), "close": np.ones(n), "tick_volume": np.ones(n)}


def test_estratificacao_usa_a_hora_de_execucao_nao_a_do_rotulo_h1():
    """`execution.resample` carimba a barra com o FIM do período (ver o
    docstring de `resample`); o kernel só entra na barra M1 SEGUINTE ao
    sinal (`kernel.py`, seção "sinais desta barra, para a próxima"). Uma
    barra H1 rotulada 09:59 executa às 10:00, não às 9h — estratificar
    pela hora do RÓTULO atrasaria o histograma do sorteio em uma hora
    inteira em relação ao das entradas reais (que vem de `entry_ts`, a
    hora de execução)."""
    bars_h1, _, _ = exe.resample(_bars_m1_dias(3), 60)
    s = aleatorio.EntradaAleatoria(3, {10: 1.0}, 1.0, 9).signals(bars_h1, {})
    execucao = (bars_h1["ts"][s.entry_long] + np.timedelta64(1, "m")
               ).astype("datetime64[h]").astype(object)
    assert {h.hour for h in execucao} == {10}


def test_estratificacao_usa_a_hora_de_execucao_nao_a_do_rotulo_m15():
    """Mesma prova em M15: os quatro rótulos que EXECUTAM às 10h (09:59,
    10:14, 10:29, 10:44) não são os quatro cujo próprio RÓTULO tem hora 10
    (10:14, 10:29, 10:44, 10:59) — o último desliza a execução para as
    11h."""
    bars_m15, _, _ = exe.resample(_bars_m1_dias(3), 15)
    s = aleatorio.EntradaAleatoria(12, {10: 1.0}, 1.0, 9).signals(bars_m15, {})
    execucao = (bars_m15["ts"][s.entry_long] + np.timedelta64(1, "m")
               ).astype("datetime64[h]").astype(object)
    assert {h.hour for h in execucao} == {10}
