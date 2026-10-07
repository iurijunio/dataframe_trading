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
from core import candidata  # noqa: E402
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


def test_calibracao_ok_com_piso_de_1_trade_em_janela_pequena():
    """Achado real em produção: com poucos trades no alvo, a relação entre
    sinais sorteados e trades que saem pode PULAR o alvo inteiro (24-26
    sinais dão 18 trades, 27+ dão 21 — nunca exatamente 19). `5% de 19` é
    0,95, ou seja, exige acerto exato — inatingível aqui mesmo com o
    `calibrar` achando o melhor `n` possível (erro mínimo = 1, não 0).
    Sem um piso absoluto de 1 trade de folga, toda janela com alvo abaixo
    de ~20 trades trava como pendente para sempre."""
    def rodar(janela, n_sinais, semente):
        n_trades = (n_sinais - 8) if n_sinais < 27 else (n_sinais - 6)
        n_trades = max(0, n_trades)
        return n_trades, float(n_trades)

    r = aleatorio.teste_janelas(rodar, ["w1"], [19], lucro_real=10.0,
                                n=5, semente=7)
    assert r["trades_obtidos"] == [18]     # o mais próximo possível de 19
    assert r["calibracao_ok"] is True


# ------------------------- calibração parcial (01/10/2026, walk-forward #25)
def _rodar_com_janela_teimosa(teimosas, lucro_sorteio=None):
    """Janelas em `teimosas` nunca chegam ao alvo (o motor satura em 50
    trades); as outras calibram de cara. `lucro_sorteio[janela]` é o lucro
    fixo que o sorteio dá ali (padrão: 1 por trade)."""
    def rodar(janela, n_sinais, semente):
        n_trades = min(n_sinais, 50) if janela in teimosas else n_sinais
        if lucro_sorteio is not None:
            return n_trades, lucro_sorteio[janela]
        return n_trades, float(n_trades)
    return rodar


def test_calibracao_parcial_conta_as_janelas_que_calibraram():
    rodar = _rodar_com_janela_teimosa({"w3"})
    r = aleatorio.teste_janelas(rodar, ["w1", "w2", "w3"], [100, 100, 700],
                                lucro_real=0.0, lucros_reais=[0.0, 0.0, 0.0],
                                n=5, semente=7)
    assert r["n_janelas"] == 3 and r["n_calibradas"] == 2
    assert r["calibracao_ok"] is False
    assert r["calibradas"] == [True, True, False]


def test_calibracao_parcial_mede_o_p_so_nas_janelas_que_calibraram():
    """A janela que não calibrou sai dos DOIS lados da conta: o sorteio
    dela não entra na soma, e o lucro real dela também não. Aqui o real de
    w1+w2 (150) bate o sorteio de w1+w2 (110) sempre — p mínimo. Somando o
    real de w3 (-1.000) ou o sorteio de w3 (+5.000), o p iria ao teto."""
    lucro_sorteio = {"w1": 10.0, "w2": 100.0, "w3": 5000.0}
    rodar = _rodar_com_janela_teimosa({"w3"}, lucro_sorteio)
    r = aleatorio.teste_janelas(rodar, ["w1", "w2", "w3"], [100, 100, 700],
                                lucro_real=-850.0,
                                lucros_reais=[50.0, 100.0, -1000.0],
                                n=20, semente=7)
    assert r["lucro_real"] == pytest.approx(150.0)
    assert r["sorteados"][0] == pytest.approx(110.0)
    assert r["p"] == pytest.approx(1 / 21)


def test_nenhuma_janela_calibrada_nao_da_p():
    rodar = _rodar_com_janela_teimosa({"w1", "w2"})
    r = aleatorio.teste_janelas(rodar, ["w1", "w2"], [700, 700],
                                lucro_real=10.0, lucros_reais=[5.0, 5.0],
                                n=5, semente=7)
    assert r["n_calibradas"] == 0 and r["p"] is None


def test_calibracao_parcial_sem_lucro_por_janela_nao_inventa_p():
    """Sem o lucro real de cada janela não há como tirar a janela que não
    calibrou do lado real — comparar o total real com o sorteio de só uma
    parte das janelas favoreceria a real à toa."""
    rodar = _rodar_com_janela_teimosa({"w2"})
    r = aleatorio.teste_janelas(rodar, ["w1", "w2"], [100, 700],
                                lucro_real=10.0, n=5, semente=7)
    assert r["n_calibradas"] == 1 and r["p"] is None


