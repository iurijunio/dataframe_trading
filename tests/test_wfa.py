"""Testes do Walk-Forward Analysis.

A disciplina de sempre: cada caso é montado com a resposta conhecida de
antemão. Aqui isso é ainda mais importante, porque o WFA é a peça que decide
se uma estratégia vai para o dinheiro real — um erro de janela ou de sinal
passa despercebido e vira prejuízo.

O caso de referência é o da tela do operador: base de 60 meses, IS 18 / OOS 6,
que tem que dar exatamente 7 passos mais a linha DEPLOY.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import wfa  # noqa: E402

CAP = 10_000.0
INICIO, FIM = "2021-03-16", "2026-03-13"


def combo(params: dict, por_mes: dict[str, float], trades_mes: int = 12):
    """Uma combinação com resultado controlado por mês.

    `por_mes` diz quanto CADA trade rende num mês (chave "AAAA-MM"); meses
    ausentes não têm trade. Assim dá para desenhar exatamente a curva que o
    teste precisa.
    """
    ts, liq = [], []
    for mes, valor in por_mes.items():
        base = np.datetime64(f"{mes}-02T10:00", "s")
        for k in range(trades_mes):
            ts.append(base + np.timedelta64(k, "D"))
            liq.append(float(valor))
    ordem = np.argsort(np.array(ts))
    return {"params": params,
            "entry_ts": np.array(ts)[ordem],
            "liquido": np.array(liq)[ordem]}


def meses(de: str, ate: str) -> list[str]:
    a, b = np.datetime64(de, "M"), np.datetime64(ate, "M")
    return [str(a + np.timedelta64(k, "M")) for k in range(int((b - a).astype(int)))]


# ------------------------------------------------------------- janelas
def test_a_escadinha_bate_com_a_referencia_do_operador():
    """60 meses, IS:18/OOS:6 → 7 passos + DEPLOY, com as datas da tela."""
    js = wfa.montar_janelas(INICIO, FIM, 18, 6)
    reais = [j for j in js if not j.deploy]

    assert len(reais) == 7
    assert sum(1 for j in js if j.deploy) == 1

    assert str(reais[0].is_de)[:10] == "2021-03-01"
    assert str(reais[0].is_ate)[:10] == "2022-09-01"
    assert str(reais[0].oos_ate)[:10] == "2023-03-01"

    dep = js[-1]
    assert str(dep.is_de)[:10] == "2024-09-01"
    assert str(dep.is_ate)[:10] == "2026-03-01"
    assert str(dep.oos_de)[:10] == "2026-03-01"    # o OOS dele é o futuro


@pytest.mark.parametrize("is_m,oos_m,esperado", [
    (6, 3, 18), (9, 3, 17), (12, 3, 16), (8, 4, 13), (12, 4, 12), (16, 4, 11),
    (10, 5, 10), (15, 5, 9), (12, 6, 8), (20, 5, 8), (18, 6, 7), (24, 6, 6),
])
def test_as_doze_configuracoes_dao_os_steps_da_referencia(is_m, oos_m, esperado):
    """A lista que o operador roda em lote. Se esta conta mudar, a matriz
    inteira deixa de bater com o que ele conhece."""
    js = wfa.montar_janelas(INICIO, FIM, is_m, oos_m)
    assert len([j for j in js if not j.deploy]) == esperado


def test_oos_sao_contiguos_e_nao_se_sobrepoem():
    """Passo = OOS. Sobrepor contaria o mesmo trade duas vezes na curva."""
    reais = [j for j in wfa.montar_janelas(INICIO, FIM, 12, 3) if not j.deploy]
    for a, b in zip(reais, reais[1:]):
        assert a.oos_ate == b.oos_de
    assert all(j.oos_de == j.is_ate for j in reais)


def test_ancorada_cresce_e_rolante_anda():
    rol = [j for j in wfa.montar_janelas(INICIO, FIM, 12, 6) if not j.deploy]
    anc = [j for j in wfa.montar_janelas(INICIO, FIM, 12, 6, ancorada=True)
           if not j.deploy]

    assert len(rol) == len(anc)
    assert len({j.is_de for j in rol}) == len(rol)      # o começo anda
    assert len({j.is_de for j in anc}) == 1             # o começo fica preso
    assert anc[-1].is_anos > anc[0].is_anos             # a janela cresce
    assert rol[-1].is_anos == pytest.approx(rol[0].is_anos)
    # e as duas testam exatamente os mesmos períodos OOS
    assert [j.oos_de for j in rol] == [j.oos_de for j in anc]


def test_janela_maior_que_a_base_nao_produz_passo():
    assert wfa.montar_janelas(INICIO, FIM, 120, 6) == []


def test_is_e_oos_precisam_de_pelo_menos_um_mes():
    with pytest.raises(ValueError):
        wfa.montar_janelas(INICIO, FIM, 0, 3)


# ------------------------------------------------------------ métricas
def test_metricas_de_uma_fatia_conhecida():
    liq = np.array([100.0, -50.0, 100.0, -50.0])
    dias = np.array(["2022-01-03"] * 4, dtype="datetime64[D]")
    m = wfa.metricas(liq, dias, CAP)

    assert m["trades"] == 4
    assert m["lucro"] == pytest.approx(100.0)
    assert m["pf"] == pytest.approx(2.0)
    assert m["dd"] == pytest.approx(50.0)      # cai 50 depois do primeiro topo
    assert m["fr"] == pytest.approx(2.0)


def test_fatia_vazia_nao_quebra():
    m = wfa.metricas(np.array([]), np.array([], dtype="datetime64[D]"), CAP)
    assert m["trades"] == 0 and m["lucro"] == 0.0
    assert m["ulcer"] == float("inf")          # não compete por "menor ulcer"


def test_drawdown_conta_o_mergulho_inicial():
    """Janela que abre perdendo: sem o capital como primeiro ponto, o
    drawdown seria zero até fazer o primeiro topo."""
    liq = np.array([-200.0, 300.0])
    dias = np.array(["2022-01-03"] * 2, dtype="datetime64[D]")
    assert wfa.metricas(liq, dias, CAP)["dd"] == pytest.approx(200.0)


# ---------------------------------------------------------------- WFE
def test_wfe_anualiza_os_dois_lados():
    """IS de 2 anos com 2.000 e OOS de 6 meses com 250: 500/ano contra
    1.000/ano = 50%."""
    assert wfa.wfe(2_000.0, 2.0, 250.0, 0.5) == pytest.approx(0.5)


def test_wfe_e_indefinido_quando_o_is_nao_lucrou():
    """Não é zero e não é infinito: a razão não existe. Dividir um OOS
    positivo por um IS negativo daria um número negativo que se leria como
    'péssimo' quando o fato é 'a otimização não achou nada para degradar'."""
    assert wfa.wfe(-500.0, 1.0, 300.0, 0.25) is None
    assert wfa.wfe(0.0, 1.0, 300.0, 0.25) is None


def test_wfe_acima_de_um_significa_que_o_oos_superou_o_is():
    assert wfa.wfe(1_000.0, 1.0, 500.0, 0.25) == pytest.approx(2.0)


# ------------------------------------------------- inteligências
def _cenario_plato():
    """Uma região com platô claro em periodo=50: os vizinhos rendem quase o
    mesmo, e há um pico isolado e mentiroso em periodo=90."""
    combos, mets = [], []
    for p in range(10, 101, 10):
        if p == 90:
            lucro, dd, sharpe, t, ulcer = 5_000.0, 2_000.0, 0.4, 1.1, 30.0
        elif 40 <= p <= 60:
            lucro, dd, sharpe, t, ulcer = 3_000.0, 500.0, 2.0, 4.0, 3.0
        else:
            lucro, dd, sharpe, t, ulcer = -200.0, 900.0, -0.2, -0.5, 20.0
        combos.append({"periodo": p})
        mets.append({"trades": 300, "lucro": lucro, "dd": dd, "pf": 1.4,
                     "fr": lucro / dd, "sharpe": sharpe, "t": t,
                     "ulcer": ulcer, "expectativa": lucro / 300})
    return list(range(len(combos))), combos, mets


@pytest.mark.parametrize("qual", [c for _, c in wfa.INTELIGENCIAS])
def test_toda_inteligencia_devolve_um_candidato_valido(qual):
    idx, params, mets = _cenario_plato()
    i, _ = wfa.escolher(qual, idx, params, mets)
    assert i in idx


@pytest.mark.parametrize("qual", ["moda", "centroide_media", "centroide_mediana"])
def test_as_de_plato_ficam_no_meio_da_regiao_boa(qual):
    """O pico isolado em 90 não pode atrair quem procura platô."""
    idx, params, mets = _cenario_plato()
    i, _ = wfa.escolher(qual, idx, params, mets)
    assert 40 <= params[i]["periodo"] <= 60


def test_sharpe_e_alpha_escolhem_pelo_criterio_proprio():
    idx, params, mets = _cenario_plato()
    i_s, _ = wfa.escolher("sharpe", idx, params, mets)
    i_a, _ = wfa.escolher("alpha", idx, params, mets)
    assert mets[i_s]["sharpe"] == max(m["sharpe"] for m in mets)
    assert mets[i_a]["t"] == max(m["t"] for m in mets)


def test_estabilidade_de_drawdown_pega_o_menor_ulcer():
    idx, params, mets = _cenario_plato()
    i, _ = wfa.escolher("ulcer", idx, params, mets)
    assert mets[i]["ulcer"] == min(m["ulcer"] for m in mets)


def test_conselho_converge_quando_a_regiao_e_plato():
    """Platô de verdade: as seis concordam e o placar mostra isso."""
    idx, params, mets = _cenario_plato()
    i, d = wfa.escolher("conselho", idx, params, mets)
    assert 40 <= params[i]["periodo"] <= 60
    assert d["votos"] >= 4 and d["votantes"] == len(wfa.VOTANTES)


def _conselho_com_votos(monkeypatch, votos_por_quem, fr):
    """Roda o Conselho com os votos DITADOS, para testar a regra de
    desempate sem depender de montar métricas que produzam aquele placar."""
    params = [{"periodo": p} for p in range(10, 80, 10)]      # 10..70
    mets = [{"trades": 300, "lucro": 100.0, "fr": fr.get(k, 1.0)}
            for k in range(len(params))]
    reais = wfa.escolher
    monkeypatch.setattr(wfa, "escolher",
                        lambda q, *a: (votos_por_quem[q], {}) if q in votos_por_quem
                        else reais(q, *a))
    return wfa._conselho(list(range(len(params))), params, mets), params


def test_conselho_empate_222_vai_para_a_mediana_dos_indicados(monkeypatch):
    """A documentação: empate → centroide mediano dos indicados. Antes, um
    2-2-2 era decidido pelo fator de recuperação — e o pico levava."""
    votos = dict(zip(wfa.VOTANTES, [0, 0, 1, 1, 6, 6, 1]))  # 10:2 · 20:3 · 70:2
    (i, d), params = _conselho_com_votos(monkeypatch, votos, fr={6: 9.0})
    assert params[i]["periodo"] == 20 and d["votos"] == 3   # maioria simples vence

    votos = dict(zip(wfa.VOTANTES, [0, 0, 1, 1, 6, 6, 3]))  # 10:2 · 20:2 · 70:2 · 40:1
    (i, d), params = _conselho_com_votos(monkeypatch, votos, fr={6: 9.0})
    # mediana de {10, 20, 40, 70} = 30 → a indicada mais próxima: 20 ou 40,
    # e NUNCA a de maior fr (70)
    assert params[i]["periodo"] in (20, 40)
    assert d["votos"] >= 1                                  # sempre alguém votou nela


def test_conselho_nunca_vence_sem_voto(monkeypatch):
    """A mediana de 10, 20, 30, 50, 60, 70, 40 cai perto de 40; ancorando
    entre os INDICADOS, o vencedor tem pelo menos um voto."""
    votos = dict(zip(wfa.VOTANTES, [0, 1, 2, 4, 5, 6, 3]))
    (i, d), _ = _conselho_com_votos(monkeypatch, votos, fr={})
    assert d["votos"] == 1 and d["por_quem"]


def test_ancoragem_normaliza_as_escalas():
    """Um stop de 320 pontos não pode dominar um desvio de 2,75 no cálculo de
    distância — sem normalizar, o centroide viraria 'a combinação com o stop
    mais parecido' e o outro parâmetro seria ignorado."""
    params = [{"stop": 100, "desvio": 3.0}, {"stop": 320, "desvio": 2.0},
              {"stop": 100, "desvio": 2.0}]
    mets = [{"fr": 1.0, "lucro": 1.0}] * 3
    i = wfa._ancorar({"stop": 100, "desvio": 2.0}, [0, 1, 2], params, mets)
    assert i == 2


