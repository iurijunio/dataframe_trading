# Menu da esquerda, topo e Backtest dentro da Mineração — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tirar ativo, "Sincronizar com MT5" e a aba Backtest do topo; a Backtest vira subtela da Mineração; o menu da esquerda ganha topo fixo, 5 abas e gavetas, com ~400 px.

**Architecture:** Só tela (Dash). Os ids dos campos não mudam — mudam de lugar na árvore. A subtela é um `dcc.RadioItems` novo (`mine-subtela`) que o callback `modo` passa a ler junto com `modo`. Gavetas são `html.Details`/`html.Summary` (abrem e fecham no navegador, sem callback); o resumo de cada gaveta e o pontinho das abas vêm de callbacks. Um JSON de "campos do menu" gravado do código de HOJE prova que nenhum campo mudou de id, valor, faixa, passo ou rótulo.

**Tech Stack:** Python 3, Dash 4.4.1, dash-ag-grid, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-menu-e-mineracao-design.md` (+ rascunhos em `docs/superpowers/specs/2026-11-01-menu-e-mineracao/` — **contrato**).

## Global Constraints

- Rascunhos aprovados são contrato; desvio só perguntando antes.
- Nenhum texto explicativo visível solto; explicação só no "(?)" (`ui.components.cartao.dica(texto)`).
- Textos de tela em português, como os de hoje.
- Ids usados por callbacks não mudam (`ativo`, `estrategia`, `d-de`, `d-ate`, `e-timeframe`, `excluir-holdout`, `btn-run`, `params-body`, `{"type":"val"|"opt"|"opt-on"|"optrow"|"valwrap","p":...}`, todos os `e-*`, `blk-*`, `sec-mineracao`, `acao-backtest`, `painel-backtest`, `painel-mineracao`).
- `ui/components/controls.py` é protegido: autorizado mexer no necessário, avisando no relatório. `ui/components/wfa_matriz.py`: não mexer.
- Motor, otimizador, WFA, Candidata, Portfólio, Ao vivo (conteúdo): não mudam.
- Referência das telas: `scripts/referencia_telas.py conferir` passa em todos os arquivos, exceto `parametros.json`, que só pode ser regravado na Task 4 **depois** do teste de campos do menu (Task 1) passar.
- Nunca subir cópia do app (preview) com o app real aberto: só fora do pregão ou com o app real fechado (a cópia abre o banco real).
- Commits: arquivo por arquivo (nunca `git add -A`), mensagem terminando em `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Suíte inteira passa ao fim de cada task: `.venv/Scripts/python.exe -m pytest -q` (2.713 hoje).

## Review Focus

1. Mineração rodando reescreve `grid-mine.rowData` a cada 800 ms: isso **não** pode pular para a subtela Backtest — só seleção/clique do usuário pula (teste na Task 2).
2. Carregar uma mineração salva (callback que escreve `cards`/`grid-trades`/`chart-capital` com `allow_duplicate`) **não** pula para o Backtest; fica na Varredura (teste na Task 2).
3. Trocar estratégia ou ativo com a aba Saída/Filtros aberta: `params-body` é reconstruído e a aba escolhida não muda; os campos do novo conjunto aparecem nos grupos certos (teste na Task 4).
4. Curva de capital (`chart-capital`, Tvlwc) desenhada enquanto escondida: hoje `painel-backtest` nasce visível, então não há solução pronta. O `rodar` inicial (`prevent_initial_call=False`, callbacks.py:764) passa a desenhar escondido. Precedente: `av-op-curva` (callbacks_operacao.py:849-883) usa callback clientside com `timeScaleAction` `fitContent` ao ficar visível — fazer igual para `chart-capital` (Task 2) e conferir no app (Task 5).
5. "tipo de alvo/stop" troca os blocos `blk-*` dentro da gaveta Gestão como hoje; trailing, direção e "sem entradas" mudaram de grupo mas leem/escrevem os mesmos ids (teste de campos, Task 1, e teste na Task 4).

