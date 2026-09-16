# Plano: aba Walk-Forward

O terceiro modo da plataforma, ao lado de Backtest e Mineração. Implementa o
Walk-Forward Analysis de Robert Pardo — **reotimizando** a cada janela, que é
o que a mineração de hoje não faz.

> A mineração mede **consistência**: este parâmetro funcionou em vários
> períodos? O WFA mede outra coisa: **o meu processo de escolher parâmetro**
> funciona? O WFA valida o método, não o número.

---

## 1. A decisão que torna isto viável

As 12 configurações somam **135 janelas de otimização**:

    steps = floor((meses_totais − IS) ÷ OOS)

| Config | Steps | | Config | Steps |
|---|---|---|---|---|
| IS:6 / OOS:3 | 18 | | IS:15 / OOS:5 | 9 |
| IS:9 / OOS:3 | 17 | | IS:12 / OOS:6 | 8 |
| IS:12 / OOS:3 | 16 | | IS:20 / OOS:5 | 8 |
| IS:8 / OOS:4 | 13 | | IS:18 / OOS:6 | 7 |
| IS:12 / OOS:4 | 12 | | IS:24 / OOS:6 | 6 |
| IS:16 / OOS:4 | 11 | | **total** | **135** |
| IS:10 / OOS:5 | 10 | | | |

Rodar cada janela como um backtest próprio custaria `135 × espaço`. Com 5 mil
combinações são 675 mil execuções — inviável a cada clique.

**Não é preciso.** Roda-se cada combinação **uma vez** sobre o histórico
inteiro, guardando `entry_ts` e `liquido` por trade, e cada janela vira uma
máscara sobre esses arrays. É a mesma técnica que `core/walkforward.avaliar`
já usa para os folds.

Por que fatiar é correto, e não uma aproximação:

- as janelas caem em fronteiras de **mês**, e os limites diários (máx.
  trades/dia, stop diário) zeram por pregão — nenhum estado atravessa a
  fronteira;
- o trade é atribuído pela **entrada**, então nenhum trade é contado duas vezes;
- o indicador entra na janela **já aquecido**, que é o que aconteceria na
  vida real — rodar a janela isolada é que introduziria um artefato de
  warm-up inexistente na operação.

Custo real: **uma varredura**, a mesma que a Mineração já faz. As 12
configurações viram fatiamento de array.

### Memória

Por combinação guardamos `entry_ts` (int64) e `liquido` (float64). Para 5.000
combinações × 600 trades ≈ **48 MB**. Cabe. Acima de um teto configurável, a
tela avisa e sugere estreitar o espaço.

---

## 2. Decisões travadas (respostas do dia 09/09/2026)

| # | Decisão |
|---|---|
| 1 | Rolante **e** ancorada, as duas disponíveis para comparar |
| 2 | IS/OOS configurável **e** as 12 configurações pré-definidas rodando em lote |
| 3 | Passo travado = OOS (sem sobreposição) |
| 4 | Roda até o corte do holdout; botão **"estender ao holdout"** liga/desliga, re-executável |
| 5 | Função-objetivo embutida na inteligência de seleção (uma escolha só) |
| 6 | Sete inteligências de seleção em `select` — ver seção 4 |
| 7 | Janela IS com poucos trades: **roda e marca** |
| 8 | Critérios de aceite valem **dentro** de cada IS |
| 9 | Camada 4 reotimizável ou travada, por caixa de marcar |
| 10 | Nenhuma combinação aprovada na janela → **fica fora do mercado** |
| 11 | WFE em três métricas lado a lado (e mais, se houver) |
| 12 | WFE **global agregado** principal, **mediana** secundária, nunca a média |
| 13 | Portões: OOS>0 · **≥70%** janelas positivas · **WFE ≥70%** · ≥300 trades OOS · DD OOS ≤1,5× IS |
| 14 | Matriz das 12 configurações, com foco em performance |
| 15 | Curva de comparação: parâmetro travado × WFA |
| 16 | Terceiro modo no topo |
| 17 | Seletor de estratégia + lista abaixo |
| 18 | Salvar no banco, com opção de excluir |
| 19 | Botão "mandar vencedora para o Backtest" |
| 20 | **Símbolo carregado do instrumento** — a plataforma não é só do mini índice |
| 21 | "Walk-forward" da Mineração renomeado para "Consistência entre períodos" |

---

## 3. As tarefas

