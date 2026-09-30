from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _mineracao_com_plano_ativo(run_id, variante_id, wfa_id,
                               symbol="WIN$N", strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, "2026-01-01", 10, "concluida", variante_id])
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])
    plano.salvar(
        wfa_id=wfa_id, run_id=run_id, symbol=symbol, strategy=strategy,
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})


def test_criar_e_listar(banco):
    pid = P.criar("meu portfólio")
    ps = P.listar()
    assert [p["portfolio_id"] for p in ps] == [pid]
    assert ps[0]["nome"] == "meu portfólio"
    assert ps[0]["n_membros"] == 0


def test_adicionar_e_remover_membro(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert [m["variante_id"] for m in ms] == [vid]
    assert P.listar()[0]["n_membros"] == 1

    P.remover_variante(pid, vid)
    assert P.membros(pid) == []
    assert P.listar()[0]["n_membros"] == 0


def test_membro_sem_plano_ativo_e_sinalizado(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is True
    assert ms[0]["wfa_id"] is None


def test_membro_com_plano_ativo_traz_o_wfa_id(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is False
    assert ms[0]["wfa_id"] == 10


def test_adicionar_a_mesma_variante_duas_vezes_nao_duplica(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)
    P.adicionar_variante(pid, vid)
    assert len(P.membros(pid)) == 1


# --------------------------------------------------------------- correlacao
from datetime import datetime, timedelta


def _gravar_trades(wfa_id, dias_e_liquidos):
    """dias_e_liquidos: [(offset_dias, liquido), ...] a partir de 2026-01-01."""
    base = datetime(2026, 1, 1)
    with db.connect_write() as con:
        for n, (offset, liquido) in enumerate(dias_e_liquidos):
            ts = base + timedelta(days=offset)
            con.execute(
                "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, "
                "liquido, mae, contratos) VALUES (?,?,?,?,?,?,?)",
                [wfa_id, n, ts, ts, liquido, 100, 1])


def _membro_pronto(pid, nome, wfa_id, dias_e_liquidos):
    vid = variantes.criar(nome, "rompimento_canal")
    _mineracao_com_plano_ativo(wfa_id, vid, wfa_id=wfa_id)
    P.adicionar_variante(pid, vid)
    _gravar_trades(wfa_id, dias_e_liquidos)
    return vid


def test_correlacao_de_series_identicas_e_proxima_de_um(banco):
    pid = P.criar("p1")
    serie = [(i, float((i % 5) - 2)) for i in range(30)]
    _membro_pronto(pid, "a", 10, serie)
    _membro_pronto(pid, "b", 11, serie)

    r = P.correlacao(pid)

    assert r["variantes"] == ["a", "b"]
    assert r["matriz"][0][1] == pytest.approx(1.0, abs=1e-6)
    assert r["avisos"] == []


def test_correlacao_de_series_opostas_e_proxima_de_menos_um(banco):
    pid = P.criar("p1")
    serie_a = [(i, float((i % 5) - 2)) for i in range(30)]
    serie_b = [(i, -v) for i, v in serie_a]
    _membro_pronto(pid, "a", 10, serie_a)
    _membro_pronto(pid, "b", 11, serie_b)

    r = P.correlacao(pid)
    assert r["matriz"][0][1] == pytest.approx(-1.0, abs=1e-6)


def test_periodo_sem_intersecao_suficiente_vira_aviso(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 1.0) for i in range(30)])
    _membro_pronto(pid, "b", 11, [(i, 1.0) for i in range(200, 210)])

    r = P.correlacao(pid)
    assert r["matriz"][0][1] is None
    assert "período curto demais" in r["avisos"][0]


def test_serie_com_variancia_zero_vira_aviso_nao_nan(banco):
    """Retorno constante no periodo faz corrcoef dar 0/0 = nan - um numero
    "real" sem sentido nenhum se deixado passar direto pra matriz."""
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 5.0) for i in range(30)])  # sempre +5
    _membro_pronto(pid, "b", 11, [(i, float((i % 5) - 2)) for i in range(30)])

    r = P.correlacao(pid)
    assert r["matriz"][0][1] is None
    assert "variação suficiente" in r["avisos"][0]


