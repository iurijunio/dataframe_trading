---
paths:
  - "ordens_real.py"
  - "captura.py"
  - "core/ordens.py"
  - "core/corretora.py"
  - "core/ordem_teste.py"
  - "core/ponte.py"
  - "core/comandos.py"
  - "core/diario_ordens.py"
  - "core/papel_vivo.py"
  - "core/conferencia_ordens.py"
  - "core/ordens_backtest.py"
  - "core/ao_vivo.py"
  - "core/mt5_source.py"
  - "ui/callbacks_ordens.py"
  - "ui/callbacks_ao_vivo.py"
  - "ui/components/ordens_panel.py"
  - "ui/components/ordens/**"
  - "ui/components/ao_vivo_panel.py"
  - "ui/components/ao_vivo/**"
  - "core/diario.py"
  - "core/db_manager.py"
  - "core/schema.sql"
  - "iniciar.bat"
  - "captura.bat"
  - "ordens_real.bat"
---
# Ordens e conta real

- **Toda ordem errada é dinheiro.** Antes de usar a API do MetaTrader 5 (`order_send`, `positions_get`, filling,
  retcodes, `symbol_info`), confira a documentação oficial (mql5.com/en/docs, mql5.com/en/docs/python_metatrader5)
  e cite o que conferiu; o que ela não garante, trate como incerto e proteja.
- **Vigia de stop e alvo:** o papel sai no toque, no candle em formação. A corretora tem 1 s para executar o tocado;
  depois a automação sai a mercado e abre chamado. Execução sem negócio naquele preço sai marcada "fora do mercado".

## Ordens na demo (parte 4; `core/corretora.py`, `ordens.py`, `papel_vivo.py`)

- **Barra provisória:** o minuto em formação vale para sinal, nunca para
  stop/alvo/indicador; stop e alvo da entrada vêm da vela fechada até o minuto
  anterior (`0dfa0db`, `engine.VERSAO` 2026.10.09 — fecha o look-ahead do
  M1+ATR). Saída forçada na provisória fica aberta.
- **O caminho da ordem nunca espera o banco:** papel vivo e decisão saem da
  memória e do `estado.json`; o evento vai primeiro ao `.jsonl` (`fsync`) e
  ao banco só quando ele estiver livre.
- **Desejado "indisponível" = não fazer nada, não zerar:** dado velho ou
  cálculo faltando não fecha posição aberta.
- **Retornos do MT5: tabela única** em `core/corretora.py`, testada linha a
  linha. INCERTA (10012, e `None`) pode ter executado: adotar/conferir antes
  de reenviar. ACEITA (10008, PLACED) é recebida, o negócio vem depois.
  10036 é "já saiu", não falha.
- **Filling por máscara:** `SYMBOL_FILLING_MODE` é máscara (FOK=1, IOC=2), não
  o valor de `ORDER_FILLING_*` (FOK 0, IOC 1, RETURN 2); em bolsa, RETURN vale
  como último recurso.
- **`None` do MT5 só se entende com `last_error()`:** sem erro (1) é "nenhuma
  resposta", não falha de configuração.
- **Conta travada pelo limite de perda vale até o próximo pregão, sem botão
  de destravar** (evento `conta_travada`, sobrevive a reinício).
- **"Desligar envio" grava o comando antes de tocar no banco** (e o envio
  vai junto no comando); banco ocupado não pode segurar o desligamento.
- **Limite de perda vazio não se grava com Envio ligado**, e limite vazio
  não desliga o envio sozinho.
- Envio nasce **desligado** (`contas.envio_ligado`) e registra "seria enviada".
  O ensaio passa o MESMO pedido pelo `order_check` (nunca envia; retcode 0
  = passou) e grava `retcode`/`comment` (ou `last_error`); a tela mostra
  "seria recusada: …".
- **Foto parcial:** posições e ordens lidas, mas histórico/negócios/conta
  falharam → só sair e proteger (nada de entrar, adotar, perdida nem
  "saiu antes"). Sem conta legível vale a da mesma conexão. Foto incompleta
  > 30 s no pregão (ou ilegível com posição aberta) → chamado `sem_leitura`.
  Exceção à "só proteger": a candidata ÚNICA da entrada sem resposta, sem SL,
  recebe o stop/alvo do `enviando` que a abriu (nunca o do papel), sem ser
  adotada, e com o stop recusado > 2 s encerra como na foto completa; duas
  candidatas ou envio sem stop → chamado `sem_stop` (`_orfa_na_parcial`).
- **"Zerar tudo" de outro dia** (clicado fora do pregão sem posição, lido na
  manhã seguinte) é descartado no diário — não desliga o envio de hoje.
