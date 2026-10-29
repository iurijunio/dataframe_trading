"""Mineração na moeda do ativo: porteira, região, nuvem e gráficos.

Sem `moeda` o WIN fica idêntico (quem garante é `test_referencia_telas.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from core import analytics, optimizer, porteira  # noqa: E402
from core import mineracao_stats as MS  # noqa: E402
from scripts import referencia_telas as R  # noqa: E402
from ui import callbacks  # noqa: E402
from ui.components import mine_charts as MC  # noqa: E402
from ui.components import mine_porteira as MP  # noqa: E402
from ui.components import mine_regiao as MR  # noqa: E402
from ui.components import scatter  # noqa: E402


def _sem_real(texto: str):
    assert "R$" not in texto
    assert "em reais" not in texto


def _porteira_texto(trials, moeda):
    av = porteira.avaliar(trials)
    painel = MP.painel(av, 0, moeda=moeda)
    # o (?) dos portões vem de core/porteira (layout fixo, fica em R$):
    # a conferência é só do que o componente monta
    return str(MP.numeros(av["estatisticas"], moeda)), str(painel)


def test_porteira_em_dolar():
    trials = R._trials()
    numeros, _ = _porteira_texto(trials, "USD")
    assert "US$" in numeros and "dólares" in numeros
    _sem_real(numeros)
    av = porteira.avaliar(trials)
    assert "US$" in str(MP.grafico(av["estatisticas"], "USD").layout.xaxis.title.text)
    portoes = str(MP.tabela_portoes(av, "USD"))
    assert "US$" in portoes
    # o valor formatado dos portões em dinheiro segue a moeda
    for p in av["portoes"]:
        if p["valor"] is not None and MP.FORMATO.get(p["nome"]) == "R$":
            assert MP._fmt(p, "USD").startswith(("US$", "-US$"))


def test_porteira_sem_moeda_continua_em_reais():
    numeros, _ = _porteira_texto(R._trials(), "BRL")
    assert "R$" in numeros and "em reais" in numeros


def test_regiao_em_dolar():
    texto = str(MR.cards(MS.resumo(R._trials()), moeda="USD"))
    assert "US$" in texto
    _sem_real(texto)


def test_nuvem_em_dolar():
    fig = scatter.figura(R._trials(), "a", "b", None, "robusto", moeda="USD")
    hover = " ".join(fig.data[0].hovertemplate)
    assert "US$" in hover and "R$" not in hover
    padrao = scatter.figura(R._trials(), "a", "b", None, "robusto")
    assert "R$" in " ".join(padrao.data[0].hovertemplate)


def test_graficos_em_dolar_e_metrica_sem_dinheiro():
    trials = R._trials()
    valores = np.array([l["lucro"] for l in trials], dtype=float)
    d = analytics.distribuicao(valores)
    usd = MC.histograma(d, "lucro", "USD").to_json()
    assert "US$" in usd and "R$" not in usd
    assert "US$" in MC.curva(MS.curva(trials, "lucro"), "lucro", "USD").to_json()
    # None é métrica que não é dinheiro: sem prefixo nenhum
    fr = np.array([l["fr"] for l in trials], dtype=float)
    sem = MC.histograma(analytics.distribuicao(fr), "fr", None).to_json()
    assert "R$" not in sem and "US$" not in sem
    # o bool antigo continua valendo
    assert MC.histograma(d, "lucro", True).to_json() == \
        MC.histograma(d, "lucro", "BRL").to_json()
    assert MC.histograma(d, "lucro", False).to_json() == \
        MC.histograma(d, "lucro", None).to_json()


def test_estado_guarda_o_simbolo_ao_carregar_salva(monkeypatch):
    monkeypatch.setattr(optimizer, "carregar_salva", lambda run_id: [{"trial_id": 1}])
    e = optimizer.Mineracao().estado
    assert e["symbol"] is None
    callbacks._entrar_mineracao_salva(
        e, 7, {"symbol": "MES", "corte": None, "holdout_de": "2025-01-01"})
    assert e["symbol"] == "MES"
    assert e["trials"] == [{"trial_id": 1}] and e["fonte"] == "banco"


def test_moeda_da_mineracao_vem_do_estado_e_nao_do_seletor(monkeypatch):
    estado = optimizer.MINERACAO.estado
    antes = estado.get("symbol")
    try:
        estado["symbol"] = "MES"
        assert callbacks._moeda_da_mineracao() == "USD"
        estado["symbol"] = None
        assert callbacks._moeda_da_mineracao() == "BRL"
    finally:
        estado["symbol"] = antes


def test_rodar_guarda_o_simbolo_no_estado(monkeypatch):
    def sem_dados(*a, **k):
        raise RuntimeError("sem dados")
    monkeypatch.setattr(optimizer.db, "read_bars_parquet", sem_dados)
    m = optimizer.Mineracao()
    m._rodar("MES", "x", {}, {}, {}, {}, None, None, {})
    assert m.estado["symbol"] == "MES"
