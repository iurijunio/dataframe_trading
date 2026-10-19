# Parte 5 — Conta real (desenho)

Data: 19/10/2026 · branch `live-trading` · protótipo aprovado:
`.superpowers/brainstorm/conta-real/conta-real-v2.html` (contrato visual —
ver §7).

## 1. Objetivo

Variantes promovidas operam na **conta real** da Clear com o mesmo motor de
ordens da demo, **em paralelo com a demo** (espelho), com a **real mandando
ordem primeiro**. A tela deixa de ser "só demo": sai todo texto/elemento que
só vale para a demo e entra o que a real precisa.

## 2. Decisões do usuário (19/10/2026)

| # | Decisão |
|---|---|
| D1 | Variante na real **continua na demo** (espelho). Prioridade de ordem: **real primeiro**. |
| D2 | **Sem trava** para promover: o usuário promove quando quiser (inclusive no 1º dia, inclusive direto do papel). A tela só **informa** os números da demo. |
| D3 | Ligar o Envio da real = **igual à demo** (dois cliques). |
| D4 | Arquitetura **A**: a captura atual segue (candles, papel, demo) + **processo novo "ordens real"** no terminal da real. |
| D5 | Tela = protótipo v2, fielmente (regras de `prototipo-e-contrato`): funções existentes ficam, (?) existentes ficam, sem frase explicativa visível. |

Contas já cadastradas: demo #2 (1193398927, terminal
`…\Clear Investimentos MT5 Terminal\terminal64.exe`) e real #3 (1014062283,
servidor `ClearInvestimentos-CLEAR`, terminal `…\Clear Investimentos MT5
Terminal - Real\terminal64.exe`). Portfólio 6 aponta para as duas.

## 3. Fases

`papel → demo → real`. **real ⊃ demo**: uma ligação em fase `real` manda
ordens na conta real **e** na demo do portfólio. `mudar_fase` aceita `real`
de qualquer fase (D2), com as mesmas recusas técnicas de hoje para sair do
papel (plano em vigor, stop, papel × backtest sem diferença, conta do tipo
certo cadastrada no portfólio). "Voltar para demo" e "Voltar para papel"
encerram a posição na(s) conta(s) que deixam de operar (aviso no (?)).
Contratos: `contratos_real` (coluna já existe) com o mesmo editor da demo;
`NULL` = do plano.

## 4. Arquitetura

### 4.1 Processos

| Processo | Terminal | Faz |
|---|---|---|
| Captura (existente) | demo | candles, papel, **publica desejados**, ordens da demo |
| **Ordens real** (novo, `ordens_real.py`) | real | só ordens da real; não grava candles nem papel |
| App | — | tela |

O pacote MetaTrader5 fala com um terminal por processo — por isso dois.
`mt5.initialize(path=<terminal da conta>)` com o caminho cadastrado em
`contas.terminal`; o processo confere `account_info().login` == login da conta
real e `trade_mode` == REAL antes de qualquer ordem (senão: chamado, nada
sai). `iniciar.bat` abre as três janelas ("Dataframe - Ordens real" é a nova).
Fechar a da real não afeta a demo.

### 4.2 Desejados publicados (a ponte)

A captura já calcula `papel_vivo.desejados(...)` por ligação. Passa a gravar,
**antes de executar as ordens da demo**, um arquivo atômico
`data/ao_vivo/desejados.json` (tmp + `os.replace`):

```
{"versao": 1, "escrito_em_srv": "...", "minuto": "HH:MM", "seq": N,
 "contrato_dia": {...}, "disponivel": true,
 "ligacoes": {"3": {"desejado": "posicao|zerado|indisponivel", "lado": 1,
   "entry_ts": "...", "stop_px": ..., "alvo_px": ..., "preco_papel": ...,
   "fase": "real", ...}}}
```

Só o que o motor de ordens precisa (o mesmo `LigacaoViva`/desejado que a
demo usa), com contratos **não** incluídos (cada processo aplica os da sua
conta). Escrita só quando muda ou a cada volta rápida perto da virada; nunca
espera banco.

**Prioridade da real (D1):** a escrita do arquivo é o primeiro passo da
volta de ordens da captura; o processo da real lê o arquivo em laço de 0,05 s
nos segundos [58, 60) ∪ [0, 10] do servidor (0,5 s fora disso) e age assim que
o `seq` muda. A demo só executa depois de escrever.

**Frescor:** desejados mais velhos que 5 s no pregão (pelo relógio do
servidor do terminal da real) = **indisponível** para a real: não entra nada
novo, mantém e protege o que tem (regra já existente da demo); > 180 s →
chamado `papel_parado` na real. Captura fechada = mesma coisa.

