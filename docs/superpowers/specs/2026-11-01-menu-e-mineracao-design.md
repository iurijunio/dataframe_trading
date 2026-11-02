# Menu da esquerda, topo e Backtest dentro da Mineração — design

Data: 01/11/2026. Aprovado em conversa com o usuário (rascunhos em
`2026-11-01-menu-e-mineracao/`: `menu.html` e `tela-mineracao.html`).
**Os rascunhos são contrato** — implementação igual a eles; desvio só
perguntando antes.

Base: o branch da etapa 4 da CME (`cme-etapa4`), depois de juntado no `master`.

## Por quê

- O seletor de ativo no topo fica longe da estratégia e confunde (ex.: carregar
  uma mineração do WIN com o topo dizendo MES).
- "Sincronizar com MT5" não é mais usado: a captura (`captura.py`, ligada pelo
  `iniciar.bat`) já busca sozinha tudo desde a última barra gravada, inclusive
  dias com o app fechado. E o botão não serve para a CME nem para mercados
  futuros que não vêm do MT5.
- A tela Backtest só é usada para abrir os detalhes de uma linha da mineração e
  testar ajustes à mão (ex.: tirar a sexta-feira). Não faz sentido ela ser a
  tela inicial nem uma aba própria.
- O menu da esquerda é uma coluna longa e estreita; as estratégias vão ganhar
  mais campos.

## Objetivos

### 1. Topo
- Sai o seletor de ativo (`ativo`) — vai para o menu (item 4).
- Sai o botão "Sincronizar com MT5" (`btn-mt5-sync`) e o seu status
  (`mt5-sync-status`).
- Sai a aba Backtest de `modo`. Abas que ficam, nesta ordem: Mineração,
  Walk-Forward, Candidata, Estratégias, Portfólio, Ao vivo.
- Ficam como estão: selo de reotimizar, selo da captura, "Ordens paradas…",
  "Zerar tudo e desligar envio".

### 2. Tela inicial
- O app abre em **Ao vivo › Estratégias**.

### 3. Mineração com duas subtelas
- **Varredura**: tudo o que a Mineração mostra hoje (Minerar/Parar, carregar e
  salvar mineração, análise da varredura, tabela).
- **Backtest**: a tela Backtest de hoje, inteira (cartões, curva de capital,
  diagnóstico com todas as abas, lista de trades, "Visualizar estratégia" e o
  modal do gráfico) mais o botão "Rodar backtest".
- No alto da subtela Backtest, uma linha curta diz qual combinação está
  carregada (ex.: "linha #3 · stop_pontos=10"). Sem frase explicativa.
- **Clicar numa linha** da tabela da mineração, num ponto da nuvem ou numa
  linha das aprovadas: roda o backtest daquela combinação (como hoje) **e pula
  sozinho para a subtela Backtest**.
- O menu da esquerda é o mesmo nas duas subtelas; o usuário mexe nele (ex.:
  desmarca sexta) e clica "Rodar backtest".

### 4. Menu da esquerda
- Largura de ~270 px para **~400 px**. A área principal encolhe.
- **Topo fixo** (não rola): ativo e estratégia lado a lado; abaixo, de, até e
  tempo gráfico. "Excluir holdout" fica no topo fixo também (decisão minha).
- Abaixo do topo fixo, **5 abas**, presas junto com o topo:

  | Aba | Grupos de hoje que vão dentro |
  |---|---|
  | Entrada | Parâmetros da estratégia, direção, sem entradas |
  | Saída | Gestão (stop, alvo, trailing e tipos) · Proteções |
  | Filtros | Filtro de mercado · Janela · Filtro de mineração |
  | Risco | Limites diários · Custos · Posição |
  | Períodos | Consistência entre períodos (treino, teste, passo, holdout, processos) |

- Aba com **um** grupo: mostra os campos direto, sem gaveta.
- Aba com **dois ou mais** grupos: cada grupo é uma **gaveta** que abre e
  fecha. Fechada, mostra na própria linha um resumo curto do que está nela
  (ex.: Gestão "stop 8 · alvo 16 · trailing 0"; Proteções "desligadas").
- Dentro de gavetas e abas, campos lado a lado: 2 ou 3 por linha (stop, alvo e
  trailing na mesma linha).
- Pontinho na aba quando algum campo dela está marcado para "minerar"
  (decisão minha, aprovada no rascunho).
- Nada dentro do menu rola na horizontal; só a parte abaixo das abas rola na
  vertical.

