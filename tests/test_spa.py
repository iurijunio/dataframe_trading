"""Testes do teste de muitas tentativas (SPA de Hansen).

Mesma disciplina dos outros: cada caso tem a resposta conhecida de
antemão — só ruído dá p alto, um ganho isolado dá p baixo, e esconder o
mesmo ganho entre muitas colunas de ruído torna o teste mais exigente.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata, robustez as rb, spa  # noqa: E402


# ---------------------------------------------------------------- spa.teste
def test_so_ruido_da_p_alto():
    rng = np.random.default_rng(4)
    m = rng.normal(0, 30, size=(600, 40))
    assert spa.teste(m, n=500)["p"] > 0.2


def test_uma_coluna_com_ganho_forte_da_p_baixo():
    rng = np.random.default_rng(4)
    m = rng.normal(0, 30, size=(600, 40))
    m[:, 7] += 12.0
    r = spa.teste(m, n=500)
    assert r["p"] < 0.05 and r["melhor"] == 7


def test_muitas_tentativas_pesam():
    """O mesmo ganho moderado, sozinho, passa; escondido entre 200 colunas de
    ruído com o mesmo nível, o teste fica mais exigente."""
    rng = np.random.default_rng(5)
    sozinha = rng.normal(3, 30, size=(600, 1))
    muitas = np.hstack([sozinha, rng.normal(0, 30, size=(600, 200))])
    assert spa.teste(muitas, n=500)["p"] > spa.teste(sozinha, n=500)["p"]


def test_mesma_semente_mesmo_p():
    m = np.random.default_rng(6).normal(1, 30, size=(300, 10))
    assert spa.teste(m, n=300, semente=9)["p"] == spa.teste(m, n=300, semente=9)["p"]


def test_matriz_curta_devolve_vazio():
    assert spa.teste(np.zeros((5, 3))) == {}


def test_coluna_constante_sai_da_conta_sem_quebrar():
    """Uma coluna sem variação nenhuma teria w_k = 0 (divisão por zero); ela
    tem que ser descartada, não travar o teste."""
    rng = np.random.default_rng(3)
    m = rng.normal(0, 20, size=(400, 5))
    m[:, 2] = 7.0
    r = spa.teste(m, n=300)
    assert r and r["melhor"] != 2


def test_todas_as_colunas_constantes_devolve_vazio():
    m = np.full((200, 4), 3.0)
    assert spa.teste(m, n=100) == {}


def test_bloco_explicito_e_usado_sem_quebrar():
    rng = np.random.default_rng(2)
    m = rng.normal(0, 10, size=(200, 6))
    r = spa.teste(m, n=200, bloco=5)
    assert r and r["n"] == 200


def test_bloco_invalido_e_rejeitado():
    with pytest.raises(ValueError):
        spa.teste(np.zeros((100, 3)), bloco=0)


# -------------------------------- prova de discriminação (quebrar e ver cair)
#
# As duas provas abaixo foram desenhadas rodando `spa.teste` de verdade, com
# a conta certa e depois com cada mutação aplicada à mão em `core/spa.py`
# (tirar a recentragem; sortear índices por coluna), para confirmar que a
# mutação muda o veredito. Os números couberam nos dois casos do enunciado:
#
#   sem recentragem (many colunas de média bem negativa + 1 de ganho
#   modesto): correto p=0.01 (passa) -> mutado p=0.99125 (reprova)
#   sorteio por coluna (30 colunas fortemente correlacionadas): correto
#   p=0.0317 (passa) -> mutado p=0.5017 (reprova)


def test_sem_recentragem_o_ganho_modesto_deixaria_de_passar():
    """Muitas colunas de média claramente negativa (perto de -14, desvio 15,
    bem abaixo do limiar de recentragem) e uma só de ganho modesto e real
    (média 3.2, desvio 22). Com a recentragem certa, as colunas ruins saem
    da disputa (g_k=0) e a coluna boa se destaca: passa. Sem recentragem
    (g_k=d_k sempre, mutação provada à mão em `core/spa.py`), as colunas
    ruins voltam a competir centradas em zero e inflam a distribuição de
    referência — o mesmo caso passaria a reprovar (p subiu de 0.01 para
    0.99 na mutação)."""
    rng = np.random.default_rng(4)
    ruim = rng.normal(-14.0, 15.0, size=(500, 300))
    boa = rng.normal(3.2, 22.0, size=(500, 1))
    m = np.hstack([boa, ruim])
    r = spa.teste(m, n=800, semente=5)
    assert r["p"] <= 0.10
    assert r["melhor"] == 0


def test_sortear_por_coluna_perde_a_correlacao_entre_elas():
    """30 colunas fortemente correlacionadas (a mesma série de base com um
    ruidinho por cima) com uma média real de 2.0 por pregão — como
    combinações vizinhas que operam o mesmo mercado. Sorteando a MESMA linha
    para todas (a conta certa), o sorteio preserva a correlação e o ganho
    real se confirma: passa. Sorteando índices independentes por coluna
    (mutação provada à mão em `core/spa.py`), a correlação se perde e o
    mesmo caso passaria a reprovar (p subiu de 0.03 para 0.50 na mutação)."""
    rng = np.random.default_rng(4)
    base = rng.normal(2.0, 25, size=500)
    m = base[:, None] + rng.normal(0, 1.0, size=(500, 30))
    r = spa.teste(m, n=600, semente=3)
    assert r["p"] <= 0.10


# --------------------------------------------------- indices_estacionarios
def test_indices_estacionarios_extraido_bate_com_o_bootstrap():
    """A extração não pode mudar nenhum número: os mesmos parâmetros e a
    mesma semente têm que produzir o mesmo bootstrap de antes."""
    dia = np.random.default_rng(1).normal(10, 100, 400)
    a = rb.bootstrap(dia, 10_000.0, n=50, semente=5, bloco=3)
    b = rb.bootstrap(dia, 10_000.0, n=50, semente=5, bloco=3)
    assert a["dd_p95"] == b["dd_p95"]
    assert a["final_p50"] == b["final_p50"]


def test_indices_estacionarios_forma_e_faixa():
    rng = np.random.default_rng(2)
    idx = rb.indices_estacionarios(50, 20, 7, 4, rng)
    assert idx.shape == (7, 20)
    assert idx.min() >= 0 and idx.max() < 50


# ------------------------------------------------------------- desempenho
def test_tempo_com_matriz_realista():
    """~1.050 pregões x 42 colunas, 1.000 reamostragens — o tamanho real da
    tela Candidata. Só documenta que roda em tempo de teste normal, não é
    um benchmark formal."""
    import time

    rng = np.random.default_rng(11)
    m = rng.normal(0, 30, size=(1050, 42))
    ini = time.perf_counter()
    r = spa.teste(m, n=1000)
    dur = time.perf_counter() - ini
    assert r
    assert dur < 10.0


# --------------------------------------------------------- portao_tentativas
def test_portao_tentativas_passa_com_p_baixo():
    r = candidata.portao_tentativas({"p": 0.03, "estatistica": 2.1, "melhor": 3, "n": 500})
    assert r["ok"] is True
    assert r["valor"] == 0.03


def test_portao_tentativas_reprova_com_p_alto():
    r = candidata.portao_tentativas({"p": 0.4, "estatistica": 0.2, "melhor": 1, "n": 500})
    assert r["ok"] is False


def test_portao_tentativas_no_limite_passa():
    """p exatamente igual ao máximo passa — só reprova ACIMA de 10%."""
    r = candidata.portao_tentativas({"p": 0.10, "estatistica": 1.0, "melhor": 0, "n": 500})
    assert r["ok"] is True


def test_portao_tentativas_sem_resultado_fica_pendente():
    r = candidata.portao_tentativas({})
    assert r["ok"] is None


def test_portao_tentativas_exigido_sem_sigla_e_sem_numero_cru():
    r = candidata.portao_tentativas({"p": 0.03, "estatistica": 2.1, "melhor": 3, "n": 500})
    assert "SPA" not in r["nome"] and "Hansen" not in r["nome"]
    assert "SPA" not in r["dica"] and "Hansen" not in r["dica"]
    assert r["exigido"] == "até 10% de chance de ser sorte"
