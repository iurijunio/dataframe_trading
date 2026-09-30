"""Impressão digital do código de uma estratégia.

O plano grava parâmetros, mas os números que ele promete vieram de uma
VERSÃO do código. Se o arquivo muda depois, o que roda ao vivo já não é o
que foi aprovado — e nada avisava (achado real: rompimento_abertura.py
editado com o plano #4 ativo, 30/09/2026).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import db_manager as db


def hash_estrategia(estrategia: str, pasta: Path | None = None) -> str | None:
    pasta = Path(pasta) if pasta else db.ROOT / "strategies"
    arquivo = pasta / f"{estrategia}.py"
    if not arquivo.exists():
        return None
    h = hashlib.sha256()
    # base.py entra junto: é o contrato de toda estratégia, e mudar ele
    # muda o sinal de todas
    for parte in (pasta / "base.py", arquivo):
        if parte.exists():
            # o git troca LF por CRLF nesta máquina; sem normalizar, todo
            # checkout acusaria "código mudou"
            h.update(parte.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()
