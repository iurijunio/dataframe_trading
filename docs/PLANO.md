# Dataframe — plano e arquitetura

Plataforma quantitativa em Python para substituir o MT5 na análise, mineração
e validação visual de estratégias. Foco no Mini Índice (WIN), com a camada de
instrumento preparada para Forex e futuros globais.

Este arquivo é a fonte da verdade sobre **por que** o sistema é como é.
O que mudou e quando fica no [CHANGELOG](../CHANGELOG.md).

---

## 1. Por que banco de dados, e não planilha

O terminal do MT5 serve no máximo ~5 anos de M1 do mini índice. A planilha
exportada hoje começa em março de 2021; a de amanhã já não tem o dia 16 de
março de 2021. Consumir a planilha direto significa operar para sempre numa
**janela deslizante de 5 anos** — a base nunca cresce, só anda.

Com banco, cada exportação é *somada* à anterior. A base vira um arquivo
permanente que ganha um pregão por dia e nunca perde a ponta antiga. Em dois
anos serão 7 anos de histórico; em cinco, 10 — algo que o MT5 nunca vai poder
devolver.

**Consequência que manda no projeto:** se a base é a única cópia de um
histórico que o MT5 não fornece mais, backup deixa de ser higiene e vira
requisito funcional. Três camadas:

| Camada | Papel | Perder significa |
|---|---|---|
| `data/raw/*.csv` | toda exportação, guardada para sempre | história que não volta |
| `data/parquet/` | espelho particionado por ano | reconstruível dos CSVs |
| `data/database.duckdb` | cache de consulta | nada — reconstrói do Parquet |

---

## 2. O que os dados dizem

Medido em `m1-hist-16-03-2026.csv`, não estimado.

| Propriedade | Valor |
|---|---|
| Formato | TSV (separador TAB), header `<DATE> <TIME> …` |
| Período | 2021-03-16 → 2026-03-13 |
| Barras / pregões | 688.224 / 1.247 |
| Duplicatas / barras zeradas | 0 / 0 |
| Escala de preço | inteiro em pontos, 96.155 a 197.760 |
| Fuso | abre 09:00 = abertura da B3 → já é hora de Brasília |

### Amplitude das barras M1 (high − low, em pontos)

| p50 | p75 | p90 | p95 | p99 | p99,9 | máx |
|---|---|---|---|---|---|---|
| 65 | 95 | 135 | 170 | 260 | 480 | 2.105 |

**A volatilidade em pontos não é estacionária.** Amplitude média por ano:
86 (2021) · 88 (2022) · 74 (2023) · 61 (2024) · 74 (2025) · 129 (2026).
O índice saiu de 115 mil para 190 mil pontos e a amplitude acompanhou. Um
stop fixo de 200 pontos era largo em 2024 e é apertado em 2026 — o mesmo
número significa coisas diferentes em anos diferentes. Daí o stop em ATR
existir como alternativa ao stop em pontos.

### Rolagem de contrato

O arquivo é série emendada tipo `WIN$N`. As viradas caem na quarta-feira mais
próxima do dia 15 dos meses pares, com gaps de 2.000 a 4.000 pontos
(`13→18/02/26` +3.780, `14→15/10/25` +3.355, `12→13/08/25` +2.995).

Para day trade puro é inofensivo — nunca se atravessa a noite. Vira problema
real no primeiro instrumento com carrego. 30 datas detectadas por calendário,
29 confirmadas pelo gap medido.

### Duas simplificações que a medição confirmou

**Horário de sessão.** Nenhum dos 1.247 pregões fecha antes das 17:30 — o mais
cedo do histórico inteiro é 17:54. Encerrar às 17:30 é seguro por construção,
sem calendário dinâmico. Dos 108 pregões que abrem depois das 09:00, 103 são
primeiro negócio atrasado e 5 são quartas de carnaval abrindo 13:00.

**Ambiguidade intrabarra.** Para stop e alvo de 200 pontos caírem ambos dentro
do mesmo minuto, a barra precisa ter amplitude ≥ 400 pontos: **1.293 de
688.224 barras, ou 0,19%**. Não virou módulo configurável — virou política
pessimista fixa (stop primeiro) mais um contador no painel. Duas ressalvas:
a taxa é por barra e barras ambíguas são as violentas, então por *trade* é
maior; e não é estável (2026 está em 1,20% contra 0,07% em 2024).

