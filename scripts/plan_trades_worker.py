"""Backtest of plans with the code of ONE folder: the worker of
`resign_code_hash.py`.

Runs in its own process, once with the old code and once with the new: two
versions of `core`/`strategies` cannot live in the same interpreter (the same
module name would point to only one). So it uses only what both versions have
(`plano.detalhes`, `papel.perfil_do_plano`, `prepare_bars`, `run_strategy`) and
nothing from `resign_code_hash.py`.

Usage: python -I plan_trades_worker.py <code_root> <database> <ids> <output>
       (comma-separated ids; the output is a pickle)

The database is opened READ-ONLY, and it is the copy `resign_code_hash.py`
made: the whole history costs seconds and must not lock the real database.
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
            # the two forms the code really runs: the closed-day backtest
            # (reconciliation) and the live paper one, with the last candle
            # provisional
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
