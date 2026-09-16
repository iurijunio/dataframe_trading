# Modo Candidata — plano de execução, parte 1 (fases 0 a 2)

> **Para quem executa:** implemente tarefa por tarefa, na ordem. Cada passo é
> uma ação de 2 a 5 minutos. Os passos usam caixas (`- [ ]`) para marcar o que
> já foi feito. Não pule o passo de rodar o teste e vê-lo **falhar**: é ele que
> prova que o teste testa alguma coisa.

**Objetivo:** pôr no ar o quarto modo da plataforma — Candidata — com a
robustez calculada sobre a curva fora da amostra, usando bootstrap estacionário
em vez de permutação, mais o platô do parâmetro e o teste de entrada aleatória.

**Arquitetura:** `core/` guarda contas puras (sem Dash, sem banco na assinatura);
`ui/callbacks_candidata.py` liga a tela; o banco ganha as colunas que faltam em
`wfa_runs` para a tela não depender da mineração de origem. Cada bloco da tela
degrada sozinho quando falta dado.

**Ferramentas:** Python 3.11, numpy, DuckDB, Dash 4.4.1, dash-ag-grid, Numba,
pytest. **Não há scipy no projeto, de propósito** — `core/robustez.py` usa
`math.erfc`. Não instale scipy.

**Desenho:** [PLANO-CANDIDATA.md](PLANO-CANDIDATA.md) — leia antes de começar.
Este plano argumenta a partir dele; onde houver divergência, o desenho manda.

## Restrições globais

- Código, nomes de função, comentários e textos de tela em **português**.
- Comentário explica **por que**, nunca o que a linha faz. Siga o tom dos
  módulos existentes (`core/wfa.py` é a referência).
- Toda métrica nova na tela precisa de um (?) com faixa boa e ruim.
- Nada em `core/` importa Dash.
- Nenhum teste toca o banco real `data/database.duckdb`.
- Rodar a suíte inteira antes de cada commit: `.venv/Scripts/python.exe -m pytest -q`.
- Base de teste: `WIN$N`, 16/03/2021 a 13/03/2026. Capital padrão R$ 10.000.
- A parte 2 (fases 3 a 6: sorte, SPA, holdout, plano de operação) vira plano
  próprio **depois** da tarefa 11, porque a tarefa 9 mede uma coisa que decide
  o desenho dela.

---

### Tarefa 1: Repositório git

Hoje a pasta não é repositório. Sem histórico, as tarefas seguintes não têm
onde commitar e não há como voltar atrás. Se você preferir seguir sem git,
pule esta tarefa e ignore os passos "Commit" das demais.

**Arquivos:**
- Criar: `.gitignore`

- [ ] **Passo 1: Criar o `.gitignore`**

```
.venv/
__pycache__/
*.pyc
data/database.duckdb
data/database.duckdb.wal
data/parquet/
data/raw/
TEST$N/
WIN$N/
```

O banco fica de fora: ele tem 688 mil barras e é dado, não código. Os CSVs
brutos também — a METODOLOGIA já manda guardá-los fora da máquina.

- [ ] **Passo 2: Iniciar e commitar**

```bash
git init && git add -A && git commit -m "chore: estado inicial antes do modo Candidata"
```

- [ ] **Passo 3: Conferir**

Run: `git log --oneline && git status --short`
Esperado: um commit, nada pendente.

---

### Tarefa 2: `wfa_runs` guarda perfil, capital e os sharpes da matriz

Hoje a tabela não tem capital nem perfil de execução. A Candidata precisa dos
dois para Monte Carlo, dimensionamento e portão de capital — e hoje eles vêm
da mineração, que pode não existir mais.

**Arquivos:**
- Modificar: `core/schema.sql` (bloco de ALTER, junto da linha 152)
- Modificar: `core/wfa_store.py` (`salvar`, `detalhes`)
- Testar: `tests/test_wfa_store.py`

**Interfaces:**
- Consome: nada.
- Produz: `wfa_store.salvar(..., profile: dict | None = None, capital: float | None = None, sharpes_matriz: list[float] | None = None)`; `wfa_store.detalhes(wfa_id)` passa a devolver as chaves `profile`, `capital` e `sharpes_matriz` (None quando o registro é antigo).

- [ ] **Passo 1: Escrever o teste que falha**

Em `tests/test_wfa_store.py`, no fim do arquivo:

```python
def test_salvar_guarda_perfil_capital_e_sharpes(tmp_path, monkeypatch):
    """A Candidata lê só wfa_runs + wfa_trades. Se o capital vier da
    mineração, apagar a mineração derruba o dimensionamento."""
    _banco_temporario(tmp_path, monkeypatch)
    wfa_id = wfa_store.salvar(
        run_id=1, symbol="WIN$N", strategy="teste", nome="x",
        is_meses=12, oos_meses=6, inteligencia="sharpe", holdout=False,
        agregado={"steps": 2, "oos_lucro": 100.0, "oos_trades": 10,
                  "wfe_global": 1.0, "consistencia_lucro": 50.0,
                  "dd_oos": 10.0},
        veredito={"estado": "aprovado"}, passos=[],
        profile={"capital_inicial": 10_000.0, "timeframe": "M15"},
        capital=10_000.0, sharpes_matriz=[0.8, 1.1, 0.4])

    d = wfa_store.detalhes(wfa_id)
    assert d["capital"] == 10_000.0
    assert d["profile"]["timeframe"] == "M15"
    assert d["sharpes_matriz"] == [0.8, 1.1, 0.4]


def test_wfa_antigo_sem_as_colunas_novas_nao_quebra(tmp_path, monkeypatch):
    """Os registros gravados antes desta tela existirem continuam abrindo —
    a tela mostra 'indisponível', não um erro."""
    _banco_temporario(tmp_path, monkeypatch)
    wfa_id = wfa_store.salvar(
        run_id=1, symbol="WIN$N", strategy="teste", nome="x",
        is_meses=12, oos_meses=6, inteligencia="sharpe", holdout=False,
        agregado={"steps": 1}, veredito={}, passos=[])
    d = wfa_store.detalhes(wfa_id)
    assert d["capital"] is None and d["profile"] is None
    assert d["sharpes_matriz"] is None
```

Se `_banco_temporario` ainda não existir no arquivo, use o mesmo mecanismo que
os outros testes desse arquivo já usam para apontar `db_manager` a um banco
temporário — não invente um novo.

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wfa_store.py -k perfil_capital -v`
Esperado: FALHA com `TypeError: salvar() got an unexpected keyword argument 'profile'`.

- [ ] **Passo 3: Acrescentar as colunas no schema**

Em `core/schema.sql`, no bloco de ALTER que já existe (perto da linha 152):

```sql
-- A Candidata (passo 10 da metodologia) lê só wfa_runs + wfa_trades: o
-- capital e o perfil vinham da mineracao, e mineracao apagada derrubava o
-- dimensionamento inteiro. Retrato, nao referencia.
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS profile JSON;
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS capital DOUBLE;
-- os sharpes das 96 celulas da matriz: entrada do Sharpe Deflacionado
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS sharpes_matriz JSON;
```

`db_manager.DESCARTAVEIS` só confere deriva de schema em `mining_trials` e
`mining_runs`. Para `wfa_runs`, `CREATE TABLE IF NOT EXISTS` é no-op silencioso
— por isso o ALTER explícito.

- [ ] **Passo 4: Gravar e ler as colunas**

Em `core/wfa_store.py`, acrescente os três parâmetros a `salvar` (com default
`None`), inclua as colunas no INSERT nomeado, e em `detalhes` acrescente ao
SELECT e ao dicionário de saída:

```python
def salvar(*, run_id, symbol, strategy, nome, is_meses, oos_meses,
           inteligencia, holdout, agregado, veredito, passos,
           trades=None, profile=None, capital=None,
           sharpes_matriz=None) -> int:
```

No INSERT, acrescente `profile, capital, sharpes_matriz` à lista de colunas e
aos valores:

```python
             json.dumps(linhas), json.dumps(deploy),
             json.dumps(profile) if profile else None,
             float(capital) if capital is not None else None,
             json.dumps(sharpes_matriz) if sharpes_matriz else None])
