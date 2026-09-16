"""Ponto de entrada da camada de dados.

    py cli.py init                      cria o schema e carrega os instrumentos
    py cli.py ingest <csv> [--symbol]   importa uma exportacao do MT5 (merge)
    py cli.py derive [--symbol]         reconstroi trading_days e rollovers
    py cli.py status [--symbol]         estado da base
    py cli.py verify [--symbol]         reconstroi do Parquet e compara
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import calendar as cal  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from core import rollovers as roll  # noqa: E402

DEFAULT_SYMBOL = "WIN$N"


def _fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n)


def cmd_init(args) -> None:
    with db.connect() as con:
        db.init_schema(con)
        symbols = db.sync_instruments(con)
        profile_id = db.ensure_default_profile(con)
    print(f"schema criado em {db.DB_PATH}")
    print(f"instrumentos carregados: {', '.join(symbols)}")
    print(f"perfil de execucao padrao: id {profile_id}")


def cmd_ingest(args) -> None:
    path = Path(args.csv)
    if not path.exists():
        sys.exit(f"arquivo nao encontrado: {path}")

    with db.connect() as con:
        db.init_schema(con)
        db.sync_instruments(con)
        inst = db.load_instrument_yaml(args.symbol)

        result = ing.ingest_csv(
            con, path, args.symbol, price_decimals=inst.get("price_decimals", 0)
        )
        print(result.summary())
        if result.conflicts:
            print("\n  divergencias (ate 5 exemplos):")
            for c in result.conflicts:
                print(f"    {c['ts']}  base={c['na_base']}  arquivo={c['no_arquivo']}")

        if args.copy_raw:
            dest = db.RAW_DIR / path.name
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(path.read_bytes())
                print(f"\n  copia bruta guardada em {dest}")

        print("\n  reconstruindo derivadas...")
        n_days = cal.rebuild_trading_days(con, args.symbol)
        n_roll = roll.rebuild_rollovers(con, args.symbol, inst.get("rollover_policy"))
        print(f"    trading_days: {_fmt(n_days)}")
        print(f"    rollovers   : {_fmt(n_roll)}")

        print("  escrevendo espelho Parquet...")
        out = db.export_parquet(con, args.symbol)
        print(f"    {out}")


def cmd_derive(args) -> None:
    with db.connect() as con:
        inst = db.load_instrument_yaml(args.symbol)
        n_days = cal.rebuild_trading_days(con, args.symbol)
        n_roll = roll.rebuild_rollovers(con, args.symbol, inst.get("rollover_policy"))
        db.export_parquet(con, args.symbol)
    print(f"trading_days: {_fmt(n_days)}   rollovers: {_fmt(n_roll)}")


def cmd_status(args) -> None:
    sym = args.symbol
    with db.connect(read_only=True) as con:
        bars, t0, t1 = con.execute(
            "SELECT count(*), min(ts), max(ts) FROM bars_m1 WHERE symbol = ?", [sym]
        ).fetchone()
        if not bars:
            sys.exit(f"nenhuma barra para {sym}. Rode 'ingest' primeiro.")

        days, partial = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE is_partial) "
            "FROM trading_days WHERE symbol = ?",
            [sym],
        ).fetchone()

        print(f"=== {sym} ===")
        print(f"barras M1     : {_fmt(bars)}")
        print(f"periodo       : {t0}  ->  {t1}")
        print(f"pregoes       : {_fmt(days)}  ({partial} parciais)")
        print(f"fecha mais cedo em: {cal.earliest_close(con, sym)}")

        print("\n--- formatos de sessao (top 6) ---")
        for abertura, fechamento, n in cal.session_shape(con, sym)[:6]:
            print(f"  {abertura} -> {fechamento}   {_fmt(n)} pregoes")

        print("\n--- rolagens de contrato ---")
        rows = con.execute(
            "SELECT date, prev_close, next_open, gap_points, detected_by "
            "FROM rollovers WHERE symbol = ? ORDER BY date DESC LIMIT 8",
            [sym],
        ).fetchall()
        for d, pc, no, gap, how in rows:
            print(f"  {d}  {pc} -> {no}   gap {gap:+6d}   [{how}]")
        total, confirmed = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE detected_by = 'calendar+gap') "
            "FROM rollovers WHERE symbol = ?",
            [sym],
        ).fetchone()
        print(f"  ({total} no total, {confirmed} confirmadas por gap)")

        print("\n--- exportacoes importadas ---")
        for r in con.execute(
            "SELECT ingest_id, source_file, source_min_ts, source_max_ts, "
            "rows_in_file, rows_inserted, rows_updated, rows_identical "
            "FROM ingest_log WHERE symbol = ? ORDER BY ingest_id",
            [sym],
        ).fetchall():
            print(
                f"  #{r[0]} {Path(r[1]).name}\n"
                f"      {r[2]} -> {r[3]}\n"
                f"      arquivo {_fmt(r[4])} | novas {_fmt(r[5])} | "
                f"atualizadas {_fmt(r[6])} | identicas {_fmt(r[7])}"
            )


def cmd_verify(args) -> None:
    """Prova que o .duckdb e descartavel: reconstroi do Parquet e compara."""
    sym = args.symbol
    with db.connect() as con:
        antes = con.execute(
            "SELECT count(*), sum(open), sum(high), sum(low), sum(close) "
            "FROM bars_m1 WHERE symbol = ?",
            [sym],
        ).fetchone()
        db.rebuild_from_parquet(con, sym)
        depois = con.execute(
            "SELECT count(*), sum(open), sum(high), sum(low), sum(close) "
            "FROM bars_m1 WHERE symbol = ?",
            [sym],
        ).fetchone()

    print(f"antes  : {antes}")
    print(f"depois : {depois}")
    if antes == depois:
        print("OK - reconstrucao a partir do Parquet e identica.")
    else:
        sys.exit("FALHA - o espelho Parquet divergiu da base.")


def cmd_minas(args) -> None:
    """Lista as minerações salvas e, com --limpar, apaga as que sobraram de
    antes de salvar virar decisão sua."""
    with db.connect_write() as con:
        db.init_schema(con)
        linhas = con.execute(
            "SELECT r.run_id, r.created_at, r.nome, r.strategy, r.n_combinacoes, "
            "r.status, count(t.trial_id) "
            "FROM mining_runs r LEFT JOIN mining_trials t USING (run_id) "
            "GROUP BY 1,2,3,4,5,6 ORDER BY r.run_id"
        ).fetchall()

        if not linhas:
            print("nenhuma mineração no banco.")
            return

        print(f"{'run':>5}  {'quando':<16} {'combinações':>12}  {'status':<13} nome")
        for run_id, quando, nome, _est, n, status, guardadas in linhas:
            print(f"{run_id:>5}  {quando:%d/%m/%Y %H:%M}  {guardadas:>12,}  "
                  f"{status:<13} {nome or ''}".replace(",", "."))

        if not args.limpar:
            print("\nuse --limpar para apagar as abandonadas e interrompidas")
            return

        alvos = [r[0] for r in linhas if r[5] in ("abandonada", "interrompida")]
        if not alvos:
            print("\nnada a limpar.")
            return
        marcas = ", ".join("?" * len(alvos))
        con.execute(f"DELETE FROM mining_trials WHERE run_id IN ({marcas})", alvos)
        con.execute(f"DELETE FROM mining_runs   WHERE run_id IN ({marcas})", alvos)
        print(f"\n{len(alvos)} minerações apagadas.")
        print("o arquivo .duckdb não encolhe sozinho; para compactar, apague-o e "
              "rode 'cli.py verify' — mas isso também apaga as minerações salvas.")


def main() -> None:
    p = argparse.ArgumentParser(prog="cli.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    pi = sub.add_parser("ingest")
    pi.add_argument("csv")
    pi.add_argument("--symbol", default=DEFAULT_SYMBOL)
    pi.add_argument("--no-copy-raw", dest="copy_raw", action="store_false")
    pi.set_defaults(func=cmd_ingest, copy_raw=True)

    pm = sub.add_parser("minas", help="lista/limpa minerações salvas")
    pm.add_argument("--limpar", action="store_true")
    pm.set_defaults(func=cmd_minas)

    for name, fn in (("derive", cmd_derive), ("status", cmd_status), ("verify", cmd_verify)):
        sp = sub.add_parser(name)
        sp.add_argument("--symbol", default=DEFAULT_SYMBOL)
        sp.set_defaults(func=fn)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
