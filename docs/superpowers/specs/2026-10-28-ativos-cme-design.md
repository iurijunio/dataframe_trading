# Ativos da CME na pesquisa (MES e MNQ) — desenho

Data: 28/10/2026 · Branch: `new-strategies` · Status: aprovado em conversa;
revisado por agente (14 achados incorporados); aguardando leitura do usuário

## Objetivo

Levar os micros americanos **MES** (Micro S&P 500) e **MNQ** (Micro Nasdaq-100),
da CME, para a parte de **pesquisa** da plataforma: importação dos candles, gráfico,
backtest, mineração, Walk-Forward, Candidata e resultados. A operação ao vivo
(corretora, captura, ordens, papel) fica de fora — o usuário ainda não tem
corretora.

O WIN e tudo o que já foi salvo para ele (planos, minerações, Walk-Forwards,
Candidatas, portfólios) continuam com **resultado idêntico, número a número**.

## Decisões tomadas com o usuário

| # | Decisão | Por quê |
|---|---------|---------|
| D1 | Contratos **micro** (MES, MNQ), não mini | Tamanho compatível com a conta. |
| D2 | Dados do **próprio micro**, não do mini | Comparação minuto a minuto (7 anos): fechamento difere em média 1,5 tick, e a fonte troca de contrato em dias diferentes nos dois (até 250 pontos de diferença por 3–4 dias a cada trimestre). Misturar levaria esses desencontros ao backtest. |
| D3 | Opera-se o **pregão inteiro** da CME, dia e noite | Escolha do usuário. |
| D4 | O "dia" é o **pregão da CME**: das 18:00 de Nova York até as 17:00 do dia seguinte | É assim que a bolsa define o dia; limite diário, contagem de operações, fechamento forçado e Walk-Forward seguem isso. Nada fica aberto de um pregão para o outro. |
| D5 | Nos ativos americanos, **todo horário em hora de Nova York** (parâmetros, gráfico, relatórios). O WIN continua em Brasília | Nova York tem horário de verão e Brasília não; horário gravado em Brasília escorregaria 1 h duas vezes por ano. |
| D6 | **Caminho A — relógio de pregão** (ver abaixo) | Não mexe no motor; WIN intocado. |
| D7 | **Abertura de referência** na ficha do ativo; nos micros, **09:30 de Nova York** | As estratégias de abertura medem a partir da abertura da bolsa de ações, onde nasce o movimento; o dia continua começando às 18:00. |
| D8 | **Faixas de mineração por ativo**, na ficha; Claude propõe, o usuário ajusta | As faixas de hoje são do WIN (stop de 150 pontos é absurdo no MES). |
| D9 | Custo inicial: **US$ 0,60 por contrato por lado + 1 tick de derrapagem**, editável | Sem corretora ainda; ordem de grandeza típica de micro (corretagem + bolsa + NFA). |
| D10 | Portfólio que misture moedas (WIN em R$ com micro em US$) fica **bloqueado** | Somar real com dólar dá número errado; conversão de moeda fica para quando houver portfólio misto. |
| D11 | Arquivos protegidos `rompimento_abertura.py` e `ui/components/controls.py` podem ser alterados no mínimo necessário | Autorizado pelo usuário em 28/10 ("se precisar mexer em algum arquivo que precise de permissão, eu permito"). |

Decisões de Claude (C1 confirmada pelo usuário; C2 decidida por ele):

| # | Decisão | Por quê |
|---|---------|---------|
| C1 | Parâmetros e faixas em pontos são **inteiros** também nos micros (stop de 12 pontos, não 12,25) | A grade, a validação e a vizinhança da mineração tratam esses campos como inteiros; 1 ponto de passo é fino o bastante (4 ticks). Quem quiser precisão fina usa stop/alvo em porcentagem, que já arredonda ao tick. |
| C2 | `rompimento_ema_abertura` **só sinaliza a partir da abertura de referência** (09:30 NY nos micros), medindo a distância a partir da barra das 09:30 | Decisão do usuário em 28/10: "se é abertura, deve ser trabalhado na abertura". O `rompimento_abertura` já se comporta assim (só sinaliza depois de formar o range das 09:30). |

## Os dados (London Strategic Edge)

Arquivos em `ativos_temp/` (fora do git), baixados pelo usuário:

- `MICROSP500_futures_1m_2019-05-05_2019-09-14.parquet` + `..._2019-09-14_2026-10-28.parquet`
- `MICRONASDAQ100_futures_1m_2019-01-05_2019-09-20.parquet` + `..._2019-09-20_2026-10-28.parquet`

O site limita cada download a ~2,5 milhões de linhas; por isso cada ativo vem em
partes que se complementam. Conferido:

- Colunas: `time` (timestamp com fuso, **UTC**), `open`, `high`, `low`, `close`,
  `volume` (double), `trades` (inteiro).
