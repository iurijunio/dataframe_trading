"""Testes da sincronização automática com o MT5 (projeto B).

O que estes testes protegem: o TSV que `exportar_tsv` escreve precisa ser
exatamente o que `core.ingest.read_mt5_export` — já testado e usado pela
importação manual — sabe ler de volta, sem nenhuma lógica de merge nova
aqui.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ingest as ing  # noqa: E402
from core import mt5_source as src  # noqa: E402


def _barras():
    return pl.DataFrame({
        "ts": [datetime(2026, 9, 21, 9, 0), datetime(2026, 9, 21, 9, 1)],
        "open": [100000, 100050],
        "high": [100100, 100120],
        "low": [99950, 100000],
        "close": [100050, 100080],
        "tick_volume": [120, 95],
        "volume": [0, 0],
        "spread": [5, 5],
    })


def test_exportar_tsv_e_read_mt5_export_fazem_roundtrip(tmp_path):
    """O que `exportar_tsv` escreve, `ing.read_mt5_export` precisa
    conseguir ler de volta, com os mesmos valores — senão a sincronização
    grava um arquivo que a ingestão existente rejeita."""
    destino = tmp_path / "mt5_sync_teste.tsv"
    barras = _barras()

    src.exportar_tsv(barras, destino)
    lido = ing.read_mt5_export(destino, price_decimals=0)

    assert lido["ts"].to_list() == barras["ts"].to_list()
    assert lido["open"].to_list() == barras["open"].to_list()
    assert lido["high"].to_list() == barras["high"].to_list()
    assert lido["low"].to_list() == barras["low"].to_list()
    assert lido["close"].to_list() == barras["close"].to_list()
    assert lido["tick_volume"].to_list() == barras["tick_volume"].to_list()
    assert lido["volume"].to_list() == barras["volume"].to_list()
    assert lido["spread"].to_list() == barras["spread"].to_list()


def test_exportar_tsv_cria_a_pasta_se_nao_existir(tmp_path):
    destino = tmp_path / "sub" / "pasta" / "mt5_sync_teste.tsv"
    src.exportar_tsv(_barras(), destino)
    assert destino.exists()


def test_exportar_tsv_recusa_coluna_faltando(tmp_path):
    """Sem checagem explícita, faltar 'spread' vira um KeyError cru dentro
    do laço — a mensagem precisa dizer qual coluna falta, no mesmo estilo
    de ing.read_mt5_export."""
    barras = _barras().drop("spread")
    with pytest.raises(ValueError, match="spread"):
        src.exportar_tsv(barras, tmp_path / "sem_coluna.tsv")


def test_exportar_tsv_recusa_valor_nulo(tmp_path):
    """Um None gravado como texto ('None') no TSV quebraria read_mt5_export
    de um jeito confuso lá na frente — recusa aqui, com motivo."""
    barras = _barras().with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(None).otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(ValueError, match="nulo"):
        src.exportar_tsv(barras, tmp_path / "com_nulo.tsv")


# ---------------------------------------------------------- offset_servidor

class _FakeTick:
    def __init__(self, epoch):
        self.time = epoch


class _FakeMT5Offset:
    """Substitui o módulo MetaTrader5 nos testes de offset_servidor."""

    def __init__(self, epoch_servidor):
        self._epoch = epoch_servidor

    def symbol_info_tick(self, symbol):
        if symbol != "WIN$N":
            return None
        return _FakeTick(self._epoch)


def _instalar_fake_mt5(monkeypatch, epoch_servidor):
    fake = _FakeMT5Offset(epoch_servidor)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return fake


def test_offset_servidor_calibra_fuso_de_horas_inteiras(monkeypatch):
    """Servidor 3 horas à frente do UTC (ex: fuso do corretor)."""
    agora = datetime.now(timezone.utc)
    epoch_servidor = int((agora + timedelta(hours=3)).timestamp())
    _instalar_fake_mt5(monkeypatch, epoch_servidor)

    offset = src.offset_servidor("WIN$N")

    assert offset == timedelta(hours=3)


def test_offset_servidor_recusa_simbolo_desconhecido(monkeypatch):
    _instalar_fake_mt5(monkeypatch, 0)
    with pytest.raises(src.MT5Error, match="não encontrado"):
        src.offset_servidor("XXX$N")


def test_offset_servidor_recusa_fuso_que_nao_e_hora_inteira(monkeypatch):
    """Se o offset não bate com nenhuma hora inteira, algo está errado na
    calibração: melhor parar do que gravar hora torta silenciosamente."""
    agora = datetime.now(timezone.utc)
    epoch_servidor = int((agora + timedelta(hours=3, minutes=17)).timestamp())
    _instalar_fake_mt5(monkeypatch, epoch_servidor)

    with pytest.raises(src.MT5Error, match="múltiplo de hora"):
        src.offset_servidor("WIN$N")


def test_offset_servidor_recusa_tick_parado_ha_dias(monkeypatch):
    """Um tick de 3 dias atrás (mercado fechado, terminal sem cotação nova)
    também bate 'múltiplo de hora inteira' — 72h é múltiplo de hora — e
    passaria disfarçado de fuso válido sem um limite de plausibilidade.
    Nenhum corretor real fica a mais de 14h de UTC."""
    agora = datetime.now(timezone.utc)
    epoch_servidor = int((agora - timedelta(days=3)).timestamp())
    _instalar_fake_mt5(monkeypatch, epoch_servidor)

    with pytest.raises(src.MT5Error, match="implausível"):
        src.offset_servidor("WIN$N")
