"""Prioridade abaixo do normal: a busca pode rodar no pregão, ao lado da
captura e das Ordens real, e nunca pode disputar a CPU com elas."""

from __future__ import annotations

import sys

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def baixar() -> bool:
    """Põe o processo atual abaixo do normal (os filhos herdam). Fora do
    Windows não faz nada."""
    if sys.platform != "win32":
        return False
    import ctypes

    k = ctypes.windll.kernel32
    return bool(k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))


def atual() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    k = ctypes.windll.kernel32
    return int(k.GetPriorityClass(k.GetCurrentProcess()))
