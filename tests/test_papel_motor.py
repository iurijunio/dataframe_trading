# tests/test_papel_motor.py
"""O motor do papel (spec Ao vivo › papel §4): idêntico ao backtest por
construção, recalculado inteiro a cada minuto a partir dos candles do dia."""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import codigo, diario, metrics, papel, plano, variantes  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import portfolio as P  # noqa: E402
from core.engine import kernel as K  # noqa: E402
from core.engine.execution import ExecutionProfile, run_strategy  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

SIMB = "WIN$N"
ESTRAT = "rompimento_canal"
# o stop do PLANO (123) é diferente do stop do perfil base (300): é assim
# que a montagem prova que usou a separação do walk-forward
PARAMS = {"periodo_canal": 20, "folga_ticks": 0, "filtro_amplitude": 0,
          "stop_pontos": 123}
PERFIL = ExecutionProfile(timeframe="M5", stop_pontos=300, alvo_pontos=400,
                          corretagem_por_contrato=0.5,
                          emolumentos_por_contrato=0.25).to_config()
CONTRATOS = 2


# ------------------------------------------------------------- dados
def _dias_uteis(n, inicio=date(2026, 1, 5)):
    out, d = [], inicio
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _barras_sinteticas(n_dias=40, seed=11):
    """Pregões de 09:00 a 18:24 (565 minutos), tendência do dia + ruído, de
    5 em 5 pontos como o WIN."""
    rng = np.random.default_rng(seed)
    dias = _dias_uteis(n_dias)
    ts, o, h, l, c = [], [], [], [], []
    preco = 120_000
    for dia in dias:
        tendencia = rng.normal(0, 6)
        preco += int(rng.normal(0, 150)) // 5 * 5
        inicio = np.datetime64(dia) + np.timedelta64(9 * 60, "m")
        for m in range(565):
            ab = preco
            fe = ab + int(round((tendencia + rng.normal(0, 30)) / 5)) * 5
            ts.append(inicio + np.timedelta64(m, "m"))
            o.append(ab)
            c.append(fe)
            h.append(max(ab, fe) + int(abs(rng.normal(0, 15))) // 5 * 5)
            l.append(min(ab, fe) - int(abs(rng.normal(0, 15))) // 5 * 5)
            preco = fe
    n = len(ts)
    b = {"ts": np.array(ts, dtype="datetime64[ns]"),
         "open": np.array(o, np.int64), "high": np.array(h, np.int64),
         "low": np.array(l, np.int64), "close": np.array(c, np.int64),
         "tick_volume": np.ones(n, np.int64), "volume": np.ones(n, np.int64)}
    return b, dias


def _inserir(con, b, sl=slice(None)):
    ts = [str(x) for x in b["ts"][sl].astype("datetime64[s]")]
    cols = [b[c][sl].tolist() for c in ("open", "high", "low", "close")]
    if len(ts) == 1:
        con.execute("INSERT INTO bars_m1 VALUES (?, ?, ?, ?, ?, ?, 1, 1, 0, 1)",
                    [SIMB, ts[0], *(c[0] for c in cols)])
        return
    # parâmetro em lista é lento demais para 22 mil barras: vai por CSV
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     encoding="ascii") as f:
        f.write("ts,open,high,low,close\n")
        f.writelines(f"{t},{o},{h},{lo},{c}\n" for t, o, h, lo, c
                     in zip(ts, *cols))
        caminho = f.name
    try:
        con.execute(
            "INSERT INTO bars_m1 SELECT ?, ts, open, high, low, close, 1, 1, "
            f"0, 1 FROM read_csv({db._sql_str(Path(caminho).as_posix())}, "
            "header = true, columns = {'ts': 'TIMESTAMP', 'open': 'BIGINT', "
            "'high': 'BIGINT', 'low': 'BIGINT', 'close': 'BIGINT'})", [SIMB])
    finally:
        Path(caminho).unlink()


def _indices_do_dia(b, dia):
    return np.flatnonzero(b["ts"].astype("datetime64[D]") == np.datetime64(dia))


@pytest.fixture
def sem_pandas(monkeypatch):
    """O duckdb procura o pandas a cada `execute` com parâmetro; sem ele
    instalado, cada procura varre o sys.path (~2 ms). Nos testes de minuto
    a minuto isso eram 20 s de espera. `None` em sys.modules faz a
    procura falhar na hora — o resultado é o mesmo ImportError."""
    monkeypatch.setitem(sys.modules, "pandas", None)


class _Recargas(list):
    quebrar = False


@pytest.fixture(autouse=True)
def recargas(monkeypatch):
    """`importlib.reload` de verdade re-executaria `strategies.base` e a
    estratégia no meio da suíte (classe `Signals` nova para uns, velha para
    outros). Aqui só anota quem seria recarregado — e simula o arquivo com
    erro de sintaxe quando `quebrar`."""
    vistos = _Recargas()

    def falsa(mod):
        vistos.append(mod.__name__)
        if vistos.quebrar:
            raise SyntaxError("invalid syntax (rompimento_canal.py, line 1)")
        return mod
    monkeypatch.setattr(papel.importlib, "reload", falsa)
    return vistos


@pytest.fixture
def mundo(banco):
    b, dias = _barras_sinteticas()
    with db.connect() as con:
        _inserir(con, b)
    v = variantes.criar("romp-teste", ESTRAT)
    mineracao(1, variante_id=v)
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(
        params=PARAMS, profile=PERFIL, contratos=CONTRATOS,
        codigo_hash=codigo.hash_estrategia(ESTRAT)),
        agora=datetime(2025, 12, 1, 10))
    pf = P.criar("pf")
    lig = P.adicionar_variante(pf, v)
    with db.connect() as con:
        # adicionada e ligada bem antes dos pregões sintéticos
        con.execute("UPDATE portfolio_membros SET adicionado_em = "
                    "'2025-12-01 09:00'")
        con.execute("UPDATE portfolios SET ligado = true")
    return SimpleNamespace(barras=b, dias=dias, plano_id=pid, lig=lig, pf=pf,
                           v=v, inst=db.load_instrument_yaml(SIMB))