def test_sem_candidato_aprovado_e_erro_de_quem_chama():
    with pytest.raises(ValueError):
        wfa.escolher("moda", [], [], [])


# ------------------------------------------------------------ critérios
def test_criterios_do_is_reprovam_e_aprovam():
    m = {"trades": 50, "lucro": 100.0, "pf": 1.1, "fr": 0.5, "dd": 3_000.0}
    assert wfa.passa_criterios(m, None)                      # sem limiar, passa
    assert not wfa.passa_criterios(m, {"trades": 300})
    assert not wfa.passa_criterios(m, {"dd": 2_500})         # dd é TETO
    assert wfa.passa_criterios(m, {"dd": 5_000, "pf": 1.0})


def test_valor_infinito_nao_reprova_por_falta_de_dado():
    """Fator de recuperação infinito é drawdown zero — a janela que nunca
    afundou. Reprová-la seria eliminar justamente a melhor."""
    m = {"trades": 300, "lucro": 100.0, "pf": float("inf"),
         "fr": float("inf"), "dd": 0.0}
    assert wfa.passa_criterios(m, {"fr": 2.0, "pf": 1.25})


# ---------------------------------------------------------------- rodar
def _dois_combos():
    """Um combo bom o tempo todo e um que só funciona no começo. Um WFA que
    presta tem que abandonar o segundo quando ele para de funcionar."""
    todos = meses("2021-03", "2026-03")
    bom = combo({"p": 10}, {m: 20.0 for m in todos})
    cedo = combo({"p": 20}, {m: (60.0 if m < "2023-03" else -30.0)
                             for m in todos})
    return [bom, cedo]