## Ruling sobre a spec

A spec diz "cada campo continua no grupo em que está hoje", com exceções: direção e "sem entradas · 1/2/3" vão para a aba Entrada; Trailing vai para Gestão. "dias da semana" fica em Janela (aba Filtros); "tempo máximo (barras)" fica em Proteções.

O rascunho (contrato) mostra na Gestão "stop · alvo · trailing", nesta ordem e com rótulos curtos. Vale o rascunho: rótulos `stop`, `alvo`, `trailing` (só os de pontos; ATR/% mantêm os de hoje) e stop antes de alvo. A Task 1 declara essas 3 trocas de rótulo como permitidas.

"Visualizar estratégia" (`btn-chart`) vai para a barra do alto da subtela Backtest, ao lado de "Rodar backtest" (rascunho `tela-mineracao.html`).

---

### Task 1: Prova dos campos do menu (antes de mexer)

**Files:**
- Create: `scripts/campos_menu.py`
- Create: `tests/dados/campos_menu.json` (gravado do código de HOJE)
- Create: `tests/test_campos_menu.py`

**Interfaces:**
- Produces: `scripts.campos_menu.extrair(arvore) -> list[dict]` — percorre um componente Dash (qualquer árvore) e devolve, para cada componente com `id` que seja `dcc.Input`, `dcc.Dropdown`, `dcc.Checklist`, `dcc.DatePickerSingle` ou `dcc.RadioItems`, um dict `{"id": id_canonico, "tipo": nome_da_classe, "value"/"date", "min", "max", "step", "options": [values], "rotulo": texto do html.Label mais próximo no mesmo .fld ou None}`, ordenado por `id_canonico` (dict-id serializado com chaves ordenadas). Ordem e estrutura da árvore NÃO entram.
- Produces: `scripts.campos_menu.menu(simbolo, estrategia) -> list[dict]` — monta o menu como o app monta para aquele ativo/estratégia (hoje: `controls.periodo`, `mining.controles`, `controls.seletor_estrategia`, `controls.parametros` com `campos_da_estrategia(mod, None, ativo.faixas_do_ativo(simbolo, nome))`, `controls.execucao` com a camada 4 do ativo como `_camada4_do_ativo` aplica) e chama `extrair`. **Incluir o seletor `ativo`** (hoje no topo: `app.topbar`) para a lista já conter o id que vai mudar de lugar.
- **Sem banco e sem estado global:** `menu()` usa datas fixas (`inicio=2021-03-16`, `fim=2026-10-30`), lista fixa de instrumentos (`WIN$N`, `MES`, `MNQ`) e fixa `estrategia.value` = a estratégia do par (não `registry.nome_atual()`). O teste roda no banco isolado do conftest, que só tem WIN.
- `extrair` ignora ids novos que o layout novo cria e não são campo de hoje: `menu-aba`, `mine-subtela`, e qualquer id com `type` em `{"menu-pane","gaveta","gaveta-resumo"}`. E ignora spans `dica-mark` ao montar `rotulo`.
- Trocas de rótulo permitidas (ruling acima): `alvo_pontos` "Alvo (pontos)"→"alvo", `stop_pontos` "Stop (pontos)"→"stop", `trailing_pontos` "Trailing (pontos)"→"trailing". O teste aceita só essas.
- Produces: CLI `python scripts/campos_menu.py gravar|conferir` sobre todas as estratégias de `registry.descobrir()` × `WIN$N`, `MES`, `MNQ`.

- [ ] **Step 1:** Escrever `scripts/campos_menu.py` e gravar `tests/dados/campos_menu.json` com o código atual (`gravar`).
- [ ] **Step 2:** Teste `tests/test_campos_menu.py::test_campos_do_menu_iguais_a_referencia` — chama `menu(...)` para cada par e compara com o JSON gravado; falha listando os ids que diferem.
- [ ] **Step 3:** Teste `test_extrair_ignora_estrutura` — a mesma lista sai de `html.Div([a, b])` e de `html.Details([html.Summary("x"), html.Div([b]), a])`.
- [ ] **Step 4:** Rodar `pytest tests/test_campos_menu.py -v` → PASS; suíte inteira → PASS.
- [ ] **Step 5:** Commit (`scripts/campos_menu.py`, `tests/dados/campos_menu.json`, `tests/test_campos_menu.py`).

