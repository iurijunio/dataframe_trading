"""Proof that the search gives the Scan's number.

    python scripts/verify_search.py <busca_id> [n=10]

Redoes the N best valid elites through the Scan path (`optimizer._uma`, a
backtest from scratch, without the search's reused signal) and compares trades,
profit, profit factor, drawdown and recovery factor, with no tolerance. Read-only:
the search database and the Parquet mirror.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402


def _igual(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return float(a) == float(b)


def conferir(busca_id: int, n: int = 10) -> list[str]:
    from core import db_manager as db, optimizer, walkforward as wf
    from core.busca import banco
    from core.busca.espaco import Combinacao, Espaco

    b = banco.ler_busca(busca_id)
    c = b["config"]
    esp = Espaco.de_json(c["espaco"])
    amostra = db.read_bars_parquet(c["simbolo"], c.get("de"), c.get("ate"))["ts"]
    janelas = wf.montar_janelas(np.datetime64(c.get("de") or amostra[0], "s"),
                                np.datetime64(c.get("ate") or amostra[-1], "s"),
                                **c["wf_config"])
    optimizer._init(c["simbolo"], c.get("de"), c.get("ate"), c["estrategia"])
    elites = [e for e in banco.ler_elites(busca_id) if e["valida"]][:n]
    difs = []
    for i, e in enumerate(elites):
        comb = Combinacao.de_chave(e["combo"])
        perfil = esp.perfil(comb, c["perfil_base"])
        r = optimizer._uma((i, esp.params(comb), {}, perfil.to_config(), janelas))
        g = r["geral"]
        pares = {"trades": (e["trades"], g["trades"]), "lucro": (e["lucro"], g["lucro"]),
                 "pf": (e["pf"], optimizer._num(g["profit_factor"]) and g["profit_factor"]),
                 "dd": (e["dd"], g["max_dd"]),
                 "fr": (e["fr"], g["fator_recuperacao"] if np.isfinite(
                     g["fator_recuperacao"]) else None)}
        ruins = [k for k, (x, y) in pares.items() if not _igual(x, y)]
        linha = (f"{i + 1:2d}. {comb.timeframe} {comb.ini}-{comb.fim} {comb.direcao} "
                 f"FR {e['fr']:.2f} · {e['trades']} trades")
        print(linha + (" — IDENTICAL" if not ruins else f" — DIFFERS in {ruins}: {pares}"))
        if ruins:
            difs.append(linha)
    return difs


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    difs = conferir(int(argv[0]), int(argv[1]) if len(argv) > 1 else 10)
    print("all identical" if not difs else f"{len(difs)} different")
    return 1 if difs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