def test_todas_calibradas_continua_como_antes():
    r = aleatorio.teste_janelas(_rodar_barato(taxa=0.7), ["w1", "w2"],
                                [700, 700], lucro_real=10.0, n=5, semente=7)
    assert r["calibracao_ok"] is True
    assert r["n_janelas"] == 2 and r["n_calibradas"] == 2
    assert r["p"] == pytest.approx(1.0)


def test_com_lucro_por_janela_o_lado_real_e_sempre_a_soma_delas():
    """Com `lucros_reais`, o lado real é sempre a soma por janela — também
    quando todas calibram. Senão a base trocava entre o total dos trades do
    walk-forward (`lucro_real`) e a soma por step conforme a calibração, e
    os dois podem divergir (trade fora de qualquer janela válida)."""
    lucro_sorteio = {"w1": 10.0, "w2": 100.0}
    rodar = _rodar_com_janela_teimosa(set(), lucro_sorteio)
    r = aleatorio.teste_janelas(rodar, ["w1", "w2"], [100, 100],
                                lucro_real=99_999.0, lucros_reais=[50.0, 20.0],
                                n=10, semente=7)
    assert r["calibracao_ok"] is True
    assert r["lucro_real"] == pytest.approx(70.0)
    # real 70 < sorteio 110 em toda repetição: p no teto
    assert r["p"] == pytest.approx(1.0)


def test_janelas_e_alvos_de_tamanhos_diferentes_e_erro():
    with pytest.raises(ValueError):
        aleatorio.teste_janelas(_rodar_barato(), ["w1", "w2"], [700],
                                lucro_real=0.0, n=1, semente=1)


# --------------------------------------------- rodador_do_motor (motor de verdade)
def test_rodador_do_motor_bate_com_referencia_independente():
    """Teste de integração: a saída REAL de `rodar_janela` — não uma
    reconstrução à parte — tem que bater com uma referência calculada por
    fora (rodar o motor no histórico INTEIRO com a mesma semente e contar
    só as entradas dentro da janela).

    Isto corrige a versão anterior (rodada de correção 1): lá, "nenhum
    trade fora da janela" e "proporção de compra" eram conferidos sobre um
    `EntradaAleatoria` + `run_strategy` montados à parte, e da saída de
    `rodar_janela` só se conferiam os TIPOS do retorno. O revisor deslocou
    `i0`/`i1` em +2 dias dentro de `rodar_janela` (sem mexer em `de`/`ate`)
    e aquele teste continuou passando, porque nunca comparava com nada.

    A janela usada aqui NÃO começa no primeiro dia dos dados (`bars` cobre
    8 dias, a janela é o dia 5-7): só assim deslocar a fatia dentro de
    `rodar_janela` muda o resultado — numa janela que já começasse no
    início dos dados um deslocamento "pra trás" não teria pra onde ir e o
    bug passaria batido de qualquer jeito."""
    from core import metrics, wfa

    bars = _bars_m1_dias(n_dias=8)                  # 2024-01-02 .. 2024-01-09
    instrumento = {"point_value": 1.0, "tick_size": 1}
    perfil = exe.ExecutionProfile(entrada_inicio="00:00", entrada_fim="23:59",
                                  fechamento="23:59",
                                  dias_semana=(1, 2, 3, 4, 5, 6, 7))
    trades_reais = [
        {"step": 1, "entry_ts": "2024-01-06T10:05", "side": 1},
        {"step": 1, "entry_ts": "2024-01-07T10:10", "side": 1},
        {"step": 1, "entry_ts": "2024-01-07T14:00", "side": 1},
        {"step": 1, "entry_ts": "2024-01-07T11:00", "side": -1},
    ]
    janela = wfa.Janela(step=1,
                        is_de=np.datetime64("2024-01-02T00:00", "s"),
                        is_ate=np.datetime64("2024-01-06T00:00", "s"),
                        oos_de=np.datetime64("2024-01-06T00:00", "s"),
                        oos_ate=np.datetime64("2024-01-08T00:00", "s"))

    rodar_janela = aleatorio.rodador_do_motor(bars, None, perfil, instrumento,
                                              trades_reais)
    n_trades, lucro = rodar_janela(janela, n_sinais=200, semente=1)

    # referência independente: histórico INTEIRO (não a fatia que
    # `rodar_janela` monta), mesma semente/histograma/proporção, contando
    # só as entradas dentro da janela.
    de = np.datetime64(janela.oos_de).astype(bars["ts"].dtype)
    ate = np.datetime64(janela.oos_ate).astype(bars["ts"].dtype)
    horarios = aleatorio._histograma_horario_execucao(trades_reais)
    p_compra = aleatorio._proporcao_compra(trades_reais)
    estrategia = aleatorio.EntradaAleatoria(200, horarios, p_compra, 1,
                                            janela_valida=(de, ate))
    res = exe.run_strategy(bars, estrategia, {}, perfil, instrumento)
    dentro = (res.trades["entry_ts"] >= de) & (res.trades["entry_ts"] < ate)
    n_ref = int(dentro.sum())
    lucro_ref = float(metrics.monetize(res)["liquido"][dentro].sum())

    assert n_ref > 0                # o cenário precisa gerar trade de verdade
    assert n_trades == n_ref
    assert lucro == pytest.approx(lucro_ref)


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