```

Em `detalhes`, o SELECT ganha `profile, capital, sharpes_matriz` e o retorno:

```python
        "profile": json.loads(r[10]) if r[10] else None,
        "capital": float(r[11]) if r[11] is not None else None,
        "sharpes_matriz": json.loads(r[12]) if r[12] else None,
```

- [ ] **Passo 5: Rodar os dois testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wfa_store.py -v`
Esperado: PASSA.

- [ ] **Passo 6: Migrar o banco real**

Run: `.venv/Scripts/python.exe -c "from core import db_manager as db; db.init_schema(); print('ok')"`
Esperado: `ok`. Confirme com:
`.venv/Scripts/python.exe -c "from core import db_manager as db; print([c[1] for c in db.connect(read_only=True).__enter__().execute('PRAGMA table_info(wfa_runs)').fetchall()])"`
Esperado: a lista inclui `profile`, `capital`, `sharpes_matriz`.

- [ ] **Passo 7: Commit**

```bash
git add core/schema.sql core/wfa_store.py tests/test_wfa_store.py
git commit -m "feat(wfa): wfa_runs guarda perfil, capital e sharpes da matriz"
```

---

### Tarefa 3: Sharpe por configuração na matriz

O Sharpe Deflacionado precisa da variância dos Sharpes entre as 96 células.
Hoje `agregar` não calcula Sharpe nenhum.

**Arquivos:**
- Modificar: `core/wfa.py` (`agregar`, `_linha_matriz`)
- Testar: `tests/test_wfa.py`

**Interfaces:**
- Consome: `wfa.sharpe_diario(por_dia, n_pregoes)` (já existe, devolve **anualizado**).
- Produz: `agregar(...)["sharpe"]` e a chave `"sharpe"` em cada linha de `matriz`/`matrizes`.

- [ ] **Passo 1: Escrever o teste que falha**

Em `tests/test_wfa.py`:

```python
def test_agregar_traz_o_sharpe_da_curva_oos():
    """O Sharpe Deflacionado precisa da dispersão dos Sharpes entre as
    configurações — sem este campo, não há de onde tirá-la."""
    combos = _dois_combos()
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(combos, js, CAP, "sharpe")
    ts, liq, _ = wfa.trades_oos(combos, passos)
    ag = wfa.agregar(passos, CAP, liq, ts)

    assert ag["sharpe"] is not None
    assert ag["sharpe"] > 0                      # as duas combinações lucram
    linhas = wfa.matriz(combos, INICIO, FIM, CAP, "sharpe",
                        configs=[(12, 6), (24, 6)])
    assert all(r["sharpe"] is not None for r in linhas)


def test_agregar_sem_curva_oos_devolve_sharpe_nulo():
    js = wfa.montar_janelas(INICIO, FIM, 12, 6)
    passos = wfa.rodar(_dois_combos(), js, CAP, "sharpe")
    assert wfa.agregar(passos, CAP)["sharpe"] is None
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wfa.py -k sharpe_da_curva -v`
Esperado: FALHA com `KeyError: 'sharpe'`.

- [ ] **Passo 3: Calcular o Sharpe dentro de `agregar`**

Em `core/wfa.py`, dentro de `agregar`, junto do cálculo de `dd_oos` (que já
recebe `liquido_oos`):

```python
    # o Sharpe da curva concatenada, para a dispersão entre configurações
    # alimentar o Sharpe Deflacionado da tela Candidata
    sharpe = None
    if liquido_oos is not None and len(liquido_oos) and entrada_oos is not None:
        dia = np.asarray(entrada_oos, dtype="datetime64[D]")
        ordem = np.argsort(dia, kind="stable")
        d, por_dia = np.unique(dia[ordem], return_index=True)
        soma = np.add.reduceat(np.asarray(liquido_oos)[ordem], por_dia)
        sharpe = sharpe_diario(soma, pregoes(reais[0].oos_de, reais[-1].oos_ate))
```

E acrescente `"sharpe": sharpe,` ao dicionário devolvido. Em `_linha_matriz`,
acrescente `"sharpe": ag.get("sharpe"),`.

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wfa.py -q`
Esperado: PASSA, inclusive os antigos.

- [ ] **Passo 5: Ligar na gravação**

Em `ui/callbacks.py`, no callback `wfa_guardar`, passe para `wfa_store.salvar`
o `profile` (o mesmo `ExecutionProfile` já usado na varredura, como dicionário),
o `capital` e a lista de sharpes das células da matriz guardada em
`_WFA["matrizes"]`:

```python
        sharpes = [r["sharpe"] for linhas in (_WFA.get("matrizes") or {}).values()
                   for r in linhas if r.get("sharpe") is not None]
```

- [ ] **Passo 6: Rodar a suíte e commitar**

```bash
.venv/Scripts/python.exe -m pytest -q
git add core/wfa.py ui/callbacks.py tests/test_wfa.py
git commit -m "feat(wfa): sharpe por configuracao na matriz e na gravacao"
```

---

### Tarefa 4: `core/candidata.py` — chave de parâmetros e série por pregão

Dois utilitários que todo o resto usa. A chave existe porque `deploy.params`
vem em float (`78.0`) e `mining_trials.params` em int (`78`): casamento por
igualdade devolveria zero vizinhos **sem erro nenhum**.

**Arquivos:**
- Criar: `core/candidata.py`
- Criar: `tests/test_candidata.py`

**Interfaces:**
- Produz: `candidata.chave(params: dict) -> tuple`; `candidata.por_pregao(saida_ts, liquido, de=None, ate=None) -> tuple[np.ndarray, np.ndarray]` (dias úteis e P&L do dia, com zeros nos pregões parados).

- [ ] **Passo 1: Escrever os testes que falham**

`tests/test_candidata.py`:

```python
"""Testes da tela Candidata (passo 10 da metodologia).

A disciplina de sempre: cada caso tem a resposta conhecida de antemão.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata  # noqa: E402

CAP = 10_000.0


def test_chave_iguala_float_e_int_do_mesmo_ponto_da_grade():
    """O DEPLOY vem do JSON como 78.0; mining_trials gravou 78. Sem
    normalizar, a vizinhança não acha vizinho nenhum e não dá erro."""
    assert candidata.chave({"periodo_canal": 78.0, "folga": 9.0}) == \
        candidata.chave({"folga": 9, "periodo_canal": 78})


def test_chave_preserva_texto_e_booleano():
    k = dict(candidata.chave({"lado": "compra", "usa_trail": True, "n": 3.0}))
    assert k["lado"] == "compra" and k["usa_trail"] is True and k["n"] == 3.0


def test_por_pregao_enche_os_dias_parados_com_zero():
    """Quem opera pouco tinha Sharpe inflado: a série precisa dos zeros."""
    saida = np.array(["2024-03-04T15:00", "2024-03-06T10:00"],
                     dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([100.0, -40.0]))
    assert len(dias) == 3                       # 04, 05 e 06 de março
    assert list(pnl) == [100.0, 0.0, -40.0]


def test_por_pregao_soma_os_trades_do_mesmo_dia_e_pula_fim_de_semana():
    saida = np.array(["2024-03-08T10:00", "2024-03-08T16:00",
                      "2024-03-11T10:00"], dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([10.0, 5.0, -3.0]))
    assert len(dias) == 2                       # sexta e segunda
    assert list(pnl) == [15.0, -3.0]


def test_por_pregao_respeita_o_recorte_pedido():
    saida = np.array(["2024-03-04T10:00", "2024-04-01T10:00"],
                     dtype="datetime64[s]")
    dias, pnl = candidata.por_pregao(saida, np.array([10.0, 20.0]),
                                     de="2024-03-01", ate="2024-04-01")
    assert pnl.sum() == 10.0                    # abril ficou fora
    assert len(dias) == 21
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -v`
Esperado: FALHA com `ModuleNotFoundError: No module named 'core.candidata'`.

- [ ] **Passo 3: Escrever o módulo**

`core/candidata.py`:

```python
"""A tela Candidata: o passo 10 da metodologia sobre a curva que o
otimizador nunca viu.

