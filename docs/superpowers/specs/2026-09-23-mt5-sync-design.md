# Projeto B: sincronização automática com o MT5

> Faz parte dos "cinco projetos" descritos em
> [PLANO-CANDIDATA.md](../../PLANO-CANDIDATA.md) §11. B é só infraestrutura:
> trocar a exportação manual do CSV pela API do MT5, alimentando a mesma
> base (`database.duckdb`) de sempre. Captura de sinal ao vivo (demo/real) e
> a tela de conferência lado a lado são o projeto **C**, que vem depois
> deste, como projeto separado.

Desenhado em 22/09/2026.

## 1. O problema

Hoje a base histórica (`data/database.duckdb`) só cresce quando alguém
exporta manualmente um CSV do MT5 (`Ferramentas → Exportar histórico`) e
roda `cli.py ingest`. É um passo manual, fácil de esquecer, e cada dia sem
rodar é um dia de pregão que a base não tem.

## 2. Escopo desta versão

**Só o `WIN$N`, automatizando exatamente o que `cli.py ingest` já faz
manualmente hoje.** Ações, os parquets de índices futuros internacionais
(londonstrategicedge) e uma tela genérica de importar/excluir/unificar
ativo ficam **fora** — são o próximo projeto, depois que a segunda fonte de
dados de verdade entrar. Generalizar antes disso é resolver um problema que
ainda não existe.

## 3. Decisões travadas (22/09/2026)

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Como disparar a sincronização? | **Botão na tela do Dash**, perto do seletor de ativo — não linha de comando, não agendador. |
| 2 | Qual janela buscar no MT5? | **Do último candle salvo até agora, com folga de 5 dias corridos** (cobre fim de semana e feriados) — cobre barra que o corretor revisou depois de fechada, e a lógica de conflito existente (mais recente vence) resolve. Constante em código, não campo na tela. |
| 3 | Como integrar com a ingestão que já existe? | **Reaproveitar 100%**: gerar um TSV no mesmo formato da exportação manual e chamar `ing.ingest_csv()` sem alterá-la. Nada de lógica de merge nova. |
| 4 | Como testar? | Lógica (montar range, escrever TSV) testada com barras falsas. A conexão real com o MT5 é conferência manual na tela, com o terminal aberto e logado — não dá para automatizar em CI o que depende do terminal Windows rodando. |

## 4. Arquitetura

```
MT5 (terminal aberto, logado)
   │  mt5.copy_rates_range(...)
   ▼
core/mt5_source.py           ← módulo novo, nada de Dash
   │  escreve TSV no formato <DATE> <TIME> <OPEN> ... (mesmo da exportação manual)
   ▼
data/raw/mt5_sync_AAAAMMDD_HHMMSS.tsv
   │
   ▼
ing.ingest_csv()             ← já existe, sem alterar
   │
   ▼
database.duckdb  (+ trading_days, rollovers, espelho Parquet — reconstrução
                   igual à do cmd_ingest de hoje)
```

O botão no Dash chama `core.mt5_source.sincronizar(...)` a partir de
`ui/callbacks.py` (o único lugar autorizado a tocar Dash + `core/`); o
módulo `core/mt5_source.py` em si não importa Dash, seguindo a mesma regra
do resto do `core/`.

## 5. Componentes

### `core/mt5_source.py` (novo)

