---
paths:
  - "core/optimizer.py"
  - "core/walkforward.py"
  - "core/mineracao_stats.py"
  - "core/porteira.py"
  - "core/wfa.py"
  - "core/wfa_runner.py"
  - "ui/components/mining.py"
  - "ui/components/mine_*.py"
  - "ui/components/scatter.py"
  - "ui/components/controls.py"
  - "ui/components/catalogo.py"
---
# Mining

- **Mining without copies:** a field of a type that was not chosen (ATR with a
  target in points, DI in the range) and the variations of a disabled ADX give an
  identical result — `optimizer.espaco_util` / `combinacoes_uteis` prune before
  sweeping (mining and WFA). Copies create a false plateau in `score_vizinhanca`.
- **Decimal range:** `(ate - de) / passo` gives 2.9999…; round before the
  `int()` or the last value disappears.
- **Mirror, don't copy:** a list that already exists in the code (`core.engine.execution.TIMEFRAMES`,
  `ui/components/catalogo.OPCOES`, `params_schema`) is reused or mirrored by code, never typed or
  copied from a prototype. Where it cannot be imported, a test proves the lists match. Invented default range:
  wide, saying where it came from.
