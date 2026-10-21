# Projeto C/E, parte 4: ordens na conta demo

> Spec de 08/10/2026 (rev. 2, depois da revisão contra o código). Parte das
> 12 decisões + ajustes de `2026-10-05-ao-vivo-ordens-decisoes.md` e do
> rascunho visual aprovado
> (`.superpowers/brainstorm/1270-1791478735/content/ordens-operacao-v2.html`).
> Herda a captura (parte 2) e o papel (parte 3). **É a entrega mais delicada
> do projeto: as seções 5 e 6 são o coração dela.**

## 1. Objetivo

A automação passa a mandar ordens à conta demo, copiando o papel: a mesma
operação, no mesmo minuto, com os contratos da conta. O usuário compara
papel × demo (derrapagem, atraso, ordens perdidas) e só depois, numa parte
própria, liga a conta real (§9).

Princípio: **o papel decide, a corretora executa, a automação reconcilia os
dois.** Na dúvida, a automação **protege e espera** — nunca entra nem sai
por falta de informação.

## 2. Decisões travadas

As 12 decisões e os ajustes 5a, 6a, 13 e 14 de
`2026-10-05-ao-vivo-ordens-decisoes.md`, mais (08/10/2026):

- **6b** — Conta travada fica travada até o próximo pregão, sem destravar.
- Aprovadas pelo usuário em 08/10/2026:
  - **D1** Stop e alvo da demo no **mesmo preço** do papel, com teto: se o
    preço de entrada já estiver a mais de 1,5× a distância de stop do plano,
    não entra (§5.4).
  - **D2** O limite de perda do dia é **da conta** (é assim na corretora e na
    mesa): soma tudo o que há nela — todos os portfólios que usam a conta e a
    operação feita à mão. A trava só encerra as da automação e avisa das
    outras. **Na tela, o número do portfólio e o da conta nunca se misturam**
    (§8): o resultado do portfólio é só das variantes dele; a barra "perda do
    dia da conta" mostra a conta inteira, aberta em "este portfólio · outros
    portfólios · fora da automação".
  - **D3** Execução parcial é aceita; o resto da ordem nunca fica vivo
    (preenchimento IOC ou cancelamento imediato) (§5.2).
  - **D4** Posição da automação que o papel **sabidamente** não tem é
    encerrada sozinha (saída atrasada). Isso substitui o chamado "posição
    diferente da esperada" do ajuste 5a. Posição aberta à mão nunca é tocada.
- **Regra de trabalho (usuário, 08/10):** todo uso da API do MetaTrader 5 é
  conferido na documentação oficial (mql5.com/en/docs e
  mql5.com/en/docs/python_metatrader5) antes de entrar no plano e de novo na
  implementação; o que a documentação não garante (ex.: lista vazia logo
  após reconectar) é tratado como incerto e protegido. §6.5 registra o que
  já foi conferido.

## 3. Onde roda e o caminho até a ordem

- **No processo da captura** (decisão 11), no mesmo fio de execução (o pacote
  MetaTrader5 não é seguro entre threads).
- **Ordem da volta:** conectar MT5 → buscar candles → **papel → ordens** →
  gravar candles/papel no banco → conferências → publicar `estado.json`.
  As ordens vêm antes de qualquer escrita no banco e de qualquer conferência
  (o `export_parquet` pode levar segundos).