Aqui ficam as contas puras — sem Dash, sem banco. Quem lê o banco é o
callback; quem decide é o portão; quem calcula é este módulo.
"""

from __future__ import annotations

import numpy as np


def chave(params: dict) -> tuple:
    """Endereço canônico de uma combinação na grade.

    `wfa_runs.deploy` volta do JSON com 78.0 e `mining_trials` gravou 78:
    comparar dicionários direto devolve "nenhum vizinho encontrado" sem
    levantar erro nenhum — o pior tipo de defeito.
    """
    itens = []
    for nome in sorted(params):
        v = params[nome]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            itens.append((nome, v))
        else:
            itens.append((nome, round(float(v), 6)))
    return tuple(itens)


def por_pregao(saida_ts, liquido, de=None, ate=None):
    """O resultado por pregão, com os dias parados valendo zero.

    O trade entra no dia da SAÍDA, que é quando o resultado se realiza.
    Contar só os dias operados inflava quem opera pouco — quatro trades num
    ano davam Sharpe 129. E é o pregão, não o trade, a unidade em que a
    camada 4 impõe limite e em que o risco se materializa.
    """
    d = np.asarray(saida_ts, dtype="datetime64[D]")
    liq = np.asarray(liquido, dtype=float)
    if not len(d):
        return np.array([], dtype="datetime64[D]"), np.array([])
    ini = np.datetime64(de, "D") if de is not None else d.min()
    fim = np.datetime64(ate, "D") if ate is not None else d.max() + 1
    dias = np.arange(ini, fim)
    dias = dias[np.is_busday(dias)]
    if not len(dias):
        return dias, np.array([])
    pos = np.searchsorted(dias, d)
    dentro = (pos < len(dias)) & (dias[np.clip(pos, 0, len(dias) - 1)] == d)
    pnl = np.bincount(pos[dentro], weights=liq[dentro], minlength=len(dias))
    return dias, pnl
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -v`
Esperado: PASSA, cinco testes.

- [ ] **Passo 5: Commit**

```bash
git add core/candidata.py tests/test_candidata.py
git commit -m "feat(candidata): chave de parametros e serie por pregao"
```

---

### Tarefa 5: Tamanho do bloco pela dependência do P&L diário

O bootstrap precisa saber de quantos pregões é o bloco. Quem responde é a
autocorrelação da própria série — e é o `teste_runs`, hoje um cartão que
ninguém usa para nada, que passa a ter função.

**Arquivos:**
- Modificar: `core/robustez.py`
- Testar: `tests/test_robustez.py`

**Interfaces:**
- Produz: `robustez.bloco_medio(por_dia: np.ndarray) -> int` (≥ 1).

- [ ] **Passo 1: Escrever o teste que falha**

Em `tests/test_robustez.py`:

```python
def test_bloco_medio_e_um_em_serie_independente():
    """Sem dependência entre dias, o bootstrap em blocos tem que degenerar
    para o sorteio dia a dia."""
    rng = np.random.default_rng(3)
    assert robustez.bloco_medio(rng.normal(10, 100, 500)) == 1


def test_bloco_medio_cresce_quando_os_dias_andam_juntos():
    """Volatilidade agrupada: bons e maus vêm em sequência, que é o que
    produz drawdown de verdade."""
    rng = np.random.default_rng(3)
    base = rng.normal(10, 100, 100)
    agrupada = np.repeat(base, 5)               # cada valor dura 5 pregões
    assert robustez.bloco_medio(agrupada) >= 4


def test_bloco_medio_nao_quebra_com_serie_curta_ou_constante():
    assert robustez.bloco_medio(np.array([1.0, 2.0])) == 1
    assert robustez.bloco_medio(np.zeros(200)) == 1
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_robustez.py -k bloco_medio -v`
Esperado: FALHA com `AttributeError: module 'core.robustez' has no attribute 'bloco_medio'`.

- [ ] **Passo 3: Implementar**

Em `core/robustez.py`:

```python
def bloco_medio(por_dia: np.ndarray) -> int:
    """De quantos pregões é o bloco do bootstrap.

    Permutar dia a dia supõe que o resultado de hoje nada diz sobre o de
    amanhã. Em day trade isso é falso: regime, volatilidade e notícia duram
    mais que um pregão, e é justamente essa dependência que produz o
    drawdown. O comprimento sai da autocorrelação de defasagem 1, pela
    razão (1+ρ)/(1−ρ) — a mesma que descreve a perda de amostra efetiva.
    """
    x = np.asarray(por_dia, dtype=float)
    if len(x) < 30:
        return 1
    x = x - x.mean()
    den = float((x * x).sum())
    if den <= 0:
        return 1
    rho = float((x[:-1] * x[1:]).sum() / den)
    rho = min(max(rho, 0.0), 0.95)              # dependência negativa não alonga bloco
    return max(1, int(round((1 + rho) / (1 - rho))))
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_robustez.py -v`
Esperado: PASSA.

- [ ] **Passo 5: Commit**

```bash
git add core/robustez.py tests/test_robustez.py
git commit -m "feat(robustez): comprimento de bloco pela dependencia diaria"
```

---

### Tarefa 6: Bootstrap estacionário com reposição

O coração da correção. `monte_carlo` permuta sem reposição: os 2.000 caminhos
terminam **no mesmo lucro**, e o `dd_p95` que vira disjuntor supõe que o edge
medido é o verdadeiro. O bootstrap estacionário sorteia blocos **com
reposição**, então o lucro varia e a dependência entre dias sobrevive.

**Arquivos:**
- Modificar: `core/robustez.py`
- Testar: `tests/test_robustez.py`

**Interfaces:**
- Consome: `robustez.bloco_medio`.
- Produz: `robustez.bootstrap(por_dia, capital, n=2000, semente=7, bloco=None, horizonte=None) -> dict` com as chaves `bloco`, `n`, `horizonte`, `dd_p50`, `dd_p95`, `dd_p99`, `submerso_p95`, `perdas_seguidas_p95`, `final_p10`, `final_p50`, `final_p90`, `quedas` (array) e `finais` (array).

- [ ] **Passo 1: Escrever os testes que falham**

Em `tests/test_robustez.py`:

```python
def test_bootstrap_faz_o_lucro_final_variar():
    """A diferença que motivou a troca: na permutação o lucro final é
    constante, então a incerteza que mais importa fica de fora."""
    rng = np.random.default_rng(1)
    dia = rng.normal(20, 150, 400)
    b = robustez.bootstrap(dia, 10_000.0, n=300, semente=5)
    assert b["final_p10"] < b["final_p50"] < b["final_p90"]
    perm = robustez.monte_carlo(dia, 10_000.0, n=300)
    assert perm["lucro_final"] == pytest.approx(float(dia.sum()))


def test_bootstrap_com_bloco_1_fica_perto_da_permutacao():
    """Sem dependência, os dois métodos medem a mesma coisa — a diferença
    toda vem do bloco e da reposição."""
    rng = np.random.default_rng(2)
    dia = rng.normal(15, 100, 600)
    b = robustez.bootstrap(dia, 10_000.0, n=800, semente=4, bloco=1)
    p = robustez.monte_carlo(dia, 10_000.0, n=800)
    assert b["dd_p95"] == pytest.approx(p["dd_p95"], rel=0.25)


def test_bootstrap_em_serie_agrupada_acha_drawdown_maior():
    """O que a permutação escondia: dias ruins vindo juntos afundam mais."""
    rng = np.random.default_rng(7)
    base = rng.normal(10, 120, 120)
    dia = np.repeat(base, 5)
    b = robustez.bootstrap(dia, 10_000.0, n=500, semente=9)
    p = robustez.monte_carlo(dia, 10_000.0, n=500)
    assert b["dd_p95"] > p["dd_p95"]


def test_bootstrap_com_horizonte_curto_reduz_o_drawdown():
    """O disjuntor precisa de horizonte: o p95 de cinco anos não é o p95 de
    três meses, e desligar pelo primeiro é desligar estratégia sadia."""
    rng = np.random.default_rng(11)
    dia = rng.normal(10, 100, 1000)
    inteiro = robustez.bootstrap(dia, 10_000.0, n=400, semente=2)
    curto = robustez.bootstrap(dia, 10_000.0, n=400, semente=2, horizonte=60)
    assert curto["dd_p95"] < inteiro["dd_p95"]
    assert curto["horizonte"] == 60


def test_bootstrap_conta_perdas_seguidas_e_tempo_submerso_em_pregoes():
    dia = np.array([-10.0] * 7 + [100.0] * 30)
    b = robustez.bootstrap(dia, 10_000.0, n=200, semente=3, bloco=1)
    assert b["perdas_seguidas_p95"] >= 1
    assert b["submerso_p95"] >= 1


def test_bootstrap_com_serie_curta_devolve_vazio():
    assert robustez.bootstrap(np.zeros(5), 10_000.0) == {}
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_robustez.py -k bootstrap -v`
Esperado: FALHA com `AttributeError: ... has no attribute 'bootstrap'`.

- [ ] **Passo 3: Implementar**

Em `core/robustez.py`:

```python
def _maior_seq(mask: np.ndarray) -> int:
    """O maior trecho seguido de True."""
    m = np.asarray(mask, dtype=np.int8)
    if not m.any():
        return 0
    d = np.diff(np.concatenate(([0], m, [0])))
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


def bootstrap(por_dia: np.ndarray, capital: float, n: int = 2000,
              semente: int = 7, bloco: int | None = None,
              horizonte: int | None = None) -> dict:
    """Bootstrap estacionário sobre o resultado DIÁRIO (Politis & Romano, 1994).

    Três diferenças para `monte_carlo`, e cada uma corrige um viés:

    1. **com reposição** — o lucro final varia. A permutação fixa o lucro e
       responde só "e se a ordem fosse outra?", deixando de fora a incerteza
       que domina: o edge medido não ser o verdadeiro.
    2. **em blocos** — dias vizinhos viajam juntos, preservando o agrupamento
       de volatilidade que produz o drawdown.
    3. **com horizonte** — mede o drawdown no prazo em que a decisão vale
       (até a próxima reotimização), não no comprimento inteiro do histórico.

    O bloco tem comprimento aleatório (geométrico de média `bloco`); é isso
    que torna o processo estacionário e evita que a emenda dos blocos crie
    quebras sistemáticas.
    """
    x = np.asarray(por_dia, dtype=float)
    if len(x) < 30:
        return {}
    L = int(bloco or bloco_medio(x))
    H = int(horizonte or len(x))
    rng = np.random.default_rng(semente)

    # o índice de cada dia sorteado: começa um bloco novo com probabilidade
    # 1/L, senão anda um dia à frente (circular)
    t = np.arange(H)
    novo = rng.random((n, H)) < (1.0 / L)
    novo[:, 0] = True
    inicio_em = np.maximum.accumulate(np.where(novo, t, 0), axis=1)
    sorteado = rng.integers(0, len(x), size=(n, H))
    base = np.take_along_axis(sorteado, inicio_em, axis=1)
    idx = (base + (t - inicio_em)) % len(x)
    series = x[idx]

    quedas = np.empty(n)
    submersos = np.empty(n)
    seguidas = np.empty(n)
    for i in range(n):
        eq = np.concatenate(([capital], capital + np.cumsum(series[i])))
        pico = np.maximum.accumulate(eq)
        quedas[i] = float((pico - eq).max())
        submersos[i] = _maior_seq(eq < pico)
        seguidas[i] = _maior_seq(series[i] < 0)

    finais = series.sum(axis=1)
    p = np.percentile(quedas, [50, 95, 99])
    return {
        "bloco": L, "n": n, "horizonte": H,
        "dd_p50": float(p[0]), "dd_p95": float(p[1]), "dd_p99": float(p[2]),
        "submerso_p95": float(np.percentile(submersos, 95)),
        "perdas_seguidas_p95": float(np.percentile(seguidas, 95)),
        "final_p10": float(np.percentile(finais, 10)),
        "final_p50": float(np.percentile(finais, 50)),
        "final_p90": float(np.percentile(finais, 90)),
        "quedas": quedas, "finais": finais,
    }
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_robustez.py -v`
Esperado: PASSA, seis testes novos.

- [ ] **Passo 5: Medir o custo**

Run:
```bash
.venv/Scripts/python.exe -c "import numpy as np, time; from core import robustez; x=np.random.default_rng(1).normal(10,100,1250); t=time.time(); robustez.bootstrap(x,10000.0); print(round(time.time()-t,2),'s')"
```
Esperado: menos de 3 s. Se passar disso, reduza `n` para 1.000 e anote no
comentário por quê — não vale bloquear a tela por precisão que ninguém lê.

- [ ] **Passo 6: Commit**

```bash
git add core/robustez.py tests/test_robustez.py
git commit -m "feat(robustez): bootstrap estacionario com reposicao e horizonte"
```

---

### Tarefa 7: Probabilidade de desligamento em falso

O número que falta para o disjuntor fazer sentido: se a estratégia está viva,
qual a chance de ela bater o limite mesmo assim, até a próxima reotimização.

**Arquivos:**
- Modificar: `core/candidata.py`
- Testar: `tests/test_candidata.py`

**Interfaces:**
- Consome: `robustez.bootstrap` (chave `quedas`).
- Produz: `candidata.risco_de_desligar(boot: dict, limite: float) -> float | None` (0 a 100).

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_risco_de_desligar_le_a_distribuicao_do_bootstrap():
    boot = {"quedas": np.array([100.0, 200.0, 300.0, 400.0])}
    assert candidata.risco_de_desligar(boot, 250.0) == pytest.approx(50.0)
    assert candidata.risco_de_desligar(boot, 1000.0) == 0.0
    assert candidata.risco_de_desligar({}, 100.0) is None


def test_limite_no_p95_deixa_cerca_de_cinco_por_cento_de_falso_desligamento():
    """É a razão de o número existir: desligar no p95 desliga uma estratégia
    sadia em 5% dos ciclos, e isso precisa estar escrito no plano."""
    rng = np.random.default_rng(5)
    dia = rng.normal(10, 100, 400)
    from core import robustez
    b = robustez.bootstrap(dia, 10_000.0, n=600, semente=8)
    assert candidata.risco_de_desligar(b, b["dd_p95"]) == pytest.approx(5.0, abs=1.5)
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -k desligar -v`
Esperado: FALHA com `AttributeError`.

- [ ] **Passo 3: Implementar**

Em `core/candidata.py`:

```python
def risco_de_desligar(boot: dict, limite: float) -> float | None:
    """Chance de bater o limite de desligamento ESTANDO a estratégia viva.

    O bootstrap simula trajetórias de uma estratégia que continua funcionando
    como funcionou. Se X% delas encostam no limite, esse é o preço do
    disjuntor: desligar na hora errada X% das vezes. Sem este número, o
    limite não está calibrado — está chutado.
    """
    quedas = (boot or {}).get("quedas")
    if quedas is None or not len(quedas):
        return None
    return float((np.asarray(quedas) >= limite).mean() * 100)
```

- [ ] **Passo 4: Rodar e commitar**

```bash
.venv/Scripts/python.exe -m pytest tests/test_candidata.py -q
git add core/candidata.py tests/test_candidata.py
git commit -m "feat(candidata): risco de desligamento em falso"
```

---

### Tarefa 8: O quarto modo, vazio, sem quebrar a tela

Antes de qualquer conta na tela: o modo existe, troca, e o teste de ciclo
continua passando. É o erro que já custou caro uma vez — laço de callbacks na
aba Walk-Forward.

**Arquivos:**
- Modificar: `ui/app.py` (opções do `modo`, painel novo, `register`)
- Criar: `ui/components/candidata_panel.py`
- Criar: `ui/callbacks_candidata.py`
- Modificar: `ui/callbacks.py` (chamar o `register` novo)
- Modificar: `ui/assets/style.css`
- Testar: `tests/test_callbacks_sem_ciclo.py` (já existe, só rodar)

**Interfaces:**
- Produz: `candidata_panel.painel()` devolve o `html.Div` do modo; `callbacks_candidata.register(app)`.

- [ ] **Passo 1: Escrever o teste que falha**

Em `tests/test_callbacks_sem_ciclo.py`:

```python
def test_o_modo_candidata_existe_e_tem_painel():
    app = build()
    texto = str(app.layout)
    assert "'Candidata'" in texto and "'candidata'" in texto
    assert "painel-candidata" in texto
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_callbacks_sem_ciclo.py -k candidata -v`
Esperado: FALHA no primeiro assert.

- [ ] **Passo 3: Criar o painel vazio**

`ui/components/candidata_panel.py`:

```python
"""O quarto modo: a candidata.

