"""A captura liga a conferência ordens × papel ao mecanismo de chamados.

Só a cola: a regra está em `tests/test_conferencia_ordens.py`. Aqui o
Servico recebe à mão os desejados, o retrato e o resultado do papel — sem
MT5 e sem banco — e o chamado `divergencia_papel` tem de abrir no motor
(selo, alarme e diário), fechar quando volta a bater e nunca comparar
minutos diferentes."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import captura as P  # noqa: E402
from core import conferencia_ordens as CO  # noqa: E402
from core import diario_ordens  # noqa: E402
from core.diario_ordens import Diario  # noqa: E402
from core.papel_vivo import POSICAO, Desejado, LigacaoViva, Retrato  # noqa: E402

DIA = date(2026, 11, 5)


def _as(hh, mm, ss=0):
    return datetime(2026, 11, 5, hh, mm, ss)


@pytest.fixture
def s(tmp_path):
    s = P.Servico(mt5=object(), pasta=tmp_path / "ao_vivo",
                  terminal_aberto=lambda: True)
    lv = LigacaoViva(ligacao_id=5, portfolio_id=1, status="rodando", motivo=None,
                     plano=None, modulo=None, fase="real", ligada=True)
    s.retrato = Retrato(dia=DIA, lido_em=_as(10, 0), ligacoes={5: lv},
                        contas={}, portfolio_de={5: 1})
    # o caso de 05/11: as ordens compradas desde 10:15
    s._desejados_ordens = {5: Desejado(POSICAO, lado=1, entry_ts=_as(10, 15))}
    return s


def _papel(lado, ts):
    return [{"ligacao_id": 5, "status": "rodando", "operacoes": [
        {"entry_ts": ts, "side": lado, "aberta": True, "conta": True}]}]


def _minuto(s, mm, res):
    """Uma volta do papel no minuto 10:mm com os desejados do mesmo minuto."""
    momento = (DIA, _as(10, mm), _as(10, mm - 1))
    s._desejados_momento = momento
    s._conferir_ordens_papel(res, momento, _as(10, mm, 2))


def _divergencias(s):
    return {k: c for k, c in s.motor.chamados.items() if c["tipo"] == CO.TIPO}


def test_caso_de_05_11_abre_chamado_depois_de_persistir(s):
    vendido = _papel(-1, _as(9, 45))
    _minuto(s, 16, vendido)
    _minuto(s, 17, vendido)
    assert _divergencias(s) == {}
    _minuto(s, 18, vendido)
    [(chave, c)] = _divergencias(s).items()
    assert chave == "divergencia_papel:5:2026-11-05:09:45"
    assert c["ligacao_id"] == 5
    assert c["texto"] == ("ordem ≠ papel: ligação 5 — ordens comprado desde "
                          "10:15, papel vendido desde 09:45")
    # o diário registra o chamado (é dele que a tela e o alarme leem)
    evs = Diario(diario_ordens.PASTA, DIA).eventos
    assert [e["chave"] for e in evs if e["tipo"] == "chamado"] == [chave]


def test_igual_nao_chama(s):
    for mm in (16, 17, 18, 19):
        _minuto(s, mm, _papel(1, _as(10, 15)))
    assert _divergencias(s) == {}


def test_fecha_quando_volta_a_bater(s):
    for mm in (16, 17, 18):
        _minuto(s, mm, _papel(-1, _as(9, 45)))
    assert _divergencias(s)
    _minuto(s, 19, _papel(1, _as(10, 15)))
    assert _divergencias(s) == {}
    evs = Diario(diario_ordens.PASTA, DIA).eventos
    assert [e["tipo"] for e in evs] == ["chamado", "chamado_fechado"]


def test_minutos_diferentes_nao_se_comparam(s):
    # papel com a provisória das 10:16, desejados ainda das 10:15
    for mm in (16, 17, 18, 19):
        s._desejados_momento = (DIA, _as(10, mm - 1), _as(10, mm - 2))
        s._conferir_ordens_papel(_papel(-1, _as(9, 45)),
                                 (DIA, _as(10, mm), _as(10, mm - 1)),
                                 _as(10, mm, 2))
    assert _divergencias(s) == {}


def test_sem_desejados_calculados_nao_compara(s):
    s._desejados_momento = None
    for mm in (16, 17, 18):
        s._conferir_ordens_papel(_papel(-1, _as(9, 45)), None, _as(10, mm, 2))
    assert _divergencias(s) == {}


def test_falha_na_conferencia_nao_derruba_o_papel(s, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("bug")
    monkeypatch.setattr(CO, "comparar", quebra)
    _minuto(s, 16, _papel(-1, _as(9, 45)))     # não levanta


def test_desejados_guardam_o_minuto_das_barras(s):
    import numpy as np
    hoje = {"ts": np.array([np.datetime64(_as(10, 14), "ns"),
                            np.datetime64(_as(10, 15), "ns")])}
    assert P._momento(DIA, _as(10, 16), hoje) == (DIA, _as(10, 16), _as(10, 15))
    assert P._momento(DIA, None, {"ts": np.array([], dtype="datetime64[ns]")}) \
        == (DIA, None, None)


# --------------------------------------------- a volta de verdade (falso MT5)
from tests.test_captura_ordens import (_as as _as_10_09, cena, mundo,  # noqa: E402,F401
                                       mods)
from tests.test_captura_processo import base  # noqa: E402,F401


def test_na_volta_real_desejados_e_papel_se_comparam_e_batem(cena, mundo, monkeypatch):
    """Na captura de verdade (MT5 falso), o minuto de barras dos desejados e
    o do papel gravado coincidem — senão a conferência nunca compararia
    nada e calaria. Com o mesmo cálculo dos dois lados, bate."""
    vistos = []
    real = CO.comparar

    def espia(desejados, ligacoes, res):
        c = real(desejados, ligacoes, res)
        vistos.append(c)
        return c
    monkeypatch.setattr(CO, "comparar", espia)
    cena.ir(_as_10_09(10, 0, 30))
    cena.ir(_as_10_09(10, 1, 1))          # a entrada das 10:01 (provisória)
    cena.ir(_as_10_09(10, 2, 1))
    cena.ir(_as_10_09(10, 3, 1))
    comparados = [c for c in vistos if mundo.lig in c]
    assert comparados, "a captura nunca comparou desejados com o papel"
    assert all(c[mundo.lig] is None for c in comparados)
    assert not [k for k, c in cena.s.motor.chamados.items() if c["tipo"] == CO.TIPO]


def test_ordens_backtest_roda_com_a_papel_backtest_so_fora_do_pregao(
        cena, mundo, monkeypatch):
    from core import ordens_backtest, papel_backtest
    ordem = []
    monkeypatch.setattr(papel_backtest, "pendentes",
                        lambda con, symbol="WIN$N": [(mundo.lig, date(2026, 10, 8))])
    monkeypatch.setattr(papel_backtest, "conferir",
                        lambda con, lig, dia, *a, **k: ordem.append(("papel", lig)) or {})
    feitos = []
    monkeypatch.setattr(ordens_backtest, "pendentes",
                        lambda con, symbol="WIN$N", **k: [p for p in [
                            (mundo.lig, date(2026, 10, 8), "real"),
                            (mundo.lig, date(2026, 10, 8), "demo")] if p not in feitos])

    def conferir(con, lig, dia, origem, cache, agora, symbol="WIN$N"):
        feitos.append((lig, dia, origem))
        ordem.append(("ordens", origem))
        return {}
    monkeypatch.setattr(ordens_backtest, "conferir", conferir)
    cena.s.reexportar = True
    cena.ir(_as_10_09(10, 5))             # no pregão: nada
    assert ordem == []
    cena.ir(_as_10_09(18, 40))
    assert ordem == [("papel", mundo.lig), ("ordens", "real"), ("ordens", "demo")]
