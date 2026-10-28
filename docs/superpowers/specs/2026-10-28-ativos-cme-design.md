# Ativos da CME na pesquisa (MES e MNQ) — desenho

Data: 28/10/2026 · Branch: `new-strategies` · Status: aprovado em conversa, aguardando revisão do documento

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

## Os dados (London Strategic Edge)

Arquivos em `ativos_temp/` (fora do git), baixados pelo usuário:

- `MICROSP500_futures_1m_2019-05-05_2019-09-14.parquet` + `..._2019-09-14_2026-10-28.parquet`
- `MICRONASDAQ100_futures_1m_2019-01-05_2019-09-20.parquet` + `..._2019-09-20_2026-10-28.parquet`

O site limita cada download a ~2,5 milhões de linhas; por isso cada ativo vem em
partes que se complementam. Conferido:

- Colunas: `time` (timestamp com fuso, **UTC**), `open`, `high`, `low`, `close`,
  `volume` (double), `trades` (inteiro). Os arquivos antigos do ES/NQ têm outro
  formato (`ts`, `symbol`, sem `trades`) — o importador aceita os dois.
- Candles de 1 minuto, de 05/05/2019 (lançamento dos micros) até 28/10/2026;
  ~2,6 milhões por ativo. Só existem minutos com negócio (minuto sem negócio não
  vem).
- Preço **sem ajuste** (série contínua com o preço real de cada contrato, como o
  `WIN$N`). A opção "Adjusted for splits" do site não altera futuros.
- Partes emendam sem falha (MNQ: 1.352 minutos sobrepostos, idênticos; MES: uma
  parte acaba na sexta e a outra começa no domingo).
- Ruído de ponto flutuante (7665,4999 em vez de 7665,50): arredondar ao tick.
- Volume nunca zero.
- **Buracos da fonte** (iguais nos dois micros): de 02/03/2020 até 03/03/2020
  09:40 NY; 21/06/2022 (~272 barras); 12/10/2026 (~265 barras).
- Dias curtos **reais** (não são buraco): feriados, meio pregão (Black Friday,
  véspera de Natal), funeral do Carter (09/01/2025), paradas por queda em março
  de 2020. Saltos grandes reais: 12/01/2023 e 14/10/2026, às 08:30 NY (dado
  econômico).

## Arquitetura

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
faixas: { ... }            # faixas de mineracao por parametro (ver secao 6)
custos_padrao: { corretagem: 0.60, emolumentos: 0.0, slippage_ticks: 1 }
```

`tick_size` passa a aceitar fração **na ficha**; dentro do sistema tudo continua
inteiro (ver 3). Todo leitor de `tick_size` e `point_value` que multiplica ou
compara com **diferença de preço guardada** passa a receber os valores em
unidades guardadas (`tick_unid`: WIN 5, MES 25; `valor_por_unid`: WIN 0,20,
MES 0,05), via `core/ativo.py` (seção 4). Leitores mapeados:
`core/engine/execution.py:~466, ~496, ~555`, `core/metrics.py:~38, ~49`,
`core/portfolio.py:~199`, `core/tamanho.py` (incluindo `trava_do_indice`, que
usa o preço do índice), `core/robustez.py:~449`, `ui/callbacks.py:~243`. O plano
confere a lista completa com `grep`. `tick_value` (dinheiro por tick) não muda de
unidade.

A tabela `instruments` ganha as colunas novas (`sessao_abertura`,
`abertura_referencia`) com `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, nulas para
o WIN. `faixas` e `custos_padrao` são lidos direto do YAML
(`load_instrument_yaml`), não vão para o banco.

### 2. Relógio de pregão (caminho A)

Na importação, cada horário americano é convertido assim:

```
UTC  →  hora de Nova York (com horário de verão, via zoneinfo)
     →  + deslocamento fixo = 24:00 − sessao_abertura  (18:00 → +6 h)
     →  gravado como timestamp sem fuso em bars_m1.ts
```