- **O caminho da ordem não usa o banco.** Uma mineração gravando, a tela
  salvando um plano ou o próprio Parquet não podem atrasar uma saída:
  - **Aquecimento** (pregões anteriores ao dia, `papel.barras_do_dia`): lido
    do banco **uma vez por pregão** (na subida ou na virada do dia) e mantido
    em memória por ligação. Sem aquecimento carregado = papel indisponível
    (§5.1).
  - **Barras de hoje:** da memória da captura (o que o MT5 devolveu), não do
    banco. O banco continua sendo gravado como hoje; ele é o espelho.
  - **Configuração** (ligações, fase, ligada, planos do dia, contratos da
    conta, contas, Envio, limite): um **retrato** lido do banco sempre que a
    leitura der certo, mantido em memória. Mudança feita na tela vale quando
    o retrato for relido (a tela mostra "aplicado às HH:MM:SS").
  - **Comandos da tela** (zerar tudo, encerrar posição): arquivo atômico em
    `data/ao_vivo/comandos/` (a tela escreve, a captura consome e apaga,
    resultado no `estado.json`). Não passam pelo banco.
  - **Diário de ordens:** primeiro no arquivo local (§7.2), depois no banco.
- **Papel ao vivo enxerga a barra em formação.** O motor só cria a entrada
  (ou a saída por sinal) do sinal da barra *i* quando a barra *i+1* existe
  (`kernel.py:324`), e a captura nunca grava o candle em formação. Sem
  correção, toda entrada apareceria 1 min atrasada. Correção: no cálculo do
  pregão vivo (não na conferência), o papel recebe uma **barra provisória**
  no minuto em formação, com abertura, máxima, mínima e fechamento iguais à
  **abertura** desse minuto (vinda do MT5). Isso faz a entrada e a saída por
  sinal aparecerem no primeiro segundo do minuto, ao preço de abertura — o
  mesmo que o backtest usa. O motor não muda; a barra provisória nunca é
  gravada em `bars_m1`, e a operação do papel gravada com ela é provisória
  como toda operação aberta (o candle real substitui no minuto seguinte).
  Teste obrigatório: sinal no fechamento das 10:00 → ordem às 10:01:0x.

### 3.1 Velocidade: meta de menos de 1 s

O backtest supõe a execução na **abertura** do minuto seguinte ao sinal.
Cada segundo de atraso vira derrapagem que o backtest não tem. A ordem não
espera gravar candle no banco nem atualizar a tela; o caminho é:

1. **Virada do minuto.** No pregão, a volta fica rápida perto da virada:
   dos 2 s antes até os 10 s depois de cada minuto (relógio do servidor), a
   volta roda a cada **100 ms**; no resto do minuto, a cada 1 s (como hoje).
   O minuto novo é reconhecido no primeiro tick dele (`copy_rates` já traz a
   barra em formação).
2. **Papel só das ligações que operam primeiro.** Logo no minuto novo,
   calcula só as ligações em fase demo (com o aquecimento em memória, §3) e
   manda as ordens; as demais ligações, a gravação no banco e as
   conferências vêm depois, na mesma volta.
3. **Envio.** `order_send` direto ao terminal; a resposta da corretora é o
   tempo de rede.

Orçamento: virada → ordem enviada **< 1 s** (cálculo do papel < 300 ms por
ligação, medido em teste com o aquecimento real da maior estratégia do
portfólio). Cada ordem grava `atraso_ms` (abertura do minuto no servidor →
execução); a tela mostra o atraso médio e a faixa de saúde fica âmbar acima
de 2 s em média no dia.

## 4. Quem opera

Uma ligação **pode entrar** na demo quando, no retrato da configuração:

1. `fase = 'demo'`;
2. portfólio ligado e ligação ligada **agora**;
3. portfólio com `conta_demo_id` de conta não arquivada, com `login`,
   `servidor` e **limite de perda do dia** cadastrados;
4. **Envio de ordens** da conta ligado (`contas.envio_ligado`, começa
   desligado) — desligado, tudo é calculado e registrado como "seria
   enviada";
5. conta não travada hoje (§5.7);
6. o MT5 está logado nessa conta (`account_info()` lido **a cada volta**,
   antes de qualquer ordem — hoje só é lido no login, `captura.py:304`);
7. o plano tem stop (`stop_px` sempre preenchido). Plano sem stop não pode
   ser promovido para demo (a ficha recusa com o motivo).

