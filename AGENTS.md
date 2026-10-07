# Dataframe — instruções do projeto

> **Fonte única.** Codex, Claude e OpenCode leem este arquivo. O `CLAUDE.md`
> é só um ponteiro para cá: mudou regra, status ou pendência, edite **aqui**.

Plataforma quantitativa em Python (Dash + DuckDB + Numba) para criar, minerar,
validar e operar estratégias de day trade no Mini Índice (`WIN$N`),
substituindo o fluxo que antes vivia no MT5. Branch de trabalho: `candidata`
(remoto `origin` no GitHub). `master` é só o estado anterior ao modo
Candidata — não trabalhe nela.

## O usuário

- Fala português; responda em português, **direto e sem jargão**.
- Não gosta de terminal: prefere **ver funcionando na tela**. Resultado se
  mostra com screenshot do app, não com saída de comando.
- Ele dá o aval final. Não commite nem faça push sem ele pedir.

## Rodar

```
.venv/Scripts/python.exe ui/app.py          # http://127.0.0.1:8050
.venv/Scripts/python.exe -m pytest -q       # suíte inteira (~1.300 testes, <1 min de coleta)
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
  eliminado nas decisões da parte 4 — o código ainda tem `real_minimo`
  até a migração da parte 4.)
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
| Ao vivo | `ao_vivo.py`, `diario.py`, `codigo.py`, `captura.py` (o processo da captura é o `captura.py` da raiz, aberto pelo `captura.bat`), `papel.py`, `papel_leitura.py` | `callbacks_ao_vivo.py`, `components/ao_vivo_panel.py`, `callbacks_pregao.py`, `components/pregao_panel.py`, `callbacks_operacao.py`, `components/operacao_panel.py` |

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
  `ao_vivo_eventos`, `planos`, `papel_operacoes` e `papel_pregoes` não se recriam — backup antes de qualquer
  migração; nunca apagar o banco.
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
| `CHANGELOG.md` | atualizado até a parte 3 do Ao vivo (papel/Operação); **não cobre variantes, portfólio nem gatilho** |
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
4. Ordens pelo próprio Dataframe (demo primeiro) + comparativo backtest ×
   papel × demo/real (sinal no mesmo minuto, preço, derrapagem).
   **Em brainstorming:** 12 decisões já tomadas em
   `docs/superpowers/specs/2026-10-05-ao-vivo-ordens-decisoes.md` (retomar
   dali: rascunho visual → spec → revisão → plano). Pausar com posição
   aberta encerra na hora.
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
