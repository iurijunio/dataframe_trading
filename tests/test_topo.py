"""Topo limpo e tela inicial (menu da esquerda, Task 3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from dash import dcc, html  # noqa: E402

from core import db_manager as db  # noqa: E402
from ui.app import build  # noqa: E402


@pytest.fixture(autouse=True)
def _banco(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00'"
                f" + INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")


def _todos(no):
    yield no
    filhos = getattr(no, "children", None)
    if filhos is None:
        return
    if not isinstance(filhos, (list, tuple)):
        filhos = [filhos]
    for f in filhos:
        if hasattr(f, "children") or hasattr(f, "id"):
            yield from _todos(f)


def _por_id(app, i):
    layout = app.layout() if callable(app.layout) else app.layout
    return [c for c in _todos(layout) if getattr(c, "id", None) == i]


def test_ordem_das_abas():
    app = build()
    modo = _por_id(app, "modo")[0]
    assert [o["value"] for o in modo.options] == [
        "mineracao", "wfa", "candidata", "estrategias", "portfolio", "aovivo"]


def test_sem_botao_de_sincronizar():
    app = build()
    for i in ("btn-mt5-sync", "mt5-sync-status"):
        assert not _por_id(app, i)
    for chave, cb in app.callback_map.items():
        ids = [e["id"] for e in cb["inputs"]] + [s["id"] for s in cb.get("state", [])]
        assert "btn-mt5-sync" not in ids and "mt5-sync-status" not in ids
        assert "mt5-sync-status" not in chave and "btn-mt5-sync" not in chave


def test_ao_vivo_abre_em_estrategias():
    from ui.components import ao_vivo_panel as AV
    casca = Path(AV.__file__)  # o código mora no pacote ao lado da casca
    fonte = "".join(p.read_text(encoding="utf-8") for p in [casca, *sorted(casca.with_name("ao_vivo").glob("*.py"))])
    app = build()
    layout = app.layout() if callable(app.layout) else app.layout
    sub = [c for c in _todos(layout) if getattr(c, "id", None) == "av-subtela"]
    assert sub, "av-subtela fora do layout"
    assert sub[0].value == "estrategias"
    assert getattr(sub[0], "persistence", None) in (None, False)
    assert "persistence" not in fonte.split('id="av-subtela"')[1].split("options")[0]