**Saída não depende de 1–5:** toda posição com magic da automação
(`7_000_000 + ligacao_id`) na conta logada é reconciliada, em **qualquer
contrato**, mesmo que a ligação tenha deixado de operar (desligada, voltou ao
papel, removida, Envio desligado, conta travada). Depende só de 6 (conta
certa logada).

Fase: o usuário promove papel → demo na ficha (Ao vivo › Estratégias), com
confirmação; volta para papel do mesmo jeito (encerra a posição, decisão 12).
Migração idempotente no `schema.sql`: `real_minimo` → `real` (o
`_FASE_CONTA` de `core/ao_vivo.py` já os trata igual).

## 5. O motor de ordens

### 5.1 Reconciliação: desejado × corretora

**Desejado**, por ligação, tem três estados:

- **posição** — o papel calculado **nesta volta ou na anterior, por este
  processo**, tem operação aberta (`aberta`, `conta`) e a ligação está ligada
  agora: lado, `stop_px`, `alvo_px`, `entry_ts`, `entry_px`. A chave da
  operação é **`(ligacao_id, entry_ts)`** (a mesma `UNIQUE` de
  `papel_operacoes`); o `op_id` só aparece no espelho do banco.
- **zerado** — o papel calculado por este processo não tem operação aberta,
  ou a ligação foi desligada / saiu da fase demo / o Envio foi desligado /
  a conta travou / "zerar tudo".
- **indisponível** — não há cálculo fresco do papel: processo recém-aberto
  antes do primeiro cálculo, cálculo que falhou, aquecimento não carregado,
  pregão `interrompido` sem conhecer a saída, MT5 sem relógio do servidor.
  **Indisponível não entra nem sai**: só confere a proteção (SL/TP) que já
  está na corretora. Na subida, a captura calcula o papel imediatamente
  (sem esperar candle novo). Indisponível há mais de 3 min no pregão →
  chamado "papel parado".
  - Exceção: pregão `interrompido` porque a variante foi **removida** ou o
    **código mudou** → vira **zerado** (sai), porque o papel não saberá mais
    a saída dela.

**Corretora**: `positions_get()` sem filtro de símbolo, separado por magic;
mais `orders_get()` (ordem em trânsito). **`None` = volta perdida, nenhuma
ação** (o MT5 devolve `None` em erro). Nos 5 s depois de (re)conectar, a
lista de posições pode vir vazia antes de sincronizar: **nenhuma entrada
nesses 5 s**.

**Casamento por ticket, não por lado.** A entrada executada grava no diário
o ticket da posição. Cada posição da corretora é casada com a operação pelo
ticket.

| Desejado | Corretora | Ação |
|---|---|---|
| posição, entrada há ≤ 30 s, nunca enviada (diário) | nada | **entrar** (§5.2) |
| posição, entrada há > 30 s, nunca executada | nada | registra "não executada" (motivo do último erro, ou "automação fora do ar") — uma vez |
| posição | nada, mas o diário tem o ticket | saiu na corretora antes do papel (SL/TP do servidor, ou o usuário no MT5): registra, **não reentra** |
| posição | posição com o ticket dela | **conferir proteção** (§5.4) |
| qualquer | posição da ligação com ticket que não é o da operação atual (operação anterior que não saiu, duplicada) | **sair** dela (D4) |
| zerado | posição da ligação | **sair** (§5.3) |
| indisponível | qualquer | só conferir proteção |
| zerado | nada | nada |

Ordem em trânsito (`orders_get` com o magic) bloqueia qualquer nova ordem
daquela ligação até se resolver. É idempotente: rodar duas vezes seguidas não
faz nada a mais.

### 5.2 Entrada

- **Antes de enviar, o diário local recebe "enviando"** (com chave, lado,
  contratos, contrato) — escrita adiantada (§7.2). Sem ela, uma queda logo
  depois do envio duplicaria a entrada.
