"""Re-sign plans when the strategy code changes without changing the trades.

Usage (from the project root, the capture may be open):

    .venv\\Scripts\\python.exe scripts\\resign_code_hash.py --since <commit>
    .venv\\Scripts\\python.exe scripts\\resign_code_hash.py --since <commit> --apply

`--since` is the commit of the code the plans were recorded with (the one from
BEFORE the change; e.g. `f96be02~1`). Without `--apply` it only compares and shows.

What it does, in order:
1. copies the database and runs everything on the copy (the backtest of the
   whole history takes seconds and must not lock the capture's database);
2. extracts the old code (`git archive`) into a temporary folder;
3. takes the plans whose recorded hash is the old code's and not the one on
   disk, and runs each one's backtest with the old and the new code, each in
   its own process (`plan_trades_worker.py`);
4. with `--apply`: database backup, and `codigo.reassinar` ONLY for the plans
   with trades identical field by field, in one transaction; the rest stays
   as is and shows up in the report. A log goes to the backup folder.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import codigo  # noqa: E402
from core import db_manager as db  # noqa: E402

TRABALHADOR = Path(__file__).with_name("plan_trades_worker.py")
BACKUPS = RAIZ.parent / "backups"


def _sha(arquivo: Path) -> str:
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def copiar_banco(origem: Path, destino: Path, tentativas: int = 40,
                 espera: float = 0.5) -> Path:
    """Copies the database file, waiting its turn if the capture is writing
    (same patience as `db.connect_write`). Verifies the copy by sha256:
    copying in the middle of a write would give a different file."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    ultimo = None
    for _ in range(tentativas):
        try:
            shutil.copy2(origem, destino)
            if _sha(origem) == _sha(destino):
                return destino
            ultimo = "the database changed during the copy"
        except OSError as erro:
            ultimo = erro
        time.sleep(espera)
    raise RuntimeError(f"could not copy the database: {ultimo}")


def extrair_commit(ref: str, destino: Path) -> Path:
    """The code of commit `ref`, without touching the checkout or the worktrees."""
    tar = subprocess.run(["git", "-C", str(RAIZ), "archive", "--format=tar",
                          ref, "core", "strategies", "configs"],
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(destino, filter="data")
    return destino


def planos_afetados(banco: Path, pasta_antiga: Path,
                    pasta_nova: Path) -> list[dict]:
    """Plans with a hash whose code on disk changed. `situacao`: "comparar"
    (the recorded hash is the old code's) or why it cannot be compared."""
    import duckdb
    con = duckdb.connect(str(banco), read_only=True)
    try:
        linhas = con.execute(
            "SELECT p.plano_id, coalesce(p.strategy, ev.estrategia), "
            "p.codigo_hash FROM planos_operacao p "
            "LEFT JOIN estrategia_variantes ev ON ev.variante_id = p.variante_id "
            "WHERE p.codigo_hash IS NOT NULL ORDER BY p.plano_id").fetchall()
    finally:
        con.close()
    proprios = hashes_do_codigo(pasta_antiga, sorted({e for _, e, _ in linhas}))
    out = []
    for pid, estrategia, gravado in linhas:
        # the old code by TODAY's function and by its own: the fingerprint
        # recipe also changes (e.g. helpers like saida.py started to count),
        # and the recorded one was computed by the commit's recipe
        antigos = {codigo.hash_estrategia(estrategia, pasta_antiga / "strategies"),
                   proprios.get(estrategia)} - {None}
        novo = codigo.hash_estrategia(estrategia, pasta_nova / "strategies")
        if gravado == novo:
            continue
        bate = gravado in antigos
        situacao = ("comparar" if bate and novo
                    else "the recorded hash is not the --since code's")
        out.append({"plano_id": int(pid), "estrategia": estrategia,
                    "hash_gravado": gravado,
                    "hash_antigo": gravado if bate else None,
                    "hash_novo": novo, "situacao": situacao})
    return out


_HASH_NO_CODIGO = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "raiz = Path(sys.argv[1]).resolve()\n"
    "sys.path.insert(0, str(raiz))\n"
    "from core import codigo\n"
    "print(json.dumps({e: codigo.hash_estrategia(e, raiz / 'strategies')\n"
    "                  for e in json.loads(sys.argv[2])}))\n")


