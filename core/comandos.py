"""Comandos da tela para a captura, por arquivo (spec §3, §5.8).

Não passam pelo banco: "Zerar tudo" com uma mineração segurando a escrita
não pode esperar. A tela escreve um arquivo atômico; a captura consome e
apaga na volta seguinte e devolve o resultado no estado.json.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from . import db_manager as db

log = logging.getLogger(__name__)

TIPOS = frozenset({"zerar_tudo", "encerrar_posicao", "envio"})
# constante de módulo: o conftest a desvia — um teste não pode deixar um
# comando para a captura real do usuário consumir. Quem usa lê
# `comandos.PASTA` na hora (nunca `from ... import PASTA`).
PASTA = db.DATA / "ao_vivo" / "comandos"


def escrever(pasta, tipo: str, **dados) -> str:
    if tipo not in TIPOS:
        raise ValueError(f"comando desconhecido: {tipo}")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    cid = uuid.uuid4().hex
    # o nome começa pela hora: a ordem alfabética é a ordem em que a tela
    # escreveu (desligar e religar em sequência não podem trocar de lugar)
    nome = f"{datetime.now():%Y%m%d%H%M%S%f}-{cid}.json"
    tmp = pasta / (nome + ".tmp")
    tmp.write_text(json.dumps({"id": cid, "tipo": tipo,
                               "criado_em": datetime.now().isoformat(), **dados}),
                   encoding="utf-8")
    # os.replace é atômico: a captura nunca lê um comando pela metade
    os.replace(tmp, pasta / nome)
    return cid


def consumir(pasta, registrar=None) -> list[dict]:
    """Os comandos em ordem, cada um apagado depois de lido.

    `registrar(comando)` roda ANTES de apagar o arquivo (a captura grava o
    comando no diário do dia): se ele falhar, o arquivo fica para a volta
    seguinte e o erro sobe — uma queda no meio nunca perde um comando."""
    pasta = Path(pasta)
    if not pasta.exists():
        return []
    out = []
    for arq in sorted(pasta.glob("*.json")):
        try:
            texto = arq.read_text(encoding="utf-8")
        except OSError:
            # arquivo preso por instantes (antivírus, Windows): fica para a
            # próxima volta — apagar aqui perderia um comando bom
            log.warning("comando %s ilegível agora; fica para a próxima volta", arq.name)
            continue
        try:
            cmd = json.loads(texto)
            if not isinstance(cmd, dict) or cmd.get("tipo") not in TIPOS:
                raise ValueError("comando sem tipo conhecido")
        except ValueError as erro:
            # lixo nunca vira comando, e não pode travar os de trás
            log.warning("comando ilegível descartado: %s (%s)", arq.name, erro)
            arq.unlink(missing_ok=True)
            continue
        if registrar is not None:
            registrar(cmd)
        arq.unlink(missing_ok=True)
        out.append(cmd)
    return out
