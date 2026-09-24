"""Portfólio: agrupar variantes de estratégia e medir correlação/risco.

O portfólio referencia só a VARIANTE, nunca plano/wfa/mineração
diretamente — "o que está ativo hoje" é sempre resolvido na hora via
variantes.plano_ativo, a mesma filosofia de "recalcula na hora" que o
WFA/Mineração já usa (core/wfa_runner.py:_span). Reotimizar uma variante
atualiza o portfólio sozinho, sem precisar mexer em nada aqui. Ver
docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db
from . import variantes as V


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
