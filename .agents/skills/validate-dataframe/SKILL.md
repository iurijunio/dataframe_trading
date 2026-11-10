---
name: validate-dataframe
description: Selecionar e executar verificações do Dataframe após mudanças ou diagnosticar falhas de testes. Usar para código ou manutenção do harness; dispensar em perguntas e ajustes micro.
---

# Validar Dataframe

## Passos

1. Leia o `AGENTS.md` da raiz, instruções locais e regras da área alterada.
   Consulte `git status --short` e o diff; separe o escopo pedido das mudanças do usuário.
2. Antes de alterar código, escolha o teste que prova o comportamento. Bug exige
   regressão: falhar antes, passar depois. Impacto exige também mutação e revisão
   conforme a raiz; detalhes em `.codex/agents/mutation.toml`.
3. Na raiz, execute `.venv/Scripts/python.exe -m pytest -q tests/<arquivo>.py`
   com caminhos reais relacionados. Para impacto, rode também
   `.venv/Scripts/python.exe -m pytest -q`.
4. Depois de mudar código, execute
   `.venv/Scripts/python.exe scripts/conferir.py`. Leia os comandos indicados
   antes de executá-los: alguns dependem de dados, argumento ou comparação prévia.
   O relatório inclui todas as mudanças locais, inclusive as do usuário.
5. Mudou Input/Output de callback: rode
   `.venv/Scripts/python.exe -m pytest -q tests/test_callbacks_sem_ciclo.py`.
   Mudou harness: rode
   `.venv/Scripts/python.exe -m pytest -q tests/test_regras_agentes.py` e
   `.venv/Scripts/python.exe -m unittest discover -s .codex/tests -v`;
   confira o frontmatter e as referências das skills alteradas.
6. Relate comandos, totais, falhas e limites. Destaque o que o usuário precisa
   reabrir; não reinicie serviços. Diagnóstico: reproduza a falha isolada e
   identifique a causa antes de mudar código ou dependências.

## Aceite

Verificações exigidas pelo tamanho da tarefa passam; cada pendência está explícita.
Documento puro dispensa suíte completa; layout segue a aprovação visual da raiz.
Não há lint/typecheck/build configurados: registre como não configurados.

## Não fazer

- Não usar banco, diário, comandos ou ponte reais para gravar testes; seguir
  `tests/conftest.py` e o exemplo de fixture em `tests/test_portfolio.py`.
- Não abrir app, captura, MT5 ou ordens para diagnosticar teste.
- Não regenerar referências para esconder diferenças nem instalar ferramentas.
- Não repetir suíte verde sem mudança ou dúvida concreta; não commitar.

As referências são caminhos relativos à raiz do repositório. Para relatório
compacto de falhas, consulte `.codex/agents/tester.toml`.
