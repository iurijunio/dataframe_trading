"""Testes do plano de operação — o registro que a incubação vai ler.

Um plano é decisão gravada, não resultado recalculável: ele carrega RETRATOS
dos parâmetros, do perfil de execução e do capital. Mineração apagada não
pode mudar o tamanho de posição de quem já está operando.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import optimizer, plano, variantes, wfa_store  # noqa: E402


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


def _fora_de_vigor(pid):
    from datetime import datetime
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))


def test_excluir_walk_forward_leva_os_planos_junto(banco):
    """Com o plano fora de vigor e sem portfólio, a cascata continua: sem
    ela, o plano apontaria para um walk-forward que não existe mais."""
    _wfa_no_banco()
    pid = plano.salvar(**_campos())
    _fora_de_vigor(pid)
    wfa_store.excluir(1)
    assert plano.detalhes(pid) is None


def test_excluir_mineracao_leva_os_planos_dos_walk_forwards_dela(banco):
    """Regra de 18/09/2026, revista em 30/09/2026: apagar mineração apaga
    tudo que nasceu dela — EXCETO plano que opera ou pode operar."""
    _wfa_no_banco(run_id=7, wfa_id=3)
    pid = plano.salvar(**_campos(wfa_id=3, run_id=7))
    _fora_de_vigor(pid)
    optimizer.excluir_salva(7)
    assert plano.detalhes(pid) is None and plano.listar() == []


def test_excluir_mineracao_nao_leva_plano_de_outra(banco):
    _wfa_no_banco(run_id=7, wfa_id=3)
    _wfa_no_banco(run_id=8, wfa_id=4)
    fica = plano.salvar(**_campos(wfa_id=4, run_id=8))
    sai = plano.salvar(**_campos(wfa_id=3, run_id=7))
    _fora_de_vigor(sai)
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
    """Só o que não opera nem pode operar pode ser apagado — aqui, planos
    sem variante e já fora de vigor."""
    from datetime import datetime
    _wfa_no_banco()
    a = plano.salvar(**_campos(), agora=datetime(2026, 9, 1, 10))
    b = plano.salvar(**_campos(), agora=datetime(2026, 9, 2, 10))
    plano.aposentar(b, agora=datetime(2026, 9, 3, 10))
    assert plano.excluir(a) is True
    assert [p["plano_id"] for p in plano.listar()] == [b]


def test_regravar_o_walk_forward_com_plano_mantem_os_dois(banco):
    """Regravar o MESMO walk-forward substituía o registro e aposentava o
    plano ativo em silêncio (a estratégia saía do ar). Agora, se o antigo
    tem plano, ele fica e o novo entra ao lado; o plano não muda nada."""
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
            passos=passos(), capital=10_000.0, codigo_hash="h1")

    primeiro = grava_wfa()
    pid = plano.salvar(**_campos(wfa_id=primeiro))
    segundo = grava_wfa()

    d = plano.detalhes(pid)
    assert segundo != primeiro
    assert d["estado"] == "ativo" and d["wfa_id"] == primeiro
    assert wfa_store.detalhes(primeiro) is not None
    assert wfa_store.detalhes(segundo)["codigo_hash"] == "h1"
    rotulos = {w["wfa_id"]: w["rotulo"] for w in wfa_store.listar()}
    assert "tem plano" in rotulos[primeiro]
    assert "tem plano" not in rotulos[segundo]
    tem = {w["wfa_id"]: w["tem_plano"] for w in wfa_store.listar()}
    assert tem[primeiro] is True and tem[segundo] is False
    terceiro = grava_wfa()                 # o SEGUNDO não tem plano: substitui
    assert wfa_store.detalhes(segundo) is None
    assert {w["wfa_id"] for w in wfa_store.listar()} == {primeiro, terceiro}
    tem = {w["wfa_id"]: w["tem_plano"] for w in wfa_store.listar()}
    assert tem[primeiro] is True and tem[terceiro] is False


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


# ------------------------------------------- montar o plano pela tela
import numpy as np  # noqa: E402


def _ver(estado="aprovada", reprovados=(), pendentes=()):
    return {"estado": estado, "reprovados": list(reprovados),
            "pendentes": list(pendentes),
            "portoes": [{"nome": "O lucro não é acaso?", "ok": True,
                         "valor": np.float64(2.59), "exigido": "≥ 2,0",
                         "critico": True}]}


def _dim(n=2, margem=None):
    return {"n": n, "risco_pedido_pct": 1.0, "risco_efetivo_pct": 0.8 if n else None,
            "perda_ref": 400.0, "margem": margem, "uso_margem_pct": 50.0,
            "limite": "risco",
            # o texto real de `tamanho.contratos`, não um resumo inventado
            "motivo": None if n else ("o capital não comporta nem 1 contrato: "
                                      "1 contrato já arrisca mais do que o "
                                      "limite pedido")}


def test_pode_gravar_so_aprovada_com_contratos():
    assert plano.pode_gravar(_ver("aprovada"), _dim()) is None
    assert plano.pode_gravar(_ver("aprovada com ressalva"), _dim()) is None


def test_reprovada_nao_grava_e_diz_o_porque():
    """Gravar plano de estratégia reprovada é dar forma oficial a uma
    decisão que a própria tela desaconselhou."""
    m = plano.pode_gravar(_ver("reprovada", reprovados=["Aguenta custo maior?"]),
                          _dim())
    assert m and "reprovada" in m and "Aguenta custo maior?" in m


def test_sem_testes_completos_nao_grava():
    """Teste não medido não aprova nada — é a regra do selo, e vale aqui."""
    m = plano.pode_gravar(_ver("aguardando testes completos",
                               pendentes=["Ganha de entradas sorteadas ao acaso?"]),
                          _dim())
    assert m and "testes completos" in m


def test_zero_contratos_nao_grava():
    """E diz qual conta zerou, sem repetir a mesma frase duas vezes."""
    m = plano.pode_gravar(_ver(), _dim(n=0))
    assert m and "arrisca mais" in m
    assert m.count("1 contrato") <= 2 and "não cabe nem" not in m


def test_expectativa_tem_os_tres_marcos_e_escala_com_os_contratos():
    rng = np.random.default_rng(3)
    pnl = rng.normal(20, 80, 500)
    um = plano.expectativa(pnl, 100_000.0, 1)
    dois = plano.expectativa(pnl, 100_000.0, 2)
    assert set(um) == {"3_meses", "6_meses", "12_meses"}
    for k in um:
        assert um[k]["p10"] <= um[k]["p50"] <= um[k]["p90"]
        assert dois[k]["p50"] == pytest.approx(2 * um[k]["p50"])


def test_expectativa_sem_pregoes_suficientes_nao_inventa():
    assert plano.expectativa(np.zeros(10), 100_000.0, 1) == {}


def _detalhes():
    return {"run_id": 7, "symbol": "WIN$N", "strategy": "rompimento_canal",
            "nome": "#8", "is_meses": 12, "oos_meses": 6,
            "inteligencia": "ulcer", "capital": 100_000.0,
            "camada4_travada": True, "profile": {"contratos": 1},
            "deploy": {"params": {"periodo_canal": 78},
                       "oos_de": "2026-03-01", "oos_ate": "2026-09-01"}}


def test_montar_junta_os_grupos_do_desenho(banco):
    ref = {"valor": 400.0, "de_onde": "a média dos 5% piores pregões"}
    disj = {"nivel2": {"queda": 1800.0}}
    campos = plano.montar(8, _detalhes(), ref, _dim(n=2, margem=1_000.0), disj,
                          _ver("aprovada com ressalva"), {"6_meses": {}})
    # identidade e retratos
    assert campos["wfa_id"] == 8 and campos["params"] == {"periodo_canal": 78}
    # tamanho: capital livre desconta a garantia dos contratos
    assert campos["contratos"] == 2
    assert campos["capital_livre"] == pytest.approx(98_000.0)
    # A data de reotimizar conta de HOJE + os meses de OOS, em coluna
    # própria. Usar o fim da janela do DEPLOY gravava data VENCIDA: com
    # holdout, essa janela começa no corte dos dados (o #8 gravaria
    # "reotimizar em 01/09/2026" num dia 19/09/2026).
    from datetime import date
    hoje = date.today()
    assert campos["reotimizar_em"] > hoje
    meses = (campos["reotimizar_em"].year - hoje.year) * 12 +         (campos["reotimizar_em"].month - hoje.month)
    assert meses == 6
    # receita da reotimização e as duas regras operacionais, por escrito
    r = campos["reotimizacao"]
    assert r["run_id"] == 7 and r["inteligencia"] == "ulcer"
    assert r["camada4_travada"] is True and r["is_meses"] == 12
    regras = " ".join(campos["definicoes"]["regras"]).lower()
    assert "véspera" in regras and "posição aberta" in regras
    # a régua congelada, com o veredito
    assert campos["regua"]["veredito"] == "aprovada com ressalva"
    assert campos["regua"]["portoes"][0]["valor"] == pytest.approx(2.59)


def test_plano_montado_grava_mesmo_com_numeros_do_numpy(banco):
    """Os portões chegam com valores do numpy, que o JSON padrão recusa: a
    gravação não pode quebrar por isso na hora do clique."""
    _wfa_no_banco(run_id=7, wfa_id=8)
    campos = plano.montar(8, _detalhes(), {"valor": 400.0, "de_onde": "x"},
                          _dim(), {"nivel2": {"queda": np.float64(1800.0)}},
                          _ver(), {})
    pid = plano.salvar(**campos)
    d = plano.detalhes(pid)
    assert d["disjuntor"]["nivel2"]["queda"] == 1800.0
    assert d["regua"]["portoes"][0]["valor"] == pytest.approx(2.59)


def test_expectativa_usa_o_sorteio_que_a_tela_ja_fez(banco):
    """O plano não pode gravar dois números diferentes para a mesma
    pergunta: a faixa de 6 meses tem que ser o mesmo número que o disjuntor
    mostrou para o mesmo prazo, e não um sorteio novo de outro recorte."""
    from core import robustez

    rng = np.random.default_rng(4)
    pnl = rng.normal(20, 80, 400)
    boot = robustez.bootstrap(pnl, 100_000.0, horizonte=126)
    e = plano.expectativa(pnl, 100_000.0, fator=2.0, boot=boot)
    assert e["6_meses"]["p10"] == pytest.approx(
        float(boot["envelope_p10"][125]) * 2)
    # o marco de 12 meses vai além do sorteio da tela: sorteio próprio, sobre
    # a MESMA série
    assert e["12_meses"]["pregoes"] == 252


def test_expectativa_nao_promete_prazo_que_a_curva_nao_sustenta(banco):
    curta = np.full(25, 10.0)
    assert plano.expectativa(curta, 100_000.0) == {}


def test_deploy_fora_do_mercado_nao_vira_plano(banco):
    """A última janela pode ficar fora do mercado (ninguém aprovado, ou a
    camada 4 travada sem candidata que case). Gravar isso daria um plano de
    operação que não diz o que operar."""
    m = plano.pode_gravar(_ver(), _dim(), params={})
    assert m and "fora do mercado" in m
    assert plano.pode_gravar(_ver(), _dim(), params={"a": 1}) is None


def test_plano_novo_aposenta_o_ativo_do_mesmo_walk_forward(banco):
    """Dois planos ativos deixariam a incubação sem saber qual obedecer — e
    um duplo clique já criava esse caso. O anterior fica no banco."""
    _wfa_no_banco()
    velho = plano.salvar(**_campos())
    novo = plano.salvar(**_campos(contratos=1))
    assert plano.detalhes(velho)["estado"] == "aposentado"
    assert plano.detalhes(novo)["estado"] == "ativo"
    assert [p["plano_id"] for p in plano.listar(wfa_id=1, apenas_ativos=True)] == [novo]


def test_aviso_da_ressalva_de_reotimizar(banco):
    """Decisão do usuário: grava, mas avisa em destaque."""
    com = plano.aviso_ao_gravar({"ressalvas": [{"nome": "Reotimizar compensou?"}]})
    assert com and "não compensou" in com.lower()
    assert plano.aviso_ao_gravar({"ressalvas": [{"nome": "Algum vizinho dá prejuízo?"}]}) is None


# ------------------------------------------------------------ gatilho: vencendo
def test_vencendo_plano_no_passado_tem_dias_restantes_negativo(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=hoje - timedelta(days=4)))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)

    assert len(v) == 1
    assert v[0]["dias_restantes"] == -4


def test_vencendo_dentro_da_janela_aparece(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=hoje + timedelta(days=5)))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert len(v) == 1


def test_vencendo_no_limite_exato_da_janela_aparece(banco):
    """`dias_aviso=7` inclui o dia exatamente 7 dias à frente — não é
    "menos de 7", é "até 7"."""
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=hoje + timedelta(days=7)))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert len(v) == 1


def test_vencendo_fora_da_janela_nao_aparece(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=hoje + timedelta(days=30)))

    assert plano.vencendo(dias_aviso=7, hoje=hoje) == []


def test_vencendo_ignora_plano_aposentado(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    velho = plano.salvar(**_campos(reotimizar_em=hoje - timedelta(days=10)))
    plano.aposentar(velho)

    assert plano.vencendo(dias_aviso=7, hoje=hoje) == []


def test_vencendo_ignora_plano_sem_reotimizar_em(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=None))

    assert plano.vencendo(dias_aviso=7, hoje=hoje) == []


def test_vencendo_traz_nome_da_variante(banco):
    hoje = date(2026, 9, 24)
    vid = variantes.criar("conservadora", "rompimento_canal")
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [1, "WIN$N", "rompimento_canal", "2026-01-01", 10, "concluida", vid])
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=hoje - timedelta(days=1)))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert v[0]["variante_nome"] == "conservadora"


def test_vencendo_sem_variante_traz_none(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco()
    plano.salvar(**_campos(reotimizar_em=hoje - timedelta(days=1)))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert v[0]["variante_nome"] is None


def test_vencendo_ordenado_pelo_mais_vencido_primeiro(banco):
    hoje = date(2026, 9, 24)
    _wfa_no_banco(wfa_id=1)
    _wfa_no_banco(run_id=2, wfa_id=2)
    plano.salvar(**_campos(wfa_id=1, run_id=1,
                           reotimizar_em=hoje - timedelta(days=1)))
    plano.salvar(**_campos(wfa_id=2, run_id=2,
                           reotimizar_em=hoje - timedelta(days=10)))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert [p["dias_restantes"] for p in v] == [-10, -1]


# ------------------------------------- gravar mesmo assim (01/10/2026)
def test_forcar_ignora_so_a_trava_do_veredito():
    """"Gravar mesmo assim" passa por cima do veredito — a decisão é do
    operador —, mas nunca grava um plano que não diz o que operar."""
    reprovada = _ver("reprovada", reprovados=["Os parâmetros estão numa região larga?"])
    aguardando = _ver("aguardando testes completos",
                      pendentes=["Ganha de entradas sorteadas ao acaso?"])
    assert plano.pode_gravar(reprovada, _dim()) is not None
    assert plano.pode_gravar(reprovada, _dim(), forcar=True) is None
    assert plano.pode_gravar(aguardando, _dim(), forcar=True) is None
    fora = plano.pode_gravar(reprovada, _dim(), params={}, forcar=True)
    assert fora and "fora do mercado" in fora
    sem_contrato = plano.pode_gravar(reprovada, _dim(n=0), forcar=True)
    assert sem_contrato and "arrisca mais" in sem_contrato


def test_pendencias_lista_o_que_falhou_e_o_que_nao_mediu():
    ver = _ver("reprovada", reprovados=["Aguenta custo maior?"],
               pendentes=["Ganha de entradas sorteadas ao acaso?"])
    assert plano.pendencias(ver) == [
        {"nome": "Aguenta custo maior?", "motivo": "reprovado"},
        {"nome": "Ganha de entradas sorteadas ao acaso?", "motivo": "não medido"}]
    # o veredito do core traz os portões inteiros, não só os nomes
    core = {"reprovados": [{"nome": "A", "ok": False}],
            "pendentes": [{"nome": "B", "ok": None}]}
    assert [p["nome"] for p in plano.pendencias(core)] == ["A", "B"]
    assert plano.pendencias(_ver("aprovada")) == []


def test_salvar_grava_a_decisao_de_gravar_mesmo_assim(banco):
    _wfa_no_banco()
    pend = [{"nome": "Aguenta custo maior?", "motivo": "reprovado"}]
    pid = plano.salvar(**_campos(gravado_mesmo_assim=True, pendencias=pend))
    d = plano.detalhes(pid)
    assert d["gravado_mesmo_assim"] is True
    assert d["pendencias"] == pend
    normal = plano.detalhes(plano.salvar(**_campos()))
    assert normal["gravado_mesmo_assim"] is False and normal["pendencias"] == []


def test_diario_registra_o_que_ficou_pendente(banco):
    from core import diario
    _wfa_no_banco()
    pend = [{"nome": "Aguenta custo maior?", "motivo": "reprovado"},
            {"nome": "Ganha de entradas sorteadas ao acaso?", "motivo": "não medido"}]
    pid = plano.salvar(**_campos(gravado_mesmo_assim=True, pendencias=pend))
    ev = [e for e in diario.eventos(tipo="plano_gravado") if e["plano_id"] == pid]
    assert len(ev) == 1
    m = ev[0]["motivo"]
    assert "gravado mesmo assim" in m
    assert "reprovado em: Aguenta custo maior?" in m
    assert "não medido: Ganha de entradas sorteadas ao acaso?" in m
    normal = plano.salvar(**_campos())
    ev = [e for e in diario.eventos(tipo="plano_gravado") if e["plano_id"] == normal]
    assert "mesmo assim" not in ev[0]["motivo"]


def test_colunas_novas_entram_em_banco_antigo_e_rodar_duas_vezes_nao_quebra(banco):
    """Banco de antes desta entrega (sem as duas colunas): subir o app
    acrescenta, e subir de novo não faz nada — o .duckdb não se recria."""
    with db.connect() as con:
        con.execute("ALTER TABLE planos_operacao DROP COLUMN gravado_mesmo_assim")
        con.execute("ALTER TABLE planos_operacao DROP COLUMN pendencias")
        db.init_schema(con)
        db.init_schema(con)
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'planos_operacao'").fetchall()}
    assert {"gravado_mesmo_assim", "pendencias"} <= cols


def test_montar_com_forcar_leva_as_pendencias(banco):
    ver = _ver("reprovada", reprovados=["Aguenta custo maior?"])
    campos = plano.montar(8, _detalhes(), {"valor": 400.0, "de_onde": "x"},
                          _dim(), {}, ver, {}, forcar=True)
    assert campos["gravado_mesmo_assim"] is True
    assert campos["pendencias"] == [{"nome": "Aguenta custo maior?",
                                     "motivo": "reprovado"}]
    normal = plano.montar(8, _detalhes(), {"valor": 400.0, "de_onde": "x"},
                          _dim(), {}, _ver(), {})
    assert normal["gravado_mesmo_assim"] is False and normal["pendencias"] == []
    # sem forcar, o plano não se marca nem com o veredito contra — só o
    # segundo clique de "Gravar mesmo assim" registra a decisão
    sem_forcar = plano.montar(8, _detalhes(), {"valor": 400.0, "de_onde": "x"},
                              _dim(), {}, ver, {})
    assert sem_forcar["gravado_mesmo_assim"] is False
    assert sem_forcar["pendencias"] == []
