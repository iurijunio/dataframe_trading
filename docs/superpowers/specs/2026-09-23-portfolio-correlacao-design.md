# Projeto D, parte 2: portfólio e correlação

> Projeto D ("Portfólio", `PLANO-CANDIDATA.md §11`) foi decomposto em três
> sub-projetos no brainstorm de 23/09/2026: **identidade da estratégia**
> (parte 1, `docs/superpowers/specs/2026-09-23-identidade-estrategia-design.md`,
> já implementada), **portfólio e correlação** (esta spec), e **gatilho
> operacional** (parte 3, ainda não desenhada).

Desenhado em 23/09/2026.

## 1. O problema

Você opera (ou pretende operar) mais de uma variante de estratégia ao
mesmo tempo. Hoje não existe lugar nenhum que responda:

- Quais variantes estão juntas num portfólio?
- Elas se movem parecido (perdem dinheiro nos mesmos dias) ou são
  diversificadas de verdade?
- No pior cenário razoável, quanto esse portfólio pode cair num único
  dia — relevante para regras de mesa proprietária que reprovam por
  drawdown diário?

## 2. Escopo desta versão

- Montar portfólios: agrupar variantes (identidade da parte 1) num
  conjunto nomeado.
- Correlação entre as variantes de um portfólio, a partir dos trades
  fora da amostra (OOS) do plano ativo de cada uma.
