# Metodologia

O processo, não o código. `PLANO.md` explica por que a plataforma é como é;
aqui está **o que fazer com ela, em que ordem, e o que cada passo decide**.

O fluxo abaixo é o da metodologia Data N Quant / DQ Labs. A plataforma foi
construída para servi-lo — cada tela existe por causa de um passo daqui.

---

## O fluxo

| # | Passo | A pergunta que ele responde |
|---|---|---|
| 1 | Criar estratégia | a regra está implementada como eu pensei? |
| 2 | Busca de clusters | onde, no espaço de parâmetros, existe região fértil? |
| 3 | Pegar um cluster | qual região vou investigar a fundo? |
| 4 | Mineração de parâmetros | como o resultado varia dentro dessa região? |
| 5 | Mineração de resultados | a **distribuição** dos resultados é sadia ou é um pico? |
| 6 | Otimização e validação | o resultado se repete entre períodos? |
| 7 | Critério de validação | passa nos números mínimos que eu defini? |
| 8 | Salvar mineração | vira candidata — só o que passou |
| 9 | Carregar a mineração salva | recuperar a estratégia por completo |
| 10 | Testes de robustez | quanto disto sobrevive fora do cenário perfeito? |
| 11 | Incubação | funciona em dado que nunca existiu quando otimizei? |
| 12 | Portfólio de baixa correlação | esta soma com as outras ou é mais do mesmo? |
| 13 | Demo | a infraestrutura aguenta? |
| 14 | Contrato mínimo | eu aguento? |
| 15 | Live | operação |

**Fase 1 — construir** (1–3) · **Fase 2 — minerar** (4–7) ·
**Fase 3 — selecionar** (8–10) · **Fase 4 — provar** (11–15)

---

## Fase 1 — Construir

### 1. Criar estratégia

Traduzir a ideia em regra de entrada e saída, e **conferir visualmente** que
ela dispara onde deveria. Esta conferência não é opcional: a maior parte dos
backtests bons demais é bug, não descoberta.

**Na Dataframe:** aba Operações com a lista de trades; clicar numa linha leva
o gráfico de candles até aquela operação, com as linhas de entrada, stop,
alvo e saída desenhadas.

**O que olhar:** dez trades escolhidos a esmo. Se todos os dez estiverem onde
você esperava, a regra está implementada.

### 2. Busca de clusters

Varredura ampla e grossa, para achar **onde** o espaço é fértil. Passo largo,
faixa inteira. Não interessa o melhor resultado aqui — interessa o mapa.

**Na Dataframe:** dispersão com X, Y e cor por métrica. A leitura é
geográfica: manchas contínuas de cor boa são clusters; pontos isolados
brilhantes no meio de ruído são armadilha.

### 3. Pegar um cluster

Escolher a **região**, não o ponto. O centro de uma mancha larga vale mais
que o pico de uma agulha, mesmo com número pior — porque o mercado vai andar,
e a agulha não sobrevive a isso.

**Na Dataframe:** clicar na região da dispersão carrega aquela combinação nos
campos, e daí você estreita as faixas em torno dela.

---

## Fase 2 — Minerar

### 4. Mineração de parâmetros

Agora sim: passo fino, faixa estreita, dentro do cluster escolhido. É aqui
que se rodam centenas de varreduras — **isso é o trabalho**, não desperdício.
Encontrar cluster bom de primeira não acontece.

**Na Dataframe:** a mineração roda em processos paralelos, com barra de
progresso, e pode ser parada a qualquer momento. O resultado fica em memória:
nada vai para o banco até você mandar salvar (passo 8).

### 5. Mineração de resultados

O passo que separa quem tem método de quem tem sorte. Depois de varrer, você
não olha o melhor resultado — você olha a **distribuição de todos eles**.

Três leituras, e as três decidem coisas diferentes:

- **Quantos por cento das combinações são lucrativas?** Acima de 70% você
  achou um platô: qualquer ponto ali dentro funciona, e escolher o "melhor" é
  detalhe. Abaixo de 30% você achou ruído com uma sorte dentro. O portão
  crítico da Porteira corta em 60%.