```python
def conectar() -> None
    # mt5.initialize(); erro claro se terminal fechado/sem login

def offset_servidor(symbol: str) -> timedelta
    # calibra o fuso do broker: symbol_info_tick(symbol).time (epoch, hora do
    # servidor) contra datetime.now(timezone.utc) agora. O MT5 guarda tudo em
    # UTC puro, mas o servidor do corretor pode estar em outro fuso — sem
    # calibrar, o range buscado erra por horas.

def buscar_barras(symbol: str, desde: datetime, ate: datetime) -> pl.DataFrame
    # symbol_select(symbol) antes de qualquer busca — sem isso o MT5 pode
    # devolver vazio SEM erro nenhum (pegadinha confirmada no fórum oficial:
    # mql5.com/en/forum/369602). Checa explicitamente se voltou vazio e avisa.
    # mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, desde_utc, ate_utc)

def exportar_tsv(barras: pl.DataFrame, destino: Path) -> None
    # grava <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>
    # formato %Y.%m.%d / %H:%M:%S — o mesmo que ing.read_mt5_export espera

def sincronizar(con, symbol: str, price_decimals: int) -> ing.IngestResult
    # 1. lê o último ts salvo (SELECT max(ts) FROM bars_m1 WHERE symbol = ?)
    # 2. desde = último ts - 5 dias corridos de folga;
    #    sem nenhuma barra salva, recusa com um erro claro em vez de
    #    adivinhar uma data de início (WIN$N já tem base desde 2021 — este
    #    caso só apareceria com um símbolo novo, fora do escopo aqui)
    # 3. ate = agora
    # 4. busca no MT5, grava TSV em data/raw/mt5_sync_<timestamp>.tsv
    # 5. chama ing.ingest_csv(con, path, symbol, price_decimals)
    # 6. reconstrói trading_days e rollovers, reexporta Parquet
    #    (mesmos passos de cmd_ingest em cli.py)
    # 7. devolve o IngestResult para a tela mostrar o resumo
```

### UI (`ui/callbacks.py` + componente de layout)

- Botão "Sincronizar com MT5" perto do seletor de ativo no topo.
- Ao clicar: roda `sincronizar`, mostra um resumo (período buscado, linhas
  inseridas, divergências, dias reconstruídos) — o mesmo texto que
  `IngestResult.summary()` já produz hoje no terminal, só que num bloco na
  tela em vez de print.
- Estados de erro tratados na tela, em português simples: terminal fechado,
  sem login, símbolo não encontrado — nunca uma stack trace crua.

## 6. Fuso horário — o ponto delicado

O MT5 guarda `ts` sempre em UTC, sem shift. O `database.duckdb` de hoje
guarda os horários **como o MT5 exportou** (hora do corretor, sem conversão
— é assim que a base atual já funciona, calibrada pela planilha manual).
`offset_servidor` existe para que o range pedido ao MT5 (`desde`/`ate`)
corresponda à mesma hora de corretor que já está salva — **não** para
converter os dados recebidos, que devem sair da API já no fuso do corretor
(o próprio MT5 devolve os horários no fuso do terminal/corretor quando a
consulta é feita certa). Se a calibração mostrar um offset inesperado (não
múltiplo de hora), a sincronização para e avisa, em vez de gravar hora
errada silenciosamente.

## 7. O que fica de fora (próximo projeto)

- Ações e os parquets de índices futuros internacionais (londonstrategicedge).
- Tela de importar/excluir/unificar ativo, com validações — só faz sentido
  desenhada quando a segunda fonte de dados realmente existir.
- Agendamento automático (cron/agendador do Windows) — pode entrar depois
  se o botão manual se provar repetitivo demais.
- Captura de sinal ao vivo (demo/real) e a tela de comparação com o
  walk-forward — **projeto C**, muda o assunto de "manter a base histórica"
  para "gravar o que o robô faria agora".

## 8. Testes

| alvo | o que prova |
|---|---|
| `exportar_tsv` | o TSV gerado tem exatamente as colunas e o formato que `ing.read_mt5_export` espera — roundtrip: gera com `exportar_tsv`, lê de volta com `ing.read_mt5_export`, confere que bate |
| `sincronizar` (com `buscar_barras` trocado por um fake) | calcula a janela certa (último ts − folga até agora), sem nenhuma barra salva não inventa uma data de início, chama `ing.ingest_csv` com o arquivo certo |
| `offset_servidor` (com `mt5` trocado por um fake) | calibra corretamente; recusa (com motivo) um offset que não é múltiplo de hora |
| conferência manual, com o MT5 de verdade | terminal aberto e logado, símbolo `WIN$N` selecionado, clicar no botão e comparar o resumo com o que `cmd_ingest` mostraria para o mesmo período |

Nunca tocar `data/database.duckdb` real nos testes automatizados — banco
temporário, como o resto da suíte.