### 4.3 Motor da real

Reaproveita `core/ordens.py` (`planejar`, `Motor`) e `core/corretora.py`
(as regras de ordem não mudam; os pontos presos em "demo" mudam — §10 R1): `Motor(pasta=data/ao_vivo/ordens/real/, origem="real")`,
diário write-ahead próprio (`AAAA-MM-DD.jsonl`), espelho no mesmo
`ordens_eventos` com `origem='real'` (coluna/valor a conferir no schema;
migração idempotente se faltar, com backup). Magic igual por ligação (contas
separadas). Trava de perda do dia, limite, chamados, adoção, proteção,
leitura parcial, órfã, retrato em arquivo — tudo por conta, como já é.
Retrato: lê o banco só-leitura a cada 5 s como a captura (`ler_retrato`
filtrando a conta real), com o arquivo local de fallback próprio.

Comandos: **uma pasta por processo** (`comandos/demo`, `comandos/real`) — §10 R2.
Ordem de teste continua **só demo**.

Estado: `data/ao_vivo/estado_real.json` com o mesmo formato do bloco
`ordens` do `estado.json`; o app lê os dois.

### 4.4 O que NÃO muda

Papel, backtest, mineração, conferência papel × backtest, captura de candles,
regras de ordem (tabela de retornos, preenchimento, D1–D4 da parte 4).

## 5. Tela (protótipo v2 é o contrato)

### 5.1 Ao vivo (cabeçalho)
Faixa de saúde em duas linhas **REAL** / **DEMO** (MT5, Algo Trading, Conta,
Margem livre, Ordem (média)), mais "sinal de vida" e "último candle" comuns,
todos com o (?) que já têm.

### 5.2 Operação
- Linha do portfólio: `| WINZ26 · real ClearContaReal · demo
  ClearInvestimentos · R$ 10.000 · 2/2 operando · pregão DD/MM · papel
  HH:MM:SS` com os (?) atuais; à direita "Envio" + **toggle Real** (laranja)
  + **toggle Demo** (ciano), sem texto ligado/desligado; separador; botão
  power (Desligar portfólio, title explica que para real e demo).
  Toggles mantêm dois cliques (D3) — o primeiro arma (rótulo "Confirmar?"
  ao lado), o segundo faz; desligar com posição aberta pede a confirmação
  com "encerra N posição(ões)" como hoje.
- Tira de números (6): **REAL hoje**, **DEMO hoje**, **PAPEL hoje** — cada um
  com "total R$ X,XX" embaixo (desde o plano em vigor; verde/vermelho);
  **Perda do dia · real**, **Perda do dia · demo** (barra até o limite, pior
  momento continua no (?)); **Contra o esperado** com a faixa desenhada (80% e
  50% da Candidata, mediana, ponto atual) e os valores embaixo. Saem:
  Acumulado papel, Posição agora, Pior momento (como número próprio).
- Variantes: um painel com duas partes, **REAL** em cima e **DEMO** embaixo
  (colunas Variante · Hoje · Op. · Acerto · Total · ações). Variante em fase
  real aparece nas duas partes com o resultado de cada conta; pausar só na
  parte REAL (pausa a variante inteira); ✎ por parte (contratos daquela
  conta). Variante só no papel: parte "PAPEL" embaixo, se houver.
- Posições abertas: coluna **Conta** (chip real/demo) antes de Variante.
- Abas: **Operações** = tabelas Real, Demo, Papel (nessa ordem); Papel ganha
  "Contr. papel / real / demo" e coluna "Papel × real". **Diário** = coluna
  **Conta**. **Avaliação** = coluna Real preenchida + "Papel × real" (igual à
  Papel × demo) + o resto como hoje; tabela Esperado com cor por coluna
  (cinza/violeta/ciano/laranja), seções "Resultado por contrato" e
  "Execução", etiquetas **bom/atenção/ruim** contra o esperado e legenda.
  Faixas das etiquetas (no (?) de cada linha): derrapagem ≤1 tick bom, ≤2
  atenção, >2 ruim; mesmo minuto ≥95% bom, ≥80% atenção; atraso ≤300 ms bom,
  ≤1000 atenção; rejeitadas 0 bom, ≤2 atenção; fator de lucro e acerto: ≥
  esperado bom, ≥80% do esperado atenção, abaixo ruim.

