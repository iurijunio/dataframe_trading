"""Correção da base com hora deslocada — roda UMA vez (spec captura §0).

    .venv/Scripts/python.exe corrigir_base.py             # simulação: só mostra
    .venv/Scripts/python.exe corrigir_base.py --executar  # faz
    .venv/Scripts/python.exe corrigir_base.py --retomar   # só refaz os passos 5-7

Antes: feche o app (iniciar.bat) e a captura; abra o MT5 logado.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from core import calendar as cal
from core import db_manager as db
from core import diario
from core import ingest as ing
from core import mt5_source as src
from core import reparo_base as R
from core import rollovers as roll

SYMBOL = "WIN$N"
MARCA_LOTE_ERRADO = "mt5_sync_2026092"
LOTES_ESPERADOS = {3, 4}
CSV_PADRAO = db.RAW_DIR / "m1-hist-16-03-2026.csv"
MSG_SEM_HISTORICO = ("o MT5 não tem o histórico desde 09/03 (confira 'Máx. barras no "
                     "gráfico' em Ferramentas › Opções › Gráficos) — nada foi apagado")


# ------------------------------------------------------------------ passo 0
def mt5_tem_historico() -> bool:
    """Só leitura no MT5. Sem o histórico de 09/03 não dá para refazer a
    base, então isto vem antes de qualquer coisa que apague."""
    try:
        src.conectar()
        try:
            b = src.buscar_barras(SYMBOL, datetime(2026, 3, 9), datetime(2026, 3, 17))
        finally:
            src.desconectar()
    except Exception as erro:  # terminal fechado, sem login, sem pacote...
        print(f"MT5 indisponível: {erro}")
        return False
    for dia in (date(2026, 3, 9), date(2026, 3, 16)):
        horas = [t.time() for t in b["ts"].to_list() if t.date() == dia]
        if not horas or not (R.ABRE[0][0] <= min(horas) <= R.ABRE[0][1]):
            return False
    return True


# ------------------------------------------------------------------ passo 1
def lotes_errados(con) -> list[tuple[int, str]]:
    return con.execute(
        "SELECT ingest_id, source_file FROM ingest_log "
        "WHERE source_file LIKE ? ORDER BY ingest_id", [f"%{MARCA_LOTE_ERRADO}%"]).fetchall()


def _contagens(con, lotes) -> tuple[dict[str, int], int]:
    tabelas = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
               for t in R.TABELAS_DERIVADAS}
    ids = [i for i, _ in lotes]
    if not ids:
        return tabelas, 0
    marcas = ",".join("?" * len(ids))
    barras = con.execute(f"SELECT count(*) FROM bars_m1 WHERE symbol = ? "
                         f"AND src_ingest_id IN ({marcas})", [SYMBOL, *ids]).fetchone()[0]
    return tabelas, barras


def _caminho_do_lote(source_file: str) -> Path | None:
    p = Path(source_file)
    for cand in (p, db.RAW_DIR / p.name):
        if cand.exists():
            return cand
    return None


# ----------------------------------------------------------------- simulação
def simular() -> int:
    """Caminho sem nenhuma escrita: só conexão read_only e leitura do MT5."""
    print("SIMULAÇÃO — nada será alterado.\n")
    print("Passo 0: conferindo o histórico no MT5...")
    if mt5_tem_historico():
        print("  OK: o MT5 tem 09/03 e 16/03 abrindo às 09:00.")
    else:
        print(f"  ABORTARIA: {MSG_SEM_HISTORICO}")

    con = db.connect(read_only=True)
    try:
        lotes = lotes_errados(con)
        tabelas, barras = _contagens(con, lotes)
    finally:
        con.close()
    ids = {i for i, _ in lotes}
    print(f"\nLotes errados (ingest_id): {sorted(ids)}"
          + ("" if ids == LOTES_ESPERADOS else "  <- diferente de {3, 4}; --executar exigiria --lotes"))
    print(f"Barras desses lotes que seriam apagadas: {barras}")
    print("\nLinhas que seriam apagadas por tabela:")
    for t, n in tabelas.items():
        print(f"  {t:22s} {n}")
    print("\nArquivos que seriam renomeados para .hora-errada:")
    for _, arq in lotes:
        c = _caminho_do_lote(arq)
        print(f"  {c if c else arq + '  (não existe)'}")
    sem_yaml = db.PARQUET_DIR / "SEM_YAML"
    if sem_yaml.exists():
        print(f"\nPasta que seria apagada: {sem_yaml}")
    return 0


# ----------------------------------------------------------------- execução
def _backup(hoje: date) -> Path:
    destino = db.ROOT.parent / "backups" / f"{hoje:%Y-%m-%d}-antes-correcao-hora"
    if destino.exists():
        raise SystemExit(f"o backup {destino} já existe; se a base já foi apagada, use --retomar")
    try:
        con = db.connect_write(tentativas=1)
    except Exception as erro:
        raise SystemExit(f"o banco está em uso (app ou captura abertos): {erro}")
    con.execute("CHECKPOINT")  # leva o .wal para o arquivo antes de copiar
    con.close()
    destino.mkdir(parents=True)
    shutil.copy2(db.DB_PATH, destino / db.DB_PATH.name)
    wal = db.DB_PATH.with_name(db.DB_PATH.name + ".wal")
    if wal.exists():
        shutil.copy2(wal, destino / wal.name)
    shutil.copytree(db.PARQUET_DIR, destino / "parquet")
    shutil.copytree(db.RAW_DIR, destino / "raw")
    return destino


def _apagar(lotes) -> None:
    ids = [i for i, _ in lotes]
    con = db.connect_write()
    try:
        with db.transacao(con):
            R.apagar_derivados(con)
            R.apagar_lotes(con, SYMBOL, ids)
            diario.registrar(
                con, "base_corrigida", "sistema",
                motivo="hora do MT5 deslocada em 3 h (16/03→23/09/2026); cadeia apagada; "
                       "ingest_log 3 e 4 ficam como histórico, arquivos renomeados .hora-errada")
    finally:
        con.close()
    for _, arq in lotes:
        c = _caminho_do_lote(arq)
        if c is not None:
            c.rename(c.with_name(c.name + ".hora-errada"))
    sem_yaml = db.PARQUET_DIR / "SEM_YAML"
    if sem_yaml.exists():
        print(f"aviso: apagando {sem_yaml}, resto de um teste antigo")
        shutil.rmtree(sem_yaml)


def _refazer(csv: Path, backup: Path | None) -> None:
    con = db.connect_write()
    try:
        try:
            ing.ingest_csv(con, csv, SYMBOL, price_decimals=0)  # passo 5, fora de transação
            src.sincronizar(con, SYMBOL, price_decimals=0)      # passo 6
            _relatorio(con)                                     # passo 7
        except BaseException as erro:
            # sem isto ficaria Parquet com a hora errada e calendário velho
            cal.rebuild_trading_days(con, SYMBOL)
            policy = db.load_instrument_yaml(SYMBOL).get("rollover_policy")
            if policy:
                roll.rebuild_rollovers(con, SYMBOL, policy)
            db.export_parquet(con, SYMBOL)
            print(f"\nFALHOU: {erro}")
            print(f"Backup: {backup or '(o de uma rodada anterior)'}")
            print("Corrija e rode `corrigir_base.py --retomar`.")
            raise SystemExit(1)
    finally:
        con.close()


def _relatorio(con) -> None:
    n, ultimo = con.execute("SELECT count(*), max(ts) FROM bars_m1 WHERE symbol = ?",
                            [SYMBOL]).fetchone()
    print(f"\nTotal de candles: {n}  |  último candle: {ultimo}")
    print("\nPregões suspeitos (olhar à mão):")
    for s in R.sessoes_suspeitas(con, SYMBOL, date(2026, 3, 9)):
        print(f"  {s['dia']}  abre {s['abre']}  fecha {s['fecha']}  {s['candles']} candles")
    print("\ndia         primeiro  último  candles")
    for dia, a, b, c in con.execute(
            "SELECT date, first_ts, last_ts, bar_count FROM trading_days "
            "WHERE symbol = ? AND date >= ? ORDER BY date", [SYMBOL, date(2026, 3, 9)]).fetchall():
        aviso = "   <<< ABAIXO DE 500, pode ser buraco" if c < 500 else ""
        print(f"{dia}  {a:%H:%M}     {b:%H:%M}   {c}{aviso}")


def executar(args) -> int:
    backup = None
    if not args.retomar:
        if not mt5_tem_historico():
            print(MSG_SEM_HISTORICO)
            return 1
        con = db.connect(read_only=True)
        try:
            lotes = lotes_errados(con)
        finally:
            con.close()
        ids = {i for i, _ in lotes}
        if ids != LOTES_ESPERADOS and (args.lotes is None or ids != set(args.lotes)):
            print(f"lotes errados achados: {sorted(ids)}; esperado {{3, 4}}. "
                  "Se estiver certo, passe --lotes com esses ids.")
            return 1
        backup = _backup(date.today())
        print(f"Backup em {backup}")
        _apagar(lotes)
    _refazer(args.csv, backup)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--executar", action="store_true")
    p.add_argument("--retomar", action="store_true")
    p.add_argument("--lotes", type=lambda s: [int(x) for x in s.split(",")])
    p.add_argument("--csv", type=Path, default=CSV_PADRAO)
    args = p.parse_args(argv)
    if args.executar or args.retomar:
        return executar(args)
    return simular()


if __name__ == "__main__":
    sys.exit(main())