> Nas tasks seguintes, o que o `menu()` monta passa a ser o layout novo (Task 4 muda a função para montar o menu novo); o JSON **nunca** é regravado.

---

### Task 2: Mineração com subtelas Varredura | Backtest

**Files:**
- Modify: `ui/app.py` (`painel()`: `painel-backtest` passa a ficar DENTRO de `painel-mineracao`, junto com os blocos atuais da varredura, sob um `dcc.RadioItems(id="mine-subtela", value="varredura", options=[{"label":"Varredura","value":"varredura"},{"label":"Backtest","value":"backtest"}])`)
- Modify: `ui/components/mining.py` (se a barra de subtelas morar lá)
- Modify: `ui/callbacks.py` (`modo`, `faixas`, `carregar_combinacao`, callback novo da linha da combinação)
- Modify: `ui/components/controls.py` (mover `btn-run`/`acao-backtest` para onde o rascunho mostra: barra no alto da subtela Backtest — `tela-mineracao.html`) — protegido, avisar
- Modify: `ui/assets/style.css`
- Test: `tests/test_mineracao_subtelas.py`

**Interfaces:**
- Produces: `Input("mine-subtela","value")` com valores `"varredura"|"backtest"`; blocos `id="mine-bloco-varredura"` e `painel-backtest` (mantido) alternam por ele.
- Produces: `dcc.Store(id="store-combinacao")` com `{"origem": "linha"|"nuvem"|"aprovada", "n": int|None, "params": {nome: valor só dos varridos}, "menu": {snapshot}}`; `html.Div(id="mine-combinacao")` no alto da subtela Backtest.
  - `n` = `selectedRows[0]["n"]` (as linhas já trazem `n`, optimizer.py:567/732; a tabela é ordenável, então posição não serve). Aprovadas: o `n` da linha também. Nuvem: o `n` da linha com aquele `trial_id`.
  - Snapshot = valores de `{"type":"val"}` JÁ com o `p` novo aplicado + `excluir-holdout=["on"]` (o callback escreve e dispara no mesmo passo; snapshot dos States antigos marcaria "editado" logo na primeira rodada).
  - "editado" = no clique de "Rodar backtest", algum `val` ou `excluir-holdout` difere do snapshot, ou algum `e-*` mudou desde o clique da linha (guardar também os `e-*` no snapshot).
  - Trocar de estratégia ou carregar mineração salva limpa `store-combinacao` — callback separado com `allow_duplicate`; **não** acrescentar Output em `estrategia_ou_mineracao` (indexação posicional `r[...]`/`_INICIO_STEP`).
- Produces: callback clientside em `modo` + `mine-subtela` que manda `timeScaleAction` `fitContent` (com nonce, como `av-op-curva`) para `chart-capital` quando a subtela Backtest fica visível.
- `btn-chart` ("Visualizar estratégia") vai para a barra do alto da subtela Backtest, ao lado de `btn-run`.
- **Nesta task também** sai a opção Backtest de `modo` e o padrão vira `"aovivo"` (senão o app abre em branco entre a Task 2 e a 3).
- `carregar_combinacao` ganha `Output("mine-subtela","value")` (→ `"backtest"` quando carrega; `no_update` quando não) e `Output("store-combinacao","data")`.
- `modo(qual)` passa a ler também `mine-subtela`: `acao-backtest` visível só com `modo=="mineracao"` e subtela `"backtest"`; `sec-mineracao` só com subtela `"varredura"`.
- `faixas(ligados, qual, subtela)`: `minerando = qual=="mineracao" and subtela=="varredura"`.

