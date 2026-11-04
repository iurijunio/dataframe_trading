"""Detalhe do nicho, Minerar a região e Abrir o campeão no Backtest."""
import numpy as np
import pytest

from core import db_manager as db
from core.busca import banco as B
from core.busca import detalhe as D
from core.busca.espaco import CAMPO_STOP, Combinacao


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")


@pytest.fixture(scope="module")
def busca(tmp_path_factory):
    # o conftest isola por teste; aqui o banco vive o módulo inteiro
    pasta = tmp_path_factory.mktemp("busca_det")
    antes = (B.CAMINHO, B.PASTA)
    B.CAMINHO, B.PASTA = pasta / "b.duckdb", pasta / "buscas"
    try:
        from tests import _busca_pequena

        bid = _busca_pequena.rodar(4)
        yield bid, (B.CAMINHO, B.PASTA)
    finally:
        B.CAMINHO, B.PASTA = antes


@pytest.fixture
def no_banco(busca, monkeypatch):
    bid, (cam, pasta) = busca
    monkeypatch.setattr(B, "CAMINHO", cam)
    monkeypatch.setattr(B, "PASTA", pasta)
    elites = [e for e in B.ler_elites(bid) if e["valida"]]
    assert elites, "a busca pequena não achou elite válida"
    return bid, elites[0]


def test_kpis_sao_os_da_elite(no_banco):
    bid, e = no_banco
    d = D.detalhe(bid, e["casa"])
    assert d["kpis"]["fr"] == e["fr"] and d["kpis"]["trades"] == e["trades"]
    assert d["kpis"]["maior_queda"] == e["dd"] and d["kpis"]["membros"] >= 1
    assert d["moeda"] == "BRL"


def test_fr_mediano_e_a_mediana_dos_membros(no_banco):
    bid, e = no_banco
    membros, g = D._membros(bid, e)
    frs = [m["fr"] for m in membros if m.get("fr") is not None]
    assert D.detalhe(bid, e["casa"])["kpis"]["fr_mediano"] == pytest.approx(np.median(frs))


def test_hora_dia_formato_e_regiao(no_banco):
    bid, e = no_banco
    hd = D.detalhe(bid, e["casa"])["hora_dia"]
    c = Combinacao.de_chave(e["combo"])
    assert hd["dias"] == ["seg", "ter", "qua", "qui", "sex"]
    assert len(hd["valores"]) == len(hd["horas"]) == len(hd["dentro"])
    dentro = [(h, d) for h, linha in zip(hd["horas"], hd["dentro"])
              for d, x in zip(range(1, 6), linha) if x]
    assert dentro and all(c.ini <= h <= c.fim and d in c.dias for h, d in dentro)
    assert all(v is None or isinstance(v, float) for linha in hd["valores"] for v in linha)


def test_por_ano_e_holdout(no_banco):
    bid, e = no_banco
    anos = D.detalhe(bid, e["casa"])["por_ano"]
    assert [a["ano"] for a in anos] == [2024]
    assert all(a["pct_lucro"] is None or 0 <= a["pct_lucro"] <= 100 for a in anos)


def test_curva_fecha_no_lucro_da_elite(no_banco):
    bid, e = no_banco
    cv = D.detalhe(bid, e["casa"])["curva"]
    assert cv["y"][-1] == pytest.approx(e["lucro"], abs=0.01)


def test_regiao_contem_todos_os_membros(no_banco):
    bid, e = no_banco
    r = D.regiao_para_varredura(bid, e["casa"])
    membros, _ = D._membros(bid, e)
    camp = Combinacao.de_chave(e["combo"])
    assert r["timeframe"] == camp.timeframe and r["dias_semana"] == list(camp.dias)
    assert r["entrada_inicio"] <= camp.ini and r["entrada_fim"] >= camp.fim
    for m in membros:
        c = Combinacao.de_chave(m["combo"])
        for n, v in c.params:
            f = r["campos"][n]
            assert (f["de"] <= v <= f["ate"]) if f["on"] else v == f["de"]
    campo = CAMPO_STOP[camp.stop_tipo]
    assert r["campos"][campo]["valor"] == camp.stop_valor


def test_campeao_no_backtest_da_as_metricas_da_elite(no_banco):
    from core import optimizer, walkforward as wf
    from core.engine.execution import ExecutionProfile

    bid, e = no_banco
    cb = D.campeao_para_backtest(bid, e["casa"])
    cfg = B.ler_busca(bid)["config"]
    optimizer._init(cb["simbolo"], cb["de"], cb["ate"], cb["estrategia"])
    janelas = wf.montar_janelas(np.datetime64(cfg["de"], "s"), np.datetime64(cfg["ate"], "s"),
                                **cfg["wf_config"])
    r = optimizer._uma((0, cb["params"], {}, ExecutionProfile(**cb["perfil"]).to_config(),
                        janelas))
    assert r["geral"]["trades"] == e["trades"] and r["geral"]["lucro"] == e["lucro"]


def test_regiao_com_um_membro_ainda_tem_o_que_minerar(no_banco, monkeypatch):
    bid, e = no_banco
    monkeypatch.setattr(D, "_membros", lambda _b, el: ([el], None))
    r = D.regiao_para_varredura(bid, e["casa"])
    camp = Combinacao.de_chave(e["combo"])
    ligados = [n for n, f in r["campos"].items() if f.get("on")]
    assert "di_periodo" in ligados and CAMPO_STOP[camp.stop_tipo] in ligados
    f = r["campos"]["di_periodo"]
    assert f["de"] < dict(camp.params)["di_periodo"] < f["ate"] or \
        dict(camp.params)["di_periodo"] in (f["de"], f["ate"])
    assert (r["entrada_inicio"], r["entrada_fim"]) == (camp.ini, camp.fim)
