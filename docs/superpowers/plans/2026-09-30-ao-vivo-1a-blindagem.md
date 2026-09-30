# Ao vivo 1a — Blindagem do banco: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** proteger o banco para que nenhuma estratégia em operação perca o plano em silêncio, e criar as estruturas (contas, portfólio ligado, ligações com fase, diário de eventos, vigência e impressão digital do plano) que a tela Ao vivo e o robô vão usar.

**Architecture:** tudo em `core/` sem Dash, com testes em banco temporário. Três módulos novos pequenos: `core/codigo.py` (impressão digital), `core/diario.py` (diário só-inserção) e `core/ao_vivo.py` (contas, interruptores, vincular). Mudanças cirúrgicas em `plano.py`, `variantes.py`, `portfolio.py`, `optimizer.py`, `wfa_store.py`, `schema.sql`. A tela só ganha as mensagens de recusa; a sub-tela Ao vivo › Estratégias é o plano 1b.

**Tech Stack:** Python 3.11, DuckDB 1.5.5, pytest 9, Dash (só na Task 12).

**Spec:** `docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md` — leia §3 e §4 antes de começar. Onde este plano e a spec divergirem, a spec manda. Divergência consciente: `registrar`/`eventos` moram em `core/diario.py` (não em `ao_vivo.py`) para `plano.py` e `portfolio.py` poderem usá-los sem import circular; `em_operacao`, `repetidas` e `rastreio` ficam para o plano 1b.

## Global Constraints

- Leia `CLAUDE.md` na raiz. Código, nomes, comentários e mensagens em **português**; comentário explica **por quê**.
- **Nada em `core/` importa Dash.**
- **Nenhum teste toca `data/database.duckdb`** — fixture `banco` com `monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")` + `db.init_schema`.
- **Nunca abrir conexão nova com uma transação aberta no mesmo processo** (o DuckDB recusa e `connect` fica 15 s tentando). Funções chamadas de dentro de uma transação recebem `con`.
- Toda recusa de regra é `ValueError` com texto em português, pronto para a tela.
- Todo evento do diário é gravado **na mesma transação** da mudança de estado (`diario.registrar(con, ...)`).
- **NÃO tocar** em `ui/components/controls.py`, `ui/components/wfa_matriz.py`, `strategies/rompimento_abertura.py`. `git add` sempre por caminho.
- Git pela tool **PowerShell**; mensagem de commit em arquivo do scratchpad + `git commit -F <arquivo>`, terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Suíte: `.venv/Scripts/python.exe -m pytest -q`. Arquivo único: `.venv/Scripts/python.exe -m pytest -q tests/<arquivo>.py`.
- Datas de teste: 2026-10-01 é **quinta**. `proximo_dia_util`: qua→qui, qui→sex, sex/sáb/dom→seg (2026-10-05).
- Mutação (CLAUDE.md, "Como trabalhar"): ao fim de cada task de `core/`, quebrar a implementação de propósito 2–3 vezes (agente `mutacao` se disponível), confirmar que algum teste falha, restaurar.

---

### Task 1: Impressão digital do código da estratégia

**Files:**
- Create: `core/codigo.py`
- Test: `tests/test_codigo.py`

**Interfaces:**
- Produces: `codigo.hash_estrategia(estrategia: str, pasta: Path | None = None) -> str | None` — sha256 hex de `base.py` + `<estrategia>.py` com `\r\n`→`\n`; `None` se o arquivo da estratégia não existe.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_codigo.py
"""A impressão digital do código: o plano precisa saber qual versão da
estratégia gerou os números que ele promete."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import codigo  # noqa: E402


def _pasta(tmp_path, estrategia="x", corpo=b"a = 1\nb = 2\n", base=b"BASE\n"):
    (tmp_path / "base.py").write_bytes(base)
    (tmp_path / f"{estrategia}.py").write_bytes(corpo)
    return tmp_path


def test_lf_e_crlf_dao_a_mesma_impressao(tmp_path):
    """O git converte LF<->CRLF nesta máquina: sem normalizar, todo checkout
    daria 'código mudou' sem ninguém ter mexido."""
    a = codigo.hash_estrategia("x", _pasta(tmp_path / "a", corpo=b"a = 1\nb = 2\n"))
    b = codigo.hash_estrategia("x", _pasta(tmp_path / "b", corpo=b"a = 1\r\nb = 2\r\n"))
    assert a == b and len(a) == 64


def test_mudar_uma_linha_da_estrategia_muda_a_impressao(tmp_path):
    a = codigo.hash_estrategia("x", _pasta(tmp_path / "a", corpo=b"a = 1\n"))
    b = codigo.hash_estrategia("x", _pasta(tmp_path / "b", corpo=b"a = 2\n"))
    assert a != b


def test_mudar_base_py_muda_a_impressao(tmp_path):
    """base.py é o contrato de toda estratégia: mexer nele muda o sinal."""
    a = codigo.hash_estrategia("x", _pasta(tmp_path / "a", base=b"B1\n"))
    b = codigo.hash_estrategia("x", _pasta(tmp_path / "b", base=b"B2\n"))
    assert a != b


def test_estrategia_inexistente_devolve_none(tmp_path):
    assert codigo.hash_estrategia("nao_existe", _pasta(tmp_path)) is None


def test_pasta_padrao_e_strategies_do_projeto():
    assert codigo.hash_estrategia("setup_cruzamento") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_codigo.py`
Expected: FAIL — `ImportError: cannot import name 'codigo'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/codigo.py
"""Impressão digital do código de uma estratégia.

