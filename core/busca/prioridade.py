"""Prioridade abaixo do normal: a busca pode rodar no pregão, ao lado da
captura e das Ordens real, e nunca pode disputar a CPU com elas."""

from __future__ import annotations

import sys

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def _kernel32():
    """Tipos explícitos: o handle do processo é ponteiro de 64 bits, e o
    padrão do ctypes (int de 32) o corta — a chamada falhava calada."""
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.SetPriorityClass.restype = wintypes.BOOL
    k.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    k.GetPriorityClass.restype = wintypes.DWORD
    return k


def baixar() -> bool:
    """Põe o processo atual abaixo do normal (os filhos herdam). Fora do
    Windows não faz nada."""
    if sys.platform != "win32":
        return False
    k = _kernel32()
    return bool(k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))


def atual() -> int | None:
    if sys.platform != "win32":
        return None
    k = _kernel32()
    return int(k.GetPriorityClass(k.GetCurrentProcess()))
