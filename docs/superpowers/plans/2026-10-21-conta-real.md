# Parte 5 — Conta real: plano de implementação

Spec: docs/superpowers/specs/2026-10-19-conta-real-design.md (R1–R14 obrigatórios).
Protótipo (contrato visual): .superpowers/brainstorm/conta-real/conta-real-v2.html.
Execução: micro-tarefas para agentes Haiku (worktree isolada quando em paralelo), revisão cruzada Haiku + orquestrador. Briefs em .superpowers/sdd/real/<id>-brief.md.

## Constantes globais
- Testes nunca tocam data/database.duckdb, data/ao_vivo real, MT5 real (conftest desvia toda pasta nova).
- `git commit -F`, add por caminho, sem push; `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Envio da real continua travado (`ligar_envio`) até a tarefa F2.
- Telas: protótipo v2 é contrato; nenhum (?) some; nenhuma frase explicativa visível; nunca dict como filho html.

## Onda 1 (paralelo, arquivos disjuntos)
- **W1-A banco**: `ordens_eventos.origem` (schema idempotente + preenchimento pelo prefixo do evento_id), `diario_ordens.espelhar` grava origem, leitores de `papel_leitura` filtram origem (R6). Arquivos: core/schema.sql, core/diario_ordens.py, core/papel_leitura.py.
- **W1-B comandos por conta**: `comandos.PASTA_REAL`, `pasta_do_tipo()`, `zerar_tudo` nas duas pastas sem banco, `ligar_envio(tipo=)` e `encerrar_posicao` roteados (R2). Arquivos: core/comandos.py, core/ao_vivo.py (só ligar_envio/editar_conta), ui/callbacks_ordens.py, ui/callbacks_operacao.py (só o roteamento), tests/conftest.py (desvio PASTA_REAL).
- **W1-C fases**: `mudar_fase` aceita real (R1/R13), `definir_contratos`/`_restricoes`/`custo_de_um_stop` por conta, `papel_vivo.desejados` aceita fase real, `ler_retrato(tipo=)` (R7). Arquivos: core/ao_vivo.py (exceto ligar_envio), core/papel_vivo.py. ⚠ W1-B e W1-C tocam core/ao_vivo.py em funções diferentes → W1-C roda depois de W1-B ou faz merge.

## Onda 2
- **W2-A ponte**: `core/ponte.py` (escrever/ler desejados.json + vivo_em + seq + ack, R8–R11, retry PermissionError R10), captura publica antes da demo e espera ack ≤200 ms. Arquivos: core/ponte.py, captura.py, tests.
- **W2-B conta conferida**: `Fotografia.trade_mode`, conferência por volta (DEMO na captura, REAL na real), chamado conta_errada (R3). Arquivos: core/corretora.py, core/ordens.py.
- **W2-C processo real**: `ordens_real.py` (lock R4, loop 10 ms/0,5 s, Motor origem real pasta ordens/real, retrato tipo real + fallback, preparar_dia/cache_codigo, symbol_select+GuardaPreco, frescor R9, comandos real, estado_real.json, espelho feito pela captura R6), `ordens_real.bat`, `iniciar.bat`. Depende de W2-A/W2-B.

## Onda 3 (telas, paralelo por arquivo)
- **W3-A dados/saúde**: ui/data lê estado_real.json; faixa de saúde REAL/DEMO + "parado"; chamados da real com chip; zerar soma os dois (R12).
- **W3-B Operação** conforme v2 (tira 6, variantes REAL/DEMO, posições com Conta, abas com Real).
- **W3-C Estratégias** conforme v2 (portfólio por conta com toggles, ficha fases/contratos/na demo, contas em tabela, frases fora).

## Onda 4
- **F1** revisão final (agente + orquestrador), suíte inteira, comparação com o v2.
- **F2** soltar o Envio da real (`ligar_envio`), AGENTS/CHANGELOG, aviso de reabrir as 3 janelas.
