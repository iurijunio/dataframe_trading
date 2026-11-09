# Dataframe — instruções do projeto

> Só o que vale para quase toda tarefa, carregado em toda sessão (um teste limita
> o tamanho). Regra de uma área vai em `.claude/rules/`, não aqui.

Plataforma quantitativa em Python (Dash + DuckDB + Numba) para criar, minerar,
validar e operar estratégias de day trade. Ramo principal: `master`; remoto
`origin` no GitHub.

**⚠ Há estratégias operando na conta real.** Nunca envie ordem nem zere posição:
o usuário faz isso na tela ou no MT5.

## O usuário

- Trader, não programador. Responda em português, **direto e sem jargão**;
  termo novo vem com um exemplo dos dados dele.
- Prefere **ver funcionando na tela**: resultado se mostra com screenshot.
- Ele dá o aval final. Não commite, não faça merge nem push sem ele pedir.

## Rodar

```
.venv/Scripts/python.exe ui/app.py          # http://127.0.0.1:8050
.venv/Scripts/python.exe -m pytest -q       # suíte inteira
```

- Para ver o app, `preview_start` com o nome `dataframe`; **só com o app real
  fechado**, porque a cópia abre o banco real.
- **Git**: mensagem de commit com mais de uma linha vai num arquivo do
  scratchpad, com `git commit -F <arquivo>`; nunca heredoc (quebra com acentos).
- Adicione arquivos ao commit **pelo caminho**, nunca `git add -A` / `git add .`.
  Alteração que você não fez é do usuário: não stageie.
- **Worktrees:** `data/` e `.venv/` são junções para os originais. Remova com
  `cmd /c rmdir`, nunca `rm -rf`, ou apaga o banco real.

## Contexto barato

Localize com busca de texto e leia arquivo grande por trecho, em volta da linha
encontrada. Nunca abra o `CHANGELOG.md` inteiro.

## Tamanho da tarefa

Classifique antes de começar e use o **menor** fluxo que cabe:

- **Micro** (texto, CSS, renomear, pergunta de "onde fica"): faça direto, sem
  plano nem subagente.
- **Simples** (poucos arquivos, sem conta/estado/banco): localizar → editar →
  teste do arquivo tocado.
- **Impacto**: o fluxo abaixo, inteiro.

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

**Depois de mudar código**, rode `.venv/Scripts/python.exe scripts/conferir.py`:
ele diz o que conferir e o que reabrir. Avise o usuário em destaque; o app
aberto não carrega código novo.

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
- Nada de valor fixo ou nome de item específico (estratégia, ativo, arquivo) onde
  a regra vale para todos: leia do código.

## Glossário (use estes nomes com o usuário)

- **Estratégia** — o código em `strategies/*.py`.
- **Variante** — uma configuração salva de uma estratégia, com nome dado pelo
  usuário. Clusters diferentes da mesma estratégia são variantes diferentes.
  Atravessa reotimizações: só troca de plano.
- **Plano** — o que a Candidata grava para operar (parâmetros, contratos,
  disjuntor). Uma variante tem **um plano ativo por vez**.
- **Fase** — onde a variante está no caminho até o dinheiro real, por
  portfólio: papel → demo → real. (Nunca "degrau". O "real mínimo" foi
  eliminado nas decisões da parte 4; o `real_minimo` do banco migra para
  `real`.)
- **Serviço de captura** — o processo à parte (aberto pelo `iniciar.bat`) que
  grava os candles ao vivo; na parte 4 passa a ser a automação que opera.
  Nunca "robô". Vocabulário profissional, de mesa de operações.

## Armadilhas que valem para tudo

- **DuckDB: vários leitores OU um escritor.** Workers leem do espelho Parquet
  (`db.read_bars_parquet`); gravação via `db.connect_write()`.
- **`COPY … TO ?` com parâmetro não grava nada, em silêncio** — caminho literal via `_sql_str`.
- **Ciclo entre callbacks congela a tela sem erro.** `tests/test_callbacks_sem_ciclo.py`
  pega; rode-o sempre que mexer em Inputs/Outputs.
- Nunca mandar as ~700 mil barras ao navegador — `ui/data.py` agrega pelo `MAX_CANDLES`.
- Look-ahead é travado no kernel: sinal da barra `i` executa na abertura de `i+1`.
- **O `.duckdb` deixou de ser só cache:** `contas`, `portfolio_membros`,
  `ao_vivo_eventos`, `planos`, `papel_operacoes`, `papel_pregoes`,
  `ordens_eventos` e `papel_backtest` não se recriam — backup antes de qualquer
  migração; nunca apagar o banco. Também nunca se apaga o diário de escrita
  adiantada `data/ao_vivo/ordens/*.jsonl`: é dele (não do banco) que a captura
  relê "já enviei a entrada X" e "conta travada hoje".

## Regras por área

Cada regra carrega sozinha quando um arquivo da área é aberto, inclusive em
subagente. **Busca de texto não carrega.** Antes de criar arquivo novo ou editar
por script, ou se a regra da área não estiver no seu contexto, leia-a à mão:

| A tarefa toca… | Regra |
|---|---|
| captura, MT5, candles, papel, reconferência | `.claude/rules/captura-papel.md` |
| ordens, conta real, ponte, promoção de fase | `.claude/rules/ordens.md` |
| motor, estratégias, `codigo_hash` | `.claude/rules/motor-estrategias.md` |
| mineração, faixas, campos do menu | `.claude/rules/mineracao.md` |
| Busca automática | `.claude/rules/busca.md` |
| MES/MNQ, escala, unidades | `.claude/rules/cme.md` |
| Portfólio | `.claude/rules/portfolio.md` |
| qualquer tela | `.claude/rules/tela.md` |

Para retomar entrega, ver pendências ou saber qual documento confiar:
`docs/agentes/estado.md`. Mapa dos arquivos: `docs/agentes/arquitetura.md`.

## Agentes do projeto

Ficam em `.claude/agents/*.md`. Se a sessão não tiver o subagente, leia o
arquivo do agente e siga-o você mesmo. Só use agente onde ele poupa trabalho real.

Modelo pelo risco: Haiku no mecânico e conferível, Sonnet para codar, Opus só
onde um erro passaria despercebido. Busca que varre muitos arquivos vai para o
`Explore` (Haiku), não para a conversa principal.

| Agente | Quando |
|---|---|
| `testador` | rodar pytest e `scripts/conferir.py`; devolve só as falhas |
| `executor` | implementar um passo de plano já decidido (arquivos e teste definidos) |
| `revisor` | revisão de uma mudança de impacto antes do commit, em segundo plano |
| `mutacao` | provar que os testes novos pegam implementação quebrada |
| `documentador` | pôr CHANGELOG/README/METODOLOGIA e `docs/agentes/estado.md` em dia depois de uma entrega |
| `auditor` | conferir se dados e cálculos batem com a realidade — refaz as contas por fora, só leitura no banco real |
| `designer-ui` | toda tela nova ou mudança visual, e quando o usuário achar uma tela confusa — layout, textos e CSS, sem mudar comportamento |
