---
paths:
  - "ordens_real.py"
  - "captura.py"
  - "core/ordens.py"
  - "core/corretora.py"
  - "core/ordem_teste.py"
  - "core/ponte.py"
  - "core/comandos.py"
  - "core/diario_ordens.py"
  - "core/papel_vivo.py"
  - "core/conferencia_ordens.py"
  - "core/ordens_backtest.py"
  - "core/ao_vivo.py"
  - "core/mt5_source.py"
  - "ui/callbacks_ordens.py"
  - "ui/callbacks_ao_vivo.py"
  - "ui/components/ordens_panel.py"
  - "ui/components/ordens/**"
  - "ui/components/ao_vivo_panel.py"
  - "ui/components/ao_vivo/**"
  - "core/diario.py"
  - "core/db_manager.py"
  - "core/schema.sql"
  - "iniciar.bat"
  - "captura.bat"
  - "ordens_real.bat"
---
# Orders and the real account

- **Every wrong order is money.** Before using the MetaTrader 5 API (`order_send`, `positions_get`, filling,
  retcodes, `symbol_info`), check the official documentation (mql5.com/en/docs, mql5.com/en/docs/python_metatrader5)
  and cite what you checked; treat what it does not guarantee as uncertain and protect against it.
- **Stop and target watcher:** paper exits on touch, on the forming candle. The broker has 1 s to execute the touched level;
  after that the automation exits at market and opens an incident. An execution with no trade at that price is marked "outside the market".

## Orders on demo (part 4; `core/corretora.py`, `ordens.py`, `papel_vivo.py`)

- **Provisional bar:** the forming minute counts for signal, never for
  stop/target/indicator; the entry's stop and target come from the candle closed up to the previous
  minute (`0dfa0db`, `engine.VERSAO` 2026.10.09 — closes the look-ahead of
  M1+ATR). A forced exit on the provisional bar stays open.
- **The order path never waits for the database:** live paper and decision come from
  memory and `estado.json`; the event goes first to the `.jsonl` (`fsync`) and
  to the database only when it is free.
- **Desired "unavailable" = do nothing, do not flatten:** stale data or a
  missing calculation does not close an open position.
- **MT5 return codes: a single table** in `core/corretora.py`, tested line by
  line. UNCERTAIN (10012, and `None`) may have executed: adopt/check before
  resending. ACCEPTED (10008, PLACED) is received, the trade comes later.
  10036 is "already out", not a failure.
- **Filling by mask:** `SYMBOL_FILLING_MODE` is a mask (FOK=1, IOC=2), not
  the value of `ORDER_FILLING_*` (FOK 0, IOC 1, RETURN 2); on an exchange, RETURN counts
  as a last resort.
- **A `None` from MT5 is only understood with `last_error()`:** with no error (1) it is "no
  response", not a configuration failure.
- **An account locked by the loss limit lasts until the next session, with no
  unlock button** (event `conta_travada`, survives a restart).
- **"Turn off sending" writes the command before touching the database** (and the sending
  goes in the command); a busy database cannot hold up the shutdown.
- **An empty loss limit is not saved with Sending on**, and an empty limit
  does not turn sending off by itself.
- Sending is born **off** (`contas.envio_ligado`) and logs "would be sent".
  The rehearsal passes the SAME request through `order_check` (never sends; retcode 0
  = passed) and records `retcode`/`comment` (or `last_error`); the screen shows
  "would be refused: …".