def _plano(pid):
    return plano.detalhes(pid)


def _mod(nome=ESTRAT):
    return __import__(f"strategies.{nome}", fromlist=["x"])


def _chave(ops):
    return [(o["entry_ts"], o["exit_ts"], o["side"], o["entry_px"],
             o["exit_px"], o["points"], round(o["liquido"], 6)) for o in ops]


def _historico(b, plano_d, mod, inst, dia):
    """O backtest sobre o histórico INTEIRO, só as entradas do dia."""
    estrat, perfil = papel.perfil_do_plano(plano_d)
    res = run_strategy(b, mod, estrat, perfil, inst)
    if res.n_trades == 0:
        return []
    din = metrics.monetize(res)
    t = res.trades
    sel = np.flatnonzero(t["entry_ts"].astype("datetime64[D]")
                         == np.datetime64(dia))
    return [(t["entry_ts"][i].astype("datetime64[us]").item(),
             t["exit_ts"][i].astype("datetime64[us]").item(),
             int(t["side"][i]), int(t["entry_px"][i]), int(t["exit_px"][i]),
             int(t["points"][i]), round(float(din["liquido"][i]), 6))
            for i in sel]


def _ops(con, lig, dia):
    cols = ("op_id", "entry_ts", "exit_ts", "side", "contratos", "entry_px",
            "exit_px", "points", "bruto", "custo", "liquido", "reason", "mae",
            "mfe", "stop_px", "alvo_px", "aberta", "conta", "plano_id")
    return [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM papel_operacoes WHERE ligacao_id = ? "
        "AND dia = ? ORDER BY entry_ts", [lig, dia]).fetchall()]


def _pregao(con, lig, dia):
    cols = ("plano_id", "codigo_hash", "motor_versao", "status", "motivo",
            "interrompido_em", "n_operacoes", "liquido", "checksum",
            "calculado_em")
    r = con.execute(f"SELECT {', '.join(cols)} FROM papel_pregoes "
                    "WHERE ligacao_id = ? AND dia = ?", [lig, dia]).fetchone()
    return dict(zip(cols, r)) if r else None


def _as(dia, hh, mm=0):
    return datetime.combine(dia, time(hh, mm))


# ------------------------------------------------------------- identidade
CONFIGS = {
    "canal-20-M5": (ESTRAT, {"periodo_canal": 20, "folga_ticks": 0,
                             "filtro_amplitude": 0},
                    dict(timeframe="M5")),
    "canal-150-M15-atr": (ESTRAT, {"periodo_canal": 150, "folga_ticks": 0,
                                   "filtro_amplitude": 0},
                          dict(timeframe="M15", stop_tipo="atr",
                               alvo_tipo="atr", stop_atr_periodo=20)),
    "rsi-tendencia-600-M15": ("reversao_rsi",
                              {"periodo_rsi": 2, "limite_extremo": 10,
                               "periodo_tendencia": 600, "periodo_saida": 5},
                              dict(timeframe="M15")),
    "cruzamento-200-M5-protecoes": ("setup_cruzamento",
                                    {"media_rapida": 9, "media_lenta": 200,
                                     "breakeven_pct": 30,
                                     "trailing_pontos": 150},
                                    dict(timeframe="M5")),
}


def _plano_cfg(nome):
    estrategia, params, perfil = CONFIGS[nome]
    return estrategia, {"params": params, "contratos": 1,
                        "profile": ExecutionProfile(**perfil).to_config()}


@pytest.mark.parametrize("nome", list(CONFIGS))
def test_identidade_com_o_backtest_do_historico_inteiro(mundo, nome):
    estrategia, plano_d = _plano_cfg(nome)
    mod = _mod(estrategia)
    estrat, perfil = papel.perfil_do_plano(plano_d)
    n_preg = papel.pregoes_de_aquecimento(mod, estrat, perfil)
    total = 0
    with db.connect(read_only=True) as con:
        for dia in mundo.dias[-5:]:
            barras = papel.barras_do_dia(con, SIMB, dia, n_preg)
            ops = papel.calcular(barras, dia, plano_d, mod, mundo.inst, None)
            assert not any(o["aberta"] for o in ops)   # dia inteiro: nada aberto
            esperado = _historico(mundo.barras, plano_d, mod, mundo.inst, dia)
            assert _chave(ops) == esperado, dia
            total += len(ops)
    assert total > 0          # sem operação nenhuma o teste não prova nada