- [ ] **Step 1: testes que falham** em `tests/test_mineracao_subtelas.py`:
  - `carregar_combinacao` lê `ctx.triggered_id`, que não existe fora de uma requisição Dash. Ou extrair o corpo para uma função pura `_carregar_combinacao(gatilho, selecionadas, clique, aprovadas, ids_val, linhas, n_run)` (padrão de `_estrategia_ou_mineracao`, callbacks.py:406), ou nos testes trocar `CB.ctx` por `SimpleNamespace(triggered_id=...)` como `tests/test_portfolio_moeda.py:242`.
  - `test_linha_da_tabela_pula_para_backtest` — gatilho `grid-mine` com `selectedRows=[{"n":3,"params":{"stop_pontos":10},"trial_id":3}]` → `mine-subtela` == `"backtest"`, `btn-run` incrementado, store com `n=3`.
  - `test_sem_selecao_nao_pula` — `selectedRows=[]` (é o que `progresso` deixa ao carregar mineração salva, callbacks.py:1198) → `mine-subtela` é `no_update`.
  - `test_carregar_mineracao_salva_nao_pula` — além disso, o callback que carrega mineração salva não tem `mine-subtela` como Output.
  - `test_primeira_rodada_nao_e_editado` — snapshot do store == valores que o próprio callback escreveu → linha sem "editado".
  - `test_linha_da_combinacao` — texto para cada origem: `"linha #3 · stop_pontos=10"`, `"nuvem · stop_pontos=10"`, `"aprovada #2 · stop_pontos=10"`; com menu diferente do snapshot → termina em `" · editado"`; sem store → `""`.
  - `test_faixas_so_na_varredura` — `faixas([["on"]], "mineracao", "backtest")` mostra o valor e esconde faixa e interruptor; com `"varredura"` mostra faixa e interruptor.
  - `test_backtest_dentro_da_mineracao` — `painel-backtest` é descendente de `painel-mineracao`; `modo.value == "aovivo"`; "backtest" não está nas opções de `modo`.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar. "n" da linha: posição (1-based) da linha selecionada em `grid-mine.rowData` ordenado como na tela; para aprovadas, posição em `grid-aprovadas`. Parâmetros mostrados: só os que a mineração varreu (as chaves de `MINERACAO`/faixas marcadas `on`), formato `nome=valor`, separados por `" · "`. "editado": comparar os valores atuais do menu com o snapshot quando o usuário clica "Rodar backtest".
- [ ] **Step 4:** Rodar os testes → PASS; `tests/test_callbacks_sem_ciclo.py` → PASS; `scripts/referencia_telas.py conferir` → OK; suíte → PASS.
- [ ] **Step 5:** Commit.

---

### Task 3: Topo limpo e tela inicial

**Files:**
- Modify: `ui/app.py` (`topbar`: saem `btn-mt5-sync` e `mt5-sync-status`; o `ativo` **continua no topo nesta task** — sai na Task 4; a aba Backtest e o padrão `aovivo` já saíram na Task 2)
- Modify: `ui/callbacks_mt5.py` (sai o callback `sincronizar_mt5`; se o módulo ficar vazio, sai o registro dele) e quem registra
- Modify: `ui/callbacks_pregao.py` (`selo_captura` perde os Outputs `btn-mt5-sync` disabled/title; o selo continua)
- Modify: `ui/components/ao_vivo_panel.py` (`av-subtela`: tirar `persistence`, `value="estrategias"` — o app sempre abre em Ao vivo › Estratégias)
- Modify: `ui/assets/style.css` (sai o CSS de `btn-mt5-sync`/`mt5-sync-status`; `.mt5-sync-wrap` pode ficar com outro nome só se nada mais depender)
- Modify: `tests/test_pregao_tela.py` (saem os testes do botão; os do selo ficam)
- Test: `tests/test_topo.py`

