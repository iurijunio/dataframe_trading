# Dataframe — instruções do projeto

> **Fonte única.** Codex, Claude e OpenCode leem este arquivo. O `CLAUDE.md`
> é só um ponteiro para cá: mudou regra, status ou pendência, edite **aqui**.

Plataforma quantitativa em Python (Dash + DuckDB + Numba) para criar, minerar,
validar e operar estratégias de day trade no Mini Índice (`WIN$N`),
substituindo o fluxo que antes vivia no MT5. Branch de trabalho:
`new-strategies` (ativos da CME, estratégias novas). O ramo principal é o
`master` (não o `candidata`): as partes 4 e 5 (ordens e conta real, ramo
`live-trading`) já entraram nele pelo PR #2. Remoto `origin` no GitHub.

## O usuário

- Fala português; responda em português, **direto e sem jargão**.
- Não gosta de terminal: prefere **ver funcionando na tela**. Resultado se
  mostra com screenshot do app, não com saída de comando.
- Ele dá o aval final. Não commite nem faça push sem ele pedir.

## Rodar

```
.venv/Scripts/python.exe ui/app.py          # http://127.0.0.1:8050
.venv/Scripts/python.exe -m pytest -q       # suíte inteira (2.568 testes coletados em 29/10/2026)
```

- Para ver o app: rode `ui/app.py` e abra http://127.0.0.1:8050. Quem tiver
  `preview_start` usa o nome `dataframe` (o `launch.json` existe só em
  `.claude/launch.json`).
- **Git**: funciona pela tool de shell; se aparecer "git não é reconhecido",
  use a tool PowerShell. Mensagem de commit com mais de uma linha: escreva
  num arquivo do scratchpad e use `git commit -F <arquivo>`. Nunca heredoc
  (quebra com aspas e acentos).
- Adicione arquivos ao commit **pelo caminho**, nunca `git add -A` / `git add .`.

## Arquivos que NÃO são seus

`ui/components/controls.py`, `ui/components/wfa_matriz.py` e
`strategies/rompimento_abertura.py` são de edição manual do usuário. **Nunca
editar, formatar, stagear ou commitar** — nem quando o `git status` estiver
limpo. Se uma tarefa parecer exigir mexer neles, pare e pergunte.

## Como trabalhar

**Mudança de impacto** (conta, lógica, dado, banco, callback com estado):

1. Teste falhando → implementação mínima → teste passando.
2. **Mutação**: quebre a implementação de propósito, confirme que o teste
   pega, desfaça (agente `mutacao`). Teste que não falha com código errado
   não prova nada — aqui já aconteceu de 10 de 12 versões defeituosas do
   bootstrap passarem.
3. Revisão em segundo plano (agente `revisor`) → aplicar o que procede.
4. Suíte inteira verde → conferir na tela contra o banco real → commit.

**Mudança simples de layout/CSS/texto**: sem testes, sem mutação, sem
revisão. Faça, mostre na tela (screenshot) e **o usuário aprova**.

**Conferir na tela contra o banco real** (`data/database.duckdb`) é
obrigatório para mudança de UI. Cuidado: um clique ou rolagem errada num
campo numérico altera dado real — anote o valor antes e restaure depois.

## Regras do código

- Código, nomes, comentários e textos de tela em **português**.
- Comentário explica **por quê**, nunca o quê. Tom de referência: `core/wfa.py`.
- **Nada em `core/` importa Dash.** `core/` são contas; `ui/` liga a tela.
- **Nenhum teste toca `data/database.duckdb`.** Todo teste já roda isolado do
  banco real por `tests/conftest.py` (autouse); mesmo assim use a fixture
  `banco`: `monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")` (e
  `PARQUET_DIR` quando ler barras). Veja `tests/test_portfolio.py`.
- Toda métrica nova na tela tem um (?) com faixa boa e ruim (`ui/components/cartao.py`).
- Sem scipy, de propósito (`core/robustez.py` usa `math.erfc`).
- Não desligar o logo da TradingView no gráfico — exigência da licença.
- Base de referência: `WIN$N`, 16/03/2021 em diante, capital padrão R$ 10.000.

## Glossário (use estes nomes com o usuário)

