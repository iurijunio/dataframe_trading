"""Backtest de planos com o código de UMA pasta — o trabalhador do
`reassinar_codigo.py`.

Roda num processo próprio, uma vez com o código antigo e outra com o novo:
duas versões de `core`/`strategies` não convivem no mesmo interpretador
(o mesmo nome de módulo apontaria para uma só). Por isso usa só o que as
duas versões têm (`plano.detalhes`, `papel.perfil_do_plano`,
`prepare_bars`, `run_strategy`) e nada do `reassinar_codigo.py`.

Uso: python -I _trades_do_plano.py <raiz_do_codigo> <banco> <ids> <saida>
     (ids separados por vírgula; saída é um pickle)

O banco é aberto SÓ PARA LEITURA, e é a cópia que o `reassinar_codigo.py`
tirou — o histórico inteiro custa segundos e não pode prender o banco real.
"""
from __future__ import annotations

import importlib
import pickle
import sys
from pathlib import Path


def main(raiz: str, banco: str, ids: str, saida: str) -> None:
    sys.path.insert(0, str(Path(raiz).resolve()))
    import duckdb
    import numpy as np

    from core import db_manager as db
    from core import papel
    from core import plano as _plano
    from core.engine.execution import prepare_bars, run_strategy

    db.DB_PATH = Path(banco)
    out = {}
    con = duckdb.connect(banco, read_only=True)
    try:
        for pid in [int(x) for x in ids.split(",") if x]:
            p = _plano.detalhes(pid, con=con)
            estrategia = p["strategy"] or con.execute(
                "SELECT estrategia FROM estrategia_variantes "
                "WHERE variante_id = ?", [p["variante_id"]]).fetchone()[0]
            mod = importlib.import_module(f"strategies.{estrategia}")
            estrat, perfil = papel.perfil_do_plano(p)
            inst = db.load_instrument_yaml(p["symbol"])
            item = {"estrategia": estrategia, "arquivo": mod.__file__}
            # as duas formas que o código roda de verdade: o backtest do dia
            # fechado (conferência) e o do papel ao vivo, com a última vela
            # provisória
            for vela_aberta in (False, True):
                barras = prepare_bars(con, p["symbol"])
                if not len(barras["ts"]):
                    item[vela_aberta] = {"n_trades": 0, "trades": {},
                                         "n_barras": 0}
                    continue
                res = run_strategy(barras, mod, estrat, perfil, inst,
                                   vela_aberta=vela_aberta)
                item[vela_aberta] = {
                    "n_trades": int(res.n_trades),
                    "trades": {k: np.asarray(v) for k, v in res.trades.items()},
                    "ambiguous_bars": int(res.ambiguous_bars),
                    "bloqueios": int(res.bloqueios),
                    "sl_at_entry": np.asarray(res.sl_at_entry),
                    "tp_at_entry": np.asarray(res.tp_at_entry),
                    "n_barras": int(len(barras["ts"])),
                }
            out[pid] = item
    finally:
        con.close()
    with open(saida, "wb") as f:
        pickle.dump(out, f)


if __name__ == "__main__":
    main(*sys.argv[1:5])
