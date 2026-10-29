"""Foto dos resultados do WIN, para provar que nada mudou.

    python scripts/foto_win.py gravar <nome>     (não sobrescreve)
    python scripts/foto_win.py conferir <nome>   (exit 1 se houver diferença)

A foto guarda os trades de cada plano (via `_trades_do_plano`) e de cada
estratégia com os parâmetros padrão, tudo no WIN$N, numa cópia do banco
aberta só para leitura. Fica em `data/foto_win/<nome>.pkl` (fora do git).
"""
from __future__ import annotations

import pickle
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

PASTA_FOTOS = RAIZ / "data" / "foto_win"


def comparar(antes, depois, caminho: str = "") -> list[str]:
    """Diferenças exatas (sem tolerância); lista vazia = idêntico."""
    if isinstance(antes, dict) and isinstance(depois, dict):
        difs = []
        for k in sorted(set(antes) | set(depois), key=str):
            sub = f"{caminho}/{k}" if caminho else str(k)
            if k not in antes:
                difs.append(f"{sub}: ausente != presente")
            elif k not in depois:
                difs.append(f"{sub}: presente != ausente")
            else:
                difs += comparar(antes[k], depois[k], sub)
        return difs
    if isinstance(antes, np.ndarray) or isinstance(depois, np.ndarray):
        a, d = np.asarray(antes), np.asarray(depois)
        try:
            igual = np.array_equal(a, d, equal_nan=True)
        except TypeError:  # dtype sem NaN (texto, datas)
            igual = np.array_equal(a, d)
        return [] if igual else [f"{caminho}: {a.tolist()[:5]}... != {d.tolist()[:5]}..."]
    return [] if antes == depois else [f"{caminho}: {antes} != {depois}"]


def gerar() -> dict:
    import duckdb

    from core import db_manager as db
    from core.engine.execution import ExecutionProfile, prepare_bars, run_strategy
    from scripts import _trades_do_plano
    from scripts.reassinar_codigo import copiar_banco
    from strategies import registry
    from strategies.base import defaults

    with tempfile.TemporaryDirectory(prefix="foto-win-") as tmp:
        copia = str(copiar_banco(Path(db.DB_PATH), Path(tmp) / "copia.duckdb"))
        con = duckdb.connect(copia, read_only=True)
        try:
            ids = [int(r[0]) for r in con.execute(
                "SELECT plano_id FROM planos_operacao ORDER BY plano_id").fetchall()]
            saida = Path(tmp) / "planos.pkl"
            _trades_do_plano.main(str(RAIZ), copia, ",".join(map(str, ids)), str(saida))
            with open(saida, "rb") as f:
                planos = pickle.load(f)
            barras = prepare_bars(con, "WIN$N")
            inst = db.load_instrument_yaml("WIN$N")
            estrategias = {}
            for e in registry.descobrir():
                mod = registry.carregar(e["modulo"])
                res = run_strategy(barras, mod, defaults(mod.params_schema),
                                   ExecutionProfile(), inst)
                estrategias[e["modulo"]] = {
                    "n_trades": int(res.n_trades),
                    "trades": {k: np.asarray(v) for k, v in res.trades.items()},
                    "sl_at_entry": np.asarray(res.sl_at_entry),
                    "tp_at_entry": np.asarray(res.tp_at_entry),
                    "ambiguous_bars": int(res.ambiguous_bars),
                    "bloqueios": int(res.bloqueios),
                }
        finally:
            con.close()
    return {"planos": planos, "estrategias": estrategias}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("gravar", "conferir"):
        print(__doc__)
        return 2
    cmd, nome = argv
    arq = PASTA_FOTOS / f"{nome}.pkl"
    if cmd == "gravar":
        if arq.exists():
            print(f"{arq} já existe; não sobrescrevo (escolha outro nome).")
            return 1
        foto = gerar()
        arq.parent.mkdir(parents=True, exist_ok=True)
        with open(arq, "wb") as f:
            pickle.dump(foto, f)
        print(f"foto {nome} gravada ({len(foto['planos'])} planos, "
              f"{len(foto['estrategias'])} estratégias)")
        return 0
    with open(arq, "rb") as f:
        salva = pickle.load(f)
    nova = gerar()
    difs = comparar(salva, nova)
    if not difs:
        print(f"foto {nome}: idêntica ({len(nova['planos'])} planos, "
              f"{len(nova['estrategias'])} estratégias)")
        return 0
    print(f"foto {nome}: {len(difs)} diferença(s)")
    for d in difs[:30]:
        print("  " + d)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
