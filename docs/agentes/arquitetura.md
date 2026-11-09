# Arquitetura em uma tela

As quatro camadas (pergunta: *de quem é essa informação?*):

| Camada | Onde | Conteúdo |
|---|---|---|
| 1 Instrumento | `configs/instruments/*.yaml` | tick, valor do ponto, rolagem |
| 2 Estratégia | `strategies/*.py` | só sinais (`Signals`); soltar o arquivo na pasta basta (`strategies/registry.py`) |
| 3 Parâmetros | `configs/strategies/*.json` / `params_schema` | default, min, max, passo |
| 4 Execução | tabela `execution_profiles` | horário, stop/alvo, custos, tamanho — aplicada pelo motor, nunca pela estratégia |

Os seis modos do topo (`ui/app.py`; o app abre em Ao vivo › Estratégias) e
onde vivem. O Backtest não é mais aba: é a subtela Backtest da Mineração
(Varredura | Busca automática | Backtest), e clicar numa linha, ponto da nuvem ou aprovada roda o
backtest e pula para ela:

| Modo | Contas (`core/`) | Tela (`ui/`) |
|---|---|---|
| Mineração (Varredura + Busca automática + Backtest) | Varredura: `optimizer.py`, `walkforward.py`, `mineracao_stats.py`, `porteira.py`. Busca automática: `busca/*` (catalogo, espaco, avaliador, motor, nucleos, banco, controle, prioridade, grupos, projecao, detalhe) + o processo `busca.py` da raiz. Backtest: `engine/kernel.py`, `engine/execution.py` (`preparar`/`executar`), `metrics.py`, `analytics.py`, `detalhes.py`, `robustez.py` | `components/mining.py`, `mine_*.py`, `scatter.py`; Busca: `callbacks_busca.py`, `components/busca_panel.py`, `assets/busca.js`, `assets/busca.css`; Backtest: `callbacks.py`, `components/stats_cards.py`, `charts.py`, `results_grid.py` |
| Walk-Forward | `wfa.py`, `wfa_runner.py`, `wfa_store.py` | `components/wfa_panel.py` |
| Candidata | `candidata.py`, `candidata_runner.py`, `aleatorio.py`, `spa.py`, `tamanho.py`, `plano.py` | `callbacks_candidata.py`, `components/candidata_panel.py` |
| Estratégias | `variantes.py` | `callbacks_estrategias.py`, `components/estrategias_panel.py` |
| Portfólio | `portfolio.py` | `callbacks_portfolio.py`, `components/portfolio_panel.py` |
| Ao vivo | `ao_vivo.py`, `diario.py`, `codigo.py`, `captura.py` (o processo da captura é o `captura.py` da raiz, aberto pelo `captura.bat`), `papel.py`, `papel_leitura.py`, `papel_vivo.py`, `papel_backtest.py`, `conferencia_ordens.py`, `ordens_backtest.py`, `corretora.py`, `ordens.py`, `diario_ordens.py`, `comandos.py`, `contrato_dia.py` | `callbacks_ao_vivo.py`, `components/ao_vivo_panel.py`, `callbacks_pregao.py`, `components/pregao_panel.py`, `callbacks_operacao.py`, `components/operacao_panel.py`, `components/ordens_panel.py` |

Outros: `core/mt5_source.py` (sincronização com o MT5, sem botão na tela — a
captura já preenche o que falta; o `ui/callbacks_mt5.py` foi removido); `core/plano.vencendo` + selo no topbar (reotimização vencendo);
`ui/callbacks.py:register` registra todos os `callbacks_*.py` (a chamada mora em `ui/cb_pesquisa/r_resto.py`).

Arquivo grande virou pacote: o arquivo antigo é uma **casca** que só reexporta, e o código mora no pacote:

| Casca | Pacote |
|---|---|
| `ui/callbacks.py` | `ui/cb_pesquisa/` (menu, Backtest, mineração, Walk-Forward) |
| `ui/callbacks_operacao.py` | `ui/cb_operacao/` |
| `ui/components/operacao_panel.py` | `ui/components/operacao/` |
| `ui/components/ordens_panel.py` | `ui/components/ordens/` |
| `ui/components/ao_vivo_panel.py` | `ui/components/ao_vivo/` |
| `core/papel_leitura.py` | `core/leitura/` |

Para trocar um nome num teste (`monkeypatch`), mire o módulo do pacote onde ele é usado, não a casca. Divisão
nova: só mudança de lugar, provada por `scripts/provar_divisao.py --de <commit>`.

Fluxo do dado: mineração (`mining_runs`, com `variante_id`) → walk-forward
(`wfa_runs`, `wfa_trades` = trades fora da amostra) → Candidata grava
`planos_operacao` (retratos, não referências) → Portfólio referencia **só a
variante** e resolve o plano ativo na hora (`variantes.plano_ativo`).
