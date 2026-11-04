"""Mineração com duas subtelas: Varredura | Backtest.

Clicar numa linha da tabela, num ponto da nuvem ou numa aprovada carrega a
combinação, roda o backtest e pula para a subtela Backtest. Carregar uma
mineração salva (ou a tabela sendo reescrita durante a varredura) não pula.
No alto da subtela Backtest, uma linha diz qual combinação está carregada.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from dash import no_update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from ui import callbacks as CB  # noqa: E402
from ui.app import build  # noqa: E402

LINHA = {"n": 3, "params": {"stop_pontos": 10}, "trial_id": 3}
IDS_VAL = [{"type": "val", "p": "stop_pontos"}, {"type": "val", "p": "alvo_pontos"}]
VALORES = [300, 600]


@pytest.fixture
def app(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00'"
                f" + INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")
    return build()


def _funcoes(app) -> dict:
    fns = {}
    for cb in app.callback_map.values():
        f = cb.get("callback")   # os clientside não têm função Python
        if f is not None:
            fns[f.__name__] = getattr(f, "__wrapped__", f)
    return fns


def _achar(comp, id_):
    if getattr(comp, "id", None) == id_:
        return comp
    filhos = getattr(comp, "children", None)
    if filhos is None or isinstance(filhos, str):
        return None
    for f in (filhos if isinstance(filhos, (list, tuple)) else [filhos]):
        achado = _achar(f, id_)
        if achado is not None:
            return achado
    return None


def _menu(**troca):
    """O menu como o snapshot o guarda, com a linha já aplicada."""
    m = {"val:stop_pontos": 10, "val:alvo_pontos": 600,
         "excluir-holdout": ["on"], "e-dias": [1, 2, 3, 4, 5]}
    m.update(troca)
    return m


# ------------------------------------------------------- pular para o backtest
def test_linha_da_tabela_pula_para_backtest():
    vals, holdout, n_run, subtela, store = CB._carregar_combinacao(
        "grid-mine", [LINHA], None, None, IDS_VAL, [LINHA], 4,
        valores_val=VALORES)
    assert subtela == "backtest"
    assert n_run == 5
    assert vals == [10, no_update] and holdout == ["on"]
    assert store["origem"] == "linha" and store["n"] == 3
    assert store["params"] == {"stop_pontos": 10}


def test_sem_selecao_nao_pula():
    # é o que `progresso` deixa ao carregar mineração salva
    saida = CB._carregar_combinacao("grid-mine", [], None, None, IDS_VAL,
                                    [LINHA], 4, valores_val=VALORES)
    assert saida[3] is no_update and saida[4] is no_update
    assert saida[2] is no_update


def test_nuvem_e_aprovada():
    clique = {"points": [{"customdata": 3}]}
    s = CB._carregar_combinacao("scatter", None, clique, None, IDS_VAL,
                                [LINHA], 0, valores_val=VALORES)
    assert s[3] == "backtest" and s[4]["origem"] == "nuvem" and s[4]["n"] == 3
    apr = [{"n": 2, "params": {"stop_pontos": 10}, "trial_id": 9}]
    s = CB._carregar_combinacao("grid-aprovadas", None, None, apr, IDS_VAL,
                                [LINHA], 0, valores_val=VALORES)
    assert s[3] == "backtest" and s[4]["origem"] == "aprovada" and s[4]["n"] == 2


def test_so_os_parametros_varridos_entram_na_linha():
    linha = {"n": 1, "trial_id": 1,
             "params": {"stop_pontos": 10, "alvo_pontos": 600}}
    s = CB._carregar_combinacao(
        "grid-mine", [linha], None, None, IDS_VAL, [linha], 0,
        valores_val=VALORES,
        ids_on=[{"type": "opt-on", "p": "stop_pontos"},
                {"type": "opt-on", "p": "alvo_pontos"}],
        ligados=[["on"], []])
    assert s[4]["params"] == {"stop_pontos": 10}


def test_carregar_mineracao_salva_nao_pula(app):
    for chave, cb in app.callback_map.items():
        entradas = {(e["id"], e["property"]) for e in cb["inputs"]}
        if ("mine-carregar", "value") in entradas:
            assert "mine-subtela.value" not in chave, chave


def test_primeira_rodada_nao_e_editado():
    menu = {"e-dias": [1, 2, 3, 4, 5]}
    *_, store = CB._carregar_combinacao(
        "grid-mine", [LINHA], None, None, IDS_VAL, [LINHA], 0,
        valores_val=VALORES, menu=menu)
    # o que a tela tem depois que o callback escreveu
    atual = CB._menu_atual(IDS_VAL, [10, 600], ["on"], menu)
    assert store["menu"] == atual
    assert CB._linha_combinacao(store, atual) == "linha #3 · stop_pontos=10"


# ------------------------------- clicar de novo na linha já carregada (I1)
def test_reclique_na_linha_carregada_volta_ao_backtest():
    store = {"origem": "linha", "n": 3, "params": {"stop_pontos": 10}}
    assert CB._reclique_mesma_linha("grid-mine", [LINHA], None,
                                    store) == "backtest"
    apr = [{"n": 2, "params": {"stop_pontos": 10}, "trial_id": 9}]
    st_apr = {"origem": "aprovada", "n": 2, "params": {"stop_pontos": 10}}
    assert CB._reclique_mesma_linha("grid-aprovadas", None, apr,
                                    st_apr) == "backtest"


def test_reclique_em_outra_linha_fica_com_a_selecao():
    store = {"origem": "linha", "n": 3, "params": {"stop_pontos": 10}}
    outra = {"n": 4, "params": {"stop_pontos": 12}, "trial_id": 4}
    assert CB._reclique_mesma_linha("grid-mine", [outra], None,
                                    store) is no_update
    # nada carregado ainda: o primeiro clique é do caminho da seleção
    assert CB._reclique_mesma_linha("grid-mine", [LINHA], None,
                                    None) is no_update
    assert CB._reclique_mesma_linha("grid-mine", [], None, store) is no_update
    # mesma "n", outra grade: a aprovada #3 não é a linha #3
    assert CB._reclique_mesma_linha("grid-aprovadas", None, [LINHA],
                                    store) is no_update
    # carregada pela nuvem: clique na tabela segue o caminho da seleção
    nuvem = {**store, "origem": "nuvem"}
    assert CB._reclique_mesma_linha("grid-mine", [LINHA], None,
                                    nuvem) is no_update
    # mesma "n" de outra mineração (parâmetros diferentes)
    nova = {"n": 3, "params": {"stop_pontos": 99}, "trial_id": 3}
    assert CB._reclique_mesma_linha("grid-mine", [nova], None,
                                    store) is no_update


def test_reclique_so_troca_a_subtela(app):
    achados = [cb for cb in app.callback_map.values()
               if getattr(cb.get("callback"), "__name__", "")
               == "reclique_combinacao"]
    assert len(achados) == 1
    cb = achados[0]
    entradas = {(e["id"], e["property"]) for e in cb["inputs"]}
    assert entradas == {("grid-mine", "cellClicked"),
                        ("grid-aprovadas", "cellClicked")}
    assert ("grid-mine", "rowData") not in entradas
    saida = cb["output"]
    assert "mine-subtela.value" in str(saida)
    assert "btn-run" not in str(saida)


def test_nuvem_continua_no_caminho_da_selecao(app):
    # o clique na nuvem segue em carregar_combinacao, não no reclique
    for cb in app.callback_map.values():
        entradas = {(e["id"], e["property"]) for e in cb["inputs"]}
        nome = getattr(cb.get("callback"), "__name__", "")
        if ("scatter", "clickData") in entradas and "btn-run" in str(cb["output"]):
            assert nome == "carregar_combinacao"
        if nome == "reclique_combinacao":
            assert ("scatter", "clickData") not in entradas


# ------------------------------------------------ blocos de ATR em grade (M1)
def test_blocos_atr_aparecem_em_grade(app):
    tipos = _funcoes(app)["tipos"]
    s = dict(zip(["alvo-pontos", "alvo-atr", "alvo-razao", "alvo-pct",
                  "stop-pontos", "stop-atr", "stop-pct"], tipos("atr", "atr")))
    assert s["alvo-atr"] == {"display": "grid"}
    assert s["stop-atr"] == {"display": "grid"}
    assert s["alvo-pontos"] == CB.OCULTO and s["stop-pontos"] == CB.OCULTO
    s = dict(zip(list(s), tipos("pontos", "pontos")))
    assert s["alvo-pontos"] == CB.VISIVEL and s["stop-pontos"] == CB.VISIVEL
    assert s["alvo-atr"] == CB.OCULTO and s["stop-atr"] == CB.OCULTO
    s = dict(zip(list(s), tipos("multiplicador", "percentual")))
    assert s["alvo-razao"] == CB.VISIVEL and s["stop-pct"] == CB.VISIVEL


# ------------------------------------------------------- linha da combinação
def test_linha_da_combinacao():
    base = {"params": {"stop_pontos": 10}, "menu": _menu()}
    assert (CB._linha_combinacao({**base, "origem": "linha", "n": 3}, _menu())
            == "linha #3 · stop_pontos=10")
    assert (CB._linha_combinacao({**base, "origem": "nuvem", "n": 3}, _menu())
            == "nuvem · stop_pontos=10")
    assert (CB._linha_combinacao({**base, "origem": "aprovada", "n": 2}, _menu())
            == "aprovada #2 · stop_pontos=10")
    editado = _menu(**{"e-dias": [1, 2, 3, 4]})
    assert CB._linha_combinacao({**base, "origem": "linha", "n": 3},
                                editado).endswith(" · editado")
    sem_holdout = _menu(**{"excluir-holdout": []})
    assert CB._linha_combinacao({**base, "origem": "linha", "n": 3},
                                sem_holdout).endswith(" · editado")
    outro_val = _menu(**{"val:stop_pontos": 12})
    assert CB._linha_combinacao({**base, "origem": "linha", "n": 3},
                                outro_val).endswith(" · editado")
    assert CB._linha_combinacao(None, _menu()) == ""


def test_ordem_dos_dias_nao_e_edicao():
    base = {"params": {"stop_pontos": 10}, "menu": _menu(), "origem": "linha",
            "n": 3}
    assert not CB._linha_combinacao(
        base, _menu(**{"e-dias": [5, 4, 3, 2, 1]})).endswith("editado")


# ------------------------------------------------------------- telas e menu
def test_faixas_so_na_varredura(app):
    faixas = _funcoes(app)["faixas"]
    optrow, valwrap, chave = faixas([["on"]], "mineracao", "backtest")
    assert optrow == [CB.OCULTO] and valwrap == [CB.VISIVEL]
    assert chave == [CB.OCULTO]
    optrow, valwrap, chave = faixas([["on"]], "mineracao", "varredura")
    assert optrow == [CB.VISIVEL] and valwrap == [CB.OCULTO]
    assert chave == [CB.VISIVEL]


def test_modo_alterna_as_subtelas(app):
    modo = _funcoes(app)["modo"]
    s = dict(zip(["painel-backtest", "painel-mineracao", "painel-wfa",
                  "painel-candidata", "painel-estrategias", "painel-portfolio",
                  "painel-aovivo", "acao-backtest", "sec-mineracao", "sidebar",
                  "mine-bloco-varredura"], modo("mineracao", "backtest")))
    assert s["painel-backtest"] != CB.OCULTO and s["acao-backtest"] != CB.OCULTO
    assert s["mine-bloco-varredura"] == CB.OCULTO
    assert s["sec-mineracao"] == CB.OCULTO
    s = dict(zip(list(s), modo("mineracao", "varredura")))
    assert s["painel-backtest"] == CB.OCULTO and s["acao-backtest"] == CB.OCULTO
    assert s["mine-bloco-varredura"] != CB.OCULTO
    assert s["sec-mineracao"] != CB.OCULTO
    s = dict(zip(list(s), modo("aovivo", "backtest")))
    assert s["painel-backtest"] == CB.OCULTO and s["painel-mineracao"] == CB.OCULTO
    assert s["acao-backtest"] == CB.OCULTO


def test_backtest_dentro_da_mineracao(app):
    mineracao = _achar(app.layout, "painel-mineracao")
    assert _achar(mineracao, "painel-backtest") is not None
    assert _achar(mineracao, "mine-bloco-varredura") is not None
    for id_ in ("btn-run", "acao-backtest", "btn-chart", "mine-combinacao",
                "cards", "chart-capital", "grid-trades"):
        assert _achar(_achar(mineracao, "painel-backtest"), id_) is not None, id_
    sub = _achar(mineracao, "mine-subtela")
    assert sub.value == "varredura"
    assert [o["value"] for o in sub.options] == ["varredura", "busca", "backtest"]
    modo = _achar(app.layout, "modo")
    assert modo.value == "aovivo"
    assert "backtest" not in [o["value"] for o in modo.options]
    assert _achar(app.layout, "store-combinacao") is not None
    assert _achar(_achar(app.layout, "sidebar"), "btn-run") is None


def test_esquecer_combinacao_e_callback_proprio(app):
    donos = [getattr(cb.get("callback"), "__name__", chave)
             for chave, cb in app.callback_map.items()
             if "store-combinacao.data" in chave]
    assert "estrategia_ou_mineracao" not in donos
    # o clique na Varredura, o esquecimento e o "Abrir o campeão" da busca
    assert sorted(donos) == ["carregar_combinacao", "esquecer_combinacao", "ir"]