### 5.3 Estratégias
- Saem os passos "1-2-3" do topo e as frases-subtítulo ("Seção Contas, lá
  embaixo. Ela só passa a ser usada na fase demo.", "Ligar um portfólio
  libera…", etc.) → (?) quando útil.
- Portfólio: tabela com uma linha por conta (chip real/demo · conta do MT5 ·
  toggle de Envio · limite do dia + Salvar); power separado.
- Ficha da variante, bloco "Ordens nas contas": Fase como trilha papel → demo
  → real com o botão do próximo passo e o de voltar; selo papel × backtest;
  "Na demo até agora" (operações, derrapagem média, rejeitadas, chamados sem
  solução — só informação, D2); "Contratos na real" e "Contratos na demo",
  cada um com o custo de um stop em % do limite da conta.
- Contas: tabela (Tipo · Nome · Número · Servidor · Pasta do MT5 · Limite ·
  Editar); o formulário abre no Editar; "Nova conta" e "Puxar do MT5" ficam.

## 6. Segurança

- Real nunca envia se: login/trade_mode do terminal ≠ conta real cadastrada;
  Envio da real desligado (registra "seria_enviada" com `order_check`, como a
  demo); desejados indisponíveis/velhos; trava do dia; algo trading
  desligado.
- Zerar tudo do app fecha as duas contas.
- Testes nunca falam com MT5 real; `mt5_falso` ganha `trade_mode` REAL.
- Ensaio: antes de ligar o Envio da real, um pregão com a variante em fase
  real e Envio da real desligado — o usuário pode pular (D2), a tela só avisa.

## 7. Fidelidade ao protótipo

O v2 é a especificação visual (memória `prototipo-e-contrato`). Antes de
entregar: comparar parte a parte com o v2 em 1920 px e corrigir diferenças.
Funções existentes não mostradas no v2 ficam, encaixadas no visual; nenhum (?)
some.

## 8. Fora desta parte

Alvo "só encostado" (anotado em `ideias-depois`); custos reais por conta
diferentes dos do plano; conta netting; mais de uma conta real.

## 9. Testes

Motor/planejar já cobertos — novos: processo da real com `mt5_falso`
(login/trade_mode errados recusam; desejados velhos = indisponível; prioridade
— real age na mesma volta em que o arquivo muda; comandos roteados por
conta; zerar_tudo nas duas), `mudar_fase` real (de papel e de demo; voltar
encerra), contratos_real, telas (componentes, sem dict como filho), mutação
nas guardas de conta real.

## 10. Resoluções da revisão (19/10/2026) — obrigatórias

**R1 — pontos presos em "demo" (C1).** `papel_vivo.desejados` aceita
`fase in ("demo","real")`; `n_demo`, chamado `conta_errada`, `mudar_fase`,
`definir_contratos`, `_restricoes` e `custo_de_um_stop` passam a tratar
`real` (conta e contratos da real). No processo da real, ligação com fase ≠
real = ZERADO; se o arquivo de desejados e o retrato próprio discordarem,
vale o mais restritivo.

**R2 — comandos por pasta (C2).** `comandos/demo` (captura) e
`comandos/real` (ordens real); cada processo só lê a sua. `envio` e
`encerrar_posicao` vão para a pasta da conta (o app sabe a conta do chamado
/ do toggle). `zerar_tudo` é gravado **nas duas pastas sem ler o banco**
(antes de qualquer outra coisa, como hoje). `recusar_testes` só na demo.

**R3 — cada processo na sua conta (C3).** Captura abre só o terminal da
conta `tipo='demo'` (já corrigido em c0ff1b7) e a real só o da `tipo='real'`
(conferindo também o caminho do executável do terminal conectado). Em
**toda volta**, os dois conferem login e `account_info().trade_mode`
(DEMO na captura, REAL na real; `trade_mode` entra na `Fotografia`). Errado =
chamado `conta_errada`, nada sai, nada é encerrado. O retrato de cada
processo só contém as contas do seu tipo. Envio da real fica travado
(`ligar_envio` recusa) até esta parte estar pronta — já em c0ff1b7.

**R4 — instância única (C4).** `ordens_real.lock` (mesmo `travar` da
captura); `ordens_real.bat` com o laço de reabrir e os códigos 3/4; log
próprio; `iniciar.bat` abre a terceira janela.

**R5 — testes nunca chegam no real (C5).** `desejados.json`,
`estado_real.json`, `ordens/real/` e `comandos/real/` são constantes de módulo
desviadas no `tests/conftest.py` (autouse) + teste que prova o desvio.

**R6 — banco (I1).** `ordens_eventos.origem VARCHAR` (migração idempotente,
backup antes, preenchida pelo prefixo do `evento_id`; roda no schema da
captura/app, nunca na real). Todos os leitores de `ordens_eventos`
(`eventos_ordens`, `_impressao_do_dia`, `_pregoes_demo`, `operacoes_demo`,
`comparativo_demo`…) filtram por `origem`. **Quem espelha a real é a
captura**, na conexão de escrita que já abre (lê `ordens/real/*.jsonl`); o
processo da real nunca escreve no banco.

**R7 — retrato da real (I2).** `ler_retrato(..., tipo="real")` lê
`conta_real_id` e `contratos_real`; o processo da real faz `preparar_dia` e
`cache_codigo` (plano, custos, desvio) e relê o banco só-leitura a cada 5 s
fora da janela 58–10 s, com o arquivo local de fallback.

**R8 — conteúdo do arquivo (I3).** Serializa o `Desejado` inteiro (inclui
`entry_px`, `preco_papel`, `stop_px`, `alvo_px`, `lado`, `entry_ts`,
`motivo`), menos `contratos`, e o bloco do contrato (`simbolo`, `motivo`,
`vence_em`, guarda de preço). A real faz `symbol_select` e confere o símbolo
no próprio terminal (negociável), com `GuardaPreco` própria; símbolo
indisponível = sem entrada (chamado).

**R9 — frescor (I4).** Campo `vivo_em` = `time.time()` do PC gravado **em
toda volta** da captura (batimento), separado do `seq` (que muda quando os
desejados mudam; a regra é "mudou", não "aumentou" — reinício zera).
Frescor: `time.time() − vivo_em > 5 s` no pregão = indisponível (só
protege); > 180 s = chamado `papel_parado` na real. Relógio do servidor só
para `entry_ts`/janelas. Quando a captura não publica (MT5 da demo fora,
fora do pregão sem posição na demo), a real fica só protegendo — documentado
e testado.

**R10 — Windows (I5).** Escrita: tmp + `os.replace` com até 5 tentativas
de 5 ms em `PermissionError`; falha nunca impede a volta da demo. Leitura:
`read_bytes` rápido; JSON inválido/incompleto = ignora e relê.

**R11 — real primeiro de verdade (I6).** Na janela [58,60) ∪ [0,10] s a real
confere o `mtime` do arquivo a cada 10 ms; ao agir num `seq` novo grava
`ack_real.json` com o `seq`. A captura, depois de escrever um `seq` novo,
espera o ack desse `seq` por até 200 ms antes de executar a demo; sem ack,
segue (a real fora não segura a demo). O `Motor.passo` da real roda em toda
volta (proteção, comandos), não só em `seq` novo. Teste mede a ordem
relativa das ordens (real antes da demo) com os dois motores falsos.

**R12 — saúde e chamados da real na tela (I7, I8).** Na faixa de saúde, a
linha REAL mostra "parado" (rosa) quando o `estado_real.json` estiver velho
(> 10 s) — sem elemento novo. Chamados da real entram na faixa "Precisa de
você" com o chip "real". "Zerar tudo e desligar envio" (topo do app) e o
"Encerrar posição" dos chamados continuam onde estão (funções existentes);
o zerar e a contagem "encerra N posições" somam os dois estados.

**R13 — menores.** Pausar só na parte REAL **quando** a variante está em
fase real; variante só na demo/papel tem pausar na sua parte. Chip "ligado"
do portfólio fica. Promover para real exige conta demo **e** conta real no
portfólio, com terminal, login, servidor e limite cadastrados; trocar
login/conta de um portfólio com posição aberta naquela conta é recusado.
O `.jsonl` de `ordens/real/` nunca se apaga. Mudou `core/ordens.py`,
`corretora`, `papel_vivo` ou `ordens_real.py` → fechar as janelas
"Dataframe - Captura" **e** "Dataframe - Ordens real" e reabrir o
`iniciar.bat`.

**R14 — testes a mais.** Os da revisão: `desejados` com fase real; retrato
antigo publica `disponivel=false`; ligação ausente do arquivo não fecha
posição real sem ZERADO explícito; frescor com relógios de servidor
diferentes; `PermissionError` no replace; `entry_px` no JSON; leitores sem
misturar real e demo; captura recusa conta real e real recusa conta demo
(também no meio da sessão); segunda instância da real sai; comandos em
pastas separadas; zerar com banco ocupado chega às duas; `encerrar_posicao`
roteado; desvio do conftest; migração idempotente do `origem`; reinício da
real com posição aberta e arquivo velho só protege; mutação nas guardas de
`trade_mode` e de pasta.
