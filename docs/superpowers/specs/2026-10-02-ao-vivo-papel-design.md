# Projeto C, parte 3: incubação em papel e sub-tela Operação

> Terceira parte da tela **Ao vivo**. Herda da seção 1
> (`2026-09-30-ao-vivo-estrategias-design.md` §4, §10) e da parte 2
> (`2026-10-01-ao-vivo-captura-design.md`). Ordens, contas demo/real e o
> comparativo com elas são a parte 4.

Desenhado em 02/10/2026 com o usuário; layout aprovado em rascunho visual
(`.superpowers/brainstorm/67-1790900038/content/operacao-portfolio-v2.html`).
Revisado por agente contra o código (medições no banco real citadas abaixo).

## 1. Objetivo

Ver a estratégia **rodando ao vivo**: operações do dia no gráfico, posição e
resultado de cada variante, acumulado contra o que o plano prometeu e — a
partir da parte 4 — o comparativo papel × demo/real (derrapagem, atrasos).

Fora do objetivo (decisão do usuário): disjuntor que desliga sozinho e
critério automático para subir de fase.

## 2. Decisões travadas (02/10/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Execução | **Igual ao backtest**: mesmo motor, mesmos candles, entrada na abertura do candle seguinte ao sinal, derrapagem e custos do perfil do plano. |
| 2 | Onde roda | **No serviço de captura**, depois de gravar candle novo. |
| 3 | Estado | Sem posição em memória: o dia é **recalculado inteiro** a cada candle novo. |
| 4 | Interruptor | O papel calcula o dia **inteiro** de toda ligação não removida, ligada ou não, portfólio ligado ou não. O interruptor **só marca** o que conta: operação com entrada fora do período ligado (variante e portfólio) fica `conta = false` — aparece apagada e fora do acumulado. As ordens reais (parte 4) é que obedecem o interruptor. |
| 5 | Código mudou | Se o hash do código da estratégia muda **no meio do pregão**, o que já foi gravado **fica**, o pregão vira `interrompido` e nada mais é calculado no dia. No pregão seguinte, sem plano novo, fica `pulado` ("código mudou desde o plano"). |
| 6 | Dia corrigido depois | Papel de pregão **conferido fica congelado**. Se os candles do dia mudarem depois (reimportação, Sincronizar, reparo), o checksum gravado acusa divergência (aviso na tela e no auditor); o papel não muda. |
| 7 | Stop da posição aberta | Mostra o **stop e o alvo atuais** (já com breakeven/stop móvel): o motor ganha duas saídas (§4.5). |
| 8 | Contratos | O papel opera **os contratos do plano**. Comparação com demo/real (parte 4) sempre **por contrato e em pontos**; o total "com o tamanho real" à parte. |
| 9 | Coluna "Backtest" | Vira **"Esperado (WFA)"**: médias por operação e por contrato dos trades fora da amostra do walk-forward que gerou o plano. |
| 10 | Faixa esperada | p10–p90 **por variante**; na visão do portfólio, curva do papel + **soma das medianas** (sem faixa: somar percentis não dá o percentil da soma). |
| 11 | Tela | Sub-tela **Ao vivo › Operação**, um portfólio por vez (§6). A visão de todos ("Mesa", por conta/ativo) é entrega futura. |

**Requisito herdado para a parte 4** (pedido do usuário, 02/10/2026): ao
pausar um portfólio ou variante com posição aberta na demo/real, perguntar
**encerrar a posição × só não abrir novas** (já previsto na seção 1 §10).

## 3. Quem entra no papel

Toda ligação em `portfolio_membros` com `removido_em IS NULL` cujo plano em
vigor é do símbolo da captura (`WIN$N`). Mesma variante em dois portfólios:
calcula **uma vez por `plano_id`** e grava para cada ligação.

