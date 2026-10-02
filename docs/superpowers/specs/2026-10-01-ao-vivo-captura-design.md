# Projeto C, parte 2: serviço de captura e sub-tela Pregão

> Segunda parte da tela **Ao vivo** (spec da seção 1:
> `2026-09-30-ao-vivo-estrategias-design.md`, §10 "o que as partes 2–4
> herdam"). Esta parte grava o mercado ao vivo e mostra-o na tela. Sinais
> das estratégias (papel) são a parte 3; ordens e o comparativo
> backtest × papel × conta, a parte 4.

Desenhado em 01/10/2026 com o usuário; layout escolhido em rascunho visual
(opção A). Revisado por agente contra o código e o banco real — a revisão
achou a base com hora errada (§0).

## 0. Pré-requisito: corrigir a base (hora deslocada em 3 h)

**Achado (01/10/2026, confirmado no banco e no MT5):** o MT5 devolve
`time` já em **hora de Brasília** (22/09 vem de 09:02 a 18:24), mas
`mt5_source.buscar_barras` (`core/mt5_source.py`) somou o offset de
`offset_servidor` (−3 h) achando que era UTC. A sincronização de 23/09
gravou:
- 16/03 → 23/09: pregões de **06:00 a 15:24** (deviam ser 09:00–18:24);
- 09–13/03: 1.926 candles bons **sobrescritos** por candles deslocados;
- a última barra de 23/09 (09:49, `tick_volume` 165) é um **candle em
  formação** gravado como fechado.

Tudo o que foi minerado/testado depois de 23/09 usou essa base.

**Decisão do usuário (01/10/2026): apagar tudo e recomeçar** — minerações,
walk-forwards, planos, variantes e portfólios. O diário de eventos fica
(registro do que existiu). Contas: já não há nenhuma.

Passos, nesta ordem, cada um conferido:
1. **Código:** `buscar_barras` sem offset (o `time` do MT5 já é hora de
   Brasília). O botão "Sincronizar" passa a descartar o candle em formação
   (§5, "fechado"). Teste com formato real: barra de 09:00 sai 09:00.
   `offset_servidor` deixa de ser usado para converter barras.
2. **Backup** do `.duckdb` e do Parquet (app e captura parados).
3. **Limpeza:** apagar `bars_m1` com `src_ingest_id IN (3, 4)`; apagar
   minerações, trials, walk-forwards, trades OOS, planos, membros de
   portfólio, portfólios e variantes (script de manutenção único, com
   relatório do que apagou; não pelas funções da tela, que corretamente
   recusam apagar cadeia protegida).
4. **Restaurar 09–13/03:** reimportar `m1-hist-16-03-2026.csv`
   (Downloads e `data/raw`). Atenção: o lote 3 apagado não pode mais vencer
   pela regra "mais novo vence", porque não existe mais.
5. **Rebaixar 16/03 → hoje** do MT5 com o código corrigido.
6. **Reconstruir** `trading_days`, `rollovers`, Parquet.
7. **Conferir dia a dia:** todo pregão começa às 09:0x (13:0x em
   quarta-feira de cinzas) e termina 17:5x/18:2x; nenhum dia com início
   06:xx; contagem de candles por dia coerente com o histórico.
8. Os arquivos TSV de 23/09 em `data/raw` ficam renomeados com sufixo
   `.hora-errada` (não reimportáveis por engano).

## 1. O problema (parte 2)

- A base só cresce quando alguém clica em "Sincronizar com MT5". As
  partes 3 e 4 precisam do candle **no minuto em que ele fecha**.
- Não há como acompanhar o mercado dentro do Dataframe.
- Qualquer interrupção (tela travada, MT5 fechado, internet caída, PC
  desligado) não pode deixar buraco permanente nem candle errado na base.

## 2. Vocabulário

- **Serviço de captura** — o processo à parte que grava os candles. Na
  tela, **Captura**. (Nunca "robô".)
- **Candle em formação** — o minuto atual, ainda aberto. Aparece na tela;
  **nunca** vai para o banco.
- **Lacuna** — minuto que **o MT5 tem** e o banco não tem.
- **Minuto sem negócio** — minuto que nem o MT5 tem (leilão, mercado
  parado). Não é alerta.
- **Conferência do dia** — releitura do dia no MT5 depois do fechamento.

## 3. Decisões travadas (01/10/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Onde roda a captura? | **Processo à parte, dentro do projeto**, aberto pelo `iniciar.bat` numa janela própria (a tela reinicia a cada mudança, trava em mineração e não foi feita para laço contínuo — na parte 4 isso seria ordem perdida ou duplicada). |
| 2 | E se a captura cair? | O `iniciar.bat` reabre com espera crescente; erro permanente (outra instância, configuração) **não** reabre (§5). Ao subir, completa tudo desde o último candle salvo. |
| 3 | Quando o candle é utilizável? | **No banco assim que o minuto fecha** (tela, gráfico, partes 3/4). **Em mineração, walk-forward e Candidata, após a conferência do dia** — elas leem o Parquet, que é exportado uma vez por dia. |
| 4 | Candle em formação na tela? | **Sim**, a cada 1–2 s, lido do arquivo de estado (não do banco). |
| 5 | Alertas | **Só na tela**: faixa na sub-tela Pregão + selo no topo. |
| 6 | Layout | **Opção A**: estado em cima, gráfico na largura toda, placar embaixo. Zoom/arrastar, **tela cheia**, **voltar para agora**, tempo gráfico 1/5/15 min. |
| 7 | Vocabulário | Profissional: "serviço de captura"/"Captura", "lacuna", "conferência do dia". |
| 8 | Base com hora errada | **Corrigir antes (§0)** e apagar tudo o que foi feito sobre ela, inclusive variantes e portfólios. |

## 4. Princípio que resolve as falhas

**O MT5 guarda o histórico; a captura nunca depende de ter "visto" cada
minuto.** A cada volta ela pede ao MT5 "todos os candles **fechados** desde
o último que eu salvei". Qualquer interrupção se fecha sozinha na volta
seguinte.

| Falha | Comportamento | Na tela |
|---|---|---|
| Tela/navegador trava | Nada (processo à parte) | Ao recarregar, tudo em dia |
| Captura fecha/trava | `.bat` reabre (10 s, 30 s, 60 s… até 5 min); completa o período | "Captura parada há X min" |
| MT5 fechado | `terminal_info()` None → espera; não chama `initialize` sem caminho (isso abriria um terminal) | "MT5 fechado — abra e faça login; a captura recupera o período sozinha" |
| Internet cai (MT5 aberto) | `terminal_info().connected == False` → espera | "Sem conexão com a corretora desde HH:MM" |
| PC desliga / hiberna | Na volta completa desde o último salvo e confere **cada dia** recuperado; durante o pregão a captura pede ao Windows para não hibernar | "Recuperados N" |
| Banco ocupado (mineração gravando) | Tenta gravar por ~1 s; se não der, **não avança** o último salvo — a próxima volta pede de novo ao MT5. Nada se perde, laço não trava | "Banco ocupado há X s" só se passar de 2 min |
| `iniciar.bat` aberto duas vezes | Trava de instância por arquivo (`msvcrt.locking`, o Windows solta se o processo morrer); a segunda sai com código 3 e não é reaberta | Nada |
| Relógio do PC errado | "Agora" = relógio do PC em America/Sao_Paulo, conferido contra o último tick quando ele tem < 2 min; "fechado" não depende só do relógio (§5) | Aviso se a diferença passar de 30 s |

## 5. Arquitetura

```
core/ingest.py — extrair ingest_df(con, df, symbol, origem, sha,
    source_max_ts=None): valida como read_mt5_export (OHLC coerente, preço
    inteiro, ts sem duplicata) e faz o merge em transação. ingest_csv passa
    a chamá-lo. Sem lógica de merge nova.

core/captura.py (novo, sem Dash) — a lógica, testável com MT5 e relógio falsos
    fechados(barras_mt5, agora) -> lista
        # candle é FECHADO se existe barra posterior no MT5, ou se
        # agora >= ts + 65 s. A última barra devolvida nunca é gravada
        # enquanto o tick for do mesmo minuto.
    gravar(con, symbol, barras, origem) -> {"inseridos","revisados"}
        # via ingest_df; só grava quando há barra nova ou diferente.
        # source_file = 'captura://<login>@<servidor>' (uma linha de
        # ingest_log por gravação, ~140 mil/ano: aceitável)
    lacunas(barras_mt5_do_dia, barras_banco_do_dia) -> list[datetime]
        # minuto que o MT5 tem e o banco não; minuto que nenhum dos dois
        # tem é "sem negócio", não lacuna
    fechamento_esperado(con, symbol) -> time
        # o mais frequente dos últimos 10 pregões (17:54 ou 18:24)
    conferir_dia(con, symbol, dia, barras_mt5) -> {"revisados","faltantes"}
        # grava com source_max_ts = hora em que a conferência rodou, para
        # vencer a captura do mesmo dia (sem depender do desempate por
        # sha256); uma exportação manual posterior continua vencendo
    estado(...) -> dict

captura.py (novo, raiz) — o processo
    trava de instância (data/ao_vivo/captura.lock via msvcrt.locking)
    conecta com initialize(path=<terminal da conta de dados>, se houver)
      e MANTÉM a conexão; checa terminal_info() a cada volta
    laço ~1 s: busca fechados desde o último salvo → grava → estado
    após o fechamento esperado (MT5 conectado): conferir_dia de todo dia
      ainda não conferido + rebuild trading_days/rollovers + export do
      Parquet para pasta temporária e troca atômica
    códigos de saída: 0 normal, 3 = não reiniciar (outra instância,
      configuração), outros = reiniciar
    log rotativo data/ao_vivo/captura.log (5 MB)
    SetThreadExecutionState durante o pregão (não hibernar)

data/ao_vivo/estado.json (gravação atômica: .tmp + os.replace com 3
    tentativas — no Windows dá PermissionError se a tela estiver lendo)
    {"pid","atualizado_em","mt5":"conectado|sem_conexao|fechado",
     "conta":{"login","servidor"}, "contrato_vigente", "ultimo_salvo",
     "em_formacao":{...}|null, "lacunas_hoje":[...], "gravados_hoje",
     "recuperados_hoje","revisados_hoje","conferencia":{"status","em"},
     "banco_ocupado_desde": null|ts, "erro": str|null}

iniciar.bat
    janela "Dataframe — Captura": laço que roda captura.py; código 3 →
    para; outros → espera crescente (10 s, 30 s, 60 s… máx 5 min) e reabre
    depois sobe a tela

core/mt5_source.py
    buscar_barras sem offset (§0); sincronizar descarta o candle em
    formação; com a captura ativa (estado.json < 60 s) o botão
    "Sincronizar" fica desativado com "a captura ao vivo já mantém a base
    em dia"

ui/data.py
    leitura do estado.json; candles do dia lidos do banco só quando
    `ultimo_salvo` muda; `_bars_cache` e o span limpos quando
    `estado.conferencia.em` muda (a mineração/backtest passam a ver o dia)
```

**Concorrência entre processos (DuckDB: um escritor por vez):** a captura
grava ≈1 vez por minuto, em milissegundos, e fecha a conexão. A tela lê por
conexões curtas como hoje e, a cada 2 s, só lê o `estado.json`. Uma
mineração longa segurando o escritor apenas atrasa a gravação (sem perda).

**MT5:** a captura e o botão da tela são processos diferentes no mesmo
terminal (o MT5 aceita vários clientes); a captura não chama `shutdown` a
cada volta. Para a parte 4: **um processo de automação por terminal**
(uma conexão MT5 por processo).

**Pregão:** fechamento esperado pelo histórico (17:54 ou 18:24); abertura
pelo primeiro negócio (09:0x; 13:0x em quarta de cinzas). Fora do pregão a
captura fica ociosa (estado a cada 30 s) e "Captura parada" não é alerta.
Dia que não fechou (PC desligou antes) é conferido no dia seguinte.

**Reconferência na manhã seguinte (02/10/2026):** de madrugada a corretora
consolida o próprio histórico. Em 01/10 a captura gravou o leilão de
fechamento como candle próprio às 18:31 (o=h=l=c=187760, 22.355 contratos)
e o 18:24 fechando em 187800; a conferência das 18:38 bateu com o MT5
daquela hora. No dia seguinte o MT5 já não tinha o 18:31: o 18:24 fechava em
187760 com 24.212 contratos (leilão somado) — e todo o histórico baixado
termina assim. Por isso, na janela da conferência (e na primeira volta
conectada), cada dia passado com a marca `conferencia://` e sem
`reconferencia://` é relido do MT5 (`dias_a_reconferir` →
`reconferir_dia`): os candles que diferem são regravados e os do dia que o
MT5 não tem mais são **apagados**, na mesma transação, gravando a marca
`reconferencia://AAAA-MM-DD`. Só a partir das 08:55 do dia seguinte (logo
depois da meia-noite a corretora ainda não consolidou, e a marca impediria a
releitura que importa). Recusa — sem apagar nem marcar — o dia do MT5 que
parece incompleto: vazio, com mais de 3 candles a menos que o banco, que
apagaria mais de 3 candles, ou que começa mais de 5 min depois do banco (o
caso real: 565 no MT5, 541 no banco, 1 removido). A janela seguinte tenta de
novo; passados 5 pregões o dia é abandonado (aviso único no log e em
`reconferencia.abandonados`). Qualquer erro numa reconferência fica no dia
dela e não impede a conferência de hoje. Depois, trading_days/rolagens e o
Parquet são refeitos (marca `reexportar`). O `estado.json` ganha
`"reconferencia": {"em", "dias", "erro", "abandonados"}` e
`"base_alterada_em"` (candles já espelhados reescritos: a tela limpa o cache
de barras). O cartão da conferência de hoje só vira "concluída" com o dia
de hoje conferido — nem a reconferência das 08:56 nem a conferência de um
dia recuperado o mudam. Dia de exportação antiga (sem a marca
`conferencia://`) nunca é reconferido. O `tick_volume` (atualizações de
cotação, não negócios) e o `spread` (0 ao vivo, 5 no consolidado, em toda
barra) a corretora também revisa de madrugada: o merge do ingest e o
`gravar` os ignoram ao comparar — barra que só difere neles é idêntica e
mantém a proveniência (para essas duas colunas o resultado deixa de ser
independente da ordem de importação). O `volume` (contratos, da B3)
continua comparado. Nada no motor lê tick_volume nem spread.

**Dados:** série contínua `WIN$N`, da conta logada no MT5; `ingest_log`
registra a origem; o estado registra o contrato vigente (para a rolagem na
parte 4).

## 6. A sub-tela Pregão (opção A)

Seletor **Estratégias | Pregão** no topo da tela Ao vivo (lembra a escolha).

1. **Faixa de estado** — **Captura** (em operação / parada há X min) ·
   **MT5** (conectado / sem conexão desde HH:MM / fechado) · **Último
   candle** (HH:MM, há N s — verde até 90 s, âmbar até 3 min, vermelho
   depois, só no pregão) · **Lacunas hoje**. Problema: faixa vermelha com a
   frase e o que fazer.
2. **Gráfico `WIN$N`** (componente TradingView do Backtest): candles do
   dia; o candle em formação entra pela propriedade `tick` (acrescenta ou
   atualiza a última barra **sem perder o zoom**); em 5/15 min, o candle em
   formação é o balde atual somado ao minuto em formação. Zoom e arrastar;
   **tela cheia**; **voltar para agora**; 1/5/15 min. Fora do pregão: último
   dia, "mercado fechado".
3. **Placar do dia** — gravados · recuperados · correções da corretora ·
   conferência do dia (pendente / concluída às HH:MM).

**Selo no topo** (todas as telas, lê o mesmo `estado.json`): verde "Captura
ativa"; âmbar/vermelho com a frase curta; nada fora do pregão com a captura
parada.

Atualização: `dcc.Interval` de 2 s só com a sub-tela Pregão aberta; selo a
cada 30 s.

## 7. Erros e estados

- `estado.json` ausente → "Captura nunca rodou neste computador — abra pelo
  iniciar.bat".
- `atualizado_em` > 60 s no pregão → "Captura parada há X min".
- `estado.json` ilegível → última leitura válida.
- MT5 sem `WIN$N` ou pacote MetaTrader5 ausente → erro de configuração
  (código 3), mensagem clara no estado e no log.
- Erro inesperado no laço → log + `estado.erro`; segue na volta seguinte.

## 8. Testes

Banco temporário (conftest), MT5 e relógio falsos. Mutação em
`core/captura.py`, `ingest_df` e na correção de hora.

| alvo | prova |
|---|---|
| hora (§0) | barra real do MT5 com `time` de 09:00 é gravada 09:00; sem offset em lugar nenhum do caminho |
| `fechados` | nunca devolve o candle em formação; PC adiantado 70 s não deixa passar o em formação; após queda de 3 h devolve tudo; nada novo → vazio |
| `ingest_df` | mesmo resultado que `ingest_csv` para o mesmo conteúdo; recusa OHLC incoerente/duplicata; `ingest_csv` continua passando nos testes antigos |
| `gravar` | inserção; repetido não grava; diferente vira correção contada; origem no `ingest_log` |
| `lacunas` | pregão completo → 0; minuto que o MT5 tem e o banco não → lacuna; minuto que ninguém tem → não é lacuna; leilão de abertura (09:00–09:02 vazios) → 0 |
| `fechamento_esperado` / conferência | dia de fechamento 17:54 não espera 18:24; conferência vence a captura do mesmo dia (empate de `source_max_ts`); exportação manual posterior vence a conferência; recuperação de 3 dias confere os 3 |
| banco ocupado | `connect_write` falha → último salvo não avança; volta seguinte grava sem perda nem duplicata |
| trava / `.bat` | segunda instância sai com 3; trava liberada após morte forçada; espera crescente |
| estado | gravação atômica com leitura concorrente; arquivo ilegível → última válida |
| Parquet | export em pasta temporária + troca; `_bars_cache` invalidado após a conferência |
| tela | faixa para cada situação; selo; gráfico recebe `tick` sem trocar `series`; `test_callbacks_sem_ciclo.py` verde |
| Sincronizar | desativado com captura ativa; sem captura, descarta o candle em formação |

**Conferência real:** §0 primeiro (com backup), conferindo dia a dia.
Depois, com o mercado **fechado**: subir pelo `iniciar.bat`, ver a captura
completar até o último pregão, "mercado fechado" na tela; fechar o MT5 e ver
o aviso; reabrir e ver voltar. Com o mercado **aberto**: candles entrando
minuto a minuto, candle em formação mexendo sem perder zoom, lacunas = 0,
conferência do dia após o fechamento.

## 9. Fora desta parte

- Sinais das estratégias, papel, posição e resultado por portfólio no
  gráfico — parte 3. **Requisito herdado:** a base corrigida (§0) e a hora
  certa são obrigatórias antes de qualquer sinal.
- Ordens, contas e o comparativo — parte 4 (um processo de automação por
  terminal; a gravação no banco nunca no caminho da ordem; contrato
  vigente na rolagem).
- Outros ativos; notificação fora da tela; agendador do Windows.
