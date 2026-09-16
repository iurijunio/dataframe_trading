# Plano: modo Candidata

O quarto modo da plataforma, ao lado de Backtest, Mineração e Walk-Forward.
Implementa o **passo 10 da metodologia** — testes de robustez — sobre a curva
que o otimizador nunca viu, e termina gravando o **plano de operação**: os
limites escritos antes de ligar o robô.

> O walk-forward responde "o meu processo de escolher parâmetro funciona?".
> A Candidata responde outra coisa: **quanto disto sobrevive fora do cenário
> perfeito, com quantos contratos eu opero, e o que me faz desligar.**

Desenhado em 15/09/2026, revisado no mesmo dia por três revisores
(estatística, prática de trading, aderência ao código). As contas detalhadas,
com exemplos reais, vão para `CALCULOS-CANDIDATA.md` na fase 6 — no mesmo
formato do [CALCULOS-WFA.md](CALCULOS-WFA.md).

---

## 1. O problema que motivou a tela

A aba Robustez existe desde o começo e roda dez testes: Monte Carlo, maiores
mergulhos, concentração do lucro, sensibilidade a custo, Ulcer/MAR/SQN, teste
de sequências, meses positivos, significância e correlação linear.

Todos rodam sobre **os trades do backtest** (`ui/callbacks.py`, `_robustez`) —
a curva que o otimizador escolheu **olhando o resultado**.

O número mais importante que sai dali é o `dd_p95` do Monte Carlo. É ele que
deveria virar o disjuntor do live. Medido sobre a curva otimizada, sai
otimista — e um disjuntor otimista dispara depois de o prejuízo ter acontecido.

A curva certa já está gravada: `wfa_trades` guarda trade a trade a curva fora
da amostra de cada walk-forward salvo. **Falta a tela, não a matéria-prima.**

### O que a revisão acrescentou a este diagnóstico

Trocar a curva **não bastava**. `robustez.monte_carlo` usa
`rng.permutation(liquido)` — amostragem **sem reposição**: os 2.000 caminhos
terminam todos no mesmo capital final, e o embaralhamento trade a trade destrói
o agrupamento por pregão, que é o que produz drawdown de verdade. O método
pressupõe que o edge medido é o verdadeiro, que é justamente a incerteza que
domina. Ver §4.1.

---

## 2. Decisões travadas (15/09/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Como a estratégia é operada ao vivo? | **Reotimizando a cada OOS**, como o WFA simulou, e **reotimizando imediatamente antes de ligar** (§6.4). |
| 2 | O que entra na tela? | Cinco blocos: robustez, platô, sorte, holdout, tamanho e plano. |
| 3 | Onde ela fica? | **Quarto modo no topo**, com painel próprio. |
| 4 | Como decide? | **Portões + leituras**, com o veredito sempre visível. |
| 5 | De onde vêm os números? | Do banco, rodando o motor só onde não há alternativa. |
| 6 | O que reprova por excesso de tentativas? | **SPA de Hansen, p ≤ 0,10, crítico.** Mede a correlação real entre tentativas em vez de supor N independentes. |
| 7 | O holdout lacrado entra? | **Sim, como portão crítico.** Muda a regra anterior ("holdout é só visualização"). Ver §6.5. |
| 8 | Ordem dos projetos? | **B (sincronização MT5) em paralelo com A**, gravando sinais ao vivo desde já. Ver §11. |

---

## 3. Arquitetura

```
core/candidata.py       contas puras: platô, sorte, SPA, contratos, portões
core/aleatorio.py       estratégia falsa de entrada aleatória + repetições
core/plano.py           monta e grava o plano de operação
core/robustez.py        MUDA: bootstrap estacionário ao lado da permutação
core/wfa.py             MUDA: sharpe por configuração em agregar/_linha_matriz
core/wfa_store.py       MUDA: grava profile, capital e os sharpes da matriz
core/schema.sql         MUDA: planos_operacao + ALTER TABLE em wfa_runs
ui/components/candidata_panel.py    os cinco blocos e a faixa de portões
ui/callbacks_candidata.py           callbacks próprios, com register(app)
```

`ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são do walk-forward. A
Candidata acrescentaria 400 a 600. Arquivo próprio não é refactor cosmético: é
a diferença entre o teste de ciclo apontar um arquivo de 2.300 linhas ou um de
500.

Nada em `core/` importa Dash — o padrão que `wfa.py`, `robustez.py` e
`metrics.py` já seguem, e o que torna os testes possíveis sem navegador.

### Fluxo

    escolher WFA salvo
      → banco devolve: trades OOS, perfil e capital (wfa_runs), DEPLOY,
        sharpes da matriz, e a mineração de origem (só para o bloco 2)
      → blocos 1, 3 e 5 calculam direto
      → aleatório, SPA e holdout rodam sob demanda, em segundo plano
      → portões dão o veredito
      → botão grava o plano de operação

### Onde cada número nasce

| bloco | fonte | custo medido |
|---|---|---|
| 1 robustez | `wfa_trades` | instantâneo |
| 2 platô | `mining_trials` + `mining_runs.space` | instantâneo |
| 3 PSR, minTRL, Deflacionado | `wfa_trades` + sharpes da matriz | instantâneo |
| 3 SPA | curvas diárias de todas as combinações (`wfa.faixa_fixas`) | ~5 s |
| 3 aleatório | motor, 1.000 execuções calibradas | ~2 min, segundo plano |
| 4 holdout | motor, 1 execução | ~1 s |
| 5 contratos, ruína | `wfa_trades` | instantâneo |

Medição real do revisor de código: 5 execuções do motor com estratégia falsa
sobre 552 mil barras M1 levaram 0,26 s. O aparato de véu e progresso continua
necessário só por causa da calibração (§6.2), não pelo motor.

### O que `wfa_runs` precisa passar a guardar

Hoje a tabela não tem **capital** nem **perfil de execução** (`schema.sql:159`).
O capital vem de `VARREDURA.estado`, que veio de `mining_runs.profile`. Sem ele
não há Monte Carlo, portão de capital nem dimensionamento — os blocos 1 e 5
inteiros dependem de a mineração ainda existir.

    ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS profile JSON;
    ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS capital DOUBLE;
    ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS sharpes_matriz JSON;

`db_manager.DESCARTAVEIS` só verifica deriva de schema em `mining_trials` e
`mining_runs`; para `wfa_runs`, `CREATE TABLE IF NOT EXISTS` é no-op silencioso
e a falha apareceria só na hora de salvar. Por isso, `ALTER TABLE` explícito.

**Retrocompatibilidade:** o `wfa_id=3` já salvo não tem nenhuma das três. Cada
bloco diz "indisponível, com o motivo", e oferece recalcular — nunca calcula com
dado suposto.

---

## 4. Os cinco blocos

### 4.1 Robustez sobre a curva fora da amostra

Os dez testes atuais, com a fonte trocada, **mais a correção de método**:

| medida | como era | como fica |
|---|---|---|
| distribuição de drawdown | permutação sem reposição | **bootstrap estacionário com reposição**, em blocos de pregão |
| tamanho do bloco | — | calibrado pela autocorrelação do P&L diário (o `teste_runs` vira o calibrador, não um cartão) |
| o que a permutação vira | o disjuntor | uma leitura à parte: "risco de ordenação" |
| horizonte | inexistente | trajetórias truncadas em **H = meses até a próxima reotimização** |

Referência: Politis & Romano (1994), *The Stationary Bootstrap*.

**Por que o horizonte muda tudo.** `dd_p95` é o p95 do drawdown de uma
trajetória do comprimento **inteiro** do OOS. Uma estratégia saudável o atinge
com 5% de probabilidade nesse comprimento — em um horizonte maior, mais. Sem
horizonte declarado o disjuntor não é calibrado, é palpite. O plano grava a
frase: *"até DD/MM, P(bater este drawdown, estando a estratégia viva) = x%"*.

**Dois recortes, sempre.** Todas as contas de risco rodam sobre a curva inteira
**e** sobre os últimos 12 meses; vale a pior. O mini índice foi de 96 mil a 197
mil pontos dentro da própria amostra — stop, alvo e limites em pontos
significam coisas diferentes em 2021 e em 2026.

**Sai da tela** (medido, redundante ou enganoso): `correlacao_lr` (qualquer
passeio com deriva dá r ≈ 0,9), SQN (é o t-stat com outro nome),
`meses_positivos` (o WFA já tem o portão de semestres, e por um motivo escrito),
e **MAR/CAGR** — `cagr` compõe uma curva que não compõe, porque o
dimensionamento é de contratos fixos e o P&L é aditivo. No lugar do MAR:
`lucro anual médio / dd_p95`.

### 4.2 Platô do parâmetro

O desenho original media "2k vizinhos, um passo da grade em cada parâmetro".
No dado real isso degenera: o espaço da #40 varia **um único** parâmetro
(`periodo_canal`, 40→80) — k = 1, dois vizinhos, e o portão mais severo da tela
decidido por duas amostras.

**O bloco passa a mostrar o perfil inteiro:** lucro e fator de recuperação ao
longo de toda a faixa minerada, com o DEPLOY marcado. O portão mede a **largura
do platô** — quantos passos de cada lado seguram ≥ 60% do centro, medido por FR
e não por lucro (lucro perto de zero faz a razão explodir).

Com k > 1, a mesma leitura vira a caixa de `wfa._plato_pessimista`, que já
existe, é testada e é invariante à resolução da grade.

**Dois cuidados de dado:**
- `deploy.params` vem em **float** (`78.0`) e `mining_trials.params` em **int**
  (`78`). Casamento por igualdade devolveria zero vizinhos **sem erro nenhum**.
  Uma única função de chave normaliza os dois.
- Vizinho ausente tem duas causas diferentes: **borda da faixa** e **mineração
  interrompida** (`mining_runs.status`). A tela distingue, e o portão **abstém**
  (cinza, não verde) quando falta mais de um terço da vizinhança.

**Ressalva, no (?):** estes números são do período inteiro da mineração. A
pergunta é o **formato da superfície**, não o nível do lucro. A fase 2 mede uma
vez a diferença contra o recorte OOS e registra o resultado aqui.

### 4.3 Sorte e tentativas

**Regra que vale para o bloco inteiro: tudo em base diária; anualiza só para
exibir.** `wfa.sharpe_diario` devolve o valor **anualizado** (`× √252`); as
fórmulas de Bailey & López de Prado exigem o Sharpe por período. Medido na
curva do WFA #3: com o Ŝ certo o tempo mínimo de histórico dá **321 pregões (15
meses)**; com o anualizado, **10 pregões**. Erro de 30×, na direção otimista.

**Sharpe Probabilístico** — Bailey & López de Prado (2012):

    PSR = Φ[ (Ŝ − S*)·√(n−1) / √(1 − γ₃·Ŝ + (γ₄−1)/4·Ŝ²) ]

γ₄ é a curtose **não-excedente** (normal = 3). Usar o excesso troca `(3−1)/4`
por `(0−1)/4` e pode deixar o radicando negativo — `nan` silencioso. O radicando
é protegido por piso.

**Tempo mínimo de histórico** — mesmo artigo, com `z` **unicaudal** (1,645):

    minTRL = 1 + [1 − γ₃·Ŝ + (γ₄−1)/4·Ŝ²] · (z/(Ŝ − S*))²

Mostrado com **duas referências**: `S* = 0` ("quanto tempo para provar que o
Sharpe é positivo") e `S* = E[max Sharpe]` ("…depois de descontar a busca"). A
segunda costuma multiplicar o prazo por 3 a 10, e é ela que dimensiona a
incubação. Indefinido para Ŝ ≤ S* → "não aplicável", nunca um número plausível.

**Sharpe Deflacionado** — Bailey & López de Prado (2014):

    S* = √V[S] · [ (1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ],  γ = 0,5772

Leitura, não portão. Mostrado em **faixa**: N = 96 (a matriz) e N = 96 + as
combinações mineradas. As 96 células saem da mesma varredura e são
correlacionadas — o N honesto está entre os dois extremos, e é por isso que
quem tem dentes é o SPA.

**SPA de Hansen — o portão** (decisão 6). Testa H₀: *a melhor das N tentativas
não bate o benchmark depois de descontar a busca*, com bootstrap estacionário
sobre a matriz T×N de curvas diárias — **a mesma que `wfa.faixa_fixas` já
monta**. Corrige múltiplas tentativas com a correlação **medida**, não estimada
por uma fórmula i.i.d. com N chutado. Referências: White (2000); Hansen (2005).

O CSCV/PBO **sai do desenho**: responderia a mesma pergunta exigindo três
escolhas delicadas (o S das divisões, o critério de ranqueamento — que aqui é FR
mais inteligência, não Sharpe — e alimentar a matriz com todas as combinações e
não só as aprovadas). Mesma pergunta, três lugares a mais para errar.

**`Φ⁻¹` não existe no projeto** (`robustez.py` usa `math.erfc` para Φ, e não há
scipy, de propósito). Entra em `core/candidata.py` como aproximação racional,
com teste contra valores tabelados.

### 4.4 Holdout lacrado

O corte está em `mining_runs.holdout_de` (14/09/2025) e a base vai até
13/03/2026: **~6 meses que nem a mineração, nem o WFA, nem a matriz de 96
tocaram**. É o único número da plataforma sem viés de seleção.

**Como funciona:** roda os parâmetros do DEPLOY no período do holdout, uma vez,
e compara o lucro/mês com a faixa p10–p90 que o plano prevê. Dentro da faixa,
passa; fora, reprova.

**Munição de tiro único.** O resultado é gravado como registro imutável, com a
data. Reabrir o holdout depois de reotimizar transforma-o em mais um período de
otimização — e a plataforma perde para sempre o único dado limpo que tinha.

### 4.5 Contratos, ruína e plano de operação

**Tamanho pelo CVaR do pregão, não do trade.** A camada 4 tem limites do dia
(`max_trades_dia`, stop diário): o dia pode empilhar duas ou três perdas, e a
unidade de risco operacional é o pregão.

    CVaR₅ = média dos 5% piores PREGÕES, por contrato
    contratos = piso( capital × risco% / |CVaR₅| )

- **`contratos = 0` reprova** por capital insuficiente, explicitamente.
- O **risco efetivo do inteiro** escolhido é exibido e gravado: entre 1 e 2
  contratos o risco dobra, e "1%" vira ficção.
- Todas as contas seguintes usam o **inteiro**, nunca o fracionário.
- O (?) diz o que "1% com CVaR" significa: 1% do capital é a **média** da cauda,
  não o teto dela. Metade das perdas da cauda será maior.
- Piso de estresse: dimensiona-se pelo **pior** entre o CVaR do pregão e um
  cenário de gap/trava, e trava-se também pela **margem intradiária** exigida.

**Risco de desligamento, não "ruína".** A pergunta operacional não é "caio X%
antes de dobrar" (fração fixa, de Vince, com capital composto — a curva aqui é
aditiva). É: **P(bater o drawdown de desligamento até a próxima reotimização)**,
que o bootstrap já calcula e o plano já tem o horizonte para definir.

**O plano de operação**, gravado em `planos_operacao`:

| grupo | campos |
|---|---|
| identidade | `wfa_id`, `run_id`, símbolo, estratégia, nome, data |
| retratos | `params`, `profile`, `capital` — cópias, não referências |
| tamanho | contratos, risco por trade pedido, **risco efetivo**, margem exigida, capital livre |
| disjuntor | drawdown de desligamento, **nível de redução** (§6.3), sequência máxima de perdas, prazo sem novo topo, limite diário em R$ e em trades |
| definições | o que é "novo topo", DD sobre capital inicial ou corrente, posição aberta conta ou não, regra de reentrada e quarentena |
| expectativa | faixa p10–p90 em 3, 6 e 12 meses, e o minTRL ao lado |
| reotimização | a receita inteira (§6.4) e a data |
| régua | os limiares congelados, e o resultado do holdout |
| reprodutibilidade | versão do motor, retrato da base, `estado` ('ativo'/'aposentado') |

Sem `UNIQUE` por `wfa_id`: dois planos do mesmo WFA com risco diferente são
decisões diferentes, e ambas são histórico. Exclusão em cascata nos **três**
pontos — `wfa_store.excluir`, `optimizer.excluir_salva` e o botão da tela —
porque o acidente de deixar 551 trades órfãos já aconteceu uma vez.

---

## 5. Os portões

Mesma estrutura do WFA: **críticos** reprovam, **alertas** aparecem em amarelo.
Limiares editáveis; qualquer alteração aparece na tela com data e valor antigo,
e vai congelada para dentro do plano.

| # | Portão | Limiar de partida | Tipo |
|---|---|---|---|
| 1 | Largura do platô | ≥ 2 passos de cada lado segurando 60% do FR do centro | crítico |
| 2 | Vizinhança disponível | menos de 1/3 ausente, senão **abstém** | alerta |
| 3 | Entrada aleatória | p-valor de permutação ≤ 0,05 | crítico |
| 4 | Significância | **t ≥ 2,0 sobre o P&L diário** | crítico |
| 5 | Dependência de dias | sobrevive sem os **5 melhores pregões** | crítico |
| 5b | Dependência de trades | sobrevive sem o **top 1%** dos trades | alerta |
| 6 | Capital comporta o mínimo | com **1 contrato**, `dd_p95(H)` ≤ 20% do capital | crítico |
| 7 | Custo | sobrevive a **+1 tick de slippage por ponta** | crítico |
| 8 | Tentativas | **SPA de Hansen, p ≤ 0,10** | crítico |
| 9 | Holdout | lucro/mês dentro da faixa p10–p90 prevista | crítico |
| 10 | Reotimizar compensa | WFA ≥ **p50** da faixa das combinações fixas | alerta |

### As decisões por trás dos limiares

**Portão 4 mudou de unidade.** Com ~1,5 trades por pregão, trades do mesmo dia
compartilham regime e notícia: o `n` efetivo é o de pregões, não o de trades, e
o t por trade vem inflado. Medido sobre o P&L diário, `t ≥ 2,0` é o que
aparenta ser.

**Portão 6 deixou de ser um dial.** `dd_p95 ≤ 20% do capital` escala
linearmente com os contratos, e os contratos são escolha do usuário — um portão
que sempre passa girando um botão vira carimbo. Agora o bloco 5 **resolve** o
número máximo de contratos, e o portão pergunta a única coisa livre de tamanho:
**a unidade mínima cabe?** Se com 1 contrato o drawdown esperado já passa de 20%
do capital, não é a estratégia que está errada — é o capital que não comporta o
instrumento.

**Portão 7 é o mais barato e um dos mais letais.** No WIN, 1 tick = 5 pontos =
R$ 1,00 por contrato por ponta, contra ~R$ 0,77 de corretagem e emolumentos:
**um tick de slippage mais que dobra o custo total**. O kernel preenche com
slippage fixo e trata o alvo como preenchido ao toque, sem fila — premissa
otimista justamente no stop em movimento rápido. `robustez.custo_que_zera` já
calcula o limite; passa a ser expresso em **ticks** e a reprovar.

**Portão 8 é o que tem dentes contra a busca.** Sem ele, o desenho mediria
sobreajuste com quatro instrumentos e ignoraria os quatro resultados.

**Portão 9 muda uma regra anterior.** O holdout era visualização; passa a
reprovar. Em troca, vira tiro único (§4.4).

**Portão 10 é alerta porque decide o modo, não a estratégia.** Se o walk-forward
termina abaixo da mediana das combinações fixas, reotimizar **destruiu** valor
naquele período — o caminho certo é operar parâmetro fixo, que é mais simples e
mais barato. Na #40 o resultado foi **p34**, ou seja: 66% das combinações fixas
fizeram mais. Isso contradiz a decisão 1 no caso de referência, e precisa estar
visível na hora de gravar o plano.

**Recusa dura abaixo de 100 trades OOS.** Trinta trades não sustentam nenhum
número desta tela — o CVaR₅ seria um trade e meio de cauda. Rótulo de "amostra
pequena" ao lado de um número preciso perde para o número.

**Leituras que nunca reprovam:** PSR, Deflacionado, minTRL, risco de ordenação
(a permutação), tempo submerso, Ulcer, percentil do drawdown observado.

---

## 6. Os pontos delicados

### 6.1 O aleatório mede o quê, exatamente

**Só o sinal de entrada muda.** Período, parâmetros de gestão, stop, alvo,
trailing, horário, custo e limites do dia são idênticos.

| detalhe | decisão | motivo |
|---|---|---|
| contra o quê | a **curva OOS real**, janela a janela, com o parâmetro de cada janela | um backtest fixo do DEPLOY seria curva **dentro da amostra**: o IS do DEPLOY cobre os OOS anteriores |
| sorteio | **estratificado pelo horário** das entradas reais | sorteio uniforme mede a volatilidade em U do WIN, não o sinal |
| quantidade | calibrada por bisseção até bater o nº de **trades** (±5%) | 600 sinais deram 497 trades; 3.000 deram 1.885 — a taxa não é fixa |
| lado | mesma proporção da real | o perfil da #40 é só compra; sorteio de venda evaporaria |
| repetições | **1.000** | 200 tem variância de Monte Carlo relevante perto do p95 |
| leitura | p-valor de permutação `(1 + k)/(1 + B)` | o percentil empírico cru é viesado |

**O que ele não mede, escrito no (?):** a estratégia real passou por seleção de
parâmetro e as aleatórias não. Com um único parâmetro varrido, a vantagem é
pequena, mas existe.

### 6.2 O cálculo pesado não pode sequestrar a varredura

`wfa_runner.VARREDURA` é **singleton por processo**, e `iniciar` zera o cache e
incrementa a geração. Um clique em "recalcular matriz" na Candidata deixaria a
aba Walk-Forward aberta ao lado em "clique em Executar", sem explicação — os
dois painéis coexistem no DOM.

Regra: a Candidata **reusa** a varredura viva quando o `run_id` bate (o caso
comum, já que o WFA acabou de ser salvo); se não bater, avisa antes do que vai
acontecer. Cada cálculo tem seu evento de parada e seu contador de geração —
que é o mecanismo de "descartar resposta atrasada".

`tick.disabled` tem dono único (`pulso`). Estender esse callback e rodar
`tests/test_callbacks_sem_ciclo.py` é **tarefa explícita**, não cuidado difuso.

### 6.3 Desligar em degraus

Um gatilho único de nível é mau detector: em `dd_p95` desliga-se uma estratégia
**sadia** em ~5% dos ciclos, e uma morta só depois de 20% do capital ter ido.

| nível | gatilho | ação |
|---|---|---|
| 1 | equity sai do p10 do envelope, **ou** sequência de perdas > p95 | reduzir para 1 contrato |
| 2 | `dd_p95(H)` atingido | desligar |

### 6.4 A receita da reotimização, não só a data

Reotimizar exige: qual mineração fornece o espaço, qual inteligência, rolante ou
ancorada, IS de quantos meses, quais critérios de aceite, e **o que fazer se
nenhuma combinação passar** (a regra do WFA é ficar fora do mercado — o plano
precisa herdá-la). Tudo isso vai gravado.

Duas regras operacionais:
- **reotimizar imediatamente antes de ligar**, com dado até a véspera. O WFA só
  mediu parâmetros com idade entre 0 e OOS meses; entre aprovar a candidata e a
  primeira ordem passam-se meses, e opera-se um trecho da curva de degradação
  que nunca foi medido;
- **nunca trocar parâmetro com posição aberta**: reotimiza fora do pregão, vale
  a partir da abertura seguinte. Se a reotimização mudar os parâmetros, o plano
  inteiro é regravado — contratos e disjuntor junto.

A tarefa 5.6 do [PLANO-WFA](PLANO-WFA.md) (camada 4 reotimizável ou travada)
precisa ser fechada **antes** de qualquer plano ser gravado.

### 6.5 O que a decisão do holdout custa

Aberto o holdout, ele acaba. A plataforma passa a ter zero dado intocado até a
próxima exportação do MT5 crescer a base. É o preço de ter um portão sem viés de
seleção, e está registrado aqui para não ser esquecido.

---

## 7. A tela

```
┌ walk-forward salvo ▾   estratégia · símbolo · IS/OOS · inteligência · período   [Analisar] ┐
├ PORTÕES  1✓ 2✓ 3✓ 4✓ 5⚠ 6✓ 7✗ 8✓ 9· 10⚠            REPROVADA — custo                      ┤
├ 1 Robustez da curva fora da amostra   cartões + mergulhos + os dois recortes (tudo / 12m)  ┤
├ 2 Platô                                perfil do parâmetro na faixa minerada, DEPLOY marcado┤
├ 3 Sorte e tentativas                   PSR · minTRL(0 e max) · Deflacionado · SPA [calcular]┤
├ 4 Holdout lacrado                      [abrir — uma vez só]   resultado e data              ┤
├ 5 Tamanho e plano   risco/trade [1%] → contratos · risco efetivo · desligamento  [Gravar]   ┤
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

