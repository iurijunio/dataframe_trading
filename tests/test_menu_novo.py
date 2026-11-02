"""Menu novo da esquerda: topo fixo, cinco abas, gavetas.

Topo fixo com ativo, estratégia, datas, tempo gráfico e "excluir holdout";
abaixo, as abas Entrada | Saída | Filtros | Risco | Períodos. Aba com um
grupo mostra os campos direto; com dois ou mais, cada grupo é uma gaveta com
resumo. Na subtela Backtest não há aba Períodos nem Filtro de mineração.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from dash import html

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from ui import callbacks as CB  # noqa: E402
from ui.app import build  # noqa: E402
from ui.components import controls  # noqa: E402

# a tabela da spec: aba → títulos das gavetas (aba de um grupo: nenhuma)
GRUPOS = {
    "entrada": [],
    "saida": ["Gestão", "Proteções"],
    "filtros": ["Filtro de mercado", "Janela", "Filtro de mineração"],
    "risco": ["Limites diários", "Custos", "Posição"],
    "periodos": [],
}
ESTADO = {"estrategia-nota", "wf-resumo", "mine-salvo"}


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


def _filhos(c):
    f = getattr(c, "children", None)
    if f is None or isinstance(f, (str, int, float)):
        return []
    return list(f) if isinstance(f, (list, tuple)) else [f]


def _todos(c):
    yield c
    for f in _filhos(c):
        yield from _todos(f)


def _achar(c, id_):
    return next((x for x in _todos(c) if getattr(x, "id", None) == id_), None)


def _texto(c) -> str:
    if isinstance(c, str):
        return c
    f = getattr(c, "children", None)
    if isinstance(f, str):
        return f
    return "".join(_texto(x) for x in _filhos(c))


def _titulos(pane):
    """Títulos das gavetas (o texto do Summary sem o resumo)."""
    out = []
    for g in _todos(pane):
        if isinstance(g, html.Details):
            titulo = next(x for x in _todos(g) if "gaveta-titulo" in
                          (getattr(x, "className", None) or "").split())
            out.append(_texto(titulo).strip())
    return out


def _pane(arv, aba):
    return _achar(arv, {"type": "menu-pane", "aba": aba})


def _funcoes(app) -> dict:
    fns = {}
    for cb in app.callback_map.values():
        f = cb.get("callback")
        if f is not None:
            fns[f.__name__] = getattr(f, "__wrapped__", f)
    return fns


# ------------------------------------------------------------------ layout
def test_ativo_no_menu_e_nao_no_topo(app):
    lay = app.layout
    assert _achar(_achar(lay, "sidebar"), "ativo") is not None
    topo = next(x for x in _todos(lay) if getattr(x, "className", None) == "topbar")
    assert _achar(topo, "ativo") is None


def test_topo_fixo_tem_os_campos(app):
    sb = _achar(app.layout, "sidebar")
    topo = next(x for x in _todos(sb) if getattr(x, "className", None) == "menu-topo")
    for i in ("ativo", "estrategia", "d-de", "d-ate", "e-timeframe",
              "excluir-holdout", "menu-aba"):
        assert _achar(topo, i) is not None, i
    aba = _achar(topo, "menu-aba")
    assert aba.value == "entrada"
    assert [o["value"] for o in aba.options] == list(GRUPOS)


def test_abas_e_grupos(app):
    sb = _achar(app.layout, "sidebar")
    for aba, titulos in GRUPOS.items():
        pane = _pane(sb, aba)
        assert pane is not None, aba
        assert _titulos(pane) == titulos, aba
    entrada = _pane(sb, "entrada")
    for i in ("params-body", "e-direcao", "e-sem-ent1", "e-sem-ent2", "e-sem-ent3"):
        assert _achar(entrada, i) is not None, i
    gestao = _achar(sb, {"type": "gaveta", "g": "gestao"})
    assert _achar(gestao, {"type": "val", "p": "trailing_pontos"}) is not None
    assert _achar(_pane(sb, "periodos"), "sec-mineracao") is not None
    # a primeira gaveta de cada aba abre; as outras, fechadas
    for aba, titulos in GRUPOS.items():
        gav = [g for g in _todos(_pane(sb, aba)) if isinstance(g, html.Details)]
        assert [bool(g.open) for g in gav] == [i == 0 for i in range(len(gav))], aba


def test_execucao_continua_com_todos_os_grupos():
    ids = {str(getattr(c, "id", None)) for c in _todos(controls.execucao())}
    for i in ("e-filtro-adx", "e-ent-ini", "e-dias", "e-direcao", "e-sem-ent3",
              "e-alvo-tipo", "e-stop-tipo", "e-max-barras", "e-lim-ganho",
              "e-corretagem", "e-modo", "e-capital", "e-min-ops",
              "blk-stop-pct", "blk-alvo-razao"):
        assert i in ids, i
    assert str({"type": "val", "p": "trailing_pontos"}) in ids


def test_sem_texto_explicativo_solto(app):
    sb = _achar(app.layout, "sidebar")
    soltos = [c for c in _todos(sb)
              if isinstance(c, (html.P, html.Span))
              and "fld-hint" in (getattr(c, "className", None) or "").split()
              and getattr(c, "id", None) not in ESTADO]
    assert not soltos, [_texto(c) for c in soltos]
    # e o texto foi para o (?) — não sumiu
    dicas = [c for c in _todos(sb)
             if "dica-mark" in (getattr(c, "className", None) or "").split()]
    textos = " ".join(getattr(c, "data-dica", "") or "" for c in dicas)
    for t in ("0 desliga", "Ao bater, o dia para", "cobrado por ponta",
              "risco:retorno", "onde o stop vai parar",
              "combinação com menos que isso"):
        assert t in textos, t


def test_dica_fora_do_label(app):
    for lb in _todos(_achar(app.layout, "sidebar")):
        if isinstance(lb, html.Label):
            assert not any("dica-mark" in (getattr(x, "className", None) or "")
                           for x in _todos(lb))


# ---------------------------------------------------------------- callbacks
def test_periodos_some_no_backtest(app):
    menu_abas = _funcoes(app)["menu_abas"]
    valor, opcoes, *panes, filtro_min = menu_abas("periodos", "mineracao", "backtest")
    estilos = dict(zip(controls.ABAS_MENU, panes))
    assert valor == "entrada"
    assert estilos["entrada"] != CB.OCULTO
    assert all(estilos[a] == CB.OCULTO for a in controls.ABAS_MENU if a != "entrada")
    assert "periodos" not in [o["value"] for o in opcoes]
    assert filtro_min == CB.OCULTO
    # na Varredura, tudo de volta
    valor, opcoes, *panes, filtro_min = menu_abas("periodos", "mineracao", "varredura")
    estilos = dict(zip(controls.ABAS_MENU, panes))
    assert estilos["periodos"] != CB.OCULTO and estilos["entrada"] == CB.OCULTO
    assert "periodos" in [o["value"] for o in opcoes]
    assert filtro_min != CB.OCULTO


def test_pontinho(app):
    pontinhos = _funcoes(app)["pontinhos"]
    ids = [{"type": "opt-on", "p": "periodo"}, {"type": "opt-on", "p": "stop_pontos"},
           {"type": "opt-on", "p": "adx_limiar"}]
    cls = pontinhos([[], ["on"], []], ids, "mineracao", "varredura")
    assert "dot-saida" in cls.split()
    assert not any(c in cls.split() for c in ("dot-entrada", "dot-filtros"))
    cls = pontinhos([[], [], []], ids, "mineracao", "varredura")
    assert not [c for c in cls.split() if c.startswith("dot-")]
    # no Backtest, sem pontinho
    cls = pontinhos([[], ["on"], []], ids, "mineracao", "backtest")
    assert not [c for c in cls.split() if c.startswith("dot-")]


def test_resumo_gestao():
    r = CB.resumo_gestao("pontos", "pontos", 8, 16, 0)
    assert "8" in r and "16" in r and "0" in r
    assert r == "stop 8 · alvo 16 · trailing 0"
    assert "ATR" in CB.resumo_gestao("atr", "pontos", 8, 16, 0, stop_atr=(20, 1.5))


def test_resumos_textos():
    assert CB.resumo_protecoes(0, 0, 0, 0) == "desligadas"
    assert CB.resumo_janela("09:30", "15:45", "17:00", [1, 2, 3, 4, 5]).startswith(
        "09:30–15:45")
    assert "seg–sex" in CB.resumo_janela("09:30", "15:45", "17:00", [1, 2, 3, 4, 5])
    assert CB.resumo_limites(0, 0, 0, 0, "R$") == "sem limite"
    assert "US$" in CB.resumo_custos(0.5, 0.27, 1, "US$")
    assert "US$" in CB.resumo_posicao("contratos_fixos", 1, 200, 10000, "US$")
    assert CB.resumo_filtro_mercado("tendencia", 0, 25) == "sem filtro"


def test_trocar_estrategia_mantem_aba(app):
    donos_params = [c for k, c in app.callback_map.items() if "params-body.children" in k]
    assert donos_params
    for k, _c in app.callback_map.items():
        if "params-body.children" in k:
            assert "menu-aba.value" not in k
    donos_aba = [k for k in app.callback_map if "menu-aba.value" in k]
    assert len(donos_aba) == 1
    entradas = app.callback_map[donos_aba[0]]["inputs"]
    assert {e["id"] for e in entradas} <= {"menu-aba", "modo", "mine-subtela"}
