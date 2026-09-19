"""Camada 4 travada: o stop e o alvo não mudam a cada reotimização.

Decisão do usuário (18/09/2026). Esses campos protegem o capital, não geram
lucro: reotimizá-los faz o stop aprender o passado, e mudaria o disjuntor do
plano de operação a cada seis meses.

A trava é no valor da PRIMEIRA janela, nunca no melhor do período inteiro —
o melhor do período só é conhecido depois que o período acabou.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import wfa  # noqa: E402

CAP = 10_000.0
EXEC = {"stop_pontos"}
# "ulcer" com curvas só de lucro dá índice zero nas duas combinações, e o
# desempate é o lucro: a escolha de cada janela fica conferível no papel, que
# é o que estes testes precisam medir — a trava, não a inteligência.
COMO = "ulcer"


def combo(params: dict, por_mes: dict[str, float], trades_mes: int = 12):
    ts, liq = [], []
    for mes, valor in por_mes.items():
        base = np.datetime64(f"{mes}-02T10:00", "s")
        for k in range(trades_mes):
            ts.append(base + np.timedelta64(k, "D"))
            liq.append(float(valor))
    ordem = np.argsort(np.array(ts))
    entrada = np.array(ts)[ordem]
    return {"params": params, "entry_ts": entrada,
            "exit_ts": entrada + np.timedelta64(3, "h"),
            "liquido": np.array(liq)[ordem]}


def meses(de: str, ate: str, valor: float) -> dict[str, float]:
    a, b = np.datetime64(de, "M"), np.datetime64(ate, "M")
    return {str(a + np.timedelta64(k, "M")): valor
            for k in range(int((b - a).astype(int)))}


def _cenario(stop_a=300, stop_b=500):
    """Duas combinações que trocam de lugar no meio do caminho.

    A de stop 300 é a melhor no primeiro IS; a de stop 500 é a melhor no
    segundo. Solta, a segunda janela troca o stop; travada, não pode.
    """
    a = combo({"periodo": 10, "stop_pontos": stop_a},
              {**meses("2021-03", "2022-09", 10.0),
               **meses("2022-09", "2024-03", 1.0)})
    b = combo({"periodo": 10, "stop_pontos": stop_b},
              {**meses("2021-03", "2022-09", 1.0),
               **meses("2022-09", "2024-03", 100.0)})
    janelas = wfa.montar_janelas("2021-03-16", "2024-03-13", 18, 6)
    return [a, b], [j for j in janelas if not j.deploy]


def test_travada_a_janela_seguinte_nao_troca_o_stop():
    """Sem trava, a segunda janela escolhe o outro stop porque ele foi melhor
    no IS dela. Com trava, o stop da primeira janela vale para todas."""
    combos, janelas = _cenario()
    soltos = wfa.rodar(combos, janelas, CAP, COMO)
    assert [p.params["stop_pontos"] for p in soltos][:2] == [300, 500]

    travados = wfa.rodar(combos, janelas, CAP, COMO,
                         travar_execucao=EXEC)
    assert {p.params["stop_pontos"] for p in travados} == {300}


def test_travada_nao_prende_o_parametro_da_estrategia():
    """Só a camada 4 trava. O parâmetro da estratégia continua sendo
    reotimizado janela a janela — é para isso que o walk-forward existe."""
    a = combo({"periodo": 10, "stop_pontos": 300},
              {**meses("2021-03", "2022-09", 10.0),
               **meses("2022-09", "2024-03", 1.0)})
    b = combo({"periodo": 20, "stop_pontos": 300},
              {**meses("2021-03", "2022-09", 1.0),
               **meses("2022-09", "2024-03", 100.0)})
    janelas = [j for j in wfa.montar_janelas("2021-03-16", "2024-03-13", 18, 6)
               if not j.deploy]
    passos = wfa.rodar([a, b], janelas, CAP, COMO,
                       travar_execucao=EXEC)
    assert [p.params["periodo"] for p in passos][:2] == [10, 20]


def test_trava_compara_78_com_78_ponto_zero():
    """Float do JSON contra int do banco: sem normalizar o valor, a trava não
    encontra candidata nenhuma e o walk-forward inteiro fica fora do mercado
    em silêncio — o pior tipo de defeito."""
    combos, janelas = _cenario(stop_a=300.0, stop_b=500)
    combos[0]["params"]["stop_pontos"] = 300.0
    # a mesma combinação, com o valor escrito como inteiro noutra linha
    gemea = combo({"periodo": 10, "stop_pontos": 300},
                  meses("2021-03", "2024-03", 2.0))
    passos = wfa.rodar(combos + [gemea], janelas, CAP, COMO,
                       travar_execucao=EXEC)
    assert not any(p.fora_do_mercado for p in passos)
    assert {float(p.params["stop_pontos"]) for p in passos} == {300.0}


def test_travada_sem_candidata_que_case_fica_fora_do_mercado():
    """Regra herdada do walk-forward: sem combinação válida na janela, não se
    opera. Fingir que opera com o stop de outra combinação seria inventar um
    backtest que nunca rodou."""
    a = combo({"periodo": 10, "stop_pontos": 300},
              meses("2021-03", "2021-09", 1000.0))   # some antes do 2º IS
    b = combo({"periodo": 20, "stop_pontos": 500},
              meses("2021-03", "2024-03", 5.0))
    janelas = [j for j in wfa.montar_janelas("2021-03-16", "2024-03-13", 18, 6)
               if not j.deploy]
    passos = wfa.rodar([a, b], janelas, CAP, COMO,
                       travar_execucao=EXEC)
    assert passos[0].params["stop_pontos"] == 300
    assert passos[1].fora_do_mercado is True


def test_sem_travar_nada_o_resultado_e_o_de_sempre():
    """A trava é opcional e não pode mudar o caminho de quem não a usa."""
    combos, janelas = _cenario()
    assert ([p.params for p in wfa.rodar(combos, janelas, CAP, COMO)]
            == [p.params for p in wfa.rodar(combos, janelas, CAP,
                                            "ulcer",
                                            travar_execucao=set())])


def test_a_trava_nasce_na_primeira_janela_nao_no_melhor_do_periodo():
    """Travar no melhor do período inteiro seria olhar o futuro: na primeira
    janela ninguém sabia qual stop venceria no fim. Aqui o stop 500 ganha em
    dois dos três IS, e mesmo assim o travado é o 300, da primeira."""
    a = combo({"periodo": 10, "stop_pontos": 300},
              {**meses("2021-03", "2022-09", 10.0),
               **meses("2022-09", "2024-03", 1.0)})
    b = combo({"periodo": 10, "stop_pontos": 500},
              {**meses("2021-03", "2022-09", 1.0),
               **meses("2022-09", "2024-03", 99.0)})
    janelas = [j for j in wfa.montar_janelas("2021-03-16", "2024-03-13", 18, 6)
               if not j.deploy]
    passos = wfa.rodar([a, b], janelas, CAP, COMO,
                       travar_execucao=EXEC)
    assert {p.params["stop_pontos"] for p in passos} == {300}