def test_aquecimento_calculado_cobre_o_minimo_necessario(mundo):
    estrategia, plano_d = _plano_cfg("rsi-tendencia-600-M15")
    mod = _mod(estrategia)
    estrat, perfil = papel.perfil_do_plano(plano_d)
    calc = papel.pregoes_de_aquecimento(mod, estrat, perfil)
    assert calc == 18          # ⌈600 × 15 / 565⌉ + 2
    dias = mundo.dias[-5:]
    esperado = {d: _historico(mundo.barras, plano_d, mod, mundo.inst, d)
                for d in dias}
    with db.connect(read_only=True) as con:
        def igual(p):
            return all(
                _chave(papel.calcular(papel.barras_do_dia(con, SIMB, d, p),
                                      d, plano_d, mod, mundo.inst, None))
                == esperado[d] for d in dias)
        ok = {p: igual(p) for p in range(0, calc + 1)}
    minimo = min(p for p in ok if all(ok[q] for q in range(p, calc + 1)))
    # pouco aquecimento ERRA (senão o teste não mede nada) e o calculado
    # está do lado certo do mínimo
    assert minimo > 1, f"mínimo necessário: {minimo}"
    assert calc >= minimo, f"mínimo necessário: {minimo}, calculado: {calc}"


def test_aquecimento_estrategia_que_declara(mundo):
    estrategia, plano_d = _plano_cfg("canal-20-M5")
    estrat, perfil = papel.perfil_do_plano(plano_d)
    mod = SimpleNamespace(aquecimento_barras=lambda p: 1130)
    # declarado tem prioridade sobre os nomes dos parâmetros: 1130 × 5 / 565
    assert papel.pregoes_de_aquecimento(mod, estrat, perfil) == 12
    sem = SimpleNamespace()
    assert papel.pregoes_de_aquecimento(sem, estrat, perfil) == 3


def test_aquecimento_soma_o_atr_do_perfil():
    perfil = ExecutionProfile(timeframe="M15", stop_tipo="atr",
                              stop_atr_periodo=40, alvo_tipo="atr",
                              alvo_atr_periodo=60)
    # ⌈(400 × 15 + 60 × 15) / 565⌉ + 2 = ⌈12,2⌉ + 2
    assert papel.pregoes_de_aquecimento(
        SimpleNamespace(), {"periodo_canal": 400, "folga_ticks": 7},
        perfil) == 15


# ------------------------------------------------------------- montagem
def test_montagem_separa_execucao_de_estrategia():
    plano_d = {"params": {"periodo_canal": 20, "stop_pontos": 123,
                          "alvo_pontos": 456},
               "profile": ExecutionProfile(stop_pontos=300, alvo_pontos=600,
                                           contratos=9, timeframe="M5",
                                           modo_posicao="risco").to_config(),
               "contratos": 3}
    estrat, perfil = papel.perfil_do_plano(plano_d)
    assert estrat == {"periodo_canal": 20}
    assert (perfil.stop_pontos, perfil.alvo_pontos) == (123, 456)
    assert perfil.timeframe == "M5"
    assert (perfil.modo_posicao, perfil.contratos) == ("contratos_fixos", 3)