- Ordem a mercado (`TRADE_ACTION_DEAL`) com `sl`/`tp` na mesma ordem, `magic`
  da ligação, `comment` curto com a hora da entrada (a corretora pode
  apagá-lo; quem identifica é o magic + ticket), `deviation` = derrapagem do
  plano + folga (valor no plano de implementação).
- **Preenchimento:** `symbol_info().filling_mode` é uma máscara de bits
  (1 = FOK, 2 = IOC), diferente da numeração de `ORDER_FILLING_*`
  (FOK 0, IOC 1, RETURN 2). Mapear; preferir **IOC**. Com RETURN, cancelar o
  resto (`TRADE_ACTION_REMOVE`) na hora — resto de ordem nunca fica vivo (D3).
- Antes: `order_check` (sucesso = `retcode 0`) e a checagem 6a, com o
  **preço corrente**: perda do dia + (distância corrente até o stop ×
  contratos × valor do ponto + custos) > 90% do limite → não entra.
- Retornos (tabela única, §6): `DONE` executou; `DONE_PARTIAL` executou em
  parte (D3); **`PLACED` = aceita, aguardando** — nunca reenvia: espera a
  posição ou a recusa aparecer (`orders_get`/`history_orders_get`).
- Passageira → nova tentativa na volta seguinte, **até 30 s da abertura do
  minuto de entrada** (relógio do servidor; sem relógio, não entra). Antes
  de cada nova tentativa: `positions_get` + `orders_get` +
  `history_deals_get` do dia com o magic — se a anterior executou sem a
  resposta chegar, **adota** em vez de reenviar.
- Posição aberta sem SL/TP (aceitou a entrada, não a proteção):
  `TRADE_ACTION_SLTP` imediato; recusado → **encerra a posição**. Posição da
  automação sem stop não pode existir.

### 5.3 Saída

- Por preço (stop/alvo): é o SL/TP do servidor. Se o papel saiu por
  stop/alvo e a corretora ainda tem a posição, encerra a mercado — o papel
  manda.
- Por sinal, tempo, fechamento, desligar, zerar: ordem a mercado contrária
  com `position=<ticket>` (hedging), na mesma volta em que o desejado vira
  zerado.
- **Nunca desiste:** passageira → tenta a cada volta, sem limite
  ("saída pendente — tentando (Nª)"). Mais de 2 min → chamado, e segue
  tentando. `POSITION_CLOSED` = já saiu, só registra.
- Posição sem magic da automação (aberta à mão): nunca tocada; aviso
  "posição fora da automação".

### 5.4 Proteção (SL/TP) e stop móvel

- ⚠ D1: SL/TP = **preço** `stop_px`/`alvo_px` do papel. Teto: se
  `|preço corrente − stop_px|` > 1,5 × a distância de stop do plano, não
  entra ("preço longe demais do stop do papel"). Preço já além do stop **ou
  do alvo** do papel: não entra.
- **Arredondamento ao tick sempre para longe da entrada** (stop de compra
  para baixo, alvo de compra para cima; espelhado na venda), respeitando
  `trade_stops_level`. A comparação "a corretora tem o SL certo?" usa o valor
  **já arredondado** — senão um stop por ATR fora do tick geraria uma
  modificação a cada volta.
- Papel moveu o stop (`stop_fim`): `TRADE_ACTION_SLTP` na mesma volta.
  `NO_CHANGES` = já está certo. Recusado porque o preço já passou do novo
  stop → encerra a mercado.
- Passageira → tenta a cada volta; a proteção anterior segue valendo.

### 5.5 Contratos

- Papel: sempre os do plano.
- Conta: `portfolio_membros.contratos_demo` (e `contratos_real`, só a
  coluna, para a parte da conta real). NULL = do plano. Editável no cartão
  (Ao vivo › Operação) e na ficha (Ao vivo › Estratégias); **nunca** em
  Mineração/WFA/Candidata.
