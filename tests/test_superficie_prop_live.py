"""Superfície do Dataframe que a ponte do prop_live usa: nome e parâmetros fixados."""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AVISO = "a ponte do prop_live usa isto; mudou? avise e atualize a ponte"

# (módulo, função) -> parâmetros, na ordem
ASSINATURAS = {
    ("core.papel", "perfil_do_plano"): ["plano"],
    ("core.papel", "pregoes_de_aquecimento"): ["estrategia_mod", "params", "perfil"],
    ("core.papel", "com_barra_provisoria"): ["barras", "ts", "abertura"],
    ("core.papel", "calcular"): [
        "barras", "dia", "plano", "mod", "inst", "fechamento_hhmm", "provisoria", "toque",
    ],
    ("core.engine.execution", "run_strategy"): [
        "bars", "estrategia", "params", "profile", "instrument", "vela_aberta",
    ],
    ("core.ativo", "ficha_de"): ["cfg"],
    ("core.ativo", "preco_para_exibir"): ["v", "f"],
    ("core.ativo", "hora_para_exibir"): ["ts", "f"],
    ("core.ativo", "hora_para_motor"): ["hhmm", "f"],
    ("core.importar_lse", "preparar"): ["df", "f"],
    ("strategies.registry", "carregar"): ["nome"],
}


@pytest.mark.parametrize(("modulo", "nome"), list(ASSINATURAS))
def test_assinatura_fixada(modulo, nome):
    funcao = getattr(importlib.import_module(modulo), nome)
    assert list(inspect.signature(funcao).parameters) == ASSINATURAS[(modulo, nome)], AVISO


def test_constantes_existem():
    from core import engine, papel

    assert papel.FECHAMENTO_DIA_ENCERRADO == "00:00", AVISO
    assert isinstance(engine.VERSAO, str) and engine.VERSAO, AVISO
