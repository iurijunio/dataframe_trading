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


# ---- sub-tela Pregão ----

def _textos(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(_textos(x) for x in c)
    return _textos(getattr(c, "children", None))


def test_idade_tom_quatro_faixas():
    assert PP.idade_tom(10, False) == "cinza"
    assert PP.idade_tom(500, False) == "cinza"
    assert PP.idade_tom(90, True) == "verde"
    assert PP.idade_tom(91, True) == "ambar"
    assert PP.idade_tom(180, True) == "ambar"
    assert PP.idade_tom(181, True) == "rosa"


def test_tick_formacao_sem_candle_em_formacao_e_none():
    assert PP.tick_formacao(_estado(), "M1", []) is None
    assert PP.tick_formacao(None, "M1", []) is None


def test_tick_formacao_m1_e_o_proprio_candle():
    from ui import data as D
    e = _estado(em_formacao={"ts": "2026-10-01T09:59:00", "open": 10.0,
                             "high": 12.0, "low": 9.0, "close": 11.0})
    t = PP.tick_formacao(e, "M1", [])
    assert t == {"id": "preco", "bar": {
        "time": D.to_epoch(datetime(2026, 10, 1, 9, 59)),
        "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}}


def test_tick_formacao_m5_soma_o_balde_e_o_minuto_em_formacao():
    from ui import data as D
    e = _estado(em_formacao={"ts": "2026-10-01T09:57:00", "open": 103.0,
                             "high": 104.0, "low": 102.0, "close": 103.5})
    balde = [
        {"ts": datetime(2026, 10, 1, 9, 55), "open": 100.0, "high": 106.0,
         "low": 99.0, "close": 101.0},
        {"ts": datetime(2026, 10, 1, 9, 56), "open": 101.0, "high": 102.0,
         "low": 97.0, "close": 103.0},
    ]
    t = PP.tick_formacao(e, "M5", balde)
    assert t == {"id": "preco", "bar": {
        "time": D.to_epoch(datetime(2026, 10, 1, 9, 55)),
        "open": 100.0, "high": 106.0, "low": 97.0, "close": 103.5}}


def test_tick_formacao_m15_balde_vazio_abre_no_minuto_em_formacao():
    from ui import data as D
    e = _estado(em_formacao={"ts": "2026-10-01T10:00:00", "open": 50.0,
                             "high": 51.0, "low": 49.0, "close": 50.5})
    t = PP.tick_formacao(e, "M15", [])
    assert t["bar"] == {"time": D.to_epoch(datetime(2026, 10, 1, 10, 0)),
                        "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.5}


def test_inicio_do_balde():
    assert PP.inicio_balde(datetime(2026, 10, 1, 10, 14), "M15") == datetime(2026, 10, 1, 10, 0)
    assert PP.inicio_balde(datetime(2026, 10, 1, 10, 14), "M5") == datetime(2026, 10, 1, 10, 10)
    assert PP.inicio_balde(datetime(2026, 10, 1, 10, 14), "M1") == datetime(2026, 10, 1, 10, 14)


def test_faixa_no_pregao_mostra_os_quatro_cartoes_e_as_lacunas():
    e = _estado(lacunas_hoje=["2026-10-01T09:30:00", "2026-10-01T09:31:00"])
    t = _textos(PP.faixa(e, AGORA))
    for rotulo in ("Captura", "MT5", "Último candle", "Lacunas hoje"):
        assert rotulo in t
    assert "em operação" in t
    assert "conectado" in t
    assert "09:58" in t
    assert "2 minutos faltando" in t
    assert "Mercado fechado" not in t


def test_faixa_fora_do_pregao_diz_mercado_fechado():
    noite = datetime(2026, 10, 1, 21, 0)
    e = _estado(atualizado_em=noite.isoformat(), em_pregao=False,
                ultimo_salvo="2026-10-01T18:23:00")
    t = _textos(PP.faixa(e, noite))
    assert "Mercado fechado" in t


def test_faixa_com_problema_mostra_a_frase_e_o_que_fazer():
    e = _estado(mt5="fechado")
    t = _textos(PP.faixa(e, AGORA))
    assert "MT5 fechado" in t and "faça login" in t
    assert "nunca rodou" in _textos(PP.faixa(None, AGORA))


def test_ultimo_candle_de_ontem_e_cinza_aguardando_a_abertura():
    cedo = datetime(2026, 10, 1, 9, 2)
    e = _estado(atualizado_em=cedo.isoformat(), primeiro_candle_hoje=None,
                ultimo_salvo="2026-09-30T18:23:00")
    c = PP.cartao_ultimo(e, cedo)
    assert c["tom"] == "cinza"
    assert "aguardando a abertura" in c["nota"]
    assert "30/09" in c["valor"]


def test_ultimo_candle_idade_conta_do_fechamento_do_minuto():
    # o candle das 09:58 fecha às 09:59; às 10:00 tem 60 s
    c = PP.cartao_ultimo(_estado(), AGORA)
    assert c["tom"] == "verde"
    assert c["valor"] == "09:58"
    assert "60 s" in c["nota"]
    c = PP.cartao_ultimo(_estado(ultimo_salvo="2026-10-01T09:55:00"), AGORA)
    assert c["tom"] == "rosa"


def test_placar_conferencia():
    t = _textos(PP.placar(_estado(gravados_hoje=60, recuperados_hoje=3,
                                  revisados_hoje=2)))
    for rotulo in ("Gravados hoje", "Recuperados", "Correções da corretora",
                   "Conferência do dia", "pendente"):
        assert rotulo in t
    t = _textos(PP.placar(_estado(conferencia={
        "status": "concluida", "em": "2026-10-01T18:40:12",
        "dias": ["2026-10-01"]})))
    assert "concluída às 18:40" in t
    t = _textos(PP.placar(_estado(conferencia={
        "status": "falhou", "em": "2026-10-01T18:40:12", "erro": "x"})))
    assert "falhou — tenta de novo em 5 min" in t
    assert "—" in _textos(PP.placar(None))


def test_dia_do_pregao():
    from datetime import date
    from ui import data as D
    assert D.dia_do_pregao(_estado()) == date(2026, 10, 1)
    assert D.dia_do_pregao({"ultimo_salvo": None}) == date.today()
    assert D.dia_do_pregao(None) == date.today()


def test_dia_do_pregao_sem_estado_usa_o_ultimo_dia_do_banco():
    from datetime import date
    from core import db_manager as db
    from ui import data as D
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-09-29 "
                    "18:23:00', 1, 1, 1, 1, 1)")
    assert D.dia_do_pregao(None) == date(2026, 9, 29)
    # estado velho (captura parada há dias) não esconde o que o banco já tem
    assert D.dia_do_pregao({"ultimo_salvo": "2026-09-25T18:23:00"}) == date(2026, 9, 29)


@pytest.fixture
def _banco_com_barras(_banco_isolado):
    # o layout lê barras na montagem (mesma semente de test_callbacks_sem_ciclo)
    from core import db_manager as db
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00'"
                f" + INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")


def test_nenhum_callback_escreve_series_e_tick_juntos(_banco_com_barras):
    # escrever `series` refaz o gráfico e joga fora o zoom do usuário; o
    # pulso de 2 s só pode mexer no `tick`
    from ui.app import build
    app = build()
    saidas = [chave for chave in app.callback_map]
    com_tick = [c for c in saidas if "av-pg-grafico.tick" in c]
    assert com_tick, "o pulso tem de escrever o tick do gráfico"
    assert any("av-pg-grafico.series" in c for c in saidas)
    for c in saidas:
        assert not ("av-pg-grafico.series" in c and "av-pg-grafico.tick" in c), c


def test_juntar_poe_o_candle_em_formacao_no_fim_da_serie():
    from ui import callbacks_pregao as CP
    velhos = [{"time": 60, "close": 1}, {"time": 120, "close": 2}]
    assert CP.juntar(velhos, None) == velhos
    assert CP.juntar(velhos, {"time": 120, "close": 9})[-1] == {"time": 120, "close": 9}
    assert len(CP.juntar(velhos, {"time": 120, "close": 9})) == 2
    assert CP.juntar(velhos, {"time": 180, "close": 3})[-1]["time"] == 180
    assert CP.juntar(velhos, {"time": 60, "close": 5}) == velhos
    assert CP.juntar([], {"time": 60, "close": 5}) == [{"time": 60, "close": 5}]


def test_tick_agora_com_a_captura_parada_nao_desenha_retrato_velho():
    from ui import callbacks_pregao as CP
    f = {"ts": "2026-10-01T09:59:00", "open": 1.0, "high": 2.0, "low": 0.5,
         "close": 1.5}
    viva = _estado(em_formacao=f)
    assert CP.tick_agora(viva, "M1", AGORA)["bar"]["close"] == 1.5
    parada = _estado(em_formacao=f,
                     atualizado_em=(AGORA - timedelta(minutes=5)).isoformat())
    assert CP.tick_agora(parada, "M1", AGORA) is None


def test_tick_agora_m5_le_do_banco_so_o_balde_atual(monkeypatch):
    from ui import callbacks_pregao as CP
    pedidos = []

    def m1(simbolo, inicio, fim):
        pedidos.append((simbolo, inicio, fim))
        return [{"ts": datetime(2026, 10, 1, 9, 55), "open": 7.0, "high": 9.0,
                 "low": 6.0, "close": 8.0}]

    monkeypatch.setattr(CP.D, "m1_fechados", m1)
    e = _estado(em_formacao={"ts": "2026-10-01T09:57:00", "open": 8.0,
                             "high": 8.5, "low": 7.5, "close": 8.2})
    t = CP.tick_agora(e, "M5", AGORA)
    assert pedidos == [("WIN$N", datetime(2026, 10, 1, 9, 55),
                        datetime(2026, 10, 1, 9, 57))]
    assert (t["bar"]["open"], t["bar"]["high"], t["bar"]["low"]) == (7.0, 9.0, 6.0)


def test_tick_formacao_ignora_candles_fora_do_balde():
    # a leitura do banco e o estado.json não são do mesmo instante: um M1 do
    # balde anterior (ou o próprio minuto, já gravado) não entra na conta
    e = _estado(em_formacao={"ts": "2026-10-01T09:57:00", "open": 103.0,
                             "high": 104.0, "low": 102.0, "close": 103.5})
    balde = [
        {"ts": datetime(2026, 10, 1, 9, 54), "open": 1.0, "high": 999.0,
         "low": 0.0, "close": 1.0},
        {"ts": datetime(2026, 10, 1, 9, 55), "open": 100.0, "high": 104.0,
         "low": 101.0, "close": 101.0},
        {"ts": datetime(2026, 10, 1, 9, 57), "open": 5.0, "high": 500.0,
         "low": 5.0, "close": 5.0},
    ]
    b = PP.tick_formacao(e, "M5", balde)["bar"]
    assert (b["open"], b["high"], b["low"]) == (100.0, 104.0, 101.0)
    assert PP.tick_formacao(e, "M1", balde)["bar"]["high"] == 104.0


def test_voltar_para_agora_muda_a_cada_pedido():
    # o gráfico ignora um comando igual ao anterior: sem o nonce, o segundo
    # clique em "Voltar para agora" não faria nada
    from ui import callbacks_pregao as CP
    a = CP.voltar_para_agora()
    b = CP.voltar_para_agora()
    assert a["action"] == "scrollToPosition" and a["animated"] is False
    assert a["position"] == 6
    assert a["nonce"] != b["nonce"]


def test_janela_inicial_termina_no_candle_mais_novo():
    from ui import callbacks_pregao as CP
    # 1 min, dia cheio: as últimas 120 barras, com a folga de 6 à direita
    assert CP.janela_inicial(560) == {"from": 440, "to": 565}
    # 5 min: o dia inteiro cabe
    assert CP.janela_inicial(112) == {"from": 0, "to": 117}
    # 15 min no começo do dia: largura mínima, sem candle gigante
    assert CP.janela_inicial(13) == {"from": -22, "to": 18}
