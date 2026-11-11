# Novo ao vivo para mesas (prop_live) — o que muda no Dataframe

**Data:** 11/11/2026 · desenho aprovado pelo usuário.
O desenho completo mora no projeto novo: `C:\Users\mrRobot\Documents\Neturna\prop_live\docs\specs\2026-11-11-design.md`.
Aqui fica só a parte que toca o Dataframe.

## O que muda aqui
1. **Contrato do pacote** em `core/contratos/pacote_mesa.py`: dataclass + gravar/ler + `format_version`.
   Chaves do JSON e campos em **inglês** (superfície entre projetos); o resto do módulo em português.
   Campos: `format_version`, `exported_at`, `platform_commit`, `engine_version` (`core.engine.VERSAO`),
   `portfolio` (id, nome, capital, moeda), `variants` (campos tipados: id, nome, estratégia, `plan_id`,
   símbolo, timeframe, contratos, limites do disjuntor + `engine_plan` opaco com o plano gravado) e
   `instrument` (a ficha do ativo, com `pregoes_descartados`).
2. **Comando** `cli.py exportar-pacote --portfolio <id> --saida <pasta>`: só lê o banco; grava o JSON.
3. **`tests/test_superficie_prop_live.py`**: fixa nome e assinatura das funções que a ponte do prop_live usa
   (`papel.perfil_do_plano`, `pregoes_de_aquecimento`, `com_barra_provisoria`, `calcular`;
   `execution.run_strategy`; `ativo.ficha_de`, `preco_para_exibir`, `hora_para_exibir`;
   `importar_lse.preparar`; `registry.carregar`), para a modularização avisar antes de quebrar.

## O que não muda
O ao vivo do WIN, o banco, a captura, as ordens e a tela. O prop_live importa o código do Dataframe de uma
**worktree fixa num commit**, nunca desta pasta, e nunca abre `data/database.duckdb`.
