# Incubação em papel + sub-tela Operação — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o serviço de captura passa a calcular, a cada candle novo, as operações de papel de cada variante ligada a um portfólio (idênticas ao backtest), e a sub-tela Ao vivo › Operação mostra o portfólio operando ao vivo.

**Architecture:** `core/papel.py` (sem Dash) monta o plano/perfil do dia, calcula o aquecimento, roda `engine.execution.run_strategy` sobre as barras do banco e grava `papel_operacoes`/`papel_pregoes` por upsert; `captura.py` chama isso depois de cada gravação e na conferência; `core/papel_leitura.py` devolve o que a tela mostra; a tela (`ui/components/operacao_panel.py`, `ui/callbacks_operacao.py`) relê só quando o `estado.json` diz que o papel mudou.

**Tech Stack:** Python 3, numpy, Numba (kernel), polars, DuckDB 1.5.5, Dash 4.4.1, dash_tvlwc.

**Spec:** `docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md` (leia inteira; as decisões da §2 são do usuário e travadas).

## Global Constraints

- Código, nomes, comentários e textos de tela em **português**; comentário explica **por quê** (tom de `core/wfa.py`). Nunca "robô".
- **Nada em `core/` importa Dash.**
- Testes nunca tocam `data/`: o `tests/conftest.py` desvia `db.DB_PATH` e o estado da captura; quem lê/exporta Parquet desvia `db.PARQUET_DIR`. Helpers de cadeia: `tests/_cadeia.py`.
- TDD em toda tarefa de lógica e **mutação** (quebrar de propósito, ver falhar, desfazer) nos pontos que a tarefa indicar.
- Papel = backtest **por construção**: mesmo `run_strategy`, mesma montagem de perfil que `wfa_runner.trades_oos_detalhados` (`core/wfa_runner.py:359-362`); **proibido** `ExecutionProfile.from_config`.
- Toda métrica nova na tela tem (?) com faixa boa/ruim (`ui/components/cartao.py` → `dica`). Layout segue `.claude/agents/designer-ui.md`.
- `tests/test_callbacks_sem_ciclo.py` verde sempre que mexer em Inputs/Outputs.
- Git **pela tool PowerShell**; `git add` por caminho; `git commit -F <arquivo>` (sem BOM) terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; sem push.
- **Nunca** editar/stagear `ui/components/controls.py`, `ui/components/wfa_matriz.py`, `strategies/rompimento_abertura.py`.
- Mudou `captura.py`/`core/captura.py`/`core/ingest.py`/`core/db_manager.py` → avisar: fechar a janela "Dataframe - Captura" e reabrir o `iniciar.bat`.
- Antes de qualquer migração no banco real: backup (o `.duckdb` não é só cache).
- Suíte: `.venv/Scripts/python.exe -m pytest -q` (~1163 testes).

---

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `core/engine/kernel.py`, `core/engine/execution.py` | duas saídas novas: stop e alvo vigentes no fim de cada operação |
| `core/schema.sql` | `papel_operacoes`, `papel_pregoes` |
| `core/papel.py` (novo) | plano/perfil do dia, aquecimento, `rodar_ligacoes`, upsert, `conta`, código carregado, conferência/checksum |
| `core/papel_leitura.py` (novo) | o que a tela lê: resumo do portfólio, posições, operações do dia, pior momento, curva × esperado, comparativo |
| `core/plano.py`, `core/ao_vivo.py`, `core/db_manager.py`, `cli.py` | proteção da cadeia, contador de pregões reais, textos |
| `strategies/base.py` | (opcional) `aquecimento_barras(params)` declarável |
| `captura.py` | chama o papel após gravar e na conferência; "papel pendente"; publica `papel` no estado |
| `ui/components/operacao_panel.py`, `ui/callbacks_operacao.py` (novos) | sub-tela Operação |
| `ui/components/ao_vivo_panel.py`, `ui/callbacks_pregao.py`, `ui/callbacks.py`, `ui/assets/style.css` | seletor com "Operação", Interval, registro, CSS |

---

### Task 1: Stop e alvo vigentes no motor

**Files:** Modify `core/engine/kernel.py`, `core/engine/execution.py`; Test `tests/test_kernel_stop_vigente.py` (novo).

