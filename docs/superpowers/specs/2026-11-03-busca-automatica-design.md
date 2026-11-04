# Busca automática por nichos — desenho

Data: 03/11/2026. Protótipo aprovado (contrato visual):
`docs/superpowers/specs/2026-11-03-busca-automatica/layout-b.html` (layout B,
"mapa de nichos", com o modal lateral).

## 1. Intenção

Hoje o usuário minera à mão, num funil: roda uma varredura genérica, abre no
Backtest uma faixa que foi boa, percebe em que horário e dia a estratégia
começa a ter vantagem, afunila stop/alvo e dias, testa os outros parâmetros
e só num cluster bom experimenta breakeven, stop móvel e trailing.

A busca automática faz **o reconhecimento do terreno**: testa o máximo
possível de combinações de UMA estratégia num ativo e entrega uma lista de
**nichos/grupos bons e diferentes entre si** — com tempo gráfico, horário,
dias, direção, stop e alvo — para o usuário então minerar a região à mão no
processo de hoje.

**Não é:** algo que salva estratégia no Portfólio, nem um otimizador que
entrega "a melhor combinação". A validação (minerar a região, WFA,
Candidata) continua sendo do usuário.

## 2. Objetivos, não-objetivos, anti-objetivos

Objetivos
- Encontrar MAIS clusters, e diferentes entre si, em menos tempo de busca.
- Achar vantagens estreitas que o funil manual não acharia (ex.: "3 dias por
  semana, só das 10:00 às 10:30, 900 trades").
- Ser escalável: novos parâmetros globais (ex.: preço médio), novas
  estratégias e novos ativos entram sem mexer na busca.

Não-objetivos
- Refinar a região em volta do campeão, grade de stop/alvo do cluster,
  proteções — é a etapa de validação do usuário.
- "Memória entre buscas" (começar pelos nichos bons de buscas anteriores):
  **reprovado pelo usuário**.

Anti-objetivos (seria fracasso mesmo funcionando)
- Lista com 30 variações do mesmo ponto.
- Campeão de poucos trades com números absurdos.
- Descartar uma combinação que é ruim no dia inteiro mas boa numa janela
  estreita.
- Busca que atrapalhe a captura e as ordens do pregão (portfólio 6 na conta
  REAL).
- Tela que trava o acesso ("relatório só de manhã", "só depois de terminar").

## 3. O que entra na busca e o que fica fixo

Entra na busca (o usuário pode ajustar as faixas na tela antes de iniciar):
- parâmetros da estratégia (`params_schema`), incluindo a opção de saída
  (`saida`);
- tempo gráfico (conjunto escolhido);
- direção (compra, venda, as duas);
- janela de entradas: início e fim, em degraus (padrão 30 min), com janela
  mínima; respeita `janela_valida` (não atravessa a pausa da CME);
- dias da semana: qualquer combinação dos 5;
- tipo e valor do stop (pontos, ATR, % do preço) e do alvo (pontos, ATR,
  múltiplo do stop, % do preço);
- nas estratégias de abertura, o **horário de referência da abertura**
  (hoje `abertura_referencia` da ficha do ativo, 09:30 nos micros): a
  estratégia pode render ancorada em outro horário.

Fica fixo, lido do menu como estiver: filtro de mercado ADX, janelas "sem
entradas", limites diários (ganho, perda, nº de operações, máx. prejuízos),
breakeven, stop móvel, trailing, custos, dimensionamento. Ativo, estratégia,
período (de/até) e "excluir holdout" vêm do topo do menu.

Regras
- **Mínimo de 400 trades** por combinação (padrão, editável): abaixo disso a
  combinação não conta como campeã nem entra em nicho/grupo.
- **Critério de ordenação** escolhido pelo usuário entre os da aba
  Critérios (`core/mineracao_stats.CRITERIOS`); padrão **fator de
  recuperação**. É também o que a busca persegue.
- **Holdout fora** em todas as etapas, quando "excluir holdout" está
  marcado (padrão) — ver seção 9.
- O relatório mostra quantas combinações foram testadas no total.

## 4. Como a busca funciona (decidido)

**Biblioteca única: `pyribs`** (MAP-Elites / CMA-ME). Optuna fica de fora:
persegue um campeão só e seria redundante.

1. **Nichos (quality-diversity).** Um arquivo de nichos guarda o melhor de
   cada nicho; a busca é premiada por achar nichos novos bons, não só por
   melhorar o mesmo. Dimensões padrão do nicho: tempo gráfico × janela de
   horário (com dias e direção como alternativas na tela). As dimensões são
   configuráveis — amanhã pode ser um parâmetro novo.
2. **Calcular uma vez, testar muitas.** O indicador é calculado uma vez por
   (tempo gráfico, parâmetros que mexem no sinal). Horário, dias, direção,
   stop e alvo filtram/simulam por cima, em lote. Cada item do catálogo
   declara sua **camada**: "essencial" (exige recalcular o sinal) ou
   "filtro" (só filtra/simula). O resultado de cada combinação tem que
   **bater exatamente** com a mineração/backtest de hoje.
3. **Descarte cedo, conservador.** Combinação que claramente não chega a 400
   trades, ou que vai muito mal na amostra inicial, é abandonada antes do
   período inteiro. **O descarte olha a combinação na melhor janela e nos
   melhores dias dela**, nunca o dia inteiro: ruim só por causa do horário
   não pode cair.
4. **Degrau proporcional** em parâmetros de período (ex.: médias): perto de
   zero anda de 1 em 1; lá em cima, ~8% (250 → 270), porque 250 e 251 dão
   praticamente o mesmo. Combinações com exatamente os mesmos trades contam
   como uma só. O tipo de degrau é declarado no catálogo.
5. **Paralelo.** Núcleos ajustáveis na tela (1 a 24 no PC atual), com
   padrão pré-definido (ex.: 20 com "parar às" ligado, 4 desligado);
   mudança vale a partir do próximo lote, inclusive rodando.
6. **Agrupar.** Campeões parecidos viram um grupo: mesmo tempo gráfico,
   mesma direção, mesmos tipos de stop/alvo, parâmetros a poucos degraus,
   janela e dias parecidos. Cada grupo mostra melhor e mediana, nº de
   membros, hora × dia, espalhamento dos membros, por ano e curva do
   campeão.

## 5. Processo, controle e dados

- Roda num **processo separado** (o app pode até estar fechado), com
  prioridade baixa.
- Controles a qualquer momento: Iniciar, Pausar, Continuar, Parar e guardar,
  Nova busca. Uma busca parada/interrompida pode **continuar** depois
  (inclusive em outro dia).
- **Parar às 08:30**: ligado por padrão, desligável; limite de testes
  opcional.
- **Nada volta sozinho** (decisão do usuário): uma busca parada só continua
  quando o usuário clica em Continuar. Sem tarefa agendada, sem arranque
  pelo `iniciar.bat`.
- **Pode rodar durante o pregão** (decisão do usuário), junto com a captura
  e as ordens da conta real. **O usuário controla os núcleos**; a busca não
  impõe teto, só roda com prioridade baixa.
- **Banco próprio** `data/buscas.duckdb` (DuckDB aceita um escritor por vez
  e o banco principal é gravado pela captura). A busca só LÊ as barras do
  banco principal. Guarda: buscas (config, estado, contagens), nichos,
  combinações/elites, grupos e os dados do detalhe.
- **Sem coluna por parâmetro**: a combinação é guardada como nome = valor
  (ex.: JSON), para parâmetros novos não exigirem mudar o banco e buscas
  antigas continuarem abrindo.
- Buscas salvas: reabrir e **excluir** (ícone de lixeira, com confirmação;
  desligado com a busca rodando).

## 6. Escalabilidade (requisito)

- O que a busca varre vem de um **catálogo declarativo** (tipo, faixa
  padrão, degrau, camada). Novo parâmetro global (preço médio) = declarar
  no catálogo; tela de configuração, busca e relatório o pegam sozinhos.
- Ativos novos entram pela ficha YAML (horários, tick, faixas), como MES e
  MNQ. Nada amarrado ao WIN.
- Cada estratégia declara o que faz sentido para ela (ex.: só as de
  abertura declaram o horário de referência; janela de horário plausível).

## 7. Tela (contrato: layout B)

Subtela nova na Mineração: **Varredura | Busca automática | Backtest**.
- Peça principal: **mapa de nichos** (linhas = tempo gráfico; colunas =
  horário, dias ou direção), cor contínua pelo critério com legenda,
  listrado = menos de 400 trades, vazio = não testado, ★ = melhor, tooltip,
  setas do teclado, casa que acende pulsa uma vez. Acende ao vivo.
- Alternador **Mapa | Lista | Espaço de busca** (lista com selos, barras,
  sparkline, ordenação; espaço de busca travado enquanto existe busca).
- **Menu lateral direito**: status, controles, parada, limite de testes,
  núcleos, buscas salvas com lixeira.
- **Detalhe do nicho/grupo em modal lateral** (gaveta por cima; usuário
  "amou"): hora × dia, por ano, espalhamento, curva do campeão, "abrir o
  campeão no Backtest" e **"Minerar a região"** (leva à Varredura com faixas,
  tempo, janela, dias, stop e alvo preenchidos com a faixa do grupo). Foco
  preso, Esc, ← → para o vizinho; marca "parcial" com a busca rodando.
