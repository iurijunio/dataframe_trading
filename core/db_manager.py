"""Conexao com o DuckDB, criacao do schema e espelho Parquet.

Regra de ouro deste modulo: o .duckdb e um CACHE. A verdade sao os CSVs em
data/raw/ e o espelho Parquet em data/parquet/. Apagar o banco e reconstruir
tem que dar exatamente a mesma coisa - e existe teste que cobra isso.
"""

from __future__ import annotations

import contextlib

import json
from datetime import datetime
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "database.duckdb"
PARQUET_DIR = DATA / "parquet"
RAW_DIR = DATA / "raw"
SCHEMA_SQL = Path(__file__).with_name("schema.sql")
INSTRUMENTS_DIR = ROOT / "configs" / "instruments"


def _ocupado(erro: Exception) -> bool:
    """O banco estava em uso por outra conexão — vale esperar e tentar de
    novo. Qualquer outro erro (SQL, arquivo corrompido) sobe na hora, em vez
    de aparecer só depois de dez segundos de espera inútil."""
    return isinstance(erro, (duckdb.IOException, duckdb.ConnectionException))


def connect(db_path: Path | str | None = None, read_only: bool = False,
            tentativas: int = 60, espera: float = 0.25):
    """Abre o banco. Lembre que o DuckDB aceita UM escritor por vez -
    o pool de mineracao le em read_only e escreve por fila.

    A LEITURA também espera a vez. No mesmo processo o DuckDB recusa abrir
    uma conexão só-leitura enquanto há um escritor aberto ("different
    configuration") — e a tela lê o banco enquanto uma mineração grava.
    Sem a espera, a lista de minerações e o walk-forward quebravam durante
    a gravação inteira.
    """
    import time as _t

    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ultimo = None
    for _ in range(tentativas if read_only else 1):
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except Exception as erro:
            if not _ocupado(erro):
                raise
            ultimo = erro
            _t.sleep(espera)
    raise RuntimeError(f"banco ocupado para leitura: {ultimo}")


@contextlib.contextmanager
def transacao(con):
    """Tudo ou nada. Se o processo morrer no meio, o DuckDB descarta a
    transação aberta: não sobra mineração pela metade marcada como
    'concluida', nem walk-forward sem os trades."""
    con.execute("BEGIN TRANSACTION")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def connect_write(tentativas: int = 40, espera: float = 0.25):
    """Conexão de escrita com paciência.

    Um leitor de vida curta (a interface desenhando um gráfico) pode estar
    com o arquivo aberto no exato momento da gravação. Em vez de derrubar a
    mineração inteira, espera a vez.
    """
    import time as _t

    ultimo = None
    for _ in range(tentativas):
        try:
            return connect()
        except Exception as erro:
            if not _ocupado(erro):
                raise
            ultimo = erro
            _t.sleep(espera)
    raise RuntimeError(
        f"banco ocupado após {tentativas * espera:.0f}s de espera: {ultimo}"
    )


# Tabelas que sao artefato derivado: podem ser recriadas sem perda. As de
# historico (bars_m1, ingest_log) NUNCA entram aqui - elas guardam o que o
# MT5 nao devolve mais.
DESCARTAVEIS = ("mining_trials", "mining_runs")


