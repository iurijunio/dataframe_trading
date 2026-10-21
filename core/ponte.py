"""Ponte entre a captura (demo) e o processo da conta real (spec conta-real
§4.2 e §10 R8–R11).

A captura publica em `desejados.json` o que o papel quer fazer agora; o
processo da real lê esse arquivo e age nele. A real devolve em
`ack_real.json` o `seq` que já tratou, e a captura espera esse ack por um
instante antes de executar a demo.

Puro e só de arquivo: sem banco e sem MT5. Todas as leituras e escritas
usam `PASTA` na hora da chamada (o conftest a desvia para tmp).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path

from . import db_manager as db
from .papel_vivo import Desejado

log = logging.getLogger(__name__)

PASTA = db.DATA / "ao_vivo"
ARQ_DESEJADOS = "desejados.json"
ARQ_ACK = "ack_real.json"
ARQ_VIVO_REAL = "real_vivo.json"
VERSAO = 1
TENTATIVAS = 5                 # escrita: até 5 tentativas (R10)
ESPERA_TENTATIVA_S = 0.005
# campos que mudam a cada volta ou são do próprio seq: não contam como
# "conteúdo mudou" (a captura compara o resto)
CAMPOS_VIVOS = ("seq", "vivo_em", "escrito_em_srv")


def _jsonavel(v):
    """Valores que o json padrão não aceita (inteiro do numpy, data)."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return str(v)


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _desejado(d: Desejado) -> dict:
    return {f.name: _iso(getattr(d, f.name))
            for f in fields(Desejado) if f.name != "contratos"}


def serializar(desejados: dict, disponivel: bool, contrato_dia: dict | None,
               seq: int, agora_srv) -> dict:
    """O arquivo que a real lê: cada Desejado inteiro (menos `contratos`),
    o bloco do contrato do dia e o batimento (`vivo_em`, PC)."""
    return {
        "versao": VERSAO,
        "seq": seq,
        "vivo_em": time.time(),
        "escrito_em_srv": _iso(agora_srv),
        "disponivel": bool(disponivel),
        "contrato_dia": (None if contrato_dia is None
                         else {k: _iso(v) for k, v in contrato_dia.items()}),
        "desejados": {str(lig): _desejado(d) for lig, d in desejados.items()},
    }


def _dt(v):
    return datetime.fromisoformat(v) if v else None


def ler(dados: dict):
    """Inverso de `serializar`: (desejados, disponivel, contrato_dia, seq,
    vivo_em). Levanta se faltar campo (quem chama decide: `ler_arquivo`)."""
    desejados = {}
    for lig, campos in dados["desejados"].items():
        kw = dict(campos)
        kw["entry_ts"] = _dt(kw.get("entry_ts"))
        kw["toque_em"] = _dt(kw.get("toque_em"))
        desejados[int(lig)] = Desejado(**kw)
    contrato = dados["contrato_dia"]
    if contrato is not None:
        contrato = dict(contrato)
        for campo in ("vence_em", "amanha"):
            if contrato.get(campo):
                contrato[campo] = date.fromisoformat(contrato[campo])
    return (desejados, bool(dados["disponivel"]), contrato,
            int(dados["seq"]), float(dados["vivo_em"]))


def _gravar(alvo: Path, dados: dict) -> bool:
    """tmp + os.replace; em PermissionError (o Windows segura o arquivo por
    um instante) tenta de novo. Nunca levanta."""
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_name(alvo.name + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, default=_jsonavel),
                       encoding="utf-8")
        for tentativa in range(TENTATIVAS):
            try:
                os.replace(tmp, alvo)
                return True
            except PermissionError:
                if tentativa < TENTATIVAS - 1:
                    time.sleep(ESPERA_TENTATIVA_S)
        log.warning("ponte: %s segue preso após %d tentativas", alvo.name, TENTATIVAS)
    except Exception:
        log.exception("ponte: não consegui gravar %s", alvo.name)
    return False


def escrever(dados: dict) -> bool:
    """Publica os desejados. Devolve False (e loga) em falha; nunca levanta."""
    return _gravar(PASTA / ARQ_DESEJADOS, dados)


def ler_arquivo() -> dict | None:
    """O arquivo de desejados já validado, ou None (ausente, JSON inválido,
    incompleto)."""
    try:
        dados = json.loads((PASTA / ARQ_DESEJADOS).read_bytes())
        ler(dados)
    except Exception:
        return None
    return dados


def fresco(dados: dict, agora_pc: float | None = None, limite_s: float = 5.0) -> bool:
    """O batimento (`vivo_em`, relógio do PC) tem menos de `limite_s`."""
    try:
        vivo = float(dados["vivo_em"])
    except (KeyError, TypeError, ValueError):
        return False
    agora = time.time() if agora_pc is None else agora_pc
    return agora - vivo <= limite_s


def gravar_ack(seq: int) -> bool:
    return _gravar(PASTA / ARQ_ACK, {"seq": int(seq)})


def ler_ack() -> int | None:
    try:
        return int(json.loads((PASTA / ARQ_ACK).read_bytes())["seq"])
    except Exception:
        return None


def gravar_vivo_real() -> bool:
    """Batimento do processo da conta real (chamado a cada volta dele). O
    tempo vai dentro do arquivo: o mtime não é confiável no Windows."""
    return _gravar(PASTA / ARQ_VIVO_REAL, {"vivo_em": time.time()})


def real_ativo(agora_pc: float | None = None, limite_s: float = 5.0) -> bool:
    """O processo da real bateu há menos de `limite_s` (sem arquivo = não)."""
    try:
        vivo = float(json.loads((PASTA / ARQ_VIVO_REAL).read_bytes())["vivo_em"])
    except Exception:
        return False
    agora = time.time() if agora_pc is None else agora_pc
    return agora - vivo <= limite_s
