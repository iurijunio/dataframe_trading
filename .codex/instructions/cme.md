---
paths:
  - "core/ativo.py"
  - "core/importar_lse.py"
  - "configs/instruments/**"
---
# Ativos da CME

## Ativos da CME (MES, MNQ; `core/ativo.py`, spec `docs/superpowers/specs/2026-10-28-ativos-cme-design.md`)

- **Três unidades, cada lugar usa uma.** *Humana* (pontos, hora de NY) na
  tela, no YAML, nos perfis e nos `params`/`profile` salvos. *Guardada*
  (preço × 10^`price_decimals`, relógio de pregão = hora de NY + 360 min) em
  barras, motor e registros de trade (`points`, `entry_px`, `wfa_trades`…).
  *Dinheiro* na moeda do ativo.
- **A conversão humana → guardada só acontece em `run_strategy`, numa
  cópia.** Nunca converta em outro lugar (dupla conversão): o instrumento
  convertido guarda `_original`. Guardada → humana só na tela, via
  `core/ativo.py`. O WIN é identidade (escala 1, deslocamento 0).
- **Faixas por ativo (etapa 4):** vêm de `faixas:` em `mes.yaml`/`mnq.yaml`
  via `core.ativo.faixas_do_ativo(simbolo, estrategia=None)` e **só
  preenchem a tela**; motor, otimizador, validação, WFA e Candidata não as
  conhecem. Ordem, campo a campo: mineração > faixa do ativo > padrão da
  estratégia / `PADRAO_C4`. Automação futura de mineração tem de pedir as
  faixas a `faixas_do_ativo`, não ao schema. Stop/alvo padrão aprovados:
  MES 8/16, MNQ 45/90 (tabela na spec).
- **Salvar plano em MES/MNQ já é permitido na pesquisa**, mas operar não:
  não há corretora para os micros.
- **Portfólio recusa moedas misturadas** (`MoedaMista`), também quando o
  plano ativo de uma variante troca de ativo.