A faixa de portões fica **grudada no topo** enquanto se rola. Cinco blocos de
diagnóstico convidam a procurar o número que justifica seguir em frente; o
veredito sempre visível é o que impede a análise de virar advocacia.

Reaproveitamento: `robustez_cards`, `stats_cards`/`cartao`, `dash-ag-grid` com
os formatadores pt-BR, e a barra de progresso com véu do WFA. Todo número com (?).

### Estados e erros

| situação | o que a tela faz |
|---|---|
| WFA salvo sem `profile`/`capital` (anteriores a esta tela) | blocos 1 e 5 indisponíveis com o motivo e botão de recalcular |
| WFA salvo sem os sharpes da matriz | Deflacionado indisponível; o SPA não depende deles |
| mineração de origem excluída | só o bloco 2 cai — possível **depois** de `wfa_runs` ficar autossuficiente |
| menos de 100 trades OOS | recusa dura, sem calcular |
| vizinhança com buracos | portão 2 abstém, distinguindo borda de mineração interrompida |
| holdout já aberto | mostra o registro gravado; não roda de novo |
| cálculo rodando | botões travados, véu, progresso, interrompível |
| trocar de WFA no meio | a resposta atrasada é descartada pela geração |

Cada bloco **degrada sozinho**. Como o banco guarda registros de decisão e não
resultados, dado faltando é o erro comum — e não pode derrubar a tela inteira.