`conta` de cada operação (decisão 4): `true` se, no minuto da entrada, a
ligação estava ligada **e** o portfólio estava ligado. Os horários vêm do
diário (`ao_vivo_eventos`: `membro_ligado/desligado`,
`portfolio_ligado/desligado`, `membro_adicionado`) — não há coluna de horário
em `portfolio_membros`. Ligação adicionada hoje: operações antes da adição
não contam.

## 4. Motor do papel

### 4.1 Plano e perfil do dia

- `plano_do_dia(ligacao, dia)`: no primeiro cálculo do pregão grava em
  `papel_pregoes` o `plano_id` de `variantes.plano_em_vigor(variante, dia)`;
  recálculos do mesmo dia usam **o `plano_id` gravado** (reinício da captura
  não troca o plano). Sem plano em vigor → `pulado`, motivo de
  `ao_vivo._motivo` ("sem plano em vigor").
- Montagem (mesma separação de `wfa_runner.trades_oos_detalhados`
  `core/wfa_runner.py:359-362`):
  - `exec_ = {k: v for k, v in plano.params.items() if k in CAMPOS_EXECUCAO_NOMES}`
  - `estrat = {k: v for ... if k not in CAMPOS_EXECUCAO_NOMES}`
  - `perfil = replace(ExecutionProfile(**plano.profile), **exec_,
    modo_posicao="contratos_fixos", contratos=plano.contratos)`
  - **Proibido** `ExecutionProfile.from_config` (o perfil gravado é plano, e
    `from_config` devolveria o padrão sem avisar — `core/engine/execution.py:90-96`).
- Grava em `papel_pregoes`: `plano_id`, `codigo_hash`, `motor_versao`
  (`engine.VERSAO`).

### 4.2 Código carregado

`codigo.hash_estrategia` lê o **disco**; a captura importa a estratégia uma
vez (`strategies/registry.py:53-61`). O papel guarda `(hash, módulo)` por
estratégia: quando o hash do disco muda, **recarrega** `strategies.base` e o
módulo da estratégia (sem o cache do registry) e aplica a decisão 5. Plano
com `codigo_hash` nulo (antigo) **roda com aviso**, como na seção 1 §4.6
(`core/ao_vivo.py:345,394`).

### 4.3 Barras e aquecimento

- Só calcula se **existe candle de hoje** gravado (nada de pregão em fim de
  semana/feriado/antes da abertura).
- Aquecimento (medido: 10 pregões **não** bastam — `reversao_rsi` tendência
  600 em M15 divergiu em 32 de 59 pregões): pregões de aquecimento =
  ⌈(maior parâmetro de período da estratégia × minutos do tempo gráfico +
  período do ATR × minutos do tempo gráfico) / minutos de um pregão⌉ + 2.
  Estratégia pode declarar `aquecimento_barras(params)`; estratégia com
  indicador **recursivo** (média exponencial etc.) é obrigada a declarar.
  Hoje nenhuma é recursiva.
- Pregões contados pelas **datas distintas de `bars_m1`** (o `trading_days`
  só ganha o dia após a conferência).
- Barras lidas do **banco** (o dia não está no Parquet), **uma vez por
  volta** para o símbolo, com o maior aquecimento entre as ligações.

### 4.4 Cálculo e gravação

1. `run_strategy(barras, estrategia, estrat, perfil, instrumento)`.
2. Operações com **entrada no dia**.
3. **Aberta** ⇔ `exit_i == n-1` **e** motivo ∈ {3 fechamento, 5 fim dos
   dados} **e** o minuto de `ts[n-1]` < `perfil.fechamento` **e** o pregão
   não foi conferido. (O motor trata o dia incompleto como pregão que fechou
   cedo e sai com motivo 3 na última barra — medido em 238 de 238 casos.)
   Saída na última barra por stop (0), alvo (1) ou tempo (4) é fechada.
4. Resultado da aberta: **marcação a mercado** pelo fechamento da última
   barra com a derrapagem do perfil (o que o motor já calcula), rotulado
   "provisório"; entra no resultado do dia da tela, não no `liquido`
   gravado do pregão até fechar.
