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


def _base_com_captura(dias_conferidos=()):
    from core import captura as C
    from core import db_manager as db
    from tests.test_captura import barras
    with db.connect_write() as con:
        db.init_schema(con)
        db.sync_instruments(con)
        C.gravar(con, "WIN$N", barras("10:00", "10:01"), C.origem_captura(1, "x"))
        for dia in dias_conferidos:
            C.conferir_dia(con, "WIN$N", dia, barras("10:00", "10:01"),
                           agora=datetime(2026, 10, 1, 18, 40))


def test_verify_recusa_com_dia_da_captura_sem_conferencia(tmp_path, monkeypatch):
    # captura fechada, mas o dia que ela gravou ainda não foi conferido: o
    # Parquet não o tem e a reconstrução o apagaria
    _estado(tmp_path, monkeypatch, 600)
    _base_com_captura()
    reconstruiu = []
    monkeypatch.setattr(cli.db, "rebuild_from_parquet", lambda *a: reconstruiu.append(a))
    with pytest.raises(SystemExit, match="ainda sem conferência"):
        cli.cmd_verify(Namespace(symbol="WIN$N"))
    assert reconstruiu == []


def test_verify_segue_com_os_dias_da_captura_conferidos(tmp_path, monkeypatch, capsys):
    from datetime import date
    _estado(tmp_path, monkeypatch, 600)
    _base_com_captura(dias_conferidos=[date(2026, 10, 1)])
    monkeypatch.setattr(cli.db, "rebuild_from_parquet", lambda *a: None)
    cli.cmd_verify(Namespace(symbol="WIN$N"))
    assert "OK" in capsys.readouterr().out