**Interfaces:**
- Consumes: Task 2 (Backtest já é subtela; sem isso a remoção da aba esconderia o backtest).
- `core/mt5_source.sincronizar` e `tests/test_mt5_source.py` ficam.

- [ ] **Step 1: testes que falham** em `tests/test_topo.py`:
  - `test_ordem_das_abas` — opções de `modo` == `["mineracao","wfa","candidata","estrategias","portfolio","aovivo"]`.
  - `test_sem_botao_de_sincronizar` — nenhum componente com id `btn-mt5-sync` ou `mt5-sync-status` no layout; nenhum callback com esses ids.
  - `test_ao_vivo_abre_em_estrategias` — `av-subtela.value == "estrategias"` e sem `persistence`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** testes + referência + suíte → PASS.
- [ ] **Step 5:** Commit.

---

### Task 4: Menu novo — topo fixo, abas, gavetas, 400 px

**Files:**
- Modify: `ui/components/controls.py` (protegido — avisar): reorganizar `periodo`, `seletor_estrategia`, `parametros`, `execucao` em:
  - `topo_menu(simbolo, inicio, fim)` → `html.Div(className="menu-topo")` com `ativo` (movido do `app.topbar`) e `estrategia` lado a lado; `d-de`, `d-ate`, `e-timeframe`; `excluir-holdout`; e `dcc.RadioItems(id="menu-aba", value="entrada", options=entrada|saida|filtros|risco|periodos)`.
  - `abas_menu()` → um `html.Div(id={"type":"menu-pane","aba":<aba>})` por aba:
    - entrada: `params-body` + direção + "sem entradas · 1/2/3" (campos direto, sem gaveta).
    - saida: gavetas Gestão (tipos de alvo/stop, blocos `blk-*`, stop/alvo/trailing na mesma linha) e Proteções.
    - filtros: gavetas Filtro de mercado, Janela, Filtro de mineração.
    - risco: gavetas Limites diários, Custos, Posição.
    - periodos: `mining.controles()` direto (um grupo só).
  - Gaveta: `html.Details([html.Summary([título, html.Span(id={"type":"gaveta-resumo","g":<grupo>})]), corpo], open=<primeira da aba>, id={"type":"gaveta","g":<grupo>})`.
- Keep: `controls.execucao()` continua existindo e devolvendo todos os grupos de hoje (é chamada por `scripts/referencia_telas.py:566`, `tests/test_perfil_por_ativo.py:56`, `tests/test_stop_percentual.py:196`); `abas_menu()` monta as abas a partir de funções por grupo que `execucao()` também usa.
- `cartao.dica` vai como irmão do `html.Label`, nunca dentro dele (`tests/test_moeda_rotulos.py:70-74` lê o texto do Label).
- Modify: `ui/app.py` (`sidebar` usa `topo_menu` + `abas_menu`; `topbar` perde o `ativo`)
- Modify: `ui/components/mining.py` (`controles()` sem `_section` com título, se a aba já dá o nome)
- Modify: `ui/callbacks.py`: callback `menu_abas(aba, modo, subtela)` mostra o pane da aba; esconde a opção "periodos" e o grupo Filtro de mineração quando não for Varredura (no Backtest a aba ativa "periodos" cai para "entrada"); callback `resumos(...)` escreve cada `gaveta-resumo`; callback `pontinhos(ligados, ids, modo, subtela)` marca as abas com campo `opt-on` ligado, só com `modo=="mineracao"` e subtela `"varredura"`.
- Modify: `scripts/campos_menu.py` (`menu()` monta o menu novo)
- Modify: `ui/assets/style.css` (`.sidebar` 342 → 400 px; topo fixo com `position:sticky`; grades 2/3 colunas; abas; gavetas; pontinho — conforme `menu.html`)
- Textos hoje visíveis no menu (`fld-hint`, `fld-hint solo`: "0 desliga", parágrafo do ADX, "0 desliga o limite. Ao bater, o dia para.", "cobrado por ponta: entrada e saída", "só na tendência…", "risco:retorno…", "onde o stop vai parar, a favor", "combinação com menos que isso é descartada") vão para `cartao.dica(texto)` ao lado do rótulo do campo ou do título da gaveta. `estrategia-nota` e `wf-resumo`/`mine-salvo`/`espaco-busca` são estado, não explicação: ficam.
- Test: `tests/test_menu_novo.py`; `tests/test_campos_menu.py` (sem mudar o JSON)

