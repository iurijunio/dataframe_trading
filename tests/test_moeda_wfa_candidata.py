"""Walk-Forward, Candidata e ficha da estratégia na moeda do ativo.

Em dólar nenhum "R$" nem "em reais" pode sobrar; o WIN (sem `moeda`) continua
idêntico — isso quem garante é `test_referencia_telas.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from core import candidata, wfa  # noqa: E402
from scripts import referencia_telas as R  # noqa: E402
from ui import callbacks_candidata as CC  # noqa: E402
from ui.components import candidata_panel as CP  # noqa: E402
from ui.components import ficha as FI  # noqa: E402
from ui.components import wfa_panel as WP  # noqa: E402

FRASE_WIN = "No mini índice 1 tick vale mais que a corretagem inteira"


def _txt(o) -> str:
    """Todo texto de um componente Dash ou figura Plotly, para a busca."""
    if hasattr(o, "to_json"):
        return o.to_json()
    return str(R._c(o))


def _sem_real(texto: str):
    assert "R$" not in texto
    assert "em reais" not in texto


def _veredito():
    return candidata.veredito([
        candidata.portao("a", True, True, 1500.0, "≥ 1", "dica a",
                         formato=candidata.REAIS),
        candidata.portao("b", False, False, 2, "≥ 3", "dica b")])


# ------------------------------------------------------------- Walk-Forward
def test_curva_em_dolar():
    passos, o = R._passos(), R._oos()
    fixas_dias = np.arange(np.datetime64("2022-07-01"), np.datetime64("2023-12-01"))
    fixas = {"dias": fixas_dias,
             "quantis": {p: np.full(len(fixas_dias), R.CAPITAL + p)
                         for p in (10, 25, 50, 75, 90)},
             "finais": np.array([10.0, 50.0, 500.0])}
    fig = WP.curva(o["ts"], o["liq"], o["steps"], passos, R.CAPITAL, fixas,
                   holdout_de="2023-06-15 00:00:00", moeda="USD")
    t = _txt(fig)
    _sem_real(t)
    assert "US$" in t


def test_kpis_em_dolar():
    passos, o = R._passos(), R._oos()
    ag = {"wfe_global": 0.9, "consistencia_lucro": 100.0, "lucro_mes_oos": 321.0}
    t = _txt(WP.kpis(passos, o["ts"], o["liq"], ag, R.CAPITAL,
                     custo=o["custo"], saida=o["saida"], moeda="USD"))
    _sem_real(t)
    assert "US$" in t and "dólares" in t


def test_dicas_oos_moeda():
    assert "em dólares" in WP.dicas_oos("USD")["lucro líquido"]
    assert "US$ 1 perdido" in WP.dicas_oos("USD")["profit factor"]
    assert WP.DICAS_OOS == WP.dicas_oos("BRL")
    assert "em reais" in WP.DICAS_OOS["lucro líquido"]
    assert "R$ 1 perdido" in WP.DICAS_OOS["profit factor"]


def test_selo_e_portoes_em_dolar():
    ver = _veredito()
    t = _txt(WP.selo(ver, moeda="USD"))
    assert "US$ 1.500,00" in t and "R$" not in t
    assert "R$ 1.500,00" in _txt(WP.selo(ver))
    assert WP._fmt_portao(ver["portoes"][0], "USD") == "US$ 1.500,00"
    assert WP._fmt_portao(ver["portoes"][0]) == "R$ 1.500,00"
    p = {"nome": "lucro", "valor": -3.0, "ok": False, "critico": True,
         "exigido": "> 0", "dica": "d"}
    assert WP._fmt_portao(p, "USD") == "-US$ 3,00"
    assert "US$" in _txt(WP._linha_portao(ver["portoes"][0], "USD"))


def test_regiao_larga_em_dolar():
    trials, espaco, deploy = R._grade_plato([5, 6, 8, 9, 10, 9, 8, 6, 5], 4)
    perfil = candidata.perfil_plato(trials, espaco, deploy)
    portoes = [{**candidata.portao("x", True, True, 50.0, "> 0", "d",
                                    formato=candidata.REAIS)}]
    t = _txt(WP.regiao_larga(perfil, portoes, run_id=1, moeda="USD"))
    assert "US$ 50,00" in t and "R$" not in t


def test_fita_cards_e_mensal_em_dolar():
    passos, o = R._passos(), R._oos()
    mes = wfa.mensal(o["ts"], o["liq"], wfa.meses_oos(passos))
    t_fita = _txt(WP.fita(passos, "USD"))
    assert "R$" not in t_fita and "US$" in t_fita
    t_cards = _txt(WP.cards_mensais(mes, "USD"))
    assert "US$" in t_cards and "R$" not in t_cards
    t_mensal = _txt(WP.mensal_fig(mes, "USD"))
    assert "US$" in t_mensal and "R$" not in t_mensal


# ---------------------------------------------------------------- Candidata
def test_candidata_linhas_e_blocos_em_dolar():
    leitura = R._leitura()
    gate = {"pregoes_holdout": 42, "lucro_mes_holdout": 850.0,
            "lucro_mes_antes": 620.0}
    grupos = CP.linhas(leitura, R.CAPITAL, True, "2023-01-02", "2023-12-29",
                       gate, moeda="USD")
    t = str(grupos)
    _sem_real(t)
    assert "US$" in t and "dólares" in t
    t2 = _txt(CP.bloco_robustez(leitura, R.CAPITAL, True, "2023-01-02",
                                "2023-12-29", gate, moeda="USD"))
    _sem_real(t2)
    assert "US$ 850,00/mês no holdout" in t2


def test_candidata_tamanho_em_dolar():
    dim, _zero, ref, disj = R._tamanho()
    dim = {**dim, "margem": 1500.0}
    t = str(CP.linhas_tamanho(dim, ref, disj, R.CAPITAL, moeda="USD"))
    _sem_real(t)
    assert "US$ 1.500,00" in t and "dólares" in t
    _sem_real(_txt(CP.bloco_tamanho(dim, ref, disj, R.CAPITAL, moeda="USD")))
    # sem moeda: o texto de hoje
    assert "em reais" in str(CP.linhas_tamanho(dim, ref, disj, R.CAPITAL))


def _acha(c, pred):
    if isinstance(c, (list, tuple)):
        return [a for x in c for a in _acha(x, pred)]
    if c is None or isinstance(c, str):
        return []
    achados = [c] if pred(c) else []
    return achados + _acha(getattr(c, "children", None), pred)


def _folhas(c):
    if isinstance(c, (list, tuple)):
        return [t for x in c for t in _folhas(x)]
    if isinstance(c, str):
        return [c]
    f = getattr(c, "children", None)
    if isinstance(f, str):
        return [f]
    if f is None:
        return []
    return [t for x in (f if isinstance(f, (list, tuple)) else [f])
            for t in _folhas(x)]


def test_rotulo_da_garantia_tem_o_span_da_moeda():
    ent = CP.entradas_tamanho()
    spans = _acha(ent, lambda c: isinstance(getattr(c, "id", None), dict)
                  and c.id.get("type") == "moeda-cand")
    assert [s.id["i"] for s in spans] == ["margem"]
    assert spans[0].children == "R$"
    rot = next(l for l in _acha(ent, lambda c: type(c).__name__ == "Label")
               if spans[0] in _acha(l, lambda c: c is spans[0]))
    assert "".join(_folhas(rot)).startswith("garantia por contrato (R$)")


# ------------------------------------------------------------ portão de custo
def test_portao_custo_mes_sem_frase_do_mini_indice():
    d = candidata.portao_custo(1500.0, np.ones(510), 1.25, simbolo="MES")["dica"]
    assert "mini índice" not in d
    assert d.startswith("O lucro depois de pagar 1 tick a mais")
    assert d.endswith("Se o lucro some, a estratégia vive no limite do custo.")
    assert "  " not in d


def test_portao_custo_win_igual_ao_de_hoje():
    hoje = candidata.portao_custo(1500.0, np.ones(510), 0.2)["dica"]
    assert FRASE_WIN in hoje
    assert candidata.portao_custo(1500.0, np.ones(510), 0.2,
                                  simbolo="WIN$N")["dica"] == hoje
    assert candidata.portao_custo(1500.0, np.ones(510), 0.2,
                                  simbolo="SEM_YAML")["dica"] == hoje


def test_portoes_rapidos_repassa_o_simbolo():
    trials, espaco, deploy = R._grade_plato([5] * 9, 4)
    args = (R._trades_rapidos(),
            {"resumo": {"lucro_liquido": 1800.0},
             "boot": {"dd_p95": 800.0, "perdas_seguidas_p95": 5.0,
                      "submerso_p95": 20.0}, "boot_12m": {}},
            trials, espaco, deploy)
    kw = dict(corte="2024-06-01", tick_value=1.0, capital=R.CAPITAL)

    def custo(**extra):
        g = candidata.portoes_rapidos(*args, **kw, **extra)
        return next(p for p in g if p["nome"] == "Aguenta custo maior?")

    assert "mini índice" not in custo(simbolo="MES")["dica"]
    assert FRASE_WIN in custo(simbolo="WIN$N")["dica"]
    assert custo()["dica"] == custo(simbolo="WIN$N")["dica"]


# -------------------------------------------------------------------- ficha
def _estrategia():
    return SimpleNamespace(
        label="x", params_schema={"p": {"label": "P", "default": 1}})


def test_ficha_em_dolar_e_padrao_brl():
    perfil = {"risco_por_trade": 200.0, "capital_inicial": 25_000.0,
              "limite_ganho_contrato": 150.0, "limite_perda_contrato": 100.0}
    kw = dict(estrategia=_estrategia(), params={}, perfil=perfil, espaco={})
    usd = _txt(FI.ficha(**kw, moeda="USD"))
    assert "US$" in usd and "R$" not in usd
    padrao = _txt(FI.ficha(**kw))
    assert "R$" in padrao
    assert padrao == _txt(FI.ficha(**kw, moeda="BRL"))
    assert FI.formatar("capital_inicial", "brl", 10.0, "USD") == "US$ 10,00"
    assert FI.formatar("capital_inicial", "brl", 10.0) == "R$ 10,00"


# --------------------------------------------------------------- cand_tamanho
class _AppFalso:
    def __init__(self):
        self.funcs, self.saidas = {}, {}

    def callback(self, *args, **kw):
        def deco(fn):
            self.funcs[fn.__name__] = fn
            self.saidas[fn.__name__] = args
            return fn
        return deco


def test_cand_tamanho_devolve_o_simbolo_da_moeda(monkeypatch):
    app = _AppFalso()
    CC.register(app)
    fn = app.funcs["cand_tamanho"]
    saidas = [o for o in app.saidas["cand_tamanho"]
              if getattr(o, "component_id", None) == {"type": "moeda-cand",
                                                      "i": CC.ALL}]
    assert len(saidas) == 1 and saidas[0].component_property == "children"

    dim, _zero, ref, disj = R._tamanho()
    det = {"symbol": "MES", "capital": R.CAPITAL}
    monkeypatch.setattr(CC.wfa_store, "detalhes", lambda wid: det)
    monkeypatch.setattr(CC, "leitura_do_wfa",
                        lambda wid, d: {"leitura": R._leitura(), "trades": [],
                                        "de": None, "ate": None})
    monkeypatch.setattr(CC, "_dimensionar",
                        lambda *a, **k: (ref, {**dim, "margem": 1500.0}, disj))
    corpo, rotulo = fn(7, 1.0, 1500.0, 50.0)
    assert rotulo == ["US$"]
    t = _txt(corpo)
    assert "US$ 1.500,00" in t and "R$" not in t

    det["symbol"] = "WIN$N"
    corpo, rotulo = fn(7, 1.0, 1500.0, 50.0)
    assert rotulo == ["R$"]
    assert "R$ 1.500,00" in _txt(corpo)

    assert fn(None, 1.0, None, 50.0)[1] == ["R$"]


def test_cand_tamanho_sem_capital_mantem_a_moeda_do_ativo(monkeypatch):
    app = _AppFalso()
    CC.register(app)
    fn = app.funcs["cand_tamanho"]
    det = {"symbol": "MES", "capital": None}
    monkeypatch.setattr(CC.wfa_store, "detalhes", lambda wid: det)
    _corpo, rotulo = fn(7, 1.0, 1500.0, 50.0)
    assert rotulo == ["US$"]
    det["symbol"] = "WIN$N"
    _corpo, rotulo = fn(7, 1.0, 1500.0, 50.0)
    assert rotulo == ["R$"]