Recebe um walk-forward salvo e pergunta quanto daquilo sobrevive fora do
cenário perfeito. Ver docs/PLANO-CANDIDATA.md.
"""

from __future__ import annotations

from dash import dcc, html

from core import wfa_store


def _opcoes():
    return [{"label": w["rotulo"], "value": w["wfa_id"]}
            for w in wfa_store.listar()]


def painel():
    return html.Div(
        [
            html.Div(
                [
                    dcc.Dropdown(id="cand-wfa", className="dd dd-wfa",
                                 placeholder="walk-forward salvo…",
                                 options=_opcoes(), value=None),
                    html.Span(id="cand-resumo", className="cand-resumo"),
                ],
                className="cand-topo",
            ),
            html.Div(id="cand-portoes", className="cand-portoes"),
            html.Div(id="cand-blocos", className="cand-blocos"),
        ],
        id="painel-candidata", className="modo-bloco cand",
    )
```

- [ ] **Passo 4: Ligar no app**

Em `ui/app.py`, acrescente a opção ao `RadioItems` do `modo`:

```python
                                 {"label": "Candidata", "value": "candidata"},
```

e o painel junto dos outros `modo-bloco`:

```python
            html.Div(id="painel-candidata", className="modo-bloco",
                     children=candidata_panel.painel()),
```

Importe `candidata_panel` no topo. Depois acrescente o painel novo ao callback
`modo`, em `ui/callbacks.py:283` — ele é quem mostra e esconde os painéis, e
sem isto o painel da Candidata aparece junto com o do Backtest:

```python
        Output("painel-backtest", "style"), Output("painel-mineracao", "style"),
        Output("painel-wfa", "style"), Output("painel-candidata", "style"),
```

E no corpo, na tupla devolvida, na mesma posição:

```python
                VISIVEL if qual == "candidata" else OCULTO,
```

Confira a ordem: a tupla de retorno tem que ter exatamente a mesma quantidade
de itens que a lista de `Output`, e na mesma sequência.

- [ ] **Passo 5: Registrar os callbacks**

`ui/callbacks_candidata.py`:

```python
"""Callbacks da tela Candidata.

