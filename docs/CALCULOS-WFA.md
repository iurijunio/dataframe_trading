# As contas do Walk-Forward

Como cada número da aba Walk-Forward é calculado, **na ordem em que acontece**,
com o porquê de cada escolha e um exemplo real da mineração #40
(`rompimento_canal`, WIN$N, M15, só compra, base 16/03/2021 → corte do holdout
14/09/2025, critérios padrão).

Onde está no código: `core/wfa.py` (tudo o que é conta), `core/wfa_runner.py`
(a varredura), `core/metrics.py` (métricas de trade compartilhadas com o
Backtest), `ui/callbacks.py` `_criterios_wfa` (de onde vêm os critérios).

> Este arquivo descreve o que o código **faz hoje**. Quando uma conta mudar, ele
> muda junto — o histórico de por que mudou fica no `CHANGELOG.md`.

---

## 1. A varredura — uma vez só

Cada combinação do espaço minerado roda **um backtest sobre a base inteira**. De
cada trade guarda-se entrada, saída, resultado líquido e custo (32 bytes por
trade). Toda janela depois é um **recorte** desses arrays — nenhum backtest novo.

Recortar é exato, e não aproximação: as janelas caem em fronteira de mês, os
limites diários zeram por pregão e o indicador entra na janela já aquecido, como
na operação real.

**O trade pertence à janela da sua ENTRADA** — nenhum trade é contado duas vezes.

Limite de memória: 400 MB. Se a varredura passar disso, ela **aborta** e não
entrega cache nenhum. Uma varredura interrompida também não é entregue.

---

## 2. A escadinha de janelas

```
total  = meses entre o início da base e o fim (corte do holdout, ou fim da base)
steps  = ⌊(total − IS) ÷ OOS⌋
sobra  = (total − IS) mod OOS

rolante:   IS_início = início + sobra + k·OOS       IS_fim = IS_início + IS
ancorada:  IS_início = início (sempre)             IS_fim = início + sobra + IS + k·OOS
           OOS_início = IS_fim                      OOS_fim = OOS_início + OOS
```

- **Rolante**: a janela de otimização anda junto, sempre do mesmo tamanho —
  esquece o passado remoto e se adapta a regime (preferida do Pardo).
- **Ancorada**: começa sempre no primeiro dia e cresce — usa toda a história.
- **Alinhada pelo FIM**: a sobra da divisão fica no começo. Assim o último OOS
  termina no fim da base e o **DEPLOY** (a otimização "para operar hoje", um step
  a mais sem OOS) usa os meses mais recentes.
- As bordas caem no início do mês.

**Exemplo #40, IS 12 / OOS 6**: 54 meses, 7 janelas + DEPLOY, sobra 0.

---

## 3. Métricas de uma janela IS

Para cada combinação, sobre os trades com entrada dentro da janela:

| métrica | conta |
|---|---|
| trades | quantidade |
| lucro | Σ líquido |
| profit factor | Σ ganhos ÷ Σ perdas (sem perda: ∞ se houve ganho, 0 se não) |
| drawdown | maior queda da curva `capital + Σ acumulado`, **começando no capital** |
| fator de recuperação (FR) | lucro ÷ drawdown (sem drawdown: ∞ se lucrou, 0 se não) |
| Sharpe | ver seção 6 |
| Ulcer | √ média(queda percentual do topo²), medido trade a trade |
| t | média ÷ (desvio ÷ √n); **0** sem variação (desvio ≤ 1e-9 × \|média\|) |

O "sem variação" tem tolerância porque trades de valor idêntico (35 × R$ 36,56)
dão desvio de 7×10⁻¹⁵ por arredondamento, e não zero — e o t saía 3×10¹⁶.

---

## 4. Critérios de aceite dentro da janela

Uma combinação só é **candidata** numa janela IS se passar em todos os critérios.
Eles vêm **da mineração salva** (gravados ao salvar); minerações antigas, como a
#40, usam os padrões da tela de Critérios. O resumo da tela diz qual foi usado
("critérios da mineração" / "critérios padrão").

Os critérios da mineração julgam o **período inteiro** (anos). A janela tem
meses — por isso os de contagem são **escalados** pelo tamanho da janela:

```
f = meses da janela IS ÷ meses da mineração        (no máximo 1)
```