- `time` é o **início** do minuto (mesma convenção do MT5): a primeira barra de
  domingo é 22:00 UTC no verão americano = 18:00 NY, e a última do dia é
  20:59 UTC = 16:59 NY. Um teste trava isso.
- Candles de 1 minuto, de 05/05/2019 (lançamento dos micros) até 28/10/2026;
  ~2,6 milhões por ativo. Só existem minutos com negócio.
- Preço **sem ajuste** (série contínua com o preço real de cada contrato, como o
  `WIN$N`). A opção "Adjusted for splits" do site não altera futuros.
- Partes emendam sem falha (MNQ: 1.352 minutos sobrepostos, idênticos; MES: uma
  parte acaba na sexta e a outra começa no domingo).
- Ruído de ponto flutuante (7665,4999 em vez de 7665,50): arredondar ao tick.
- Volume nunca zero.
- **Buracos da fonte** (iguais nos dois micros): de 27/02/2020 14:29 NY até
  03/03/2020 09:40 NY (o pregão de 28/02 não existe); 21/06/2022 (~272 barras); 12/10/2026 (~265 barras).
- Dias curtos **reais** (não são buraco): feriados, meio pregão (Black Friday,
  véspera de Natal), funeral do Carter (09/01/2025), paradas por queda em março
  de 2020. Saltos grandes reais: 12/01/2023 e 14/10/2026, às 08:30 NY (dado
  econômico).
- O último pregão de cada download é parcial (o arquivo acaba no meio do dia).

## Arquitetura

### Regra de unidades (vale para tudo abaixo)

Existem três unidades, e cada lugar usa só uma:

| Unidade | Exemplo MES | Onde vive |
|---------|-------------|-----------|
| **Humana** (pontos e hora de NY, como o usuário lê) | stop 12 pontos; janela 09:30 | Tela, ficha YAML, **tudo o que é salvo como parâmetro ou perfil**: `params`/`profile` de minerações, Walk-Forwards, Candidatas, planos, `execution_profiles`. |
| **Guardada** (preço × 10^`price_decimals`, relógio de pregão) | 543225; 15:30 | `bars_m1`, Parquet, **dentro do motor**, e **tudo o que é registro de trade**: `points`, `mae`, `mfe`, `entry_px`, `exit_px`, `sl_at_entry`, `wfa_trades` (`core/wfa_store.py:~110`), trades de mineração/Candidata. |
| **Dinheiro** (moeda do ativo) | US$ | Resultados, custos, `tick_value`, `point_value` da ficha. |

A conversão humana → guardada acontece **só dentro de `run_strategy`**
(`core/engine/execution.py:~211-222`), numa cópia local. A conversão guardada →
humana acontece **só na tela**, via `core/ativo.py`. Para o WIN as duas
conversões são identidade (escala 1, deslocamento 0).

### 1. Ficha do ativo (camada 1) — `configs/instruments/mes.yaml`, `mnq.yaml`

Mesmos campos do `win.yaml`, mais os novos. Campo novo ausente = comportamento de
hoje, então o `win.yaml` não precisa mudar.

```yaml
symbol: "MES"
description: "Micro E-mini S&P 500 - serie continua (London Strategic Edge)"
exchange: "CME"
currency: "USD"
timezone: "America/New_York"
price_decimals: 2          # 5432.25 guardado como 543225
tick_size: 0.25            # em pontos, como o usuario le
point_value: 5.00          # US$ por ponto, por contrato (MNQ: 2.00)
tick_value: 1.25           # MNQ: 0.50
allows_overnight: false
rollover_policy: "none"    # serie continua da fonte; day trade
# novos
sessao_abertura: "18:00"   # hora local (NY) em que o pregao comeca
abertura_referencia: "09:30"
perfil_padrao:             # preenche a camada 4 ao escolher o ativo (secao 7)
  inicio: "18:00"
  fim: "16:30"             # ultima entrada
  fechamento: "16:50"      # fechamento forcado, antes da pausa das 17:00
  corretagem: 0.60         # US$ por contrato por lado
  emolumentos: 0.0
  slippage_ticks: 1
  stop_pontos: 8             # etapa 4 (30/10): MES 8, MNQ 45
  alvo_pontos: 16            # etapa 4 (30/10): MES 16, MNQ 90
faixas: { ... }            # faixas de mineracao por parametro (secao 6)
```

Na tabela `instruments` (`core/schema.sql:~9`), `tick_size` é INTEGER: grava-se
`tick_unid` (MES: 25), não 0,25. Nenhuma coluna nova no banco — os campos novos
são lidos direto do YAML por `load_instrument_yaml`.

### 2. Relógio de pregão (caminho A)

Na importação, cada horário americano é convertido assim:

