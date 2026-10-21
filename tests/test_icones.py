"""Ícones locais: cada nome do helper tem desenho e regra CSS."""
import re
from pathlib import Path

import pytest

from ui.components.icones import ICONES, icone

ASSETS = Path(__file__).resolve().parents[1] / "ui" / "assets"


def test_todo_icone_tem_svg_e_regra_css():
    css = (ASSETS / "icones.css").read_text(encoding="utf-8")
    regras = set(re.findall(r"\.ic-([a-z0-9-]+)\{-webkit-mask-image:url\(icones/\1\.svg\)", css))
    for nome in ICONES:
        assert (ASSETS / "icones" / f"{nome}.svg").is_file(), nome
        assert nome in regras, nome


def test_icone_vira_span_escondido_do_leitor_de_tela():
    s = icone("send")
    assert s.className == "ic ic-send"
    assert getattr(s, "aria-hidden") == "true"
    assert icone("pencil", pequeno=True, classe="x").className == "ic ic-pencil ic-sm x"


def test_nome_errado_e_erro():
    with pytest.raises(ValueError):
        icone("candlestick-chart")