- **Estratégia** — o código em `strategies/*.py` (ex.: `rompimento_canal`).
- **Variante** — uma configuração salva de uma estratégia, com nome dado pelo
  usuário (ex.: "romp-canal-02"). Clusters diferentes da mesma estratégia são
  variantes diferentes. Atravessa reotimizações: só troca de plano.
- **Plano** — o que a Candidata grava para operar (parâmetros, contratos,
  disjuntor). Uma variante tem **um plano ativo por vez**.
- **Fase** — onde a variante está no caminho até o dinheiro real, por
  portfólio: papel → demo → real. (Nunca "degrau". O "real mínimo" foi
  eliminado nas decisões da parte 4; o `real_minimo` do banco migra para
  `real`.)
- **Serviço de captura** — o processo à parte (aberto pelo `iniciar.bat`) que
  grava os candles ao vivo; na parte 4 passa a ser a automação que opera.
  Nunca "robô". Vocabulário profissional, de mesa de operações.
- Ao introduzir qualquer termo novo, explique com um exemplo dos dados dele.

## Arquitetura em uma tela

As quatro camadas (pergunta: *de quem é essa informação?*):

| Camada | Onde | Conteúdo |
|---|---|---|
| 1 Instrumento | `configs/instruments/*.yaml` | tick, valor do ponto, rolagem |
| 2 Estratégia | `strategies/*.py` | só sinais (`Signals`); soltar o arquivo na pasta basta (`strategies/registry.py`) |
| 3 Parâmetros | `configs/strategies/*.json` / `params_schema` | default, min, max, passo |
| 4 Execução | tabela `execution_profiles` | horário, stop/alvo, custos, tamanho — aplicada pelo motor, nunca pela estratégia |

Os sete modos do topo (`ui/app.py`) e onde vivem:

| Modo | Contas (`core/`) | Tela (`ui/`) |
|---|---|---|
| Backtest | `engine/kernel.py`, `engine/execution.py`, `metrics.py`, `analytics.py`, `detalhes.py`, `robustez.py` | `callbacks.py`, `components/stats_cards.py`, `charts.py`, `results_grid.py` |
| Mineração | `optimizer.py`, `walkforward.py`, `mineracao_stats.py`, `porteira.py` | `components/mining.py`, `mine_*.py`, `scatter.py` |
| Walk-Forward | `wfa.py`, `wfa_runner.py`, `wfa_store.py` | `components/wfa_panel.py` |
| Candidata | `candidata.py`, `candidata_runner.py`, `aleatorio.py`, `spa.py`, `tamanho.py`, `plano.py` | `callbacks_candidata.py`, `components/candidata_panel.py` |
| Estratégias | `variantes.py` | `callbacks_estrategias.py`, `components/estrategias_panel.py` |
| Portfólio | `portfolio.py` | `callbacks_portfolio.py`, `components/portfolio_panel.py` |
| Ao vivo | `ao_vivo.py`, `diario.py`, `codigo.py`, `captura.py` (o processo da captura é o `captura.py` da raiz, aberto pelo `captura.bat`), `papel.py`, `papel_leitura.py`, `papel_vivo.py`, `papel_backtest.py`, `corretora.py`, `ordens.py`, `diario_ordens.py`, `comandos.py`, `contrato_dia.py` | `callbacks_ao_vivo.py`, `components/ao_vivo_panel.py`, `callbacks_pregao.py`, `components/pregao_panel.py`, `callbacks_operacao.py`, `components/operacao_panel.py`, `components/ordens_panel.py` |