- **Onde está a massa?** Uma distribuição com o corpo à direita do zero é
  região boa. Uma com o corpo colado no zero e uma cauda longa é uma região
  ruim com dois bilhetes premiados.
- **O melhor está muito longe da mediana?** Se o campeão faz R$ 20 mil e a
  mediana da região faz R$ 2 mil, o campeão não é representativo — é o ponto
  que mais se ajustou ao passado.

**Este é o antídoto prático contra sobreajuste.** Se a *região inteira*
funciona, você não escolheu um ponto por sorte — não importa quantas
varreduras rodou até chegar ali.

E há a versão numérica da mesma pergunta, na aba **Porteira**: total de
resultados, positivos, negativos, média, desvio padrão e o **Z-score** —
média ÷ desvio, ou seja, quantos desvios separam a média de zero.

Sobre a dúvida dos "três desvios": as duas formulações que circulam são a
mesma conta.

    média − 3σ > 0    ⟺    média / σ > 3    ⟺    Z > 3

Uma está em reais, a outra em desvios. Abaixo de Z = 1 a região é frouxa (o
resultado típico está a menos de um desvio do prejuízo); acima de Z = 3 é
sólida. E **não se multiplica por √N** aqui: no SQN de Van Tharp isso está
certo porque o N são trades, e mais trades é mais evidência — aqui o N são as
combinações que você escolheu testar, e testar mais não prova nada.

Pela mesma razão não se faz teste t sobre as combinações: vizinhos na grade
compartilham quase todos os trades, então são fortemente dependentes entre si
e o p-valor sairia absurdamente otimista.

**Na Dataframe:** aba **Distribuição**, dentro de Análise da varredura. Traz
o % de combinações lucrativas, a mediana da região, a razão melhor ÷ mediana,
o intervalo onde caem metade delas, o histograma com curva acumulada e a
curva das combinações ordenadas — em que a forma responde de imediato: queda
suave é platô, degrau nos primeiros por cento é precipício. O **score
robusto** (mediana dos vizinhos na grade) continua na tabela, punindo pico
isolado combinação a combinação.

### 6. Otimização e validação de parâmetros

Walk-forward: o período é fatiado em janelas de treino e teste que caminham
no tempo. A pergunta não é "quanto rendeu" — é **"rendeu de novo?"**.

Uma estratégia que ganha muito em 2022 e nada nos outros anos tem lucro total
bonito e valor nenhum. O que interessa é a mediana entre janelas e quantas
delas ficaram positivas.

**Na Dataframe:** treino, teste, passo e holdout são configuráveis; cada
combinação traz `folds_positivos`, `folds_com_trades` e `mediana_fold`. O
holdout fica gravado mas **não é exibido durante a varredura** — mostrar o
holdout de mil combinações e escolher a melhor é o mesmo que não ter holdout.
Ele é para a decisão final, no passo 7.

### 7. Critério de validação

Os números mínimos, **definidos antes de olhar o resultado**. Não é
burocracia: é o que impede a régua de esticar para acomodar o resultado de
que você gostou.

Os sete critérios da tela, com as faixas de partida para day trade de mini
índice:

| Critério | Faixa inicial |
|---|---|
| Nº de operações | ≥ 300 no período |
| Profit factor | ≥ 1,25 líquido |
| Fator de recuperação | ≥ 2,0 |
| Janelas positivas (walk-forward) | ≥ 60% |
| Mediana por período | ≥ R$ 0 |
| Drawdown máximo | ≤ R$ 2.500 |
| Lucro total | ≥ R$ 0 |

O drawdown é um teto **em reais**, não em percentual: R$ 2.500 equivalem a
25% do capital padrão de R$ 10.000, mas trocar o capital não move o limiar —
ajuste-o na mão. "Meses positivos" não é critério de mineração; é leitura da
aba Robustez, sobre um backtest já escolhido.

**Na Dataframe:** aba **Critérios**. Os sete limiares acima são
configuráveis e aplicados à varredura inteira; a tela mostra quantas
combinações passam em todos, qual critério mais corta (o gargalo, em
vermelho) e a lista das aprovadas — clicável, que carrega os parâmetros e
roda o backtest. Campo vazio desliga o critério.

---

## Fase 3 — Selecionar

### 8. Salvar mineração