| critério | na janela | por quê |
|---|---|---|
| **trades** | `max(30, ⌈trades × f⌉)` | contagem cresce com o tempo; abaixo de 30 a métrica é ruído |
| **lucro** | `lucro × f` | o piso em R$ encolhe junto com o tempo |
| **drawdown máximo** | `dd × f^0,3` | ver abaixo |
| **fator de recuperação** | `fr × f^0,7` | ver abaixo |
| **profit factor** | igual | é razão entre duas somas que crescem juntas |

"Janelas positivas" e "mediana por período" não entram: dentro de uma janela
não existem folds para medir isso.

### Por que f^0,3 e f^0,7

O fator de recuperação é **lucro ÷ pior drawdown**, e os dois crescem com o tempo
em ritmos diferentes:

- o **lucro** cresce proporcional ao tempo (f¹);
- o **pior drawdown** cresce **bem mais devagar**: o pior mergulho de 5 anos não
  é 5× o de 1 ano, porque uma estratégia com expectativa positiva tende a sair do
  buraco antes de ele ficar muito fundo. Em horizontes longos o máximo cresce
  perto de log t (Magdon-Ismail, 2004);
- logo `FR ∝ f¹ ÷ f^0,3 = f^0,7`.

O expoente foi **medido por Monte Carlo** com parâmetros do WIN (média R$ 5–20,
desvio R$ 150 por trade, ~1,5 trade/dia, 6 a 60 meses): ficou entre 0,6 e 0,75.
A raiz (0,5) reprovava metade das combinações que estavam exatamente no limiar; o
linear (1,0) aprovava demais.

**Exemplo #40** (54 meses, padrões: 300 trades, PF 1,25, FR 2,0, DD R$ 2.500,
lucro 0):

| janela IS | trades | FR | DD máx | PF | lucro |
|---|---|---|---|---|---|
| 6 meses | 34 | 0,43 | R$ 1.293 | 1,25 | 0 |
| 12 meses | 67 | 0,70 | R$ 1.592 | 1,25 | 0 |
| 24 meses | 134 | 1,13 | R$ 1.960 | 1,25 | 0 |

### Fora do mercado

Se **nenhuma** combinação passa nos critérios de uma janela IS, a estratégia **não
opera** no OOS seguinte. Não é por poucos trades no OOS — é o regime daquela
janela sendo ruim para a estratégia inteira. Na #40 (IS 6 / OOS 3), as quatro
janelas fora do mercado foram todas assim: as 41 combinações com PF abaixo de
1,25, e numa delas todas perdendo dinheiro.

Ficar fora **não é punido**: não conta como semestre negativo, e o lucro por mês
divide pelo calendário (os meses passaram do mesmo jeito). O alerta "janelas fora
do mercado" dos portões avisa quando isso acontece.

---

## 5. As inteligências de seleção

Entre as candidatas da janela, uma inteligência escolhe **uma** combinação:

| inteligência | escolhe |
|---|---|
| Moda | moda de cada parâmetro no **topo** por FR; ancorada no topo |
| Sharpe | maior Sharpe (desempate: lucro) |
| Centroid Média | média de cada parâmetro no topo; ancorada no topo |
| Centroid Mediana | mediana de cada parâmetro no topo; ancorada no topo |
| Drawdown | menor Ulcer (desempate: maior lucro) |
| Alpha | maior t (desempate: lucro) |
| Platô Pessimista | maior quantil 25% do FR na vizinhança da grade |
| Conselho | as outras 7 votam; empate no topo → centroide mediano dos indicados |

- **Topo** = os 10% melhores por FR (desempate: lucro), **nunca menos de 3**. FR
  infinito vale o maior FR finito da janela.
- **Ancorar** = achar a combinação real mais próxima do ponto calculado, **só
  dentro do topo**, com distância normalizada pela amplitude de cada parâmetro
  (empate: maior FR).
- **Platô Pessimista**: coordenada = posição do valor na lista ordenada de cada
  parâmetro; vizinhança = caixa de raio `max(1, 5% dos valores)` em cada eixo
  (parâmetro de texto só compara iguais); nota = quantil 25% do FR dos vizinhos,
  **inclusive os reprovados**; precisa de pelo menos `max(3, metade da caixa)`
  vizinhos, senão cai na Centroid Mediana.