5. **Upsert** por chave natural `(ligacao_id, entry_ts)`: `op_id` é dado na
   primeira inserção e **nunca muda** (a parte 4 liga execuções por ele).
   Operação que deixou de existir (só com correção de candle) é apagada.
6. Cálculo **fora** da conexão de escrita; gravação de todas as ligações
   numa só `connect_write`. Banco ocupado → marca "papel pendente" e refaz
   na volta seguinte mesmo sem candle novo. O papel nunca atrasa o
   `publicar` do estado.
7. A captura publica no `estado.json`: `papel: {calculado_em, ligacoes:
   {id: status}}` — é o que a tela usa para saber quando reler.

### 4.5 Stop e alvo atuais

O kernel (`core/engine/kernel.py`) já guarda `stop_px`/`tgt_px` por dentro;
ganha duas saídas (stop e alvo vigentes no fim) para a operação aberta.
Único ponto de chamada: `core/engine/execution.py:320`. Teste: com breakeven
e stop móvel, o stop final bate com o recalculado à mão; backtests antigos
não mudam (mesmos trades).

### 4.6 Ciclo no dia

- A cada candle novo gravado: recalcula o dia de cada ligação (decisões 3–5).
- Depois da conferência do dia: recalcula uma última vez com os candles
  conferidos, grava o **checksum** das barras do dia (quantidade + soma de
  OHLC) e marca `conferido`. A partir daí congelado (decisão 6).
- Na manhã seguinte, a **reconferência** dos candles (spec da captura §5)
  deixa o dia idêntico ao MT5 consolidado — o leilão de fechamento que a
  captura gravou às 18:31 vai para dentro do 18:24. Isso não é "correção
  posterior" (decisão 6): é o dia como o backtest o vê. Se o checksum do
  dia mudou, o pregão `conferido` volta a `rodando` e é conferido de novo
  na mesma conexão de escrita (`papel.reabrir_reconferido` + `conferir`),
  com os candles finais; os `op_id` ficam (upsert por `entry_ts`). Escolhido
  em vez de adiar o congelamento para a manhã: a tela mostra o pregão
  conferido na mesma noite e um dia que nunca é reconferido (PC desligado)
  não fica "rodando". Não reabre — fica congelado e a divergência acusa —
  o pregão que o `conferir` refaria diferente por outro motivo: variante
  tirada do portfólio no próprio dia depois do fechamento (seria encerrada
  como removida) e código da estratégia mudado desde então (seria
  interrompido). Reaberto cujo cálculo falha fica `rodando` num dia com a
  marca `conferencia://`, e a janela seguinte o confere como qualquer
  papel por conferir.
- Dias recuperados (PC desligado): ganham papel na conferência deles.
- Falha numa ligação não derruba a captura nem as outras (log + motivo).

## 5. Dados

```sql
CREATE SEQUENCE IF NOT EXISTS seq_papel_op START 1;
CREATE TABLE IF NOT EXISTS papel_operacoes (
    op_id        BIGINT PRIMARY KEY,
    ligacao_id   BIGINT NOT NULL,
    plano_id     BIGINT NOT NULL,
    dia          DATE NOT NULL,
    entry_ts     TIMESTAMP NOT NULL,
    exit_ts      TIMESTAMP,            -- nulo = aberta
    side         INTEGER NOT NULL,     -- +1 compra, -1 venda
    contratos    BIGINT NOT NULL,
    entry_px     BIGINT NOT NULL,
    exit_px      BIGINT,
    points       BIGINT,
    bruto        DOUBLE, custo DOUBLE, liquido DOUBLE,
    reason       INTEGER,              -- códigos de wfa_trades
    mae BIGINT, mfe BIGINT,
    stop_px      BIGINT, alvo_px BIGINT,   -- vigentes (aberta)
    aberta       BOOLEAN NOT NULL,
    conta        BOOLEAN NOT NULL,     -- decisão 4
    calculado_em TIMESTAMP NOT NULL,
    UNIQUE (ligacao_id, entry_ts)
);
CREATE TABLE IF NOT EXISTS papel_pregoes (
    ligacao_id   BIGINT NOT NULL,
    dia          DATE NOT NULL,
    plano_id     BIGINT,
    codigo_hash  VARCHAR,
    motor_versao VARCHAR,
    status       VARCHAR NOT NULL,     -- 'rodando'|'conferido'|'pulado'|'interrompido'
    motivo       VARCHAR,
    interrompido_em TIMESTAMP,
    n_operacoes  INTEGER,
    liquido      DOUBLE,               -- só operações fechadas que contam
    checksum     VARCHAR,              -- barras do dia na conferência
    calculado_em TIMESTAMP,
    PRIMARY KEY (ligacao_id, dia)
);
```