Só o que passou no passo 7. Varredura descartada não vai para o banco — banco
cheio de lixo é banco que ninguém abre.

**Na Dataframe:** botão Salvar com nome. A varredura guarda o retrato
completo da camada 4, o espaço varrido, as janelas e o corte do holdout.

### 9. Carregar a mineração salva

Retomar a candidata **por completo**: estratégia, parâmetros e os 31 campos
de execução. Se um campo voltar diferente, os números na tela deixam de
corresponder aos do banco.

**Na Dataframe:** funciona, e há teste que percorre as chaves reais do perfil
para garantir que nenhuma fique sem destino. A lista mostra apenas as
minerações da estratégia ativa.

### 10. Testes de robustez

Sair do cenário perfeito e ver o que sobra. Cada teste ataca uma suposição
diferente:

| Teste | Suposição que ele quebra | Situação |
|---|---|---|
| Monte Carlo (ordem dos trades) | a sequência que aconteceu era a única possível | ✅ |
| Maiores mergulhos | drawdown é profundidade, não tempo | ✅ |
| Concentração do lucro | todo trade contribui | ✅ |
| Sensibilidade a custo | a corretagem de hoje é a de sempre | ✅ |
| Ulcer / MAR / SQN | max drawdown basta para ranquear | ✅ |
| Teste de sequência (runs) | as perdas são independentes | ✅ |
| Meses positivos | o total anual descreve a experiência | ✅ |
| Significância (t, p) | a expectativa difere de zero? | ✅ |
| Correlação LR | a curva é reta ou um degrau? | ✅ |
| SQN (Van Tharp) | quão regular é o resultado por trade | ✅ |
| **Vizinhança do parâmetro** | **o ponto escolhido é estável** | parcial |
| **Entrada aleatória** | **o mérito é do sinal** | ❌ |
| **Outro ativo / outro período** | **o padrão é do mercado, não da série** | ❌ |

---

## Fase 4 — Provar

### 11. Incubação

Deixar a estratégia rodando **sem enviar ordem**, sobre dado que não existia
quando você otimizou. É o único teste verdadeiramente fora da amostra, porque
é o único em que o dado não podia ter vazado.

Três meses costuma ser o mínimo que diz alguma coisa em day trade.

**O que comparar** — e é aqui que a incubação deixa de ser só espera:

1. o sinal disparou no minuto que o backtest diria?
2. o preço de execução bateu, ou o slippage real é maior?
3. o acumulado está dentro do intervalo do Monte Carlo, ou já saiu fora?

A pergunta 1 é a que pega **look-ahead** — o erro mais caro e mais silencioso
que existe em backtest.

**Na Dataframe:** não existe. É o maior buraco da plataforma para quem quer
chegar ao live.

### 12. Portfólio de baixa correlação

Uma estratégia sozinha tem o drawdown que tem. Duas que ganham em momentos
diferentes têm um drawdown combinado **menor que a soma** — é a única coisa
em trading que se ganha de graça.

O que medir:

- correlação dos **retornos diários** (não dos trades);
- a mesma correlação **restrita aos piores dias** — duas estratégias com 0,1
  na média podem ir a 0,8 no dia ruim, que é justamente quando a
  diversificação precisava funcionar;
- o **drawdown do conjunto**, calculado sobre a curva somada;
- se elas ficam posicionadas ao mesmo tempo (a exposição soma, o risco também).

**Na Dataframe:** a tela ainda não existe, mas os **dados já estão
gravados**. Todo walk-forward salvo guarda os trades da sua curva fora da
amostra (`wfa_trades`), com entrada, saída, lado, contratos e custo — de onde
saem a série diária, os intervalos de exposição e, daí, todas as leituras
acima. Faltam os gráficos, não a matéria-prima.

E vale registrar por que são os trades **OOS**: montar portfólio com
backtests otimizados é correlacionar dois sobreajustes. A curva concatenada
do walk-forward é a única aqui que o otimizador nunca enxergou.

### 13. Demo

Aqui não se testa a estratégia — ela já foi testada. Testa-se a
**infraestrutura**: o robô reconecta se cair? o que acontece com uma posição
aberta se o processo morrer? a ordem chega no tempo certo? o horário do
servidor bate com o de Brasília?

