"""Contrato do pacote das mesas: ida e volta, versão, escrita atômica."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contratos import pacote_mesa as pm  # noqa: E402


def _pacote() -> pm.Pacote:
    return pm.Pacote(
        format_version=pm.FORMATO,
        exported_at=datetime(2026, 11, 11, 9, 0),
        session_date=date(2026, 11, 11),
        platform_commit="abc123",
        engine_version="2026.10.09",
        portfolio=pm.PortfolioPacote(id=7, name="p", capital=50000.0, currency="BRL"),
        variants=(pm.VariantePacote(
            id=1, name="v", strategy="rompimento_canal", plan_id=3, symbol="WIN$N",
            timeframe="M15", contracts=2, breaker={"nivel2.queda": 900.0},
            engine_plan={"plano_id": 3, "params": {"a": 1}, "contratos": 2}),),
        instrument={"symbol": "WIN$N", "currency": "BRL", "tick_size": 5, "tick_value": 1.0,
                    "point_value": 0.2, "price_decimals": 0, "pregoes_descartados": {}},
    )


def test_ida_e_volta(tmp_path):
    destino = tmp_path / "p.json"
    pm.gravar(_pacote(), destino)
    assert pm.ler(destino) == _pacote()


def test_json_tem_as_chaves_em_ingles(tmp_path):
    destino = tmp_path / "p.json"
    pm.gravar(_pacote(), destino)
    bruto = json.loads(destino.read_text(encoding="utf-8"))
    assert set(bruto) == {"format_version", "exported_at", "platform_commit", "engine_version",
                          "portfolio", "variants", "instrument", "session_date"}
    assert bruto["format_version"] == 1


def test_versao_errada_e_recusada(tmp_path):
    destino = tmp_path / "p.json"
    pm.gravar(_pacote(), destino)
    bruto = json.loads(destino.read_text(encoding="utf-8"))
    bruto["format_version"] = 2
    destino.write_text(json.dumps(bruto), encoding="utf-8")
    with pytest.raises(pm.PacoteInvalido, match="format_version"):
        pm.ler(destino)


def test_escrita_atomica_nao_deixa_arquivo_pela_metade(tmp_path, monkeypatch):
    destino = tmp_path / "p.json"
    pm.gravar(_pacote(), destino)
    antes = destino.read_bytes()

    def quebra(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(pm.os, "replace", quebra)
    with pytest.raises(OSError):
        pm.gravar(_pacote(), destino)
    assert destino.read_bytes() == antes
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


def test_nao_deixa_temporario_no_sucesso(tmp_path):
    pm.gravar(_pacote(), tmp_path / "p.json")
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


def test_replace_tenta_de_novo_quando_o_leitor_segura_o_arquivo(tmp_path, monkeypatch):
    destino = tmp_path / "p.json"
    real = pm.os.replace
    chamadas = []

    def instavel(origem, alvo):
        chamadas.append(1)
        if len(chamadas) <= 2:
            raise PermissionError("em uso")
        real(origem, alvo)

    monkeypatch.setattr(pm.os, "replace", instavel)
    monkeypatch.setattr(pm.time, "sleep", lambda _s: None)
    pm.gravar(_pacote(), destino)
    assert len(chamadas) == 3 and pm.ler(destino) == _pacote()


def test_replace_desiste_depois_de_5_tentativas(tmp_path, monkeypatch):
    def preso(*_a):
        raise PermissionError("em uso")

    monkeypatch.setattr(pm.os, "replace", preso)
    monkeypatch.setattr(pm.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        pm.gravar(_pacote(), tmp_path / "p.json")
    assert list(tmp_path.iterdir()) == []