- Tudo acessível em qualquer estado (Parada, Rodando, Pausada, Concluída,
  Erro); travados só os campos que mudariam a busca em andamento.
- Regras de tela do projeto: títulos curtos, nada de texto explicativo
  visível (explicação só no "(?)"), skills de UI/UX no acabamento.

## 8. Etapas sugeridas

1. Motor em camadas (com a foto do WIN antes/depois; resultado idêntico).
2. Busca por nichos + processo separado + banco próprio + controles.
3. Agrupamento e dados do detalhe.
4. Tela (layout B) e "Minerar a região".

## 9. Decisões tomadas pelo designer/Claude (o usuário pode revisar)

- "Minerar a região" fica liberado mesmo com a busca rodando (grupo marcado
  "parcial").
- Núcleos podem mudar com a busca rodando (vale no próximo lote).
- Padrões 20/4 núcleos conforme "parar às".
- **Nicho = grade fina:** tempo gráfico × início da janela × fim da janela ×
  dias × direção (ordem de dezenas de milhares de casas, cabe no banco). O
  mapa mostra **projeções**: cada casa (ex.: tempo × início) exibe o melhor
  entre os nichos que caem nela; trocar as colunas para dias ou direção só
  muda a projeção, não a busca. "Nicho novo" é uma casa nova da grade fina.
