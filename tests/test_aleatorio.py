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


# ------------------------------------------------------ teste_janelas (portão 3)
def _rodar_barato(taxa=0.7, lucro_por_trade=1.0):
    """`rodar_janela` falso: `taxa` dos sinais viram trade, cada trade dá
    `lucro_por_trade` de lucro — barato o bastante para 1.000 repetições x
    várias janelas rodarem em milissegundos no teste."""
    def rodar(janela, n_sinais, semente):
        n_trades = int(n_sinais * taxa)
        return n_trades, n_trades * lucro_por_trade
    return rodar


def test_sorteio_que_sempre_perde_da_p_pequeno():
    """Se o sorteio nunca chega perto do lucro real, `p` tem que ficar
    pequeno — é o caso em que a estratégia claramente bate o acaso."""
    rodar = _rodar_barato(lucro_por_trade=1.0)     # sorteio sempre lucra ~700
    r = aleatorio.teste_janelas(rodar, ["w1"], [700], lucro_real=10_000.0,
                                n=50, semente=7)
    assert r["p"] == pytest.approx(1 / 51)         # nenhum sorteio bate


def test_sorteio_igual_ao_real_da_p_alto():
    """Se o sorteio empata com a real toda vez, `p` tem que ficar no teto —
    não há evidência de que a real bate o acaso. `lucro_real` é o que a
    PRÓPRIA calibração desta janela produz (a calibração raramente bate o
    alvo de trades exatamente, só dentro de 5% — ver `calibrar`), não o
    alvo de trades em si."""
    rodar = _rodar_barato(taxa=1.0, lucro_por_trade=1.0)
    n_sinais = aleatorio.calibrar(lambda n: rodar("w1", n, 7)[0], 700)
    _, lucro_calibrado = rodar("w1", n_sinais, 7)

    r = aleatorio.teste_janelas(rodar, ["w1"], [700], lucro_real=lucro_calibrado,
                                n=50, semente=7)
    assert r["p"] == pytest.approx(1.0)


def test_calibracao_chamada_uma_vez_por_janela_nao_por_repeticao():
    """Se a calibração rodasse dentro do laço de repetições, o número de
    chamadas com a semente de calibração escalaria com `n`. Aqui a semente
    de calibração (`semente`, nunca `semente + 1 + rep`) só pode aparecer
    `calibrar.tentativas` vezes por janela, não importa quantas repetições
    rodam depois."""
    chamadas = []

    def rodar(janela, n_sinais, semente):
        chamadas.append(semente)
        n_trades = int(n_sinais * 0.7)
        return n_trades, float(n_trades)

    janelas, alvos = ["w1", "w2"], [700, 700]

    chamadas.clear()
    aleatorio.teste_janelas(rodar, janelas, alvos, lucro_real=100.0,
                            n=5, semente=7)
    calib_5 = sum(1 for s in chamadas if s == 7)

    chamadas.clear()
    aleatorio.teste_janelas(rodar, janelas, alvos, lucro_real=100.0,
                            n=200, semente=7)
    calib_200 = sum(1 for s in chamadas if s == 7)

    assert calib_5 == calib_200
    assert 0 < calib_5 <= len(janelas) * 8    # <= tentativas de calibrar, por janela


def test_soma_o_lucro_de_todas_as_janelas_nao_so_da_ultima():
    """Cada repetição soma o lucro sorteado de TODAS as janelas — se
    somasse só a última, o resultado ficaria preso ao lucro daquela janela
    e ignoraria as outras duas."""
    lucro_fixo = {"w1": 10.0, "w2": 100.0, "w3": 1000.0}

    def rodar(janela, n_sinais, semente):
        return n_sinais, lucro_fixo[janela]        # trades = sinais: calibra de cara

    r = aleatorio.teste_janelas(rodar, ["w1", "w2", "w3"], [5, 5, 5],
                                lucro_real=0.0, n=3, semente=1)
    assert r["sorteados"][0] == pytest.approx(sum(lucro_fixo.values()))


def test_parar_interrompe_e_devolve_dict_vazio():
    r = aleatorio.teste_janelas(_rodar_barato(), ["w1"], [700],
                                lucro_real=700.0, n=1000, semente=7,
                                parar=lambda: True)
    assert r == {}


def test_progresso_e_chamado_a_cada_repeticao():
    feitos = []
    aleatorio.teste_janelas(_rodar_barato(), ["w1"], [700], lucro_real=700.0,
                            n=4, semente=7, progresso=lambda f, t: feitos.append((f, t)))
    assert feitos == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_calibracao_ok_falso_quando_alvo_e_inatingivel():
    """A real tão ativa que nem a maior tentativa de `calibrar` bate o alvo
    (motor satura, ex.: limite diário) não pode aprovar a calibração em
    silêncio."""
    def rodar(janela, n_sinais, semente):
        n_trades = min(int(n_sinais * 0.1), 50)    # nunca chega a 700 trades
        return n_trades, float(n_trades)

    r = aleatorio.teste_janelas(rodar, ["w1"], [700], lucro_real=10.0,
                                n=5, semente=7)
    assert r["calibracao_ok"] is False


