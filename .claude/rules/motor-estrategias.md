---
paths:
  - "core/engine/**"
  - "core/codigo.py"
  - "core/busca/motor.py"
  - "core/busca/avaliador.py"
  - "strategies/**"
  - "configs/strategies/**"
  - "scripts/foto_win.py"
  - "scripts/gabarito_motor.py"
  - "scripts/reassinar_codigo.py"
---
# Motor e estratégias

## Foto do WIN é obrigatória antes e depois de mexer no motor

  `scripts/foto_win.py gravar` / `conferir` (banco congelado em
  `data/foto_win/<nome>.duckdb`, fora do git). Tem de dar idêntico.
- **Mudou código de estratégia?** Rode
  `scripts/reassinar_codigo.py --de <commit> --aplicar`. O papel lê o
  `codigo_hash` a cada ciclo: troque só fora do pregão, com o app e a
  captura fechados. Planos 5, 6 e 7 reassinados em 29/10/2026, trades
  idênticos (backup em `backups/2026-10-29-antes-reassinar/`).
- **Motor em camadas** (`preparar` = sinal, caro; `executar` = janela, dias,
  direção, stop e alvo). O gabarito `tests/dados/motor_camadas.json`
  **nunca se regrava**; `scripts/gabarito_motor.py conferir` o confere. Mexeu
  no motor? Rode-o junto com a foto do WIN.
- **Plano salvo é intocável:** mudança em estratégia dá resultado idêntico no padrão (teste de equivalência).
- **Estratégia nova:** nomes de parâmetro únicos, nunca um campo do `ExecutionProfile`
  (`tests/test_estrategias_nomes.py`); indicador recursivo (EMA/Wilder) declara `aquecimento_barras`; antes de
  dizer que está pronta, abra a barra lateral numa cópia do app e confira campos, mineração e backtest.
- O ADX é o de Wilder: **não bate com o ADX padrão do MT5**. Nos tempos M7/M11/M13/M17 a primeira vela do pregão
  sai parcial (contam da meia-noite); igual em todos os modos.