```
UTC  →  hora de Nova York (com horário de verão, via zoneinfo)
     →  + deslocamento fixo = 24:00 − sessao_abertura  (18:00 → +6 h)
     →  gravado como timestamp sem fuso em bars_m1.ts
```

Resultado: o pregão de 18:00 (NY, véspera) até 17:00 (NY) vira **00:00–23:00 da
mesma data**. Todo o código que hoje deriva o dia de `ts.astype("datetime64[D]")`
ou `CAST(ts AS DATE)` (limite diário, `day_id` do kernel, fechamento forçado,
`dias_semana`, `resample`, `trading_days`, Walk-Forward, métricas, gráficos por
dia) passa a enxergar a **data do pregão** sem mudança. A noite de domingo cai na
segunda (correto na CME). As viradas de horário de verão americano acontecem no
domingo de madrugada, com o mercado fechado — não há hora repetida nem pulada
dentro de um pregão. Para o WIN o deslocamento é zero.

**Datas:** os seletores de período (Walk-Forward, filtros, gráfico) trabalham com
a **data do pregão**. A lista de trades mostra data e hora do **calendário de
NY** — um trade de domingo 19:00 aparece com "domingo 19:00" e pertence ao
pregão de segunda. O (?) da lista explica isso.

**A regra de ouro:** o relógio de pregão nunca aparece para o usuário. Toda tela
que mostra ou recebe hora passa por `core/ativo.py`:

- `hora_para_exibir(ts, ficha)` — relógio de pregão → hora e data de NY.
- `hora_para_motor("09:30", ficha)` — hora de NY digitada → relógio de pregão
  (`09:30` → `15:30`). Chamada **só** dentro de `run_strategy` (perfil) e nos
  callbacks que filtram/posicionam o gráfico — nunca sobre um valor já
  convertido.

Lugares que exibem/recebem hora (o plano confere a lista completa com `grep`):

- gráfico de candles e marcas de trade (`ui/data.py:~265-290`,
  `ui/components/charts.py`);
- `store-window` de/até, que dá zoom no gráfico (`ui/callbacks.py:~691, ~717`);
- listas de trades e detalhes (`core/detalhes.py`, catálogo, ficha);
- histograma por hora e por dia da semana (`core/analytics.py:~64-70`);
- campos de horário do perfil — início/fim da janela, fechamento, `sem_entrada`
  (`ui/components/controls.py:~203-209`, `ui/callbacks.py:~592, ~790`);
- filtro por hora do catálogo (`catalogo.py`).

**Janela que atravessa a pausa:** uma janela 16:00→19:00 NY vira 22:00→01:00 no
relógio de pregão e ficaria vazia em silêncio. A tela valida início ≤ fim **na
ordem do pregão** (18:00 é o começo) e recusa com mensagem.

### 3. Preço com centavos

`bars_m1` continua `BIGINT`. O preço é guardado como `preço × 10^price_decimals`
(MES: 5432,25 → 543225). Para o WIN `price_decimals = 0`, nada muda. A tela
divide por `escala` em todo lugar que mostra **preço ou diferença de preço**:
OHLC do gráfico, grade de resultados, Detalhes, MAE/MFE, pontos do trade,
textos de sugestão (`core/analytics.py:~223-240`).

### 4. Fronteira única de tradução — `core/ativo.py` (novo) dentro de `run_strategy`

`core/ativo.py` é a única peça que conhece "humana × guardada × relógio":

- `Ficha` — dataclass com os campos do YAML e os derivados: `escala =
  10**price_decimals`, `tick_unid = round(tick_size * escala)`,
  `valor_por_unid = point_value / escala`, `deslocamento_min`,
  `abertura_min` (minuto do pregão da abertura de referência, ou `None`).
- `ficha(symbol) -> Ficha` — carrega via `load_instrument_yaml`.
- `params_para_motor(params, schema, ficha)` — multiplica por `escala` os
  parâmetros marcados com `"unidade": "pontos"` no `params_schema`.
- `perfil_para_motor(perfil, ficha)` — converte pontos (stop, alvo, trailing,
  meta) e horários (janela, fechamento, `sem_entrada`) do perfil, com
  `dataclasses.replace`.
- `instrumento_para_motor(instr, ficha)` — `tick_size = tick_unid`,
  `point_value = valor_por_unid`.
- `hora_para_exibir`, `hora_para_motor`, `preco_para_exibir`.

**Onde roda:** só em `run_strategy` (`core/engine/execution.py:~211-222`), que
é o caminho comum de todos: `optimizer.py`, `wfa_runner.py`,
`candidata_runner.py`, `aleatorio.py:~474`, `ui/callbacks.py:~665`.
`run_strategy`:

