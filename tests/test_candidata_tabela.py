"""A tela Candidata mostra os números numa tabela com mapa de calor.

A cor de cada valor sai da faixa boa/ruim que o próprio (?) descreve —
estes testes travam que a cor e o texto contam a mesma história.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import candidata_panel as CP  # noqa: E402
from ui.components import stats_cards as SC  # noqa: E402

CAP = 10_000.0


def _resumo(**troca):
    m = {"trades": 510, "lucro_liquido": 5474.0, "lucro_bruto": 5984.0,
         "custo_total": 510.0, "max_drawdown": 791.0, "max_drawdown_pct": 6.3,
         "max_drawdown_pct_capital": 7.9, "max_drawdown_rel_pct": 6.3,
         "profit_factor": 1.44, "win_rate": 23.3, "payoff": 4.73,
         "expectativa": 10.73, "fator_recuperacao": 6.92, "sharpe": 1.27,
         "sortino": 3.74, "trades_por_dia": 1.49}
    m.update(troca)
    return m


def _leitura(resumo=None, dd=831.0, seguidas=15.0, topo=125.0, topo50=57.0,
             ordem=1395.0):
    boot = {"horizonte": 131, "bloco": 1, "dd_p95": dd,
            "perdas_seguidas_p95": seguidas, "submerso_p95": topo,
            "submerso_p50": topo50}
    return {"resumo": resumo or _resumo(), "boot": boot, "boot_12m": {},
            "ordenacao": {"dd_p95": ordem}, "pregoes": 1044,
            "perdas_seguidas_reais": 11}


def _por_nome(grupos):
    return {l["nome"]: l for _, _, linhas in grupos for l in linhas}


# -------------------------------------------------- a fonte única dos textos
def test_itens_e_cartoes_saem_da_mesma_fonte():
    """Os cartões das abas Backtest e Walk-Forward e a tabela da Candidata
    usam os mesmos números e as mesmas explicações."""
    m = _resumo(periodo="01/03/2022 → 01/03/2026")
    itens = SC.itens(m)
    assert [i["rotulo"] for i in itens] == list(SC.cartoes(m))
    assert all(i["explica"] for i in itens)


# ------------------------------------------------------------------ tabela
def test_tabela_tem_os_dois_grupos_e_todos_os_numeros():
    grupos = CP.linhas(_leitura(), CAP)
    assert [g[0] for g in grupos] == ["Resultado fora da amostra",
                                      "Quanto a estratégia aguenta"]
    nomes = _por_nome(grupos)
    for n in ("lucro líquido", "max drawdown", "perda esperada · 6 meses",
              "dias perdendo seguidos", "dias até novo topo",
              "perda com outra ordem"):
        assert n in nomes, n
    assert all(l["explica"] for l in nomes.values())


def test_cor_segue_a_faixa_do_capital():
    """Perda esperada: até 10% do capital é bom, acima de 20% é ruim."""
    assert _por_nome(CP.linhas(_leitura(dd=831.0), CAP))[
        "perda esperada · 6 meses"]["tom"] == "bom"
    assert _por_nome(CP.linhas(_leitura(dd=1500.0), CAP))[
        "perda esperada · 6 meses"]["tom"] == "medio"
    assert _por_nome(CP.linhas(_leitura(dd=2500.0), CAP))[
        "perda esperada · 6 meses"]["tom"] == "ruim"


def test_poucos_trades_fica_vermelho():
    """Abaixo de ~100 trades quase nada é conclusivo — é o que o (?) diz."""
    linhas = _por_nome(CP.linhas(_leitura(_resumo(trades=80)), CAP))
    assert linhas["trades"]["tom"] == "ruim"


def test_numero_sem_faixa_fica_sem_cor():
    """Win rate sozinho não diz nada: sem faixa, sem cor."""
    assert _por_nome(CP.linhas(_leitura(), CAP))["win rate"]["tom"] is None


def test_dias_ate_novo_topo_mostra_o_tipico_e_o_pior_na_nota():
    linha = _por_nome(CP.linhas(_leitura(topo=125.0, topo50=57.0), CAP))[
        "dias até novo topo"]
    assert linha["valor"] == "57"
    assert "125" in linha["nota"]


def test_lucro_negativo_fica_vermelho():
    linhas = _por_nome(CP.linhas(_leitura(_resumo(lucro_liquido=-300.0,
                                                  expectativa=-0.6)), CAP))
    assert linhas["lucro líquido"]["tom"] == "ruim"
    assert linhas["expectativa"]["tom"] == "ruim"