def test_o_wfa_troca_de_combinacao_quando_a_antiga_para_de_funcionar():
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(combos, js, CAP, "sharpe")

    escolhidas = [p.escolhida for p in passos if not p.janela.deploy]
    assert escolhidas[0] == 1        # no começo o "cedo" é melhor
    assert escolhidas[-1] == 0       # no fim já migrou para o "bom"


def test_deploy_nao_tem_oos_mas_tem_parametro():
    passos = wfa.rodar(_dois_combos(), wfa.montar_janelas(INICIO, FIM, 12, 6),
                       CAP, "sharpe")
    dep = passos[-1]
    assert dep.janela.deploy
    assert dep.params and dep.is_["trades"] > 0
    assert dep.oos == {} and dep.wfe_lucro is None


def test_nenhuma_aprovada_deixa_a_janela_fora_do_mercado():
    """Critério impossível: a estratégia não opera, e o WFA diz isso em vez
    de escolher a menos ruim."""
    passos = wfa.rodar(_dois_combos(), wfa.montar_janelas(INICIO, FIM, 12, 6),
                       CAP, "sharpe", criterios={"lucro": 10_000_000})
    assert all(p.fora_do_mercado for p in passos)
    assert all(p.escolhida is None for p in passos)


def test_poucos_trades_e_marcado_e_nao_pulado():
    passos = wfa.rodar(_dois_combos(), wfa.montar_janelas(INICIO, FIM, 6, 3),
                       CAP, "sharpe", min_trades_is=10_000)
    reais = [p for p in passos if not p.janela.deploy]
    assert all(p.poucos_trades for p in reais)
    assert all(p.escolhida is not None for p in reais)   # rodou assim mesmo


def test_curva_oos_nao_repete_nem_perde_trade():
    """A curva concatenada tem que conter exatamente os trades das janelas
    OOS — nem um a mais, nem um a menos."""
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(combos, js, CAP, "sharpe")
    ts, liq, step = wfa.trades_oos(combos, passos)

    assert len(ts) == len(liq) == len(step)
    assert list(ts) == sorted(ts)                  # em ordem de tempo
    esperado = sum(p.oos["trades"] for p in passos if not p.janela.deploy)
    assert len(ts) == esperado
    # e nenhum trade do DEPLOY entrou
    assert ts.max() < passos[-1].janela.oos_de


# -------------------------------------------------------------- agregar
def test_agregado_soma_antes_de_dividir():
    """O WFE global não é a média dos WFE: soma os OOS e soma os IS, e só
    então divide. Uma janela com IS minúsculo não desequilibra."""
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(combos, js, CAP, "sharpe")
    a = wfa.agregar(passos, CAP)

    reais = [p for p in passos if not p.janela.deploy]
    assert a["steps"] == len(reais)
    assert a["oos_lucro"] == pytest.approx(sum(p.oos["lucro"] for p in reais))
    assert 0 <= a["consistencia_lucro"] <= 100
    assert a["wfe_acima_50"] >= a["wfe_acima_70"] >= a["wfe_acima_90"]


def test_agregado_nao_usa_media_de_wfe():
    """Uma janela com WFE gigante não pode contaminar a leitura central."""
    combos = _dois_combos()
    passos = wfa.rodar(combos, wfa.montar_janelas(INICIO, FIM, 12, 6),
                       CAP, "sharpe")
    definidos = [p.wfe_lucro for p in passos if p.wfe_lucro is not None]
    a = wfa.agregar(passos, CAP)
    if definidos:
        assert a["wfe_mediana"] == pytest.approx(float(np.median(definidos)))


