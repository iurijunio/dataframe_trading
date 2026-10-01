"""Serviço de captura: as contas, sem Dash e sem MetaTrader5 no topo.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §5.

O processo (`captura.py`, na raiz) é só o laço; tudo o que decide alguma
coisa mora aqui, para ser testado com MT5 e relógio falsos. A regra que
sustenta o resto: a captura nunca depende de ter "visto" cada minuto — a
cada volta pede ao MT5 tudo o que fechou desde o último candle salvo.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

# O minuto só fecha quando o seguinte começa; 5 s de folga cobrem o atraso
# entre o último negócio e a barra seguinte aparecer no MT5.
FECHA_APOS = timedelta(seconds=65)


def fechados(barras: pl.DataFrame, agora_servidor: datetime | None) -> pl.DataFrame:
    """Só os candles fechados. Todos menos o último já fecharam (existe
    barra depois deles); o último só fecha 65 s depois do início do minuto,
    pela hora do SERVIDOR — o relógio do PC pode estar adiantado."""
    if barras.height == 0:
        return barras
    barras = barras.sort("ts")
    if agora_servidor is not None and agora_servidor >= barras["ts"][-1] + FECHA_APOS:
        return barras
    return barras.head(barras.height - 1)


class RelogioServidor:
    """Hora da corretora estimada sem confiar no relógio do PC: o último
    tick mais o tempo decorrido (monotonic) desde que esse valor apareceu.
    Fica sempre um pouco atrás da hora real — erra para o lado seguro."""

    def __init__(self):
        self._tick = None
        self._visto = None

    def observar(self, tick: datetime | None, mono: float) -> None:
        if tick is None:
            self._tick = self._visto = None
        elif tick != self._tick:
            self._tick, self._visto = tick, mono

    def agora(self, mono: float) -> datetime | None:
        if self._tick is None:
            return None
        return self._tick + timedelta(seconds=mono - self._visto)

    def desvio_s(self, agora_pc: datetime, mono: float) -> float | None:
        """PC menos servidor, em segundos. Só vale com tick recente (< 10 s):
        com o mercado parado a estimativa fica para trás e o desvio mentiria."""
        if self._tick is None or mono - self._visto > 10:
            return None
        return (agora_pc - self.agora(mono)).total_seconds()