Em arquivo próprio: `ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são
do walk-forward. Arquivo focado é o que permite o teste de ciclo apontar
para um lugar pequeno quando algo trava.
"""

from __future__ import annotations

from dash import Input, Output

from core import wfa_store


def register(app):
    @app.callback(
        Output("cand-resumo", "children"),
        Input("cand-wfa", "value"),
    )
    def cand_resumo(wfa_id):
        if not wfa_id:
            return "escolha um walk-forward salvo"
        d = wfa_store.detalhes(int(wfa_id)) or {}
        return (f"{d.get('strategy', '—')} · {d.get('symbol', '—')} · "
                f"IS{d.get('is_meses')}/OOS{d.get('oos_meses')} · "
                f"{d.get('inteligencia', '—')}")
```

E, no fim de `ui/callbacks.py::register`:

```python
    from ui import callbacks_candidata
    callbacks_candidata.register(app)
```

- [ ] **Passo 6: Rodar os testes de ciclo**

Run: `.venv/Scripts/python.exe -m pytest tests/test_callbacks_sem_ciclo.py -v`
Esperado: PASSA — inclusive `test_o_app_nao_tem_ciclo_entre_callbacks`.

- [ ] **Passo 7: Ver na tela**

Suba o servidor, abra o modo Candidata, escolha o WFA salvo e confirme que o
resumo aparece. Não siga adiante sem ter visto isso funcionando.

- [ ] **Passo 8: Commit**

```bash
git add ui/ tests/test_callbacks_sem_ciclo.py
git commit -m "feat(candidata): quarto modo com seletor de walk-forward salvo"
```

---

### Tarefa 9: Bloco 1 — robustez sobre a curva fora da amostra

**Arquivos:**
- Modificar: `core/candidata.py` (`leitura_robustez`)
- Modificar: `ui/callbacks_candidata.py`, `ui/components/candidata_panel.py`
- Testar: `tests/test_candidata.py`

**Interfaces:**
- Consome: `wfa_store.trades`, `wfa_store.detalhes`, `candidata.por_pregao`, `robustez.bootstrap`, `metrics.resumo`.
- Produz: `candidata.leitura_robustez(trades: list[dict], capital: float, horizonte_pregoes: int | None = None) -> dict` com as chaves `resumo`, `boot`, `boot_12m`, `ordenacao`, `concentracao`, `pregoes` — ou `{"erro": "..."}` quando há menos de 100 trades.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def _trades_falsos(n=400, semente=1):
    rng = np.random.default_rng(semente)
    dias = np.arange(np.datetime64("2024-01-01"), np.datetime64("2025-12-31"))
    dias = dias[np.is_busday(dias)]
    escolha = np.sort(rng.choice(len(dias), size=n, replace=True))
    return [{"exit_ts": dias[i].astype("datetime64[s]").item(),
             "entry_ts": dias[i].astype("datetime64[s]").item(),
             "liquido": float(v), "custo": 3.5, "contratos": 1}
            for i, v in zip(escolha, rng.normal(15, 120, n))]


def test_leitura_robustez_usa_o_bootstrap_e_nao_a_permutacao():
    t = _trades_falsos()
    r = candidata.leitura_robustez(t, CAP)
    assert r["boot"]["dd_p95"] > 0
    assert r["boot"]["bloco"] >= 1
    # a permutação continua, mas como leitura à parte
    assert r["ordenacao"]["dd_p95"] > 0
    assert r["resumo"]["trades"] == len(t)


def test_leitura_robustez_traz_o_recorte_de_12_meses():
    """O índice dobrou de escala dentro da amostra: o risco do regime atual
    não é o risco médio de cinco anos."""
    r = candidata.leitura_robustez(_trades_falsos(), CAP)
    assert r["boot_12m"]["horizonte"] <= r["boot"]["horizonte"]


def test_leitura_robustez_recusa_amostra_pequena():
    """Rótulo de 'amostra pequena' ao lado de um número preciso perde para o
    número — abaixo de 100 trades a tela não calcula."""
    assert candidata.leitura_robustez(_trades_falsos(n=80), CAP) == \
        {"erro": "menos de 100 trades fora da amostra"}
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -k robustez -v`
Esperado: FALHA com `AttributeError`.

- [ ] **Passo 3: Implementar**

Em `core/candidata.py`:

```python
MIN_TRADES = 100


def leitura_robustez(trades: list[dict], capital: float,
                     horizonte_pregoes: int | None = None) -> dict:
    """O bloco 1: a robustez medida na curva que o otimizador nunca viu.

    Dois recortes sempre: a curva inteira e os últimos 12 meses. O mini
    índice foi de 96 mil a 197 mil pontos dentro da própria amostra — stop e
    alvo em pontos não significam a mesma coisa nas duas pontas, e o risco do
    regime atual não é a média de cinco anos. Vale o pior dos dois.
    """
    if len(trades) < MIN_TRADES:
        return {"erro": f"menos de {MIN_TRADES} trades fora da amostra"}

    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liq = np.array([t["liquido"] for t in trades], dtype=float)
    custo = np.array([t.get("custo", 0.0) for t in trades], dtype=float)
    dias, pnl = por_pregao(saida, liq)
    corte = dias[-1] - np.timedelta64(365, "D")
    _, pnl12 = por_pregao(saida, liq, de=str(corte), ate=str(dias[-1] + 1))

    from . import metrics, robustez
    return {
        "resumo": metrics.resumo(liq, custo, saida, capital, len(dias)),
        "boot": robustez.bootstrap(pnl, capital, horizonte=horizonte_pregoes),
        "boot_12m": robustez.bootstrap(pnl12, capital,
                                       horizonte=horizonte_pregoes),
        # a permutação sobrevive como o que ela realmente mede: e se a mesma
        # sequência de resultados tivesse vindo noutra ordem
        "ordenacao": robustez.monte_carlo(liq, capital),
        "concentracao": robustez.concentracao(liq),
        "pregoes": len(dias),
    }
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -v`
Esperado: PASSA.

- [ ] **Passo 5: Mostrar na tela**

Em `ui/components/candidata_panel.py`:

```python
from core import metrics
from . import cartao, stats_cards


