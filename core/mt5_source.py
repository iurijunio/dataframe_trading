"""Sincronização automática de candles com o MT5.

Gera um TSV no MESMO formato da exportação manual do MT5 e usa
`core.ingest.ingest_csv` sem alterá-la — zero lógica de merge nova aqui.
Escopo: só WIN$N. Ações, outras fontes e a tela de importar/excluir ativo
ficam para outro projeto (ver docs/superpowers/specs/2026-09-23-mt5-sync-design.md §7).
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

FOLGA_DIAS = 5

HEADER = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"


class MT5Error(RuntimeError):
    """Erro de conexão, símbolo ou consulta ao terminal MT5."""


_COLUNAS_ESPERADAS = ("ts", "open", "high", "low", "close",
                      "tick_volume", "volume", "spread")


def exportar_tsv(barras: pl.DataFrame, destino: Path) -> None:
    faltando = [c for c in _COLUNAS_ESPERADAS if c not in barras.columns]
    if faltando:
        raise ValueError(f"coluna(s) faltando em `barras`: {faltando}")

    nulos = {c: n for c in _COLUNAS_ESPERADAS
             if (n := barras[c].null_count())}
    if nulos:
        raise ValueError(f"valor nulo em `barras`, não dá para exportar: {nulos}")

    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as fh:
        fh.write(HEADER + "\n")
        for linha in barras.iter_rows(named=True):
            ts = linha["ts"]
            fh.write(
                f"{ts:%Y.%m.%d}\t{ts:%H:%M:%S}\t{linha['open']}\t"
                f"{linha['high']}\t{linha['low']}\t{linha['close']}\t"
                f"{linha['tick_volume']}\t{linha['volume']}\t{linha['spread']}\n"
            )