1. converte perfil, parâmetros e instrumento numa cópia local;
2. faz o `resample` como hoje;
3. cria **uma cópia** de `bars_tf` e acrescenta `bars["tick"] = tick_unid` e
   `bars["abertura_min"]` — **depois** do `resample`, nunca no dicionário M1
   (o `resample` monta um dicionário novo sem chaves extras,
   `execution.py:~138-145`, e o `aleatorio.py:~470` fatia todas as chaves do
   M1 como vetores);
4. chama `estrategia.signals(bars_tf, params_motor)`;
5. devolve `res.profile` **em unidades humanas** (o original) e `res.instrument`
   já convertido.

Com isso `metrics.py:~38, ~49` e `execution.py:~466, ~496, ~555` não mudam: já
leem o instrumento convertido. A conversão de `stop_dia`/`meta_dia` (dinheiro →
pontos, `execution.py:~497`) passa a usar o `point_value` convertido, mantendo o
`int(round())` do WIN.

**Fora de `run_strategy`, quem lê unidade:**

- `core/tamanho.py:~123-129` (`dia_ruim`, chamado em
  `ui/callbacks_candidata.py:~204`) multiplica o `stop_pontos` **salvo (humano)**
  pelo `point_value` **humano** da ficha — fica como está.
- `ui/callbacks.py:~229` compara `sl_at_entry` (guardada) com
  `perfil.stop_pontos` (humana) e alimenta `analytics.sugestoes`: dividir
  `sl_at_entry` por `escala` antes de comparar.
- `core/portfolio.py:~199`: ver seção 8.

**Garantia do WIN:** com `escala = 1`, `deslocamento = 0`, `abertura_min =
None`, todas as funções são identidade. Um teste afirma isso para cada uma.

### 5. Estratégias

- `signals(bars, params)` mantém a assinatura. `bars` (cópia do `bars_tf`) traz
  `bars["tick"]` e `bars["abertura_min"]` (seção 4). Sem as chaves, valem os
  padrões do WIN (`tick` 5, `abertura_min` `None`).
- `TICK = 5` fixo sai de `rompimento_canal.py` e `rompimento_abertura.py`:
  `folga = folga_ticks * bars.get("tick", 5)`.
- **Abertura de referência** em `rompimento_abertura.py` e
  `rompimento_ema_abertura.py`: a abertura é a primeira barra do pregão cujo
  **minuto de início** é ≥ `abertura_min`. Minuto de início, não o `ts` da barra
  agregada — o `resample` carimba a barra com o `ts` do **fim** do grupo
  (`execution.py:~139`), e no H1 isso faria a barra de 09:00–09:59 NY passar por
  "09:30". Fora do M1, a barra da abertura é a primeira que **começa** em ou
  depois das 09:30; em tempos gráficos que não dividem 09:30 (H1, M7, M9…) ela
  começa um pouco depois — documentado no (?) do parâmetro. Com
  `abertura_min = None` (WIN), é a primeira barra do dia, exatamente como hoje.
- `rompimento_ema_abertura` antes da abertura de referência: nenhum sinal (decisão C2). Com `abertura_min = None` (WIN) não há corte, como hoje.
- Parâmetros em pontos ganham `"unidade": "pontos"` no `params_schema`
  (`filtro_amplitude`, `distancia_abertura`, `amplitude_max` etc.), e continuam
  `"tipo": "int"` (decisão C1).
- `aquecimento` e a checagem de colisão de nomes com o perfil continuam valendo
  (checklist de estratégia nova).

### 6. Faixas de mineração por ativo

`faixas` na ficha sobrepõe `min/max/step/default` do `params_schema` e das faixas
da camada 4 (sliders de alvo/stop/trailing em `controls.py:~233-267`, meta de
varredura em `callbacks.py:~108-114`), por estratégia e parâmetro, **em pontos
humanos inteiros**. Parâmetro sem faixa na ficha usa a do schema. Para o WIN não
há `faixas`, então nada muda.

Um único "schema efetivo" (schema da estratégia + faixas da ficha) é usado em
**todos** os lugares que hoje leem o schema: montagem da grade
(`optimizer.py:~42-98`), `validate` (`strategies/base.py:~77`,
`callbacks.py:~585`) e vizinhança/robustez.

Claude propõe as faixas iniciais a partir do movimento típico de cada micro
(amplitude do pregão e da abertura, medida nos dados importados) e apresenta ao
usuário numa tabela antes de gravar.

> **Como ficou (etapa 4, opção B):** o "schema efetivo" acima **não** foi feito.
> As faixas do YAML só preenchem a tela; motor, `validate` e mineração seguem o
> schema. Ver "Estado depois da etapa 4".

### 7. Perfil de execução por ativo

Os padrões de hoje são do WIN (`ExecutionProfile` em `execution.py:~47-68`,
`_PADRAO_PERFIL` em `optimizer.py:~37`, `DEFAULT_PROFILE` em
`db_manager.py:~215`, padrões da tela em `controls.py:~203-209` e
`callbacks.py:~592, ~790`). Mudanças:

- Ao escolher um ativo na tela, a camada 4 é preenchida com `perfil_padrao` da
  ficha (horários de NY, custos em US$, stop/alvo). Ativo sem `perfil_padrao`
  (WIN) usa os padrões de hoje.
- `execution_profiles` ganha a coluna `symbol` (nula = WIN, os perfis de hoje).
  A lista de perfis salvos mostra só os do ativo em foco; um perfil salvo leva o
  ativo junto.

### 8. Moeda

- `ui/components/cartao.py`: `brl()` vira `dinheiro(valor, moeda="BRL")`;
  `brl` continua existindo como atalho. As chamadas no caminho da pesquisa
  passam a moeda do ativo em foco.
- Rótulos fixos "R$" no caminho da pesquisa (`mine_charts.py:~23`, catálogo,
  ficha, Candidata) passam a vir da moeda.
- `core/candidata.py:~532-545` — texto "no mini índice" do portão de custo passa
  a usar a descrição do ativo.
- `core/portfolio.py` — ao montar ou calcular portfólio com variantes de moedas
  diferentes, recusa com mensagem clara. Variantes da mesma moeda (MES + MNQ)
  funcionam. O `point_value` lido em `portfolio.py:~199` multiplica `points` de
  trades (guardados): passa a usar `valor_por_unid`.

### 9. Importação — `core/importar_lse.py` (novo) + subcomando no `cli.py`

`python cli.py importar-lse --symbol MES ativos_temp/MICROSP500_*.parquet`

1. Lê todas as partes (formato `time/open/high/low/close/volume/trades`).
2. Junta e tira duplicados por minuto (nas sobreposições, exige que sejam
   idênticos; se divergirem, para e avisa).
3. Arredonda OHLC ao tick e multiplica por `escala`.
4. UTC → NY → relógio de pregão (seção 2).
5. Colunas para o formato de `core/ingest.py`: `trades → tick_volume`,
   `volume → real_volume`, `spread` nulo. Chama `ingest_df` com
   `price_decimals=0` (os preços já chegam inteiros em unidades guardadas; é o
   caso em que `ingest.py:~159-167` os aceita como inteiros).
6. **Pregões com falha da fonte** — um pregão é suspeito se tiver:
   - vazio interno de mais de 60 minutos fora da pausa diária, ou
   - começo tardio: primeira barra mais de 60 minutos depois das 18:00 NY.
   - fim precoce: última barra antes das 16:59 NY, exceto entre 12:59 e 13:15
     NY (fechamentos antecipados oficiais da CME, 13:00 e 13:15). O último
     pregão do arquivo fica com a regra do item 7.
   - pregão ausente: dia útil (seg–sex) entre o primeiro e o último pregão do
     arquivo sem nenhuma barra, exceto Ano Novo, Sexta-feira Santa e Natal
     (Natal em sábado vale a sexta anterior; Natal ou Ano Novo em domingo, a segunda seguinte).

   Fechamento antecipado (vazio no final) não conta. Os suspeitos são comparados
   com uma **lista esperada** (na ficha, `pregoes_descartados`, com a data do
   pregão e o motivo): os da lista **não são gravados** (ficam como feriado); um
   suspeito fora da lista faz a importação **parar** e mostrar o pregão para o
   usuário decidir (descartar ou manter, e a lista é atualizada). Lista inicial:
   pregões de 27/02/2020, 28/02/2020, 02/03/2020, 03/03/2020, 21/06/2022 e 12/10/2026 — a primeira
   importação confirma se a regra acha exatamente esses (madrugadas de pouco
   negócio de 2019 e o limite de queda de março/2020 podem aparecer e vão para a
   decisão do usuário).
7. **Último pregão do arquivo:** se o arquivo termina antes das 16:59 NY daquele
   pregão, o pregão não é gravado; o próximo download o completa.
8. Grava em `bars_m1` e no Parquet (`data/parquet/<sym>/`), refaz
   `trading_days` e registra a proveniência e os pregões descartados em
   `ingest_log`, reaproveitando `core/ingest.py`.

Reimportar com arquivos novos acrescenta e confere a sobreposição, como o
caminho do MT5 faz hoje.

`core/rollovers.py`: `"none"` já é aceito. `unexplained_gaps` e
`CONFIRM_GAP_POINTS` (pontos do WIN) não rodam para ativos com `"none"`.

## Fora de escopo

- Operação ao vivo: captura, ordens, papel, corretora, escolha de contrato do
  dia (`contrato_dia`), `SIMBOLO` fixo nos módulos ao vivo.
- Portfólio misto em moedas diferentes (só o bloqueio).
- Plano de operação para ativos da CME (`proximo_dia_util` sem feriados
  americanos) — só quando houver operação.