**Interfaces:**
- Produces: `res.trades["stop_fim"]`, `res.trades["alvo_fim"]` (int64, um por operação): o `stop_px`/`tgt_px` do kernel **no momento da saída** (0 = sem stop/alvo). Para a operação ainda aberta no último candle, é o stop/alvo vigente agora.

- [ ] **Step 1: testes (falhando).**
  - Barras sintéticas (ver como os testes existentes do kernel/execution montam barras e `ExecutionProfile`; procure em `tests/` por `run_strategy(` ou `backtest(`): compra com stop 100 e breakeven em 50% do alvo 200; preço sobe 120 → `stop_fim == entry_px` (breakeven aplicado); sem breakeven → `stop_fim == entry_px - 100`.
  - Stop móvel (`trailing_pontos`) → `stop_fim` acompanha o melhor preço menos a distância.
  - Regressão: num backtest real curto (barras sintéticas de 3 dias com sinais), todas as colunas antigas de `res.trades` são **idênticas** antes/depois (compare com os valores calculados sem as saídas novas — grave-os no teste a partir da versão atual).
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3: implementar.** `K.allocate_outputs` ganha `stop_fim`, `alvo_fim`; `K.run` recebe e grava `o_stop_fim[k] = stop_px`, `o_alvo_fim[k] = tgt_px` **no mesmo ponto em que grava `o_exit_i`** (antes de zerar a posição). `execution.backtest` passa os dois arrays (linha ~320) e eles entram em `trades` pelo `{k: v[:n_trades]}` existente. Kernel é Numba: mantenha os tipos `int64`.
- [ ] **Step 4:** testes do arquivo + `tests/` do motor (procure `test_kernel*`, `test_execution*`, `test_backtest*`) + suíte inteira → PASS (nenhum número antigo muda).
- [ ] **Step 5: mutação:** gravar `stop_fim` antes do breakeven (valor de entrada) → teste do breakeven falha; desfazer.
- [ ] **Step 6: commit** `core/engine/kernel.py core/engine/execution.py tests/test_kernel_stop_vigente.py` — `feat(motor): stop e alvo vigentes na saida de cada operacao`.

---

### Task 2: Tabelas do papel e proteção da cadeia

**Files:** Modify `core/schema.sql`, `core/plano.py` (`motivo_protecao`), `core/ao_vivo.py` (`pregoes_com_plano`), `core/db_manager.py` (docstring), `cli.py` (texto ~157); Test `tests/test_papel_dados.py` (novo).

**Interfaces:**
- Produces: tabelas `papel_operacoes` e `papel_pregoes` **exatamente** como na spec §5 (inclui `UNIQUE (ligacao_id, entry_ts)`, `conta`, `stop_px`, `alvo_px`, `mae`, `mfe`, `interrompido_em`, `checksum`, `motor_versao`, `calculado_em`), sequência `seq_papel_op`.

- [ ] **Step 1: testes (falhando)** com a fixture de banco temporário e `tests/_cadeia.py` (mineração → WFA → plano → variante → portfólio → ligação):
  - `init_schema` duas vezes não falha e cria as duas tabelas e a sequência.
  - Com uma linha em `papel_operacoes` apontando para o plano: `plano.excluir(plano)`, `wfa_store.excluir(wfa)` e `optimizer.excluir_salva(run)` **recusam** com motivo que cita o papel (veja como `motivo_protecao` monta o texto hoje e use o mesmo estilo: "o plano #N tem operações de papel").
  - Sem papel: comportamento atual inalterado (testes existentes de proteção continuam verdes).
  - `ao_vivo.pregoes_com_plano` (leia a função; ela é usada na ficha de rastreio): passa a contar linhas de `papel_pregoes` com `status IN ('rodando','conferido')` daquela ligação e plano; sem papel, 0.
- [ ] **Step 2:** FAIL. **Step 3:** implementar (SQL idempotente em `schema.sql`, no bloco "ao vivo", com comentário do porquê: decisão do usuário, não se recria). Atualizar docstring de `db_manager` e o texto do `cli.py verify` listando `papel_operacoes`/`papel_pregoes` entre as tabelas que não se recriam.
- [ ] **Step 4:** testes + `tests/test_plano.py tests/test_ao_vivo_*.py tests/test_reparo_base.py` + suíte → PASS.
- [ ] **Step 5: mutação:** `motivo_protecao` sem olhar o papel → teste de proteção falha.
- [ ] **Step 6: commit** — `feat(papel): tabelas de operacoes e pregoes do papel; papel protege a cadeia`.