def test_rodar_dia_usa_stop_do_plano_e_nunca_from_config(mundo, monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("from_config devolve o perfil padrão sem avisar")
    monkeypatch.setattr(ExecutionProfile, "from_config", classmethod(proibido))
    vistos = []
    original = papel.run_strategy

    def espia(*a, **k):
        res = original(*a, **k)
        vistos.append(res)
        return res
    monkeypatch.setattr(papel, "run_strategy", espia)
    dia = mundo.dias[30]
    with db.connect() as con:
        res = papel.rodar_dia(con, dia, _as(dia, 19), {})
        papel.gravar(con, res, _as(dia, 19))
        ops = _ops(con, mundo.lig, dia)
    assert vistos and all(r.n_trades for r in vistos)
    assert all((r.sl_at_entry == 123).all() for r in vistos)
    assert ops and all(o["contratos"] == CONTRATOS for o in ops)
    assert all(abs(o["entry_px"] - o["stop_px"]) == 123 for o in ops)


# ------------------------------------------------------------- aberta
def _operacao_longa(mundo):
    """Um dia e uma operação que dura vários minutos e NÃO sai por fechamento
    (sai por stop, alvo ou sinal) — a que o minuto a minuto precisa pegar."""
    p = _plano(mundo.plano_id)
    for dia in mundo.dias[10:]:
        with db.connect(read_only=True) as con:
            barras = papel.barras_do_dia(con, SIMB, dia, 3)
        res = run_strategy(barras, _mod(), *papel.perfil_do_plano(p),
                           mundo.inst)
        t = res.trades
        for i in range(res.n_trades):
            if (t["entry_ts"][i].astype("datetime64[D]") == np.datetime64(dia)
                    and t["reason"][i] not in (K.EXIT_CLOSE_TIME,
                                               K.EXIT_DATA_END)
                    and t["exit_i"][i] - t["entry_i"][i] >= 4):
                return dia, barras, int(t["entry_i"][i]), int(t["exit_i"][i])
    raise AssertionError("dados sintéticos sem operação longa")


def test_aberta_minuto_a_minuto_ate_a_saida_real(mundo):
    dia, barras, ent, sai = _operacao_longa(mundo)
    p = _plano(mundo.plano_id)
    final = {o["entry_ts"]: o for o in
             papel.calcular(barras, dia, p, _mod(), mundo.inst, None)}
    alvo_ts = barras["ts"][ent].astype("datetime64[us]").item()
    for k in range(ent, sai + 3):
        corte = {c: v[:k + 1] for c, v in barras.items()}
        ops = {o["entry_ts"]: o for o in
               papel.calcular(corte, dia, p, _mod(), mundo.inst, None)}
        o = ops[alvo_ts]
        if k < sai:
            assert o["aberta"], k
            assert o["exit_ts"] is None and o["exit_px"] is None
            assert o["liquido"] is not None and o["stop_px"]   # provisório
        else:
            assert not o["aberta"], k
            assert _chave([o]) == _chave([final[alvo_ts]])


def test_gravar_minuto_a_minuto_mantem_o_op_id(mundo, sem_pandas):
    dia, barras, ent, sai = _operacao_longa(mundo)
    idx = _indices_do_dia(mundo.barras, dia)
    alvo_ts = barras["ts"][ent].astype("datetime64[us]").item()
    with db.connect() as con:
        con.execute("DELETE FROM bars_m1 WHERE CAST(ts AS DATE) = ?", [dia])
        _inserir(con, mundo.barras, slice(idx[0], idx[0] + 1))
        ids, abertas = set(), []
        for g in idx[1:]:
            _inserir(con, mundo.barras, slice(g, g + 1))
            agora = mundo.barras["ts"][g].astype("datetime64[us]").item()
            if agora < alvo_ts - timedelta(minutes=2):
                continue
            if agora > alvo_ts + timedelta(minutes=sai - ent + 3):
                break
            papel.gravar(con, papel.rodar_dia(con, dia, agora, {}), agora)
            linhas = [o for o in _ops(con, mundo.lig, dia)
                      if o["entry_ts"] == alvo_ts]
            assert len(linhas) <= 1
            if linhas:
                ids.add(linhas[0]["op_id"])
                abertas.append(linhas[0]["aberta"])
    assert len(ids) == 1
    assert abertas[0] is True and abertas[-1] is False
    # aberta até a saída, depois fechada — e não volta a abrir
    assert abertas == sorted(abertas, reverse=True)


def test_queda_rodar_so_no_fim_igual_a_cada_minuto(mundo, sem_pandas):
    dia = mundo.dias[25]
    idx = _indices_do_dia(mundo.barras, dia)
    fim = _as(dia, 18, 30)
    with db.connect() as con:
        con.execute("DELETE FROM bars_m1 WHERE CAST(ts AS DATE) = ?", [dia])
        cache: dict = {}
        for g in idx:
            _inserir(con, mundo.barras, slice(g, g + 1))
            agora = mundo.barras["ts"][g].astype("datetime64[us]").item()
            papel.gravar(con, papel.rodar_dia(con, dia, agora, cache), agora)
        a_cada_minuto = _ops(con, mundo.lig, dia)
        pregao_a = _pregao(con, mundo.lig, dia)
        # recomeça do zero, inclusive a numeração, e roda uma vez só
        con.execute("DELETE FROM papel_operacoes")
        con.execute("DELETE FROM papel_pregoes")
        con.execute("DROP SEQUENCE seq_papel_op")
        con.execute("CREATE SEQUENCE seq_papel_op START 1")
        papel.gravar(con, papel.rodar_dia(con, dia, fim, {}), fim)
        so_no_fim = _ops(con, mundo.lig, dia)
        pregao_b = _pregao(con, mundo.lig, dia)
    assert a_cada_minuto and a_cada_minuto == so_no_fim
    # nenhuma operação fantasma consumiu número no caminho
    assert [o["op_id"] for o in so_no_fim] == list(
        range(1, len(so_no_fim) + 1))
    for c in ("plano_id", "status", "n_operacoes", "liquido"):
        assert pregao_a[c] == pregao_b[c], c


# ------------------------------------------------------------- plano do dia
def test_plano_do_dia_fica_fixo_no_pregao(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 10), {}),
                     _as(dia, 10))
        assert _pregao(con, mundo.lig, dia)["plano_id"] == mundo.plano_id
    # plano novo gravado no meio do pregão: vale amanhã
    novo = plano.salvar(**campos_plano(params=PARAMS, profile=PERFIL,
                                       contratos=5), agora=_as(dia, 10, 30))
    with db.connect() as con:
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 11), {}),
                     _as(dia, 11))
        assert _pregao(con, mundo.lig, dia)["plano_id"] == mundo.plano_id
        # mesmo que o banco diga que o novo já vale hoje (vínculo feito no
        # meio do dia), o pregão continua com o plano com que começou — e
        # a captura reiniciada (cache vazio) lê o gravado
        con.execute("UPDATE planos_operacao SET vale_a_partir = ? "
                    "WHERE plano_id = ?", [dia, novo])
        assert variantes.plano_em_vigor(mundo.v, dia, con=con)["plano_id"] \
            == novo
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), {}),
                     _as(dia, 12))
        assert _pregao(con, mundo.lig, dia)["plano_id"] == mundo.plano_id
        assert {o["plano_id"] for o in _ops(con, mundo.lig, dia)} \
            == {mundo.plano_id}
        assert {o["contratos"] for o in _ops(con, mundo.lig, dia)} \
            == {CONTRATOS}


