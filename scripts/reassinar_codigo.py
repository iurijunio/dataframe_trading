"""Reassinar planos quando o código da estratégia muda sem mudar os trades.

Uso (na raiz do projeto, com a captura podendo estar aberta):

    .venv\\Scripts\\python.exe scripts\\reassinar_codigo.py --de <commit>
    .venv\\Scripts\\python.exe scripts\\reassinar_codigo.py --de <commit> --aplicar

`--de` é o commit do código com que os planos foram gravados (o de ANTES da
mudança; ex.: `f96be02~1`). Sem `--aplicar` só compara e mostra.

O que faz, em ordem:
1. tira uma cópia do banco e roda tudo nela (o backtest do histórico
   inteiro leva segundos e não pode prender o banco da captura);
2. extrai o código antigo (`git archive`) numa pasta temporária;
3. pega os planos cujo hash gravado é o do código antigo e não é o do
   disco, e roda o backtest de cada um com o código antigo e com o novo,
   cada um no seu processo (`_trades_do_plano.py`);
4. com `--aplicar`: backup do banco, e `codigo.reassinar` SÓ dos planos com
   trades idênticos campo a campo, numa transação; o resto fica como está
   e aparece no relatório. Um log vai para a pasta do backup.
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

TRABALHADOR = Path(__file__).with_name("_trades_do_plano.py")
BACKUPS = RAIZ.parent / "backups"


def _sha(arquivo: Path) -> str:
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def copiar_banco(origem: Path, destino: Path, tentativas: int = 40,
                 espera: float = 0.5) -> Path:
    """Copia o arquivo do banco, esperando a vez se a captura estiver
    gravando (mesma paciência do `db.connect_write`). Confere a cópia pelo
    sha256: copiar no meio de uma gravação daria um arquivo diferente."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    ultimo = None
    for _ in range(tentativas):
        try:
            shutil.copy2(origem, destino)
            if _sha(origem) == _sha(destino):
                return destino
            ultimo = "o banco mudou durante a cópia"
        except OSError as erro:
            ultimo = erro
        time.sleep(espera)
    raise RuntimeError(f"não consegui copiar o banco: {ultimo}")


def extrair_commit(ref: str, destino: Path) -> Path:
    """O código do commit `ref`, sem mexer no checkout nem nos worktrees."""
    tar = subprocess.run(["git", "-C", str(RAIZ), "archive", "--format=tar",
                          ref, "core", "strategies", "configs"],
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(destino, filter="data")
    return destino


def planos_afetados(banco: Path, pasta_antiga: Path,
                    pasta_nova: Path) -> list[dict]:
    """Planos com hash cujo código no disco mudou. `situacao`: "comparar"
    (o hash gravado é o do código antigo) ou por que não dá."""
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
    out = []
    for pid, estrategia, gravado in linhas:
        antigo = codigo.hash_estrategia(estrategia, pasta_antiga / "strategies")
        novo = codigo.hash_estrategia(estrategia, pasta_nova / "strategies")
        if gravado == novo:
            continue
        situacao = ("comparar" if gravado == antigo and novo
                    else "o hash gravado não é o do código --de")
        out.append({"plano_id": int(pid), "estrategia": estrategia,
                    "hash_gravado": gravado, "hash_antigo": antigo,
                    "hash_novo": novo, "situacao": situacao})
    return out


def rodar(raiz: Path, banco: Path, ids: list[int], saida: Path) -> dict:
    # -I: nem a pasta do script nem o diretório atual entram no sys.path —
    # o único `core` visível é o de `raiz`
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
                        "diferenca": "plano não rodou"}
            continue
        diferenca = None
        for vela in (False, True):
            diferenca = codigo.trades_iguais(a[vela], d[vela])
            if diferenca:
                diferenca = (("vela aberta: " if vela else "") + diferenca)
                break
        if diferenca is None and not a[False]["n_trades"]:
            # zero trades dos dois lados é igual, mas não prova nada
            diferenca = "nenhum trade para comparar"
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
    """Tudo o que o comando faz; devolve o relatório. `pasta_antiga` no
    lugar de `de` (os testes montam o código antigo à mão)."""
    banco = Path(banco or db.DB_PATH)
    if trabalho is None:
        # a cópia do banco tem ~100 MB: não deixar uma por rodada no TEMP
        with tempfile.TemporaryDirectory(prefix="reassinar-") as tmp:
            return executar(de=de, pasta_antiga=pasta_antiga,
                            aplicar=aplicar, banco=banco, backup=backup,
                            raiz_nova=raiz_nova, trabalho=Path(tmp))
    tmp = Path(trabalho)
    tmp.mkdir(parents=True, exist_ok=True)
    if pasta_antiga is None:
        if not de:
            raise ValueError("diga o commit do código antigo (--de)")
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
                # backup já tirado (rodada anterior): só vale se for deste
                # mesmo banco, intacto — nunca sobrescrever um backup
                if _sha(destino) != _sha(banco):
                    raise RuntimeError(f"{destino} já existe e não é este "
                                       "banco; escolha outra --backup")
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
        print(f"plano #{p['plano_id']} ({p['estrategia']}): "
              f"{(p['hash_gravado'] or '')[:12]} -> {(p['hash_novo'] or '')[:12]}  "
              + (f"IDÊNTICO, {p['n_trades']} trades comparados"
                 if p["identicos"] else
                 f"NÃO reassinado: {p.get('diferenca') or p['situacao']}"))
    if not rel["planos"]:
        print("nenhum plano com o código mudado")
    for a in rel["alterado"]:
        print(f"  reassinado #{a['plano_id']}: {a['planos']} plano, "
              f"{a['pregoes']} pregões de papel")
    if rel.get("log"):
        print(f"backup: {rel['backup']}\nlog: {rel['log']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--de", required=True,
                    help="commit do código com que os planos foram gravados")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava (sem isto, só compara)")
    ap.add_argument("--backup", type=Path, help="pasta do backup e do log")
    a = ap.parse_args()
    _mostrar(executar(de=a.de, aplicar=a.aplicar, backup=a.backup))