O plano grava parâmetros, mas os números que ele promete vieram de uma
VERSÃO do código. Se o arquivo muda depois, o que roda ao vivo já não é o
que foi aprovado — e nada avisava (achado real: rompimento_abertura.py
editado com o plano #4 ativo, 30/09/2026).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import db_manager as db


def hash_estrategia(estrategia: str, pasta: Path | None = None) -> str | None:
    pasta = Path(pasta) if pasta else db.ROOT / "strategies"
    arquivo = pasta / f"{estrategia}.py"
    if not arquivo.exists():
        return None
    h = hashlib.sha256()
    # base.py entra junto: é o contrato de toda estratégia, e mudar ele
    # muda o sinal de todas
    for parte in (pasta / "base.py", arquivo):
        if parte.exists():
            # o git troca LF por CRLF nesta máquina; sem normalizar, todo
            # checkout acusaria "código mudou"
            h.update(parte.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_codigo.py`
Expected: 5 passed

- [ ] **Step 5: Mutation** — remova o `.replace(b"\r\n", b"\n")` → `test_lf_e_crlf...` falha; tire `base.py` da tupla → `test_mudar_base_py...` falha. Restaure.

- [ ] **Step 6: Commit** — `core/codigo.py`, `tests/test_codigo.py`; mensagem `feat(ao-vivo): impressao digital do codigo da estrategia`.

---

### Task 2: Schema novo e migração

**Files:**
- Modify: `core/schema.sql` (anexar no fim do arquivo)
- Create: `tests/_cadeia.py` (ajudantes de teste reusados nas tasks seguintes)
- Test: `tests/test_ao_vivo_schema.py`

**Interfaces:**
- Produces (tabelas/colunas): `contas`, `portfolio_membros`, `ao_vivo_eventos`, sequências `seq_conta_id`, `seq_ligacao_id`, `seq_evento_id`; `portfolios.ligado/conta_demo_id/conta_real_id`; `planos_operacao.variante_id/vale_a_partir/aposentado_em/codigo_hash`; `wfa_runs.codigo_hash`.
- Produces (teste): `tests/_cadeia.py` com `banco` (fixture), `mineracao(run_id, variante_id=None, strategy="rompimento_canal")`, `wfa(wfa_id, run_id, strategy="rompimento_canal")`, `campos_plano(**extra) -> dict`.

- [ ] **Step 1: Criar os ajudantes de teste**

```python
# tests/_cadeia.py
"""Ajudantes para montar mineração -> WFA -> plano direto no banco de teste.

Os testes da tela Ao vivo testam a CADEIA (quem protege quem, quem vale
quando), não o conteúdo de uma mineração ou de um WFA.
"""
from __future__ import annotations

import pytest

from core import db_manager as db


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def mineracao(run_id, variante_id=None, strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, "WIN$N", strategy, "2026-01-01", 10, "concluida",
             variante_id])


def wfa(wfa_id, run_id, strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
                    "VALUES (?,?,?,?)", [wfa_id, run_id, "WIN$N", strategy])


def campos_plano(**extra) -> dict:
    base = dict(
        wfa_id=1, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={"periodo_canal": 78}, profile={"contratos": 1},
        capital=100_000.0, contratos=1, risco_pedido_pct=1.0,
        risco_efetivo_pct=0.9, perda_referencia=300.0, de_onde="teste",
        margem=None, uso_margem_pct=50.0, camada4_travada=True,
        disjuntor={}, expectativa={}, reotimizacao={}, definicoes={},
        regua={})
    base.update(extra)
    return base
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ao_vivo_schema.py
"""Schema da tela Ao vivo e a migração dos portfólios que já existem."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from tests._cadeia import banco, mineracao, wfa  # noqa: E402,F401


def _q(sql, args=()):
    with db.connect(read_only=True) as con:
        return con.execute(sql, list(args)).fetchall()


def _reiniciar():
    with db.connect() as con:
        db.init_schema(con)


def _pv(portfolio_id, variante_id):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (?,?,?) ON CONFLICT DO NOTHING",
                    [portfolio_id, f"p{portfolio_id}", datetime(2026, 9, 1)])
        con.execute("INSERT INTO portfolio_variantes VALUES (?,?,?)",
                    [portfolio_id, variante_id, datetime(2026, 9, 2)])


def test_tabelas_e_colunas_novas_existem(banco):
    for t in ("contas", "portfolio_membros", "ao_vivo_eventos"):
        assert _q(f"SELECT count(*) FROM {t}") == [(0,)]
    cols = {r[0] for r in _q(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'planos_operacao'")}
    assert {"variante_id", "vale_a_partir", "aposentado_em",
            "codigo_hash"} <= cols
    assert "codigo_hash" in {r[0] for r in _q(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'wfa_runs'")}


def test_portfolio_novo_nasce_desligado(banco):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (1, 'x', now())")
    assert _q("SELECT ligado FROM portfolios") == [(False,)]


def test_migracao_vira_membro_no_papel_ligado(banco):
    _pv(1, 7)
    _reiniciar()
    r = _q("SELECT portfolio_id, variante_id, fase, ligada, fase_desde, "
           "removido_em FROM portfolio_membros")
    assert r == [(1, 7, "papel", True, datetime(2026, 9, 2), None)]


def test_migracao_rodar_duas_vezes_nao_duplica(banco):
    _pv(1, 7)
    _reiniciar()
    _reiniciar()
    assert _q("SELECT count(*) FROM portfolio_membros") == [(1,)]


def test_remover_e_reiniciar_nao_ressuscita(banco):
    """Sem contar os removidos, a variante tirada do portfólio voltaria a
    cada subida do app — portfolio_variantes nunca é apagada."""
    _pv(1, 7)
    _reiniciar()
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET removido_em = now()")
    _reiniciar()
    assert _q("SELECT count(*) FROM portfolio_membros") == [(1,)]


def test_migracao_preenche_variante_do_plano_pela_mineracao(banco):
    mineracao(5, variante_id=3)
    wfa(9, 5)
    with db.connect_write() as con:
        con.execute("INSERT INTO planos_operacao (plano_id, wfa_id, run_id, "
                    "estado) VALUES (1, 9, 5, 'ativo')")
    _reiniciar()
    assert _q("SELECT variante_id FROM planos_operacao") == [(3,)]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_schema.py`
Expected: FAIL — `Catalog Error: Table with name contas does not exist`

- [ ] **Step 4: Anexar ao fim de `core/schema.sql`**

```sql
-- ----------------------------------------------------------------- ao vivo
-- Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md.
-- O que está ligado, em que fase e para qual conta. Diferente do resto do
-- banco, isto NÃO se reconstrói a partir dos CSVs: é decisão do usuário.

-- conta nunca se apaga, só se arquiva: as ordens da parte 4 vão apontar
-- para ela. Nome único entre as não arquivadas é checado em código (o
-- DuckDB não tem UNIQUE parcial).
CREATE SEQUENCE IF NOT EXISTS seq_conta_id START 1;
CREATE TABLE IF NOT EXISTS contas (
    conta_id         BIGINT PRIMARY KEY,
    nome             VARCHAR NOT NULL,
    tipo             VARCHAR NOT NULL,     -- 'demo' | 'real'
    limite_perda_dia DOUBLE,               -- R$, opcional (mesa proprietária)
    criado_em        TIMESTAMP NOT NULL,
    arquivada_em     TIMESTAMP
);

ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS ligado BOOLEAN DEFAULT false;
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS conta_demo_id BIGINT;
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS conta_real_id BIGINT;

-- substitui portfolio_variantes: a chave composta de lá não deixa uma
-- variante voltar ao portfólio sem apagar o histórico, e a parte 4 precisa
-- de um número por ligação para etiquetar a ordem no MT5
CREATE SEQUENCE IF NOT EXISTS seq_ligacao_id START 1;
CREATE TABLE IF NOT EXISTS portfolio_membros (
    ligacao_id         BIGINT PRIMARY KEY,
    portfolio_id       BIGINT NOT NULL,
    variante_id        BIGINT NOT NULL,
    adicionado_em      TIMESTAMP NOT NULL,
    removido_em        TIMESTAMP,          -- remoção só marca, nunca apaga
    fase               VARCHAR NOT NULL,   -- 'papel'|'demo'|'real_minimo'|'real'
    fase_desde         TIMESTAMP NOT NULL,
    ligada             BOOLEAN NOT NULL,
    desligada_por      VARCHAR,            -- 'usuario' | 'disjuntor'
    desligada_em       TIMESTAMP,
    desligada_plano_id BIGINT              -- plano em vigor ao desligar (informativo)
);

-- diário: SÓ INSERÇÃO. Nenhum código faz UPDATE/DELETE aqui (há teste que
-- varre o fonte). É a única informação que não se recria depois.
CREATE SEQUENCE IF NOT EXISTS seq_evento_id START 1;
CREATE TABLE IF NOT EXISTS ao_vivo_eventos (
    evento_id     BIGINT PRIMARY KEY,
    quando        TIMESTAMP NOT NULL,
    tipo          VARCHAR NOT NULL,
    origem        VARCHAR NOT NULL,     -- 'usuario' | 'disjuntor' | 'sistema'
    portfolio_id  BIGINT,
    ligacao_id    BIGINT,
    variante_id   BIGINT,
    conta_id      BIGINT,
    plano_id      BIGINT,
    de            VARCHAR,
    para          VARCHAR,
    motivo        VARCHAR
);

-- o plano sabe de que variante é SEM depender da mineração (retrato): a
-- mineração pode ser apagada, o histórico da variante não
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS variante_id BIGINT;
-- vigência: o plano novo só vale no próximo pregão, e o antigo vale até lá
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS vale_a_partir DATE;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS aposentado_em DATE;
-- impressão digital do código que gerou os números (ver core/codigo.py)
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS codigo_hash VARCHAR;
ALTER TABLE wfa_runs        ADD COLUMN IF NOT EXISTS codigo_hash VARCHAR;

-- migração (roda a cada subida, idempotente): cada portfolio_variantes
-- vira membro no papel, ligado — SÓ se não existe membro nenhum para o
-- par, REMOVIDO OU NÃO. Contar só os ativos ressuscitaria a variante
-- removida a cada reinício.
INSERT INTO portfolio_membros (ligacao_id, portfolio_id, variante_id,
    adicionado_em, fase, fase_desde, ligada)
SELECT nextval('seq_ligacao_id'), pv.portfolio_id, pv.variante_id,
       pv.adicionado_em, 'papel', pv.adicionado_em, true
FROM portfolio_variantes pv
WHERE NOT EXISTS (SELECT 1 FROM portfolio_membros m
                  WHERE m.portfolio_id = pv.portfolio_id
                    AND m.variante_id = pv.variante_id);

UPDATE planos_operacao SET variante_id = (
    SELECT m.variante_id FROM mining_runs m
    WHERE m.run_id = planos_operacao.run_id)
WHERE variante_id IS NULL;
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_schema.py`
Expected: 6 passed. Depois a suíte inteira: nenhuma regressão (o schema só cresce).

- [ ] **Step 6: Mutation** — troque `WHERE NOT EXISTS (... m.variante_id = pv.variante_id)` por `... AND m.removido_em IS NULL)` → `test_remover_e_reiniciar...` falha. Restaure.

- [ ] **Step 7: Commit** — `core/schema.sql`, `tests/_cadeia.py`, `tests/test_ao_vivo_schema.py`; mensagem `feat(ao-vivo): schema de contas, ligacoes, diario e vigencia do plano`.

---

### Task 3: Diário de eventos

**Files:**
- Create: `core/diario.py`
- Test: `tests/test_diario.py`

**Interfaces:**
- Produces: `diario.TIPOS: frozenset[str]`, `diario.ORIGENS: frozenset[str]`,
  `diario.registrar(con, tipo, origem, *, portfolio_id=None, ligacao_id=None, variante_id=None, conta_id=None, plano_id=None, de=None, para=None, motivo=None, quando=None) -> int`,
  `diario.eventos(*, tipo=None, portfolio_id=None, ligacao_id=None, variante_id=None, conta_id=None, plano_id=None, motivo=None) -> list[dict]` (ordem de `evento_id`; chaves = colunas da tabela).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diario.py
"""O diário da tela Ao vivo: só recebe linhas novas, nunca apaga."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401

RAIZ = Path(__file__).resolve().parent.parent


def test_registrar_e_ler(banco):
    with db.connect_write() as con, db.transacao(con):
        eid = diario.registrar(con, "conta_criada", "usuario", conta_id=4,
                               para="Demo XP")
    [e] = diario.eventos(conta_id=4)
    assert e["evento_id"] == eid and e["tipo"] == "conta_criada"
    assert e["origem"] == "usuario" and e["para"] == "Demo XP"
    assert e["quando"] is not None


def test_filtros(banco):
    with db.connect_write() as con, db.transacao(con):
        diario.registrar(con, "membro_ligado", "usuario", ligacao_id=1)
        diario.registrar(con, "membro_desligado", "disjuntor", ligacao_id=1)
        diario.registrar(con, "membro_ligado", "usuario", ligacao_id=2)
    assert [e["tipo"] for e in diario.eventos(ligacao_id=1)] == [
        "membro_ligado", "membro_desligado"]
    assert len(diario.eventos(tipo="membro_ligado")) == 2


@pytest.mark.parametrize("tipo,origem", [("inventado", "usuario"),
                                         ("conta_criada", "robo")])
def test_tipo_ou_origem_desconhecidos_sao_recusados(banco, tipo, origem):
    with db.connect_write() as con, db.transacao(con):
        with pytest.raises(ValueError):
            diario.registrar(con, tipo, origem)


def test_nenhum_codigo_altera_ou_apaga_o_diario():
    """A garantia de 'só inserção' é esta varredura: qualquer UPDATE ou
    DELETE no diário, em core/ ou ui/, quebra aqui."""
    padrao = re.compile(r"(UPDATE|DELETE\s+FROM)\s+ao_vivo_eventos", re.I)
    achados = [str(p) for pasta in ("core", "ui")
               for p in (RAIZ / pasta).rglob("*.py")
               if padrao.search(p.read_text(encoding="utf-8"))]
    assert achados == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_diario.py`
Expected: FAIL — `ImportError: cannot import name 'diario'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/diario.py
"""Diário da tela Ao vivo: o que foi ligado, desligado, trocado e por quem.

Só inserção. Estado atual qualquer tabela guarda; o que não se recria
depois é a SEQUÊNCIA — por que a estratégia não operou no dia 12, quem
subiu de fase e quando, qual plano valia. `registrar` exige a conexão do
chamador para o evento cair na MESMA transação da mudança: ou os dois
ficam, ou nenhum.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db

TIPOS = frozenset({
    "portfolio_ligado", "portfolio_desligado", "portfolio_conta_mudou",
    "membro_adicionado", "membro_removido", "membro_ligado",
    "membro_desligado", "fase_mudou",
    "conta_criada", "conta_editada", "conta_arquivada",
    "plano_gravado", "plano_aposentado", "plano_vinculado",
    "variante_renomeada",
})
ORIGENS = frozenset({"usuario", "disjuntor", "sistema"})

_COLUNAS = ("evento_id", "quando", "tipo", "origem", "portfolio_id",
            "ligacao_id", "variante_id", "conta_id", "plano_id", "de",
            "para", "motivo")
_FILTROS = ("tipo", "portfolio_id", "ligacao_id", "variante_id", "conta_id",
            "plano_id", "motivo")


def registrar(con, tipo, origem, *, portfolio_id=None, ligacao_id=None,
              variante_id=None, conta_id=None, plano_id=None, de=None,
              para=None, motivo=None, quando=None) -> int:
    if tipo not in TIPOS:
        raise ValueError(f"tipo de evento desconhecido: {tipo}")
    if origem not in ORIGENS:
        raise ValueError(f"origem de evento desconhecida: {origem}")
    eid = con.execute("SELECT nextval('seq_evento_id')").fetchone()[0]
    con.execute(
        f"INSERT INTO ao_vivo_eventos ({', '.join(_COLUNAS)}) "
        f"VALUES ({', '.join('?' * len(_COLUNAS))})",
        [eid, quando or datetime.now(), tipo, origem, portfolio_id,
         ligacao_id, variante_id, conta_id, plano_id,
         None if de is None else str(de), None if para is None else str(para),
         motivo])
    return int(eid)


def eventos(**filtros) -> list[dict]:
    desconhecidos = set(filtros) - set(_FILTROS)
    if desconhecidos:
        raise ValueError(f"filtro desconhecido: {sorted(desconhecidos)}")
    ativos = {k: v for k, v in filtros.items() if v is not None}
    onde = " AND ".join(f"{k} = ?" for k in ativos)
    sql = (f"SELECT {', '.join(_COLUNAS)} FROM ao_vivo_eventos"
           + (f" WHERE {onde}" if onde else "") + " ORDER BY evento_id")
    with db.connect(read_only=True) as con:
        return [dict(zip(_COLUNAS, r))
                for r in con.execute(sql, list(ativos.values())).fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_diario.py`
Expected: 5 passed

- [ ] **Step 5: Mutation** — remova a checagem de `TIPOS` → teste parametrizado falha; acrescente ao fim de `core/diario.py` a função `def _limpar(con): con.execute("DELETE FROM ao_vivo_eventos")` → `test_nenhum_codigo_altera...` falha. Restaure.

- [ ] **Step 6: Commit** — `core/diario.py`, `tests/test_diario.py`; mensagem `feat(ao-vivo): diario de eventos so de insercao`.

---

### Task 4: Gravar plano — variante, vigência, impressão digital e eventos

**Files:**
- Modify: `core/plano.py` (`_COLUNAS`, `salvar`, nova `proximo_dia_util`, `montar`)
- Test: `tests/test_plano_vigencia.py`

**Interfaces:**
- Consumes: `diario.registrar` (Task 3); colunas da Task 2.
- Produces:
  - `plano.proximo_dia_util(d: date) -> date`
  - `plano.salvar(..., codigo_hash=None, agora: datetime | None = None) -> int` — grava `variante_id` (de `mining_runs` pelo `run_id`), `vale_a_partir`, `codigo_hash`; tira de vigor na data `vale_a_partir` todo plano da mesma variante (ou do mesmo `wfa_id`, se sem variante) que ainda estaria em vigor; eventos `plano_gravado` (origem `usuario`) e `plano_aposentado` (origem `sistema`, `motivo = "substituído pelo plano #<novo>"`).
  - `plano.detalhes/listar` passam a devolver as chaves `variante_id`, `vale_a_partir`, `aposentado_em`, `codigo_hash`.
  - `plano.montar(...)` inclui `"codigo_hash": d.get("codigo_hash")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plano_vigencia.py
"""Gravar plano: o novo só vale no próximo pregão, o antigo vale até lá, e
reotimizar com mineração nova não deixa dois planos ativos na variante."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import diario, plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = datetime(2026, 10, 1, 14, 0)


@pytest.mark.parametrize("dia,esperado", [
    (date(2026, 9, 30), date(2026, 10, 1)),   # qua -> qui
    (date(2026, 10, 1), date(2026, 10, 2)),   # qui -> sex
    (date(2026, 10, 2), date(2026, 10, 5)),   # sex -> seg
    (date(2026, 10, 3), date(2026, 10, 5)),   # sáb -> seg
    (date(2026, 10, 4), date(2026, 10, 5)),   # dom -> seg
])
def test_proximo_dia_util(dia, esperado):
    assert plano.proximo_dia_util(dia) == esperado


def _var(nome="v"):
    return variantes.criar(nome, "rompimento_canal")


def test_grava_variante_vigencia_e_impressao(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(codigo_hash="abc"), agora=QUI)
    d = plano.detalhes(pid)
    assert d["variante_id"] == v
    assert d["vale_a_partir"] == date(2026, 10, 2)
    assert d["aposentado_em"] is None and d["codigo_hash"] == "abc"
    assert d["estado"] == "ativo"


def test_reotimizar_com_mineracao_nova_aposenta_o_da_variante(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    velho = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    mineracao(2, variante_id=v)
    wfa(2, 2)
    novo = plano.salvar(**campos_plano(wfa_id=2, run_id=2), agora=QUI)
    d = plano.detalhes(velho)
    assert d["estado"] == "aposentado"
    assert d["aposentado_em"] == date(2026, 10, 2)   # vale até o novo valer
    assert plano.detalhes(novo)["estado"] == "ativo"


def test_nao_toca_plano_de_outra_variante(banco):
    a, b = _var("a"), _var("b")
    mineracao(1, variante_id=a)
    wfa(1, 1)
    mineracao(2, variante_id=b)
    wfa(2, 2)
    pa = plano.salvar(**campos_plano(), agora=QUI)
    plano.salvar(**campos_plano(wfa_id=2, run_id=2), agora=QUI)
    assert plano.detalhes(pa)["estado"] == "ativo"


def test_sem_variante_mantem_a_regra_por_wfa(banco):
    wfa(1, 1)   # sem mineração com variante
    wfa(2, 2)
    p1 = plano.salvar(**campos_plano(), agora=QUI)
    p2 = plano.salvar(**campos_plano(wfa_id=2, run_id=2), agora=QUI)
    p3 = plano.salvar(**campos_plano(), agora=QUI)
    assert plano.detalhes(p1)["estado"] == "aposentado"
    assert plano.detalhes(p2)["estado"] == "ativo"
    assert plano.detalhes(p3)["estado"] == "ativo"


def test_eventos_de_gravar_e_aposentar(banco):
    v = _var()
    mineracao(1, variante_id=v)
    wfa(1, 1)
    velho = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    novo = plano.salvar(**campos_plano(), agora=QUI)
    [g] = diario.eventos(tipo="plano_gravado", plano_id=novo)
    assert g["origem"] == "usuario" and g["variante_id"] == v
    [a] = diario.eventos(tipo="plano_aposentado", plano_id=velho)
    assert a["origem"] == "sistema"
    assert a["motivo"] == f"substituído pelo plano #{novo}"


def test_montar_leva_a_impressao_do_wfa(banco):
    # `banco` é obrigatório: montar lê o banco (retrato_da_base), e sem a
    # fixture leria data/database.duckdb
    campos = plano.montar(1, {"codigo_hash": "h1", "symbol": "WIN$N"}, {}, {},
                          {}, {}, {})
    assert campos["codigo_hash"] == "h1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_plano_vigencia.py`
Expected: FAIL — `AttributeError: module 'core.plano' has no attribute 'proximo_dia_util'`

- [ ] **Step 3: Implementar em `core/plano.py`**

Imports: acrescente `from . import diario`.

`_COLUNAS` ganha, no fim: `"variante_id", "vale_a_partir", "aposentado_em", "codigo_hash"`.

Nova função (acima de `salvar`):

```python
def proximo_dia_util(d: date) -> date:
    """O próximo dia de semana depois de `d`. Feriado não precisa de
    calendário: sem pregão, o plano simplesmente começa no seguinte."""
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d
```

`salvar` inteiro:

```python
def salvar(*, wfa_id, run_id, symbol, strategy, nome, params, profile,
           capital, contratos, risco_pedido_pct, risco_efetivo_pct,
           perda_referencia, de_onde, margem, uso_margem_pct,
           camada4_travada, disjuntor, expectativa, reotimizacao,
           definicoes, regua, motor_versao=None, base_ate=None,
           base_barras=None, capital_livre=None, reotimizar_em=None,
           codigo_hash=None, agora: datetime | None = None) -> int:
    """Grava um plano e devolve o id.

    Nunca substitui: dois planos do mesmo walk-forward com risco diferente
    são duas decisões, e as duas ficam. O novo só vale a partir do próximo
    pregão — nunca se troca de parâmetro no meio do dia — e o anterior
    continua valendo até lá.
    """
    agora = agora or datetime.now()
    vale = proximo_dia_util(agora.date())
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT variante_id FROM mining_runs WHERE run_id = ?",
                        [run_id]).fetchone()
        variante_id = r[0] if r else None
        # um plano ativo por VARIANTE: reotimizar com mineração nova deixava
        # o antigo ativo, e se o novo sumisse o antigo voltava a valer
        # sozinho. Sem variante, vale a regra antiga (por walk-forward).
        alvo, arg = (("variante_id = ?", variante_id) if variante_id is not None
                     else ("wfa_id = ?", wfa_id))
        saem = [x[0] for x in con.execute(
            f"SELECT plano_id FROM planos_operacao WHERE {alvo} "
            "AND (estado = 'ativo' OR aposentado_em > ?)", [arg, vale]
        ).fetchall()]
        if saem:
            con.execute(
                "UPDATE planos_operacao SET estado = 'aposentado', "
                "aposentado_em = ? "
                f"WHERE plano_id IN ({', '.join('?' * len(saem))})",
                [vale, *saem])
        pid = con.execute("SELECT nextval('seq_plano_id')").fetchone()[0]
        con.execute(
            f"INSERT INTO planos_operacao ({', '.join(_COLUNAS)}) "
            f"VALUES ({', '.join('?' * len(_COLUNAS))})",
            [pid, wfa_id, run_id, symbol, strategy, nome or None, agora,
             _js(params), _js(profile),
             float(capital) if capital is not None else None,
             int(contratos) if contratos is not None else None,
             risco_pedido_pct, risco_efetivo_pct, perda_referencia, de_onde,
             float(margem) if margem is not None else None,
             uso_margem_pct,
             None if camada4_travada is None else bool(camada4_travada),
             _js(disjuntor), _js(expectativa),
             _js(reotimizacao), _js(definicoes),
             _js(regua), "ativo", motor_versao, base_ate,
             base_barras, capital_livre, reotimizar_em,
             variante_id, vale, None, codigo_hash])
        diario.registrar(con, "plano_gravado", "usuario", plano_id=pid,
                         variante_id=variante_id,
                         motivo=f"vale a partir de {vale:%d/%m/%Y}")
        for antigo in saem:
            diario.registrar(con, "plano_aposentado", "sistema",
                             plano_id=antigo, variante_id=variante_id,
                             de="ativo", para="aposentado",
                             motivo=f"substituído pelo plano #{pid}")
    return int(pid)
```

Em `montar`, no bloco `# reprodutibilidade`, acrescente:

```python
        "codigo_hash": d.get("codigo_hash"),
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_plano_vigencia.py tests/test_plano.py tests/test_portfolio.py tests/test_callbacks_candidata.py`
Expected: todos passam (os antigos continuam: sem variante a regra por `wfa_id` é a mesma).

- [ ] **Step 5: Mutation** — (a) troque `aposentado_em = ?` por `aposentado_em = CURRENT_DATE` → `test_reotimizar...` falha; (b) force `alvo = ("wfa_id = ?", wfa_id)` sempre → `test_reotimizar...` falha; (c) `vale = agora.date()` → `test_grava_variante...` falha. Restaure.

- [ ] **Step 6: Commit** — `core/plano.py`, `tests/test_plano_vigencia.py`; mensagem `feat(ao-vivo): plano grava variante, vigencia e impressao digital`.

---

### Task 5: Plano em vigor

**Files:**
- Modify: `core/variantes.py` (nova função)
- Test: `tests/test_plano_em_vigor.py`

**Interfaces:**
- Consumes: `plano.salvar(..., agora=)` (Task 4).
- Produces: `variantes.plano_em_vigor(variante_id: int, dia: date | None = None, con=None) -> dict | None` → `{"plano_id", "wfa_id", "run_id"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plano_em_vigor.py
"""Qual plano vale NAQUELE pregão — que pode não ser o último gravado."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI, SEX, SEG = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)


def _variante_com_dois_planos():
    v = variantes.criar("v", "rompimento_canal")
    mineracao(1, variante_id=v)
    wfa(1, 1)
    p1 = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    p2 = plano.salvar(**campos_plano(), agora=datetime(2026, 10, 1, 14))
    return v, p1, p2


def _vigor(v, dia):
    r = variantes.plano_em_vigor(v, dia)
    return r and r["plano_id"]


def test_antes_de_valer_devolve_o_anterior(banco):
    v, p1, p2 = _variante_com_dois_planos()
    assert _vigor(v, QUI) == p1


def test_no_dia_devolve_o_novo(banco):
    v, p1, p2 = _variante_com_dois_planos()
    assert _vigor(v, SEX) == p2 and _vigor(v, SEG) == p2


def test_dois_no_mesmo_dia_o_do_meio_nunca_vale(banco):
    v, p1, p2 = _variante_com_dois_planos()
    p3 = plano.salvar(**campos_plano(), agora=datetime(2026, 10, 1, 16))
    assert _vigor(v, QUI) == p1
    assert _vigor(v, SEX) == p3


def test_sem_plano_devolve_none(banco):
    v = variantes.criar("v", "rompimento_canal")
    assert variantes.plano_em_vigor(v, QUI) is None


def test_plano_antigo_sem_datas_e_o_desempate_por_id(banco):
    """Planos anteriores a esta versão: vigência nula = vale desde sempre;
    dois ativos (caso antigo) desempatam pelo maior id."""
    v = variantes.criar("v", "rompimento_canal")
    with db.connect_write() as con:
        con.execute("INSERT INTO planos_operacao (plano_id, estado, "
                    "variante_id) VALUES (1,'ativo',?), (2,'ativo',?), "
                    "(3,'aposentado',?)", [v, v, v])
    assert _vigor(v, QUI) == 2


def test_aceita_conexao_do_chamador(banco):
    v, p1, p2 = _variante_com_dois_planos()
    with db.connect_write() as con, db.transacao(con):
        assert variantes.plano_em_vigor(v, SEX, con=con)["plano_id"] == p2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_plano_em_vigor.py`
Expected: FAIL — `AttributeError: ... 'plano_em_vigor'`

- [ ] **Step 3: Implementar em `core/variantes.py`** (imports: `from datetime import date, datetime`)

```python
def plano_em_vigor(variante_id: int, dia: date | None = None,
                   con=None) -> dict | None:
    """O plano que vale naquele pregão (padrão: hoje).

    Diferente de `plano_ativo` (o mais recente gravado, que a análise de
    portfólio usa): o plano novo só vale a partir do próximo pregão, e o
    anterior continua em vigor até lá. Lê `planos_operacao.variante_id`,
    nunca a mineração — ela pode ter sido apagada. `con` para quem chama de
    dentro de uma transação aberta.
    """
    dia = dia or date.today()
    sql = """
        SELECT plano_id, wfa_id, run_id FROM planos_operacao
        WHERE variante_id = ?
          AND (vale_a_partir IS NULL OR vale_a_partir <= ?)
          AND ((estado = 'ativo' AND aposentado_em IS NULL)
               OR aposentado_em > ?)
        ORDER BY plano_id DESC LIMIT 1
    """
    args = [variante_id, dia, dia]
    if con is not None:
        r = con.execute(sql, args).fetchone()
    else:
        with db.connect(read_only=True) as c:
            r = c.execute(sql, args).fetchone()
    return {"plano_id": r[0], "wfa_id": r[1], "run_id": r[2]} if r else None
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_plano_em_vigor.py` → 6 passed.

- [ ] **Step 5: Mutation** — `vale_a_partir <= ?` → `< ?` (falha `test_no_dia...`); `aposentado_em > ?` → `>= ?` (falha `test_antes_de_valer...`); `DESC` → `ASC` (falha `test_plano_antigo...`). Restaure.

- [ ] **Step 6: Commit** — `core/variantes.py`, `tests/test_plano_em_vigor.py`; mensagem `feat(ao-vivo): plano_em_vigor por data`.

---

### Task 6: Aposentar à mão, proteção e excluir plano

**Files:**
- Modify: `core/plano.py` (`aposentar`, `excluir`, nova `motivo_protecao`)
- Test: `tests/test_protecao.py` (criado aqui, ampliado na Task 7)

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - `plano.motivo_protecao(con, plano_ids: list[int], hoje: date | None = None) -> str | None` — primeiro motivo encontrado, na ordem: (a) ativo, (b) aposentado ainda em vigor (`aposentado_em > hoje`), (c) variante com ligação não removida em algum portfólio.
  - `plano.aposentar(plano_id, agora: datetime | None = None) -> bool` — `aposentado_em = min(atual, proximo_dia_util(hoje))`, estado `aposentado`, evento `plano_aposentado` origem `usuario`.
  - `plano.excluir(plano_id) -> bool` — `ValueError` se protegido.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_protecao.py
"""Nada que opera ou pode operar é apagado ou aposentado em silêncio."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario, plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = datetime(2026, 10, 1, 14, 0)


def _cadeia(run_id=1, wfa_id=1, com_variante=True, nome="v"):
    v = variantes.criar(nome, "rompimento_canal") if com_variante else None
    mineracao(run_id, variante_id=v)
    wfa(wfa_id, run_id)
    pid = plano.salvar(**campos_plano(wfa_id=wfa_id, run_id=run_id),
                       agora=datetime(2026, 9, 1, 10))
    return v, pid


def _membro(variante_id, removido=False):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (1, 'pf-teste', now()) ON CONFLICT DO NOTHING")
        con.execute(
            "INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
            "variante_id, adicionado_em, removido_em, fase, fase_desde, "
            "ligada) VALUES (nextval('seq_ligacao_id'), 1, ?, now(), ?, "
            "'papel', now(), false)",
            [variante_id, datetime(2026, 9, 5) if removido else None])


def _motivo(pids, hoje=date(2026, 10, 1)):
    with db.connect(read_only=True) as con:
        return plano.motivo_protecao(con, pids, hoje)


def test_ativo_e_protegido(banco):
    _, pid = _cadeia()
    assert "está ativo" in _motivo([pid])


def test_aposentado_ainda_em_vigor_e_protegido(banco):
    _, pid = _cadeia()
    plano.aposentar(pid, agora=QUI)          # sai de vigor na sexta
    assert "até" in _motivo([pid], hoje=date(2026, 10, 1))
    assert _motivo([pid], hoje=date(2026, 10, 2)) is None


def test_variante_em_portfolio_protege_mesmo_aposentado(banco):
    v, pid = _cadeia()
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    _membro(v)
    assert "pf-teste" in _motivo([pid])


def test_membro_removido_nao_protege(banco):
    v, pid = _cadeia()
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    _membro(v, removido=True)
    assert _motivo([pid]) is None


def test_lista_vazia_nao_protege(banco):
    assert _motivo([]) is None


def test_aposentar_vale_no_proximo_pregao_e_registra(banco):
    _, pid = _cadeia()
    assert plano.aposentar(pid, agora=QUI) is True
    d = plano.detalhes(pid)
    assert d["estado"] == "aposentado" and d["aposentado_em"] == date(2026, 10, 2)
    [e] = diario.eventos(tipo="plano_aposentado", plano_id=pid)
    assert e["origem"] == "usuario"


def test_aposentar_nao_estica_vigencia_ja_marcada(banco):
    """Aposentar o que já sai de vigor antes não pode prolongá-lo: min()."""
    _, pid = _cadeia()
    plano.aposentar(pid, agora=QUI)                       # sai na sexta
    plano.aposentar(pid, agora=datetime(2026, 10, 7, 10))  # seria quinta que vem
    assert plano.detalhes(pid)["aposentado_em"] == date(2026, 10, 2)


def test_aposentar_o_novo_antes_de_valer_nao_ressuscita_o_velho(banco):
    v, velho = _cadeia()
    novo = plano.salvar(**campos_plano(), agora=QUI)      # vale sexta
    plano.aposentar(novo, agora=QUI)                      # também sexta
    assert variantes.plano_em_vigor(v, date(2026, 10, 1))["plano_id"] == velho
    assert variantes.plano_em_vigor(v, date(2026, 10, 2)) is None


def test_excluir_plano_protegido_recusa_e_nao_apaga(banco):
    _, pid = _cadeia()
    with pytest.raises(ValueError, match="está ativo"):
        plano.excluir(pid)
    assert plano.detalhes(pid) is not None


def test_excluir_plano_livre_apaga(banco):
    _, pid = _cadeia(com_variante=False)
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    assert plano.excluir(pid) is True and plano.detalhes(pid) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_protecao.py`
Expected: FAIL — `AttributeError: ... 'motivo_protecao'`

- [ ] **Step 3: Implementar em `core/plano.py`** (substitui `aposentar` e `excluir`)

```python
def motivo_protecao(con, plano_ids, hoje: date | None = None) -> str | None:
    """Por que estes planos não podem sumir — ou None se podem.

    Protegido é o que opera ou pode operar: (a) ativo; (b) aposentado mas
    ainda em vigor (o pregão de hoje pode estar usando); (c) de uma
    variante que está em algum portfólio, ligado ou não. Recebe `con`
    porque é chamada de dentro da transação que ia apagar.
    """
    ids = [int(p) for p in plano_ids or []]
    if not ids:
        return None
    hoje = hoje or date.today()
    linhas = con.execute(
        "SELECT p.plano_id, p.estado, p.aposentado_em, ev.nome, pf.nome "
        "FROM planos_operacao p "
        "LEFT JOIN estrategia_variantes ev ON ev.variante_id = p.variante_id "
        "LEFT JOIN portfolio_membros pm ON pm.variante_id = p.variante_id "
        "     AND pm.removido_em IS NULL "
        "LEFT JOIN portfolios pf ON pf.portfolio_id = pm.portfolio_id "
        f"WHERE p.plano_id IN ({', '.join('?' * len(ids))}) "
        "ORDER BY p.plano_id", ids).fetchall()
    for pid, estado, _apos, variante, _pf in linhas:
        if estado == "ativo":
            return (f"o plano #{pid} está ativo"
                    + (f" na variante {variante}" if variante else ""))
    for pid, _estado, apos, _var, _pf in linhas:
        if apos is not None and apos > hoje:
            return f"o plano #{pid} ainda vale até {apos - timedelta(days=1):%d/%m}"
    for pid, _estado, _apos, variante, pf in linhas:
        if pf is not None:
            return (f"o plano #{pid} é da variante {variante}, que está no "
                    f"portfólio {pf}")
    return None


def aposentar(plano_id: int, agora: datetime | None = None) -> bool:
    """Tira o plano de operação sem apagá-lo — a partir do PRÓXIMO pregão.

    O pregão em curso termina com o plano com que começou; para parar
    agora, o caminho é o interruptor da ligação. Se já estava marcado para
    sair antes, fica a data mais cedo: aposentar de novo não prolonga.
    """
    agora = agora or datetime.now()
    data = proximo_dia_util(agora.date())
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT estado, aposentado_em, variante_id "
                        "FROM planos_operacao WHERE plano_id = ?",
                        [plano_id]).fetchone()
        if r is None:
            return False
        estado, atual, variante_id = r
        nova = min(atual, data) if atual is not None else data
        con.execute("UPDATE planos_operacao SET estado = 'aposentado', "
                    "aposentado_em = ? WHERE plano_id = ?", [nova, plano_id])
        diario.registrar(con, "plano_aposentado", "usuario", plano_id=plano_id,
                         variante_id=variante_id, de=estado, para="aposentado",
                         motivo=f"sai de vigor em {nova:%d/%m/%Y}")
    return True


def excluir(plano_id: int) -> bool:
    with db.connect_write() as con, db.transacao(con):
        if con.execute("SELECT 1 FROM planos_operacao WHERE plano_id = ?",
                       [plano_id]).fetchone() is None:
            return False
        motivo = motivo_protecao(con, [plano_id])
        if motivo:
            raise ValueError(f"o plano #{plano_id} não pode ser apagado: {motivo}")
        con.execute("DELETE FROM planos_operacao WHERE plano_id = ?",
                    [plano_id])
    return True
```

> `test_aposentar_nao_apaga` e `test_excluir_plano_apaga_so_ele` em `tests/test_plano.py` mudam: o primeiro continua passando; o segundo agora recusa (os dois planos estão ativos/em vigor). Reescreva-o assim:

```python
def test_excluir_plano_apaga_so_ele(banco):
    """Só o que não opera nem pode operar pode ser apagado — aqui, planos
    sem variante e já fora de vigor."""
    from datetime import datetime
    _wfa_no_banco()
    a = plano.salvar(**_campos(), agora=datetime(2026, 9, 1, 10))
    b = plano.salvar(**_campos(), agora=datetime(2026, 9, 2, 10))
    plano.aposentar(b, agora=datetime(2026, 9, 3, 10))
    assert plano.excluir(a) is True
    assert [p["plano_id"] for p in plano.listar()] == [b]
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_protecao.py tests/test_plano.py` → tudo passa (os testes de cascata de `test_plano.py` continuam verdes porque `excluir_salva`/`wfa_store.excluir` ainda não checam proteção; a Task 7 os reescreve).

- [ ] **Step 5: Mutation** — (a) tire o bloco (b) de `motivo_protecao` → `test_aposentado_ainda_em_vigor...` falha; (b) tire `AND pm.removido_em IS NULL` → `test_membro_removido...` falha; (c) em `aposentar`, `nova = data` sempre → `test_aposentar_nao_estica...` falha. Restaure.

- [ ] **Step 6: Commit** — `core/plano.py`, `tests/test_protecao.py`, `tests/test_plano.py`; mensagem `feat(ao-vivo): aposentar vale no proximo pregao e protecao de plano`.

---

### Task 7: Apagar mineração e walk-forward respeita a proteção

**Files:**
- Modify: `core/optimizer.py` (`excluir_salva`), `core/wfa_store.py` (`excluir`)
- Modify: `tests/test_plano.py` (os dois testes de cascata)
- Test: `tests/test_protecao.py` (acrescentar)

**Interfaces:**
- Consumes: `plano.motivo_protecao` (Task 6).
- Produces: `optimizer.excluir_salva(run_id)` e `wfa_store.excluir(wfa_id)` levantam `ValueError("a mineração #N não pode ser apagada: <motivo>")` / `("o walk-forward #N não pode ser apagado: <motivo>")` e **não apagam nada**; sem proteção, cascata como hoje.

- [ ] **Step 1: Acrescentar a `tests/test_protecao.py`**

```python
from core import optimizer, wfa_store  # noqa: E402


def _conta(tabela):
    with db.connect(read_only=True) as con:
        return con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]


def test_apagar_mineracao_com_plano_ativo_recusa_e_nao_apaga_nada(banco):
    _cadeia()
    with db.connect_write() as con:
        con.execute("INSERT INTO mining_trials (run_id, trial_id) VALUES (1, 1)")
    with pytest.raises(ValueError, match="mineração #1 não pode ser apagada"):
        optimizer.excluir_salva(1)
    assert [_conta(t) for t in ("mining_runs", "mining_trials", "wfa_runs",
                                "planos_operacao")] == [1, 1, 1, 1]


def test_apagar_wfa_com_plano_ativo_recusa(banco):
    _cadeia()
    with pytest.raises(ValueError, match="walk-forward #1 não pode ser apagado"):
        wfa_store.excluir(1)
    assert _conta("wfa_runs") == 1


def test_mineracao_sem_plano_de_variante_em_portfolio_pode_ser_apagada(banco):
    """Minerações-lixo de uma variante em operação continuam apagáveis."""
    v, _ = _cadeia()
    _membro(v)
    mineracao(2, variante_id=v)          # outra mineração, sem WFA nem plano
    assert optimizer.excluir_salva(2) is True


def test_mineracao_sem_protecao_apaga_em_cascata(banco):
    _, pid = _cadeia(com_variante=False)
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))
    assert optimizer.excluir_salva(1) is True
    assert [_conta(t) for t in ("mining_runs", "wfa_runs",
                                "planos_operacao")] == [0, 0, 0]
```

E em `tests/test_plano.py` substitua `test_excluir_walk_forward_leva_os_planos_junto`, `test_excluir_mineracao_leva_os_planos_dos_walk_forwards_dela` e `test_excluir_mineracao_nao_leva_plano_de_outra` por:

```python
def _fora_de_vigor(pid):
    from datetime import datetime
    plano.aposentar(pid, agora=datetime(2026, 9, 2, 10))


def test_excluir_walk_forward_leva_os_planos_junto(banco):
    """Com o plano fora de vigor e sem portfólio, a cascata continua: sem
    ela, o plano apontaria para um walk-forward que não existe mais."""
    _wfa_no_banco()
    pid = plano.salvar(**_campos())
    _fora_de_vigor(pid)
    wfa_store.excluir(1)
    assert plano.detalhes(pid) is None


def test_excluir_mineracao_leva_os_planos_dos_walk_forwards_dela(banco):
    """Regra de 18/09/2026, revista em 30/09/2026: apagar mineração apaga
    tudo que nasceu dela — EXCETO plano que opera ou pode operar."""
    _wfa_no_banco(run_id=7, wfa_id=3)
    pid = plano.salvar(**_campos(wfa_id=3, run_id=7))
    _fora_de_vigor(pid)
    optimizer.excluir_salva(7)
    assert plano.detalhes(pid) is None and plano.listar() == []


def test_excluir_mineracao_nao_leva_plano_de_outra(banco):
    _wfa_no_banco(run_id=7, wfa_id=3)
    _wfa_no_banco(run_id=8, wfa_id=4)
    fica = plano.salvar(**_campos(wfa_id=4, run_id=8))
    sai = plano.salvar(**_campos(wfa_id=3, run_id=7))
    _fora_de_vigor(sai)
    optimizer.excluir_salva(7)
    assert [p["plano_id"] for p in plano.listar()] == [fica]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_protecao.py`
Expected: FAIL — `test_apagar_mineracao_com_plano_ativo...` (DID NOT RAISE)

- [ ] **Step 3: Implementar**

`core/optimizer.py` — imports: `from . import plano as _plano`. Em `excluir_salva`, logo depois de abrir a transação e **antes** do primeiro DELETE:

```python
    with db.connect_write() as con, db.transacao(con):
        # nada que opera ou pode operar sai daqui (spec Ao vivo §4.1):
        # a limpeza de minerações antigas derrubava o plano em operação
        ids = [r[0] for r in con.execute(
            "SELECT plano_id FROM planos_operacao WHERE run_id = ? OR wfa_id IN "
            "(SELECT wfa_id FROM wfa_runs WHERE run_id = ?)",
            [run_id, run_id]).fetchall()]
        motivo = _plano.motivo_protecao(con, ids)
        if motivo:
            raise ValueError(
                f"a mineração #{run_id} não pode ser apagada: {motivo}")
        con.execute("DELETE FROM mining_trials WHERE run_id = ?", [run_id])
        # ... resto igual ...
```

`core/wfa_store.py` — imports: `from . import plano as _plano`. `excluir`:

```python
def excluir(wfa_id: int) -> bool:
    with db.connect_write() as con, db.transacao(con):
        ids = [r[0] for r in con.execute(
            "SELECT plano_id FROM planos_operacao WHERE wfa_id = ?",
            [wfa_id]).fetchall()]
        motivo = _plano.motivo_protecao(con, ids)
        if motivo:
            raise ValueError(
                f"o walk-forward #{wfa_id} não pode ser apagado: {motivo}")
        con.execute("DELETE FROM wfa_trades WHERE wfa_id = ?", [wfa_id])
        # o plano de operação vai junto: sem isto ele fica apontando para um
        # walk-forward que não existe mais, e a tela mostraria plano sem
        # origem — o mesmo acidente dos trades órfãos, uma tabela adiante
        con.execute("DELETE FROM planos_operacao WHERE wfa_id = ?", [wfa_id])
        con.execute("DELETE FROM wfa_runs WHERE wfa_id = ?", [wfa_id])
    return True
```

Confira que não há import circular: `.venv/Scripts/python.exe -c "import core.optimizer, core.wfa_store, core.plano"`.

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_protecao.py tests/test_plano.py tests/test_salvar.py tests/test_wfa_store.py` → tudo passa.

- [ ] **Step 5: Mutation** — tire o `raise` em `excluir_salva` → `test_apagar_mineracao_com_plano_ativo...` falha; troque `run_id = ? OR wfa_id IN (...)` por só `run_id = ?` e confirme se algum teste pega (se não, acrescente um caso com plano cujo `run_id` difere mas o `wfa_id` pertence à mineração). Restaure.

- [ ] **Step 6: Commit** — `core/optimizer.py`, `core/wfa_store.py`, `tests/test_protecao.py`, `tests/test_plano.py`; mensagem `feat(ao-vivo): apagar mineracao/WFA recusa cadeia protegida`.

---

### Task 8: Regravar walk-forward não mexe em plano; impressão digital no WFA

**Files:**
- Modify: `core/wfa_store.py` (`salvar`, `listar`, `detalhes`)
- Modify: `tests/test_plano.py` (`test_regravar_o_walk_forward...`)
- Test: `tests/test_protecao.py` (acrescentar)

**Interfaces:**
- Produces: `wfa_store.salvar(..., codigo_hash=None)` grava a coluna; com chave repetida, antigo **com plano** fica e o novo entra ao lado; `listar()` acrescenta `" · tem plano"` ao rótulo quando há plano; `detalhes()` devolve `"codigo_hash"`.

- [ ] **Step 1: Test** — substitua `test_regravar_o_walk_forward_aposenta_o_plano_e_nao_o_perde` em `tests/test_plano.py` por:

```python
def test_regravar_o_walk_forward_com_plano_mantem_os_dois(banco):
    """Regravar o MESMO walk-forward substituía o registro e aposentava o
    plano ativo em silêncio (a estratégia saía do ar). Agora, se o antigo
    tem plano, ele fica e o novo entra ao lado; o plano não muda nada."""
    import numpy as np

    from core import wfa

    def passos():
        j = wfa.Janela(1, np.datetime64("2021-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-03-01", "s"),
                       np.datetime64("2022-09-01", "s"), False)
        return [wfa.Passo(janela=j, escolhida=0, params={"a": 10},
                          is_={"lucro": 900.0, "trades": 200, "dd": 80.0},
                          oos={"lucro": 300.0, "trades": 60}, wfe_lucro=0.66)]

    def grava_wfa():
        return wfa_store.salvar(
            run_id=1, symbol="WIN$N", strategy="rompimento_canal",
            nome="x", is_meses=18, oos_meses=6, inteligencia="ulcer",
            holdout=False, agregado={"steps": 1}, veredito={"estado": "boa"},
            passos=passos(), capital=10_000.0, codigo_hash="h1")

    primeiro = grava_wfa()
    pid = plano.salvar(**_campos(wfa_id=primeiro))
    segundo = grava_wfa()

    d = plano.detalhes(pid)
    assert segundo != primeiro
    assert d["estado"] == "ativo" and d["wfa_id"] == primeiro
    assert wfa_store.detalhes(primeiro) is not None
    assert wfa_store.detalhes(segundo)["codigo_hash"] == "h1"
    rotulos = {w["wfa_id"]: w["rotulo"] for w in wfa_store.listar()}
    assert "tem plano" in rotulos[primeiro]
    assert "tem plano" not in rotulos[segundo]
    terceiro = grava_wfa()                 # o SEGUNDO não tem plano: substitui
    assert wfa_store.detalhes(segundo) is None
    assert {w["wfa_id"] for w in wfa_store.listar()} == {primeiro, terceiro}
```

- [ ] **Step 2: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_plano.py -k regravar` → FAIL (`unexpected keyword argument 'codigo_hash'`).

- [ ] **Step 3: Implementar em `core/wfa_store.py`**

- `salvar(..., camada4_travada=None, codigo_hash=None)`; no laço dos `antigos`, troque o corpo por:

```python
        for antigo in antigos:
            # antigo com plano FICA: substituí-lo aposentava o plano ativo em
            # silêncio e a estratégia saía do ar (spec Ao vivo §4.1). O novo
            # entra ao lado, e a lista marca qual tem plano.
            if con.execute("SELECT 1 FROM planos_operacao WHERE wfa_id = ?",
                           [antigo]).fetchone():
                continue
            con.execute("DELETE FROM wfa_trades WHERE wfa_id = ?", [antigo])
            con.execute("DELETE FROM wfa_runs WHERE wfa_id = ?", [antigo])
```

- No `INSERT INTO wfa_runs`, acrescente a coluna `codigo_hash` na lista de colunas, um `?` a mais em `VALUES`, e `codigo_hash` no fim da lista de valores.
- `listar`: acrescente ao `SELECT` a coluna
  `(SELECT count(*) FROM planos_operacao p WHERE p.wfa_id = wfa_runs.wfa_id)`
  (13º campo, desempacote como `n_planos`) e no rótulo, antes de `f" · {quando:%d/%m %H:%M}"`: `+ (" · tem plano" if n_planos else "")`.
- `detalhes`: acrescente `codigo_hash` ao `SELECT` (15º campo) e `"codigo_hash": r[14]` ao dicionário.

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_plano.py tests/test_wfa_store.py tests/test_callbacks_candidata.py tests/test_wfa_panel_selo.py` → passam.

- [ ] **Step 5: Mutation** — tire o `continue` → teste falha (`detalhes(primeiro) is None`). Restaure.

- [ ] **Step 6: Commit** — `core/wfa_store.py`, `tests/test_plano.py`; mensagem `feat(ao-vivo): regravar WFA com plano nao aposenta o plano`.

---

### Task 9: Contas e interruptor do portfólio

**Files:**
- Create: `core/ao_vivo.py`
- Test: `tests/test_ao_vivo_contas.py`

**Interfaces:**
- Consumes: `diario.registrar` (Task 3).
- Produces (`core/ao_vivo.py`):
  - `criar_conta(nome: str, tipo: str, limite_perda_dia: float | None = None) -> int`
  - `editar_conta(conta_id: int, *, nome=_NADA, tipo=_NADA, limite_perda_dia=_NADA) -> None` (um evento `conta_editada` por campo que mudou, `motivo` = nome do campo)
  - `arquivar_conta(conta_id: int) -> None`
  - `listar_contas(incluir_arquivadas: bool = False) -> list[dict]` (chaves = colunas de `contas`)
  - `ligar_portfolio(portfolio_id: int) -> None`, `desligar_portfolio(portfolio_id: int) -> None`
  - `definir_contas(portfolio_id: int, conta_demo_id: int | None, conta_real_id: int | None) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ao_vivo_contas.py
"""Contas (demo/real, mesa) e o interruptor do portfólio."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import diario  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401


def test_criar_e_listar(banco):
    cid = AV.criar_conta("Demo XP", "demo", 500.0)
    [c] = AV.listar_contas()
    assert c["conta_id"] == cid and c["tipo"] == "demo"
    assert c["limite_perda_dia"] == 500.0
    assert diario.eventos(tipo="conta_criada", conta_id=cid)


@pytest.mark.parametrize("nome,tipo", [("", "demo"), ("X", "papel")])
def test_criar_invalido_recusa(banco, nome, tipo):
    with pytest.raises(ValueError):
        AV.criar_conta(nome, tipo)


def test_nome_unico_so_entre_nao_arquivadas(banco):
    a = AV.criar_conta("Mesa A", "real")
    with pytest.raises(ValueError, match="já existe"):
        AV.criar_conta("Mesa A", "real")
    AV.arquivar_conta(a)
    AV.criar_conta("Mesa A", "real")          # arquivada libera o nome
    assert len(AV.listar_contas(incluir_arquivadas=True)) == 2


def test_editar_registra_de_para_por_campo(banco):
    cid = AV.criar_conta("Mesa A", "real", 500.0)
    AV.editar_conta(cid, limite_perda_dia=400.0, nome="Mesa A1")
    ev = {e["motivo"]: e for e in diario.eventos(tipo="conta_editada")}
    assert (ev["limite_perda_dia"]["de"], ev["limite_perda_dia"]["para"]) == (
        "500.0", "400.0")
    assert ev["nome"]["para"] == "Mesa A1"
    AV.editar_conta(cid, limite_perda_dia=None)     # limite é opcional
    assert AV.listar_contas()[0]["limite_perda_dia"] is None


def test_nenhuma_funcao_apaga_conta():
    assert not [n for n in dir(AV) if "conta" in n and
                any(p in n for p in ("excluir", "apagar", "remover"))]


def test_ligar_e_desligar_portfolio_com_eventos(banco):
    pid = P.criar("p")
    AV.ligar_portfolio(pid)
    assert P.listar()[0]["ligado"] is True
    AV.ligar_portfolio(pid)                   # já ligado: não duplica evento
    AV.desligar_portfolio(pid)
    assert [e["tipo"] for e in diario.eventos(portfolio_id=pid)] == [
        "portfolio_ligado", "portfolio_desligado"]


def test_definir_contas_valida_tipo_e_arquivada(banco):
    pid = P.criar("p")
    demo, real = AV.criar_conta("D", "demo"), AV.criar_conta("R", "real")
    with pytest.raises(ValueError, match="demo"):
        AV.definir_contas(pid, real, None)
    AV.definir_contas(pid, demo, real)
    p = P.listar()[0]
    assert (p["conta_demo_id"], p["conta_real_id"]) == (demo, real)
    AV.arquivar_conta(demo)
    with pytest.raises(ValueError, match="arquivada"):
        AV.definir_contas(pid, demo, real)


def test_evento_falho_desfaz_a_mudanca(banco, monkeypatch):
    """Estado e evento na mesma transação: ou os dois, ou nenhum."""
    pid = P.criar("p")

    def quebra(*a, **k):
        raise RuntimeError("falhou no meio")
    monkeypatch.setattr(AV.diario, "registrar", quebra)
    with pytest.raises(RuntimeError):
        AV.ligar_portfolio(pid)
    assert P.listar()[0]["ligado"] is False
```

- [ ] **Step 2: Run to verify it fails** — `ImportError: cannot import name 'ao_vivo'`.

- [ ] **Step 3: Implementar**

`core/portfolio.py` — `listar()` passa a devolver `ligado`, `conta_demo_id`, `conta_real_id` e a contar de `portfolio_membros` (a Task 10 depende disto):

```python
def listar() -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT p.portfolio_id, p.nome, p.criado_em, p.capital, "
            "count(pm.ligacao_id), coalesce(p.ligado, false), "
            "p.conta_demo_id, p.conta_real_id "
            "FROM portfolios p "
            "LEFT JOIN portfolio_membros pm "
            "ON pm.portfolio_id = p.portfolio_id AND pm.removido_em IS NULL "
            "GROUP BY ALL ORDER BY p.nome"
        ).fetchall()
    return [{"portfolio_id": r[0], "nome": r[1], "criado_em": r[2],
             "capital": r[3], "n_membros": r[4], "ligado": bool(r[5]),
             "conta_demo_id": r[6], "conta_real_id": r[7]} for r in rows]
```

> Isto muda a contagem de `n_membros` para a tabela nova antes de `adicionar_variante` escrever nela (Task 10): rode Task 9 e 10 em sequência e só rode a suíte inteira no fim da Task 10.

`core/ao_vivo.py`:

```python
"""Tela Ao vivo: contas, interruptores e arrumação da cadeia.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md.
Toda mudança de estado grava o evento do diário NA MESMA transação.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db
from . import diario

_TIPOS_CONTA = ("demo", "real")
_COLS_CONTA = ("conta_id", "nome", "tipo", "limite_perda_dia", "criado_em",
               "arquivada_em")
_NADA = object()


def _nome_livre(con, nome, ignorar_id=None):
    r = con.execute(
        "SELECT conta_id FROM contas WHERE nome = ? AND arquivada_em IS NULL "
        "AND conta_id IS DISTINCT FROM ?", [nome, ignorar_id]).fetchone()
    if r:
        raise ValueError(f"já existe uma conta ativa chamada '{nome}'")


def criar_conta(nome, tipo, limite_perda_dia=None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("a conta precisa de um nome")
    if tipo not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    with db.connect_write() as con, db.transacao(con):
        _nome_livre(con, nome)
        cid = con.execute("SELECT nextval('seq_conta_id')").fetchone()[0]
        con.execute("INSERT INTO contas VALUES (?,?,?,?,?,NULL)",
                    [cid, nome, tipo, limite_perda_dia, datetime.now()])
        diario.registrar(con, "conta_criada", "usuario", conta_id=cid,
                         para=nome, motivo=tipo)
    return int(cid)


def editar_conta(conta_id, *, nome=_NADA, tipo=_NADA,
                 limite_perda_dia=_NADA) -> None:
    novos = {k: v for k, v in (("nome", nome), ("tipo", tipo),
                               ("limite_perda_dia", limite_perda_dia))
             if v is not _NADA}
    if "nome" in novos:
        novos["nome"] = (novos["nome"] or "").strip()
        if not novos["nome"]:
            raise ValueError("a conta precisa de um nome")
    if "tipo" in novos and novos["tipo"] not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT nome, tipo, limite_perda_dia FROM contas "
                        "WHERE conta_id = ?", [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        atual = dict(zip(("nome", "tipo", "limite_perda_dia"), r))
        if "nome" in novos:
            _nome_livre(con, novos["nome"], conta_id)
        if "tipo" in novos and novos["tipo"] != atual["tipo"]:
            # a fase das variantes decide para qual conta vai a ordem: trocar
            # o tipo de uma conta já escolhida mandaria demo para o real
            if con.execute("SELECT 1 FROM portfolios WHERE conta_demo_id = ? "
                           "OR conta_real_id = ?",
                           [conta_id, conta_id]).fetchone():
                raise ValueError("a conta está escolhida num portfólio: "
                                 "tire-a de lá antes de trocar o tipo")
        for campo, valor in novos.items():
            if valor == atual[campo]:
                continue
            con.execute(f"UPDATE contas SET {campo} = ? WHERE conta_id = ?",
                        [valor, conta_id])
            diario.registrar(con, "conta_editada", "usuario",
                             conta_id=conta_id, de=atual[campo], para=valor,
                             motivo=campo)


def arquivar_conta(conta_id) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute("UPDATE contas SET arquivada_em = ? WHERE conta_id = ? "
                    "AND arquivada_em IS NULL", [datetime.now(), conta_id])
        diario.registrar(con, "conta_arquivada", "usuario", conta_id=conta_id)


def listar_contas(incluir_arquivadas: bool = False) -> list[dict]:
    sql = (f"SELECT {', '.join(_COLS_CONTA)} FROM contas"
           + ("" if incluir_arquivadas else " WHERE arquivada_em IS NULL")
           + " ORDER BY nome")
    with db.connect(read_only=True) as con:
        return [dict(zip(_COLS_CONTA, r)) for r in con.execute(sql).fetchall()]


def _mudar_portfolio(portfolio_id, ligado: bool) -> None:
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT coalesce(ligado, false) FROM portfolios "
                        "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        if r is None:
            raise ValueError(f"portfólio #{portfolio_id} não existe")
        if bool(r[0]) == ligado:
            return
        con.execute("UPDATE portfolios SET ligado = ? WHERE portfolio_id = ?",
                    [ligado, portfolio_id])
        diario.registrar(con, "portfolio_ligado" if ligado
                         else "portfolio_desligado", "usuario",
                         portfolio_id=portfolio_id)


def ligar_portfolio(portfolio_id) -> None:
    _mudar_portfolio(portfolio_id, True)


def desligar_portfolio(portfolio_id) -> None:
    _mudar_portfolio(portfolio_id, False)


def _conta_valida(con, conta_id, tipo):
    if conta_id is None:
        return
    r = con.execute("SELECT tipo, arquivada_em FROM contas WHERE conta_id = ?",
                    [conta_id]).fetchone()
    if r is None:
        raise ValueError(f"conta #{conta_id} não existe")
    if r[0] != tipo:
        raise ValueError(f"a conta #{conta_id} não é do tipo {tipo}")
    if r[1] is not None:
        raise ValueError(f"a conta #{conta_id} está arquivada")


def definir_contas(portfolio_id, conta_demo_id, conta_real_id) -> None:
    with db.connect_write() as con, db.transacao(con):
        _conta_valida(con, conta_demo_id, "demo")
        _conta_valida(con, conta_real_id, "real")
        antes = con.execute("SELECT conta_demo_id, conta_real_id FROM portfolios "
                            "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        if antes is None:
            raise ValueError(f"portfólio #{portfolio_id} não existe")
        if tuple(antes) == (conta_demo_id, conta_real_id):
            return
        con.execute("UPDATE portfolios SET conta_demo_id = ?, conta_real_id = ? "
                    "WHERE portfolio_id = ?",
                    [conta_demo_id, conta_real_id, portfolio_id])
        diario.registrar(con, "portfolio_conta_mudou", "usuario",
                         portfolio_id=portfolio_id,
                         de=f"demo:{antes[0]} real:{antes[1]}",
                         para=f"demo:{conta_demo_id} real:{conta_real_id}")
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_contas.py` → passam.

- [ ] **Step 5: Mutation** — tire `AND arquivada_em IS NULL` de `_nome_livre` → `test_nome_unico...` falha; em `_mudar_portfolio`, mova `diario.registrar` para fora do `with` → `test_evento_falho...` falha. Restaure.

- [ ] **Step 6: Commit** — só depois da Task 10 (ver nota em `listar`). Siga direto.

---

### Task 10: Ligações (membros) com fase, interruptor e remoção só por marcação

**Files:**
- Modify: `core/portfolio.py` (`adicionar_variante`, `remover_variante`, `membros`)
- Modify: `core/ao_vivo.py` (`ligar_membro`, `desligar_membro`)
- Test: `tests/test_ao_vivo_membros.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 9.
- Produces:
  - `portfolio.adicionar_variante(portfolio_id, variante_id) -> int` (o `ligacao_id`; se já existe não removida, devolve a existente e não grava nada)
  - `portfolio.remover_variante(portfolio_id, variante_id) -> None` — `ValueError` com portfólio ligado; com desligado: desliga (se ligada) e marca `removido_em`, dois eventos.
  - `portfolio.membros(portfolio_id)` — cada item ganha `ligacao_id`, `fase`, `ligada`.
  - `ao_vivo.ligar_membro(ligacao_id) -> None`, `ao_vivo.desligar_membro(ligacao_id, por: str = "usuario") -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ao_vivo_membros.py
"""A ligação variante × portfólio: nunca apagada, com fase e interruptor."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import diario, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401


def _pv():
    return P.criar("p"), variantes.criar("v", "rompimento_canal")


def _linha(lig):
    with db.connect(read_only=True) as con:
        return con.execute(
            "SELECT fase, ligada, removido_em, desligada_por "
            "FROM portfolio_membros WHERE ligacao_id = ?", [lig]).fetchone()


def test_adicionar_entra_ligada_no_papel(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    assert _linha(lig) == ("papel", True, None, None)
    [m] = P.membros(pid)
    assert (m["ligacao_id"], m["fase"], m["ligada"]) == (lig, "papel", True)
    assert diario.eventos(tipo="membro_adicionado", ligacao_id=lig)


def test_adicionar_duas_vezes_nao_faz_nada(banco):
    pid, vid = _pv()
    a = P.adicionar_variante(pid, vid)
    assert P.adicionar_variante(pid, vid) == a
    assert len(diario.eventos(tipo="membro_adicionado")) == 1


def test_remover_com_portfolio_ligado_recusa(banco):
    pid, vid = _pv()
    P.adicionar_variante(pid, vid)
    AV.ligar_portfolio(pid)
    with pytest.raises(ValueError, match="desligue"):
        P.remover_variante(pid, vid)
    assert len(P.membros(pid)) == 1


def test_remover_com_portfolio_desligado_marca_e_gera_dois_eventos(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    P.remover_variante(pid, vid)
    assert P.membros(pid) == [] and P.listar()[0]["n_membros"] == 0
    assert _linha(lig)[2] is not None            # continua no banco
    assert [e["tipo"] for e in diario.eventos(ligacao_id=lig)] == [
        "membro_adicionado", "membro_desligado", "membro_removido"]


def test_readicionar_cria_ligacao_nova_no_papel(banco):
    pid, vid = _pv()
    a = P.adicionar_variante(pid, vid)
    P.remover_variante(pid, vid)
    b = P.adicionar_variante(pid, vid)
    assert b != a and _linha(b) == ("papel", True, None, None)


def test_desligar_e_ligar(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    AV.desligar_membro(lig)
    assert _linha(lig)[1:] == (False, None, "usuario")
    AV.desligar_membro(lig)                         # já desligada: nada
    AV.ligar_membro(lig)
    assert _linha(lig)[1] is True and _linha(lig)[3] is None
    assert [e["tipo"] for e in diario.eventos(ligacao_id=lig)] == [
        "membro_adicionado", "membro_desligado", "membro_ligado"]


def test_religar_depois_do_disjuntor_e_livre_e_registrado(banco):
    """Decisão do usuário (30/09/2026): religa a qualquer momento."""
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    AV.desligar_membro(lig, por="disjuntor")
    AV.ligar_membro(lig)
    [e] = diario.eventos(tipo="membro_ligado", ligacao_id=lig)
    assert e["motivo"] == "religada após disjuntor"


def test_ligacao_removida_nao_liga(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    P.remover_variante(pid, vid)
    with pytest.raises(ValueError, match="removida"):
        AV.ligar_membro(lig)


def test_por_invalido_recusa(banco):
    pid, vid = _pv()
    lig = P.adicionar_variante(pid, vid)
    with pytest.raises(ValueError):
        AV.desligar_membro(lig, por="robo")
```

- [ ] **Step 2: Run to verify it fails** — `test_adicionar_entra_ligada_no_papel` falha (`adicionar_variante` devolve `None`).

- [ ] **Step 3: Implementar**

`core/portfolio.py` — imports: `from . import diario`. Substitua `adicionar_variante`, `remover_variante` e a consulta de `membros`:

```python
def adicionar_variante(portfolio_id: int, variante_id: int) -> int:
    """Entra ligada, no papel: papel não envia ordem, e começar ligada não
    faz a incubação perder dias. Já presente: não faz nada."""
    with db.connect_write() as con, db.transacao(con):
        r = con.execute(
            "SELECT ligacao_id FROM portfolio_membros WHERE portfolio_id = ? "
            "AND variante_id = ? AND removido_em IS NULL",
            [portfolio_id, variante_id]).fetchone()
        if r:
            return int(r[0])
        agora = datetime.now()
        lig = con.execute("SELECT nextval('seq_ligacao_id')").fetchone()[0]
        con.execute(
            "INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
            "variante_id, adicionado_em, fase, fase_desde, ligada) "
            "VALUES (?,?,?,?,'papel',?,true)",
            [lig, portfolio_id, variante_id, agora, agora])
        diario.registrar(con, "membro_adicionado", "usuario",
                         portfolio_id=portfolio_id, ligacao_id=lig,
                         variante_id=variante_id, para="papel")
    return int(lig)


def remover_variante(portfolio_id: int, variante_id: int) -> None:
    """Remoção só marca: a ligação guarda a incubação e vai etiquetar
    ordens na parte 4. Com o portfólio ligado, recusa."""
    with db.connect_write() as con, db.transacao(con):
        ligado = con.execute("SELECT coalesce(ligado, false) FROM portfolios "
                             "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        r = con.execute(
            "SELECT ligacao_id, ligada FROM portfolio_membros "
            "WHERE portfolio_id = ? AND variante_id = ? AND removido_em IS NULL",
            [portfolio_id, variante_id]).fetchone()
        if r is None:
            return
        if ligado and ligado[0]:
            raise ValueError("desligue o portfólio antes de remover uma variante")
        lig, ligada = r
        agora = datetime.now()
        if ligada:
            con.execute("UPDATE portfolio_membros SET ligada = false, "
                        "desligada_por = 'usuario', desligada_em = ? "
                        "WHERE ligacao_id = ?", [agora, lig])
            diario.registrar(con, "membro_desligado", "usuario",
                             portfolio_id=portfolio_id, ligacao_id=lig,
                             variante_id=variante_id, motivo="removida")
        con.execute("UPDATE portfolio_membros SET removido_em = ? "
                    "WHERE ligacao_id = ?", [agora, lig])
        diario.registrar(con, "membro_removido", "usuario",
                         portfolio_id=portfolio_id, ligacao_id=lig,
                         variante_id=variante_id)
```

Em `membros`, troque a consulta e o `for`:

```python
        rows = con.execute(
            "SELECT ev.variante_id, ev.nome, ev.estrategia, pm.ligacao_id, "
            "pm.fase, pm.ligada "
            "FROM portfolio_membros pm "
            "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
            "WHERE pm.portfolio_id = ? AND pm.removido_em IS NULL "
            "ORDER BY ev.nome", [portfolio_id]
        ).fetchall()
    out = []
    for vid, nome, estrategia, lig, fase, ligada in rows:
        ativo = V.plano_ativo(vid)
        out.append({
            "variante_id": vid, "nome": nome, "estrategia": estrategia,
            "ligacao_id": lig, "fase": fase, "ligada": bool(ligada),
            "wfa_id": ativo["wfa_id"] if ativo else None,
            "sem_plano_ativo": ativo is None,
        })
    return out
```

`core/ao_vivo.py` — imports: `from . import variantes as V`. Acrescente:

```python
_POR = ("usuario", "disjuntor")


def _membro(con, ligacao_id):
    r = con.execute("SELECT portfolio_id, variante_id, ligada, removido_em, "
                    "desligada_por FROM portfolio_membros WHERE ligacao_id = ?",
                    [ligacao_id]).fetchone()
    if r is None:
        raise ValueError(f"ligação #{ligacao_id} não existe")
    if r[3] is not None:
        raise ValueError(f"a ligação #{ligacao_id} foi removida do portfólio")
    return r


def desligar_membro(ligacao_id, por: str = "usuario") -> None:
    if por not in _POR:
        raise ValueError("desligar só 'usuario' ou 'disjuntor'")
    with db.connect_write() as con, db.transacao(con):
        pid, vid, ligada, _rem, _por = _membro(con, ligacao_id)
        if not ligada:
            return
        vigor = V.plano_em_vigor(vid, con=con)
        con.execute("UPDATE portfolio_membros SET ligada = false, "
                    "desligada_por = ?, desligada_em = ?, "
                    "desligada_plano_id = ? WHERE ligacao_id = ?",
                    [por, datetime.now(), vigor and vigor["plano_id"],
                     ligacao_id])
        diario.registrar(con, "membro_desligado", por, portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         plano_id=vigor and vigor["plano_id"])


def ligar_membro(ligacao_id) -> None:
    """Livre a qualquer momento, inclusive depois do disjuntor (decisão do
    usuário, 30/09/2026) — o evento guarda que foi religada depois dele."""
    with db.connect_write() as con, db.transacao(con):
        pid, vid, ligada, _rem, por = _membro(con, ligacao_id)
        if ligada:
            return
        con.execute("UPDATE portfolio_membros SET ligada = true, "
                    "desligada_por = NULL, desligada_em = NULL, "
                    "desligada_plano_id = NULL WHERE ligacao_id = ?",
                    [ligacao_id])
        diario.registrar(con, "membro_ligado", "usuario", portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         motivo="religada após disjuntor"
                         if por == "disjuntor" else None)
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_membros.py tests/test_ao_vivo_contas.py tests/test_portfolio.py tests/test_portfolio_panel_comparativo.py` → passam. Depois a **suíte inteira**.

- [ ] **Step 5: Mutation** — (a) tire o `raise` de portfólio ligado → `test_remover_com_portfolio_ligado...` falha; (b) troque o UPDATE de `removido_em` por `DELETE FROM portfolio_membros` → `test_remover_com_portfolio_desligado...` falha; (c) tire `AND removido_em IS NULL` de `adicionar_variante` → `test_readicionar...` falha. Restaure.

- [ ] **Step 6: Commit (Tasks 9 e 10 juntas)** — `core/ao_vivo.py`, `core/portfolio.py`, `tests/test_ao_vivo_contas.py`, `tests/test_ao_vivo_membros.py`; mensagem `feat(ao-vivo): contas, portfolio ligado e ligacoes com fase e interruptor`.

---

### Task 11: Arrumação — vincular plano a variante e renomear variante

**Files:**
- Modify: `core/ao_vivo.py` (`vincular_plano`), `core/variantes.py` (`renomear`)
- Test: `tests/test_ao_vivo_arrumacao.py`

**Interfaces:**
- Consumes: `plano.proximo_dia_util` (Task 4), `diario.registrar`.
- Produces:
  - `ao_vivo.vincular_plano(run_id: int, variante_id: int, manter_plano_id: int | None = None, agora: datetime | None = None) -> None` — grava `variante_id` na mineração e em todos os planos dela; recusa estratégia diferente e mineração já vinculada; se sobrarem 2+ ativos na variante exige `manter_plano_id` e aposenta os outros (sai de vigor no próximo dia útil). Eventos `plano_vinculado` (um por plano) e `plano_aposentado`.
  - `variantes.renomear(variante_id: int, nome: str) -> None` — evento `variante_renomeada`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ao_vivo_arrumacao.py
"""Arrumar a cadeia pela tela: vincular plano órfão e renomear variante.
Caso real: plano #3 (mineração #50, sem variante) × variante 7, que já
tem o plano #4 ativo."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import diario, plano, variantes  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = datetime(2026, 10, 1, 14, 0)


def _orfa_e_destino():
    v = variantes.criar("v7", "rompimento_canal")
    mineracao(53, variante_id=v)
    wfa(24, 53)
    p4 = plano.salvar(**campos_plano(wfa_id=24, run_id=53),
                      agora=datetime(2026, 9, 28, 10))
    mineracao(50)                       # sem variante
    wfa(18, 50)
    p2 = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                      agora=datetime(2026, 9, 25, 10))
    p3 = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                      agora=datetime(2026, 9, 25, 11))
    return v, p2, p3, p4


def test_sem_escolha_com_dois_ativos_recusa(banco):
    v, p2, p3, p4 = _orfa_e_destino()
    with pytest.raises(ValueError, match="escolha"):
        AV.vincular_plano(50, v, agora=QUI)
    assert plano.detalhes(p3)["variante_id"] is None


def test_vincular_leva_mineracao_e_todos_os_planos(banco):
    v, p2, p3, p4 = _orfa_e_destino()
    AV.vincular_plano(50, v, manter_plano_id=p4, agora=QUI)
    assert all(plano.detalhes(p)["variante_id"] == v for p in (p2, p3))
    assert plano.detalhes(p3)["estado"] == "aposentado"
    assert plano.detalhes(p3)["aposentado_em"] == date(2026, 10, 2)
    assert plano.detalhes(p4)["estado"] == "ativo"
    assert len(diario.eventos(tipo="plano_vinculado")) == 2
    with pytest.raises(ValueError, match="já é da variante"):
        AV.vincular_plano(50, v, manter_plano_id=p4, agora=QUI)


def test_vincular_manter_o_orfao_aposenta_o_do_destino(banco):
    v, p2, p3, p4 = _orfa_e_destino()
    AV.vincular_plano(50, v, manter_plano_id=p3, agora=QUI)
    assert plano.detalhes(p4)["estado"] == "aposentado"
    assert plano.detalhes(p3)["estado"] == "ativo"


def test_vincular_estrategia_diferente_recusa(banco):
    v = variantes.criar("outra", "setup_cruzamento")
    mineracao(50)
    with pytest.raises(ValueError, match="estratégia"):
        AV.vincular_plano(50, v)


def test_renomear(banco):
    a = variantes.criar("a", "rompimento_canal")
    variantes.criar("b", "rompimento_canal")
    with pytest.raises(ValueError, match="já existe"):
        variantes.renomear(a, "b")
    variantes.renomear(a, "romp-abert-m15")
    assert {x["nome"] for x in variantes.listar()} == {"romp-abert-m15", "b"}
    [e] = diario.eventos(tipo="variante_renomeada", variante_id=a)
    assert (e["de"], e["para"]) == ("a", "romp-abert-m15")
```

- [ ] **Step 2: Run to verify it fails** — `AttributeError: ... 'vincular_plano'`.

- [ ] **Step 3: Implementar**

`core/variantes.py` — imports: `from . import diario`.

```python
def renomear(variante_id: int, nome: str) -> None:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome da variante não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT nome, estrategia FROM estrategia_variantes "
                        "WHERE variante_id = ?", [variante_id]).fetchone()
        if r is None:
            raise ValueError(f"variante #{variante_id} não existe")
        antigo, estrategia = r
        if nome == antigo:
            return
        if con.execute("SELECT 1 FROM estrategia_variantes WHERE estrategia = ? "
                       "AND nome = ?", [estrategia, nome]).fetchone():
            raise ValueError(f"já existe uma variante '{nome}' para {estrategia}")
        con.execute("UPDATE estrategia_variantes SET nome = ? "
                    "WHERE variante_id = ?", [nome, variante_id])
        diario.registrar(con, "variante_renomeada", "usuario",
                         variante_id=variante_id, de=antigo, para=nome)
```

`core/ao_vivo.py` — imports: `from . import plano as _plano`.

```python
def vincular_plano(run_id, variante_id, manter_plano_id=None,
                   agora: datetime | None = None) -> None:
    """Põe uma mineração sem variante (e todos os planos dela) numa variante
    da mesma estratégia. Se a variante acabar com dois planos ativos, o
    usuário escolhe qual fica; o outro sai de vigor no próximo pregão."""
    agora = agora or datetime.now()
    sai_em = _plano.proximo_dia_util(agora.date())
    with db.connect_write() as con, db.transacao(con):
        m = con.execute("SELECT strategy, variante_id FROM mining_runs "
                        "WHERE run_id = ?", [run_id]).fetchone()
        v = con.execute("SELECT estrategia, nome FROM estrategia_variantes "
                        "WHERE variante_id = ?", [variante_id]).fetchone()
        if m is None or v is None:
            raise ValueError("mineração ou variante não existe")
        if m[1] is not None:
            raise ValueError(f"a mineração #{run_id} já é da variante #{m[1]}")
        if m[0] != v[0]:
            raise ValueError(f"a variante {v[1]} é de outra estratégia ({v[0]})")
        ativos = [r[0] for r in con.execute(
            "SELECT plano_id FROM planos_operacao WHERE estado = 'ativo' "
            "AND (variante_id = ? OR run_id = ?) ORDER BY plano_id",
            [variante_id, run_id]).fetchall()]
        if len(ativos) > 1 and manter_plano_id not in ativos:
            raise ValueError(
                "a variante ficaria com dois planos ativos: escolha qual fica ("
                + " ou ".join(f"#{p}" for p in ativos) + ")")
        planos = [r[0] for r in con.execute(
            "SELECT plano_id FROM planos_operacao WHERE run_id = ?",
            [run_id]).fetchall()]
        con.execute("UPDATE mining_runs SET variante_id = ? WHERE run_id = ?",
                    [variante_id, run_id])
        con.execute("UPDATE planos_operacao SET variante_id = ? "
                    "WHERE run_id = ?", [variante_id, run_id])
        for p in planos:
            diario.registrar(con, "plano_vinculado", "usuario", plano_id=p,
                             variante_id=variante_id,
                             motivo=f"mineração #{run_id}")
        for p in ativos:
            if len(ativos) > 1 and p != manter_plano_id:
                con.execute("UPDATE planos_operacao SET estado = 'aposentado', "
                            "aposentado_em = ? WHERE plano_id = ?", [sai_em, p])
                diario.registrar(con, "plano_aposentado", "usuario",
                                 plano_id=p, variante_id=variante_id,
                                 de="ativo", para="aposentado",
                                 motivo=f"fica o plano #{manter_plano_id}")
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_arrumacao.py tests/test_variantes.py` → passam.

- [ ] **Step 5: Mutation** — tire a checagem de estratégia → `test_vincular_estrategia_diferente...` falha; tire o `UPDATE planos_operacao SET variante_id` → `test_vincular_leva...` falha. Restaure.

- [ ] **Step 6: Commit** — `core/ao_vivo.py`, `core/variantes.py`, `tests/test_ao_vivo_arrumacao.py`; mensagem `feat(ao-vivo): vincular plano a variante e renomear variante`.

---

### Task 12: As telas mostram as recusas; Candidata e WFA gravam a impressão digital

**Files:**
- Modify: `ui/components/mining.py` (div `mine-aviso`), `ui/callbacks.py` (`excluir_mineracao`, `wfa_excluir`, `wfa_guardar`), `ui/callbacks_portfolio.py` (remover), `ui/callbacks_candidata.py` (`gravar_plano`), `cli.py` (`--limpar`), `core/plano.py` (`DEFINICOES["depois_de_desligar"]`)
- Test: `tests/test_callbacks_candidata.py` (acrescentar), `tests/test_callbacks_sem_ciclo.py` (rodar)

**Interfaces:**
- Consumes: Tasks 1, 4, 6, 7, 8, 10.

- [ ] **Step 1: Teste da mensagem da Candidata** — acrescente a `tests/test_callbacks_candidata.py`, reaproveitando a montagem de `test_gravar_plano_grava_e_diz_o_numero` (linha ~373; copie a preparação dela):

```python
def test_gravar_plano_diz_quando_vale_e_quem_aposentou(tmp_path, monkeypatch):
    wid = _wfa_gravavel(tmp_path, monkeypatch)
    ver = {"wfa_id": wid, "estado": "aprovada", "reprovados": [],
           "pendentes": [], "portoes": []}
    primeiro = CC.gravar_plano(ver, 5.0, None, 50.0)
    assert "vale a partir de" in primeiro and "aposentou" not in primeiro
    segundo = CC.gravar_plano(ver, 2.0, None, 50.0)
    assert "aposentou #" in segundo
    CC._LEITURAS.clear()
```

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_callbacks_candidata.py -k diz_quando_vale` → FAIL.

- [ ] **Step 2: `ui/callbacks_candidata.py` — `gravar_plano`**, troque o `return` final por:

```python
    pid = plano.salvar(**campos)
    quando = campos.get("reotimizar_em")
    aviso = plano.aviso_ao_gravar(ver)
    vale = plano.detalhes(pid)["vale_a_partir"]
    trocados = [e["plano_id"] for e in diario.eventos(
        tipo="plano_aposentado", motivo=f"substituído pelo plano #{pid}")]
    atual = codigo.hash_estrategia(campos.get("strategy") or "")
    mudou = bool(campos.get("codigo_hash")) and atual != campos["codigo_hash"]
    return (f"plano #{pid} gravado · vale a partir de {vale:%d/%m/%Y} · "
            f"{dim['n']} contrato(s) · reotimizar até "
            f"{quando.strftime('%d/%m/%Y') if quando else '—'}"
            + (" · aposentou " + ", ".join(f"#{p}" for p in trocados)
               if trocados else "")
            + (" · ⚠ o código da estratégia mudou desde o walk-forward"
               if mudou else "")
            + (f" · {aviso}" if aviso else ""))
```

Imports do arquivo: `from core import codigo, diario` (junto dos outros `from core import ...`). Run → passa.

- [ ] **Step 3: `ui/callbacks.py` — WFA grava a impressão digital.** Em `wfa_guardar`, na chamada `wfa_store.salvar(...)`, acrescente o argumento `codigo_hash=codigo.hash_estrategia(_WFA["strategy"])` e o import `from core import codigo` no topo.

- [ ] **Step 4: `ui/components/mining.py`** — logo depois do `html.Button("Excluir", id="btn-excluir-mine", ...)`, dentro da mesma `html.Div([...], className="acoes acoes-carregar")`:

```python
                    # a recusa de apagar (plano em operação) aparece aqui
                    html.Span(id="mine-aviso", className="mine-aviso"),
```

- [ ] **Step 5: `ui/callbacks.py` — `excluir_mineracao`** ganha a saída e o tratamento:

```python
    @app.callback(
        Output("btn-excluir-mine", "disabled"),
        Output("btn-excluir-mine", "children"),
        Output("mine-carregar", "value", allow_duplicate=True),
        Output("mine-aviso", "children"),
        Input("mine-carregar", "value"),
        Input("btn-excluir-mine", "n_clicks"),
        State("btn-excluir-mine", "children"),
        prevent_initial_call=True,
    )
    def excluir_mineracao(run_id, _n, rotulo):
        """(docstring atual) ... Recusada (plano em operação), diz o motivo
        e não mexe no seletor nem esquece a mineração aberta."""
        if ctx.triggered_id == "mine-carregar":
            return (not run_id), "Excluir", no_update, ""
        if not run_id:
            return True, "Excluir", no_update, ""
        if rotulo != "Confirmar?":
            return False, "Confirmar?", no_update, ""
        try:
            optimizer.excluir_salva(int(run_id))
        except ValueError as e:
            return False, "Excluir", no_update, str(e)
        MINERACAO.esquecer()
        return True, "Excluir", None, ""
```

`wfa_excluir`:

```python
        try:
            wfa_store.excluir(int(wfa_id))
        except ValueError as e:
            return "Excluir", no_update, str(e), no_update
        return ("Excluir", None, f"walk-forward #{wfa_id} excluído",
                {"excluido": int(wfa_id), "t": __import__("time").time()})
```

- [ ] **Step 6: `ui/callbacks_portfolio.py`** — no ramo `pf-btn-remover`:

```python
        aviso_remover = None
        ...
        elif (isinstance(gatilho, dict) and gatilho.get("type") == "pf-btn-remover"
              and valor_disparo and pid is not None):
            try:
                P.remover_variante(pid, gatilho["variante_id"])
            except ValueError as e:
                aviso_remover = str(e)
```

(declare `aviso_remover = None` antes do `if` do gatilho) e, onde `avisos_txt` é montado:

```python
        avisos_txt = list(dict.fromkeys(
            ([aviso_remover] if aviso_remover else [])
            + r["avisos"] + curvas["avisos"]))
```

- [ ] **Step 7: `cli.py` `--limpar`** — troque o laço:

```python
    from core import optimizer
    apagadas, recusadas = 0, []
    for run_id in alvos:
        # a mesma porta que o botao da tela usa - inclusive a recusa de
        # apagar cadeia com plano em operacao
        try:
            optimizer.excluir_salva(run_id)
            apagadas += 1
        except ValueError as e:
            recusadas.append(str(e))
    print(f"\n{apagadas} minerações apagadas, com os walk-forwards e os "
          "planos de operação que nasceram delas.")
    for motivo in recusadas:
        print(f"  não apagada: {motivo}")
```

(mantenha as duas linhas finais de `print` sobre compactar o `.duckdb`).

- [ ] **Step 8: `core/plano.py`** — `DEFINICOES["depois_de_desligar"] = "volta a operar quando o usuário religar"` (decisão 13 da spec; planos antigos guardam o texto da época).

- [ ] **Step 9: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_callbacks_candidata.py tests/test_callbacks_sem_ciclo.py` e depois a **suíte inteira** → tudo verde.

- [ ] **Step 10: Commit** — `ui/components/mining.py`, `ui/callbacks.py`, `ui/callbacks_portfolio.py`, `ui/callbacks_candidata.py`, `cli.py`, `core/plano.py`, `tests/test_callbacks_candidata.py`; mensagem `feat(ao-vivo): telas mostram recusas e gravam impressao digital`.

---

### Task 13: Fechamento — revisão, backup, conferência no banco real, documentação

**Files:** `CHANGELOG.md`, `CLAUDE.md` (seção "Onde estamos"), nenhum código novo.

- [ ] **Step 1: Suíte inteira verde** — `.venv/Scripts/python.exe -m pytest -q`. Colar o resumo no relatório.

- [ ] **Step 2: Revisão** — agente `revisor` (em segundo plano) sobre o diff desde o commit da spec (`git diff c796565..HEAD -- core ui cli.py tests`). Aplicar o que proceder, com teste, e commitar.

- [ ] **Step 3: Backup do banco real ANTES de subir o app** — a migração da Task 2 roda na primeira subida e altera `data/database.duckdb`. Com o app **parado**:

```powershell
New-Item -ItemType Directory -Force "C:\Users\mrRobot\Documents\Neturna\backups" | Out-Null
Copy-Item data\database.duckdb "C:\Users\mrRobot\Documents\Neturna\backups\database-antes-ao-vivo-1a.duckdb"
if (Test-Path data\database.duckdb.wal) { Copy-Item data\database.duckdb.wal "C:\Users\mrRobot\Documents\Neturna\backups\database-antes-ao-vivo-1a.duckdb.wal" }
```

- [ ] **Step 4: Conferência na tela** (`preview_start` nome `dataframe`), **sem gravar nada**:
  1. Portfólio › "portifolio-teste": os 2 membros aparecem como antes; curva, tabela e correlação iguais.
  2. Mineração: selecionar a **#47** (cadeia do plano #1, ativo) → Excluir → Confirmar? → aparece *"a mineração #47 não pode ser apagada: o plano #1 está ativo na variante romp-canal-02"* e a mineração **continua** na lista.
  3. Walk-Forward: selecionar o **#13** → Excluir → Confirmar? → recusa com motivo; registro continua.
  4. Consultar só-leitura: `portfolio_membros` tem as 2 ligações (papel, ligada); `planos_operacao.variante_id` preenchido para #1 e #4 e nulo para #2/#3.
  Screenshot de 2 e 3 para o usuário. Se qualquer coisa for apagada: parar, restaurar o backup do Step 3.

- [ ] **Step 5: Documentação** — agente `documentador`: entrada no `CHANGELOG.md` (`[Não lançado]` → "Ao vivo, entrega 1a: blindagem") e `CLAUDE.md` "Onde estamos" → próximo passo = plano 1b. Commit `docs(ao-vivo): changelog e estado da entrega 1a`.

- [ ] **Step 6: Push** — `git push origin candidata` (se pedir login: `$env:GIT_TERMINAL_PROMPT='1'; $env:GCM_INTERACTIVE='auto'` antes, só no comando).