Cada uma termina com algo que dá para **ver na tela** e um teste que a
sustenta. As revisões e a documentação entram no fim de cada fase, não só no
fim de tudo.

### Fase 0 — Fundação

| # | Tarefa | O que se vê |
|---|---|---|
| ~~0.1~~ | ~~Renomear "Walk-forward" → "Consistência entre períodos"~~ | **feito** |
| ~~0.2~~ | ~~Desamarrar o símbolo~~ | **feito** — seletor de ativo no topo |
| ~~0.3~~ | ~~`core/wfa.py`~~ | **feito** — 50 testes |
| ~~0.4~~ | ~~Cache de trades por combinação~~ | **feito** — `core/wfa_runner.py`, 1,9 s / 0,4 MB na #40 |

### Fase 1 — O modo e a lista

| # | Tarefa | O que se vê |
|---|---|---|
| ~~1.1~~ | ~~Terceiro modo no topo~~ | **feito** |
| ~~1.2~~ | ~~Excluir mineração da lista~~ | **feito** — dois cliques para confirmar |

### Fase 2 — Uma configuração ponta a ponta

| # | Tarefa | O que se vê |
|---|---|---|
| ~~2.1~~ | ~~Executar + Detalhamento Técnico + DEPLOY~~ | **feito** |
| ~~2.2~~ | ~~Curva OOS trade a trade + KPIs~~ | **feito** |

### Fase 3 — A matriz

| # | Tarefa | O que se vê |
|---|---|---|
| ~~3.1~~ | ~~Matriz WFM com heatmap e seleção de linha~~ | **feito** |
| ~~3.2~~ | ~~Select de inteligência re-executando~~ | **feito** — as sete recalculam a matriz inteira |
| ~~3.3~~ | ~~Rolante × ancorada~~ | **feito** — duas colunas na mesma linha |
| ~~3.4~~ | ~~Matriz em abas: Consenso + uma por inteligência~~ | **feito** — seis portões por célula; ordem consenso → WFE mediano → pior WFE; métricas compartilhadas (0,87 s as sete) |

### Fase 4 — As leituras

| # | Tarefa | O que se vê |
|---|---|---|
| ~~4.1~~ | ~~Fita das janelas IS/OOS~~ | **feito** |
| ~~4.2~~ | ~~Drift de parâmetros + volatilidade~~ | **feito** |
| ~~4.3~~ | ~~Eficiência temporal OOS~~ | **feito** — mensal, dia da semana, hora |
| ~~4.4~~ | ~~Curva de comparação: parâmetro travado × WFA~~ | **feito** |
| ~~4.5~~ | ~~Portões da WFA~~ | **feito** — selo + 6 portões |
| ~~4.6~~ | ~~Holdout: botão estender~~ | **feito** — instantâneo, sem varredura nova |

### Fase 5 — Persistência e integração

| # | Tarefa | O que se vê |
|---|---|---|
| ~~5.1~~ | ~~Salvar e excluir WFA no banco~~ | **feito** — tabela `wfa_runs` |
| ~~5.2~~ | ~~Ver a vencedora~~ | **feito** — sub-aba "Parâmetros da vencedora": tabela com faixa minerada e alerta de borda (o backtest no período inteiro saiu — era curva otimizada) |
| ~~5.3~~ | ~~Tira-teima: os trades OOS linha a linha~~ | **feito** — com entrada, saída, custo e capital |
| ~~5.4~~ | ~~Cartões OOS unificados com os do Backtest~~ | **feito** — `metrics.resumo` + `stats_cards.cartoes` |
| ~~5.4a~~ | ~~Ficha completa da vencedora, dinâmica~~ | **feito** — `ficha.py` + `catalogo.py`: estratégia pelo schema, execução pelo `ExecutionProfile` |
| ~~5.4b~~ | ~~Progresso da varredura, travas e véu na matriz~~ | **feito** — sem laço de callbacks; teste de ciclo no app inteiro |
| 5.5 | Botão "editar faixas" (decisão da pergunta 7) | pendente — usa o espaço gravado por padrão; editar avisa que a matriz deixa de ser comparável com a mineração de origem |
| 5.6 | Camada 4 reotimizável ou travada, por caixa de marcar (decisão 9) | pendente |

### Fase 6 — Fechamento

| # | Tarefa |
|---|---|
| 6.1 | Revisão de código, de trading e de estatística (agentes) |
| 6.2 | `METODOLOGIA.md`, `PLANO.md`, `README.md`, `CHANGELOG.md` |