---

## 3. Decisões travadas

| Decisão | Escolha | Por quê |
|---|---|---|
| Perfil operacional | day trade e overnight, flag por instrumento | WIN zera no dia; Forex entra depois com carrego |
| Motor | kernel Numba próprio | ver abaixo |
| Validação | consistência entre períodos + holdout lacrado | ver seção 7 |

### Por que motor próprio e não Vectorbt

Três argumentos, um dos quais caiu:

1. **Licença e manutenção** *(de pé)* — a edição aberta está sob Apache 2.0
   **com Commons Clause** e o desenvolvimento migrou para a versão paga.
2. **Numba basta sozinho** *(de pé)* — 688 mil barras em dezenas de
   milissegundos; não sobra trabalho para uma segunda biblioteca.
3. **Fidelidade intrabarra** *(enfraquecido)* — com stops acima de 200 pontos
   a ambiguidade afeta 0,19% das barras. Era o argumento mais forte e virou o
   mais fraco. Registrado por honestidade.

NautilusTrader volta à mesa quando entrar execução ao vivo, pela paridade
entre backtest e produção.

---

## 4. Stack

| Camada | Escolha | Descartado | Motivo |
|---|---|---|---|
| Armazenamento | DuckDB + Parquet | ClickHouse, ArcticDB | sem ticks, 688 mil linhas dão ~15 MB; servidor seria peso morto |
| Dados | Polars | Pandas como principal | Pandas só na fronteira de libs que o exigem |
| Motor | Numba | Vectorbt, Backtrader | ver seção 3 |
| App | Plotly Dash | Reflex, Panel | Reflex escreve menos código mas não tem Lightweight Charts nem AG Grid |
| Gráfico de preço | TradingView Lightweight Charts v5 (`dash-tvlwc`) | Plotly Candlestick | canvas dedicado a série financeira; Plotly trava |
| Dispersão | Plotly Scattergl / Scatter3d | Datashader, deck.gl | WebGL até ~100k pontos e `clickData` nativo |
| Tabela | `dash-ag-grid` (Community) | `dash_table.DataTable` | scroll virtual e seleção como evento |
| Ingestão | exportação manual do MT5 | API Python no MVP | elimina 3 armadilhas da API e a dependência de Windows com terminal aberto |

### Custo: zero, com dois asteriscos

Tudo roda local. DuckDB, Polars, Optuna, Dash, Plotly: MIT. Numba: BSD.

- **Lightweight Charts** é Apache 2.0 e livre inclusive comercialmente, mas
  **exige atribuição** — link visível para tradingview.com. A opção
  `attributionLogo` da v5 cumpre por padrão; está ligada em `ui/theme.py`.
  Não desligar.
- **AG Grid Community** (MIT) cobre ordenação, filtro, paginação e seleção.
  Enterprise (pago) só adiciona agrupamento, pivot e export Excel estilizado.
  `dash-ag-grid` traz os dois; sem chave, roda Community.

---

## 5. As quatro camadas

A pergunta que separa as camadas: **de quem é essa informação?**

| Camada | Onde vive | Conteúdo | Quem muda |
|---|---|---|---|
| 1 · Instrumento | `configs/instruments/*.yaml` | tick_size, tick_value, moeda, rolagem, `allows_overnight` | propriedade do contrato |
| 2 · Estratégia | `strategies/*.py` | a matemática: recebe barras, devolve sinais | só o código |
| 3 · Parâmetros | `params_schema` da estratégia | períodos, limiares, com default e faixa | você e a mineração |
| 4 · Execução | `ExecutionProfile`, editável na tela | janela, limites, gestão, proteções, custos, dimensionamento | você, na hora |

A camada 4 é a que o PRD original não tinha. Ela é **idêntica para toda
estratégia** e aplicada pelo motor — nenhuma estratégia calcula o próprio
custo ou lembra de encerrar às 17:30.

**O preço de deixar custo editável na tela:** duas minerações rodadas em dias
diferentes podem ter usado custos diferentes. Por isso todo `run` grava um
*retrato completo* do perfil, nunca uma referência.

---

## 6. O motor (`core/engine/kernel.py`)