def test_margem_de_adx_reproduz_o_resultado_do_historico_inteiro():
    """A margem do teste aleatório só conhecia o ATR. Com o filtro de ADX
    ligado e stop/alvo em PONTOS, a fatia começava exatamente em oos_de:
    as primeiras barras do dia tinham ADX NaN e bloqueavam entrada que o
    histórico completo (com o ADX aquecido dias antes) deixava entrar —
    e os dois lados do teste deixavam de disputar as mesmas faixas.

    Rango com limiar 101 deixa o caso nítido: depois de aquecido,
    `ADX < 101` é sempre verdade (o ADX não passa de 100), então a única
    diferença possível entre fatia e histórico é o aquecimento. M30 com
    período 40 de propósito: o aquecimento (78 × 30 = 2.340 min) passa do
    piso de margem (um pregão, 1.440) — a margem tem de olhar o ADX, não
    só acordar para o dia inteiro."""
    from core import metrics, wfa

    bars = _bars_com_volatilidade(n_dias=6, semente=0)
    instrumento = {"point_value": 1.0, "tick_size": 1}
    perfil = exe.ExecutionProfile(
        entrada_inicio="00:00", entrada_fim="23:59", fechamento="23:59",
        dias_semana=(1, 2, 3, 4, 5, 6, 7), timeframe="M30",
        filtro_adx="rango", adx_periodo=40, adx_limiar=101,
    )
    trades_reais = [
        {"step": 1, "entry_ts": "2024-01-04T00:05", "side": 1},
        {"step": 1, "entry_ts": "2024-01-05T00:10", "side": -1},
    ]
    janela = wfa.Janela(step=1,
                        is_de=np.datetime64("2024-01-02T00:00", "s"),
                        is_ate=np.datetime64("2024-01-04T00:00", "s"),
                        oos_de=np.datetime64("2024-01-04T00:00", "s"),
                        oos_ate=np.datetime64("2024-01-06T00:00", "s"))

    # mesma hora 0 concentrada do teste de ATR: é onde uma fatia sem
    # margem teria as primeiras barras do dia ainda com ADX NaN
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


def test_rodador_do_motor_recusa_trade_real_sem_step():
    """Aperto da rodada de correção 2: sem o campo `step` em algum trade
    real, a checagem da correção 2 não tem contra o que conferir — antes
    isso ficava mudo (`t.get("step")` vira `None`, desliga a proteção sem
    avisar); agora `rodador_do_motor` recusa na hora da montagem, porque
    `wfa_store.trades` sempre grava o `step` e um trade sem ele indica que
    quem chamou não filtrou (ou montou) os dados como devia."""
    bars = _bars_m1_dias(3)
    instrumento = {"point_value": 1.0, "tick_size": 1}
    perfil = exe.ExecutionProfile(entrada_inicio="00:00", entrada_fim="23:59",
                                  fechamento="23:59",
                                  dias_semana=(1, 2, 3, 4, 5, 6, 7))
    trades_sem_step = [{"entry_ts": "2024-01-02T10:05", "side": 1}]

    with pytest.raises(ValueError):
        aleatorio.rodador_do_motor(bars, None, perfil, instrumento,
                                   trades_sem_step)


# ------------------------------------------------------------ portao_aleatorio
def test_portao_aleatorio_passa_com_p_baixo():
    r = candidata.portao_aleatorio({"p": 0.02, "calibracao_ok": True})
    assert r["ok"] and r["critico"] and r["valor"] == 0.02


def test_portao_aleatorio_reprova_com_p_alto():
    r = candidata.portao_aleatorio({"p": 0.4, "calibracao_ok": True})
    assert r["ok"] is False and r["critico"]