---

## 8. As tarefas

### Fase 0 — Fundação (faz `wfa_runs` bastar sozinho)
| # | Tarefa |
|---|---|
| 0.1 | `ALTER TABLE wfa_runs`: `profile`, `capital`, `sharpes_matriz`; `wfa_store.salvar` grava |
| 0.2 | `sharpe` por configuração em `wfa.agregar` e `wfa._linha_matriz` |
| 0.3 | `planos_operacao` + sequência + cascata nos três pontos de exclusão |
| 0.4 | Função única de chave de parâmetros (float × int), com teste 78.0 vs 78 |

### Fase 1 — A curva certa, com o método certo
| # | Tarefa |
|---|---|
| 1.1 | Bootstrap estacionário em `robustez.py`, bloco calibrado pelo `teste_runs` |
| 1.2 | Horizonte H nas trajetórias e a taxa de desligamento em falso |
| 1.3 | Quarto modo, painel, faixa de portões, `ui/callbacks_candidata.py` |
| 1.4 | Bloco 1 com os dois recortes; sai MAR/CAGR, SQN, `correlacao_lr`, `meses_positivos` |

### Fase 2 — Platô e aleatório
| # | Tarefa |
|---|---|
| 2.1 | Perfil do parâmetro na faixa minerada; largura do platô; abstenção |
| 2.2 | Medir uma vez platô in-sample × recorte OOS e registrar no doc |
| 2.3 | `core/aleatorio.py`: estratificado, calibrado por bisseção, janela a janela |
| 2.4 | Portões 1, 2, 3, 5, 5b |