Regras de execução, explícitas de propósito:

1. Sinal lido na barra `i` só executa na **abertura da barra `i+1`**. A trava
   de look-ahead é do motor, não da estratégia.
2. Ordem a mercado na abertura do candle seguinte: como as barras do
   timeframe são contíguas, a barra após o fechamento de um M15 é a primeira
   do M15 seguinte.
3. Duas travas na entrada: a próxima barra tem que estar na janela **e ser do
   mesmo pregão** — sem a segunda, sinal no fim do dia abriria posição na
   abertura do dia seguinte.
4. **Janela de entrada ≠ horário de fechamento.** Entre um e outro a posição
   segue viva, mas nenhuma nova é aberta.
5. Stop e alvo verificados contra high/low da barra. Ambos na mesma barra →
   assume **stop** (pessimista) e conta em `ambiguous`.
6. **Gap atravessando o nível preenche na abertura**, não no nível. Um stop de
   200 pontos não protege contra um gap de 500.
7. As três proteções (breakeven, stop móvel, trailing) atualizam no **fim da
   barra** e só **apertam** o stop. Usar o high da própria barra para mover o
   stop e depois testar o low dela seria look-ahead intrabarra.
8. Stop, alvo e gatilhos chegam como **arrays por barra**, congelados no valor
   da barra de entrada. É isso que permite stop em ATR sem o kernel saber o
   que é ATR.
9. O kernel devolve trades em **pontos**. Dinheiro, contratos e capital entram
   depois, em `metrics.py` — o que deixa comparar contratos fixos e risco fixo
   sobre o mesmo conjunto de trades.

---

## 7. Mineração: consistência e holdout

> Esta seção corrige o desenho original. Vale ler mesmo se você já leu a
> versão em HTML do plano.

A versão ingênua deste módulo repartia os trades em "dentro" e "fora da
amostra" e reportava IS/OOS lado a lado. **Estava errado.**

Aqui os parâmetros são **fixos**: a mesma combinação roda em todos os folds,
ninguém reotimiza por janela. Chamar as janelas de teste de "fora da amostra"
seria mentira — o otimizador enxerga todas elas ao escolher o vencedor, e as
janelas de treino de um fold se sobrepõem às de teste do anterior. Rotular
isso de OOS produz um número que *parece* validação e não é.

O que de fato existe são duas coisas:

**Consistência.** A combinação ganha dinheiro em quantos dos períodos, ou só
num que puxou a média? É o que os folds medem e o que entra no score. O score
é a **mediana** do fator de recuperação entre períodos, não a soma — prêmio
para quem repete, não para quem acertou uma vez grande.

**Holdout.** Os últimos meses, que nenhuma combinação enxergou. Fica
calculado mas **guardado**: exibir o holdout de mil combinações e escolher a
melhor é destruí-lo. É para uma olhada só, na hora de decidir.

Filtros que descartam combinação antes do ranking:

- mínimo de operações configurável (camada 4);
- presença em ao menos 60% dos períodos — operar em 2 de 12 janelas não é
  estratégia, é coincidência.

**Score robusto.** O score final de cada ponto é a mediana dos vizinhos na
grade. Pico isolado cercado de prejuízo é ruído; mancha contígua é parâmetro.
É por isso que o scatter colore por score robusto e não por lucro.

### Uma escolha de implementação

Cada combinação roda **uma vez** sobre o período inteiro, e os trades são
repartidos depois. Não é atalho — é mais correto: rodar cada fold isolado
zeraria o aquecimento dos indicadores no início de cada janela, coisa que não
acontece ao vivo, onde a média móvel de hoje conhece o mês passado.

---

## 7b. Diagnóstico: do resultado para a decisão

Um painel de métricas diz *se* a estratégia funcionou. Não diz **o que
mexer**. A aba de diagnóstico existe para essa segunda pergunta, e cada
recorte foi escolhido porque tem uma ação do outro lado:

| Recorte | Pergunta | Campo que ele aponta |
|---|---|---|
| Lucro por hora | algum horário só sangra? | janela de entrada |
| Lucro por dia da semana | segunda vale a pena? | dias da semana |
| Lucro por mês / calendário ano×mês | vive de um regime só? | nenhum — é sinal de fragilidade |
| MAE × MFE | o stop está no lugar? | stop, alvo, breakeven |
| Lucro por tempo em posição | trade que arrasta dá prejuízo? | tempo máximo em barras |
| Motivo de saída | quem paga a conta? | stop vs alvo vs fechamento |
| Distribuição | o lucro vem de dois outliers? | nenhum — é sinal de fragilidade |

**Por que a expectativa aparece junto do total.** Um horário com 400 trades a
−R$ 2 cada perde R$ 800; um com 3 trades a −R$ 90 perde R$ 270. O total
manda cortar o primeiro, a expectativa mostra que o segundo é ruído. Os dois
juntos evitam o corte errado.

**MAE e MFE são o par mais acionável.** MAE é o quanto o trade andou contra
antes de fechar; MFE, o quanto andou a favor. Duas leituras saem daí:

- **MAE dos vencedores** — um stop menor que o p95 disso teria matado 5% dos
  seus ganhadores. É o piso do stop.
- **MFE dos perdedores** — quanto de lucro eles chegaram a mostrar antes de
  virar. Mediana alta significa dinheiro escorrendo que breakeven ou trailing
  recuperariam.

O sistema escreve essas leituras em português quando há amostra (≥20 trades
de cada lado) e **nunca afirma o que mudar** — diz o que os dados mostram e
qual campo mexer.

Separação: `core/analytics.py` só calcula, em numpy, sobre os arrays que o
kernel já devolveu — nenhum backtest roda de novo. `ui/components/
analytics_charts.py` só desenha. A tela pode mudar inteira sem encostar na
conta, e a conta é testável sozinha.

### As cinco abas, e por que são cinco

A parede de gráfico é o modo mais fácil de tornar um painel inútil. As abas
existem para que cada uma responda a **uma** pergunta, e para que a pergunta
seja diferente da vizinha:

| Aba | Pergunta | O que se faz com a resposta |
|---|---|---|
| Operações | o que exatamente aconteceu? | conferir trade a trade |
| Tempo | quando a estratégia ganha? | janela, dias da semana |
| **Detalhes** | **o que ajustar?** | **stop, alvo, limites diários** |
| Robustez | quanto disto é sorte? | levar adiante ou descartar |
| Gestão | onde o dinheiro escorre? | breakeven, trailing, tempo máximo |

Os cartões do topo ficaram só com o que se lê **antes** de decidir se a
estratégia merece mais tempo. Sequências, motivo de saída e barras ambíguas
saíram de lá: são diagnóstico, e diagnóstico só interessa depois que o
resultado passou no primeiro olhar.

## 7c. A aba Robustez: quanto disto é sorte

Um backtest bonito é fácil de produzir por acidente. Esta aba é a peneira, e
tudo nela sai dos trades que o kernel já devolveu — nenhum backtest roda de
novo, e por isso ela recalcula a cada execução sem custo perceptível.

| Bloco | O que responde |
|---|---|
| Monte Carlo (reembaralha a ordem) | o drawdown que eu vi foi sorte de ordenação? |
| Maiores mergulhos | por quanto **tempo** eu ficaria no vermelho? |
| Significância (t, p) | a expectativa é distinguível de zero? |
| Teste de runs | as perdas vêm agrupadas? |
| Correlação LR | a curva é uma reta ou um degrau? |
| Concentração | o lucro vem de muitos trades ou de cinco? |
| Ulcer / MAR | como este candidato se ordena contra os outros? |
| Meses positivos | eu aguentaria operar isto? |
| Custo que zera | quanta corretagem a estratégia suporta? |

Duas decisões que valem registro:

**O lucro final não muda quando se reembaralha a ordem — o caminho muda.**
Por isso o Monte Carlo só reporta drawdown e tempo submerso. Se o p95 do
drawdown é o dobro do observado, é para ele que o capital precisa estar
preparado, não para o que aconteceu.

**O teste de significância é bicaudal.** Ele diz que a expectativa difere de
zero, não que ela é boa. A primeira versão mostrava "99,8% de confiança" em
verde numa estratégia que perdia com consistência — uma conclusão sólida,
apresentada como elogio. Agora o sinal é lido junto do p-valor.

