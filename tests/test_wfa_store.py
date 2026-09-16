"""Testes do que fica gravado de um walk-forward.

O que se guarda aqui não é performance — o resultado é barato de recalcular.
É o registro da decisão, e os **trades da curva fora da amostra**, que são a
matéria-prima do portfólio: correlação de verdade pede a série, e exposição
simultânea pede saber quando cada posição esteve aberta. Nada disso se
reconstrói a partir de um total por janela.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import wfa  # noqa: E402
from core import wfa_store as st  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def janela(k=1, deploy=False):
    return wfa.Janela(k, np.datetime64("2021-03-01", "s"),
                      np.datetime64("2022-03-01", "s"),
                      np.datetime64("2022-03-01", "s"),
                      np.datetime64("2022-09-01", "s"), deploy)


def passos_falsos():
    return [
        wfa.Passo(janela=janela(1), escolhida=0, params={"a": 10},
                  is_={"lucro": 900.0, "trades": 200, "dd": 80.0},
                  oos={"lucro": 300.0, "trades": 60}, wfe_lucro=0.66),
        wfa.Passo(janela=janela(2, deploy=True), escolhida=1,
                  params={"a": 12}, is_={"lucro": 800.0, "trades": 190}),
    ]


def trade(n, dia, hora, saida_hora, liquido, step=1):
    return {"n": n, "step": step,
            "entry_ts": datetime(2022, 3, dia, hora, 0),
            "exit_ts": datetime(2022, 3, dia, saida_hora, 0),
            "side": 1, "entry_px": 116000, "exit_px": 116100,
            "points": 100, "contratos": 1, "bruto": liquido + 1.0,
            "custo": 1.0, "liquido": liquido, "reason": 1,
            "mae": -20, "mfe": 140, "bars_held": 30}


AGREGADO = {"steps": 1, "oos_lucro": 300.0, "oos_trades": 60,
            "wfe_global": 0.66, "consistencia_lucro": 100.0, "dd_oos": 40.0}
VEREDITO = {"estado": "aprovado"}


def _salvar(**extra):
    base = dict(run_id=40, symbol="WIN$N", strategy="rompimento_canal",
                nome="teste", is_meses=12, oos_meses=6,
                inteligencia="centroide_mediana", holdout=False,
                agregado=AGREGADO, veredito=VEREDITO, passos=passos_falsos())
    base.update(extra)
    return st.salvar(**base)


# ------------------------------------------------------------- o registro
def test_salvar_grava_e_lista(banco):
    wid = _salvar()
    lista = st.listar("rompimento_canal")

    assert len(lista) == 1
    assert lista[0]["wfa_id"] == wid
    assert lista[0]["veredito"] == "aprovado"
    assert "IS12/OOS6" in lista[0]["rotulo"]
    assert "WFE 66%" in lista[0]["rotulo"]


def test_o_deploy_fica_gravado_com_os_parametros(banco):
    """O DEPLOY é a combinação que se colocaria para operar hoje. De nada
    serve o registro da decisão sem ela."""
    d = st.detalhes(_salvar())
    assert d["deploy"]["step"] == "DEPLOY"
    assert d["deploy"]["params"] == {"a": 12}
    assert len(d["passos"]) == 2


def test_rodar_o_mesmo_de_novo_substitui(banco):
    """Mesma mineração, mesma janela, mesma inteligência: o resultado é
    idêntico, e dois registros iguais só fariam a lista crescer sem
    informar nada."""
    st.salvar(run_id=40, symbol="WIN$N", strategy="rompimento_canal",
              nome="a", is_meses=12, oos_meses=6,
              inteligencia="centroide_mediana", holdout=False,
              agregado=AGREGADO, veredito=VEREDITO, passos=passos_falsos(),
              trades=[trade(1, 2, 10, 11, 50.0)])
    segundo = st.salvar(run_id=40, symbol="WIN$N", strategy="rompimento_canal",
                        nome="b", is_meses=12, oos_meses=6,
                        inteligencia="centroide_mediana", holdout=False,
                        agregado=AGREGADO, veredito=VEREDITO,
                        passos=passos_falsos(),
                        trades=[trade(1, 3, 10, 11, 70.0)])

    lista = st.listar("rompimento_canal")
    assert len(lista) == 1 and lista[0]["wfa_id"] == segundo
    # e os trades do registro velho foram junto: sem isso a tabela ficaria
    # com órfãos que ninguém mais consegue atribuir
    assert [t["liquido"] for t in st.trades(segundo)] == [70.0]


def test_configuracao_diferente_e_outro_registro(banco):
    a = _salvar(is_meses=12, oos_meses=6)
    b = _salvar(is_meses=24, oos_meses=6)
    assert a != b and len(st.listar("rompimento_canal")) == 2


def test_lista_filtra_por_estrategia(banco):
    _salvar(strategy="rompimento_canal")
    _salvar(strategy="setup_cruzamento")
    assert len(st.listar("rompimento_canal")) == 1
    assert len(st.listar()) == 2


# ---------------------------------------------- matéria-prima do portfólio
def test_trades_voltam_inteiros_e_em_ordem(banco):
    """Sem entrada, saída, lado e contratos não há análise de portfólio —
    só um total mensal, que não responde nada sobre exposição."""
    wid = _salvar(trades=[trade(1, 2, 10, 11, 50.0),
                          trade(2, 3, 14, 15, -30.0, step=2)])
    lidos = st.trades(wid)

    assert [t["n"] for t in lidos] == [1, 2]
    assert lidos[0]["entry_ts"] == datetime(2022, 3, 2, 10, 0)
    assert lidos[0]["exit_ts"] == datetime(2022, 3, 2, 11, 0)
    assert lidos[1]["step"] == 2 and lidos[1]["liquido"] == -30.0
    # todo o detalhe que o portfólio pode querer
    for chave in ("side", "entry_px", "exit_px", "points", "contratos",
                  "bruto", "custo", "reason", "mae", "mfe", "bars_held"):
        assert chave in lidos[0]


def test_serie_diaria_agrupa_pela_saida(banco):
    """O trade entra no dia em que o resultado se REALIZA. Dois trades que
    saem no mesmo pregão são um ponto só da série — e é sobre essa série que
    a correlação entre estratégias se calcula."""
    wid = _salvar(trades=[trade(1, 2, 10, 11, 50.0),
                          trade(2, 2, 14, 15, -20.0),
                          trade(3, 4, 10, 11, 80.0)])
    s = st.serie_diaria(wid)

    assert s["dias"] == ["2022-03-02", "2022-03-04"]
    assert s["pnl"] == [pytest.approx(30.0), pytest.approx(80.0)]
    assert s["trades"] == [2, 1]


def test_serie_diaria_soma_o_mesmo_que_a_curva(banco):
    ts = [trade(i, 2 + i, 10, 11, v)
          for i, v in enumerate([100.0, -40.0, 25.0, -15.0], start=1)]
    wid = _salvar(trades=ts)
    assert sum(st.serie_diaria(wid)["pnl"]) == pytest.approx(70.0)


def test_exposicao_traz_os_intervalos_de_posicao(banco):
    """Duas estratégias com correlação baixa de resultado podem estar
    posicionadas ao mesmo tempo o dia inteiro — e aí o risco soma mesmo que o
    resultado não se pareça."""
    wid = _salvar(trades=[trade(1, 2, 10, 12, 50.0)])
    exp = st.exposicao(wid)

    assert len(exp) == 1
    entrada, saida, lado, contratos = exp[0]
    assert entrada == datetime(2022, 3, 2, 10, 0)
    assert saida == datetime(2022, 3, 2, 12, 0)
    assert lado == 1 and contratos == 1


def test_excluir_leva_os_trades_junto(banco):
    wid = _salvar(trades=[trade(1, 2, 10, 11, 50.0)])
    assert st.trades(wid)

    st.excluir(wid)
    assert st.listar("rompimento_canal") == []
    assert st.trades(wid) == []


def test_walk_forward_sem_trades_ainda_grava_o_registro(banco):
    """Gravar o registro não depende de reconstruir os trades: se a
    reconstrução falhar, é melhor ter a decisão anotada do que nada."""
    wid = _salvar(trades=None)
    assert st.detalhes(wid) is not None
    assert st.trades(wid) == []
