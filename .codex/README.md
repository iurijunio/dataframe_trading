# Harness nativo do Codex

## Estrutura e carregamento

- `AGENTS.md`: núcleo compartilhado, sem modelos, caminhos ou operação do Codex.
- `.codex/INSTRUCTIONS.md`: encaminhamento exclusivo do Codex, solicitado por
  `developer_instructions` em `.codex/config.toml`. Não substitui as instruções
  nativas do modelo. Markdown em `.codex/instructions/` não é regra executável
  nem carrega automaticamente por `paths`.
- `.codex/config.toml`: modelo principal Sol/medium, subagente padrão Luna/high,
  até três subagentes simultâneos, hooks habilitados. Não altera permissões,
  provedor, secrets ou configuração global.
- `.codex/agents/*.toml`: agentes nativos descobertos pelo cliente, cada um com
  nome, descrição, instruções, modelo e esforço explícitos.
- `.agents/skills/*/SKILL.md`: workflows descobertos pelo Codex. Validação e
  revisão usam somente referências nativas deste harness.
- `.codex/instructions/*.md`: oito áreas do domínio mantidas pelo harness do Codex.
- `.codex/rules/security.rules`: prefixos proibidos (limpeza Git e adição ampla).
  Controlam pedidos de execução fora do sandbox; o hook complementa a execução
  normal. `git clean` é proibido inclusive além de `-x`, por segurança.
- `.codex/hooks.json` e `.codex/hooks/guard.py`: proteção antes de shell e
  patches para serviços operacionais, diário, junções, Git e app duplicado.
  O hook resolve a raiz Git e usa o Python do projeto, inclusive em subpastas.

## Modelos configurados

| Papel | Modelo | Esforço |
|---|---|---|
| Principal | `gpt-6.1-sol` | `medium` |
| explorer, tester, mutation, documenter | `gpt-6-luna` | `high` |
| implementer, ui-designer | `gpt-6.1-terra` | `medium` |
| reviewer | `gpt-6.1-sol` | `high` |
| auditor, architect | `gpt-6-astra` | `high` |

Luna/high segue a orientação atual da OpenAI para tarefas delimitadas. Esforço
não é comparável como custo absoluto entre famílias. Astra fica restrito a
auditoria, diagnóstico e decisões profundas; Sol faz a revisão diária.
Não troque silenciosamente um modelo indisponível: relate a limitação.

## Ativação e limites

Abra uma nova sessão no projeto confiável após mudar configuração/agentes/regras.
Revise os hooks em Settings > Hooks ou `/hooks`; o cliente exige confiança antes
de executar hooks não gerenciados. Não automatize a concessão dessa confiança.
Uma escolha explícita de modelo da sessão pode sobrepor o padrão do projeto;
o TOML do agente customizado define seu próprio modelo/esforço.
Herança de permissões não muda: instrução de somente leitura não cria sandbox
separado. Hooks e prefixos são proteções contra enganos, não uma barreira completa:
shell dinâmico, ferramentas especiais e entrada por `write_stdin` têm limites.
Erro/timeout do hook pode liberar a ferramenta; as regras da raiz continuam valendo.

Não é preciso abrir o Dataframe, reiniciar captura ou ordens reais para ativar
este harness. Não use outra CLI com inferência para contornar limites de agentes.

## Validação sem operação

Na raiz, com Python existente:

```
.venv/Scripts/python.exe -m unittest discover -s .codex/tests -v
.venv/Scripts/python.exe -m pytest -q tests/test_regras_agentes.py
.venv/Scripts/python.exe scripts/conferir.py
codex execpolicy check --rules .codex/rules/security.rules -- git clean -fdx
codex execpolicy check --rules .codex/rules/security.rules -- git status
```

Os testes do harness não importam produção, não abrem MT5 nem banco real.
O teste pytest existente usa seu isolamento normal. Se a pasta temporária do
sandbox falhar, forneça `--basetemp` com pasta nova permitida fora de `data/`.
Testes que usam `tempfile.TemporaryDirectory` também precisam de `TEMP` e `TMP`
apontando para uma pasta permitida, apenas no processo de teste. Não altere as
variáveis permanentes do Windows. Na validação de 10/11/2026, a suíte teve
3.195 passes e cinco falhas de permissão no temporário do sandbox; os cinco
passaram isoladamente com esses diretórios ajustados. Os 15 testes próprios
do harness passaram; revisão independente e três mutações em memória verificaram
as proteções sem executar comandos operacionais.
Para validar skills, use `quick_validate.py` da skill de criação disponível
no host, com `PYTHONUTF8=1`; não instale validadores no projeto.

## Documentação oficial consultada

- [Configuração](https://learn.chatgpt.com/docs/config-file/config-basic)
- [Referência](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Subagentes](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Regras de comandos](https://learn.chatgpt.com/docs/agent-configuration/rules)
- [Hooks](https://learn.chatgpt.com/docs/hooks)
- [Modelos](https://learn.chatgpt.com/docs/models)
- [Skills](https://learn.chatgpt.com/docs/build-skills)
