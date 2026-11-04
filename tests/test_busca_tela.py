"""A subtela Busca automática: o que o servidor manda à tela (layout B) e o
que ele faz com os cliques. O desenho em si é de `ui/assets/busca.js`."""
import json
import math

import pytest

from core import db_manager as db
from core.busca import banco as B
from core.busca import controle as K
from core.engine.execution import ExecutionProfile
from ui import callbacks_busca as CB
from ui.callbacks import MENU_PERFIL, perfil_do_menu


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


# ------------------------------------------------------------ menu
def test_perfil_do_menu_le_todos_os_campos():
    menu = {"e-timeframe": "M5", "e-ent-ini": "10:00", "e-ent-fim": "11:30",
            "e-fechamento": "17:00", "e-dias": [2, 4], "e-direcao": "compra",
            "e-filtro-adx": "rango", "e-sem-ent1": "12:00", "e-sem-ent2": "",
            "e-sem-ent3": "", "e-alvo-tipo": "multiplicador", "e-stop-tipo": "atr",
            "e-max-barras": 30, "e-lim-ganho": 100, "e-lim-perda": 50,
            "e-max-trades": 3, "e-max-loss": 2, "e-corretagem": 0.5,
            "e-emolumentos": 0.27, "e-slippage": 1, "e-modo": "contratos_fixos",
            "e-contratos": 2, "e-risco": None, "e-capital": 20000, "e-min-ops": 50}
    assert {cid for cid, _ in MENU_PERFIL} == set(menu)
    p = perfil_do_menu({"adx_periodo": 14, "adx_limiar": 20, "stop_atr_mult": 1.5,
                        "alvo_razao": 2.0}, menu)
    assert (p.timeframe, p.entrada_inicio, p.entrada_fim, p.fechamento) == \
        ("M5", "10:00", "11:30", "17:00")
    assert tuple(p.dias_semana) == (2, 4) and p.direcao == "compra"
    assert (p.filtro_adx, p.adx_periodo, p.adx_limiar) == ("rango", 14, 20)
    assert (p.stop_tipo, p.stop_atr_mult, p.alvo_tipo) == ("atr", 1.5, "multiplicador")
    assert (p.limite_ganho_contrato, p.limite_perda_contrato, p.max_trades_dia,
            p.max_prejuizos_dia) == (100, 50, 3, 2)
    assert (p.corretagem_por_contrato, p.contratos, p.capital_inicial,
            p.min_operacoes) == (0.5, 2, 20000, 50)


def test_perfil_do_menu_vazio_cai_nos_padroes():
    p = perfil_do_menu({}, {})
    assert (p.timeframe, p.entrada_inicio, p.entrada_fim, p.fechamento) == \
        ("M1", "09:00", "17:00", "17:30")
    assert tuple(p.dias_semana) == (1, 2, 3, 4, 5) and p.capital_inicial == 10_000.0


# ------------------------------------------------------------ dados
def test_json_seguro_tira_infinito_e_nan():
    d = CB._json_seguro({"a": float("inf"), "b": [1.0, float("nan")], "c": {"d": -math.inf}})
    assert d == {"a": None, "b": [1.0, None], "c": {"d": None}}
    json.dumps(d, allow_nan=False)


def test_sem_busca_a_tela_fica_parada_e_editavel():
    d = CB.dados_da_tela(None, "adx_direcao", "WIN$N", ExecutionProfile())
    assert d["status"] == "parada" and d["busca_id"] is None and d["mapas"] is None
    assert not d["espaco"]["travado"]
    nomes = [i["nome"] for i in d["espaco"]["itens"]]
    assert nomes[:6] == ["timeframe", "direcao", "janela", "dias", "stop", "alvo"]
    assert "di_periodo" in nomes
    tf = next(i for i in d["espaco"]["itens"] if i["nome"] == "timeframe")
    rotulos = [o["rotulo"] for o in tf["opcoes"]]          # em minutos, como o protótipo
    assert {"M60", "M120", "M240"} <= set(rotulos) and rotulos[-1] == "M240"
    assert d["controle"] == {"nucleos": 20, "parar_as": "08:30",
                             "parar_as_ligado": True, "limite": None}
    assert d["salvas"] == []