def test_membro_sem_plano_ativo_fica_de_fora_da_matriz(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 1.0) for i in range(30)])
    vid_b = variantes.criar("b", "rompimento_canal")
    P.adicionar_variante(pid, vid_b)

    r = P.correlacao(pid)
    assert r["variantes"] == ["a"]
    assert any("sem plano ativo" in a for a in r["avisos"])


# ------------------------------------------------------------- risco diario
def _gravar_trade_risco(wfa_id, entry_ts, exit_ts, mae_pontos, liquido):
    # sem linha em `instruments` para o simbolo do teste, `_trades_para_risco`
    # cai no padrao point_value=1.0 - mae_pontos vira mae_reais 1:1, de
    # proposito, pra deixar os numeros dos testes faceis de conferir a mao
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, mae, "
            "contratos, liquido) VALUES (?,?,?,?,?,?,?)",
            [wfa_id, 0, entry_ts, exit_ts, mae_pontos, 1, liquido])


def test_risco_diario_none_sem_sobreposicao_nenhuma(banco):
    pid = P.criar("p1")
    vid = variantes.criar("a", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)
    _gravar_trade_risco(10, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 17),
                        mae_pontos=100, liquido=50.0)

    r = P.correlacao(pid)
    assert r["risco_diario"] is None


def test_risco_diario_trades_sem_sobreposicao_de_horario_fica_leve(banco):
    """Duas variantes que operam em janelas de horário que NUNCA se cruzam
    no mesmo dia não devem produzir um risco parecido com a soma dos dois
    piores casos - é essa a armadilha que a simulação evita."""
    pid = P.criar("p1")
    vid_a = variantes.criar("a", "rompimento_canal")
    vid_b = variantes.criar("b", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid_a, wfa_id=10)
    _mineracao_com_plano_ativo(2, vid_b, wfa_id=11)
    P.adicionar_variante(pid, vid_a)
    P.adicionar_variante(pid, vid_b)
    dia = datetime(2026, 1, 1)
    _gravar_trade_risco(10, dia.replace(hour=9), dia.replace(hour=10),
                        mae_pontos=500, liquido=-100.0)
    _gravar_trade_risco(11, dia.replace(hour=14), dia.replace(hour=15),
                        mae_pontos=500, liquido=-100.0)

    r = P.correlacao(pid)
    assert r["risco_diario"] is not None
    assert r["risco_diario"]["p90"] > -700


def test_risco_diario_trades_sempre_sobrepostos_fica_proximo_da_soma(banco):
    """Duas variantes que operam o dia inteiro (janela igual) se encontram
    em toda simulação - o p90 deve chegar perto da soma dos dois MAEs."""
    pid = P.criar("p1")
    vid_a = variantes.criar("a", "rompimento_canal")
    vid_b = variantes.criar("b", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid_a, wfa_id=10)
    _mineracao_com_plano_ativo(2, vid_b, wfa_id=11)
    P.adicionar_variante(pid, vid_a)
    P.adicionar_variante(pid, vid_b)
    dia = datetime(2026, 1, 1)
    _gravar_trade_risco(10, dia.replace(hour=9), dia.replace(hour=17),
                        mae_pontos=500, liquido=-100.0)
    _gravar_trade_risco(11, dia.replace(hour=9), dia.replace(hour=17),
                        mae_pontos=500, liquido=-100.0)

    r = P.correlacao(pid)
    assert -1000.0 < r["risco_diario"]["p90"] < -600
    assert r["risco_diario"]["pior_dia"] == "2026-01-01"


# ------------------------------------------------------------ curva de capital
def test_curvas_acumula_a_partir_do_capital_do_plano(banco):
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(0, 500.0), (1, -200.0), (2, 300.0)])

    r = P.curvas(pid)

    serie = r["series"]["a"]
    assert serie["capital_inicial"] == 100_000.0
    assert [p["capital"] for p in serie["pontos"]] == [
        100_500.0, 100_300.0, 100_600.0]
    assert r["avisos"] == []


