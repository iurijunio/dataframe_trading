# Dataframe — project instructions

> Core limited by a test; details in the per-area rules.

Python platform (Dash + DuckDB + Numba) to research and trade intraday.
Main branch `master`; remote `origin` on GitHub.

**⚠ Strategies are trading on the real account.** Never send an order or flatten a position:
the user does that on the screen or in MT5.

## The user

- A trader, not a programmer. Chat with them in plain Portuguese; explain a new term with an example from their data.
- Prefers to **see it working on screen**: show results with a screenshot.
- They give the final approval. Do not commit, merge or push unless they ask.

## Language

- **Everything committed to the repository is in English:** files, folders, names, code, comments,
  docstrings, logs, commits, docs, rules and agent prompts.
- On-screen text for the user stays in Portuguese and comes from a single module, never scattered
  through the logic. Chat with the user stays in Portuguese.
- Legacy Portuguese identifiers (tables, columns, modules) are not mass-renamed; never rename DB names without a migration.

## Run

Python 3.13.7, venv + pip:

```
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Do not recreate the environment. Screen dependencies are commented out in `requirements.txt`:
incomplete install. Build/lint/typecheck are not configured; do not invent commands.

```
.venv/Scripts/python.exe ui/app.py          # http://127.0.0.1:8050
.venv/Scripts/python.exe -m pytest -q tests/<file>.py
.venv/Scripts/python.exe -m pytest -q       # whole suite
```

- Do not open `iniciar.bat`, capture or real orders: they start services that can
  trade. The user opens them. The interface also applies the database schema.
- Do not change dependencies, secrets, deploy, CI or generated files without authorization.
- Never use `git clean -x`: it deletes the database and the journal that Git ignores.
- To see the app, `preview_start` with the name `dataframe`; **only with the real app
  closed**, because the copy opens the real database.
- **Git**: a commit message of more than one line goes in a scratchpad file,
  with `git commit -F <file>`; never a heredoc (it breaks on accents).
- Add files to the commit **by path**, never `git add -A` / `git add .`.
  A change you did not make is the user's: do not stage it.
- **Worktrees:** `data/` and `.venv/` are junctions to the originals. Remove with
  `cmd /c rmdir`, never `rm -rf`, or it deletes the real database.

## Cheap context

Search with `rg`, read excerpts; never the whole `CHANGELOG.md`. Before editing,
identify the minimal tests and read local `AGENTS.md` files; expand only by dependency.

## Task size

Classify before starting and use the **smallest** flow that fits:

- **Micro** (text, CSS, rename, a "where is it" question): do it directly, no
  plan or subagent.
- **Simple** (few files, no account/state/database): locate → edit →
  test of the touched file.
- **High impact**: the whole flow below.

## How to work

**High-impact change** (account, logic, data, database, callback with state):

1. Failing test → minimal implementation → passing test.
2. **Mutation**: break the implementation on purpose, confirm the test
   catches it, undo (`mutation` agent). A test that passes with wrong code proves nothing.
3. Background review (`reviewer` agent) → apply what is valid.
4. Whole suite green → check on screen against the real database, with the real app and
   services closed. Commit only if the user asks.
5. **At delivery**, delete the proofs, scratch files and run-once scripts this change created, and
   move or delete the delivered plan.

**Simple layout/CSS/text change**: no tests, no mutation, no
review. Do it, show it on screen (screenshot) and **the user approves**.

**After changing code**, run `.venv/Scripts/python.exe scripts/check_changes.py`:
it says what to check and what to reopen. Warn the user prominently; the open
app does not load new code.

**Done:** scope implemented and required checks passing; explain
commands, failures, limits and reopenings. Lint/typecheck only when configured.
Report pending validation. The script's suite reminder does not remove the layout
exception; documentation requires validating the instructions, not the production suite.

## Code rules

- **Small file (≤ 500 lines, aim for 150–300), atomic function, folder per
  subject** — in all new or touched code: `.claude/rules/small-code.md`.
- Code, names, comments and docs in **English**; on-screen text in Portuguese from a single module.
- A comment explains **why**; reference: `core/wfa.py`.
- **Nothing in `core/` imports Dash.** `core/` is calculations; `ui/` wires up the screen.
- **No test touches `data/database.duckdb`.** Every test already runs isolated from the real
  database through `tests/conftest.py` (autouse); still, use the fixture
  `banco`: `monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")` (and
  `PARQUET_DIR` when reading bars). See `tests/test_portfolio.py`.