def test_calibracao_ok_verdadeiro_quando_todas_as_janelas_batem_o_alvo():
    r = aleatorio.teste_janelas(_rodar_barato(taxa=0.7), ["w1", "w2"],
                                [700, 700], lucro_real=10.0, n=5, semente=7)
    assert r["calibracao_ok"] is True


def test_janelas_e_alvos_de_tamanhos_diferentes_e_erro():
    with pytest.raises(ValueError):
        aleatorio.teste_janelas(_rodar_barato(), ["w1", "w2"], [700],
                                lucro_real=0.0, n=1, semente=1)


# --------------------------------------------- rodador_do_motor (motor de verdade)
def test_rodador_do_motor_liga_o_sorteio_ao_motor_de_verdade():
    """Teste de integração curto: garante que a fatia por janela OOS, o
    histograma de horário e a proporção compra/venda vindos dos trades
    reais chegam inteiros até `run_strategy` e voltam sem quebrar — o
    mérito estatístico já está coberto pelos testes de `teste_janelas` com
    `rodar_janela` falso.

    Reforço da rodada de correção 1: confere também, inspecionando os
    trades do mesmo mecanismo que `rodar_janela` usa por dentro (a
    interface pública só devolve o resumo `(n_trades, lucro)`), que nenhum
    trade sorteado entra fora da janela e que a proporção de compra do
    sorteio acompanha a dos trades reais (aqui, 3 compras em 4 = 0,75)."""
    from core import wfa

    bars = _bars_m1_dias(3)
    instrumento = {"point_value": 1.0, "tick_size": 1}
    perfil = exe.ExecutionProfile(entrada_inicio="00:00", entrada_fim="23:59",
                                  fechamento="23:59",
                                  dias_semana=(1, 2, 3, 4, 5, 6, 7))
    trades_reais = [
        {"step": 1, "entry_ts": "2024-01-02T10:05", "side": 1},
        {"step": 1, "entry_ts": "2024-01-03T10:10", "side": 1},
        {"step": 1, "entry_ts": "2024-01-03T14:00", "side": 1},
        {"step": 1, "entry_ts": "2024-01-03T11:00", "side": -1},
    ]
    janela = wfa.Janela(step=1,
                        is_de=np.datetime64("2024-01-01T00:00", "s"),
                        is_ate=np.datetime64("2024-01-02T00:00", "s"),
                        oos_de=np.datetime64("2024-01-02T00:00", "s"),
                        oos_ate=np.datetime64("2024-01-05T00:00", "s"))

    rodar_janela = aleatorio.rodador_do_motor(bars, None, perfil, instrumento,
                                              trades_reais)
    n_trades, lucro = rodar_janela(janela, n_sinais=200, semente=1)
    assert isinstance(n_trades, int)
    assert isinstance(lucro, float)

    # reforço: mesmo mecanismo de `rodar_janela`, mas inspecionando os
    # trades individuais em vez do resumo agregado.
    de = np.datetime64(janela.oos_de).astype(bars["ts"].dtype)
    ate = np.datetime64(janela.oos_ate).astype(bars["ts"].dtype)
    horarios = aleatorio._histograma_horario_execucao(trades_reais)
    p_compra = aleatorio._proporcao_compra(trades_reais)
    assert p_compra == pytest.approx(0.75)

    estrategia = aleatorio.EntradaAleatoria(200, horarios, p_compra, 1,
                                            janela_valida=(de, ate))
    res = exe.run_strategy(bars, estrategia, {}, perfil, instrumento)
    assert res.n_trades > 0
    assert np.all(res.trades["entry_ts"] >= de)
    assert np.all(res.trades["entry_ts"] < ate)
    fracao_compra = float((res.trades["side"] == 1).mean())
    assert 0.55 <= fracao_compra <= 0.95   # p_compra real é 0,75


def _bars_com_volatilidade(n_dias=6, semente=0):
    """Preço em passeio aleatório (não fica achatado como `_bars_m1_dias`) —
    sem variação de preço o ATR seria sempre 0 e não haveria como distinguir
    aquecido de não aquecido."""
    n = n_dias * 1440
    ts = np.arange(np.datetime64("2024-01-01T00:00", "s"),
                   np.datetime64("2024-01-01T00:00", "s") + np.timedelta64(n, "m"),
                   np.timedelta64(1, "m"))
    rng = np.random.default_rng(semente)
    passos = rng.integers(-5, 6, size=n).astype(np.float64)
    close = 100_000.0 + np.cumsum(passos)
    aberto = close - passos
    alta = np.maximum(aberto, close) + rng.integers(1, 6, size=n)
    baixa = np.minimum(aberto, close) - rng.integers(1, 6, size=n)
    return {"ts": ts, "open": aberto, "high": alta, "low": baixa,
            "close": close, "tick_volume": np.ones(n)}