def test_curvas_ordena_por_data_de_saida(banco):
    pid = P.criar("p1")
    # grava fora de ordem de proposito - a curva tem que reordenar por exit_ts
    vid = variantes.criar("a", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)
    from datetime import datetime
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, liquido, "
            "mae, contratos) VALUES (?,?,?,?,?,?,?)",
            [10, 0, datetime(2026, 1, 3), datetime(2026, 1, 3), 300.0, 0, 1])
        con.execute(
            "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, liquido, "
            "mae, contratos) VALUES (?,?,?,?,?,?,?)",
            [10, 1, datetime(2026, 1, 1), datetime(2026, 1, 1), 500.0, 0, 1])

    serie = P.curvas(pid)["series"]["a"]
    assert [p["capital"] for p in serie["pontos"]] == [100_500.0, 100_800.0]


def test_curvas_so_traz_membros_com_plano_ativo(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(0, 100.0)])
    vid_b = variantes.criar("b", "rompimento_canal")
    P.adicionar_variante(pid, vid_b)

    r = P.curvas(pid)
    assert list(r["series"]) == ["a"]
    assert any("sem plano ativo" in a for a in r["avisos"])


def test_curvas_combinada_usa_o_capital_do_portfolio_nao_a_soma(banco):
    """Achado real do usuário: somar o capital de cada plano assumia
    contas separadas por variante. Na prática é a MESMA conta rodando as
    duas juntas - o capital combinado é o do PORTFÓLIO, não a soma."""
    pid = P.criar("p1")
    P.definir_capital(pid, 150_000.0)
    _membro_pronto(pid, "a", 10, [(0, 100.0)])
    _membro_pronto(pid, "b", 11, [(0, -50.0)])

    r = P.curvas(pid)
    assert r["combinada"]["capital_inicial"] == 150_000.0  # nao 200.000


def test_curvas_combinada_intercala_por_data_de_fechamento(banco):
    """Trade de "b" fecha ENTRE os dois de "a" - a combinada tem que
    seguir a ordem cronológica real, não uma variante inteira e depois
    a outra."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(0, 100.0), (2, 100.0)])   # dias 0 e 2
    _membro_pronto(pid, "b", 11, [(1, -30.0)])                # dia 1, no meio

    r = P.curvas(pid)
    capitais = [p["capital"] for p in r["combinada"]["pontos"]]
    # 100.000 + 100 (dia 0, "a") = 100.100
    # 100.100 - 30 (dia 1, "b") = 100.070
    # 100.070 + 100 (dia 2, "a") = 100.170
    assert capitais == [100_100.0, 100_070.0, 100_170.0]


def test_curvas_combinada_none_sem_nenhum_trade(banco):
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    vid = variantes.criar("a", "rompimento_canal")
    P.adicionar_variante(pid, vid)  # sem plano ativo nenhum

    r = P.curvas(pid)
    assert r["combinada"] is None


def test_curvas_combinada_none_sem_capital_do_portfolio(banco):
    """Trades existem, mas ninguém disse quanto a conta do portfólio
    tem - sem isso não dá pra desenhar uma curva em R$ honesta."""
    pid = P.criar("p1")  # capital nunca definido
    _membro_pronto(pid, "a", 10, [(0, 100.0)])

    r = P.curvas(pid)
    assert r["combinada"] is None
    assert any("capital do portfólio" in a for a in r["avisos"])


# ------------------------------------------------------------------ resumo
def test_resumo_agrega_trades_de_todas_as_variantes(banco):
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(0, 100.0), (1, -40.0)])
    _membro_pronto(pid, "b", 11, [(0, 50.0)])

    r = P.resumo(pid)
    assert r["trades"] == 3
    assert r["lucro_liquido"] == pytest.approx(110.0)  # 100 - 40 + 50


def test_resumo_ordena_trades_por_data_para_o_drawdown(banco):
    """Achado real do usuário ("é isso mesmo o drawdown combinado?"): os
    trades das duas variantes entravam na conta member-a-member (todos os
    de "a", depois todos os de "b"), não intercalados por data como em
    `curvas()`. O lucro total bate igual nas duas ordens, mas o CAMINHO da
    curva - e portanto o drawdown máximo - muda de verdade quando a ordem
    cronológica dá um pico mais alto antes da queda."""
    pid = P.criar("p1")
    P.definir_capital(pid, 1_000.0)
    # sequencial (a inteiro, depois b): 1000 -500(a)=500 +1000(b)=1500 -1000(b)=500
    #   -> dd = 1000 (de 1500 a 500)
    # cronologico (b dia0, a dia1, b dia2): 1000 +1000(b)=2000 -500(a)=1500 -1000(b)=500
    #   -> dd = 1500 (de 2000 a 500)
    _membro_pronto(pid, "a", 10, [(1, -500.0)])
    _membro_pronto(pid, "b", 11, [(0, 1000.0), (2, -1000.0)])

    r = P.resumo(pid)
    assert r["lucro_liquido"] == pytest.approx(-500.0)
    assert r["max_drawdown"] == pytest.approx(1500.0)


# ---------------------------------------------------- comparativo por membro
def test_resumo_membros_calcula_cada_variante_isolada(banco):
    """Pedido real do usuário: comparar o DD de cada estratégia com o do
    portfólio combinado, lado a lado, pra ver se juntar compensa."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(0, 100.0), (1, -40.0)])
    _membro_pronto(pid, "b", 11, [(0, 50.0)])

    r = P.resumo_membros(pid)

    assert set(r.keys()) == {"a", "b"}
    assert r["a"]["trades"] == 2
    assert r["a"]["lucro_liquido"] == pytest.approx(60.0)
    assert r["b"]["trades"] == 1
    assert r["b"]["lucro_liquido"] == pytest.approx(50.0)


