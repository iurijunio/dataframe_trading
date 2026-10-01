"""`corrigir_base.py` apaga e refaz a base: com a captura gravando ao mesmo
tempo, os candles de hoje (que o CSV e o Parquet não têm) se perderiam."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import corrigir_base as CB  # noqa: E402


@pytest.fixture
def refez(tmp_path, monkeypatch):
    # sem banco nem MT5: só importa se o comando chega a refazer a base
    monkeypatch.setattr(CB.db, "connect", lambda **k: _ConFalsa())
    monkeypatch.setattr(CB.R, "ja_corrigida", lambda con: True)
    monkeypatch.setattr(CB, "lotes_errados", lambda con: [])
    chamadas = []
    monkeypatch.setattr(CB, "_refazer", lambda csv: chamadas.append(csv))
    return chamadas


class _ConFalsa:
    def close(self):
        pass


def _estado(tmp_path, monkeypatch, segundos_atras):
    p = tmp_path / "estado.json"
    quando = datetime.now() - timedelta(seconds=segundos_atras)
    p.write_text(json.dumps({"atualizado_em": quando.isoformat()}), encoding="utf-8")
    monkeypatch.setattr(CB, "ESTADO_CAPTURA", p)


def _args(**mudar):
    a = {"executar": False, "retomar": True, "lotes": None, "csv": Path("x.csv")}
    a.update(mudar)
    return Namespace(**a)


def test_retomar_recusa_com_a_captura_ativa(tmp_path, monkeypatch, refez, capsys):
    _estado(tmp_path, monkeypatch, 5)
    assert CB.executar(_args()) == 1
    assert refez == []
    assert "Dataframe - Captura" in capsys.readouterr().out


def test_executar_tambem_recusa_com_a_captura_ativa(tmp_path, monkeypatch, refez):
    _estado(tmp_path, monkeypatch, 5)
    assert CB.executar(_args(executar=True, retomar=False)) == 1
    assert refez == []


def test_retomar_segue_com_a_captura_parada(tmp_path, monkeypatch, refez):
    _estado(tmp_path, monkeypatch, 600)
    assert CB.executar(_args()) == 0
    assert refez == [Path("x.csv")]