---

### Task 3: O motor do papel (`core/papel.py`)

**Files:** Create `core/papel.py`; Modify `strategies/base.py` (só se precisar do hook opcional); Test `tests/test_papel_motor.py`.

**Interfaces:**
- Consumes: Task 1 (`stop_fim`, `alvo_fim`), Task 2 (tabelas), `variantes.plano_em_vigor(variante_id, dia, con)`, `plano.detalhes`/linha do plano (params, profile, contratos, codigo_hash, wfa_id, vale_a_partir), `codigo.hash_estrategia(estrategia)`, `wfa_runner.CAMPOS_EXECUCAO_NOMES`, `engine.execution.ExecutionProfile/run_strategy`, `metrics.monetize`, `engine.VERSAO`, `db.load_instrument_yaml`, diário `ao_vivo_eventos`.
- Produces (usado pelas Tasks 4–5):
  - `perfil_do_plano(plano: dict) -> tuple[dict, ExecutionProfile]` → `(params_da_estrategia, perfil)` — `exec_`/`estrat` separados por `CAMPOS_EXECUCAO_NOMES`; `perfil = replace(ExecutionProfile(**plano["profile"]), **exec_, modo_posicao="contratos_fixos", contratos=int(plano["contratos"]))`. Se o nome real do campo de dimensionamento em `ExecutionProfile` for outro, use o real e diga no relatório.
  - `pregoes_de_aquecimento(estrategia_mod, params, perfil) -> int` — regra da spec §4.3: `ceil((maior período × min_tf + período_ATR × min_tf) / 565) + 2`, onde "maior período" = maior valor inteiro entre os parâmetros cujo nome contém `periodo`/`media`/`canal`/`janela`/`tendencia`/`lenta`/`rapida` **ou** `estrategia_mod.aquecimento_barras(params)` se existir (prioridade). `min_tf` = `TIMEFRAMES[perfil.timeframe]`; ATR = maior entre `stop_atr_periodo`/`alvo_atr_periodo` quando o tipo é ATR.
  - `barras_do_dia(con, symbol, dia, pregoes) -> dict | None` — `pregoes` datas distintas de `bars_m1` anteriores a `dia` + o dia (até o último candle gravado); `None` se não há candle no dia. Formato igual a `prepare_bars`.
  - `calcular(barras, dia, plano, mod, inst, fechamento_hhmm) -> list[dict]` (puro, sem banco) — roda o motor e devolve as operações com **entrada no dia**: `entry_ts, exit_ts|None, side, contratos, entry_px, exit_px|None, points, bruto, custo, liquido, reason, mae, mfe, stop_px, alvo_px, aberta`. Regra da aberta (spec §4.4.3): `exit_i == n-1` **e** `reason ∈ {3, 5}` **e** minuto de `ts[n-1]` < `perfil.fechamento` → `aberta=True`, `exit_ts=None`, `exit_px=None`, resultado provisório preenchido (marcação a mercado que o motor já fez); senão fechada. Confirme os códigos de `reason` no kernel e use as constantes de lá.
  - `ligacoes_do_papel(con, symbol, dia) -> list[dict]` — ligações com `removido_em IS NULL` + plano em vigor do símbolo (spec §3).
  - `periodos_ligados(con, ligacao_id, portfolio_id, dia) -> list[tuple[datetime, datetime]]` — a partir do diário (`membro_adicionado/ligado/desligado`, `portfolio_ligado/desligado`) e do estado atual; operação `conta=True` se `entry_ts` cai num período em que **ligação e portfólio** estavam ligados.
  - `rodar_dia(con_leitura, dia, agora, cache_codigo) -> list[dict]` (cálculo) e `gravar(con_escrita, resultados, agora)` (gravação) — separados porque a captura calcula fora do escritor (spec §4.4.6). Fluxo por ligação:
    1. pregão: se já existe linha em `papel_pregoes` com status `conferido` ou `interrompido` → não recalcula (congelado);
    2. `plano_id` fixado: o da linha existente do dia, senão `plano_em_vigor` (sem plano → status `pulado`, motivo "sem plano em vigor");
    3. código: `cache_codigo` guarda `{estrategia: (hash, módulo)}`; hash do disco ≠ cache → recarrega `importlib.reload(strategies.base)` e o módulo (fora do cache de `strategies.registry`); hash do disco ≠ `plano.codigo_hash` (não nulo): se o pregão já tem operações gravadas → `interrompido` (com `interrompido_em = agora`, mantém o gravado); senão → `pulado` ("código mudou desde o plano"); `codigo_hash` nulo → roda com motivo "plano sem impressão do código" (aviso, status `rodando`);
    4. mesma variante (mesmo `plano_id`) em várias ligações → calcula uma vez;
    5. `conta` por operação (períodos ligados).
  - `gravar`: upsert em `papel_operacoes` por `(ligacao_id, entry_ts)` — insere com `nextval('seq_papel_op')` se novo, atualiza os campos se existe (o `op_id` **nunca** muda), apaga as do dia/ligação que sumiram; upsert de `papel_pregoes` (`plano_id`, `codigo_hash`, `motor_versao`, `status`, `motivo`, `n_operacoes`, `liquido` = soma das fechadas com `conta`, `calculado_em`). Tudo numa transação (`db.transacao`).
  - `conferir(con, dia, agora, cache_codigo)` — recalcula o dia, grava, depois `checksum = f"{n}:{sum(open)}:{sum(high)}:{sum(low)}:{sum(close)}"` das barras do dia e `status='conferido'`; operação ainda "aberta" num dia conferido não existe (o dia acabou: a última barra é o fechamento real).
  - `divergencias(con, symbol) -> list[dict]` — pregões conferidos cujo checksum atual das barras ≠ gravado.