def test_resumo_membros_ignora_membro_sem_plano_ou_sem_trade(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(0, 100.0)])
    vid_b = variantes.criar("b", "rompimento_canal")
    P.adicionar_variante(pid, vid_b)  # sem plano ativo

    r = P.resumo_membros(pid)
    assert set(r.keys()) == {"a"}


# --------------------------------------------- Kelly e risco de ruina
def test_simulacao_capital_none_sem_capital_do_portfolio(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(0, 100.0)])
    assert P.simulacao_capital(pid) is None


def test_simulacao_capital_kelly_positivo_para_serie_com_edge_positivo(banco):
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    # 15 ganhos de 100 pra 5 perdas de 50 - edge positivo real, win_rate
    # 75% e payoff 2:1, o par que a fórmula de Kelly usa
    trades = [(i, 100.0) for i in range(15)] + [(i, -50.0) for i in range(15, 20)]
    _membro_pronto(pid, "a", 10, trades)

    r = P.simulacao_capital(pid)
    assert r["kelly_pct"] > 0
    assert r["kelly_meio_pct"] == pytest.approx(r["kelly_pct"] / 2)
    assert r["kelly_indefinido"] is False


def test_simulacao_capital_kelly_indefinido_sem_nenhuma_perda(banco):
    """payoff=0.0 é sentinela pra DUAS situações bem diferentes: "sem
    vantagem nenhuma" e "ainda sem trade perdedor pra medir o tamanho da
    perda". Achado do usuário ("13% o quê? não ficou claro"): tratar as
    duas como Kelly=0% escondia justamente o caso bom (edge forte demais
    pra fórmula calcular) atrás do caso neutro."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(i, 100.0) for i in range(10)])  # só ganhos

    r = P.simulacao_capital(pid)
    assert r["kelly_indefinido"] is True
    assert r["kelly_pct"] is None
    assert r["kelly_meio_pct"] is None


def test_simulacao_capital_indefinida_sem_nenhuma_perda(banco):
    """Sem perda registrada não dá pra medir "1R" - nem Kelly nem risco de
    ruína têm o que calcular (mesma amostra, mesma limitação)."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(i, 100.0) for i in range(10)])

    r = P.simulacao_capital(pid)
    assert r["prob_ruina_meio_kelly_pct"] is None
    assert r["risco_recomendado_pct"] is None