- **Conselho**: o vencedor sempre tem pelo menos um voto.

---

## 6. O resultado fora da amostra

A combinação escolhida em cada janela é aplicada nos meses seguintes (OOS). Os
trechos OOS colados formam a **curva fora da amostra** — em nenhum ponto dela o
otimizador tinha visto o dado que estava operando.

### WFE

```
WFE_janela = (lucro_OOS ÷ anos_OOS) ÷ (lucro_IS ÷ anos_IS)      indefinido se lucro_IS ≤ 0
WFE_global = (Σ lucro_OOS ÷ Σ anos_OOS) ÷ (Σ lucro_IS ÷ Σ anos_IS)
```

Somas só das janelas **operadas** (fora do mercado sai dos dois lados: não há IS
para degradar). O **global** é o principal; a **mediana** das janelas é o
secundário; a média nunca aparece (uma janela com IS pequeno produz 300% e
contamina a média).

- **Dispersão** = desvio dos WFE por janela ÷ |mediana|. Com janelas de 3–6 meses
  valores de 1 a 5 são normais mesmo sem degradação nenhuma — serve para comparar
  configurações entre si, não contra um número fixo.
- **WFE>50/70/90** = % das janelas com WFE acima de cada nível.

**Exemplo #40, IS 12 / OOS 6, Centroid Mediana**: WFE por janela
41% · 206% · 99% · 73% · 10% · 232% · 100%; global **96,4%**; dispersão 0,83.

### Lucro por mês

- **lucro/mês** = lucro OOS ÷ meses de **calendário** do OOS (inclui os meses fora
  do mercado).
- **lucro/mês comum** (matriz) = lucro OOS a partir do **OOS que começa mais
  tarde** entre as 12 configurações, ÷ meses desse período comum. Cada
  configuração começa a operar numa data (IS 6/OOS 3 em 2021-09, IS 24/OOS 6 em
  2023-03); comparar períodos diferentes compara mercados diferentes.

### Sharpe e Sortino

```
retorno_dia = Σ líquido dos trades do pregão ÷ capital
pregões     = dias úteis do período (os sem trade entram como ZERO)
Sharpe      = média(retorno_dia) ÷ desvio(retorno_dia) × √252
Sortino     = média(retorno_dia) ÷ √(Σ min(retorno_dia, 0)² ÷ pregões) × √252
```

Contar só os dias com trade inflava quem opera pouco (4 trades num ano davam
Sharpe na casa das centenas). Feriados da B3 não são descontados (~3,5% dos dias,
erro de ~1,7% no Sharpe). No Backtest o dia é o da **saída** do trade; na escolha
dentro do IS, o da entrada — em day trade dão o mesmo.

---

## 7. Os seis portões

| portão | regra | tipo |
|---|---|---|
| lucro OOS total | > 0 | crítico |
| **semestres OOS positivos** | ≥ 70% | crítico |
| WFE global | ≥ 70% | crítico |
| trades OOS somados | ≥ 300 | crítico |
| drawdown OOS ÷ pior drawdown IS | ≤ 1,5× | alerta |
| janelas fora do mercado | = 0 | alerta |

Um crítico reprovado → **reprovado**. Só alertas → **aprovado com ressalva**.

### Semestres positivos

O teste de repetição é medido em **semestres civis** (jan–jun, jul–dez) da curva
OOS, e não por janela:

- positivo = Σ resultado dos trades com entrada no semestre > 0;
- só entram semestres **inteiramente** cobertos pelo OOS;
- semestre **todo fora do mercado** não conta (nem a favor nem contra);
- sem nenhum semestre inteiro, o portão usa a contagem por janela.

Por quê: uma janela OOS de 3 meses tem ~25 trades e fecha negativa por puro acaso
muito mais vezes que uma de 6 meses com ~60. Simulando uma estratégia com o edge
da #40 e **sem degradação nenhuma**, o portão por janela a reprovava em 42% das
vezes com IS 6/OOS 3 e em 12% com IS 12/OOS 6 — o portão estava medindo o tamanho
da janela, não a estratégia. O semestre é a mesma régua para as 12 configurações.
A contagem por janela continua na matriz como informação.

**Exemplo #40, Centroid Mediana**:

| config | semestres + | janelas + | lucro/mês | lucro/mês comum | veredito |
|---|---|---|---|---|---|
| IS 6 / OOS 3 | 86% (7) | 58% | 38 | 53 | reprovado* |
| IS 12 / OOS 4 | 83% (6) | 67% | 84 | 74 | com ressalva |
| IS 10 / OOS 5 | 67% (6) | 86% | 68 | 55 | reprovado |
| IS 12 / OOS 6 | 83% (6) | 100% | 101 | 107 | aprovado |
| IS 18 / OOS 6 | 80% (5) | 100% | 109 | 104 | aprovado |

\* reprovado por outro portão, não mais pelas janelas.

---

## 8. A matriz e o Consenso

A matriz roda as **12 configurações** × **8 inteligências**, cada uma com a
escadinha rolante e a ancorada, e aplica os seis portões em cada célula. As
métricas de cada janela são calculadas **uma vez** e divididas entre as
inteligências; o Conselho reaproveita as escolhas das votantes. Guardada por
varredura e estado do holdout.

**Consenso** (só a rolante), por configuração:

```
aprovam      = quantas das 7 votantes (todas menos o Conselho) não reprovaram
WFE mediano  = mediana dos WFE globais das 7
pior WFE     = mínimo dos WFE das 7
ordem        = aprovam ↓, WFE mediano ↓, pior WFE ↓
```

O maior WFE aparece só como informação: escolher o pico de 84 variantes é
escolher a mais sortuda. O Conselho não conta porque é a votação das outras.

---

## 9. A curva e a faixa das combinações fixas

Atrás da curva do walk-forward, a **faixa** mostra o que **todas** as combinações
da mineração teriam feito **sem reotimizar**, no mesmo intervalo:

```
para cada combinação: capital + Σ acumulado dos trades por dia útil (pela entrada)
faixa clara  = percentis 10 e 90 dessas curvas, dia a dia
faixa escura = percentis 25 e 75
pontilhada   = mediana
pNN          = % das combinações fixas que terminaram ABAIXO do walk-forward
```

Reotimizar só está acrescentando algo se a curva sai **por cima** da faixa. Na
#40 (IS 12 / OOS 6, Centroid Mediana) o walk-forward terminou em **p34**: 66% das
41 combinações fixas fizeram mais no mesmo período (mediana R$ 4.430 contra
R$ 4.240). A versão anterior mostrava uma combinação só — a escolhida na primeira
janela — e sugeria o contrário.

---

## 10. Deriva dos parâmetros (drift)

```
volatilidade = desvio dos valores escolhidos por janela ÷ faixa minerada (máx − mín)
percorreu    = (maior − menor valor escolhido) ÷ faixa minerada
estável ≤ 5% · em transição ≤ 15% · instável > 15%
```

Referência: um valor sorteado ao acaso em toda a faixa dá ~29%. Pela faixa, e não
pela média, porque a média depende de onde fica o zero da escala (um parâmetro de
1.000 a 1.010 pareceria estável pulando de ponta a ponta). Sem faixa minerada, cai
na régua antiga (desvio ÷ média, 5% / 20%).

**Exemplo #40**: `periodo_canal` escolhido 75 · 63 · 60 · 60 · 58 · 46 · 46 · 64
numa faixa 40→80 → desvio **24%** da faixa, **instável**, percorreu 72%.

---

## 11. Eficiência temporal

Sobre os **meses de calendário** das janelas OOS (os sem trade entram com zero):

- **meses positivos** = % dos meses com resultado > 0;
- **curva mensal** começa no **zero** (um primeiro mês negativo já é mergulho);
- **tempo médio de recuperação** = média, em meses, dos mergulhos que **já**
  voltaram ao topo;
- **maior período sem novo topo** = o pior mergulho, em curso ou não;
- **em curso** = meses do mergulho que ainda não se recuperou.

---

## 12. O que é gravado ao salvar

- `wfa_runs`: a decisão (mineração, IS, OOS, inteligência, holdout), o agregado,
  o veredito, as janelas e o DEPLOY;
- `wfa_trades`: os trades da curva OOS, reconstruídos na hora de salvar com um
  backtest por janela — idênticos aos do cache (conferido em 32 cenários).

Tudo numa transação: se o processo morrer no meio, nada fica gravado pela metade.