Resultado: o pregão de 18:00 (NY, véspera) até 17:00 (NY) vira **00:00–23:00 da
mesma data**. Todo o código que hoje deriva o dia de `ts.astype("datetime64[D]")`
ou `CAST(ts AS DATE)` (~25 lugares: limite diário, fechamento forçado, janela,
`dias_semana`, calendário, Walk-Forward, métricas, gráficos por dia) passa a
enxergar a **data do pregão** sem nenhuma mudança. A noite de domingo cai na
segunda (correto na CME). Velas H1–H4 alinham com o início do pregão.

O deslocamento é fixo em relação a Nova York; o horário de verão já foi resolvido
na conversão UTC→NY. Para o WIN o deslocamento é zero (campo ausente), então
nada muda.

**A regra de ouro:** o relógio de pregão nunca aparece para o usuário. Toda tela
que mostra ou recebe hora passa por duas funções do módulo `core/ativo.py`:

- `hora_para_exibir(ts, ficha)` — relógio de pregão → hora de NY (subtrai o
  deslocamento; a data mostrada é a do calendário de NY, não a do pregão).
- `hora_para_motor("09:30", ficha)` — hora de NY digitada → relógio de pregão
  (`09:30` → `15:30`).

Lugares que exibem/recebem hora (lista mínima, a conferir no plano):

- gráfico de candles e marcas de trade (`ui/data.py`, `ui/components/charts.py`);
- listas de trades e detalhes (`core/detalhes.py`, catálogo, ficha);
- histograma por hora (`core/analytics.py`);
- campos de horário do perfil — início/fim da janela, fechamento, `sem_entrada`
  (`ui/components/controls.py`, `ui/callbacks.py`) e seus padrões
  `09:00/17:00/17:30`, que passam a vir da ficha do ativo;
- `catalogo.py` filtro por hora.

### 3. Preço com centavos

`bars_m1` continua `BIGINT`. O preço é guardado como `preço × 10^price_decimals`
(MES: 5432,25 → 543225). Para o WIN `price_decimals = 0`, nada muda.

Dentro do motor tudo trabalha em **unidades guardadas** (inteiras). As unidades
humanas (pontos, com fração) só existem na tela, na ficha e no que fica salvo:
os parâmetros e o perfil salvos guardam o que o usuário digitou (ex.: stop de
12,5 pontos), e a conversão acontece numa fronteira única (seção 4).

Consequência: `stop_pontos`, `alvo_pontos`, `trailing_pontos` e parâmetros de
estratégia em pontos passam a aceitar fração **na tela** quando o ativo tem
decimais; o motor recebe inteiros em unidades guardadas.

### 4. Fronteira única de tradução — `core/ativo.py` (novo)

Um módulo pequeno, a única peça que conhece "unidade humana × unidade guardada ×
relógio":

- `Ficha` — dataclass com os campos do YAML e os derivados: `escala =
  10**price_decimals`, `tick_unid = round(tick_size * escala)`,
  `valor_por_unid = point_value / escala`, `deslocamento_min`.
- `ficha(symbol) -> Ficha` — carrega via `load_instrument_yaml`.
- `params_para_motor(params, schema, ficha)` — multiplica por `escala` os
  parâmetros marcados com `"unidade": "pontos"` no `params_schema` da estratégia,
  e arredonda ao tick.
- `perfil_para_motor(perfil, ficha)` — converte pontos (stop, alvo, trailing) e
  horários (janela, fechamento, `sem_entrada`) do perfil.
- `hora_para_exibir`, `hora_para_motor`, `preco_para_exibir`.

Ponto de entrada no motor: `core/engine/execution.py`, na chamada única
`estrategia.signals(bars_tf, params)` (~linha 219) e na montagem do
`ExecutionProfile`. A conversão de `stop_dia`/`meta_dia` (dinheiro → pontos,
`execution.py:~497`) passa a usar `valor_por_unid`, mantendo o `int(round())` do
WIN.

**Garantia do WIN:** com `escala = 1` e `deslocamento = 0`, todas as funções são
identidade. Um teste afirma isso para cada uma.

### 5. Estratégias

- `signals(bars, params)` continua com a mesma assinatura. O motor passa a
  incluir no dicionário `bars` duas chaves: `bars["tick"]` (tick em unidades
  guardadas) e `bars["abertura_min"]` (minuto do pregão da abertura de
  referência, ou `None`).