### Fase 3 — Sorte e tentativas
| # | Tarefa |
|---|---|
| 3.1 | `Φ⁻¹` e os momentos em base diária |
| 3.2 | PSR e minTRL (duas referências) |
| 3.3 | Deflacionado em faixa de N |
| 3.4 | SPA de Hansen sobre a matriz de `faixa_fixas`; portão 8 |

### Fase 4 — Holdout
| # | Tarefa |
|---|---|
| 4.1 | Abrir uma vez, gravar registro imutável, portão 9 |

### Fase 5 — Tamanho e plano
| # | Tarefa |
|---|---|
| 5.1 | CVaR do pregão, contratos, risco efetivo, margem; portões 6 e 7 |
| 5.2 | `core/plano.py`: os seis grupos de campos, gravação, listagem, exclusão |
| 5.3 | Fechar a 5.6 do PLANO-WFA (camada 4 travada ou reotimizável) |

### Fase 6 — Fechamento
| # | Tarefa |
|---|---|
| 6.1 | Rodar a tela inteira na #40 e registrar o veredito real |
| 6.2 | Revisão por agentes |
| 6.3 | `CALCULOS-CANDIDATA.md`, METODOLOGIA, PLANO, README, CHANGELOG |

A 6.1 não é formalidade: com oito portões críticos, é provável que a #40
reprove. **Isso é informação, não defeito** — mas precisa ser medido antes de a
documentação afirmar qualquer coisa.

