---
paths:
  - "core/portfolio.py"
  - "ui/callbacks_portfolio.py"
  - "ui/components/portfolio_panel.py"
---
# Portfólio

## Portfólio

- Curva/drawdown combinado: trades de todas as variantes **intercalados pela data
  real de fechamento**, nunca uma variante depois da outra.
- `profit_factor` / fator de recuperação viram `+inf` sem nenhuma perda — fora do
  min/max do mapa de calor.
- Kelly com payoff `0.0` é ambíguo ("sem vantagem" × "ainda sem perda") → estado
  "indefinido" separado.
- Risco de ruína e simulador de crescimento usam **o mesmo modelo**: aposta de
  fração fixa, em múltiplos de R (R = perda média histórica). Não divergir.
