"""Rotulos fixos de dinheiro da camada 4 seguem a moeda do ativo."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core import db_manager as db  # noqa: E402
from ui import callbacks as CB  # noqa: E402
from ui.app import build  # noqa: E402

ITENS = ["lim-ganho", "lim-perda", "risco", "capital"]


def _texto(c) -> str:
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, (list, tuple)):
        return "".join(_texto(x) for x in c)
    return _texto(getattr(c, "children", None))


def _acha(c, pred, saida):
    if pred(c):
        saida.append(c)
    f = getattr(c, "children", None)
    if isinstance(f, (list, tuple)):
        for x in f:
            _acha(x, pred, saida)
    elif f is not None and not isinstance(f, str):
        _acha(f, pred, saida)
    return saida


@pytest.fixture
def app(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, src_ingest_id) "
                "VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00' "
                f"+ INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")
    return build()


def _spans(app):
    return _acha(app.layout() if callable(app.layout) else app.layout,
                 lambda c: isinstance(getattr(c, "id", None), dict)
                 and c.id.get("type") == "moeda-c4", [])


def _labels(app):
    lay = app.layout() if callable(app.layout) else app.layout
    return [_texto(l) for l in _acha(lay, lambda c: type(c).__name__ == "Label", [])]


def test_quatro_spans_moeda_c4(app):
    spans = _spans(app)
    assert sorted(s.id["i"] for s in spans) == sorted(ITENS)
    assert all(s.children == "R$" for s in spans)


def test_texto_visivel_dos_rotulos_inalterado(app):
    rot = _labels(app)
    for t in ("ganho máx. R$/contrato", "perda máx. R$/contrato",
              "risco/trade R$", "capital inicial R$"):
        assert t in rot


def test_rotulos_moeda():
    assert CB.rotulos_moeda("MES", 4) == ["US$"] * 4
    assert CB.rotulos_moeda("WIN$N", 4) == ["R$"] * 4
    assert CB.rotulos_moeda(None, 4) == ["R$"] * 4


def test_callback_registrado_com_entrada_do_ativo(app):
    achados = [v for k, v in app.callback_map.items() if "moeda-c4" in k]
    assert len(achados) == 1
    assert {"id": "ativo", "property": "value"} in achados[0]["inputs"]
