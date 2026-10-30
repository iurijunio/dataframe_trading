"""Perfil padrao por ativo (camada 4) e recusa da janela que cruza a pausa."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from dash import no_update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ativo, db_manager as db  # noqa: E402
from ui import callbacks as CB  # noqa: E402
from ui.app import build  # noqa: E402
from ui.components import controls  # noqa: E402


def _valor(comp, id_):
    """Procura, na arvore de componentes, o `value` do componente com esse id."""
    achado = []

    def visita(c):
        if getattr(c, "id", None) == id_ and hasattr(c, "value"):
            achado.append(c.value)
        filhos = getattr(c, "children", None)
        if isinstance(filhos, (list, tuple)):
            for x in filhos:
                visita(x)
        elif filhos is not None:
            visita(filhos)

    visita(comp)
    return achado[0]


def _achar(comp, id_):
    achado = []

    def visita(c):
        if getattr(c, "id", None) == id_:
            achado.append(c)
        filhos = getattr(c, "children", None)
        if isinstance(filhos, (list, tuple)):
            for x in filhos:
                visita(x)
        elif filhos is not None:
            visita(filhos)

    visita(comp)
    assert achado, f"componente {id_} nao encontrado na camada 4"
    return achado[0]


def test_perfil_win_igual_aos_padroes_da_tela():
    p = ativo.perfil_padrao(ativo.ficha("WIN$N"))
    tela = controls.execucao()
    ids = {"entrada_inicio": "e-ent-ini", "entrada_fim": "e-ent-fim",
           "fechamento": "e-fechamento", "corretagem": "e-corretagem",
           "emolumentos": "e-emolumentos", "slippage_ticks": "e-slippage",
           "stop_pontos": {"type": "val", "p": "stop_pontos"},
           "alvo_pontos": {"type": "val", "p": "alvo_pontos"}}
    assert set(p) == set(ids)
    for chave, cid in ids.items():
        assert _achar(tela, cid).value == p[chave], chave


def test_win_com_perfil_padrao_continua_identidade():
    cfg = db.load_instrument_yaml("WIN$N")
    assert ativo.instrumento_para_motor(cfg, ativo.ficha_do_instrumento(cfg)) is cfg


def test_mes_tem_perfil_de_ny():
    p = ativo.perfil_padrao(ativo.ficha("MES"))
    assert (p["entrada_inicio"], p["entrada_fim"], p["fechamento"]) == ("18:00", "16:30", "16:50")
    assert (p["corretagem"], p["emolumentos"], p["slippage_ticks"]) == (0.60, 0.0, 1)
    assert (p["stop_pontos"], p["alvo_pontos"]) == (8, 16)
    q = ativo.perfil_padrao(ativo.ficha("MNQ"))
    assert (q["stop_pontos"], q["alvo_pontos"]) == (45, 90)


def test_janela_16h_19h_ny_recusada():
    msg = ativo.janela_valida("16:00", "19:00", ativo.ficha("MES"))
    assert msg


def test_janela_horario_malformado_nao_levanta():
    f = ativo.ficha("MES")
    assert ativo.janela_valida("9h", "16:30", f) == "horário inválido"
    assert ativo.janela_valida("", "16:30", f) == "horário inválido"


def test_janela_ny_normal_e_win_aceitos():
    assert ativo.janela_valida("18:00", "16:30", ativo.ficha("MES")) is None
    assert ativo.janela_valida("09:00", "17:00", ativo.ficha("WIN$N")) is None
    assert ativo.janela_valida("17:00", "09:00", ativo.ficha("WIN$N"))


def test_fechamento_validado_mes():
    mes = ativo.ficha("MES")
    assert ativo.janela_valida("09:30", "15:00", mes, "16:00") is None
    assert ativo.janela_valida("09:30", "15:00", mes, "17:00") is None
    assert ativo.janela_valida("09:30", "15:00", mes, "") is None
    assert ativo.janela_valida("09:30", "15:00", mes, None) is None
    assert ativo.janela_valida("09:30", "15:00", mes, "14:00")        # antes do fim
    assert ativo.janela_valida("09:30", "15:00", mes, "17:30")        # na pausa
    assert ativo.janela_valida("09:30", "15:00", mes, "17:59")
    assert ativo.janela_valida("09:30", "15:00", mes, "18:00")       # inicio do pregao seguinte
    assert ativo.janela_valida("09:30", "15:00", mes, "9h") == "horário inválido"


def test_fechamento_win_aceito():
    win = ativo.ficha("WIN$N")
    assert ativo.janela_valida("09:00", "17:00", win, "17:30") is None
    assert ativo.janela_valida("09:00", "17:00", win, "") is None
    assert ativo.janela_valida("09:00", "17:00", win, None) is None


@pytest.fixture
def app(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, src_ingest_id) "
                "VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00' "
                f"+ INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")
    return build()


def _callback(app, saida):
    for k, v in app.callback_map.items():
        if k.startswith("..") and k.strip(".").split("...")[0].startswith(saida):
            f = v["callback"]
            return getattr(f, "__wrapped__", f)  # a funcao do usuario, sem o contexto do Dash
    raise AssertionError(saida)


def test_callback_aplica_perfil_do_ativo(app, monkeypatch):
    from core.optimizer import MINERACAO
    monkeypatch.setattr(MINERACAO, "estado", {"rodando": False, "trials": []})
    cb = _callback(app, "e-ent-ini.value")
    # perfil (6) + stop e alvo; o resto da camada 4 em test_faixas_tela
    mes = cb("MES")
    assert tuple(mes)[:8] == ("18:00", "16:30", "16:50", 0.60, 0.0, 1, 8, 16)
    win = cb("WIN$N")
    assert tuple(win)[:8] == ("09:00", "17:00", "17:30", 0.50, 0.27, 1, 300, 600)


def test_rodar_param_invalido_devolve_oito_saidas(app):
    rodar = _callback(app, "store-run.data")
    n = len(rodar.__code__.co_varnames[:rodar.__code__.co_argcount])
    args = [None] * n
    from strategies import registry
    mod = registry.atual()
    nome, meta = next((k, m) for k, m in mod.params_schema.items() if m.get("min") is not None)
    args[5], args[6] = [meta["min"] - 1], [{"type": "val", "p": nome}]  # abaixo do minimo
    r = rodar(*args)
    assert len(r) == 8
    assert r[1] is not no_update
