# Projeto D, parte 3: gatilho de reotimização

> Projeto D foi decomposto em três sub-projetos no brainstorm de
> 23/09/2026: **identidade da estratégia** (parte 1, implementada),
> **portfólio e correlação** (parte 2, implementada), e **gatilho
> operacional** (parte 3, esta spec). O gatilho operacional original foi
> ainda dividido em duas fatias — esta spec cobre só a primeira: avisar
> quando `reotimizar_em` vence. A segunda fatia (avisar quando a
> correlação de um portfólio ficou desatualizada porque uma variante
> membro foi reotimizada) fica para depois, como spec própria.

Desenhado em 24/09/2026.

## 1. O problema

`planos_operacao.reotimizar_em` já é gravado desde o fluxo original do
WFA/Candidata — é a data a partir da qual o plano deveria ser reavaliado
(rodar o WFA de novo com dado novo). Hoje essa data só aparece uma vez,
na mensagem de confirmação de quando o plano foi salvo
(`ui/callbacks_candidata.py`: "reotimizar até DD/MM/AAAA"). Depois disso
ela nunca mais é mostrada — não existe lugar nenhum na plataforma onde
você possa ver "quais planos estão vencidos ou perto de vencer" sem ir
consultar o banco à mão.

## 2. Escopo desta versão

- Achar planos **ativos** cujo `reotimizar_em` já passou ou está
  chegando (janela de 7 dias).
- Mostrar isso num selo no topo da tela, visível em qualquer modo, com
  uma lista ao clicar.

**Fora do escopo:**

- Mudar como `reotimizar_em` é calculado (`_quando_reotimizar`,
  `core/plano.py`) — fica como está.
- Avisar sobre correlação desatualizada em portfólio — segunda fatia do
  gatilho operacional, spec própria, mais adiante.
- Snooze/dispensar um aviso individualmente — todo plano vencido ou
  próximo aparece sempre, até você reotimizar de verdade (gravar um novo
  plano, que aposenta o antigo).
- Notificação fora da plataforma (e-mail, push) — só o selo, dentro do
  app.

## 3. Decisões travadas (24/09/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Qual das duas partes do gatilho primeiro? | **Reotimizar_em vencendo.** Mais simples, mais urgente, e serve pra qualquer plano — com ou sem portfólio. |
| 2 | Onde aparece? | **Selo no topbar**, ao lado do botão "Sincronizar com MT5" — visível em qualquer tela, sem precisar entrar em lugar nenhum. |
| 3 | O que o clique faz? | **Abre uma lista suspensa** ali mesmo, sem navegar para outra tela. |
| 4 | Janela de aviso ("próximo de vencer", não só "já venceu")? | **7 dias** de antecedência. |
| 5 | Atualização automática? | **Não.** Calculado uma vez por carregamento de página/troca de modo — reotimização é assunto de dias, não de segundos; um `dcc.Interval` novo rodando o tempo todo seria desperdício. |

## 4. Arquitetura

```
core/plano.py (já existe, ganha 1 função)
    vencendo(dias_aviso: int = 7) -> list[dict]

UI
    topbar(): selo (contagem + cor) + dropdown com a lista, ao lado do
    botão de sincronizar MT5.
```

Nenhuma tabela nova, nenhuma coluna nova — `reotimizar_em` já existe.
Esta spec só lê e mostra.

## 5. `vencendo(dias_aviso=7)`

```sql
SELECT p.plano_id, p.nome, p.symbol, p.strategy, p.reotimizar_em,
       ev.nome
FROM planos_operacao p
LEFT JOIN wfa_runs w ON w.wfa_id = p.wfa_id
LEFT JOIN mining_runs m ON m.run_id = w.run_id
LEFT JOIN estrategia_variantes ev ON ev.variante_id = m.variante_id
WHERE p.estado = 'ativo'
  AND p.reotimizar_em IS NOT NULL
  AND p.reotimizar_em <= ?   -- hoje + dias_aviso, calculado em Python
ORDER BY p.reotimizar_em
```

Devolve, por linha:

```python
{"plano_id": 7, "nome": "cruzamento tentativa 1", "symbol": "WIN$N",
 "strategy": "rompimento_canal", "variante_nome": "conservadora" | None,
 "reotimizar_em": date(2026, 9, 20), "dias_restantes": -4}
```

`dias_restantes` é calculado em Python (`(reotimizar_em - hoje).days`),
não em SQL — mais fácil de testar com data fixa via `monkeypatch`.
Negativo = já venceu; `variante_nome` é `None` quando a mineração é
antiga (sem `variante_id`) ou a variante foi apagada.

## 6. Tela

No `topbar()`, ao lado do botão "Sincronizar com MT5":

- Selo com a contagem (ex.: "3"). Sem itens → selo não aparece
  (nenhuma poluição visual quando não há nada pendente).
- Cor âmbar se todos os itens têm `dias_restantes >= 0` (só
  "próximos"); vermelha se pelo menos um já venceu
  (`dias_restantes < 0`).
- Clique abre/fecha um dropdown simples, cada linha:
  `<variante ou "sem variante"> · <estratégia> · vence em DD/MM` (ou
  `venceu há N dia(s)` quando `dias_restantes < 0`).

## 7. Testes

| alvo | prova |
|---|---|
| `plano.vencendo` | plano ativo com `reotimizar_em` no passado aparece com `dias_restantes` negativo; dentro da janela de `dias_aviso` aparece; fora da janela não aparece; plano `aposentado` nunca aparece (mesmo com `reotimizar_em` vencido); plano sem `reotimizar_em` (`NULL`) nunca aparece; mineração sem `variante_id` aparece com `variante_nome=None`; ordenado por `reotimizar_em` (o mais vencido primeiro) |

Banco temporário, como o resto da suíte — nunca `data/database.duckdb`.

## 8. O que fica de fora (segunda fatia do gatilho)

- Avisar quando a correlação de um portfólio ficou desatualizada porque
  uma variante membro foi reotimizada (plano ativo mudou depois do
  último cálculo de `correlacao()`).
- Qualquer forma de silenciar/adiar um aviso individual.
