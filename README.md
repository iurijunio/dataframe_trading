# Dataframe

Plataforma quantitativa em Python para análise, mineração e validação visual
de estratégias — começando pelo Mini Índice (WIN).

**Status: MVP concluído** — F0 dados · F1 motor · F2 dashboard · F3 mineração ·
F4 dispersão.

```bash
.venv\Scripts\python.exe ui\app.py     # http://127.0.0.1:8050
```

| Documento | O que responde |
|---|---|
| este README | como usar |
| [docs/PLANO.md](docs/PLANO.md) | por que é assim: decisões, alternativas descartadas, licenças, riscos |
| [docs/METODOLOGIA.md](docs/METODOLOGIA.md) | o processo: da ideia ao dinheiro real |
| [docs/PLANO-WFA.md](docs/PLANO-WFA.md) | o plano e as decisões da aba Walk-Forward |
| [docs/CALCULOS-WFA.md](docs/CALCULOS-WFA.md) | **como cada número do Walk-Forward é calculado**, com exemplos da #40 |
| [CHANGELOG.md](CHANGELOG.md) | o que mudou e quando |

## Por que banco, e não planilha

O MT5 serve no máximo ~5 anos de M1 do mini índice. A planilha exportada hoje
começa em março/2021; a de amanhã já não tem 16/03/2021. Consumir a planilha
direto significa operar para sempre numa **janela deslizante**.

Somando cada exportação à anterior, a base vira um **arquivo permanente** que
ganha um pregão por dia e nunca perde a ponta antiga. Em dois anos são 7 anos
de histórico; em cinco, 10 — algo que o MT5 não vai poder devolver.

Consequência direta: **backup não é higiene, é requisito funcional.** Os CSVs
em `data/raw/` e o espelho em `data/parquet/` são a única cópia. O
`database.duckdb` é cache descartável — `cli.py verify` prova isso.

## Uso

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

