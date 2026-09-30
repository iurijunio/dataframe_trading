# Projeto C, seção 1: tela "Ao vivo" › Estratégias

> Primeira entrega da tela **Ao vivo** (7º modo), que vai concentrar tudo o
> que roda com dinheiro ou dado de verdade: candles ao vivo (parte 2),
> incubação em papel (parte 3), ordens e comparativo com as contas demo/real
> (parte 4). Esta spec cobre só a **seção 1**: a blindagem do banco (1a) e a
> sub-tela Estratégias com a ficha de rastreio (1b). As partes 2–4 terão
> spec própria; o que elas herdam desta seção está no §10.

Desenhado em 30/09/2026. Duas revisões independentes por agente (desenho e
spec), ambas conferidas contra o código e o banco real.

## 1. O problema

1. **"Me perdi."** Para saber o que uma variante do portfólio vai operar é
   preciso cruzar à mão mineração → Walk-Forward → Candidata → plano. Nenhuma
   tela junta isso, e os dados reais mostram o custo: o plano #3 está ativo
   mas veio de uma mineração sem variante (invisível em qualquer portfólio), e
   duas variantes têm nome de outra estratégia.
2. **O banco de hoje pode derrubar uma estratégia em operação sem aviso**
   (conferido no código):
   - apagar mineração ou WFA apaga o plano junto (`optimizer.py:716`,
     `wfa_store.py:192`);
   - salvar de novo um WFA com a mesma chave aposenta o plano ativo dele
     (`wfa_store.py:74`);
   - reotimizar com mineração nova deixa **dois** planos ativos na mesma
     variante (`plano.py:69` só aposenta dentro do mesmo `wfa_id`), e se o
     novo some o velho volta a valer sozinho (`variantes.py:89`);
   - o plano não sabe de que variante é sem a mineração (a ligação só existe
     em `mining_runs.variante_id`), nem qual versão do código gerou os números;
   - `plano.aposentar` / `plano.excluir` existem mas nenhuma tela os chama.
3. Nada guarda **o que está ligado, em que fase, para qual conta** — e isso
   precisa existir antes de o primeiro robô rodar, porque é caro mudar depois
   que houver operação gravada apontando para esses registros.

## 2. Glossário (nomes de tela)

| Termo | Significado | Exemplo |
|---|---|---|
| Estratégia | o código em `strategies/` | `rompimento_canal` |
| Variante | configuração salva de uma estratégia, nome do usuário; atravessa reotimizações | "romp-canal-02" |
| Plano | o que a Candidata grava para operar | plano #1 |
| Plano em vigor | o plano que vale **naquele pregão** (pode ser diferente do último gravado) | |
| Fase | caminho até o dinheiro real, **por portfólio** | papel · demo · real mínimo · real |
| Conta | conta MT5 cadastrada | "Demo XP", "Mesa A" |
| Ligação | uma variante dentro de um portfólio (tem número próprio) | |