- Uma estimativa de drawdown diário combinado do portfólio, pensada para
  checar limites de mesa proprietária (ex.: "não pode passar de -R$
  400/dia").

**Fora do escopo:**

- Alocação de capital por variante dentro do portfólio — o capital de
  cada uma já vem do plano de operação dela (retrato gravado); o
  portfólio só agrupa, não redistribui.
- Gatilho automático de "hora de reotimizar" ou "correlação mudou,
  re-teste" — sub-projeto 3.
- Reconstrução exata (minuto a minuto) da curva de patrimônio combinada
  — ver §5.2, é deliberadamente uma estimativa estatística, não uma
  reconstrução perfeita.
- Vínculo com sinais ao vivo (projeto C).

## 3. Decisões travadas (23/09/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Quantos portfólios? | **Vários.** Uma variante pode participar de mais de um. |
| 2 | O que um portfólio guarda por variante? | **Só a associação** (`portfolio_id`, `variante_id`) — sem peso/capital próprio; o capital de cada uma vem do plano ativo dela. |
| 3 | O portfólio segue o plano ativo da variante, ou trava num plano específico? | **Segue automático.** O portfólio referencia a VARIANTE, nunca um `plano_id`; reotimizar a variante atualiza o portfólio sozinho — é o problema original que motivou o projeto D inteiro. |
| 4 | Correlação em cima de quê? | **Trades OOS do walk-forward** (`wfa_trades` do `wfa_id` do plano ativo de cada variante), reagregados em retorno diário — não a curva de equity (que mistura dimensionamento) e não o backtest otimizado (sobreajuste). |
| 5 | Período divergente entre variantes | **Interseção** das datas onde as duas têm dado — nunca inventa dado fora dela. |
| 6 | Onde acha "o plano ativo de hoje" de uma variante? | Helper novo `core.variantes.plano_ativo(variante_id)`, reaproveitando a mesma cascata de `linha_do_tempo` já revisada e testada na parte 1 — evita duplicar a lógica de "última mineração com plano ativo" dentro de `core/portfolio.py`. |
| 7 | Onde fica a tela? | **Sexto modo no topo**, tela própria "Portfólio" — mesmo padrão das outras cinco. |
| 8 | Drawdown diário combinado: soma do pior caso de todo mundo? | **Não** — descartado por ser pessimista demais (assume que todo trade bate o fundo no mesmo instante, o que não é realista com vários trades abertos em horários diferentes do dia). Ver §5.2. |

## 4. Arquitetura

```
core/variantes.py (já existe, parte 1 — ganha 1 função)
    plano_ativo(variante_id) -> dict | None
    # {"run_id", "wfa_id", "plano_id"} da mineracao mais recente desta
    # variante com um plano_operacao em estado='ativo'; None se nenhuma
    # mineracao da variante tem plano ativo hoje.

core/portfolio.py (novo, sem Dash)
    criar(nome) -> int
    listar() -> list[dict]
    adicionar_variante(portfolio_id, variante_id)
    remover_variante(portfolio_id, variante_id)
    membros(portfolio_id) -> list[dict]
    # {"variante_id", "nome", "estrategia", "wfa_id" | None,
    #  "sem_plano_ativo": bool}
    correlacao(portfolio_id) -> dict
    # {"variantes": [...nomes...], "matriz": [[...]],
    #  "risco_diario": {"p90": float, "pior_dia": str} | None,
    #  "avisos": [str, ...]}

portfolios              (novo)
portfolio_variantes     (novo, join)

UI
    Sexto modo "Portfólio": lista de portfólios -> detalhe (membros +
    heatmap de correlação + card de risco diário), no mesmo padrão da
    tela de Estratégias.
```

O portfólio nunca referencia `plano_id`, `wfa_id` ou `run_id` diretamente
— só `variante_id`. Tudo o mais é resolvido em tempo real via
`plano_ativo`, seguindo a mesma filosofia de "recalcula na hora" que o
WFA/Mineração já usa (`wfa_runner._span`).

## 5. Modelo de dados e cálculo

### 5.1 Tabelas

```sql
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id  BIGINT PRIMARY KEY,
    nome          VARCHAR NOT NULL,
    criado_em     TIMESTAMP NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_portfolio_id START 1;

CREATE TABLE IF NOT EXISTS portfolio_variantes (
    portfolio_id  BIGINT NOT NULL,
    variante_id   BIGINT NOT NULL,
    adicionado_em TIMESTAMP NOT NULL,
    PRIMARY KEY (portfolio_id, variante_id)
);
```

Nenhuma coluna nova em `mining_runs`, `wfa_runs` ou `planos_operacao`.

### 5.2 Correlação (Pearson, retorno diário)

Para cada membro do portfólio: `plano_ativo(variante_id)` → `wfa_id`.
Quem não tem plano ativo fica de fora da matriz e entra em `avisos`.

Para cada `wfa_id` restante: lê `wfa_trades` (`entry_ts`, `exit_ts`,
`liquido`), reagrega em retorno líquido por dia (soma de `liquido` dos
trades cujo `exit_ts` cai naquele dia — fechamento é o que realiza o
resultado).

Para cada par: corta as duas séries na interseção das datas onde ambas
têm dado. Menos de 20 dias úteis em comum → aviso "período curto demais
para correlação", não um número. Caso contrário, Pearson padrão. Matriz
simétrica, diagonal 1.0.

### 5.3 Drawdown diário combinado (estimativa, não reconstrução exata)

**Por que não é a soma bruta do MAE de todo mundo:** cada trade em
`wfa_trades` já grava `mae` (o pior ponto contra a posição, em pontos,
durante o trade — calculado pelo kernel de execução) e `entry_ts`/
`exit_ts`, mas **não** o instante exato em que o MAE aconteceu dentro
dessa janela. Somar o MAE de todos os trades abertos num dia assume que
todos bateram o fundo ao mesmo tempo — pessimismo artificial que
destruiria combinações genuinamente diversificadas.

**O que se faz em vez disso — simulação:**

```python
core/portfolio.py
    _simular_drawdown_dia(trades_do_dia: list[dict], n: int = 2000) -> list[float]
    # trades_do_dia: [{"entry_ts", "exit_ts", "mae_reais", "liquido_reais"}, ...]
    # devolve N amostras do "pior ponto combinado" daquele dia
```

Para cada uma das ~2.000 simulações: sorteia, para cada trade do dia, um
instante uniforme dentro de `[entry_ts, exit_ts]` como "quando" o MAE
teria acontecido; monta a linha do tempo de todos os trades daquele dia
e soma o efeito de cada um no instante em que está "no fundo" (MAE) ou
já encerrado (`liquido`, se o instante simulado for depois do `exit_ts`
de outro trade); guarda o pior ponto combinado dessa simulação.

`risco_diario` reporta o **percentil 90** dessas amostras — um número
que só é ultrapassado em 10% dos cenários simulados, não o pior caso
impossível. Roda por dia com 2+ trades sobrepostos; o pior dia entre
todos vira `pior_dia`. Portfólio com histórico curto ou sem sobreposição
nenhuma → `risco_diario: None`, sem quebrar a tela.

Todo o cálculo usa só colunas que já existem em `wfa_trades` — nenhuma
mudança na engine, nenhuma leitura de barra.

## 6. Tela

Sexto modo "Portfólio", mesmo padrão de Estratégias (lista de cartões →
detalhe):

- **Lista**: cartão por portfólio (nome, contagem de membros).
- **Criar**: campo de nome + botão.
- **Detalhe de um portfólio**:
  - Lista de membros: nome da variante, estratégia, e "plano ativo" ou
    "sem plano ativo" por linha; dropdown para adicionar variante
    (todas as variantes existentes, qualquer estratégia); botão remover
    por linha.
  - **Heatmap de correlação**: matriz nome × nome, célula colorida
    verde (baixa/negativa) → vermelho (alta), não só número cru.
  - **Card de risco diário**: "drawdown diário combinado (p90): R$ X",
    mesmo padrão visual dos cartões de métrica do Backtest (cor
    vermelho/verde conforme severidade).
  - Avisos (variante sem plano ativo, par com período curto demais)
    aparecem como nota discreta abaixo do heatmap — nunca travam a
    tela.

## 7. Testes

| alvo | prova |
|---|---|
| `variantes.plano_ativo` | mineração mais recente da variante com plano `ativo`; ignora planos `aposentado`; `None` quando nenhuma mineração da variante tem plano ativo |
| `portfolio.criar/listar` | grava e lista |
| `portfolio.adicionar_variante/remover_variante/membros` | membros refletem adições/remoções; membro sem plano ativo aparece com `sem_plano_ativo=True` |
| `portfolio.correlacao` — matriz | duas séries de retorno diário sintéticas idênticas dão ~1.0; opostas dão ~-1.0; interseção de datas cortada corretamente quando os períodos não batem; par com poucos dias em comum vira aviso, não número |
| `portfolio.correlacao` — risco diário | dois trades com MAE grande e janelas de tempo QUE NÃO SE SOBREPÕEM nunca aparecem juntos numa simulação (p90 não conta os dois); dois trades cujas janelas cobrem o dia INTEIRO (sempre sobrepostos) dão p90 próximo da soma dos MAEs, já que a simulação sempre os encontra juntos; portfólio sem sobreposição nenhuma dá `risco_diario: None` |
| §7 fora de escopo | nenhum teste cobre alocação de capital, gatilho automático ou reconstrução minuto a minuto — não fazem parte desta spec |