### 5. Ativo nas outras abas
- O menu continua escondido em Walk-Forward, Candidata, Estratégias, Portfólio
  e Ao vivo, como hoje. Essas telas não têm seletor de ativo: usam o ativo do
  que mostram (a mineração escolhida, a variante, o plano). Aprovado pelo
  usuário em 01/11. Onde hoje um callback lê `State("ativo")` como reserva,
  ele continua lendo o seletor do menu (escondido), que guarda o último ativo
  escolhido.

## Fora do escopo

- Nenhuma conta, motor, otimizador, WFA, Candidata, Portfólio ou Ao vivo muda.
- Conteúdo das outras abas do topo não muda.
- `core/mt5_source.sincronizar` e `scripts`/testes do núcleo continuam (só a
  tela perde o botão).
- Corrigir o erro React #31 ao abrir (anotado à parte).

## O que seria falha mesmo funcionando

- Algum campo de hoje sumir, mudar de valor padrão, de faixa ou de passo.
- Texto explicativo visível na tela (explicação só no "(?)").
- Quebrar o que a etapa 4 fez: faixas por ativo, troca de ativo sem mineração
  na tela, mineração carregada ajustando stop/alvo/trailing ao ativo dela.
- Clicar numa linha da mineração e o backtest não rodar, ou rodar com outra
  combinação.
- Telas do WIN diferentes de hoje fora do que este design muda.

## Restrições

- Dash 4.4.1. Ids que os callbacks usam continuam os mesmos sempre que
  possível; o que precisar mudar, muda em todos os lugares juntos.
- `ui/components/controls.py` é protegido: autorizado mexer no necessário
  para este design, avisando. `ui/components/wfa_matriz.py`: não mexer.
- Referência das telas (`scripts/referencia_telas.py`): todos os arquivos de
  `tests/dados/telas_win/` continuam idênticos, exceto `parametros.json`, que
  muda de forma (abas, gavetas). Antes de regravá-lo, provar que a lista de
  campos (id, valor, mínimo, máximo, passo, rótulo) extraída do layout novo é
  igual à extraída do layout de hoje, para todas as estratégias e para o
  WIN, MES e MNQ.
- Conferência no app só com o app real fechado (a cópia abre o banco real).
- Docs (AGENTS.md, README, CHANGELOG) deixam de falar do botão de sincronizar
  e da aba Backtest.

## Decisões minhas (para o usuário conferir)

- "Excluir holdout" no topo fixo do menu.
- A aba e as gavetas abertas ficam como o usuário deixou enquanto o app estiver
  aberto; ao abrir o app, aba Entrada e a primeira gaveta de cada aba abertas.
- Trocar de estratégia ou de ativo não muda a aba escolhida.
- Depois de mexer no menu e rodar de novo, a linha "linha #N · …" continua
  mostrando a combinação de origem, com "editado" ao lado.

- **Menu por subtela** (o "mesmo menu" é a mesma estrutura de topo, abas e
  gavetas; o que é só da mineração aparece só na Varredura, como hoje):
  - Varredura: caixas "minerar", linha de/passo/até dos campos marcados, aba
    Períodos, grupo Filtro de mineração e o pontinho nas abas.
  - Backtest: só o valor de cada campo (campo marcado para minerar mostra o
    valor, editável), sem caixas "minerar", sem aba Períodos, sem Filtro de
    mineração, sem pontinho. Ou seja, 4 abas no Backtest.
  - O rascunho mostra valor, faixa e caixa juntos só para ilustrar; vale a
    regra acima.
- **Linha da combinação** no alto do Backtest: só os parâmetros que a
  mineração varreu, com a origem — "linha #3 · stop_pontos=10" (tabela),
  "nuvem · stop_pontos=10" (ponto da nuvem), "aprovada #2 · …" (aprovadas). Se
  o usuário mexer em qualquer campo do menu e rodar de novo, ganha
  "· editado" no fim. Rodar sem ter vindo de uma linha: a linha fica vazia.
- **Textos explicativos que o menu tem hoje** ("0 desliga", o parágrafo do
  ADX, "cobrado por ponta…" etc.) vão para o "(?)" do campo ou grupo; nenhum
  fica visível solto.
- **Cada campo continua no grupo em que está hoje**; os grupos vão para as
  abas pela tabela acima. (A tabela do rascunho cita "dias" sob Filtro de
  mercado só como exemplo; vale o grupo de hoje.) Linhas de estado do menu
  (`wf-resumo` etc.) ficam com o grupo a que pertencem hoje — `wf-resumo` vai
  com Consistência entre períodos, na aba Períodos.

## Deixado para quem implementar

- O texto exato de cada resumo de gaveta (curto, sem frase).
- Como guardar o estado de aba e gavetas (store do Dash ou só no navegador).
- CSS e espaçamentos, seguindo os rascunhos.