- **Número de referência = o da Varredura de hoje:** cada combinação é
  avaliada como a mineração avalia hoje (mesmos folds/`wf.avaliar`, mesmas
  métricas e `score`). "Bater exatamente" é contra esse número.
- **Holdout segue a caixa "excluir holdout" do menu**, como na Varredura
  (padrão marcada = holdout fora). "Intocado" na seção 3 vale com a caixa
  marcada.
- **Horário de referência da abertura não desloca a janela:** a janela de
  entradas é sempre em horário absoluto (hora de NY nos micros); a âncora
  só muda o sinal da estratégia (camada essencial).

## 10. Deixado para quem constrói

- Escolha do emissor da pyribs e de como mapear parâmetros discretos /
  categóricos (tempo gráfico, tipos, dias) no arquivo de nichos.
- Tamanho do lote, critério numérico do descarte cedo (desde que respeite a
  regra da melhor janela), distância usada no agrupamento.
- Formato exato das tabelas de `data/buscas.duckdb`.

## 11. Estado depois da implementação (04/11/2026)

O que vale hoje (commits `030ef6d` a `85519c9`) e difere da seção 3:

- **Entra a camada 4 quase toda**: horário de fechamento, tempo máximo na
  operação, três horas "sem entradas", filtro ADX (régua, período, limiar,
  DI, ADX subindo), breakeven, limites do dia (ganho, perda, operações,
  prejuízos) e o período do ATR do stop e do alvo (5 a 60, de 5 em 5, passo
  editável). Em toda faixa entra o "desligado". Lista sem nada marcado
  desliga o recurso; sem régua, o ADX inteiro fica desligado.
- **Fica fixo (valor do menu, bloco "Fixos"):** stop móvel e trailing
  (`FORA_DA_BUSCA`, decisão do usuário), custos e dimensionamento
  (`NAO_MINERAVEIS`). Antes a seção 3 dizia que ADX, sem entradas, limites e
  breakeven eram fixos: não são mais. Campo novo do perfil de execução tem de
  entrar na busca ou numa dessas listas (um teste cobra).
- **Faixas largas e editáveis:** stop e alvo em pontos saem do padrão da
  ficha do ativo (passo = padrão/6, até = padrão x 20/3; WIN 50-2.000 e
  100-4.000). Cada tipo tem de, até e passo editáveis. Janela mínima não é
  campo da tela: 30 min fixos.
- **Tempos gráficos** espelham o motor (16, de M1 a H4; marcados de 2 a 30
  min).
- **Cópias viram uma:** combinações que dão os mesmos trades (`canonico`).
- Buscas gravadas antes reabrem iguais (sem os extras, mesmas chaves).