def test_simulacao_capital_prob_ruina_none_sem_vantagem_nenhuma(banco):
    """kelly_pct=0.0 é "sem vantagem nenhuma" de verdade (há perda no
    histórico, mas nenhum ganho) - meio-Kelly seria 0% (não aposte
    nada). Medir ruína num risco % que não é Kelly nenhum, sob um rótulo
    que diz "no meio-kelly", seria um número que parece medido mas não
    mede o que o rótulo promete (achado da revisão)."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(i, -100.0) for i in range(10)])  # só perdas

    r = P.simulacao_capital(pid)
    assert r["kelly_pct"] == 0.0
    assert r["prob_ruina_meio_kelly_pct"] is None


def test_simulacao_capital_e_simular_crescimento_concordam_sobre_risco(banco):
    """Achado real do usuário: o cartão de risco de ruína e o simulador de
    crescimento pareciam discordar porque usavam modelos de aposta
    diferentes (tamanho fixo em R$ vs. fração fixa do capital). Prova de
    consistência de verdade (não vacuosa): série determinística (só
    perdas de -1R iguais) onde `simulacao_capital` recomenda 2% e rejeita
    3% - o PRÓPRIO drawdown medido por `simular_crescimento` (função
    independente) tem que confirmar isso, ficando abaixo do limiar nos
    2% recomendados e acima dele nos 3% rejeitados. "prob_zerar_pct" não
    servia pra esse teste: com séries de edge positivo ele fica em 0%
    pra qualquer risco testado, então passaria mesmo com um
    risco_recomendado_pct errado (achado da revisão)."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(i, -100.0) for i in range(10)])  # só perdas

    sim_risco = P.simulacao_capital(pid, limiar_dd_pct=25.0, prob_max_pct=10.0)
    risco_seguro = sim_risco["risco_recomendado_pct"]
    assert risco_seguro == pytest.approx(2.0)

    seguro = P.simular_crescimento(pid, capital_inicial=100_000.0,
                                   risco_pct=risco_seguro, n_trades=10,
                                   n_simulacoes=100)
    dd_seguro = 1 - seguro["p50"][-1] / 100_000.0
    assert dd_seguro < 0.25

    # um degrau de risco acima (3%) foi rejeitado por simulacao_capital -
    # o simulador de crescimento, rodando por conta própria, tem que
    # concordar que aquele nível já estoura o limiar
    arriscado = P.simular_crescimento(pid, capital_inicial=100_000.0,
                                      risco_pct=3.0, n_trades=10,
                                      n_simulacoes=100)
    dd_arriscado = 1 - arriscado["p50"][-1] / 100_000.0
    assert dd_arriscado > 0.25


def test_simulacao_capital_risco_recomendado_e_o_maior_ainda_seguro(banco):
    """Série SEM variação nenhuma (toda perda de -1R exatamente igual) -
    o bootstrap fica determinístico, então dá pra calcular o risco de
    ruína na mão e comparar: com 10 trades e limiar de 25% de drawdown,
    2% de risco sobrevive (dd acumulado ~18,3%) e 3% não (dd ~26,3%) -
    o recomendado tem que ser exatamente 2%, nem mais nem menos."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(i, -100.0) for i in range(10)])

    r = P.simulacao_capital(pid, limiar_dd_pct=25.0, prob_max_pct=10.0)
    assert r["risco_recomendado_pct"] == pytest.approx(2.0)


def test_simulacao_capital_risco_alto_demais_nao_recomenda_nada(banco):
    """Uma série com uma perda catastrófica isolada e um limiar de
    drawdown apertado deve deixar claro que NENHUM risco testado (nem o
    menor da grade, 1%) é seguro o bastante, em vez de recomendar um
    risco % que na prática ainda é perigoso. Sob fração fixa, 1% de
    risco já produz exatamente 1% de drawdown num trade de "1R" perdido -
    com limiar de 0,5% até isso estoura."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    trades = [(i, 50.0) for i in range(10)] + [(10, -5_000.0)]
    _membro_pronto(pid, "a", 10, trades)

    r = P.simulacao_capital(pid, limiar_dd_pct=0.5, prob_max_pct=1.0)
    assert r["risco_recomendado_pct"] is None


