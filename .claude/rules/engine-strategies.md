---
paths:
  - "core/engine/**"
  - "core/codigo.py"
  - "core/busca/motor.py"
  - "core/busca/avaliador.py"
  - "strategies/**"
  - "configs/strategies/**"
  - "scripts/resign_code_hash.py"
---
# Engine and strategies

## Touched the engine? The suite must stay identical

- Run `tests/test_motor_camadas.py` (golden file) and the whole suite before and after.
- **Changed strategy code?** Run
  `scripts/resign_code_hash.py --since <commit> --apply`. Paper reads the
  `codigo_hash` every cycle: change it only outside the trading session, with the app and
  the capture closed. Plans 5, 6 and 7 re-signed on 2026-10-29, identical trades
  (backup in `backups/2026-10-29-antes-reassinar/`).
- **Layered engine** (`preparar` = signal, expensive; `executar` = window, days,
  direction, stop and target). The golden file `tests/dados/motor_camadas.json`
  **is never re-recorded**; `tests/test_motor_camadas.py` checks it (helpers in
  `tests/_motor_camadas_helpers.py`). Touched the engine? Run it.
  Valid until: the next engine refactor ships; then delete the proof (golden file, its test and helpers) and this line.
- **A saved plan is untouchable:** a strategy change gives an identical result at the default (equivalence test).
- **New strategy:** unique parameter names, never a field of `ExecutionProfile`
  (`tests/test_estrategias_nomes.py`); a recursive indicator (EMA/Wilder) declares `aquecimento_barras`; before
  saying it is done, open the sidebar in a copy of the app and check fields, mining and backtest.
- ADX is Wilder's: **it does not match the standard MT5 ADX**. On the M7/M11/M13/M17 timeframes the session's first
  candle comes out partial (they count from midnight); the same in every mode.
