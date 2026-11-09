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
  - "scripts/campos_menu.py"
---
# Mineração

- **Mineração sem cópias:** campo de um tipo não escolhido (ATR com alvo
  em pontos, DI no rango) e as variações do ADX desligado dão resultado
  idêntico — `optimizer.espaco_util` / `combinacoes_uteis` podam antes de
  varrer (mineração e WFA). Cópias criam platô falso no `score_vizinhanca`.
- **Faixa decimal:** `(ate - de) / passo` dá 2,9999…; arredonde antes do
  `int()` ou o último valor some.
- **Mexeu em campo do menu (Mineração/Backtest)? Rode
  `scripts/campos_menu.py`.** Ele compara com `tests/dados/campos_menu.json`
  (gravado do menu antigo; **nunca regravar**) e prova que nenhum campo
  mudou de id, valor, faixa, passo ou rótulo além das trocas permitidas.
- **Espelhar, não copiar:** lista que já existe no código (`core.engine.execution.TIMEFRAMES`,
  `ui/components/catalogo.OPCOES`, `params_schema`) é reaproveitada ou espelhada por código, nunca digitada ou
  copiada de protótipo. Onde não dá para importar, um teste prova que as listas batem. Faixa padrão inventada:
  larga, dizendo de onde veio.