def test_portao_aleatorio_no_limite_passa():
    r = candidata.portao_aleatorio({"p": 0.05, "calibracao_ok": True})
    assert r["ok"]


def test_portao_aleatorio_sem_resultado_fica_pendente():
    """`{}` é o que `teste_janelas` devolve quando a thread é interrompida
    antes de terminar — falta de dado, não reprovação."""
    r = candidata.portao_aleatorio({})
    assert r["ok"] is None and r["critico"]


def test_portao_aleatorio_com_erro_mostra_o_motivo():
    r = candidata.portao_aleatorio({"erro": "motor indisponível"})
    assert r["ok"] is None and r["valor"] == "motor indisponível"


def test_portao_aleatorio_calibracao_em_menos_da_metade_vira_alerta():
    """O sorteio só imitou o número de trades em 4 de 10 janelas: a medida
    vale pouco, mas ficar pendente para sempre travava a gravação do plano
    sem nada que o operador pudesse fazer. Vira alerta — não trava o
    veredito, e o motivo diz quantas janelas mediu."""
    r = candidata.portao_aleatorio({"p": 0.01, "calibracao_ok": False,
                                    "n_janelas": 10, "n_calibradas": 4})
    assert r["ok"] is False and r["critico"] is False
    assert "4 de 10 janelas" in r["valor"]


def test_portao_aleatorio_calibracao_em_metade_ou_mais_mede():
    r = candidata.portao_aleatorio({"p": 0.01, "calibracao_ok": False,
                                    "n_janelas": 10, "n_calibradas": 5})
    assert r["ok"] is True and r["critico"] is True and r["valor"] == 0.01
    assert "5 de 10 janelas" in r["exigido"]
    assert "5 de 10 janelas" in r["dica"]
    ruim = candidata.portao_aleatorio({"p": 0.30, "calibracao_ok": False,
                                       "n_janelas": 10, "n_calibradas": 9})
    assert ruim["ok"] is False and ruim["critico"] is True
    assert "9 de 10 janelas" in ruim["exigido"]


def test_portao_aleatorio_limiar_da_metade_com_janelas_impares():
    """3 de 7 é menos da metade (alerta); 4 de 7 é mais (mede)."""
    tres = candidata.portao_aleatorio({"p": 0.01, "n_janelas": 7,
                                       "n_calibradas": 3})
    quatro = candidata.portao_aleatorio({"p": 0.01, "n_janelas": 7,
                                         "n_calibradas": 4})
    assert tres["critico"] is False and tres["ok"] is False
    assert quatro["critico"] is True and quatro["ok"] is True


def test_portao_aleatorio_nenhuma_calibrada_vira_alerta():
    r = candidata.portao_aleatorio({"p": None, "calibracao_ok": False,
                                    "n_janelas": 1, "n_calibradas": 0})
    assert r["ok"] is False and r["critico"] is False
    assert "0 de 1 janela" in r["valor"]


def test_portao_aleatorio_sem_contagem_e_calibracao_ruim_vira_alerta():
    """Resultado sem `n_janelas` (formato antigo) e calibração ruim: alerta,
    não pendente eterno — e sem inventar uma contagem que não veio."""
    r = candidata.portao_aleatorio({"p": 0.01, "calibracao_ok": False})
    assert r["ok"] is False and r["critico"] is False
    assert "alguma janela" in r["valor"]


def test_portao_aleatorio_sem_janela_nenhuma_fica_pendente():
    """Zero janelas não é "o sorteio não imitou": não houve sorteio. Falta
    de dado fica pendente, não vira alerta "0 de 0 janelas"."""
    r = candidata.portao_aleatorio({"p": None, "calibracao_ok": True,
                                    "n_janelas": 0, "n_calibradas": 0})
    assert r["ok"] is None and r["critico"] is True
    assert "nenhuma janela" in r["valor"]


def test_portao_aleatorio_todas_calibradas_nao_fala_em_janelas():
    r = candidata.portao_aleatorio({"p": 0.02, "calibracao_ok": True,
                                    "n_janelas": 10, "n_calibradas": 10})
    assert r["ok"] is True and "janelas" not in r["exigido"]


def test_portao_aleatorio_exigido_sem_numero_cru():
    r = candidata.portao_aleatorio({"p": 0.02, "calibracao_ok": True},
                                   maximo=0.10)
    assert "10%" in r["exigido"]
    assert "0.1" not in r["exigido"]
