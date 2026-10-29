"""A moeda do ativo na tela: símbolo, nome por extenso e o número em dinheiro.

O número fica no formato brasileiro também em dólar ("US$ 1.234,56"); só o
símbolo muda. `brl` continua o mesmo, porque o ao vivo o usa.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ativo  # noqa: E402
from ui.components import cartao  # noqa: E402


def test_dinheiro_em_dolar_usa_o_formato_brasileiro():
    assert cartao.dinheiro(1234.5, "USD") == "US$ 1.234,50"


def test_dinheiro_negativo_e_zero_em_dolar():
    assert cartao.dinheiro(-57056, "USD") == "-US$ 57.056,00"
    assert cartao.dinheiro(0, "USD") == "US$ 0,00"
    assert cartao.dinheiro(-1.5, "USD") == "-US$ 1,50"


def test_dinheiro_sem_moeda_e_brl_e_igual_ao_brl():
    assert cartao.dinheiro(1234.5) == cartao.brl(1234.5) == "R$ 1.234,50"
    assert cartao.dinheiro(-3, None) == "-R$ 3,00"
    assert cartao.brl(-3) == "-R$ 3,00"


def test_moeda_desconhecida_usa_o_proprio_codigo():
    assert cartao.dinheiro(1.0, "EUR") == "EUR 1,00"


def test_simbolo_e_nome_da_moeda():
    assert cartao.simbolo_moeda("USD") == "US$"
    assert cartao.simbolo_moeda("EUR") == "EUR"
    assert cartao.simbolo_moeda(None) == "R$"
    assert cartao.nome_moeda("USD") == "dólares"
    assert cartao.nome_moeda("BRL") == "reais"
    assert cartao.nome_moeda(None) == "reais"
    assert cartao.nome_moeda("EUR") == "EUR"


def test_tabelas_de_moeda_do_core():
    assert ativo.SIMBOLOS_MOEDA == {"BRL": "R$", "USD": "US$"}
    assert ativo.NOMES_MOEDA == {"BRL": "reais", "USD": "dólares"}


def test_moeda_de_le_a_ficha_do_ativo():
    assert ativo.moeda_de("WIN$N") == "BRL"
    assert ativo.moeda_de("MES") == "USD"
    assert ativo.moeda_de(None) == "BRL"


def test_moeda_de_simbolo_sem_yaml_cai_em_brl():
    assert ativo.moeda_de("XYZ") == "BRL"


def test_linha_de_comando_troca_so_o_simbolo():
    from core import metrics

    m = {
        "trades": 3, "lucro_liquido": 1234.5, "custo_total": 10.0,
        "profit_factor": 1.5, "win_rate": 50.0, "payoff": 1.2,
        "expectativa": 411.5, "max_drawdown": -57056.0,
        "max_drawdown_pct": 5.0, "max_drawdown_pct_capital": 4.0,
        "fator_recuperacao": 2.0, "sharpe": 1.0, "sortino": 1.1,
        "max_perdas_consecutivas": 2, "trades_por_dia": 1.0,
        "barras_ambiguas": 0, "barras_ambiguas_pct": 0.0, "saidas": {},
    }
    usd = metrics.format_panel(m, "USD")
    assert "US$" in usd and "R$" not in usd
    assert metrics.format_panel(m) == metrics.format_panel(m, "BRL")
    assert "R$" in metrics.format_panel(m) and "US$" not in metrics.format_panel(m)
