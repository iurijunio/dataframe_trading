"""Testes do plano de operação — o registro que a incubação vai ler.

Um plano é decisão gravada, não resultado recalculável: ele carrega RETRATOS
dos parâmetros, do perfil de execução e do capital. Mineração apagada não
pode mudar o tamanho de posição de quem já está operando.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import optimizer, plano, wfa_store  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _wfa_no_banco(run_id=1, wfa_id=1, strategy="rompimento_canal"):
    """Um walk-forward mínimo direto no banco: aqui o que se testa é a
    cascata, não o conteúdo do WFA."""
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, "WIN$N", strategy])


def _campos(**extra):
    base = dict(
        wfa_id=1, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={"periodo_canal": 78}, profile={"contratos": 1},
        capital=100_000.0, contratos=3, risco_pedido_pct=1.0,
        risco_efetivo_pct=0.9, perda_referencia=300.0,
        de_onde="a média dos 5% piores pregões", margem=None,
        uso_margem_pct=50.0, camada4_travada=True,
        disjuntor={"nivel2": {"queda": 3000.0}},
        expectativa={"p50_6m": 5000.0},
        reotimizacao={"is_meses": 18, "camada4_travada": True},
        definicoes={"novo_topo": "fechamento do pregão"},
        regua={"holdout": "R$ 942"})
    base.update(extra)
    return base


def test_salvar_e_ler_devolve_os_retratos(banco):
    """Parâmetros, perfil e capital são cópias dentro do plano: é o que
    permite apagar a mineração sem mudar o que está operando."""
    _wfa_no_banco()
    pid = plano.salvar(**_campos())
    d = plano.detalhes(pid)
    assert d["params"] == {"periodo_canal": 78}
    assert d["profile"] == {"contratos": 1}
    assert d["contratos"] == 3 and d["capital"] == 100_000.0
    assert d["estado"] == "ativo" and d["camada4_travada"] is True
    assert d["disjuntor"]["nivel2"]["queda"] == 3000.0
    assert d["created_at"] is not None


def test_dois_planos_do_mesmo_walk_forward_convivem(banco):
    """Risco diferente é decisão diferente, não correção da anterior: as
    duas são histórico, e gravar por cima apagaria a primeira."""
    _wfa_no_banco()
    a = plano.salvar(**_campos(contratos=3, risco_pedido_pct=1.0))
    b = plano.salvar(**_campos(contratos=1, risco_pedido_pct=0.5))
    assert a != b
    assert {p["plano_id"] for p in plano.listar(wfa_id=1)} == {a, b}


def test_listar_traz_o_mais_novo_primeiro(banco):
    _wfa_no_banco()
    a = plano.salvar(**_campos())
    b = plano.salvar(**_campos())
    assert [p["plano_id"] for p in plano.listar()] == [b, a]


def test_excluir_walk_forward_leva_os_planos_junto(banco):
    """Sem a cascata, o plano fica apontando para um walk-forward que não
    existe mais — e a tela mostraria plano sem origem."""
    _wfa_no_banco()
    pid = plano.salvar(**_campos())
    wfa_store.excluir(1)
    assert plano.detalhes(pid) is None


def test_excluir_mineracao_leva_os_planos_dos_walk_forwards_dela(banco):
    """A regra do usuário: apagar mineração apaga tudo que nasceu dela."""
    _wfa_no_banco(run_id=7, wfa_id=3)
    pid = plano.salvar(**_campos(wfa_id=3, run_id=7))
    optimizer.excluir_salva(7)
    assert plano.detalhes(pid) is None and plano.listar() == []


def test_excluir_mineracao_nao_leva_plano_de_outra(banco):
    """A cascata precisa acertar o alvo: apagar demais é pior que não
    apagar."""
    _wfa_no_banco(run_id=7, wfa_id=3)
    _wfa_no_banco(run_id=8, wfa_id=4)
    fica = plano.salvar(**_campos(wfa_id=4, run_id=8))
    plano.salvar(**_campos(wfa_id=3, run_id=7))
    optimizer.excluir_salva(7)
    assert [p["plano_id"] for p in plano.listar()] == [fica]


def test_aposentar_nao_apaga(banco):
    """Plano não se edita: aposenta-se e grava-se outro. Histórico de
    decisão reescrito não é histórico."""
    _wfa_no_banco()
    pid = plano.salvar(**_campos())
    assert plano.aposentar(pid) is True
    assert plano.detalhes(pid)["estado"] == "aposentado"
    assert plano.listar(apenas_ativos=True) == []
    assert len(plano.listar()) == 1


def test_excluir_plano_apaga_so_ele(banco):
    _wfa_no_banco()
    a = plano.salvar(**_campos())
    b = plano.salvar(**_campos())
    assert plano.excluir(a) is True
    assert [p["plano_id"] for p in plano.listar()] == [b]


def test_regravar_o_walk_forward_aposenta_o_plano_e_nao_o_perde(banco):
    """Regravar o MESMO walk-forward apaga o registro antigo e cria outro id.
    Sem tratar o plano, ele ficava apontando para um id que não existe mais:
    invisível nas duas telas, achável só por consulta à mão. Agora ele muda
    de dono e fica aposentado — decisão gravada não se apaga."""
    import numpy as np

    from core import wfa

    def passos():
        j = wfa.Janela(1, np.datetime64("2021-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-09-01", "s"), False)
        return [wfa.Passo(janela=j, escolhida=0, params={"a": 10},
                          is_={"lucro": 900.0, "trades": 200, "dd": 80.0},
                          oos={"lucro": 300.0, "trades": 60}, wfe_lucro=0.66)]

    def grava_wfa():
        return wfa_store.salvar(
            run_id=1, symbol="WIN$N", strategy="rompimento_canal",
            nome="x", is_meses=18, oos_meses=6, inteligencia="ulcer",
            holdout=False, agregado={"steps": 1}, veredito={"estado": "boa"},
            passos=passos(), capital=10_000.0)

    primeiro = grava_wfa()
    pid = plano.salvar(**_campos(wfa_id=primeiro))
    segundo = grava_wfa()          # mesma configuração: SUBSTITUI o anterior

    d = plano.detalhes(pid)
    assert d is not None and d["estado"] == "aposentado"
    assert d["wfa_id"] == segundo
    assert [p["plano_id"] for p in plano.listar(wfa_id=segundo)] == [pid]


def test_camada4_nao_informada_nao_vira_destravada(banco):
    """Afirmar 'não estava travada' sobre uma decisão que ninguém registrou é
    pior que deixar em branco: ela muda o que o plano promete."""
    _wfa_no_banco()
    pid = plano.salvar(**_campos(camada4_travada=None))
    assert plano.detalhes(pid)["camada4_travada"] is None


def test_todos_os_campos_de_retrato_voltam_como_dicionario(banco):
    """Se um deles sair da lista de JSON, ele volta como texto e a tela
    mostra um dicionário escrito à mão."""
    _wfa_no_banco()
    d = plano.detalhes(plano.salvar(**_campos()))
    for campo in ("params", "profile", "disjuntor", "expectativa",
                  "reotimizacao", "definicoes", "regua"):
        assert isinstance(d[campo], dict), campo
    assert d["expectativa"]["p50_6m"] == 5000.0
    assert d["reotimizacao"]["is_meses"] == 18
    assert d["definicoes"]["novo_topo"] == "fechamento do pregão"
    assert d["regua"]["holdout"] == "R$ 942"


def test_reprodutibilidade_fica_gravada(banco):
    """Os retratos protegem contra a mineração sumir; estes campos protegem
    contra o MOTOR mudar. Sem eles, um plano de seis meses atrás não tem como
    explicar por que o mesmo backtest dá outro número hoje."""
    from core import engine

    _wfa_no_banco()
    pid = plano.salvar(**_campos(
        **plano.retrato_da_base("WIN$N"), capital_livre=70_000.0,
        reotimizar_em="2026-03-31"))
    d = plano.detalhes(pid)
    assert d["motor_versao"] == engine.VERSAO
    assert d["capital_livre"] == 70_000.0
    assert str(d["reotimizar_em"]) == "2026-03-31"


def test_detalhes_de_plano_que_nao_existe_devolve_nada(banco):
    assert plano.detalhes(999) is None
    assert plano.aposentar(999) is False
    assert plano.excluir(999) is False
