"""Testes dos recortes de diagnóstico.

Cada um monta trades com uma resposta conhecida de antemão: se o gráfico
disser outra coisa na tela, o erro está no desenho, não na conta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import analytics as an  # noqa: E402


def ts(*textos):
    return np.array([np.datetime64(t, "s") for t in textos])


# --------------------------------------------------------------------- tempo
def test_agrupa_por_hora_de_entrada():
    entradas = ts("2025-01-06T09:30", "2025-01-06T09:45",
                  "2025-01-06T14:10", "2025-01-07T09:05")
    liq = np.array([100.0, -40.0, -200.0, 10.0])

    r = an.por_hora(entradas, liq)
    assert r["chaves"] == ["09h", "14h"]
    assert r["liquido"] == pytest.approx([70.0, -200.0])
    assert r["trades"] == [3, 1]
    # expectativa e o que decide um corte, nao o total
    assert r["expectativa"] == pytest.approx([70 / 3, -200.0])
    assert r["win_rate"] == pytest.approx([200 / 3, 0.0])


def test_dia_da_semana_com_o_nome_certo():
    # 2025-01-06 foi segunda; 2025-01-10, sexta
    r = an.por_dia_semana(ts("2025-01-06T10:00", "2025-01-10T10:00"),
                          np.array([50.0, -20.0]))
    assert r["chaves"] == ["segunda", "sexta"]
    assert r["liquido"] == pytest.approx([50.0, -20.0])


def test_mes_soma_todos_os_anos():
    """Sazonalidade: março de 2021 e de 2026 caem no mesmo balde."""
    r = an.por_mes(ts("2021-03-10T10:00", "2026-03-11T10:00",
                      "2024-07-01T10:00"), np.array([10.0, 20.0, -5.0]))
    assert r["chaves"] == ["mar", "jul"]
    assert r["liquido"] == pytest.approx([30.0, -5.0])


def test_calendario_mensal_deixa_vazio_o_mes_sem_trade():
    c = an.calendario_mensal(ts("2024-02-05T10:00", "2025-11-20T10:00"),
                             np.array([100.0, -50.0]))
    assert c["anos"] == ["2024", "2025"]
    grade = np.array(c["valores"], dtype=float)
    assert grade[0][1] == pytest.approx(100.0)     # fev/2024
    assert grade[1][10] == pytest.approx(-50.0)    # nov/2025
    # mês sem operação fica NaN, não zero: zero mentiria dizendo "empatou"
    assert np.isnan(grade[0][0])
    assert np.isnan(grade).sum() == 22


# -------------------------------------------------------------------- trades
def test_duracao_cai_na_faixa_certa():
    r = an.por_duracao(np.array([1, 2, 5, 200]),
                       np.array([10.0, 10.0, -30.0, -100.0]),
                       faixas=(1, 3, 10))
    assert r["chaves"] == ["≤1 barras", "2–3 barras", "4–10 barras",
                           ">10 barras"]
    assert r["liquido"] == pytest.approx([10.0, 10.0, -30.0, -100.0])


def test_motivo_usa_os_rotulos_do_kernel():
    r = an.por_motivo(np.array([0, 0, 1]), np.array([-10.0, -20.0, 60.0]),
                      {0: "stop", 1: "alvo"})
    assert r["chaves"] == ["stop", "alvo"]
    assert r["liquido"] == pytest.approx([-30.0, 60.0])


def test_distribuicao_nao_perde_nenhum_trade():
    """Cada trade está num balde ou contado numa das pontas aparadas."""
    liq = np.array([-100.0, -50.0, 10.0, 20.0, 300.0])
    d = an.distribuicao(liq, bins=5)
    assert sum(d["contagem"]) + d["fora_esq"] + d["fora_dir"] == len(liq)


def test_serie_vazia_nao_quebra():
    vazio = np.array([], dtype="datetime64[s]")
    assert an.por_hora(vazio, np.array([]))["chaves"] == []
    vazia = an.distribuicao(np.array([]))
    assert vazia["centros"] == [] and vazia["contagem"] == []


# ------------------------------------------------------------- MAE/MFE
def test_calor_separa_ganhadores_de_perdedores():
    mae = np.array([-10, -300, -20, -400])
    mfe = np.array([500, 80, 600, 120])
    liq = np.array([100.0, -50.0, 200.0, -60.0])

    d = an.calor_mae_mfe(mae, mfe, liq)
    assert d["n_ganhadores"] == 2 and d["n_perdedores"] == 2
    # ganhadores sofreram pouco contra; perdedores mostraram lucro antes de virar
    assert d["mae_ganhadores_p95"] < 25
    assert d["mfe_perdedores_p50"] == pytest.approx(100.0)
    assert all(v >= 0 for v in d["mae"])          # MAE vai para a tela em módulo


def test_sugere_apertar_stop_quando_ninguem_chega_perto():
    d = {"mae_ganhadores_p95": 90.0, "mfe_perdedores_p50": 0.0,
         "n_ganhadores": 50, "n_perdedores": 50}
    dicas = " ".join(an.sugestoes(d, stop_atual=400, alvo_atual=800))
    assert "apertar" in dicas.lower()


def test_sugere_stop_mais_largo_quando_os_ganhadores_raspam_nele():
    d = {"mae_ganhadores_p95": 390.0, "mfe_perdedores_p50": 0.0,
         "n_ganhadores": 50, "n_perdedores": 50}
    dicas = " ".join(an.sugestoes(d, stop_atual=400, alvo_atual=800))
    assert "mais largo" in dicas.lower()


def test_sugere_breakeven_quando_perdedores_mostram_lucro():
    d = {"mae_ganhadores_p95": 200.0, "mfe_perdedores_p50": 400.0,
         "n_ganhadores": 50, "n_perdedores": 50}
    dicas = " ".join(an.sugestoes(d, stop_atual=400, alvo_atual=800))
    assert "breakeven" in dicas.lower()


def test_amostra_pequena_nao_gera_sugestao():
    """Com 5 trades não se conclui nada — e a tela não pode fingir que sim."""
    d = {"mae_ganhadores_p95": 390.0, "mfe_perdedores_p50": 400.0,
         "n_ganhadores": 5, "n_perdedores": 5}
    assert an.sugestoes(d, stop_atual=400, alvo_atual=800) == []


# ----------------------------------------- ganho x prejuizo, nao so o saldo
def test_agrupa_ganho_e_prejuizo_separados():
    """Um grupo que fecha em zero pode ter girado muito dos dois lados.
    O saldo esconde isso; as duas barras mostram."""
    entradas = ts("2025-01-06T09:10", "2025-01-06T09:20",
                  "2025-01-06T14:00", "2025-01-06T14:30")
    liq = np.array([500.0, -500.0, 30.0, -10.0])

    r = an.por_hora(entradas, liq)
    assert r["chaves"] == ["09h", "14h"]
    assert r["liquido"] == pytest.approx([0.0, 20.0])   # 09h empata...
    assert r["ganhos"] == pytest.approx([500.0, 30.0])  # ...mas girou 500
    assert r["perdas"] == pytest.approx([500.0, 10.0])  # de cada lado


def test_perdas_saem_positivas_para_a_barra():
    r = an.por_dia_semana(ts("2025-01-06T10:00"), np.array([-250.0]))
    assert r["perdas"] == pytest.approx([250.0])
    assert r["ganhos"] == pytest.approx([0.0])


# --------------------------------- duracao em barras do timeframe, nao M1
def test_duracao_converte_para_barras_do_timeframe():
    """O kernel conta barras M1 porque a execução roda em M1. Quem opera em
    M15 pensa em candles de 15, e é essa a unidade do campo max_barras."""
    m1 = np.array([15, 45, 150])          # 1, 3 e 10 candles de M15
    liq = np.array([10.0, -20.0, 30.0])

    r = an.por_duracao(m1, liq, minutos_por_barra=15, faixas=(1, 3, 10))
    assert r["chaves"] == ["≤1 barras", "2–3 barras", "4–10 barras"]

    # em M1 os mesmos trades cairiam todos na ultima faixa
    r1 = an.por_duracao(m1, liq, minutos_por_barra=1, faixas=(1, 3, 10))
    assert r1["chaves"] == [">10 barras"]


# ------------------------------------------------- histograma legivel
def test_baldes_do_histograma_sao_redondos():
    rng = np.random.default_rng(7)
    d = an.distribuicao(rng.normal(0, 137.4189, 2000))
    largura = d["largura"]
    # 1, 2, 2.5 ou 5 vezes uma potencia de dez - nunca 37.4189
    mantissa = largura / 10 ** np.floor(np.log10(largura))
    assert mantissa in (1.0, 2.0, 2.5, 5.0, 10.0)


def test_baldes_alinham_no_zero():
    """Sem alinhar, um balde cruza o zero e mistura ganho com prejuízo."""
    d = an.distribuicao(np.array([-300.0, -100.0, 50.0, 200.0, 700.0]))
    bordas = np.array(d["centros"]) - d["largura"] / 2
    assert np.isclose(bordas % d["largura"], 0).all()


def test_cauda_aparada_e_contada():
    """O outlier não pode espremer 99% dos dados em duas colunas — mas
    também não pode sumir sem aviso."""
    rng = np.random.default_rng(3)
    liq = np.concatenate([rng.normal(0, 100, 500), np.array([50_000.0])])
    d = an.distribuicao(liq)
    assert d["fora_dir"] >= 1
    assert max(d["centros"]) < 50_000
    assert sum(d["contagem"]) + d["fora_esq"] + d["fora_dir"] == len(liq)


def test_distribuicao_traz_mediana_e_media():
    d = an.distribuicao(np.array([10.0, 10.0, 10.0, 1000.0]))
    assert d["mediana"] == pytest.approx(10.0)
    assert d["media"] == pytest.approx(257.5)   # média longe = poucos grandes


# ------------------------------------- escala de cor que vira no zero
def test_zero_e_negativo_ficam_vermelhos():
    """`RdYlGn` com zmid=0 pinta o zero de amarelo, e amarelo lê-se como
    'morno'. Um mês de prejuízo não pode se disfarçar de neutro."""
    from ui.components.analytics_charts import escala_no_zero

    escala, lo, hi = escala_no_zero([[-1800.0, -10.0], [500.0, 1000.0]])
    assert (lo, hi) == (-1800.0, 1000.0)

    t = (0 - lo) / (hi - lo)
    paradas = {round(p, 4): cor for p, cor in escala}
    # a virada acontece no zero, não no meio da escala
    assert abs(min(paradas, key=lambda p: abs(p - t)) - t) < 1e-3
    abaixo = [cor for p, cor in escala if p <= t]
    acima = [cor for p, cor in escala if p > t]
    assert all(c in ("#7A0B25", "#FF4D7D") for c in abaixo)     # só vermelhos
    assert all(c in ("#7BE8B6", "#00F5A0") for c in acima)      # só verdes


def test_tudo_positivo_nao_pinta_vermelho():
    from ui.components.analytics_charts import escala_no_zero

    escala, lo, hi = escala_no_zero([[10.0, 200.0]])
    assert lo == 0
    assert all("#7A0B25" not in cor and "#FF4D7D" not in cor for _, cor in escala)


def test_tudo_negativo_nao_pinta_verde():
    from ui.components.analytics_charts import escala_no_zero

    escala, lo, hi = escala_no_zero([[-10.0, -200.0]])
    assert hi == 0
    assert all("#00F5A0" not in cor and "#7BE8B6" not in cor for _, cor in escala)


def test_grade_so_com_nan_nao_quebra():
    from ui.components.analytics_charts import escala_no_zero

    escala, lo, hi = escala_no_zero([[float("nan"), float("nan")]])
    assert escala == "RdYlGn" and lo is None and hi is None
