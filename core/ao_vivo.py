"""Tela Ao vivo: contas, interruptores e arrumação da cadeia.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md.
Toda mudança de estado grava o evento do diário NA MESMA transação.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db
from . import diario
from . import variantes as V

_TIPOS_CONTA = ("demo", "real")
_COLS_CONTA = ("conta_id", "nome", "tipo", "limite_perda_dia", "criado_em",
               "arquivada_em")
_NADA = object()


def _nome_livre(con, nome, ignorar_id=None):
    r = con.execute(
        "SELECT conta_id FROM contas WHERE nome = ? AND arquivada_em IS NULL "
        "AND conta_id IS DISTINCT FROM ?", [nome, ignorar_id]).fetchone()
    if r:
        raise ValueError(f"já existe uma conta ativa chamada '{nome}'")


def criar_conta(nome, tipo, limite_perda_dia=None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("a conta precisa de um nome")
    if tipo not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    with db.connect_write() as con, db.transacao(con):
        _nome_livre(con, nome)
        cid = con.execute("SELECT nextval('seq_conta_id')").fetchone()[0]
        con.execute("INSERT INTO contas VALUES (?,?,?,?,?,NULL)",
                    [cid, nome, tipo, limite_perda_dia, datetime.now()])
        diario.registrar(con, "conta_criada", "usuario", conta_id=cid,
                         para=nome, motivo=tipo)
    return int(cid)


def editar_conta(conta_id, *, nome=_NADA, tipo=_NADA,
                 limite_perda_dia=_NADA) -> None:
    novos = {k: v for k, v in (("nome", nome), ("tipo", tipo),
                               ("limite_perda_dia", limite_perda_dia))
             if v is not _NADA}
    if "nome" in novos:
        novos["nome"] = (novos["nome"] or "").strip()
        if not novos["nome"]:
            raise ValueError("a conta precisa de um nome")
    if "tipo" in novos and novos["tipo"] not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT nome, tipo, limite_perda_dia FROM contas "
                        "WHERE conta_id = ?", [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        atual = dict(zip(("nome", "tipo", "limite_perda_dia"), r))
        if "nome" in novos:
            _nome_livre(con, novos["nome"], conta_id)
        if "tipo" in novos and novos["tipo"] != atual["tipo"]:
            # a fase das variantes decide para qual conta vai a ordem: trocar
            # o tipo de uma conta já escolhida mandaria demo para o real
            if con.execute("SELECT 1 FROM portfolios WHERE conta_demo_id = ? "
                           "OR conta_real_id = ?",
                           [conta_id, conta_id]).fetchone():
                raise ValueError("a conta está escolhida num portfólio: "
                                 "tire-a de lá antes de trocar o tipo")
        for campo, valor in novos.items():
            if valor == atual[campo]:
                continue
            con.execute(f"UPDATE contas SET {campo} = ? WHERE conta_id = ?",
                        [valor, conta_id])
            diario.registrar(con, "conta_editada", "usuario",
                             conta_id=conta_id, de=atual[campo], para=valor,
                             motivo=campo)


def arquivar_conta(conta_id) -> None:
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT arquivada_em FROM contas WHERE conta_id = ?",
                        [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        if r[0] is not None:
            return                        # já arquivada: sem evento repetido
        con.execute("UPDATE contas SET arquivada_em = ? WHERE conta_id = ?",
                    [datetime.now(), conta_id])
        diario.registrar(con, "conta_arquivada", "usuario", conta_id=conta_id)


def listar_contas(incluir_arquivadas: bool = False) -> list[dict]:
    sql = (f"SELECT {', '.join(_COLS_CONTA)} FROM contas"
           + ("" if incluir_arquivadas else " WHERE arquivada_em IS NULL")
           + " ORDER BY nome")
    with db.connect(read_only=True) as con:
        return [dict(zip(_COLS_CONTA, r)) for r in con.execute(sql).fetchall()]


def _mudar_portfolio(portfolio_id, ligado: bool) -> None:
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT coalesce(ligado, false) FROM portfolios "
                        "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        if r is None:
            raise ValueError(f"portfólio #{portfolio_id} não existe")
        if bool(r[0]) == ligado:
            return
        con.execute("UPDATE portfolios SET ligado = ? WHERE portfolio_id = ?",
                    [ligado, portfolio_id])
        diario.registrar(con, "portfolio_ligado" if ligado
                         else "portfolio_desligado", "usuario",
                         portfolio_id=portfolio_id)


def ligar_portfolio(portfolio_id) -> None:
    _mudar_portfolio(portfolio_id, True)


def desligar_portfolio(portfolio_id) -> None:
    _mudar_portfolio(portfolio_id, False)


def _conta_valida(con, conta_id, tipo):
    if conta_id is None:
        return
    r = con.execute("SELECT tipo, arquivada_em FROM contas WHERE conta_id = ?",
                    [conta_id]).fetchone()
    if r is None:
        raise ValueError(f"conta #{conta_id} não existe")
    if r[0] != tipo:
        raise ValueError(f"a conta #{conta_id} não é do tipo {tipo}")
    if r[1] is not None:
        raise ValueError(f"a conta #{conta_id} está arquivada")


def definir_contas(portfolio_id, conta_demo_id, conta_real_id) -> None:
    with db.connect_write() as con, db.transacao(con):
        _conta_valida(con, conta_demo_id, "demo")
        _conta_valida(con, conta_real_id, "real")
        antes = con.execute("SELECT conta_demo_id, conta_real_id FROM portfolios "
                            "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        if antes is None:
            raise ValueError(f"portfólio #{portfolio_id} não existe")
        if tuple(antes) == (conta_demo_id, conta_real_id):
            return
        con.execute("UPDATE portfolios SET conta_demo_id = ?, conta_real_id = ? "
                    "WHERE portfolio_id = ?",
                    [conta_demo_id, conta_real_id, portfolio_id])
        diario.registrar(con, "portfolio_conta_mudou", "usuario",
                         portfolio_id=portfolio_id,
                         de=f"demo:{antes[0]} real:{antes[1]}",
                         para=f"demo:{conta_demo_id} real:{conta_real_id}")


_POR = ("usuario", "disjuntor")


def _membro(con, ligacao_id):
    r = con.execute("SELECT portfolio_id, variante_id, ligada, removido_em, "
                    "desligada_por FROM portfolio_membros WHERE ligacao_id = ?",
                    [ligacao_id]).fetchone()
    if r is None:
        raise ValueError(f"ligação #{ligacao_id} não existe")
    if r[3] is not None:
        raise ValueError(f"a ligação #{ligacao_id} foi removida do portfólio")
    return r


def desligar_membro(ligacao_id, por: str = "usuario") -> None:
    if por not in _POR:
        raise ValueError("desligar só 'usuario' ou 'disjuntor'")
    with db.connect_write() as con, db.transacao(con):
        pid, vid, ligada, _rem, _por = _membro(con, ligacao_id)
        if not ligada:
            return
        vigor = V.plano_em_vigor(vid, con=con)
        con.execute("UPDATE portfolio_membros SET ligada = false, "
                    "desligada_por = ?, desligada_em = ?, "
                    "desligada_plano_id = ? WHERE ligacao_id = ?",
                    [por, datetime.now(), vigor and vigor["plano_id"],
                     ligacao_id])
        diario.registrar(con, "membro_desligado", por, portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         plano_id=vigor and vigor["plano_id"])


def ligar_membro(ligacao_id) -> None:
    """Livre a qualquer momento, inclusive depois do disjuntor (decisão do
    usuário, 30/09/2026) — o evento guarda que foi religada depois dele."""
    with db.connect_write() as con, db.transacao(con):
        pid, vid, ligada, _rem, por = _membro(con, ligacao_id)
        if ligada:
            return
        vigor = V.plano_em_vigor(vid, con=con)
        con.execute("UPDATE portfolio_membros SET ligada = true, "
                    "desligada_por = NULL, desligada_em = NULL, "
                    "desligada_plano_id = NULL WHERE ligacao_id = ?",
                    [ligacao_id])
        diario.registrar(con, "membro_ligado", "usuario", portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         plano_id=vigor and vigor["plano_id"],
                         motivo="religada após disjuntor"
                         if por == "disjuntor" else None)
