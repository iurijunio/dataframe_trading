"""Sincronização automática de candles com o MT5.

Gera um TSV no MESMO formato da exportação manual do MT5 e usa
`core.ingest.ingest_csv` sem alterá-la — zero lógica de merge nova aqui.
Escopo: só WIN$N. Ações, outras fontes e a tela de importar/excluir ativo
ficam para outro projeto (ver docs/superpowers/specs/2026-09-23-mt5-sync-design.md §7).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from . import calendar as cal
from . import captura
from . import db_manager as db
from . import ingest as ing
from . import rollovers as roll

FOLGA_DIAS = 5

# O botão é manual e não tem o relógio do servidor. Ele só grava o último
# minuto devolvido se o PC disser que ele começou há mais de 10 min, o que
# cobre um relógio errado em até 9 min. O minuto que ficar de fora entra na
# próxima sincronização ou pela captura.
MARGEM_SINCRONIZAR = timedelta(minutes=10)

HEADER = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"


# O módulo MetaTrader5 guarda uma única conexão por processo: ler a conta
# no meio de uma sincronização derrubaria a conexão de quem está lendo barras.
_TERMINAL = threading.Lock()


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


def buscar_barras(symbol: str, desde: datetime, ate: datetime) -> pl.DataFrame:
    """`desde`/`ate` e o `time` devolvido são hora de Brasília, sem
    conversão. Achado real (01/10/2026): o MT5 já entrega o `time` das
    barras no relógio do servidor da corretora; somar ou subtrair fuso
    gravou seis meses de pregão deslocado em 3 h.

    O pacote converte datetime sem fuso pelo fuso do PC, o que deslocaria a
    janela pedida; marcar como UTC faz o valor seguir como está.
    """
    import MetaTrader5 as mt5

    if not mt5.symbol_select(symbol, True):
        raise MT5Error(f"não foi possível selecionar o símbolo {symbol} no MT5.")

    taxas = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1,
                                  desde.replace(tzinfo=timezone.utc),
                                  ate.replace(tzinfo=timezone.utc))
    if taxas is None or len(taxas) == 0:
        raise MT5Error(
            f"o MT5 não devolveu nenhuma barra para {symbol} entre "
            f"{desde} e {ate}. Confira se o símbolo está certo e se há "
            "histórico baixado no terminal para esse período."
        )

    df = pl.DataFrame(taxas)
    return df.select(
        pl.from_epoch("time", time_unit="s").alias("ts"),
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
    # O MT5 nunca devolve barra do futuro; a folga de um dia só garante que
    # o pedido alcance o último minuto, qualquer que seja o relógio do PC.
    ate = datetime.now() + timedelta(days=1)

    with _TERMINAL:
        conectar()
        try:
            barras = buscar_barras(symbol, desde, ate)
        finally:
            desconectar()

    barras = captura.fechados(
        barras, datetime.now() - MARGEM_SINCRONIZAR + captura.FECHA_APOS)
    if barras.height == 0:
        raise MT5Error("nenhum candle fechado novo no MT5 — tente de novo "
                       "em alguns minutos")

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


def ler_conta(terminal: str | None = None) -> dict:
    """O que o terminal MT5 aberto diz da conta logada nele: número,
    servidor, se é demo ou real (informado pela corretora) e o titular.

    A senha nunca passa por aqui: o MT5 já está logado, só lemos.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise MT5Error("o pacote MetaTrader5 não está instalado neste "
                       "computador") from e

    if not _TERMINAL.acquire(timeout=2):
        raise MT5Error("o MT5 está ocupado sincronizando — tente de novo "
                       "em instantes")
    try:
        ok = mt5.initialize(path=terminal) if terminal else mt5.initialize()
        if not ok:
            raise MT5Error(
                f"não foi possível conectar ao MT5 ({mt5.last_error()}). "
                "Abra o MetaTrader 5 e faça login na conta.")
        info = mt5.account_info()
        if info is None:
            raise MT5Error("o MT5 está aberto mas não está logado em "
                           "nenhuma conta")
        # trade_mode: 0 demo, 1 concurso (também sem dinheiro de verdade), 2 real
        tipo = "real" if info.trade_mode == 2 else "demo"
        return {"login": int(info.login), "servidor": info.server,
                "tipo": tipo, "titular": info.name, "corretora": info.company}
    finally:
        try:
            mt5.shutdown()
        finally:
            _TERMINAL.release()