.venv\Scripts\python.exe cli.py init
.venv\Scripts\python.exe cli.py ingest caminho\para\export-mt5.csv
.venv\Scripts\python.exe cli.py status
.venv\Scripts\python.exe cli.py verify
```

`ingest` é um **merge**, não uma carga: pode rodar quantas vezes quiser, com
arquivos que se sobrepõem, em qualquer ordem. Numa divergência (mesmo
timestamp, OHLC diferente — o MT5 revisa histórico) vence a exportação mais
recente, e a divergência é contada e registrada em `ingest_log` com exemplos.
Nunca é engolida em silêncio.

## As quatro camadas

A pergunta que separa as camadas é: **de quem é essa informação?**

| | Onde vive | Conteúdo |
|---|---|---|
| 1 · Instrumento | `configs/instruments/*.yaml` | tick, valor do ponto, política de rolagem |
| 2 · Estratégia | `strategies/*.py` | a matemática: recebe barras, devolve sinais |
| 3 · Parâmetros | `configs/strategies/*.json` | períodos, distâncias — com default e range |
| 4 · Execução | tabela `execution_profiles`, **editável na tela** | tempo gráfico, janela, gestão, proteções, limites diários, custos, dimensionamento |

A camada 4 é idêntica para toda estratégia e aplicada pelo motor. Nenhuma
estratégia calcula o próprio custo nem lembra de encerrar às 17:30, pelo mesmo
motivo que nenhuma sabe o valor do tick. Stop e alvo moram aqui também: no MQL5
são `input` como qualquer outro, mas quanto arriscar e como proteger é decisão
do operador, não da matemática do setup.

O que a camada 4 controla hoje:

| Bloco | Campos |
|---|---|
| Tempo gráfico | M1 a H4 — sinais no timeframe, execução sempre em M1 |
| Janela | entradas de/até, **fechar posições às**, dias da semana, direção |
| Gestão | alvo e stop, cada um em **pontos fixos ou múltiplo de ATR** (período, multiplicador) |
| Proteções | breakeven e stop móvel em **% do alvo**, trailing em pontos, tempo máximo |
| Limites diários | ganho e perda máx. **R$ por contrato**, máx. operações, máx. prejuízos |
| Custos | corretagem, emolumentos, slippage — por contrato e por ponta |
| Posição | contratos fixos ou risco fixo, capital inicial |
| Mineração | mínimo de operações para a combinação valer |

Ao bater qualquer limite diário, o dia para: nenhuma nova entrada é aberta até
o pregão seguinte. O contador `dias_bloqueados` mostra quantas vezes isso ocorreu.

**Trava obrigatória:** todo `run` grava um *retrato* completo do perfil de
execução que o gerou, nunca uma referência. Sem isso, duas minerações feitas
em dias diferentes poderiam ter usado custos diferentes e a tabela de
resultados viraria uma comparação entre coisas incomparáveis, sem aviso.

## O que a base já sabe

Medido no histórico de 16/03/2021 a 13/03/2026 (688.224 barras, 1.247 pregões):

- **Nenhum pregão fecha antes das 17:54.** Encerrar às 17:30 é seguro por
  construção — não precisa de calendário dinâmico no motor.
- **Amplitude M1:** mediana 65 pontos, p99 = 260, p99,9 = 480. Para stop e alvo
  de 200 pontos caírem ambos dentro do mesmo minuto, a barra precisa de ≥400
  pontos: 1.293 barras, ou **0,19%**. A ambiguidade intrabarra é um contador no
  painel, não um módulo.
- **Volatilidade em pontos não é estacionária:** média anual 86 · 88 · 74 · 61 ·
  74 · 129. Parâmetro em pontos fixos otimizado nos 5 anos mistura regimes.

## Rolagem de contrato

`WIN$N` é série emendada: na virada o preço salta milhares de pontos sem que
nada tenha acontecido. A detecção é por **calendário** (quarta-feira mais
próxima do dia 15 dos meses pares), não por tamanho de gap — 29 das 30
detectadas são confirmadas pelo gap medido, e a única que não é (14/04/2021,
gap de apenas 480 pontos) mostra por que gap sozinho não serve como critério.

O inverso importa mais: os maiores gaps do histórico **não** são rolagem.
31/10/2022 (−4.045, dia seguinte ao 2º turno), 03/10/2022 (+3.455, 1º turno),
26/11/2021 (−3.335, Ômicron), 05/08/2024 (−2.985, carry trade do iene). Detectar
rolagem por gap teria apagado do backtest os maiores movimentos reais da amostra.

`core/rollovers.unexplained_gaps()` lista esses dias para inspeção, sem gravá-los.

## O motor

```bash
.venv\Scripts\python.exe backtest.py
.venv\Scripts\python.exe backtest.py --tf M15 --media-rapida 5 --media-lenta 40
.venv\Scripts\python.exe backtest.py --stop-tipo atr --stop-atr-mult 2 --breakeven 50
```

Regras de execução, todas no `core/engine/kernel.py` e todas com teste:

1. **Look-ahead é travado pelo motor.** Sinal lido na barra `i` só executa na
   abertura de `i+1`. Nenhuma estratégia pode burlar por engano.
2. **Stop e alvo na mesma barra:** o dado OHLC não diz qual veio primeiro.
   Assume o stop (pessimista) e conta a barra em `barras_ambiguas`.
3. **Gap atravessando o nível preenche na abertura**, não no nível. Um stop de
   200 pontos não protege contra um gap de 500.
4. **Breakeven e trailing atualizam no fim da barra.** Usar o high da própria
   barra para mover o stop e depois testar o low dela seria look-ahead intrabarra.
5. **Slippage sempre contra.** Stop e alvo são ancorados no preço *efetivo* de
   entrada, então saída no nível cobra uma ponta e saída a mercado cobra duas.
6. **O kernel devolve pontos.** Dinheiro, contratos e custo entram em
   `metrics.py`, depois — por isso os dois modos de dimensionamento saem do
   mesmo conjunto de trades.

Desempenho medido nas 688.224 barras: **54 ms por backtest completo de 5 anos**.
10.000 combinações levam 9 minutos num núcleo, ~30 segundos em 20.

## Estrutura

```
core/schema.sql            as 6 tabelas
core/db_manager.py         conexão, instrumentos, perfis, espelho Parquet
core/ingest.py             merge com resolução determinística de conflito
core/calendar.py           trading_days derivado das barras
core/rollovers.py          viradas de contrato por calendário B3
core/engine/kernel.py      o laço compilado — fonte única da verdade
core/engine/execution.py   camada 4 + timeframe, ATR, sessão
core/metrics.py            pontos viram dinheiro aqui, e só aqui
core/analytics.py          recortes de diagnóstico (hora, dia, MAE/MFE)
core/robustez.py           peneira do candidato: quanto disto é sorte
core/detalhes.py           leituras finas: sequências, eficiência, risco, ritmo
core/mineracao_stats.py    a região varrida: distribuição e critérios de aceite
core/porteira.py           o veredito sobre a varredura inteira + SQN
strategies/base.py         contrato Strategy / Signals + espaço de busca
strategies/setup_cruzamento.py
ui/app.py                  dashboard (Dash + Lightweight Charts + AG Grid)
ui/theme.py                paleta neon, num lugar só
ui/components/             controles, cartões, gráficos, tabela
ui/components/cartao.py    molde do cartão e do (?) — usado pelos três painéis
ui/assets/dica.js          o balão do (?), preso ao <body> para não ser cortado
cli.py                     init · ingest · derive · status · verify
backtest.py                backtest único pela linha de comando
core/walkforward.py        consistência entre períodos e holdout
core/optimizer.py          pool de processos + escritor único
ui/components/scatter.py   dispersão e cross-filtering
docs/PLANO.md              decisões e razões
docs/METODOLOGIA.md        o processo: da ideia ao dinheiro real
docs/PLANO-WFA.md          plano e decisões do Walk-Forward
docs/CALCULOS-WFA.md       as contas do Walk-Forward, uma a uma
tests/                     179 testes
```

## O dashboard

```bash
.venv\Scripts\python.exe ui\app.py     # http://127.0.0.1:8050
```

A tela reflete as quatro camadas: a barra lateral separa visualmente *Parâmetros*
(camada 3, o que a mineração vai varrer) de *Execução* (camada 4, do operador).
Mudar horário, custo ou dimensionamento e rodar de novo não toca em uma linha
de estratégia.

- **Preço** — TradingView Lightweight Charts com candles, volume em painel
  próprio, setas de compra e venda e, no trade selecionado, as linhas de
  entrada, stop, alvo e saída.
- **Capital** — equity acima, underwater drawdown abaixo, no mesmo eixo de tempo.
- **Trades** — AG Grid com scroll virtual. **Clicar numa linha leva o gráfico
  até aquele trade**, trocando o timeframe para M1 automaticamente.

O **Diagnóstico** fica em cinco abas, cada uma respondendo a uma pergunta
diferente — parede de gráfico é o jeito mais fácil de tornar um painel
inútil:

| Aba | Pergunta | O que se faz com a resposta |
|---|---|---|
| Operações | o que exatamente aconteceu? | conferir trade a trade |
| Tempo | quando a estratégia ganha? | janela de entrada, dias da semana |
| Detalhes | o que ajustar? | stop, alvo, limites diários |
| Robustez | quanto disto é sorte? | levar adiante ou descartar |
| Gestão | onde o dinheiro escorre? | breakeven, trailing, tempo máximo |

Os cartões do topo ficam só com o que se lê **antes** de decidir se a
estratégia merece mais tempo. **Cada métrica tem um (?)** dizendo o que ela é
e que valores são bons ou ruins: número sem faixa de referência não sustenta
decisão — "Ulcer 8,4" só vira informação quando se sabe que abaixo de 5 é
confortável.

Duas leituras que costumam surpreender:

- **"Depois de N perdas"** (aba Detalhes) mostra a expectativa do próximo
  trade condicionada a 1, 2 e 3 derrotas em fila. Se despencar, perda puxa
  perda e pausar o dia melhora o resultado; se ficar igual, as perdas são
  independentes e pausar só tira trade bom.
- **Eficiência da entrada vs da saída** separa o culpado: entrada baixa é
  gatilho adiantado; saída baixa é lucro devolvido. Mexer no alvo quando o
  problema é o gatilho não leva a lugar nenhum.

A curva de capital ocupa a faixa larga do topo porque é a leitura principal; o
gráfico de candles divide a faixa de baixo com a lista de trades, já que serve
para conferir se a estratégia está fazendo o que deveria, não para operar.

Campos mineráveis trazem embaixo a faixa de otimização no formato da tela do
MT5 — **de / passo / até**, com um interruptor por parâmetro. O rodapé do painel
mostra o tamanho do espaço de busca em tempo real, antes de você gastar o
processamento da F3 nele.

O gráfico nunca recebe as 688 mil barras: a janela visível é agregada no DuckDB
para o timeframe que couber em 4.000 candles (`ui/data.py`). Uma janela de 5 dias
vira M5; um trade isolado vira M1.

O logo da TradingView no canto do gráfico é **requisito da licença** Apache 2.0
da Lightweight Charts, não enfeite. Não desligar.

## Tempo gráfico

A estratégia lê barras do timeframe escolhido, mas **a execução roda sempre em
M1** — o que preserva a precisão intrabarra do stop mesmo operando em H1.

Um sinal fechado numa barra de 15 minutos é conhecido no minuto do fechamento
dela e executa na barra seguinte. Como as barras do timeframe são contíguas,
essa barra seguinte é a **primeira do próximo candle de 15** — ou seja, ordem
a mercado na abertura do candle novo, que é o comportamento de um robô de
verdade. As duas leituras são o mesmo instante.

## Mineração

Marque "minerar" nos parâmetros, ajuste `de / passo / até`, configure os folds
e clique em **Minerar**. A tabela aparece enquanto a varredura corre.

**A tabela ordena por score robusto, não por lucro.** Robusto é a mediana dos
vizinhos na grade: um pico isolado cercado de prejuízo é ruído, um platô é
estratégia. O score de cada ponto é a **mediana do fator de recuperação entre
os períodos**, não a soma — prêmio para quem repete, não para quem acertou
uma vez grande.

**O holdout não aparece na tabela, de propósito.** Exibir o holdout de mil
combinações e escolher a melhor é o mesmo que não ter holdout. Ele é
calculado, gravado em `mining_trials.holdout_lucro` e reservado para uma
olhada só, na hora de decidir.

Uma correção conceitual que vale registrar: aqui os parâmetros são **fixos** —
a mesma combinação roda em todos os folds, ninguém reotimiza por janela.
Chamar as janelas de teste de "fora da amostra" seria mentira, porque o
otimizador enxerga todas elas ao escolher o vencedor. O que os folds medem de
verdade é **consistência entre períodos** ("lucrou em 9 de 12"), e é isso que
a coluna diz. Fora da amostra mesmo, só o holdout.

Filtros que descartam uma combinação: menos operações que o mínimo, ou
presença em menos de 60% dos períodos — operar em 2 de 12 janelas não é
estratégia, é coincidência.

## Dispersão e cross-filtering

A nuvem mostra o que a tabela não mostra: **onde fica a região boa**. Um ponto
verde cercado de vermelho é sorte; uma mancha verde contígua é parâmetro
robusto. Por isso a cor padrão é o score robusto, e não o lucro — e por isso a
nuvem carrega as combinações ruins junto: sem o vermelho em volta não dá para
saber se o verde é região ou acidente.

Eixos X, Y e Z opcional escolhidos entre os parâmetros que de fato variaram na
varredura. Cor em `RdYlGn`, tamanho do ponto pelo número de trades.

**Um caminho, dois gatilhos.** Clicar num ponto da nuvem ou numa linha da
tabela faz a mesma coisa: carrega a combinação nos campos e dispara o backtest
único. Os cartões, a curva de capital e a lista de trades se atualizam; daí um
clique num trade abre o gráfico de candles naquela operação. Da região boa no
scatter até o trade desenhado no candle, sem digitar nada.

## MVP concluído

F0 dados · F1 motor · F2 dashboard · F3 mineração · F4 dispersão.

Pós-MVP, em ordem: sincronização automática pela API do MT5, execução ao vivo
em papel, segundo instrumento para validar a camada de metadados, série
ajustada por rolagem para estratégias com carrego.
