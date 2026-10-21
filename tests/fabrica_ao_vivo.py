"""Fábrica de ligações e barras para os testes do papel e das ordens.

Os testes do papel (`test_papel_motor.py`) e do papel ao vivo
(`test_papel_vivo.py`) montam a mesma cadeia — variante → mineração →
walk-forward → plano → portfólio → ligação — e gravam barras no banco de
teste do mesmo jeito. Uma cópia em cada arquivo divergiria na primeira
mudança de schema.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from core import codigo, plano, variantes
from core import db_manager as db
from core import portfolio as P
from tests._cadeia import campos_plano, mineracao, wfa


def ligacao_com_plano(nome: str, *, params: dict, profile: dict,
                      contratos: int, run_id: int = 1,
                      strategy: str = "rompimento_canal",
                      codigo_hash: str | None = None,
                      portfolio_id: int | None = None,
                      agora: datetime = datetime(2025, 12, 1, 10),
                      adicionado_em: str = "2025-12-01 09:00"):
    """Variante com plano em vigor, ligada num portfólio ligado.

    `adicionado_em` bem antes dos pregões dos testes: adicionada no dia, só
    o que entra depois dela conta. `codigo_hash` padrão é o do arquivo da
    estratégia no disco — o papel pula plano de código diferente."""
    v = variantes.criar(nome, strategy)
    mineracao(run_id, variante_id=v, strategy=strategy)
    wfa(run_id, run_id, strategy=strategy)
    pid = plano.salvar(**campos_plano(
        wfa_id=run_id, run_id=run_id, strategy=strategy, params=params,
        profile=profile, contratos=contratos,
        codigo_hash=codigo_hash or codigo.hash_estrategia(strategy)),
        agora=agora)
    pf = portfolio_id if portfolio_id is not None else P.criar(f"pf-{nome}")
    lig = P.adicionar_variante(pf, v)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = ? "
                    "WHERE ligacao_id = ?", [adicionado_em, lig])
        con.execute("UPDATE portfolios SET ligado = true "
                    "WHERE portfolio_id = ?", [pf])
    return SimpleNamespace(v=v, plano_id=pid, pf=pf, lig=lig)


def inserir_barras(con, b: dict, sl=slice(None), symbol: str = "WIN$N") -> None:
    """Grava em `bars_m1` as barras `b` (formato de `prepare_bars`)."""
    ts = [str(x) for x in b["ts"][sl].astype("datetime64[s]")]
    cols = [b[c][sl].tolist() for c in ("open", "high", "low", "close")]
    if len(ts) == 1:
        con.execute("INSERT INTO bars_m1 VALUES (?, ?, ?, ?, ?, ?, 1, 1, 0, 1)",
                    [symbol, ts[0], *(c[0] for c in cols)])
        return
    # parâmetro em lista é lento demais para 22 mil barras: vai por CSV
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
            "'high': 'BIGINT', 'low': 'BIGINT', 'close': 'BIGINT'})", [symbol])
    finally:
        Path(caminho).unlink()


def dias_uteis(n, inicio=date(2026, 1, 5)):
    out, d = [], inicio
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def barras_sinteticas(n_dias=40, seed=11):
    """Pregões de 09:00 a 18:24 (565 minutos), tendência do dia + ruído, de
    5 em 5 pontos como o WIN."""
    rng = np.random.default_rng(seed)
    dias = dias_uteis(n_dias)
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