def test_sem_plano_em_vigor_pulado(mundo):
    with db.connect() as con:
        con.execute("UPDATE planos_operacao SET vale_a_partir = '2027-01-01'")
        dia = mundo.dias[30]
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), {}),
                     _as(dia, 12))
        p = _pregao(con, mundo.lig, dia)
        assert (p["status"], p["motivo"]) == ("pulado", "sem plano em vigor")
        assert _ops(con, mundo.lig, dia) == []


# ------------------------------------------------------------- código
def _hash(monkeypatch, valor):
    monkeypatch.setattr(codigo, "hash_estrategia", lambda *a, **k: valor)


def test_codigo_mudou_antes_do_pregao_pulado(mundo, monkeypatch):
    _hash(monkeypatch, "outro")
    dia = mundo.dias[30]
    with db.connect() as con:
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), {}),
                     _as(dia, 12))
        p = _pregao(con, mundo.lig, dia)
        assert (p["status"], p["motivo"]) == ("pulado",
                                              "código mudou desde o plano")
        assert _ops(con, mundo.lig, dia) == []


def test_codigo_mudou_no_meio_interrompe_e_preserva(mundo, monkeypatch):
    dia = mundo.dias[30]
    idx = _indices_do_dia(mundo.barras, dia)
    real = codigo.hash_estrategia(ESTRAT)
    with db.connect() as con:
        con.execute("DELETE FROM bars_m1 WHERE CAST(ts AS DATE) = ?", [dia])
        _inserir(con, mundo.barras, slice(idx[0], idx[0] + 300))   # até ~14h
        cache: dict = {}
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 14), cache),
                     _as(dia, 14))
        manha = _ops(con, mundo.lig, dia)
        assert manha, "precisa de operação gravada de manhã"
        _hash(monkeypatch, "editado")
        _inserir(con, mundo.barras, slice(idx[0] + 300, idx[0] + 400))
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 15), cache),
                     _as(dia, 15))
        p = _pregao(con, mundo.lig, dia)
        assert p["status"] == "interrompido"
        assert p["interrompido_em"] == _as(dia, 15)
        assert p["codigo_hash"] == real      # o código que calculou o gravado
        assert _ops(con, mundo.lig, dia) == manha
        # congelado: nem o código de volta nem candle novo mudam nada
        _hash(monkeypatch, real)
        _inserir(con, mundo.barras, slice(idx[0] + 400, idx[-1] + 1))
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 18), cache),
                     _as(dia, 18))
        assert _ops(con, mundo.lig, dia) == manha
        assert _pregao(con, mundo.lig, dia) == p
        # o pregão seguinte, sem plano novo e com o código editado: pulado
        _hash(monkeypatch, "editado")
        prox = mundo.dias[31]
        papel.gravar(con, papel.rodar_dia(con, prox, _as(prox, 12), cache),
                     _as(prox, 12))
        assert _pregao(con, mundo.lig, prox)["status"] == "pulado"


def test_plano_sem_impressao_do_codigo_roda_com_aviso(mundo):
    with db.connect() as con:
        con.execute("UPDATE planos_operacao SET codigo_hash = NULL")
        dia = mundo.dias[30]
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 19), {}),
                     _as(dia, 19))
        p = _pregao(con, mundo.lig, dia)
        assert p["status"] == "rodando"
        assert p["motivo"] == "plano sem impressão do código"
        assert _ops(con, mundo.lig, dia)


def test_codigo_novo_no_disco_recarrega_o_modulo(mundo, recargas):
    real = codigo.hash_estrategia(ESTRAT)
    velho = SimpleNamespace(signals=None)        # quebraria se fosse usado
    cache = {ESTRAT: ("hash-antigo", velho)}
    dia = mundo.dias[30]
    with db.connect() as con:
        res = papel.rodar_dia(con, dia, _as(dia, 19), cache)
        assert recargas == ["strategies.base", f"strategies.{ESTRAT}"]
        assert res[0]["status"] == "rodando" and res[0]["operacoes"]
        assert cache[ESTRAT][0] == real
        assert cache[ESTRAT][1] is not velho
        assert cache[ESTRAT][1].__name__ == f"strategies.{ESTRAT}"
        # mesmo hash: não recarrega de novo
        papel.rodar_dia(con, dia, _as(dia, 19), cache)
        assert len(recargas) == 2


