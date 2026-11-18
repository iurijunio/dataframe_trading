---
paths:
  - "busca.py"
  - "core/busca/**"
  - "ui/callbacks_busca.py"
  - "ui/components/busca_panel.py"
  - "ui/assets/busca.js"
  - "ui/assets/busca.css"
  - "scripts/verify_search.py"
---
# Automatic Search

## Automatic Search (`core/busca/`, `busca.py`; spec `docs/superpowers/specs/2026-11-03-busca-automatica-design.md`)

- **Own database `data/buscas.duckdb`** (outside git). Open, use, close: never
  keep it open. When busy it raises `BancoOcupado`; the app shows that and retries later.
- **The search runs in the `busca.py` process**, windowless and below normal
  priority, and only reads Parquet (never the main database) — that is why it
  runs during the trading session. **One live search at a time**, marked by an
  `msvcrt` lock. Never `os.kill` (on Windows it kills) nor the `Popen` pid (it
  is not the real process's pid).
- **`scripts/verify_search.py <busca_id>`** proves the search gives the Scan's
  number (it redoes the best elites through the old path, with no tolerance).
  Valid until: the old Scan path is removed or the search engine changes again; then delete the proof and this line.
- **Period fixed at creation** of the search: it does not change afterwards.
- **"Open the champion in Backtest"** carries the search's slice (`store-combinacao`
  with `origem: "busca"`); Mine and Mine the region erase it.
  `perfil_da_busca` = menu profile + the protections.
- **The screen is `ui/assets/busca.js`**, built from the prototype (contract); Dash
  only sends data through the `busca-*` stores. Visual deviation: ask first.
- **JSON without `inf`/`NaN`** for the browser (`_json_seguro` in
  `ui/callbacks_busca.py`).
- `ribs` brings scipy as a dependency; `core/robustez.py` stays without it.
- Changed `core/busca/*` or `busca.py`? A search in progress keeps running the
  old code: stop it and continue later.