def _num(v, casas=0):
    return f"{v:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def bloco_robustez(leitura: dict, capital: float):
    """Os cartões da curva fora da amostra.

    Ficaram de fora, de propósito: MAR e CAGR (compõem uma curva que é
    aditiva — o dimensionamento é de contratos fixos), SQN (é o t-stat com
    outro nome) e meses positivos (o portão de semestres do WFA já responde,
    e por uma régua melhor).
    """
    if leitura.get("erro"):
        return html.Div(leitura["erro"], className="cand-vazio")

    b, o = leitura["boot"], leitura["ordenacao"]
    b12 = leitura.get("boot_12m") or {}
    pior = max(b.get("dd_p95", 0.0), b12.get("dd_p95", 0.0))
    return html.Div(
        [
            html.H3("Robustez da curva fora da amostra", className="bloco-tit"),
            stats_cards.cartoes(leitura["resumo"]),
            html.Div([
                cartao.cartao(
                    "drawdown esperado", f"R$ {_num(pior, 0)}",
                    nota=f"{_num(pior / capital * 100, 1)}% do capital · "
                         f"blocos de {b.get('bloco', 1)} pregões",
                    dica="O p95 de 2.000 trajetórias sorteadas em blocos de "
                         "pregão, com reposição — o lucro final varia, então "
                         "a incerteza do próprio edge entra na conta. Vale o "
                         "pior entre a curva inteira e os últimos 12 meses. "
                         "Bom: até 10% do capital. Ruim: acima de 20%."),
                cartao.cartao(
                    "perdas seguidas", f"{_num(b.get('perdas_seguidas_p95', 0))}",
                    nota=f"{_num(b.get('submerso_p95', 0))} pregões no fundo",
                    dica="O p95 da maior sequência de pregões negativos e do "
                         "maior tempo abaixo do topo anterior. É o que você "
                         "vai viver antes de o disjuntor disparar."),
                cartao.cartao(
                    "risco de ordenação", f"R$ {_num(o.get('dd_p95', 0), 0)}",
                    nota="mesma carteira, outra ordem",
                    dica="Os MESMOS trades embaralhados: o lucro final não "
                         "muda, só o caminho. Mede azar de sequência, não "
                         "incerteza do resultado — por isso não é o disjuntor."),
            ], className="grade-cartoes"),
        ],
        className="cand-bloco",
    )
```

Se a assinatura de `cartao.cartao` no seu código for diferente (confira em
`ui/components/cartao.py`), use a que existe — o que não pode faltar é o
`dica=`, que é o (?) de cada número.

Em `ui/callbacks_candidata.py`:

```python
    @app.callback(
        Output("cand-blocos", "children"),
        Input("cand-wfa", "value"),
    )
    def cand_blocos(wfa_id):
        if not wfa_id:
            return CP.vazio("escolha um walk-forward salvo para analisar")
        d = wfa_store.detalhes(int(wfa_id)) or {}
        capital = d.get("capital")
        if capital is None:
            return CP.vazio("este walk-forward foi salvo antes desta tela: "
                            "não tem capital nem perfil gravados. Rode e "
                            "salve o walk-forward de novo para analisá-lo.")
        trades = wfa_store.trades(int(wfa_id))
        # o disjuntor vale até a próxima reotimização, não até o fim dos
        # tempos: o horizonte é o OOS da configuração escolhida
        horizonte = int(d.get("oos_meses", 6) * 21)
        return CP.bloco_robustez(
            candidata.leitura_robustez(trades, capital, horizonte), capital)
```

`CP.vazio(texto)` é um `html.Div(texto, className="cand-vazio")` — escreva-o
junto no painel.

- [ ] **Passo 6: Ver na tela e commitar**

Abra o modo, escolha o WFA #3 e confirme os números. Compare com a aba
Robustez do Backtest: **os dois drawdowns têm que ser diferentes** — se forem
iguais, você ligou a curva errada.

```bash
git add core/candidata.py ui/ tests/test_candidata.py
git commit -m "feat(candidata): bloco 1 sobre a curva fora da amostra"
```

---

### Tarefa 10: Bloco 2 — o perfil do platô

O desenho original media 2k vizinhos. No dado real o espaço da #40 varia **um**
parâmetro: k=1, dois vizinhos, e o portão mais severo decidido por duas
amostras. O bloco passa a mostrar o perfil inteiro da faixa minerada.

**Arquivos:**
- Modificar: `core/candidata.py`
- Testar: `tests/test_candidata.py`

**Interfaces:**
- Consome: `candidata.chave`, `optimizer.faixas_do_espaco`, linhas de `mining_trials`.
- Produz: `candidata.perfil_plato(trials: list[dict], espaco: dict, deploy: dict) -> dict` com `pontos` (lista de `{params, lucro, fr, atual}` ordenada), `largura_esq`, `largura_dir`, `centro_fr`, `ausentes`, `abstem`.

- [ ] **Passo 1: Escrever os testes que falham**

```python
def _trials(valores, lucros, dd=500.0):
    return [{"params": {"periodo_canal": v}, "lucro": l, "max_dd": dd}
            for v, l in zip(valores, lucros)]


def test_perfil_plato_mede_a_largura_em_torno_do_deploy():
    """Platô largo: os vizinhos seguram o fator de recuperação. É isto que
    distingue região fértil de pico de sorte."""
    trials = _trials([40, 50, 60, 70, 80],
                     [100.0, 900.0, 1000.0, 950.0, 120.0])
    espaco = {"periodo_canal": [40, 50, 60, 70, 80]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 60.0})
    assert p["largura_esq"] == 1 and p["largura_dir"] == 1
    assert [x["atual"] for x in p["pontos"]] == [False, False, True, False, False]


def test_perfil_plato_acha_o_deploy_mesmo_vindo_em_float():
    """78.0 do JSON tem que casar com o 78 gravado na mineração."""
    trials = _trials([76, 78, 80], [500.0, 600.0, 550.0])
    p = candidata.perfil_plato(trials, {"periodo_canal": [76, 78, 80]},
                               {"periodo_canal": 78.0})
    assert p["centro_fr"] == pytest.approx(600.0 / 500.0)


def test_perfil_plato_abstem_quando_falta_um_terco_da_grade():
    """Mineração interrompida abre buraco no meio da grade, não só na borda
    — e portão que decide sobre grade furada decide sobre nada."""
    trials = _trials([40, 50], [100.0, 900.0])
    espaco = {"periodo_canal": [40, 50, 60, 70, 80]}
    p = candidata.perfil_plato(trials, espaco, {"periodo_canal": 50})
    assert p["ausentes"] == 3 and p["abstem"]


def test_perfil_plato_sem_o_deploy_na_grade_nao_quebra():
    p = candidata.perfil_plato(_trials([40, 50], [1.0, 2.0]),
                               {"periodo_canal": [40, 50]},
                               {"periodo_canal": 99})
    assert p["centro_fr"] is None and p["abstem"]
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -k plato -v`
Esperado: FALHA com `AttributeError`.

- [ ] **Passo 3: Implementar**

```python
PLATO_PISO = 0.6            # o vizinho segura 60% do FR do centro