def test_margem_de_atr_reproduz_o_resultado_do_historico_inteiro():
    """Correção 1: sem margem de aquecimento, o ATR das primeiras barras da
    fatia vale 0 (sem stop, sem alvo) — uma gestão que a real nunca operou.
    `execution.atr` é média móvel simples: uma vez aquecido, o valor em
    cada barra só depende das `periodo` barras anteriores a ela, nunca de
    barras mais antigas — então rodar com a margem tem que reproduzir
    EXATAMENTE o resultado de rodar o histórico inteiro e filtrar por
    dentro da janela, não uma aproximação."""
    from core import metrics, wfa

    bars = _bars_com_volatilidade(n_dias=6, semente=0)
    instrumento = {"point_value": 1.0, "tick_size": 1}
    perfil = exe.ExecutionProfile(
        entrada_inicio="00:00", entrada_fim="23:59", fechamento="23:59",
        dias_semana=(1, 2, 3, 4, 5, 6, 7),
        stop_tipo="atr", stop_atr_periodo=14, stop_atr_mult=1.5,
        alvo_tipo="atr", alvo_atr_periodo=14, alvo_atr_mult=3.0,
    )
    # os dois trades reais concentram o histograma na hora 0 — é exatamente
    # a hora onde a fatia SEM margem tem o defeito (as primeiras 13 barras
    # do dia 1 do OOS não têm as 14 barras anteriores que o ATR pede). Um
    # histograma disperso pelo dia (como o do outro teste de integração)
    # não passaria perto dessas barras e não pegaria o defeito.
    trades_reais = [
        {"step": 1, "entry_ts": "2024-01-04T00:05", "side": 1},
        {"step": 1, "entry_ts": "2024-01-05T00:10", "side": -1},
    ]
    janela = wfa.Janela(step=1,
                        is_de=np.datetime64("2024-01-02T00:00", "s"),
                        is_ate=np.datetime64("2024-01-04T00:00", "s"),
                        oos_de=np.datetime64("2024-01-04T00:00", "s"),
                        oos_ate=np.datetime64("2024-01-06T00:00", "s"))

    # a hora 0 tem 60 barras candidatas por dia (2 dias no OOS = 120); pedir
    # 110 sinais escolhe quase todas, incluindo (com prob. praticamente 1)
    # as 13 primeiras barras do dia 1 — a zona vulnerável sem margem.
    N_SINAIS = 110
    rodar_janela = aleatorio.rodador_do_motor(bars, None, perfil, instrumento,
                                              trades_reais)
    n_fatia, lucro_fatia = rodar_janela(janela, n_sinais=N_SINAIS, semente=3)

    de = np.datetime64(janela.oos_de).astype(bars["ts"].dtype)
    ate = np.datetime64(janela.oos_ate).astype(bars["ts"].dtype)
    horarios = aleatorio._histograma_horario_execucao(trades_reais)
    p_compra = aleatorio._proporcao_compra(trades_reais)
    estrategia = aleatorio.EntradaAleatoria(N_SINAIS, horarios, p_compra, 3,
                                            janela_valida=(de, ate))
    res = exe.run_strategy(bars, estrategia, {}, perfil, instrumento)
    dentro = (res.trades["entry_ts"] >= de) & (res.trades["entry_ts"] < ate)
    n_ref = int(dentro.sum())
    lucro_ref = float(metrics.monetize(res)["liquido"][dentro].sum())

    assert n_fatia > 0 and n_ref > 0     # o cenário precisa gerar trade
    assert n_fatia == n_ref
    assert lucro_fatia == pytest.approx(lucro_ref)


def test_rodador_do_motor_rejeita_janela_de_outro_step():
    """Correção 2: `rodador_do_motor` é montado com o perfil e o histograma
    de UMA janela (aqui, step 1). Chamar `rodar_janela` com a janela de
    outro step aplicaria esse perfil e histograma errados sem aviso — tem
    que recusar."""
    from core import wfa

    bars = _bars_m1_dias(3)
    instrumento = {"point_value": 1.0, "tick_size": 1}
    perfil = exe.ExecutionProfile(entrada_inicio="00:00", entrada_fim="23:59",
                                  fechamento="23:59",
                                  dias_semana=(1, 2, 3, 4, 5, 6, 7))
    trades_reais = [{"step": 1, "entry_ts": "2024-01-02T10:05", "side": 1}]
    rodar_janela = aleatorio.rodador_do_motor(bars, None, perfil, instrumento,
                                              trades_reais)

    janela_de_outro_step = wfa.Janela(
        step=2,
        is_de=np.datetime64("2024-01-01T00:00", "s"),
        is_ate=np.datetime64("2024-01-02T00:00", "s"),
        oos_de=np.datetime64("2024-01-02T00:00", "s"),
        oos_ate=np.datetime64("2024-01-05T00:00", "s"))

    with pytest.raises(ValueError):
        rodar_janela(janela_de_outro_step, n_sinais=10, semente=1)
