"""Guardar e recuperar um plano de operação.

O plano é o fim do passo 10: o documento que a incubação vai ler e que a
operação vai obedecer. Diferente do walk-forward, ele não é recalculável —
é decisão tomada num dia, com os números daquele dia.

Por isso tudo aqui é **retrato**: os parâmetros, o perfil de execução, o
capital e os limiares vão copiados para dentro da linha. Mineração apagada
não pode mudar o tamanho de posição de quem já está operando.

E plano não se edita: **aposenta-se** e grava-se outro. Histórico de decisão
reescrito não é histórico.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import db_manager as db

_JSON = ("params", "profile", "disjuntor", "expectativa", "reotimizacao",
         "definicoes", "regua")

_COLUNAS = ("plano_id", "wfa_id", "run_id", "symbol", "strategy", "nome",
            "created_at", "params", "profile", "capital", "contratos",
            "risco_pedido_pct", "risco_efetivo_pct", "perda_referencia",
            "de_onde", "margem", "uso_margem_pct", "camada4_travada",
            "disjuntor", "expectativa", "reotimizacao", "definicoes",
            "regua", "estado")


def salvar(*, wfa_id, run_id, symbol, strategy, nome, params, profile,
           capital, contratos, risco_pedido_pct, risco_efetivo_pct,
           perda_referencia, de_onde, margem, uso_margem_pct,
           camada4_travada, disjuntor, expectativa, reotimizacao,
           definicoes, regua) -> int:
    """Grava um plano e devolve o id.

    Nunca substitui: dois planos do mesmo walk-forward com risco diferente
    são duas decisões, e as duas ficam.
    """
    with db.connect_write() as con, db.transacao(con):
        pid = con.execute("SELECT nextval('seq_plano_id')").fetchone()[0]
        con.execute(
            f"INSERT INTO planos_operacao ({', '.join(_COLUNAS)}) "
            f"VALUES ({', '.join('?' * len(_COLUNAS))})",
            [pid, wfa_id, run_id, symbol, strategy, nome or None,
             datetime.now(),
             json.dumps(params or {}), json.dumps(profile or {}),
             float(capital) if capital is not None else None,
             int(contratos) if contratos is not None else None,
             risco_pedido_pct, risco_efetivo_pct, perda_referencia, de_onde,
             float(margem) if margem is not None else None,
             uso_margem_pct, bool(camada4_travada),
             json.dumps(disjuntor or {}), json.dumps(expectativa or {}),
             json.dumps(reotimizacao or {}), json.dumps(definicoes or {}),
             json.dumps(regua or {}), "ativo"])
    return int(pid)


def _linha(r) -> dict:
    d = dict(zip(_COLUNAS, r))
    for c in _JSON:
        d[c] = json.loads(d[c]) if d[c] else {}
    d["camada4_travada"] = bool(d["camada4_travada"])
    return d


def listar(wfa_id: int | None = None, apenas_ativos: bool = False
           ) -> list[dict]:
    """Os planos gravados, mais recentes primeiro."""
    onde, args = [], []
    if wfa_id is not None:
        onde.append("wfa_id = ?")
        args.append(wfa_id)
    if apenas_ativos:
        onde.append("estado = 'ativo'")
    sql = (f"SELECT {', '.join(_COLUNAS)} FROM planos_operacao"
           + (" WHERE " + " AND ".join(onde) if onde else "")
           + " ORDER BY plano_id DESC")
    with db.connect(read_only=True) as con:
        return [_linha(r) for r in con.execute(sql, args).fetchall()]


def detalhes(plano_id: int) -> dict | None:
    with db.connect(read_only=True) as con:
        r = con.execute(
            f"SELECT {', '.join(_COLUNAS)} FROM planos_operacao "
            "WHERE plano_id = ?", [plano_id]).fetchone()
    return _linha(r) if r else None


def aposentar(plano_id: int) -> bool:
    """Tira o plano de operação sem apagá-lo.

    É o caminho normal: trocou de parâmetro, mudou o risco ou o disjuntor
    disparou, aposenta este e grava outro. O que ficou gravado é o que foi
    decidido na época, e continua valendo como registro.
    """
    if detalhes(plano_id) is None:
        return False
    with db.connect_write() as con, db.transacao(con):
        con.execute("UPDATE planos_operacao SET estado = 'aposentado' "
                    "WHERE plano_id = ?", [plano_id])
    return True


def excluir(plano_id: int) -> bool:
    if detalhes(plano_id) is None:
        return False
    with db.connect_write() as con, db.transacao(con):
        con.execute("DELETE FROM planos_operacao WHERE plano_id = ?",
                    [plano_id])
    return True