## 3. Decisões travadas (30/09/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Onde fica? | 7º modo **"Ao vivo"**, com sub-telas que só aparecem quando a parte delas estiver pronta. Nesta entrega: **Estratégias**. |
| 2 | Quantos portfólios operam? | **Vários ao mesmo tempo**, cada um com interruptor ligado/desligado. |
| 3 | Mesma variante em dois portfólios ligados? | **Permitido, só alerta** ("os contratos somam na conta"). |
| 4 | Fase controlada como? | **Por ligação** (variante dentro do portfólio). Subir de fase é sempre clique do usuário com confirmação (botões chegam na parte 4). |
| 5 | Reotimizou (plano novo) — e a fase? | **Mantém a fase**; o plano novo só vale **a partir do próximo pregão**, nunca com posição aberta. |
| 6 | Interruptores | No portfólio **e** em cada ligação. Variante recém-adicionada entra **ligada, no papel**. Motivos de não rodar: lista única no §4.6. |
| 7 | Contas | **Cadastro de contas** (nome, demo/real, limite de perda diária), **tudo editável**, toda edição vai ao diário. **Conta nunca se apaga, só se arquiva.** Cada portfólio aponta para uma conta demo e uma real (ambas opcionais); a fase decide para qual vai a ordem. |
| 8 | Papel | **O papel roda sempre**, para toda ligação ativa, em qualquer fase. A fase só decide se, **além** do papel, vai ordem para a demo/real. |
| 9 | Plano ativo | **Um plano ativo por variante.** Clusters diferentes da mesma estratégia são variantes diferentes, cada uma com o seu. |
| 10 | Nomes | "Variante" fica. "Degrau" vira **"Fase"**. |
| 11 | Apagar mineração/WFA | **⚠ Reverte a regra de 18/09/2026** ("apagar mineração apaga tudo que nasceu dela"): continua apagando em cascata, **exceto** quando a cadeia tem plano que opera ou pode operar (§4.1) — aí recusa com o motivo. **Confirmado pelo usuário.** |
| 13 | Religar depois do disjuntor | **Livre, a qualquer momento**, pelo interruptor — decisão do usuário, que substitui a regra "só volta com plano novo" escrita em `DEFINICOES["depois_de_desligar"]`. O evento registra que foi religada após o disjuntor. |
| 14 | Aposentar plano à mão | Vale a partir do **próximo pregão**; parar na hora é pelo interruptor. |
| 12 | Onde mora o estado ao vivo | Contas, ligações e diário ficam no `.duckdb` principal (mudam por clique, baixa frequência, e precisam da mesma transação do plano). O dado de alta frequência do robô (candles, operações) tem o arquivo decidido na spec da parte 2. |

## 4. Entrega 1a — blindagem (mudança de impacto: TDD + mutação + revisão)

### 4.1 Proteções em `core/` (não só na tela)

Uma cadeia (mineração → WFAs → planos) **está protegida** se algum plano dela:
(a) está `ativo`; ou (b) está aposentado mas **ainda em vigor**
(`aposentado_em > hoje`); ou (c) é de uma variante com **ligação não
removida** em qualquer portfólio (ligado ou não). Mineração ou WFA **sem
nenhum plano sempre pode ser apagado** — minerações-lixo de uma variante em
portfólio continuam apagáveis.

| Operação | Regra nova | Hoje |
|---|---|---|
| `optimizer.excluir_salva(run_id)` | cadeia protegida → `ValueError` com o motivo; senão apaga em cascata como hoje | apaga tudo |
| `wfa_store.excluir(wfa_id)` | idem, olhando só os planos desse WFA | apaga plano junto |
| `wfa_store.salvar` com chave repetida | se o antigo tem **qualquer plano**, ele **fica** e o novo entra ao lado (novo `wfa_id`); sem plano, substitui como hoje. Na lista da Candidata o antigo ganha "(tem plano)" no rótulo | re-aponta os planos e aposenta |
| `plano.excluir(plano_id)` | recusa se (a), (b) ou (c) | apaga |
| `plano.salvar(...)` | aposenta **todos** os ativos da **mesma variante** (por `planos_operacao.variante_id`, §4.2); plano sem variante mantém a regra por `wfa_id` | só mesmo `wfa_id` |

**Recusa na tela:** todas as recusas são `ValueError` com texto em português.
- `excluir_mineracao` (`ui/callbacks.py:1581`) ganha saída de aviso
  (`mine-aviso`, novo) e **não** limpa o seletor nem chama
  `MINERACAO.esquecer()` quando recusa.
- `wfa_excluir` (`ui/callbacks.py:1697`) escreve o motivo em vez de
  "excluído".
- `cli.py minas --limpar` pula a recusada, continua, e lista os motivos no fim.

Exemplo de motivo: *"a mineração #47 não pode ser apagada: o plano #1 dela
está ativo na variante romp-canal-02 (portifolio-teste)"*.