- ES/NQ (minis), formato antigo de arquivo (`ts`/`symbol`) e outros ativos
  (ouro, moedas): a estrutura serve, mas só MES e MNQ são cadastrados agora.
- Política de rolagem trimestral da CME (a série vem contínua da fonte).

## Garantia do WIN — a "foto"

Antes da etapa 1, grava-se em `tests/fixtures/foto_win/` o resultado atual de:

- cada plano salvo (`planos_operacao`): métricas e lista de trades;
- um backtest de cada estratégia registrada com parâmetros padrão;
- uma mineração pequena (grade de ~20 combinações) de uma estratégia;
- um Walk-Forward curto;
- uma rodada da Candidata (inclui o `aleatorio.py`).

Um teste compara número a número ao fim de **cada etapa**. Se não bater, a
etapa não é entregue.

## Ordem de entrega

Cada etapa termina com testes passando, revisor, teste de mutação e a foto do
WIN batendo.

1. **Fichas e importação** — `mes.yaml`, `mnq.yaml`, `core/ativo.py` (relógio e
   preço), `core/importar_lse.py`, subcomando do `cli.py`; gráfico mostrando
   hora de NY e preço com centavos.
   *Pronto quando:* MES e MNQ aparecem no seletor "ativo", o gráfico abre em
   hora de NY, e o relatório de importação lista os pregões descartados,
   conferidos com o usuário.
2. **Motor e estratégias** — conversão em `run_strategy`, `bars["tick"]`,
   `bars["abertura_min"]`, `TICK` lido do ativo, abertura de referência,
   `stop_dia`/`meta_dia`, perfil padrão por ativo, `execution_profiles.symbol`,
   validação da janela, telas de trades/detalhes em unidades humanas.
   *Pronto quando:* backtest de cada estratégia roda no MES e no MNQ, com os
   horários de NY e preços em pontos na tela.
3. **Moeda** — `dinheiro()`, rótulos, portão de custo da Candidata, bloqueio do
   portfólio misto.
4. **Faixas de mineração** — `faixas` e "schema efetivo" na mineração, na
   camada 4, no Walk-Forward e na Candidata. Claude mede e propõe; o usuário
   aprova.
   *Pronto quando:* mineração, Walk-Forward e Candidata rodam nos micros.

## Testes

- **Foto do WIN** (acima), em toda etapa.
- **Identidade:** cada função de `core/ativo.py` é identidade para a ficha do
  WIN.
- **Sem dupla conversão:** rodar `run_strategy` duas vezes com o mesmo perfil dá
  o mesmo resultado; `res.profile` sai igual ao que entrou.
- **Chaves extras:** `bars["tick"]` chega à estratégia em M1 e em H1; o
  `aleatorio.py` continua fatiando o M1 sem erro.
- **Relógio:** conversões nas duas mudanças de horário de verão americano
  (março e novembro), domingo 18:00 NY caindo na segunda, `time` como início do
  minuto (primeira barra de domingo = 18:00 NY), pregão de fechamento
  antecipado, ida-e-volta `hora_para_motor`/`hora_para_exibir`, janela que
  atravessa a pausa recusada.
- **Telas:** cada tela da lista da seção 2 mostra hora de NY e preço em pontos
  para o MES, e hora de Brasília para o WIN.
- **Importação:** com recortes pequenos dos arquivos reais em
  `tests/fixtures/`: emenda de partes, sobreposição divergente (deve parar),
  ruído de arredondamento, vazio interno > 60 min e começo tardio (suspeitos),
  suspeito fora da lista (para), fechamento antecipado (mantido), último pregão
  parcial (não gravado).
- **Estratégias:** abertura de referência às 09:30 NY no MES em M1 e H1;
  `folga` com tick 0,25; C2 na EMA; WIN idêntico.
- **Moeda:** US$ no MES, R$ no WIN; portfólio misto recusado.

## Riscos

| Risco | Como se cobre |
|-------|---------------|
| Alguma tela esquece a conversão e mostra 6 h a mais ou preço ×100 | Funções únicas em `core/ativo.py`; teste por tela; conferência no app antes de entregar. |
| Conversão aplicada duas vezes (ou nenhuma) | Conversão só em `run_strategy`, em cópia; registros salvos com unidade fixa (regra de unidades); teste de dupla execução. |
| Mudança no motor altera o WIN | Foto do WIN em toda etapa; funções identidade para o WIN. |
| Regra de "pregão com falha" descartar dia bom | Lista esperada; qualquer suspeito fora dela para a importação e vai para o usuário. |
| Arquivos protegidos | Autorizados (D11); mudança mínima, WIN idêntico pela foto. |

## Herança da etapa 1 (para as próximas etapas)

