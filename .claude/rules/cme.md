---
paths:
  - "core/ativo.py"
  - "configs/instruments/**"
---
# CME assets

## CME assets (MES, MNQ; `core/ativo.py`, spec `docs/superpowers/specs/2026-10-28-ativos-cme-design.md`)

- **Three units, each place uses one.** *Human* (points, NY time) on the
  screen, in YAML, in profiles and in saved `params`/`profile`. *Stored*
  (price × 10^`price_decimals`, session clock = NY time + 360 min) in
  bars, engine and trade records (`points`, `entry_px`, `wfa_trades`…).
  *Money* in the asset's currency.
- **Human → stored conversion happens only in `run_strategy`, on a
  copy.** Never convert anywhere else (double conversion): the converted
  instrument keeps `_original`. Stored → human only on the screen, via
  `core/ativo.py`. WIN is the identity (scale 1, offset 0).
- **Per-asset ranges (stage 4):** come from `faixas:` in `mes.yaml`/`mnq.yaml`
  via `core.ativo.faixas_do_ativo(simbolo, estrategia=None)` and **only
  fill in the screen**; engine, optimizer, validation, WFA and Candidate do not
  know them. Order, field by field: mining > asset range > strategy default /
  `PADRAO_C4`. Future mining automation must ask `faixas_do_ativo` for the
  ranges, not the schema. Approved default stop/target:
  MES 8/16, MNQ 45/90 (table in the spec).
- **Saving a plan on MES/MNQ is already allowed in research**, but trading is
  not: there is no broker for the micros.
- **Portfolio refuses mixed currencies** (`MoedaMista`), also when a variant's
  active plan switches asset.
