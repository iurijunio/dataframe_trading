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
    assert [o["rotulo"] for o in tf["opcoes"]][-1] == "M60"     # o protótipo escreve M60
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
def test_ir_regiao_escreve_faixas_e_volta_para_a_varredura():
    r = {"timeframe": "M15", "entrada_inicio": "10:00", "entrada_fim": "11:30",
         "dias_semana": [2, 4], "direcao": "venda", "stop_tipo": "atr",
         "alvo_tipo": "multiplicador",
         "campos": {"di_periodo": {"on": True, "de": 10, "ate": 20, "passo": 1, "valor": 14},
                    "stop_atr_mult": {"on": False, "de": 1.5, "ate": 1.5, "passo": 0.25,
                                      "valor": 1.5}}}
    ids_val = [{"p": "di_periodo"}, {"p": "stop_atr_mult"}, {"p": "outro"}]
    ids_on = [{"p": "di_periodo"}, {"p": "stop_atr_mult"}, {"p": "outro"}]
    ids_opt = [{"p": "di_periodo", "k": "de"}, {"p": "di_periodo", "k": "ate"},
               {"p": "outro", "k": "de"}]
    out = CB._ir_regiao(r, ids_val, [1, 2, 3], ids_on, [[], [], ["on"]], ids_opt, [0, 0, 9])
    val, on, opt = out[0], out[1], out[2]
    assert val == [14, 1.5, 3] and on == [["on"], [], ["on"]] and opt == [10, 20, 9]
    assert out[3:10] == ("M15", "10:00", "11:30", [2, 4], "venda", "atr", "multiplicador")
    assert out[14] == "varredura"


def test_ir_backtest_leva_o_corte_e_nao_nasce_editado():
    from ui.callbacks import _linha_combinacao, _menu_atual

    cb = {"params": {"di_periodo": 33}, "de": "2021-03-16T00:00:00",
          "ate": "2026-11-03T23:59:59", "fim_otimizacao": "2025-11-08T23:59:59",
          "perfil": ExecutionProfile(timeframe="M2", entrada_inicio="13:00",
                                     entrada_fim="13:30", dias_semana=(2, 5),
                                     stop_tipo="percentual", stop_pct=0.5,
                                     alvo_tipo="multiplicador", alvo_razao=3.5).to_config()}
    ids_val = [{"p": "di_periodo"}, {"p": "stop_pct"}, {"p": "alvo_razao"}]
    menu = {"ativo": "WIN$N", "e-capital": 10000}
    out = CB._ir_backtest(cb, 3, ids_val, [14, 0.2, 2.0], [], [], [], [], 4, menu)
    assert out[0] == [33, 0.5, 3.5]
    assert out[3:12] == ("M2", "13:00", "13:30", [2, 5], "ambas", "percentual",
                         "multiplicador", "2021-03-16", "2026-11-03")
    assert out[12] == ["on"] and out[13] == 5 and out[14] == "backtest"
    store = out[15]
    assert store["origem"] == "busca" and store["corte"] == "2025-11-08T23:59:59"
    # o menu logo depois do clique é igual à foto: a linha não nasce "editado"
    depois = _menu_atual(ids_val, out[0], ["on"], {
        **menu, "e-timeframe": "M2", "e-ent-ini": "13:00", "e-ent-fim": "13:30",
        "e-dias": [2, 5], "e-direcao": "ambas", "e-stop-tipo": "percentual",
        "e-alvo-tipo": "multiplicador", "d-de": "2021-03-16", "d-ate": "2026-11-03"})
    assert "editado" not in _linha_combinacao(store, depois)


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
