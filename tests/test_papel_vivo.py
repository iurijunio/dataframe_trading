"""Papel ao vivo para as ordens (spec 2026-10-08-ao-vivo-ordens §3, §4,
§5.1): o desejado de cada ligação — posição, zerado ou indisponível — de um
retrato da configuração e de barras em memória, sem banco no caminho."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from core import ao_vivo, codigo, diario, papel
from core import db_manager as db
from core import ingest as ing
from core import papel_vivo as PV
from strategies.base import Signals
from tests.fabrica_ao_vivo import inserir_barras, ligacao_com_plano
from tests.test_ingest import write_export

SIMB = "WIN$N"
DIA = date(2026, 10, 9)
ONTEM = date(2026, 10, 8)
SINAL = datetime(2026, 10, 9, 10, 0)
ENTRADA = SINAL + timedelta(minutes=1)
AGORA = ENTRADA + timedelta(seconds=2)       # relógio do servidor
PROV = (ENTRADA, 189_100)                    # o minuto em formação
PERFIL = {"timeframe": "M1", "entrada_inicio": "09:00", "entrada_fim": "17:00",
          "fechamento": "17:50", "stop_tipo": "pontos", "stop_pontos": 200,
          "alvo_tipo": "pontos", "alvo_pontos": 400,
          "dias_semana": [1, 2, 3, 4, 5]}
# compra na abertura das 10:01 (189_100) com 1 tick de derrapagem
ENTRADA_PX = 189_105


# ------------------------------------------------------------------ dados
def _mod(sinal=SINAL):
    """Estratégia de mentira: compra no fechamento de `sinal`."""
    def signals(bars, params):
        z = np.zeros(len(bars["close"]), dtype=bool)
        el = bars["ts"] == np.datetime64(sinal, "ns")
        return Signals(el, z, z.copy(), z.copy())
    return SimpleNamespace(signals=signals)


def _quebrada():
    def signals(bars, params):
        raise RuntimeError("estratégia quebrou")
    return SimpleNamespace(signals=signals)


def _barras(dia: date, ate: datetime | None = None, base: int = 189_000):
    """De 09:00 até `ate` (inclusive; padrão 18:24), preço parado em `base`
    com 50 pontos de faixa — nem o stop (200) nem o alvo (400) são tocados."""
    ini = np.datetime64(datetime(dia.year, dia.month, dia.day, 9, 0), "ns")
    fim = np.datetime64(ate or datetime(dia.year, dia.month, dia.day, 18, 24),
                        "ns")
    ts = np.arange(ini, fim + np.timedelta64(1, "m"), np.timedelta64(1, "m"))
    n = len(ts)
    px = np.full(n, base, dtype=np.int64)
    return {"ts": ts, "open": px, "high": px + 50, "low": px - 50,
            "close": px.copy(), "tick_volume": np.zeros(n, np.int64),
            "volume": np.zeros(n, np.int64)}


AQUEC = _barras(ONTEM)
AQ2 = PV.Aquecimento(AQUEC, 2)       # 2 pregões: o da estratégia sem janela


@pytest.fixture
def base(tmp_path, monkeypatch):
    # cópia da fixture de tests/test_captura_processo.py
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    with db.connect_write() as con:
        db.init_schema(con)
        db.sync_instruments(con)
        ing.ingest_csv(con, write_export(tmp_path / "s.tsv", [
            (datetime(2026, 9, 30, 18, 24), 100000, 100050, 99950, 100010)]),
            "WIN$N")
    return tmp_path


@pytest.fixture
def inst():
    return db.load_instrument_yaml(SIMB)


@pytest.fixture
def mods(monkeypatch):
    """O módulo de cada estratégia, por nome — sem recarregar arquivo."""
    m = {"rompimento_canal": _mod(), "reversao_rsi": _mod()}
    monkeypatch.setattr(papel, "_modulo", lambda estrategia, h, cache: m[estrategia])
    return m


def _ligacao(nome, *, run_id=1, strategy="rompimento_canal", fase="demo",
             contratos_demo=3, **perfil):
    f = ligacao_com_plano(nome, params={}, profile={**PERFIL, **perfil},
                          contratos=1, run_id=run_id, strategy=strategy,
                          agora=datetime(2026, 9, 1, 10),
                          adicionado_em="2026-09-01 09:00")
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET fase = ?, contratos_demo = ? "
                    "WHERE ligacao_id = ?", [fase, contratos_demo, f.lig])
    return f


@pytest.fixture
def lig(base, mods):
    return _ligacao("vivo-a")


def _retrato(agora=AGORA):
    with db.connect(read_only=True) as con:
        return PV.ler_retrato(con, DIA, agora, {})


def _desejados(ret, inst, *, hoje=None, prov=PROV, agora=AGORA, aquec=AQ2):
    hoje = _barras(DIA, SINAL) if hoje is None else hoje
    return PV.desejados(ret, aquec, hoje, prov, inst, agora)


# ------------------------------------------------------------------ estados
def test_posicao_quando_o_papel_tem_aberta_e_a_ligacao_opera(lig, inst):
    cid = ao_vivo.criar_conta("demo-1", "demo", 500.0, login=4321,
                              servidor="Corretora-DEMO")
    ao_vivo.definir_contas(lig.pf, cid, None)
    ret = _retrato()
    lv = ret.ligacoes[lig.lig]
    assert (lv.status, lv.falha, lv.fase, lv.ligada) == ("rodando", None,
                                                         "demo", True)
    assert (lv.portfolio_id, lv.conta_id, lv.contratos_conta) == (lig.pf, cid, 3)
    assert lv.plano["plano_id"] == lig.plano_id and lv.modulo is not None
    assert lv.desvio == 15        # 1 tick de derrapagem do plano + 2 ticks
    assert ret.portfolio_de == {lig.lig: lig.pf}
    assert ret.contas == {cid: {"login": 4321, "servidor": "Corretora-DEMO",
                                "limite": 500.0, "envio": False, "tipo": "demo"}}
    assert (ret.dia, ret.lido_em) == (DIA, AGORA)

    des, ok = _desejados(ret, inst)
    assert ok
    assert des == {lig.lig: PV.Desejado(
        PV.POSICAO, lado=1, entry_ts=ENTRADA, entry_px=ENTRADA_PX,
        stop_px=ENTRADA_PX - 200, alvo_px=ENTRADA_PX + 400, contratos=3)}

    # contratos da conta em branco: os do plano
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET contratos_demo = NULL")
    des, _ = _desejados(_retrato(), inst)
    assert des[lig.lig].contratos == 1


def test_sem_a_barra_provisoria_ainda_nao_ha_posicao(lig, inst):
    # o sinal das 10:00 só vira entrada com o minuto seguinte na mão
    des, ok = _desejados(_retrato(), inst, prov=None)
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO)


def test_zerado_quando_a_ligacao_esta_desligada_agora(lig, inst):
    ao_vivo.desligar_membro(lig.lig)
    with db.connect_write() as con:
        # o diário com a hora das 10:20: a entrada das 10:01 CONTA no papel
        con.execute("UPDATE ao_vivo_eventos SET quando = ? WHERE ligacao_id = ? "
                    "AND tipo = 'membro_desligado'",
                    [datetime(2026, 10, 9, 10, 20), lig.lig])
    agora = datetime(2026, 10, 9, 10, 21, 1)
    hoje = _barras(DIA, datetime(2026, 10, 9, 10, 20))
    prov = (datetime(2026, 10, 9, 10, 21), 189_000)
    ret = _retrato(agora)
    lv = ret.ligacoes[lig.lig]
    assert lv.ligada is False
    assert papel._conta(ENTRADA, lv.periodos)          # contou no papel

    des, ok = _desejados(ret, inst, hoje=hoje, prov=prov, agora=agora)
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO, motivo="desligada")
    # a única razão é o estado de agora: ligada, a mesma conta dá posição
    lv.ligada = True
    des, _ = _desejados(ret, inst, hoje=hoje, prov=prov, agora=agora)
    assert des[lig.lig].estado == PV.POSICAO
    assert des[lig.lig].entry_ts == ENTRADA

    # portfólio desligado com a ligação ligada: também zerado
    ao_vivo.ligar_membro(lig.lig)
    ao_vivo.desligar_portfolio(lig.pf)
    ret = _retrato(agora)
    assert ret.ligacoes[lig.lig].ligada is False
    des, _ = _desejados(ret, inst, hoje=hoje, prov=prov, agora=agora)
    assert des[lig.lig] == PV.Desejado(PV.ZERADO, motivo="desligada")


def test_zerado_quando_fase_nao_e_demo(base, mods, inst):
    f = _ligacao("vivo-papel", fase="papel")
    ret = _retrato()
    assert ret.ligacoes[f.lig].fase == "papel"
    des, ok = _desejados(ret, inst)
    assert ok and des[f.lig] == PV.Desejado(PV.ZERADO, motivo="fase papel")


def test_zerado_quando_a_entrada_nao_conta(lig, inst):
    # desligada às 09:30 e religada às 10:01:30: a entrada das 10:01 caiu no
    # buraco — o papel a tem aberta, mas ela não é da ligação
    with db.connect_write() as con:
        diario.registrar(con, "membro_desligado", "usuario", portfolio_id=lig.pf,
                         ligacao_id=lig.lig, quando=datetime(2026, 10, 9, 9, 30))
        diario.registrar(con, "membro_ligado", "usuario", portfolio_id=lig.pf,
                         ligacao_id=lig.lig,
                         quando=datetime(2026, 10, 9, 10, 1, 30))
    ret = _retrato()
    assert ret.ligacoes[lig.lig].ligada is True
    des, ok = _desejados(ret, inst)
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO)


def test_zerado_quando_pulado_ou_sem_plano(lig, inst, monkeypatch):
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET vale_a_partir = '2027-01-01'")
    ret = _retrato()
    assert ret.ligacoes[lig.lig].status == "pulado"
    assert ret.ligacoes[lig.lig].plano is None
    des, ok = _desejados(ret, inst)
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO,
                                              motivo="sem plano em vigor")

    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET vale_a_partir = '2026-09-02'")
    monkeypatch.setattr(codigo, "hash_estrategia", lambda *a, **k: "outro")
    des, ok = _desejados(_retrato(), inst)
    assert ok and des[lig.lig] == PV.Desejado(
        PV.ZERADO, motivo="código mudou desde o plano")


def test_indisponivel_sem_aquecimento_ou_sem_relogio(lig, inst):
    ret = _retrato()
    assert _desejados(ret, inst, aquec=None) == ({}, False)
    assert _desejados(ret, inst, agora=None) == ({}, False)
    assert PV.desejados(ret, AQ2, None, PROV, inst, AGORA) == ({}, False)
    assert PV.desejados(None, AQ2, _barras(DIA, SINAL), PROV, inst,
                        AGORA) == ({}, False)
    # retrato de ontem com o relógio de hoje (virada do dia): velho
    amanha = AGORA + timedelta(days=1)
    hoje_amanha = _barras(amanha.date(), SINAL + timedelta(days=1))
    assert _desejados(ret, inst, agora=amanha, hoje=hoje_amanha,
                      prov=(ENTRADA + timedelta(days=1), 189_100)) == ({}, False)
    # e com tudo na mão, disponível
    assert _desejados(ret, inst)[1] is True


def test_indisponivel_so_da_ligacao_cujo_calculo_falhou(lig, mods, inst):
    mods["reversao_rsi"] = _quebrada()
    outra = _ligacao("vivo-b", run_id=2, strategy="reversao_rsi")
    des, ok = _desejados(_retrato(), inst)
    assert ok
    assert des[outra.lig].estado == PV.INDISPONIVEL
    assert des[outra.lig].motivo == "falha no cálculo: estratégia quebrou"
    assert des[lig.lig].estado == PV.POSICAO
    assert des[lig.lig].entry_ts == ENTRADA


def test_preparo_com_falha_e_indisponivel_nunca_zerado(lig, inst, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("disco ilegível")
    monkeypatch.setattr(codigo, "hash_estrategia", quebra)
    ret = _retrato()
    lv = ret.ligacoes[lig.lig]
    assert lv.falha == "falha no cálculo: disco ilegível"
    des, ok = _desejados(ret, inst)
    assert ok and des[lig.lig] == PV.Desejado(
        PV.INDISPONIVEL, motivo="falha no cálculo: disco ilegível")


def test_duas_abertas_vale_a_mais_nova(lig, inst, monkeypatch):
    """O motor tem uma posição por vez; se o cálculo devolvesse duas abertas,
    a mais velha é "operação anterior que não saiu" e a reconciliação sai
    dela pelo ticket (§5.1) — o desejado é a mais nova."""
    def op(hhmm, px):
        ts = datetime.combine(DIA, datetime.strptime(hhmm, "%H:%M").time())
        return {"entry_ts": ts, "aberta": True, "side": 1, "entry_px": px,
                "stop_px": px - 200, "alvo_px": px + 400,
                "stop_ini_px": px - 200, "alvo_ini_px": px + 400}
    monkeypatch.setattr(papel, "calcular", lambda *a, **k: [
        op("09:31", 188_000), op("10:01", 189_105)])
    des, ok = _desejados(_retrato(), inst, prov=None)
    assert ok and des[lig.lig].entry_ts == ENTRADA
    assert des[lig.lig].entry_px == 189_105


# ------------------------------------------------- stop em vigor no minuto
def test_breakeven_da_provisoria_nao_move_o_stop_antes_do_backtest(
        base, mods, inst):
    """Entrou às 10:01; a provisória das 10:06 abre 200 pontos acima. O motor
    roda o breakeven no fim de toda barra, inclusive da provisória — mas no
    backtest o stop só sobe no fim do minuto 10:06. Durante ele vale o stop
    do fim das 10:05."""
    f = _ligacao("vivo-be", breakeven_pct=25)      # 25% do alvo = 100 pontos
    hoje = _barras(DIA, datetime(2026, 10, 9, 10, 5))
    prov = (datetime(2026, 10, 9, 10, 6), 189_200)
    agora = datetime(2026, 10, 9, 10, 6, 1)
    ret = _retrato(agora)
    # sem isto o teste não mede nada: a conta com a provisória move o stop
    com = papel.com_barra_provisoria(PV._juntar(AQUEC, hoje), *prov)
    calc = papel.calcular(com, DIA, ret.ligacoes[f.lig].plano, mods[
        "rompimento_canal"], inst, None, True)
    entrada_px = 189_005
    assert calc[-1]["aberta"] and calc[-1]["stop_px"] == entrada_px

    des, ok = _desejados(ret, inst, hoje=hoje, prov=prov, agora=agora)
    assert ok and des[f.lig] == PV.Desejado(
        PV.POSICAO, lado=1, entry_ts=ENTRADA, entry_px=entrada_px,
        stop_px=entrada_px - 200, alvo_px=entrada_px + 400, contratos=3)


def test_entrada_na_provisoria_usa_o_stop_inicial(base, mods, inst):
    """Entrou agora, na provisória: o stop móvel do fim dela ainda não vale."""
    f = _ligacao("vivo-trail", trailing_pontos=150)
    ret = _retrato()
    com = papel.com_barra_provisoria(PV._juntar(AQUEC, _barras(DIA, SINAL)),
                                     *PROV)
    calc = papel.calcular(com, DIA, ret.ligacoes[f.lig].plano,
                          mods["rompimento_canal"], inst, None, True)
    assert calc[-1]["stop_px"] > ENTRADA_PX - 200     # o trailing já subiu
    des, ok = _desejados(ret, inst)
    assert ok and des[f.lig].stop_px == ENTRADA_PX - 200
    assert des[f.lig].alvo_px == ENTRADA_PX + 400


# ------------------------------------------------------------ barras de hoje
def test_barras_de_hoje_converte_o_dataframe_do_mt5():
    df = pl.DataFrame({
        "ts": [datetime(2026, 10, 9, 9, 0), datetime(2026, 10, 9, 9, 1),
               datetime(2026, 10, 9, 9, 2)],
        "open": [189_000.0, 189_005.0, 188_999.9999],
        "high": [189_050.0, 189_060.0, 189_010.0],
        "low": [188_950.0, 188_990.0, 188_900.0],
        "close": [189_005.0, 189_000.0, 188_950.0],
        "tick_volume": [10.0, 12.0, 7.0],
        "volume": [3.0, 4.0, 0.0],
        "spread": [5, 5, 5]})
    b = PV.barras_de_hoje(df)
    assert set(b) == {"ts", "open", "high", "low", "close", "tick_volume",
                      "volume"}
    assert b["ts"].dtype == np.dtype("datetime64[ns]")
    assert b["ts"].tolist() == [np.datetime64("2026-10-09T09:00", "ns").item(),
                                np.datetime64("2026-10-09T09:01", "ns").item(),
                                np.datetime64("2026-10-09T09:02", "ns").item()]
    for c in ("open", "high", "low", "close", "tick_volume", "volume"):
        assert b[c].dtype == np.int64, c
    assert b["open"].tolist() == [189_000, 189_005, 189_000]
    assert b["high"].tolist() == [189_050, 189_060, 189_010]
    assert b["low"].tolist() == [188_950, 188_990, 188_900]
    assert b["close"].tolist() == [189_005, 189_000, 188_950]
    assert b["tick_volume"].tolist() == [10, 12, 7]
    assert b["volume"].tolist() == [3, 4, 0]


# ------------------------------------------------- igual ao papel gravado
def _df(b: dict) -> pl.DataFrame:
    """As barras como o MT5 as devolve (`mt5_source.barras_de_taxas`)."""
    return pl.DataFrame({"ts": b["ts"].astype("datetime64[us]"),
                         **{c: b[c].astype(float) for c in
                            ("open", "high", "low", "close", "tick_volume",
                             "volume")}})


def test_igual_ao_papel_gravado(lig, inst):
    """O mesmo instante pelos dois caminhos — o do banco (`rodar_dia`, a
    tela) e o da memória (`desejados`, a ordem) — dá a mesma operação."""
    with db.connect_write() as con:
        inserir_barras(con, AQUEC)
    dia_todo = _barras(DIA, datetime(2026, 10, 9, 10, 4))
    vistos = 0
    for k in range(4):
        ultimo = SINAL + timedelta(minutes=k)
        sl = slice(None, int(np.flatnonzero(
            dia_todo["ts"] == np.datetime64(ultimo, "ns"))[0]) + 1)
        hoje_b = {c: v[sl] for c, v in dia_todo.items()}
        # `inserir_barras` grava volume 1: o MT5 de mentira devolve o mesmo
        hoje_b["tick_volume"] = np.ones(len(hoje_b["ts"]), np.int64)
        hoje_b["volume"] = np.ones(len(hoje_b["ts"]), np.int64)
        with db.connect_write() as con:
            con.execute("DELETE FROM bars_m1 WHERE ts >= ?", [DIA])
            inserir_barras(con, hoje_b)
        minuto = ultimo + timedelta(minutes=1)
        prov = (minuto, 189_100)
        agora = minuto + timedelta(seconds=1)
        with db.connect(read_only=True) as con:
            ret = PV.ler_retrato(con, DIA, agora, {})
            aquec = PV.carregar_aquecimento(con, SIMB, DIA, ret)
            res = papel.rodar_dia(con, DIA, agora, {}, provisoria=prov)
            do_banco = papel.barras_do_dia(con, SIMB, DIA, 2)
        hoje = PV.barras_de_hoje(_df(hoje_b))
        # as barras da memória são as do banco
        assert aquec.pregoes == 2
        juntas = PV._juntar(aquec.barras, hoje)
        assert set(juntas) == set(do_banco)
        for c in do_banco:
            assert np.array_equal(juntas[c], do_banco[c]), c
        des, ok = PV.desejados(ret, aquec, hoje, prov, inst, agora)
        assert ok
        abertas = [o for o in res[0]["operacoes"] if o["aberta"] and o["conta"]]
        assert len(abertas) == 1, k
        o, d = abertas[0], des[lig.lig]
        assert d.estado == PV.POSICAO
        assert (d.entry_ts, d.lado, d.entry_px, d.stop_px, d.alvo_px) == (
            o["entry_ts"], o["side"], o["entry_px"], o["stop_px"],
            o["alvo_px"]), k
        assert d.entry_ts == ENTRADA
        vistos += 1
    assert vistos == 4


def test_carregar_aquecimento_sem_pregao_anterior_e_none(base, mods):
    with db.connect_write() as con:
        con.execute("DELETE FROM bars_m1")
    _ligacao("vivo-a")
    with db.connect(read_only=True) as con:
        ret = PV.ler_retrato(con, DIA, AGORA, {})
        assert PV.carregar_aquecimento(con, SIMB, DIA, ret) is None


def test_carregar_aquecimento_pega_os_pregoes_do_maior_aquecimento(base, mods):
    _ligacao("vivo-a")
    with db.connect_write() as con:
        for d in (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
                  ONTEM, DIA):
            inserir_barras(con, _barras(d, datetime.combine(
                d, datetime.min.time()) + timedelta(hours=9, minutes=4)))
    with db.connect(read_only=True) as con:
        ret = PV.ler_retrato(con, DIA, AGORA, {})
        aq = PV.carregar_aquecimento(con, SIMB, DIA, ret)
    assert aq.pregoes == 2
    b = aq.barras
    # estratégia sem janela: 0 + 2 de folga = os 2 pregões antes do dia
    datas = sorted({d for d in b["ts"].astype("datetime64[D]").tolist()})
    assert datas == [date(2026, 10, 7), ONTEM]


# ------------------------------------------- papel.rodar_dia com provisória
@pytest.fixture
def dia_ate_o_sinal(lig):
    with db.connect_write() as con:
        inserir_barras(con, AQUEC)
        inserir_barras(con, _barras(DIA, SINAL))
    return lig


def _ops_rodar(**kw):
    with db.connect(read_only=True) as con:
        res = papel.rodar_dia(con, DIA, AGORA, {}, **kw)
    return res[0]["operacoes"]


def test_rodar_dia_sem_provisoria_como_antes(dia_ate_o_sinal):
    assert _ops_rodar() == []
    assert _ops_rodar(provisoria=None) == []


def test_rodar_dia_encerrado_ignora_a_provisoria(dia_ate_o_sinal):
    assert _ops_rodar(provisoria=PROV, dia_encerrado=True) == []


def test_rodar_dia_ignora_provisoria_de_outro_dia(dia_ate_o_sinal):
    assert _ops_rodar(provisoria=(ENTRADA + timedelta(days=1), 189_100)) == []


def test_rodar_dia_com_provisoria_abre_no_minuto_em_formacao(dia_ate_o_sinal):
    ops = _ops_rodar(provisoria=PROV)
    assert len(ops) == 1
    o = ops[0]
    assert (o["entry_ts"], o["aberta"], o["conta"], o["side"]) == (
        ENTRADA, True, True, 1)
    assert o["entry_px"] == ENTRADA_PX
    assert o["stop_px"] == ENTRADA_PX - 200


# ------------------------------------------------ revisão, rodada 1
def _quebra_preparo(monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("disco ilegível")
    monkeypatch.setattr(codigo, "hash_estrategia", quebra)


def test_preparo_com_falha_e_desligada_e_zerado(lig, inst, monkeypatch):
    """Estratégia quebrada não pode prender a posição: desligar sai sem
    precisar de cálculo nenhum (spec §4/§5.1)."""
    _quebra_preparo(monkeypatch)
    ao_vivo.desligar_membro(lig.lig)
    ret = _retrato()
    assert ret.ligacoes[lig.lig].falha
    des, ok = _desejados(ret, inst)
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO, motivo="desligada")


def test_preparo_com_falha_e_fase_papel_e_zerado(lig, inst, monkeypatch):
    _quebra_preparo(monkeypatch)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET fase = 'papel'")
    ret = _retrato()
    assert ret.ligacoes[lig.lig].falha
    des, ok = _desejados(ret, inst)
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO, motivo="fase papel")


def _as(hh, mm, ss=0):
    return datetime(2026, 10, 9, hh, mm, ss)


def test_barras_de_hoje_cortadas_deixam_indisponivel(lig, inst):
    """Logo depois de reconectar o MT5 pode devolver o dia cortado: a
    operação das 10:01 sumiria do cálculo e a posição seria encerrada."""
    ret = _retrato(_as(10, 5, 1))

    def rodar(ate, prov, agora=_as(10, 5, 1)):
        hoje = _barras(DIA, ate) if ate else {
            k: v[:0] for k, v in _barras(DIA, SINAL).items()}
        return _desejados(ret, inst, hoje=hoje, prov=prov, agora=agora)
    # normal: até 10:04, provisória 10:05 — posição
    des, ok = rodar(_as(10, 4), (_as(10, 5), 189_000))
    assert ok and des[lig.lig].estado == PV.POSICAO
    assert des[lig.lig].entry_ts == ENTRADA
    # cortado às 09:58 com a provisória das 10:05: não se sabe
    assert rodar(_as(9, 58), (_as(10, 5), 189_000)) == ({}, False)
    # vazio às 10:30
    assert rodar(None, (_as(10, 30), 189_000), agora=_as(10, 30, 1)) == (
        {}, False)
    # um minuto atrasado é tolerado (sem provisória); dois, não
    des, ok = rodar(_as(10, 3), None)
    assert ok and des[lig.lig].estado == PV.POSICAO
    assert rodar(_as(10, 2), None) == ({}, False)
    # provisória que não cola (falta o 10:04): buraco, não se sabe
    assert rodar(_as(10, 3), (_as(10, 5), 189_000)) == ({}, False)
    # antes das 09:01 o dia vazio é normal
    des, ok = rodar(None, (_as(9, 0), 189_000), agora=_as(9, 0, 30))
    assert ok and des[lig.lig] == PV.Desejado(PV.ZERADO)


def test_aquecimento_insuficiente_so_para_quem_precisa_de_mais(lig, mods, inst):
    # declara 1695 barras: ⌈1695 / 565⌉ + 2 = 5 pregões
    mods["reversao_rsi"] = SimpleNamespace(signals=_mod().signals,
                                           aquecimento_barras=lambda p: 1695)
    outra = _ligacao("vivo-longa", run_id=2, strategy="reversao_rsi")
    ret = _retrato()
    assert PV.pregoes_necessarios(ret) == 5
    des, ok = _desejados(ret, inst, aquec=PV.Aquecimento(AQUEC, 2))
    assert ok
    assert des[outra.lig] == PV.Desejado(PV.INDISPONIVEL,
                                         motivo="aquecimento insuficiente")
    assert des[lig.lig].estado == PV.POSICAO
    # relido com 5 pregões, as duas calculam
    des, _ = _desejados(ret, inst, aquec=PV.Aquecimento(AQUEC, 5))
    assert des[outra.lig].estado == PV.POSICAO
    assert des[lig.lig].estado == PV.POSICAO

# ------------------------------------------------------- zerado no toque
def _pos(lado, stop=189_000, alvo=189_400, entrada=189_200):
    return PV.Desejado(PV.POSICAO, lado=lado, entry_ts=ENTRADA,
                       entry_px=entrada, stop_px=stop, alvo_px=alvo,
                       contratos=2)


def test_toque_compra_stop_zera_com_motivo_e_campos():
    d = _pos(1)
    out = PV.aplicar_toque({1: d}, maxima=189_250, minima=189_000)
    assert out[1] == PV.Desejado(PV.ZERADO, lado=1, entry_ts=ENTRADA,
                                 entry_px=189_200, stop_px=189_000,
                                 alvo_px=189_400, contratos=2,
                                 motivo="stop no toque")
    assert out[1].toque_em is None


def test_toque_compra_alvo_zera():
    out = PV.aplicar_toque({1: _pos(1)}, maxima=189_400, minima=189_100)
    assert out[1].estado == PV.ZERADO and out[1].motivo == "alvo no toque"
    assert out[1].alvo_px == 189_400


def test_toque_venda_stop_e_alvo():
    venda = _pos(-1, stop=189_400, alvo=189_000, entrada=189_200)
    out = PV.aplicar_toque({1: venda}, maxima=189_400, minima=189_100)
    assert (out[1].estado, out[1].motivo) == (PV.ZERADO, "stop no toque")
    out = PV.aplicar_toque({1: venda}, maxima=189_300, minima=189_000)
    assert (out[1].estado, out[1].motivo) == (PV.ZERADO, "alvo no toque")


def test_toque_stop_tem_prioridade_sobre_alvo():
    out = PV.aplicar_toque({1: _pos(1)}, maxima=189_500, minima=188_900)
    assert out[1].motivo == "stop no toque"
    venda = _pos(-1, stop=189_400, alvo=189_000)
    out = PV.aplicar_toque({1: venda}, maxima=189_500, minima=188_900)
    assert out[1].motivo == "stop no toque"


def test_sem_toque_ou_sem_maxima_minima_nao_mexe():
    d = _pos(1)
    assert PV.aplicar_toque({1: d}, 189_300, 189_100)[1] is d
    assert PV.aplicar_toque({1: d}, None, 188_000)[1] is d
    assert PV.aplicar_toque({1: d}, 189_900, None)[1] is d
    sem_nada = PV.Desejado(PV.POSICAO, lado=1, stop_px=None, alvo_px=None)
    assert PV.aplicar_toque({1: sem_nada}, 189_900, 188_000)[1] is sem_nada


def test_outros_estados_nao_mudam():
    zer = PV.Desejado(PV.ZERADO, motivo="desligada")
    ind = PV.Desejado(PV.INDISPONIVEL, motivo="falha")
    out = PV.aplicar_toque({1: zer, 2: ind}, 190_000, 188_000)
    assert out == {1: zer, 2: ind}


def test_toque_nao_altera_o_dict_de_entrada():
    entrada = {1: _pos(1)}
    copia = dict(entrada)
    out = PV.aplicar_toque(entrada, 189_250, 189_000)
    assert entrada == copia and entrada[1].estado == PV.POSICAO
    assert out is not entrada and out[1].estado == PV.ZERADO
    assert PV.Desejado(PV.ZERADO).toque_em is None


def test_aplicar_toque_vigia_o_stop_mesmo_sem_alvo():
    from core.papel_vivo import aplicar_toque, Desejado, POSICAO, ZERADO
    d = {1: Desejado(POSICAO, lado=1, stop_px=100, alvo_px=None)}
    assert aplicar_toque(d, 120, 95)[1].estado == ZERADO
    d = {1: Desejado(POSICAO, lado=-1, stop_px=None, alvo_px=80)}
    assert aplicar_toque(d, 90, 80)[1].motivo == "alvo no toque"
