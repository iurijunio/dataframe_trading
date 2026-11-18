---
paths:
  - "ui/**"
---
# Screen

- **Text:** short title, no visible subtitle or explanatory sentence. Explanation only in the (?) (`dica` in
  `ui/components/cartao.py`); never remove a (?) that already exists.
- **An approved prototype is a contract:** it ships identical, measurements included. Does not fit = stop and ask, showing the
  alternative. An existing function the prototype did not show stays, fitted into the look. Compare with screenshots.
- **Every screen or draft uses the skills** `frontend-design:frontend-design`, `design:design-critique`,
  `design:accessibility-review` and `design:ux-copy`. The `ui-designer` agent does not have the Skill tool: give it
  the SKILL.md paths. For a new feature with a screen, offer browser drafts once.
- **A copy of the app opens the real database with write access:** only with the real app closed (a hook refuses while the app is open).
  With it open, verify through tests and leave the screen for later. A visual complaint right after a delivery:
  first ask whether the user has already reopened `iniciar.bat`.

**Checking on screen against the real database** (`data/database.duckdb`) is
mandatory for a UI change. Careful: a wrong click or scroll on a numeric
field changes real data — note the value beforehand and restore it afterwards.

After any screen change, warn prominently: **close and reopen
`iniciar.bat`** — the open app does not load new code or CSS.

- **Never pass a dictionary (or anything that is not a component) as a
  child of `html.*`.** Dash 4 fails to render and silently returns the
  state of OTHER components: the menu and sub-screens went back by themselves to
  the previous tab (`421cc4f`: the Operação header received the whole
  `contrato_dia`). Switching to `dcc.Tabs` (`47b00bb`) was not the problem and was
  reverted (`d0d180b`). Format the text before putting it on screen.
- **Numeric field:** a focused `<input type=number>` changes value with the mouse
  wheel (Chrome bug). Use `type="text"` + `inputMode="numeric"` + manual parsing;
  `ui/assets/num_input.js` protects the rest of the app.
- **Money on screen: always `cartao.dinheiro(v, moeda)`**, with the currency from
  `ativo.moeda_de(simbolo)`. Components take `moeda="BRL"` as the default.
- **Changed a research screen? Run `scripts/screens_reference.py check`**
  (mandatory; WIN must come out identical). Only re-record the reference from
  the code as it was before the change. Permanent, owner-approved 2026-11-18: a standing WIN-screens
  regression net (`scripts/screens_reference.py` + `tests/dados/telas_win/`); it has no expiry.
- **Currency label ids: one `type` per screen** (`moeda-c4`, `moeda-cand`).
- **(?) texts in fixed layouts stay in R$** (list in the spec, "State after
  stage 3"); do not try to swap them one by one.