- `TICK = 5` fixo sai de `rompimento_canal.py` e `rompimento_abertura.py`
  (arquivo protegido — autorizado pelo usuário): `folga = folga_ticks *
  bars.get("tick", 5)`.
- **Abertura de referência:** `rompimento_abertura.py` e
  `rompimento_ema_abertura.py` passam a contar a abertura a partir da primeira
  barra do pregão com minuto ≥ `abertura_min`. Com `abertura_min = None` (WIN),
  é a primeira barra do dia, exatamente como hoje. O range da abertura do MES
  começa às 09:30 NY; o limite diário continua começando às 18:00.
- Parâmetros em pontos ganham `"unidade": "pontos"` no `params_schema`
  (`filtro_amplitude`, `distancia_abertura`, `amplitude_max` etc.).
- `aquecimento` e a checagem de colisão de nomes com o perfil continuam valendo
  (checklist de estratégia nova).

### 6. Faixas de mineração por ativo

`faixas` na ficha sobrepõe `min/max/step/default` do `params_schema` e das faixas
da camada 4 (sliders de alvo/stop/trailing em `controls.py`, meta de varredura em
`callbacks.py`), por estratégia e parâmetro, **em pontos humanos**. Parâmetro sem
faixa na ficha usa a do schema. Para o WIN não há `faixas`, então nada muda.

Claude propõe as faixas iniciais a partir do movimento típico de cada micro
(amplitude do pregão e da abertura, medida nos dados importados) e apresenta ao
usuário numa tabela antes de gravar.

### 7. Moeda

- `ui/components/cartao.py`: `brl()` vira `dinheiro(valor, moeda="BRL")`;
  `brl` continua existindo como atalho para não mexer em quem não precisa. As
  ~30 chamadas no caminho da pesquisa passam a moeda do ativo em foco.
- Rótulos fixos "R$" no caminho da pesquisa (`mine_charts.py`, catálogo, ficha,
  Candidata) passam a vir da moeda.
- `core/candidata.py` — texto "no mini índice" do portão de custo passa a usar a
  descrição do ativo.
- `core/portfolio.py` — ao montar ou calcular portfólio com variantes de moedas
  diferentes, recusa com mensagem clara. Variantes da mesma moeda (MES + MNQ)
  funcionam; para ponto padrão, ativo ausente continua usando R$1.

### 8. Importação — `core/importar_lse.py` (novo) + subcomando no `cli.py`

`python cli.py importar-lse --symbol MES ativos_temp/MICROSP500_*.parquet`

1. Lê todas as partes; aceita os dois formatos (`time` ou `ts`).
2. Junta e tira duplicados por minuto (nas sobreposições, exige que sejam
   idênticos; se divergirem, para e avisa).
3. Arredonda OHLC ao tick e converte para unidades guardadas.
4. UTC → NY → relógio de pregão (seção 2).
5. **Pregões com falha da fonte:** um pregão com um vazio interno de mais de
   60 minutos fora da pausa diária (17:00–18:00 NY) é tratado como falha e
   **não é gravado** — fica como se fosse feriado, e o backtest não opera em
   cima de dado faltando. Fechamentos antecipados (vazio no final) e paradas
   curtas não contam. A lista de pregões descartados sai no relatório da
   importação e fica gravada em `ingest_log`. Esperado: os de 02/03 e 03/03/2020,
   21/06/2022 e 12/10/2026.
6. Grava em `bars_m1` e no Parquet (`data/parquet/<sym>/`), refaz
   `trading_days` e registra a proveniência em `ingest_log`, reaproveitando o
   que `core/ingest.py` já faz.
7. O volume é guardado como inteiro; `trades` é descartado (o banco não tem
   coluna para ele e nenhuma estratégia usa).

Reimportar com arquivos novos (próximo download) acrescenta e confere a
sobreposição, como o caminho do MT5 faz hoje.

`core/rollovers.py`: `"none"` já é aceito. `unexplained_gaps` e
`CONFIRM_GAP_POINTS` (pontos do WIN) não rodam para ativos com `"none"`.

## Fora de escopo

- Operação ao vivo: captura, ordens, papel, corretora, escolha de contrato do
  dia (`contrato_dia`), `SIMBOLO` fixo nos módulos ao vivo.
