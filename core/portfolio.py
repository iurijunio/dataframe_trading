"""Portfólio: agrupar variantes de estratégia e medir correlação/risco.

O portfólio referencia só a VARIANTE, nunca plano/wfa/mineração
diretamente — "o que está ativo hoje" é sempre resolvido na hora via
variantes.plano_ativo, a mesma filosofia de "recalcula na hora" que o
WFA/Mineração já usa (core/wfa_runner.py:_span). Reotimizar uma variante
atualiza o portfólio sozinho, sem precisar mexer em nada aqui. Ver
docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import numpy as np

from . import db_manager as db
from . import variantes as V

_MIN_DIAS_COMUNS = 20
_N_SIMULACOES = 2000
_PERCENTIL_RISCO = 10  # "so e ultrapassado em 10% dos cenarios" - ver spec §5.3


def criar(nome: str) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome do portfólio não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        pid = con.execute("SELECT nextval('seq_portfolio_id')").fetchone()[0]
        con.execute(
            "INSERT INTO portfolios (portfolio_id, nome, criado_em) "
            "VALUES (?,?,?)", [pid, nome, datetime.now()])
    return int(pid)


def listar() -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT p.portfolio_id, p.nome, p.criado_em, "
            "count(pv.variante_id) "
            "FROM portfolios p "
            "LEFT JOIN portfolio_variantes pv "
            "ON pv.portfolio_id = p.portfolio_id "
            "GROUP BY p.portfolio_id, p.nome, p.criado_em "
            "ORDER BY p.nome"
        ).fetchall()
    return [{"portfolio_id": r[0], "nome": r[1], "criado_em": r[2],
             "n_membros": r[3]} for r in rows]


def adicionar_variante(portfolio_id: int, variante_id: int) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute(
            "INSERT OR IGNORE INTO portfolio_variantes "
            "(portfolio_id, variante_id, adicionado_em) VALUES (?,?,?)",
            [portfolio_id, variante_id, datetime.now()])


def remover_variante(portfolio_id: int, variante_id: int) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute(
            "DELETE FROM portfolio_variantes "
            "WHERE portfolio_id = ? AND variante_id = ?",
            [portfolio_id, variante_id])


def membros(portfolio_id: int) -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT ev.variante_id, ev.nome, ev.estrategia "
            "FROM portfolio_variantes pv "
            "JOIN estrategia_variantes ev ON ev.variante_id = pv.variante_id "
            "WHERE pv.portfolio_id = ? ORDER BY ev.nome", [portfolio_id]
        ).fetchall()
    out = []
    for vid, nome, estrategia in rows:
        ativo = V.plano_ativo(vid)
        out.append({
            "variante_id": vid, "nome": nome, "estrategia": estrategia,
            "wfa_id": ativo["wfa_id"] if ativo else None,
            "sem_plano_ativo": ativo is None,
        })
    return out


def _retornos_diarios(wfa_id: int) -> dict:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT exit_ts, liquido FROM wfa_trades WHERE wfa_id = ?",
            [wfa_id]).fetchall()
    diario: dict = defaultdict(float)
    for exit_ts, liquido in rows:
        diario[exit_ts.date()] += liquido
    return dict(diario)


def correlacao(portfolio_id: int) -> dict:
    ms = membros(portfolio_id)
    ativos = [m for m in ms if not m["sem_plano_ativo"]]
    avisos = [f"{m['nome']}: sem plano ativo" for m in ms if m["sem_plano_ativo"]]

    series = {m["nome"]: _retornos_diarios(m["wfa_id"]) for m in ativos}
    nomes = list(series)
    n = len(nomes)
    matriz = [[1.0 if i == j else None for j in range(n)] for i in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            a, b = series[nomes[i]], series[nomes[j]]
            comuns = sorted(set(a) & set(b))
            if len(comuns) < _MIN_DIAS_COMUNS:
                avisos.append(
                    f"{nomes[i]} × {nomes[j]}: período curto demais para correlação")
                continue
            xa = np.array([a[d] for d in comuns])
            xb = np.array([b[d] for d in comuns])
            if xa.std() == 0 or xb.std() == 0:
                # retorno constante no periodo (ex.: so um trade fechando
                # sempre o mesmo valor) - corrcoef daria 0/0 = nan, um
                # numero "real" mas sem sentido, silenciosamente
                avisos.append(
                    f"{nomes[i]} × {nomes[j]}: sem variação suficiente no "
                    f"período para correlação")
                continue
            r = float(np.corrcoef(xa, xb)[0, 1])
            matriz[i][j] = matriz[j][i] = r

    return {"variantes": nomes, "matriz": matriz,
            "risco_diario": _risco_diario(ativos), "avisos": avisos}


def _trades_para_risco(wfa_id: int) -> list[dict]:
    with db.connect(read_only=True) as con:
        symbol = con.execute(
            "SELECT symbol FROM wfa_runs WHERE wfa_id = ?", [wfa_id]
        ).fetchone()[0]
        r = con.execute(
            "SELECT point_value FROM instruments WHERE symbol = ?", [symbol]
        ).fetchone()
        # mesmo padrao de fallback ja usado em core/engine/execution.py -
        # sem cotacao cadastrada assume 1 ponto = R$ 1
        ponto = float(r[0]) if r and r[0] else 1.0
        rows = con.execute(
            "SELECT entry_ts, exit_ts, mae, contratos, liquido "
            "FROM wfa_trades WHERE wfa_id = ? ORDER BY entry_ts",
            [wfa_id]).fetchall()
    return [
        {"entry_ts": r[0], "exit_ts": r[1],
         "mae_reais": abs(r[2] or 0) * ponto * (r[3] or 1),
         "liquido": r[4] or 0.0}
        for r in rows if r[0] and r[1]
    ]


def _simular_pior_ponto(trades: list[dict], rng) -> float:
    # trade com entry_ts == exit_ts (fechamento na mesma barra) fica de
    # fora - caso raro; o liquido dele nao entra no risco do dia
    partes = []
    for t in trades:
        ini, fim = t["entry_ts"].timestamp(), t["exit_ts"].timestamp()
        if fim <= ini:
            continue
        t_mae = rng.uniform(ini, fim)
        partes.append((ini, t_mae, fim, -t["mae_reais"], t["liquido"]))
    if not partes:
        return 0.0

    def valor(p, inst):
        ini, t_mae, fim, fundo, liquido = p
        if inst < ini:
            return 0.0
        if inst >= fim:
            return liquido
        if inst <= t_mae:
            frac = (inst - ini) / (t_mae - ini) if t_mae > ini else 1.0
            return fundo * frac
        frac = (inst - t_mae) / (fim - t_mae) if fim > t_mae else 1.0
        return fundo + (liquido - fundo) * frac

    candidatos = [p[1] for p in partes]
    return min(sum(valor(p, inst) for p in partes) for inst in candidatos)


def _risco_diario(membros_ativos: list[dict]) -> dict | None:
    todos = []
    for m in membros_ativos:
        todos.extend(_trades_para_risco(m["wfa_id"]))
    if not todos:
        return None

    por_dia: dict = defaultdict(list)
    for t in todos:
        por_dia[t["entry_ts"].date()].append(t)

    rng = np.random.default_rng(0)
    piores_por_dia = {}
    for dia, trades in por_dia.items():
        if len(trades) < 2:
            continue
        amostras = [_simular_pior_ponto(trades, rng) for _ in range(_N_SIMULACOES)]
        piores_por_dia[dia] = float(np.percentile(amostras, _PERCENTIL_RISCO))

    if not piores_por_dia:
        return None
    pior_dia = min(piores_por_dia, key=piores_por_dia.get)
    return {"p90": piores_por_dia[pior_dia], "pior_dia": str(pior_dia)}
