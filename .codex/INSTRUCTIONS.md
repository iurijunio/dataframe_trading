# Instruções exclusivas do Codex

Leia também o `AGENTS.md` compartilhado. Para regras de domínio, use os arquivos
abaixo em vez das referências `.claude/` da raiz; não dependa do cliente Claude.
Antes de abrir ou editar a área, leia as instruções aplicáveis, inclusive em
subagentes. O cabeçalho `paths` orienta a seleção; não carrega Markdown sozinho.

| Área | Instrução |
|---|---|
| captura, MT5, candles, papel, reconferência | `.codex/instructions/capture-paper.md` |
| ordens, conta real, ponte, promoção de fase | `.codex/instructions/orders.md` |
| motor, estratégias, codigo_hash | `.codex/instructions/engine-strategies.md` |
| mineração, faixas, campos do menu | `.codex/instructions/mining.md` |
| busca automática | `.codex/instructions/search.md` |
| CME, escala e unidades | `.codex/instructions/cme.md` |
| portfólio | `.codex/instructions/portfolio.md` |
| qualquer tela | `.codex/instructions/ui.md` |

## Orquestração

Modelos, esforços e limite de concorrência estão em `.codex/config.toml` e nos
perfis nativos `.codex/agents/*.toml`; não duplique essas configurações na raiz.
Para exploração ampla, delegue ao `explorer`; para impacto, `mutation` e
`reviewer`. `implementer` implementa passos definidos, `ui-designer` cuida das telas,
`auditor` refaz contas e `architect` diagnostica problemas profundos. Use
`tester` para verificações e `documenter` para documentação. Micro fica no
principal. Sem agente disponível, leia seu TOML e identifique a execução própria.
Não abra outra CLI para contornar limites.

Skills: `.agents/skills/validate-dataframe/` e `.agents/skills/review-dataframe/`.
Hooks: `.codex/hooks.json`; regras de comandos: `.codex/rules/`. Exigem projeto
confiável e revisão dos hooks pelo usuário, sem substituir as regras de segurança.
Configuração nova exige nova sessão; escolha explícita pode sobrepor o padrão.
Guia de ativação e validação: `.codex/README.md`.
