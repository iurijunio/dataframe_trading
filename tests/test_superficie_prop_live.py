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
    ("core.codigo", "hash_estrategia"): ["estrategia", "pasta"],
}


@pytest.mark.parametrize(("modulo", "nome"), list(ASSINATURAS))
def test_assinatura_fixada(modulo, nome):
    funcao = getattr(importlib.import_module(modulo), nome)
    assert list(inspect.signature(funcao).parameters) == ASSINATURAS[(modulo, nome)], AVISO


def test_constantes_existem():
    from core import engine, papel

    assert papel.FECHAMENTO_DIA_ENCERRADO == "00:00", AVISO
    assert isinstance(engine.VERSAO, str) and engine.VERSAO, AVISO


def test_hash_estrategia_devolve_hex_ou_none(tmp_path):
    """A ponte compara o hash da worktree fixa com o `code_hash` do pacote."""
    from core import codigo

    (tmp_path / "base.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "minha.py").write_text("y = 2\n", encoding="utf-8")
    h = codigo.hash_estrategia("minha", tmp_path)
    assert isinstance(h, str) and len(h) == 64 and int(h, 16) >= 0, AVISO
    assert codigo.hash_estrategia("nao_existe", tmp_path) is None, AVISO


def test_contrato_do_pacote():
    import dataclasses

    from core.contratos import pacote_mesa

    assert issubclass(pacote_mesa.VersaoDiferente, pacote_mesa.PacoteInvalido), AVISO
    campos = {c.name for c in dataclasses.fields(pacote_mesa.VariantePacote)}
    assert "code_hash" in campos, AVISO