- [ ] **Step 1: testes (falhando)** — fixture com banco temporário semeado por `ingest_df`/`write_export` (veja `tests/test_ingest.py`) com ~40 pregões sintéticos realistas (tendência + ruído, 09:00–18:24) e uma estratégia do registry com parâmetros pequenos (ex.: `rompimento_canal` canal 20, M5) + plano gravado via `tests/_cadeia.py`:
  - **identidade:** para 5 dias, `calcular` com aquecimento calculado = trades de `run_strategy` sobre **o histórico inteiro** com entrada naquele dia (entrada, saída, lado, preços, pontos, líquido iguais).
  - **aquecimento:** com `pregoes_de_aquecimento − 3` pregões, ao menos um dia diverge numa configuração de período longo (escolha parâmetros para isso acontecer nos dados sintéticos; se não divergir, o teste mostra o número mínimo necessário e assere que o calculado ≥ ele).
  - **montagem:** plano com `stop_pontos=123` nos params e perfil base com outro stop → `sl_at_entry` usado = 123; e um teste que falha se `from_config` for chamado (monkeypatch levantando erro).
  - **aberta:** truncar as barras do dia minuto a minuto durante uma operação longa: `aberta=True` até a saída real, depois fechada; `gravar` repetido mantém **o mesmo `op_id`** e nunca duas linhas.
  - **queda:** rodar só no fim do dia = rodar a cada minuto (mesmo conteúdo final, mesmos `op_id`s).
  - **plano do dia:** plano novo gravado no meio do dia (vale amanhã) não muda o `plano_id` do dia; reinício (cache vazio) usa o gravado.
  - **código:** hash do disco diferente do plano → `pulado`; com operações já gravadas → `interrompido`, operações da manhã preservadas, chamadas seguintes não alteram; hash nulo → roda com motivo de aviso. Simule o hash com monkeypatch de `codigo.hash_estrategia`.
  - **interruptor:** eventos no diário desligando a ligação às 11:00 → operações com entrada depois de 11:00 `conta=False`; `liquido` do pregão soma só as que contam.
  - **conferência/checksum:** `conferir` → `conferido`, checksum gravado; alterar um candle do dia → `divergencias` acusa; nova chamada de `rodar_dia` não muda nada (congelado).
  - **sem candle hoje:** `barras_do_dia` → `None` e nenhuma linha gravada.
