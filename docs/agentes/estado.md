# Estado do projeto — documentos e pendências

> Parte do `AGENTS.md`. Leia quando a tarefa for retomar uma entrega, escolher
> o próximo passo ou saber qual documento confiar. Atualize ao fim de cada entrega.

## Documentos: qual confiar

| Documento | Estado (04/11/2026) |
|---|---|
| `docs/superpowers/specs/2026-11-03-busca-automatica-design.md` + `plans/2026-11-03-busca-automatica.md` (+ protótipo `2026-11-03-busca-automatica/layout-b.html`, contrato visual) | busca automática por nichos — implementada, tudo no `master`; a seção 3 da spec ficou velha, vale "Estado depois da implementação (04/11/2026)" |
| `docs/superpowers/specs/2026-11-01-menu-e-mineracao-design.md` + `plans/2026-11-01-menu-e-mineracao.md` | redesenho do menu e Backtest dentro da Mineração — implementado, no `master` |
| `docs/superpowers/specs/*` e `plans/*` | desenho de cada entrega recente — **fonte mais confiável** do porquê |
| `docs/CALCULOS-WFA.md`, `docs/CALCULOS-CANDIDATA.md` | como cada número é calculado — confiável |
| `docs/PLANO*.md`, `docs/EXECUCAO-CANDIDATA-*.md` | histórico de decisões; planos já executados |
| `docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md` | spec da parte 4 (ordens) — implementada; o `...-ordens-decisoes.md` é o rascunho que a originou |
| `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` + `plans/2026-10-28-ativos-cme-etapa1.md`, `2026-10-29-ativos-cme-etapa2.md`, `2026-10-30-ativos-cme-etapa4.md` | ativos da CME; as seções "Herança da etapa 1", "Estado depois da etapa 2", "Estado depois da etapa 3" e "Estado depois da etapa 4" dizem o que ficou |
| `CHANGELOG.md` | atualizado até a busca automática e a camada 4 nela (04/11/2026); **não cobre variantes, portfólio nem gatilho** |
| `README.md` | atualizado até a busca automática (04/11/2026); o texto do MVP segue como história |
| `docs/METODOLOGIA.md` "Estado da plataforma" | atualizado em 04/11/2026 |

Na dúvida entre documento e código, o código manda. Use o agente
`documentador` para pôr a documentação em dia depois de uma entrega.

## Onde estamos

No `master`: Candidata, MT5, Portfólio (identidade, correlação, selo de reotimização), Ao vivo partes 1 a 5 (captura,
papel, ordens na demo, conta real, vigia de stop e alvo), ativos da CME só na pesquisa (etapas 1 a 4, sem corretora
para operar), redesenho do menu, Busca automática, conferências ordens × papel e ordens × backtest (05/11/2026) e
promoção direta para a fase real (06/11/2026).

Há estratégias na **conta real**: fase, contratos e Envio de cada uma estão na ficha da tela (o banco é a fonte, não
este arquivo). O histórico de cada entrega está no `CHANGELOG.md`, em "Histórico da plataforma".

Entrega futura: aba **Conta** no topo (nome escolhido pelo usuário; nunca "Mesa"), com controle e visão por conta e
ativo. Ainda sem spec. Recursos com LLM só fora do caminho da ordem.

## Pendências

- **"Período do canal" (relato do usuário):** depois de "Minerar a região", o usuário editou a faixa para 3 a 20 e
  a mineração rodou com a faixa herdada da busca. Não reproduzido; reproduzir com o app real fechado.
- **Conferir na tela:** promoção "Promover para real" e aviso flutuante (`e35a009`), com o app real fechado.
- **Erro React #31 (2 vezes) ao abrir o app:** objeto `{props, type, namespace}` como filho; causa desconhecida.
- `scripts/campos_menu.py conferir` já falhava antes da busca (só rótulos; `tests/test_campos_menu.py` passa).
- Dúvida: o aquecimento curto do papel vivo pode divergir do backtest de histórico inteiro? Menu sem acompanhar o
  ativo de mineração restaurada após F5.
- Pendências pequenas da CME: "Estado depois da etapa 2" e "Estado depois da etapa 3" da spec.
- **Alvo "só encostado"** (anotado em 19/10): o preço toca o alvo e não passa;
  o papel conta alvo, mas a TP limitada da corretora fica na fila e não
  executa. Falta (a) medir no histórico dos planos quantas saídas por alvo
  foram só toque e quanto pesam; (b) decidir a regra — backtest exigir passar
  1 tick e/ou manter a TP por até N min e sair a mercado se afastar X ticks.
- **Limpezas pequenas, sem efeito na tela:** `MOTIVO_CAPTURA` em
  `ui/components/pregao_panel.py` não é usado; `ui/components/catalogo.py`
  ainda lista o trailing em "Proteções" (o menu novo o pôs em Saída);
  `State("mine-carregar")` sem uso em callback da Mineração; o teste de
  mineração salva do redesenho é trivial.
- **Gatilho, fatia 2**: avisar na tela de Portfólio que a correlação/risco
  estão desatualizados porque o plano ativo de uma variante membro mudou.
  Descrito como fora de escopo em `docs/superpowers/specs/2026-09-24-gatilho-reotimizacao-design.md §8`
  — ainda **não tem spec própria**; começar pelo brainstorming.
