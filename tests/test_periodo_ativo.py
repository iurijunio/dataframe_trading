"""O calendário (de/até) segue a base do ativo escolhido.

Era montado uma vez, na subida, com a base do ativo padrão (WIN, desde
16/03/2021): o MNQ, com base desde 2019, abria em 2021 e nem deixava escolher
um dia antes disso.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

from dash import no_update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.optimizer import MINERACAO  # noqa: E402
from ui import callbacks as CB  # noqa: E402

SPANS = {"WIN$N": (datetime(2021, 3, 16, 9), datetime(2026, 11, 3, 16, 54)),
         "MNQ": (datetime(2019, 5, 6, 0, 12), datetime(2026, 10, 28, 22, 59))}


def test_trocar_ativo_poe_o_periodo_da_base_dele(monkeypatch):
    monkeypatch.setattr(CB.D, "span", lambda s: SPANS[s])
    monkeypatch.setattr(MINERACAO, "estado", {**MINERACAO.estado,
                                              "rodando": False})
    de, de_min, de_max, ate, ate_min, ate_max = CB._periodo_do_ativo("MNQ")
    assert de == de_min == ate_min == date(2019, 5, 6)
    assert ate == ate_max == de_max == date(2026, 10, 28)


def test_com_mineracao_rodando_o_periodo_fica(monkeypatch):
    monkeypatch.setattr(CB.D, "span", lambda s: SPANS[s])
    monkeypatch.setattr(MINERACAO, "estado", {**MINERACAO.estado,
                                              "rodando": True})
    assert CB._periodo_do_ativo("MNQ") == (no_update,) * 6
