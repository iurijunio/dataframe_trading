"""`ativo.pregao_de`: o pregão de um instante UTC nunca cai no sábado nem no domingo."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ativo  # noqa: E402


def _utc(dia: int, hora: int, minuto: int, mes: int = 11) -> datetime:
    return datetime(2026, mes, dia, hora, minuto, tzinfo=timezone.utc)


# 06/11/2026 é sexta; o horário de verão dos EUA acabou em 01/11 (NY = UTC-5). 30/10 ainda é UTC-4.
CASOS_CME = [
    ("sexta 17:30 NY", _utc(6, 22, 30), date(2026, 11, 6)),
    ("sexta 18:30 NY", _utc(6, 23, 30), date(2026, 11, 9)),
    ("sábado meio-dia NY", _utc(7, 17, 0), date(2026, 11, 9)),
    ("domingo 18:30 NY", _utc(8, 23, 30), date(2026, 11, 9)),
    ("sexta 18:30 NY no horário de verão", _utc(30, 22, 30, mes=10), date(2026, 11, 2)),
    ("quarta 18:30 NY segue para quinta", _utc(11, 23, 30), date(2026, 11, 12)),
]


@pytest.mark.parametrize(("nome", "instante", "esperado"), CASOS_CME, ids=[c[0] for c in CASOS_CME])
def test_pregao_do_cme(nome, instante, esperado):
    assert ativo.pregao_de(instante, ativo.ficha("MNQ")) == esperado, nome


def test_pregao_do_win_pula_o_fim_de_semana():
    win = ativo.ficha("WIN$N")
    assert ativo.pregao_de(_utc(7, 15, 0), win) == date(2026, 11, 9)  # sábado
    assert ativo.pregao_de(_utc(8, 15, 0), win) == date(2026, 11, 9)  # domingo
    assert ativo.pregao_de(_utc(11, 15, 0), win) == date(2026, 11, 11)  # quarta