def test_fixos_na_moeda_do_ativo():
    f = dict(CB._fixos(ExecutionProfile(corretagem_por_contrato=0.5,
                                        emolumentos_por_contrato=0.27), "R$"))
    assert f["Custos"] == "R$ 0,77 + 1 tick" and f["Breakeven"] == "desligado"


def test_nova_mostra_parada_mesmo_com_buscas():
    B.criar({"simbolo": "WIN$N", "estrategia": "adx_direcao"})
    assert CB.dados_da_tela("nova", "adx_direcao", "WIN$N", ExecutionProfile())["status"] == "parada"


def test_busca_que_caiu_aparece_interrompida():
    bid = B.criar({"simbolo": "WIN$N", "estrategia": "adx_direcao", "criterio": "fr",
                   "minimo": 400})           # banco diz "rodando", ninguém com a trava
    d = CB.dados_da_tela(None, "adx_direcao", "WIN$N", ExecutionProfile())
    assert d["busca_id"] == bid and d["status"] in ("interrompida", "rodando")
    assert d["espaco"]["travado"]
    assert d["salvas"][0]["id"] == bid


# ------------------------------------------------------------ ações
def test_iniciar_recusa_janela_invalida(monkeypatch):
    chamado = []
    monkeypatch.setattr(K, "iniciar", lambda *a, **k: chamado.append(1))
    perfil = ExecutionProfile(entrada_inicio="15:00", entrada_fim="10:00")
    sel, aviso = CB.atender({"acao": "iniciar"}, None, "adx_direcao", "WIN$N",
                            "2024-01-01", "2024-06-30", {}, perfil)
    assert aviso and not chamado


def test_iniciar_monta_a_config_da_busca(monkeypatch):
    capturado = {}
    monkeypatch.setattr(K, "iniciar", lambda cfg, **ctl: capturado.update(cfg=cfg, ctl=ctl) or 7)
    perfil = ExecutionProfile(corretagem_por_contrato=0.5, fechamento="17:30")
    sel, aviso = CB.atender(
        {"acao": "iniciar", "faixas": {"timeframe": {"ligados": ["M5"]}}, "criterio": "pf",
         "minimo": 300, "nucleos": 6, "parar_as": "07:00", "parar_as_ligado": True,
         "limite": 1000},
        None, "adx_direcao", "WIN$N", "2024-01-01", "2024-06-30",
        {"treino_meses": 2, "teste_meses": 1, "passo_meses": 1, "holdout_meses": 1}, perfil)
    assert (sel, aviso) == (7, "")
    c = capturado["cfg"]
    assert (c["criterio"], c["minimo"], c["de"], c["ate"]) == \
        ("pf", 300, "2024-01-01T00:00:00", "2024-06-30T23:59:59")
    assert c["espaco"]["faixas"] == {"timeframe": {"ligados": ["M5"]}}
    assert c["perfil_base"]["corretagem_por_contrato"] == 0.5
    assert capturado["ctl"] == {"nucleos": 6, "parar_as": "07:00", "parar_as_ligado": True,
                                "limite": 1000}


def test_acoes_de_controle(monkeypatch):
    feitos = []
    for nome in ("pausar", "continuar", "parar"):
        monkeypatch.setattr(K, nome, lambda bid, _n=nome: feitos.append((_n, bid)))
    monkeypatch.setattr(K, "ajustar", lambda bid, **c: feitos.append(("ajustar", bid, c)))
    p = ExecutionProfile()
    for a in ("pausar", "continuar", "parar"):
        CB.atender({"acao": a, "id": 5}, 5, "adx_direcao", "WIN$N", None, None, {}, p)
    CB.atender({"acao": "ajustar", "id": 5, "campos": {"nucleos": 3, "malicioso": 1}},
               5, "adx_direcao", "WIN$N", None, None, {}, p)
    assert feitos == [("pausar", 5), ("continuar", 5), ("parar", 5),
                      ("ajustar", 5, {"nucleos": 3})]