- [ ] **Step 2:** FAIL. **Step 3:** implementar `core/papel.py` (docstring do módulo: o porquê do recálculo inteiro e da identidade com o backtest).
- [ ] **Step 4:** testes + suíte → PASS.
- [ ] **Step 5: mutação:** (a) usar `from_config`/ignorar `exec_` → montagem falha; (b) aquecimento fixo 1 pregão → identidade falha; (c) upsert que apaga e reinsere (novo `op_id`) → teste do `op_id` falha; (d) regra da aberta sem checar `reason` → teste da aberta falha; (e) `interrompido` apagando o gravado → falha.
- [ ] **Step 6: commit** `core/papel.py tests/test_papel_motor.py` (+ `strategies/base.py` se mudou) — `feat(papel): motor do papel identico ao backtest`.

---

### Task 4: O papel dentro do serviço de captura

**Files:** Modify `captura.py`; Test `tests/test_captura_processo.py` (acrescentar).

**Interfaces:**
- Consumes: `papel.rodar_dia`, `papel.gravar`, `papel.conferir`, `papel.divergencias`.
- Produces: no `estado.json`, chave `papel: {"calculado_em": iso|None, "pendente": bool, "ligacoes": {"<ligacao_id>": {"status": str, "motivo": str|None}}, "divergencias": int}`.

- [ ] **Step 1: testes (falhando)** com o `MT5Falso` existente e uma cadeia com plano/ligação no banco temporário:
  - volta que grava candle novo → `papel_pregoes` do dia existe e `estado["papel"]["calculado_em"]` preenchido;
  - volta **sem** candle novo → papel não é recalculado (conte chamadas de `papel.rodar_dia` por monkeypatch);
  - banco ocupado na gravação do papel → `pendente=True`; volta seguinte sem candle novo recalcula e grava;
  - exceção dentro do papel de uma ligação não derruba a volta nem impede o `publicar` (estado escrito, `erro` da volta nulo, motivo na ligação);
  - conferência do dia → `papel.conferir` chamado para o dia conferido; pregões `conferido`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar: em `volta`, depois de `_buscar_e_gravar` ter gravado candle novo (ou com `self.papel_pendente`), passo `_papel(agora)`: leitura curta (`db.connect(read_only=True, tentativas=4)`) → `rodar_dia` → `connect_write(tentativas=4)` → `gravar`; `_Ocupado`/`RuntimeError` de banco → `papel_pendente=True`. Em `_conferir_com`, depois de conferir cada dia: `papel.conferir(con, dia, agora, cache)` (mesma conexão de escrita; o cálculo pode ser feito antes de abrir o escritor, como as barras do MT5). `cache_codigo` vive no `Servico`. Publicar a chave `papel`. Comentários do porquê (identidade, nunca atrasar o publicar).
- [ ] **Step 4:** `tests/test_captura_processo.py` + suíte → PASS.
- [ ] **Step 5: mutação:** calcular a cada volta (sem checar candle novo) → teste de contagem falha; não marcar pendente → teste do ocupado falha.
- [ ] **Step 6: commit** `captura.py tests/test_captura_processo.py` — `feat(captura): papel calculado a cada candle novo e na conferencia`. Avisar: fechar a janela da Captura antes de reabrir o `iniciar.bat`.

---

### Task 5: Leituras para a tela (`core/papel_leitura.py`)

**Files:** Create `core/papel_leitura.py`; Test `tests/test_papel_leitura.py`.