- Proteção da cadeia: `plano.motivo_protecao` (único ponto que barra apagar
  plano, WFA e mineração — `core/plano.py:283`, `core/wfa_store.py:199`,
  `core/optimizer.py:716`) passa a olhar `papel_operacoes`.
- Tabelas que **não se recriam**: atualizar os textos de
  `core/db_manager.py:7` e `cli.py:157`. Ficam fora de
  `reparo_base.TABELAS_DERIVADAS` (lista do que o reparo apaga).
- Contador de pregões **reais** da seção 1 (`ao_vivo.pregoes_com_plano`,
  `core/ao_vivo.py:423`) passa a contar `papel_pregoes` com status
  `rodando|conferido`.

## 6. Sub-tela Ao vivo › Operação

Seletor **Estratégias | Pregão | Operação**. Ids próprios (`av-op-*`);
`dcc.Interval` próprio de 2 s ligado só nesta sub-tela (o callback `subtela`
de `ui/callbacks_pregao.py:166-178` ganha a saída). A tela **não abre o
banco a cada 2 s**: lê `estado.json`; relê operações só quando
`papel.calculado_em` muda.

1. **Cabeçalho:** seletor de portfólio (lembra o último), ligado/desligado,
   ativo, contas demo/real, capital, "N variantes · M operando", botões "Ver
   ficha do portfólio" e "Desligar portfólio" (dois cliques, ação da seção 1).
2. **Seis indicadores** com (?) faixa boa/ruim:
   - resultado hoje (papel, fechadas + aberta provisória, só `conta`);
   - posição agora (líquida; por variante no subtexto; contratos);
   - pior momento hoje (mínimo da curva minuto a minuto do dia, fechadas +
     aberta marcada) × `contas.limite_perda_dia` da conta demo — limite nulo
     esconde a barra;
   - acumulado no papel (pregões, operações) **desde o plano em vigor**;
   - contra o esperado: **faixa** em que está (abaixo de p10 · p10–p50 ·
     p50–p90 · acima de p90), por variante; no portfólio, contra a soma das
     medianas;
   - papel × demo hoje ("—" até a parte 4).
3. **Gráfico** (mesmas regras do Pregão: `tick` sem perder zoom, 1/5/15 min,
   tela cheia, voltar para agora) com marcadores das operações de papel do
   dia: ▲ compra / ▼ venda na entrada, ◆ na saída, posição aberta com linhas
   de stop/alvo atuais. Uma cor por variante; operação com `conta = false`
   em cinza. (Ligar entrada e saída por linha: só se o componente suportar;
   senão, marcadores.)
4. **Variantes:** interruptor (ação da seção 1), fase, posição, hoje,
   operações, acerto (ganhadoras/fechadas do dia), acumulado, contratos
   "papel N · demo —", plano em vigor, etiqueta "gravado mesmo assim",
   status do pregão (pulado/interrompido com motivo). Risco do dia na conta
   demo embaixo.
5. **Operações do dia:** entrada, saída (ou "aberta" com stop/alvo atuais),
   variante, lado, contratos papel/demo, preços, pontos, resultado papel
   (provisório na aberta), saiu por, papel × demo por contrato ("—"). Filtro
   por variante. `conta = false` em cinza com "fora do período ligado".