Sem scipy de propósito: o p-valor usa `math.erfc`, e para as centenas de
trades desta escala a aproximação normal é indistinguível do t exato.

## 7d. A aba Detalhes: o que ajustar

Robustez pergunta se o resultado é real. Detalhes pergunta **onde mexer**, e
cada bloco aponta para um campo da camada 4 ou para a lógica do sinal.

| Bloco | Leitura que ele entrega | Aponta para |
|---|---|---|
| Sequências | perda puxa perda? | stop diário, pausa após N derrotas |
| Eficiência da operação | o gargalo é a entrada ou a saída? | gatilho vs alvo/trailing |
| Risco por trade | quanto arriscar, com número | contratos, risco por trade |
| Exposição e ritmo | opera pouco e bem, ou muito e mal? | máx. de trades por dia |
| Diagnóstico do motor | quanto depende de suposição | — |

**A média das sequências importa mais que o máximo.** Um recorde de 13 perdas
seguidas assusta; se a média é 1,6, aquilo foi um evento. Se a média for 4, o
drawdown é estrutural e o stop diário deixa de ser exagero.

**"Depois de N perdas" é o cartão que decide pausar o dia.** Ele mostra a
expectativa do próximo trade condicionada a 1, 2 e 3 derrotas em fila. Se
despencar, existe dependência; se ficar igual, as perdas são independentes e
pausar só tira trades bons — a intuição de "hoje está ruim" custa dinheiro.

**Eficiência separa entrada de saída, e é aí que está o valor.** Eficiência da
entrada é quanto do intervalo percorrido pelo trade foi a favor: baixo
significa gatilho adiantado. Eficiência da saída é quanto do pico do trade
sobrou no fechamento: baixo significa lucro devolvido. Mexer no alvo quando o
problema é o gatilho não leva a lugar nenhum.

**VaR e CVaR não são a mesma coisa.** O VaR é a perda que só 5% dos trades
superam; o CVaR é a média desses 5% piores. Dimensionar posição pelo VaR
ignora justamente a cauda que quebra conta.

**Stop furado desconta o slippage configurado.** O motor já embute o slippage
no resultado; sem descontá-lo, *toda* saída por stop apareceria como furada e
a métrica não diria nada. Com o desconto, o que sobra é gap de verdade.

### O (?) de cada métrica

Todo cartão tem um **(?)** com o que a métrica é e que faixa de valores é boa
ou ruim. Número sem referência não sustenta decisão: "Ulcer 8,4" só vira
informação quando se sabe que abaixo de 5 é confortável. O texto mora no
mesmo arquivo do cartão que ele explica — mudar a métrica e esquecer a
explicação fica difícil.

O balão **não** é um `::after` do (?). Dentro de uma aba com rolagem não
existe CSS que faça um pseudo-elemento escapar do recorte de um ancestral com
`overflow`, e ele era cortado nos cartões da primeira linha e nos das
laterais. `ui/assets/dica.js` mantém um único nó preso ao `<body>`, em
`position: fixed`, e o posiciona a cada hover — virando-o para baixo quando
não cabe acima e grudando-o na borda quando não cabe de lado.

### Drawdown: dois percentuais, porque são duas perguntas

`max_drawdown_pct` divide o mergulho pelo **pico** do momento — é o
rebaixamento relativo, o que o MT5 reporta e a base certa para comparar
sistemas. `max_drawdown_pct_capital` divide pelo **capital inicial**, que é a
conta que se faz de cabeça. Eles divergem assim que a curva sobe: R$ 791 são
5,5% de um pico de R$ 14.382 e 7,9% dos R$ 10.000 depositados. O cartão
mostrava só o primeiro com o rótulo do segundo — o tipo de detalhe que faz
duvidar do painel inteiro. Agora mostra os dois, nomeados.

## 8. Restrições técnicas que moldaram o código

**DuckDB aceita vários leitores OU um escritor, nunca os dois.** Isso derrubou
a primeira versão do pool de mineração. Solução em duas partes:

- os workers leem do **espelho Parquet**, nunca do `.duckdb`
  (`db.read_bars_parquet`);
- a gravação passa por `db.connect_write()`, que espera a vez em vez de
  derrubar a mineração inteira.

**Nunca mandar 688 mil candles para o navegador.** A janela visível é agregada
no DuckDB para o timeframe adequado, limitada a `MAX_CANDLES`.

