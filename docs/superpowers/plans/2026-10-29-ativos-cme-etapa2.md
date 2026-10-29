# Ativos da CME — Etapa 2 (motor e estratégias) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backtest de cada estratégia roda no MES e no MNQ com parâmetros em pontos e horários de NY, e a tela mostra trades em hora de NY e preço em pontos — com o WIN idêntico.

**Architecture:** A conversão humana → guardada acontece só em `run_strategy`, numa cópia: perfil (pontos ×escala, horários +6 h), parâmetros marcados `"unidade": "pontos"` e instrumento (`tick_unid`, `valor_por_unid`). A cópia do `bars_tf` recebe `tick`, `abertura_min` e `inicio_min` para as estratégias. A volta guardada → humana fica só na tela, via `core/ativo.py`. Para o WIN tudo é identidade.

**Tech Stack:** Python 3, numpy, polars, DuckDB, Dash, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` — seções "Regra de unidades", 2 (datas e janela), 4, 5, 7, "Garantia do WIN", "Ordem de entrega" item 2 e "Herança da etapa 1".

## Global Constraints

- **WIN idêntico, número a número.** A foto `antes_etapa2` (Task 1) é conferida ao fim das Tasks 3, 4 e 7.
- **Para o WIN** (`win.yaml`, `price_decimals` 0, sem `sessao_abertura`) toda conversão é identidade e devolve o **mesmo objeto** sempre que possível.
- **Conversão humana → guardada só dentro de `run_strategy`**, em cópia. Instrumento convertido leva `"_unidade": "guardada"`; `run_strategy` não converte de novo um instrumento que já tem essa marca.
- **`res.profile` sai em unidade humana** (o objeto que entrou). `res.instrument` sai convertido. Trades, `sl_at_entry` e `tp_at_entry` saem em unidade guardada.
- **O que é salvo** (perfis em `mining_runs`/`wfa_runs`/`planos_operacao`, parâmetros) continua em unidade humana.
- **Parâmetros em pontos continuam inteiros** (decisão C1).
- **Abertura de referência:** é a primeira barra do pregão cujo **minuto de início** é ≥ `abertura_min`. Com `abertura_min = None` (WIN), é a primeira barra do dia, como hoje.
  - `rompimento_ema_abertura` não sinaliza antes da barra de abertura (decisão C2).
- **Estratégias e hash dos planos:** mexer em `strategies/*.py` muda o `codigo_hash` dos planos. O papel lê o hash do disco a cada ciclo e **interrompe o pregão** se ele mudar.
  - Por isso o plano roda numa **worktree**: `superpowers:using-git-worktrees`, branch derivada de `new-strategies`.
  - A troca na pasta do usuário só acontece na Task 7, com o app fechado e fora do pregão, seguida de `scripts/reassinar_codigo.py`.
- **Arquivos do usuário:**
  - `strategies/rompimento_abertura.py`: autorizado (D11) só na mudança mínima da Task 4; avisar no relatório.
  - `ui/components/controls.py` e `ui/components/wfa_matriz.py`: **não editar**.
- **Telas:** nada de texto explicativo visível; explicação só em "(?)". Mensagens de erro são permitidas.
- **Testes:** nunca tocam `data/database.duckdb` (o conftest isola `DB_PATH`). Isole também `db.PARQUET_DIR` quando escrever Parquet.
- **Ambiente:** a venv não tem tzdata. Use `.venv/Scripts/python.exe`.
- **Commits:** mensagem terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nunca `git add -A`.
- **Fora desta etapa:**
  - moeda (rótulos R$, `dinheiro()`, portão de custo, portfólio) — etapa 3;
  - faixas de mineração e sliders — etapa 4;
  - telas ao vivo (WIN-only);
  - os `int(tick_size)` do caminho ao vivo.
- **`execution_profiles.symbol` (spec seção 7) não é feito.** A tabela não tem leitor nem escritor fora do `cli init`, e não existe tela de perfis salvos. Coluna sem uso é YAGNI. O perfil por ativo vem do `perfil_padrao` da ficha.

## Review Focus

1. **Barra agregada (H1) que contém as 09:30.** A barra de 09:00–09:59 NY tem `ts` 09:59 e não pode ser tomada como abertura; a abertura em H1 é a das 10:00. Teste na Task 4.
2. **Chamada dupla.** `run_strategy` chamado duas vezes com o mesmo perfil e instrumento dá trades iguais, e o perfil que entrou não muda. Teste na Task 3.
3. **`aleatorio.py`.** Ele fatia todas as chaves do dicionário M1. As chaves novas só podem existir na cópia do `bars_tf`, nunca no M1 do chamador. Teste na Task 3.
4. **Trocar o ativo na tela.** De MES para WIN, a camada 4 volta exatamente aos valores de hoje (`win.yaml` `perfil_padrao` = padrões do `controls.py`). Teste na Task 5.
5. **Lista e gráfico do MES.** Marcadores, linhas de preço e lista de trades caem no mesmo horário e preço dos candles: hora de NY e pontos com 2 casas. Teste na Task 6.

---

### Task 1: Foto do WIN ampliada

**Files:**
- Modify: `scripts/foto_win.py`
- Test: `tests/test_foto_win.py`

**Interfaces:**
- Consumes:
  - `optimizer._init(symbol, de, ate, estrategia_nome)` e `optimizer._uma((trial_id, params_estrategia, campos_execucao, perfil_base, janelas))`;
  - `optimizer.montar_espaco`, `optimizer.espaco_util`, `optimizer.combinacoes_uteis`, `walkforward.montar_janelas`;
  - `wfa_runner._init` e `wfa_runner._uma((trial_id, estrat, exec_, perfil_base))`;
  - `aleatorio.rodador_do_motor(bars, estrategia_real, perfil, instrumento, trades_reais)` e `aleatorio.teste_janelas(...)`.
- Produces: `gerar()` devolve também as chaves `"mineracao"`, `"walkforward"` e `"candidata"`. `comparar` não muda.

- [ ] **Step 1: Teste.** Em `tests/test_foto_win.py` acrescentar `test_gerar_tem_as_cinco_partes`. Ele monkeypatcha as funções de geração de cada parte para devolver `{}` e afirma `set(gerar()) == {"planos", "estrategias", "mineracao", "walkforward", "candidata"}`. Organize `gerar()` em funções `_planos`, `_estrategias`, `_mineracao`, `_walkforward`, `_candidata` para isso.
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_foto_win.py -v`. Expected: FAIL.
- [ ] **Step 3: Implementar**, sempre no WIN$N, com resultados determinísticos:
  - **`_mineracao`:** estratégia `setup_cruzamento`, período 2024-01-01 a 2025-06-30. Grade de `media_rapida` {5, 9, 13, 17} × `media_lenta` {21, 34, 55, 89, 144} (20 combinações) com `ExecutionProfile().to_config()`. Janelas de `walkforward.montar_janelas` com treino 12, teste 3, passo 3 e holdout 0. Guarda o dicionário devolvido por `_uma` de cada combinação, por `trial_id`.
  - **`_walkforward`:** mesmas 4 primeiras combinações via `wfa_runner._init`/`_uma`, mesmo período. Guarda o retorno de cada uma.
  - **`_candidata`:** `aleatorio.rodador_do_motor` com as barras WIN de 2025-01-01 a 2025-06-30, a estratégia `setup_cruzamento` padrão, `ExecutionProfile()` e os trades reais de um `run_strategy`. Depois `teste_janelas` com 2 janelas mensais, `n=20`, `semente=7`. Guarda o retorno.
  - Se `_init` ler o Parquet real de `db.PARQUET_DIR`, ok: é leitura.
- [ ] **Step 4: Run** os testes. Expected: PASS.
- [ ] **Step 5: Gravar a foto de base:** `.venv/Scripts/python.exe scripts/foto_win.py gravar antes_etapa2`, depois `conferir antes_etapa2`. Expected: "idêntica" e as 5 partes com contagem. Anotar o tempo de execução no relatório (meta: menos de 5 min).
- [ ] **Step 6: Commit** `feat(cme): foto do WIN com mineracao, walk-forward e candidata`.

---

### Task 2: `core/ativo.py` — conversões do motor e da tela

**Files:**
- Modify: `core/ativo.py`
- Test: `tests/test_ativo_motor.py` (novo)

**Interfaces:**
- Consumes: `Ficha` e as funções da etapa 1.
- Produces:
  - `ficha_do_instrumento(instr: dict) -> Ficha | None`: `None` quando o dicionário não tem `price_decimals` nem `sessao_abertura` (dicionário de teste ou WIN antigo), ou quando já tem `"_unidade": "guardada"`; senão `ficha_de(instr)`.
  - `instrumento_para_motor(instr: dict, f: Ficha | None) -> dict`: com `f is None` ou identidade, devolve `instr` (mesmo objeto); senão uma cópia com `tick_size = f.tick_unid`, `point_value = f.valor_por_unid`, `"_unidade": "guardada"`.
  - `perfil_para_motor(p: ExecutionProfile, f: Ficha | None) -> ExecutionProfile`: na identidade devolve `p`. Senão `dataclasses.replace` com `alvo_pontos`, `stop_pontos`, `trailing_pontos` × `f.escala`, e `entrada_inicio`, `entrada_fim`, `fechamento`, `sem_entrada1..3` (não vazios) por `hora_para_motor`. Dinheiro não muda.
  - `params_para_motor(params: dict, schema: dict, f: Ficha | None) -> dict`: na identidade devolve `params`; senão cópia com cada chave cujo schema tem `"unidade": "pontos"` × `f.escala`.
  - `trades_para_exibir(trades: dict, f: Ficha | None) -> dict`: na identidade devolve `trades`; senão cópia com `entry_ts`/`exit_ts` − `deslocamento_min` e `entry_px`, `exit_px`, `points`, `mae`, `mfe` como `float / escala`. As outras chaves são as mesmas.
  - `pontos_para_exibir(v, f: Ficha | None)`: escalar ou array; identidade devolve `v`.
  - `hora_do_pregao_para_exibir(h: int, f: Ficha | None) -> int`: hora cheia, `(h − deslocamento_min // 60) % 24`.
  - `perfil_padrao(f: Ficha) -> dict | None`: o bloco `perfil_padrao` do YAML (campos de tela), ou `None`. Adicionar o campo `perfil_padrao: dict | None` à `Ficha`, com `hash=False, compare=False`.
- "Identidade" = `f is None or (f.escala == 1 and f.deslocamento_min == 0)`.

- [ ] **Step 1: Testes** em `tests/test_ativo_motor.py`, com fichas em memória (como `tests/test_ativo.py`):
  - **identidade do WIN:** `instrumento_para_motor(win_cfg, ficha_do_instrumento(win_cfg)) is win_cfg`; o mesmo vale para perfil, params e trades;
  - **`ficha_do_instrumento`:** `{"tick_size": 5, "point_value": 0.2}` dá `None`;
  - **instrumento do MES:** `tick_size == 25`, `point_value == 0.05`, `_unidade == "guardada"`; e `ficha_do_instrumento(convertido) is None`;
  - **perfil do MES:** `ExecutionProfile(stop_pontos=10, alvo_pontos=20, trailing_pontos=5, entrada_inicio="09:30", entrada_fim="16:00", fechamento="16:50", sem_entrada1="12:00")` vira 1000/2000/500, `"15:30"`, `"22:00"`, `"22:50"`, `"18:00"`; `limite_perda_contrato` e `corretagem_por_contrato` não mudam; o original não muda;
  - **params:** com schema `{"a": {"unidade": "pontos"}, "b": {}}` e `{"a": 12, "b": 3}` dá `{"a": 1200, "b": 3}`;
  - **trades:** `entry_ts` 2024-06-17 15:30 vira 09:30, `entry_px` 543225 vira 5432.25, `points` −125 vira −1.25;
  - **hora:** `hora_do_pregao_para_exibir(15, MES) == 9` e `hora_do_pregao_para_exibir(3, MES) == 21`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implementar.** `core/ativo.py` não importa `core.engine` no topo (ciclo): importar `dataclasses.replace` e tipar o perfil por anotação em string.
- [ ] **Step 4: Run** `tests/test_ativo_motor.py tests/test_ativo.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(cme): conversoes do motor e da tela em core/ativo`.

---

### Task 3: Conversão dentro de `run_strategy`

**Files:**
- Modify: `core/engine/execution.py` (`run_strategy` ~L196-244)
- Test: `tests/test_run_strategy_ativo.py` (novo)

**Interfaces:**
- Consumes: Task 2.
- Produces: `run_strategy(bars, estrategia, params, profile, instrument, vela_aberta=False)` com a mesma assinatura e esta ordem:
  1. `f = ativo.ficha_do_instrumento(instrument)`;
  2. `inst_m = instrumento_para_motor(instrument, f)`, `perfil_m = perfil_para_motor(profile, f)`, `params_m = params_para_motor(params, estrategia.params_schema, f)`;
  3. `resample` como hoje;
  4. `bars_s = dict(bars_tf)` (cópia rasa, sempre, também em M1), com:
     - `bars_s["tick"] = inst_m tick (int)`;
     - `bars_s["abertura_min"] = f.abertura_min if f else None`;
     - `bars_s["inicio_min"]` = minuto do dia (relógio de pregão) do **primeiro M1** de cada barra de `bars_tf`. Em M1 é o minuto do próprio `ts`; agregado, é o minuto de `bars["ts"][inicio]`, com `inicio[0] = 0` e `inicio[k] = fim[k-1] + 1`;
  5. `s = estrategia.signals(bars_s, params_m)`;
  6. `backtest(bars, sig, perfil_m, inst_m, bars_tf, fechada)`;
  7. no resultado, `res.profile = profile` (o original humano); `res.instrument` fica `inst_m`.
- `backtest` não muda: L466, L496-498 e `metrics` já leem o instrumento convertido.

- [ ] **Step 1: Testes** em `tests/test_run_strategy_ativo.py`, com barras sintéticas MES em relógio de pregão (preço ×100), ficha MES em memória (cfg como `tests/test_ativo.py`) e uma estratégia de teste de módulo:
  - **unidades:** `run_strategy` com `stop_pontos=10` dá `res.sl_at_entry` == 1000; `res.profile is perfil_original` e `perfil_original.stop_pontos == 10`;
  - **chamada dupla:** duas chamadas seguidas dão `trades` iguais (`np.array_equal` por chave);
  - **instrumento já convertido:** passar `res.instrument` de volta não converte de novo (mesmo `sl_at_entry`);
  - **chaves extras:** a estratégia de teste registra o `bars` que recebe. Em M1 e em H1 ele tem `tick == 25`, `abertura_min == 930` e `inicio_min` certo (barra H1 de `ts` 15:59 → `inicio_min` 900). O dicionário M1 passado não ganhou chaves;
  - **janela de horário:** `entrada_inicio="09:30"`, `entrada_fim="10:00"` só arma entradas com `ts` entre 15:30 e 16:00 do relógio de pregão;
  - **limite diário em dinheiro:** `limite_perda_contrato=50.0` (US$) no MES para o dia após 1000 unidades guardadas de perda (10 pontos × US$ 5);
  - **WIN identidade:** com o instrumento do `win.yaml` e as barras WIN da mesma fixture, as chaves de `bars` recebidas valem `tick == 5`, `abertura_min is None`, e os trades são idênticos aos de um `backtest` montado à mão como hoje.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implementar** conforme a interface.
- [ ] **Step 4: Run** o arquivo novo e `tests/test_execution*.py`, `tests/test_aleatorio*.py`, `tests/test_optimizer*.py` (os que existirem). Expected: PASS.
- [ ] **Step 5: Foto:** `scripts/foto_win.py conferir antes_etapa2`. Expected: "idêntica". Se não for, parar e diagnosticar.
- [ ] **Step 6: Commit** `feat(cme): run_strategy converte perfil, parametros e instrumento do ativo`.

---

### Task 4: Estratégias — tick e abertura de referência

**Files:**
- Modify: `strategies/rompimento_canal.py`, `strategies/rompimento_abertura.py` (autorizado, mínimo), `strategies/rompimento_ema_abertura.py`, `strategies/adx_direcao.py`
- Test: `tests/test_estrategias_ativo.py` (novo)

**Interfaces:**
- Consumes: as chaves `tick`, `abertura_min`, `inicio_min` de `bars` (Task 3). Sem elas, valem `5`, `None`, `None`, e a estratégia se comporta como hoje.
- Produces:
  - `"unidade": "pontos"` no `params_schema` de `adx_direcao.amplitude_max`, `rompimento_abertura.filtro_amplitude`, `rompimento_canal.filtro_amplitude` e `rompimento_ema_abertura.distancia_abertura`;
  - `folga = folga_ticks * bars.get("tick", 5)`; a constante `TICK` sai dos dois arquivos.

- [ ] **Step 1: Registrar o commit base** (`git rev-parse HEAD`) no relatório. É o `--de` da re-assinatura na Task 7.
- [ ] **Step 2: Testes** em `tests/test_estrategias_ativo.py`, chamando `run_strategy` com barras sintéticas MES de dois pregões (relógio de pregão: 00:00 = 18:00 NY) e o instrumento MES:
  - **`rompimento_abertura` em M1, `barras_abertura=6`:** o range é das barras de 15:30 a 15:35 (09:30–09:35 NY), não das de 00:00. Nenhuma entrada antes de 15:36;
  - **`rompimento_abertura` em H1:** a barra de abertura é a de `inicio_min` 960 (10:00 NY), não a de `ts` 15:59;
  - **`rompimento_canal` com `folga_ticks=2`:** a entrada exige `close > teto + 50` (unidades guardadas);
  - **`rompimento_ema_abertura`:** sem sinal antes das 15:30; a distância é medida do `open` da barra das 15:30 (C2); `distancia_abertura=3` vira 300;
  - **WIN:** com o instrumento do `win.yaml`, os sinais das 4 estratégias são idênticos aos de `signals(bars_sem_chaves, params)`.
- [ ] **Step 3: Run.** Expected: FAIL.
- [ ] **Step 4: Implementar.**
  - **Abertura:**
    - Se `abertura_min` for `None`: índice de abertura = primeira barra do dia (hoje).
    - Senão: primeira barra do dia com `inicio_min >= abertura_min`. Dia sem essa barra = sem abertura, sem sinal.
  - **`rompimento_abertura`:** conta `barras_abertura` a partir do índice de abertura. `formado` passa a valer `pos_desde_abertura >= barras_abertura`.
  - **`rompimento_ema_abertura`:** `abertura_dia` = `open` do índice de abertura. Barras antes dele não sinalizam.
  - Em ambos, o caminho do WIN fica idêntico.
  - Atualizar o "(?)" (label/hint do schema) da `barras_abertura` dizendo que, fora do M1, a abertura é a primeira barra que **começa** às 09:30 ou depois.
- [ ] **Step 5: Run** o arquivo novo e todos os `tests/test_*estrateg*`, `tests/test_rompimento*`, `tests/test_adx*`, `tests/test_registry*` existentes. Expected: PASS.
- [ ] **Step 6: Foto:** `conferir antes_etapa2`. Expected: "idêntica".
- [ ] **Step 7: Commit** `feat(cme): estrategias leem tick e abertura de referencia do ativo`. O relatório avisa que `rompimento_abertura.py` (arquivo do usuário) foi alterado e diz o que mudou.

---

### Task 5: Perfil padrão por ativo e validação da janela

**Files:**
- Modify: `configs/instruments/win.yaml`, `mes.yaml`, `mnq.yaml` (bloco `perfil_padrao`), `ui/callbacks.py` (callback novo + validação em `rodar` e `minerar`)
- Test: `tests/test_perfil_por_ativo.py` (novo)

**Interfaces:**
- Consumes: `ativo.perfil_padrao(f)`.
- Produces:
  - `perfil_padrao` nos três YAML, com as chaves de tela `entrada_inicio`, `entrada_fim`, `fechamento`, `corretagem`, `emolumentos`, `slippage_ticks`, `stop_pontos`, `alvo_pontos`:
    - **`win.yaml`:** exatamente os padrões atuais da tela (`controls.py`: 09:00, 17:00, 17:30, 0.50, 0.27, 1, 300, 600);
    - **`mes.yaml`/`mnq.yaml`:** 18:00, 16:30, 16:50, 0.60, 0.0, 1, e stop/alvo **provisórios até a etapa 4**: MES 10/20 e MNQ 40/80 (comentário no YAML).
  - Callback `aplicar_perfil_do_ativo`: `Input("ativo", "value")`, `prevent_initial_call=True`, escreve nos ids da camada 4 (`e-ent-ini`, `e-ent-fim`, `e-fechamento`, `e-corretagem`, `e-emolumentos`, `e-slippage`, `{"type": "val", "p": "stop_pontos"}`, `{"type": "val", "p": "alvo_pontos"}`) com `allow_duplicate=True`.
  - Função pura `janela_valida(ini: str, fim: str, f) -> str | None` em `core/ativo.py`: mensagem de erro se `hora_para_motor(ini) > hora_para_motor(fim)` em minutos, senão `None`.
    - `rodar` e `minerar` chamam e, havendo erro, não rodam e mostram a mensagem pelo mesmo caminho de erro que já usam.

- [ ] **Step 1: Testes:**
  - `test_perfil_win_igual_aos_padroes_da_tela`: lê os `value` iniciais dos componentes de `controls` (montando o layout ou lendo as constantes) e compara com `win.yaml`;
  - `test_mes_tem_perfil_de_ny`;
  - `test_janela_16h_19h_ny_recusada` (16:00→19:00 NY vira 22:00→01:00, mensagem não vazia);
  - `test_janela_win_normal_aceita`;
  - teste do callback chamando a função decorada direto com "MES" e com "WIN$N".
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implementar.** Conferir que nenhum outro callback deixa de funcionar com o `allow_duplicate` (o carregamento de mineração ~L505-535 escreve nos mesmos ids). `tests/test_callbacks_sem_ciclo.py` precisa passar.
- [ ] **Step 4: Run** os arquivos novos, `tests/test_callbacks_sem_ciclo.py` e os testes de UI existentes. Expected: PASS.
- [ ] **Step 5: Commit** `feat(cme): perfil padrao por ativo e janela recusada fora da ordem do pregao`.

---

### Task 6: Telas de trades em hora de NY e pontos

**Files:**
- Modify:
  - `ui/components/results_grid.py` (`rows`, formatação de preço);
  - `ui/components/charts.py` (`trade_markers`, `trade_price_lines`);
  - `core/analytics.py` (`por_hora`);
  - `ui/callbacks.py` (`desenhar`, `_referencias_operadas`, `_detalhes`, `diagnostico` ~L1952-1970, WFA OOS ~L1532 e a montagem da grade).
- Test: `tests/test_telas_ativo.py` (novo)

**Interfaces:**
- Consumes: `ativo.trades_para_exibir`, `pontos_para_exibir`, `hora_do_pregao_para_exibir`, `ficha`.
- Produces:
  - `rows(trades, dinheiro, f=None)`: textos `entrada`/`saida` em hora de NY; `preco_ent`, `preco_sai`, `pontos`, `mae`, `mfe` em pontos (float com 2 casas no MES, int no WIN). `t_ent`/`t_sai` **continuam em relógio de pregão** (o clique posiciona o gráfico com eles). As colunas de preço usam formatação com `price_decimals` casas.
  - `trade_markers(trades, t0, t1, limite=400, f=None)` e `trade_price_lines(res, i, f=None)`: tempo e preço na mesma unidade dos candles.
  - `por_hora(entry_ts, liquido, f=None)`: rótulo pela hora de NY.
  - **Valores para os textos de sugestão e Detalhes:**
    - `_referencias_operadas`: `stop`/`alvo` em pontos humanos (`sl_at_entry / escala`), comparáveis a `perfil.stop_pontos`;
    - `analytics.sugestoes` e `AC.mae_mfe` recebem `diag` calculado de `trades_para_exibir`;
    - `detalhes.eficiencia` e `detalhes.risco_trade` recebem pontos humanos, com `folga = slippage_ticks * tick_size` do YAML (humano).
  - Para o WIN, toda saída é idêntica à de hoje.

- [ ] **Step 1: Testes** em `tests/test_telas_ativo.py`, com um `BacktestResult` sintético MES (trade de compra com `entry_ts` 2024-06-17 15:30, `entry_px` 543225, `points` 125, `sl_at_entry` 1000):
  - `rows` mostra entrada "17/06/2024 09:30" e preço 5432.25, e `t_ent` fica em 15:30;
  - `trade_markers` dá `time == to_epoch(09:30)` e texto "+1.25";
  - `trade_price_lines` dá a entrada em 5432.25 e o stop em 5422.25;
  - `por_hora` dá o rótulo "09h";
  - `_referencias_operadas` dá stop 10.0;
  - WIN: as mesmas funções com um resultado WIN dão a saída idêntica à chamada sem `f` (comparação de igualdade completa).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implementar.** Cada callback carrega `f = ativo.ficha(simbolo)` uma vez. No WFA OOS (~L1532), o símbolo vem da execução salva. `equity_series` fica como está (dia do pregão).
- [ ] **Step 4: Run** o arquivo novo e os testes de UI/analytics/detalhes existentes (`grep -l "rows(\|trade_markers\|por_hora\|_detalhes" tests/`). Expected: PASS.
- [ ] **Step 5: Commit** `feat(cme): trades, graficos e detalhes em hora de NY e pontos`.

---

### Task 7: Conferência e troca na pasta do usuário

**Files:** nenhum novo.

- [ ] **Step 1: Na worktree:**
  - `foto_win.py conferir antes_etapa2`. Expected: "idêntica".
  - Suíte inteira em segundo plano (`.venv/Scripts/python.exe -m pytest -q`, ~14 min). Expected: tudo passa.
- [ ] **Step 2: Na worktree, conferir no app** (`preview_start` "dataframe" apontando para a worktree, ou checagem por script se o preview só servir a pasta principal):
  - para MES e MNQ, rodar o backtest de cada uma das 6 estratégias com o perfil padrão do ativo: roda sem erro, a lista mostra hora de NY e preço com 2 casas, e os marcadores caem nos candles;
  - voltar ao WIN: camada 4 com os valores de hoje e resultado igual ao de antes.
  - Screenshots.
- [ ] **Step 3: Re-assinatura (comparação, sem aplicar).** Rodar `scripts/reassinar_codigo.py --de <commit base da Task 4>` contra o banco real. O script copia o banco e só compara. Expected: todos os planos afetados com trades idênticos.
- [ ] **Step 4: PARAR e pedir ao usuário um momento com o app fechado e fora do pregão.** Explicar em uma frase: o código das estratégias mudou, e sem re-assinar o papel interrompe o pregão.
- [ ] **Step 5: Com o "pode" do usuário:**
  - integrar a branch da worktree em `new-strategies` (fast-forward);
  - `scripts/reassinar_codigo.py --de <commit base> --aplicar` (faz backup);
  - `foto_win.py conferir antes_etapa2` na pasta principal;
  - avisar para reabrir o `iniciar.bat`.
- [ ] **Step 6:** Atualizar a seção "Herança da etapa 1" da spec: marcar o que a etapa 2 resolveu e o que passa para as etapas 3 e 4. Commit `docs(spec): ativos da CME - estado depois da etapa 2`.
