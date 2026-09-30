"""Identidade da estratégia através de ciclos de reotimização.

Reotimizar (minerar de novo, rodar o WFA de novo, gravar outro plano) não
deixa rastro de que aquilo é a MESMA estratégia de antes, só atualizada —
isso separa em `variantes`. A variante é escolhida na hora de salvar a
mineração; WFA e plano de operação herdam por cascata (run_id ->
variante_id), sem coluna própria — ver docs/superpowers/specs/
2026-09-23-identidade-estrategia-design.md.
"""
from __future__ import annotations

from datetime import date, datetime

from . import db_manager as db
from . import diario

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


def linha_do_tempo(variante_id: int) -> list[dict]:
    sql = """
        SELECT m.run_id, m.created_at, m.n_combinacoes,
               w.wfa_id, p.plano_id, p.estado
        FROM mining_runs m
        LEFT JOIN wfa_runs w ON w.run_id = m.run_id
        LEFT JOIN planos_operacao p ON p.wfa_id = w.wfa_id
            AND p.plano_id = (
                SELECT MAX(p2.plano_id) FROM planos_operacao p2
                WHERE p2.wfa_id = w.wfa_id
            )
        WHERE m.variante_id = ?
        ORDER BY m.created_at
    """
    with db.connect(read_only=True) as con:
        rows = con.execute(sql, [variante_id]).fetchall()
    return [
        {"run_id": r[0], "criado_em": r[1], "n_combinacoes": r[2],
         "wfa_id": r[3], "plano_id": r[4], "plano_estado": r[5]}
        for r in rows
    ]


def plano_ativo(variante_id: int) -> dict | None:
    # Se a variante tiver mais de um wfa com plano 'ativo' ao mesmo tempo
    # (raro - normalmente reotimizar aposenta o anterior, mas nada no
    # banco impede duas mineracoes/wfa's diferentes com plano ativo cada
    # uma), o desempate e pelo plano_id mais alto (o criado por ultimo),
    # nao pela mineracao mais recente - sao ordens que costumam coincidir
    # mas nao sao garantidamente a mesma coisa.
    sql = """
        SELECT m.run_id, w.wfa_id, p.plano_id
        FROM mining_runs m
        JOIN wfa_runs w ON w.run_id = m.run_id
        JOIN planos_operacao p ON p.wfa_id = w.wfa_id AND p.estado = 'ativo'
        WHERE m.variante_id = ?
        ORDER BY p.plano_id DESC
        LIMIT 1
    """
    with db.connect(read_only=True) as con:
        r = con.execute(sql, [variante_id]).fetchone()
    return {"run_id": r[0], "wfa_id": r[1], "plano_id": r[2]} if r else None


def plano_em_vigor(variante_id: int, dia: date | None = None,
                   con=None) -> dict | None:
    """O plano que vale naquele pregão (padrão: hoje).

    Diferente de `plano_ativo` (o mais recente gravado, que a análise de
    portfólio usa): o plano novo só vale a partir do próximo pregão, e o
    anterior continua em vigor até lá. Lê `planos_operacao.variante_id`,
    nunca a mineração — ela pode ter sido apagada. `con` para quem chama de
    dentro de uma transação aberta.
    """
    dia = dia or date.today()
    sql = """
        SELECT plano_id, wfa_id, run_id FROM planos_operacao
        WHERE variante_id = ?
          AND (vale_a_partir IS NULL OR vale_a_partir <= ?)
          AND ((estado = 'ativo' AND aposentado_em IS NULL)
               OR aposentado_em > ?)
        ORDER BY plano_id DESC LIMIT 1
    """
    args = [variante_id, dia, dia]
    if con is not None:
        r = con.execute(sql, args).fetchone()
    else:
        with db.connect(read_only=True) as c:
            r = c.execute(sql, args).fetchone()
    return {"plano_id": r[0], "wfa_id": r[1], "run_id": r[2]} if r else None


def renomear(variante_id: int, nome: str) -> None:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome da variante não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT nome, estrategia FROM estrategia_variantes "
                        "WHERE variante_id = ?", [variante_id]).fetchone()
        if r is None:
            raise ValueError(f"variante #{variante_id} não existe")
        antigo, estrategia = r
        if nome == antigo:
            return
        if con.execute("SELECT 1 FROM estrategia_variantes WHERE estrategia = ? "
                       "AND nome = ?", [estrategia, nome]).fetchone():
            raise ValueError(f"já existe uma variante '{nome}' para {estrategia}")
        con.execute("UPDATE estrategia_variantes SET nome = ? "
                    "WHERE variante_id = ?", [nome, variante_id])
        diario.registrar(con, "variante_renomeada", "usuario",
                         variante_id=variante_id, de=antigo, para=nome)
