"""Diário da tela Ao vivo: o que foi ligado, desligado, trocado e por quem.

Só inserção. Estado atual qualquer tabela guarda; o que não se recria
depois é a SEQUÊNCIA — por que a estratégia não operou no dia 12, quem
subiu de fase e quando, qual plano valia. `registrar` exige a conexão do
chamador para o evento cair na MESMA transação da mudança: ou os dois
ficam, ou nenhum.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db

TIPOS = frozenset({
    "portfolio_ligado", "portfolio_desligado", "portfolio_conta_mudou",
    "membro_adicionado", "membro_removido", "membro_ligado",
    "membro_desligado", "fase_mudou",
    "conta_criada", "conta_editada", "conta_arquivada",
    "plano_gravado", "plano_aposentado", "plano_vinculado",
    "variante_renomeada", "base_corrigida",
})
ORIGENS = frozenset({"usuario", "disjuntor", "sistema"})

_COLUNAS = ("evento_id", "quando", "tipo", "origem", "portfolio_id",
            "ligacao_id", "variante_id", "conta_id", "plano_id", "de",
            "para", "motivo")
_FILTROS = ("tipo", "portfolio_id", "ligacao_id", "variante_id", "conta_id",
            "plano_id", "motivo")


def registrar(con, tipo, origem, *, portfolio_id=None, ligacao_id=None,
              variante_id=None, conta_id=None, plano_id=None, de=None,
              para=None, motivo=None, quando=None) -> int:
    if tipo not in TIPOS:
        raise ValueError(f"tipo de evento desconhecido: {tipo}")
    if origem not in ORIGENS:
        raise ValueError(f"origem de evento desconhecida: {origem}")
    eid = con.execute("SELECT nextval('seq_evento_id')").fetchone()[0]
    con.execute(
        f"INSERT INTO ao_vivo_eventos ({', '.join(_COLUNAS)}) "
        f"VALUES ({', '.join('?' * len(_COLUNAS))})",
        [eid, quando or datetime.now(), tipo, origem, portfolio_id,
         ligacao_id, variante_id, conta_id, plano_id,
         None if de is None else str(de), None if para is None else str(para),
         motivo])
    return int(eid)


def eventos(**filtros) -> list[dict]:
    desconhecidos = set(filtros) - set(_FILTROS)
    if desconhecidos:
        raise ValueError(f"filtro desconhecido: {sorted(desconhecidos)}")
    ativos = {k: v for k, v in filtros.items() if v is not None}
    onde = " AND ".join(f"{k} = ?" for k in ativos)
    sql = (f"SELECT {', '.join(_COLUNAS)} FROM ao_vivo_eventos"
           + (f" WHERE {onde}" if onde else "") + " ORDER BY evento_id")
    with db.connect(read_only=True) as con:
        return [dict(zip(_COLUNAS, r))
                for r in con.execute(sql, list(ativos.values())).fetchall()]
