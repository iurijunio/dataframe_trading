# Dataframe — instruções do projeto

> **Fonte única.** Codex, Claude e OpenCode leem este arquivo. O `CLAUDE.md`
> é só um ponteiro para cá: mudou regra, status ou pendência, edite **aqui**.

Plataforma quantitativa em Python (Dash + DuckDB + Numba) para criar, minerar,
validar e operar estratégias de day trade no Mini Índice (`WIN$N`),
substituindo o fluxo que antes vivia no MT5. Branch de trabalho:
`live-trading` (parte 4, ordens), criada do `master` em 08/10/2026 depois
de o usuário juntar o `candidata` nele (remoto `origin` no GitHub).

## O usuário

- Fala português; responda em português, **direto e sem jargão**.
- Não gosta de terminal: prefere **ver funcionando na tela**. Resultado se
  mostra com screenshot do app, não com saída de comando.
- Ele dá o aval final. Não commite nem faça push sem ele pedir.

## Rodar

```
.venv/Scripts/python.exe ui/app.py          # http://127.0.0.1:8050
.venv/Scripts/python.exe -m pytest -q       # suíte inteira (~2.100 testes, <1 min de coleta)
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
    `git diff 421cc4f..be5ba7f -- ui/`):
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

| Documento | Estado (05/10/2026) |
|---|---|
| `docs/superpowers/specs/*` e `plans/*` | desenho de cada entrega recente — **fonte mais confiável** do porquê |
| `docs/CALCULOS-WFA.md`, `docs/CALCULOS-CANDIDATA.md` | como cada número é calculado — confiável |
| `docs/PLANO*.md`, `docs/EXECUCAO-CANDIDATA-*.md` | histórico de decisões; planos já executados |
| `docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md` | spec da parte 4 (ordens) — implementada; o `...-ordens-decisoes.md` é o rascunho que a originou |
| `CHANGELOG.md` | atualizado até a parte 4 do Ao vivo (ordens na demo); **não cobre variantes, portfólio nem gatilho** |
| `README.md` | **desatualizado**: descreve o MVP (4 modos, "759 testes") |
| `docs/METODOLOGIA.md` "Estado da plataforma" | **desatualizado**: marca Portfólio como ❌ |

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
   "seria enviada". Conta real fica fora desta parte. Pausar com posição
   aberta encerra na hora.
   **Situação em 15/10/2026:** o usuário dispensou o ensaio de um pregão
   inteiro. A **ordem de teste** na demo passou (entrada 149 ms, proteção
   676 ms, saída 496 ms). O **Envio de ordens está LIGADO na conta demo, com
   1 contrato**, na ligação do `rompimento_ema_abertura`; a ligação do
   rompimento de canal segue só no papel. O PR `live-trading` → `master` está
   aberto (não mergeado).
   **Próximo passo:** acompanhar a demo por 3 a 5 pregões, comparando papel ×
   demo todo dia; depois mergear no `master` e promover a estratégia de canal.
   Ideias para depois: "sair no sinal contrário" como opção minerável; recursos
   com LLM fora do caminho da ordem; aba Conta.
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

Só use agente onde ele poupa trabalho real; o resto faça direto.
