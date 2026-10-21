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

# "ordem_teste": o botão "Ordem de teste" — quem executa é a captura (o
# Motor), nunca a tela; o comando só leva a conta demo do clique
TIPOS = frozenset({"zerar_tudo", "encerrar_posicao", "envio", "ordem_teste"})
# constante de módulo: o conftest a desvia — um teste não pode deixar um
# comando para a captura real do usuário consumir. Quem usa lê
# `comandos.PASTA` na hora (nunca `from ... import PASTA`).
PASTA = db.DATA / "ao_vivo" / "comandos"
# a conta real tem processo próprio (parte 5): cada processo lê só a sua
# pasta, então um comando da demo nunca chega à real e vice-versa
PASTA_REAL = db.DATA / "ao_vivo" / "comandos_real"


def pasta_do_tipo(tipo: str) -> Path:
    """A pasta de comandos da conta `tipo`. Lê as constantes na hora: o
    conftest as desvia depois do import."""
    if tipo == "demo":
        return PASTA
    if tipo == "real":
        return PASTA_REAL
    raise ValueError(f"tipo de conta desconhecido: {tipo!r}")


def escrever_zerar_tudo() -> list[str]:
    """"Zerar tudo" vai para as duas pastas e nunca toca no banco: com uma
    mineração segurando a escrita ele já precisa valer."""
    return [escrever(PASTA, "zerar_tudo"), escrever(PASTA_REAL, "zerar_tudo")]


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


def consumir(pasta, registrar=None, tipos=None) -> list[dict]:
    """Os comandos em ordem, cada um apagado depois de lido.

    `tipos` (opcional): só estes tipos são consumidos; os outros ficam na
    pasta para a volta que os executa (a captura recusa a "Ordem de teste"
    sem tocar no "Zerar tudo" que ainda não pode cumprir).

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
        if tipos is not None and cmd["tipo"] not in tipos:
            continue
        # registrar devolve False para um comando já conhecido (o arquivo que
        # não apagou da outra vez): sai da pasta sem rodar de novo
        novo = registrar is None or registrar(cmd) is not False
        arq.unlink(missing_ok=True)
        if novo:
            out.append(cmd)
    return out
