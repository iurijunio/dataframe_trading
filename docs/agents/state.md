# Project state — documents and pending items

> Part of `AGENTS.md`. Read it when the task is to resume a delivery, choose
> the next step or find out which document to trust. Update it at the end of each delivery.

## Documents: which one to trust

| Document | State (2026-11-04) |
|---|---|
| `docs/superpowers/specs/2026-11-03-busca-automatica-design.md` (+ prototype `2026-11-03-busca-automatica/layout-b.html`, visual contract) | automatic niche search — implemented, all on `master`; section 3 of the spec went stale, "State after the implementation (2026-11-04)" is the valid one |
| `docs/superpowers/specs/2026-11-01-menu-e-mineracao-design.md` | menu redesign and Backtest inside Mining — implemented, on `master` |
| `docs/superpowers/specs/*` | design of each recent delivery — **most reliable source** for the why |
| `docs/CALCULOS-WFA.md`, `docs/CALCULOS-CANDIDATA.md` | how each number is calculated — reliable |
| `docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md` | spec of part 4 (orders) — implemented; `...-ordens-decisoes.md` is the draft that originated it |
| `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` | CME assets; the sections "Inheritance from stage 1", "State after stage 2", "State after stage 3" and "State after stage 4" say what remained |
| `CHANGELOG.md` | updated up to the automatic search and layer 4 in it (2026-11-04); **does not cover variants, portfolio or trigger** |
| `README.md` | updated up to the automatic search (2026-11-04); the MVP text remains as history |
| `docs/METODOLOGIA.md` "Estado da plataforma" | updated on 2026-11-04 |

When document and code disagree, the code rules. Use the `documenter`
agent to bring the documentation up to date after a delivery.

## Where we are

On `master`: Candidate, MT5, Portfolio (identity, correlation, re-optimization seal), Live parts 1 to 5 (capture,
paper, orders on demo, real account, stop and target watcher), CME assets in research only (stages 1 to 4, no broker
to trade), menu redesign, Automatic Search, orders × paper and orders × backtest reconciliations (2026-11-05) and
direct promotion to the real stage (2026-11-06).

There are strategies on the **real account**: stage, contracts and Sending of each one are on the screen's sheet (the database is the
source, not this file). Each delivery's history is in `CHANGELOG.md`, under "Histórico da plataforma".

Future delivery: an **Account** tab at the top (name chosen by the user; never "Desk"), with control and view per account and
asset. No spec yet. LLM features only outside the order path.

## Pending items

- **"Channel period" (user report):** after "Mine the region", the user edited the range to 3 to 20 and
  mining ran with the range inherited from the search. Not reproduced; reproduce with the real app closed.
- **Check on screen:** the "Promote to real" promotion and the floating notice (`e35a009`), with the real app closed.
- **React error #31 (twice) when opening the app:** a `{props, type, namespace}` object as a child; cause unknown.
- Question: can live paper's short warm-up diverge from the full-history backtest? Menu not following the
  mining asset restored after F5.
- Small CME pending items: "State after stage 2" and "State after stage 3" of the spec.
- **Target "only touched"** (noted on 10-19): the price touches the target and does not go through;
  paper counts the target, but the broker's limit TP sits in the queue and does not
  execute. Still to do: (a) measure in the plans' history how many target exits
  were only a touch and how much they weigh; (b) decide the rule — backtest requiring a pass of
  1 tick and/or keeping the TP for up to N min and exiting at market if the price moves X ticks away.
- **Small cleanups, no effect on screen:** `MOTIVO_CAPTURA` in
  `ui/components/pregao_panel.py` is unused; `ui/components/catalogo.py`
  still lists trailing under "Protections" (the new menu put it under Exit);
  `State("mine-carregar")` unused in a Mining callback; the redesign's
  saved-mining test is trivial.
- **Trigger, slice 2**: warn on the Portfolio screen that correlation/risk
  are out of date because a member variant's active plan changed.
  Described as out of scope in `docs/superpowers/specs/2026-09-24-gatilho-reotimizacao-design.md §8`
  — it **still has no spec of its own**; start with brainstorming.
