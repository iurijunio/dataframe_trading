# Gatilho de reotimização (projeto D, parte 3) — Plano de implementação

> **Para agentes:** cada tarefa é executada uma de cada vez, **sem agente
> executor** (o desenvolvedor implementa em pessoa, nesta sessão), e um
> agente é chamado só para **revisar** cada tarefa pronta antes do commit —
> mesma preferência já registrada nos planos anteriores do projeto D.

**Goal:** avisar, num selo no topo da tela, quando um plano de operação
ativo está com `reotimizar_em` vencido ou perto de vencer (7 dias).

**Architecture:** uma função nova em `core/plano.py` (`vencendo`), sem
tabela nem coluna nova — `reotimizar_em` já existe. Um selo no `topbar()`
ao lado do botão de sincronizar MT5, calculado uma vez por carregamento
de página/troca de modo (sem `dcc.Interval` novo).

**Tech Stack:** Python 3.12, DuckDB, Dash 4.4.1.

**Spec:** [docs/superpowers/specs/2026-09-24-gatilho-reotimizacao-design.md](../specs/2026-09-24-gatilho-reotimizacao-design.md)

## Global Constraints

- Nada em `core/` importa Dash.
- Teste nunca toca `data/database.duckdb`: sempre banco temporário.
- Python é `.venv/Scripts/python.exe`; testes com
  `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`.
- Commits: `git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit`.
- `vencendo()` não muda como `reotimizar_em` é calculado — só lê.
- Selo não aparece quando não há nada pendente (sem poluição visual).
- Linguagem de tela em português simples, sem jargão.

---

### Task 1: `plano.vencendo`

**Files:**
- Modify: `core/plano.py`
- Test: `tests/test_plano.py`

**Interfaces:**
- Produces: `plano.vencendo(dias_aviso: int = 7, hoje: date | None = None)
  -> list[dict]` (`{"plano_id", "nome", "symbol", "strategy",
  "variante_nome", "reotimizar_em", "dias_restantes"}`, ordenado por
  `reotimizar_em` crescente — o mais vencido primeiro).

- [ ] **Step 1: Escrever o teste que falha**

Trocar a linha de import do topo de `tests/test_plano.py`:

```python
from core import optimizer, plano, wfa_store          # como já está
```

por:

```python
from core import optimizer, plano, variantes, wfa_store
```

E acrescentar, no topo do arquivo (junto dos outros imports de
biblioteca padrão):

```python
from datetime import date, timedelta
```

E, mais abaixo, os testes e o helper novo:

```python
# adicionar em tests/test_plano.py
def _plano_ativo(plano_id, reotimizar_em, variante_id=None,
                 run_id=None, wfa_id=None, symbol="WIN$N",
                 strategy="rompimento_canal"):
    """Grava um plano_operacao 'ativo' direto no banco, com a cascata
    mining_runs -> wfa_runs -> planos_operacao (ou sem ela, se run_id/
    wfa_id vierem None - simula mineração/wfa apagados)."""
    with db.connect_write() as con:
        if run_id is not None:
            con.execute(
                "INSERT INTO mining_runs (run_id, symbol, strategy, "
                "created_at, n_combinacoes, status, variante_id) "
                "VALUES (?,?,?,?,?,?,?)",
                [run_id, symbol, strategy, "2026-01-01", 10, "concluida",
                 variante_id])
        if wfa_id is not None:
            con.execute(
                "INSERT INTO wfa_runs (wfa_id, run_id, symbol, strategy) "
                "VALUES (?,?,?,?)", [wfa_id, run_id, symbol, strategy])
        con.execute(
            "INSERT INTO planos_operacao (plano_id, wfa_id, symbol, "
            "strategy, nome, estado, reotimizar_em) VALUES (?,?,?,?,?,?,?)",
            [plano_id, wfa_id, symbol, strategy, "teste", "ativo",
             reotimizar_em])


def test_vencendo_plano_no_passado_tem_dias_restantes_negativo(banco):
    hoje = date(2026, 9, 24)
    _plano_ativo(1, hoje - timedelta(days=4))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)

    assert len(v) == 1
    assert v[0]["plano_id"] == 1
    assert v[0]["dias_restantes"] == -4


def test_vencendo_dentro_da_janela_aparece(banco):
    hoje = date(2026, 9, 24)
    _plano_ativo(1, hoje + timedelta(days=5))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert [p["plano_id"] for p in v] == [1]


def test_vencendo_fora_da_janela_nao_aparece(banco):
    hoje = date(2026, 9, 24)
    _plano_ativo(1, hoje + timedelta(days=30))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert v == []


def test_vencendo_ignora_plano_aposentado(banco):
    hoje = date(2026, 9, 24)
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO planos_operacao (plano_id, symbol, strategy, "
            "nome, estado, reotimizar_em) VALUES (?,?,?,?,?,?)",
            [1, "WIN$N", "rompimento_canal", "teste", "aposentado",
             hoje - timedelta(days=10)])

    assert plano.vencendo(dias_aviso=7, hoje=hoje) == []


def test_vencendo_ignora_plano_sem_reotimizar_em(banco):
    hoje = date(2026, 9, 24)
    _plano_ativo(1, None)
    assert plano.vencendo(dias_aviso=7, hoje=hoje) == []


def test_vencendo_traz_nome_da_variante(banco):
    hoje = date(2026, 9, 24)
    vid = variantes.criar("conservadora", "rompimento_canal")
    _plano_ativo(1, hoje - timedelta(days=1), variante_id=vid,
                run_id=10, wfa_id=100)

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert v[0]["variante_nome"] == "conservadora"


def test_vencendo_sem_variante_traz_none(banco):
    hoje = date(2026, 9, 24)
    _plano_ativo(1, hoje - timedelta(days=1), run_id=10, wfa_id=100)

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert v[0]["variante_nome"] is None


def test_vencendo_ordenado_pelo_mais_vencido_primeiro(banco):
    hoje = date(2026, 9, 24)
    _plano_ativo(1, hoje - timedelta(days=1))
    _plano_ativo(2, hoje - timedelta(days=10))

    v = plano.vencendo(dias_aviso=7, hoje=hoje)
    assert [p["plano_id"] for p in v] == [2, 1]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plano.py -q -k vencendo`
