"""Foto dos resultados do WIN, para provar que nada mudou.

    python scripts/foto_win.py gravar <nome>     (não sobrescreve; congela o banco
                                                  em data/foto_win/<nome>.duckdb)
    python scripts/foto_win.py conferir <nome>   (exit 1 se houver diferença)

A foto tem cinco partes, tudo no WIN$N: trades de cada plano (via
`_trades_do_plano`), de cada estratégia com os parâmetros padrão (numa cópia
do banco aberta só para leitura), uma mineração pequena, um walk-forward
curto e um teste aleatório da Candidata (estes três leem o Parquet). Fica em `data/foto_win/<nome>.pkl` (fora do git).
"""
from __future__ import annotations

import pickle
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

PASTA_FOTOS = RAIZ / "data" / "foto_win"


def comparar(antes, depois, caminho: str = "") -> list[str]:
    """Diferenças exatas (sem tolerância); lista vazia = idêntico."""
    if isinstance(antes, dict) and isinstance(depois, dict):
        difs = []
        for k in sorted(set(antes) | set(depois), key=str):
            sub = f"{caminho}/{k}" if caminho else str(k)
            if k not in antes:
                difs.append(f"{sub}: ausente != presente")
            elif k not in depois:
                difs.append(f"{sub}: presente != ausente")
            else:
                difs += comparar(antes[k], depois[k], sub)
        return difs
    if isinstance(antes, np.ndarray) or isinstance(depois, np.ndarray):
        a, d = np.asarray(antes), np.asarray(depois)
        try:
            igual = np.array_equal(a, d, equal_nan=True)
        except TypeError:  # dtype sem NaN (texto, datas)
            igual = np.array_equal(a, d)
        return [] if igual else [f"{caminho}: {a.tolist()[:5]}... != {d.tolist()[:5]}..."]
    return [] if antes == depois else [f"{caminho}: {antes} != {depois}"]


SIMBOLO = "WIN$N"
PERIODO = ("2024-01-01", "2025-06-30")  # mineração e walk-forward
# Alvo de trades por janela do sorteio. O sorteio satura em ~120 trades por
# mês (os reais do cruzamento passam de 300), então o alvo real nunca
# calibraria e as 20 repetições nem rodariam; 100 calibra e exercita tudo.
ALVOS_ALEATORIO = [100, 100]
GRADE = {"media_rapida": [5, 9, 13, 17], "media_lenta": [21, 34, 55, 89, 144]}


@contextmanager
def _banco(origem: Path | None = None):
    """Cópia do banco (`origem`, por padrão o real) aberta só para leitura."""
    import duckdb

    from core import db_manager as db
    from scripts.reassinar_codigo import copiar_banco

    with tempfile.TemporaryDirectory(prefix="foto-win-") as tmp:
        copia = str(copiar_banco(Path(origem or db.DB_PATH), Path(tmp) / "copia.duckdb"))
        con = duckdb.connect(copia, read_only=True)
        try:
            yield con, copia, Path(tmp)
        finally:
            con.close()


def _planos(banco: Path | None = None) -> dict:
    with _banco(banco) as (con, copia, tmp):
        ids = [int(r[0]) for r in con.execute(
            "SELECT plano_id FROM planos_operacao ORDER BY plano_id").fetchall()]
        saida = tmp / "planos.pkl"
        from core import db_manager as db
        from scripts import _trades_do_plano
        real = db.DB_PATH  # o worker troca db.DB_PATH pela cópia; devolvo
        try:
            _trades_do_plano.main(str(RAIZ), copia, ",".join(map(str, ids)), str(saida))
        finally:
            db.DB_PATH = real
        with open(saida, "rb") as f:
            return pickle.load(f)


def _estrategias(banco: Path | None = None) -> dict:
    from core import db_manager as db
    from core.engine.execution import ExecutionProfile, prepare_bars, run_strategy
    from strategies import registry
    from strategies.base import defaults

    estrategias = {}
    with _banco(banco) as (con, _copia, _tmp):
        barras = prepare_bars(con, SIMBOLO)
        inst = db.load_instrument_yaml(SIMBOLO)
        for e in registry.descobrir():
            mod = registry.carregar(e["modulo"])
            res = run_strategy(barras, mod, defaults(mod.params_schema),
                               ExecutionProfile(), inst)
            estrategias[e["modulo"]] = {
                "n_trades": int(res.n_trades),
                "trades": {k: np.asarray(v) for k, v in res.trades.items()},
                "sl_at_entry": np.asarray(res.sl_at_entry),
                "tp_at_entry": np.asarray(res.tp_at_entry),
                "ambiguous_bars": int(res.ambiguous_bars),
                "bloqueios": int(res.bloqueios),
            }
    return estrategias


def _combinacoes() -> list[dict]:
    from core import optimizer

    espaco = {k: list(v) for k, v in GRADE.items()}
    return optimizer.combinacoes_uteis(optimizer.espaco_util(espaco, {}))


