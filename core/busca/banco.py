"""O banco da busca automática: `data/buscas.duckdb`, separado do principal.

Separado porque o DuckDB aceita um escritor por vez e o banco principal é
gravado pela captura o pregão inteiro: a busca roda à noite E no pregão, e
nunca pode disputar o arquivo com quem grava as ordens.

Aqui também há dois processos — a busca grava, o app lê —, então ninguém
segura o arquivo aberto: abre, faz, fecha. Quem encontra o arquivo ocupado
tenta de novo por alguns segundos e, esgotado, recebe `BancoOcupado`: o app
mostra a última leitura; o motor guarda o lote e grava junto com o próximo.

A combinação é guardada como JSON nome = valor, nunca uma coluna por
parâmetro: parâmetro novo não muda o banco e busca antiga continua abrindo.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import duckdb

from core import db_manager as db

CAMINHO: Path = db.DATA / "buscas.duckdb"
PASTA: Path = db.DATA / "buscas"


class BancoOcupado(RuntimeError):
    """O outro processo está com o arquivo; tente de novo depois."""


ESQUEMA = """
CREATE SEQUENCE IF NOT EXISTS seq_busca START 1;
CREATE TABLE IF NOT EXISTS buscas (
    busca_id INTEGER PRIMARY KEY, criada_em TIMESTAMP, simbolo VARCHAR,
    estrategia VARCHAR, config VARCHAR, status VARCHAR,
    testes INTEGER DEFAULT 0, distintos INTEGER DEFAULT 0,
    descartados INTEGER DEFAULT 0, lote_n INTEGER DEFAULT 0,
    inicio TIMESTAMP, fim TIMESTAMP, duracao_s DOUBLE DEFAULT 0,
    erro VARCHAR, historico VARCHAR, versao_grupos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS combos (
    busca_id INTEGER, lote_n INTEGER, teste_n INTEGER, casa VARCHAR,
    combo VARCHAR, trades INTEGER, lucro DOUBLE, pf DOUBLE, dd DOUBLE,
    fr DOUBLE, consistencia DOUBLE, mediana_fold DOUBLE, score DOUBLE,
    objetivo DOUBLE, valida BOOLEAN, trades_hash VARCHAR, descartada VARCHAR);
CREATE TABLE IF NOT EXISTS elites (
    busca_id INTEGER, casa VARCHAR, combo VARCHAR, objetivo DOUBLE,
    valida BOOLEAN, trades INTEGER, lucro DOUBLE, pf DOUBLE, dd DOUBLE,
    fr DOUBLE, achado_em INTEGER, PRIMARY KEY (busca_id, casa));
CREATE TABLE IF NOT EXISTS elites_hist (
    busca_id INTEGER, lote_n INTEGER, casa VARCHAR, teste_n INTEGER,
    objetivo DOUBLE);
CREATE TABLE IF NOT EXISTS grupos (
    busca_id INTEGER, grupo_id INTEGER, versao INTEGER, lider_casa VARCHAR,
    lider VARCHAR, membros VARCHAR, mediana_obj DOUBLE, n_membros INTEGER);
-- as casas finas de cada grupo (o mapa acha o grupo de uma casa por aqui)
ALTER TABLE grupos ADD COLUMN IF NOT EXISTS casas VARCHAR;
"""

COLS_COMBO = ("busca_id", "lote_n", "teste_n", "casa", "combo", "trades", "lucro",
              "pf", "dd", "fr", "consistencia", "mediana_fold", "score",
              "objetivo", "valida", "trades_hash", "descartada")
COLS_ELITE = ("busca_id", "casa", "combo", "objetivo", "valida", "trades", "lucro",
              "pf", "dd", "fr", "achado_em")
CAMPOS_STATUS = {"status", "testes", "distintos", "descartados", "inicio", "fim",
                 "duracao_s", "erro", "historico", "lote_n", "versao_grupos", "config"}


@contextlib.contextmanager
def conectar(escrita: bool, tentativas: int = 20, espera_s: float = 0.25):
    """Conexão de vida curta, com paciência (mesmo padrão de
    `db.connect_write`). Leitura com o arquivo ainda inexistente cria o
    esquema primeiro, para a tela nunca quebrar na primeira abertura."""
    if not escrita and not CAMINHO.exists():
        with conectar(True, tentativas, espera_s):
            pass
    ultimo = None
    for _ in range(max(1, tentativas)):
        try:
            CAMINHO.parent.mkdir(parents=True, exist_ok=True)
            con = duckdb.connect(str(CAMINHO), read_only=not escrita)
            break
        except Exception as erro:
            if not db._ocupado(erro):
                raise
            ultimo = erro
            time.sleep(espera_s)
    else:
        raise BancoOcupado(str(ultimo))
    try:
        if escrita:
            con.execute(ESQUEMA)
        yield con
    finally:
        con.close()


def _linhas(cur) -> list[dict]:
    nomes = [d[0] for d in cur.description]
    return [dict(zip(nomes, r)) for r in cur.fetchall()]


def _inserir(con, tabela: str, colunas: tuple, linhas: list[dict]):
    """Em lote, por uma tabela Arrow: executemany confirma linha a linha
    (ver `optimizer._inserir_trials`)."""
    import pyarrow as pa

    if not linhas:
        return
    t = pa.table({c: [l.get(c) for l in linhas] for c in colunas})
    con.register("_novas", t)
    try:
        cols = ", ".join(colunas)
        con.execute(f"INSERT INTO {tabela} ({cols}) SELECT {cols} FROM _novas")
    finally:
        con.unregister("_novas")


# ----------------------------------------------------------------- escrita
def criar(config: dict) -> int:
    with conectar(True) as con:
        bid = con.execute("SELECT nextval('seq_busca')").fetchone()[0]
        con.execute(
            "INSERT INTO buscas (busca_id, criada_em, simbolo, estrategia, config, "
            "status, historico) VALUES (?,?,?,?,?,?,?)",
            [bid, datetime.now(), config["simbolo"], config["estrategia"],
             json.dumps(config, default=str), "rodando", "[]"])
    return int(bid)


def gravar_lote(busca_id: int, lote_n: int, combos: list[dict], elites: list[dict],
                hist: list[dict], contagens: dict) -> None:
    """Um lote inteiro numa transação: combinações, elites que mudaram,
    histórico e os contadores — com o `lote_n`, que é o que a retomada
    compara com o arquivo da pyribs."""
    with conectar(True) as con, db.transacao(con):
        _inserir(con, "combos", COLS_COMBO,
                 [{**c, "busca_id": busca_id, "lote_n": lote_n} for c in combos])
        if elites:
            con.execute(
                f"DELETE FROM elites WHERE busca_id = ? AND casa IN "
                f"({','.join('?' * len(elites))})",
                [busca_id, *[e["casa"] for e in elites]])
            _inserir(con, "elites", COLS_ELITE,
                     [{**e, "busca_id": busca_id} for e in elites])
        _inserir(con, "elites_hist", ("busca_id", "lote_n", "casa", "teste_n", "objetivo"),
                 [{**h, "busca_id": busca_id, "lote_n": lote_n} for h in hist])
        _atualizar(con, busca_id, {**contagens, "lote_n": lote_n})


def substituir_elites(busca_id: int, elites: list[dict]) -> None:
    """Na retomada: as elites voltam a ser exatamente as do arquivo salvo."""
    with conectar(True) as con, db.transacao(con):
        con.execute("DELETE FROM elites WHERE busca_id = ?", [busca_id])
        _inserir(con, "elites", COLS_ELITE, [{**e, "busca_id": busca_id} for e in elites])


def descartar_apos(busca_id: int, lote_n: int) -> None:
    """Apaga o que veio de lotes depois de `lote_n`: o lote que chegou ao
    banco mas não ao arquivo da pyribs (o processo caiu entre os dois) roda
    de novo, e não pode ficar em dobro."""
    with conectar(True) as con, db.transacao(con):
        for t in ("combos", "elites_hist"):
            con.execute(f"DELETE FROM {t} WHERE busca_id = ? AND lote_n > ?",
                        [busca_id, lote_n])
        con.execute("UPDATE buscas SET lote_n = ? WHERE busca_id = ?", [lote_n, busca_id])


def _atualizar(con, busca_id: int, campos: dict):
    invalidos = set(campos) - CAMPOS_STATUS
    if invalidos:
        raise ValueError(f"campos desconhecidos: {sorted(invalidos)}")
    if not campos:
        return
    vals = [json.dumps(v) if k in ("historico", "config") and not isinstance(v, str)
            else v for k, v in campos.items()]
    sets = ", ".join(f"{k} = ?" for k in campos)
    con.execute(f"UPDATE buscas SET {sets} WHERE busca_id = ?", [*vals, busca_id])


def marcar_status(busca_id: int, status: str | None = None, **campos) -> None:
    if status is not None:
        campos["status"] = status
    with conectar(True) as con:
        _atualizar(con, busca_id, campos)


def gravar_grupos(busca_id: int, versao: int, grupos: list[dict]) -> None:
    with conectar(True) as con, db.transacao(con):
        con.execute("DELETE FROM grupos WHERE busca_id = ?", [busca_id])
        _inserir(con, "grupos", ("busca_id", "grupo_id", "versao", "lider_casa", "lider",
                                 "membros", "mediana_obj", "n_membros", "casas"),
                 [{"busca_id": busca_id, "versao": versao, "grupo_id": g["grupo_id"],
                   "lider_casa": g["lider_casa"], "lider": json.dumps(g["lider"]),
                   "membros": json.dumps(g["membros"]), "mediana_obj": g["mediana_obj"],
                   "n_membros": g["n_membros"],
                   "casas": json.dumps(g.get("casas") or [g["lider_casa"]])}
                  for g in grupos])
        _atualizar(con, busca_id, {"versao_grupos": versao})


def pasta_da(busca_id: int) -> Path:
    return PASTA / str(int(busca_id))


def excluir(busca_id: int) -> None:
    """Apaga a busca do banco e a pasta dela (estado, controle, arquivo da
    pyribs, detalhes). Só a pasta da própria busca, dentro de `PASTA`."""
    with conectar(True) as con, db.transacao(con):
        for t in ("combos", "elites", "elites_hist", "grupos", "buscas"):
            con.execute(f"DELETE FROM {t} WHERE busca_id = ?", [busca_id])
    alvo = pasta_da(busca_id).resolve()
    if alvo.parent != PASTA.resolve():
        raise ValueError(f"pasta fora de {PASTA}: {alvo}")
    if alvo.exists():
        shutil.rmtree(alvo)


# ----------------------------------------------------------------- leitura
def _decodificar_busca(b: dict) -> dict:
    b["config"] = json.loads(b["config"]) if b.get("config") else {}
    b["historico"] = json.loads(b["historico"]) if b.get("historico") else []
    return b


def ler_busca(busca_id: int) -> dict | None:
    with conectar(False) as con:
        r = _linhas(con.execute("SELECT * FROM buscas WHERE busca_id = ?", [busca_id]))
    return _decodificar_busca(r[0]) if r else None


def listar(estrategia: str | None = None, simbolo: str | None = None) -> list[dict]:
    where, args = [], []
    if estrategia:
        where.append("estrategia = ?")
        args.append(estrategia)
    if simbolo:
        where.append("simbolo = ?")
        args.append(simbolo)
    filtro = ("WHERE " + " AND ".join(where)) if where else ""
    with conectar(False) as con:
        return _linhas(con.execute(
            f"SELECT busca_id, criada_em, simbolo, estrategia, status, testes, "
            f"inicio, fim FROM buscas {filtro} ORDER BY busca_id DESC", args))


def ler_elites(busca_id: int) -> list[dict]:
    with conectar(False) as con:
        return _linhas(con.execute(
            "SELECT * FROM elites WHERE busca_id = ? ORDER BY objetivo DESC", [busca_id]))


def ler_combos(busca_id: int, so_validas: bool = True) -> list[dict]:
    filtro = "AND valida" if so_validas else ""
    with conectar(False) as con:
        return _linhas(con.execute(
            f"SELECT * FROM combos WHERE busca_id = ? {filtro} ORDER BY teste_n",
            [busca_id]))


def ler_hist(busca_id: int) -> list[dict]:
    with conectar(False) as con:
        return _linhas(con.execute(
            "SELECT casa, teste_n, objetivo FROM elites_hist WHERE busca_id = ? "
            "ORDER BY teste_n", [busca_id]))


def ler_grupos(busca_id: int) -> list[dict]:
    with conectar(False) as con:
        gs = _linhas(con.execute(
            "SELECT * FROM grupos WHERE busca_id = ? ORDER BY grupo_id", [busca_id]))
    for g in gs:
        g["lider"] = json.loads(g["lider"])
        g["membros"] = json.loads(g["membros"])
        g["casas"] = json.loads(g["casas"]) if g.get("casas") else [g["lider_casa"]]
    return gs
