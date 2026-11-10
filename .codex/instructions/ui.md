---
paths:
  - "ui/**"
---
# Tela

- **Texto:** título curto, sem subtítulo nem frase explicativa visível. Explicação só no (?) (`dica` em
  `ui/components/cartao.py`); nunca remova um (?) que já existe.
- **Protótipo aprovado é contrato:** sai igual, medidas inclusive. Não caber = pare e pergunte, mostrando a
  alternativa. Função existente que o protótipo não mostrou fica, encaixada no visual. Compare por prints.
- Para tela nova ou confusa, use o agente `ui-designer`; mantenha o sistema visual existente. Não dependa de skills de plugins ausentes.
- **Cópia do app abre o banco real com escrita:** só com o app real fechado (um hook recusa com o app aberto).
  Com ele aberto, confira por testes e deixe a tela para depois. Reclamação do visual logo após uma entrega:
  pergunte primeiro se o usuário já reabriu o `iniciar.bat`.

**Conferir na tela contra o banco real** (`data/database.duckdb`) é
obrigatório para mudança de UI. Cuidado: um clique ou rolagem errada num
campo numérico altera dado real — anote o valor antes e restaure depois.

Depois de qualquer mudança de tela, avise em destaque: **feche e abra o
`iniciar.bat`** — o app aberto não carrega código nem CSS novos.

- **Nunca passe dicionário (ou qualquer coisa que não seja componente) como
  filho de `html.*`.** O Dash 4 falha ao desenhar e, em silêncio, devolve o
  estado de OUTROS componentes: o menu e as sub-telas voltavam sozinhos para
  a aba anterior (`421cc4f`: o cabeçalho da Operação recebeu o `contrato_dia`
  inteiro). Trocar para `dcc.Tabs` (`47b00bb`) não era o problema e foi
  revertido (`d0d180b`). Formate o texto antes de pôr na tela.
- **Campo numérico:** `<input type=number>` focado muda de valor com a rolagem do
  mouse (bug do Chrome). Use `type="text"` + `inputMode="numeric"` + parse manual;
  `ui/assets/num_input.js` protege o resto do app.
- **Dinheiro na tela: sempre `cartao.dinheiro(v, moeda)`**, com a moeda de
  `ativo.moeda_de(simbolo)`. Componentes recebem `moeda="BRL"` como padrão.
- **Mexeu em tela da pesquisa? Rode `scripts/referencia_telas.py conferir`**
  (obrigatório; o WIN tem de dar idêntico). Só regrave a referência a partir
  do código de antes da mudança.
- **Ids de rótulo de moeda: um `type` por tela** (`moeda-c4`, `moeda-cand`).
- **Textos de (?) de layout fixo ficam em R$** (lista na spec, "Estado depois
  da etapa 3"); não tente trocar um por um.