def test_recarga_que_falha_nao_se_repete_a_cada_minuto(mundo, recargas,
                                                       monkeypatch):
    dia = mundo.dias[30]
    with db.connect() as con:
        # plano sem hash: é o caso em que o código novo seria usado
        con.execute("UPDATE planos_operacao SET codigo_hash = NULL")
        cache = {ESTRAT: ("antigo", _mod())}
        recargas.quebrar = True
        _hash(monkeypatch, "quebrado")
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), cache),
                     _as(dia, 12))
        p = _pregao(con, mundo.lig, dia)
        assert p["motivo"].startswith("falha no cálculo")
        assert "SyntaxError" in p["motivo"] or "erro de sintaxe" in p["motivo"]
        n = len(recargas)
        assert n >= 1
        res = papel.rodar_dia(con, dia, _as(dia, 12, 1), cache)
        assert len(recargas) == n            # mesmo hash quebrado: não tenta
        # e não roda o módulo antigo como se fosse o arquivo novo
        assert res[0]["operacoes"] is None
        assert res[0]["motivo"].startswith("falha no cálculo")
        # o arquivo muda de novo (consertado): tenta, e volta a rodar
        recargas.quebrar = False
        _hash(monkeypatch, "consertado")
        res = papel.rodar_dia(con, dia, _as(dia, 12, 2), cache)
        assert len(recargas) > n
        assert res[0]["status"] == "rodando" and res[0]["operacoes"]


# ------------------------------------------------------------- interruptor
def test_interruptor_so_marca_o_que_conta(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        diario.registrar(con, "membro_desligado", "usuario",
                         portfolio_id=mundo.pf, ligacao_id=mundo.lig,
                         variante_id=mundo.v, quando=_as(dia, 11))
        con.execute("UPDATE portfolio_membros SET ligada = false")
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 19), {}),
                     _as(dia, 19))
        ops = _ops(con, mundo.lig, dia)
        p = _pregao(con, mundo.lig, dia)
    antes = [o for o in ops if o["entry_ts"] < _as(dia, 11)]
    depois = [o for o in ops if o["entry_ts"] >= _as(dia, 11)]
    assert antes and depois, "precisa de operação dos dois lados das 11h"
    assert all(o["conta"] for o in antes)
    assert not any(o["conta"] for o in depois)
    # calcula o dia inteiro mesmo desligada (decisão 4)
    assert len(ops) == len(_historico(mundo.barras, _plano(mundo.plano_id),
                                      _mod(), mundo.inst, dia))
    assert p["liquido"] == pytest.approx(sum(o["liquido"] for o in antes))
    assert p["n_operacoes"] == len(ops)


def test_periodos_ligados_combina_ligacao_e_portfolio(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        diario.registrar(con, "portfolio_desligado", "usuario",
                         portfolio_id=mundo.pf, quando=_as(dia, 10))
        diario.registrar(con, "portfolio_ligado", "usuario",
                         portfolio_id=mundo.pf, quando=_as(dia, 13))
        diario.registrar(con, "membro_desligado", "usuario",
                         ligacao_id=mundo.lig, quando=_as(dia, 15))
        diario.registrar(con, "membro_ligado", "usuario",
                         ligacao_id=mundo.lig, quando=_as(dia, 16))
        # outra ligação não interfere
        diario.registrar(con, "membro_desligado", "usuario",
                         ligacao_id=mundo.lig + 99, quando=_as(dia, 9))
        per = papel.periodos_ligados(con, mundo.lig, mundo.pf, dia)
    assert per == [(_as(dia, 0), _as(dia, 10)), (_as(dia, 13), _as(dia, 15)),
                   (_as(dia, 16), datetime.combine(dia + timedelta(days=1),
                                                   time()))]


def test_periodos_ligados_sem_eventos_usa_estado_atual_e_adicao(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = ?",
                    [_as(dia, 12)])
        assert papel.periodos_ligados(con, mundo.lig, mundo.pf, dia) == [
            (_as(dia, 12), datetime.combine(dia + timedelta(days=1), time()))]
        con.execute("UPDATE portfolios SET ligado = false")
        assert papel.periodos_ligados(con, mundo.lig, mundo.pf, dia) == []


# ------------------------------------------------------------- várias ligações
def test_mesma_variante_em_dois_portfolios_calcula_uma_vez(mundo, monkeypatch):
    pf2 = P.criar("pf2")
    lig2 = P.adicionar_variante(pf2, mundo.v)
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = "
                    "'2025-12-01 09:00'")
    chamadas = []
    original = papel.calcular
    monkeypatch.setattr(papel, "calcular",
                        lambda *a, **k: chamadas.append(1) or original(*a, **k))
    dia = mundo.dias[30]
    with db.connect() as con:
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 19), {}),
                     _as(dia, 19))
        a, b = _ops(con, mundo.lig, dia), _ops(con, lig2, dia)
    assert len(chamadas) == 1
    assert a and _chave(a) == _chave(b)
    assert not {o["op_id"] for o in a} & {o["op_id"] for o in b}
    # pf2 desligado: tudo calculado, nada conta
    assert all(o["conta"] for o in a) and not any(o["conta"] for o in b)


