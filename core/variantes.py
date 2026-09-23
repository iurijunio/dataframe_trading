"""Identidade da estratégia através de ciclos de reotimização.

Reotimizar (minerar de novo, rodar o WFA de novo, gravar outro plano) não
deixa rastro de que aquilo é a MESMA estratégia de antes, só atualizada —
isso separa em `variantes`. A variante é escolhida na hora de salvar a
mineração; WFA e plano de operação herdam por cascata (run_id ->
variante_id), sem coluna própria — ver docs/superpowers/specs/
2026-09-23-identidade-estrategia-design.md.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db

_COLUNAS = ("variante_id", "estrategia", "nome", "descricao", "criado_em")


def criar(nome: str, estrategia: str, descricao: str | None = None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome da variante não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        existe = con.execute(
            "SELECT 1 FROM estrategia_variantes WHERE estrategia = ? "
            "AND nome = ?", [estrategia, nome]).fetchone()
        if existe:
            raise ValueError(
                f"já existe uma variante '{nome}' para {estrategia}")
        vid = con.execute(
            "SELECT nextval('seq_variante_id')").fetchone()[0]
        con.execute(
            "INSERT INTO estrategia_variantes "
            "(variante_id, estrategia, nome, descricao, criado_em) "
            "VALUES (?,?,?,?,?)",
            [vid, estrategia, nome, descricao, datetime.now()])
    return int(vid)


def listar(estrategia: str | None = None) -> list[dict]:
    onde, args = [], []
    if estrategia is not None:
        onde.append("estrategia = ?")
        args.append(estrategia)
    sql = (f"SELECT {', '.join(_COLUNAS)} FROM estrategia_variantes"
           + (" WHERE " + " AND ".join(onde) if onde else "")
           + " ORDER BY nome")
    with db.connect(read_only=True) as con:
        rows = con.execute(sql, args).fetchall()
    return [dict(zip(_COLUNAS, r)) for r in rows]
