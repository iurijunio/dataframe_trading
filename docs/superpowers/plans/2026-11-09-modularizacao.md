# Modularização do código — plano

Status: active

**Objetivo:** arquivos pequenos, de uma responsabilidade só, fáceis de achar e baratos de ler, sem mudar nenhum comportamento.

**Regra central:** nesta entrega o código **só muda de lugar**. Nenhuma função é reescrita, renomeada ou "melhorada" no mesmo commit. Melhoria que aparecer no caminho vira pendência em `docs/agentes/estado.md`.

## O que os números dizem (09/11/2026)

Leitura de código nas sessões do Claude: 18,7 milhões de caracteres.

| Arquivo | Linhas | Parte da leitura | Toca dinheiro? | Fase |
|---|---|---|---|---|
| `core/ordens.py` | 1.769 | 10,5% | **sim** | 3 |
| `captura.py` | 1.774 | 10,3% | **sim** | 3 |
| `core/papel.py` | 939 | 6,9% | **sim** (decide as ordens) | 3 |
| `ui/components/operacao_panel.py` | 1.536 | 5,3% | não | 1 |
| `ui/callbacks_operacao.py` | 1.050 | 4,8% | só repassa comandos | 1 |
| `ui/components/ordens_panel.py` | 1.236 | 4,6% | não | 1 |
| `ui/components/ao_vivo_panel.py` | 1.066 | 3,5% | não | 1 |
| `core/papel_leitura.py` | 1.343 | 3,4% | não (só leitura para a tela) | 1 |
| `ui/callbacks.py` | 2.924 | 2,8% | não | 1 |

**Ficam como estão:**
- `core/engine/*` e `strategies/*`: o `codigo_hash` e o motor ficam intocados; não há ganho que pague o risco.
- `core/wfa.py`, `ui/components/wfa_panel.py`, `ui/assets/busca.js`: quase nunca lidos.
- `ui/assets/style.css`: a ordem das regras muda o visual; só depois, com comparação de telas.
- `core/ao_vivo.py` e `ordens_real.py`: abaixo do teto ou perto dele.

**Ganho esperado, sem exagero:** os agentes já leem esses arquivos por trechos (cerca de 14 mil caracteres por leitura em `core/ordens.py` e `captura.py`). O ganho vem de achar o lugar certo de primeira, reler menos e carregar só a regra da área. A Fase 1 mede isso antes de a Fase 3 ser decidida.

## Fase 0 — Ferramentas de prova (nada do app muda)

1. **`scripts/provar_divisao.py --de <commit>`**, a prova de que nada mudou além do lugar. Compara, sem rodar o projeto:
   - cada função e método, pelo nome completo: árvore de sintaxe (AST) idêntica antes e depois; nenhum perdido, nenhum duplicado;
   - cada classe: mesmo conjunto de métodos e nenhum nome repetido entre as partes;
   - constantes de módulo: mesmas e num só lugar;
   - nomes indefinidos no arquivo novo (pyflakes);
   - alerta para `__file__`, `getLogger(__name__)` e `from x import y` de valor que muda: os três mudam de sentido ao trocar de arquivo.

   Testado com divisões de brinquedo e com defeitos plantados (função alterada, método perdido, nome indefinido). Tem de reprovar cada um.
2. **Teto de tamanho em `tests/test_regras_agentes.py`:** arquivo novo até 500 linhas. Os atuais acima disso ficam numa lista congelada que só pode diminuir.

## Fase 1 — Telas e leitura (fora do caminho da ordem)

Um arquivo por commit, nesta ordem (de maior ganho e menor risco):

1. `ui/components/operacao_panel.py` → pasta `ui/components/operacao/` (cabeçalho, cartões, tabelas, diário, gráfico).
2. `ui/callbacks_operacao.py` → leitura de dados, ações e `register`.
3. `ui/components/ordens_panel.py` → saúde e chamados, posições, diário, avaliação.
4. `ui/components/ao_vivo_panel.py` → lista de estratégias, ficha, contas.
5. `core/papel_leitura.py` → resumo, operações, comparativo, alertas.
6. `ui/callbacks.py` → `callbacks_menu`, `callbacks_mineracao`, `callbacks_wfa`, `callbacks_diagnostico`. O `register` tem 54 funções internas, mas só 6 usam outra função interna (`faixas`, `espaco`, `modo`, `_regiao_de_hoje`, `_wfa_montar`, `_matriz_guardada`): essas viram funções de módulo ou ficam juntas de quem as usa.

O caminho de import antigo continua funcionando (`from ui.components import operacao_panel`), reexportando os nomes. Testes não mudam.

**Portão de cada commit:** `provar_divisao` limpo → `test_callbacks_sem_ciclo` → `referencia_telas conferir` idêntico → suíte inteira → revisor. Conferência na tela com o app real fechado; merge com o ok do usuário.

**Fim da Fase 1:** atualizar `.claude/rules`, `docs/agentes/arquitetura.md` e `scripts/conferir.py`. Comparar o custo de leitura das sessões seguintes com a tabela acima e levar o resultado ao usuário.

## Fase 2 — Medir e decidir

Depois de algumas sessões de uso, o usuário decide com os números se a Fase 3 vale o risco.

Alternativa sem mexer em lógica nenhuma, que pode vir antes: um índice no topo de `core/ordens.py`, `captura.py` e `core/papel.py`, em comentário, dizendo o que há em cada seção. A árvore de sintaxe sai idêntica e o arquivo em execução não muda.

## Fase 3 — Código que envolve dinheiro (só com aprovação específica)

Um arquivo por vez, cada um com aprovação própria da divisão:

- **`core/papel.py`**: cálculo, gravação e conferência.
- **`captura.py`**: o `Servico` (1.504 linhas, 61 métodos) vira uma classe composta de partes (candles, papel e conferência, reconferência, ordens, retrato). O `captura.py` da raiz continua sendo o que o `captura.bat` abre, com `volta`, `rodar` e `main`.
- **`core/ordens.py`**: `planejar` e o `Motor` (1.226 linhas, 44 métodos) em pasta `core/ordens/` (planejar, passo, régua, entrar, proteger e sair, registros). `from core import ordens` continua igual.

**Pontos de atenção já identificados:**
- nenhum dos três usa `global`, e o `codigo_hash` só cobre `strategies/`: mover não altera hash de plano;
- `tests/test_ordens_motor.py:1052` troca `planejar` no módulo `ordens`: em outro arquivo, a troca deixa de valer. Só o alvo do teste muda; a verificação, não;
- `log = getLogger(__name__)` mudaria o nome do log: fixar o nome atual;
- `captura.py` roda como `__main__`: nada novo pode importar de volta dele.

**Portão, além do da Fase 1:**
1. Trabalho numa worktree, sem tocar no app em uso.
2. `tests/test_captura_processo.py`, `test_captura_ordens.py` e `test_ordens_*` idênticos, sem alterar verificação.
3. Foto do WIN e `gabarito_motor` idênticos.
4. Agentes `revisor` e `auditor` lendo só a prova e o diff.
5. **Merge só com o pregão fechado e o ok explícito do usuário.** Ele fecha as janelas Captura e Ordens real e reabre o `iniciar.bat`.
6. Marca no git antes do merge. Se algo estranhar: `git revert`, fechar as janelas e reabrir.
7. **Primeiro pregão acompanhado:** o usuário decide como quer rodar esse dia, e as conferências ordens × papel e ordens × backtest ficam de olho. O próximo arquivo só começa depois de um pregão limpo.