- Portfólio misto em moedas diferentes (só o bloqueio).
- Plano de operação para ativos da CME (`proximo_dia_util` sem feriados
  americanos) — só quando houver operação.
- ES/NQ (minis) e outros ativos (ouro, moedas): a estrutura serve, mas só MES e
  MNQ são cadastrados agora.
- Política de rolagem trimestral da CME (a série vem contínua da fonte).

## Garantia do WIN — a "foto"

Antes da etapa 1, grava-se em `tests/fixtures/foto_win/` (ou equivalente) o
resultado atual de:

- cada plano salvo (`planos_operacao`): métricas e lista de trades;
- um backtest de cada estratégia registrada com parâmetros padrão;
- uma mineração pequena (grade de ~20 combinações) de uma estratégia;
- um Walk-Forward curto.

Um teste compara número a número ao fim de **cada etapa**. Se não bater, a
etapa não é entregue.

## Ordem de entrega

Cada etapa termina com testes passando, revisor, teste de mutação e a foto do
WIN batendo.

1. **Fichas e importação** — `mes.yaml`, `mnq.yaml`, `core/ativo.py` (parte de
   relógio e preço), `core/importar_lse.py`, subcomando do `cli.py`, colunas
   novas em `instruments`; gráfico mostrando hora de NY e preço com centavos.
   *Pronto quando:* MES e MNQ aparecem no seletor "ativo", o gráfico abre em
   hora de NY, e o relatório de importação lista os pregões descartados
   esperados.
2. **Motor e estratégias** — `params_para_motor`, `perfil_para_motor`,
   `bars["tick"]`, `bars["abertura_min"]`, `TICK` lido do ativo, abertura de
   referência, `stop_dia`/`meta_dia`, padrões de horário vindos da ficha.
   *Pronto quando:* backtest de cada estratégia roda no MES e no MNQ, com os
   horários de NY na tela.
3. **Moeda** — `dinheiro()`, rótulos, portão de custo da Candidata, bloqueio do
   portfólio misto.
4. **Faixas de mineração** — `faixas` na ficha, aplicadas na mineração, na
   camada 4, no Walk-Forward e na Candidata. Claude mede e propõe; o usuário
   aprova.
   *Pronto quando:* mineração, Walk-Forward e Candidata rodam nos micros.

## Testes

- **Foto do WIN** (acima), em toda etapa.
- **Identidade:** cada função de `core/ativo.py` é identidade para a ficha do
  WIN.
- **Relógio:** conversões nas duas mudanças de horário de verão americano
  (março e novembro), domingo 18:00 NY caindo na segunda, pregão de fechamento
  antecipado, e ida-e-volta `hora_para_motor`/`hora_para_exibir`.
- **Telas:** cada tela da lista da seção 2 mostra hora de NY para o MES e hora
  de Brasília para o WIN.
- **Importação:** com recortes pequenos dos arquivos reais em
  `tests/fixtures/`: emenda de partes, sobreposição divergente (deve parar),
  ruído de arredondamento, pregão com vazio > 60 min (descartado), fechamento
  antecipado (mantido), os dois formatos de coluna.
- **Estratégias:** abertura de referência às 09:30 NY no MES; `folga` com tick
  0,25; WIN idêntico.
- **Moeda:** US$ no MES, R$ no WIN; portfólio misto recusado.

## Riscos

| Risco | Como se cobre |
|-------|---------------|
| Alguma tela esquece a conversão e mostra 6 h a mais | Funções únicas em `core/ativo.py`; teste por tela; conferência no app antes de entregar. |
| Conversão de pontos aplicada duas vezes (ou nenhuma) | Fronteira única no motor; parâmetros salvos sempre em pontos humanos; teste de ida e volta. |
| Mudança no motor altera o WIN | Foto do WIN em toda etapa; funções identidade para o WIN. |
| Regra de "pregão com falha" descartar dia bom | Relatório lista cada descarte com o motivo; o usuário confere na primeira importação. |
| Arquivo protegido `rompimento_abertura.py` | Autorizado; mudança mínima (tick e abertura de referência), WIN idêntico pela foto. |
