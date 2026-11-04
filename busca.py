"""Processo da busca automática: `python busca.py <busca_id> [--pasta P]
[--banco B] [--db-principal D]`.

Aberto pelo app (`core/busca/controle.py`), sem janela, com prioridade
abaixo do normal; continua rodando com o app fechado. Os caminhos chegam
explícitos porque o processo filho não enxerga o que o pai desviou (os
testes desviam para pastas temporárias).

Nunca abre o banco principal: as barras vêm do espelho Parquet. É o que
deixa a busca rodar no pregão, ao lado da captura e das Ordens real.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("busca_id", type=int)
    ap.add_argument("--pasta")
    ap.add_argument("--banco")
    ap.add_argument("--db-principal")
    a = ap.parse_args(argv)

    from core import db_manager as db
    from core.busca import banco, controle, prioridade

    if a.pasta:
        banco.PASTA = Path(a.pasta)
    if a.banco:
        banco.CAMINHO = Path(a.banco)
    if a.db_principal:
        db.DB_PATH = Path(a.db_principal)
    prioridade.baixar()

    # o app testa a trava a cada leitura (trava e solta): tentar algumas
    # vezes antes de concluir que outra busca está rodando
    trava = None
    for _ in range(25):
        trava = controle.travar(banco.PASTA / "rodando.lock")
        if trava is not None:
            break
        time.sleep(0.2)
    if trava is None:
        print("outra busca já está rodando", flush=True)
        return 4
    try:
        from core.busca.motor import Busca, escrever_json

        escrever_json(banco.PASTA / "rodando.json", {"busca_id": a.busca_id})
        status = Busca(a.busca_id).rodar()
        print(f"busca {a.busca_id}: {status}", flush=True)
        return 0
    except BaseException:
        traceback.print_exc()
        return 1
    finally:
        controle.soltar(trava)


if __name__ == "__main__":
    sys.exit(main())
