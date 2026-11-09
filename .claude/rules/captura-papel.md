---
paths:
  - "captura.py"
  - "core/captura.py"
  - "core/ingest.py"
  - "core/db_manager.py"
  - "core/schema.sql"
  - "core/mt5_source.py"
  - "core/reparo_base.py"
  - "core/rollovers.py"
  - "core/contrato_dia.py"
  - "core/papel.py"
  - "core/papel_backtest.py"
  - "core/papel_leitura.py"
  - "core/papel_vivo.py"
  - "core/plano.py"
  - "core/variantes.py"
  - "corrigir_base.py"
  - "cli.py"
  - "ui/callbacks_pregao.py"
  - "ui/callbacks_operacao.py"
  - "ui/components/pregao_panel.py"
  - "ui/components/operacao_panel.py"
  - "iniciar.bat"
  - "captura.bat"
---
# Captura e papel

- **Hora do MT5:** o `time` das barras que o MT5 devolve **já é hora de
  Brasília** — não somar offset. A sincronização de 23/09/2026 subtraiu 3 h
  e corrompeu 16/03→23/09 (corrigida em 01/10/2026; backup do banco antigo em
  `C:\Users\mrRobot\Documents\Neturna\backups\2026-10-01-antes-correcao-hora`).
  Nunca gravar o candle em formação (o último minuto devolvido).
- **Captura:** o `captura.bat` (serviço de captura) abre pelo `iniciar.bat`.
  Não há botão Sincronizar: a captura busca as barras desde a última gravada. As barras de HOJE
  só existem no banco até a conferência do dia — o Parquet e o `data/raw` não
  as têm — então a mineração só vê o dia de hoje depois dela. Por isso
  `cli.py verify` (que reconstrói do Parquet) com a captura rodando apagaria o
  dia: ele recusa se o `data/ao_vivo/estado.json` foi atualizado há menos de
  60 s ("feche a captura antes"). O relógio do PC pode atrasar ~1 min em
  relação à corretora; a captura usa o relógio do servidor (a tela avisa acima
  de 30 s). O Clear não publica o contrato vigente (`contrato_vigente` = None).
- **Corretora consolida de madrugada:** o leilão de fechamento gravado ao vivo
  como candle próprio (01/10: 18:31) vira parte do 18:24, minutos da manhã são
  refeitos, e `tick_volume`/`spread` (0 ao vivo, 5 consolidado) são revisados.
  A captura reconfere cada dia passado a partir das 08:55 do dia seguinte
  (`reconferir_dia`: apaga o candle que o MT5 não tem mais, recusa dia
  incompleto, desiste após 5 pregões; reconfere o papel). O merge ignora
  `tick_volume` e `spread` (não são preço nem negócio); `volume` segue comparado.

## Papel (`core/papel.py`)

- É backtest por construção. O perfil de execução é montado como no WFA
  (`CAMPOS_EXECUCAO_NOMES`); nunca `ExecutionProfile.from_config`.
  `run_strategy(..., vela_aberta=True)` só no papel ao vivo.
- O aquecimento é calculado pelos parâmetros da estratégia; 10 pregões
  não bastam e o resultado diverge do backtest.
- `op_id` é estável por (`ligacao_id`, `entry_ts`). A parte 4 depende dele.
- Pregão conferido fica congelado; o checksum acusa divergência.
- A captura calcula o papel só com candle novo e refaz a conferência do
  papel na janela seguinte se ela falhar.
- A tela Operação lê o `estado.json` a cada 2 s e só abre o banco quando
  `papel.calculado_em` muda.
- **Relógio do Windows:** com o serviço `w32time` parado o PC atrasou 222 s.
  Com o MT5 conectado a automação usa o relógio da corretora, mas deixe o
  `w32time` em início automático com os servidores do ntp.br.
- **Aquecimento e reconferência (05/11/2026):** o papel vivo guarda o aquecimento em memória. Se a reconferência
  da manhã muda candles, a captura relê o aquecimento (`_reler_aquecimento`); sem isso o papel vivo diverge do
  backtest: o ADX é recursivo e uma mudança pequena no passado vira outro sinal (fix `0fcf282`, `12d157f`).

Se mudou `captura.py`, `core/captura.py`, `core/ingest.py`, `core/db_manager.py`,
`core/schema.sql` ou algo que o papel usa dentro da captura — `core/papel.py`,
`core/engine/*`, `core/plano.py`, `core/variantes.py`, `strategies/*` —,
feche também a janela **Dataframe - Captura** antes de reabrir o
`iniciar.bat`: a captura antiga segura a trava e a nova sai calada (código 4),
então reabrir só o `iniciar.bat` deixa o código velho gravando.
