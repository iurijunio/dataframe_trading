"""Avaliador da busca: a nota de cada combinação = a da Varredura."""
import math

import numpy as np
import pytest

from core import db_manager as db
from core import optimizer, walkforward as wf
from core.busca import avaliador as A
from core.busca.espaco import Espaco
from core.engine.execution import ExecutionProfile

PERIODO = ("2024-01-01", "2024-12-31")


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")


@pytest.fixture(scope="module")
def ctx():
    A.iniciar_nucleo("WIN$N", *PERIODO, "adx_direcao")
    esp = Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                 faixas={"timeframe": {"ligados": ["M5", "M15"]},
                         "di_periodo": {"de": 10, "ate": 20},
                         "adx_suavizacao": {"de": 10, "ate": 14},
                         "amplitude_max": {"de": 500, "ate": 1000, "passo": 500}})
    return {"espaco": esp.para_json(), "esp": esp,
            "perfil_base": ExecutionProfile(corretagem_por_contrato=0.5,
                                            min_operacoes=20).to_config(),
            "janelas": wf.montar_janelas(*PERIODO, 4, 2, 2, 2),
            "minimo": 60, "criterio": "fr"}


def _amostra(ctx, n, semente):
    esp = ctx["esp"]
    combos = [esp.decodificar(x) for x in np.random.default_rng(semente).random((n, esp.n_genes))]
    return combos


def _avaliar(ctx, combos):
    out = []
    for i, c in enumerate(combos):
        out += A.avaliar_grupo(c.chave_essencial(), [(i, c.chave())], ctx)
    return out


def _iguais(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_iguais(a[k], b[k]) for k in a)
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or a == b
    return a == b


def test_bate_com_a_varredura(ctx):
    optimizer._init("WIN$N", *PERIODO, "adx_direcao")
    esp = ctx["esp"]
    combos = _amostra(ctx, 25, 11)
    rodadas = 0
    for r, c in zip(_avaliar(ctx, combos), combos):
        if r["descartada"]:
            continue
        rodadas += 1
        perfil = esp.perfil(c, ctx["perfil_base"])
        esperado = optimizer._uma((r["teste_n"], esp.params(c), {}, perfil.to_config(),
                                   ctx["janelas"]))
        assert _iguais(r["aval"], esperado), c
        assert r["trades"] == esperado["geral"]["trades"]
    assert rodadas >= 10


def test_mesmo_sinal_varias_combinacoes_num_grupo(ctx):
    """O grupo (como o motor manda) dá o mesmo que uma a uma."""
    esp = ctx["esp"]
    base = _amostra(ctx, 1, 3)[0]
    xs = np.random.default_rng(4).random((6, esp.n_genes))
    combos = []
    for x in xs:
        c = esp.decodificar(x)
        combos.append(c.__class__(**{**c.__dict__, "timeframe": base.timeframe,
                                     "params": base.params}))
    juntos = A.avaliar_grupo(base.chave_essencial(),
                             [(i, c.chave()) for i, c in enumerate(combos)], ctx)
    separados = _avaliar(ctx, combos)
    for a, b in zip(juntos, separados):
        assert a["objetivo"] == b["objetivo"] and a["trades_hash"] == b["trades_hash"]


def test_descarte_so_quando_impossivel(ctx):
    exigente = {**ctx, "minimo": 150}
    combos = _amostra(ctx, 60, 21)
    descartadas = 0
    for r, c in zip(_avaliar(exigente, combos), combos):
        if r["descartada"] == "poucos sinais":
            descartadas += 1
            real = A.avaliar_grupo(c.chave_essencial(), [(0, c.chave())],
                                   {**ctx, "minimo": 0})[0]
            assert real["trades"] < exigente["minimo"], c
    assert descartadas >= 5


def test_teto_nunca_abaixo_dos_trades(ctx):
    esp = ctx["esp"]
    from core.engine.execution import executar
    for c in _amostra(ctx, 30, 31):
        perfil = esp.perfil(c, ctx["perfil_base"])
        prep = A._preparado(c.chave_essencial())
        res = executar(prep, perfil)
        dentro = int(np.count_nonzero(
            res.trades["entry_ts"] < ctx["janelas"].fim_otimizacao))
        assert A.teto_de_trades(prep, perfil, ctx["janelas"].fim_otimizacao) >= dentro


def test_abaixo_do_minimo_nunca_vale():
    o, valida = A.objetivo({"geral": {"trades": 399, "fator_recuperacao": 9.0},
                            "passa_filtro": True}, "fr", 400)
    assert not valida and o == A.INVALIDA + 399
    o2, _ = A.objetivo({"geral": {"trades": 401, "fator_recuperacao": -50.0},
                        "passa_filtro": True}, "fr", 400)
    assert o2 > o


def test_reprovada_no_filtro_da_varredura_nao_vale():
    _, valida = A.objetivo({"geral": {"trades": 900, "fator_recuperacao": 3.0},
                            "passa_filtro": False}, "fr", 400)
    assert not valida


def test_sem_perda_nao_vira_infinito():
    o, valida = A.objetivo({"geral": {"trades": 500, "fator_recuperacao": float("inf")},
                            "passa_filtro": True}, "fr", 400)
    assert valida and o == A.TETO_OBJETIVO


def test_menor_drawdown_inverte():
    def g(dd):
        return {"geral": {"trades": 500, "max_dd": dd}, "passa_filtro": True}
    assert A.objetivo(g(100.0), "dd", 1)[0] > A.objetivo(g(200.0), "dd", 1)[0]


def test_metas_do_prototipo():
    assert set(A.METAS) == {"fr", "pf", "lucro", "dd"}


def test_lru_de_preparados(ctx):
    for c in _amostra(ctx, 30, 41):
        A._preparado(c.chave_essencial())
    assert len(A._PREPS) <= A.N_PREPARADOS


def _prep_falso(longs, shorts):
    """Barras de uma terça às 10:00, com sinais nos minutos pedidos."""
    from types import SimpleNamespace

    ts = np.datetime64("2024-03-05T10:00") + np.arange(20).astype("timedelta64[m]")
    el = np.zeros(20, bool)
    es = np.zeros(20, bool)
    el[longs] = True
    es[shorts] = True
    return SimpleNamespace(bars={"ts": ts.astype("datetime64[ns]")}, cache={}, ficha=None,
                           sinais=SimpleNamespace(entry_long=el, entry_short=es))


def test_teto_conta_so_antes_do_fim_da_otimizacao():
    prep = _prep_falso([1, 3, 5, 11, 12, 13, 14, 15], [])
    perfil = ExecutionProfile(entrada_inicio="10:00", entrada_fim="10:30")
    assert A.teto_de_trades(prep, perfil, np.datetime64("2024-03-05T10:10")) == 3


def test_teto_respeita_a_direcao():
    prep = _prep_falso([1, 2, 3, 4], [6, 7])
    fim = np.datetime64("2024-03-06")
    def t(d):
        return A.teto_de_trades(prep, ExecutionProfile(entrada_inicio="10:00",
                                                       entrada_fim="10:30", direcao=d), fim)
    assert (t("compra"), t("venda"), t("ambas")) == (4, 2, 6)


def test_teto_respeita_janela_e_dia():
    prep = _prep_falso([1, 2, 8, 9], [])
    fim = np.datetime64("2024-03-06")
    assert A.teto_de_trades(prep, ExecutionProfile(entrada_inicio="10:05",
                                                   entrada_fim="10:30"), fim) == 2
    assert A.teto_de_trades(prep, ExecutionProfile(dias_semana=(3,)), fim) == 0