def perfil_plato(trials: list[dict], espaco: dict, deploy: dict) -> dict:
    """O perfil do parâmetro varrido, com o DEPLOY marcado.

    A pergunta é o FORMATO da superfície: o ponto escolhido está num platô ou
    num pico? Medimos por fator de recuperação, não por lucro — lucro perto de
    zero faz a razão explodir, e o que interessa é lucro por unidade de
    mergulho.

    A largura é contada em PASSOS da grade para cada lado, parando no
    primeiro ponto que não segura 60% do centro. Combinação que perde metade
    do FR com um passo de diferença não é candidata, é coincidência.
    """
    varridos = [k for k, v in espaco.items() if len(set(v)) > 1]
    if len(varridos) != 1:
        return {"pontos": [], "centro_fr": None, "abstem": True,
                "ausentes": 0, "largura_esq": 0, "largura_dir": 0,
                "motivo": "perfil só existe com um parâmetro varrido"}
    nome = varridos[0]
    grade = sorted({round(float(v), 6) for v in espaco[nome]})

    achados = {}
    for t in trials:
        p = dict(t["params"])
        v = round(float(p[nome]), 6)
        dd = float(t.get("max_dd") or 0.0)
        achados[v] = {"valor": v, "lucro": float(t.get("lucro") or 0.0),
                      "fr": (float(t["lucro"]) / dd) if dd > 0 else None}

    alvo = round(float(deploy.get(nome, float("nan"))), 6)
    pontos = [dict(achados.get(v, {"valor": v, "lucro": None, "fr": None}),
                   atual=(v == alvo)) for v in grade]
    ausentes = sum(1 for p in pontos if p["fr"] is None)

    centro = next((p for p in pontos if p["atual"]), None)
    centro_fr = centro["fr"] if centro else None
    if centro_fr is None:
        return {"pontos": pontos, "centro_fr": None, "ausentes": ausentes,
                "largura_esq": 0, "largura_dir": 0, "abstem": True,
                "motivo": "o DEPLOY não está na grade minerada"}

    piso = centro_fr * PLATO_PISO
    i = pontos.index(centro)

    def anda(passo):
        n, k = 0, i + passo
        while 0 <= k < len(pontos) and pontos[k]["fr"] is not None \
                and pontos[k]["fr"] >= piso:
            n += 1
            k += passo
        return n

    return {"pontos": pontos, "centro_fr": centro_fr, "ausentes": ausentes,
            "largura_esq": anda(-1), "largura_dir": anda(1),
            "abstem": ausentes * 3 > len(pontos), "parametro": nome}
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_candidata.py -v`
Esperado: PASSA.

- [ ] **Passo 5: Medir o platô da #40 e anotar**

Run:
```bash
.venv/Scripts/python.exe -c "from core import optimizer, wfa_store, candidata; d=wfa_store.detalhes(3); t=optimizer.carregar_salva(d['run_id']); e=optimizer.detalhes_salva(d['run_id'])['espaco']; p=candidata.perfil_plato(t,e,d['deploy']['params']); print(p['parametro'], p['largura_esq'], p['largura_dir'], p['centro_fr'])"
```

Anote o resultado no CHANGELOG. Se as larguras derem 0, **não conserte o
código**: é a #40 dizendo que o DEPLOY está numa borda da região boa, e isso é
informação.

- [ ] **Passo 6: Commit**

```bash
git add core/candidata.py tests/test_candidata.py CHANGELOG.md
git commit -m "feat(candidata): perfil do plato na faixa minerada"
```

---

### Tarefa 11: Entrada aleatória

O teste que pergunta se o **sinal** vale alguma coisa. A camada 2 torna isto
barato: uma estratégia devolve só sinais, e o kernel cuida do resto.

**Arquivos:**
- Criar: `core/aleatorio.py`
- Testar: `tests/test_aleatorio.py`

**Interfaces:**
- Consome: `core.engine.execution.run_strategy`, `strategies.base.Signals`.
- Produz: `aleatorio.EntradaAleatoria(n_sinais, horarios, p_compra, semente)` com `.signals(bars, params)`; `aleatorio.calibrar(rodar, alvo_trades, tentativas=8) -> int`; `aleatorio.p_valor(reais: float, sorteados: np.ndarray) -> float`.

- [ ] **Passo 1: Escrever os testes que falham**

`tests/test_aleatorio.py`:

```python
"""Testes da entrada aleatória (portão 3).

O teste é desconfortável de propósito: se o sorteio vai tão bem quanto o
sinal, o mérito é da gestão de saída, não da estratégia.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import aleatorio  # noqa: E402


def _bars(n=2000):
    ts = np.arange(np.datetime64("2024-01-02T09:00", "s"),
                   np.datetime64("2024-01-02T09:00", "s") + np.timedelta64(n, "m"),
                   np.timedelta64(1, "m"))
    return {"ts": ts, "open": np.ones(n), "high": np.ones(n),
            "low": np.ones(n), "close": np.ones(n)}


def test_sorteia_o_numero_pedido_de_sinais():
    bars = _bars()
    e = aleatorio.EntradaAleatoria(n_sinais=50, horarios=None,
                                   p_compra=1.0, semente=3)
    s = e.signals(bars, {})
    assert int(s.entry_long.sum()) == 50
    assert int(s.entry_short.sum()) == 0


def test_mesma_semente_da_o_mesmo_sorteio():
    bars = _bars()
    a = aleatorio.EntradaAleatoria(30, None, 1.0, 7).signals(bars, {})
    b = aleatorio.EntradaAleatoria(30, None, 1.0, 7).signals(bars, {})
    assert np.array_equal(a.entry_long, b.entry_long)


def test_respeita_a_proporcao_de_lado():
    s = aleatorio.EntradaAleatoria(100, None, 0.7, 1).signals(_bars(), {})
    assert 60 <= int(s.entry_long.sum()) <= 80
    assert int(s.entry_long.sum()) + int(s.entry_short.sum()) == 100


def test_estratifica_pelo_histograma_de_horario():
    """Sorteio uniforme mede a volatilidade em U do WIN, não o sinal: se a
    estratégia real só entra na abertura, o sorteio também tem que entrar."""
    bars = _bars()
    horarios = {9: 1.0}                      # tudo na primeira hora
    s = aleatorio.EntradaAleatoria(40, horarios, 1.0, 5).signals(bars, {})
    hora = bars["ts"][s.entry_long].astype("datetime64[h]").astype(object)
    assert {h.hour for h in hora} == {9}


def test_calibrar_acha_o_numero_de_sinais_que_da_o_alvo_de_trades():
    """600 sinais deram 497 trades e 3.000 deram 1.885 — a taxa não é fixa,
    então o número de sinais tem que ser procurado."""
    def rodar(n):                            # 70% dos sinais viram trade
        return int(n * 0.7)
    assert abs(aleatorio.calibrar(rodar, 700) - 1000) <= 50


def test_p_valor_de_permutacao_nunca_e_zero():
    """(1+k)/(1+B): com B sorteios, zero não é uma evidência possível."""
    sorteados = np.array([1.0, 2.0, 3.0, 4.0])
    assert aleatorio.p_valor(10.0, sorteados) == pytest.approx(1 / 5)
    assert aleatorio.p_valor(2.5, sorteados) == pytest.approx(3 / 5)
```

- [ ] **Passo 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_aleatorio.py -v`
Esperado: FALHA com `ModuleNotFoundError: No module named 'core.aleatorio'`.

- [ ] **Passo 3: Implementar**

`core/aleatorio.py`:

```python
"""Entrada aleatória: o mérito é do sinal ou da gestão de saída?

A camada 2 diz que uma estratégia devolve APENAS sinais — stop, alvo,
horário, custo e limites do dia são do kernel. Então este teste é uma
estratégia falsa que sorteia as barras de entrada e herda toda a gestão da
real, sem tocar no motor.