---

## 9. Testes

| alvo | teste |
|---|---|
| chave de parâmetros | `78.0` e `78` são o mesmo ponto da grade |
| bootstrap | com bloco 1 reduz à permutação; bloco maior aumenta o `dd_p95` em série agrupada |
| horizonte | H menor reduz a taxa de desligamento em falso |
| platô | largura conferida à mão; abstenção com 1/3 ausente; borda ≠ não varrido |
| aleatório | nº de trades bate ±5%; histograma de horário igual ao real; semente reproduz |
| PSR / minTRL | caso com assimetria e curtose conhecidas; `Ŝ ≤ S*` devolve "não aplicável"; radicando protegido |
| Deflacionado | `V[S] = 0 → S* = 0 → DSR ≡ PSR`; `N = 2` dá 0,520 contra `1/√π = 0,564` |
| `Φ⁻¹` | contra valores tabelados |
| SPA | série sem edge dá p alto; série com edge forte dá p baixo |
| contratos | CVaR do pregão à mão; `contratos = 0` reprova; risco efetivo do inteiro |
| portões | cada um passando e reprovando; veredito só olha os críticos |
| plano | grava e lê idêntico; excluir WFA ou mineração leva o plano junto |
| callbacks | `test_callbacks_sem_ciclo` cobrindo o modo novo |