- Vale a partir da próxima entrada (a posição aberta segue com o volume com
  que entrou, gravado no diário). Ao editar, a tela mostra o custo de um stop
  do plano × contratos contra o limite do dia. Evento `contratos_alterados`
  em `ao_vivo_eventos`.

### 5.6 Contrato do dia (rolagem)

- Na primeira volta do pregão com MT5 conectado, a automação escolhe, dentre
  `symbols_get("WIN*")` negociáveis, o de último preço **igual** ao do
  `WIN$N` (o que o papel olha); reserva: maior volume no pregão anterior.
  Fixo no dia (nada atravessa a noite).
- **Dia do vencimento (decisão 7):** se o contrato igual ao `WIN$N` vence
  hoje, a demo **não entra** naquele dia (o papel roda; aviso "vencimento:
  sem entradas hoje"). O dia em que o `WIN$N` da Clear passa para o contrato
  seguinte será **medido no vencimento de 14/10/2026** (WINV26) com o papel
  rodando, e o resultado registrado no `AGENTS.md`; a regra acima é segura
  qualquer que seja.
- Véspera: faixa "rolagem" avisando o contrato de amanhã.
- Guarda: último preço do contrato e do `WIN$N` afastados mais de 2 ticks
  por mais de 1 min → entradas param (chamado "preço do contrato não bate");
  saídas seguem.

### 5.7 Limite de perda do dia da conta

- Perda do dia = realizado no dia (negócios do dia, com custos) + resultado
  aberto, **lidos da corretora**. ⚠ D2: tudo o que há na conta.
- Chegou a 90% do limite: zera as posições da automação daquela conta (saída
  que nunca desiste), **trava até o próximo pregão** (evento `conta_travada`
  com o dia, no diário de ordens; sobrevive a reinício), avisa das posições
  fora da automação. Sem destravar (6b). O papel segue.
- Sem limite cadastrado: o Envio de ordens não liga.

### 5.8 Zerar tudo e desligar envio

Botão do topo (dois cliques): comando "zerar_tudo" (arquivo, §3) → a captura
desliga o Envio de todas as contas e o desejado de todas as ligações vira
zerado. Desligar portfólio, variante ou Envio com posição aberta (decisão 12)
avisa "isso encerra N posição(ões)" e segue o mesmo caminho. Se a captura
estiver fora do ar, a tela diz que o comando ficou esperando e que stop/alvo
seguem na corretora.

O Envio de ordens ligado/desligado é gravado no banco (`contas.envio_ligado`)
**e** vai junto no comando, para valer na volta seguinte mesmo com o banco
ocupado.

## 6. Falhas

Toda falha cai numa de três caixas. A classificação é por **código de
retorno do MT5, numa tabela única** (`core/corretora.py`), testada linha a
linha. Códigos que a tabela precisa ter, no mínimo: `DONE` (10009),
`PLACED` (10008), `DONE_PARTIAL` (10010), `REQUOTE` (10004), `REJECT`
(10006), `TIMEOUT` (10012), `INVALID_STOPS` (10016), `MARKET_CLOSED`
(10018), `NO_MONEY` (10019), `PRICE_CHANGED` (10020), `PRICE_OFF` (10021),
`TOO_MANY_REQUESTS` (10024), `NO_CHANGES` (10025), `SERVER_DISABLES_AT`
(10026), `CLIENT_DISABLES_AT` (10027), `CONNECTION` (10031),
`POSITION_CLOSED` (10036), `CLOSE_ONLY` (10044), e `None`.

Os demais códigos da documentação também entram na tabela, classificados:
`INVALID`, `INVALID_VOLUME`, `INVALID_PRICE`, `INVALID_EXPIRATION`,
`INVALID_ORDER`, `TRADE_DISABLED`, `ONLY_REAL`, `LIMIT_*`, `LONG_ONLY`,
`SHORT_ONLY`, `FIFO_CLOSE`, `HEDGE_PROHIBITED` → precisa do usuário (são
configuração, não instante); `LOCKED`, `FROZEN`, `ORDER_CHANGED`, `ERROR` →
passageira; `CLOSE_ORDER_EXIST` → já há saída em trânsito, espera;
`INVALID_FILL` → troca para o outro modo de preenchimento permitido uma vez,
e chama se persistir; `INVALID_CLOSE_VOLUME` → relê a posição e manda o
volume dela.

Na conexão, a automação confere `account_info().margin_mode` = hedging
(decisão 1); se não for, nenhuma ordem e chamado "conta não é hedging".

### 6.1 Passageira — resolve sozinha

Requote, preço mudou/fora, leilão/mercado fechado por instantes, timeout,
muitos pedidos, conexão, `None` com terminal conectado. Entrada: até 30 s.
Saída e proteção: sempre. Cada tentativa vai ao diário; a tela agrupa.

### 6.2 Precisa do usuário — chama (faixa, som, título da aba)

| Situação | O que a automação faz |
|---|---|
| MT5 fechado / sem conexão | nada pode; stop/alvo no servidor; ao voltar, reconcilia |
| Algo Trading desligado (`trade_allowed` falso ou `CLIENT_DISABLES_AT`) | nenhuma ordem; ao religar, reconcilia |
| Conta errada logada | nenhuma ordem |
| Sem margem (`NO_MONEY`) | entrada perdida; saída segue tentando |
| Saída pendente > 2 min | segue tentando |
| Preço do contrato ≠ WIN$N | para entradas |
| Papel parado (indisponível > 3 min no pregão) | só protege |
| `CLOSE_ONLY` | para entradas naquele contrato |
| Retorno desconhecido | saída: tenta de novo; entrada: perdida; chama |

Botões, quando há posição envolvida: **Encerrar posição** (comando) e
**Manter e acompanhar** (só fecha o aviso, sem comando).

### 6.3 Avisos que não param nada

Posição fora da automação; parcial; derrapagem acima do esperado; entrada
pulada pela checagem 6a ou pelo teto D1; fechamento do plano depois do fim
real do pregão (a zeragem da corretora vira a rede).

### 6.4 Casos que o plano tem de cobrir com teste próprio

1. Sinal no fechamento das 10:00 → ordem às 10:01:0x (barra provisória).
2. Entra e sai no mesmo minuto de entrada (stop na barra de entrada).
3. Ordem executa, resposta não chega → a seguinte adota, não duplica.
4. `PLACED` → espera, não reenvia.
5. Queda entre "enviando" no diário e o envio / entre o envio e a resposta.
6. Reinício às 10:30:20 com 3 posições abertas → indisponível até calcular;
   **nenhuma sai** por falta de papel.
7. Reinício com `positions_get` vazio nos primeiros segundos → não duplica.
8. Captura fora do ar enquanto o papel sai → ao voltar e calcular, sai.
9. Operação anterior stopada no papel mas não no servidor + nova operação do
   mesmo lado no minuto seguinte → a antiga sai (ticket), a nova entra.
10. SL do servidor executa no mesmo minuto em que o papel move o stop →
    `POSITION_CLOSED`, só registra.
11. Candle revisado apaga a operação do papel → sai; faz surgir entrada no
    passado → não entra.
12. Usuário fecha no MT5 à mão → não reentra.
13. Desligar a variante às 10:20 com operação que entrou às 10:10 → sai
    (ligada **agora**, não só no `entry_ts`).
14. Envio desligado / fase volta para papel / conta trava com posição aberta
    → sai (universo por magic).
15. Trava a 90% com saída pendente → trava mesmo assim; a saída segue.
16. Reinício depois da trava → continua travada.
17. Contrato vence hoje → sem entradas; véspera avisa.
18. Banco ocupado 2 min (mineração gravando) → entrada e saída saem igual.
19. Relógio do PC atrasado; MT5 sem tick (sem relógio) → sem entrada.
20. Parcial com RETURN → resto cancelado na hora.
21. Plano sem stop → promoção recusada.
22. Stop por ATR fora do tick → uma modificação só, não uma por volta.

### 6.5 Conferido na documentação oficial (08/10/2026)

- `order_send` (mql5.com/en/docs/python_metatrader5/mt5ordersend_py):
  campos `action`, `position` (ticket, para fechar/alterar a posição),
  `type_filling`, `deviation` (pontos), `magic`, `comment`, `sl`, `tp`; o
  exemplo oficial fecha com ordem contrária e `position=<ticket>`. A página
  não diz o que volta em erro — tratar `None` como possível.
- Preenchimento (mql5.com/en/docs/constants/tradingconstants/orderproperties):
  em **execução em bolsa** (B3), FOK e IOC só valem se o símbolo os permitir;
  **RETURN vale sempre** e deixa o resto da ordem viva — por isso D3 manda
  cancelar o resto. `SYMBOL_FILLING_MODE` é máscara de bits (FOK = 1,
  IOC = 2), não o valor de `ORDER_FILLING_*`: testar com `&`.
- Códigos de retorno (mql5.com/en/docs/constants/errorswarnings/
  enum_trade_return_codes): lista completa 10004–10046 usada no §6.
- `positions_get` (…/mt5positionsget_py): `None` em erro; sem parâmetro
  devolve todas as posições abertas. O que volta logo após reconectar não é
  documentado → regra dos 5 s do §5.1.
- A conferir no plano de implementação, também na documentação: `orders_get`,
  `history_deals_get`, `history_orders_get`, `order_check`,
  `symbol_info` (`trade_stops_level`, `trade_exemode`, `expiration_time`),
  `account_info` (`margin_mode`), `terminal_info` (`trade_allowed`).

## 7. Dados

### 7.1 Banco (`core/schema.sql`, `IF NOT EXISTS`, backup antes)

- `contas.envio_ligado BOOLEAN DEFAULT false`.
- `portfolio_membros.contratos_demo BIGINT`, `.contratos_real BIGINT`;
  migração `fase 'real_minimo' → 'real'`.
- **`ordens_eventos`** — só inserção, espelho do diário local: `evento_id`
  (chave do arquivo), `quando`, `conta_id`, `ligacao_id`, `entry_ts` (chave da
  operação), `tipo` (enviando|executada|parcial|recusada|perdida|
  seria_enviada|adotada|saida|protecao|cancelada|chamado|chamado_fechado|
  conta_travada|rolagem|comando), `lado`, `contratos`, `simbolo`, `ticket`,
  `retcode`, `preco_papel`, `preco`, `atraso_ms`, `tentativa`, `motivo`.
  O estado de cada ordem é **derivado** dos eventos (não há tabela com
  UPDATE). Tabela protegida (não se recria): entra na lista do `AGENTS.md`.

### 7.2 Diário local (escrita adiantada)

`data/ao_vivo/ordens/AAAA-MM-DD.jsonl`: cada evento vai **primeiro** ao
arquivo (uma linha JSON, `flush` + `fsync`) e depois ao banco, quando livre.
Na subida, a captura relê o arquivo do dia (é dele, não do banco, que vem "já
enviei a entrada X", "o ticket da operação Y", "conta travada hoje") e
reenvia ao banco as linhas que faltam, pela chave do evento.

### 7.3 `estado.json`

Bloco `ordens`: por conta — envio ligado, travada (desde), conta logada
confere, Algo Trading, margem livre, perda do dia, contrato do dia, sinal de
vida, retrato da configuração (hora); por ligação — desejado (posição/
zerado/indisponível), posição na corretora (lado, volume, preço, SL, TP,
resultado aberto), ordem pendente (tipo, tentativas, desde); chamados
abertos; resultado dos comandos; `ordens_em`. A tela só lê o banco quando
`ordens_em` muda.

## 8. Tela

Segue o rascunho v2 aprovado, com estes acertos:

- **Topo (todas as abas):** selo da conta e botão **Zerar tudo e desligar
  envio**.
- **Ao vivo › Operação:** faixa de saúde; faixa "precisa de você"; cabeçalho
  com contrato do dia e Envio de ordens; três números; Posições abertas
  (conferidas com a corretora, proteção ✓, ticks até stop/alvo, desejado
  "indisponível" visível); cartões (contratos da conta editáveis) ao lado do
  gráfico; Operações do dia (derrapagem em ticks, Situação); Diário do dia;
  Avaliação recolhível. O exemplo de chamado "comprado 2, esperado 1" sai
  (D4); o da implementação é "saída pendente há 2 min".
- **Ao vivo › Estratégias (ficha):** fase com "Promover para demo" / "Voltar
  para papel" (confirmação; recusa plano sem stop); contratos da conta;
  conta do portfólio com limite do dia e Envio de ordens.
- **Números do portfólio × da conta (D2):** "Resultado hoje" e as variantes
  são só deste portfólio. A barra "Perda do dia da conta" é da conta inteira
  e diz isso no rótulo, aberta em "este portfólio R$ X · outros portfólios
  R$ Y · fora da automação R$ Z" — a soma é o que a corretora mostra.
- **Papel × backtest (pergunta do usuário):** a cadeia é backtest → papel →
  demo. Backtest e papel usam o mesmo motor e os mesmos candles, então devem
  bater **operação por operação**; a demo difere deles só pela execução.
  Para isso não ser só promessa, toda manhã, depois da reconferência, a
  captura roda o **backtest do plano** nos pregões desde que a ligação entrou
  e compara com o papel gravado: mesma hora, lado, preço de entrada e saída,
  motivo da saída. A Avaliação mostra "papel = backtest ✓ (5 pregões, 14
  operações)" ou "2 diferenças" com a lista. Se o selo cair, a variante não
  pode ser promovida (e a tela explica). A faixa p10–p90 continua
  respondendo a outra pergunta: se o resultado está dentro do que a
  Candidata prometeu.
- **Alarme:** som + título da aba piscando no chamado e na trava, em qualquer
  aba.
- (?) com faixa boa/ruim em toda métrica nova. Conta real escondida.

## 9. Conta real — fora desta parte

Desenhada só em linhas gerais, para a arquitetura não fechar a porta: outro
processo no terminal da conta real, sem gravar candles, com trava,
`estado.json` e diário próprios. **Como** ele recebe o papel (banco ou
arquivo) será decidido com a medição da demo. Nenhum código da conta real
nesta parte além da coluna `contratos_real`.

## 10. Testes

- **Nenhum teste fala com MT5 de verdade nem envia ordem.** MT5 falso
  (`tests/mt5_falso.py`): posições, ordens, negócios, retornos programáveis,
  `None`, lista vazia após reconexão, relógio controlado.
- Tabela de retornos: um teste por código. Reconciliação: um teste por linha.
- Os 22 casos de §6.4, um teste cada.
- Diário local: queda entre arquivo e banco; reenvio sem duplicar.
- Barra provisória: o papel com ela dá a mesma entrada (hora e preço) que o
  papel do minuto seguinte com o candle real de abertura igual.
- Mutação (agente `mutacao`) obrigatória em `core/ordens.py`,
  `core/corretora.py` e na montagem da barra provisória.
- **Ensaio antes de ligar:** um pregão inteiro com Envio desligado ("seria
  enviada") conferido contra o papel; depois a demo com 1 contrato.

## 11. Fora desta parte

Conta real (§9); alerta no celular; histograma de derrapagem; atalhos;
exportar o dia; aba Conta; "sair no sinal contrário" minerável; recursos com
LLM (memória `ideias-depois`).