- **Antes de mexer no `run_strategy` (etapa 2):** estender `scripts/foto_win.py` com mineração curta, Walk-Forward curto e rodada de Candidata. Hoje a foto cobre só os planos salvos e um backtest por estratégia.
- **`int(tick_size)` lido do YAML** (vira 0 ou 1 no MES) em: `core/engine/execution.py:466`, `core/ordens.py:553`, `core/papel.py:255`, `core/papel_leitura.py:303,1112`, `core/papel_vivo.py:128`, `captura.py:256`, `ui/callbacks.py:243`, `ui/callbacks_operacao.py:168`. Passar a usar `ativo.ficha(...).tick_unid`.
- **No gráfico do MES/MNQ:** marcadores de trade, barra ao vivo e linha de preço ainda saem em relógio de pregão e em inteiro.
- **Até a etapa 2,** rodar ou minerar no MES/MNQ dá números sem sentido. Não salvar planos neles.
- **Pendências pequenas:**
  - `foto_win.comparar` não trata NaN escalar;
  - `ler_partes` compara floats exatos e ignora `trades`;
  - não há guarda de NaN em preço;
  - o UPDATE de `observacao` roda fora da transação do ingest;
  - faltam testes do gráfico em D1 e em M5/H1 atravessando a pausa.
- **Pregões descartados** (decisão do usuário em 28/10/2026): toda falha da fonte e todo evento atípico real fica fora — MES 43, MNQ 44 (lista nos YAML).

## Estado depois da etapa 2 (29/10/2026)

**Resolvido:**
- A foto do WIN cobre planos, backtests, mineração curta, Walk-Forward curto e Candidata, num banco congelado (`data/foto_win/<nome>.duckdb`). Ela deu idêntica em toda tarefa. Fora do lugar onde foi gravada, só o caminho do arquivo da estratégia difere.
- `run_strategy` converte perfil, parâmetros e instrumento em cópia. O instrumento convertido guarda `_original`, por isso não há dupla conversão. `bars` leva `tick`, `abertura_min` e `inicio_min`.
- As estratégias leem o tick e a abertura de referência do ativo. A EMA de abertura não sinaliza na própria barra de abertura.
- O perfil padrão vem por ativo (`perfil_padrao` no YAML) e é aplicado ao trocar o ativo.
- `janela_valida` recusa uma janela que atravesse a pausa e um fechamento antes do fim ou dentro da pausa. Isso vale também para o WIN.
- Lista de trades, marcadores (também em D1), linhas de stop e alvo, horários, Detalhes e o Walk-Forward mostram hora de NY e pontos.
- O motor usa o tick na unidade guardada. Os outros `int(tick_size)` ficam no papel, no vivo e na captura, que só operam WIN.
- Os planos 5, 6 e 7 foram re-assinados em 29/10, com trades idênticos e backup em `backups/2026-10-29-antes-reassinar/`.

**Fica para depois:**
- **Etapa 3:** os rótulos ainda mostram R$ nos micros, mas os valores estão em US$.
- **Etapa 4:** as faixas de mineração ainda são as do WIN. O stop e o alvo padrão do MES (10/20) e do MNQ (40/80) são provisórios. Planos não devem ser salvos nos micros até lá. *(Feito em 30/10: stop/alvo MES 8/16 e MNQ 45/90, faixas por ativo pela opção B — ver "Estado depois da etapa 4".)*
- `execution_profiles.symbol` não foi feito, porque não existe tela de perfis salvos.
- **Pendências pequenas:**
  - `foto_win.comparar` não trata NaN escalar nem listas de arrays;
  - `hora_para_minuto` quebra com "HH:MM:SS";
  - `hora_do_pregao_para_exibir` ignora os minutos do deslocamento;
  - `metrics` `pontos_liquidos`, `mae_medio` e `mfe_medio` saem na unidade guardada, mas nenhuma tela os lê hoje;
  - a foto grava o caminho absoluto do arquivo da estratégia;
  - continuam as da etapa 1 (`ler_partes`, guarda de NaN em preço, UPDATE de `observacao`).

## Estado depois da etapa 3 (29/10/2026)

**Resolvido:**
- Todo valor em dinheiro da pesquisa sai na moeda do ativo, com formato brasileiro ("US$ 1.234,56", "-US$ 57.056,00"). Isso vale para:
  - backtest, Detalhes, Robustez, gráficos e lista de trades;
  - mineração, que segue o ativo da mineração e não o seletor;
  - Walk-Forward, Candidata e ficha da estratégia;
  - Portfólio e linha de comando.
- A moeda vem de `Ficha.currency`, por `ativo.moeda_de`. Os símbolos estão em `core/ativo.py` e a formatação em `cartao.dinheiro`.
- Os 4 rótulos de dinheiro da camada 4 seguem o ativo. O `controls.py` (protegido) mudou só nesses rótulos, com autorização do usuário.
- **Portfólio:**
  - recusa misturar moedas (`MoedaMista`) ao adicionar a variante e em todas as contas, inclusive quando o plano ativo de uma variante troca de ativo depois;
  - o risco diário usa `point_value / 10**price_decimals`;
  - o capital digitado lê o ponto como milhar ("10.000" = dez mil), mas só quando ele separa grupos de 3 dígitos que não começam por zero ("0.5" e "0.500" continuam decimais).