O teste do Deflacionado **não** pode ser "N = 1 volta ao PSR": com N = 1,
`Φ⁻¹(1 − 1/1) = Φ⁻¹(0) = −∞`. A fórmula não degenera, explode — e um teste
assim faria alguém "consertar" a fórmula certa até ele passar. Estava errado na
primeira versão deste documento.

---

## 10. O que fica de fora

- **Outro ativo**: o banco só tem `WIN$N`, de 16/03/2021 a 13/03/2026.
- **Regime de volatilidade**: o recorte de 12 meses cobre a parte que decide.
- **CSCV/PBO**: substituído pelo SPA (§4.3).
- **Catálogo acumulado de tentativas** para alimentar o N do Deflacionado: boa
  ideia, projeto próprio.
- **Capacidade e liquidez**: nesta escala o book do WIN absorve o tamanho sem
  mover preço. O gargalo é margem e o mínimo de 1 contrato.
- **Múltiplas candidatas lado a lado**: é o projeto D.

---

## 11. Os cinco projetos

| # | Projeto | Passos | Quando |
|---|---|---|---|
| **A** | **Candidata** — este plano | 10 | agora |
| **B** | Sincronização com o MT5 | infra | **em paralelo com A** |
| C | Incubação com conferência | 11 | depois de A e B |
| D | Portfólio | 12 | com 2 candidatas |
| E | Execução e monitoramento | 13–16 | depois de C |

