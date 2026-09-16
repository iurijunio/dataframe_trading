"""Testes da porteira: a varredura inteira passa ou não passa?

Cada caso monta uma região com veredito conhecido — um platô, uma região que
perde dinheiro com um campeão dentro, uma varredura pequena demais para
concluir qualquer coisa.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import porteira as P  # noqa: E402


def linha(n, lucro, **extra):
    base = {"n": n, "trial_id": n, "params": {"a": n}, "params_txt": f"a={n}",
            "lucro": lucro, "trades": 500, "filtro": "ok"}
    base.update(extra)
    return base


def regiao(valores, **extra):
    return [linha(i, v, **extra) for i, v in enumerate(valores)]


# ------------------------------------------------------------ estatísticas
def test_contagens_batem_com_a_regiao():
    e = P.estatisticas(regiao([100.0] * 60 + [-50.0] * 30 + [0.0] * 10))
    assert e["avaliadas"] == 100
    assert e["positivos"] == 60 and e["negativos"] == 30 and e["zerados"] == 10
    assert e["pct_positivas"] == pytest.approx(60.0)


def test_z_score_e_media_menos_3s_sao_a_mesma_pergunta():
    """A equivalência que o cartão promete: Z > 3 e média − 3σ > 0 são a
    mesma conta escrita de duas formas. Se uma passa, a outra passa."""
    for semente in range(12):
        v = np.random.default_rng(semente).normal(1_000, 250, 300)
        e = P.estatisticas(regiao(v.tolist()))
        assert (e["z"] > 3) == (e["media_menos_3s"] > 0)


def test_z_score_nao_cresce_com_o_numero_de_combinacoes():
    """A armadilha que o módulo evita: varrer mais pontos da MESMA
    distribuição não pode melhorar a nota. Se multiplicássemos por √N (como
    o SQN faz, corretamente, sobre trades), 2.000 combinações dariam uma nota
    quatro vezes maior que 125 — de graça."""
    rng = np.random.default_rng(3)
    pequena = P.estatisticas(regiao(rng.normal(800, 400, 125).tolist()))
    grande = P.estatisticas(regiao(rng.normal(800, 400, 2_000).tolist()))
    assert abs(pequena["z"] - grande["z"]) < 0.4


def test_assimetria_denuncia_cauda_direita():
    """Muitas combinações medianas e um punhado excelente: a média engana, a
    assimetria não."""
    e = P.estatisticas(regiao([100.0] * 95 + [20_000.0] * 5))
    assert e["assimetria"] > 2
    simetrica = P.estatisticas(
        regiao(np.random.default_rng(1).normal(500, 100, 500).tolist()))
    assert abs(simetrica["assimetria"]) < 0.4


def test_desvio_zero_nao_divide_por_zero():
    e = P.estatisticas(regiao([500.0] * 40))
    assert e["desvio"] == 0.0
    assert e["z"] == float("inf")
    assert e["cv"] == 0.0


def test_varredura_vazia():
    assert P.estatisticas([]) == {}


# ---------------------------------------------------------------- veredito
def test_plato_solido_e_aprovado():
    v = np.random.default_rng(7).normal(5_000, 400, 200)
    av = P.avaliar(regiao(v.tolist()))
    assert av["estado"] == "aprovada"
    assert not av["reprovados"] and not av["ressalvas"]


def test_media_positiva_nao_salva_regiao_carregada_por_campeoes():
    """O caso que mais engana e o que mais importa barrar.

    90 combinações perdendo R$ 300 e 10 ganhando R$ 8.000: o somatório é
    positivo e a MÉDIA também (+R$ 530). Quem olha só a média aprova. A
    porteira reprova pelos dois portões que enxergam a forma da região —
    apenas 10% lucram, e o desvio é tão maior que a média que o Z-score fica
    perto de zero.
    """
    av = P.avaliar(regiao([-300.0] * 90 + [8_000.0] * 10))
    assert av["estatisticas"]["media"] > 0        # a média engana...
    assert av["estado"] == "reprovada"            # ...e não salva a região
    nomes = [p["nome"] for p in av["reprovados"]]
    assert "combinações lucrativas" in nomes
    assert "Z-score da região" in nomes


def test_regiao_com_media_negativa_e_reprovada():
    """Média negativa é portão crítico por si só: nem adianta olhar o resto."""
    av = P.avaliar(regiao([-300.0] * 95 + [2_000.0] * 5))
    assert av["estatisticas"]["media"] < 0
    assert av["estado"] == "reprovada"
    assert "média da região" in [p["nome"] for p in av["reprovados"]]


def test_varredura_pequena_demais_e_barrada():
    """Não é defeito da estratégia — é amostra insuficiente para responder."""
    av = P.avaliar(regiao([1_000.0] * 12))
    assert av["estado"] == "reprovada"
    assert av["reprovados"][0]["nome"] == "amostra da varredura"


def test_regiao_frouxa_reprova_no_z():
    """Lucra na maioria, mas o desvio é tão grande que a média fica a menos
    de um desvio do zero: uma mudança pequena leva tudo para o vermelho."""
    v = np.random.default_rng(11).normal(200, 900, 400)
    av = P.avaliar(regiao(v.tolist()))
    assert av["estado"] == "reprovada"
    assert "Z-score da região" in [p["nome"] for p in av["reprovados"]]


def test_ressalva_passa_mas_avisa():
    """Passa em tudo que é crítico e falha só nos três sigma: segue com
    aviso, porque exigir três sigma de um espaço de parâmetros reprovaria
    quase toda varredura real."""
    v = np.random.default_rng(5).normal(1_000, 500, 300)     # Z ≈ 2
    av = P.avaliar(regiao(v.tolist()))
    assert av["estado"] == "aprovada com ressalva"
    assert not av["reprovados"]
    assert "3 desvios (média − 3σ)" in [p["nome"] for p in av["ressalvas"]]


def test_amostra_fraca_conta_como_ressalva():
    dados = (regiao([5_000.0] * 60)
             + [linha(i, 5_000.0, filtro="amostra fraca") for i in range(60, 120)])
    av = P.avaliar(dados)
    assert "combinações com amostra fraca" in [p["nome"] for p in av["ressalvas"]]


def test_z_forte_e_um_limiar_de_verdade():
    """`LIMIARES["z_forte"]` era anunciado como configurável e ignorado: o
    portão comparava `media_menos_3s > 0` cravado. Passar outro valor tem que
    mudar o portão, o nome dele e o veredito."""
    v = np.random.default_rng(5).normal(1_000, 500, 300)      # Z ~ 2
    frouxo = P.avaliar(regiao(v.tolist()), lim={"z_forte": 1.0})
    apertado = P.avaliar(regiao(v.tolist()), lim={"z_forte": 5.0})

    assert "1 desvios (média − 1σ)" in [p["nome"] for p in frouxo["portoes"]]
    assert frouxo["estado"] == "aprovada"                  # Z 2 passa em 1σ
    assert apertado["estado"] == "aprovada com ressalva"   # e falha em 5σ


def test_regiao_perdedora_sem_dispersao_tem_z_menos_infinito():
    """Todas as combinações perdendo exatamente o mesmo: o Z devolvia 0,00,
    que na tela se lê como 'neutro' quando o correto é o pior caso possível."""
    e = P.estatisticas(regiao([-500.0] * 40))
    assert e["desvio"] == 0.0
    assert e["z"] == float("-inf")
    assert P.avaliar(regiao([-500.0] * 40))["estado"] == "reprovada"


def test_todo_portao_tem_dica():
    """A regra da casa: nada aparece na tela sem o (?) explicando faixa boa e
    faixa ruim."""
    av = P.avaliar(regiao(np.random.default_rng(2).normal(3_000, 600, 200).tolist()))
    for p in av["portoes"]:
        assert p["dica"] and len(p["dica"]) > 80


# --------------------------------------------------------------------- SQN
def test_sqn_cresce_com_regularidade():
    """Mesma expectativa, desvios diferentes: quem entrega o resultado de
    forma mais regular tem nota maior."""
    rng = np.random.default_rng(4)
    regular = P.sqn(rng.normal(50, 100, 300))
    irregular = P.sqn(rng.normal(50, 400, 300))
    assert regular["sqn"] > irregular["sqn"]


def test_sqn_tem_teto_de_amostra():
    """A regra de Tharp: sem o teto de 100, dez mil trades medíocres bateriam
    quinhentos excelentes só pelo volume."""
    rng = np.random.default_rng(6)
    base = rng.normal(20, 100, 10_000)
    a = P.sqn(base)
    b = P.sqn(base[:100])
    assert a["n_efetivo"] == 100 and a["limitado"]
    assert a["sqn"] == pytest.approx(np.sqrt(100) * base.mean()
                                     / base.std(ddof=1), rel=1e-6)
    assert not b["limitado"]


def test_sqn_classifica_nas_faixas_de_tharp():
    # média 100, desvio 100, N=100 -> SQN = 10 * 1 = 10
    v = np.concatenate([np.full(50, 200.0), np.full(50, 0.0)])
    s = P.sqn(v)
    assert s["sqn"] == pytest.approx(10.0, rel=.02)
    assert "excepcional" in s["faixa"]


def test_sqn_negativo_para_sistema_perdedor():
    s = P.sqn(np.random.default_rng(8).normal(-40, 100, 300))
    assert s["sqn"] < 0 and s["faixa"] == "abaixo do operável"


def test_sqn_sem_dispersao_ou_sem_amostra():
    assert P.sqn(np.array([10.0])) == {}
    assert P.sqn(np.full(50, 10.0)) == {}
