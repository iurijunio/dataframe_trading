---
paths:
  - "*.py"
  - "core/**"
  - "ui/**"
  - "strategies/**"
  - "scripts/**"
---
# Código pequeno (pedido do usuário, 11/11/2026)

Vale para todo código novo e para todo arquivo que você tocar, em qualquer sessão e em qualquer agente.

- **Arquivo pequeno, uma responsabilidade.** Teto de 500 linhas por arquivo (o teste
  `tests/test_regras_agentes.py` barra). Mire em 150–300. Chegou perto do teto: divida antes de
  acrescentar, nunca depois.
- **Função atômica.** Faz uma coisa só e cabe numa tela (mire em até ~40 linhas). Se precisa de um
  comentário "agora faz X" no meio, X é outra função.
- **Pasta por assunto.** Tema com mais de um arquivo vira pacote (`core/busca/`, `core/leitura/`,
  `ui/cb_operacao/`). Nome do arquivo diz o que mora nele; nada de `utils.py` genérico.
- **Projeto novo nasce assim:** estrutura de pastas decidida no desenho, antes do primeiro arquivo.
- **Arquivo grande que já existe** (lista `GRANDES` do teste): não cresce. Mexeu nele, tire a sua parte
  para um arquivo novo; dividir o resto é entrega separada, sem mudar comportamento (plano
  `docs/superpowers/plans/2026-11-09-modularizacao.md`). Código que opera a conta real (captura, ordens,
  papel) só se divide com a suíte inteira verde e o aval do usuário.
