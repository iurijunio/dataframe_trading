"""Sub-tela Ao vivo › Operação: o que ela desenha a partir de `core.papel_leitura`.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6–§7.
As funções de desenho recebem dicionários montados à mão no formato que o
core devolve; nenhum teste lê o banco real nem o estado.json real.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from dash import no_update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import operacao_panel as OP  # noqa: E402

AGORA = datetime(2026, 10, 2, 14, 37)


def textos(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(textos(x) for x in c)
    return textos(getattr(c, "children", None))


def todos(c):
    """Todos os componentes da árvore, em profundidade."""
    if c is None or isinstance(c, (str, int, float)):
        return []
    if isinstance(c, (list, tuple)):
        return [x for y in c for x in todos(y)]
    return [c] + todos(getattr(c, "children", None))


def classes(c) -> str:
    return getattr(c, "className", "") or ""


def _resumo(**mudar):
    r = {
        "resultado_hoje": 286.0,
        "posicao": {"liquida": 1, "por_ligacao": {1: 0, 2: 1}},
        "pior_momento": {"valor": -164.0, "quando": datetime(2026, 10, 2, 11, 8)},
        "limite_dia": 500.0,
        "acumulado": {"valor": 2418.0, "pregoes": 12, "operacoes": 41},
        "n_variantes": 2, "n_operando": 2,
        "contas": {"demo": {"conta_id": 2, "nome": "Clear demo",
                            "limite_perda_dia": 500.0}, "real": None},
        "capital": 10000.0,
    }
    r.update(mudar)
    return r


def _var(lig=1, **mudar):
    v = {"ligacao_id": lig, "variante_id": 10 + lig, "nome": f"var-{lig}",
         "fase": "papel", "ligada": True, "cor": lig - 1, "status": "rodando",
         "motivo": None, "posicao": 0, "hoje": 120.0, "n_ops": 3,
         "acerto": "2/3", "acumulado": 840.0, "contratos": 2, "plano_id": 5,
         "gravado_mesmo_assim": False, "pendencias": []}
    v.update(mudar)
    return v


def _op(**mudar):
    o = {"op_id": 1, "ligacao_id": 1, "plano_id": 5,
         "entry_ts": datetime(2026, 10, 2, 9, 14),
         "exit_ts": datetime(2026, 10, 2, 9, 52), "side": 1, "contratos": 2,
         "entry_px": 187420, "exit_px": 188080, "points": 660,
         "liquido": 128.0, "reason": 1, "stop_px": None, "alvo_px": None,
         "aberta": False, "provisorio": False, "situacao": "fechada",
         "conta": True, "variante": "var-1", "cor": 0}
    o.update(mudar)
    return o


# ------------------------------------------------------------------ KPIs
def _kpi(cartoes, rotulo):
    return next(c for c in cartoes if rotulo in textos(c))


def test_seis_indicadores_cada_um_com_dica():
    cartoes = OP.kpis(_resumo(), [_op()], {"diferenca": 120.0, "faixas": []})
    assert len(cartoes) == 6
    for c in cartoes:
        assert any("dica-mark" in classes(x) for x in todos(c)), textos(c)


def test_pior_momento_com_limite_mostra_a_barra():
    c = _kpi(OP.kpis(_resumo(), [], {}), "Pior momento")
    t = textos(c)
    assert "-R$ 164" in t and "11:08" in t and "R$ 500" in t
    barra = [x for x in todos(c) if "op-barra-uso" in classes(x)]
    assert barra and barra[0].style["width"] == "33%"


def test_pior_momento_sem_limite_esconde_a_barra():
    c = _kpi(OP.kpis(_resumo(limite_dia=None), [], {}), "Pior momento")
    assert not [x for x in todos(c) if "op-barra" in classes(x)]
    assert "sem limite" in textos(c)


def test_posicao_agora_diz_o_lado_e_os_contratos():
    c = _kpi(OP.kpis(_resumo(posicao={"liquida": -2, "por_ligacao": {}}),
                     [], {}), "Posição agora")
    t = textos(c)
    assert "vendido" in t and "papel 2" in t and "demo —" in t


def test_resultado_hoje_conta_so_o_que_conta():
    ops = [_op(), _op(op_id=2, conta=False),
           _op(op_id=3, situacao="aberta", aberta=True, exit_ts=None)]
    t = textos(_kpi(OP.kpis(_resumo(), ops, {}), "Resultado hoje"))
    assert "+R$ 286" in t
    assert "2 operações" in t and "1 aberta" in t


def test_contra_o_esperado_sem_expectativa_e_travessao():
    c = _kpi(OP.kpis(_resumo(), [], {"diferenca": None, "faixas": [None]}),
             "Contra o esperado")
    assert "—" in textos(c)


def test_contra_o_esperado_conta_as_faixas():
    esp = {"diferenca": -80.0,
           "faixas": ["p10_p50", "p50_p90", "abaixo_p10", None]}
    t = textos(_kpi(OP.kpis(_resumo(), [], esp), "Contra o esperado"))
    assert "abaixo da mediana" in t
    assert "2 de 3 dentro da faixa" in t and "1 abaixo do p10" in t


# ------------------------------------------------------------- variantes
def test_cartao_mostra_contratos_papel_e_demo():
    t = textos(OP.cartao_variante(_var(contratos=3), None))
    assert "papel 3" in t and "demo —" in t and "plano #5" in t


def test_cartao_pulado_fica_apagado_com_o_motivo():
    c = OP.cartao_variante(_var(status="pulado",
                                motivo="código mudou desde o plano"), None)
    assert "op-var-apagada" in classes(c)
    t = textos(c)
    assert "pulado" in t and "código mudou desde o plano" in t


def test_cartao_interrompido_fica_apagado_com_o_motivo():
    c = OP.cartao_variante(_var(status="interrompido", motivo="código mudou"),
                           None)
    assert "op-var-apagada" in classes(c)
    assert "interrompido" in textos(c) and "código mudou" in textos(c)


def test_cartao_gravado_mesmo_assim_tem_a_etiqueta():
    c = OP.cartao_variante(_var(gravado_mesmo_assim=True,
                                pendencias=[{"nome": "SPA", "motivo": "x"}]),
                           None)
    assert "gravado mesmo assim" in textos(c)


def test_cartao_posicao_aberta():
    t = textos(OP.cartao_variante(_var(posicao=1), None))
    assert "comprado 1" in t


def test_cartao_botao_de_dois_cliques():
    b = [x for x in todos(OP.cartao_variante(_var(), None))
         if isinstance(getattr(x, "id", None), dict)]
    assert b[0].id == {"type": "av-op-acao", "acao": "membro-desligar", "id": 1}
    armado = OP.cartao_variante(_var(), "membro-desligar:1")
    assert "Confirmar?" in textos(armado)


def test_quinze_variantes_com_nomes_longos_todas_com_reticencias():
    nomes = [f"rompimento-canal-M15-cluster-{i:02d}-otimizado-x"[:45]
             .ljust(45, "z") for i in range(15)]
    assert all(len(n) == 45 for n in nomes)
    vs = [_var(i + 1, nome=n, cor=i) for i, n in enumerate(nomes)]
    arvore = OP.coluna_variantes(vs, None, _resumo())
    nomes_tela = [x for x in todos(arvore) if "op-nome" in classes(x)]
    assert [x.title for x in nomes_tela] == nomes
    assert [x.children for x in nomes_tela] == nomes


def test_legenda_quinze_chips_rolaveis_e_forma_depois_de_oito():
    vs = [_var(i + 1, nome="x" * 45, cor=i) for i in range(15)]
    chips = [x for x in todos(OP.legenda(vs, [3])) if "op-chip" in classes(x)
             and isinstance(getattr(x, "id", None), dict)]
    assert len(chips) == 15
    assert all(c.title for c in chips)
    oculto = next(c for c in chips if c.id["id"] == 3)
    assert "op-chip-off" in classes(oculto)
    amostras = [x for x in todos(OP.legenda(vs, [])) if "op-amostra" in classes(x)]
    assert "op-amostra-quadrado" not in classes(amostras[0])
    assert "op-amostra-quadrado" in classes(amostras[8])


def test_cartao_traduz_a_fase():
    t = textos(OP.cartao_variante(_var(fase="real_minimo"), None))
    assert "real mínimo" in t and "real_minimo" not in t


def test_pior_momento_sem_hora_nao_comeca_com_separador():
    c = _kpi(OP.kpis(_resumo(pior_momento={"valor": 0.0, "quando": None}),
                     [], {}), "Pior momento")
    nota = next(x for x in todos(c) if "op-kpi-n" in classes(x))
    assert not nota.children.startswith(" ·")
    assert nota.children.startswith("limite do dia")


def _com_dica(arvore, rotulo):
    for x in todos(arvore):
        filhos = getattr(x, "children", None)
        if isinstance(filhos, list) and filhos and filhos[0] == rotulo:
            return any("dica-mark" in classes(y) for y in todos(filhos[1:]))
    raise AssertionError(f"rótulo {rotulo!r} não achado")


def test_colunas_da_variante_tem_dica():
    arvore = OP.coluna_variantes([_var()], None, _resumo())
    for rot in ("Hoje", "Operações", "Acerto", "Acumulado"):
        assert _com_dica(arvore, rot), rot


def test_cabecalho_da_tabela_tem_dica_nas_metricas():
    arvore = OP.tabela_operacoes([_op()])
    for rot in ("Contr. papel / demo", "Pontos", "Resultado papel"):
        assert _com_dica(arvore, rot), rot


def test_comparativo_tem_dica_em_todas_as_linhas():
    vazio = {"n": 0}
    arvore = OP.tabela_comparativo({"esperado_wfa": vazio, "papel": vazio,
                                    "demo": None, "real": None})
    for rot in ("Contratos por operação", "Pontos por operação", "Acerto",
                "Fator de lucro", "Operações"):
        assert _com_dica(arvore, rot), rot


def test_botao_estado_armado_sem_reler_o_banco():
    assert OP.estado_botao("membro-desligar", 1, None)[0] == "Pausar"
    rot, cls = OP.estado_botao("membro-desligar", 1, "membro-desligar:1")
    assert rot == "Confirmar?" and "av-armado" in cls
    assert OP.estado_botao("membro-desligar", 2, "membro-desligar:1")[0] == "Pausar"
    assert OP.estado_botao("pf-ligar", 3, None)[0] == "Ligar portfólio"


# -------------------------------------------------------------- operações
def test_linha_aberta_mostra_stop_alvo_e_provisorio():
    o = _op(situacao="aberta", aberta=True, provisorio=True, exit_ts=None,
            exit_px=None, points=240, liquido=48.0, stop_px=188645,
            alvo_px=189665)
    linha = OP.linha_operacao(o)
    assert "op-aberta" in classes(linha)
    t = textos(linha)
    assert "aberta" in t and "188.645" in t and "189.665" in t
    assert "provisório" in t and "1 / —" not in t and "2 / —" in t


def test_linha_que_nao_conta_fica_cinza_com_o_motivo():
    linha = OP.linha_operacao(_op(conta=False))
    assert "op-fora" in classes(linha)
    assert "fora do período ligado" in textos(linha)


def test_linha_nao_conferida():
    linha = OP.linha_operacao(_op(situacao="nao_conferido", exit_ts=None,
                                  exit_px=None, aberta=False))
    assert "não conferida" in textos(linha)


def test_tabela_vazia_explica():
    assert "nenhuma operação" in textos(OP.tabela_operacoes([]))


def test_saiu_por_traduzido():
    assert "alvo" in textos(OP.linha_operacao(_op(reason=1)))
    assert "sinal contrário" in textos(OP.linha_operacao(_op(reason=2)))


# ---------------------------------------------------------------- gráfico
def _mk(**mudar):
    m = {"time": 1000 * 60, "position": "belowBar", "shape": "arrowUp",
         "text": "C", "cor": 0, "conta": True, "ligacao_id": 1}
    m.update(mudar)
    return m


def test_marcadores_pintados_e_sem_chaves_extras():
    dados = {"marcadores": [_mk(), _mk(cor=1, conta=False, ligacao_id=2)],
             "linhas_abertas": []}
    mk, _ = OP.marcadores_tela(dados, [], "M1")
    assert mk[0]["color"] == OP.cor(0)
    assert mk[1]["color"] == OP.CINZA
    assert set(mk[0]) == {"time", "position", "shape", "color", "text"}


def test_marcadores_escondem_a_variante_oculta():
    dados = {"marcadores": [_mk(), _mk(ligacao_id=2)],
             "linhas_abertas": [{"tipo": "stop", "price": 100, "title": "stop x",
                                 "cor": 1, "conta": True, "ligacao_id": 2}]}
    mk, linhas = OP.marcadores_tela(dados, [2], "M1")
    assert len(mk) == 1 and linhas == []


def test_marcador_de_saida_muda_de_forma_depois_de_oito_cores():
    dados = {"marcadores": [_mk(shape="circle", cor=0, time=60),
                            _mk(shape="circle", cor=8, time=2 * 60)],
             "linhas_abertas": []}
    mk, _ = OP.marcadores_tela(dados, [], "M1")
    assert mk[0]["shape"] == "circle" and mk[1]["shape"] == "square"
    assert mk[0]["color"] == mk[1]["color"]


def test_marcador_cai_no_inicio_do_candle_de_5_min():
    dados = {"marcadores": [_mk(time=7 * 60)], "linhas_abertas": []}
    mk, _ = OP.marcadores_tela(dados, [], "M5")
    assert mk[0]["time"] == 5 * 60


def test_linhas_de_stop_e_alvo():
    dados = {"marcadores": [],
             "linhas_abertas": [{"tipo": "stop", "price": 100, "title": "stop x",
                                 "cor": 0, "conta": True, "ligacao_id": 1},
                                {"tipo": "alvo", "price": 200, "title": "alvo x",
                                 "cor": 0, "conta": True, "ligacao_id": 1}]}
    _, linhas = OP.marcadores_tela(dados, [], "M1")
    assert [l["price"] for l in linhas] == [100, 200]
    assert all(l["lineStyle"] == 2 for l in linhas)
    assert all(l["axisLabelVisible"] for l in linhas)


def test_mais_de_duas_abertas_escondem_os_rotulos_do_eixo():
    linhas = [{"tipo": t, "price": 100 + i, "title": "x", "cor": i,
               "conta": True, "ligacao_id": i}
              for i in range(3) for t in ("stop", "alvo")]
    _, saida = OP.marcadores_tela({"marcadores": [], "linhas_abertas": linhas},
                                  [], "M1")
    assert len(saida) == 6
    assert not any(l["axisLabelVisible"] for l in saida)
    assert all(l["title"] == "" for l in saida)
    # escondendo uma pela legenda, voltam a ser duas: rótulos aparecem
    _, saida = OP.marcadores_tela({"marcadores": [], "linhas_abertas": linhas},
                                  [0], "M1")
    assert all(l["axisLabelVisible"] for l in saida)


# ------------------------------------------------- tick sem ler o banco
def _estado(**mudar):
    e = {"atualizado_em": (AGORA - timedelta(seconds=2)).isoformat(),
         "em_pregao": True, "mt5": "conectado",
         "primeiro_candle_hoje": "2026-10-02T09:00:00",
         "ultimo_salvo": "2026-10-02T14:36:00",
         "em_formacao": {"ts": "2026-10-02T14:37:00", "open": 10, "high": 12,
                         "low": 9, "close": 11},
         "papel": {"calculado_em": "2026-10-02T14:37:01", "pendente": False,
                   "divergencias": 0, "erros": {}}}
    e.update(mudar)
    return e


def test_tick_m1_e_o_minuto_em_formacao():
    t = OP.tick_operacao(_estado(), "M1", None, AGORA)
    assert t["bar"]["open"] == 10 and t["bar"]["close"] == 11


def test_tick_m5_junta_o_candle_da_serie_do_mesmo_balde():
    from ui.data import to_epoch
    base = {"time": to_epoch(datetime(2026, 10, 2, 14, 35)), "open": 5,
            "high": 20, "low": 7, "close": 8}
    t = OP.tick_operacao(_estado(), "M5", base, AGORA)
    assert t["bar"] == {"time": base["time"], "open": 5, "high": 20, "low": 7,
                        "close": 11}


def test_tick_m5_sem_candle_do_balde_usa_so_o_minuto():
    from ui.data import to_epoch
    base = {"time": to_epoch(datetime(2026, 10, 2, 14, 30)), "open": 5,
            "high": 20, "low": 7, "close": 8}
    t = OP.tick_operacao(_estado(), "M5", base, AGORA)
    assert t["bar"]["open"] == 10
    assert t["bar"]["time"] == to_epoch(datetime(2026, 10, 2, 14, 35))


def test_tick_com_captura_parada_e_nada():
    velho = _estado(atualizado_em=(AGORA - timedelta(minutes=5)).isoformat())
    assert OP.tick_operacao(velho, "M1", None, AGORA) is None


# ------------------------------------------------------------- situação
def test_situacao_captura_parada_diz_quando_o_papel_congelou():
    velho = _estado(atualizado_em=(AGORA - timedelta(minutes=5)).isoformat())
    t = textos(OP.faixa_situacao(velho, AGORA))
    assert "papel congelado em 14:37" in t


def test_situacao_erro_do_papel_aparece():
    e = _estado(papel={"calculado_em": None, "pendente": False,
                       "erros": {"calculo": "boom"}})
    assert "papel de hoje não foi calculado" in textos(OP.faixa_situacao(e, AGORA))


def test_alertas_viram_faixas():
    al = [{"tipo": "pulado", "ligacao_id": 1, "texto": "var-1: pregão pulado — x"}]
    t = textos(OP.lista_alertas(al))
    assert "var-1: pregão pulado" in t
    assert "nada pede atenção" in textos(OP.lista_alertas([]))


# ------------------------------------------------------------ curva / comp.
def test_curva_por_variante_tem_faixa_e_mediana():
    c = {"dias": [date(2026, 9, 30), date(2026, 10, 1)], "papel": [10.0, 30.0],
         "mediana": [5.0, 10.0], "p10": [-20.0, -30.0], "p90": [30.0, 50.0],
         "faixa_atual": "p50_p90", "aviso": None}
    ids = [s["id"] for s in OP.curva_series(c)]
    assert ids == ["p90", "p10", "mediana", "papel"]


def test_curva_sem_expectativa_so_o_papel():
    c = {"dias": [date(2026, 10, 1)], "papel": [10.0], "mediana": None,
         "p10": None, "p90": None, "aviso": "plano sem expectativa"}
    assert [s["id"] for s in OP.curva_series(c)] == ["papel"]


def test_comparativo_demo_e_real_travessao_e_fator_infinito():
    m = {"n": 3, "resultado_por_contrato": 40.0, "pontos_por_operacao": 147.0,
         "fator_lucro": float("inf"), "acerto": 1.0,
         "contratos_por_operacao": 1.0, "total": 120.0}
    vazio = {"n": 0, "resultado_por_contrato": None, "pontos_por_operacao": None,
             "fator_lucro": None, "acerto": None, "contratos_por_operacao": None,
             "total": 0.0}
    t = textos(OP.tabela_comparativo({"esperado_wfa": m, "papel": vazio,
                                      "demo": None, "real": None}))
    assert "sem perdas" in t and "Esperado (WFA)" in t and "Demo" in t
    assert "None" not in t and "nan" not in t


# ------------------------------------------------------------- estrutura
def test_bloco_tem_os_ids():
    ids = {x.id for x in todos(OP.bloco()) if isinstance(getattr(x, "id", None), str)}
    assert {"av-bloco-operacao", "av-op-intervalo", "av-op-portfolio",
            "av-op-versao", "av-op-kpis", "av-op-grafico", "av-op-tf",
            "av-op-agora", "av-op-cheia", "av-op-variantes", "av-op-filtro",
            "av-op-operacoes", "av-op-curva", "av-op-curva-modo",
            "av-op-comparativo", "av-op-alertas", "av-op-legenda"} <= ids


@pytest.fixture
def app(_banco_isolado):
    from core import db_manager as db
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 "
                    "09:00:00', 100, 101, 99, 100, 1)")
    from ui.app import build
    return build()


def _entradas(cb):
    return {f"{e['id']}.{e['property']}" for e in cb["inputs"]}


def test_nenhum_callback_que_le_o_banco_ouve_o_pulso(app):
    """O pulso de 2 s só lê o estado.json: quem lê o banco depende de
    `av-op-versao`, que muda uma vez por cálculo do papel."""
    ouvem = [cb for cb in app.callback_map.values()
             if "av-op-intervalo.n_intervals" in _entradas(cb)]
    assert [cb["callback"].__name__ for cb in ouvem] == ["pulso_op"]
    from ui.callbacks_operacao import SAIDAS_DO_PULSO
    chave = next(k for k, cb in app.callback_map.items() if cb in ouvem)
    partes = (chave.strip(".").split("...") if chave.startswith("..")
              else [chave])
    # só o que vem do estado.json: situação, versão, último candle e tick
    assert {p.split("@")[0] for p in partes} == set(SAIDAS_DO_PULSO)


def test_armar_um_botao_nao_rele_o_banco(app):
    """O primeiro clique só troca o rótulo: `av-op-armado` não pode ser
    Input do redesenho que lê o banco."""
    pesado = next(cb for cb in app.callback_map.values()
                  if getattr(cb.get("callback"), "__name__", "") == "desenhar_op")
    assert "av-op-armado.data" not in _entradas(pesado)
    # quem ouve o armado é só o callback dos rótulos (sem banco)
    ouvem = {getattr(cb.get("callback"), "__name__", "")
             for cb in app.callback_map.values()
             if "av-op-armado.data" in _entradas(cb)}
    assert "rotulos_op" in ouvem and "desenhar_op" not in ouvem


def test_caixas_que_rolam_sao_fixas_no_layout():
    """A rolagem só sobrevive à releitura de minuto em minuto se a caixa
    que rola não for recriada: ela mora no layout, o callback troca só o
    conteúdo dela."""
    fixas = {x.id: classes(x) for x in todos(OP.bloco())
             if isinstance(getattr(x, "id", None), str)}
    assert "op-var-lista" in fixas["av-op-var-lista"]
    assert "op-tabela-caixa" in fixas["av-op-operacoes"]
    assert "op-chips" in fixas["av-op-chips"]
    # e o conteúdo devolvido não traz outra caixa de rolagem dentro
    assert not [x for x in todos(OP.cartoes([_var()], None))
                if "op-var-lista" in classes(x)]
    assert not [x for x in todos(OP.tabela_operacoes([_op()]))
                if "op-tabela-caixa" in classes(x)]


def test_botao_abrir_em_estrategias():
    b = next(x for x in todos(OP.bloco()) if getattr(x, "id", None) == "av-op-ficha")
    assert b.children == "Abrir em Estratégias"


def test_o_pulso_nao_abre_o_banco(monkeypatch):
    from core import db_manager as db
    from ui import callbacks_operacao as CO

    def explode(*a, **k):
        raise AssertionError("o pulso abriu o banco")
    monkeypatch.setattr(db, "connect", explode)
    monkeypatch.setattr(db, "connect_write", explode)
    out = CO.pulso(_estado(), "2026-10-02T14:30:00", "2026-10-02T14:30:00",
                   "M5", None, AGORA)
    assert out[1] == "2026-10-02T14:37:01"         # versão nova
    assert out[2] == "2026-10-02T14:36:00"         # candle novo
    assert out[3] is not no_update


def test_o_pulso_so_muda_a_versao_quando_o_papel_muda():
    from ui import callbacks_operacao as CO
    out = CO.pulso(_estado(), "2026-10-02T14:37:01", "2026-10-02T14:36:00",
                   "M1", None, AGORA)
    assert out[1] is no_update and out[2] is no_update


def test_subtela_operacao_liga_o_pulso_dela():
    from ui.callbacks_pregao import mostrar_subtela
    est, pg, op, pg_off, op_off = mostrar_subtela("operacao", "aovivo")
    assert est["display"] == "none" and pg["display"] == "none"
    assert op["display"] != "none"
    assert pg_off is True and op_off is False
    assert mostrar_subtela("operacao", "backtest")[4] is True
    assert mostrar_subtela("pregao", "aovivo")[4] is True
