"""Testes da leitura da varredura (passos 5 e 7 da metodologia).

Cada caso monta uma região com resposta conhecida: um platô, um precipício,
uma região que perde dinheiro com um campeão dentro. Se a tela disser outra
coisa, o erro está no desenho — não na conta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import mineracao_stats as MS  # noqa: E402


def linha(n, lucro, **extra):
    """Uma linha da tabela de mineração, com os campos que os critérios leem."""
    base = {
        "n": n, "trial_id": n, "params": {"a": n}, "params_txt": f"a={n}",
        "lucro": lucro, "fr": 2.5, "pf": 1.4, "dd": 1_000.0, "trades": 500,
        "consistencia": 70.0, "mediana_fold": 300.0, "score": 1.0,
        "robusto": 1.0, "filtro": "ok",
    }
    base.update(extra)
    return base


def plato(n=100):
    """Região homogênea: todas as combinações rendem parecido."""
    return [linha(i, 1_000.0 + i * 5) for i in range(n)]


def precipicio(n=100):
    """Três combinações carregam a região; o resto perde."""
    return ([linha(i, 20_000.0) for i in range(3)]
            + [linha(i, -300.0) for i in range(3, n)])


# ------------------------------------------------------------------ resumo
def test_plato_e_reconhecido():
    r = MS.resumo(plato())
    assert r["pct_lucrativas"] == 100.0
    assert r["razao_melhor_mediana"] < 1.6      # campeão perto da mediana
    assert r["p75"] > r["p25"] > 0


def test_precipicio_e_denunciado_pela_razao():
    """O total engana: a região tem lucro somado positivo, mas a mediana é
    negativa e o campeão faz muitas vezes o meio dela."""
    r = MS.resumo(precipicio())
    assert r["pct_lucrativas"] == 3.0
    assert r["mediana"] < 0
    # com mediana negativa a razão inverteria de sinal: não se calcula
    assert r["razao_melhor_mediana"] is None
    assert r["melhor"] == 20_000.0


def test_regiao_boa_com_um_campeao_exagerado():
    """Metade lucra, mas um ponto faz 40× a mediana: é ele que está sendo
    escolhido, e não a região."""
    dados = [linha(i, 500.0) for i in range(50)] + [linha(i, -400.0) for i in range(49)]
    dados.append(linha(99, 20_000.0))
    r = MS.resumo(dados)
    assert r["razao_melhor_mediana"] > 20


def test_resumo_vazio_nao_quebra():
    assert MS.resumo([]) == {}


# ------------------------------------------------------------------- curva
def test_curva_vai_do_melhor_para_o_pior():
    c = MS.curva(plato())
    assert c["valores"] == sorted(c["valores"], reverse=True)
    assert c["pct"][0] > 0 and c["pct"][-1] == pytest.approx(100.0)


def test_curva_de_outra_metrica():
    dados = [linha(i, 100.0, fr=float(i)) for i in range(10)]
    c = MS.curva(dados, "fr")
    assert c["valores"][0] == 9.0 and c["chave"] == "fr"


# --------------------------------------------------------------- critérios
def test_todas_passam_quando_os_limiares_sao_folgados():
    av = MS.avaliar(plato(), {"trades": 100, "pf": 1.0, "fr": 1.0,
                              "consistencia": 50, "mediana": 0,
                              "dd": 5_000, "lucro": 0})
    assert av["n_aprovadas"] == 100 and av["pct"] == 100.0


def test_gargalo_aponta_o_criterio_que_manda():
    """Todas passam em tudo, menos no drawdown — que reprova 90%."""
    dados = ([linha(i, 1_000.0, dd=900.0) for i in range(10)]
             + [linha(i, 1_000.0, dd=9_000.0) for i in range(10, 100)])
    av = MS.avaliar(dados, {"trades": 100, "pf": 1.0, "fr": 1.0,
                            "consistencia": 50, "mediana": 0,
                            "dd": 2_500, "lucro": 0})
    assert av["n_aprovadas"] == 10
    assert av["gargalo"]["id"] == "dd"
    assert av["gargalo"]["pct"] == pytest.approx(10.0)


def test_criterio_desligado_nao_filtra_nem_aparece():
    """Campo vazio na tela chega como None: aquele critério sai de cena em
    vez de reprovar tudo."""
    dados = [linha(i, 1_000.0, dd=9_000.0) for i in range(20)]
    av = MS.avaliar(dados, {"trades": None, "pf": None, "fr": None,
                            "consistencia": None, "mediana": None,
                            "dd": None, "lucro": None})
    assert av["n_aprovadas"] == 20
    assert all(not c["ativo"] for c in av["por_criterio"])
    assert av["gargalo"] is None


def test_valor_ausente_nao_reprova():
    """Fator de recuperação vazio é drawdown zero — a combinação que nunca
    afundou. Reprová-la por falta de dado seria eliminar a melhor."""
    dados = [linha(i, 1_000.0, fr=None, dd=0.0) for i in range(20)]
    av = MS.avaliar(dados, {"trades": 100, "pf": 1.0, "fr": 2.0,
                            "consistencia": 50, "mediana": 0,
                            "dd": 2_500, "lucro": 0})
    assert av["n_aprovadas"] == 20
    fr = next(c for c in av["por_criterio"] if c["id"] == "fr")
    assert fr["avaliadas"] == 0        # ninguém tinha o dado
    assert fr["ativo"] and not fr["avaliavel"]
    # e o critério que ninguém pôde responder NÃO pode virar o gargalo: com
    # pct=0 ele aparecia como barra vermelha em 0% ao lado de "aproveitamento
    # 100%", dizendo que cortava tudo sem ter cortado ninguém
    assert av["gargalo"] is None
    assert "fator de recuperação" in av["sem_dado"]


def test_criterio_de_teto_usa_menor_ou_igual():
    dados = [linha(0, 100.0, dd=2_500.0), linha(1, 100.0, dd=2_501.0)]
    av = MS.avaliar(dados, {"dd": 2_500})
    dd = next(c for c in av["por_criterio"] if c["id"] == "dd")
    assert dd["passam"] == 1


def test_nenhuma_aprovada_nao_quebra():
    av = MS.avaliar(plato(), {"lucro": 10_000_000})
    assert av["n_aprovadas"] == 0 and av["aprovadas"] == []
    assert av["pct"] == 0.0


def test_varredura_vazia():
    assert MS.avaliar([], {"lucro": 0}) == {}


# ------------------------------------------- a varredura que a tela enxerga
def test_extrato_nao_trunca_como_o_ranking():
    """A porteira, a distribuição e os critérios precisam da varredura
    INTEIRA.

    `_ranking` corta em 5.000 linhas para a tabela e a nuvem aguentarem — e
    corta pelo TOPO, ordenado por qualidade. Alimentar a estatística com esse
    recorte era pedir que ela julgasse a região olhando só a metade boa: uma
    varredura medíocre de 8 mil pontos passava de "reprovada" a "aprovada com
    ressalva" porque os 3 mil piores ficavam de fora da conta.
    """
    from core.optimizer import Mineracao

    resultados = [
        {"params": {"a": i},
         "geral": {"lucro": float(i), "trades": 500, "max_dd": 100.0,
                   "profit_factor": 1.2, "fator_recuperacao": 2.0},
         "folds": {"positivos": 4, "com_trades": 5, "mediana_lucro": 10.0},
         "consistencia": 0.8, "score": 1.0, "score_robusto": float(i),
         "passa_filtro": True, "trial_id": i}
        for i in range(8_000)
    ]
    extrato = Mineracao._extrato(resultados)
    ranking = Mineracao._ranking(resultados)

    assert len(extrato) == 8_000        # a estatística vê tudo
    assert len(ranking) == 5_000        # a tabela, só o topo
    # e o corte do ranking é enviesado para cima, que é o motivo do extrato
    assert min(l["lucro"] for l in ranking) > min(l["lucro"] for l in extrato)


def test_extrato_descarta_combinacao_com_erro():
    from core.optimizer import Mineracao

    bom = {"params": {"a": 1},
           "geral": {"lucro": 10.0, "trades": 5, "max_dd": 1.0,
                     "profit_factor": 1.1, "fator_recuperacao": 1.0},
           "folds": {"positivos": 1, "com_trades": 1, "mediana_lucro": 1.0},
           "consistencia": 1.0, "score": 1.0, "passa_filtro": True}
    assert len(Mineracao._extrato([bom, {"erro": "estourou"}])) == 1
