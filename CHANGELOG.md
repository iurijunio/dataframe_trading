# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As razões por trás das decisões ficam em [docs/PLANO.md](docs/PLANO.md).

---

## [Não lançado]

### Adicionado
- **Modo Candidata, parte 1** (`core/candidata.py`, `core/aleatorio.py`,
  `ui/components/candidata_panel.py`, `ui/callbacks_candidata.py`): o quarto
  modo, ao lado de Backtest, Mineração e Walk-Forward. É o passo 10 da
  metodologia — robustez — medido sobre a curva que o otimizador **nunca
  viu**. Desenho em [docs/PLANO-CANDIDATA.md](docs/PLANO-CANDIDATA.md). Nesta
  parte a tela **mostra, mas ainda não reprova**: os portões vêm na parte 2.
  - **A robustez mudou de curva.** A aba Robustez do Backtest mede os trades
    que o otimizador escolheu olhando o resultado. A Candidata mede os trades
    fora da amostra do walk-forward salvo (`wfa_trades`).
  - **E mudou de método.** O Monte Carlo antigo permuta os trades **sem
    reposição**: todas as trajetórias terminam no mesmo lucro, e a dependência
    entre pregões some. Entrou o **bootstrap estacionário** (Politis & Romano,
    1994) sobre o resultado diário: com reposição (o lucro varia, então a
    incerteza do próprio edge entra na conta), em blocos de pregão (o
    agrupamento de ganhos e perdas sobrevive) e com **horizonte** — o
    drawdown é medido até a próxima reotimização, não no comprimento inteiro
    do histórico. A permutação continua, como "risco de ordenação".
  - **Comprimento do bloco pela própria série** (`robustez.bloco_medio`):
    autocorrelação de defasagem 1 do resultado e do seu valor absoluto — a
    volatilidade agrupada com sinal alternado some da primeira e aparece na
    segunda. No walk-forward #3 o bloco saiu 1, e isso é dos dados: a
    autocorrelação fica entre −0,06 e +0,04 nas defasagens 1 a 10, e forçar
    blocos maiores não aumenta o drawdown.
  - **Dois recortes, vale o pior, métrica a métrica**: curva inteira e
    últimos 12 meses (o índice foi de 96 mil a 197 mil pontos dentro da
    amostra). Cada cartão diz de qual recorte e de qual prazo veio o seu
    número, e avisa quando o recorte contém o holdout.
  - **Perdas seguidas contam só pregões operados.** Dia sem trade não
    interrompe a sequência: no #3, 64% dos pregões não têm operação, e a
    contagem antiga mostrava 5 onde a curva real teve 12.
  - **Risco de desligar uma estratégia sadia** (`candidata.risco_de_desligar`):
    a fração das trajetórias simuladas que encosta no limite estando a
    estratégia viva — o preço do disjuntor.
  - **Perfil do platô** (`candidata.perfil_plato`): o fator de recuperação ao
    longo da faixa minerada, com o parâmetro escolhido marcado, a largura do
    platô em passos da grade e **se cada lado parou por queda ou porque a
    grade acabou**. Na #40 as duas larguras são a grade acabando: toda a
    faixa de 40 a 80 fica acima do piso.
  - **Entrada aleatória** (`core/aleatorio.py`): estratégia falsa que sorteia
    as barras de entrada e herda toda a gestão da real, sem tocar no motor.
    Estratificada pela **hora de execução** (a barra reamostrada é carimbada
    pelo fim do período e a entrada acontece no minuto seguinte — sortear pela
    hora do carimbo tirava 5 pontos da abertura na #40), calibrada até o
    número de trades bater, e com p-valor de permutação conservador.
  - **`wfa_runs` guarda perfil, capital e os Sharpes da matriz**, para a
    Candidata não depender de a mineração de origem ainda existir. Os
    walk-forwards salvos antes disso abrem com o aviso "salvo antes desta
    tela".
  - 445 testes (eram 372). Toda conta que vira número de disjuntor tem teste
    que **falha quando a implementação é quebrada de propósito** — dez de doze
    versões defeituosas do bootstrap passavam nos testes da primeira versão.

### Corrigido
- **Sharpe da matriz agregado pelo dia de saída.** O cálculo novo nasceu
  agregando pelo dia de entrada, ao contrário do resto da plataforma
  (`metrics.resumo`, `wfa_store.serie_diaria`): a mesma curva mostraria dois
  Sharpes na mesma tela.
- **Barra lateral do Backtest** deixa de aparecer nos modos em que os
  parâmetros não são escolhidos à mão.
- **Modo Walk-Forward** (`core/wfa.py`, `core/wfa_runner.py`,
  `ui/components/wfa_panel.py`): o terceiro modo, ao lado de Backtest e
  Mineração. Implementa o WFA do Pardo — **reotimizando a cada janela**, que
  é o que a mineração não faz.
  - **A curva de capital fora da amostra, trade a trade.** Cada ponto é uma
    operação, a área vermelha é o afastamento do topo, e as divisórias
    verticais marcam onde a estratégia foi reotimizada. É a coisa mais
    próxima de um track record que se constrói do passado: em nenhum ponto
    dela o otimizador tinha visto o dado que estava operando.
  - **Detalhamento técnico** com uma linha por janela — parâmetros
    escolhidos, datas de IS e OOS, lucro dos dois lados e o WFE — mais a
    linha **DEPLOY**, que otimiza na última janela possível e não tem OOS
    porque o OOS dela é o futuro: é a configuração que se colocaria para
    operar hoje.
  - **Sete inteligências de seleção** decidem quem vence dentro de cada
    janela IS: Moda (Estabilidade), Sharpe (Eficiência), Centroid Média,
    Centroid Mediana, Estabilidade de Drawdown, Probabilidade do Alpha e o
    **Conselho de Notáveis**, em que as seis votam — e a discordância entre
    elas é informação.
  - **Uma varredura, 135 janelas.** As 12 configurações IS/OOS do operador
    somam 135 otimizações; rodadas uma a uma seriam `135 × espaço` backtests.
    O `wfa_runner` roda o espaço **uma vez** e guarda os trades por
    combinação; cada janela vira uma máscara. Medido na #40: 1,9 s de
    varredura, 0,4 MB de cache, e as 12 configurações inteiras em 235 ms.
  - **WFE** nas três leituras, com o global agregado (soma os OOS e os IS
    antes de dividir) como principal e a mediana como secundária. A média
    nunca aparece: uma janela com IS minúsculo a faz explodir.
  - **Os trades da curva OOS ficam gravados** (tabela `wfa_trades`), um por
    linha, com entrada, saída, lado, preços, contratos, custo, motivo de
    saída e excursão. É a matéria-prima do portfólio: correlação de verdade
    pede a série, e exposição simultânea pede saber **quando** cada posição
    esteve aberta — nada disso se reconstrói a partir de um total por janela.
    E são os trades **fora da amostra** de propósito: montar portfólio com
    backtests otimizados é correlacionar dois sobreajustes.
    Junto vêm `serie_diaria()` (o resultado por pregão, que é a menor unidade
    em que duas curvas são comparáveis) e `exposicao()` (os intervalos de
    posição). A reconstrução roda só na hora de salvar — uns oito backtests,
    menos de um segundo — para o cache da varredura seguir cabendo na
    memória com milhares de combinações.
  - **Sub-aba "Parâmetros da vencedora"**, dentro do próprio Walk-Forward.
    A **ficha completa** da janela escolhida — sem escolha, a do **DEPLOY**:
    ativo, estratégia e mineração; os parâmetros da estratégia com os rótulos
    dela; e TODO o perfil de execução — tempo gráfico, horários, dias,
    direção, alvo e stop, proteções, limites diários, custos, posição. Nada é
    específico de uma estratégia (`ui/components/ficha.py`): ela percorre o
    `params_schema` da estratégia e os campos do `ExecutionProfile`, e o
    `ui/components/catalogo.py` só diz como cada campo se apresenta. Um campo
    novo no motor aparece mesmo sem catálogo (em "outros"), e um teste acusa
    que falta rotulá-lo. Campos que dependem de outro somem quando não se
    aplicam (ATR do alvo com alvo em pontos). A barra lateral passou a usar
    as mesmas opções do catálogo — "só compra" é o mesmo texto nos dois
    lugares.
    - Os parâmetros **minerados** ganham, embaixo do valor, a faixa testada e
      **onde o valor caiu nela**. Na borda (ou no último décimo) acende em
      amarelo: o ótimo pode estar do lado de fora do que se testou, e a saída
      é alargar a faixa, não aceitar a borda. Na #40 ela já apontou um caso:
      `periodo_canal = 79` numa faixa que parou em 80. E revelou o que não
      estava em lugar nenhum da tela: a #40 roda em **M15** e **só compra**.
  - **Barra de progresso da varredura**, logo abaixo do Executar e na altura
    dos campos da linha de baixo: "iniciando os processos" (o ~1 s de subir
    os workers no Windows), "varrendo 16 de 41 · falta ~3 s", e no fim
    "41 combinações de 41 · 1,8 s · 0,9 MB", com (?). Enquanto algo calcula, o **Executar desabilita**, os campos travam e
    a **matriz ganha um véu** com o que está acontecendo — um por dono
    (varredura, janelas, matriz), para que o que termina primeiro não libere
    a tela com outro ainda rodando. O véu só aparece se a espera passar de
    250 ms, para não piscar. Em tela estreita a barra desce para uma linha
    própria.
    - Substituiu a primeira versão, que rodava um **backtest da vencedora no
      período inteiro** e mostrava os cartões e a curva dele. Saiu porque
      era uma curva otimizada logo abaixo da fora da amostra: dois lucros
      para a mesma estratégia, e o maior era o que não vale. Com ela saíram
      `ui/components/painel_resultado.py` e `_backtest_de`, que só existiam
      para essa sub-aba.
  - **Os cartões do WFA e do Backtest viraram um só.** `metrics.resumo`
    calcula as métricas de trade a partir de arrays — o `compute` do
    Backtest agora delega para ela — e `stats_cards.cartoes(m, dicas)`
    devolve os cartões chaveados pelo rótulo, com o (?) trocável. O WFA
    monta os seus sobre a curva fora da amostra e intercala os que só ele
    tem (WFE global, janelas positivas, lucro por mês). Ganhou de quebra
    período OOS, bruto e custo, payoff, fator de recuperação, Sharpe e
    Sortino — e a garantia de que dois cartões "sharpe" na plataforma nunca
    discordam.
    - Para o Sharpe OOS agregar pelo **dia da saída**, como no Backtest, o
      cache da varredura passou a guardar `exit_ts` e `custo` além de
      `entry_ts` e `liquido` (32 bytes por trade; a #40 foi de 0,4 para
      0,9 MB). Os campos ficam declarados em `wfa_runner.CAMPOS`, e
      `wfa.trades_oos_campos` recorta qualquer um deles nas janelas OOS.
  - **Matriz de otimização em abas: Consenso + uma por inteligência**
    (`ui/components/wfa_matriz.py`). O **Consenso** cruza as 12
    configurações com as seis inteligências num mapa de calor do WFE
    rolante, com ✓ (ou ⚠, com ressalva) onde os **seis portões** aprovam, e
    ordena por quantas aprovam → WFE mediano → pior WFE. As cinco primeiras
    ficam em destaque e a primeira é a recomendada (★); o maior WFE fica na
    linha só como informação — escolher o pico de 84 variantes é escolher a
    mais sortuda. O Conselho de Notáveis não conta: é a votação das outras
    seis. Cada inteligência tem sua aba com a tabela de sempre (rolante e
    ancorado) mais a coluna de portões, e cada aba tem o seu (?), assim como
    rolante, ancorado, mediana, dispersão e portões.
    - Clicar numa linha abre a configuração no detalhe de baixo — e, na aba
      de uma inteligência, abre também a inteligência. A configuração aberta
      fica com **fundo amarelo** em qualquer aba, e a faixa da matriz diz
      qual é ("aberta IS 18 / OOS 6 · Conselho de Notáveis").
    - Com isso os campos **IS, OOS e inteligência saíram da barra**: escolher
      pela matriz é mais informado que digitar um número. Os componentes
      continuam na página, escondidos, como estado da configuração aberta.
    - **"Estender ao holdout" mudou da curva para o cabeçalho da matriz**:
      ligar recalcula as sete matrizes, e é ali que se decide.
    - A tabela **estica até a borda** da tela (`responsiveSizeToFit`), com a
      largura de cada coluna valendo como mínima.
    - **Custo**: `wfa.preparar` calcula as métricas IS de cada janela uma vez
      e `wfa.matrizes` as divide entre as sete (era ~90% do tempo, idêntico
      para todas). As 7 inteligências × 12 configurações, já com os seis
      portões por célula, saem em **0,87 s** na #40 — contra 4,3 s se cada
      uma refizesse a conta. O resultado fica guardado por varredura e estado
      do holdout; trocar de aba não recalcula. O select de inteligência
      deixou de disparar a matriz.
    - Na #40, quatro configurações são aprovadas pelas seis inteligências
      (IS 10/5, 12/6, 18/6, 15/5), e IS 16/4 tem WFE entre 103% e 119% sem
      nenhuma aprovação nos portões — o tipo de coisa que a tabela antiga,
      uma inteligência por vez, não mostrava.
  - **8ª inteligência: Platô Pessimista** (`"vizinhanca"`). A nota de cada
    combinação é o **pior quarto dos vizinhos dela na grade** (quantil 25% do
    fator de recuperação numa caixa de 5% dos valores de cada parâmetro, pela
    posição do valor — o que resolve passo irregular), contando também os
    vizinhos reprovados nos critérios. Um pico cercado de prejuízo perde para
    um ponto bom cercado de pontos bons; ao contrário das Centroides, não cai
    no vale entre duas ilhas. Parâmetro de texto compara só iguais; sem
    parâmetro numérico, ou sem vizinhança suficiente, cai na Centroid
    Mediana. Vota no Conselho e conta no Consenso. Base: a preferência de
    Pardo por regiões largas e a seleção por "ilhas" em walk-forward
    (Eng. Proc. 2024) — evidência coerente, não conclusiva. Com um parâmetro
    minerado só (a #40), a vizinhança é uma linha; o ganho aparece com dois
    ou mais variando juntos.
  - **Tira-teima** ganhou as colunas **saída** e **custo**.
  - **O holdout aparece na curva fora da amostra.** Com "estender ao
    holdout" ligado, o trecho a partir do corte fica em **amarelo**, com a
    faixa de fundo tingida, a linha tracejada no corte e o rótulo "HOLDOUT" — é o pedaço mais parecido com o
    mercado de amanhã, e antes ele se misturava ao resto da curva. A curva
    também ficou mais alta (400 → 540 px).
  - O painel de drift não lista mais os parâmetros sem gráfico.
  - **Excluir mineração salva**, com dois cliques (o primeiro vira
    "Confirmar?"). Apagar é irreversível e o alvo mora num seletor onde a
    linha errada está a um pixel da certa. Trocar de mineração desarma a
    confirmação. Some junto o que dependia dela: trials e walk-forwards.
  - **Salvar e excluir walk-forwards** (tabela `wfa_runs`). O que se guarda
    não é performance — o resultado é barato de recalcular, o custo está na
    varredura. É o **registro da decisão**: qual mineração, com que janela,
    que inteligência, se o holdout entrou, e a combinação de DEPLOY. Um
    registro por combinação desses; rodar o mesmo de novo substitui em vez de
    empilhar duplicata.
  - **Fita das janelas**: a escadinha IS/OOS desenhada na linha do tempo,
    cinza para otimização e colorido para teste (verde lucrou, vermelho
    perdeu). Mostra de imediato quanto do histórico cada configuração consome
    antes de produzir o primeiro resultado.
  - **Eficiência temporal**: resultado mês a mês da curva fora da amostra,
    com meses positivos, média mensal, mês bom × mês ruim, **tempo médio de
    recuperação** e **maior período sem novo topo** — a métrica que ninguém
    olha e que decide se você continua operando. Mais lucro × prejuízo por
    dia da semana e por hora de entrada, reaproveitando o `core/analytics.py`
    que já servia o backtest.
  - **Tira-teima**: cada operação da curva OOS numa linha, com data,
    resultado, capital acumulado e a janela que escolheu aquele parâmetro.
  - **Veredito do walk-forward**: seis portões na mesma gramática da
    Porteira da mineração — críticos barram, alertas passam com ressalva.
    Lucro OOS > 0, ≥70% de janelas positivas, WFE ≥70%, ≥300 trades OOS
    somados (Pardo: ~30 por janela, dez janelas), drawdown OOS ≤1,5× o pior
    que a otimização viu, e zero janelas fora do mercado. A diferença para a
    Porteira é o que se julga: lá, a região do espaço; aqui, **o processo de
    escolher dentro dela**, medido no único dado que o otimizador nunca viu.
  - **Estabilidade e deriva dos parâmetros**: um gráfico por parâmetro
    mostrando o valor escolhido em cada janela, com volatilidade e veredito
    (estável até 5%, em transição até 20%, instável acima). Parâmetro que a
    mineração varreu com valor único não ganha gráfico — a reta plana não diz
    nada e rouba espaço de quem deriva.
  - **Curva do parâmetro travado**, pontilhada sobre a do walk-forward: quem
    escolheu uma vez na primeira janela IS e nunca mais mexeu. É o
    contrafactual que faltava — se as duas andam juntas, reotimizar não está
    trazendo nada; se a travada fica para trás, a reotimização é o que
    sustenta o resultado.
  - **Matriz de otimização**: as 12 configurações IS/OOS numa tabela só, com
    heatmap por faixa. A pergunta que ela responde não é "qual rendeu mais" e
    sim **de que tamanho de janela a estratégia precisa** — uma que só
    funciona com IS de 24 meses depende de memória longa; uma que funciona em
    quase todas é robusta; uma que só funciona numa configuração não tem
    edge, tem coincidência. Cada linha traz **WFE rolante e ancorado lado a
    lado**: quando o ancorado ganha, o edge é estrutural e antigo; quando o
    rolante ganha, o mercado mudou. Clicar numa linha abre aquela
    configuração no detalhe abaixo.
  - **Botão "estender ao holdout"** no cabeçalho do gráfico — junto de quem
    ele muda, e não no meio da configuração da varredura. Desligado, o
    walk-forward para no corte do holdout — o mesmo período em que a
    mineração otimizou, e por isso comparável com ela. Ligado, avança sobre
    os meses que nenhuma combinação jamais enxergou.
    Ligar **não gasta o holdout**: o walk-forward nunca otimiza sobre dado
    posterior à janela IS de cada passo, então esses meses só podem aparecer
    como resultado, nunca como escolha. Por isso a varredura roda sempre até
    o fim da base, e o botão apenas move o limite da escadinha — a resposta
    é instantânea, sem varredura nova.
  - O retorno da varredura ("41 combinações · 1,9 s · 0,4 MB") ficou numa
    linha própria abaixo da barra: no meio dela, comia a largura dos campos
    que se usam a cada execução.
  - A barra lateral do Backtest **some** neste modo: aqui os parâmetros não
    se escolhem à mão, mudam a cada janela.

### Corrigido
- **O portão de repetição passou a ser por SEMESTRE, e não por janela.**
  Uma janela OOS de 3 meses tem ~25 trades e fecha negativa por puro acaso
  bem mais vezes que uma de 6 meses; simulando o edge da #40 sem degradação
  nenhuma, o portão por janela reprovava IS6/OOS3 em 42% das vezes. Agora
  conta a % de semestres civis (jan–jun, jul–dez) da curva OOS que lucraram:
  só semestres inteiros, e semestre todo fora do mercado não conta contra
  (`wfa.semestres_oos`). O cartão virou "semestres positivos" (com a
  contagem por janela na nota) e a matriz ganhou a coluna "semestres +". Na
  #40, IS6/OOS3 foi de 58% (janelas) para 86% (semestres).
- **Lucro/mês no período comum** na matriz: cada configuração começa a
  operar numa data (IS6/OOS3 em 2021-09, IS24/OOS6 em 2023-03), e comparar
  lucro/mês de períodos diferentes compara mercados diferentes. A coluna
  nova mede todas a partir do OOS que começa mais tarde.
- **A linha "parâmetro travado" virou a faixa das combinações fixas**
  (`wfa.faixa_fixas`): p10–p90 e p25–p75 de TODAS as combinações da
  mineração sem reotimizar, no mesmo período, com a mediana pontilhada e um
  "pNN" curto na ponta da curva (a % das fixas que terminaram abaixo do
  walk-forward). A linha antiga era uma combinação só e enganava: na #40
  sugeria que reotimizar ajudava, mas o walk-forward terminou em p34 — 66%
  das combinações fixas fizeram mais. `wfa.travada` saiu.
- **Drift medido contra a faixa minerada**: desvio dos valores escolhidos ÷
  (máx − mín do espaço), com estável ≤ 5%, em transição ≤ 15%, instável
  acima. Dividir pela média dependia de onde fica o zero da escala. Na #40,
  `periodo_canal` foi de "em transição" (16% da média) para "instável"
  (24% da faixa; percorreu 72% dela).
- **Documentação das contas**: [docs/CALCULOS-WFA.md](docs/CALCULOS-WFA.md)
  descreve cada número da aba Walk-Forward — varredura, escadinha,
  critérios por janela e fora do mercado, inteligências, WFE, Sharpe,
  portões, Consenso, faixa, drift e eficiência temporal —, com exemplos
  reais da #40. A seção de contas do PLANO-WFA, que tinha ficado
  desatualizada, passou a apontar para ele.
- **Critérios por janela: fator de recuperação × f^0,7 e drawdown × f^0,3**
  (f = meses da janela ÷ meses da mineração), no lugar da raiz do tempo e do
  drawdown sem escala. O pior mergulho cresce bem mais devagar que o tempo
  (perto de log t numa estratégia lucrativa), então o FR = lucro ÷ DD sobe
  como f^0,7 — expoente medido por Monte Carlo com parâmetros do WIN (0,6 a
  0,75). A raiz reprovava metade das combinações que estavam exatamente no
  limiar. Na #40: IS12/OOS6 e IS18/OOS6 seguem aprovadas pelas sete; IS8/OOS4
  subiu para 7 de 7 e IS10/OOS5 saiu do top 5.
- **Revisão geral por quatro agentes (motor, estatística, banco e telas).**
  Os dados gravados estão íntegros (nenhum órfão ou duplicata; o #3 confere
  trade a trade; o espelho Parquet bate linha a linha) e os trades salvos
  reproduzem exatamente os da tela em 32 cenários. O que estava errado:
  - **Tela presa em "montando as janelas…"** depois de um F5 no meio da
    varredura ou de qualquer erro do cálculo: só o caminho de sucesso
    marcava o resultado como entregue. Agora toda saída marca (inclusive
    exceção, que vira mensagem na barra), e ao voltar ao modo a estratégia e
    a mineração da varredura em memória são restauradas.
  - **Estatística t e Sharpe explodiam com trades de valor idêntico**: 35 ×
    R$ 36,56 dão desvio de 7e-15 por arredondamento, não zero, e o t saía
    3e16 (o Alpha escolhia essa combinação). Tolerância relativa nos dois.
  - **Excluir mineração deixava os trades do walk-forward órfãos.**
  - **Gravação de mineração sem transação e lenta**: interrompida no meio,
    ficava "concluida" com parte das combinações; ~9 ms por combinação com o
    banco trancado para a tela. Agora é uma transação só, em lote por Arrow
    (20 mil combinações em poucos segundos), e a subida do app marca como
    `incompleta` o que foi gravado pela metade antes disto. O walk-forward
    salvo e a exclusão também são atômicos.
  - **Leituras da tela quebravam durante uma gravação** ("different
    configuration" do DuckDB no mesmo processo): a leitura espera a vez. A
    espera só vale para banco ocupado — outros erros sobem na hora.
  - **O walk-forward usava o ativo da barra do topo**, e não o da mineração;
    o cache só é reaproveitado se for da mesma mineração no mesmo ativo.
  - **DEPLOY treinado com meses de atraso**: a escadinha era alinhada pelo
    começo da base e a sobra ia para o fim (IS10/OOS5 otimizava até maio com
    dados até setembro). Agora é alinhada pelo fim.
  - **Varreduras começavam sozinhas** (trocar de mineração no meio de uma
    fazia o fim dela disparar outra) e **o Executar varria de novo com o
    cache pronto**. Varredura só por pedido — Executar ou walk-forward salvo
    — e o Executar reaproveita o cache.
  - **Cada clique em IS/OOS recalculava a matriz, a lista de salvos e a
    ficha**: o `dcc.Store` redispara a cada escrita, mesmo com o mesmo valor
    (o comentário no código dizia o contrário). Só é regravado quando muda.
  - **Matriz velha visível e clicável durante uma varredura nova**; **holdout
    alternável durante o cálculo** (fica desabilitado enquanto a matriz
    calcula); **dois cálculos simultâneos da mesma matriz** (lock).
  - **Excluir walk-forward salvo com um clique e sem limpar o seletor**:
    agora dois cliques, como na mineração, e o seletor é limpo. **Carregar um
    walk-forward cuja mineração foi excluída** avisa, em vez de trocar por
    outra em silêncio. **A ficha lia a mineração do seletor**, e não a do
    cálculo.
  - **Limite de memória da varredura era só aviso** e **varredura
    interrompida era entregue como completa**: as duas agora abortam sem
    cache. `iniciar` e a publicação do resultado ficam sob lock.
  - **Eficiência temporal ignorava os meses sem trade** e começava a curva
    sem o zero; o tempo médio de recuperação contava o mergulho ainda em
    curso. **Drift quebrava com parâmetro de texto** e chamava de "estável"
    um parâmetro de média zero que oscilava.
  - **Recriar tabela quebrava num ";" dentro de comentário** do schema, e a
    comparação de colunas levava a ordem em conta — as duas podiam derrubar
    a subida do app.
  - **Performance**: a matriz de 2.000 combinações × 12 configurações caiu de
    74 s para 24 s, com resultados idênticos (conferidos): o Conselho
    reaproveita as escolhas das votantes na mesma janela, o Platô Pessimista
    lê os vizinhos pelo endereço na grade em vez de comparar contra a grade
    inteira, as janelas são recortadas por busca binária e a matriz pula o
    DEPLOY.
  - **Visual**: números no padrão brasileiro em hovers, tabela da matriz e
    fita; (?) nas colunas das Janelas, da matriz e na curva; o (?) abre pelo
    teclado; o (?) da dispersão deixou de chamar ruído de amostra de
    problema.
- **Revisão das inteligências de seleção** (dois agentes: um conferindo o
  cálculo contra casos de resposta conhecida, outro pesquisando a
  literatura). As fórmulas estavam certas; as bordas, não:
  - **O walk-forward rodava sem critérios de aceite.** A decisão 8 ("os
    critérios valem dentro de cada IS") existia no motor, mas a tela nunca
    os passava: qualquer combinação era candidata, inclusive a que perdia
    dinheiro no próprio IS. Na #40 isso aconteceu em 19 escolhas. Agora os
    critérios da mineração salva — gravados ao salvar, coluna `criterios` em
    `mining_runs`; as antigas usam os padrões — são trazidos para o tamanho
    de cada janela por `wfa.criterios_por_janela`: trades e lucro
    proporcionais ao tempo, fator de recuperação pela raiz do tempo, PF e
    drawdown como estão, e um piso de **30 trades** para ser candidata. O
    resumo diz de onde vieram ("critérios da mineração" / "padrão").
  - **Desvio zero virava infinito.** Dois trades iguais davam estatística t e
    fator de recuperação infinitos, e a combinação de 2 trades vencia seis
    das sete inteligências. t passa a 0 sem variação, e o infinito do FR,
    como chave de ordem, vale o maior valor finito da janela.
  - **A ancoragem de Moda e Centroides procurava entre todas as aprovadas** e
    podia cair numa perdedora no meio de duas boas (−R$ 5.000 no caso de
    teste). Agora ancora dentro do decil, com empate decidido pelo FR.
  - **O Conselho desempatava pelo FR num 2-2-2**, contra a documentação;
    agora qualquer empate no topo vai para o centroide mediano dos
    indicados, e o vencedor sempre tem voto (antes podia sair "0 de 6").
  - **Decil com um elemento só** transformava as de platô em escolha de pico:
    agora tem no mínimo 3. Empates (Ulcer zero, Sharpe igual) decidem pelo
    lucro, e não pela ordem da grade.
  - **Sharpe e Sortino ignoravam os pregões sem trade** — em toda a
    plataforma. Quatro trades num ano davam Sharpe na casa das centenas. Os
    dias parados entram como zero (`wfa.sharpe_diario`, usado também por
    `metrics.resumo`), e o Sortino passou a usar o desvio das perdas, que é a
    definição. **Os Sharpe exibidos caem**: o OOS da #40 foi de 2,33 para
    1,25.
  - **Antes × depois na #40** (sem holdout, critérios padrão): IS12/OOS6
    Centroid Mediana foi de R$ 4.532 / WFE 104% para **R$ 4.240 / 96,4%**,
    ainda aprovado. No Consenso, quatro configurações aprovadas por todas
    viraram duas (IS 12/6 e 18/6, 7 de 7). Escolhas com prejuízo no IS: 0.
- **O esquema do banco só era aplicado ao salvar uma mineração.** Uma coluna
  nova não existia até alguém salvar, e a primeira leitura quebrava. Agora
  `init_schema` roda na subida do app.
- **O mapa de calor das colunas de WFE da matriz nunca pintava.** Os cortes
  eram 90/70/50/30, mas o WFE vem em fração (1,04 = 104%): nenhuma célula
  passava do primeiro corte. Agora 0,9/0,7/0,5/0,3.
- **O portão de drawdown das linhas da matriz passava sempre.** A matriz
  agregava sem a curva OOS, e o drawdown OOS saía zero. Cada célula agora
  recebe a curva e é julgada pelos seis portões de verdade.
- **Escolher um walk-forward salvo não carregava nada.** O seletor só
  habilitava o Excluir; nenhum callback o ouvia. Agora `wfa_carregar_salvo`
  devolve à tela a decisão gravada — estratégia, mineração, IS, OOS,
  inteligência, holdout e nome — e o cálculo refaz curva, cartões, janelas e
  matriz (com varredura nova, se o cache em memória for de outra mineração).
  Um Store (`store-wfa-carregar`) força o cálculo mesmo quando os valores
  gravados já são os da tela. `wfa_mineracoes` deixou de atropelar a
  mineração escolhida pelo registro com a mais recente da lista.
  - Conferido com a página recém-aberta: o #3 volta com 551 trades,
    R$ 5.449,00 e WFE 101,6%, os mesmos números gravados.
  - O #3 tinha sido salvo por um script de verificação que passou o fim da
    base como corte do holdout: os trades incluíam o holdout, mas a marca
    dizia que não. A marca foi corrigida no banco.
- **Ciclo latente entre a estratégia e o seletor de mineração salva.**
  `trocar_estrategia` (ouvia `estrategia`, limpava `mine-carregar`) e
  `restaurar_config` (ouvia `mine-carregar`, trocava `estrategia`) eram cada
  um Input do outro — o mesmo desenho que congelou a barra do walk-forward.
  Nunca travou porque os dois lados só disparavam por clique, nunca juntos.
  Viraram um callback só, `estrategia_ou_mineracao`, dono das duas
  propriedades, que decide o que fazer por `ctx.triggered_id`:
  - trocar a estratégia à mão continua zerando a tela **e** limpando o
    seletor da mineração carregada;
  - carregar uma mineração de outra estratégia continua trocando a
    estratégia e remontando os parâmetros com as faixas dela.

  Um callback não espera por si mesmo: o renderer desconta dos Inputs as
  próprias Outputs, e escrever `estrategia` de dentro dele não o dispara de
  novo. Por isso sumiu também o remendo `nome == MINERACAO.estado["estrategia"]`,
  que existia só para a troca disparada pelo carregamento não apagar a
  varredura recém-carregada. De brinde, `progresso` (que confere a
  estratégia antes de encher a tabela) agora roda garantidamente depois da
  troca, porque `mine-carregar` é saída do dono.
- **`tests/test_callbacks_sem_ciclo.py` passou a modelar a regra do renderer.**
  O grafo antigo era por propriedade e acusaria ciclo dentro de um único
  callback que lê e escreve duas propriedades. Agora é um grafo de
  **retenção entre callbacks**, como `getReadyCallbacks` do dash-renderer: A
  fica retido por B se um Input de A que não é Output do próprio A está no
  alcance transitivo das saídas de B. Três testes novos cobrem o desenho
  antigo (trava), o dono único (não trava) e o anel com um terceiro no meio
  (trava). `CICLOS_CONHECIDOS` ficou vazio.
- **Walk-forward entrava em laço e a barra de progresso congelava.** Dois
  defeitos que se alimentavam:
  - o `wfa_executar` ouvia o **relógio** e refazia o walk-forward inteiro a
    cada batida (800 ms), mesmo com o resultado já na tela. Quando o cálculo
    passava da batida, o servidor enfileirava, as respostas chegavam depois
    do disparo seguinte e o Dash as descartava — inclusive a do `pulso`, que
    desligaria o relógio. O laço não saía mais (~20 requisições por segundo
    com a tela parada). Agora o fim da varredura é anunciado **uma vez** por
    `store-varredura` (callback `wfa_fim_da_varredura`), e é ele que dispara
    o cálculo;
  - o Dash **segura** um callback enquanto qualquer entrada dele é saída de
    outro ainda pendente. A primeira versão da barra gravava o Store que
    dispara o cálculo e ouvia o `store-wfa` que o cálculo grava: um ciclo, e
    cada lado esperava o outro. Sem `debug`, nenhum erro aparece — a tela só
    para. Novo teste `tests/test_callbacks_sem_ciclo.py` monta o grafo de
    dependências do app inteiro e reprova qualquer ciclo; o único antigo
    (`estrategia ↔ mine-carregar`, na Mineração) ficou listado como conhecido.
  - As travas (`running=`) marcam divs **irmãs** dos campos, e o CSS trava
    pelo seletor `~`. Envolver os campos numa div cuja classe muda
    re-renderizaria os `dcc.Input` a cada cálculo.
- **A barra lateral virou uma linha e engoliu as próprias seções.** O callback
  de modo devolvia `display:flex` para o `<aside>`, que é um bloco comum de
  largura fixa — como flex sem direção definida, ele vira container de
  **linha**, e Período, Estratégia, Parâmetros e Execução se enfileiraram na
  horizontal. Só a primeira cabia nos 342 px; o resto sumia no corte do
  `overflow`. Agora volta como `display:block`.
- **O painel do Walk-Forward não ocupava a tela.** Mesma falha, no outro
  lugar: `#painel-wfa` não tinha a classe `modo-bloco`, então o `display:flex`
  do callback o fazia container de **linha**, e o conteúdo encolhia para a
  largura natural — sobrava um vazio à direita, exatamente onde antes ficava
  a barra lateral. A classe passou para o elemento que o callback liga e
  desliga, e o `painel()` devolve uma lista em vez de um `Div` a mais.
- **A mineração travava a tela enquanto rodava.** Distribuição, Porteira e
  Critérios ouviam o `rowData` da tabela, que o progresso reescrevia a cada
  batida de 800 ms — cada batida disparava três recálculos sobre até 5.000
  combinações, e a interface congelava justamente quando ela precisa
  responder ao "Parar". As três passaram a ouvir um store que só muda quando
  a varredura **termina**, e leem as combinações do servidor em vez de
  recebê-las pelo callback: 5.000 dicionários não precisam viajar até o
  navegador e voltar só para serem somados. Durante a varredura elas mostram
  "aguardando o fim", e a interface segue fluida — medido em 170 fps com
  1.586 combinações em curso.
- **Engasgos ao redesenhar a tabela e a nuvem.** As duas acompanhavam a
  cadência de 800 ms do relógio, com milhares de linhas atravessando a cada
  vez. Ganharam uma folga de 2 s; o texto do progresso e a barra continuam na
  cadência cheia, que é o que dá a sensação de varredura viva. Ao terminar, a
  tabela sempre recebe a versão final, inteira.
- **O Walk-Forward sequestrava a tela do Backtest.** A primeira versão do
  "mandar vencedora ao Backtest" escrevia nos campos do outro modo e trocava
  a aba — acoplando dois módulos que não deviam se conhecer, disputando o
  estado dos parâmetros com o callback que os remonta, e, do lado de quem
  usa, alterando uma tela que ninguém pediu para alterar. Foi substituída por
  uma sub-aba dentro do próprio Walk-Forward, com o painel de resultado
  extraído para componente reutilizável. O modo Backtest não é mais tocado.
- **A varredura terminava rápido demais para o relógio.** Com 41 combinações
  ela acaba em 1,4 s — antes de o `pulso` ligar o relógio. O resultado ficava
  pronto no servidor e a tela travada num "varrendo… 0/41" eterno. O relógio
  passou a bater até a tela **desenhar** o resultado, e não até a varredura
  terminar.
- **A fita das janelas derrubava o callback inteiro.** `np.timedelta64` não
  atravessa a serialização JSON do Plotly: *"Object of type timedelta is not
  JSON serializable"*. Como o erro acontecia na serialização, nada aparecia
  na tela e nada explicava. A largura da barra passou a ir em milissegundos e
  a base como texto ISO — com o eixo declarado como data, sem o que o Plotly
  ignora a base e todas as barras nascem em zero.
- **O WFE aparecia como "1,0%" em vez de "104,0%".** O valor vem em fração
  (1,04) e o limiar dele é escrito em porcento; testar o "%" do limiar antes
  do nome fazia cair no ramo errado. O portão aprovava e o número dizia o
  contrário — o tipo de coisa que faz duvidar da tela inteira.
- **A matriz nascia vazia por corrida entre ticks.** O `tick` era Input do
  callback da matriz; o cálculo das 24 configurações leva ~1 s, e o tick
  seguinte respondia `no_update` na hora — o Dash descarta a resposta mais
  velha para o mesmo output, e as linhas calculadas iam para o lixo. A tela
  ficava com a matriz vazia e **nenhum erro em lugar nenhum**. Quem avisa que
  a varredura acabou passou a ser o `store-wfa`, com um valor estável que
  muda uma vez só.
- **O relógio não sabia do botão do Walk-Forward.** `pulso` só ouvia os
  botões da Mineração, então a varredura do WFA rodava por baixo e a tela
  ficava congelada em "varrendo o espaço…" para sempre. Pior: havia corrida
  — `pulso` e `wfa_executar` disparam juntos no clique, e quando o pulso
  vinha primeiro ainda via `rodando=False`. Um `dcc.Store` escrito pelo
  `wfa_executar` acorda o relógio depois que a varredura já começou.
- **`lucro por mês` do WFA dividia só pelos meses OPERADOS.** Se a estratégia
  ficou fora do mercado em 6 de 16 janelas, esses meses passaram do mesmo
  jeito — a conta inflava justamente quem menos operou. Agora há duas
  contagens: operado (base do WFE, simétrica dos dois lados) e calendário
  (base do lucro por mês).
- **`docs/PLANO-WFA.md`** — o plano da aba Walk-Forward: as 6 fases, as sete
  inteligências de seleção, as fórmulas escritas antes do código e a decisão
  que torna a matriz de 135 janelas viável (rodar o espaço uma vez e fatiar
  os trades, em vez de 135 varreduras).
- **Seletor de ativo no topo.** O símbolo saiu do código — `SYMBOL = "WIN$N"`
  estava cravado em `ui/app.py` e `ui/callbacks.py` — e passou a vir da
  tabela `instruments`, listando apenas os que têm barras. Acrescentar um
  ativo virou ingerir um CSV, e não editar Python.

### Alterado
- **A seção "Walk-forward" da Mineração virou "Consistência entre períodos".**
  Ali os parâmetros são FIXOS em todas as janelas: o que se mede é
  consistência, não walk-forward. O walk-forward de verdade — que reotimiza a
  cada janela — é o terceiro modo, em construção.
- **Aba Porteira** (`core/porteira.py` + `ui/components/mine_porteira.py`): o
  veredito sobre a **varredura inteira**, e não sobre uma combinação. Uma
  mineração pode ter dez combinações aprovadas nos critérios e ainda assim
  ser lixo, se essas dez forem exceções num universo que não funciona.
  - **Os números**: total de resultados, positivos, negativos, média, desvio
    padrão, **Z-score**, **média − 3σ**, dispersão relativa (σ ÷ média),
    assimetria e curtose.
  - **Nove portões** com passa/reprova, separados em **críticos** (barram a
    varredura) e **alertas** (passam com ressalva). O veredito tem três
    estados — aprovada, aprovada com ressalva, reprovada — porque reprovar
    por não atingir três sigma reprovaria quase toda varredura real.
  - **Régua dos desvios**: a média com as faixas de ±1σ, ±2σ e ±3σ e a marca
    do zero. Quando o zero cai dentro da faixa, a região está a um passo do
    prejuízo — e isso se vê antes de ler qualquer número.
  - **Z-score e "média − 3 desvios" são a mesma conta**: `média − 3σ > 0` é
    idêntico a `Z > 3`, uma escrita em reais e a outra em desvios. Os dois
    aparecem na tela porque cada um se lê melhor num contexto.
  - **Não se multiplica por √N aqui**, ao contrário do SQN. Lá o N são
    trades, e mais trades é mais evidência; aqui o N são as combinações que
    você escolheu testar, e testar mais não prova nada — inflaria o número de
    graça. Há teste garantindo que a nota não sobe com o tamanho da varredura.
  - **Nada de teste t sobre as combinações**: vizinhos na grade compartilham
    quase todos os trades, então elas são fortemente dependentes e qualquer
    p-valor calculado sobre elas seria absurdamente otimista.
- **SQN (System Quality Number)** de Van Tharp na aba Robustez do backtest:
  √N × média ÷ desvio dos resultados dos trades, com o N limitado a 100 pela
  regra do próprio Tharp — sem o teto, dez mil trades medíocres bateriam
  quinhentos excelentes só pelo volume. Faixas de referência no (?).
- **Análise da varredura em abas** (`core/mineracao_stats.py` +
  `ui/components/mine_charts.py`, `mine_regiao.py`, `mine_criterios.py`), no
  mesmo padrão do Diagnóstico do backtest: **Dispersão · Distribuição ·
  Critérios**. A ordem é a do método — primeiro *onde* está a região boa,
  depois *como é* a região inteira, e só então *quem passa* nos números
  fixados. A tabela de resultados continua abaixo, comum às três.
- **Distribuição dos resultados** (passo 5 da metodologia). Depois de varrer,
  a pergunta que decide não é "qual foi o melhor?" e sim "como está a
  região?". Cinco cartões e dois gráficos:
  - **% de combinações lucrativas** — acima de 70% é platô, e escolher o
    ponto dentro dele é detalhe; abaixo de 30% o campeão é a sorte da região.
  - **mediana da região** — a expectativa honesta de escolher um ponto
    qualquer, que é a situação real no futuro.
  - **melhor ÷ mediana** — até 3× o campeão ainda pertence à região; acima de
    10× ele é o ponto que mais se ajustou ao passado.
  - **meio da região** (p25–p75) e **% das combinações com ≥ 60% de janelas
    positivas**.
  - **histograma** com curva acumulada e **curva das combinações ordenadas**,
    onde a forma responde direto: descida suave é platô, degrau nos primeiros
    por cento é precipício. Ambos com seletor de métrica.
  - É o antídoto prático contra sobreajuste: se a região inteira funciona,
    não foi um ponto escolhido por sorte — não importa quantas varreduras
    rodaram até chegar ali.
- **Painel de critérios** (passo 7). Sete limiares configuráveis — operações,
  profit factor, fator de recuperação, janelas positivas, mediana por
  período, drawdown e lucro —, o veredito em cartões, o gráfico de **quem
  passa em cada critério** com o gargalo em vermelho, e a **lista de
  aprovadas** clicável, que carrega os parâmetros e roda o backtest como a
  dispersão e a tabela já faziam. Campo vazio desliga aquele critério; valor
  ausente na combinação não conta como reprovação (fator de recuperação fica
  vazio quando o drawdown é zero — é a combinação que nunca afundou).
- **`docs/METODOLOGIA.md`** — os 15 passos da metodologia Data N Quant, o que
  cada um decide, o que a plataforma já atende e o que falta. Fecha com as
  dez adições possíveis, cada uma encaixada no passo a que pertence.
- **Aba Detalhes** (`core/detalhes.py` + `ui/components/detalhes_cards.py`):
  onde a Robustez pergunta *"isto é sorte?"*, esta pergunta **o que ajustar**
  — e cada bloco aponta para um campo da camada 4 ou para a lógica do sinal.
  - **Sequências** — média e máximo de ganhos e de perdas em fila. A média
    importa mais que o máximo: um recorde de 13 derrotas assusta, mas se a
    média é 1,6 aquilo foi um evento; média 4 é drawdown estrutural, e aí o
    stop diário deixa de ser exagero. Junto vem *"depois de N perdas"*: a
    expectativa do próximo trade condicionada a 1, 2 e 3 derrotas seguidas —
    se despencar, pausar o dia melhora o resultado; se ficar igual, pausar só
    tira trade bom.
  - **Eficiência da operação** — separa o mérito da ENTRADA (quanto do
    intervalo percorrido foi a favor; baixo = gatilho adiantado) do mérito da
    SAÍDA (quanto do pico do trade sobrou no fechamento; baixo = lucro
    devolvido), mais MFE ÷ MAE e quantos trades encostaram no alvo e saíram
    por outro motivo. Mexer no alvo quando o problema é o gatilho não leva a
    lugar nenhum.
  - **Risco por trade** — VaR e CVaR 95%, pior perda sobre perda média,
    desvio, e **stops furados** (saídas por stop piores que o stop, já fora o
    slippage configurado — sem esse desconto *toda* saída por stop apareceria
    como furada).
  - **Exposição e ritmo** — percentual do tempo com posição aberta, pregões
    operados sobre pregões do período, trades por pregão e o máximo num dia,
    dias positivos, melhor e pior dia, mais um gráfico de resultado por
    número de trades no pregão: se as faixas altas concentram prejuízo, o
    limite de operações por dia deixa de ser palpite.
- **Os três cartões de diagnóstico saíram do topo** — *perdas seguidas*,
  *saídas por motivo* e *barras ambíguas* agora moram no bloco "Diagnóstico
  do motor", dentro de Detalhes. O topo ficou só com o que se lê **antes** de
  decidir se a estratégia merece mais tempo.
- **(?) também nos cartões do topo.** Período, lucro líquido, drawdown,
  profit factor, win rate, payoff, expectativa, fator de recuperação, Sharpe
  e trades — cada um com o que é e que faixa é boa ou ruim.
- **Aba Robustez** (`core/robustez.py` + `ui/components/robustez_cards.py`):
  a peneira do candidato, focada em *quanto disto é sorte* — não em moldar
  parâmetro, que é trabalho do walk-forward.
  - **Monte Carlo** reembaralhando a ordem dos mesmos trades: percentis do
    drawdown máximo e onde o drawdown observado cai nessa distribuição. O
    lucro final não muda com a ordem; o caminho, sim.
  - **Maiores mergulhos** com data de início, fundo, profundidade e quantos
    dias levou para recuperar — o max drawdown diz quanto se perde, não por
    quanto tempo se fica no vermelho.
  - **Significância** da expectativa (t, p-valor, confiança), com o número de
    trades que faltaria quando não é conclusiva; **teste de runs** para
    detectar perdas em bloco; **correlação LR** da curva contra a reta.
  - **Concentração**: lucro sem os 5, 10 e 20 melhores trades e o peso do
    maior. Se cair para prejuízo sem os cinco maiores, não é sistema.
  - **Ulcer Index** e **MAR**, para ranquear candidatos entre si.
  - **Meses positivos** e a maior sequência de meses negativos.
  - **Custo que zera** a estratégia, com a folga sobre o que você paga hoje.
- **Cada métrica tem um (?)** dizendo o que é e que valores são bons ou
  ruins. Número sem faixa de referência não sustenta decisão: "Ulcer 8,4" só
  vira informação quando se sabe que abaixo de 5 é confortável. O texto mora
  junto do cartão que explica, para mudar a métrica e esquecer a explicação
  ficar difícil.
- **Diagnóstico do backtest em abas** (`core/analytics.py` +
  `ui/components/analytics_charts.py`). Cartões e curva de capital continuam
  no topo; o detalhe fica em três abas para não virar parede de gráfico:
  - **Operações** — a lista de trades, como antes.
  - **Tempo** — lucro por hora de entrada, por dia da semana, por mês do ano
    e o calendário ano × mês. Cada um responde a um campo da camada 4:
    encurtar a janela, desligar um dia, ou reconhecer que a estratégia vive
    de um regime só.
  - **Gestão** — MAE × MFE por trade com as linhas de stop e alvo, lucro por
    tempo em posição, por motivo de saída e a distribuição dos resultados.
- **Leituras acionáveis de MAE/MFE.** O MAE dos vencedores diz quanto de
  prejuízo temporário foi preciso aguentar para ganhar; o MFE dos perdedores,
  quanto de lucro eles mostraram antes de virar. Quando os números são
  conclusivos (≥20 trades do lado), a aba Gestão escreve a leitura — *"nenhum
  ganhador passou de 423 pontos contra, metade do stop de 900"* — sem afirmar
  o que mudar. A decisão continua sua.
- Nas barras, a expectativa por trade vira linha sobre o total: é ela que
  decide um corte, porque um horário com 400 trades e −R$ 2 cada sangra mais
  que um com 3 trades e −R$ 90.

- **Hora, dia da semana e mês viraram ganho × prejuízo**, duas barras lado a
  lado em vez de uma barra de saldo. O saldo sozinho engana: um horário que
  fecha em zero pode ter girado R$ 25 mil de cada lado — muito trade, muito
  custo, nenhum resultado. A linha do saldo continua por cima.
- **Distribuição dos resultados relegível.** Largura de balde arredondada
  para 1/2/2,5/5 × potência de dez e alinhada ao zero (antes eram baldes de
  R$ 37,4189 e um deles cruzava o zero misturando ganho com prejuízo);
  barras coladas, para a silhueta aparecer como forma e não como serrilhado;
  cauda aparada no p1/p99 com o que ficou de fora contado no rodapé; e
  mediana e média marcadas — média longe da mediana é o aviso de que o total
  depende de poucos trades grandes.
- **Os gráficos abrem enquadrados nos dados**, não no zoom que a biblioteca
  escolhe. A curva de capital mostra o backtest inteiro e o gráfico de preço
  mostra a janela carregada, via `timeScaleAction: fitContent`. O `nonce` do
  comando muda a cada execução — sem ele o componente ignora a repetição e o
  gráfico herda o zoom do backtest anterior. A curva perdeu também a folga
  de 6 barras à direita, que só encolhia o desenho.

### Corrigido
- **A Porteira julgava as 5.000 melhores combinações, não a varredura.** O
  `_ranking` corta a tabela em 5.000 linhas — e corta pelo **topo**, ordenado
  por score robusto. Como a porteira, a distribuição e os critérios liam o
  `rowData` da tabela, acima de 5.000 combinações eles passavam a julgar só a
  metade boa, com viés para cima. Numa varredura medíocre de 8 mil pontos, o
  veredito ia de **reprovada** (média R$ 190 · 57% positivas · Z 0,19) para
  **aprovada com ressalva** (média R$ 796 · 93% positivas · Z 1,20). Agora o
  optimizer mantém `estado["resumo"]` com TODAS as combinações válidas — oito
  números por linha, que não viajam para o navegador — e a estatística lê de
  lá. A contagem de aprovadas vale sobre todas; a lista clicável continua
  saindo das linhas exibidas, e o selo avisa quando os dois conjuntos diferem.
- **CVaR calculado sobre 31% da amostra e rotulado como "os 5% piores".** A
  cauda vinha de `liquido <= percentil_5`, e com stop fixo em pontos dezenas
  de trades fecham exatamente no valor do percentil — todos entravam. Num
  caso real de 100 trades a média saía de 31 deles, puxada na direção do VaR:
  −R$ 516 em vez de −R$ 600. O erro era para o lado **otimista**, no número
  que dimensiona posição. Agora a cauda são os k piores, k = 5% arredondado
  para cima, e o cartão informa quantos trades entraram na conta.
- **"Critério que mais corta" apontava um critério que não avaliou ninguém.**
  Um critério ligado cujo dado não existe em nenhuma combinação (fator de
  recuperação fica vazio quando o drawdown é zero) ficava com 0% e vencia o
  `min()`: barra vermelha em 0% no funil ao lado de "aproveitamento 100%".
  Agora o gargalo só considera critérios que puderam ser respondidos, o funil
  não os desenha, e o cartão lista quais ficaram sem dado.
- **Eficiência da saída escondia o tamanho da amostra.** A média exclui os
  trades que nunca andaram a favor — que são justamente os piores — e a tela
  não dizia isso: 80% parecia a eficiência de todos quando era a de metade.
  O cartão agora mostra "sobre N de M trades", e o (?) explica o caso
  negativo. Sem amplitude nenhuma, entrada e saída devolvem "—" em vez de
  0,0% em vermelho, que se lia como "péssima" onde o certo é "indisponível".
- **`max_drawdown_pct` tinha o nome da outra métrica do MT5.** O código
  calcula o *Balance Drawdown Maximal* (maior mergulho em dinheiro, com o
  percentual daquele ponto), e a documentação o chamava de "rebaixamento
  relativo" — que no MT5 é o *Balance Drawdown Relative*, o maior mergulho em
  percentual, que pode estar em outro ponto da curva. Os nomes foram
  corrigidos e o número que faltava entrou como `max_drawdown_rel_pct`.
- **`LIMIARES["z_forte"]` era anunciado como configurável e ignorado** — o
  portão dos três sigma comparava `média − 3σ > 0` cravado. Agora o limiar
  vale, e o nome do portão acompanha (`5 desvios (média − 5σ)`).
- **Z-score 0,00 numa região que só perde.** Sem dispersão e com média
  negativa o fallback devolvia zero, que se lê como "neutro"; agora devolve
  −∞, e a tabela de portões formata infinito como ∞ / −∞ em vez de `inf`.
- **`profit_factor` era o único campo do ranking sem passar pelo `_num`** — a
  mesma combinação aparecia diferente conforme viesse da varredura ou do banco.
- **A linha do zero esticava o histograma.** Numa varredura em que todas as
  combinações lucram, a linha vertical do zero forçava o eixo a partir dele e
  espremia os dados no canto direito — dois terços do gráfico em branco.
  Agora ela só é desenhada quando o zero cai dentro da faixa dos dados.
- **O max drawdown dizia "% do capital" e mostrava o % do pico.** A conta
  divide o mergulho pelo pico do momento — que é o rebaixamento relativo, o
  que o MT5 reporta e a base certa para comparar sistemas — mas o rótulo
  falava em capital. Os dois divergem assim que a curva sobe: R$ 791 são 5,5%
  de um pico de R$ 14.382 e 7,9% dos R$ 10.000 depositados. Agora o cartão
  mostra **os dois, nomeados**, e `metrics.compute` devolve
  `max_drawdown_pct_capital` junto de `max_drawdown_pct`.
- **O balão do (?) era cortado pela aba.** Ele era um `::after` do próprio
  (?), e dentro de um container com `overflow` não existe CSS que faça um
  pseudo-elemento escapar do recorte: sumia por cima nos cartões da primeira
  linha e por fora nos das laterais. Agora `ui/assets/dica.js` mantém um
  único nó preso ao `<body>` em `position: fixed` e o posiciona a cada
  hover — virando para baixo quando não cabe acima, grudando na borda quando
  não cabe de lado, e sumindo ao rolar.
- **Valor de cartão truncado.** "independentes" virava "independen…" e
  "-R$ 16.920,08" virava "-R$ 16.920,0…": o corpo de 22px é feito para
  dígitos. Valores em palavras passaram a ter corpo próprio e quebrar linha,
  e valores numéricos longos encolhem um ponto conforme o comprimento e a
  largura do cartão. A nota de rodapé do cartão também quebra em até duas
  linhas em vez de virar reticências.
- **Distribuição dos resultados ilegível na célula da grade.** Os rótulos de
  mediana e média eram escritos dentro da área do gráfico e caíam um sobre o
  outro sempre que os dois valores ficavam próximos — que é o caso comum.
  Foram para uma única linha no topo, com as linhas verticais mantidas. E
  como estratégia de stop e alvo fixos produz uma distribuição de picos
  (quase todo trade termina exatamente no stop ou no alvo), entrou a curva
  **acumulada** no eixo da direita: ela lê bem justamente onde as barras não
  leem, e responde de imediato "quantos por cento dos trades perderam".
- **A lista de minerações mostrava as da estratégia anterior.** A troca de
  estratégia não era Input do callback que monta a lista, e o relógio fica
  parado quando não há varredura correndo — então a lista podia ficar
  desatualizada por tempo indeterminado. Continua filtrada pela estratégia
  ativa: varredura de outra não tem o que fazer ali, porque os parâmetros
  dela não existem nos campos.
- **Carregar uma mineração não trocava a estratégia.** A seção de parâmetros
  era remontada por um callback depois que os valores tinham sido escritos,
  apagando-os — e minerações de outra estratégia eram recusadas em vez de
  trazerem a própria estratégia junto. Agora os valores vão embutidos nos
  componentes reconstruídos, a varredura manda na estratégia, e a troca não
  desfaz um carregamento que ela mesma disparou.
- **`init_schema` apagava as minerações salvas.** Um bloco de auto-reparo
  comparava as colunas da tabela com as declaradas no `CREATE TABLE` e,
  divergindo, dava `DROP TABLE`. Colunas acrescentadas por `ALTER` não eram
  contadas como declaradas, então bastava existir uma para a tabela ser
  derrubada a cada gravação — salvar uma segunda mineração fazia a primeira
  sumir, sem erro nenhum. Agora o `ALTER` conta, e **recriar só acontece em
  tabela vazia**: com dado dentro, levanta erro pedindo migração explícita.
  Minerar deixou de ser automático, e o que está gravado foi você que mandou
  salvar.
- **O corte do holdout não viajava com a mineração salva.** Clicar numa linha
  recalculava o corte com os campos da tela: a varredura #40 rodou com
  holdout de 6 meses (corte 14/09/2025) e a tela estava em 12 (corte
  18/03/2025), então a mesma combinação aparecia com R$ 6.165 na tabela e
  R$ 5.491 no card. Agora `wf_config` é gravado junto, o backtest usa o corte
  da varredura, e os campos de walk-forward voltam ao carregar.
- **Tempo em posição contava barras de M1**, não do timeframe da estratégia.
  Um trade de 4 candles em M15 aparecia como 60 barras, na última faixa do
  gráfico. Agora a contagem usa a mesma unidade do campo `max_barras`, e o
  título diz qual é (“barras M5”).
- **As abas de diagnóstico não rolavam e a tabela de trades sumia.** O
  `dcc.Tabs` cria um `div.tab-content` próprio; sem estilizá-lo, ele crescia
  até a altura natural do conteúdo (1.865 px de gráficos) dentro de um painel
  de 289 px com `overflow:hidden` — tudo cortado, nada rolava, e a grade de
  trades colapsava para altura zero. Corrigido com `content_className` e a
  cadeia de flex fechada até o corpo da aba.
- **Gráficos de diagnóstico achatados em 104 px.** A grade também é o
  elemento que rola; com altura definida, ela estica as linhas para caber em
  vez de transbordar. `grid-auto-rows` fixo devolve a altura e a rolagem.
- `np.digitize` sem `right=True` deslizava todas as faixas de duração uma
  casa: o trade de 1 barra caía no balde "2–3". Rótulo descrevendo a faixa
  vizinha, em todo o gráfico.

### Removido
- Texto "N parâmetros · resultados anteriores descartados" ao trocar de
  estratégia.

### Adicionado (antes)
- **Seletor de estratégia na tela.** `strategies/registry.py` descobre sozinho
  todo módulo em `strategies/` que exponha `name`, `params_schema` e
  `signals` — soltar o arquivo na pasta basta. Trocar de estratégia remonta
  os campos de parâmetro a partir do novo schema e **zera tudo**: mineração,
  nuvem, cartões, tabela de trades e curva de capital.
- Segunda estratégia, `rompimento_canal` (Donchian com filtro de
  volatilidade). Parâmetros sem nenhuma relação com os do cruzamento —
  existe para provar que a plataforma não foi escrita em volta de médias.
- `backtest.py --estrategia <modulo>`.
- Coluna **score** separada de **score robusto** na tabela de mineração.

### Corrigido
- **A faixa de mineração furava os limites do schema.** Digitar "até 400" num
  parâmetro com `max: 200` varria valores que a estratégia nunca declarou.
  Agora a faixa é recortada pelos limites, com três testes cobrindo.
- **Scores "sumiam" ao terminar a varredura.** Durante a mineração a coluna
  "score robusto" mostrava o score cru; no fim, o robusto verdadeiro (mediana
  dos vizinhos) entrava no lugar e os valores caíam. Mesmo nome, duas
  medidas. Agora são duas colunas e a robusta nasce vazia.
- **Trocar de estratégia durante uma mineração deixava a varredura antiga
  repovoar a tela** segundos depois do reset. Cada varredura carrega o número
  da geração em que nasceu; a obsoleta descarta o próprio resultado.
- Backtest e mineração mediam **períodos diferentes** para a mesma
  combinação: a tabela exclui o holdout, o card incluía. O clique agora liga
  "excluir holdout" e o card declara a janela que está medindo.
- **Parar não parava.** A saída do `with ProcessPoolExecutor` esperava todas
  as tarefas já enfileiradas; com 300 mil combinações o botão não cancelava
  nada. Agora `shutdown(cancel_futures=True)` — para em ~2 s.
- Minerações não vão mais para o banco sozinhas: só pelo botão **Salvar**.
- Escala de cor da nuvem ancorada no zero (`cmid=0`). Sem isso o RdYlGn se
  normalizava pelo lote e a combinação **menos ruim** de uma varredura toda
  negativa saía verde-vivo.

---

## [F4] — Dispersão e cross-filtering

### Adicionado
- Scatter 2D (`Scattergl`) e 3D (`Scatter3d`) das combinações mineradas,
  colorido em `RdYlGn` por score robusto e dimensionado por nº de trades.
- Cross-filtering: clicar num ponto da nuvem **ou** numa linha da tabela
  carrega a combinação nos campos e dispara o backtest — um caminho, dois
  gatilhos.
- Eixos preenchidos automaticamente só com os parâmetros que **variaram**:
  eixo de valor único não é dispersão, é uma linha.
- Toggle **Backtest / Mineração** no topo. São duas atividades diferentes,
  não duas abas do mesmo painel: backtest confere se a estratégia segue o
  roteiro; mineração procura região boa no espaço.

### Corrigido
- Numa varredura de um parâmetro só os dois eixos caíam no mesmo campo,
  gerando uma diagonal inútil. O eixo Y agora também aceita métricas e assume
  o score robusto nesse caso.
- Os eixos ficavam presos no primeiro parâmetro durante a varredura: no começo
  só um parâmetro parece ter variado.

### Alterado
- Rótulos de "camada 3 / camada 4" removidos da interface — poluíam a tela sem
  informar. A distinção segue valendo no código e no PLANO.
- Marcar "minerar" agora esconde o campo de valor fixo: ou o valor, ou a
  faixa, nunca os dois.

---

## [F3] — Mineração com walk-forward

### Adicionado
- `core/walkforward.py`: folds deslizantes, holdout lacrado, score de
  vizinhança, filtros de presença e mínimo de operações.
- `core/optimizer.py`: pool de processos, escritor único, progresso em memória
  lido pela interface via `dcc.Interval`.
- Tabelas `mining_runs` e `mining_trials`, com retrato do perfil de execução.
- Painel de mineração com barra de progresso e ranking reativo.

### Corrigido — conceitual, importante
- **A separação IS/OOS estava errada.** Com parâmetros fixos varridos em todos
  os folds, chamar as janelas de teste de "fora da amostra" é mentira: o
  otimizador enxerga todas ao escolher o vencedor. Substituído por
  **consistência entre períodos** (mediana do fator de recuperação, não soma)
  e **holdout guardado, não exibido** durante a varredura. Ver PLANO §7.
- **Workers travavam a gravação.** DuckDB aceita vários leitores OU um
  escritor. Os workers agora leem do espelho Parquet e nunca abrem o
  `.duckdb`; a gravação usa `connect_write()`, que espera a vez.
- `passo = r.get("passo") or meta["step"]` transformava passo 0 em 1 em
  silêncio, gerando uma varredura que o usuário não pediu. Faixa inválida
  agora cai no valor único.

---

## [F2] — Dashboard de backtest

### Adicionado
- Gráfico de preço em TradingView Lightweight Charts v5 via `dash-tvlwc`, com
  marcadores de compra e venda e price lines de entrada, stop, alvo e saída.
- Curva de capital com underwater drawdown em painel próprio.
- Painel estatístico e tabela de trades em AG Grid.
- Tema neon escuro; `color-scheme: dark` para os controles nativos, que vinham
  com fundo branco.

### Alterado
- Gráfico de candles movido para modal ("visualizar estratégia" e clique num
  trade). Lado a lado com a tabela, os dois ficavam ilegíveis.
- Curva de capital ganhou altura — é o item mais importante da tela.

---

## [F1] — Motor e métricas

### Adicionado
- `core/engine/kernel.py`: laço Numba com stop, alvo, breakeven, stop móvel,
  trailing, tempo máximo, encerramento por horário e limites diários.
- `core/engine/execution.py`: perfil de execução (camada 4), reamostragem
  para o timeframe da estratégia, ATR e mapeamento de sinais para M1.
- `core/metrics.py`: conversão pontos → dinheiro, com contratos fixos e risco
  fixo comparáveis sobre o mesmo conjunto de trades.
- Contador de barras ambíguas no painel.

### Corrigido
- Sinal na última barra do dia armava entrada na abertura do dia seguinte.
  Entrada agora exige que a próxima barra esteja na janela **e** seja do mesmo
  pregão.

---

## [F0] — Fundação de dados

### Adicionado
- Schema DuckDB, espelho Parquet particionado por ano e ingestão por **merge**
  com resolução determinística de conflito (a exportação mais recente vence,
  por `source_max_ts` e não por ordem de importação).
- `trading_days` e `rollovers` derivados das próprias barras.
- CLI: `init`, `ingest`, `derive`, `status`, `verify`.

### Verificado
- 688.224 barras e 1.247 pregões carregados em 2,1 s.
- Reimportar o mesmo arquivo não muda nada (0 inseridas, 688.224 idênticas).
- Reconstrução a partir do Parquet é idêntica à base.
- 30 rolagens detectadas por calendário, 29 confirmadas pelo gap medido.

### Corrigido
- `COPY … TO ?` com parâmetro ligado não gravava nada, sem erro. Destino de
  `COPY` e caminho de `read_parquet` precisam ser literais.
- Carga que falhava no meio deixava linha órfã em `ingest_log`. A ingestão
  agora é transacional.
