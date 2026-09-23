# Projeto D, parte 1: identidade da estratégia

> Projeto D ("Portfólio", `PLANO-CANDIDATA.md §11`) na verdade mistura três
> coisas: **identidade da estratégia** (esta spec), **portfólio e
> correlação propriamente ditos**, e **gatilho operacional** (avisar quando
> reotimizar, disparar re-teste). As duas últimas ficam para depois, como
> sub-projetos próprios, decompostos no brainstorm de 23/09/2026.

Desenhado em 23/09/2026.

## 1. O problema

Hoje, reotimizar uma estratégia (minerar de novo com dado novo, rodar o WFA,
gravar outro plano) não deixa rastro de que aquilo é **a mesma estratégia
de antes**, só que atualizada. Isso quebra em pelo menos dois lugares:

- **Projeto D (portfólio):** uma estratégia pode ter várias *variantes* —
  mesma lógica, capital/alvo/stop diferentes para portfólios diferentes.
  Reotimizar uma não avisa que as outras existem e podem precisar do mesmo
  cuidado.
- **Projeto C (incubação e conferência):** sinais capturados ao vivo
  (demo/real) precisam saber **qual plano estava valendo** quando saíram,
  para a comparação (backtest × demo × real) não misturar parâmetro velho
  com sinal novo depois de uma reotimização.

## 2. Escopo desta versão

Só a **identidade**: agrupar minerações/WFAs/planos que pertencem à mesma
variante de estratégia, ao longo do tempo. **Fora do escopo:**

- Portfólio propriamente dito (alocação, correlação entre variantes,
  risco agregado) — sub-projeto 2.
- Gatilho de "hora de reotimizar" / disparo automático de re-teste de
  correlação — sub-projeto 3.
- Vínculo com sinais ao vivo (isso é do projeto C, que ainda nem começou;
  quando C for desenhado, ele referencia `plano_id`, que por sua vez já
  aponta pra variante através da cascata desta spec).
- Metadados ricos por estratégia (autor, perfil, o que cada parâmetro
  faz, mercado, o que já foi medido) — o pedido original do
  `PLANO.md` item 6. Os módulos de hoje só expõem `label`; criar a
  convenção pra esses outros campos é tarefa própria, não consequência
  natural de rastrear variante.
- Marcar retroativamente as minerações já existentes (#40 a #45 e outras)
  com uma variante — **decisão do usuário (23/09/2026): não vale a pena**,
  elas podem inclusive ser apagadas. O controle vale só para o que for
  criado depois desta implementação.

## 3. Decisões travadas (23/09/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | O que define "mesma estratégia, variante diferente"? | **Módulo da estratégia + rótulo que o usuário dá.** Nada de agrupar sozinho comparando perfil de execução — arriscado (dois planos legítimos podem ter perfis parecidos por coincidência). |
| 2 | Onde a variante é escolhida/criada? | **Na mineração.** Ao salvar, escolhe uma variante existente ou cria uma nova. WFA e plano herdam por cascata (`run_id → variante_id`), sem precisar marcar de novo em cada tela. |
| 3 | Minerações antigas precisam de variante? | **Não.** Só o que for criado a partir de agora entra nesse controle; o antigo fica "sem variante" (ou é apagado, à parte desta spec). |
| 4 | Onde isso aparece na tela? | **Dentro da tela de estratégias pendente** (`PLANO.md` item 6, ainda não construída) — resolve os dois pedidos ao mesmo tempo, mas só a fatia que esta spec cobre: lista dos módulos (usando o `label` que `registry.descobrir` já lê hoje) e, dentro de cada um, a seção de variantes com a linha do tempo. **Os metadados ricos do pedido original de 18/09/2026** (autor, perfil "acerta muito/erra grande", o que cada parâmetro faz, mercado, o que já foi medido) **ficam de fora** — os módulos de estratégia não têm esses campos hoje (só `label`), e criar essa convenção é tarefa própria, não uma consequência natural de rastrear variante. |

## 4. Arquitetura

```
core/variantes.py (novo, sem Dash)
    criar(nome, estrategia) -> int
    listar(estrategia=None) -> list[dict]
    linha_do_tempo(variante_id) -> list[dict]

mining_runs
    + variante_id BIGINT NULL   (FK opcional; runs antigos ficam NULL)

wfa_runs, planos_operacao
    SEM coluna nova — chegam na variante seguindo run_id -> variante_id,
    a mesma cascata que mineração -> WFA -> plano já usa hoje.

UI
    "Salvar mineração": dropdown "variante" (opcional) ao lado do nome,
    com "criar nova variante" inline.
    Tela de estratégias (PLANO.md item 6): lista de módulos -> detalhe
    do módulo -> seção "variantes em uso" com a linha do tempo de cada uma.
```

## 5. Modelo de dados

```sql
CREATE TABLE IF NOT EXISTS estrategia_variantes (
    variante_id  BIGINT PRIMARY KEY,
    estrategia   VARCHAR NOT NULL,   -- nome do módulo (registry.descobrir)
    nome         VARCHAR NOT NULL,   -- rótulo dado pelo usuário
    descricao    VARCHAR,
    criado_em    TIMESTAMP NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_variante_id START 1;

ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS variante_id BIGINT;
```

`nome` é único **dentro da mesma estratégia** (duas variantes de
`rompimento_canal` não podem ter o mesmo rótulo; `rompimento_canal` e
`reversao_rsi` podem, cada uma tendo sua própria "conservadora", por
exemplo).

## 6. `linha_do_tempo(variante_id)`

Devolve, em ordem cronológica, uma linha por mineração vinculada àquela
variante, com o WFA salvo (se houver) e o plano de operação (se houver,
com `estado`) que vieram dela — a mesma cascata de exclusão que já existe
(`wfa_store.excluir`, `optimizer.excluir_salva`) é a fonte de quem
pertence a quem, só filtrada por `variante_id` na ponta da mineração.

```python
[
  {"run_id": 46, "criado_em": ..., "n_combinacoes": 165,
   "wfa_id": 12, "plano_id": 7, "plano_estado": "aposentado"},
  {"run_id": 52, "criado_em": ..., "n_combinacoes": 180,
   "wfa_id": 15, "plano_id": 9, "plano_estado": "ativo"},
]
```

## 7. Testes

| alvo | prova |
|---|---|
| `criar` | grava e devolve `variante_id`; nome duplicado na MESMA estratégia é recusado; nome duplicado em estratégias DIFERENTES é aceito |
| `listar` | filtra por estratégia; sem filtro devolve todas |
| `linha_do_tempo` | ordem cronológica certa; mineração sem WFA aparece com `wfa_id=None`; WFA sem plano aparece com `plano_id=None`; várias minerações da mesma variante aparecem todas |

Banco temporário, como o resto da suíte — nunca `data/database.duckdb`.

## 8. O que fica de fora (sub-projetos seguintes do D)

- Portfólio: escolher candidatas, alocação, correlação, risco agregado.
- Gatilho: avisar quando `reotimizar_em` (já gravado no plano) vence, e
  disparar re-teste de correlação quando uma variante do portfólio muda.
- Vínculo com sinais ao vivo do projeto C.