def init_schema(con) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    con.execute(sql)

    # `CREATE TABLE IF NOT EXISTS` nao altera tabela existente: se o schema
    # mudou, a tabela velha fica e a insercao quebra por contagem de coluna.
    #
    # Recriar so e seguro em tabela VAZIA. Minerar deixou de ser automatico -
    # o que esta gravado foi voce que mandou salvar, e apagar isso para
    # "consertar" o schema seria destruir trabalho sem avisar. Com dado
    # dentro, isto levanta erro e pede migracao explicita.
    for tabela in DESCARTAVEIS:
        esperado = _colunas_declaradas(sql, tabela)
        atual = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [tabela]).fetchall()]
        # sem ordem: uma coluna que mudou de posição no CREATE não é uma
        # coluna diferente, e não pode derrubar o app na subida
        if not atual or set(atual) == set(esperado):
            continue
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        if n:
            faltando = [c for c in esperado if c not in atual]
            raise RuntimeError(
                f"{tabela} tem {n} linhas e um schema diferente do declarado "
                f"(faltam {faltando or 'nenhuma'}; sobram "
                f"{[c for c in atual if c not in esperado] or 'nenhuma'}). "
                "Adicione um ALTER TABLE em schema.sql em vez de recriar, ou "
                "apague as minerações com 'cli.py minas --limpar'."
            )
        con.execute(f"DROP TABLE {tabela}")
        # o arquivo INTEIRO de uma vez, como na abertura: cortar por ";"
        # quebrava num ponto e vírgula dentro de comentário — a tabela já
        # tinha sido derrubada, e o app só voltava na segunda subida
        con.execute(sql)


def _colunas_declaradas(sql: str, tabela: str) -> list[str]:
    import re

    m = re.search(rf"CREATE TABLE IF NOT EXISTS {tabela} \((.*?)\n\);", sql, re.S)
    if not m:
        return []
    cols = []
    for linha in m.group(1).splitlines():
        linha = linha.split("--")[0].strip()
        if not linha or linha.upper().startswith("PRIMARY KEY"):
            continue
        cols.append(linha.split()[0].strip(","))

    # Coluna acrescentada por ALTER conta como declarada. Sem isto o reparo
    # via divergencia onde nao havia: foi assim que `wf_config`, presente so
    # no ALTER, fez a tabela de mineracoes ser derrubada a cada gravacao.
    padrao = rf"ALTER TABLE\s+{tabela}\s+ADD COLUMN(?:\s+IF NOT EXISTS)?\s+(\w+)"
    for nome in re.findall(padrao, sql, re.I):
        if nome not in cols:
            cols.append(nome)
    return cols


def safe_symbol(symbol: str) -> str:
    """WIN$N nao vira nome de diretorio. WIN_N vira."""
    return "".join(c if c.isalnum() else "_" for c in symbol)