### 4.2 Plano: variante, vigência e impressão digital

```sql
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS variante_id BIGINT;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS vale_a_partir DATE;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS aposentado_em DATE;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS codigo_hash VARCHAR;
ALTER TABLE wfa_runs        ADD COLUMN IF NOT EXISTS codigo_hash VARCHAR;
```

**`variante_id` no plano** é retrato, gravado por `plano.salvar` (via
`run_id → mining_runs`). A migração preenche os existentes pelo mesmo
caminho. `plano_em_vigor`, a regra de aposentar e `rastreio` leem **esta
coluna**, nunca o join com a mineração — assim o plano continua sabendo de
quem é mesmo depois de a mineração ser apagada.

**Vigência:**
- `plano.salvar(..., agora=None)` (relógio injetável para teste).
  `vale_a_partir` = próximo dia de semana (seg–sex) **depois** da data de
  gravação — gravar sexta, sábado ou domingo → segunda. Feriado não precisa
  de calendário: sem pregão, o plano começa no pregão seguinte.
- Ao gravar P2, cada ativo P1 da variante vira `aposentado` com
  `aposentado_em = P2.vale_a_partir` — **continua em vigor até lá**.
- **Aposentar à mão** (botão novo, §5): `aposentado_em = próximo dia útil`,
  nunca "hoje" — o pregão em curso termina com o plano que começou (decisão
  5). Se o plano já estava aposentado, `aposentado_em = min(atual, novo)`.
  Para parar **agora**, o caminho é o interruptor da ligação, não aposentar.
- Aposentar P2 antes de ele valer **não ressuscita** P1: P1 sai de vigor na
  data já marcada e a variante fica sem plano em vigor até um novo ser gravado.
- Dois planos gravados no mesmo dia: o do meio nunca entra em vigor (é
  aposentado com `aposentado_em = vale_a_partir` dele mesmo).
- `_quando_reotimizar` continua contando da **gravação**, não da vigência
  (diferença de no máximo 3 dias; não vale mexer).
- Planos antigos: `vale_a_partir` nulo = vale desde sempre; `aposentado_em`
  nulo com estado `aposentado` = fora de vigor desde sempre.

```python
core/variantes.py
    plano_em_vigor(variante_id, dia: date | None = None) -> dict | None
    # planos da variante (planos_operacao.variante_id) com
    #   (vale_a_partir IS NULL OR vale_a_partir <= dia) AND
    #   ((estado = 'ativo' AND aposentado_em IS NULL) OR aposentado_em > dia)
    # desempate: plano_id DESC LIMIT 1 (cobre planos antigos com dois ativos)
```

`plano_ativo` (usado pela análise de portfólio) não muda.

**Impressão digital do código (`codigo_hash`):**
- sha256 de `strategies/<estrategia>.py` **+** `strategies/base.py`, com
  quebras de linha normalizadas para `\n` (o git converte LF↔CRLF nesta
  máquina).
- Gravada no **WFA quando ele roda** (é aí que os números do plano nascem);
  o plano **copia a do WFA**. Se o arquivo atual já diverge da do WFA no
  momento de gravar o plano, a Candidata avisa.
