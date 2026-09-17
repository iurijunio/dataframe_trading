# As contas da Candidata

O que cada teste da tela Candidata faz, em palavras simples, com o número
real do walk-forward **#8** (`rompimento_canal`, WIN$N, IS 12 meses / OOS 6
meses, inteligência Ulcer, holdout incluído, capital R$ 10.000).

Onde está no código: `core/candidata.py` (os portões), `core/aleatorio.py`
(a entrada sorteada), `core/spa.py` (o teste de muitas tentativas),
`core/candidata_runner.py` (roda os três testes demorados em segundo plano).

> Este arquivo descreve o que o código **faz hoje**. Quando uma conta mudar,
> ele muda junto — o histórico de por que mudou fica no `CHANGELOG.md`.

---

## O que é esta tela

Você escolhe um walk-forward já salvo e a tela responde uma pergunta só:
**esta estratégia está pronta para ir para a incubação?** Ela faz isso rodando
uma lista de testes — os **portões** — sobre a curva **fora da amostra** do
walk-forward, a mesma que ele já mediu e que o otimizador nunca viu enquanto
escolhia parâmetro.

São 12 portões ao todo. Nove respondem na hora, lendo o que já está gravado.
Três são mais pesados — sorteiam entradas, refazem a varredura da mineração e
comparam com milhares de combinações — e levam cerca de **43 segundos** (a
varredura de novo: 1,6 s; o sorteio de entradas: 41 s). Enquanto eles não
rodam, o selo da tela mostra **AGUARDANDO TESTES COMPLETOS**.

O selo no topo resume tudo:

- **REPROVADA** — algum portão **crítico** falhou. Não segue adiante.
- **APROVADA COM RESSALVA** — todos os críticos passaram, mas algum
  **alerta** não. Segue, mas com um aviso escrito para ler antes de operar.
- **APROVADA** — passou em tudo.
- **AGUARDANDO TESTES COMPLETOS** — falta rodar os três testes demorados
  (ou algum crítico ainda não tem resultado, o que dá no mesmo: sem medir
  tudo, a tela não aprova em verde).

Cada portão tem seu próprio **(?)** na tela, com a mesma explicação destas
seções. Alguns nomes técnicos aparecem uma vez, entre parênteses, para quem
quiser procurar a referência — não são necessários para ler o resultado.

**No walk-forward #8: aprovada com ressalva, 11 de 12.** O único que não
passou foi um alerta, não um crítico — ver a seção 11.

---

## 1. O parâmetro está numa região larga, ou é um pico?

**A pergunta:** se o mercado mudasse um pouco e o parâmetro ideal deslizasse
um pouco do lugar, a estratégia continuaria funcionando?