def test_excluir_viva_avisa_e_nao_apaga(monkeypatch):
    def recusa(_bid):
        raise K.BuscaViva("a busca está rodando; pare antes de excluir")

    monkeypatch.setattr(K, "excluir", recusa)
    sel, aviso = CB.atender({"acao": "excluir", "id": 5}, 5, "adx_direcao", "WIN$N",
                            None, None, {}, ExecutionProfile())
    assert "pare antes" in aviso


# ------------------------------------------------------------ ir
def _saida(out) -> dict:
    """A tupla do callback `ir` por nome: val, on, opt, os campos do menu,
    d-de, d-ate, holdout, btn-run, subtela, store."""
    nomes = (["val", "on", "opt"] + [cid for cid, _p in MENU_PERFIL]
             + ["d-de", "d-ate", "holdout", "btn-run", "subtela", "store"])
    assert len(out) == len(nomes)
    return dict(zip(nomes, out))


PERFIL_BUSCA = ExecutionProfile(corretagem_por_contrato=1.25, fechamento="17:00",
                                adx_periodo=14, adx_limiar=20, breakeven_pct=40,
                                max_trades_dia=3).to_config()


def test_ir_regiao_escreve_faixas_fixos_e_volta_para_a_varredura():
    r = {"timeframe": "M15", "entrada_inicio": "10:00", "entrada_fim": "11:30",
         "dias_semana": [2, 4], "direcao": "venda", "stop_tipo": "atr",
         "alvo_tipo": "multiplicador",
         "campos": {"di_periodo": {"on": True, "de": 10, "ate": 20, "passo": 1, "valor": 14},
                    "stop_atr_mult": {"on": False, "de": 1.5, "ate": 1.5, "passo": 0.25,
                                      "valor": 1.5}}}
    cfg = {"perfil_base": PERFIL_BUSCA, "de": "2021-03-16T00:00:00",
           "ate": "2026-11-03T23:59:59"}
    ids_val = [{"p": "di_periodo"}, {"p": "stop_atr_mult"}, {"p": "adx_periodo"},
               {"p": "breakeven_pct"}]
    ids_on = [{"p": "di_periodo"}, {"p": "stop_atr_mult"}, {"p": "breakeven_pct"}]
    ids_opt = [{"p": "di_periodo", "k": "de"}, {"p": "di_periodo", "k": "ate"},
               {"p": "outro", "k": "de"}]
    o = _saida(CB._ir_regiao(r, cfg, ids_val, [1, 2, 3, 4], ids_on, [[], [], ["on"]],
                             ids_opt, [0, 0, 9]))
    assert o["val"] == [14, 1.5, 14, 40]                 # região + fixos da busca
    assert o["on"] == [["on"], [], []]                   # marca velha sai do minerar
    assert o["opt"] == [10, 20, 9]
    assert (o["e-timeframe"], o["e-ent-ini"], o["e-ent-fim"], o["e-dias"],
            o["e-direcao"], o["e-stop-tipo"], o["e-alvo-tipo"]) == \
        ("M15", "10:00", "11:30", [2, 4], "venda", "atr", "multiplicador")
    assert (o["e-corretagem"], o["e-fechamento"], o["e-max-trades"]) == (1.25, "17:00", 3)
    assert (o["d-de"], o["d-ate"]) == ("2021-03-16", "2026-11-03")
    assert o["subtela"] == "varredura" and o["store"] is None


