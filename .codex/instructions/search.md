---
paths:
  - "busca.py"
  - "core/busca/**"
  - "ui/callbacks_busca.py"
  - "ui/components/busca_panel.py"
  - "ui/assets/busca.js"
  - "ui/assets/busca.css"
  - "scripts/conferir_busca.py"
---
# Busca automática

## Busca automática (`core/busca/`, `busca.py`; spec `docs/superpowers/specs/2026-11-03-busca-automatica-design.md`)

- **Banco próprio `data/buscas.duckdb`** (fora do git). Abre-faz-fecha: nunca
  segure aberto. Ocupado vira `BancoOcupado`; o app mostra e tenta depois.
- **A busca roda no processo `busca.py`**, sem janela e abaixo do normal, e só
  lê o Parquet (nunca o banco principal) — por isso roda no pregão. **Uma
  busca viva por vez**, marcada por trava `msvcrt`. Nunca `os.kill` (no
  Windows mata) nem o pid do `Popen` (não é o do processo real).
- **`scripts/conferir_busca.py <busca_id>`** prova que a busca dá o número da
  Varredura (refaz as melhores elites pelo caminho antigo, sem tolerância).
- **Período fixo na criação** da busca: não muda depois.
- **"Abrir o campeão no Backtest"** leva o recorte da busca (`store-combinacao`
  com `origem: "busca"`); Minerar e Minerar a região o apagam.
  `perfil_da_busca` = perfil do menu + as proteções.
- **A tela é de `ui/assets/busca.js`**, a partir do protótipo (contrato); o
  Dash só manda dados pelos stores `busca-*`. Desvio visual: perguntar antes.
- **JSON sem `inf`/`NaN`** para o navegador (`_json_seguro` em
  `ui/callbacks_busca.py`).
- O `ribs` traz scipy como dependência; `core/robustez.py` segue sem ele.
- Mexeu em `core/busca/*` ou `busca.py`? Busca em andamento segue com o
  código antigo: pare-a e continue depois.