def _mineracao() -> dict:
    """Mineração pequena: 20 combinações do setup_cruzamento, em processo."""
    from core import optimizer, walkforward
    from core.engine.execution import ExecutionProfile

    de, ate = PERIODO
    optimizer._init(SIMBOLO, de, ate, "setup_cruzamento")
    janelas = walkforward.montar_janelas(de, ate, 12, 3, 3, 0)
    perfil_base = ExecutionProfile().to_config()
    return {i: optimizer._uma((i, params, {}, perfil_base, janelas))
            for i, params in enumerate(_combinacoes())}


def _walkforward() -> dict:
    """As 4 primeiras combinações pelo executor do walk-forward."""
    from core import wfa_runner
    from core.engine.execution import ExecutionProfile

    de, ate = PERIODO
    wfa_runner._init(SIMBOLO, de, ate, "setup_cruzamento")
    perfil_base = ExecutionProfile().to_config()
    return {i: wfa_runner._uma((i, params, {}, perfil_base))
            for i, params in enumerate(_combinacoes()[:4])}


def _candidata() -> dict:
    """Teste aleatório (portão 3) sobre 2 janelas mensais, n=20, semente 7."""
    from core import aleatorio, db_manager as db, metrics
    from core.engine.execution import ExecutionProfile, run_strategy
    from core.wfa import Janela
    from strategies import registry
    from strategies.base import defaults

    d = db.read_bars_parquet(SIMBOLO, "2025-01-01", "2025-06-30")
    bars = {
        "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
        **{c: np.ascontiguousarray(d[c], dtype=np.int64)
           for c in ("open", "high", "low", "close", "tick_volume", "volume")},
    }
    inst = db.load_instrument_yaml(SIMBOLO)
    mod = registry.carregar("setup_cruzamento")
    perfil = ExecutionProfile()
    res = run_strategy(bars, mod, defaults(mod.params_schema), perfil, inst)
    liquido = metrics.monetize(res)["liquido"]
    entradas = res.trades["entry_ts"]

    cortes = [np.datetime64(x, "s") for x in
              ("2025-01-01", "2025-02-01", "2025-03-01")]
    janelas, trades_por_janela, lucros = [], [], []
    for step, (de_j, ate_j) in enumerate(zip(cortes[:-1], cortes[1:]), start=1):
        janelas.append(Janela(step, de_j, de_j, de_j, ate_j))
        dentro = (entradas >= de_j) & (entradas < ate_j)
        trades_por_janela.append([
            {"step": step, "entry_ts": t, "side": int(s)}
            for t, s in zip(entradas[dentro], res.trades["side"][dentro])])
        lucros.append(float(liquido[dentro].sum()))

    rodadores = {j: aleatorio.rodador_do_motor(bars, mod, perfil, inst, tr)
                 for j, tr in zip(janelas, trades_por_janela)}
    return aleatorio.teste_janelas(
        lambda j, n_sinais, semente: rodadores[j](j, n_sinais, semente),
        janelas, ALVOS_ALEATORIO, sum(lucros),
        n=20, semente=7, lucros_reais=lucros)


def gerar(banco: Path | None = None) -> dict:
    """`banco`: arquivo do banco congelado na gravação (padrão: o real). Só
    planos e estratégias leem o banco; o resto lê o Parquet, cortado em 2025."""
    return {"planos": _planos(banco), "estrategias": _estrategias(banco),
            "mineracao": _mineracao(), "walkforward": _walkforward(),
            "candidata": _candidata()}


def _contagens(foto: dict) -> str:
    return ", ".join(f"{len(v)} {k}" for k, v in foto.items())


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("gravar", "conferir"):
        print(__doc__)
        return 2
    cmd, nome = argv
    arq = PASTA_FOTOS / f"{nome}.pkl"
    if cmd == "gravar":
        if arq.exists():
            print(f"{arq} já existe; não sobrescrevo (escolha outro nome).")
            return 1
        from core import db_manager as db
        from scripts.reassinar_codigo import copiar_banco
        arq.parent.mkdir(parents=True, exist_ok=True)
        congelado = copiar_banco(Path(db.DB_PATH), arq.with_suffix(".duckdb"))
        foto = gerar(congelado)
        with open(arq, "wb") as f:
            pickle.dump(foto, f)
        print(f"foto {nome} gravada ({_contagens(foto)})")
        return 0
    with open(arq, "rb") as f:
        salva = pickle.load(f)
    congelado = arq.with_suffix(".duckdb")
    if congelado.exists():
        nova = gerar(congelado)
    else:
        print(f"AVISO: {congelado.name} não existe; confiro contra o banco "
              "real, que ganha barras todo dia.")
        nova = gerar()
    difs = comparar(salva, nova)
    if not difs:
        print(f"foto {nome}: idêntica ({_contagens(nova)})")
        return 0
    print(f"foto {nome}: {len(difs)} diferença(s)")
    for d in difs[:30]:
        print("  " + d)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
