"""Exportar o pacote de um portfólio: só variante ligada, um ativo, banco só em leitura."""

from __future__ import annotations

import json
import sys
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import exportar_pacote as ex  # noqa: E402
from core import plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from core.contratos import pacote_mesa as pm  # noqa: E402

HOJE = date(2026, 11, 11)
DISJUNTOR = {"nivel1": {"queda": 450.5, "perdas_seguidas": 4, "lucro_no_prazo": None,
                        "faixa_por_pregao": [1.0, 2.0], "alarme_pct": 20.0, "acao": "reduzir"},
             "nivel2": {"queda": 900.0, "pct": 3.0, "alarme_pct": 5.0},
             "limite_dia_reais": 300.0, "limite_dia_trades": None, "horizonte": "12 meses"}


def _git_simulado(sujo: str = ""):
    """Git de mentira: `status` devolve `sujo`; `rev-parse` devolve um commit fixo."""
    def rodar(args):
        texto = sujo if args[0] == "status" else "abc123\n"
        return subprocess.CompletedProcess(args, 0, stdout=texto, stderr="")
    return rodar


@pytest.fixture(autouse=True)
def git_limpo(monkeypatch):
    monkeypatch.setattr(ex, "rodar_git", _git_simulado())


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _variante_com_plano(n, symbol="WIN$N", nome=None):
    """Variante `n` com mineração, walk-forward e plano em vigor hoje."""
    vid = variantes.criar(nome or f"v{n}", "rompimento_canal")
    with db.connect_write() as con:
        con.execute("INSERT INTO mining_runs (run_id, symbol, strategy, created_at, n_combinacoes, "
                    "status, variante_id) VALUES (?,?,?,?,?,?,?)",
                    [n, symbol, "rompimento_canal", "2026-01-01", 10, "concluida", vid])
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) VALUES (?,?,?,?)",
                    [n, n, symbol, "rompimento_canal"])
    pid = plano.salvar(
        wfa_id=n, run_id=n, symbol=symbol, strategy="rompimento_canal", nome="p",
        params={"periodo": 20, "stop_pontos": 100}, profile={"timeframe": "M15", "fechamento": "17:30"},
        capital=100_000.0, contratos=2, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="t", margem=None, uso_margem_pct=50.0,
        camada4_travada=True, disjuntor=DISJUNTOR, expectativa={}, reotimizacao={},
        definicoes={}, regua={}, agora=datetime(2026, 1, 1))
    return vid, pid


def _portfolio(*vids):
    pf = P.criar("mesa")
    P.definir_capital(pf, 50_000.0)
    for v in vids:
        P.adicionar_variante(pf, v)
    return pf


def test_exporta_so_variante_ligada_e_nao_removida(banco):
    (v1, p1), (v2, _), (v3, _) = (_variante_com_plano(i) for i in (1, 2, 3))
    pf = _portfolio(v1, v2, v3)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET ligada = false WHERE variante_id = ?", [v2])
    P.remover_variante(pf, v3)

    pacote = ex.montar_pacote(pf, hoje=HOJE)

    assert [v.id for v in pacote.variants] == [v1]
    v = pacote.variants[0]
    assert (v.plan_id, v.symbol, v.timeframe, v.contracts) == (p1, "WIN$N", "M15", 2)
    assert pacote.portfolio == pm.PortfolioPacote(pf, "mesa", 50_000.0, "BRL")
    assert pacote.instrument["symbol"] == "WIN$N" and pacote.instrument["tick_size"] == 5


def test_engine_plan_e_o_plano_do_papel(banco):
    vid, pid = _variante_com_plano(1)
    pf = _portfolio(vid)
    pacote = ex.montar_pacote(pf, hoje=HOJE)
    esperado = plano.detalhes(pid)
    entregue = pacote.variants[0].engine_plan
    for chave in ("plano_id", "params", "profile", "contratos", "strategy", "symbol"):
        assert entregue[chave] == esperado[chave]


def test_breaker_so_com_numeros(banco):
    vid, _ = _variante_com_plano(1)
    breaker = ex.montar_pacote(_portfolio(vid), hoje=HOJE).variants[0].breaker
    assert breaker["nivel2.queda"] == 900.0
    assert breaker["nivel1.perdas_seguidas"] == 4.0
    assert breaker["limite_dia_reais"] == 300.0
    assert "nivel1.lucro_no_prazo" not in breaker and "nivel1.faixa_por_pregao" not in breaker
    assert "nivel1.acao" not in breaker and "horizonte" not in breaker


def test_moeda_mista_recusada(banco):
    v1, _ = _variante_com_plano(1)
    v2, _ = _variante_com_plano(2, symbol="MES")
    pf = P.criar("mista")
    P.definir_capital(pf, 1000.0)
    with db.connect_write() as con:  # contorna a recusa da tela para testar a do exportador
        for lig, v in enumerate((v1, v2), start=100):
            con.execute("INSERT INTO portfolio_membros (ligacao_id, portfolio_id, variante_id, "
                        "adicionado_em, fase, fase_desde, ligada) VALUES (?,?,?,?,'papel',?,true)",
                        [lig, pf, v, datetime(2026, 1, 1), datetime(2026, 1, 1)])
    # mensagem exata da checagem de moeda (a de ativo único diria "um ativo só")
    with pytest.raises(ex.ExportacaoRecusada) as erro:
        ex.montar_pacote(pf, hoje=HOJE)
    assert str(erro.value) == "o pacote não aceita moedas diferentes: BRL, USD"