def test_lucro_por_mes_conta_os_meses_em_que_ficou_fora():
    """Se a estratégia ficou fora do mercado em metade das janelas, esses
    meses passaram do mesmo jeito. Dividir o lucro só pelos meses OPERADOS
    inflaria o resultado de quem quase não operou — o contrário do que a
    métrica deve dizer.
    """
    # o combo só tem trades na primeira metade do período
    todos = meses("2021-03", "2026-03")
    metade = todos[:len(todos) // 2]
    c = combo({"p": 1}, {m: 20.0 for m in metade})
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar([c], js, CAP, "sharpe", criterios={"trades": 1})
    a = wfa.agregar(passos, CAP)

    assert a["fora_do_mercado"] > 0
    assert a["oos_meses"] > a["oos_meses_operados"]
    # o denominador é o calendário inteiro, não só o operado
    assert a["lucro_mes_oos"] == pytest.approx(a["oos_lucro"] / a["oos_meses"])
    apenas_operado = a["oos_lucro"] / a["oos_meses_operados"]
    assert a["lucro_mes_oos"] < apenas_operado


def test_agregado_de_lista_vazia():
    assert wfa.agregar([], CAP) == {}


# ------------------------------------------------------------- matriz WFM
def test_matriz_devolve_uma_linha_por_configuracao():
    """As 12 configurações do operador, cada uma com o seu número de janelas.
    Se esta contagem mudar, a matriz deixa de bater com a referência dele."""
    linhas = wfa.matriz(_dois_combos(), INICIO, FIM, CAP)
    assert len(linhas) == len(wfa.CONFIGS)

    por_config = {l["config"]: l["steps"] for l in linhas}
    assert por_config["IS:6 / OOS:3"] == 18
    assert por_config["IS:24 / OOS:6"] == 6
    assert por_config["IS:18 / OOS:6"] == 7


def test_matriz_traz_rolante_e_ancorado_lado_a_lado():
    """A comparação entre os dois é o que diz se o edge é estrutural (o
    ancorado ganha) ou se o mercado mudou (o rolante ganha).

    Nota de quem escreveu: uma série de retorno mensal CONSTANTE não serve de
    caso aqui, e demorei a ver. Com taxa constante o desempenho anualizado do
    IS é o mesmo em janela de 12 ou de 36 meses, então rolante e ancorado
    coincidem — por matemática, não por bug. O caso que separa os dois é uma
    série cujo RITMO muda: aqui ela acelera ao longo do período, e a janela
    ancorada, que carrega os meses fracos do começo, mede um IS mais baixo
    que a rolante.
    """
    todos = meses("2021-03", "2026-03")
    acelera = combo({"p": 1}, {m: 5.0 + 2.0 * i for i, m in enumerate(todos)})
    linhas = wfa.matriz([acelera], INICIO, FIM, CAP, criterios={"trades": 1})

    assert all("wfe" in l and "wfe_ancorado" in l for l in linhas)
    assert any(l["wfe"] != l["wfe_ancorado"] for l in linhas)
    # e o ancorado mede um IS mais fraco (carrega o começo lento), o que faz
    # o MESMO OOS parecer mais eficiente contra ele
    piores = [l for l in linhas if l["wfe"] is not None
              and l["wfe_ancorado"] is not None]
    assert any(l["wfe_ancorado"] > l["wfe"] for l in piores)


def test_matriz_ordena_os_cortes_de_wfe():
    linhas = wfa.matriz(_dois_combos(), INICIO, FIM, CAP)
    for l in linhas:
        assert l["a50"] >= l["a70"] >= l["a90"]
        assert 0 <= l["consistencia"] <= 100


def test_matriz_aceita_configuracoes_proprias():
    linhas = wfa.matriz(_dois_combos(), INICIO, FIM, CAP,
                        configs=[(12, 6), (24, 6)])
    assert [l["config"] for l in linhas] == ["IS:12 / OOS:6", "IS:24 / OOS:6"]


def test_matriz_descarta_configuracao_que_nao_cabe():
    """IS de 120 meses numa base de 60 não produz janela nenhuma — a linha
    simplesmente não existe, em vez de aparecer zerada e enganar."""
    linhas = wfa.matriz(_dois_combos(), INICIO, FIM, CAP,
                        configs=[(120, 6), (12, 6)])
    assert [l["config"] for l in linhas] == ["IS:12 / OOS:6"]


def test_matriz_sem_cache():
    assert wfa.matriz([], INICIO, FIM, CAP) == []


# --------------------------------------------------------------- drift
def test_drift_separa_parametro_estavel_de_instavel():
    """Dois parâmetros no mesmo conjunto de janelas: um que quase não sai do
    lugar e outro que pula de um extremo ao outro. O primeiro é edge com
    endereço; o segundo é o otimizador perseguindo ruído."""
    passos = []
    for k, (est, inst) in enumerate([(100, 10), (101, 90), (99, 15), (100, 80)]):
        j = wfa.Janela(k + 1, np.datetime64("2021-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-09-01", "s"))
        passos.append(wfa.Passo(janela=j, escolhida=0,
                                params={"estavel": est, "instavel": inst}))

    d = {i["nome"]: i for i in wfa.drift(passos)}
    assert d["estavel"]["estado"] == "estável"
    assert d["instavel"]["estado"] == "instável"
    assert d["instavel"]["volatilidade"] > d["estavel"]["volatilidade"]
    assert d["estavel"]["trocas"] == 3 and d["estavel"]["janelas"] == 4


def test_parametro_de_valor_unico_e_marcado_como_fixo():
    """A mineração varreu um valor só: a reta plana não diz nada e não deve
    ganhar gráfico."""
    passos = []
    for k in range(3):
        j = wfa.Janela(k + 1, np.datetime64("2021-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-09-01", "s"))
        passos.append(wfa.Passo(janela=j, escolhida=0, params={"folga": 9}))
    assert wfa.drift(passos)[0]["fixo"] is True


def test_drift_precisa_de_pelo_menos_duas_janelas():
    assert wfa.drift([]) == []


# -------------------------------------------------------------- portões
def _passos_bons():
    """Um walk-forward que passa em tudo, de propósito.

    Nota de quem escreveu: `_dois_combos()` NÃO serve aqui. Nele o edge
    migra de uma combinação para a outra, e o WFA — mesmo funcionando — sai
    com WFE de 50,9%, abaixo do piso de 70% que o operador fixou. Ou seja,
    'reprovado' seria a resposta certa, e o teste estaria medindo outra coisa.
    Para exercitar a aprovação é preciso uma série cujo desempenho fora da
    amostra IGUALE o de dentro: retorno constante dá WFE de exatamente 100%.
    """
    todos = meses("2021-03", "2026-03")
    combos = [combo({"p": 1}, {m: 20.0 for m in todos})]
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(combos, js, CAP, "sharpe")
    _, liq, _ = wfa.trades_oos(combos, passos)
    return passos, wfa.agregar(passos, CAP, liq)


def test_portoes_aprovam_um_wfa_saudavel():
    passos, ag = _passos_bons()
    ver = wfa.portoes_wfa(ag, passos, CAP)
    assert ver["estado"] in ("aprovado", "aprovado com ressalva")
    assert not ver["reprovados"]


def test_lucro_oos_negativo_reprova():
    """O portão mais duro: se o processo de escolher não lucra fora da
    amostra, trocar de combinação não resolve — foi escolhendo que se chegou
    ali."""
    passos, ag = _passos_bons()
    ag = {**ag, "oos_lucro": -1_000.0}
    ver = wfa.portoes_wfa(ag, passos, CAP)
    assert ver["estado"] == "reprovado"
    assert "lucro OOS total" in [p["nome"] for p in ver["reprovados"]]


def test_wfe_abaixo_do_piso_reprova():
    passos, ag = _passos_bons()
    ver = wfa.portoes_wfa({**ag, "wfe_global": 0.4}, passos, CAP)
    assert "WFE global" in [p["nome"] for p in ver["reprovados"]]
    # e o piso é configurável: com 30% o mesmo número passa
    solto = wfa.portoes_wfa({**ag, "wfe_global": 0.4}, passos, CAP,
                            lim={"min_wfe": 0.30})
    assert "WFE global" not in [p["nome"] for p in solto["reprovados"]]


def test_wfe_indefinido_nao_passa_no_portao():
    """WFE None é 'não deu para medir', e não 'está ótimo'."""
    passos, ag = _passos_bons()
    ver = wfa.portoes_wfa({**ag, "wfe_global": None}, passos, CAP)
    assert "WFE global" in [p["nome"] for p in ver["reprovados"]]


def test_drawdown_fora_de_escala_e_ressalva_e_nao_reprova():
    """Drawdown OOS muito maior que o da otimização é aviso sério, mas não
    barra: pode ser o período, e o operador decide."""
    passos, ag = _passos_bons()
    passos[0].is_["dd"] = 100.0        # a otimização viu um mergulho pequeno
    ver = wfa.portoes_wfa({**ag, "dd_oos": 900.0}, passos, CAP)

    assert ver["dd_razao"] == pytest.approx(9.0)
    assert "drawdown OOS ÷ IS" in [p["nome"] for p in ver["ressalvas"]]
    assert not ver["reprovados"]       # é alerta, não portão crítico


def test_sem_drawdown_no_is_a_razao_nao_existe():
    """Dividir por zero daria infinito, que se leria como 'péssimo' quando o
    fato é 'a otimização nunca afundou'. O portão passa, e o valor fica
    vazio."""
    passos, ag = _passos_bons()
    ver = wfa.portoes_wfa({**ag, "dd_oos": 900.0}, passos, CAP)

    assert ver["dd_is"] == 0.0 and ver["dd_razao"] is None
    portao = next(p for p in ver["portoes"] if "drawdown" in p["nome"])
    assert portao["ok"] and portao["valor"] is None


def test_todo_portao_do_wfa_tem_dica():
    passos, ag = _passos_bons()
    for p in wfa.portoes_wfa(ag, passos, CAP)["portoes"]:
        assert p["dica"] and len(p["dica"]) > 80


def test_portoes_sem_agregado():
    assert wfa.portoes_wfa({}, [], CAP) == {}


# ------------------------------------ faixa das combinações fixas (contrafactual)
def test_faixa_fixas_cobre_o_intervalo_do_walk_forward_e_ordena_os_quantis():
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    f = wfa.faixa_fixas(combos, js, CAP)
    reais = [j for j in js if not j.deploy]

    assert f["dias"][0] >= np.datetime64(reais[0].oos_de, "D")
    assert f["dias"][-1] < np.datetime64(reais[-1].oos_ate, "D")
    q = f["quantis"]
    assert np.all(q[10] <= q[25]) and np.all(q[25] <= q[50])
    assert np.all(q[50] <= q[75]) and np.all(q[75] <= q[90])
    assert f["n"] == 2 and len(f["finais"]) == 2


def test_faixa_fixas_final_bate_com_o_lucro_de_cada_combinacao():
    """O último ponto de cada curva fixa é a soma dos trades dela no
    intervalo — a faixa não inventa nada."""
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    reais = [j for j in js if not j.deploy]
    f = wfa.faixa_fixas(combos, js, CAP)
    for c, final in zip(combos, f["finais"]):
        m = (c["entry_ts"] >= reais[0].oos_de) & (c["entry_ts"] < reais[-1].oos_ate)
        assert final == pytest.approx(c["liquido"][m].sum())


def test_percentil_do_wfa_na_faixa():
    faixa = {"finais": np.array([100.0, 200.0, 300.0, 400.0])}
    assert wfa.percentil_na_faixa(faixa, 250.0) == pytest.approx(50.0)
    assert wfa.percentil_na_faixa(faixa, 50.0) == 0.0
    assert wfa.percentil_na_faixa({}, 10.0) is None


# ---------------------------------------------------- semestres positivos
def _passos_janelas(meses_oos, fora=()):
    """Janelas OOS de 3 meses a partir de cada mês dado (AAAA-MM)."""
    passos = []
    for k, m in enumerate(meses_oos, start=1):
        ini = np.datetime64(m, "M")
        j = wfa.Janela(k, (ini - np.timedelta64(6, "M")).astype("datetime64[s]"),
                       ini.astype("datetime64[s]"), ini.astype("datetime64[s]"),
                       (ini + np.timedelta64(3, "M")).astype("datetime64[s]"))
        passos.append(wfa.Passo(janela=j, escolhida=None if m in fora else 0,
                                params={} if m in fora else {"p": 1},
                                fora_do_mercado=m in fora))
    return passos


def test_semestres_so_contam_os_inteiros_e_somam_os_trades():
    # OOS de 2022-03 a 2023-03: jan-jun/2022 é parcial (fica de fora);
    # jul-dez/2022 é inteiro
    passos = _passos_janelas(["2022-03", "2022-06", "2022-09", "2022-12"])
    ts = np.array(["2022-07-10", "2022-10-10", "2022-12-10"], dtype="datetime64[s]")
    liq = np.array([100.0, -50.0, -60.0])              # jul-dez/2022 soma −10
    s = wfa.semestres_oos(passos, ts, liq)
    assert s["n"] == 1 and s["positivos"] == 0 and s["pct"] == 0.0


def test_janela_curta_negativa_nao_derruba_o_semestre_positivo():
    """O problema que os semestres resolvem: duas janelas de 3 meses, uma
    positiva e outra negativa por acaso, dão 50% por janela — e o semestre
    inteiro lucrou."""
    passos = _passos_janelas(["2022-07", "2022-10"])
    ts = np.array(["2022-08-10", "2022-11-10"], dtype="datetime64[s]")
    liq = np.array([300.0, -40.0])
    s = wfa.semestres_oos(passos, ts, liq)
    assert s["pct"] == 100.0


def test_semestre_todo_fora_do_mercado_nao_conta_contra():
    passos = _passos_janelas(["2022-07", "2022-10", "2023-01", "2023-04"],
                             fora=("2023-01", "2023-04"))
    ts = np.array(["2022-08-10"], dtype="datetime64[s]")
    s = wfa.semestres_oos(passos, ts, np.array([100.0]))
    assert s["n"] == 1 and s["pct"] == 100.0 and s["fora"] == 1


def test_portao_usa_semestres_quando_existem():
    passos = _passos_janelas(["2022-07", "2022-10"])
    ag = wfa.agregar(passos, CAP, np.array([300.0, -40.0]),
                     np.array(["2022-08-10", "2022-11-10"], dtype="datetime64[s]"))
    ag.update(oos_lucro=260.0, consistencia_lucro=50.0, wfe_global=1.0,
              oos_trades=500)
    ver = wfa.portoes_wfa(ag, passos, CAP)
    p = next(x for x in ver["portoes"] if "positiv" in x["nome"])
    assert p["nome"] == "semestres OOS positivos" and p["ok"]


def test_matriz_traz_lucro_mes_no_periodo_comum():
    """As duas configurações medidas a partir da MESMA data: a do OOS que
    começa mais tarde (IS24/OOS6 → 2023-03), recalculado à mão."""
    combos = _dois_combos()
    configs = [(6, 3), (24, 6)]
    linhas = wfa.matriz(combos, INICIO, FIM, CAP, "sharpe", configs=configs)
    comum = max(wfa.montar_janelas(INICIO, FIM, a, b)[0].oos_de for a, b in configs)
    assert str(comum)[:7] == "2023-03"
    for (a, b), r in zip(configs, linhas):
        js = [j for j in wfa.montar_janelas(INICIO, FIM, a, b) if not j.deploy]
        ts, liq, _ = wfa.trades_oos(combos, wfa.rodar(combos, js, CAP, "sharpe"))
        meses = int((np.datetime64(js[-1].oos_ate, "M") - np.datetime64(comum, "M")).astype(int))
        assert r["lucro_mes_comum"] == pytest.approx(liq[ts >= comum].sum() / meses)
    # e o lucro/mês próprio da IS6/OOS3, que começa em 2021, é outro número
    assert linhas[0]["lucro_mes"] != pytest.approx(linhas[0]["lucro_mes_comum"])


# ------------------------------------------------- drawdown da curva OOS
def test_agregado_mede_o_drawdown_da_curva_inteira():
    """O mergulho da curva CONCATENADA, e não a soma dos mergulhos por
    janela: é a curva inteira que se opera, não os pedaços."""
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(combos, js, CAP, "sharpe")
    _, liq, _ = wfa.trades_oos(combos, passos)

    sem = wfa.agregar(passos, CAP)
    com = wfa.agregar(passos, CAP, liq)
    assert sem["dd_oos"] == 0.0            # sem a curva, não há o que medir
    assert com["dd_oos"] >= 0.0

    eq = np.concatenate(([CAP], CAP + np.cumsum(liq)))
    manual = float((np.maximum.accumulate(eq) - eq).max())
    assert com["dd_oos"] == pytest.approx(manual)


# ------------------------------------------------- eficiência temporal
def test_mensal_conta_meses_e_separa_bons_de_ruins():
    entradas, liq = [], []
    #  jan+  fev-  mar-  abr+  mai+
    for mes, v in zip(range(1, 6), [300.0, -100.0, -200.0, 400.0, 100.0]):
        entradas.append(np.datetime64(f"2023-{mes:02d}-10T10:00", "s"))
        liq.append(v)
    m = wfa.mensal(np.array(entradas), np.array(liq))

    assert m["meses"] == 5
    assert m["positivos"] == 3 and m["negativos"] == 2
    assert m["pct_positivos"] == pytest.approx(60.0)
    assert m["media_lucro"] == pytest.approx((300 + 400 + 100) / 3)
    assert m["media_prejuizo"] == pytest.approx(-150.0)
    assert m["melhor"] == pytest.approx(400.0)
    assert m["pior"] == pytest.approx(-200.0)


def test_mensal_soma_os_trades_do_mesmo_mes():
    """Três trades em janeiro contam como UM mês, com o saldo somado."""
    ts = np.array([np.datetime64("2023-01-05T10:00", "s"),
                   np.datetime64("2023-01-18T10:00", "s"),
                   np.datetime64("2023-01-29T10:00", "s")])
    m = wfa.mensal(ts, np.array([100.0, -30.0, 50.0]))
    assert m["meses"] == 1 and m["valores"] == [pytest.approx(120.0)]


def test_tempo_submerso_e_medido_em_meses():
    """Sobe, afunda por três meses, volta ao topo. O episódio dura 3 meses —
    é a métrica que decide se você continua operando ou desliga o robô."""
    vals = [500.0, -200.0, -100.0, 50.0, 400.0]
    ts = np.array([np.datetime64(f"2023-{k:02d}-10T10:00", "s")
                   for k in range(1, 6)])
    m = wfa.mensal(ts, np.array(vals))

    # acumulado: 500, 300, 200, 250, 650 -> submerso nos meses 2, 3 e 4
    assert m["maior_sub_topo"] == 3
    assert m["n_episodios"] == 1
    assert m["tempo_medio_recuperacao"] == pytest.approx(3.0)


def test_curva_que_so_sobe_nao_fica_submersa():
    ts = np.array([np.datetime64(f"2023-{k:02d}-10T10:00", "s")
                   for k in range(1, 5)])
    m = wfa.mensal(ts, np.array([100.0, 100.0, 100.0, 100.0]))
    assert m["maior_sub_topo"] == 0 and m["n_episodios"] == 0
    assert m["fator_recuperacao"] is None      # sem mergulho, a razão não existe


def test_mensal_vazio():
    assert wfa.mensal(np.array([], dtype="datetime64[s]"), np.array([])) == {}


# ------------------------------------------- matrizes de todas + consenso
def test_matrizes_compartilhadas_dao_o_mesmo_que_uma_por_vez():
    """As métricas das janelas são calculadas uma vez e divididas entre as
    inteligências. Isso só pode mudar o TEMPO, nunca um número."""
    combos = _dois_combos()
    qs = ["sharpe", "ulcer", "conselho"]
    juntas = wfa.matrizes(combos, INICIO, FIM, CAP, qs, configs=[(12, 6), (6, 3)])
    for q in qs:
        sozinha = wfa.matriz(combos, INICIO, FIM, CAP, q, configs=[(12, 6), (6, 3)])
        assert juntas[q] == sozinha


def test_rodar_com_preparo_igual_a_rodar_sem():
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    prep = wfa.preparar(combos, js, CAP)
    a = wfa.rodar(combos, js, CAP, "moda")
    b = wfa.rodar(combos, js, CAP, "moda", preparado=prep)
    assert [(p.escolhida, p.oos) for p in a] == [(p.escolhida, p.oos) for p in b]


def test_linha_da_matriz_traz_o_veredito_dos_seis_portoes():
    linhas = wfa.matriz(_dois_combos(), INICIO, FIM, CAP, "sharpe", configs=[(12, 6)])
    assert linhas[0]["n_portoes"] == 6
    assert linhas[0]["estado"] in ("aprovado", "aprovado com ressalva", "reprovado")


def _linha(config, wfe, estado):
    is_m, oos_m = (int(x.split(":")[1]) for x in config.split(" / "))
    return {"config": config, "is_meses": is_m, "oos_meses": oos_m,
            "wfe": wfe, "estado": estado}


def test_consenso_ordena_por_aprovacoes_depois_mediana_depois_piso():
    """A é aprovada por todas com WFE modesto; B tem o MAIOR WFE da tabela
    mas só uma aprova. Consenso vem antes do pico."""
    vs = ["q1", "q2", "q3"]
    por_q = {
        "q1": [_linha("IS:12 / OOS:6", 0.80, "aprovado"),
               _linha("IS:6 / OOS:3", 1.90, "aprovado"),
               _linha("IS:9 / OOS:3", 0.95, "aprovado")],
        "q2": [_linha("IS:12 / OOS:6", 0.85, "aprovado com ressalva"),
               _linha("IS:6 / OOS:3", 0.40, "reprovado"),
               _linha("IS:9 / OOS:3", 0.90, "aprovado")],
        "q3": [_linha("IS:12 / OOS:6", 0.90, "aprovado"),
               _linha("IS:6 / OOS:3", 0.30, "reprovado"),
               _linha("IS:9 / OOS:3", 0.60, "aprovado")],
    }
    c = wfa.consenso(por_q, votantes=vs)
    ordem = [r["config"] for r in c]
    # IS:9/OOS:3 e IS:12/OOS:6 empatam em 3 aprovações; desempata a mediana
    # (0,90 × 0,85)
    assert ordem == ["IS:9 / OOS:3", "IS:12 / OOS:6", "IS:6 / OOS:3"]
    assert c[0]["recomendada"] and c[0]["aprovam"] == 3
    assert c[2]["melhor_wfe"] == pytest.approx(1.90)   # o pico fica, como informação
    assert c[1]["pior_wfe"] == pytest.approx(0.80)


def test_consenso_desempata_pelo_pior_caso():
    vs = ["q1", "q2", "q3"]
    por_q = {q: [] for q in vs}
    for q, a, b in zip(vs, (0.7, 0.8, 0.9), (0.5, 0.8, 1.1)):
        por_q[q] += [_linha("IS:12 / OOS:6", a, "aprovado"),
                     _linha("IS:6 / OOS:3", b, "aprovado")]
    c = wfa.consenso(por_q, votantes=vs)
    # mesma contagem, mesma mediana (0,8): vence o piso mais alto (0,7 > 0,5)
    assert [r["config"] for r in c] == ["IS:12 / OOS:6", "IS:6 / OOS:3"]


def test_conselho_nao_conta_no_consenso():
    """O Conselho é a votação das outras seis: contá-lo seria votar duas vezes."""
    assert "conselho" not in wfa.VOTANTES and len(wfa.VOTANTES) == 7
    por_q = {"conselho": [_linha("IS:12 / OOS:6", 1.0, "aprovado")]}
    c = wfa.consenso(por_q)
    assert c == []


def test_ninguem_aprova_nao_ha_recomendada():
    por_q = {"q1": [_linha("IS:12 / OOS:6", 0.3, "reprovado")]}
    c = wfa.consenso(por_q, votantes=["q1"])
    assert c[0]["aprovam"] == 0 and not c[0]["recomendada"] and not c[0]["top"]


# ------------------------------------------ regressões da revisão das inteligências
def _m(trades=300, lucro=1000.0, fr=2.0, sharpe=1.0, t=2.0, ulcer=1.0, dd=500.0, pf=1.3):
    return {"trades": trades, "lucro": lucro, "fr": fr, "sharpe": sharpe,
            "t": t, "ulcer": ulcer, "dd": dd, "pf": pf, "expectativa": lucro / max(trades, 1)}


def test_desvio_zero_nao_vira_estatistica_t_infinita():
    """Dois trades de +50: antes t = inf e a combinação vencia o Alpha."""
    m = wfa.metricas(np.array([50.0, 50.0]),
                     np.array(["2024-03-04", "2024-03-05"], dtype="datetime64[D]"), CAP)
    assert m["t"] == 0.0


def test_combinacao_de_poucos_trades_nao_e_candidata():
    """O piso de 30 trades vem antes de qualquer inteligência."""
    j = wfa.montar_janelas("2021-01-01", "2026-01-01", 12, 6)[0]
    crit = wfa.criterios_por_janela({}, 60)(j)
    assert crit["trades"] == wfa.MIN_TRADES_JANELA
    assert not wfa.passa_criterios(_m(trades=2, lucro=100.0, fr=float("inf")), crit)
    assert wfa.passa_criterios(_m(trades=40), crit)


def test_criterios_escalam_com_o_tamanho_da_janela():
    """300 trades em 60 meses viram 60 numa janela de 12; FR × f^0,7 e DD × f^0,3."""
    j = wfa.montar_janelas("2021-01-01", "2026-01-01", 12, 6)[0]
    c = wfa.criterios_por_janela({"trades": 300, "pf": 1.25, "fr": 2.0,
                                  "dd": 2500, "lucro": 1000}, 60)(j)
    assert c["trades"] == 60
    assert c["lucro"] == pytest.approx(200.0)
    assert c["fr"] == pytest.approx(2.0 * (12 / 60) ** 0.7)
    assert c["dd"] == pytest.approx(2500 * (12 / 60) ** 0.3)
    assert c["pf"] == 1.25
    # coerência: FR ÷ lucro-por-DD — o FR escalado é o lucro escalado sobre o
    # DD escalado
    assert c["fr"] == pytest.approx(2.0 * (12 / 60) / (12 / 60) ** 0.3)
    # na ancorada o IS cresce, e o critério cresce junto
    anc = wfa.montar_janelas("2021-01-01", "2026-01-01", 12, 6, ancorada=True)
    assert (wfa.criterios_por_janela({"trades": 300}, 60)(anc[3])["trades"]
            > wfa.criterios_por_janela({"trades": 300}, 60)(anc[0])["trades"])


def test_ancoragem_nao_cai_numa_perdedora_fora_do_decil():
    """O cenário da revisão: o centro do decil caía em cima de uma combinação
    de −R$ 5.000 que estava no meio da grade."""
    params = [{"a": a} for a in range(1, 21)]
    mets = [_m(lucro=-5000.0, fr=-1.0) for _ in range(20)]
    for a in (1, 2, 3):
        mets[a - 1] = _m(lucro=3000.0, fr=3.0)
    mets[19] = _m(lucro=3100.0, fr=3.2)                    # uma boa isolada na ponta
    idx = list(range(20))
    for q in ("moda", "centroide_media", "centroide_mediana", "conselho"):
        i, _ = wfa.escolher(q, idx, params, mets)
        assert mets[i]["lucro"] > 0, q


def test_empate_de_ulcer_desempata_pelo_lucro():
    mets = [_m(lucro=2.0, ulcer=0.0), _m(lucro=301_500.0, ulcer=0.0)]
    i, _ = wfa.escolher("ulcer", [0, 1], [{"a": 1}, {"a": 2}], mets)
    assert i == 1


def test_decil_nunca_tem_menos_que_tres():
    """Com 4 candidatos o decil tinha 1 elemento e as de platô viravam pico."""
    mets = [_m(fr=f) for f in (1.0, 5.0, 4.0, 4.5)]
    assert len(wfa._topo([0, 1, 2, 3], mets)) == 3


def test_fr_infinito_nao_atropela_o_decil():
    """Drawdown zero: continua entre as melhores, mas não passa por cima de
    uma com fr igual e muito mais lucro."""
    mets = [_m(fr=float("inf"), lucro=10.0), _m(fr=5.0, lucro=9000.0), _m(fr=1.0)]
    topo = wfa._topo([0, 1, 2], mets)
    assert topo[0] == 1


def test_sharpe_conta_os_pregoes_sem_trade():
    """4 trades num ano: só nos dias operados o Sharpe sai absurdo; com os
    pregões parados entrando como zero, vira um número de verdade. A conta
    sem materializar os zeros tem que bater com a conta ingênua que os
    materializa."""
    liq = np.array([100.0, 120.0, 90.0, 110.0])
    dias = np.array(["2024-01-10", "2024-04-10", "2024-07-10", "2024-10-10"],
                    dtype="datetime64[D]")
    so_operados = wfa.metricas(liq, dias, CAP)["sharpe"]
    com_parados = wfa.metricas(liq, dias, CAP, n_pregoes=252)["sharpe"]

    serie = np.zeros(252)
    serie[:4] = liq / CAP
    ingenuo = serie.mean() / serie.std(ddof=1) * np.sqrt(252)
    assert com_parados == pytest.approx(ingenuo)
    assert com_parados == pytest.approx(2.0, abs=0.01)
    assert so_operados > 10 * com_parados


# ------------------------------------------------------- Platô Pessimista
def _grade_2d(f):
    params, mets = [], []
    for p in range(10, 101, 5):              # 19 valores → raio 1
        for s in range(100, 1001, 50):       # 19 valores → raio 1
            params.append({"periodo": p, "stop": s})
            mets.append(_m(fr=f(p, s)))
    return params, mets


def test_plato_pessimista_prefere_platô_a_pico_isolado():
    """Um pico de fr 9 cercado de prejuízo contra um platô de fr 3 largo."""
    def f(p, s):
        if (p, s) == (90, 900):
            return 9.0
        if 30 <= p <= 50 and 300 <= s <= 500:
            return 3.0
        return -1.0
    params, mets = _grade_2d(f)
    idx = list(range(len(params)))
    i, d = wfa.escolher("vizinhanca", idx, params, mets)
    assert 35 <= params[i]["periodo"] <= 45 and 350 <= params[i]["stop"] <= 450
    assert d["plato"] and d["nota"] == pytest.approx(3.0)
    # o pico isolado é o que Sharpe/Alpha ou um fr puro escolheriam
    assert max(idx, key=lambda k: mets[k]["fr"]) != i


def test_plato_pessimista_nao_cai_no_vale_entre_duas_ilhas():
    """Duas ilhas boas nas pontas: a Centroide Mediana cai no meio (ruim);
    o Platô Pessimista fica dentro de uma ilha."""
    def f(p, s):
        if p <= 25 and s <= 250:
            return 3.0
        if p >= 85 and s >= 850:
            return 3.0
        return -1.0
    params, mets = _grade_2d(f)
    idx = list(range(len(params)))
    i, _ = wfa.escolher("vizinhanca", idx, params, mets)
    assert mets[i]["fr"] == 3.0


def test_plato_pessimista_usa_vizinho_reprovado_como_penhasco():
    """O vizinho que não passou nos critérios não é candidato, mas conta na
    nota: é justamente o penhasco."""
    params = [{"p": p} for p in range(1, 42)]           # 41 valores → raio 2
    mets = [_m(fr=3.0) for _ in params]
    for k in (18, 19, 21, 22):                           # em volta de p=21
        mets[k - 1] = _m(fr=-5.0)
    mets[20] = _m(fr=3.5)                                # p=21: o melhor sozinho
    aprovadas = [k for k in range(41) if k not in (17, 18, 20, 21)]
    i, _ = wfa.escolher("vizinhanca", aprovadas, params, mets)
    assert params[i]["p"] != 21


def test_plato_pessimista_parametro_de_texto_so_compara_iguais():
    params = [{"p": p, "lado": lado} for lado in ("compra", "venda") for p in range(1, 21)]
    mets = [_m(fr=(3.0 if x["lado"] == "venda" else -1.0)) for x in params]
    mets[5] = _m(fr=9.0)                                 # compra, p=6: pico no lado ruim
    i, _ = wfa.escolher("vizinhanca", list(range(len(params))), params, mets)
    assert params[i]["lado"] == "venda"


def test_plato_pessimista_sem_parametro_numerico_cai_na_centroide():
    params = [{"lado": "compra"}, {"lado": "venda"}, {"lado": "ambos"}]
    mets = [_m(fr=1.0), _m(fr=2.0), _m(fr=3.0)]
    i, d = wfa.escolher("vizinhanca", [0, 1, 2], params, mets)
    assert d == {"plato": False} and i in (0, 1, 2)


def test_plato_pessimista_vota_no_conselho_e_conta_no_consenso():
    assert "vizinhanca" in wfa.VOTANTES


# ------------------------------------------------ regressões da revisão geral
def test_t_de_trades_identicos_nao_explode_com_ruido_de_arredondamento():
    """35 × R$ 36,56 dá desvio de 7e-15, não zero exato: o t saía 3e16 e o
    Alpha escolhia essa combinação."""
    liq = np.full(35, 36.56)
    dias = (np.datetime64("2024-01-01", "D") + np.arange(35)).astype("datetime64[D]")
    assert liq.std(ddof=1) > 0                      # o ruído existe mesmo
    assert wfa.metricas(liq, dias, CAP, 252)["t"] == 0.0
    assert wfa.sharpe_diario(np.full(20, 0.0036561), 20) == 0.0


def test_escadinha_alinhada_pelo_fim_o_deploy_usa_os_ultimos_meses():
    """Base até setembro, IS10/OOS5: o DEPLOY terminava em maio."""
    js = wfa.montar_janelas("2021-03-16", "2025-09-14", 10, 5)
    assert str(js[-1].is_ate)[:7] == "2025-09"
    assert str(js[-2].oos_ate)[:7] == "2025-09"
    # sem sobra, nada muda (é o caso de referência do operador)
    ref = wfa.montar_janelas(INICIO, FIM, 18, 6)
    assert str(ref[0].is_de)[:7] == "2021-03"


def test_escadinha_ancorada_tambem_termina_no_fim():
    js = wfa.montar_janelas("2021-03-16", "2025-09-14", 10, 5, ancorada=True)
    assert str(js[0].is_de)[:7] == "2021-03"
    assert str(js[-1].is_ate)[:7] == "2025-09"


def test_mensal_conta_os_meses_sem_trade_e_comeca_no_zero():
    ts = np.array(["2024-01-10", "2024-04-10"], dtype="datetime64[s]")
    cal = np.arange(np.datetime64("2024-01", "M"), np.datetime64("2024-05", "M"))
    m = wfa.mensal(ts, np.array([-100.0, 300.0]), cal)
    assert m["meses"] == 4                          # jan, fev, mar, abr
    assert m["pct_positivos"] == pytest.approx(25.0)
    # jan negativo já é mergulho (a curva começa no zero) e dura até abril
    assert m["maior_sub_topo"] == 3 and m["sub_topo_em_curso"] == 0


def test_mensal_mergulho_em_curso_nao_entra_na_media_de_recuperacao():
    ts = np.array(["2024-01-10", "2024-02-10", "2024-03-10", "2024-04-10"],
                  dtype="datetime64[s]")
    m = wfa.mensal(ts, np.array([100.0, -50.0, 80.0, -300.0]))
    assert m["tempo_medio_recuperacao"] == pytest.approx(1.0)   # fev, recuperado em mar
    assert m["sub_topo_em_curso"] == 1 and m["maior_sub_topo"] == 1


def test_drift_mede_contra_a_faixa_minerada():
    """O caso da #40: periodo_canal passeou de 46 a 75 numa faixa 40→80.
    Pela média (16%) saía "em transição"; pela faixa, 24%, instável."""
    js = wfa.montar_janelas(INICIO, FIM, 6, 3)
    vals = [75, 63, 60, 60, 58, 46, 46, 64]
    passos = [wfa.Passo(janela=j, escolhida=0, params={"periodo_canal": v})
              for j, v in zip(js, vals)]
    it = wfa.drift(passos, {"periodo_canal": list(range(40, 81))})[0]
    assert it["referencia"] == "faixa" and it["estado"] == "instável"
    assert it["percurso"] == pytest.approx((75 - 46) / 40)
    sem_espaco = wfa.drift(passos)[0]
    assert sem_espaco["referencia"] == "media" and sem_espaco["estado"] == "em transição"


def test_drift_nao_depende_de_onde_fica_o_zero():
    """O mesmo passeio, numa escala deslocada em 1.000, tem o mesmo veredito."""
    js = wfa.montar_janelas(INICIO, FIM, 6, 3)
    vals = [2, 9, 4, 8, 1, 10]
    perto = [wfa.Passo(janela=j, escolhida=0, params={"x": v}) for j, v in zip(js, vals)]
    longe = [wfa.Passo(janela=j, escolhida=0, params={"x": v + 1000}) for j, v in zip(js, vals)]
    a = wfa.drift(perto, {"x": list(range(0, 11))})[0]
    b = wfa.drift(longe, {"x": list(range(1000, 1011))})[0]
    assert a["estado"] == b["estado"] and a["volatilidade"] == pytest.approx(b["volatilidade"])


def test_drift_ignora_parametro_de_texto_e_media_zero_nao_e_estavel():
    janela = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = [wfa.Passo(janela=j, escolhida=0,
                        params={"lado": "long", "breakeven": b, "p": 10})
              for j, b in zip(janela[:4], (0, 20, -20, 0))]
    itens = {i["nome"]: i for i in wfa.drift(passos)}
    assert "lado" not in itens
    assert itens["breakeven"]["estado"] != "estável"


def test_plato_por_endereco_e_por_comparacao_em_bloco_dao_o_mesmo():
    """A busca de vizinhos por endereço é uma otimização: não pode mudar a
    escolha nem a nota em relação à comparação contra a grade inteira."""
    rng = np.random.default_rng(3)
    params = [{"p": p, "s": s, "lado": l} for p in range(10, 60, 5)
              for s in range(100, 600, 50) for l in ("compra", "venda")]
    mets = [_m(fr=float(rng.normal(1, 2)), lucro=float(rng.normal(500, 300)))
            for _ in params]
    idx = [k for k in range(len(params)) if rng.random() < 0.6]

    wfa._GRADE.clear()
    por_endereco = wfa.escolher("vizinhanca", idx, params, mets)
    R, raio, tam, grupo, passo, _mapa, _off = wfa._GRADE["dados"]
    wfa._GRADE["dados"] = (R, raio, tam, grupo, passo, None, None)
    em_bloco = wfa.escolher("vizinhanca", idx, params, mets)
    wfa._GRADE.clear()
    assert por_endereco == em_bloco


def test_conselho_com_memo_escolhe_o_mesmo_que_sem():
    idx, params, mets = _cenario_plato()
    memo = {}
    for q in wfa.VOTANTES:
        wfa.escolher(q, idx, params, mets, memo)
    assert wfa.escolher("conselho", idx, params, mets, memo) == \
        wfa.escolher("conselho", idx, params, mets)
