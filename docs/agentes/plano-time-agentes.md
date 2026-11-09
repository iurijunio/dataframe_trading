# Time de agentes — plano (09/11/2026)

**Objetivo:** gastar menos tokens sem perder qualidade onde há dinheiro. A conversa
principal no Opus pensa e decide. O trabalho braçal vai para Sonnet ou Haiku.

**Regra de escolha:** Haiku para tarefa mecânica, com resposta que dá para conferir.
Sonnet para codar. Opus só onde um erro passaria despercebido (conta, ordens, revisão).

## Passos

1. **Trocar o modelo dos agentes que já existem** (só a linha `model:`)
   - `designer-ui`: opus → sonnet
   - `mutacao`: sonnet → haiku
   - `documentador`: sonnet → haiku
   - `revisor` e `auditor` continuam no opus

2. **Criar o `testador`** (`.claude/agents/testador.md`, haiku, sem Edit/Write)
   - Roda o pytest (o arquivo pedido ou a suíte inteira) e o `scripts/conferir.py`.
   - Devolve no máximo: quantos passaram e falharam, cada falha com arquivo:linha e
     a mensagem de erro exata, e o que o `conferir.py` mandou reabrir.
   - Nunca corrige nada e nunca toca `data/`.

3. **Criar o `executor`** (`.claude/agents/executor.md`, sonnet)
   - Implementa **um** passo de plano já escrito, com os arquivos já indicados.
   - Segue as regras do AGENTS.md: teste primeiro, português, `core/` sem Dash.
   - Não commita. Devolve o que mudou (arquivo:linha) e o resultado do teste.
   - Não usar em ordens/conta real sem o `revisor` depois.

4. **Modelo dos agentes genéricos:** em `.claude/settings.json`, `env` →
   `"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"`. Vale só para agente sem `model:` próprio.

5. **AGENTS.md** — atualizar a tabela "Agentes do projeto" com `testador` e
   `executor`, e uma linha: "busca grande vai para o `Explore` (Haiku)".
   Conferir se o teste de tamanho do AGENTS.md continua passando.

6. **Conferir:** `tests/` do harness verdes; abrir uma sessão nova e chamar cada
   agente novo uma vez numa tarefa pequena para ver se ele responde curto e no modelo certo.

## Fora deste plano

- Conferir se o superpowers está instalado, depois que a sessão da worktree
  `modularizacao` terminar.