- Nulo (todos os planos de hoje: #1, #3, #4) = **roda, com aviso** *"código
  não conferido (plano anterior a 30/09/2026)"* — nunca vira "código mudou".
- Na parte 3 o robô confere o hash do que **ele carregou** (o `registry`
  guarda o módulo em memória, e o disco pode ter mudado depois).

### 4.3 Contas, portfólio e ligação

```sql
CREATE SEQUENCE IF NOT EXISTS seq_conta_id START 1;
CREATE TABLE IF NOT EXISTS contas (
    conta_id         BIGINT PRIMARY KEY,
    nome             VARCHAR NOT NULL,
    tipo             VARCHAR NOT NULL,     -- 'demo' | 'real'
    limite_perda_dia DOUBLE,               -- R$, opcional (mesa proprietária)
    criado_em        TIMESTAMP NOT NULL,
    arquivada_em     TIMESTAMP
);

ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS ligado BOOLEAN DEFAULT false;
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS conta_demo_id BIGINT;
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS conta_real_id BIGINT;

-- substitui portfolio_variantes: a chave composta de hoje não deixa uma
-- variante voltar ao portfólio sem apagar o histórico, e a parte 4 precisa
-- de um número inteiro por ligação para etiquetar a ordem no MT5
CREATE SEQUENCE IF NOT EXISTS seq_ligacao_id START 1;
CREATE TABLE IF NOT EXISTS portfolio_membros (
    ligacao_id      BIGINT PRIMARY KEY,
    portfolio_id    BIGINT NOT NULL,
    variante_id     BIGINT NOT NULL,
    adicionado_em   TIMESTAMP NOT NULL,
    removido_em     TIMESTAMP,            -- remoção só marca, nunca apaga
    fase            VARCHAR NOT NULL,     -- 'papel'|'demo'|'real_minimo'|'real'
    fase_desde      TIMESTAMP NOT NULL,
    ligada          BOOLEAN NOT NULL,
    desligada_por   VARCHAR,              -- 'usuario' | 'disjuntor'
    desligada_em    TIMESTAMP,
    desligada_plano_id BIGINT             -- plano em vigor quando desligou (informativo)
);
```

- **DuckDB não tem UNIQUE parcial:** "um membro não removido por (portfólio,
  variante)" e "nome de conta único entre as não arquivadas" são checados em
  código, **dentro da transação** que grava.
- **Migração** (roda a cada subida, tem de ser idempotente): cada linha de
  `portfolio_variantes` vira membro (`papel`, ligado, `fase_desde =
  adicionado_em`) **somente se não existe nenhum membro — removido ou não —
  para aquele par**. Sem contar os removidos, uma variante removida
  voltaria a cada reinício. A tabela velha fica intacta e sem uso.
- Adicionar variante que já está (não removida) = não faz nada (como o
  `INSERT OR IGNORE` de hoje). Voltar a adicionar uma removida cria
  **ligação nova, no papel** — a incubação recomeça; a antiga fica no histórico.
- **Remover:** com o portfólio **desligado**, desliga e remove na mesma
  transação (dois eventos) — a tela de Portfólio continua funcionando como
  hoje. Com o portfólio **ligado**, recusa: *"desligue a variante ou o
  portfólio antes de remover"*, mostrado em `pf-avisos`.
- **Religar depois do disjuntor:** permitido a qualquer momento (decisão
  13). O evento `membro_ligado` leva `motivo = "religada após disjuntor"` e
  o plano em vigor; o cartão mostra *"religada por você após o disjuntor de
  DD/MM"* até o próximo desligamento. `DEFINICOES["depois_de_desligar"]`
  (`plano.py:189`) passa a dizer *"volta a operar quando o usuário religar"*
  nos planos novos; os antigos guardam o texto da época (retrato).
- `conta_demo_id` tem que ser conta `demo` não arquivada; `conta_real_id`,
  `real` não arquivada.
- `portfolio.membros()` e o resto do módulo passam a ler de
  `portfolio_membros` (ignorando removidos).

### 4.4 Diário de eventos

```sql
CREATE SEQUENCE IF NOT EXISTS seq_evento_id START 1;
CREATE TABLE IF NOT EXISTS ao_vivo_eventos (
    evento_id     BIGINT PRIMARY KEY,
    quando        TIMESTAMP NOT NULL,
    tipo          VARCHAR NOT NULL,
    origem        VARCHAR NOT NULL,   -- 'usuario' | 'disjuntor' | 'sistema'
    portfolio_id  BIGINT,
    ligacao_id    BIGINT,
    variante_id   BIGINT,
    conta_id      BIGINT,
    plano_id      BIGINT,
    de            VARCHAR,
    para          VARCHAR,
    motivo        VARCHAR
);
```