Outros: `core/mt5_source.py` + `ui/callbacks_mt5.py` (botão "Sincronizar com
MT5"); `core/plano.vencendo` + selo no topbar (reotimização vencendo);
`ui/callbacks.py:register` registra todos os `callbacks_*.py`.

Fluxo do dado: mineração (`mining_runs`, com `variante_id`) → walk-forward
(`wfa_runs`, `wfa_trades` = trades fora da amostra) → Candidata grava
`planos_operacao` (retratos, não referências) → Portfólio referencia **só a
variante** e resolve o plano ativo na hora (`variantes.plano_ativo`).

## Armadilhas já pagas (não repetir)

- **DuckDB: vários leitores OU um escritor.** Workers leem do espelho Parquet
  (`db.read_bars_parquet`); gravação via `db.connect_write()`.
- **`COPY … TO ?` com parâmetro não grava nada, em silêncio** — caminho literal via `_sql_str`.
- **Ciclo entre callbacks congela a tela sem erro.** `tests/test_callbacks_sem_ciclo.py`
  pega; rode-o sempre que mexer em Inputs/Outputs.
- Nunca mandar as ~700 mil barras ao navegador — `ui/data.py` agrega pelo `MAX_CANDLES`.
- Look-ahead é travado no kernel: sinal da barra `i` executa na abertura de `i+1`.
- **Portfólio:**
  - Curva/drawdown combinado: trades de todas as variantes **intercalados pela data
    real de fechamento**, nunca uma variante depois da outra.
  - `profit_factor` / fator de recuperação viram `+inf` sem nenhuma perda — fora do
    min/max do mapa de calor.
  - Kelly com payoff `0.0` é ambíguo ("sem vantagem" × "ainda sem perda") → estado
    "indefinido" separado.
  - Risco de ruína e simulador de crescimento usam **o mesmo modelo**: aposta de
    fração fixa, em múltiplos de R (R = perda média histórica). Não divergir.
- **O `.duckdb` deixou de ser só cache:** `contas`, `portfolio_membros`,
  `ao_vivo_eventos`, `planos`, `papel_operacoes`, `papel_pregoes`,
  `ordens_eventos` e `papel_backtest` não se recriam — backup antes de qualquer
  migração; nunca apagar o banco. Também nunca se apaga o diário de escrita
  adiantada `data/ao_vivo/ordens/*.jsonl`: é dele (não do banco) que a captura
  relê "já enviei a entrada X" e "conta travada hoje".
- **Hora do MT5:** o `time` das barras que o MT5 devolve **já é hora de
  Brasília** — não somar offset. A sincronização de 23/09/2026 subtraiu 3 h
  e corrompeu 16/03→23/09 (corrigida em 01/10/2026; backup do banco antigo em
  `C:\Users\mrRobot\Documents\Neturna\backups\2026-10-01-antes-correcao-hora`).
  Nunca gravar o candle em formação (o último minuto devolvido).
- **Captura:** o `captura.bat` (serviço de captura) abre pelo `iniciar.bat`.
  Com a captura ativa o botão Sincronizar fica desativado. As barras de HOJE
  só existem no banco até a conferência do dia — o Parquet e o `data/raw` não
  as têm — então a mineração só vê o dia de hoje depois dela. Por isso
  `cli.py verify` (que reconstrói do Parquet) com a captura rodando apagaria o
  dia: ele recusa se o `data/ao_vivo/estado.json` foi atualizado há menos de
  60 s ("feche a captura antes"). O relógio do PC pode atrasar ~1 min em
  relação à corretora; a captura usa o relógio do servidor (a tela avisa acima
  de 30 s). O Clear não publica o contrato vigente (`contrato_vigente` = None).
- **Corretora consolida de madrugada:** o leilão de fechamento gravado ao vivo
  como candle próprio (01/10: 18:31) vira parte do 18:24, minutos da manhã são
  refeitos, e `tick_volume`/`spread` (0 ao vivo, 5 consolidado) são revisados.
  A captura reconfere cada dia passado a partir das 08:55 do dia seguinte
  (`reconferir_dia`: apaga o candle que o MT5 não tem mais, recusa dia
  incompleto, desiste após 5 pregões; reconfere o papel). O merge ignora
  `tick_volume` e `spread` (não são preço nem negócio); `volume` segue comparado.
- **Papel (`core/papel.py`):**
  - É backtest por construção. O perfil de execução é montado como no WFA
    (`CAMPOS_EXECUCAO_NOMES`); nunca `ExecutionProfile.from_config`.
    `run_strategy(..., vela_aberta=True)` só no papel ao vivo.
  - O aquecimento é calculado pelos parâmetros da estratégia; 10 pregões
    não bastam e o resultado diverge do backtest.
  - `op_id` é estável por (`ligacao_id`, `entry_ts`). A parte 4 depende dele.
  - Pregão conferido fica congelado; o checksum acusa divergência.
  - A captura calcula o papel só com candle novo e refaz a conferência do
    papel na janela seguinte se ela falhar.
  - A tela Operação lê o `estado.json` a cada 2 s e só abre o banco quando
    `papel.calculado_em` muda.
- **Ordens na demo (parte 4; `core/corretora.py`, `ordens.py`, `papel_vivo.py`):**
  - **Barra provisória:** o minuto em formação vale para sinal, nunca para
    stop/alvo/indicador; stop e alvo da entrada vêm da vela fechada até o minuto
    anterior (`0dfa0db`, `engine.VERSAO` 2026.10.09 — fecha o look-ahead do
    M1+ATR). Saída forçada na provisória fica aberta.
  - **O caminho da ordem nunca espera o banco:** papel vivo e decisão saem da
    memória e do `estado.json`; o evento vai primeiro ao `.jsonl` (`fsync`) e
    ao banco só quando ele estiver livre.
  - **Desejado "indisponível" = não fazer nada, não zerar:** dado velho ou
    cálculo faltando não fecha posição aberta.
  - **Retornos do MT5: tabela única** em `core/corretora.py`, testada linha a
    linha. INCERTA (10012, e `None`) pode ter executado: adotar/conferir antes
    de reenviar. ACEITA (10008, PLACED) é recebida, o negócio vem depois.
    10036 é "já saiu", não falha.
  - **Filling por máscara:** `SYMBOL_FILLING_MODE` é máscara (FOK=1, IOC=2), não
    o valor de `ORDER_FILLING_*` (FOK 0, IOC 1, RETURN 2); em bolsa, RETURN vale
    como último recurso.
  - **`None` do MT5 só se entende com `last_error()`:** sem erro (1) é "nenhuma
    resposta", não falha de configuração.
  - **Conta travada pelo limite de perda vale até o próximo pregão, sem botão
    de destravar** (evento `conta_travada`, sobrevive a reinício).
  - **"Desligar envio" grava o comando antes de tocar no banco** (e o envio
    vai junto no comando); banco ocupado não pode segurar o desligamento.
  - **Limite de perda vazio não se grava com Envio ligado**, e limite vazio
    não desliga o envio sozinho.
  - Envio nasce **desligado** (`contas.envio_ligado`) e registra "seria enviada".
    O ensaio passa o MESMO pedido pelo `order_check` (nunca envia; retcode 0
    = passou) e grava `retcode`/`comment` (ou `last_error`); a tela mostra
    "seria recusada: …".
  - **Foto parcial:** posições e ordens lidas, mas histórico/negócios/conta
    falharam → só sair e proteger (nada de entrar, adotar, perdida nem
    "saiu antes"). Sem conta legível vale a da mesma conexão. Foto incompleta
    > 30 s no pregão (ou ilegível com posição aberta) → chamado `sem_leitura`.
    Exceção à "só proteger": a candidata ÚNICA da entrada sem resposta, sem SL,
    recebe o stop/alvo do `enviando` que a abriu (nunca o do papel), sem ser
    adotada, e com o stop recusado > 2 s encerra como na foto completa; duas
    candidatas ou envio sem stop → chamado `sem_stop` (`_orfa_na_parcial`).
  - **"Zerar tudo" de outro dia** (clicado fora do pregão sem posição, lido na
    manhã seguinte) é descartado no diário — não desliga o envio de hoje.
  - **Retrato salvo** (`data/ao_vivo/ordens/retrato.json`, escrita atômica):
    subida com o banco preso usa o último retrato, marcado antigo — protege e
    sai por comando/trava, nada entra.
  - **Ordem de teste** (`core/ordem_teste.py`; **o botão está fora da tela**, o
    motor, o comando e o Diário continuam — dá para religar depois; ver
    `git diff 421cc4f..be5ba7f -- ui/`; o botão "Teste" da conta real também
    saiu da tela — engine mantido; ver git 6ceaa18 para trazê-lo de volta):
    comando `ordem_teste` que a captura executa depois das ações das
    estratégias, uma etapa por volta, sem `sleep` (compra 1 · SL/TP a 100 pts
    · confere · 10 s no monotônico · sai pelo ticket). Magic `MAGIC_TESTE` =
    7.000.000, fora da faixa das ligações: planejar/adoção/zerar/Encerrar
    nunca a tocam; só ela encerra a sua (inclusive a que sobrou de um
    reinício). Recusa sem `account_info().trade_mode` ==
    `ACCOUNT_TRADE_MODE_DEMO`, conta cadastrada demo, pregão, Algo, trava,
    contrato/guarda, Zerar ou pedido > 60 s; independe do Envio. Saída
    recusada > 10 s → chamado `teste_preso`. 10008 e passageiras não são
    falha (passageira: de novo a cada 1 s, até 5 s); fora do pregão e fora da
    conta DEMO o encerramento não reenvia.
  - "Saiu antes" só para ticket que a própria automação não encerrou; a
    entrada sem resposta só casa com negócio depois do 1º envio da operação
    e nunca com ticket de outra operação.
- **Conta real (parte 5; `ordens_real.py`, `core/ponte.py`, `core/comandos.py`):**
  - **Um terminal MT5 por processo.** A captura e a Ordens real têm cada uma o
    seu `mt5.initialize(path=…)`; nunca trocar de conta dentro do mesmo processo.
  - **A captura só abre o terminal da conta DEMO**; a real só abre o da conta
    real, pelo caminho cadastrado em `contas.terminal`.
  - **O tipo da conta é conferido a cada volta** (login e `trade_mode`: DEMO na
    captura, REAL na real). Conta errada = chamado `conta_errada`, nada sai.
  - **Ponte `data/ao_vivo/desejados.json`:** escrita atômica, com batimento
    (`vivo_em`) em toda volta da captura. A real só age com desejado de até 5 s
    (senão é indisponível: só protege).
  - **Ack `ack_real.json` de até 200 ms:** a demo espera a real tratar um `seq`
    novo só quando o processo da real está vivo; sem ele a demo segue sem esperar.
  - **Pastas de comando por conta:** `data/ao_vivo/comandos` (demo) e
    `data/ao_vivo/comandos_real` (real). Cada processo lê só a sua.
  - **`zerar_tudo` vai para as duas pastas**, sem ler o banco.
  - **`ordens_eventos.origem`** (`demo` ou `real`): todo leitor de eventos filtra
    por origem. Quem espelha a real no banco é a captura, nunca o processo da real.
  - **Ordem de teste na conta do processo** (demo ou real, liberada na real em 21/10/2026): botão fora da tela desde 21/10 (motor mantido; para religar veja o commit 6ceaa18); confere login, tipo cadastrado e trade_mode do MT5 antes de enviar; não depende do Envio.
  - **Dado protegido:** `data/ao_vivo/ordens/real/*.jsonl` nunca se apaga (é o
    diário write-ahead da conta real, como o da demo).
- **Ativos da CME (MES, MNQ; `core/ativo.py`, spec
  `docs/superpowers/specs/2026-10-28-ativos-cme-design.md`):**
  - **Três unidades, cada lugar usa uma.** *Humana* (pontos, hora de NY) na
    tela, no YAML, nos perfis e nos `params`/`profile` salvos. *Guardada*
    (preço × 10^`price_decimals`, relógio de pregão = hora de NY + 360 min) em
    barras, motor e registros de trade (`points`, `entry_px`, `wfa_trades`…).
    *Dinheiro* na moeda do ativo.
  - **A conversão humana → guardada só acontece em `run_strategy`, numa
    cópia.** Nunca converta em outro lugar (dupla conversão): o instrumento
    convertido guarda `_original`. Guardada → humana só na tela, via
    `core/ativo.py`. O WIN é identidade (escala 1, deslocamento 0).
  - **Foto do WIN é obrigatória antes e depois de mexer no motor:**
    `scripts/foto_win.py gravar` / `conferir` (banco congelado em
    `data/foto_win/<nome>.duckdb`, fora do git). Tem de dar idêntico.
  - **Mudou código de estratégia?** Rode
    `scripts/reassinar_codigo.py --de <commit> --aplicar`. O papel lê o
    `codigo_hash` a cada ciclo: troque só fora do pregão, com o app e a
    captura fechados. Planos 5, 6 e 7 reassinados em 29/10/2026, trades
    idênticos (backup em `backups/2026-10-29-antes-reassinar/`).
  - **Até as etapas 3 e 4, não salve planos em MES/MNQ**, e os rótulos ainda
    dizem "R$" nos micros (os valores já estão em US$).
- **Nunca passe dicionário (ou qualquer coisa que não seja componente) como
  filho de `html.*`.** O Dash 4 falha ao desenhar e, em silêncio, devolve o
  estado de OUTROS componentes: o menu e as sub-telas voltavam sozinhos para
  a aba anterior (`421cc4f`: o cabeçalho da Operação recebeu o `contrato_dia`
  inteiro). Trocar para `dcc.Tabs` (`47b00bb`) não era o problema e foi
  revertido (`d0d180b`). Formate o texto antes de pôr na tela.
- **Relógio do Windows:** com o serviço `w32time` parado o PC atrasou 222 s.
  Com o MT5 conectado a automação usa o relógio da corretora, mas deixe o
  `w32time` em início automático com os servidores do ntp.br.
- **Mineração sem cópias:** campo de um tipo não escolhido (ATR com alvo
  em pontos, DI no rango) e as variações do ADX desligado dão resultado
  idêntico — `optimizer.espaco_util` / `combinacoes_uteis` podam antes de
  varrer (mineração e WFA). Cópias criam platô falso no `score_vizinhanca`.
- **Faixa decimal:** `(ate - de) / passo` dá 2,9999…; arredonde antes do
  `int()` ou o último valor some.
- **Campo numérico:** `<input type=number>` focado muda de valor com a rolagem do
  mouse (bug do Chrome). Use `type="text"` + `inputMode="numeric"` + parse manual;
  `ui/assets/num_input.js` protege o resto do app.

## Documentos: qual confiar

| Documento | Estado (29/10/2026) |
|---|---|
| `docs/superpowers/specs/*` e `plans/*` | desenho de cada entrega recente — **fonte mais confiável** do porquê |
| `docs/CALCULOS-WFA.md`, `docs/CALCULOS-CANDIDATA.md` | como cada número é calculado — confiável |
| `docs/PLANO*.md`, `docs/EXECUCAO-CANDIDATA-*.md` | histórico de decisões; planos já executados |
| `docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md` | spec da parte 4 (ordens) — implementada; o `...-ordens-decisoes.md` é o rascunho que a originou |
| `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` + `plans/2026-10-28-ativos-cme-etapa1.md`, `2026-10-29-ativos-cme-etapa2.md` | ativos da CME; as seções "Herança da etapa 1" e "Estado depois da etapa 2" dizem o que ficou |
| `CHANGELOG.md` | atualizado até os ativos da CME, etapas 1 e 2 (29/10/2026); **não cobre variantes, portfólio nem gatilho** |
| `README.md` | atualizado até os ativos da CME (29/10/2026); o texto do MVP segue como história |
| `docs/METODOLOGIA.md` "Estado da plataforma" | atualizado em 29/10/2026 |

Na dúvida entre documento e código, o código manda. Use o agente
`documentador` para pôr a documentação em dia depois de uma entrega.

## Onde estamos e o que falta

Projetos (`docs/PLANO-CANDIDATA.md §11`): **A** Candidata ✅ · **B** MT5 ✅ ·
**D** Portfólio: parte 1 identidade ✅, parte 2 correlação ✅ (+ capital, tabela
comparativa, Kelly, risco de ruína, simulador de crescimento), parte 3 gatilho:
fatia 1 (selo de reotimização) ✅ · **C** Incubação 🔨 · **E** Execução ao vivo ❌.

**Em andamento: tela "Ao vivo"** (projeto C + E), dividida em partes:
1. **Seção 1** (1a blindagem do banco + 1b sub-tela Ao vivo › Estratégias com a
   ficha de rastreio) ✅. Spec: `docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md`.
2. Candles ao vivo (serviço de captura grava cada M1; completa lacunas;
   conferência do dia; sub-tela Pregão; selo da captura no topo) ✅. Spec:
   `docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md`.
3. Incubação em papel (**o papel roda sempre**, em qualquer fase) + sub-tela
   Operação ✅. Spec: `docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md`.
4. Ordens pelo próprio Dataframe na conta demo + comparativo backtest ×
   papel × demo (sinal no mesmo minuto, preço, derrapagem) ✅ **implementada**
   (branch `live-trading`, 16 tarefas). Spec:
   `docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md`; decisões em
   `...-ordens-decisoes.md`. O **Envio de ordens nasce desligado** e registra
   "seria enviada". Conta real ficou para a parte 5. Pausar com posição
   aberta encerra na hora.
   **Situação em 15/10/2026:** o usuário dispensou o ensaio de um pregão
   inteiro. A **ordem de teste** na demo passou (entrada 149 ms, proteção
   676 ms, saída 496 ms). O **Envio de ordens está LIGADO na conta demo, com
   1 contrato**, na ligação do `rompimento_ema_abertura`; a ligação do
   rompimento de canal segue só no papel. O PR `live-trading` → `master` está
   foi mergeado no `master` (PR #2).
   **Próximo passo:** acompanhar a demo, comparando papel × demo todo dia, e
   promover a estratégia de canal.
   **Opção "Saída" (18/10/2026, `strategies/saida.py`):** parâmetro `saida`
   em toda estratégia (inclusive a `adx_direcao`) menos o `rompimento_abertura` (um sinal por dia: os
   modos dariam os mesmos trades, cópia = platô falso), minerável como
   inteiro (o "até" da faixa já vem no último modo) — 0 sinal contrário, 1 não
   sai, 2 vira a mão (sai e entra do outro lado na mesma abertura; o motor
   aplica direção, janela, horas sem entrada e limites do dia), 3 saída
   própria (só `reversao_rsi`). O padrão de cada uma reproduz o de antes
   (cruzamento e canal 0, RSI 3, EMA da abertura 1; `tests/dados/saida_antes.json`)
   e plano sem a chave usa o padrão — `engine.VERSAO` não subiu. Na demo, a
   virada só entra com a posição contrária fora da conta (`ordens.planejar`
   e `Motor.executar`); passada a janela de 30 s com a contrária presa, a
   entrada vira "perdida". Mexer na estratégia — ou num ajudante que ela
   importa, como o `saida.py` (`codigo.ajudantes`) — muda o `codigo_hash`: plano
   gravado antes acusa "código mudou desde o plano". Mudança que NÃO muda
   os trades se reassina sem regravar o plano:
   `scripts/reassinar_codigo.py --de <commit antigo> [--aplicar]` roda o
   backtest de cada plano com o código antigo e com o novo e só troca o
   hash (do plano e dos `papel_pregoes` dele) com trades idênticos; faz
   backup antes; o hash gravado é conferido também pela receita de hash do
   commit antigo. Os planos #5 e #6 foram reassinados assim em 18/10/2026
   (backup em `C:\Users\mrRobot\Documents\Neturna\backups\2026-10-18-antes-resign-hash`);
   #5, #6 e #7 de novo em 29/10/2026.
5. **Conta real** ✅ **implementada** (21/10/2026). Spec:
   `docs/superpowers/specs/2026-10-19-conta-real-design.md`. A conta real roda
   **em paralelo com a demo, com a real primeiro**, pelo processo próprio
   **"Ordens real"** (`ordens_real.py`, aberto pelo `iniciar.bat`): lê os
   desejados que a captura publica e manda ordens só na conta real, pelo
   terminal dela. A captura segue com a demo. O Envio da conta real tem o
   mesmo interruptor de dois cliques da demo e **nasce desligado**; ligar é
   decisão do usuário.
   **Vigia de stop e alvo** (21/10, commits `d987d91`..`cf8540c`): o papel
   sai no **toque** do stop ou do alvo, no candle em formação, sem esperar o
   fim do candle. A corretora tem 1 s para executar o stop/alvo tocado; depois
   disso a automação sai a mercado e abre chamado. Execução assim sai marcada
   como "fora do mercado" e fica fora da derrapagem.
      Em 23/10 duas correções na real: preço confirmado pelo negócio (a bolsa
   devolve `price` 0) e a real aplica os próprios contratos, fase e chave aos
   desejados da ponte.
   Ideias para depois: recursos com LLM fora do caminho da ordem; aba Conta.
Cada parte 2–4 terá spec própria; o que herdam da seção 1 está no §10 da spec.

Entrega futura: aba **Conta** no topo (nome escolhido pelo usuário; nunca
"Mesa"): todo o controle e a visão por conta/ativo ficam lá. Ainda sem spec.

Camada 4 minerável (06–07/10): alvo como múltiplo do stop (arredondado ao
tick), stop/alvo ATR em faixa, três janelas "sem entradas", filtro de
mercado ADX (tendência/rango, 0 desliga) e a estratégia
`rompimento_ema_abertura`. O ADX é o de Wilder — **não bate com o ADX
padrão do MT5**, que suaviza diferente. Nos timeframes M7/M11/M13/M17 a
primeira vela do pregão sai parcial (contam da meia-noite); igual em todos
os modos.

**Ativos da CME na pesquisa (MES e MNQ; ramo `new-strategies`, desde
28/10/2026)** — só pesquisa; a operação ao vivo não inclui os micros (sem
corretora). Spec `docs/superpowers/specs/2026-10-28-ativos-cme-design.md`.
- **Etapa 1 ✅:** fichas `configs/instruments/mes.yaml` e `mnq.yaml`,
  `core/ativo.py` (ficha, relógio de pregão, escala de preço), importação do
  London Strategic Edge (`cli.py importar-lse --symbol MES <arquivos>`, em
  `core/importar_lse.py`), gráfico em hora de NY e preço com centavos. Pregões
  descartados: MES 43, MNQ 44 (lista nos YAML).
- **Etapa 2 ✅:** conversão em `run_strategy`, `bars["tick"]`/`abertura_min`/
  `inicio_min`, abertura de referência (09:30 NY), perfil padrão por ativo
  (`perfil_padrao` no YAML), `janela_valida` (recusa janela que atravessa a
  pausa; vale também para o WIN), trades, marcadores, Detalhes e Walk-Forward
  em hora de NY e pontos. A EMA de abertura só sinaliza depois da barra de
  abertura.
- **Etapa 3 (moeda) ❌:** `dinheiro()`, rótulos R$/US$, portão de custo da
  Candidata, bloqueio de portfólio com moedas misturadas.
- **Etapa 4 (faixas de mineração por ativo) ❌:** as faixas ainda são as do
  WIN; stop/alvo padrão do MES (10/20) e do MNQ (40/80) são provisórios.
- Pendências pequenas em "Estado depois da etapa 2" da spec.

Também entraram em 21–23/10: stop e alvo em porcentagem do preço de entrada
(`7d1d272`) e a estratégia `adx_direcao` (`cdb74bc`, `8eaca51`: parâmetros
`di_periodo` e `adx_suavizacao`, com trava contra colisão de nome com o perfil).

Pendente, não iniciado:
- **Gatilho, fatia 2**: avisar na tela de Portfólio que a correlação/risco
  estão desatualizados porque o plano ativo de uma variante membro mudou.
  Descrito como fora de escopo em `docs/superpowers/specs/2026-09-24-gatilho-reotimizacao-design.md §8`
  — ainda **não tem spec própria**; começar pelo brainstorming.

## Agentes do projeto (`.opencode/agent/`)

Mesmo conteúdo em `.opencode/agent/*.md` (OpenCode), `.codex/agents/*.toml`
(Codex) e `.claude/agents/*.md` (Claude); mudou um, mude os três. Se a
sessão não tiver o subagente, leia o arquivo do agente e siga-o você mesmo.

| Agente | Quando |
|---|---|
| `revisor` | revisão de uma mudança de impacto antes do commit, em segundo plano |
| `mutacao` | provar que os testes novos pegam implementação quebrada |
| `documentador` | pôr CHANGELOG/README/METODOLOGIA em dia depois de uma entrega |
| `auditor` | conferir se dados e cálculos batem com a realidade — refaz as contas por fora, só leitura no banco real |
| `designer-ui` | toda tela nova ou mudança visual, e quando o usuário achar uma tela confusa — layout, textos e CSS, sem mudar comportamento |

Depois de qualquer mudança de tela, avise em destaque: **feche e abra o
`iniciar.bat`** — o app aberto não carrega código nem CSS novos. Se mudou
`captura.py`, `core/captura.py`, `core/ingest.py`, `core/db_manager.py`,
`core/schema.sql` ou algo que o papel usa dentro da captura — `core/papel.py`,
`core/engine/*`, `core/plano.py`, `core/variantes.py`, `strategies/*` —,
feche também a janela **Dataframe - Captura** antes de reabrir o
`iniciar.bat`: a captura antiga segura a trava e a nova sai calada (código 4),
então reabrir só o `iniciar.bat` deixa o código velho gravando.

O `iniciar.bat` abre **três** janelas: **Dataframe - Captura** (`captura.bat`),
**Dataframe - Ordens real** (`ordens_real.bat`) e a do app. Se mudou
`core/ordens.py`, `core/corretora.py`, `core/papel_vivo.py`, `core/ponte.py`
ou `ordens_real.py`, feche **as duas** janelas (Captura e Ordens real) antes
de reabrir o `iniciar.bat`, pelo mesmo motivo da trava.

Só use agente onde ele poupa trabalho real; o resto faça direto.