def test_ir_backtest_leva_o_perfil_inteiro_o_corte_e_nao_nasce_editado():
    from ui.callbacks import _linha_combinacao, _menu_atual

    perfil = {**ExecutionProfile(timeframe="M2", entrada_inicio="13:00", entrada_fim="13:30",
                                 dias_semana=(2, 5), stop_tipo="percentual", stop_pct=0.5,
                                 alvo_tipo="multiplicador", alvo_razao=3.5).to_config(),
              **{k: PERFIL_BUSCA[k] for k in ("corretagem_por_contrato", "fechamento",
                                              "adx_periodo", "adx_limiar", "breakeven_pct",
                                              "max_trades_dia")}}
    cb = {"params": {"di_periodo": 33}, "de": "2021-03-16T00:00:00",
          "ate": "2026-11-03T23:59:59", "fim_otimizacao": "2025-11-08T23:59:59",
          "perfil": perfil}
    ids_val = [{"p": "di_periodo"}, {"p": "stop_pct"}, {"p": "alvo_razao"},
               {"p": "adx_periodo"}, {"p": "breakeven_pct"}]
    menu = {"ativo": "WIN$N", "e-capital": 10000}
    o = _saida(CB._ir_backtest(cb, 3, ids_val, [14, 0.2, 2.0, 0, 0], [], [], [], [], 4, menu))
    assert o["val"] == [33, 0.5, 3.5, 14, 40]
    assert (o["e-timeframe"], o["e-ent-ini"], o["e-ent-fim"], o["e-dias"],
            o["e-stop-tipo"], o["e-alvo-tipo"]) == \
        ("M2", "13:00", "13:30", [2, 5], "percentual", "multiplicador")
    assert (o["e-corretagem"], o["e-fechamento"], o["e-max-trades"]) == (1.25, "17:00", 3)
    assert (o["d-de"], o["d-ate"]) == ("2021-03-16", "2026-11-03")
    assert o["holdout"] == ["on"] and o["btn-run"] == 5 and o["subtela"] == "backtest"
    store = o["store"]
    assert store["origem"] == "busca" and store["corte"] == "2025-11-08T23:59:59"
    escrito = {cid: o[cid] for cid, _p in MENU_PERFIL}
    depois = _menu_atual(ids_val, o["val"], ["on"],
                         {**menu, **escrito, "d-de": o["d-de"], "d-ate": o["d-ate"]})
    assert "editado" not in _linha_combinacao(store, depois)


def test_menu_do_perfil_e_o_caminho_de_volta():
    from ui.callbacks import menu_do_perfil

    m, v = menu_do_perfil(PERFIL_BUSCA)
    # a Varredura não lê proteção do menu (ela vem pelos campos mineráveis);
    # a busca lê, e com ela o perfil volta inteiro
    assert perfil_do_menu(v, m).to_config() == {**PERFIL_BUSCA, "breakeven_pct": 0.0}
    from ui.callbacks import perfil_da_busca
    assert perfil_da_busca(v, m).to_config() == PERFIL_BUSCA


def test_busca_escolhida_de_outra_estrategia_nao_aparece():
    bid = B.criar({"simbolo": "WIN$N", "estrategia": "adx_direcao"})
    assert CB._busca_da_tela(bid, "adx_direcao", "WIN$N") == bid
    assert CB._busca_da_tela(bid, "rompimento_canal", "WIN$N") is None
    assert CB._busca_da_tela(bid, "adx_direcao", "MES") is None


@pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")
def test_com_uma_busca_real_os_mapas_vao_inteiros():
    from tests import _busca_pequena

    bid = _busca_pequena.rodar(2)
    B.marcar_status(bid, "concluida")
    d = CB._json_seguro(CB.dados_da_tela(None, "adx_direcao", "WIN$N", ExecutionProfile()))
    json.dumps(d, allow_nan=False)
    assert d["busca_id"] == bid and d["status"] == "concluida"
    assert set(d["mapas"]) == {"horario", "dias", "direcao"}
    m = d["mapas"]["horario"]
    assert len(m["casas"]) == len(m["linhas"]) * len(m["colunas"])
    assert all("evolucao" in c for c in m["casas"])
    assert d["de_txt"] == "feitos" and d["barra"] == 100


def test_fixos_da_busca_nova_mostram_stop_movel_e_trailing():
    p = ExecutionProfile(step_gatilho_pct=40, step_distancia_pct=10, trailing_pontos=150)
    f = dict(CB._fixos(p, "R$", True))
    assert set(f) == {"Filtro de mercado", "Sem entradas", "Custos", "Stop móvel", "Trailing"}
    assert f["Stop móvel"] == "40% / 10%" and f["Trailing"] == "150 pts"
    f = dict(CB._fixos(ExecutionProfile(), "R$", True))
    assert f["Stop móvel"] == "desligado" and f["Trailing"] == "desligado"