- **Retrato salvo** (`data/ao_vivo/ordens/retrato.json`, escrita atômica):
  subida com o banco preso usa o último retrato, marcado antigo — protege e
  sai por comando/trava, nada entra.
- **Ordem de teste** (`core/ordem_teste.py`; **o botão está fora da tela**, o
  motor, o comando e o Diário continuam — dá para religar depois; ver
  `git diff 421cc4f..be5ba7f -- ui/`; o botão "Teste" da conta real também
  saiu da tela — engine mantido; ver git 6ceaa18 para trazê-lo de volta):
  comando `ordem_teste` que a captura executa depois das ações das
  estratégias, uma etapa por volta, sem `sleep` (compra 1 · SL/TP a 100 pts
  · confere · 10 s no monotônico · sai pelo ticket). Magic `MAGIC_TESTE` =
  7.000.000, fora da faixa das ligações: planejar/adoção/zerar/Encerrar
  nunca a tocam; só ela encerra a sua (inclusive a que sobrou de um
  reinício). Recusa sem `account_info().trade_mode` ==
  `ACCOUNT_TRADE_MODE_DEMO`, conta cadastrada demo, pregão, Algo, trava,
  contrato/guarda, Zerar ou pedido > 60 s; independe do Envio. Saída
  recusada > 10 s → chamado `teste_preso`. 10008 e passageiras não são
  falha (passageira: de novo a cada 1 s, até 5 s); fora do pregão e fora da
  conta DEMO o encerramento não reenvia.
- "Saiu antes" só para ticket que a própria automação não encerrou; a
  entrada sem resposta só casa com negócio depois do 1º envio da operação
  e nunca com ticket de outra operação.

## Conta real (parte 5; `ordens_real.py`, `core/ponte.py`, `core/comandos.py`)

- **Um terminal MT5 por processo.** A captura e a Ordens real têm cada uma o
  seu `mt5.initialize(path=…)`; nunca trocar de conta dentro do mesmo processo.
- **A captura só abre o terminal da conta DEMO**; a real só abre o da conta
  real, pelo caminho cadastrado em `contas.terminal`.
- **O tipo da conta é conferido a cada volta** (login e `trade_mode`: DEMO na
  captura, REAL na real). Conta errada = chamado `conta_errada`, nada sai.
- **Ponte `data/ao_vivo/desejados.json`:** escrita atômica, com batimento
  (`vivo_em`) em toda volta da captura. A real só age com desejado de até 5 s
  (senão é indisponível: só protege).
- **Ack `ack_real.json` de até 200 ms:** a demo espera a real tratar um `seq`
  novo só quando o processo da real está vivo; sem ele a demo segue sem esperar.
- **Pastas de comando por conta:** `data/ao_vivo/comandos` (demo) e
  `data/ao_vivo/comandos_real` (real). Cada processo lê só a sua.
- **`zerar_tudo` vai para as duas pastas**, sem ler o banco.
- **`ordens_eventos.origem`** (`demo` ou `real`): todo leitor de eventos filtra
  por origem. Quem espelha a real no banco é a captura, nunca o processo da real.
- **Ordem de teste na conta do processo** (demo ou real, liberada na real em 21/10/2026): botão fora da tela desde 21/10 (motor mantido; para religar veja o commit 6ceaa18); confere login, tipo cadastrado e trade_mode do MT5 antes de enviar; não depende do Envio.
- **Dado protegido:** `data/ao_vivo/ordens/real/*.jsonl` nunca se apaga (é o
  diário write-ahead da conta real, como o da demo).
- **Ordens × papel no mesmo dia** (`core/conferencia_ordens.py`, desde
  05/11/2026): a cada papel gravado a captura compara os desejados com ele,
  só com o MESMO minuto de barras (`captura._momento`). Divergência em 3
  minutos de barra distintos, sem igualdade no meio, abre o chamado
  `divergencia_papel`; fecha quando volta a bater. Só avisa, nunca mexe em ordem.
- **Ordens × backtest** (`core/ordens_backtest.py`, tabela `ordens_backtest`):
  na manhã, só pregão encerrado; por origem; todo dia na fase da conta e ligada,
  também sem ordem (= deixou de entrar) se a conta tem prova de vida no dia (`rolagem`, que a real também grava); fora: ensaio, sem dados. Diferença
  do código/motor de hoje barra a promoção, como a do papel.

O `iniciar.bat` abre **três** janelas: **Dataframe - Captura** (`captura.bat`),
**Dataframe - Ordens real** (`ordens_real.bat`) e a do app. Se mudou
`core/ordens.py`, `core/corretora.py`, `core/papel_vivo.py`, `core/ponte.py`
ou `ordens_real.py`, feche **as duas** janelas (Captura e Ordens real) antes
de reabrir o `iniciar.bat`, pelo mesmo motivo da trava.