- Every new metric on screen has a (?) with a good and a bad range (`ui/components/cartao.py`).
- No scipy, on purpose (`core/robustez.py` uses `math.erfc`).
- Do not turn off the TradingView logo on the chart — a license requirement.
- Reference base: `WIN$N`, from 2021-03-16 on, default capital R$ 10,000.
- Do not hard-code specific values or items where the rule is general: read from the code.

## Glossary (use the user's Portuguese term in chat, the English one in the repo)

| User's term (chat) | English (repo) | Meaning |
|---|---|---|
| Estratégia | Strategy | the code in `strategies/*.py` |
| Variante | Variant | configuration saved and named by the user. Distinct clusters are distinct variants. Survives re-optimizations: only the plan changes |
| Plano | Plan | parameters, contracts and circuit breaker recorded by the Candidate; **one active plan per variant** |
| Fase | Stage | per portfolio: paper → demo → real (the stored values stay `papel`/`demo`/`real`). Never "step" or "minimum real"; DB `real_minimo` migrates to `real` |
| Serviço de captura | Capture service | live-candle and operational-automation process, opened by the user via `iniciar.bat`. Never "robot" |
| Candidata | Candidate | the stage that validates a strategy and records its plan |
| Mineração / Varredura | Mining / Scan | parameter search; the Scan is the exhaustive sweep |
| Pregão | Trading session | the exchange's trading day |
| Papel | Paper | simulated execution that follows the real session |

## Pitfalls that apply everywhere

- **DuckDB: many readers OR one writer.** Workers: `db.read_bars_parquet`;
  writing: `db.connect_write()`.
- **`COPY … TO ?` with a parameter writes nothing, silently** — literal path via `_sql_str`.
- **A cycle between callbacks freezes the screen.** Run `tests/test_callbacks_sem_ciclo.py`
  whenever you touch Inputs/Outputs.
- Never send the ~700 thousand bars to the browser — `ui/data.py` aggregates through `MAX_CANDLES`.
- Look-ahead is locked in the kernel: the signal of bar `i` executes at the open of `i+1`.
- **The `.duckdb` is no longer just a cache:** `contas`, `portfolio_membros`,
  `ao_vivo_eventos`, `planos`, `papel_operacoes`, `papel_pregoes`,
  `ordens_eventos` and `papel_backtest` cannot be recreated — back up before any
  migration; never delete the database. Also never delete the write-ahead
  journal `data/ao_vivo/ordens/*.jsonl`: the capture re-reads from it (not from the database)
  "I already sent entry X" and "account locked today".

## Per-area rules

Read the applicable rules before editing, including in subagents. Do not assume
automatic loading: follow the specific routing of the client in use.
Existing project references:

| The task touches… | Rule |
|---|---|
| capture, MT5, candles, paper, reconciliation | `.claude/rules/capture-paper.md` |
| orders, real account, bridge, stage promotion | `.claude/rules/orders.md` |
| engine, strategies, `codigo_hash` | `.claude/rules/engine-strategies.md` |
| mining, ranges, menu fields | `.claude/rules/mining.md` |
| Automatic Search | `.claude/rules/search.md` |
| MES/MNQ, scale, units | `.claude/rules/cme.md` |
| Portfolio | `.claude/rules/portfolio.md` |
| any screen | `.claude/rules/ui.md` |
| any code | `.claude/rules/small-code.md` |

To resume a delivery, see pending items or know which document to trust:
`docs/agents/state.md`. File map: `docs/agents/architecture.md`.
Map: `core/` calculations/data; `strategies/` signals; `configs/` parameters;
`ui/` screen; `tests/` isolation; `scripts/` checks. Flow: data → mining
→ WFA → Candidate → variant's plan → portfolio → paper/demo/real.

## Project agents

Use agents only when they save real work, per the task size.
With no agent available, report your own execution; do not claim an independent review.
Agents: `.claude/agents/`.
