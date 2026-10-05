# Projeto C/E, parte 4: ordens — decisões do brainstorming (rascunho)

> Decisões tomadas com o usuário em 02–05/10/2026. **Ainda não é a spec**:
> falta o rascunho visual das mudanças de tela (oferecido e adiado por
> limite de uso), escrever a spec completa, revisão por agente e plano.
> Herda da seção 1 §10, da parte 2 (captura) e da parte 3 (papel).

## Fatos levantados no MT5 (02/10/2026, só leitura)

- Conta demo Clear 1193398927 (`ClearInvestimentos-DEMO`): `margin_mode = 2` (**hedging**). Conta real também é hedging (usuário).
- `WIN$N` tem `trade_mode = 0` (não aceita ordem). Negociáveis: `WINV26` (vence ~14/10/2026) e `WINZ26`. `symbol_info("WIN$N").basis` vem vazio.
- Botão "Algo Trading" do terminal estava **desligado** (`terminal_info().trade_allowed = False`): precisa ligar para enviar ordens.

## Decisões

| # | Tema | Decisão |
|---|---|---|
| 1 | Tipo de conta | Hedging: cada variante tem a **própria posição**, identificada pelo magic number `7_000_000 + ligacao_id`. Sem contabilidade interna de netting. |
| 2 | Entrada | **Ordem a mercado** no primeiro segundo do candle seguinte ao sinal (o mesmo minuto em que o papel entra). |
| 3 | Stop/alvo | **Na corretora** (SL/TP no servidor) junto com a entrada; quando o papel move o stop (breakeven/stop móvel, `stop_fim`), a automação atualiza o SL; saídas que não são por preço (sinal, tempo, fechamento) por ordem a mercado no mesmo minuto em que o papel sai. |
| 4 | Automação fora do ar | Entrada **não sai atrasada**: se a ordem não sair até **30 s** após a abertura do candle, é perdida e registrada ("não executada: automação fora do ar"). Saída com posição aberta: sempre, assim que voltar, sem limite. |
| 5 | Divergência real × papel | **Avisar e congelar só aquela variante** (sem novas entradas até o usuário resolver); nunca abre posição sozinha; posição que sobrou → botões "Encerrar posição" × "Manter e acompanhar". Exceção esperada: SL/TP da corretora fechou antes do papel → só registra. |
| 6 | Limite de perda do dia da conta | Soma realizado + aberto de todas as variantes da conta. Ao chegar a **90% do limite**: **zera tudo e trava a conta até o pregão seguinte**. Antes de cada entrada: se perda do dia + stop da nova operação passar do limite, não entra (registra). |
| 7 | Contrato (rolagem) | Contrato = o negociável cujo último preço é **igual ao do `WIN$N`** (o mesmo que o papel olha); reserva: o de maior volume no dia anterior. Nunca opera no dia do vencimento (troca na véspera). Troca registrada no diário e mostrada na tela. |
| 8 | Fases | **papel → demo → real** (o "real mínimo" deixa de existir; migração: `real_minimo` → `real`). Papel roda sempre. Demo envia à conta demo do portfólio; real, à conta real. |
| 9 | Trava geral | Interruptor **"Envio de ordens" por conta**, começa **desligado**: desligado, a automação calcula e registra "ordem que seria enviada", sem enviar. |
| 10 | Contratos | O plano tem os contratos de referência (o papel usa sempre esses). Cada variante do portfólio ganha **"contratos na conta", separado para demo e para real**, padrão = plano, editável no cartão da variante (Ao vivo › Operação) e na ficha (Ao vivo › Estratégias); vale a partir da próxima operação; registrado no diário; ao editar mostra o custo de um stop contra o limite do dia da conta. Comparação sempre **por contrato e em pontos**. Não se edita na Mineração/WFA/Candidata. |
| 11 | Processos | **Uma automação por terminal** (um MT5 = uma conta logada). A captura (terminal da demo) grava candles e envia as ordens da demo. Conta real: segunda janela "Dataframe - Conta real" pelo `iniciar.bat`, só ordens, candles de um lugar só. **Nesta parte: demo completa; real desenhada e pronta, mas ligada só depois que a demo rodar bem.** |
| 12 | Pausar com posição aberta | Pausar variante, desligar portfólio ou desligar "Envio de ordens" com posição aberta **encerra na hora** (a mercado), com aviso "isso encerra N posição(ões) aberta(s)" e dois cliques. |

## Mudanças de tela previstas (rascunho visual pendente)

- Ao vivo › Operação: coluna Demo do comparativo preenchida (derrapagem, atraso, sinal no mesmo minuto, rejeitadas); "contratos na conta" editável no cartão; avisos de divergência com "Encerrar posição" / "Manter e acompanhar"; contrato em uso; selo "conta travada no limite".
- Contas (Ao vivo › Estratégias, futuramente aba **Conta**): interruptor "Envio de ordens".

## Próximos passos

1. Rascunho visual das mudanças de tela (oferecer ao usuário).
2. Spec completa `docs/superpowers/specs/YYYY-MM-DD-ao-vivo-ordens-design.md` a partir desta tabela + revisão por agente contra o código.
3. Plano de implementação e execução com revisão por tarefa (como as partes 2 e 3).
