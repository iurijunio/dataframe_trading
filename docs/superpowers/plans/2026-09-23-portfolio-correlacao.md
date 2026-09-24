# Portfólio e correlação (projeto D, parte 2) — Plano de implementação

> **Para agentes:** cada tarefa é executada uma de cada vez, **sem agente
> executor** (o desenvolvedor implementa em pessoa, nesta sessão), e um
> agente é chamado só para **revisar** cada tarefa pronta antes do commit —
> mesma preferência já registrada nos planos dos projetos B e D-parte-1.

**Goal:** agrupar variantes de estratégia em portfólios, medir correlação
entre elas (retorno diário OOS) e estimar o drawdown diário combinado do
portfólio via simulação — sem inventar precisão que o dado não sustenta.

**Architecture:** duas tabelas novas (`portfolios`, `portfolio_variantes`,
join simples). O portfólio referencia só `variante_id`, nunca `plano_id`
— "o plano ativo de hoje" é sempre resolvido na hora por
`variantes.plano_ativo(variante_id)` (função nova, mesma cascata já
testada de `linha_do_tempo`). Correlação e risco vivem em
`core/portfolio.py`, consumindo `wfa_trades` (já existe, sem coluna
nova). Sexto modo no topo, tela "Portfólio", mesmo padrão de Estratégias.

**Tech Stack:** Python 3.12, DuckDB, Dash 4.4.1, NumPy.

**Spec:** [docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md](../specs/2026-09-23-portfolio-correlacao-design.md)

## Global Constraints

- Nada em `core/` importa Dash.
- Teste nunca toca `data/database.duckdb`: sempre banco temporário.
- Python é `.venv/Scripts/python.exe`; testes com
  `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`.
- Commits: `git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit`.
- O portfólio nunca grava `plano_id`/`wfa_id`/`run_id` — só `variante_id`.
- Correlação e risco usam SÓ colunas que já existem em `wfa_trades`/
  `instruments` — nenhuma mudança na engine, nenhuma leitura de barra.
- Simulações usam `numpy.random.default_rng` com seed fixa nos testes,
  para os resultados serem determinísticos.
- Linguagem de tela em português simples, sem jargão.

---

### Task 1: schema + `variantes.plano_ativo`

**Files:**
- Modify: `core/schema.sql`
- Modify: `core/variantes.py`
- Test: `tests/test_variantes.py`

**Interfaces:**
- Produces: `variantes.plano_ativo(variante_id: int) -> dict | None`
  (`{"run_id", "wfa_id", "plano_id"}` da mineração mais recente desta
  variante com um plano em `estado='ativo'`; `None` se nenhuma tiver).

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em tests/test_variantes.py
def test_plano_ativo_acha_a_mineracao_com_plano_ativo(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid)
    _wfa_no_banco(10, 1)
    plano_id = plano.salvar(
        wfa_id=10, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})

    ativo = variantes.plano_ativo(vid)

    assert ativo == {"run_id": 1, "wfa_id": 10, "plano_id": plano_id}


def test_plano_ativo_ignora_planos_aposentados(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid)
    _wfa_no_banco(10, 1)
    plano.salvar(
        wfa_id=10, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="v1", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})
    p1 = plano.salvar(
        wfa_id=10, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="v2", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})
    plano.aposentar(p1)

    assert variantes.plano_ativo(vid) is None


def test_plano_ativo_none_quando_variante_nao_tem_mineracao(banco):
    vid = variantes.criar("solitaria", "rompimento_canal")
    assert variantes.plano_ativo(vid) is None
```

(`plano.salvar` já aposenta sozinho o plano anterior do MESMO `wfa_id` —
o segundo teste força o cenário onde o ÚNICO plano restante também foi
aposentado, sem nenhum substituto.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_variantes.py -q`
Expected: FAIL com `AttributeError: module 'core.variantes' has no
attribute 'plano_ativo'`

- [ ] **Step 3: Implementar**

```python
# adicionar em core/variantes.py

def plano_ativo(variante_id: int) -> dict | None:
    sql = """
        SELECT m.run_id, w.wfa_id, p.plano_id
        FROM mining_runs m
        JOIN wfa_runs w ON w.run_id = m.run_id
        JOIN planos_operacao p ON p.wfa_id = w.wfa_id AND p.estado = 'ativo'
        WHERE m.variante_id = ?
        ORDER BY p.plano_id DESC
        LIMIT 1
    """
    with db.connect(read_only=True) as con:
        r = con.execute(sql, [variante_id]).fetchone()
    return {"run_id": r[0], "wfa_id": r[1], "plano_id": r[2]} if r else None
```

Nenhuma mudança de schema nesta tarefa — `plano_ativo` só lê tabelas que
já existem.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_variantes.py -q`
Expected: 11 passed (8 já existentes + 3 novos)

- [ ] **Step 5: Provar que os testes pegam o defeito**

Trocar `AND p.estado = 'ativo'` por `AND p.estado = 'aposentado'` e
conferir que `test_plano_ativo_acha_a_mineracao_com_plano_ativo` falha
(devolve `None` em vez do plano); desfazer.

- [ ] **Step 6: Commit**

```bash
git add core/variantes.py tests/test_variantes.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(portfolio): variantes.plano_ativo acha o plano ativo de hoje"
```

---

### Task 2: schema de portfólio + `core/portfolio.py` (membros)

**Files:**
- Modify: `core/schema.sql`
- Create: `core/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `variantes.plano_ativo(variante_id) -> dict | None` (Task 1).
- Produces: `portfolio.criar(nome) -> int`,
  `portfolio.listar() -> list[dict]`
  (`{"portfolio_id", "nome", "criado_em", "n_membros"}`),
  `portfolio.adicionar_variante(portfolio_id, variante_id)`,
  `portfolio.remover_variante(portfolio_id, variante_id)`,
  `portfolio.membros(portfolio_id) -> list[dict]`
  (`{"variante_id", "nome", "estrategia", "wfa_id", "sem_plano_ativo"}`).

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_portfolio.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def _mineracao_com_plano_ativo(run_id, variante_id, wfa_id,
                               symbol="WIN$N", strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, "2026-01-01", 10, "concluida", variante_id])
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])
    plano.salvar(
        wfa_id=wfa_id, run_id=run_id, symbol=symbol, strategy=strategy,
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})