**Resumos (texto exato fica com o implementador; curto, sem frase):** Gestão "stop 8 · alvo 16 · trailing 0" (ou o tipo quando não for pontos); Proteções "desligadas" quando tudo 0; Filtro de mercado "sem filtro"/régua; Janela "09:30–15:45 · seg–sex"; Limites diários "sem limite"; Custos e Posição com valores e moeda (`moeda-c4`).

- [ ] **Step 1: testes que falham** em `tests/test_menu_novo.py`:
  - `test_ativo_no_menu_e_nao_no_topo` — `ativo` é descendente de `sidebar`, não de `topbar`.
  - `test_abas_e_grupos` — cada pane contém exatamente os grupos da tabela da spec (por título de gaveta) e entrada contém `params-body`, `e-direcao`, `e-sem-ent1..3`; `trailing_pontos` está na gaveta Gestão.
  - `test_sem_texto_explicativo_solto` — nenhum `html.P`/`Span` com classe `fld-hint` dentro de `sidebar`, exceto ids de estado (`estrategia-nota`, `wf-resumo`, `mine-salvo`).
  - `test_periodos_some_no_backtest` — `menu_abas("periodos","mineracao","backtest")` devolve pane "entrada" visível e opção periodos escondida.
  - `test_pontinho` — `opt-on` de `stop_pontos` ligado → aba "saida" marcada; nada ligado → nenhuma.
  - `test_resumo_gestao` — stop 8, alvo 16, trailing 0 → contém "8", "16" e "0".
  - `test_trocar_estrategia_mantem_aba` — `menu-aba` não é Output de quem reconstrói `params-body`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar.
- [ ] **Step 4:** `pytest tests/test_menu_novo.py tests/test_campos_menu.py tests/test_callbacks_sem_ciclo.py -v` → PASS (o JSON da Task 1 intacto). Só então `scripts/referencia_telas.py gravar` e conferir com `git diff --stat tests/dados/telas_win` que **só** `parametros.json` mudou; suíte → PASS.
- [ ] **Step 5:** Commit (incluindo `parametros.json` regravado, citando no corpo que a lista de campos foi provada igual).

---

### Task 5: Conferência no app (com o app real fechado)

**Files:** nenhum, salvo correções.

- [ ] **Step 1:** Confirmar que não há `python` rodando o app real; subir a cópia da worktree (entrada temporária no `.claude/launch.json` principal, com backup e restauração).
- [ ] **Step 2:** Abrir: cai em Ao vivo › Estratégias; topo sem ativo, sem Sincronizar, sem Backtest.
- [ ] **Step 3:** Mineração › Varredura no MES: menu de 400 px, topo fixo, 5 abas, gavetas abrem/fecham, resumos certos, pontinho ao marcar "minerar" no stop; rodar mineração curta (stop 3–16 → 14 combinações).
- [ ] **Step 4:** Clicar numa linha → vai sozinho para Backtest, curva de capital com altura cheia, linha "linha #N · stop_pontos=…", 4 abas (sem Períodos); desmarcar sexta e "Rodar backtest" → "· editado".
- [ ] **Step 5:** Carregar mineração salva → fica na Varredura. Console: só os 2 erros React #31 já conhecidos.
- [ ] **Step 6:** Desligar a cópia, restaurar `launch.json`, registrar no ledger.

> Depois do merge, o agente `documentador` tira de AGENTS.md, README e CHANGELOG as menções ao botão de sincronizar e à aba Backtest e descreve o menu novo (fora do plano, como nas etapas anteriores).