**`COPY … TO ?` com parâmetro ligado não grava nada, em silêncio.** Destino de
`COPY` e caminho de `read_parquet` precisam ser literais — ver `_sql_str`.

---

## 9. Modelo de dados

| Tabela | Chave | Papel |
|---|---|---|
| `bars_m1` | (symbol, ts) | OHLCV, append-only, preço inteiro |
| `instruments` | symbol | camada 1 |
| `trading_days` | (symbol, date) | calendário derivado das barras |
| `rollovers` | (symbol, date) | viradas de contrato |
| `ingest_log` | ingest_id | proveniência de cada carga |
| `execution_profiles` | profile_id | camada 4 salva |
| `mining_runs` / `mining_trials` | run_id | varreduras e resultados |

### A regra de merge

Exportações sucessivas se sobrepõem em anos inteiros. Deduplicar por
`(symbol, ts)` é o fácil. O difícil é o conflito: mesmo timestamp, OHLC
diferente — o MT5 revisa histórico. Se a regra fosse "ignora o que já existe",
a base guardaria a versão velha para sempre sem ninguém saber.

**A exportação mais recente vence, e toda divergência é contada e
registrada.** "Mais recente" é a exportação com a barra mais nova
(`source_max_ts`), com desempate por sha256 — não é a última a ser importada.
Por isso importar A e depois B dá exatamente a mesma tabela que B e depois A.

---

## 10. Estrutura

```
dataframe_trading/
├── data/{raw,parquet}/          arquivo histórico (guardar!)
│   └── database.duckdb          cache reconstruível
├── configs/instruments/*.yaml   camada 1
├── strategies/                  camada 2 + 3
├── core/
│   ├── ingest.py                merge idempotente
│   ├── calendar.py rollovers.py derivadas
│   ├── engine/kernel.py         o laço Numba
│   ├── engine/execution.py      camada 4 → arrays
│   ├── metrics.py               pontos → dinheiro
│   ├── analytics.py             recortes de diagnóstico (sem UI)
│   ├── robustez.py              peneira: quanto disto é sorte
│   ├── detalhes.py              leituras finas: o que ajustar
│   ├── walkforward.py           consistência e holdout
│   └── optimizer.py             pool + escritor único
├── ui/                          Dash
│   ├── assets/dica.js           o balão do (?), preso ao <body>
│   └── components/cartao.py     o molde de cartão dos três painéis
├── docs/PLANO.md                este arquivo
├── docs/METODOLOGIA.md          o processo de pesquisa, passo a passo
└── CHANGELOG.md
```

---

## 11. Estado e próximos passos

**Pronto:** ingestão, motor, dashboard de backtest com cinco abas de
diagnóstico (Operações, Tempo, Detalhes, Robustez, Gestão), mineração com
walk-forward, dispersão com cross-filtering, seletor de estratégia. Toda
métrica com (?) explicando faixa boa e ruim. 147 testes.

**A fazer, em ordem sugerida:**

1. Bugs pequenos de interface acumulados.
2. Sincronização automática pela API do MT5 — cuidado com três armadilhas:
   `Máx. barras no gráfico` do terminal precisa estar em Ilimitado; o símbolo
   precisa de `symbol_select` antes ou a chamada volta vazia sem erro; o fuso
   do servidor pode não ser o de Brasília.
3. Execução ao vivo, em papel antes de dinheiro.
4. Segundo instrumento, para validar a camada 1.
5. Série ajustada por rolagem, para estratégias com carrego.

## 12. Riscos

| Risco | Severidade | Mitigação |
|---|---|---|
| Perda da base histórica | alta | CSVs brutos + Parquet + cópia fora da máquina |
| Overfitting da mineração | alta | consistência entre períodos, holdout lacrado, score de vizinhança, filtros de presença |
| Custos e slippage subestimados | alta | calibrar com notas de corretagem reais antes de confiar em qualquer resultado |
| Merge silencioso de barra revisada | média | exportação mais nova vence, divergência contada |
| Parâmetro em pontos entre regimes | média | variante em ATR e comparação de consistência |
| `dash-tvlwc` é projeto pequeno | média | uso restrito ao que já expõe; plano B é componente React próprio |
