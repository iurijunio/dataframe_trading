# tests/test_ao_vivo_rastreio.py
"""A ficha: de onde veio o plano que a variante opera, e o que já mudou."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import codigo, db_manager as db, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = date(2026, 10, 1)


def _cadeia_completa():
    v = variantes.criar("romp", "rompimento_canal")
    mineracao(47, variante_id=v)
    with db.connect_write() as con:
        con.execute("UPDATE mining_runs SET nome = 'mina', space = ? "
                    "WHERE run_id = 47", ['{"periodo_canal": [40, 80, 5]}'])
    wfa(13, 47)
    with db.connect_write() as con:
        con.execute("UPDATE wfa_runs SET nome = 'wfa', is_meses = 18, "
                    "oos_meses = 6, inteligencia = 'ulcer', oos_lucro = 942.5, "
                    "oos_trades = 120, dd_oos = 300.0, veredito = 'boa' "
                    "WHERE wfa_id = 13")
    h = codigo.hash_estrategia("rompimento_canal")
    pid = plano.salvar(**campos_plano(
        wfa_id=13, run_id=47, codigo_hash=h,
        regua={"veredito": "aprovada", "portoes": [
            {"nome": "Platô", "ok": True, "critico": True}]}),
        agora=datetime(2026, 9, 1, 10))
    pf = P.criar("pf")
    lig = P.adicionar_variante(pf, v)
    return v, pid, lig


def test_ficha_completa(banco):
    v, pid, lig = _cadeia_completa()
    r = AV.rastreio(lig, QUI)
    assert r["alcance"] == "plano"
    assert r["plano"]["plano_id"] == pid
    assert r["plano"]["params"] == {"periodo_canal": 78}
    assert r["mineracao"]["run_id"] == 47 and r["mineracao"]["nome"] == "mina"
    assert r["mineracao"]["espaco"] == {"periodo_canal": [40, 80, 5]}
    assert r["wfa"]["wfa_id"] == 13 and r["wfa"]["oos_lucro"] == 942.5
    assert r["wfa"]["veredito"] == "boa"
    assert r["candidata"]["veredito"] == "aprovada"
    assert r["codigo"]["confere"] is True
    assert [p["plano_id"] for p in r["planos"]] == [pid]
    tipos = {e["tipo"] for e in r["eventos"]}
    assert {"membro_adicionado", "plano_gravado"} <= tipos


def test_mineracao_apagada_usa_os_retratos(banco):
    """Com a variante fora de portfólio a proteção libera apagar; a ficha
    de outra ligação da MESMA variante, criada depois, ainda precisa ler o
    plano pelo variante_id do próprio plano."""
    v, pid, lig = _cadeia_completa()
    with db.connect_write() as con:
        con.execute("DELETE FROM mining_runs WHERE run_id = 47")
    r = AV.rastreio(lig, QUI)
    assert r["mineracao"] is None
    assert r["plano"]["plano_id"] == pid and r["alcance"] == "plano"


def test_codigo_divergente(banco):
    v, pid, lig = _cadeia_completa()
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET codigo_hash = 'velho'")
    assert AV.rastreio(lig, QUI)["codigo"]["confere"] is False


def test_sem_plano_mostra_ate_onde_chegou(banco):
    v = variantes.criar("nova", "rompimento_canal")
    mineracao(9, variante_id=v)
    pf = P.criar("pf")
    lig = P.adicionar_variante(pf, v)
    r = AV.rastreio(lig, QUI)
    assert r["alcance"] == "mineração" and r["plano"] is None
    assert r["mineracao"]["run_id"] == 9 and r["wfa"] is None
    assert r["codigo"]["confere"] is None
    wfa(9, 9)
    assert AV.rastreio(lig, QUI)["alcance"] == "walk-forward"


def test_nada_ainda(banco):
    v = variantes.criar("vazia", "rompimento_canal")
    lig = P.adicionar_variante(P.criar("pf"), v)
    r = AV.rastreio(lig, QUI)
    assert r["alcance"] == "nada" and r["mineracao"] is None


def test_lista_todos_os_planos(banco):
    v, p1, lig = _cadeia_completa()
    p2 = plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                      agora=datetime(2026, 9, 10, 10))
    r = AV.rastreio(lig, QUI)
    assert [p["plano_id"] for p in r["planos"]] == [p2, p1]
    assert r["planos"][1]["estado"] == "aposentado"


def test_ligacao_inexistente(banco):
    with pytest.raises(ValueError):
        AV.rastreio(999, QUI)


def test_sem_plano_em_vigor_mostra_o_mais_novo(banco):
    """Antes de qualquer plano valer, a ficha mostra o mais recente."""
    v, p1, lig = _cadeia_completa()
    p2 = plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                      agora=datetime(2026, 9, 10, 10))
    r = AV.rastreio(lig, date(2026, 8, 1))
    assert r["ligacao"]["plano"] is None
    assert r["plano"]["plano_id"] == p2