**Interfaces (todas recebem `con` de leitura):**
- `portfolios_com_papel(con) -> list[dict]` — `{portfolio_id, nome, ligado}` para o seletor.
- `resumo(con, portfolio_id, dia) -> dict` — `{"resultado_hoje", "posicao": {"liquida": int, "por_ligacao": {id: int}}, "pior_momento": {"valor", "quando"}, "limite_dia": float|None, "acumulado": {"valor", "pregoes", "operacoes"}, "n_variantes", "n_operando", "contas": {"demo": {...}|None, "real": {...}|None}, "capital"}` — só operações `conta=True`; `resultado_hoje` = fechadas + aberta provisória; `pior_momento` = mínimo da curva minuto a minuto do dia (reconstrua com as operações fechadas acumuladas pela `exit_ts` e a aberta marcada pelo fechamento de cada barra desde a entrada — barras do dia do banco); `limite_dia` = `contas.limite_perda_dia` da conta demo do portfólio (pode ser `None`); acumulado **desde `vale_a_partir` do plano em vigor** de cada ligação.
- `variantes(con, portfolio_id, dia) -> list[dict]` — por ligação: nome, ligada, fase, `status` do pregão + motivo, posição (0/±N), hoje, n_ops, acerto `"g/f"`, acumulado, contratos do plano, plano_id, `gravado_mesmo_assim` + pendências (`plano.marca_mesmo_assim`), cor (índice estável por `ligacao_id`). Ordem: posição aberta primeiro, depois resultado do dia desc.
- `operacoes_do_dia(con, portfolio_id, dia, ligacao_id=None) -> list[dict]` — linhas da tabela (§6.5 da spec), com `conta`.
- `marcadores(con, portfolio_id, dia) -> list[dict]` — para o gráfico: `{time, position, shape, color, text}` no formato de marcadores do dash_tvlwc já usado em `ui/components/charts.trade_markers` (reuse a convenção), cinza quando `conta=False`; e `linhas_abertas` (stop/alvo vigentes).
- `curva_vs_esperado(con, portfolio_id, ligacao_id=None) -> dict` — `{"dias": [...], "papel": [...], "mediana": [...], "p10": [...]|None, "p90": [...]|None, "faixa_atual": "abaixo_p10"|"p10_p50"|"p50_p90"|"acima_p90"|None, "aviso": str|None}`. Expectativa do plano (`{"3_meses": {"pregoes": 63, "p10", "p50", "p90"}, ...}`, pode faltar) interpolada linearmente por pregão a partir de 0 no dia `vale_a_partir`; por variante: faixa + mediana; portfólio (`ligacao_id=None`): soma das medianas, `p10/p90=None`.
- `comparativo(con, portfolio_id) -> dict` — colunas `esperado_wfa` (médias por operação e por contrato dos `wfa_trades` do `wfa_id` de cada plano em vigor: resultado médio por operação, pontos por operação, fator de lucro, acerto, contratos por operação) e `papel` (mesmas métricas sobre `papel_operacoes` com `conta`, desde o plano em vigor); `demo`/`real` = `None`.
- `alertas(con, portfolio_id, dia) -> list[dict]` — gravado mesmo assim, pulado/interrompido, checksum divergente (`papel.divergencias`).

- [ ] **Step 1: testes (falhando)** semeando `papel_operacoes`/`papel_pregoes` à mão (sem rodar o motor): um portfólio com 3 ligações (uma desligada no meio do dia), operações fechadas e uma aberta, expectativa parcial (só `3_meses`), plano sem expectativa, conta sem limite. Verifique cada número com conta feita à mão no teste (resultado do dia, posição líquida, pior momento numa sequência conhecida, acumulado desde `vale_a_partir`, faixa atual, médias do esperado WFA, ordem das variantes, `conta=False` fora dos totais).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS + suíte.
- [ ] **Step 5: mutação:** incluir `conta=False` no resultado → falha; somar p10 no portfólio → falha; acumulado desde o primeiro papel (e não desde o plano em vigor) → falha.
- [ ] **Step 6: commit** — `feat(papel): leituras da tela Operacao`.

---

### Task 6: Sub-tela Ao vivo › Operação

Siga `.claude/agents/designer-ui.md` e o rascunho aprovado `.superpowers/brainstorm/67-1790900038/content/operacao-portfolio-v2.html` (abra e reproduza a estrutura, as seções e a hierarquia; tema e variáveis do `ui/assets/style.css`).

**Files:** Create `ui/components/operacao_panel.py`, `ui/callbacks_operacao.py`; Modify `ui/components/ao_vivo_panel.py` (opção "Operação" no `av-subtela`), `ui/callbacks_pregao.py` (callback `subtela` mostra/esconde o bloco e liga o Interval da Operação), `ui/callbacks.py` (registro), `ui/assets/style.css` (bloco `/* ---- Ao vivo › Operação ---- */`); Test `tests/test_operacao_tela.py`.