def test_criar_e_listar(banco):
    pid = P.criar("meu portfólio")
    ps = P.listar()
    assert [p["portfolio_id"] for p in ps] == [pid]
    assert ps[0]["nome"] == "meu portfólio"
    assert ps[0]["n_membros"] == 0


def test_adicionar_e_remover_membro(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert [m["variante_id"] for m in ms] == [vid]
    assert P.listar()[0]["n_membros"] == 1

    P.remover_variante(pid, vid)
    assert P.membros(pid) == []
    assert P.listar()[0]["n_membros"] == 0


def test_membro_sem_plano_ativo_e_sinalizado(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is True
    assert ms[0]["wfa_id"] is None


def test_membro_com_plano_ativo_traz_o_wfa_id(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)

    ms = P.membros(pid)
    assert ms[0]["sem_plano_ativo"] is False
    assert ms[0]["wfa_id"] == 10


def test_adicionar_a_mesma_variante_duas_vezes_nao_duplica(banco):
    pid = P.criar("p1")
    vid = variantes.criar("conservadora", "rompimento_canal")
    P.adicionar_variante(pid, vid)
    P.adicionar_variante(pid, vid)
    assert len(P.membros(pid)) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_portfolio.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'core.portfolio'`

- [ ] **Step 3: Schema**

Em `core/schema.sql`, perto de `estrategia_variantes` (mesmo padrão de
sequência dedicada):

```sql
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id  BIGINT PRIMARY KEY,
    nome          VARCHAR NOT NULL,
    criado_em     TIMESTAMP NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_portfolio_id START 1;

CREATE TABLE IF NOT EXISTS portfolio_variantes (
    portfolio_id  BIGINT NOT NULL,
    variante_id   BIGINT NOT NULL,
    adicionado_em TIMESTAMP NOT NULL,
    PRIMARY KEY (portfolio_id, variante_id)
);
```

- [ ] **Step 4: `core/portfolio.py`**

```python
"""Portfólio: agrupar variantes de estratégia e medir correlação/risco.

O portfólio referencia só a VARIANTE, nunca plano/wfa/mineração
diretamente — "o que está ativo hoje" é sempre resolvido na hora via
variantes.plano_ativo, a mesma filosofia de "recalcula na hora" que o
WFA/Mineração já usa (core/wfa_runner.py:_span). Reotimizar uma variante
atualiza o portfólio sozinho, sem precisar mexer em nada aqui. Ver
docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db
from . import variantes as V


def criar(nome: str) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome do portfólio não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        pid = con.execute("SELECT nextval('seq_portfolio_id')").fetchone()[0]
        con.execute(
            "INSERT INTO portfolios (portfolio_id, nome, criado_em) "
            "VALUES (?,?,?)", [pid, nome, datetime.now()])
    return int(pid)


def listar() -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT p.portfolio_id, p.nome, p.criado_em, "
            "count(pv.variante_id) "
            "FROM portfolios p "
            "LEFT JOIN portfolio_variantes pv "
            "ON pv.portfolio_id = p.portfolio_id "
            "GROUP BY p.portfolio_id, p.nome, p.criado_em "
            "ORDER BY p.nome"
        ).fetchall()
    return [{"portfolio_id": r[0], "nome": r[1], "criado_em": r[2],
             "n_membros": r[3]} for r in rows]


def adicionar_variante(portfolio_id: int, variante_id: int) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute(
            "INSERT OR IGNORE INTO portfolio_variantes "
            "(portfolio_id, variante_id, adicionado_em) VALUES (?,?,?)",
            [portfolio_id, variante_id, datetime.now()])


def remover_variante(portfolio_id: int, variante_id: int) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute(
            "DELETE FROM portfolio_variantes "
            "WHERE portfolio_id = ? AND variante_id = ?",
            [portfolio_id, variante_id])


def membros(portfolio_id: int) -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT ev.variante_id, ev.nome, ev.estrategia "
            "FROM portfolio_variantes pv "
            "JOIN estrategia_variantes ev ON ev.variante_id = pv.variante_id "
            "WHERE pv.portfolio_id = ? ORDER BY ev.nome", [portfolio_id]
        ).fetchall()
    out = []
    for vid, nome, estrategia in rows:
        ativo = V.plano_ativo(vid)
        out.append({
            "variante_id": vid, "nome": nome, "estrategia": estrategia,
            "wfa_id": ativo["wfa_id"] if ativo else None,
            "sem_plano_ativo": ativo is None,
        })
    return out
```

`INSERT OR IGNORE` com a `PRIMARY KEY (portfolio_id, variante_id)` cobre
o "adicionar duas vezes não duplica" sem precisar de um SELECT antes.

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_portfolio.py -q`
Expected: 5 passed

- [ ] **Step 6: Provar que os testes pegam o defeito**

Trocar `INSERT OR IGNORE` por `INSERT` simples e conferir que
`test_adicionar_a_mesma_variante_duas_vezes_nao_duplica` falha (violação
de chave primária estoura, ou duplica se a constraint não pegar);
desfazer.

- [ ] **Step 7: Commit**

```bash
git add core/schema.sql core/portfolio.py tests/test_portfolio.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(portfolio): portfolios, portfolio_variantes, membros"
```

---

### Task 3: correlação entre variantes do portfólio

**Files:**
- Modify: `core/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `wfa_trades` (`exit_ts`, `liquido`), `membros()` (Task 2).
- Produces: `portfolio.correlacao(portfolio_id) -> dict`
  (`{"variantes": [...], "matriz": [[...]], "risco_diario": None,
  "avisos": [...]}` — `risco_diario` fica `None` até a Task 4).

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em tests/test_portfolio.py
from datetime import datetime, timedelta

import numpy as np


def _gravar_trades(wfa_id, dias_e_liquidos, symbol="WIN$N"):
    """dias_e_liquidos: [(offset_dias, liquido), ...] a partir de 2026-01-01."""
    base = datetime(2026, 1, 1)
    with db.connect_write() as con:
        for n, (offset, liquido) in enumerate(dias_e_liquidos):
            ts = base + timedelta(days=offset)
            con.execute(
                "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, "
                "liquido, mae, contratos) VALUES (?,?,?,?,?,?,?)",
                [wfa_id, n, ts, ts, liquido, 100, 1])


def _membro_pronto(pid, nome, wfa_id, dias_e_liquidos):
    vid = variantes.criar(nome, "rompimento_canal")
    _mineracao_com_plano_ativo(wfa_id, vid, wfa_id=wfa_id)
    P.adicionar_variante(pid, vid)
    _gravar_trades(wfa_id, dias_e_liquidos)
    return vid


def test_correlacao_de_series_identicas_e_proxima_de_um(banco):
    pid = P.criar("p1")
    serie = [(i, float((i % 5) - 2)) for i in range(30)]  # 30 dias variados
    _membro_pronto(pid, "a", 10, serie)
    _membro_pronto(pid, "b", 11, serie)

    r = P.correlacao(pid)

    assert r["variantes"] == ["a", "b"]
    assert r["matriz"][0][1] == pytest.approx(1.0, abs=1e-6)
    assert r["avisos"] == []


def test_correlacao_de_series_opostas_e_proxima_de_menos_um(banco):
    pid = P.criar("p1")
    serie_a = [(i, float((i % 5) - 2)) for i in range(30)]
    serie_b = [(i, -v) for i, v in serie_a]
    _membro_pronto(pid, "a", 10, serie_a)
    _membro_pronto(pid, "b", 11, serie_b)

    r = P.correlacao(pid)
    assert r["matriz"][0][1] == pytest.approx(-1.0, abs=1e-6)


def test_periodo_sem_intersecao_suficiente_vira_aviso(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 1.0) for i in range(30)])
    _membro_pronto(pid, "b", 11, [(i, 1.0) for i in range(200, 210)])  # so 0 em comum

    r = P.correlacao(pid)
    assert r["matriz"][0][1] is None
    assert "período curto demais" in r["avisos"][0]


def test_membro_sem_plano_ativo_fica_de_fora_da_matriz(banco):
    pid = P.criar("p1")
    _membro_pronto(pid, "a", 10, [(i, 1.0) for i in range(30)])
    vid_b = variantes.criar("b", "rompimento_canal")
    P.adicionar_variante(pid, vid_b)  # sem mineração nenhuma

    r = P.correlacao(pid)
    assert r["variantes"] == ["a"]
    assert any("sem plano ativo" in a for a in r["avisos"])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_portfolio.py -q`
Expected: FAIL com `AttributeError: module 'core.portfolio' has no
attribute 'correlacao'`

- [ ] **Step 3: Implementar**

```python
# adicionar no topo de core/portfolio.py
from collections import defaultdict

import numpy as np

_MIN_DIAS_COMUNS = 20

# adicionar no fim de core/portfolio.py

def _retornos_diarios(wfa_id: int) -> dict:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT exit_ts, liquido FROM wfa_trades WHERE wfa_id = ?",
            [wfa_id]).fetchall()
    diario: dict = defaultdict(float)
    for exit_ts, liquido in rows:
        diario[exit_ts.date()] += liquido
    return dict(diario)


def correlacao(portfolio_id: int) -> dict:
    ms = membros(portfolio_id)
    ativos = [m for m in ms if not m["sem_plano_ativo"]]
    avisos = [f"{m['nome']}: sem plano ativo" for m in ms if m["sem_plano_ativo"]]

    series = {m["nome"]: _retornos_diarios(m["wfa_id"]) for m in ativos}
    nomes = list(series)
    n = len(nomes)
    matriz = [[1.0 if i == j else None for j in range(n)] for i in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            a, b = series[nomes[i]], series[nomes[j]]
            comuns = sorted(set(a) & set(b))
            if len(comuns) < _MIN_DIAS_COMUNS:
                avisos.append(
                    f"{nomes[i]} × {nomes[j]}: período curto demais para correlação")
                continue
            xa = np.array([a[d] for d in comuns])
            xb = np.array([b[d] for d in comuns])
            if xa.std() == 0 or xb.std() == 0:
                # retorno constante no periodo daria corrcoef 0/0 = nan,
                # um numero "real" sem sentido, se deixado passar direto
                # (achado real na revisao do agente)
                avisos.append(
                    f"{nomes[i]} × {nomes[j]}: sem variação suficiente no "
                    f"período para correlação")
                continue
            r = float(np.corrcoef(xa, xb)[0, 1])
            matriz[i][j] = matriz[j][i] = r

    return {"variantes": nomes, "matriz": matriz, "risco_diario": None,
            "avisos": avisos}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_portfolio.py -q`
Expected: 9 passed (5 da Task 2 + 4 novos)

- [ ] **Step 5: Provar que os testes pegam o defeito**

Remover temporariamente o corte de dias mínimos (deixar o `if` sempre
passar direto para o `corrcoef`, sem o `continue`):

```python
            comuns = sorted(set(a) & set(b))
            # if len(comuns) < _MIN_DIAS_COMUNS:      <- comentar as 3 linhas
            #     avisos.append(...)
            #     continue
```

Rodar `pytest tests/test_portfolio.py -q` e conferir que
`test_periodo_sem_intersecao_suficiente_vira_aviso` falha — com 0 dias
em comum, `np.corrcoef` sobre arrays vazios não devolve `None` na
matriz (vira `nan` ou estoura), provando que o teste depende de verdade
do corte de dias mínimos; desfazer.

- [ ] **Step 6: Commit**

```bash
git add core/portfolio.py tests/test_portfolio.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(portfolio): correlacao entre variantes, retorno diario OOS"
```

---

### Task 4: risco diário combinado (simulação)

**Files:**
- Modify: `core/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `wfa_trades` (`entry_ts`, `exit_ts`, `mae`, `contratos`,
  `liquido`), `wfa_runs.symbol`, `instruments.point_value`.
- Produces: `correlacao()`'s `risco_diario` passa a vir preenchido:
  `{"p90": float, "pior_dia": str} | None`.

**Por que a simulação interpola em vez de somar o MAE bruto:** cada
trade só grava a MAGNITUDE do pior ponto (`mae`), não o instante em que
aconteceu. Tratar um trade aberto como "sempre no fundo" durante toda a
janela reproduz o mesmo pessimismo artificial que a spec descartou (ver
design doc §3, decisão 8). Em vez disso, cada simulação sorteia UM
instante por trade como "quando" ele bateu o fundo, e interpola
linearmente `0 (entrada) -> -mae (o instante sorteado) -> liquido
(saída)` — um trade que ainda não chegou no seu próprio instante
sorteado contribui menos que o pior dele, não o pior inteiro. O pior
ponto combinado da simulação é o mínimo da soma de todos os trades,
avaliada exatamente nos instantes sorteados de cada um (são os únicos
pontos onde a curva de algum trade "dobra", e portanto os únicos
candidatos a mínimo local da soma).

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em tests/test_portfolio.py

def _gravar_trade_risco(wfa_id, entry_ts, exit_ts, mae_pontos, liquido):
    # sem linha em `instruments` para o simbolo do teste, `_trades_para_risco`
    # cai no padrao point_value=1.0 - mae_pontos vira mae_reais 1:1, de
    # proposito, pra deixar os numeros dos testes faceis de conferir a mao
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_trades (wfa_id, n, entry_ts, exit_ts, mae, "
            "contratos, liquido) VALUES (?,?,?,?,?,?,?)",
            [wfa_id, 0, entry_ts, exit_ts, mae_pontos, 1, liquido])


def test_risco_diario_none_sem_sobreposicao_nenhuma(banco):
    pid = P.criar("p1")
    vid = variantes.criar("a", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid, wfa_id=10)
    P.adicionar_variante(pid, vid)
    _gravar_trade_risco(10, datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 17),
                        mae_pontos=100, liquido=50.0)

    r = P.correlacao(pid)
    # um trade sozinho no dia nunca "combina" com ninguem - sem par, sem risco
    assert r["risco_diario"] is None


def test_risco_diario_trades_sem_sobreposicao_de_horario_fica_leve(banco):
    """Duas variantes que operam em janelas de horário que NUNCA se cruzam
    no mesmo dia não devem produzir um risco parecido com a soma dos dois
    piores casos - é essa a armadilha que a simulação evita."""
    pid = P.criar("p1")
    vid_a = variantes.criar("a", "rompimento_canal")
    vid_b = variantes.criar("b", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid_a, wfa_id=10)
    _mineracao_com_plano_ativo(2, vid_b, wfa_id=11)
    P.adicionar_variante(pid, vid_a)
    P.adicionar_variante(pid, vid_b)
    dia = datetime(2026, 1, 1)
    _gravar_trade_risco(10, dia.replace(hour=9), dia.replace(hour=10),
                        mae_pontos=500, liquido=-100.0)
    _gravar_trade_risco(11, dia.replace(hour=14), dia.replace(hour=15),
                        mae_pontos=500, liquido=-100.0)

    r = P.correlacao(pid)
    assert r["risco_diario"] is not None
    # a soma bruta dos dois MAEs seria -1000; sem sobreposicao de horario,
    # o p90 tem que ficar bem acima disso (bem menos severo)
    assert r["risco_diario"]["p90"] > -700


def test_risco_diario_trades_sempre_sobrepostos_fica_proximo_da_soma(banco):
    """Duas variantes que operam o dia inteiro (janela igual) se encontram
    em toda simulação - o p90 deve chegar perto da soma dos dois MAEs."""
    pid = P.criar("p1")
    vid_a = variantes.criar("a", "rompimento_canal")
    vid_b = variantes.criar("b", "rompimento_canal")
    _mineracao_com_plano_ativo(1, vid_a, wfa_id=10)
    _mineracao_com_plano_ativo(2, vid_b, wfa_id=11)
    P.adicionar_variante(pid, vid_a)
    P.adicionar_variante(pid, vid_b)
    dia = datetime(2026, 1, 1)
    _gravar_trade_risco(10, dia.replace(hour=9), dia.replace(hour=17),
                        mae_pontos=500, liquido=-100.0)
    _gravar_trade_risco(11, dia.replace(hour=9), dia.replace(hour=17),
                        mae_pontos=500, liquido=-100.0)

    r = P.correlacao(pid)
    # soma bruta dos MAEs = -1000; com janelas identicas a simulacao
    # frequentemente encontra os dois perto do fundo juntos, mas a
    # interpolacao (credito parcial pra quem ainda nao chegou no proprio
    # instante sorteado) tem que manter o p90 ACIMA da soma bruta - um
    # trade "sempre no fundo" enquanto aberto (sem interpolar) devolveria
    # exatamente -1000 em toda simulacao, sem variacao nenhuma
    assert -1000.0 < r["risco_diario"]["p90"] < -600
    assert r["risco_diario"]["pior_dia"] == "2026-01-01"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_portfolio.py -q`
Expected: FAIL nos 3 testes novos — `risco_diario` continua `None`
sempre (a implementação da Task 3 nunca preenche).

- [ ] **Step 3: Implementar**

```python
# adicionar no topo de core/portfolio.py
_N_SIMULACOES = 2000
_PERCENTIL_RISCO = 10  # "so e ultrapassado em 10% dos cenarios" - ver spec §5.3

# adicionar no fim de core/portfolio.py

def _trades_para_risco(wfa_id: int) -> list[dict]:
    with db.connect(read_only=True) as con:
        symbol = con.execute(
            "SELECT symbol FROM wfa_runs WHERE wfa_id = ?", [wfa_id]
        ).fetchone()[0]
        r = con.execute(
            "SELECT point_value FROM instruments WHERE symbol = ?", [symbol]
        ).fetchone()
        ponto = float(r[0]) if r and r[0] else 1.0
        rows = con.execute(
            "SELECT entry_ts, exit_ts, mae, contratos, liquido "
            "FROM wfa_trades WHERE wfa_id = ? ORDER BY entry_ts",
            [wfa_id]).fetchall()
    return [
        {"entry_ts": r[0], "exit_ts": r[1],
         "mae_reais": abs(r[2] or 0) * ponto * (r[3] or 1),
         "liquido": r[4] or 0.0}
        for r in rows if r[0] and r[1]
    ]
```

(`ORDER BY entry_ts` — achado da revisão: sem isso, a ordem dos trades
não é garantida pelo DuckDB, e a simulação Monte Carlo consome o RNG na
ordem em que os trades chegam, então dois `correlacao()` seguidos
poderiam, em teoria, dar `p90` diferente. Confirmado deterministic com
`ORDER BY`.)

```python


def _simular_pior_ponto(trades: list[dict], rng) -> float:
    partes = []
    for t in trades:
        ini, fim = t["entry_ts"].timestamp(), t["exit_ts"].timestamp()
        if fim <= ini:
            continue
        t_mae = rng.uniform(ini, fim)
        partes.append((ini, t_mae, fim, -t["mae_reais"], t["liquido"]))
    if not partes:
        return 0.0

    def valor(p, inst):
        ini, t_mae, fim, fundo, liquido = p
        if inst < ini:
            return 0.0
        if inst >= fim:
            return liquido
        if inst <= t_mae:
            frac = (inst - ini) / (t_mae - ini) if t_mae > ini else 1.0
            return fundo * frac
        frac = (inst - t_mae) / (fim - t_mae) if fim > t_mae else 1.0
        return fundo + (liquido - fundo) * frac

    candidatos = [p[1] for p in partes]
    return min(sum(valor(p, inst) for p in partes) for inst in candidatos)


def _risco_diario(membros_ativos: list[dict]) -> dict | None:
    todos = []
    for m in membros_ativos:
        todos.extend(_trades_para_risco(m["wfa_id"]))
    if not todos:
        return None

    por_dia: dict = defaultdict(list)
    for t in todos:
        por_dia[t["entry_ts"].date()].append(t)

    rng = np.random.default_rng(0)
    piores_por_dia = {}
    for dia, trades in por_dia.items():
        if len(trades) < 2:
            continue
        amostras = [_simular_pior_ponto(trades, rng) for _ in range(_N_SIMULACOES)]
        piores_por_dia[dia] = float(np.percentile(amostras, _PERCENTIL_RISCO))

    if not piores_por_dia:
        return None
    pior_dia = min(piores_por_dia, key=piores_por_dia.get)
    return {"p90": piores_por_dia[pior_dia], "pior_dia": str(pior_dia)}
```

E trocar, dentro de `correlacao()`, a linha que hoje devolve
`"risco_diario": None` por `"risco_diario": _risco_diario(ativos)`.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_portfolio.py -q`
Expected: 12 passed (9 da Task 3 + 3 novos)

- [ ] **Step 5: Provar que os testes pegam o defeito**

Em `_simular_pior_ponto`, trocar o corpo de `valor()` para tratar
qualquer trade aberto como "sempre no fundo" (a mutação reproduz a soma
bruta que a spec descartou por pessimista demais):

```python
    def valor(p, inst):
        ini, t_mae, fim, fundo, liquido = p
        if inst < ini:
            return 0.0
        if inst >= fim:
            return liquido
        return fundo
```

Rodar `pytest tests/test_portfolio.py -q` e conferir que
`test_risco_diario_trades_sempre_sobrepostos_fica_proximo_da_soma` falha
— sem interpolação, os dois trades (mesma janela 9h-17h) sempre
contribuem o MAE inteiro em qualquer instante avaliado, então o p90 vira
exatamente -1000.0 em toda simulação (sem a variação que a interpolação
produz), violando `p90 > -1000.0`. (O outro teste novo, "sem
sobreposição de horário", NÃO pega esta mutação — as janelas nunca se
cruzam, então o ramo de crédito parcial nunca chega a ser avaliado nele;
é só o de janelas idênticas que exercita essa lógica.) Desfazer depois.

- [ ] **Step 6: Commit**

```bash
git add core/portfolio.py tests/test_portfolio.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(portfolio): risco diario combinado via simulacao (p90)"
```

---

### Task 5: sexto modo — tela de Portfólio

**Files:**
- Create: `ui/components/portfolio_panel.py`
- Create: `ui/callbacks_portfolio.py`
- Modify: `ui/app.py` (topbar — novo item no `RadioItems`; `painel()` —
  novo `html.Div#painel-portfolio`)
- Modify: `ui/callbacks.py` (callback `modo` ganha o sexto caso;
  registrar `callbacks_portfolio`)
- Modify: `ui/assets/style.css`
- Test: `tests/test_callbacks_sem_ciclo.py`

**Interfaces:**
- Consumes: `core.portfolio.listar/criar/membros/adicionar_variante/
  remover_variante/correlacao`, `core.variantes.listar` (para o dropdown
  de "adicionar variante", com todas as estratégias juntas).

- [ ] **Step 1: o item no topo**

Em `ui/app.py`, dentro de `topbar()`:

```python
                        options=[{"label": "Backtest", "value": "backtest"},
                                 {"label": "Mineração", "value": "mineracao"},
                                 {"label": "Walk-Forward", "value": "wfa"},
                                 {"label": "Candidata", "value": "candidata"},
                                 {"label": "Estratégias", "value": "estrategias"},
                                 {"label": "Portfólio", "value": "portfolio"}],
```

- [ ] **Step 2: o componente**

```python
# ui/components/portfolio_panel.py
"""Portfólio: agrupar variantes, ver membros, correlação e risco diário.

Só a fatia de portfólio e correlação (projeto D, parte 2) — alocação de
capital por variante e gatilho automático de reotimização ficam de fora,
ver docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md §2.
"""
from __future__ import annotations

from dash import dcc, html

from .cartao import brl, card


def painel():
    return html.Div(
        [
            html.Section([
                html.H2("Portfólio", className="panel-title"),
                html.Div([
                    dcc.Input(id="pf-novo-nome", type="text", className="inp",
                              placeholder="nome do novo portfólio",
                              debounce=True),
                    html.Button("Criar", id="pf-btn-criar", n_clicks=0,
                                className="btn-ghost"),
                ], className="acoes"),
                html.Div(id="pf-lista", className="est-lista"),
            ], className="panel"),
            html.Section(
                id="pf-detalhe", className="panel", style={"display": "none"},
                children=[
                    html.H3(id="pf-detalhe-titulo"),
                    html.Div([
                        dcc.Dropdown(id="pf-add-variante", className="dd dd-sm",
                                    placeholder="adicionar variante…",
                                    options=[]),
                        html.Button("Adicionar", id="pf-btn-add", n_clicks=0,
                                    className="btn-ghost"),
                    ], className="acoes"),
                    html.Div(id="pf-membros"),
                    html.Div(id="pf-risco"),
                    html.Div(id="pf-heatmap"),
                    html.Div(id="pf-avisos"),
                ],
            ),
        ],
        id="painel-portfolio", className="modo-bloco",
        style={"display": "none"},
    )


def cartao_portfolio(portfolio_id: int, nome: str, n_membros: int) -> html.Div:
    return html.Div(
        [html.Span(nome, className="est-cartao-nome"),
         html.Span(f"{n_membros} variante(s)", className="est-cartao-nota")],
        id={"type": "pf-cartao", "portfolio_id": portfolio_id},
        className="est-cartao", n_clicks=0,
    )


def linha_membro(variante_id: int, nome: str, estrategia: str,
                 sem_plano_ativo: bool) -> html.Div:
    nota = "sem plano ativo" if sem_plano_ativo else "plano ativo"
    return html.Div(
        [html.Span(f"{nome} · {estrategia}", className="est-variante-nome"),
         html.Span(nota, className="est-variante-nota"
                   + (" pf-sem-plano" if sem_plano_ativo else "")),
         html.Button("remover", id={"type": "pf-btn-remover",
                                    "variante_id": variante_id},
                     className="btn-ghost btn-sm", n_clicks=0)],
        className="est-variante",
    )


def card_risco(risco: dict | None) -> html.Div:
    if risco is None:
        return html.P("adicione pelo menos duas variantes com plano ativo "
                      "e trades no mesmo dia para ver o risco combinado.")
    sinal = "neg" if risco["p90"] < 0 else "pos"
    return card("drawdown diário combinado (p90)", brl(risco["p90"]),
                explica="Estimativa por simulação: o valor só é "
                        "ultrapassado em 10% dos cenários simulados — não "
                        "é o pior caso absoluto.",
                sinal=sinal, nota=f"pior dia: {risco['pior_dia']}")


def _cor_celula(r: float | None) -> str:
    if r is None:
        return "rgba(255,255,255,.03)"
    alpha = min(abs(r), 1.0)
    cor = "255,77,125" if r >= 0 else "0,245,160"
    return f"rgba({cor},{alpha:.2f})"


def heatmap(nomes: list[str], matriz: list[list]) -> html.Div:
    if len(nomes) < 2:
        return html.P("adicione pelo menos duas variantes com plano ativo "
                      "para ver a correlação.")
    n = len(nomes)
    cabecalho = [html.Div("", className="pf-heat-canto")] + [
        html.Div(nome, className="pf-heat-rotulo") for nome in nomes]
    linhas = [cabecalho]
    for i in range(n):
        linha = [html.Div(nomes[i], className="pf-heat-rotulo")]
        for j in range(n):
            v = matriz[i][j]
            texto = f"{v:.2f}" if v is not None else "—"
            linha.append(html.Div(
                texto, className="pf-heat-cel",
                style={"backgroundColor": _cor_celula(v)}))
        linhas.append(linha)
    return html.Div(
        [html.Div(linha, className="pf-heat-linha") for linha in linhas],
        className="pf-heatmap",
        style={"gridTemplateColumns": f"auto repeat({n}, 1fr)"},
    )
```

- [ ] **Step 3: o callback**

```python
# ui/callbacks_portfolio.py
"""Callbacks da tela Portfólio — portfólios, membros, correlação e risco."""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, html, no_update

from core import portfolio as P
from core import variantes as V

from .components import portfolio_panel as PP


def register(app):
    @app.callback(
        Output("pf-lista", "children"),
        Input("modo", "value"),
        Input("pf-btn-criar", "n_clicks"),
        State("pf-novo-nome", "value"),
        prevent_initial_call=False,
    )
    def listar_portfolios(modo, n_criar, nome_novo):
        if ctx.triggered_id == "pf-btn-criar" and (nome_novo or "").strip():
            P.criar(nome_novo.strip())
        if modo != "portfolio":
            return no_update
        return [PP.cartao_portfolio(p["portfolio_id"], p["nome"], p["n_membros"])
                for p in P.listar()]

    @app.callback(
        Output("pf-add-variante", "options"),
        Input("modo", "value"),
    )
    def opcoes_variantes(modo):
        if modo != "portfolio":
            return no_update
        return [{"label": f"{v['nome']} ({v['estrategia']})",
                 "value": v["variante_id"]} for v in V.listar()]

    @app.callback(
        Output("pf-detalhe", "style"),
        Output("pf-detalhe-titulo", "children"),
        Output("pf-membros", "children"),
        Output("pf-heatmap", "children"),
        Output("pf-risco", "children"),
        Output("pf-avisos", "children"),
        Input({"type": "pf-cartao", "portfolio_id": ALL}, "n_clicks"),
        Input("pf-btn-add", "n_clicks"),
        Input({"type": "pf-btn-remover", "variante_id": ALL}, "n_clicks"),
        State("pf-add-variante", "value"),
        prevent_initial_call=True,
    )
    def abrir_detalhe(_cliques_cartao, _add, _remover, variante_add):
        gatilho = ctx.triggered_id
        pid = _portfolio_aberto()
        if isinstance(gatilho, dict) and gatilho.get("type") == "pf-cartao":
            pid = gatilho["portfolio_id"]
            _lembrar_portfolio_aberto(pid)
        elif gatilho == "pf-btn-add" and pid is not None and variante_add:
            P.adicionar_variante(pid, variante_add)
        elif isinstance(gatilho, dict) and gatilho.get("type") == "pf-btn-remover":
            if pid is not None:
                P.remover_variante(pid, gatilho["variante_id"])

        if pid is None:
            return {"display": "none"}, no_update, no_update, no_update, no_update, no_update

        nome = next((p["nome"] for p in P.listar() if p["portfolio_id"] == pid), "")
        ms = P.membros(pid)
        linhas_membros = [
            PP.linha_membro(m["variante_id"], m["nome"], m["estrategia"],
                            m["sem_plano_ativo"]) for m in ms
        ] or [html.P("nenhuma variante neste portfólio ainda.")]

        r = P.correlacao(pid)
        avisos = html.Ul([html.Li(a) for a in r["avisos"]]) if r["avisos"] else None

        return ({"display": "block"}, nome, linhas_membros,
                PP.heatmap(r["variantes"], r["matriz"]),
                PP.card_risco(r["risco_diario"]), avisos)
```

`ctx.triggered_id` decide qual ação aconteceu (mesmo padrão já corrigido
na Tarefa 5 do plano de identidade da estratégia — nunca usar
`any(n_clicks)`/primeiro-verdadeiro com padrão-matching). O portfólio
"aberto no momento" precisa sobreviver entre re-renders (clicar
Adicionar/Remover deve continuar mostrando o mesmo portfólio) — isso
pede um `dcc.Store`, adicionado no Step 4.

- [ ] **Step 4: o Store do portfólio aberto**

Em `ui/callbacks_portfolio.py`, sem um `dcc.Store` dedicado o callback
acima não tem como saber "qual portfólio estava aberto" quando o
gatilho é Adicionar/Remover (só quando o gatilho é o PRÓPRIO cartão).
Adicionar em `ui/app.py`, junto dos outros `dcc.Store` do `app.layout`:

```python
            dcc.Store(id="store-portfolio-aberto"),
```

E reescrever `_portfolio_aberto`/`_lembrar_portfolio_aberto` como
`State`/`Output` do `dcc.Store` em vez de função solta — ajustar a
assinatura do callback `abrir_detalhe`:

```python
    @app.callback(
        Output("pf-detalhe", "style"),
        Output("pf-detalhe-titulo", "children"),
        Output("pf-membros", "children"),
        Output("pf-heatmap", "children"),
        Output("pf-risco", "children"),
        Output("pf-avisos", "children"),
        Output("store-portfolio-aberto", "data"),
        Input({"type": "pf-cartao", "portfolio_id": ALL}, "n_clicks"),
        Input("pf-btn-add", "n_clicks"),
        Input({"type": "pf-btn-remover", "variante_id": ALL}, "n_clicks"),
        State("pf-add-variante", "value"),
        State("store-portfolio-aberto", "data"),
        prevent_initial_call=True,
    )
    def abrir_detalhe(_cliques_cartao, _add, _remover, variante_add, pid):
        gatilho = ctx.triggered_id
        if isinstance(gatilho, dict) and gatilho.get("type") == "pf-cartao":
            pid = gatilho["portfolio_id"]
        elif gatilho == "pf-btn-add" and pid is not None and variante_add:
            P.adicionar_variante(pid, variante_add)
        elif isinstance(gatilho, dict) and gatilho.get("type") == "pf-btn-remover":
            if pid is not None:
                P.remover_variante(pid, gatilho["variante_id"])

        if pid is None:
            return ({"display": "none"}, no_update, no_update, no_update,
                    no_update, no_update, pid)

        nome = next((p["nome"] for p in P.listar() if p["portfolio_id"] == pid), "")
        ms = P.membros(pid)
        linhas_membros = [
            PP.linha_membro(m["variante_id"], m["nome"], m["estrategia"],
                            m["sem_plano_ativo"]) for m in ms
        ] or [html.P("nenhuma variante neste portfólio ainda.")]

        r = P.correlacao(pid)
        avisos = html.Ul([html.Li(a) for a in r["avisos"]]) if r["avisos"] else None

        return ({"display": "block"}, nome, linhas_membros,
                PP.heatmap(r["variantes"], r["matriz"]),
                PP.card_risco(r["risco_diario"]), avisos, pid)
```

(remover as funções `_portfolio_aberto`/`_lembrar_portfolio_aberto` do
Step 3 — foram substituídas pelo `dcc.Store`.)

- [ ] **Step 5: ligar no `modo`, registrar, CSS**

Em `ui/app.py`, dentro de `painel()`, depois de `estrategias_panel.painel()`:

```python
            portfolio_panel.painel(),
```

(importar `portfolio_panel` junto dos outros componentes, e acrescentar
`dcc.Store(id="store-portfolio-aberto")` junto dos outros stores, como
descrito no Step 4)

Em `ui/callbacks.py`, o callback `modo` ganha o sexto `Output` e o sexto
`v(...)`:

```python
    @app.callback(
        Output("painel-backtest", "style"), Output("painel-mineracao", "style"),
        Output("painel-wfa", "style"), Output("painel-candidata", "style"),
        Output("painel-estrategias", "style"), Output("painel-portfolio", "style"),
        Output("acao-backtest", "style"), Output("sec-mineracao", "style"),
        Output("sidebar", "style"),
        Input("modo", "value"),
    )
    def modo(qual):
        ...
        return (v(qual == "backtest"), v(qual == "mineracao"), v(qual == "wfa"),
                v(qual == "candidata"), v(qual == "estrategias"),
                v(qual == "portfolio"),
                VISIVEL if qual == "backtest" else OCULTO,
                VISIVEL if qual == "mineracao" else OCULTO,
                OCULTO if qual in ("wfa", "candidata", "estrategias", "portfolio")
                else {"display": "block"})
```

E, perto do fim do arquivo, junto dos outros registros:

```python
    from ui import callbacks_portfolio
    callbacks_portfolio.register(app)
```

Em `ui/assets/style.css`, seguindo o padrão de `.est-*` já existente:

```css
.pf-sem-plano{color:var(--warn);}
.pf-heatmap{display:grid;gap:2px;margin-top:12px;}
.pf-heat-linha{display:contents;}
.pf-heat-canto{}
.pf-heat-rotulo{padding:6px 8px;font-size:.85em;color:var(--muted);
  display:flex;align-items:center;}
.pf-heat-cel{padding:6px 8px;text-align:center;border-radius:4px;
  font-family:var(--mono);font-size:.85em;}
.btn-sm{padding:2px 8px;font-size:.8em;}
```

(`.pf-heat-linha{display:contents}` é o que faz cada "linha" lógica
(uma `html.Div` de children) se comportar como se seus filhos
estivessem direto no grid pai — sem isso o CSS Grid trataria cada linha
como uma única célula.)

- [ ] **Step 6: rodar a suíte inteira, inclusive o teste de ciclo**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
Expected: tudo passa; `test_callbacks_sem_ciclo.py` prova que os
`Output`s novos (inclusive `store-portfolio-aberto.data`) têm dono só.

- [ ] **Step 7: conferência manual, na tela**

Subir o app, clicar em "Portfólio", criar um portfólio, abrir o
detalhe, adicionar duas variantes que tenham plano ativo (criadas nas
tarefas anteriores ou numa mineração de teste), conferir que o heatmap
e o card de risco aparecem. Remover uma variante e conferir que a tela
atualiza sem perder qual portfólio está aberto.

- [ ] **Step 8: Commit**

```bash
git add ui/components/portfolio_panel.py ui/callbacks_portfolio.py ui/app.py ui/callbacks.py ui/assets/style.css
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(portfolio): tela de Portfolio, membros, heatmap de correlacao e risco diario"
```

---

## Conferência do plano contra a spec

| spec | tarefa |
|---|---|
| §3 decisão 6 (`plano_ativo` reaproveitando a cascata da parte 1) | 1 |
| §4 arquitetura (tabelas novas, sem coluna em tabela existente) | 2 |
| §3 decisões 1-3 (vários portfólios, só associação, segue plano ativo) | 2 |
| §5.2 correlação (retorno diário, interseção, aviso < 20 dias) | 3 |
| §5.3 risco diário (simulação, não soma bruta) | 4 |
| §3 decisão 7 (sexto modo) | 5 |
| §6 tela (heatmap, card de risco, avisos discretos) | 5 |
| §7 testes | 1, 2, 3, 4, 5 (ciclo) |
| §2 fora de escopo | nenhuma tarefa toca alocação de capital, gatilho automático ou reconstrução minuto a minuto |
