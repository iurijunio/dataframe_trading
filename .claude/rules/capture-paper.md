---
paths:
  - "captura.py"
  - "core/captura.py"
  - "core/ingest.py"
  - "core/db_manager.py"
  - "core/schema.sql"
  - "core/mt5_source.py"
  - "core/reparo_base.py"
  - "core/rollovers.py"
  - "core/contrato_dia.py"
  - "core/papel.py"
  - "core/papel_backtest.py"
  - "core/papel_leitura.py"
  - "core/leitura/**"
  - "core/papel_vivo.py"
  - "core/plano.py"
  - "core/variantes.py"
  - "corrigir_base.py"
  - "cli.py"
  - "ui/callbacks_pregao.py"
  - "ui/callbacks_operacao.py"
  - "ui/cb_operacao/**"
  - "ui/components/pregao_panel.py"
  - "ui/components/operacao_panel.py"
  - "ui/components/operacao/**"
  - "iniciar.bat"
  - "captura.bat"
---
# Capture and paper

- **MT5 time:** the `time` of the bars MT5 returns **is already Brasília
  time** — do not add an offset. The 2026-09-23 sync subtracted 3 h
  and corrupted 03-16→09-23 (fixed on 2026-10-01; backup of the old database in
  `C:\Users\mrRobot\Documents\Neturna\backups\2026-10-01-antes-correcao-hora`).
  Never store the forming candle (the last minute returned).
- **Capture:** `captura.bat` (the capture service) is opened by `iniciar.bat`.
  There is no Sync button: the capture fetches bars from the last stored one. TODAY's bars
  exist only in the database until the day's reconciliation — Parquet and `data/raw` do not
  have them — so mining only sees today after it. That is why
  `cli.py verify` (which rebuilds from Parquet) with the capture running would erase
  the day: it refuses if `data/ao_vivo/estado.json` was updated less than
  60 s ago ("close the capture first"). The PC clock can lag ~1 min
  behind the broker; the capture uses the server clock (the screen warns
  above 30 s). Clear does not publish the current contract (`contrato_vigente` = None).
- **The broker consolidates overnight:** the closing auction stored live
  as its own candle (10-01: 18:31) becomes part of 18:24, morning minutes
  are redone, and `tick_volume`/`spread` (0 live, 5 consolidated) are revised.
  The capture re-reconciles each past day from 08:55 of the next day
  (`reconferir_dia`: deletes the candle MT5 no longer has, refuses an incomplete
  day, gives up after 5 sessions; it re-reconciles paper too). The merge ignores
  `tick_volume` and `spread` (they are neither price nor trade); `volume` is still compared.

## Paper (`core/papel.py`)

- It is a backtest by construction. The execution profile is built as in the WFA
  (`CAMPOS_EXECUCAO_NOMES`); never `ExecutionProfile.from_config`.
  `run_strategy(..., vela_aberta=True)` only in live paper.
- Warm-up is computed from the strategy's parameters; 10 sessions
  are not enough and the result diverges from the backtest.
- `op_id` is stable per (`ligacao_id`, `entry_ts`). Part 4 depends on it.
- A reconciled session stays frozen; the checksum flags divergence.
- The capture computes paper only on a new candle and redoes the paper
  reconciliation in the next window if it fails.
- The Operação screen reads `estado.json` every 2 s and only opens the database when
  `papel.calculado_em` changes.
- **Windows clock:** with the `w32time` service stopped the PC lagged 222 s.
  With MT5 connected the automation uses the broker's clock, but keep
  `w32time` on automatic start with the ntp.br servers.
- **Warm-up and reconciliation (2026-11-05):** live paper keeps the warm-up in memory. If the morning
  reconciliation changes candles, the capture re-reads the warm-up (`_reler_aquecimento`); without that live paper diverges from the
  backtest: ADX is recursive and a small change in the past becomes another signal (fix `0fcf282`, `12d157f`).

If you changed `captura.py`, `core/captura.py`, `core/ingest.py`, `core/db_manager.py`,
`core/schema.sql` or something paper uses inside the capture — `core/papel.py`,
`core/engine/*`, `core/plano.py`, `core/variantes.py`, `strategies/*` —,
also close the **Dataframe - Captura** window before reopening
`iniciar.bat`: the old capture holds the lock and the new one exits silently (code 4),
so reopening only `iniciar.bat` leaves the old code writing.
