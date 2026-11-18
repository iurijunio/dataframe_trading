# Agent team — plan (2026-11-09)

**Goal:** spend fewer tokens without losing quality where money is at stake. The main
conversation on Opus thinks and decides. The manual work goes to Sonnet or Haiku.

**Choice rule:** Haiku for a mechanical task whose answer can be checked.
Sonnet for coding. Opus only where an error would go unnoticed (calculation, orders, review).

> Naming note (2026-11-17): the agents were renamed to English. Old → new:
> `designer-ui` → `ui-designer`, `mutacao` → `mutation`, `documentador` → `documenter`,
> `testador` → `tester`, `executor` → `implementer`, `revisor` → `reviewer`. The steps
> below use the new names.

## Steps

1. **Change the model of the agents that already exist** (only the `model:` line)
   - `ui-designer`: opus → sonnet
   - `mutation`: sonnet → haiku
   - `documenter`: sonnet → haiku
   - `reviewer` and `auditor` stay on opus

2. **Create the `tester`** (`.claude/agents/tester.md`, haiku, no Edit/Write)
   - Runs pytest (the requested file or the whole suite) and `scripts/check_changes.py`.
   - Returns at most: how many passed and failed, each failure with file:line and
     the exact error message, and what `check_changes.py` said to reopen.
   - Never fixes anything and never touches `data/`.

3. **Create the `implementer`** (`.claude/agents/implementer.md`, sonnet)
   - Implements **one** step of an already-written plan, with the files already indicated.
   - Follows AGENTS.md rules: test first, `core/` without Dash.
   - Does not commit. Returns what changed (file:line) and the test result.
   - Do not use on orders/real account without the `reviewer` afterwards.

4. **Model of the generic agents:** in `.claude/settings.json`, `env` →
   `"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"`. Applies only to an agent without its own `model:`.

5. **AGENTS.md** — update the "Project agents" table with `tester` and
   `implementer`, and one line: "a large search goes to `Explore` (Haiku)".
   Check that AGENTS.md's size test still passes.

6. **Check:** harness `tests/` green; open a new session and call each
   new agent once on a small task to see whether it replies briefly and on the right model.

## Done

- Steps 1 to 5 above (`224a5c6`).
- Lock on orders, the journal and `git clean -x` in the guard hook (`4d93a16`).

## Queue (2026-11-10)

1. **Judge at the end of the turn** (`Stop` hook), looking only at what changed in the `git diff`:
   a screen callback touched → run `tests/test_callbacks_sem_ciclo.py`;
   `core/` or `ui/` touched without a test run → do not let it finish and ask for the test
   of the touched file; code touched → show what `scripts/check_changes.py` says
   to reopen. Fast (seconds), never the whole suite.
2. **Auto mode aware of the real account:** an `autoMode` block in
   `~/.claude/settings.json` (with `"$defaults"` in every list).
3. **Measure with `/usage`** before and after the changes.
4. **Python plugin (pyright)**, only with measurement before and after (lesson from graphify).
5. **`/delivery` skill** with the high-impact change flow, moving out of AGENTS.md.
6. Check whether superpowers is installed, after the `modularizacao`
   worktree session ends.
