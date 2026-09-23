"""Sincronização automática de candles com o MT5.

Gera um TSV no MESMO formato da exportação manual do MT5 e usa
`core.ingest.ingest_csv` sem alterá-la — zero lógica de merge nova aqui.
Escopo: só WIN$N. Ações, outras fontes e a tela de importar/excluir ativo
ficam para outro projeto (ver docs/superpowers/specs/2026-09-23-mt5-sync-design.md §7).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def offset_servidor(symbol: str) -> timedelta:
    """Calibra o fuso do broker contra UTC.

    O MT5 guarda tudo em UTC puro, mas o servidor do corretor pode estar
    em outro fuso — sem calibrar, o range pedido ao MT5 erra por horas.
    """
    import MetaTrader5 as mt5

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise MT5Error(f"símbolo {symbol} não encontrado no MT5.")

    hora_servidor = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    agora = datetime.now(timezone.utc)
    bruto = hora_servidor - agora

    horas = round(bruto.total_seconds() / 3600)
    offset = timedelta(hours=horas)
    if abs((bruto - offset).total_seconds()) > 120:
        raise MT5Error(
            f"fuso do servidor não é múltiplo de hora inteira ({bruto}); "
            "sincronização parada para não gravar hora errada."
        )
    if abs(horas) > 14:
        raise MT5Error(
            f"offset implausível ({horas}h) — nenhum corretor real fica a "
            "mais de 14h de UTC. O tick pode estar parado (mercado fechado "
            "há dias, terminal sem cotação nova)."
        )
    return offset