# -------------------------------------------- simulacao de crescimento
def test_simular_crescimento_none_sem_nenhuma_perda(banco):
    """Sem perda registrada não dá pra medir "1R" (o tamanho da perda
    média) - a simulação de crescimento fica indefinida, igual ao Kelly."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(i, 100.0) for i in range(10)])

    r = P.simular_crescimento(pid, capital_inicial=100_000.0, risco_pct=5.0,
                              n_trades=50)
    assert r is None


def test_simular_crescimento_recusa_parametros_nao_positivos(banco):
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(0, 100.0), (1, -50.0)])

    with pytest.raises(ValueError):
        P.simular_crescimento(pid, capital_inicial=0, risco_pct=5.0, n_trades=50)
    with pytest.raises(ValueError):
        P.simular_crescimento(pid, capital_inicial=100_000.0, risco_pct=0,
                              n_trades=50)
    with pytest.raises(ValueError):
        P.simular_crescimento(pid, capital_inicial=100_000.0, risco_pct=5.0,
                              n_trades=0)
    with pytest.raises(ValueError):
        P.simular_crescimento(pid, capital_inicial=100_000.0, risco_pct=5.0,
                              n_trades=-10)


def test_simular_crescimento_recusa_n_trades_absurdo(banco):
    """Sem teto, um número digitado por engano (ex.: "1000000" em vez de
    "100") aloca uma matriz de dezenas de GB em rng.choice e trava o
    servidor - achado da revisão."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    _membro_pronto(pid, "a", 10, [(0, 100.0), (1, -50.0)])

    with pytest.raises(ValueError):
        P.simular_crescimento(pid, capital_inicial=100_000.0, risco_pct=5.0,
                              n_trades=1_000_000)


def test_simular_crescimento_mediana_cresce_para_serie_com_edge_forte(banco):
    """Série com edge bem positivo (75% de acerto, payoff 2:1) simulada
    com risco moderado deve fazer a mediana da curva terminar ACIMA do
    capital inicial - não é só ruído, é crescimento composto de verdade."""
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    trades = [(i, 200.0) for i in range(15)] + [(i, -100.0) for i in range(15, 20)]
    _membro_pronto(pid, "a", 10, trades)

    r = P.simular_crescimento(pid, capital_inicial=100_000.0, risco_pct=5.0,
                              n_trades=200, n_simulacoes=1000)
    assert r["capital_final_mediana"] > 100_000.0
    assert len(r["p50"]) == 201  # ponto 0 (capital inicial) + 200 trades
    assert r["p50"][0] == pytest.approx(100_000.0)
    assert r["p10"][-1] <= r["p50"][-1] <= r["p90"][-1]


def test_simular_crescimento_capital_nunca_fica_negativo(banco):
    """Um único trade perdedor de "1R" arriscando mais de 100% do capital
    (risco_pct > 100, entrada absurda mas não bloqueada) faria o capital
    ir a negativo sem o clamp - "dever" não existe numa simulação de
    banca, o pior cenário é zerar."""
    pid = P.criar("p1")
    P.definir_capital(pid, 1_000.0)
    trades = [(i, 50.0) for i in range(10)] + [(10, -5_000.0)]
    _membro_pronto(pid, "a", 10, trades)

    r = P.simular_crescimento(pid, capital_inicial=1_000.0, risco_pct=150.0,
                              n_trades=30, n_simulacoes=1000)
    todos_pontos = r["p10"] + r["p50"] + r["p90"]
    assert min(todos_pontos) >= 0.0


def test_resumo_none_sem_variante_ativa(banco):
    pid = P.criar("p1")
    P.definir_capital(pid, 100_000.0)
    assert P.resumo(pid) is None


def test_resumo_none_sem_capital_do_portfolio(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(0, 100.0)])
    assert P.resumo(pid) is None


# --------------------------------------------------------- capital do portfolio
def test_definir_capital_aparece_no_listar(banco):
    pid = P.criar("p1")
    assert P.listar()[0]["capital"] is None

    P.definir_capital(pid, 250_000.0)
    assert P.listar()[0]["capital"] == 250_000.0


def test_definir_capital_recusa_valor_nao_positivo(banco):
    pid = P.criar("p1")
    with pytest.raises(ValueError, match="positivo"):
        P.definir_capital(pid, 0)
    with pytest.raises(ValueError, match="positivo"):
        P.definir_capital(pid, -100.0)