def test_plano_quebrado_nao_derruba_o_papel_das_outras_ligacoes(mundo):
    # perfil com campo que o motor não conhece: a montagem do perfil falha
    # (antes até do aquecimento) só para esta variante — spec §4.6
    v2 = variantes.criar("romp-quebrada", ESTRAT)
    mineracao(2, variante_id=v2)
    wfa(2, 2)
    plano.salvar(**campos_plano(
        wfa_id=2, run_id=2, params=PARAMS, contratos=CONTRATOS,
        profile={**PERFIL, "campo_que_nao_existe": 1},
        codigo_hash=codigo.hash_estrategia(ESTRAT)),
        agora=datetime(2025, 12, 1, 10))
    lig2 = P.adicionar_variante(mundo.pf, v2)
    with db.connect() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = "
                    "'2025-12-01 09:00'")
    dia = mundo.dias[30]
    with db.connect() as con:
        res = {r["ligacao_id"]: r for r in
               papel.rodar_dia(con, dia, _as(dia, 19), {})}
    assert res[mundo.lig]["operacoes"] and res[mundo.lig]["motivo"] is None
    assert res[lig2]["operacoes"] is None and res[lig2]["status"] == "rodando"
    assert res[lig2]["motivo"].startswith("falha no cálculo")


def test_ligacao_removida_ou_adicionada_depois_fica_de_fora(mundo):
    dia = mundo.dias[30]
    with db.connect() as con:
        assert [l["ligacao_id"] for l in
                papel.ligacoes_do_papel(con, SIMB, dia)] == [mundo.lig]
        con.execute("UPDATE portfolio_membros SET adicionado_em = ?",
                    [_as(dia + timedelta(days=1), 9)])
        assert papel.ligacoes_do_papel(con, SIMB, dia) == []
        con.execute("UPDATE portfolio_membros SET adicionado_em = "
                    "'2025-12-01', removido_em = ?", [_as(dia, 9)])
        assert papel.ligacoes_do_papel(con, SIMB, dia) == []


# ------------------------------------------------------------- conferência
def test_conferir_grava_checksum_e_congela(mundo):
    dia = mundo.dias[30]
    idx = _indices_do_dia(mundo.barras, dia)
    sl = slice(idx[0], idx[-1] + 1)
    b = mundo.barras
    esperado = (f"{len(idx)}:{int(b['open'][sl].sum())}:"
                f"{int(b['high'][sl].sum())}:{int(b['low'][sl].sum())}:"
                f"{int(b['close'][sl].sum())}")
    with db.connect() as con:
        papel.conferir(con, dia, _as(dia, 19), {})
        p = _pregao(con, mundo.lig, dia)
        ops = _ops(con, mundo.lig, dia)
        assert (p["status"], p["checksum"]) == ("conferido", esperado)
        assert ops and not any(o["aberta"] for o in ops)
        assert papel.divergencias(con, SIMB) == []
        # candle do dia corrigido depois (reimportação, Sincronizar)
        con.execute("UPDATE bars_m1 SET close = close + 5 WHERE ts = ?",
                    [b["ts"][idx[100]].astype("datetime64[us]").item()])
        div = papel.divergencias(con, SIMB)
        assert [(d["ligacao_id"], d["dia"], d["gravado"]) for d in div] \
            == [(mundo.lig, dia, esperado)]
        assert div[0]["atual"] != esperado
        # congelado: o papel não muda
        res = papel.rodar_dia(con, dia, _as(dia, 20), {})
        papel.gravar(con, res, _as(dia, 20))
        assert _ops(con, mundo.lig, dia) == ops
        assert _pregao(con, mundo.lig, dia) == p


def test_conferir_dia_que_fechou_cedo_nao_deixa_aberta(mundo):
    """Pregão encurtado (véspera de feriado): a última barra é o fechamento
    real, e o que o motor fechou nela está fechado."""
    dia = mundo.dias[30]
    with db.connect() as con:
        con.execute("DELETE FROM bars_m1 WHERE ts >= ? AND ts < ?",
                    [_as(dia, 13), _as(dia + timedelta(days=1), 0)])
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 13), {}),
                     _as(dia, 13))
        ainda = _ops(con, mundo.lig, dia)
        papel.conferir(con, dia, _as(dia, 19), {})
        ops = _ops(con, mundo.lig, dia)
    assert ops and not any(o["aberta"] for o in ops)
    assert [o["op_id"] for o in ops] == [o["op_id"] for o in ainda]


def test_conferir_nao_congela_ligacao_que_falhou(mundo, monkeypatch):
    dia = mundo.dias[30]
    with db.connect() as con:
        papel.gravar(con, papel.rodar_dia(con, dia, _as(dia, 12), {}),
                     _as(dia, 12))
        antes = _ops(con, mundo.lig, dia)

        def quebra(*a, **k):
            raise RuntimeError("motor caiu")
        monkeypatch.setattr(papel, "calcular", quebra)
        papel.conferir(con, dia, _as(dia, 19), {})
        p = _pregao(con, mundo.lig, dia)
        # fica para a próxima volta tentar de novo, sem checksum
        assert p["status"] == "rodando"
        assert p["motivo"].startswith("falha no cálculo")
        assert p["checksum"] is None
        assert _ops(con, mundo.lig, dia) == antes
        monkeypatch.undo()
        papel.conferir(con, dia, _as(dia, 19, 5), {})
        assert _pregao(con, mundo.lig, dia)["status"] == "conferido"


def test_plano_detalhes_com_conexao_aberta(mundo):
    with db.connect() as con:
        d = plano.detalhes(mundo.plano_id, con=con)
    assert d == plano.detalhes(mundo.plano_id)
    assert d["params"] == PARAMS and d["contratos"] == CONTRATOS