- **Garantia do WIN:** referência das telas (`scripts/referencia_telas.py` + `tests/dados/telas_win/`), gravada antes da etapa e idêntica no fim. A foto do motor também ficou idêntica.

**Decisões e desvios:**
- **Portão "Aguenta custo maior?":** a frase do mini índice sai fora do BRL, em vez de usar a descrição do ativo como esta spec pedia, porque nos micros a frase seria falsa (decisão do usuário). Hoje a condição é "moeda BRL". Um futuro ativo BRL que não seja o WIN, como o WDO, herdaria a frase.
- **Textos de (?) que ficam em R$:** são de layout fixo, montados uma vez (decisão do usuário):
  - `core/mineracao_stats.py:32` e `:53`;
  - `core/porteira.py:72` e `:190`;
  - `core/tamanho.py:421`.

**Pendências pequenas:**
- `_fmt_capital` não faz ida e volta com 3 casas decimais abaixo de mil;
- risco % "1.500" é lido como 1500 (ambiguidade aceita);
- `abrir_detalhe` do portfólio chama `membros()` várias vezes;
- dois "adicionar" simultâneos de moedas diferentes podem passar, mas as contas recusam depois;
- os placeholders do portfólio misto mostram "(R$)";
- `optimizer` `iniciar`/`esquecer` não zeram o símbolo da mineração;
- a referência das telas compara JSON exato, então um upgrade do plotly exige regravar.

## Estado depois da etapa 4 (30/10/2026)

**Resolvido (opção B):**
- Cada ficha de micro (`mes.yaml`, `mnq.yaml`) ganhou `faixas`: o bloco `comum` (stop, alvo e trailing) e um bloco por estratégia. O `win.yaml` não ganhou `faixas`, e a tela do WIN ficou idêntica à referência gravada antes da etapa (`tests/test_referencia_telas.py`).
- As faixas **só preenchem a tela**: valor, de, passo e até dos campos. O motor, `validate`, a mineração e o Walk-Forward não as conhecem nem as impõem. Quem automatizar a mineração no futuro tem de pegar as faixas de `core.ativo.faixas_do_ativo`, e não do schema.
- O stop e o alvo padrão saíram de provisórios: `perfil_padrao` é MES 8/16 e MNQ 45/90, igual ao `valor` de `faixas.comum` (um teste garante).
- Nos micros, toda caixa com faixa do ativo tem `step=1` (pontos inteiros); o passo da mineração fica só na célula "passo". No WIN, o step de antes.
- Prioridade, chave por chave: mineração carregada > faixa do ativo > schema (ou `PADRAO_C4` na camada 4).

**Tabela aprovada pelo usuário (valor · de–até · passo, em pontos):**

| Campo | Chave | MES | MNQ |
|---|---|---|---|
| Stop | `stop_pontos` | 8 · 3–16 · 1 | 45 · 15–90 · 5 |
| Alvo | `alvo_pontos` | 16 · 6–32 · 2 | 90 · 30–180 · 10 |
| Trailing | `trailing_pontos` | 0 · 0–14 · 2 | 0 · 0–80 · 10 |
| `rompimento_abertura` | `filtro_amplitude` | 0 · 0–40 · 2 | 0 · 0–220 · 10 |
| `rompimento_canal` | `filtro_amplitude` | 0 · 0–80 · 2 | 0 · 0–460 · 10 |
| `rompimento_ema_abertura` | `distancia_abertura` | 0 · 0–80 · 2 | 0 · 0–400 · 10 |
| `adx_direcao` | `amplitude_max` | 25 · 5–80 · 5 | 150 · 25–450 · 25 |

**Comportamento da tela ao trocar o ativo:**
- Sem mineração na tela (nem rodando, nem carregada), a seção de parâmetros e o stop, o alvo e o trailing da camada 4 são refeitos na escala do ativo novo. Isso **zera os valores digitados e as marcas de "minerar"** dos parâmetros.
- Com mineração na tela, parâmetros e stop/alvo/trailing ficam como estão, e a mineração nunca é interrompida nem esquecida por causa do ativo. Horários, custos e slippage da camada 4 trocam assim mesmo, então a tela pode ficar misturada (por exemplo horário de NY com stop do WIN) até a mineração sair da tela e o ativo ser trocado de novo.
- Carregar uma mineração salva usa a escala do ativo **dela** (`symbol` gravado), não a do seletor, também no step e nas células não varridas de stop, alvo e trailing.

**Fora do escopo, ainda:** plano de operação, papel e ao vivo para os ativos da CME — não há corretora para eles.
