"""Descoberta e troca de estratégias.

Cada arquivo em `strategies/` que exponha `name`, `params_schema` e `signals`
é uma estratégia. Nada precisa ser registrado à mão: soltar o arquivo na
pasta basta.

A estratégia em uso é estado do processo, não da tela — o motor, a mineração
e os campos de parâmetro leem daqui em vez de importarem um módulo fixo, que
era o que obrigava a editar três arquivos para plugar outra.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

PASTA = Path(__file__).resolve().parent
OCULTOS = {"base", "registry"}
PADRAO = "setup_cruzamento"

_cache: dict[str, ModuleType] = {}
_atual: str | None = None


def _valida(mod: ModuleType) -> bool:
    return all(hasattr(mod, a) for a in ("name", "params_schema", "signals"))


def descobrir() -> list[dict]:
    """Lista as estratégias disponíveis, em ordem alfabética pelo rótulo.

    Um módulo quebrado não derruba a lista: ele é ignorado e o resto aparece.
    """
    achadas = []
    for info in pkgutil.iter_modules([str(PASTA)]):
        if info.name.startswith("_") or info.name in OCULTOS:
            continue
        try:
            mod = carregar(info.name)
        except Exception:
            continue
        if _valida(mod):
            achadas.append({
                "modulo": info.name,
                "label": getattr(mod, "label", None) or mod.name,
                "n_params": len(mod.params_schema),
            })
    return sorted(achadas, key=lambda e: e["label"].lower())


def carregar(nome: str) -> ModuleType:
    if nome not in _cache:
        mod = importlib.import_module(f"strategies.{nome}")
        if not _valida(mod):
            raise ValueError(
                f"strategies/{nome}.py não expõe name, params_schema e signals"
            )
        _cache[nome] = mod
    return _cache[nome]


def definir(nome: str) -> ModuleType:
    global _atual
    mod = carregar(nome)
    _atual = nome
    return mod


def nome_atual() -> str:
    global _atual
    if _atual is None:
        disponiveis = descobrir()
        alvo = PADRAO if any(e["modulo"] == PADRAO for e in disponiveis) else None
        if alvo is None:
            if not disponiveis:
                raise RuntimeError(f"nenhuma estratégia válida em {PASTA}")
            alvo = disponiveis[0]["modulo"]
        _atual = alvo
    return _atual


def atual() -> ModuleType:
    return carregar(nome_atual())
