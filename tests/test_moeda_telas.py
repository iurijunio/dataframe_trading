"""Backtest, Detalhes, Robustez, gráficos e grade de trades na moeda do ativo.

Cada tela recebe `moeda`; em dólar nenhum "R$" nem "em reais" pode sobrar, e o
WIN (sem `moeda`) continua idêntico — isso quem garante é
`test_referencia_telas.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core import analytics, detalhes, porteira, robustez  # noqa: E402
from core import ativo as ativo_mod  # noqa: E402
from core.engine import kernel as K  # noqa: E402
from scripts import referencia_telas as R  # noqa: E402
from ui import callbacks  # noqa: E402
from ui.components import analytics_charts as AC  # noqa: E402
from ui.components import detalhes_cards as DC  # noqa: E402
from ui.components import results_grid  # noqa: E402
from ui.components import robustez_cards as RC  # noqa: E402
from ui.components import stats_cards as SC  # noqa: E402


@pytest.fixture(scope="module")
def corrida():
    return R._corrida()


def _sem_real(texto: str):
    assert "R$" not in texto
    assert "em reais" not in texto


def _detalhes(corrida, moeda):
    res, din, m = corrida
    f = ativo_mod.ficha(R.SIMBOLO)
    liq, t = din["liquido"], res.trades
    ex = ativo_mod.trades_para_exibir(t, f)
    tp = ativo_mod.pontos_para_exibir(res.tp_at_entry, f)
    sl = ativo_mod.pontos_para_exibir(res.sl_at_entry, f)
    return DC.render(
        m, detalhes.sequencias(liq),
        detalhes.eficiencia(ex["mae"], ex["mfe"], ex["points"], tp,
                            ex["reason"], K.EXIT_TARGET),
        detalhes.risco_trade(liq, ex["points"], sl, ex["reason"], K.EXIT_STOP, 0),
        detalhes.ritmo(t["entry_ts"], liq, int(ex["bars_held"].sum()),
                       res.n_bars, 80),
        AC.barras(detalhes.resultado_por_volume(t["entry_ts"], liq), "x",
                  moeda=moeda),
        casas=0, moeda=moeda)


def _robustez(corrida, moeda):
    res, din, _m = corrida
    liq, t = din["liquido"], res.trades
    dias = int((t["exit_ts"][-1] - t["entry_ts"][0]).astype("timedelta64[D]")
               .astype(int))
    p = res.profile
    return RC.render(
        robustez.monte_carlo(liq, R.CAPITAL), robustez.significancia(liq),
        robustez.teste_runs(liq), robustez.correlacao_lr(liq, R.CAPITAL),
        robustez.concentracao(liq), robustez.ulcer_mar(liq, R.CAPITAL, dias),
        robustez.meses_positivos(t["entry_ts"], liq),
        robustez.custo_que_zera(float(din["bruto"].sum()), din["contratos"],
                                p.corretagem_por_contrato
                                + p.emolumentos_por_contrato),
        robustez.drawdowns(t["entry_ts"], liq, R.CAPITAL), porteira.sqn(liq),
        moeda=moeda)


def test_cartoes_do_backtest_em_dolar():
    m = R._resumo()
    texto = str(SC.render(m, "USD"))
    assert "US$" in texto and "dólares" not in texto  # os cartões não citam o nome
    _sem_real(texto)
    # as dicas com exemplo em dinheiro seguem o símbolo
    dicas = {i["rotulo"]: i["explica"] for i in SC.itens(m, moeda="USD")}
    assert "cada US$ 1 perdido" in dicas["profit factor"]
    assert "US$ 5 por trade" in dicas["expectativa"]
    assert str(SC.cartoes(m, moeda="USD")["lucro líquido"]).count("US$") >= 2


def test_dica_trocada_continua_valendo_com_moeda():
    cs = SC.cartoes(R._resumo(), {"sharpe": "texto novo"}, moeda="USD")
    assert "texto novo" in str(cs["sharpe"])


def test_detalhes_em_dolar(corrida):
    texto = str(_detalhes(corrida, "USD"))
    assert "US$" in texto and "dólares" in texto
    _sem_real(texto)


def test_robustez_em_dolar(corrida):
    texto = str(_robustez(corrida, "USD"))
    assert "US$" in texto and "dólares" in texto
    _sem_real(texto)


def test_graficos_em_dolar(corrida):
    res, din, _m = corrida
    f = ativo_mod.ficha(R.SIMBOLO)
    liq, t = din["liquido"], res.trades
    ex = ativo_mod.trades_para_exibir(t, f)
    diag = analytics.calor_mae_mfe(ex["mae"], ex["mfe"], liq)
    figs = [
        AC.ganho_perda(analytics.por_hora(t["entry_ts"], liq, f), "x", "USD"),
        AC.calendario(analytics.calendario_mensal(t["entry_ts"], liq),
                      moeda="USD"),
        AC.mae_mfe(diag, 150, 300, "USD"),
        AC.barras(analytics.por_duracao(ex["bars_held"], liq, 5), "x",
                  moeda="USD"),
        AC.histograma(analytics.distribuicao(liq), moeda="USD"),
    ]
    for fig in figs:
        js = fig.to_json()
        assert "US$" in js
        _sem_real(js)


def test_colunas_da_grade_em_dolar():
    cab = {c["field"]: c["headerName"] for c in results_grid.colunas("USD")}
    assert cab["liquido"] == "líquido US$"
    assert results_grid.COLUNAS == results_grid.colunas("BRL")
    assert results_grid.COLUNAS[7]["headerName"] == "líquido R$"


def test_detalhes_e_robustez_do_callback_seguem_a_moeda_do_ativo(corrida):
    res, din, m = corrida
    run = {"profile": res.profile, "metrics": m, "dinheiro": din,
           "simbolo": "MES", "pregoes": 80}
    liq = din["liquido"]
    f = ativo_mod.ficha("MES")
    assert f.currency == "USD"
    d = str(callbacks._detalhes(res, run, liq, f))
    assert "US$" in d and "R$" not in d
    assert "US$" in str(callbacks._robustez(res, run, liq))
    assert "R$" not in str(callbacks._robustez(res, run, liq))