# ------------------------------------------------------------- vela parcial
def test_minuto_a_minuto_com_atr_igual_ao_historico(mundo):
    """Ao vivo, o minuto da entrada é o primeiro de uma vela de 15 que ainda
    não fechou. O ATR do stop/alvo tem que ser o da última vela FECHADA —
    como no histórico inteiro —, não o da vela pela metade."""
    estrategia, plano_d = _plano_cfg("canal-150-M15-atr")
    mod = _mod(estrategia)
    estrat, perfil = papel.perfil_do_plano(plano_d)
    n_preg = papel.pregoes_de_aquecimento(mod, estrat, perfil)
    full = run_strategy(mundo.barras, mod, estrat, perfil, mundo.inst)
    t = full.trades
    ent_ts = t["entry_ts"].astype("datetime64[us]")
    checados = 0
    for dia in mundo.dias[-5:]:
        sel = [i for i in range(full.n_trades)
               if ent_ts[i].astype("datetime64[D]") == np.datetime64(dia)]
        if not sel:
            continue
        with db.connect(read_only=True) as con:
            barras = papel.barras_do_dia(con, SIMB, dia, n_preg)
        base = len(barras["ts"]) - len(_indices_do_dia(mundo.barras, dia))
        g0 = _indices_do_dia(mundo.barras, dia)[0]
        fechadas: dict = {}
        ultimo = max(int(t["exit_i"][i]) for i in sel) - g0 + base
        for k in range(base, ultimo + 2):
            corte = {c: v[:k + 1] for c, v in barras.items()}
            ops = {o["entry_ts"]: o for o in papel.calcular(
                corte, dia, plano_d, mod, mundo.inst, None)}
            for i in sel:
                ts_e = ent_ts[i].item()
                e_k = int(t["entry_i"][i]) - g0 + base
                s_k = int(t["exit_i"][i]) - g0 + base
                if k < e_k:
                    assert ts_e not in ops
                    continue
                o = ops[ts_e]
                lado, px = int(t["side"][i]), int(t["entry_px"][i])
                assert o["entry_px"] == px
                if k < s_k:
                    assert o["aberta"], (dia, k)
                    assert ts_e not in fechadas, "fechou e reabriu"
                    sl, tp = int(full.sl_at_entry[i]), int(full.tp_at_entry[i])
                    assert o["stop_px"] == px - lado * sl, (dia, k)
                    assert o["alvo_px"] == px + lado * tp, (dia, k)
                    checados += 1
                else:
                    assert not o["aberta"], (dia, k)
                    assert (o["exit_ts"], o["exit_px"], o["stop_px"],
                            o["alvo_px"]) == (
                        t["exit_ts"][i].astype("datetime64[us]").item(),
                        int(t["exit_px"][i]), int(t["stop_fim"][i]) or None,
                        int(t["alvo_fim"][i]) or None), (dia, k)
                    fechadas[ts_e] = True
    assert checados > 0


def test_sinal_de_vela_parcial_nao_abre_operacao(mundo):
    """Se a vela de 15 que ainda não fechou já rompe o canal, isso não pode
    virar entrada: a entrada é no minuto seguinte ao FECHAMENTO da vela."""
    estrategia, plano_d = _plano_cfg("canal-20-M5")
    mod = _mod(estrategia)
    estrat, perfil = papel.perfil_do_plano(plano_d)
    full = run_strategy(mundo.barras, mod, estrat, perfil, mundo.inst)
    entradas = set(full.trades["entry_ts"].astype("datetime64[us]").tolist())
    dia = mundo.dias[-1]
    with db.connect(read_only=True) as con:
        barras = papel.barras_do_dia(con, SIMB, dia, 3)
    base = len(barras["ts"]) - len(_indices_do_dia(mundo.barras, dia))
    for k in range(base, len(barras["ts"])):
        corte = {c: v[:k + 1] for c, v in barras.items()}
        for o in papel.calcular(corte, dia, plano_d, mod, mundo.inst, None):
            assert o["entry_ts"] in entradas, (k, o["entry_ts"])


# ------------------------------------------------------------- sem candle
def test_sem_candle_no_dia_nada_e_gravado(mundo):
    sabado = date(2026, 1, 10)
    with db.connect() as con:
        assert papel.barras_do_dia(con, SIMB, sabado, 3) is None
        res = papel.rodar_dia(con, sabado, _as(sabado, 12), {})
        papel.gravar(con, res, _as(sabado, 12))
        assert res == []
        assert con.execute("SELECT count(*) FROM papel_pregoes")\
            .fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM papel_operacoes")\
            .fetchone()[0] == 0


def test_barras_do_dia_conta_pregoes_pelas_datas_de_bars_m1(mundo):
    dia = mundo.dias[20]
    with db.connect(read_only=True) as con:
        b = papel.barras_do_dia(con, SIMB, dia, 3)
    datas = sorted({d for d in b["ts"].astype("datetime64[D]").tolist()})
    assert datas == mundo.dias[17:21]
    assert set(b) == {"ts", "open", "high", "low", "close", "tick_volume",
                      "volume"}
    assert b["ts"].dtype == np.dtype("datetime64[ns]")
