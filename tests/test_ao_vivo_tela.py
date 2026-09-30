"""Tela Ao vivo: o que ela desenha a partir do que o core devolve."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import ao_vivo_panel as AP  # noqa: E402


def textos(c) -> str:
    """Todo o texto de uma árvore de componentes Dash, numa string só —
    inclusive o `value` dos campos (nome da conta, limite)."""
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(textos(x) for x in c)
    valor = getattr(c, "value", None)
    extra = str(valor) if isinstance(valor, (str, int, float)) else ""
    return extra + " " + textos(getattr(c, "children", None))


def ids(c) -> set:
    out = set()
    if isinstance(c, (list, tuple)):
        for x in c:
            out |= ids(x)
        return out
    if hasattr(c, "id") and getattr(c, "id", None) is not None:
        out.add(c.id if isinstance(c.id, str) else str(c.id))
    filhos = getattr(c, "children", None)
    if filhos is not None:
        out |= ids(filhos)
    return out


def test_painel_tem_as_pecas():
    p = AP.painel()
    assert p.id == "painel-aovivo"
    esperados = {"av-versao", "av-armado", "av-aberta", "av-aviso",
                 "av-portfolios", "av-variantes", "av-contas",
                 "av-arrumacao", "av-conta-nome", "av-conta-tipo",
                 "av-conta-limite", "av-btn-conta-criar"}
    assert esperados <= ids(p)
    assert "Estratégias" in textos(p)
