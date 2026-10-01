"""Selo da captura no topo e o "Sincronizar com MT5" travado com ela ativa.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6–7.
As regras de `situacao` são testadas com estados montados à mão; nenhum
teste lê o `data/ao_vivo/estado.json` real.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from dash import no_update

from ui.components import pregao_panel as PP

# quinta-feira, 10:00 — dentro do pregão
AGORA = datetime(2026, 10, 1, 10, 0)


@pytest.fixture(autouse=True)
def _estado_limpo(monkeypatch):
    # globais de módulo: sem isto um teste vaza estado para o seguinte
    from ui import data as D
    monkeypatch.setattr(D, "_estado_ultimo", None)
    monkeypatch.setattr(D, "_conferencia_vista", None)


def _estado(**mudar):
    """Captura saudável, atualizada há 5 s, no pregão de hoje."""
    e = {
        "pid": 1, "atualizado_em": (AGORA - timedelta(seconds=5)).isoformat(),
        "mt5": "conectado", "mt5_desde": None,
        "conta": {"login": 1, "servidor": "X"}, "contrato_vigente": None,
        "simbolo": "WIN$N", "fechamento_esperado": "18:24", "em_pregao": True,
        "ultimo_salvo": "2026-10-01T09:58:00", "em_formacao": None,
        "lacunas_hoje": [], "gravados_hoje": 60, "recuperados_hoje": 0,
        "revisados_hoje": 0, "conferencia": {"status": "pendente"},
        "banco_ocupado_desde": None, "relogio_desvio_s": None,
        "primeiro_candle_hoje": "2026-10-01T09:00:00", "erro": None,
    }
    e.update(mudar)
    return e


# ---- regras de situacao, na ordem ----

def test_regra1_sem_estado_captura_nunca_rodou():
    s = PP.situacao(None, AGORA)
    assert s["tom"] == "ambar"
    assert "nunca rodou" in s["texto"]
    assert "iniciar.bat" in s["acao"]
    assert s["ativa"] is False


def test_regra2_estado_velho_no_pregao_e_parada_rosa():
    e = _estado(atualizado_em=(AGORA - timedelta(minutes=7)).isoformat(),
                em_pregao=False)  # o serviço morto não sabe dizer: vale o relógio
    s = PP.situacao(e, AGORA)
    assert s["tom"] == "rosa"
    assert s["texto"] == "Captura parada há 7 min"
    assert "Dataframe - Captura" in s["acao"]
    assert s["ativa"] is False and s["pregao"] is True


def test_regra2_estado_velho_fora_do_pregao_e_cinza():
    noite = datetime(2026, 10, 1, 21, 0)
    e = _estado(atualizado_em=(noite - timedelta(hours=2)).isoformat(),
                em_pregao=True)
    s = PP.situacao(e, noite)
    assert s["tom"] == "cinza"
    assert s["texto"] == "Captura parada (fora do pregão)"
    assert s["ativa"] is False and s["pregao"] is False


def test_regra2_usa_o_fechamento_do_estado():
    # 18:20 com fechamento 17:54 (+6 min de folga) já é fora do pregão
    tarde = datetime(2026, 10, 1, 18, 20)
    e = _estado(atualizado_em=(tarde - timedelta(minutes=5)).isoformat(),
                fechamento_esperado="17:54")
    assert PP.situacao(e, tarde)["tom"] == "cinza"
    e["fechamento_esperado"] = "18:24"
    assert PP.situacao(e, tarde)["tom"] == "rosa"


def test_regra2_estado_velho_com_erro_mostra_o_erro_mesmo_fora_do_pregao():
    # código 3: o serviço grava o erro e sai; a mensagem fica numa janela
    # minimizada — a tela é o único lugar onde o usuário vai vê-la
    noite = datetime(2026, 10, 1, 21, 0)
    e = {"pid": 9, "atualizado_em": (noite - timedelta(hours=1)).isoformat(),
         "mt5": "fechado", "erro": "o MT5 não tem o símbolo WIN$N"}
    s = PP.situacao(e, noite)
    assert s["tom"] == "rosa"
    assert "o MT5 não tem o símbolo WIN$N" in s["texto"]
    assert s["ativa"] is False


def test_regra3_erro_e_rosa_com_o_texto_do_erro():
    s = PP.situacao(_estado(erro="disco cheio"), AGORA)
    assert s["tom"] == "rosa"
    assert "disco cheio" in s["texto"]
    assert s["ativa"] is True


def test_regra4_mt5_fechado():
    s = PP.situacao(_estado(mt5="fechado"), AGORA)
    assert s["tom"] == "rosa"
    assert s["texto"] == "MT5 fechado"
    assert "recupera" in s["acao"]


def test_regra5_sem_conexao_desde():
    s = PP.situacao(_estado(mt5="sem_conexao",
                            mt5_desde="2026-10-01T09:42:10"), AGORA)
    assert s["tom"] == "ambar"
    assert s["texto"] == "Sem conexão com a corretora desde 09:42"


def test_regra6_banco_ocupado_so_depois_de_2_min():
    pouco = _estado(banco_ocupado_desde=(AGORA - timedelta(seconds=90)).isoformat())
    assert PP.situacao(pouco, AGORA)["tom"] == "verde"
    muito = _estado(banco_ocupado_desde=(AGORA - timedelta(seconds=200)).isoformat())
    s = PP.situacao(muito, AGORA)
    assert s["tom"] == "ambar"
    assert s["texto"] == "Banco ocupado há 3 min"
    assert "nada se perde" in s["acao"]


def test_regra7_relogio_adiantado_e_atrasado():
    s = PP.situacao(_estado(relogio_desvio_s=45.2), AGORA)
    assert s["tom"] == "ambar"
    assert s["texto"] == "Relógio do PC adiantado 45 s"
    assert "Sincronizar agora" in s["acao"]
    s = PP.situacao(_estado(relogio_desvio_s=-72.7), AGORA)
    assert s["texto"] == "Relógio do PC atrasado 73 s"


def test_regra7_desvio_pequeno_e_ruido():
    assert PP.situacao(_estado(relogio_desvio_s=20.0), AGORA)["tom"] == "verde"


def test_regra8_sem_candle_hoje_antes_e_depois_das_10():
    cedo = datetime(2026, 10, 1, 9, 30)
    e = _estado(atualizado_em=cedo.isoformat(), primeiro_candle_hoje=None)
    s = PP.situacao(e, cedo)
    assert (s["tom"], s["texto"]) == ("cinza", "Aguardando a abertura")
    e = _estado(primeiro_candle_hoje=None)
    s = PP.situacao(e, AGORA)
    assert (s["tom"], s["texto"]) == ("cinza", "Sem pregão hoje (feriado?)")
    assert s["ativa"] is True


def test_regra8_candle_de_ontem_nao_conta_como_de_hoje():
    e = _estado(primeiro_candle_hoje="2026-09-30T09:00:00")
    assert PP.situacao(e, AGORA)["texto"] == "Sem pregão hoje (feriado?)"


def test_regra9_captura_ativa_no_pregao_e_fora():
    s = PP.situacao(_estado(), AGORA)
    assert (s["tom"], s["texto"]) == ("verde", "Captura ativa")
    assert s["ativa"] is True and s["pregao"] is True
    noite = datetime(2026, 10, 1, 21, 0)
    e = _estado(atualizado_em=noite.isoformat(), em_pregao=False)
    s = PP.situacao(e, noite)
    assert (s["tom"], s["texto"]) == ("verde", "Captura ativa — mercado fechado")
    assert s["pregao"] is False


def test_captura_ativa_limite_de_60_s():
    assert PP.captura_ativa(None, AGORA) is False
    e = _estado(atualizado_em=(AGORA - timedelta(seconds=59)).isoformat())
    assert PP.captura_ativa(e, AGORA) is True
    e = _estado(atualizado_em=(AGORA - timedelta(seconds=61)).isoformat())
    assert PP.captura_ativa(e, AGORA) is False
    assert PP.captura_ativa({"mt5": "conectado"}, AGORA) is False


def test_selo_some_no_cinza_e_aparece_com_tom():
    _, _, estilo = PP.selo({"tom": "cinza", "texto": "x", "acao": None,
                            "ativa": False, "pregao": False})
    assert estilo == {"display": "none"}
    filhos, classe, estilo = PP.selo(PP.situacao(_estado(), AGORA))
    assert classe == "captura-selo captura-selo-verde"
    assert estilo == {}
    assert "Captura ativa" in str(filhos)


# ---- leitura do estado.json ----

def test_estado_captura_guarda_a_ultima_leitura_valida(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    assert D.estado_captura() is None
    p.write_text('{"mt5": "conectado"}', encoding="utf-8")
    assert D.estado_captura() == {"mt5": "conectado"}
    p.write_text("{meio", encoding="utf-8")
    assert D.estado_captura() == {"mt5": "conectado"}


def test_estado_captura_arquivo_apagado_volta_a_none(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    p.write_text('{"mt5": "conectado"}', encoding="utf-8")
    D.estado_captura()
    p.unlink()
    assert D.estado_captura() is None


def test_conferencia_nova_limpa_o_cache_de_barras(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    p.write_text('{"conferencia": {"em": "2026-10-01T18:30:00"}}', encoding="utf-8")
    D.estado_captura()
    D._bars_cache["WIN$N"] = {"x": 1}
    D.estado_captura()                      # mesma conferência: cache intacto
    assert "WIN$N" in D._bars_cache
    p.write_text('{"conferencia": {"em": "2026-10-02T18:30:00"}}', encoding="utf-8")
    D.estado_captura()
    assert "WIN$N" not in D._bars_cache


def test_conferencia_pendente_no_meio_nao_apaga_a_memoria(tmp_path, monkeypatch):
    # o serviço reabre com a conferência "pendente" (sem "em"); a seguinte
    # ainda tem de limpar o cache
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    p.write_text('{"conferencia": {"em": "2026-10-01T18:30:00"}}', encoding="utf-8")
    D.estado_captura()
    p.write_text('{"conferencia": {"status": "pendente"}}', encoding="utf-8")
    D.estado_captura()
    D._bars_cache["WIN$N"] = {"x": 1}
    p.write_text('{"conferencia": {"em": "2026-10-02T18:30:00"}}', encoding="utf-8")
    D.estado_captura()
    assert "WIN$N" not in D._bars_cache


def test_primeira_leitura_nao_limpa_o_cache(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    D._bars_cache["WIN$N"] = {"x": 1}
    try:
        p.write_text('{"conferencia": {"em": "2026-10-01T18:30:00"}}', encoding="utf-8")
        D.estado_captura()
        assert "WIN$N" in D._bars_cache
    finally:
        D._bars_cache.pop("WIN$N", None)


def test_bars_devolve_o_que_carregou_mesmo_com_clear_no_meio(monkeypatch):
    # o Flask atende em várias threads: um clear() entre guardar e devolver
    # não pode virar KeyError
    from ui import data as D
    carregado = {"ts": [1]}

    def prepare(con, symbol):
        return carregado

    class _Cache(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            self.clear()

    monkeypatch.setattr(D, "prepare_bars", prepare)
    monkeypatch.setattr(D, "_bars_cache", _Cache())

    class _Con:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(D.db, "connect", lambda read_only=True: _Con())
    assert D.bars("WIN$N") is carregado


# ---- Sincronizar com MT5 ----

def test_sincronizar_recusa_com_a_captura_ativa(monkeypatch):
    from ui import callbacks_mt5 as CM
    monkeypatch.setattr(CM.D, "estado_captura",
                        lambda: {"atualizado_em": datetime.now().isoformat()})
    assert "captura" in CM.motivo_bloqueio()
    monkeypatch.setattr(CM.D, "estado_captura", lambda: None)
    assert CM.motivo_bloqueio() is None


def test_sincronizar_com_captura_ativa_nao_chama_o_mt5(monkeypatch):
    from ui import callbacks_mt5 as CM
    monkeypatch.setattr(CM.D, "estado_captura",
                        lambda: {"atualizado_em": datetime.now().isoformat()})

    def explode(*a, **k):
        raise AssertionError("não devia sincronizar")

    monkeypatch.setattr(CM.src, "sincronizar", explode)
    monkeypatch.setattr(CM.db, "connect_write", explode)
    saida = CM.executar_sincronizacao("WIN$N")
    assert "captura" in saida[0]
    assert saida[1] == "mt5-sync-status"
    assert saida[2:] == (no_update, no_update, no_update)


# ---- calendário do Backtest ----

def test_calendario_so_muda_com_conferencia_nova(monkeypatch):
    from ui import callbacks_pregao as CP
    fim = datetime(2026, 10, 1, 18, 23)
    monkeypatch.setattr(CP.D, "span", lambda s: (datetime(2021, 3, 16, 9, 0), fim))
    estado = {"conferencia": {"status": "concluida", "em": "2026-10-01T18:40:00"}}

    saida = CP.calendario(estado, "2026-09-30T18:40:00", "WIN$N")
    assert saida == (fim.date(), fim.date(), fim.date(), "2026-10-01T18:40:00")

    saida = CP.calendario(estado, "2026-10-01T18:40:00", "WIN$N")
    assert saida == (no_update,) * 4


def test_calendario_primeira_vista_so_abre_o_limite(monkeypatch):
    # logo depois de abrir a página não troca a data que o usuário escolheu;
    # só deixa escolher até o último dia gravado
    from ui import callbacks_pregao as CP
    fim = datetime(2026, 10, 1, 18, 23)
    monkeypatch.setattr(CP.D, "span", lambda s: (datetime(2021, 3, 16, 9, 0), fim))
    estado = {"conferencia": {"status": "concluida", "em": "2026-10-01T18:40:00"}}
    saida = CP.calendario(estado, None, "WIN$N")
    assert saida == (no_update, fim.date(), fim.date(), "2026-10-01T18:40:00")
    assert CP.calendario(None, None, "WIN$N") == (no_update,) * 4
    assert CP.calendario({"conferencia": {"status": "pendente"}}, None,
                         "WIN$N") == (no_update,) * 4