**O que o teste faz:** pega o parâmetro que a mineração varreu
(`periodo_canal`, no #8) e anda, passo a passo da grade testada, para os dois
lados do valor escolhido. Para no primeiro passo em que o resultado (lucro
dividido pela maior queda, o **fator de recuperação**) cai abaixo de 60% do
valor no centro.

**A regra:** precisa segurar pelo menos 2 passos de cada lado. Um alerta
separado avisa quando a caminhada parou porque a faixa **testada** acabou (ou
tem um buraco não minerado) perto do parâmetro escolhido — aí não dá para
saber se a região continua boa mais além, só que ninguém testou.

**Por que existe:** um parâmetro que só funciona num valor exato é sorte, não
estratégia. Uma região larga aguenta o mercado se mover um pouco sem quebrar.

**O número do #8:** `periodo_canal` escolhido foi **58**, numa faixa testada
de **40 a 80**. A caminhada segura **18 passos à esquerda e 22 à direita** —
bem acima do mínimo de 2. Nos dois lados ela termina porque a faixa testada
acaba, não porque o resultado cai — a estratégia nunca foi testada além
disso. **Passa** o crítico; o alerta de cobertura também passa, porque a
régua só cobra mais mineração quando a largura mínima (2 passos) não é
alcançada, e aqui ela foi alcançada com folga.

---

## 2. O lucro não é acaso?

**A pergunta:** o ganho médio por dia é firme, ou pode ser zero e o que se
viu foi sorte?

**O que o teste faz:** soma o resultado de cada **pregão** (dia parado conta
como zero, não é ignorado) e divide a média diária pelo quanto ela oscila —
é o teste clássico de significância (**teste t**), medido por dia e não por
trade, porque trades do mesmo dia compartilham o mesmo regime de mercado e
contá-los como independentes infla a firmeza aparente.

**A regra:** esse número (t) precisa ser pelo menos **2,0**.

**Por que existe:** abaixo de 2, a média ainda pode ser zero de verdade e o
lucro que se viu ser só ruído com sorte.

**O número do #8: 2,59** (mínimo 2,0). **Passa.**

---

## 3. Não depende de poucos dias?

**A pergunta:** o resultado inteiro veio de um punhado de dias sortudos?

**O que o teste faz:** tira os **5 melhores pregões** da curva e soma o
resto.

**A regra:** precisa sobrar lucro positivo.

**Por que existe:** se o lucro vira prejuízo sem os cinco melhores dias, a
estratégia não é um sistema — é um punhado de acidentes felizes que podem não
se repetir.

**O número do #8:** sem os 5 melhores pregões, sobra **R$ 2.960**. **Passa.**

---

## 4. Aguenta custo maior?

**A pergunta:** o lucro sobrevive se a corretora cobrar um pouco mais, ou o
mercado escorregar o preço na hora da entrada e da saída?

**O que o teste faz:** recalcula o lucro pagando **1 tick a mais** em cada
ponta de cada trade (entrada e saída).

**A regra:** precisa sobrar lucro positivo.

**Por que existe:** no mini índice 1 tick vale mais que a corretagem inteira,
e uma ordem a mercado na hora da pressa costuma escorregar isso. Se o lucro
some com um tick de diferença, a estratégia vive no limite do custo.

**O número do #8:** com 1 tick a mais por ponta, sobra **R$ 4.454**.
**Passa.**

---

## 5. O capital comporta 1 contrato?

**A pergunta:** o capital disponível aguenta operar o mínimo de 1 contrato,
sem risco de ruína logo de cara?

**O que o teste faz:** olha a perda esperada num mau momento (a mesma conta
da seção "quanto a estratégia aguenta", lá embaixo) e calcula que fração do
capital ela representa, operando só 1 contrato.

**A regra:** essa fração não pode passar de **20% do capital**.

**Por que existe:** se nem o mínimo cabe, o problema não é a estratégia — é o
capital não comportar o instrumento.

**O número do #8:** a perda esperada com 1 contrato é **8,3% do capital**
(máximo 20%). **Passa.**

---

## 6. O holdout confirma?

**A pergunta:** nos meses finais que ficaram de fora de toda mineração e
otimização — o **holdout** — a estratégia se comportou como o histórico
anterior fazia esperar, ou decepcionou?

**O que o teste faz:** simula **2.000 caminhos possíveis** para os meses do
holdout, usando só o que a estratégia fez **antes** do corte (a plataforma
sorteia trechos desse histórico anterior, do mesmo tamanho do holdout, e
repete 2.000 vezes — um método chamado **bootstrap**). Depois olha onde o
resultado **real** do holdout caiu nessa distribuição de possibilidades.

**A regra:** reprova só se o holdout ficar entre os **10% piores** caminhos
que o histórico anterior fazia esperar. Resultado melhor que o esperado
passa sempre.

**Por que existe:** é o único trecho da base que nenhuma mineração, backtest
ou walk-forward já olhou — o único número da plataforma sem viés de escolher
o que já deu certo.

**O número do #8:** o holdout tem **120 pregões** e rendeu **R$ 942**; a
régua que reprovaria é **abaixo de −R$ 270** (os 10% piores caminhos que o
histórico anterior projetava para um período do mesmo tamanho). Em reais por
mês: **R$ 103/mês** antes do corte contra **R$ 165/mês** no próprio holdout —
melhorou. Com esse histórico, o teste só reprovaria se o holdout tivesse
efetivamente **perdido dinheiro**; é a régua decidida, e ela só pega o lado
muito ruim. **Passa.**

*Nota: quando o histórico ANTES do corte é curto demais para simular (menos
de 30 pregões), este portão vira alerta em vez de bloquear a aprovação — não
há "rodar de novo" que resolva uma base que é do tamanho que é.*

---

## 7. Algum vizinho dá prejuízo? (alerta)

**A pergunta:** um pequeno erro de ajuste no parâmetro já custaria dinheiro?

**O que o teste faz:** olha os valores do parâmetro a até 2 passos do
escolhido, na mineração, e verifica se algum deu prejuízo.

**A regra:** é alerta, não crítico — não reprova a estratégia, só avisa.

**Por que existe:** um vizinho no vermelho não invalida a escolha, mas diz
que a margem de erro na hora de ajustar o parâmetro é menor do que parece.

**O número do #8:** **nenhum vizinho** deu prejuízo. **Ok.**

---

## 8. Depende do 1% melhor dos trades? (alerta)

**A pergunta:** o resultado mora em poucas operações excepcionais?

**O que o teste faz:** tira o **1% de trades** que mais ganharam e soma o
resto.

**A regra:** é alerta — reprovaria (com ressalva) se o que sobra virasse
prejuízo.

**Por que existe:** irmão mais severo da seção 3, olhando trade a trade em
vez de dia a dia.

**O número do #8:** sem o 1% melhor, sobra **R$ 4.106**. **Ok.**

---

## 9. Ganha de entradas sorteadas ao acaso?

**A pergunta:** o mérito é do sinal de entrada, ou só da gestão de saída
(stop, alvo, horário)?

**O que o teste faz:** troca as entradas da estratégia por entradas
**sorteadas ao acaso** — no mesmo horário, na mesma proporção compra/venda —
e mantém toda a gestão de saída exatamente como a real, janela a janela do
walk-forward. Repete o sorteio **1.000 vezes** e vê em quantas delas o
sorteio empatou ou superou o resultado real.

**A regra:** essa fração não pode passar de **5%**.

**Por que existe:** se entradas jogadas ao acaso ganham quase tanto quanto o
sinal de verdade, quem está ganhando é a gestão de saída, não o sinal.

**O número do #8:** só **1 em 1.000** sorteios igualou a estratégia real
(**0,1%**, máximo 5%). **Passa.**

---

## 10. Aguenta o desconto por muitas tentativas?

**A pergunta:** a melhor combinação de parâmetros da mineração ainda ganha de
não operar, depois de descontar que **dezenas de combinações** foram
testadas e alguma sempre sai bem só por sorte?

**O que o teste faz:** reamostra o histórico de todas as combinações
mineradas muitas vezes e compara, em cada reamostragem, a melhor coluna
**daquela** reamostragem com o que se observou de verdade (um método
chamado **SPA de Hansen**, de 2005). O resultado é a fração das
reamostragens em que o acaso teria produzido algo igual ou melhor.

**A regra:** essa fração não pode passar de **5%**.

**Por que existe:** minerar é testar muitas combinações e ficar com a
melhor — é o mesmo viés de escolher "o melhor fundo dos últimos 5 anos".
Mesmo sem nenhuma vantagem real, a melhor de quarenta sorteios de ruído sai
positiva só pela ordem.

**O número do #8:** **0,8%** (máximo 5%). **Passa.**

*Nota sobre o limite: o desenho original previa 10%, não 5%. Medido com 200
simulações sobre dados sem vantagem nenhuma, o corte de 10% deixava passar
sorte em 16–18% das vezes quando os dias de mercado dependem uns dos outros
(o caso normal) — quase o dobro do pretendido. O corte de 5% aprova sorte em
7,5–9,5% das vezes, que é o que "até cerca de 1 em 10" realmente queria
dizer. Por isso o limite deste portão é 5%, e não os 10% do desenho
original.*

---

## 11. Reotimizar compensou? (alerta)

**A pergunta:** trocar de parâmetro a cada janela (o que o walk-forward faz)
valeu o trabalho, comparado com ter escolhido uma combinação qualquer da
mineração e deixado **fixa** do início ao fim do mesmo período?

**O que o teste faz:** pega todas as combinações da mineração, roda cada
uma **sem reotimizar** durante o mesmo intervalo, e vê em que posição
(percentil) a curva do walk-forward termina entre elas.

**A regra:** precisa terminar no percentil **50 ou mais** — ou seja, pelo
menos metade das combinações fixas tem que ter feito **pior**.

**Por que existe:** se mais da metade das combinações fixas — escolhidas ao
acaso, sem inteligência nenhuma — fez mais dinheiro que o walk-forward, o
trabalho de reotimizar a cada janela não se pagou, e operar com parâmetro
fixo seria mais simples e mais barato.

**O número do #8: percentil 39** — só **39% das combinações fixas fizeram
menos** que o walk-forward, ou seja, **61% fizeram mais** no mesmo período.
**Não passa** — é o único item que fica de fora dos 12, e é por isso que o
walk-forward #8 sai **aprovado com ressalva**, não aprovado liso.

---

## Quanto a estratégia aguenta

Esta é a tabela de baixo da tela, ao lado do resultado fora da amostra. Ela
não reprova nada sozinha — quem decide passa ou reprova são os portões
acima. Ela só mostra, em números, **o preço de continuar operando**: a
plataforma sorteia 2.000 caminhos possíveis usando os dias reais que a
estratégia já operou, embaralhados e recombinados, e cada linha mostra o
pior caminho **para aquela métrica** — os números ruins de linhas diferentes
não aconteceram todos juntos, no mesmo caminho sorteado.

- **Perda esperada até a próxima reotimização** — a maior queda a partir de
  um topo que se deve esperar no horizonte até reotimizar de novo. Só 5 de
  cada 100 caminhos sorteados perdem mais que isso; é a base para decidir
  quando desligar o robô. No #8, com 1 contrato, essa perda é **8,3% do
  capital** — o mesmo número do portão 5, porque os dois vêm da mesma conta.
- **Dias perdendo seguidos** — quantos dias de operação seguidos fechando no
  prejuízo é razoável esperar (dia sem operação não conta).
- **Dias até novo topo** — quanto tempo, tipicamente, a estratégia passa
  abaixo do último topo antes de superá-lo, e qual é o pior caso dentro do
  mesmo horizonte.
- **Perda com outra ordem** — os mesmos trades, embaralhados: mede o azar de
  os prejuízos virem todos juntos, no período inteiro (não só até a próxima
  reotimização).

Bom: até 10% do capital. Ruim: acima de 20%. É a mesma faixa usada no portão
5 e na leitura de "quanto a estratégia aguenta" da tela.
