# Architecture on one screen

The four layers (question: *whose information is this?*):

| Layer | Where | Content |
|---|---|---|
| 1 Instrument | `configs/instruments/*.yaml` | tick, point value, rollover |
| 2 Strategy | `strategies/*.py` | signals only (`Signals`); dropping the file in the folder is enough (`strategies/registry.py`) |
| 3 Parameters | `configs/strategies/*.json` / `params_schema` | default, min, max, step |
| 4 Execution | table `execution_profiles` | schedule, stop/target, costs, size — applied by the engine, never by the strategy |

The six modes at the top (`ui/app.py`; the app opens on Live › Strategies) and
where they live. Backtest is no longer a tab: it is Mining's Backtest sub-screen
(Scan | Automatic Search | Backtest), and clicking a row, a cloud point or an approved one runs the
backtest and jumps to it:

| Mode | Calculations (`core/`) | Screen (`ui/`) |
|---|---|---|
| Mining (Scan + Automatic Search + Backtest) | Scan: `optimizer.py`, `walkforward.py`, `mineracao_stats.py`, `porteira.py`. Automatic Search: `busca/*` (catalogo, espaco, avaliador, motor, nucleos, banco, controle, prioridade, grupos, projecao, detalhe) + the root `busca.py` process. Backtest: `engine/kernel.py`, `engine/execution.py` (`preparar`/`executar`), `metrics.py`, `analytics.py`, `detalhes.py`, `robustez.py` | `components/mining.py`, `mine_*.py`, `scatter.py`; Search: `callbacks_busca.py`, `components/busca_panel.py`, `assets/busca.js`, `assets/busca.css`; Backtest: `callbacks.py`, `components/stats_cards.py`, `charts.py`, `results_grid.py` |
| Walk-Forward | `wfa.py`, `wfa_runner.py`, `wfa_store.py` | `components/wfa_panel.py` |
| Candidate | `candidata.py`, `candidata_runner.py`, `aleatorio.py`, `spa.py`, `tamanho.py`, `plano.py` | `callbacks_candidata.py`, `components/candidata_panel.py` |
| Strategies | `variantes.py` | `callbacks_estrategias.py`, `components/estrategias_panel.py` |
| Portfolio | `portfolio.py` | `callbacks_portfolio.py`, `components/portfolio_panel.py` |
| Live | `ao_vivo.py`, `diario.py`, `codigo.py`, `captura.py` (the capture process is the root `captura.py`, opened by `captura.bat`), `papel.py`, `papel_leitura.py`, `papel_vivo.py`, `papel_backtest.py`, `conferencia_ordens.py`, `ordens_backtest.py`, `corretora.py`, `ordens.py`, `diario_ordens.py`, `comandos.py`, `contrato_dia.py` | `callbacks_ao_vivo.py`, `components/ao_vivo_panel.py`, `callbacks_pregao.py`, `components/pregao_panel.py`, `callbacks_operacao.py`, `components/operacao_panel.py`, `components/ordens_panel.py` |

Others: `core/mt5_source.py` (synchronization with MT5, no button on the screen — the
capture already fills what is missing; `ui/callbacks_mt5.py` was removed); `core/plano.vencendo` + a topbar seal (re-optimization due);
`ui/callbacks.py:register` registers all the `callbacks_*.py` (the call lives in `ui/cb_pesquisa/r_resto.py`).

A large file became a package: the old file is a **shell** that only re-exports, and the code lives in the package:

| Shell | Package |
|---|---|
| `ui/callbacks.py` | `ui/cb_pesquisa/` (menu, Backtest, mining, Walk-Forward) |
| `ui/callbacks_operacao.py` | `ui/cb_operacao/` |
| `ui/components/operacao_panel.py` | `ui/components/operacao/` |
| `ui/components/ordens_panel.py` | `ui/components/ordens/` |
| `ui/components/ao_vivo_panel.py` | `ui/components/ao_vivo/` |
| `core/papel_leitura.py` | `core/leitura/` |

To swap a name in a test (`monkeypatch`), target the package module where it is used, not the shell. A new
split: only a change of place, proven by `scripts/verify_split.py --since <commit>`.

Data flow: mining (`mining_runs`, with `variante_id`) → walk-forward
(`wfa_runs`, `wfa_trades` = out-of-sample trades) → Candidate writes
`planos_operacao` (snapshots, not references) → Portfolio references **only the
variant** and resolves the active plan on the spot (`variantes.plano_ativo`).
