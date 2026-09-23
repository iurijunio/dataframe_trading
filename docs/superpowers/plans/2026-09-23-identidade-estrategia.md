# Identidade da estratégia (projeto D, parte 1) — Plano de implementação

> **Para agentes:** cada tarefa é executada uma de cada vez, **sem agente
> executor** (o desenvolvedor implementa em pessoa, nesta sessão), e um
> agente é chamado só para **revisar** cada tarefa pronta antes do commit —
> mesma preferência já registrada nos planos do projeto B.

**Goal:** agrupar minerações/WFAs/planos que pertencem à mesma variante de
estratégia, ao longo de vários ciclos de reotimização, e mostrar isso dentro
de uma tela de estratégias nova (módulo → detalhe → variantes em uso).

**Architecture:** tabela nova `estrategia_variantes` (identidade que não
muda) + `mining_runs.variante_id` (a única coluna nova em tabela existente).
WFA e plano herdam a variante por cascata (`run_id → variante_id`), sem
coluna própria. Uma tela nova (`Estratégias`, quarto—na verdade quinto—modo
do topo) lista os módulos e, dentro de cada um, mostra as variantes com a
linha do tempo de ciclos.

**Tech Stack:** Python 3.12, DuckDB, Dash 4.4.1.

**Spec:** [docs/superpowers/specs/2026-09-23-identidade-estrategia-design.md](../specs/2026-09-23-identidade-estrategia-design.md)

## Global Constraints

- Nada em `core/` importa Dash.
- Teste nunca toca `data/database.duckdb`: sempre banco temporário.
- Python é `.venv/Scripts/python.exe`; testes com
  `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`.
- Commits: `git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit`.
- `nome` de variante é único **dentro da mesma estratégia**, não global.
- `variante_id` é `NULL` permitido no schema por segurança técnica (o
  `ALTER TABLE` não pode exigir valor em coluna nova), **mas isso não é
  licença para manter minerações antigas** — decisão do usuário
  (23/09/2026): apagar todas as minerações, WFAs e candidatas de antes
  desta implementação. Ver Task 6.
- Linguagem de tela em português simples, sem jargão.

---

### Task 1: schema + `core/variantes.py`

**Files:**
- Modify: `core/schema.sql`
- Create: `core/variantes.py`
- Test: `tests/test_variantes.py`

**Interfaces:**
- Produces: `variantes.criar(nome: str, estrategia: str) -> int`,
  `variantes.listar(estrategia: str | None = None) -> list[dict]`
  (`{"variante_id", "estrategia", "nome", "descricao", "criado_em"}`).

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_variantes.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import variantes  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    with db.connect() as con:
        db.init_schema(con)
    return tmp_path


