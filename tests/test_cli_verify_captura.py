"""`cli.py verify` reconstrói as barras do Parquet, que não tem o dia de hoje:
com a captura rodando ele apagaria as barras gravadas hoje."""
from __future__ import annotations

import json
from argparse import Namespace
from datetime import datetime, timedelta

import pytest

import cli


def _estado(tmp_path, monkeypatch, segundos_atras):
    p = tmp_path / "estado.json"
    quando = datetime.now() - timedelta(seconds=segundos_atras)
    p.write_text(json.dumps({"atualizado_em": quando.isoformat()}), encoding="utf-8")
    monkeypatch.setattr(cli, "ESTADO_CAPTURA", p)


def test_verify_recusa_com_captura_ativa(tmp_path, monkeypatch):
    _estado(tmp_path, monkeypatch, 5)
    with pytest.raises(SystemExit, match="feche a captura antes"):
        cli.cmd_verify(Namespace(symbol="WIN$N"))


def test_captura_parada_ou_sem_estado_nao_bloqueia(tmp_path, monkeypatch):
    _estado(tmp_path, monkeypatch, 600)
    assert cli._captura_ativa() is False
    monkeypatch.setattr(cli, "ESTADO_CAPTURA", tmp_path / "nao_existe.json")
    assert cli._captura_ativa() is False