6. **Papel × esperado:** curva acumulada **desde `vale_a_partir` do plano em
   vigor** (recomeça a cada plano). Faixa de `planos_operacao.expectativa`
   (`{"3_meses": {"pregoes": 63, "p10", "p50", "p90"}, ...}`, em R$ com os
   contratos do plano; pode vir parcial ou vazia — `core/plano.py:464-470`)
   interpolada por pregão. Por variante: faixa + mediana. Portfólio: curva +
   soma das medianas, sem faixa. Sem `expectativa`: só a curva, com aviso.
7. **Esperado (WFA) × Papel × Demo × Real** (mesmos pregões):
   - Tamanho: contratos por operação;
   - Resultado por contrato: resultado médio por operação, pontos por
     operação, fator de lucro, acerto; total com o tamanho real;
   - Execução: sinal no mesmo minuto (`entry_ts − 1 min` = minuto do sinal),
     derrapagem média, atraso, rejeitadas.
   "Esperado (WFA)" = médias dos `wfa_trades` do `wfa_id` do plano, por
   operação e por contrato. Demo/Real "—".
8. **Alertas:** plano gravado mesmo assim, código mudou/interrompido, pregão
   pulado, checksum divergente.

### 6.4 Muitas variantes
- Coluna de variantes: altura máxima = do gráfico, rolagem própria, ordem
  "posição aberta → resultado do dia".
- Nomes longos: uma linha com reticências + `title` com o nome completo.
- Operações do dia: altura máxima ~10 linhas, rolagem com cabeçalho fixo.
- Legenda do gráfico: chips roláveis; clicar esconde/mostra a variante.
  Mais de 8 variantes: cores repetem com marcador de forma diferente.
- Testar com 15 variantes e nomes de 40+ caracteres.

## 7. Erros e estados

- Captura parada: faixa da `situacao` do Pregão + "papel congelado em HH:MM".
- Ligação pulada/interrompida: cartão apagado com o motivo + alerta.
- Portfólio sem ligação: estado vazio ("adicione variantes em Portfólio e
  ligue em Ao vivo › Estratégias").
- Plano sem `expectativa`: §6.6.

## 8. Testes

| alvo | prova |
|---|---|
| identidade | papel de dias passados = trades do backtest sobre o histórico inteiro com entrada naquele dia (todas as estratégias do registry, parâmetros máximos, M1–H1) |
| aquecimento | o número de pregões calculado reproduz o histórico inteiro; com 1 pregão a menos, o teste de identidade falha para a estratégia mais longa |
| montagem | params com campos de execução: o stop/alvo do plano é usado (não o do perfil base); `from_config` não é usado |
| aberta | minuto a minuto num dia com operação longa: aberta (motivo 3/5 na última barra) até a saída real, depois fechada; nunca duas linhas; `op_id` estável |
| stop atual | breakeven/stop móvel: stop final correto; backtests antigos inalterados |
| queda | rodar só no fim = rodar a cada minuto |
| plano do dia | reinício no meio do dia usa o `plano_id` gravado |
| código | hash muda no meio → `interrompido`, manhã preservada; dia seguinte `pulado`; hash nulo roda com aviso; recarga do módulo |
| interruptor | operações fora do período ligado (diário) → `conta = false`; fora do acumulado |
| conferência | rerodada, checksum gravado, congelado; candle alterado depois → divergência acusada, papel igual |
| proteção | plano/WFA/mineração com papel não se apagam |
| captura | banco ocupado → papel pendente refeito na volta seguinte; papel não atrasa o `publicar` |
| tela | 15 variantes: rolagem, reticências, filtro; `test_callbacks_sem_ciclo` verde |

## 9. Fora desta parte

- Ordens, demo/real, derrapagem e atraso reais, soma de risco por conta,
  disjuntor automático, subir de fase, **encerrar posição ao pausar** — parte 4.
- Tela "Mesa" (todos os portfólios por conta/ativo).
- Outros ativos além de `WIN$N`.