Expected: FAIL com `AttributeError: module 'core.plano' has no attribute
'vencendo'`

- [ ] **Step 3: Implementar**

Trocar a linha de import do topo do arquivo:

```python
from datetime import date, datetime          # como já está
```

por:

```python
from datetime import date, datetime, timedelta
```

E acrescentar, no fim do arquivo:

```python
# adicionar em core/plano.py
def vencendo(dias_aviso: int = 7, hoje: date | None = None) -> list[dict]:
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=dias_aviso)
    sql = """
        SELECT p.plano_id, p.nome, p.symbol, p.strategy, p.reotimizar_em,
               ev.nome
        FROM planos_operacao p
        LEFT JOIN wfa_runs w ON w.wfa_id = p.wfa_id
        LEFT JOIN mining_runs m ON m.run_id = w.run_id
        LEFT JOIN estrategia_variantes ev ON ev.variante_id = m.variante_id
        WHERE p.estado = 'ativo'
          AND p.reotimizar_em IS NOT NULL
          AND p.reotimizar_em <= ?
        ORDER BY p.reotimizar_em
    """
    with db.connect(read_only=True) as con:
        rows = con.execute(sql, [limite]).fetchall()
    return [
        {"plano_id": r[0], "nome": r[1], "symbol": r[2], "strategy": r[3],
         "reotimizar_em": r[4], "variante_nome": r[5],
         "dias_restantes": (r[4] - hoje).days}
        for r in rows
    ]
```


- [ ] **Step 4: Rodar e ver passar**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plano.py -q -k vencendo`
Expected: 8 passed

- [ ] **Step 5: Provar que os testes pegam o defeito**

Trocar `p.reotimizar_em <= ?` por `p.reotimizar_em < ?` (estrito) e
conferir que algum teste de borda muda de comportamento — se nenhum dos
testes atuais pegar (a janela de 7 dias não bate exatamente na borda),
ajustar temporariamente `test_vencendo_dentro_da_janela_aparece` para
`hoje + timedelta(days=7)` (exatamente no limite) e confirmar que ele
falha com o operador estrito; desfazer os dois.

- [ ] **Step 6: Commit**

```bash
git add core/plano.py tests/test_plano.py
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(gatilho): plano.vencendo acha planos ativos vencidos ou proximos"
```

---

### Task 2: selo no topbar

**Files:**
- Modify: `ui/app.py` (topbar — selo + dropdown)
- Modify: `ui/callbacks.py` (dois callbacks novos: montar o selo,
  abrir/fechar a lista)
- Modify: `ui/assets/style.css`
- Test: `tests/test_callbacks_sem_ciclo.py`

**Interfaces:**
- Consumes: `core.plano.vencendo()`.

- [ ] **Step 1: os elementos no topo**

Em `ui/app.py`, dentro de `topbar()`, ao lado do bloco de sincronizar
MT5:

```python
            html.Div(
                [
                    html.Button(id="reotimizar-selo",
                                className="reotimizar-selo", n_clicks=0,
                                style={"display": "none"}),
                    html.Div(id="reotimizar-lista",
                             className="reotimizar-lista",
                             style={"display": "none"}),
                ],
                className="reotimizar-wrap",
            ),
