"""Conferência no mesmo dia: desejados das ordens × papel gravado.

Em 05/11/2026 a automação calculou os desejados com um aquecimento velho e
comprou às 10:15 na conta real, enquanto o papel gravado (o da tela, igual
ao backtest) dizia VENDA desde 09:45 — e nada avisou. A regra pura
(`core/conferencia_ordens.py`) compara os dois por ligação; a `Vigia` só
transforma divergência em chamado quando ela persiste."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import conferencia_ordens as CO  # noqa: E402
from core.papel_vivo import (INDISPONIVEL, POSICAO, ZERADO, Desejado,  # noqa: E402
                             LigacaoViva)

DIA = date(2026, 11, 5)


def _as(hh, mm, ss=0):
    return datetime(2026, 11, 5, hh, mm, ss)


def _lig(lig=5, fase="real", ligada=True):
    return LigacaoViva(ligacao_id=lig, portfolio_id=1, status="rodando",
                       motivo=None, plano=None, modulo=None, fase=fase,
                       ligada=ligada)


def _op(entry_ts, side, aberta=True, conta=True):
    return {"entry_ts": entry_ts, "side": side, "aberta": aberta, "conta": conta}


def _res(lig=5, ops=(), status="rodando"):
    return {"ligacao_id": lig, "status": status,
            "operacoes": None if ops is None else list(ops)}


def _comprado(ts=_as(10, 15)):
    return Desejado(POSICAO, lado=1, entry_ts=ts)


# ----------------------------------------------------------- comparar
def test_caso_de_05_11_diverge():
    c = CO.comparar({5: _comprado()}, {5: _lig()},
                    [_res(ops=[_op(_as(9, 45), -1)])])
    d = c[5]
    assert isinstance(d, CO.Divergencia)
    assert d.ordem == (1, _as(10, 15)) and d.papel == (-1, _as(9, 45))
    assert d.texto() == ("ordem ≠ papel: ligação 5 — ordens comprado desde "
                         "10:15, papel vendido desde 09:45")


def test_igual_bate():
    c = CO.comparar({5: _comprado()}, {5: _lig()},
                    [_res(ops=[_op(_as(9, 30), 1, aberta=False),
                               _op(_as(10, 15), 1)])])
    assert c == {5: None}


def test_mesmo_lado_outra_entrada_diverge():
    c = CO.comparar({5: _comprado(_as(10, 15))}, {5: _lig()},
                    [_res(ops=[_op(_as(10, 0), 1)])])
    assert isinstance(c[5], CO.Divergencia)


def test_posicao_sem_aberta_no_papel_diverge():
    c = CO.comparar({5: _comprado()}, {5: _lig()},
                    [_res(ops=[_op(_as(10, 15), 1, aberta=False)])])
    assert c[5].papel is None
    assert "papel zerado" in c[5].texto()


def test_zerado_com_aberta_no_papel_diverge():
    c = CO.comparar({5: Desejado(ZERADO)}, {5: _lig()},
                    [_res(ops=[_op(_as(9, 45), -1)])])
    assert c[5].ordem is None and c[5].papel == (-1, _as(9, 45))
    assert "ordens zerado" in c[5].texto()


def test_zerado_e_papel_zerado_bate():
    c = CO.comparar({5: Desejado(ZERADO)}, {5: _lig()}, [_res(ops=[])])
    assert c == {5: None}


def test_aberta_que_nao_conta_fica_fora():
    # entrou com a ligação desligada: no papel não conta, nas ordens não entra
    c = CO.comparar({5: Desejado(ZERADO)}, {5: _lig()},
                    [_res(ops=[_op(_as(9, 45), -1, conta=False)])])
    assert c == {5: None}


def test_indisponivel_e_incomparavel():
    c = CO.comparar({5: Desejado(INDISPONIVEL, motivo="aquecimento insuficiente")},
                    {5: _lig()}, [_res(ops=[_op(_as(9, 45), -1)])])
    assert c == {5: CO.INCOMPARAVEL}


@pytest.mark.parametrize("lv", [_lig(fase="papel"), _lig(ligada=False)])
def test_fase_papel_ou_desligada_fica_fora(lv):
    c = CO.comparar({5: Desejado(ZERADO, motivo="x")}, {5: lv},
                    [_res(ops=[_op(_as(9, 45), -1)])])
    assert c == {}


def test_papel_sem_calculo_e_incomparavel():
    # falha no cálculo / pregão pulado: `operacoes = None`, nada a comparar
    assert CO.comparar({5: _comprado()}, {5: _lig()},
                       [_res(ops=None)]) == {5: CO.INCOMPARAVEL}
    # ligação sem resultado do papel nesta volta (pregão congelado)
    assert CO.comparar({5: _comprado()}, {5: _lig()}, []) == {5: CO.INCOMPARAVEL}


# -------------------------------------------------------------- vigia
DIV = CO.Divergencia(5, ordem=(1, _as(10, 15)), papel=(-1, _as(9, 45)))


def _minuto(mm):
    return _as(10, mm)


def test_divergencia_persistente_abre_chamado():
    v = CO.Vigia()
    assert v.observar(DIA, _minuto(15), {5: DIV}) == {}
    assert v.observar(DIA, _minuto(16), {5: DIV}) == {}
    abertos = v.observar(DIA, _minuto(17), {5: DIV})
    [(chave, (lig, texto))] = abertos.items()
    assert lig == 5 and texto == DIV.texto()
    assert chave == "divergencia_papel:5:2026-11-05:09:45"
    # segue aberto (a mesma chave) enquanto diverge
    assert v.observar(DIA, _minuto(18), {5: DIV}) == abertos


def test_muitas_comparacoes_no_mesmo_minuto_nao_bastam():
    # toque de stop/alvo: o papel regrava várias vezes no mesmo minuto
    v = CO.Vigia()
    for s in range(10):
        assert v.observar(DIA, _minuto(15), {5: DIV}) == {}
    assert v.observar(DIA, _minuto(16), {5: DIV}) == {}


def test_divergencia_de_uma_volta_nao_chama():
    v = CO.Vigia()
    assert v.observar(DIA, _minuto(15), {5: DIV}) == {}
    assert v.observar(DIA, _minuto(16), {5: None}) == {}
    assert v.observar(DIA, _minuto(17), {5: DIV}) == {}
    assert v.observar(DIA, _minuto(18), {5: DIV}) == {}


def test_fecha_quando_volta_a_bater():
    v = CO.Vigia()
    for mm in (15, 16, 17):
        abertos = v.observar(DIA, _minuto(mm), {5: DIV})
    assert abertos
    assert v.observar(DIA, _minuto(18), {5: None}) == {}


def test_incomparavel_nao_conta_nem_zera():
    v = CO.Vigia()
    v.observar(DIA, _minuto(15), {5: DIV})
    v.observar(DIA, _minuto(16), {5: CO.INCOMPARAVEL})
    v.observar(DIA, _minuto(17), {5: DIV})
    assert v.observar(DIA, _minuto(18), {5: DIV})
    # aberto, incomparável mantém o chamado
    assert v.observar(DIA, _minuto(19), {5: CO.INCOMPARAVEL})


def test_ligacao_fora_de_escopo_fecha():
    v = CO.Vigia()
    for mm in (15, 16, 17):
        v.observar(DIA, _minuto(mm), {5: DIV})
    assert v.observar(DIA, _minuto(18), {}) == {}


def test_virada_do_dia_recomeca():
    v = CO.Vigia()
    v.observar(DIA, _minuto(15), {5: DIV})
    v.observar(DIA, _minuto(16), {5: DIV})
    outro = DIA + timedelta(days=1)
    assert v.observar(outro, datetime(2026, 11, 6, 10, 17), {5: DIV}) == {}


def test_chave_usa_a_entrada_do_desejado_sem_aberta_no_papel():
    d = CO.Divergencia(5, ordem=(1, _as(10, 15)), papel=None)
    assert d.chave(DIA) == "divergencia_papel:5:2026-11-05:10:15"
