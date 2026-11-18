---
paths:
  - "core/portfolio.py"
  - "ui/callbacks_portfolio.py"
  - "ui/components/portfolio_panel.py"
---
# Portfolio

## Portfolio

- Combined curve/drawdown: trades from all variants **interleaved by the real
  closing date**, never one variant after the other.
- `profit_factor` / recovery factor become `+inf` with no loss at all — outside the
  heatmap's min/max.
- Kelly with payoff `0.0` is ambiguous ("no edge" × "no loss yet") → a separate
  "undefined" state.
- Risk of ruin and growth simulator use **the same model**: fixed-fraction
  bet, in multiples of R (R = historical average loss). Do not diverge.