### 14. Contrato mínimo

Aqui se testa **o operador**. Dinheiro real muda a relação com o drawdown, e
essa é a variável que nenhum backtest simula. Ficar no mínimo até um drawdown
normal acontecer e você não ter mexido em nada.

### 15. Live

Escalar o tamanho. E deixar escrito, **antes de ligar**, o que faz desligar:
drawdown limite, sequência de perdas acima do máximo histórico, prazo sem
novo topo. No meio do drawdown todo argumento para continuar parece bom.

---

## O que dá para acrescentar

Ordenado por quanto muda a decisão. Tudo aqui se encaixa num passo que já
existe — nada abre fase nova.

~~1. Distribuição dos resultados da mineração~~ — **feito**, aba Distribuição.
~~2. Painel de critérios de validação~~ — **feito**, aba Critérios.

### 1. Teste de vizinhança explícito — *passo 10*

Pegar a combinação escolhida e mexer um passo em cada parâmetro, para os dois
lados, mostrando a degradação numa tabela. O score robusto já faz isso por
baixo; falta **mostrar**. Combinação que perde 40% do lucro com um passo de
diferença não é candidata, é coincidência.

### 2. Teste de entrada aleatória — *passo 10*

Substituir o sinal por entradas aleatórias com a **mesma frequência**,
mantendo stop, alvo e gestão. Se o aleatório for tão bom quanto, o mérito não
é do sinal — é da gestão de saída. É desconfortável e é revelador.

### 3. Teste em outro ativo e outro período — *passo 10*

Rodar a mesma estratégia no WDO, ou nos anos anteriores ao período usado. Não
precisa ir igualmente bem: precisa não desmoronar. Padrão que só existe numa
série é propriedade da série, não do mercado.

### 4. Análise por regime de volatilidade — *passo 10*

Separar os trades por ATR do dia acima ou abaixo da mediana. Estratégia que
só funciona em volatilidade alta não é ruim — é **condicional**, e precisa
ser operada sabendo disso. Sem essa separação, você descobre no live.

### 5. Sizing e risco de ruína — *entre 10 e 13*

Quantos contratos, com conta feita. A aba Detalhes já dá o CVaR (a perda
média dos 5% piores trades); falta transformá-lo em número de contratos e na
probabilidade de perder X% do capital antes de dobrá-lo.

Regra que sobrevive ao contato com a realidade: dimensione pelo **CVaR**, não
pela perda média, e assuma que a pior sequência futura será **maior** que a
do backtest.

### 6. Incubação com reconciliação — *passo 11*

Registrar sinais em tempo real e comparar com o que o backtest diz para as
mesmas barras. Sem isso, o passo 11 é só esperar três meses.

### 7. Tela de portfólio — *passo 12*

Curvas somadas, matriz de correlação, correlação nos piores dias e drawdown
do conjunto.

### 8. Catálogo de estratégias

Uma lista das estratégias já testadas, com o veredito e o motivo da reprova.
Serve para não refazer trabalho e para escolher a próxima ideia sabendo o que
já não funcionou.

---

## Estado da plataforma

| Passo | Situação |
|---|---|
| 1 Criar estratégia | ✅ backtest com auditoria visual, 5 abas de diagnóstico |
| 2 Busca de clusters | ✅ dispersão com cross-filtering |
| 3 Pegar um cluster | ✅ clique carrega a combinação |
| 4 Mineração de parâmetros | ✅ paralela, interrompível |
| 5 Mineração de resultados | ✅ distribuição, curva ordenada, score robusto e porteira |
| 6 Otimização e validação | ✅ walk-forward com holdout lacrado · WFA de Pardo com 8 inteligências, Consenso e 6 portões ([contas](CALCULOS-WFA.md)) |
| 7 Critério de validação | ✅ sete limiares, gargalo e lista de aprovadas |
| 8 Salvar mineração | ✅ explícito, com nome |
| 9 Carregar salva | ✅ restauração completa, com teste |
| 10 Testes de robustez | ✅ dez testes · ❌ vizinhança, aleatório, outro ativo |
| 11 Incubação | ❌ |
| 12 Portfólio | ❌ |
| 13–15 Live | ❌ falta integração com o MT5 |