- **Partial snapshot:** positions and orders read, but history/trades/account
  failed → only exit and protect (no entering, adopting, lost or
  "exited earlier"). Without a readable account, use the one from the same connection. Incomplete snapshot
  > 30 s in the session (or unreadable with an open position) → incident `sem_leitura`.
  Exception to "only protect": the SINGLE candidate of an entry with no response, no SL,
  receives the stop/target of the `enviando` that opened it (never paper's), without being
  adopted, and with the stop refused > 2 s it closes as in the complete snapshot; two
  candidates or sending without a stop → incident `sem_stop` (`_orfa_na_parcial`).
- **"Flatten all" from another day** (clicked outside the session with no position, read on the
  next morning) is discarded in the journal — it does not turn off today's sending.
- **Saved snapshot** (`data/ao_vivo/ordens/retrato.json`, atomic write):
  a startup with the database locked uses the last snapshot, marked old — it protects and
  exits by command/lock, nothing enters.
- **Test order** (`core/ordem_teste.py`; **the button is off the screen**, the
  engine, the command and the Journal remain — it can be turned back on; see
  `git diff 421cc4f..be5ba7f -- ui/`; the real-account "Test" button also
  left the screen — engine kept; see git 6ceaa18 to bring it back):
  an `ordem_teste` command that the capture executes after the strategies'
  actions, one step per loop, with no `sleep` (buy 1 · SL/TP at 100 pts
  · check · 10 s on the monotonic clock · exit by ticket). Magic `MAGIC_TESTE` =
  7,000,000, outside the links' range: planning/adoption/flatten/Close
  never touch it; only it closes its own (including one left over from a
  restart). It refuses without `account_info().trade_mode` ==
  `ACCOUNT_TRADE_MODE_DEMO`, a registered demo account, session, Algo, lock,
  contract/guard, Flatten or a request > 60 s old; it is independent of Sending. Exit
  refused > 10 s → incident `teste_preso`. 10008 and transient codes are not a
  failure (transient: again every 1 s, up to 5 s); outside the session and outside the
  DEMO account the close does not resend.
- "Exited earlier" only for a ticket the automation itself did not close; an
  entry with no response only matches a trade after the operation's 1st sending
  and never with another operation's ticket.

## Real account (part 5; `ordens_real.py`, `core/ponte.py`, `core/comandos.py`)

- **One MT5 terminal per process.** The capture and Ordens real each have their
  own `mt5.initialize(path=…)`; never switch accounts within the same process.
- **The capture only opens the DEMO account's terminal**; the real one only opens the
  real account's terminal, through the path registered in `contas.terminal`.
- **The account type is checked on every loop** (login and `trade_mode`: DEMO in the
  capture, REAL in the real one). Wrong account = incident `conta_errada`, nothing goes out.
- **Bridge `data/ao_vivo/desejados.json`:** atomic write, with a heartbeat
  (`vivo_em`) on every capture loop. The real one only acts on a desired state up to 5 s old
  (otherwise it is unavailable: only protects).
- **Ack `ack_real.json` of up to 200 ms:** demo waits for the real one to handle a new `seq`
  only when the real process is alive; without it demo carries on without waiting.
- **Command folders per account:** `data/ao_vivo/comandos` (demo) and
  `data/ao_vivo/comandos_real` (real). Each process reads only its own.
- **`zerar_tudo` goes to both folders**, without reading the database.
- **`ordens_eventos.origem`** (`demo` or `real`): every event reader filters
  by origin. The one that mirrors the real account into the database is the capture, never the real process.
- **Test order on the process's account** (demo or real, enabled on real on 2026-10-21): button off the screen since 10-21 (engine kept; to turn it back on see commit 6ceaa18); it checks login, registered type and MT5 trade_mode before sending; it does not depend on Sending.
- **Protected data:** `data/ao_vivo/ordens/real/*.jsonl` is never deleted (it is the
  write-ahead journal of the real account, like demo's).
- **Orders × paper on the same day** (`core/conferencia_ordens.py`, since
  2026-11-05): on every stored paper the capture compares the desired states with it,
  only with the SAME bar minute (`captura._momento`). A divergence across 3
  distinct bar minutes, with no equality in between, opens incident
  `divergencia_papel`; it closes when they match again. It only warns, never touches an order.
- **Orders × backtest** (`core/ordens_backtest.py`, table `ordens_backtest`):
  in the morning, only a finished session; per origin; every day in the account's stage and on,
  also with no order (= it stopped entering) if the account has proof of life that day (`rolagem`, which the real one also records); otherwise: rehearsal, no data. A difference
  from today's code/engine blocks the promotion, like paper's.

`iniciar.bat` opens **three** windows: **Dataframe - Captura** (`captura.bat`),
**Dataframe - Ordens real** (`ordens_real.bat`) and the app's. If you changed
`core/ordens.py`, `core/corretora.py`, `core/papel_vivo.py`, `core/ponte.py`
or `ordens_real.py`, close **both** windows (Captura and Ordens real) before
reopening `iniciar.bat`, for the same lock reason.