**Por que B anda junto** (decisão 8): a incubação custa **calendário**, não
processamento — três meses não se compram com CPU. E a pergunta 1 da incubação,
"o sinal disparou no minuto que o backtest diria?", é a que pega **look-ahead**,
o erro mais caro e mais silencioso que existe em backtest. Começar a gravar
sinais ao vivo já, com os parâmetros atuais, custa jogar um log fora no pior
caso e adianta meses no melhor.

O passo 14 (contrato mínimo — testar o operador, não a estratégia) tem prazo
escrito dentro de E. O passo 16 — monitorar, reotimizar ou aposentar — não
estava na metodologia escrita e foi acrescentado: toda estratégia perde o edge,
e a pergunta é quando, não se.

---

## 12. Referências

- Pardo, R. *The Evaluation and Optimization of Trading Strategies*, 2ª ed., 2008.
- Bailey, D. & López de Prado, M. *The Sharpe Ratio Efficient Frontier*, Journal of Risk, 2012.
- Bailey, D. & López de Prado, M. *The Deflated Sharpe Ratio*, Journal of Portfolio Management, 2014.
- White, H. *A Reality Check for Data Snooping*, Econometrica, 2000.
- Hansen, P. *A Test for Superior Predictive Ability*, JBES, 2005.
- Politis, D. & Romano, J. *The Stationary Bootstrap*, JASA, 1994.
- Harvey, C., Liu, Y. & Zhu, H. *… and the Cross-Section of Expected Returns*, RFS, 2016.
- López de Prado, M. *Advances in Financial Machine Learning*, 2018.
- Aronson, D. *Evidence-Based Technical Analysis*, 2006.
- Vince, R. *The Mathematics of Money Management*, 1992.