```

(inserir este bloco antes do `html.Div(className="mt5-sync-wrap", ...)`
existente, dentro da mesma lista de filhos do `html.Header`)

- [ ] **Step 2: montar o selo**

Em `ui/callbacks.py`, um callback novo (perto de `variantes_da_estrategia`
ou de outro callback simples já existente):

```python
    @app.callback(
        Output("reotimizar-selo", "children"),
        Output("reotimizar-selo", "className"),
        Output("reotimizar-selo", "style"),
        Output("reotimizar-lista", "children"),
        Input("modo", "value"),
    )
    def montar_selo_reotimizar(_qual):
        from core import plano as PL
        itens = PL.vencendo()
        if not itens:
            return "", "reotimizar-selo", {"display": "none"}, []

        vencidos = any(i["dias_restantes"] < 0 for i in itens)
        cor = "reotimizar-selo vencido" if vencidos else "reotimizar-selo proximo"
        linhas = [
            html.Div(
                f"{i['variante_nome'] or 'sem variante'} · {i['strategy']} · "
                + (f"venceu há {-i['dias_restantes']} dia(s)"
                   if i["dias_restantes"] < 0
                   else f"vence em {i['reotimizar_em']:%d/%m}"),
                className="reotimizar-item",
            )
            for i in itens
        ]
        return str(len(itens)), cor, {"display": "inline-flex"}, linhas
```

(`html` já está importado em `ui/callbacks.py` — conferir com `Grep`
antes de editar, para não duplicar import)

- [ ] **Step 3: abrir/fechar a lista**

```python
    @app.callback(
        Output("reotimizar-lista", "style"),
        Input("reotimizar-selo", "n_clicks"),
        State("reotimizar-lista", "style"),
        prevent_initial_call=True,
    )
    def alternar_lista_reotimizar(_n, estilo):
        aberto = (estilo or {}).get("display") == "block"
        return {"display": "none" if aberto else "block"}
```

Nota: este callback só existe DEPOIS que `montar_selo_reotimizar` já
rodou pelo menos uma vez (senão `reotimizar-lista` ainda não tem
`style` diferente de `{"display": "none"}` do layout inicial) — o
comportamento correto (alternar entre oculto e visível) já cobre isso
naturalmente, sem precisar de nenhuma ordem especial entre os dois
callbacks.

- [ ] **Step 4: CSS**

Em `ui/assets/style.css`, seguindo o padrão de `.mt5-sync-*` já
existente:

```css
.reotimizar-wrap{position:relative;margin-left:12px;}
.reotimizar-selo{border:none;border-radius:999px;padding:4px 10px;
  font-family:var(--mono);font-weight:600;font-size:.85em;cursor:pointer;}
.reotimizar-selo.proximo{background:rgba(255,201,60,.18);color:var(--warn);}
.reotimizar-selo.vencido{background:rgba(255,77,125,.18);color:var(--neg);}
.reotimizar-lista{position:absolute;top:100%;right:0;margin-top:6px;
  background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:8px;min-width:260px;z-index:20;}
.reotimizar-item{padding:6px 4px;font-size:.85em;border-bottom:1px solid var(--line);}
.reotimizar-item:last-child{border-bottom:none;}
```

- [ ] **Step 5: rodar a suíte inteira, inclusive o teste de ciclo**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
Expected: tudo passa; `test_callbacks_sem_ciclo.py` prova que os
`Output`s novos têm dono só.

- [ ] **Step 6: conferência manual, na tela**

Subir o app. Com o banco real sem planos vencidos, o selo não deve
aparecer. Para conferir o caminho "com aviso", gravar um plano de teste
com `reotimizar_em` no passado direto no banco (via script Python
descartável, igual ao usado na Tarefa 6 do plano de identidade da
estratégia), recarregar a tela, conferir que o selo aparece vermelho com
a contagem certa, clicar e ver a lista, depois apagar o plano de teste
do banco real.

- [ ] **Step 7: Commit**

```bash
git add ui/app.py ui/callbacks.py ui/assets/style.css
git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit -m "feat(gatilho): selo de reotimizacao vencida/proxima no topbar"
```

---

## Conferência do plano contra a spec

| spec | tarefa |
|---|---|
| §4 arquitetura (`vencendo`, sem tabela/coluna nova) | 1 |
| §5 `vencendo` (janela, ordenação, variante opcional) | 1 |
| §3 decisões 2-3 (selo no topbar, dropdown ao clicar) | 2 |
| §3 decisão 4 (janela de 7 dias) | 1 |
| §3 decisão 5 (sem atualização automática — recalcula por `Input("modo")`) | 2 |
| §6 tela (cor âmbar/vermelha, selo some quando vazio) | 2 |
| §7 testes | 1 (ciclo: 2) |
| §8 fora de escopo | nenhuma tarefa toca correlação de portfólio ou snooze |
