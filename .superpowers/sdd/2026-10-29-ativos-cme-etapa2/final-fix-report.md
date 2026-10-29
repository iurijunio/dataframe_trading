# Final fix wave - etapa 2

1. rompimento_ema_abertura: `depois_ref` usa `>` (barra de abertura nao sinaliza; 1o sinal na seguinte). WIN igual (1a barra ja nao tinha anterior). RED: 2 testes falham com `>=`; GREEN. Arquivos: strategies/rompimento_ema_abertura.py, tests/test_estrategias_ativo.py.
2. D1: `trade_markers(..., d1=False)`; com ficha deslocada e d1, marcadores no dia do pregao (sem -6 h); `desenhar` passa `dados["timeframe"] == "D1"`. WIN inalterado (teste). RED: TypeError antes. Arquivos: ui/components/charts.py, ui/callbacks.py, tests/test_telas_ativo.py.
3. `janela_valida(ini, fim, f, fechamento=None)`: recusa fechamento antes do fim ou na pausa (apos 17:00 NY); vazio/None nao confere; callers rodar/minerar passam o fechamento. RED/GREEN em tests/test_perfil_por_ativo.py. Arquivos: core/ativo.py, ui/callbacks.py.
4. Teste: sessao MES sem barra >= 09:30 NY nao sinaliza nem erra (rompimento_abertura e rompimento_ema_abertura). Ja passava (so lacuna de teste).

Nota: no WIN fechamento < fim agora tambem e recusado (ordem do pregao).
