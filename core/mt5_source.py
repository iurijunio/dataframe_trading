"""Sincronização automática de candles com o MT5.

Gera um TSV no MESMO formato da exportação manual do MT5 e usa
`core.ingest.ingest_csv` sem alterá-la — zero lógica de merge nova aqui.
Escopo: só WIN$N. Ações, outras fontes e a tela de importar/excluir ativo
ficam para outro projeto (ver docs/superpowers/specs/2026-09-23-mt5-sync-design.md §7).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from . import calendar as cal
from . import db_manager as db
from . import ingest as ing
from . import rollovers as roll

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


def buscar_barras(symbol: str, desde: datetime, ate: datetime) -> pl.DataFrame:
    """`desde`/`ate` são hora de corretor (a mesma convenção já salva no
    banco, vinda das exportações manuais). A API do MT5 devolve `time` em
    UTC de verdade — por isso o pedido sai em UTC (`- offset`) e o
    resultado volta para hora de corretor (`+ offset`) antes de devolver,
    para casar com o que já está gravado.
    """
    import MetaTrader5 as mt5

    if not mt5.symbol_select(symbol, True):
        raise MT5Error(f"não foi possível selecionar o símbolo {symbol} no MT5.")

    offset = offset_servidor(symbol)
    taxas = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1,
                                  desde - offset, ate - offset)
    if taxas is None or len(taxas) == 0:
        raise MT5Error(
            f"o MT5 não devolveu nenhuma barra para {symbol} entre "
            f"{desde} e {ate}. Confira se o símbolo está certo e se há "
            "histórico baixado no terminal para esse período."
        )

    df = pl.DataFrame(taxas)
    return df.select(
        (pl.from_epoch("time", time_unit="s") + offset).alias("ts"),
        pl.col("open"), pl.col("high"), pl.col("low"), pl.col("close"),
        pl.col("tick_volume"), pl.col("real_volume").alias("volume"),
        pl.col("spread"),
    ).sort("ts")


def conectar() -> None:
    import MetaTrader5 as mt5

    if not mt5.initialize():
        erro = mt5.last_error()
        raise MT5Error(
            f"não foi possível conectar ao terminal MT5 ({erro}). "
            "Abra o MetaTrader 5 e faça login antes de sincronizar."
        )


def desconectar() -> None:
    import MetaTrader5 as mt5
    mt5.shutdown()


@dataclass
class SincronizacaoResult:
    ingest: ing.IngestResult
    trading_days: int
    rollovers: int


def sincronizar(con, symbol: str, price_decimals: int) -> SincronizacaoResult:
    ultimo = con.execute(
        "SELECT max(ts) FROM bars_m1 WHERE symbol = ?", [symbol]
    ).fetchone()[0]
    if ultimo is None:
        raise MT5Error(
            f"{symbol} não tem nenhuma barra salva ainda — a sincronização "
            "automática só atualiza uma base que já existe. Faça a "
            "primeira importação manual (cli.py ingest) antes."
        )

    desde = ultimo - timedelta(days=FOLGA_DIAS)
    # `datetime.now()` é a hora da MÁQUINA local, não a hora de corretor
    # que `buscar_barras` espera (mesma convenção do `ultimo` salvo). Em
    # vez de calcular a hora de corretor certa aqui — o que exigiria
    # offset_servidor, que esta função deliberadamente não chama —, pede-se
    # uma margem folgada além de agora: o MT5 nunca devolve barra do
    # futuro, então isso nunca traz dado inventado, só evita perder as
    # últimas barras por causa do fuso da máquina que roda o botão ser
    # diferente do fuso do corretor.
    ate = datetime.now() + timedelta(days=1)

    conectar()
    try:
        barras = buscar_barras(symbol, desde, ate)
    finally:
        desconectar()

    agora = datetime.now()
    destino = db.RAW_DIR / f"mt5_sync_{agora:%Y%m%d_%H%M%S}_{agora.microsecond:06d}.tsv"
    exportar_tsv(barras, destino)

    resultado = ing.ingest_csv(con, destino, symbol, price_decimals=price_decimals)

    # ingest_csv já commitou: as barras novas estão gravadas a partir
    # daqui, mesmo que o resto falhe. Se falhar, a mensagem precisa dizer
    # isso — "erro inesperado" genérico esconderia que parte do trabalho
    # já aconteceu, e o operador rodaria de novo achando que nada mudou.
    try:
        inst = db.load_instrument_yaml(symbol)
        n_days = cal.rebuild_trading_days(con, symbol)
        n_roll = roll.rebuild_rollovers(con, symbol, inst.get("rollover_policy"))
        db.export_parquet(con, symbol)
    except Exception as erro:
        raise MT5Error(
            f"as barras novas já foram gravadas ({resultado.rows_inserted} "
            f"inseridas, {resultado.rows_updated} revisadas), mas a "
            f"reconstrução de pregões/rolagens falhou: {erro}. Rode "
            "'cli.py derive' para terminar."
        ) from erro

    return SincronizacaoResult(ingest=resultado, trading_days=n_days, rollovers=n_roll)