# --------------------------------------------------------------- instrumentos
def load_instrument_yaml(symbol: str) -> dict:
    for path in sorted(INSTRUMENTS_DIR.glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        if cfg.get("symbol") == symbol:
            return cfg
    raise FileNotFoundError(
        f"Nenhum YAML em {INSTRUMENTS_DIR} declara symbol: {symbol!r}"
    )


def upsert_instrument(con, cfg: dict) -> None:
    cols = (
        "symbol", "description", "exchange", "currency", "timezone",
        "price_decimals", "tick_size", "point_value", "tick_value",
        "allows_overnight", "rollover_policy",
    )
    con.execute("DELETE FROM instruments WHERE symbol = ?", [cfg["symbol"]])
    con.execute(
        f"INSERT INTO instruments ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [cfg.get(c) for c in cols],
    )


def sync_instruments(con) -> list[str]:
    """Le todos os YAML de configs/instruments e grava no banco."""
    symbols = []
    for path in sorted(INSTRUMENTS_DIR.glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        upsert_instrument(con, cfg)
        symbols.append(cfg["symbol"])
    return symbols


# ------------------------------------------------------------------- perfis
DEFAULT_PROFILE = {
    "janela": {"inicio": "09:00", "fim": "17:30", "dias_semana": [1, 2, 3, 4, 5]},
    "limites": {
        "direcao": "ambas",
        "max_trades_dia": None,
        "stop_diario": None,
        "meta_diaria": None,
    },
    "custos": {
        "corretagem_por_contrato": 0.0,
        "emolumentos_por_contrato": 0.0,
        "slippage_ticks": 1,
    },
    "posicao": {
        "modo": "contratos_fixos",
        "contratos": 1,
        "risco_por_trade": None,
        "capital_inicial": 10000.0,
    },
}


def ensure_default_profile(con, name: str = "WIN day trade padrao") -> int:
    row = con.execute(
        "SELECT profile_id FROM execution_profiles WHERE name = ?", [name]
    ).fetchone()
    if row:
        return row[0]
    now = datetime.now()
    profile_id = con.execute("SELECT nextval('seq_profile_id')").fetchone()[0]
    con.execute(
        "INSERT INTO execution_profiles VALUES (?, ?, ?, ?, ?)",
        [profile_id, name, json.dumps(DEFAULT_PROFILE, ensure_ascii=False), now, now],
    )
    return profile_id


# ------------------------------------------------------------------ parquet
def _sql_str(value) -> str:
    """Literal SQL. Necessario porque COPY ... TO e read_parquet() exigem
    caminho literal - passar o destino como parametro ligado faz o COPY
    nao gravar nada, sem levantar erro."""
    return "'" + str(value).replace("'", "''") + "'"


def export_parquet(con, symbol: str) -> Path:
    """Reescreve o espelho Parquet do simbolo, particionado por ano."""
    out = PARQUET_DIR / safe_symbol(symbol)
    out.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT *, year(ts) AS year
            FROM bars_m1
            WHERE symbol = ?
            ORDER BY ts
        ) TO {_sql_str(out)}
          (FORMAT PARQUET, PARTITION_BY (year),
           OVERWRITE_OR_IGNORE 1, COMPRESSION zstd)
        """,
        [symbol],
    )
    written = list(out.rglob("*.parquet"))
    if not written:
        raise RuntimeError(f"COPY nao gravou nenhum arquivo em {out}")
    return out


def read_bars_parquet(symbol: str, start=None, end=None):
    """Le as barras do espelho Parquet, SEM abrir o database.duckdb.

    Existe por causa de uma trava real: o DuckDB aceita ou vários leitores ou
    um escritor, nunca os dois. Se os workers da mineração abrissem o banco
    para ler, o processo que grava os resultados ficaria de fora. Lendo do
    Parquet o problema simplesmente não existe - e é mais um motivo para o
    espelho ganhar o seu lugar.
    """
    src = PARQUET_DIR / safe_symbol(symbol)
    if not src.exists() or not list(src.rglob("*.parquet")):
        raise FileNotFoundError(
            f"Espelho Parquet ausente para {symbol}: {src}. "
            "Rode 'cli.py derive' para recriá-lo."
        )
    where = ["symbol = ?"]
    args: list = [symbol]
    if start:
        where.append("ts >= ?")
        args.append(start)
    if end:
        where.append("ts <= ?")
        args.append(end)

    con = duckdb.connect()  # em memoria: nao encosta no arquivo do banco
    try:
        return con.execute(
            f"SELECT ts, open, high, low, close, tick_volume, volume "
            f"FROM read_parquet({_sql_str(src.as_posix() + '/**/*.parquet')}) "
            f"WHERE {' AND '.join(where)} ORDER BY ts",
            args,
        ).fetchnumpy()
    finally:
        con.close()


def rebuild_from_parquet(con, symbol: str) -> int:
    """Reconstroi bars_m1 a partir do espelho. Prova que o banco e descartavel."""
    src = PARQUET_DIR / safe_symbol(symbol)
    if not src.exists() or not list(src.rglob("*.parquet")):
        raise FileNotFoundError(f"Espelho Parquet vazio ou inexistente: {src}")
    # DuckDB faz glob com barra normal, inclusive no Windows.
    pattern = src.as_posix() + "/**/*.parquet"
    con.execute("DELETE FROM bars_m1 WHERE symbol = ?", [symbol])
    con.execute(
        f"""
        INSERT INTO bars_m1
        SELECT symbol, ts, open, high, low, close,
               tick_volume, volume, spread, src_ingest_id
        FROM read_parquet({_sql_str(pattern)})
        WHERE symbol = ?
        """,
        [symbol],
    )
    return con.execute(
        "SELECT count(*) FROM bars_m1 WHERE symbol = ?", [symbol]
    ).fetchone()[0]