**Interfaces:**
- Consumes: Task 5 (todas as leituras), `D.estado_captura()`, `pregao_panel.situacao`, ações da seção 1 (`ao_vivo.ligar_membro/desligar_membro/desligar_portfolio`) com o padrão de confirmação em dois cliques existente.
- Ids com prefixo `av-op-`: `av-op-bloco`, `av-op-intervalo` (2 s, desligado fora da sub-tela), `av-op-portfolio` (seletor, `persistence=True`), `av-op-versao` (Store com `papel.calculado_em`), `av-op-kpis`, `av-op-grafico` (Tvlwc), `av-op-tf`, `av-op-agora`, `av-op-cheia`, `av-op-variantes`, `av-op-filtro`, `av-op-operacoes`, `av-op-curva` (Tvlwc ou SVG do padrão do app), `av-op-curva-modo` (Portfólio | Por variante + dropdown), `av-op-comparativo`, `av-op-alertas`, `av-op-legenda`.

Comportamento:
1. Pulso de 2 s lê **só** o `estado.json`: atualiza a `situacao` e grava `av-op-versao` quando `papel.calculado_em` muda (senão `no_update`). Tudo o que lê o banco depende de `av-op-versao`/seletor/filtro — nunca do Interval direto.
2. Gráfico: mesmas regras do Pregão (série só regravada quando muda o minuto; candle em formação por `tick`; 1/5/15 min; tela cheia; voltar para agora); marcadores das operações + linhas de stop/alvo da aberta (`priceLines`).
3. Seções e textos conforme spec §6 (1–8), cada indicador com (?) de faixa boa/ruim.
4. Muitas variantes (spec §6.4): coluna de variantes com `max-height` = altura do gráfico e `overflow-y:auto`; nomes `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` + `title`; operações com altura máx. ~10 linhas, rolagem e cabeçalho `position: sticky`; legenda em chips roláveis que escondem/mostram a variante no gráfico (filtrar marcadores); > 8 variantes repetem a cor com outra forma de marcador.
5. Estados vazios/erros da spec §7.

- [ ] **Step 1: testes (falhando):** funções puras de desenho (KPIs com e sem limite, cartão de variante pulada/interrompida/gravado mesmo assim, linha de operação aberta e `conta=False`, 15 variantes com nomes de 45 caracteres → todas renderizadas com `title` e classe de reticências), e o teste estrutural: nenhum callback que lê o banco tem `av-op-intervalo` como Input; `test_callbacks_sem_ciclo.py` verde.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** testes + suíte → PASS.
- [ ] **Step 5: conferir na tela** com instância descartável (porta ≠ 8050) sobre **uma cópia** do banco (apague a cópia depois; não toque no app do usuário nem na captura): semeie na cópia um portfólio com 15 variantes e papel de um dia (pode rodar `papel.conferir` na cópia sobre um dia passado), confira rolagens, reticências, filtro, chips, gráfico, comparativo; screenshots no relatório.
- [ ] **Step 6: commit** — `feat(ao-vivo): sub-tela Operacao com o papel ao vivo`. Avisar: **feche e abra o `iniciar.bat`** (e a janela da Captura, pela Task 4).

---

### Task 7: Documentação

**Files:** `CLAUDE.md`, `CHANGELOG.md`, `docs/CALCULOS-CANDIDATA.md` (se citar o motor) — via agente `documentador` ou direto.

- [ ] CLAUDE.md: tabela de modos (Ao vivo: `papel.py`, `papel_leitura.py`, `callbacks_operacao.py`, `operacao_panel.py`); armadilhas: papel = backtest por construção (montagem do perfil igual ao WFA; nunca `from_config`), aquecimento calculado, `op_id` estável, papel conferido congelado; "Onde estamos": parte 3 ✅, próximo = parte 4 (ordens) com o requisito "encerrar posição × só não abrir ao pausar"; tabelas que não se recriam inclui `papel_*`.
- [ ] CHANGELOG: entrada "Ao vivo, parte 3: incubação em papel" em linguagem de usuário.
- [ ] Commit `docs: incubacao em papel`.

---

## Depois de todas as tarefas

Revisão final da branch (modelo mais forte). Conferência real com o mercado aberto: ligar um portfólio de teste do usuário (com plano gravado) e ver as operações de papel aparecerem no gráfico e na tabela; depois do fechamento, pregão `conferido`.