---

## 4. As sete inteligências de seleção

Quem escolhe a combinação vencedora dentro de cada janela IS. Todas rodam
**depois** do filtro de critérios de aceite; se nenhuma combinação passa, a
estratégia fica fora do mercado naquele OOS.

| Inteligência | Como escolhe | Viés |
|---|---|---|
| **Moda (Estabilidade)** | moda de cada parâmetro no decil superior por fator de recuperação, ancorada na combinação existente mais próxima | acha o valor que mais se **repete** — o centro da parte densa do platô |
| **Sharpe (Eficiência)** | melhor Sharpe da janela (retorno diário anualizado) | métrica ajustada ao risco, como Pardo pede — mas é escolha de **pico** |
| **Centroid (Platô) Média** | média de cada parâmetro no decil superior, ancorada | centro geométrico; uma boa combinação distante **arrasta** o centroide |
| **Centroid (Platô) Mediana** | idem, com mediana | imune ao outlier distante — **o padrão sugerido** |
| **Estabilidade de Drawdown** | menor **Ulcer Index** entre as aprovadas | pune profundidade E tempo submerso: a curva mais fácil de operar |
| **Probabilidade do Alpha** | maior estatística t (`média ÷ (desvio/√n)`); sem variação, t = 0 | prefere o edge mais distinguível de ruído; o √n pune a combinação de poucos trades |
| **Platô Pessimista** | quantil 25% do fator de recuperação dos vizinhos na grade (raio 5% dos valores de cada parâmetro, por posição), contando vizinhos reprovados | um pico cercado de prejuízo perde para um ponto bom cercado de pontos bons; não cai no vale entre duas ilhas |
| **Conselho de Notáveis** | as outras sete votam; vence quem tiver mais indicações; **qualquer empate no topo** → centroide mediano dos indicados, ancorado entre eles | quando a região é platô, elas concordam. **A discordância entre elas é informação** — a tela mostra quantas votaram na vencedora |

Regras comuns, desde a revisão de 15/09/2026: candidatas precisam passar nos
**critérios da mineração** trazidos para o tamanho da janela (trades e lucro
∝ f, drawdown ∝ f^0,3, fator de recuperação ∝ f^0,7 — expoente medido por
Monte Carlo —, PF igual; f = meses da janela ÷ meses da mineração) e ter **≥ 30 trades**; o decil tem no
mínimo 3 elementos; Moda e Centroides ancoram **dentro do decil**; empates
decidem pelo lucro; o Sharpe conta os pregões sem trade como zero.

### Sobre o Edge Ratio

O E-Ratio original (Curtis Faith) mede MFE e MAE normalizados por ATR num
**horizonte fixo** de N barras. O ponto dele é medir o SINAL, independente da
saída. O nosso MFE/MAE é do trade inteiro, já contaminado pela regra de saída
— um trade estopado cedo tem MFE truncado.

Chamar `MFE ÷ MAE` de Edge Ratio seria dar a um número o nome de outro. Fica
como tarefa opcional: o kernel passa a registrar MFE/MAE em 10, 20 e 50
barras, o que destrava o E-Ratio de verdade. Até lá, `MFE ÷ MAE` aparece com
o nome real.

## 5. As contas

As fórmulas escritas antes de codar ficaram desatualizadas com a revisão — a
escadinha passou a ser alinhada pelo fim, o portão de repetição passou a ser
por semestre, o drift passou a ser medido contra a faixa minerada, e assim por
diante. Para não manter duas versões, **as contas vivem num lugar só**:
[CALCULOS-WFA.md](CALCULOS-WFA.md), com a fórmula, o porquê e um exemplo real
da #40 para cada número da aba.

---

## 6. Referências

- Pardo, *The Evaluation and Optimization of Trading Strategies* (2008), 2ª ed.
  de *Design, Testing and Optimization of Trading Systems* (1992)
- Rolante preferida; **IS = 4 a 6× o OOS**; **10 a 30** janelas; OOS entre
  10% e 40% de cada segmento
- Mínimos de amostra: ~120 trades no primeiro IS, ~30 por OOS
- WFE > 50% é o limiar clássico da literatura — aqui usamos **70%**, por
  decisão do operador
- Pardo sobre a escolha dentro do IS: priorizar métrica ajustada ao risco
  sobre retorno cru, e **procurar platôs**, não picos