def test_criar_devolve_id_e_listar_encontra(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    achadas = variantes.listar("rompimento_canal")
    assert [v["variante_id"] for v in achadas] == [vid]
    assert achadas[0]["nome"] == "conservadora"


def test_listar_sem_filtro_devolve_todas_as_estrategias(banco):
    variantes.criar("conservadora", "rompimento_canal")
    variantes.criar("padrao", "reversao_rsi")
    achadas = variantes.listar()
    assert {v["nome"] for v in achadas} == {"conservadora", "padrao"}


def test_nome_duplicado_na_mesma_estrategia_e_recusado(banco):
    variantes.criar("conservadora", "rompimento_canal")
    with pytest.raises(ValueError, match="já existe"):
        variantes.criar("conservadora", "rompimento_canal")


def test_nome_duplicado_em_estrategias_diferentes_e_aceito(banco):
    a = variantes.criar("conservadora", "rompimento_canal")
    b = variantes.criar("conservadora", "reversao_rsi")
    assert a != b
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_variantes.py -q`
Expected: FAIL com `ModuleNotFoundError: core.variantes` (ou tabela
inexistente, dependendo de qual passo falha primeiro).

- [ ] **Step 3: Schema**

Em `core/schema.sql`, perto de `planos_operacao` (mesmo padrão de
sequência dedicada):

```sql
CREATE TABLE IF NOT EXISTS estrategia_variantes (
    variante_id  BIGINT PRIMARY KEY,
    estrategia   VARCHAR NOT NULL,
    nome         VARCHAR NOT NULL,
    descricao    VARCHAR,
    criado_em    TIMESTAMP NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_variante_id START 1;

-- ligacao opcional: minerar sem escolher variante continua funcionando
ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS variante_id BIGINT;
```

- [ ] **Step 4: `core/variantes.py`**

```python
"""Identidade da estratégia através de ciclos de reotimização.

Reotimizar (minerar de novo, rodar o WFA de novo, gravar outro plano) não
deixa rastro de que aquilo é a MESMA estratégia de antes, só atualizada —
isso separa em `variantes`. A variante é escolhida na hora de salvar a
mineração; WFA e plano de operação herdam por cascata (run_id ->
variante_id), sem coluna própria — ver docs/superpowers/specs/
2026-09-23-identidade-estrategia-design.md.
"""
from __future__ import annotations

from datetime import datetime

from . import db_manager as db

_COLUNAS = ("variante_id", "estrategia", "nome", "descricao", "criado_em")


def criar(nome: str, estrategia: str, descricao: str | None = None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome da variante não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        existe = con.execute(
            "SELECT 1 FROM estrategia_variantes WHERE estrategia = ? "
            "AND nome = ?", [estrategia, nome]).fetchone()
        if existe:
            raise ValueError(
                f"já existe uma variante '{nome}' para {estrategia}")
        vid = con.execute(
            "SELECT nextval('seq_variante_id')").fetchone()[0]
        con.execute(
            "INSERT INTO estrategia_variantes "
            "(variante_id, estrategia, nome, descricao, criado_em) "
            "VALUES (?,?,?,?,?)",
            [vid, estrategia, nome, descricao, datetime.now()])
    return int(vid)


def listar(estrategia: str | None = None) -> list[dict]:
    onde, args = [], []
    if estrategia is not None:
        onde.append("estrategia = ?")
        args.append(estrategia)
    sql = (f"SELECT {', '.join(_COLUNAS)} FROM estrategia_variantes"
           + (" WHERE " + " AND ".join(onde) if onde else "")
           + " ORDER BY nome")
    with db.connect(read_only=True) as con:
        rows = con.execute(sql, args).fetchall()
    return [dict(zip(_COLUNAS, r)) for r in rows]
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_variantes.py -q`
Expected: 4 passed

- [ ] **Step 6: Provar que os testes pegam o defeito**

Trocar a checagem de duplicidade para comparar só `nome` (sem
`estrategia`) e conferir que `test_nome_duplicado_em_estrategias_diferentes_e_aceito`
falha; desfazer.

- [ ] **Step 7: Commit**

```bash
git add core/schema.sql core/variantes.py tests/test_variantes.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(variantes): estrategia_variantes, criar e listar"
```

---

### Task 2: `linha_do_tempo`

**Files:**
- Modify: `core/variantes.py`
- Test: `tests/test_variantes.py`

**Interfaces:**
- Consumes: tabelas `mining_runs`, `wfa_runs`, `planos_operacao` (já
  existem).
- Produces: `variantes.linha_do_tempo(variante_id: int) -> list[dict]`,
  uma linha por mineração vinculada, em ordem cronológica:
  `{"run_id", "criado_em", "n_combinacoes", "wfa_id", "plano_id",
  "plano_estado"}` (`wfa_id`/`plano_id`/`plano_estado` são `None` quando
  aquela mineração não tem WFA salvo, ou o WFA não tem plano).

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em tests/test_variantes.py
from datetime import datetime  # já deve estar no topo, ajustar imports

from core import plano  # noqa: E402


def _mineracao_no_banco(run_id, variante_id, symbol="WIN$N",
                        strategy="rompimento_canal", criado_em=None):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_runs (run_id, symbol, strategy, created_at, "
            "n_combinacoes, status, variante_id) VALUES (?,?,?,?,?,?,?)",
            [run_id, symbol, strategy, criado_em or datetime.now(),
             10, "concluida", variante_id])


def _wfa_no_banco(wfa_id, run_id, symbol="WIN$N",
                  strategy="rompimento_canal"):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
            "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])


def test_linha_do_tempo_em_ordem_cronologica(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid, criado_em=datetime(2026, 1, 1))
    _mineracao_no_banco(2, vid, criado_em=datetime(2026, 6, 1))

    linha = variantes.linha_do_tempo(vid)

    assert [l["run_id"] for l in linha] == [1, 2]
    assert linha[0]["wfa_id"] is None and linha[0]["plano_id"] is None


def test_linha_do_tempo_traz_wfa_e_plano_quando_existem(banco):
    vid = variantes.criar("conservadora", "rompimento_canal")
    _mineracao_no_banco(1, vid)
    _wfa_no_banco(10, 1)
    plano.salvar(
        wfa_id=10, run_id=1, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={}, profile={}, capital=100_000.0,
        contratos=1, risco_pedido_pct=1.0, risco_efetivo_pct=0.9,
        perda_referencia=300.0, de_onde="teste", margem=None,
        uso_margem_pct=50.0, camada4_travada=True, disjuntor={},
        expectativa={}, reotimizacao={}, definicoes={}, regua={})

    linha = variantes.linha_do_tempo(vid)

    assert linha[0]["wfa_id"] == 10
    assert linha[0]["plano_estado"] == "ativo"


def test_linha_do_tempo_so_traz_minerações_desta_variante(banco):
    vid_a = variantes.criar("conservadora", "rompimento_canal")
    vid_b = variantes.criar("agressiva", "rompimento_canal")
    _mineracao_no_banco(1, vid_a)
    _mineracao_no_banco(2, vid_b)

    linha = variantes.linha_do_tempo(vid_a)

    assert [l["run_id"] for l in linha] == [1]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_variantes.py -q`
Expected: FAIL com `AttributeError: module 'core.variantes' has no
attribute 'linha_do_tempo'`

- [ ] **Step 3: Implementar**

```python
# adicionar em core/variantes.py

def linha_do_tempo(variante_id: int) -> list[dict]:
    sql = """
        SELECT m.run_id, m.created_at, m.n_combinacoes,
               w.wfa_id, p.plano_id, p.estado
        FROM mining_runs m
        LEFT JOIN wfa_runs w ON w.run_id = m.run_id
        LEFT JOIN planos_operacao p ON p.wfa_id = w.wfa_id
            AND p.plano_id = (
                SELECT MAX(p2.plano_id) FROM planos_operacao p2
                WHERE p2.wfa_id = w.wfa_id
            )
        WHERE m.variante_id = ?
        ORDER BY m.created_at
    """
    with db.connect(read_only=True) as con:
        rows = con.execute(sql, [variante_id]).fetchall()
    return [
        {"run_id": r[0], "criado_em": r[1], "n_combinacoes": r[2],
         "wfa_id": r[3], "plano_id": r[4], "plano_estado": r[5]}
        for r in rows
    ]
```

Nota: o plano "mais recente por wfa_id" é o que interessa (ativo OU o
último aposentado, se nunca houve outro) — o `LEFT JOIN` casa pelo
`MAX(plano_id)`, não pelo `estado`. Casar por `estado` parece certo no
caso comum (só um plano `ativo` por `wfa_id`), mas duplica a linha
quando o `wfa_id` acumula dois planos `aposentado` (reotimizado mais de
uma vez, ou aposentado sem novo plano — `plano.aposentar()` existe
exatamente pra isso).

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_variantes.py -q`
Expected: 7 passed

- [ ] **Step 5: Provar que os testes pegam o defeito**

Trocar `ORDER BY m.created_at` por `ORDER BY m.run_id DESC` e conferir
que `test_linha_do_tempo_em_ordem_cronologica` falha (ordem invertida);
desfazer.

- [ ] **Step 6: Commit**

```bash
git add core/variantes.py tests/test_variantes.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(variantes): linha_do_tempo junta mineracao, wfa e plano"
```

---

### Task 3: ligar `variante_id` na gravação da mineração

**Files:**
- Modify: `core/optimizer.py`
- Test: `tests/test_salvar.py` (já existe e testa exatamente
  `Mineracao._persistir` — mesmo arquivo, mesmo estilo)

**Interfaces:**
- Consumes: nada de `core/variantes.py` diretamente — só grava o
  `variante_id` que já vier pronto (a escolha/criação acontece na UI,
  Task 4).
- Produces: `Mineracao.salvar(nome=None, criterios=None,
  variante_id=None)`, `Mineracao._persistir(nome, criterios=None,
  variante_id=None)`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_salvar.py`, usando os helpers já existentes no arquivo
(`mineracao_pronta`, `banco`):

```python
# adicionar em tests/test_salvar.py
def test_salvar_grava_variante_id_quando_informado(banco):
    m = mineracao_pronta()
    m._persistir("cruzamento tentativa 1", variante_id=7)

    with db.connect(read_only=True) as con:
        r = con.execute(
            "SELECT variante_id FROM mining_runs"
        ).fetchone()
    assert r[0] == 7


def test_salvar_sem_variante_grava_nulo(banco):
    m = mineracao_pronta()
    m._persistir(None)

    with db.connect(read_only=True) as con:
        r = con.execute(
            "SELECT variante_id FROM mining_runs"
        ).fetchone()
    assert r[0] is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_salvar.py -q`
Expected: `test_salvar_grava_variante_id_quando_informado` falha com
`TypeError: _persistir() got an unexpected keyword argument
'variante_id'`; `test_salvar_sem_variante_grava_nulo` provavelmente já
passa sem mudar nada (a coluna ainda não existe até a Task 1 rodar — se
este arquivo for escrito antes da Task 1 estar commitada, vai falhar com
"coluna não encontrada" em vez de `TypeError`; qualquer um dos dois é a
falha esperada neste passo).

- [ ] **Step 3: Implementar**

Em `core/optimizer.py`, no método `salvar`:

```python
def salvar(self, nome: str | None = None,
           criterios: dict | None = None,
           variante_id: int | None = None) -> bool:
    if not self.pode_salvar:
        return False
    self.estado["salvando"] = True
    self.estado["aviso_salvar"] = "salvando…"
    threading.Thread(target=self._persistir,
                     args=(nome, criterios, variante_id),
                     daemon=True).start()
    return True
```

E em `_persistir`, acrescentar o parâmetro e a coluna no INSERT nomeado
(a lista de colunas já é nomeada, não posicional — ver comentário
existente no arquivo):

```python
def _persistir(self, nome: str | None, criterios: dict | None = None,
               variante_id: int | None = None):
    ...
    con.execute(
        "INSERT INTO mining_runs (run_id, symbol, strategy, "
        "created_at, profile, space, folds, holdout_de, "
        "n_combinacoes, status, nome, wf_config, criterios, "
        "variante_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [run_id, ctx["symbol"], ctx["estrategia"], datetime.now(),
         json.dumps(ctx["perfil"], default=str),
         json.dumps({k: list(map(float, v))
                     for k, v in ctx["espaco"].items()}),
         json.dumps([asdict(f) for f in ctx["janelas"].folds], default=str),
         str(ctx["janelas"].holdout_de), len(self._resultados), status,
         nome or None,
         json.dumps(ctx.get("wf_config") or {}, default=str),
         json.dumps(criterios) if criterios else None,
         variante_id],
    )
```

(a lista de valores muda de tamanho — conferir com `Read` o trecho
completo do `_persistir` antes de editar, o snippet acima mostra só as
linhas que mudam)

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_salvar.py -q`
Expected: todos os testes do arquivo passam, incluindo os dois novos.

- [ ] **Step 5: Provar que os testes pegam o defeito**

Remover `variante_id` da lista de valores do INSERT (mas deixar na lista
de colunas) — o `_persistir` deve estourar com erro de contagem de
parâmetros, provando que o teste depende de verdade da coluna nova;
desfazer.

- [ ] **Step 6: Commit**

```bash
git add core/optimizer.py tests/test_salvar.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(variantes): mineracao grava variante_id quando informado"
```

---

### Task 4: dropdown de variante na tela de Mineração

**Files:**
- Modify: `ui/components/mining.py`
- Modify: `ui/callbacks.py`
- Test: `tests/test_callbacks_sem_ciclo.py` (continuar passando)

**Interfaces:**
- Consumes: `core.variantes.listar`, `core.variantes.criar`.

- [ ] **Step 1: os campos novos**

Em `ui/components/mining.py`, ao lado de `mine-nome` (linha ~119):

```python
            html.Div([
                dcc.Input(id="mine-nome", type="text", className="inp",
                          placeholder="nome da mineração", debounce=True),
                dcc.Dropdown(id="mine-variante", className="dd dd-sm",
                            placeholder="variante (opcional)",
                            options=[], clearable=True),
                dcc.Input(id="mine-variante-nova", type="text",
                          className="inp", debounce=True,
                          placeholder="ou nome de variante nova"),
                html.Button("Salvar", id="btn-salvar", n_clicks=0,
                            className="btn-ghost btn-salvar", disabled=True),
            ], className="acoes acoes-salvar"),
```

- [ ] **Step 2: popular o dropdown quando a estratégia muda**

Em `ui/callbacks.py`, um callback novo (perto do de `salvar`, linha
~763):

```python
    @app.callback(
        Output("mine-variante", "options"),
        Input("estrategia", "value"),
    )
    def variantes_da_estrategia(modulo):
        if not modulo:
            return []
        from core import variantes as V
        return [{"label": v["nome"], "value": v["variante_id"]}
                for v in V.listar(modulo)]
```

(`if not modulo: return []` — sem isso, `V.listar(None)` devolve TODAS as
variantes de todas as estratégias, achado real na revisão do agente antes
do commit desta tarefa)

- [ ] **Step 3: usar no clique de Salvar**

Modificar o callback `salvar` (linha ~764-773):

```python
    @app.callback(Output("btn-salvar", "n_clicks"),
                  Input("btn-salvar", "n_clicks"), State("mine-nome", "value"),
                  State("mine-variante", "value"),
                  State("mine-variante-nova", "value"),
                  State("estrategia", "value"),
                  *[State(f"crit-{c['id']}", "value") for c in MS.CRITERIOS],
                  prevent_initial_call=True)
    def salvar(n, nome, variante_id, variante_nova, modulo, *limites):
        from core import variantes as V
        nova = (variante_nova or "").strip()
        if nova:
            try:
                variante_id = V.criar(nova, modulo)
            except ValueError as erro:
                MINERACAO.estado["aviso_salvar"] = f"falhou ao salvar: {erro}"
                return 0
        # os critérios vão junto: o walk-forward desta mineração os aplica
        # dentro de cada janela IS
        MINERACAO.salvar((nome or "").strip() or None,
                         {c["id"]: v for c, v in zip(MS.CRITERIOS, limites)},
                         variante_id)
        return 0
```

(o `try/except` em volta de `V.criar` é o achado real da revisão: sem ele,
digitar o nome de uma variante que já existe para a mesma estratégia
estourava `ValueError` sem tratamento dentro do callback — a mensagem
`"falhou ao salvar: …"` segue o mesmo padrão que `_persistir` já usa para
erros de gravação, exibida via `estado_salvar`)

- [ ] **Step 4: rodar a suíte inteira, inclusive o teste de ciclo**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
Expected: tudo continua passando; `test_callbacks_sem_ciclo.py` prova que
`mine-variante` e `mine-variante-nova` têm dono só.

- [ ] **Step 5: conferência manual, na tela**

Subir o app, escolher uma estratégia, minerar (ou carregar mineração
salva), digitar um nome em "ou nome de variante nova", clicar Salvar,
conferir no banco que `mining_runs.variante_id` gravou. Trocar de
estratégia e conferir que o dropdown de variante muda de opções.

- [ ] **Step 6: Commit**

```bash
git add ui/components/mining.py ui/callbacks.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(variantes): dropdown de variante na tela de mineracao"
```

---

### Task 5: quinto modo — tela de Estratégias (lista)

**Files:**
- Create: `ui/components/estrategias_panel.py`
- Create: `ui/callbacks_estrategias.py`
- Modify: `ui/app.py` (topbar — novo item no `RadioItems`; `painel()` —
  novo `html.Div#painel-estrategias`)
- Modify: `ui/callbacks.py` (callback `modo` ganha o quinto caso; registrar
  `callbacks_estrategias`)
- Test: `tests/test_callbacks_sem_ciclo.py`

**Interfaces:**
- Consumes: `strategies.registry.descobrir()`, `core.variantes.listar`.

- [ ] **Step 1: o item no topo**

Em `ui/app.py`, dentro de `topbar()`:

```python
                    dcc.RadioItems(
                        id="modo", value="backtest", className="modo",
                        options=[{"label": "Backtest", "value": "backtest"},
                                 {"label": "Mineração", "value": "mineracao"},
                                 {"label": "Walk-Forward", "value": "wfa"},
                                 {"label": "Candidata", "value": "candidata"},
                                 {"label": "Estratégias", "value": "estrategias"}],
                    ),
```

- [ ] **Step 2: o componente da lista**

```python
# ui/components/estrategias_panel.py
"""Lista de estratégias e, dentro de cada uma, as variantes em uso.

Só a fatia de identidade (projeto D, parte 1) — metadados ricos por
estratégia (autor, perfil, o que cada parâmetro faz) ficam de fora, ver
docs/superpowers/specs/2026-09-23-identidade-estrategia-design.md §2.
"""
from __future__ import annotations

from dash import dcc, html


def painel():
    return html.Div(
        [
            html.Section([
                html.H2("Estratégias", className="panel-title"),
                html.Div(id="est-lista", className="est-lista"),
            ], className="panel"),
            html.Section(
                id="est-detalhe", className="panel", style={"display": "none"},
                children=[
                    html.H3(id="est-detalhe-titulo"),
                    html.Div(id="est-variantes"),
                ],
            ),
        ],
        id="painel-estrategias", className="modo-bloco",
        style={"display": "none"},
    )


def cartao_estrategia(modulo: str, label: str, n_params: int) -> html.Div:
    return html.Div(
        [html.Span(label, className="est-cartao-nome"),
         html.Span(f"{n_params} parâmetros", className="est-cartao-nota")],
        id={"type": "est-cartao", "modulo": modulo},
        className="est-cartao", n_clicks=0,
    )


def linha_variante(nome: str, ciclos: list[dict]) -> html.Div:
    ativo = next((c for c in reversed(ciclos) if c.get("plano_estado") == "ativo"), None)
    nota = (f"plano ativo (mineração #{ativo['run_id']})" if ativo
            else f"{len(ciclos)} ciclo(s), sem plano ativo" if ciclos
            else "sem minerações ainda")
    return html.Div(
        [html.Span(nome, className="est-variante-nome"),
         html.Span(nota, className="est-variante-nota")],
        className="est-variante",
    )
```

- [ ] **Step 3: o callback**

```python
# ui/callbacks_estrategias.py
"""Callbacks da tela Estratégias — lista de módulos e variantes em uso."""
from __future__ import annotations

from dash import Input, Output, State, ALL, html, no_update

from core import variantes as V
from strategies import registry

from .components import estrategias_panel as EP


def register(app):
    @app.callback(
        Output("est-lista", "children"),
        Input("modo", "value"),
    )
    def listar_estrategias(modo):
        if modo != "estrategias":
            return no_update
        return [EP.cartao_estrategia(e["modulo"], e["label"], e["n_params"])
                for e in registry.descobrir()]

    @app.callback(
        Output("est-detalhe", "style"),
        Output("est-detalhe-titulo", "children"),
        Output("est-variantes", "children"),
        Input({"type": "est-cartao", "modulo": ALL}, "n_clicks"),
        State({"type": "est-cartao", "modulo": ALL}, "id"),
        prevent_initial_call=True,
    )
    def abrir_detalhe(cliques, ids):
        if not any(cliques):
            return {"display": "none"}, no_update, no_update
        modulo = next(i["modulo"] for i, n in zip(ids, cliques) if n)
        vs = V.listar(modulo)
        if not vs:
            corpo = html.P("nenhuma variante ainda para esta estratégia.")
        else:
            corpo = [EP.linha_variante(v["nome"], V.linha_do_tempo(v["variante_id"]))
                     for v in vs]
        rotulo = next((e["label"] for e in registry.descobrir()
                      if e["modulo"] == modulo), modulo)
        return {"display": "block"}, rotulo, corpo
```

- [ ] **Step 4: ligar no `modo` e registrar**

Em `ui/app.py`, dentro de `painel()`, depois de `candidata_panel.painel()`:

```python
            estrategias_panel.painel(),
```

(lembrar de importar `estrategias_panel` no topo do arquivo, junto dos
outros componentes)

Em `ui/callbacks.py`, o callback `modo` (linha ~305-344) ganha o quinto
`Output` e o quinto `v(...)`:

```python
    @app.callback(
        Output("painel-backtest", "style"), Output("painel-mineracao", "style"),
        Output("painel-wfa", "style"), Output("painel-candidata", "style"),
        Output("painel-estrategias", "style"),
        Output("acao-backtest", "style"), Output("sec-mineracao", "style"),
        Output("sidebar", "style"),
        Input("modo", "value"),
    )
    def modo(qual):
        ...
        return (v(qual == "backtest"), v(qual == "mineracao"), v(qual == "wfa"),
                v(qual == "candidata"), v(qual == "estrategias"),
                VISIVEL if qual == "backtest" else OCULTO,
                VISIVEL if qual == "mineracao" else OCULTO,
                OCULTO if qual in ("wfa", "candidata", "estrategias")
                else {"display": "block"})
```

E, perto do fim do arquivo (onde `callbacks_candidata`/`callbacks_mt5` já
são registrados):

```python
    from ui import callbacks_estrategias
    callbacks_estrategias.register(app)
```

- [ ] **Step 5: CSS mínimo**

Em `ui/assets/style.css`, seguindo o padrão de `.cand-*`/`.mz-*` já
existentes (cores e espaçamento das variáveis do arquivo, não valores
novos):

```css
.est-lista{display:flex;flex-wrap:wrap;gap:10px;}
.est-cartao{padding:12px 16px;border:1px solid var(--line);border-radius:8px;
  cursor:pointer;display:flex;flex-direction:column;gap:4px;}
.est-cartao-nome{font-weight:600;}
.est-cartao-nota{font-size:.85em;color:var(--muted);}
.est-variante{display:flex;justify-content:space-between;padding:8px 0;
  border-bottom:1px solid var(--line);}
.est-variante-nota{color:var(--muted);font-size:.9em;}
```

- [ ] **Step 6: rodar a suíte inteira, inclusive o teste de ciclo**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
Expected: tudo passa; `test_callbacks_sem_ciclo.py` prova que os `Output`s
novos têm dono só.

- [ ] **Step 7: conferência manual, na tela**

Subir o app, clicar em "Estratégias", ver a lista de módulos. Clicar num
cartão, ver "nenhuma variante ainda" (banco limpo) ou a lista de
variantes, se já tiver criado alguma na Task 4.

- [ ] **Step 8: Commit**

```bash
git add ui/components/estrategias_panel.py ui/callbacks_estrategias.py ui/app.py ui/callbacks.py ui/assets/style.css
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(variantes): tela de Estrategias, lista de modulos e variantes em uso"
```

---

### Task 6: apagar minerações, WFAs e candidatas de antes da identidade

**Por quê:** decisão do usuário (23/09/2026) — o controle de variante só
vale para o que for criado a partir desta implementação; não vale a pena
marcar retroativamente o que já existe (spec §2), então o combinado é
apagar, não manter como "sem variante" para sempre. Isso inclui as
minerações/WFAs usadas na auditoria da Tarefa 9 do projeto Candidata
(walk-forwards #8/#10/#11) — elas já cumpriram o papel de auditoria e
ficaram documentadas em `docs/PLANO-CANDIDATA.md`; os números não somem,
só o registro no banco.

**Files:**
- Create: `scripts/limpar_minerações_antigas.py` (script único, descartável
  depois de rodado — não faz parte do produto)

**Interfaces:**
- Consumes: nenhuma função nova — só `DELETE` nas tabelas existentes.

- [ ] **Step 1: conferir com o usuário, na tela, antes de rodar**

Antes de tocar no banco real (`data/database.duckdb`, não um banco de
teste), mostrar a contagem atual de linhas em `mining_runs`, `wfa_runs`,
`planos_operacao` e pedir confirmação explícita — apagar é irreversível
e este é o banco de produção, não um teste.

```python
# scripts/limpar_minerações_antigas.py
from core import db_manager as db

with db.connect(read_only=True) as con:
    for t in ("mining_runs", "wfa_runs", "planos_operacao"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n} linha(s)")
```

Run: `.venv\Scripts\python.exe scripts\limpar_minerações_antigas.py`

- [ ] **Step 2: apagar, em ordem segura de dependência**

Ordem: tabelas-filha antes das tabelas-pai (`mining_trials`/`wfa_trades`
antes de `mining_runs`/`wfa_runs`; `planos_operacao` antes de `wfa_runs`
pois referencia `wfa_id`).

```python
# acrescentar em scripts/limpar_minerações_antigas.py
with db.connect_write() as con, db.transacao(con):
    for t in ("mining_trials", "wfa_trades", "planos_operacao",
              "wfa_runs", "mining_runs"):
        con.execute(f"DELETE FROM {t}")
print("apagado.")
```

- [ ] **Step 3: rodar contra o banco real**

Run: `.venv\Scripts\python.exe scripts\limpar_minerações_antigas.py`
(rodar de novo, agora com o `DELETE` incluído — só depois da confirmação
do Step 1)
Expected: contagens exibidas voltam a 0 numa nova checagem.

- [ ] **Step 4: conferência manual, na tela**

Subir o app, abrir Mineração/Walk-Forward/Candidata — as listas devem
aparecer vazias, prontas para o primeiro ciclo já com variante.

- [ ] **Step 5: remover o script descartável**

```bash
rm scripts/limpar_minerações_antigas.py
```

(o script não é commitado — existiu só para rodar uma vez contra o banco
real; se algo der errado no Step 3, é mais seguro poder editá-lo à vontade
sem afetar o histórico do git)

---

## Conferência do plano contra a spec

| spec | tarefa |
|---|---|
| §4 arquitetura (tabela nova, cascata sem coluna própria) | 1, 3 |
| §5 modelo de dados | 1 |
| §6 `linha_do_tempo` | 2 |
| §3 decisão 2 (variante escolhida na mineração) | 3, 4 |
| §3 decisão 4 (dentro da tela de estratégias, sem metadados ricos) | 5 |
| §7 testes | 1, 2, 3, 5 (ciclo) |
| §8 fora de escopo | nenhuma tarefa toca portfólio/gatilho/sinais ao vivo |
| §2 (não vale marcar retroativamente; usuário pode apagar) | 6 |