def hashes_do_codigo(raiz: Path, estrategias: list[str]) -> dict:
    """The hash of each strategy computed by the `core/codigo.py` of `raiz`
    itself, in a separate process, for the same reason as the worker: two
    `core` packages cannot live in the same interpreter. Without
    `core/codigo.py` in the root (code from before the fingerprint), nothing."""
    if not estrategias or not (Path(raiz) / "core" / "codigo.py").exists():
        return {}
    r = subprocess.run([sys.executable, "-I", "-c", _HASH_NO_CODIGO,
                        str(raiz), json.dumps(estrategias)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def rodar(raiz: Path, banco: Path, ids: list[int], saida: Path) -> dict:
    # -I: neither the script folder nor the current directory enters sys.path,
    # so the only visible `core` is the one in `raiz`
    subprocess.run([sys.executable, "-I", str(TRABALHADOR), str(raiz),
                    str(banco), ",".join(map(str, ids)), str(saida)],
                   check=True)
    with open(saida, "rb") as f:
        return pickle.load(f)


def comparar(antes: dict, depois: dict, ids: list[int]) -> dict[int, dict]:
    out = {}
    for pid in ids:
        a, d = antes.get(pid), depois.get(pid)
        if a is None or d is None:
            out[pid] = {"identicos": False, "n_trades": 0,
                        "diferenca": "plan did not run"}
            continue
        diferenca = None
        for vela in (False, True):
            diferenca = codigo.trades_iguais(a[vela], d[vela])
            if diferenca:
                diferenca = (("open candle: " if vela else "") + diferenca)
                break
        if diferenca is None and not a[False]["n_trades"]:
            # zero trades on both sides is equal, but proves nothing
            diferenca = "no trades to compare"
        out[pid] = {"identicos": diferenca is None,
                    "n_trades": a[False]["n_trades"] + a[True]["n_trades"],
                    "n_trades_fechado": a[False]["n_trades"],
                    "n_trades_vela_aberta": a[True]["n_trades"],
                    "diferenca": diferenca,
                    "arquivo_antigo": a["arquivo"],
                    "arquivo_novo": d["arquivo"]}
    return out


def executar(*, de: str | None = None, pasta_antiga: Path | None = None,
             aplicar: bool = False, banco: Path | None = None,
             backup: Path | None = None, raiz_nova: Path = RAIZ,
             trabalho: Path | None = None) -> dict:
    """Everything the command does; returns the report. `pasta_antiga` in
    place of `de` (tests build the old code by hand)."""
    banco = Path(banco or db.DB_PATH)
    if trabalho is None:
        # the database copy is ~100 MB: do not leave one per run in TEMP
        with tempfile.TemporaryDirectory(prefix="resign-") as tmp:
            return executar(de=de, pasta_antiga=pasta_antiga,
                            aplicar=aplicar, banco=banco, backup=backup,
                            raiz_nova=raiz_nova, trabalho=Path(tmp))
    tmp = Path(trabalho)
    tmp.mkdir(parents=True, exist_ok=True)
    if pasta_antiga is None:
        if not de:
            raise ValueError("give the commit of the old code (--since)")
        pasta_antiga = extrair_commit(de, tmp / "antigo")
    copia = copiar_banco(banco, tmp / "copia.duckdb")

    afetados = planos_afetados(copia, Path(pasta_antiga), Path(raiz_nova))
    ids = [p["plano_id"] for p in afetados if p["situacao"] == "comparar"]
    resultado: dict[int, dict] = {}
    if ids:
        antes = rodar(Path(pasta_antiga), copia, ids, tmp / "antes.pkl")
        depois = rodar(Path(raiz_nova), copia, ids, tmp / "depois.pkl")
        resultado = comparar(antes, depois, ids)
    for p in afetados:
        p.update(resultado.get(p["plano_id"], {"identicos": False,
                                               "n_trades": 0}))
    relatorio = {"de": de, "pasta_antiga": str(pasta_antiga),
                 "banco": str(banco), "planos": afetados, "alterado": []}

    if aplicar:
        iguais = [p for p in afetados if p["identicos"]]
        if iguais:
            backup = Path(backup or BACKUPS / (
                f"{datetime.now():%Y-%m-%d}-antes-reassinar"))
            destino = backup / "database.duckdb"
            if destino.exists():
                # backup already taken (earlier run): only valid if it is of
                # this same database, intact; never overwrite a backup
                if _sha(destino) != _sha(banco):
                    raise RuntimeError(f"{destino} already exists and is not this "
                                       "database; choose another --backup")
            else:
                copiar_banco(banco, destino)
            with db.connect_write() as con:
                relatorio["alterado"] = codigo.reassinar(
                    con, iguais, pasta=Path(raiz_nova) / "strategies")
            relatorio["backup"] = str(destino)
            log = backup / f"reassinar-{datetime.now():%Y%m%d-%H%M%S}.json"
            log.write_text(json.dumps(relatorio, indent=2, default=str,
                                      ensure_ascii=False), encoding="utf-8")
            relatorio["log"] = str(log)
    return relatorio


def _mostrar(rel: dict) -> None:
    for p in rel["planos"]:
        print(f"plan #{p['plano_id']} ({p['estrategia']}): "
              f"{(p['hash_gravado'] or '')[:12]} -> {(p['hash_novo'] or '')[:12]}  "
              + (f"IDENTICAL, {p['n_trades']} trades compared"
                 if p["identicos"] else
                 f"NOT re-signed: {p.get('diferenca') or p['situacao']}"))
    if not rel["planos"]:
        print("no plan with changed code")
    for a in rel["alterado"]:
        print(f"  re-signed #{a['plano_id']}: {a['planos']} plan, "
              f"{a['pregoes']} paper sessions")
    if rel.get("log"):
        print(f"backup: {rel['backup']}\nlog: {rel['log']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", required=True, dest="since",
                    help="commit of the code the plans were recorded with")
    ap.add_argument("--apply", action="store_true",
                    help="writes (without this, only compares)")
    ap.add_argument("--backup", type=Path, help="backup and log folder")
    a = ap.parse_args()
    _mostrar(executar(de=a.since, aplicar=a.apply, backup=a.backup))