def test_plano_mais_novo_com_vigencia_futura_nao_e_exportado(banco):
    vid, plano_a = _variante_com_plano(1)  # gravado em 01/01: vale desde 02/01
    plano_b = plano.salvar(
        wfa_id=1, run_id=1, symbol="WIN$N", strategy="rompimento_canal", nome="p2",
        params={"periodo": 30, "stop_pontos": 150}, profile={"timeframe": "M15", "fechamento": "17:30"},
        capital=100_000.0, contratos=5, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="t", margem=None, uso_margem_pct=50.0,
        camada4_travada=True, disjuntor=DISJUNTOR, expectativa={}, reotimizacao={},
        definicoes={}, regua={}, agora=datetime(2026, 11, 11, 10, 0))  # vale só em 12/11
    assert plano_b > plano_a

    v = ex.montar_pacote(_portfolio(vid), hoje=HOJE).variants[0]

    assert v.plan_id == plano_a and v.engine_plan["plano_id"] == plano_a
    assert v.contracts == 2 and v.engine_plan["params"]["periodo"] == 20


def test_variante_sem_plano_recusada(banco):
    vid = variantes.criar("sem plano", "rompimento_canal")
    with pytest.raises(ex.ExportacaoRecusada, match="sem plano"):
        ex.montar_pacote(_portfolio(vid), hoje=HOJE)


def test_portfolio_inexistente_ou_vazio_recusado(banco):
    with pytest.raises(ex.ExportacaoRecusada, match="não existe"):
        ex.montar_pacote(99, hoje=HOJE)
    with pytest.raises(ex.ExportacaoRecusada, match="nenhuma variante"):
        ex.montar_pacote(_portfolio(), hoje=HOJE)


def test_banco_preso_da_erro_claro(banco, monkeypatch):
    def preso(*_a, **_k):
        raise RuntimeError("banco ocupado para leitura: lock")

    monkeypatch.setattr(P, "listar", preso)
    with pytest.raises(ex.ExportacaoRecusada, match="feche a captura ou tente de novo"):
        ex.montar_pacote(1, hoje=HOJE)


def test_json_gerado_passa_nas_checagens_do_prop_live(banco, tmp_path):
    vid, _ = _variante_com_plano(1)
    caminho = ex.exportar(_portfolio(vid), tmp_path / "saida", hoje=HOJE)
    assert caminho.name.startswith("portfolio_") and caminho.suffix == ".json"
    bruto = json.loads(caminho.read_text(encoding="utf-8"))

    # as mesmas checagens de `prop_live.adapters.platform.package.parse`
    assert bruto["format_version"] == 1
    datetime.fromisoformat(bruto["exported_at"])
    str(bruto["platform_commit"]), str(bruto["engine_version"])
    for chave in ("id", "name", "capital", "currency"):
        bruto["portfolio"][chave]
    float(bruto["portfolio"]["capital"])
    ids = [v["id"] for v in bruto["variants"]]
    assert ids and len(set(ids)) == len(ids)
    for v in bruto["variants"]:
        for chave in ("id", "name", "strategy", "plan_id", "symbol", "timeframe", "contracts"):
            v[chave]
        int(v["id"]), int(v["plan_id"]), int(v["contracts"])
        assert isinstance(v["engine_plan"], dict)
        {str(k): float(x) for k, x in v["breaker"].items()}
    for chave in ("symbol", "currency", "tick_size", "tick_value", "point_value", "price_decimals"):
        bruto["instrument"][chave]
    assert bruto["engine_version"]


def test_arvore_suja_e_recusada(monkeypatch):
    monkeypatch.setattr(ex, "rodar_git", _git_simulado(" M core/papel.py\n"))
    with pytest.raises(ex.ExportacaoRecusada, match="mudanças não commitadas"):
        ex.commit_da_plataforma()


def test_arvore_limpa_devolve_o_commit():
    assert ex.commit_da_plataforma() == "abc123"


def test_pregao_do_cme_apos_18h_de_ny_e_o_dia_seguinte(banco, monkeypatch):
    vid, _ = _variante_com_plano(1, symbol="MES")
    pf = _portfolio(vid)
    # 00:00 UTC = 21:00 de Brasília = 19:00 em NY: o pregão já é o de 12/11
    monkeypatch.setattr(ex, "agora_utc", lambda: datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc))
    assert ex.montar_pacote(pf).session_date == date(2026, 11, 12)


def test_pregao_do_win_e_o_dia_corrente(banco, monkeypatch):
    vid, _ = _variante_com_plano(1)
    pf = _portfolio(vid)
    monkeypatch.setattr(ex, "agora_utc", lambda: datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc))
    assert ex.montar_pacote(pf).session_date == date(2026, 11, 11)  # 21:00 em Brasília


def test_dia_explicito_vira_o_session_date(banco):
    vid, _ = _variante_com_plano(1)
    assert ex.montar_pacote(_portfolio(vid), hoje=HOJE).session_date == HOJE


def test_ativo_sem_yaml_e_recusado(banco):
    vid, _ = _variante_com_plano(1, symbol="SEM_YAML")
    with pytest.raises(ex.ExportacaoRecusada, match="SEM_YAML"):
        ex.montar_pacote(_portfolio(vid), hoje=HOJE)