Duas decisões que fazem a comparação ser honesta (ver PLANO-CANDIDATA §6.1):
o sorteio é estratificado pelo histograma de horário das entradas reais, e o
número de sinais é calibrado até o número de TRADES bater — porque sinal não
vira trade quando já há posição aberta ou o limite do dia bloqueou.
"""

from __future__ import annotations

import numpy as np

from strategies.base import Signals


class EntradaAleatoria:
    name = "entrada_aleatoria"
    params_schema: dict = {}

    def __init__(self, n_sinais: int, horarios: dict | None,
                 p_compra: float, semente: int):
        self.n_sinais = int(n_sinais)
        self.horarios = horarios
        self.p_compra = float(p_compra)
        self.semente = int(semente)

    def signals(self, bars: dict, params: dict) -> Signals:
        n = len(bars["close"])
        rng = np.random.default_rng(self.semente)
        horas = bars["ts"].astype("datetime64[h]").astype(object)
        horas = np.array([h.hour for h in horas])

        if self.horarios:
            escolhidas = []
            for hora, peso in self.horarios.items():
                quantas = int(round(self.n_sinais * peso))
                cand = np.flatnonzero(horas == hora)
                if len(cand) and quantas:
                    escolhidas.append(rng.choice(
                        cand, size=min(quantas, len(cand)), replace=False))
            idx = np.concatenate(escolhidas) if escolhidas else np.array([], int)
        else:
            idx = rng.choice(n, size=min(self.n_sinais, n), replace=False)

        compra = rng.random(len(idx)) < self.p_compra
        el = np.zeros(n, dtype=np.bool_)
        es = np.zeros(n, dtype=np.bool_)
        el[idx[compra]] = True
        es[idx[~compra]] = True
        return Signals(entry_long=el, entry_short=es,
                       exit_long=np.zeros(n, dtype=np.bool_),
                       exit_short=np.zeros(n, dtype=np.bool_))


def calibrar(rodar, alvo_trades: int, tentativas: int = 8,
             tolerancia: float = 0.05) -> int:
    """Quantos sinais sortear para sair o número de trades da estratégia real.

    Busca por bisseção: `rodar(n)` devolve quantos trades saíram com n
    sinais. Sem isto, o sorteio opera menos (ou mais) que a real e a
    comparação vira teste de frequência, não de sinal.
    """
    baixo, alto = alvo_trades, max(alvo_trades * 4, alvo_trades + 10)
    melhor, erro_melhor = alto, float("inf")
    for _ in range(tentativas):
        meio = (baixo + alto) // 2
        saiu = rodar(meio)
        erro = abs(saiu - alvo_trades)
        if erro < erro_melhor:
            melhor, erro_melhor = meio, erro
        if erro <= alvo_trades * tolerancia:
            return meio
        if saiu < alvo_trades:
            baixo = meio
        else:
            alto = meio
    return melhor


def p_valor(real: float, sorteados: np.ndarray) -> float:
    """P-valor de permutação: (1 + quantos batem o real) / (1 + B).

    O percentil empírico cru daria zero quando nenhum sorteio bate o real —
    e "probabilidade zero" não é uma conclusão que B sorteios sustentam.
    """
    s = np.asarray(sorteados, dtype=float)
    return float((1 + int((s >= real).sum())) / (1 + len(s)))
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_aleatorio.py -v`
Esperado: PASSA, sete testes.

- [ ] **Passo 5: Medir o custo real no motor**

Escreva um script no diretório de rascunho que rode `run_strategy` com a
`EntradaAleatoria` sobre o período OOS do WFA #3, cinco vezes, e imprima o
tempo e o número de trades. Esperado, pela medição da revisão: ~0,05 s por
execução. Se 1.000 execuções passarem de 3 minutos, reduza para 500 e anote.

- [ ] **Passo 6: Commit**

```bash
git add core/aleatorio.py tests/test_aleatorio.py
git commit -m "feat(candidata): estrategia de entrada aleatoria calibrada"
```

---

## Cobertura: o que esta parte faz e o que não faz

| tarefa do desenho | aqui | onde |
|---|---|---|
| 0.1 colunas novas em `wfa_runs` | ✅ | tarefa 2 |
| 0.2 sharpe por configuração | ✅ | tarefa 3 |
| 0.3 tabela `planos_operacao` | ❌ | parte 2 — a tabela só é escrita na fase 5, e criar tabela sem quem a use gera coluna errada |
| 0.4 chave de parâmetros | ✅ | tarefa 4 |
| 1.1 bootstrap estacionário | ✅ | tarefas 5 e 6 |
| 1.2 horizonte e desligamento em falso | ✅ | tarefas 6 e 7 |
| 1.3 quarto modo e callbacks próprios | ✅ | tarefa 8 |
| 1.4 bloco 1 com os dois recortes | ✅ | tarefa 9 |
| 2.1 perfil do platô | ✅ | tarefa 10 |
| 2.2 platô in-sample × recorte OOS | ❌ | parte 2 — precisa refazer a varredura, que é o caminho caro |
| 2.3 aleatório: estratégia e calibração | ✅ | tarefa 11 |
| 2.3 aleatório: rodar janela a janela, 1.000 vezes | ❌ | parte 2 — vai junto com a faixa de portões, que é quem consome o p-valor |
| 2.4 portões 1, 2, 3, 5, 5b | ❌ | parte 2 |

Ao fim da parte 1 a tela **mostra**, mas ainda não **reprova**: os portões
inteiros vão para a parte 2, juntos, porque veredito pela metade é pior que
veredito nenhum.

## Depois desta parte

Ao terminar a tarefa 11, rode a suíte inteira
(`.venv/Scripts/python.exe -m pytest -q`) e confira na tela que os blocos 1 e 2
aparecem com números que batem com os scripts de medição.

Aí a parte 2 vira plano próprio, cobrindo as fases 3 a 6 do desenho: portões na
tela, `Φ⁻¹`, PSR, minTRL, Sharpe Deflacionado, SPA de Hansen, holdout lacrado,
CVaR do pregão, contratos e plano de operação.

Ela é escrita **depois**, e não agora, por um motivo: a medição da tarefa 10
(largura do platô da #40) e a da tarefa 11 (custo real das execuções) mudam
decisões dela — o limiar do portão 1 e quantas repetições cabem no portão 3.
Escrever agora seria escrever com número suposto, que é o que esta tela inteira
existe para evitar.

---

## Resultado da execução (16/09/2026)

As 11 tarefas foram executadas e revisadas uma a uma, mais uma revisão final
do ramo inteiro. 22 commits no ramo `candidata`, 445 testes. O que a execução
descobriu e que **muda o plano da parte 2**:

### Decisões que divergiram deste plano

- **Sharpe pelo dia de saída**, não de entrada (tarefa 3): o plano estava
  errado.
- **Perdas seguidas contam só pregões operados** (tarefa 9).
- **`bloco_medio` olha também o valor absoluto** da série (tarefa 6).
- **Horizonte por `wfa.pregoes` do deploy**, não 21 pregões por mês
  (tarefa 9): 131 pregões no #3 e no #8, contra 126.
- **Estratificação do aleatório pela hora de execução** (`ts + 1 min`),
  não pela hora do carimbo da barra (tarefa 11).
- **`perfil_plato` lê a chave `dd`**, que é o que `optimizer.carregar_salva`
  devolve — o plano dizia `max_dd` (tarefa 10).

### O que a parte 2 precisa levar em conta

1. **Portão 1 (platô): três motivos de parada, não dois.** `perfil_plato` já
   distingue queda de borda (`borda_esq`/`borda_dir`). Falta o terceiro: um
   ponto **ausente** ao lado do centro (mineração interrompida) hoje para a
   caminhada com `borda = False`, lido igual a uma queda comprovada. Na #40
   as duas larguras são a grade acabando — o portão não pode tratar isso como
   platô confirmado; a pergunta honesta é se a mineração devia ter ido além
   de 80.
2. **Portão 3 (aleatório): calibrar uma vez por janela.** Calibrando a cada
   repetição, 1.000 repetições × 8 janelas levam ~206 s; calibrando por
   janela, ~34 s. E conferir o número de trades obtidos contra o alvo depois
   de `calibrar`, que devolve o melhor visto em silêncio quando o alvo é
   inatingível.
3. **O "p95 = 5% de desligar em falso" é otimista fora da amostra.** Medido
   estimando o p95 numa curva e simulando trajetórias novas do mesmo
   processo: 6,8% a 7,1%. O teste atual do p95 é circular.
4. **O disjuntor mede drawdown desde o início do ciclo, não desde o topo
   histórico.** Medido desde o topo, o limite fica subestimado: no #8, 863 em
   131 pregões contra 1.108 em 262.
5. **Walk-forward com holdout incluído não alimenta o bloco do holdout
   lacrado.** O #3 e o #8 foram salvos com holdout incluído: para eles, o
   holdout já foi visto.
6. **`sharpes_matriz` vazio grava NULL** e fica indistinguível de registro
   antigo: a tela precisa dizer "matriz não calculada ao salvar".
7. **`optimizer.excluir_salva` ainda apaga os walk-forwards da mineração**,
   contra o §7 do desenho ("só o bloco 2 cai"). Decidir.
8. **Tela:** os três p95 do bloco 1 podem vir de recortes diferentes e não
   descrevem uma trajetória simultânea — falta uma linha na seção dizendo
   isso. E `cand_opcoes` devolve o valor atual em vez de `no_update` quando
   ele segue válido, o que recalcula o bloco à toa ao entrar no modo.