Tipos desta entrega: `portfolio_ligado/desligado`, `portfolio_conta_mudou`,
`membro_adicionado/removido`, `membro_ligado/desligado`, `fase_mudou`,
`conta_criada/editada/arquivada`, `plano_gravado`, `plano_aposentado`,
`plano_vinculado`, `variante_renomeada`.

- **Só inserção.** `core/ao_vivo.py` expõe `registrar(con, ...)` e leituras;
  nenhuma função de `core/` faz `UPDATE`/`DELETE` nesta tabela (teste varre
  o fonte).
- `registrar` **exige a conexão do chamador**: `plano.salvar`,
  `ligar_membro` etc. gravam o estado e o evento **na mesma transação** —
  ou os dois ficam, ou nenhum.
- Eventos de plano levam `variante_id`, para aparecerem no histórico da
  ficha mesmo sem `ligacao_id`.

### 4.5 Arrumação: vincular e renomear

- **Vincular plano sem variante** (hoje: #3, mineração #50): grava
  `variante_id` na mineração **e em todos os planos dela** (inclusive
  aposentados, ex.: #2). Só aceita variante **da mesma estratégia**. Se a
  variante destino já tem plano ativo (caso real: a variante 7 tem o #4),
  a tela pergunta qual fica ativo; o outro é aposentado pela regra de
  vigência do §4.2. Evento `plano_vinculado`.
- **Renomear variante:** nome único dentro da estratégia. Evento
  `variante_renomeada` (de/para).

### 4.6 Por que uma ligação roda ou não (lista única)

`em_operacao()` devolve, por ligação, o **primeiro** motivo desta lista que
se aplica (nessa ordem); nenhum = **roda**:

1. portfólio desligado
2. desligada pelo disjuntor em DD/MM
3. pausada por você
4. sem plano em vigor
5. código da estratégia não encontrado (arquivo sumiu ou não carrega)
6. código mudou desde o plano (hash gravado ≠ arquivo atual)

Avisos que **não** impedem rodar (aparecem junto): código não conferido
(hash nulo), variante em 2+ portfólios ligados, conta da fase arquivada ou
não escolhida (só importa a partir da fase demo), plano vencido
(`reotimizar_em` passou).

### 4.7 Módulo novo

```
core/ao_vivo.py (sem Dash)
    contas: criar, editar, arquivar, listar
    ligar_portfolio / desligar_portfolio, definir_contas(portfolio_id, demo, real)
    ligar_membro / desligar_membro(ligacao_id, por='usuario')
    aposentar_plano(plano_id)             # regra do §4.2, com evento
    vincular_plano(run_id, variante_id, manter_plano_id)
    renomear_variante(variante_id, nome)
    registrar(con, tipo, origem, ...), eventos(filtros)
    em_operacao() -> list[dict]           # §4.6
    repetidas() -> list[dict]
    rastreio(ligacao_id) -> dict          # §5.2
```

## 5. Entrega 1b — tela Ao vivo › Estratégias

### 5.1 Layout

1. **Portfólios:** um cartão por portfólio, com interruptor (ligar pede
   confirmação), contas demo/real escolhidas por lista, e contagem de
   variantes. Alerta de variante repetida em portfólios ligados.
2. **Variantes em operação:** agrupadas por portfólio ligado. Cartão fechado:
   `romp-canal-02 · rompimento_canal · WIN$N · Fase: papel há 12 dias ·
   6 pregões com este plano · plano #1 · reotimizar até 24/03/2027`, com
   interruptor próprio e o motivo/avisos do §4.6.
3. **Contas:** lista com criar/editar/arquivar (nome, tipo, limite diário).
4. **Arrumação:** "planos ativos sem variante" com **vincular** (§4.5).

"Pregões com este plano" nesta entrega = dias de semana desde
`vale_a_partir` (nulo: desde o próximo dia útil após `created_at`); na
parte 3 passa a contar pregões efetivamente rodados.

### 5.2 A ficha de rastreio (ao clicar no cartão)

Cabeçalho com **renomear variante** e **aposentar plano** (confirmação).
Lida **primeiro dos retratos do plano** (que sobrevivem à mineração), e só
depois da mineração/WFA, se ainda existirem:

1. **Origem** — mineração: nome, data, nº de combinações, faixas de/passo/até,
   início do holdout. Ausente → *"mineração apagada ou anterior às variantes"*.
2. **Walk-Forward** — nome, IS/OOS, inteligência, lucro OOS, trades, DD,
   veredito.
3. **Candidata** — veredito congelado (`regua`) e cada portão ✔/✖.
4. **Plano em vigor** — parâmetros exatos e camada 4 (reusa
   `ui/components/ficha.py`), capital, contratos, risco por pregão,
   disjuntor, `reotimizar_em`, `vale_a_partir`, conferência do código.
   Se há plano gravado que ainda não vale: *"plano #N entra em DD/MM"*.
5. **Histórico** — **todos** os planos da variante (por
   `planos_operacao.variante_id`, não só o último de cada WFA como
   `linha_do_tempo` faz hoje) e os eventos do diário da ligação e da variante.

### 5.3 Outras telas que mudam

- **Candidata:** a mensagem de plano gravado (`callbacks_candidata.py:276`)
  passa a dizer *"vale a partir de DD/MM"* e *"aposentou o plano #X"*.
- **Mineração / Walk-Forward:** avisos de recusa (§4.1).
- **Portfólio:** remoção com recusa em `pf-avisos` (§4.3).
- **Selo de reotimização** (`plano.vencendo`): continua olhando só `estado
  = 'ativo'` — um plano aposentado-mas-em-vigor já tem substituto gravado,
  então não está "vencendo".

## 6. Arrumação dos dados reais

Feita **pelo usuário, pela tela** (§4.5), nunca por script: vincular o
plano #3 (mineração #50, `rompimento_abertura`) — hoje o único destino da
mesma estratégia com plano é a variante 7, que já tem o #4 ativo, então a
tela vai perguntar qual fica; renomear "variante-romp-canal-M15-28" (é
`rompimento_abertura`) e "variante-romp-abert-m15" (é `setup_cruzamento`).

## 7. Erros e estados

- Toda recusa de `core/` vira mensagem em português na tela; nunca stack trace.
- Portfólio ligado sem nenhuma ligação que rode: aviso no cartão.
- `connect_write` desiste em ~10 s se a mineração estiver gravando: o clique
  mostra *"banco ocupado, tente de novo"* em vez de falhar calado.

## 8. Testes

Banco temporário, como o resto da suíte. Mutação obrigatória em 4.1–4.6.

| alvo | prova |
|---|---|
| proteção de exclusão | recusa em (a), (b) e (c) separadamente, inclusive com portfólio desligado; mineração/WFA **sem plano** de variante em portfólio é apagada; recusa não apaga nada (nem trials); plano sem variante e mineração sem variante seguem a regra (a)/(b) |
| `wfa_store.salvar` repetido | com plano: antigo fica, novo entra, plano não muda de `wfa_id` nem de estado; sem plano: substitui |
| `plano.salvar` | grava `variante_id`; aposenta os ativos da mesma variante vindos de outra mineração; não toca outra variante; sem variante mantém regra por `wfa_id`; `vale_a_partir` para qua→qui, sex→seg, sáb→seg, dom→seg; evento na mesma transação |
| `plano_em_vigor` | antes de `vale_a_partir` devolve o anterior; no dia, o novo; dois gravados no mesmo dia (o do meio nunca vale); aposentar P2 antes de valer não ressuscita P1; aposentar manual vale só no próximo dia útil e usa `min`; planos antigos nulos, inclusive dois ativos (desempate por id) |
| `codigo_hash` | igual com LF e CRLF; muda com uma linha alterada na estratégia **ou** em `base.py`; plano copia do WFA; nulo vira aviso, não motivo |
| migração | cada `portfolio_variantes` vira membro; rodar duas vezes não duplica; **remover e reiniciar não ressuscita**; `planos_operacao.variante_id` preenchido pelo run |
| membros | adicionar duplicado não faz nada; readicionar removida cria ligação nova no papel; remover com portfólio desligado gera 2 eventos; com ligado recusa; religar após disjuntor é aceito e o evento registra o motivo |
| contas | edição registra de/para; nome único entre não arquivadas; nenhuma função apaga conta; demo/real validados no portfólio; arquivada não pode ser escolhida |
| diário | cada mudança gera exatamente um evento na mesma transação; exceção no meio não deixa estado sem evento; varredura do fonte: nenhum UPDATE/DELETE em `ao_vivo_eventos` |
| `em_operacao` | cada motivo do §4.6 isolado e a ordem de prioridade quando vários se aplicam; `repetidas` só entre portfólios **ligados** |
| vincular/renomear | vincular leva mineração e todos os planos; recusa estratégia diferente; com ativo no destino aposenta o escolhido; renomear recusa nome repetido na mesma estratégia |
| `rastreio` | funciona com mineração apagada (usa retratos e `variante_id` do plano); lista todos os planos; mostra plano futuro |
| callbacks | `test_callbacks_sem_ciclo.py` verde com o 7º modo e os novos avisos |

**Testes existentes que mudam** (de propósito, pela decisão 11):
`test_plano.py:85` (excluir WFA leva o plano) e `:87-111`, `:133` (regravar
WFA), `test_portfolio.py:50-62` e `:86-91`, `test_salvar.py:379`,
`test_callbacks_candidata.py:360`. Cada um é reescrito para a regra nova,
não apagado.

**Conferência na tela contra o banco real:** ligar "portifolio-teste", abrir
as fichas de romp-canal-02 e variante-romp-canal-M15-28, e desligar ao
final. Os eventos de ligar/desligar **ficam no diário** — são ações reais e
legítimas, não sujeira. A conferência **não cria conta de teste** (conta
nunca se apaga).

## 9. Fora desta seção

Botões de subir de fase, soma de risco por conta contra `limite_perda_dia`,
e qualquer coisa que rode sozinha — partes 2–4.

## 10. O que as partes 2–4 herdam

- **Parte 2 — candles ao vivo:** robô em processo separado; grava cada M1
  fechado; ao ligar, completa o buraco desde o último candle; no fim do
  pregão, reconfere o dia (correções da corretora entram pela regra de merge
  existente). Decidir o arquivo do dado de alta frequência (decisão 12):
  `connect_write` desiste em 10 s e a mineração segura o escritor.
- **Parte 3 — papel:** fixa `plano_em_vigor(dia)` no início do pregão;
  confere o hash do código **carregado**; operações de papel referenciam
  `ligacao_id` e `plano_id` e passam a proteger a cadeia (§4.1); contador
  de pregões reais.
- **Parte 4 — ordens:** magic number = **7_000_000 + `ligacao_id`** (evita
  colidir com robôs antigos na mesma conta); netting (posição líquida por
  ativo na conta, controle por ligação); contrato do mês (WINZ26) em vez de
  `WIN$N`; um terminal MT5 por conta; conferências de ordem rejeitada / não
  executada / robô ou MT5 caído / posição divergente; soma do risco diário
  por conta contra `limite_perda_dia`; botões de subir de fase; disjuntor
  grava `desligada_por='disjuntor'` + `desligada_plano_id`; desligar com
  posição aberta pergunta zerar × só não abrir.
- **Backup** das tabelas que não se recriam (diário, contas, membros,
  operações) antes da parte 3 — o `.duckdb` deixa de ser só cache.
