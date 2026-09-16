"""Guardar e recuperar um walk-forward.

O resultado de um WFA é barato de recalcular — o custo está na varredura, não
nas janelas, que são fatiamento de array. Então o que se guarda aqui não é
performance: é o **registro da decisão**.

Qual mineração forneceu o espaço, com que janela IS/OOS, que inteligência
escolheu, se o holdout entrou, e o que deu. É o histórico de "eu já testei
isto assim" que evita refazer o mesmo caminho daqui a três meses — e é o que
sustenta a linha DEPLOY: a combinação que se colocaria para operar hoje fica
gravada junto do processo que a produziu.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import db_manager as db


def _passo_para_banco(p) -> dict:
    j = p.janela
    return {
        "step": "DEPLOY" if j.deploy else j.step,
        "is_de": str(j.is_de), "is_ate": str(j.is_ate),
        "oos_de": str(j.oos_de), "oos_ate": str(j.oos_ate),
        "params": p.params or {},
        "is_lucro": round(p.is_.get("lucro", 0.0), 2) if p.is_ else None,
        "is_trades": p.is_.get("trades") if p.is_ else None,
        "oos_lucro": round(p.oos["lucro"], 2) if p.oos else None,
        "oos_trades": p.oos.get("trades") if p.oos else None,
        "wfe": p.wfe_lucro,
        "fora_do_mercado": p.fora_do_mercado,
        "poucos_trades": p.poucos_trades,
        "candidatos": p.candidatos,
    }


def salvar(*, run_id, symbol, strategy, nome, is_meses, oos_meses,
           inteligencia, holdout, agregado, veredito, passos,
           trades=None, profile=None, capital=None,
           sharpes_matriz=None) -> int:
    """Grava um walk-forward e devolve o id.

    Um WFA por combinação de (mineração, IS, OOS, inteligência, holdout): se
    você rodar o mesmo de novo, ele SUBSTITUI em vez de empilhar duplicata.
    Guardar dois registros idênticos com resultados idênticos só faria a
    lista crescer sem informar nada.
    """
    linhas = [_passo_para_banco(p) for p in passos]
    deploy = next((l for l in linhas if l["step"] == "DEPLOY"), None)

    with db.connect_write() as con, db.transacao(con):
        # A "mesma" walk-forward é (mineração, janela, inteligência,
        # holdout). A estratégia entra na chave por garantia: ela já vem
        # implícita na mineração, mas deixar o invariante explícito custa
        # nada e impede que um id reaproveitado apague o registro alheio.
        antigos = [r[0] for r in con.execute(
            "SELECT wfa_id FROM wfa_runs WHERE run_id = ? AND strategy = ? "
            "AND is_meses = ? AND oos_meses = ? AND inteligencia = ? "
            "AND holdout = ?",
            [run_id, strategy, is_meses, oos_meses, inteligencia,
             bool(holdout)]).fetchall()]
        for antigo in antigos:
            con.execute("DELETE FROM wfa_trades WHERE wfa_id = ?", [antigo])
            con.execute("DELETE FROM wfa_runs WHERE wfa_id = ?", [antigo])
        wfa_id = con.execute("SELECT nextval('seq_wfa_id')").fetchone()[0]
        # colunas nomeadas: a tabela vai ganhar colunas com o tempo
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy, "
            "created_at, nome, is_meses, oos_meses, inteligencia, holdout, "
            "janelas, oos_lucro, oos_trades, wfe_global, consistencia, dd_oos, "
            "veredito, passos, deploy, profile, capital, sharpes_matriz) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [wfa_id, run_id, symbol, strategy, datetime.now(), nome or None,
             int(is_meses), int(oos_meses), inteligencia, bool(holdout),
             int(agregado.get("steps", 0)),
             float(agregado.get("oos_lucro", 0.0)),
             int(agregado.get("oos_trades", 0)),
             agregado.get("wfe_global"),
             float(agregado.get("consistencia_lucro", 0.0)),
             float(agregado.get("dd_oos", 0.0)),
             (veredito or {}).get("estado"),
             json.dumps(linhas), json.dumps(deploy),
             json.dumps(profile) if profile else None,
             float(capital) if capital is not None else None,
             json.dumps(sharpes_matriz) if sharpes_matriz else None])

        # Os trades da curva OOS, um por linha. É o que o portfólio vai
        # consumir: correlação de verdade pede a série, e exposição
        # simultânea pede saber quando cada posição esteve aberta — nada
        # disso se reconstrói a partir de um total por janela.
        if trades:
            con.executemany(
                "INSERT INTO wfa_trades (wfa_id, n, step, entry_ts, exit_ts, "
                "side, entry_px, exit_px, points, contratos, bruto, custo, "
                "liquido, reason, mae, mfe, bars_held) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [[wfa_id, t["n"], t["step"], t["entry_ts"], t["exit_ts"],
                  t["side"], t["entry_px"], t["exit_px"], t["points"],
                  t["contratos"], t["bruto"], t["custo"], t["liquido"],
                  t["reason"], t["mae"], t["mfe"], t["bars_held"]]
                 for t in trades])
    return int(wfa_id)


def listar(strategy: str | None = None, run_id: int | None = None) -> list[dict]:
    """Os walk-forwards gravados, mais recentes primeiro."""
    where, args = [], []
    if strategy:
        where.append("strategy = ?")
        args.append(strategy)
    if run_id is not None:
        where.append("run_id = ?")
        args.append(run_id)
    sql = ("SELECT wfa_id, run_id, nome, is_meses, oos_meses, inteligencia, "
           "holdout, wfe_global, consistencia, oos_lucro, veredito, created_at "
           "FROM wfa_runs"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY wfa_id DESC LIMIT 50")
    with db.connect(read_only=True) as con:
        linhas = con.execute(sql, args).fetchall()

    fora = []
    for (wid, rid, nome, is_m, oos_m, intel, hold, wfe, cons, lucro,
         ver, quando) in linhas:
        wfe_txt = f"WFE {wfe * 100:.0f}%" if wfe is not None else "WFE —"
        fora.append({
            "wfa_id": wid, "run_id": rid, "veredito": ver,
            "rotulo": (f"#{wid} · {nome or 'sem nome'} · IS{is_m}/OOS{oos_m}"
                       f" · {wfe_txt} · {cons:.0f}% janelas+"
                       + (" · holdout" if hold else "")
                       + f" · {quando:%d/%m %H:%M}"),
            "is_meses": is_m, "oos_meses": oos_m, "inteligencia": intel,
            "holdout": bool(hold),
            # separados do rótulo: a tela Candidata monta um rótulo curto
            "nome": nome, "quando": quando,
        })
    return fora


def estrategias() -> list[str]:
    """As estratégias que têm pelo menos um walk-forward salvo."""
    with db.connect(read_only=True) as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT strategy FROM wfa_runs ORDER BY 1").fetchall()]


def detalhes(wfa_id: int) -> dict | None:
    with db.connect(read_only=True) as con:
        r = con.execute(
            "SELECT run_id, symbol, strategy, nome, is_meses, oos_meses, "
            "inteligencia, holdout, passos, deploy, profile, capital, "
            "sharpes_matriz FROM wfa_runs WHERE wfa_id = ?",
            [wfa_id]).fetchone()
    if not r:
        return None
    return {
        "run_id": r[0], "symbol": r[1], "strategy": r[2], "nome": r[3],
        "is_meses": r[4], "oos_meses": r[5], "inteligencia": r[6],
        "holdout": bool(r[7]),
        "passos": json.loads(r[8]) if r[8] else [],
        "deploy": json.loads(r[9]) if r[9] else None,
        # None em registro antigo: a tela mostra "indisponível", não quebra
        "profile": json.loads(r[10]) if r[10] else None,
        "capital": float(r[11]) if r[11] is not None else None,
        "sharpes_matriz": json.loads(r[12]) if r[12] else None,
    }


def excluir(wfa_id: int) -> bool:
    with db.connect_write() as con, db.transacao(con):
        con.execute("DELETE FROM wfa_trades WHERE wfa_id = ?", [wfa_id])
        con.execute("DELETE FROM wfa_runs WHERE wfa_id = ?", [wfa_id])
    return True


# ------------------------------------------------- matéria-prima do portfólio
def trades(wfa_id: int) -> list[dict]:
    """Os trades da curva OOS, na ordem em que aconteceram."""
    with db.connect(read_only=True) as con:
        cols = [c[0] for c in con.execute(
            "SELECT * FROM wfa_trades LIMIT 0").description]
        linhas = con.execute(
            "SELECT * FROM wfa_trades WHERE wfa_id = ? ORDER BY n",
            [wfa_id]).fetchall()
    return [dict(zip(cols, r)) for r in linhas]


def serie_diaria(wfa_id: int) -> dict:
    """O resultado por PREGÃO — a base da correlação entre estratégias.

    Correlação por trade não existe: duas estratégias não operam nos mesmos
    instantes, e alinhar trade com trade não significa nada. O dia é a menor
    unidade em que duas curvas são comparáveis, e é a que a literatura de
    portfólio usa.

    O trade entra no dia da SAÍDA, que é quando o resultado se realiza.
    """
    with db.connect(read_only=True) as con:
        linhas = con.execute(
            "SELECT CAST(exit_ts AS DATE) AS dia, sum(liquido) AS pnl, "
            "count(*) AS trades FROM wfa_trades WHERE wfa_id = ? "
            "GROUP BY 1 ORDER BY 1", [wfa_id]).fetchall()
    return {"dias": [str(r[0]) for r in linhas],
            "pnl": [float(r[1]) for r in linhas],
            "trades": [int(r[2]) for r in linhas]}


def exposicao(wfa_id: int) -> list[tuple]:
    """Os intervalos (entrada, saída) de cada posição.

    Duas estratégias com correlação baixa de resultado diário podem estar
    posicionadas ao mesmo tempo o dia inteiro — e aí o risco soma mesmo que o
    resultado não se pareça. É esta lista que responde isso.
    """
    with db.connect(read_only=True) as con:
        return con.execute(
            "SELECT entry_ts, exit_ts, side, contratos FROM wfa_trades "
            "WHERE wfa_id = ? ORDER BY entry_ts", [wfa_id]).fetchall()
