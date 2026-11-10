---
name: review-dataframe
description: Revisar diff de impacto do Dataframe em cálculos, dados, banco, conta ou callbacks com estado antes de concluir ou quando o usuário pedir revisão. Dispensar em layout, texto e CSS simples.
---

# Revisar Dataframe

## Passos

1. Leia `AGENTS.md`, regras da área e eventuais instruções locais. Identifique
   o escopo solicitado com `git status --short`, `git diff` e
   `git diff --cached`; leia arquivos novos que façam parte desse escopo.
   Preserve mudanças alheias, inclusive as já adicionadas ao Git.
2. Consulte `.codex/agents/reviewer.toml` para os critérios do domínio.
3. Priorize erros de conta e unidade, datas e futuro indevido, persistência,
   conta/ordem errada, concorrência DuckDB, ciclos de callbacks e testes fracos.
   Confira a especificação pertinente, sem carregar todos os planos.
4. Exija evidência adequada: teste de regressão para bug; mutação restaurada,
   revisão independente e suíte completa para impacto. Para executar verificações,
   use o fluxo de validação do projeto; registre o que não foi executado.
5. Relate problemas acionáveis: arquivo:linha, cenário concreto, efeito e
   correção sugerida. Separe certeza de suspeita. Sem achados, diga isso e
   indique o limite da revisão; ausência de achados não prova ausência de bugs.

## Validação e aceite

Comandos de leitura: `git diff --check`, `git diff -- <caminhos>` e
`git diff --cached -- <caminhos>`. Se necessário e dentro do escopo, execute
`.venv/Scripts/python.exe -m pytest -q tests/<arquivo>.py`.
Revisão concluída com achados fundamentados ou nenhum achado acionável,
acompanhados das verificações disponíveis e pendências.

## Não fazer

Não editar durante revisão, enviar ordens, abrir serviços, escrever no banco
real, mudar dependências, sugerir estilo sem efeito ou criar commit.
Revisão independente usa outro agente quando disponível; revisão própria deve
ser identificada como tal. Leia `.codex/agents/mutation.toml` se precisar avaliar
a prova dos testes; não faça mutação como parte desta revisão somente leitura.

As referências são caminhos relativos à raiz do repositório.
