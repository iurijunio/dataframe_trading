# Parte 4 — Ordens na conta demo: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A captura passa a enviar à conta demo do MT5, no primeiro segundo do minuto, as mesmas operações do papel, reconciliando papel × corretora a cada volta, com todas as falhas da spec cobertas por teste.

**Architecture:** Três camadas novas, todas em `core/` e testáveis com MT5 falso: `corretora.py` (retornos, pedidos, fotografia da conta — sem decidir nada), `ordens.py` (desejado × corretora → ações, e o executor) e `papel_vivo.py` (retrato da configuração, aquecimento em memória e o papel com a barra provisória, sem banco no caminho). O diário de ordens é escrita adiantada em arquivo (`diario_ordens.py`) com espelho no banco. A captura (`captura.py`) chama tudo antes de gravar no banco. A tela lê o `estado.json` e o espelho.

**Tech Stack:** Python 3.12, numpy/numba (motor existente), polars, DuckDB, Dash, pacote `MetaTrader5` 5.0.6180, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md` (rev. 2 + D1–D4 aprovadas). Decisões: `docs/superpowers/specs/2026-10-05-ao-vivo-ordens-decisoes.md`.

## Global Constraints

- **Nunca** editar `ui/components/controls.py`, `ui/components/wfa_matriz.py`, `strategies/rompimento_abertura.py`.
- **Nenhum teste fala com MT5 de verdade nem envia ordem.** Nenhum teste toca `data/database.duckdb` (`tests/conftest.py` já isola; use a fixture `base` como em `tests/test_captura_processo.py`).
- **Antes de usar qualquer função do MetaTrader5, conferir na documentação oficial** (`https://www.mql5.com/en/docs/python_metatrader5` e `https://www.mql5.com/en/docs/constants`) e citar a URL no relatório da tarefa. Já conferido (spec §6.5): `order_send`, filling (máscara FOK=1, IOC=2; RETURN sempre vale em execução em bolsa), códigos 10004–10046, `positions_get`, `history_deals_get`, `orders_get`, `order_check` (sucesso = `retcode 0`). **`None` em `positions_get`/`orders_get`/`history_deals_get` é erro** — exceto se `last_error()[0] == 1` (RES_S_OK), quando vale como lista vazia (a documentação não garante o vazio).
- Constantes do pacote conferidas (5.0.6180): `TRADE_ACTION_DEAL=1`, `TRADE_ACTION_SLTP=6`, `TRADE_ACTION_REMOVE=8`, `ORDER_TYPE_BUY=0/SELL=1`, `ORDER_FILLING_FOK=0/IOC=1/RETURN=2`, `ORDER_TIME_GTC=0`, `POSITION_TYPE_BUY=0/SELL=1`, `DEAL_ENTRY_IN=0/OUT=1`, `DEAL_REASON_SL=4/TP=5`, `ACCOUNT_MARGIN_MODE_RETAIL_HEDGING=2`, `SYMBOL_TRADE_MODE_FULL=4`. **`SYMBOL_FILLING_*` não existe no pacote** (use 1 e 2). `TRADE_RETCODE_HEDGE_PROHIBITED` não existe no pacote: a tabela de retornos usa números.
- Magic da ligação: `7_000_000 + ligacao_id`. Chave de uma operação: `(ligacao_id, entry_ts)`.
- Janelas: entrada até **30 s** da abertura do minuto de entrada; saída pendente vira chamado após **120 s**; sem entrada nos **5 s** após (re)conectar; papel indisponível > **180 s** no pregão = chamado; trava a **90%** do limite; teto D1 = **1,5×** a distância de stop do plano; guarda de preço = **2 ticks** por **60 s**. Todo tempo de janela usa o relógio do servidor (`RelogioServidor`).
- Volta rápida: **0,1 s** entre os segundos 58 e 10 do minuto (servidor), no pregão; 1 s no resto.
- Derrapagem sempre em **ticks** na tela (1 tick = 5 pts no WIN). Textos de tela em português, sem jargão; toda métrica nova com (?) de faixa boa/ruim.
- Código, nomes e comentários em português; comentário explica **por quê**. Nada em `core/` importa Dash.
- Git: `git add` por caminho; mensagem multi-linha via arquivo e `git commit -F`; **não fazer push**. Commit termina com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Backup do banco antes de rodar o app com o schema novo (Tarefa 1).
- Mudança de impacto: teste falhando → mínimo → passando → mutação (agente `mutacao`) nos módulos `core/corretora.py`, `core/ordens.py`, `core/papel_vivo.py`, e a função `papel.com_barra_provisoria`.
- Rodar `tests/test_callbacks_sem_ciclo.py` sempre que mexer em Inputs/Outputs de callback.
- **Ordem de execução das tarefas: 1, 3, 2, 4, 5, …** (a Tarefa 2 usa o `tests/mt5_falso.py` da 3).
- **Entrada sem SL/TP na ordem a mercado.** A documentação de `MqlTradeRequest` (mql5.com/en/docs/constants/structures/mqltraderequest) lista para execução em bolsa só `action, symbol, volume, type, type_filling` — não garante `sl`/`tp`. A entrada vai sem eles e a proteção sai em `TRADE_ACTION_SLTP` (campos obrigatórios: `action, symbol, sl, tp, position`) **na mesma volta**; recusa passageira → tenta a cada volta; posição sem proteção há mais de **2 s** depois de executada → encerra.
- **Classe `INCERTA`** para `None` e `TIMEOUT` (10012): a ordem pode ter executado. Nunca reenviar antes de **3 s**, e só se `history_orders_get` (desde a entrada, com o magic) não tiver ordem dessa operação.
- **Intervalo mínimo de 1 s** entre tentativas da mesma ação (entrada da mesma operação, saída do mesmo ticket, proteção do mesmo ticket) — senão a volta de 0,1 s provoca o próprio "pedidos demais" (10024).
- **`deviation` = `slippage_ticks` do plano × tick + 2 × tick** (em pontos).
- **Toda pasta que a captura lê (`data/ao_vivo/comandos`, `data/ao_vivo/ordens`) é constante de módulo e o `tests/conftest.py` autouse a desvia para `tmp_path`** — um teste não pode escrever um comando que a captura real do usuário consumiria.
- **Um erro no caminho das ordens nunca para a captura**: `_ordens` com `try/except` (log + `ordens_estado = {"erro": …}` + chamado `ordens_falhou`), e dentro do `Motor.passo` as entradas isoladas das saídas (falha nas entradas não impede as saídas).
- **Risco conhecido fora desta parte:** em M1 com stop/alvo por ATR o motor usa o ATR da própria barra de entrada (`execution.py:181` + `kernel.py:174`) — vale para o backtest também. Até a correção do motor (parte própria, decisão do usuário), `mudar_fase` recusa promover para demo plano em M1 com stop ou alvo ATR (Tarefa 12).

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `core/schema.sql` (mod.) | colunas `envio_ligado`, `contratos_demo/_real`; tabelas `ordens_eventos`, `papel_backtest`; migração `real_minimo` |
| `core/diario.py` (mod.) | tipos novos de evento |
| `core/corretora.py` (novo) | tabela de retornos, preenchimento, arredondamento ao tick, pedidos, fotografia da conta |
| `tests/mt5_falso.py` (novo) | MT5 falso de ordens (posições, ordens, negócios, roteiro de retornos) |
| `core/diario_ordens.py` (novo) | escrita adiantada em `data/ao_vivo/ordens/AAAA-MM-DD.jsonl`, estado derivado, espelho no banco |
| `core/papel.py` (mod.) | `com_barra_provisoria`; `preparar_dia` extraído de `rodar_dia`; parâmetro `provisoria` |
| `core/papel_vivo.py` (novo) | retrato da configuração, aquecimento em memória, desejado por ligação |
| `core/ordens.py` (novo) | `planejar` (desejado × corretora → ações) e `Motor` (executa, trava, chamados, estado) |
| `core/contrato_dia.py` (novo) | contrato do dia, vencimento, guarda de preço |
| `core/comandos.py` (novo) | comandos da tela para a captura por arquivo atômico |
| `core/papel_backtest.py` (novo) | conferência diária papel × backtest |
| `core/ao_vivo.py` (mod.) | promover/voltar fase, contratos da conta, Envio de ordens |
| `captura.py` (mod.) | volta rápida, papel vivo + motor antes do banco, estado `ordens` |
| `ui/data.py`, `ui/app.py`, `ui/callbacks_ordens.py` (novo), `ui/components/ordens_panel.py` (novo), `ui/assets/alarme.js` (novo), `ui/components/operacao_panel.py`, `ui/callbacks_operacao.py`, `ui/components/ao_vivo_panel.py`, `ui/callbacks_ao_vivo.py` (mod.) | tela |
| `AGENTS.md`, `CHANGELOG.md` (mod.) | documentação |

---

### Task 1: Schema e tipos do diário

**Files:**
- Modify: `core/schema.sql` (fim da seção "ao vivo", depois da linha `ALTER TABLE papel_pregoes ADD COLUMN IF NOT EXISTS falha VARCHAR;`)
- Modify: `core/diario.py:15-22` (`TIPOS`)
- Test: `tests/test_schema_ordens.py`

**Interfaces:**
- Produces: colunas `contas.envio_ligado`, `portfolio_membros.contratos_demo`, `portfolio_membros.contratos_real`; tabelas `ordens_eventos(evento_id VARCHAR PK, quando, tipo, conta_id, ligacao_id, entry_ts, lado, contratos, simbolo, ticket, retcode, preco_papel, preco, atraso_ms, tentativa, motivo, dados JSON)` e `papel_backtest(ligacao_id, dia, conferido_em, ok, n_papel, n_backtest, diferencas JSON, PK(ligacao_id, dia))`; tipos de diário `contratos_alterados`, `envio_ligado`, `envio_desligado`.

- [ ] **Step 0: Backup do banco real** (antes de qualquer subida do app com o schema novo):

```powershell
$d = "C:\Users\mrRobot\Documents\Neturna\backups\2026-10-09-antes-ordens"; New-Item -ItemType Directory -Force $d | Out-Null; Copy-Item data\database.duckdb* $d\
```
Se a captura estiver aberta, peça ao usuário para fechá-la antes (o arquivo fica travado).

- [ ] **Step 1: Teste falhando** — `tests/test_schema_ordens.py`:

```python
"""Schema da parte 4: colunas e tabelas das ordens, e a migração da fase."""
from datetime import datetime

from core import db_manager as db
from core import diario


def _con():
    con = db.connect_write()
    db.init_schema(con)
    return con


def test_colunas_novas_e_padroes():
    with _con() as con:
        con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em) "
                    "VALUES (1, 'demo', 'demo', ?)", [datetime(2026, 10, 9)])
        assert con.execute("SELECT envio_ligado FROM contas").fetchone()[0] is False
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'portfolio_membros'").fetchall()}
        assert {"contratos_demo", "contratos_real"} <= cols


def test_tabelas_novas_existem():
    with _con() as con:
        for t in ("ordens_eventos", "papel_backtest"):
            assert con.execute("SELECT count(*) FROM information_schema.tables "
                               "WHERE table_name = ?", [t]).fetchone()[0] == 1


def test_real_minimo_vira_real_e_e_idempotente():
    with _con() as con:
        con.execute("INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
                    "variante_id, adicionado_em, fase, fase_desde, ligada) "
                    "VALUES (1, 1, 1, ?, 'real_minimo', ?, true)",
                    [datetime(2026, 10, 1), datetime(2026, 10, 1)])
        db.init_schema(con)
        db.init_schema(con)
        assert con.execute("SELECT fase FROM portfolio_membros").fetchone()[0] == "real"


def test_tipos_novos_do_diario():
    assert {"contratos_alterados", "envio_ligado", "envio_desligado"} <= diario.TIPOS
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_schema_ordens.py`
Expected: FAIL (coluna `envio_ligado` não existe).

- [ ] **Step 3: Implementar** — em `core/schema.sql`, logo depois de `ALTER TABLE papel_pregoes ADD COLUMN IF NOT EXISTS falha VARCHAR;`:

```sql
-- parte 4 (ordens): spec 2026-10-08-ao-vivo-ordens-design.md §7.1.
-- Envio de ordens por conta, começa DESLIGADO: desligado, a automação
-- calcula tudo e registra "seria enviada" sem mandar nada.
ALTER TABLE contas ADD COLUMN IF NOT EXISTS envio_ligado BOOLEAN DEFAULT false;
-- contratos na conta, por variante; NULL = os do plano (o papel usa sempre
-- os do plano)
ALTER TABLE portfolio_membros ADD COLUMN IF NOT EXISTS contratos_demo BIGINT;
ALTER TABLE portfolio_membros ADD COLUMN IF NOT EXISTS contratos_real BIGINT;
-- o "real mínimo" deixou de existir (decisão 8); idempotente
UPDATE portfolio_membros SET fase = 'real' WHERE fase = 'real_minimo';

-- espelho do diário de ordens (data/ao_vivo/ordens/*.jsonl). SÓ INSERÇÃO,
-- como ao_vivo_eventos: o estado de cada ordem é derivado dos eventos. Não
-- se recria de lugar nenhum fora do arquivo do dia — não apagar.
CREATE TABLE IF NOT EXISTS ordens_eventos (
    evento_id   VARCHAR PRIMARY KEY,
    quando      TIMESTAMP NOT NULL,
    tipo        VARCHAR NOT NULL,
    conta_id    BIGINT,
    ligacao_id  BIGINT,
    entry_ts    TIMESTAMP,
    lado        INTEGER,
    contratos   DOUBLE,
    simbolo     VARCHAR,
    ticket      BIGINT,
    retcode     INTEGER,
    preco_papel BIGINT,
    preco       BIGINT,
    atraso_ms   INTEGER,
    tentativa   INTEGER,
    motivo      VARCHAR,
    dados       JSON
);

-- conferência diária papel × backtest (spec §8): o papel conferido de um
-- dia, comparado operação a operação com o backtest do plano nos mesmos
-- candles já reconferidos
CREATE TABLE IF NOT EXISTS papel_backtest (
    ligacao_id   BIGINT NOT NULL,
    dia          DATE NOT NULL,
    conferido_em TIMESTAMP NOT NULL,
    ok           BOOLEAN NOT NULL,
    n_papel      INTEGER,
    n_backtest   INTEGER,
    diferencas   JSON,
    PRIMARY KEY (ligacao_id, dia)
);
```

Em `core/diario.py`, `TIPOS` ganha `"contratos_alterados", "envio_ligado", "envio_desligado"`.

- [ ] **Step 4: Rodar e ver passar** — `.venv/Scripts/python.exe -m pytest -q tests/test_schema_ordens.py tests/test_ao_vivo*.py tests/test_diario*.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/schema.sql core/diario.py tests/test_schema_ordens.py
git commit -F <arquivo com "feat(ordens): schema da parte 4 e tipos do diario" + Co-Authored-By>
```

---

### Task 2: `core/corretora.py` — retornos, pedidos, arredondamento

**Files:**
- Create: `core/corretora.py`
- Test: `tests/test_corretora.py`

**Interfaces:**
- Produces:
  - Constantes de classe: `OK, INCERTA, ACEITA, PARCIAL, PASSAGEIRA, USUARIO, JA_SAIU, SEM_MUDANCA, SAIDA_EM_TRANSITO, PREENCHIMENTO, VOLUME_FECHAMENTO, STOPS_INVALIDOS, DESCONHECIDO` (strings).
  - `RETORNOS: dict[int, str]`, `TEXTOS: dict[int, str]`.
  - `classificar(resultado) -> str` (`None` → `PASSAGEIRA`).
  - `texto(resultado) -> str`.
  - `MAGIC_BASE = 7_000_000`; `magic(ligacao_id) -> int`; `ligacao_do_magic(m) -> int | None`.
  - `modos_preenchimento(mascara: int, mt5) -> list[int]` (IOC, FOK se permitidos, RETURN sempre por último).
  - `ao_tick(preco, tick, para_cima: bool) -> int`; `protecao(lado, stop_px, alvo_px, tick) -> tuple[int | None, int | None]`.
  - `pedido_entrada(mt5, *, simbolo, lado, volume, preco, magic_, comentario, desvio, preenchimento) -> dict` (sem sl/tp); `pedido_saida(mt5, *, simbolo, lado_posicao, volume, preco, ticket, magic_, desvio, preenchimento) -> dict`; `pedido_protecao(mt5, *, simbolo, ticket, sl, tp, magic_) -> dict`; `pedido_cancelar(mt5, *, ordem) -> dict`.

- [ ] **Step 1: Teste falhando** — `tests/test_corretora.py`:

```python
"""Tabela de retornos do MT5, pedidos e arredondamento (spec §5.2–5.4, §6)."""
from types import SimpleNamespace as NS

import pytest

from core import corretora as K
from tests.mt5_falso import MT5Ordens

# um teste por código: a classificação decide se a automação tenta de novo,
# espera, desiste ou chama o usuário — errar aqui é ordem duplicada ou perdida
CASOS = [
    (10004, K.PASSAGEIRA), (10006, K.PASSAGEIRA), (10007, K.PASSAGEIRA),
    (10008, K.ACEITA), (10009, K.OK), (10010, K.PARCIAL),
    (10011, K.PASSAGEIRA), (10012, K.INCERTA), (10013, K.USUARIO),
    (10014, K.USUARIO), (10015, K.USUARIO), (10016, K.STOPS_INVALIDOS),
    (10017, K.USUARIO), (10018, K.PASSAGEIRA), (10019, K.USUARIO),
    (10020, K.PASSAGEIRA), (10021, K.PASSAGEIRA), (10022, K.USUARIO),
    (10023, K.PASSAGEIRA), (10024, K.PASSAGEIRA), (10025, K.SEM_MUDANCA),
    (10026, K.USUARIO), (10027, K.USUARIO), (10028, K.PASSAGEIRA),
    (10029, K.PASSAGEIRA), (10030, K.PREENCHIMENTO), (10031, K.PASSAGEIRA),
    (10032, K.USUARIO), (10033, K.USUARIO), (10034, K.USUARIO),
    (10035, K.USUARIO), (10036, K.JA_SAIU), (10038, K.VOLUME_FECHAMENTO),
    (10039, K.SAIDA_EM_TRANSITO), (10040, K.USUARIO), (10041, K.PASSAGEIRA),
    (10042, K.USUARIO), (10043, K.USUARIO), (10044, K.USUARIO),
    (10045, K.USUARIO), (10046, K.USUARIO),
]


@pytest.mark.parametrize("codigo,classe", CASOS)
def test_cada_codigo_tem_classe(codigo, classe):
    assert K.classificar(NS(retcode=codigo)) == classe


def test_toda_a_documentacao_esta_na_tabela():
    # 10004..10046 menos 10005 e 10037, que a documentação não lista
    esperados = set(range(10004, 10047)) - {10005, 10037}
    assert set(K.RETORNOS) == esperados
    assert set(K.TEXTOS) == esperados


def test_none_e_incerta_e_codigo_estranho_e_desconhecido():
    # sem resposta: a ordem pode ter executado — reenviar sem conferir duplica
    assert K.classificar(None) == K.INCERTA
    assert K.classificar(NS(retcode=12345)) == K.DESCONHECIDO


def test_magic_ida_e_volta_e_fora_da_faixa():
    assert K.magic(4) == 7_000_004
    assert K.ligacao_do_magic(7_000_004) == 4
    assert K.ligacao_do_magic(0) is None            # ordem à mão
    assert K.ligacao_do_magic(7_000_000) is None
    assert K.ligacao_do_magic(8_000_000) is None


def test_preenchimento_pela_mascara_de_bits():
    mt5 = MT5Ordens()
    # a máscara NÃO é o valor de ORDER_FILLING_*: 3 = FOK|IOC
    assert K.modos_preenchimento(3, mt5) == [1, 0, 2]
    assert K.modos_preenchimento(2, mt5) == [1, 2]
    assert K.modos_preenchimento(1, mt5) == [0, 2]
    assert K.modos_preenchimento(0, mt5) == [2]     # RETURN sempre vale na bolsa


@pytest.mark.parametrize("lado,stop,alvo,esperado", [
    (1, 188_642, 189_663, (188_640, 189_665)),     # compra: stop p/ baixo, alvo p/ cima
    (-1, 188_642, 187_663, (188_645, 187_660)),    # venda: stop p/ cima, alvo p/ baixo
    (1, 188_640, 189_665, (188_640, 189_665)),     # já no tick: não mexe
    (1, None, 189_663, (None, 189_665)),
])
def test_protecao_arredonda_para_longe_da_entrada(lado, stop, alvo, esperado):
    assert K.protecao(lado, stop, alvo, 5) == esperado


def test_pedidos_tem_os_campos_da_documentacao():
    mt5 = MT5Ordens()
    e = K.pedido_entrada(mt5, simbolo="WINV26", lado=1, volume=2, preco=189_010,
                         magic_=7_000_004, comentario="df 10:01 4 " + "x" * 40,
                         desvio=10, preenchimento=1)
    assert e["action"] == 1 and e["type"] == 0 and e["volume"] == 2.0
    # execução em bolsa: sl/tp não são campos garantidos da ordem a mercado
    assert "sl" not in e and "tp" not in e and e["magic"] == 7_000_004
    assert len(e["comment"]) <= 31 and e["type_filling"] == 1 and e["type_time"] == 0
    s = K.pedido_saida(mt5, simbolo="WINV26", lado_posicao=1, volume=2, preco=189_245,
                       ticket=55, magic_=7_000_004, desvio=10, preenchimento=1)
    assert s["type"] == 1 and s["position"] == 55 and "sl" not in s
    p = K.pedido_protecao(mt5, simbolo="WINV26", ticket=55, sl=188_645, tp=None,
                          magic_=7_000_004)
    assert p == {"action": 6, "symbol": "WINV26", "position": 55, "sl": 188_645.0,
                 "tp": 0.0, "magic": 7_000_004}
    assert K.pedido_cancelar(mt5, ordem=99) == {"action": 8, "order": 99}
```

- [ ] **Step 2: Rodar e ver falhar** — `pytest -q tests/test_corretora.py` → FAIL (`core.corretora` não existe; `tests/mt5_falso.py` vem na Tarefa 3 — **faça a Tarefa 3 antes do Step 4 desta**, ou crie já o `tests/mt5_falso.py` da Tarefa 3).

- [ ] **Step 3: Implementar** — `core/corretora.py`:

```python
"""A corretora vista pela automação: retornos, pedidos e fotografia.

Spec: docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md §5–6.
Aqui não se decide operar nada — só se traduz. A tabela de retornos é a
peça mais perigosa da parte 4: tratar um "aceita, aguardando" (PLACED) como
erro e reenviar duplica a posição; tratar um "sem margem" como passageiro
fica tentando para sempre. Por isso ela é única, por número (o pacote
5.0.6180 nem tem todas as constantes, ex.: HEDGE_PROHIBITED) e testada
código a código contra a documentação oficial
(mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes).
"""
from __future__ import annotations

import math

OK = "ok"
INCERTA = "incerta"                # sem resposta: pode ter executado
ACEITA = "aceita"                  # PLACED: a bolsa recebeu, o negócio vem depois
PARCIAL = "parcial"
PASSAGEIRA = "passageira"          # resolve sozinha: tentar de novo
USUARIO = "usuario"                # configuração: chamar o usuário
JA_SAIU = "ja_saiu"                # a posição já não existe
SEM_MUDANCA = "sem_mudanca"        # SL/TP já estão como pedido
SAIDA_EM_TRANSITO = "saida_em_transito"
PREENCHIMENTO = "preenchimento"    # modo de preenchimento recusado
VOLUME_FECHAMENTO = "volume_fechamento"
STOPS_INVALIDOS = "stops_invalidos"
DESCONHECIDO = "desconhecido"

RETORNOS: dict[int, str] = {
    10004: PASSAGEIRA,   # requote
    10006: PASSAGEIRA,   # pedido rejeitado
    10007: PASSAGEIRA,   # cancelado
    10008: ACEITA,       # ordem colocada (execução em bolsa)
    10009: OK,
    10010: PARCIAL,
    10011: PASSAGEIRA,   # erro de processamento
    10012: INCERTA,      # timeout: pode ter executado
    10013: USUARIO,      # pedido inválido
    10014: USUARIO,      # volume inválido
    10015: USUARIO,      # preço inválido
    10016: STOPS_INVALIDOS,
    10017: USUARIO,      # negociação desabilitada
    10018: PASSAGEIRA,   # mercado fechado (leilão, por instantes)
    10019: USUARIO,      # sem margem
    10020: PASSAGEIRA,   # preço mudou
    10021: PASSAGEIRA,   # sem cotação
    10022: USUARIO,      # validade inválida
    10023: PASSAGEIRA,   # ordem mudou de estado
    10024: PASSAGEIRA,   # pedidos demais
    10025: SEM_MUDANCA,
    10026: USUARIO,      # Algo Trading desligado no servidor
    10027: USUARIO,      # Algo Trading desligado no terminal
    10028: PASSAGEIRA,   # travado para processamento
    10029: PASSAGEIRA,   # ordem/posição congelada
    10030: PREENCHIMENTO,
    10031: PASSAGEIRA,   # sem conexão com o servidor
    10032: USUARIO,      # só conta real
    10033: USUARIO,      # limite de ordens pendentes
    10034: USUARIO,      # limite de volume
    10035: USUARIO,      # tipo de ordem proibido
    10036: JA_SAIU,
    10038: VOLUME_FECHAMENTO,
    10039: SAIDA_EM_TRANSITO,
    10040: USUARIO,      # limite de posições
    10041: PASSAGEIRA,   # ativação recusada, ordem cancelada
    10042: USUARIO,      # só compra
    10043: USUARIO,      # só venda
    10044: USUARIO,      # só encerramento (vencimento)
    10045: USUARIO,      # regra FIFO
    10046: USUARIO,      # posição contrária proibida (conta não é hedging)
}

TEXTOS: dict[int, str] = {
    10004: "requote", 10006: "recusada pela corretora", 10007: "cancelada",
    10008: "aceita, aguardando a bolsa", 10009: "executada",
    10010: "executada em parte", 10011: "erro na corretora",
    10012: "sem resposta a tempo", 10013: "pedido inválido",
    10014: "volume inválido", 10015: "preço inválido",
    10016: "stop ou alvo inválido", 10017: "negociação desabilitada",
    10018: "mercado fechado (leilão)", 10019: "sem margem",
    10020: "preço mudou", 10021: "sem cotação", 10022: "validade inválida",
    10023: "ordem mudou de estado", 10024: "pedidos demais",
    10025: "nada a mudar", 10026: "Algo Trading desligado na corretora",
    10027: "Algo Trading desligado no MT5", 10028: "em processamento",
    10029: "posição congelada", 10030: "modo de preenchimento recusado",
    10031: "sem conexão com a corretora", 10032: "só conta real",
    10033: "limite de ordens", 10034: "limite de volume",
    10035: "tipo de ordem proibido", 10036: "posição já encerrada",
    10038: "volume maior que a posição", 10039: "saída já em andamento",
    10040: "limite de posições", 10041: "ordem cancelada pela corretora",
    10042: "só compra permitida", 10043: "só venda permitida",
    10044: "só encerramento (vencimento)", 10045: "regra FIFO",
    10046: "conta não aceita posições contrárias",
}


def classificar(resultado) -> str:
    """`None` acontece com o terminal sem resposta: INCERTA — a ordem pode
    ter executado; a reconciliação só reenvia depois de conferir o
    histórico de ordens."""
    if resultado is None:
        return INCERTA
    return RETORNOS.get(int(resultado.retcode), DESCONHECIDO)


def texto(resultado) -> str:
    if resultado is None:
        return "sem resposta do MT5"
    c = int(resultado.retcode)
    return TEXTOS.get(c, f"retorno desconhecido {c}")


# ---------------------------------------------------------------- magic
MAGIC_BASE = 7_000_000
_MAGIC_FIM = 7_999_999


def magic(ligacao_id: int) -> int:
    return MAGIC_BASE + int(ligacao_id)


def ligacao_do_magic(m) -> int | None:
    """Fora da faixa = posição que a automação não abriu (à mão, outro
    robô): nunca é tocada (D4)."""
    m = int(m or 0)
    return m - MAGIC_BASE if MAGIC_BASE < m <= _MAGIC_FIM else None


# --------------------------------------------------------- preenchimento
# SYMBOL_FILLING_MODE é máscara de bits (FOK = 1, IOC = 2) — não o valor de
# ORDER_FILLING_* (FOK 0, IOC 1, RETURN 2). Em execução em bolsa RETURN vale
# sempre, mas deixa o resto da ordem viva (D3 manda cancelar): fica por último.
_BIT_FOK, _BIT_IOC = 1, 2


def modos_preenchimento(mascara: int, mt5) -> list[int]:
    modos = []
    if int(mascara) & _BIT_IOC:
        modos.append(mt5.ORDER_FILLING_IOC)
    if int(mascara) & _BIT_FOK:
        modos.append(mt5.ORDER_FILLING_FOK)
    modos.append(mt5.ORDER_FILLING_RETURN)
    return modos


# ------------------------------------------------------------ ao tick
def ao_tick(preco, tick: int, para_cima: bool) -> int:
    q = float(preco) / tick
    return int((math.ceil(q) if para_cima else math.floor(q)) * tick)


def protecao(lado: int, stop_px, alvo_px, tick: int):
    """Sempre para LONGE da entrada: o stop nunca fica mais apertado que o
    do papel, e a comparação com a corretora usa este mesmo valor — senão
    um stop por ATR fora do tick viraria uma modificação por volta."""
    sl = None if stop_px is None else ao_tick(stop_px, tick, para_cima=lado < 0)
    tp = None if alvo_px is None else ao_tick(alvo_px, tick, para_cima=lado > 0)
    return sl, tp


# -------------------------------------------------------------- pedidos
def pedido_entrada(mt5, *, simbolo, lado, volume, preco, magic_,
                   comentario, desvio, preenchimento) -> dict:
    """Sem sl/tp: em execução em bolsa a documentação de MqlTradeRequest só
    garante action/symbol/volume/type/type_filling na ordem a mercado. A
    proteção sai logo depois, em TRADE_ACTION_SLTP (`pedido_protecao`)."""
    return {"action": mt5.TRADE_ACTION_DEAL, "symbol": simbolo,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if lado > 0 else mt5.ORDER_TYPE_SELL,
            "price": float(preco),
            "deviation": int(desvio), "magic": int(magic_),
            "comment": str(comentario)[:31], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(preenchimento)}


def pedido_saida(mt5, *, simbolo, lado_posicao, volume, preco, ticket, magic_,
                 desvio, preenchimento) -> dict:
    """Hedging: fecha a posição pelo ticket (`position`), com ordem contrária
    — o exemplo oficial do order_send faz exatamente assim."""
    return {"action": mt5.TRADE_ACTION_DEAL, "symbol": simbolo,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_SELL if lado_posicao > 0 else mt5.ORDER_TYPE_BUY,
            "position": int(ticket), "price": float(preco),
            "deviation": int(desvio), "magic": int(magic_),
            "comment": "df saida", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(preenchimento)}


def pedido_protecao(mt5, *, simbolo, ticket, sl, tp, magic_) -> dict:
    return {"action": mt5.TRADE_ACTION_SLTP, "symbol": simbolo,
            "position": int(ticket), "sl": float(sl or 0), "tp": float(tp or 0),
            "magic": int(magic_)}


def pedido_cancelar(mt5, *, ordem) -> dict:
    return {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ordem)}
```

- [ ] **Step 4: Rodar e ver passar** — `pytest -q tests/test_corretora.py` → PASS.
- [ ] **Step 5: Commit** — `git add core/corretora.py tests/test_corretora.py` → `feat(ordens): tabela de retornos e pedidos do MT5`.

---

### Task 3: MT5 falso e a fotografia da conta

**Files:**
- Create: `tests/mt5_falso.py`
- Modify: `core/corretora.py` (acrescenta `Posicao`, `Negocio`, `Fotografia`, `fotografar`, `_lista`)
- Test: `tests/test_corretora_foto.py`

**Interfaces:**
- Consumes: `corretora.ligacao_do_magic`.
- Produces:
  - `tests.mt5_falso.MT5Ordens` — atributos `posicoes: dict[int, NS]`, `ordens: dict[int, NS]`, `negocios: list[NS]`, `enviados: list[dict]`, `roteiro: list` (próximos retornos de `order_send`: int, `None`, ou `"executou_sem_resposta"`), `preco`, `margem_livre`, `algo`, `conectado`, `hedging`, `login`, `servidor`, `vazio_uma_vez`, `erro_leitura`, `filling`, `parcial_volume`; métodos do pacote usados (`positions_get`, `orders_get`, `history_deals_get`, `account_info`, `terminal_info`, `symbol_info`, `symbol_info_tick`, `symbols_get`, `order_check`, `order_send`, `last_error`) e auxiliares de cenário `abrir_manual(lado, volume)`, `stopar(ticket, motivo=4)`, `executar_pendente(ordem)`.
  - `corretora.Posicao(ticket, magic, ligacao_id, simbolo, lado, volume, preco, sl, tp, resultado, aberta_em)`; `Negocio(ticket, posicao, magic, ligacao_id, simbolo, entrada, lado, volume, preco, resultado, motivo, quando)`; `Fotografia(posicoes, ordens, negocios, login, servidor, hedging, margem_livre, algo_ligado)`; `fotografar(mt5, inicio_dia: datetime) -> Fotografia | None`.

- [ ] **Step 1: Criar o MT5 falso** — `tests/mt5_falso.py`:

```python
"""MT5 falso de ORDENS: posições, ordens pendentes, negócios do dia e um
roteiro de retornos para o order_send. Nada aqui fala com terminal.

As constantes são as do pacote MetaTrader5 5.0.6180 (conferidas): o código
de produção as lê do objeto `mt5`, então o falso precisa dos mesmos valores.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace as NS


def _epoch(d: datetime) -> int:
    return int(d.replace(tzinfo=timezone.utc).timestamp())


class MT5Ordens:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 6, 8
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
    DEAL_REASON_CLIENT, DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 3, 4, 5
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
    SYMBOL_TRADE_MODE_FULL = 4
    TIMEFRAME_M1 = 1

    def __init__(self, *, login=1193398927, servidor="ClearInvestimentos-DEMO",
                 preco=189_000, agora=datetime(2026, 10, 9, 10, 1, 1)):
        self.login, self.servidor = login, servidor
        self.preco = preco
        self.agora = agora                 # hora dos negócios criados
        self.posicoes: dict[int, NS] = {}
        self.ordens: dict[int, NS] = {}
        self.negocios: list[NS] = []
        self.enviados: list[dict] = []
        self.checados: list[dict] = []
        self.roteiro: list = []
        self.margem_livre = 10_000.0
        self.algo = True
        self.conectado = True
        self.hedging = True
        self.vazio_uma_vez = False         # lista vazia logo após reconectar
        self.erro_leitura = False          # positions_get/orders_get/... -> None
        self.filling = 3                   # máscara FOK|IOC
        self.parcial_volume = 1.0
        self.precos = {"WIN$N": preco, "WINV26": preco, "WINZ26": preco + 1500}
        self.vencimentos = {"WINV26": datetime(2026, 10, 14, 18, 30),
                            "WINZ26": datetime(2026, 12, 16, 18, 30)}
        self._ticket = 1000

    # ---------------------------------------------------------- leitura
    def last_error(self):
        return (-10004, "IPC") if self.erro_leitura else (1, "Success")

    def positions_get(self, **k):
        if self.erro_leitura:
            return None
        if self.vazio_uma_vez:
            self.vazio_uma_vez = False
            return ()
        return tuple(self.posicoes.values())

    def orders_get(self, **k):
        return None if self.erro_leitura else tuple(self.ordens.values())

    def history_deals_get(self, de, ate, **k):
        return None if self.erro_leitura else tuple(self.negocios)

    def account_info(self):
        return NS(login=self.login, server=self.servidor,
                  margin_mode=2 if self.hedging else 0,
                  margin_free=self.margem_livre)

    def terminal_info(self):
        return NS(connected=self.conectado, trade_allowed=self.algo)

    def symbol_info(self, s):
        venc = self.vencimentos.get(s)
        return NS(name=s, filling_mode=self.filling, trade_stops_level=0,
                  trade_tick_size=5.0, trade_mode=4, basis="",
                  expiration_time=_epoch(venc) if venc else 0)

    def symbol_info_tick(self, s):
        p = self.precos.get(s, self.preco)
        return NS(time=_epoch(self.agora), last=float(p), bid=float(p),
                  ask=float(p + 5))

    def symbols_get(self, group=None):
        return tuple(self.symbol_info(s) for s in self.precos)

    def order_check(self, req):
        self.checados.append(dict(req))
        sem = self.margem_livre <= 0
        return NS(retcode=10019 if sem else 0, comment="No money" if sem else "Done",
                  margin_free=self.margem_livre)

    # ----------------------------------------------------------- envio
    def _novo(self):
        self._ticket += 1
        return self._ticket

    def order_send(self, req):
        self.enviados.append(dict(req))
        r = self.roteiro.pop(0) if self.roteiro else 10009
        if r is None:
            return None
        if r == "executou_sem_resposta":
            self._executar(req)
            return None
        if r == 10008:                      # PLACED: fica como ordem pendente
            t = self._novo()
            self.ordens[t] = NS(ticket=t, magic=req.get("magic", 0),
                                symbol=req["symbol"], volume_current=req["volume"],
                                req=dict(req))
            return NS(retcode=10008, order=t, deal=0, volume=0.0, price=0.0, comment="")
        if r in (10009, 10010):
            return self._executar(req, parcial=r == 10010)
        return NS(retcode=r, order=0, deal=0, volume=0.0, price=0.0, comment="")

    def _executar(self, req, parcial=False):
        acao = req["action"]
        if acao == self.TRADE_ACTION_SLTP:
            p = self.posicoes.get(req["position"])
            if p is None:
                return NS(retcode=10036, order=0, deal=0, volume=0.0, price=0.0, comment="")
            p.sl, p.tp = req["sl"], req["tp"]
            return NS(retcode=10009, order=0, deal=0, volume=0.0, price=0.0, comment="")
        if acao == self.TRADE_ACTION_REMOVE:
            self.ordens.pop(req["order"], None)
            return NS(retcode=10009, order=req["order"], deal=0, volume=0.0, price=0.0, comment="")
        if "position" in req:               # saída
            p = self.posicoes.pop(req["position"], None)
            if p is None:
                return NS(retcode=10036, order=0, deal=0, volume=0.0, price=0.0, comment="")
            self.negocios.append(NS(ticket=self._novo(), order=0,
                                    time=_epoch(self.agora), type=req["type"], entry=1,
                                    magic=p.magic, position_id=p.ticket, reason=3,
                                    volume=p.volume, price=float(self.preco),
                                    commission=0.0, swap=0.0, fee=0.0,
                                    profit=p.profit, symbol=p.symbol))
            return NS(retcode=10009, order=self._ticket, deal=self._ticket,
                      volume=p.volume, price=float(self.preco), comment="")
        vol = self.parcial_volume if parcial else req["volume"]
        t = self._novo()
        self.posicoes[t] = NS(ticket=t, identifier=t, magic=req["magic"],
                              symbol=req["symbol"], type=req["type"], volume=vol,
                              price_open=float(self.preco), sl=req["sl"], tp=req["tp"],
                              profit=0.0, time=_epoch(self.agora))
        self.negocios.append(NS(ticket=self._novo(), order=t, time=_epoch(self.agora),
                                type=req["type"], entry=0, magic=req["magic"],
                                position_id=t, reason=3, volume=vol,
                                price=float(self.preco), commission=0.0, swap=0.0,
                                fee=0.0, profit=0.0, symbol=req["symbol"]))
        if parcial:                          # o resto fica vivo (RETURN)
            o = self._novo()
            self.ordens[o] = NS(ticket=o, magic=req["magic"], symbol=req["symbol"],
                                volume_current=req["volume"] - vol, req=dict(req))
        return NS(retcode=10010 if parcial else 10009, order=t, deal=self._ticket,
                  volume=vol, price=float(self.preco), comment="")

    # ------------------------------------------------------- cenários
    def abrir_manual(self, lado, volume=1.0, magic=0, simbolo="WINV26"):
        return self._executar({"action": 1, "symbol": simbolo, "volume": volume,
                               "type": 0 if lado > 0 else 1, "sl": 0.0, "tp": 0.0,
                               "magic": magic}).order

    def stopar(self, ticket, motivo=4):
        """O servidor executou o SL (4) ou o TP (5)."""
        p = self.posicoes.pop(ticket)
        self.negocios.append(NS(ticket=self._novo(), order=0, time=_epoch(self.agora),
                                type=1 - p.type, entry=1, magic=p.magic,
                                position_id=p.ticket, reason=motivo, volume=p.volume,
                                price=float(self.preco), commission=0.0, swap=0.0,
                                fee=0.0, profit=p.profit, symbol=p.symbol))

    def executar_pendente(self, ordem):
        o = self.ordens.pop(ordem)
        return self._executar(o.req)
```

- [ ] **Step 2: Teste falhando** — `tests/test_corretora_foto.py`:

```python
from datetime import datetime

from core import corretora as K
from tests.mt5_falso import MT5Ordens

DIA = datetime(2026, 10, 9)


def test_fotografia_separa_por_magic_e_le_a_conta():
    mt5 = MT5Ordens()
    mt5.abrir_manual(1, magic=K.magic(4))
    mt5.abrir_manual(-1)                                   # à mão
    f = K.fotografar(mt5, DIA)
    assert [p.ligacao_id for p in f.posicoes] == [4, None]
    assert f.posicoes[0].lado == 1 and f.posicoes[1].lado == -1
    assert f.hedging and f.algo_ligado and f.login == 1193398927
    assert len(f.negocios) == 2 and f.negocios[0].entrada


def test_none_com_erro_e_volta_perdida():
    mt5 = MT5Ordens()
    mt5.erro_leitura = True
    assert K.fotografar(mt5, DIA) is None


def test_none_com_res_s_ok_vale_como_lista_vazia(monkeypatch):
    # a documentação não garante o que volta sem posição; com
    # last_error() == RES_S_OK (1) o None é "nenhuma"
    mt5 = MT5Ordens()
    monkeypatch.setattr(mt5, "orders_get", lambda **k: None)
    f = K.fotografar(mt5, DIA)
    assert f is not None and f.ordens == []
```

- [ ] **Step 3: Rodar e ver falhar** → FAIL (`fotografar` não existe).

- [ ] **Step 4: Implementar** — acrescentar ao fim de `core/corretora.py`:

```python
# ---------------------------------------------------------- fotografia
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class Posicao:
    ticket: int
    magic: int
    ligacao_id: int | None
    simbolo: str
    lado: int                 # +1 comprado, -1 vendido
    volume: float
    preco: float
    sl: float
    tp: float
    resultado: float          # R$ aberto, como a corretora calcula
    aberta_em: datetime


@dataclass
class Negocio:
    ticket: int
    posicao: int
    magic: int
    ligacao_id: int | None
    simbolo: str
    entrada: bool
    lado: int
    volume: float
    preco: float
    resultado: float          # lucro + comissão + swap + taxa
    motivo: int               # DEAL_REASON_* (4 = SL, 5 = TP)
    quando: datetime


@dataclass
class Fotografia:
    posicoes: list = field(default_factory=list)
    ordens: list = field(default_factory=list)      # dicts: ticket, magic, ligacao_id, simbolo, volume
    negocios: list = field(default_factory=list)
    login: int | None = None
    servidor: str | None = None
    hedging: bool = False
    margem_livre: float = 0.0
    algo_ligado: bool = False


def _hora(epoch) -> datetime:
    # mesma regra das barras: o epoch do MT5 já é o relógio de Brasília
    return datetime.fromtimestamp(int(epoch), timezone.utc).replace(tzinfo=None)


def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc)


def _lista(mt5, valor):
    """`None` é erro (documentação: "Return None in case of an error") —
    a não ser que o last_error diga sucesso (1), quando é "nenhuma": a
    documentação não garante o que volta sem itens. Erro = `_Falha`."""
    if valor is not None:
        return list(valor)
    erro = mt5.last_error()
    if erro and int(erro[0]) == 1:
        return []
    raise _Falha(erro)


class _Falha(Exception):
    pass


def fotografar(mt5, inicio_dia: datetime) -> Fotografia | None:
    """A conta numa leitura só. `None` = volta perdida: sem foto confiável
    a automação não decide nada (spec §5.1)."""
    try:
        pos = _lista(mt5, mt5.positions_get())
        ords = _lista(mt5, mt5.orders_get())
        deals = _lista(mt5, mt5.history_deals_get(
            _utc(inicio_dia), _utc(inicio_dia + timedelta(days=1))))
    except _Falha:
        return None
    conta, term = mt5.account_info(), mt5.terminal_info()
    if conta is None or term is None:
        return None
    f = Fotografia(login=int(conta.login), servidor=conta.server,
                   hedging=int(conta.margin_mode) == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
                   margem_livre=float(conta.margin_free),
                   algo_ligado=bool(term.trade_allowed))
    for p in pos:
        f.posicoes.append(Posicao(
            ticket=int(p.ticket), magic=int(p.magic),
            ligacao_id=ligacao_do_magic(p.magic), simbolo=p.symbol,
            lado=1 if int(p.type) == mt5.POSITION_TYPE_BUY else -1,
            volume=float(p.volume), preco=float(p.price_open),
            sl=float(p.sl or 0), tp=float(p.tp or 0), resultado=float(p.profit),
            aberta_em=_hora(p.time)))
    for o in ords:
        f.ordens.append({"ticket": int(o.ticket), "magic": int(o.magic),
                         "ligacao_id": ligacao_do_magic(o.magic),
                         "simbolo": o.symbol, "volume": float(o.volume_current)})
    for d in deals:
        f.negocios.append(Negocio(
            ticket=int(d.ticket), posicao=int(d.position_id), magic=int(d.magic),
            ligacao_id=ligacao_do_magic(d.magic), simbolo=d.symbol,
            entrada=int(d.entry) == mt5.DEAL_ENTRY_IN,
            lado=1 if int(d.type) == mt5.ORDER_TYPE_BUY else -1,
            volume=float(d.volume), preco=float(d.price),
            resultado=float(d.profit) + float(d.commission) + float(d.swap)
            + float(getattr(d, "fee", 0.0)),
            motivo=int(d.reason), quando=_hora(d.time)))
    return f
```

(Mova os `import` do topo: `dataclass, field`, `datetime, timedelta, timezone` vão para o cabeçalho do módulo junto com `math`.)

**Correções da revisão (fazem parte desta tarefa):**
- `fotografar` só aceita negócios de compra/venda: `if int(d.type) not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL): continue` (depósito/saldo na demo, `type=2`, não pode virar lucro na perda do dia). O falso ganha `DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1` e um teste com um negócio `type=2` ignorado.
- Fotografia ganha `historico_ordens: list[dict]` (`ticket`, `magic`, `ligacao_id`, `quando`) de `history_orders_get(inicio, fim)` — conferir a página `mt5historyordersget_py` antes; mesma regra de `None`/`last_error`. O falso guarda cada ordem enviada (DEAL e PLACED) num histórico e expõe `history_orders_get(de, ate, **k)`.
- `ordens` da fotografia ganha `quando` (`time_setup` da ordem), para cancelar ordem pendente velha (Tarefa 7). O falso põe `time_setup = epoch(agora)` nas ordens.
- A entrada do falso abre a posição **sem** SL/TP (`req.get("sl", 0.0)`), como a ordem real sem esses campos.

- [ ] **Step 5: Rodar e ver passar** — `pytest -q tests/test_corretora.py tests/test_corretora_foto.py` → PASS.
- [ ] **Step 6: Mutação** — agente `mutacao` em `core/corretora.py` (`RETORNOS`, `modos_preenchimento`, `protecao`, `_lista`). Todas as mutações têm de ser pegas.
- [ ] **Step 7: Commit** — `tests/mt5_falso.py core/corretora.py tests/test_corretora_foto.py` → `feat(ordens): fotografia da conta e MT5 falso de ordens`.

---

### Task 4: Diário de ordens (escrita adiantada)

**Files:**
- Create: `core/diario_ordens.py`
- Test: `tests/test_diario_ordens.py`

**Interfaces:**
- Produces: `PASTA = db.DATA / "ao_vivo" / "ordens"` (constante de módulo, desviada no `tests/conftest.py` autouse — acrescente lá); `TIPOS` (frozenset); `class Diario(pasta: Path, dia: date, origem: str = "demo")` com `arquivo`, `eventos: list[dict]`, `registrar(tipo, *, quando: datetime, **campos) -> dict`, `enviada(lig, entry_ts) -> bool`, `ticket(lig, entry_ts) -> int | None`, `tentativas(lig, entry_ts) -> int`, `registrado(lig, entry_ts, tipo) -> bool`, `ultimo_motivo(lig, entry_ts) -> str | None`, `saida_desde(ticket) -> datetime | None`, `travada(conta_id) -> dict | None`, `ultimo(lig, entry_ts) -> dict | None`, `ultima_tentativa(tipo, *, ticket=None, lig=None, entry_ts=None) -> datetime | None`, `executada_em(lig, entry_ts) -> datetime | None`, `tickets_abertos(lig) -> list[tuple[int, datetime]]`, `comandos_do_dia(tipo) -> list[dict]`, `espelhar(con) -> int`; função `espelhar_pendentes(pasta, con, dias: int = 5, origem="demo") -> int` (espelha os arquivos dos últimos `dias` — chamada na subida, na virada do dia e na escrita da conferência, para os eventos depois do último candle chegarem ao banco). Testes a mais: um por método novo. Campos de evento: os de `ordens_eventos` (Tarefa 1); o resto vai em `dados`.

- [ ] **Step 1: Teste falhando** — `tests/test_diario_ordens.py`:

```python
"""Diário de ordens: arquivo primeiro, banco depois (spec §7.2)."""
from datetime import date, datetime

from core import db_manager as db
from core.diario_ordens import Diario

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
Q = datetime(2026, 10, 9, 10, 1, 1)


def test_registra_no_arquivo_e_relendo_o_estado_volta(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T, lado=1, contratos=2)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=1001, preco=189_010)
    novo = Diario(tmp_path, DIA)                 # a captura reabriu
    assert novo.enviada(4, T) and novo.ticket(4, T) == 1001
    assert novo.tentativas(4, T) == 1
    assert not novo.enviada(4, datetime(2026, 10, 9, 10, 2))


def test_linha_cortada_por_queda_e_ignorada_e_a_seguinte_nao_se_mistura(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    with open(d.arquivo, "a", encoding="utf-8") as f:
        f.write('{"evento_id": "x", "tipo": "execu')     # queda no meio
    d2 = Diario(tmp_path, DIA)
    d2.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=7)
    d3 = Diario(tmp_path, DIA)
    assert [e["tipo"] for e in d3.eventos] == ["enviando", "executada"]
    assert d3.ticket(4, T) == 7


def test_tipo_desconhecido_recusa(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        Diario(tmp_path, DIA).registrar("inventado", quando=Q)


def test_espelho_no_banco_nao_duplica(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T, lado=1, contratos=2,
                extra="vai para dados")
    d.registrar("conta_travada", quando=Q, conta_id=2, motivo="90% do limite")
    with db.connect_write() as con:
        db.init_schema(con)
        assert d.espelhar(con) == 2
        assert Diario(tmp_path, DIA).espelhar(con) == 0
        r = con.execute("SELECT tipo, ligacao_id, entry_ts, dados FROM ordens_eventos "
                        "ORDER BY evento_id").fetchall()
    assert r[0][0] == "enviando" and r[0][1] == 4 and r[0][2] == T
    assert "vai para dados" in r[0][3]


def test_travada_e_saida_desde(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.travada(2) is None
    d.registrar("conta_travada", quando=Q, conta_id=2, motivo="90%")
    assert d.travada(2)["motivo"] == "90%"
    d.registrar("saida_enviando", quando=Q, ligacao_id=4, ticket=55)
    d.registrar("saida_recusada", quando=datetime(2026, 10, 9, 10, 1, 3), ligacao_id=4, ticket=55)
    assert d.saida_desde(55) == Q
    d.registrar("saida_executada", quando=datetime(2026, 10, 9, 10, 1, 5), ligacao_id=4, ticket=55)
    assert d.saida_desde(55) is None
```

- [ ] **Step 2: Rodar e ver falhar** → FAIL (módulo não existe).

- [ ] **Step 3: Implementar** — `core/diario_ordens.py`:

```python
"""Diário das ordens: escrita adiantada em arquivo, espelho no banco.

Spec 2026-10-08-ao-vivo-ordens-design.md §7.2. O banco tem um escritor por
vez entre processos (uma mineração gravando o segura); a ordem não pode
esperar por ele. Então cada evento vai PRIMEIRO para o arquivo do dia, com
fsync, e só depois para `ordens_eventos`. É do arquivo, na subida, que a
captura sabe "já enviei a entrada X", "o ticket da operação Y", "a conta
travou hoje" — sem isso uma queda logo depois de enviar duplicaria a
entrada.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

TIPOS = frozenset({
    "enviando", "executada", "parcial", "aceita", "recusada", "perdida",
    "nao_entrou", "seria_enviada", "adotada", "saiu_antes",
    "saida_enviando", "saida_executada", "saida_recusada",
    "protecao_enviando", "protecao", "protecao_recusada", "cancelada",
    "incerta",
    "chamado", "chamado_fechado", "conta_travada", "rolagem", "comando",
})
_COLUNAS = ("evento_id", "quando", "tipo", "conta_id", "ligacao_id", "entry_ts",
            "lado", "contratos", "simbolo", "ticket", "retcode", "preco_papel",
            "preco", "atraso_ms", "tentativa", "motivo")
_DATAS = ("quando", "entry_ts")


def _para_json(ev: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in ev.items()}


def _de_json(ev: dict) -> dict:
    for k in _DATAS:
        if ev.get(k):
            ev[k] = datetime.fromisoformat(ev[k])
    return ev


class Diario:
    def __init__(self, pasta, dia: date, origem: str = "demo"):
        self.pasta, self.dia, self.origem = Path(pasta), dia, origem
        self.arquivo = self.pasta / f"{dia:%Y-%m-%d}.jsonl"
        self._quebrar_linha = False
        self.eventos: list[dict] = self._ler()

    def _ler(self) -> list[dict]:
        if not self.arquivo.exists():
            return []
        texto = self.arquivo.read_text(encoding="utf-8")
        # queda no meio da escrita deixa a última linha sem "\n": a próxima
        # escrita começaria nela e as duas virariam lixo juntas
        self._quebrar_linha = bool(texto) and not texto.endswith("\n")
        out = []
        for linha in texto.splitlines():
            try:
                out.append(_de_json(json.loads(linha)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return out

    def registrar(self, tipo: str, *, quando: datetime, **campos) -> dict:
        if tipo not in TIPOS:
            raise ValueError(f"tipo de evento de ordem desconhecido: {tipo}")
        ev = {"evento_id": f"{self.origem}-{self.dia:%Y%m%d}-{len(self.eventos) + 1:06d}",
              "quando": quando, "tipo": tipo, **campos}
        self.pasta.mkdir(parents=True, exist_ok=True)
        with open(self.arquivo, "a", encoding="utf-8") as f:
            if self._quebrar_linha:
                f.write("\n")
                self._quebrar_linha = False
            f.write(json.dumps(_para_json(ev), ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.eventos.append(ev)
        return ev

    # ------------------------------------------------------ estado derivado
    def _da(self, lig, entry_ts, *tipos):
        return [e for e in self.eventos
                if e.get("ligacao_id") == lig and e.get("entry_ts") == entry_ts
                and (not tipos or e["tipo"] in tipos)]

    def enviada(self, lig, entry_ts) -> bool:
        return bool(self._da(lig, entry_ts, "enviando"))

    def ticket(self, lig, entry_ts) -> int | None:
        evs = self._da(lig, entry_ts, "executada", "parcial", "adotada")
        return int(evs[-1]["ticket"]) if evs and evs[-1].get("ticket") else None

    def tentativas(self, lig, entry_ts) -> int:
        return len(self._da(lig, entry_ts, "enviando"))

    def registrado(self, lig, entry_ts, tipo) -> bool:
        return bool(self._da(lig, entry_ts, tipo))

    def ultimo_motivo(self, lig, entry_ts) -> str | None:
        evs = [e for e in self._da(lig, entry_ts) if e.get("motivo")]
        return evs[-1]["motivo"] if evs else None

    def saida_desde(self, ticket) -> datetime | None:
        """Desde quando a saída deste ticket está pendente (None = não está)."""
        desde = None
        for e in self.eventos:
            if e.get("ticket") != ticket:
                continue
            if e["tipo"] == "saida_enviando" and desde is None:
                desde = e["quando"]
            elif e["tipo"] in ("saida_executada", "saiu_antes"):
                desde = None
        return desde

    def travada(self, conta_id) -> dict | None:
        evs = [e for e in self.eventos
               if e["tipo"] == "conta_travada" and e.get("conta_id") == conta_id]
        return evs[-1] if evs else None

    def ultimo(self, lig, entry_ts) -> dict | None:
        evs = self._da(lig, entry_ts)
        return evs[-1] if evs else None

    def ultima_tentativa(self, tipo, *, ticket=None, lig=None, entry_ts=None):
        """Hora da última `tipo` (enviando/saida_enviando/protecao_enviando)
        — para o intervalo mínimo de 1 s entre tentativas."""
        for e in reversed(self.eventos):
            if e["tipo"] != tipo:
                continue
            if ticket is not None and e.get("ticket") != ticket:
                continue
            if lig is not None and (e.get("ligacao_id"), e.get("entry_ts")) != (lig, entry_ts):
                continue
            return e["quando"]
        return None

    def executada_em(self, lig, entry_ts) -> datetime | None:
        evs = self._da(lig, entry_ts, "executada", "parcial", "adotada")
        return evs[0]["quando"] if evs else None

    def tickets_abertos(self, lig) -> list[tuple[int, datetime]]:
        """(ticket, entry_ts) que a automação abriu nesta ligação e o diário
        ainda não viu sair — para registrar a saída pelo servidor mesmo com
        o papel já zerado."""
        abertos, fechados = {}, set()
        for e in self.eventos:
            if e.get("ligacao_id") != lig or not e.get("ticket"):
                continue
            if e["tipo"] in ("executada", "parcial", "adotada"):
                abertos[int(e["ticket"])] = e.get("entry_ts")
            elif e["tipo"] in ("saida_executada", "saiu_antes"):
                fechados.add(int(e["ticket"]))
        return [(t, ts) for t, ts in abertos.items() if t not in fechados]

    def comandos_do_dia(self, tipo) -> list[dict]:
        return [e for e in self.eventos
                if e["tipo"] == "comando" and e.get("motivo") == tipo]

    # ------------------------------------------------------------- espelho
    def espelhar(self, con) -> int:
        """Leva ao banco o que ainda não está lá; devolve quantos. Chamado
        com a conexão de escrita já aberta pela captura."""
        prefixo = f"{self.origem}-{self.dia:%Y%m%d}-%"
        ja = {r[0] for r in con.execute(
            "SELECT evento_id FROM ordens_eventos WHERE evento_id LIKE ?",
            [prefixo]).fetchall()}
        novos = [e for e in self.eventos if e["evento_id"] not in ja]
        for e in novos:
            extra = {k: v for k, v in e.items() if k not in _COLUNAS}
            con.execute(
                f"INSERT INTO ordens_eventos ({', '.join(_COLUNAS)}, dados) "
                f"VALUES ({', '.join('?' * (len(_COLUNAS) + 1))})",
                [e.get(c) for c in _COLUNAS]
                + [json.dumps(_para_json(extra), ensure_ascii=False, default=str)
                   if extra else None])
        return len(novos)
```

- [ ] **Step 4: Rodar e ver passar** → `pytest -q tests/test_diario_ordens.py` PASS.
- [ ] **Step 5: Commit** — `core/diario_ordens.py tests/test_diario_ordens.py` → `feat(ordens): diario de ordens com escrita adiantada`.

---

### Task 5: Papel — barra provisória e `preparar_dia`

**Files:**
- Modify: `core/papel.py` (nova função depois de `checksum`; `rodar_dia` dividido)
- Test: `tests/test_papel_provisoria.py`

**Interfaces:**
- Produces:
  - `papel.com_barra_provisoria(barras: dict | None, ts: datetime, abertura: int) -> dict | None`.
  - `papel.preparar_dia(con, dia, agora, cache_codigo, *, symbol=SIMBOLO) -> tuple[list[dict], list[tuple[dict, dict, dict]], dict[int, tuple[dict, object]]]` = `(resultados, fila, planos)` — exatamente o que `rodar_dia` monta hoje antes de ler as barras (linhas `gravados = ...` até `if not fila: return resultados`), **sem** o teste de `_tem_candle`.
  - `papel.rodar_dia(..., provisoria: tuple[datetime, int] | None = None)` — com `provisoria` e sem `dia_encerrado`, acrescenta a barra provisória às barras do dia antes de calcular.

- [ ] **Step 1: Teste falhando** — `tests/test_papel_provisoria.py`:

```python
"""Barra provisória: a entrada aparece no primeiro segundo do minuto, igual
ao que o candle real daria (spec §3)."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np

from core import papel
from strategies.base import Signals

DIA = date(2026, 10, 9)
SINAL = datetime(2026, 10, 9, 10, 0)
INST = {"symbol": "WIN$N", "tick_size": 5, "point_value": 0.2, "tick_value": 1.0}
PLANO = {"plano_id": 1, "contratos": 1, "params": {},
         "profile": {"timeframe": "M1", "entrada_inicio": "09:00",
                     "entrada_fim": "17:00", "fechamento": "17:50",
                     "stop_tipo": "pontos", "stop_pontos": 200,
                     "alvo_tipo": "pontos", "alvo_pontos": 400,
                     "dias_semana": [1, 2, 3, 4, 5]}}


def _mod():
    def signals(bars, params):
        n = len(bars["close"])
        el = bars["ts"] == np.datetime64(SINAL, "ns")
        z = np.zeros(n, dtype=bool)
        return Signals(el, z, z.copy(), z.copy())
    return SimpleNamespace(signals=signals)


def _barras(ate: datetime):
    ts = np.arange(np.datetime64("2026-10-09T09:00", "ns"),
                   np.datetime64(ate, "ns") + np.timedelta64(1, "m"),
                   np.timedelta64(1, "m"))
    n = len(ts)
    base = np.full(n, 189_000, dtype=np.int64)
    return {"ts": ts, "open": base, "high": base + 50, "low": base - 50,
            "close": base, "tick_volume": np.zeros(n, np.int64),
            "volume": np.zeros(n, np.int64)}


def test_sem_provisoria_a_entrada_so_aparece_no_minuto_seguinte():
    assert papel.calcular(_barras(SINAL), DIA, PLANO, _mod(), INST) == []


def test_com_provisoria_a_entrada_aparece_ja_as_10_01_aberta():
    b = papel.com_barra_provisoria(_barras(SINAL), SINAL + timedelta(minutes=1), 189_100)
    ops = papel.calcular(b, DIA, PLANO, _mod(), INST)
    assert len(ops) == 1 and ops[0]["aberta"]
    assert ops[0]["entry_ts"] == SINAL + timedelta(minutes=1)


def test_provisoria_da_a_mesma_entrada_que_o_candle_real():
    prov = papel.com_barra_provisoria(_barras(SINAL), SINAL + timedelta(minutes=1), 189_100)
    real = _barras(SINAL + timedelta(minutes=1))
    real["open"] = real["open"].copy()
    real["open"][-1] = 189_100                        # a abertura que o MT5 mostrou
    real = papel.com_barra_provisoria(real, SINAL + timedelta(minutes=2), 189_120)
    a = papel.calcular(prov, DIA, PLANO, _mod(), INST)[0]
    b = papel.calcular(real, DIA, PLANO, _mod(), INST)[0]
    assert (a["entry_ts"], a["entry_px"], a["side"], a["stop_px"], a["alvo_px"]) == \
           (b["entry_ts"], b["entry_px"], b["side"], b["stop_px"], b["alvo_px"])


def test_provisoria_repetida_velha_ou_depois_de_buraco_nao_entra():
    b = _barras(SINAL)
    assert papel.com_barra_provisoria(b, SINAL, 1) is b
    assert papel.com_barra_provisoria(b, SINAL + timedelta(minutes=3), 1) is b
    assert papel.com_barra_provisoria(None, SINAL, 1) is None
    c = papel.com_barra_provisoria(b, SINAL + timedelta(minutes=1), 189_100)
    assert len(c["ts"]) == len(b["ts"]) + 1
    assert c["open"][-1] == c["high"][-1] == c["low"][-1] == c["close"][-1] == 189_100
```

- [ ] **Step 2: Rodar e ver falhar** — `test_com_provisoria...` FAIL (`com_barra_provisoria` não existe).

- [ ] **Step 3: Implementar** — em `core/papel.py`, depois de `checksum`:

```python
def com_barra_provisoria(barras: dict | None, ts: datetime,
                         abertura: int) -> dict | None:
    """As barras do dia com o minuto EM FORMAÇÃO, provisório: abertura,
    máxima, mínima e fechamento iguais à abertura dele.

    O motor só cria a entrada (ou a saída por sinal) do sinal da barra i
    quando a barra i+1 existe (`kernel.py`, "sinais desta barra, para a
    próxima") — e a captura nunca grava o candle em formação. Sem isto o
    papel ao vivo, e com ele a ordem da demo, sairia sempre um minuto
    atrasado. Com a barra provisória a entrada aparece no primeiro segundo
    do minuto, ao preço de abertura — o mesmo do backtest. Nunca é gravada
    em bars_m1: o candle real a substitui no minuto seguinte.
    """
    if barras is None:
        return None
    t = np.datetime64(ts, "ns")
    # só cola no minuto seguinte ao último candle: com um buraco (candles
    # atrasados no banco), a provisória viraria a "barra seguinte" de um
    # sinal velho e inventaria uma entrada
    if not len(barras["ts"]) or barras["ts"][-1] != t - np.timedelta64(1, "m"):
        return barras
    a = int(abertura)
    out = {}
    for k, v in barras.items():
        novo = t if k == "ts" else (a if k in ("open", "high", "low", "close") else 0)
        out[k] = np.append(v, np.array([novo], dtype=v.dtype))
    return out
```

Dividir `rodar_dia`: mover para `preparar_dia(con, dia, agora, cache_codigo, *, symbol=SIMBOLO)` todo o corpo de `rodar_dia` **depois** de `if not _tem_candle(...): return []` e **até** `if not fila: return resultados` (inclusive o laço de ligações); `preparar_dia` devolve `(resultados, fila, planos)`. `rodar_dia` fica:

```python
def rodar_dia(con, dia: date, agora: datetime, cache_codigo: dict, *,
              symbol: str = SIMBOLO, dia_encerrado: bool = False,
              provisoria: tuple[datetime, int] | None = None) -> list[dict]:
    """(docstring atual, mais:) `provisoria = (minuto, abertura)` do candle
    em formação — só no pregão vivo; a conferência nunca a usa."""
    if not _tem_candle(con, symbol, dia):
        return []
    resultados, fila, planos = preparar_dia(con, dia, agora, cache_codigo,
                                            symbol=symbol)
    if not fila:
        return resultados
    # ... (resto igual: falhas, aquecimento, barras_do_dia, calcular) e,
    # logo depois de `barras = barras_do_dia(con, symbol, dia, aquecimento)`:
        if (provisoria is not None and not dia_encerrado
                and provisoria[0].date() == dia):
            barras = com_barra_provisoria(barras, *provisoria)
```

- [ ] **Step 4: Rodar** — `pytest -q tests/test_papel_provisoria.py tests/test_papel*.py tests/test_captura*.py` → PASS (os testes atuais do papel provam que a divisão não mudou nada).
- [ ] **Step 5: Mutação** — agente `mutacao` em `com_barra_provisoria` (ex.: usar `>` em vez de `>=`, fechamento ≠ abertura): os testes pegam.
- [ ] **Step 6: Commit** — `core/papel.py tests/test_papel_provisoria.py` → `feat(papel): barra provisoria do minuto em formacao`.

---

### Task 6: `core/papel_vivo.py` — retrato, aquecimento e desejado

**Files:**
- Create: `core/papel_vivo.py`
- Test: `tests/test_papel_vivo.py`

**Interfaces:**
- Consumes: `papel.preparar_dia`, `papel.calcular`, `papel.com_barra_provisoria`, `papel.periodos_ligados`, `papel._conta`, `papel.perfil_do_plano`, `papel.pregoes_de_aquecimento`, `engine.execution.prepare_bars`.
- Produces:
  - `POSICAO, ZERADO, INDISPONIVEL` (str).
  - `@dataclass(frozen=True) Desejado(estado, lado=0, entry_ts=None, entry_px=None, stop_px=None, alvo_px=None, contratos=0, motivo=None)`.
  - `@dataclass LigacaoViva(ligacao_id, portfolio_id, status, motivo, plano, modulo, periodos, fase, conta_id, contratos_conta, ligada, falha, desvio)` — `ligada` = `pm.ligada AND portfolio.ligado` agora; `falha` = o `falha` do resultado de `preparar_dia`; `desvio` = deviation em pontos.
  - Teste a mais: preparo com falha (ex.: `codigo.hash_estrategia` levantando) → `INDISPONIVEL`, nunca `ZERADO`.
  - `@dataclass Retrato(dia, lido_em, ligacoes: dict[int, LigacaoViva], contas: dict[int, dict], portfolio_de: dict[int, int])` — `contas[id] = {"login", "servidor", "limite", "envio"}`.
  - `ler_retrato(con, dia, agora, cache_codigo, *, symbol="WIN$N") -> Retrato`.
  - `carregar_aquecimento(con, symbol, dia, retrato) -> dict | None`.
  - `barras_de_hoje(df: polars.DataFrame) -> dict` (formato de `prepare_bars`).
  - `desejados(retrato, aquecimento, hoje, provisoria, inst, agora_srv) -> tuple[dict[int, Desejado], bool]` — o bool é "disponível".

- [ ] **Step 1: Teste falhando** — `tests/test_papel_vivo.py`. Monte a base com a fixture `base` de `tests/test_captura_processo.py` (copie a fixture) e crie portfólio/variante/plano/ligação com os helpers que `tests/test_papel_motor.py` já usa para isso (**leia esse arquivo e reaproveite os helpers de criação de plano/ligação**; se forem locais, mova-os para `tests/fabrica_ao_vivo.py` e importe dos dois lados — o teste antigo continua passando). Casos:

```python
# esqueleto — cada caso com asserts concretos; use _mod() e PLANO como na
# Tarefa 5 (estratégia stub registrada via monkeypatch em papel._modulo)

def test_posicao_quando_o_papel_tem_aberta_e_a_ligacao_opera(...):
    # ligação em fase demo, ligada desde 09:00; sinal às 10:00
    # desejados(...) com provisória 10:01 -> estado POSICAO, lado 1,
    # entry_ts 10:01, stop_px = entrada - 200 (pontos do plano), contratos
    # = contratos_demo da ligação (ou do plano se NULL)

def test_zerado_quando_a_ligacao_esta_desligada_agora(...):
    # desligada às 10:20 (ao_vivo.desligar_membro); operação entrou às
    # 10:01 e o papel ainda a tem aberta -> ZERADO (ligada AGORA, pelo
    # estado atual pm.ligada/portfolio.ligado — spec §6.4 caso 13)

def test_zerado_quando_fase_nao_e_demo(...):
    # fase 'papel' com operação aberta -> ZERADO

def test_zerado_quando_pulado_ou_sem_plano(...):

def test_indisponivel_sem_aquecimento_ou_sem_relogio(...):
    # aquecimento None -> ({}, False); agora_srv None -> ({}, False)

def test_indisponivel_so_da_ligacao_cujo_calculo_falhou(...):
    # módulo que levanta no signals -> essa ligação INDISPONIVEL, a outra
    # segue com o seu estado

def test_barras_de_hoje_converte_o_dataframe_do_mt5(...):
    # polars com ts/open/high/low/close/tick_volume/volume float ->
    # dict com int64 e datetime64[ns], mesma ordem
```

Escreva os sete testes por inteiro (dados e asserts concretos, sem "…") antes de implementar.

- [ ] **Step 2: Rodar e ver falhar** → FAIL (módulo não existe).

- [ ] **Step 3: Implementar** — `core/papel_vivo.py`:

```python
"""Papel ao vivo para as ordens: o desejado de cada ligação, sem banco.

Spec 2026-10-08-ao-vivo-ordens-design.md §3 e §5.1. O papel gravado no
banco (`papel.rodar_dia` + `gravar`) continua sendo o da tela e da
conferência; este módulo calcula A MESMA COISA, com as mesmas funções, só
que de um retrato da configuração e de barras em memória — uma mineração
segurando o banco não pode atrasar uma saída. Quem escolhe as ligações e o
plano do dia é `papel.preparar_dia`, a mesma régua do papel gravado.

Três estados por ligação: POSICAO (o papel tem operação aberta que conta e
a ligação opera agora), ZERADO (sabidamente não tem — a corretora deve
estar zerada) e INDISPONIVEL (não dá para saber; a automação só protege).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
import polars as pl

from . import db_manager as db
from . import papel
from .engine.execution import prepare_bars

POSICAO, ZERADO, INDISPONIVEL = "posicao", "zerado", "indisponivel"


@dataclass(frozen=True)
class Desejado:
    estado: str
    lado: int = 0
    entry_ts: datetime | None = None
    entry_px: int | None = None
    stop_px: int | None = None
    alvo_px: int | None = None
    contratos: int = 0
    motivo: str | None = None


@dataclass
class LigacaoViva:
    ligacao_id: int
    portfolio_id: int | None
    status: str
    motivo: str | None
    plano: dict | None
    modulo: object | None
    periodos: list = field(default_factory=list)
    fase: str = "papel"
    conta_id: int | None = None
    contratos_conta: int | None = None
    ligada: bool = False          # pm.ligada AND portfolio.ligado, AGORA
    falha: str | None = None      # o preparo do papel falhou (não é "zerado")
    desvio: int = 0               # deviation da ordem, em pontos


@dataclass
class Retrato:
    dia: date
    lido_em: datetime
    ligacoes: dict
    contas: dict
    portfolio_de: dict


def ler_retrato(con, dia: date, agora: datetime, cache_codigo: dict, *,
                symbol: str = papel.SIMBOLO) -> Retrato:
    resultados, fila, planos = papel.preparar_dia(con, dia, agora, cache_codigo,
                                                  symbol=symbol)
    na_fila = {l["ligacao_id"]: (l, p) for _, l, p in fila}
    # "ligada agora" vem do estado atual das duas chaves, não dos períodos
    # do diário: o diário usa a hora do PC, e com o PC adiantado uma
    # variante desligada ainda entraria por alguns segundos (os períodos
    # ficam só para o `conta` de cada operação, como no papel gravado)
    meta = {r[0]: r[1:] for r in con.execute(
        "SELECT pm.ligacao_id, pm.portfolio_id, pm.fase, p.conta_demo_id, "
        "pm.contratos_demo, pm.ligada AND coalesce(p.ligado, false) "
        "FROM portfolio_membros pm "
        "JOIN portfolios p ON p.portfolio_id = pm.portfolio_id").fetchall()}
    tick = int(db.load_instrument_yaml(symbol)["tick_size"])
    ligs = {}
    for r in resultados:
        lig = r["ligacao_id"]
        pf, fase, conta, contratos, ligada = meta.get(
            lig, (None, "papel", None, None, False))
        lp = na_fila.get(lig)
        plano = lp[1] if lp else None
        desvio = 2 * tick
        if plano is not None:
            _, perfil = papel.perfil_do_plano(plano)
            desvio += int(round(float(perfil.slippage_ticks or 0) * tick))
        ligs[lig] = LigacaoViva(
            ligacao_id=lig, portfolio_id=pf, status=r["status"], motivo=r["motivo"],
            plano=plano,
            modulo=planos[lp[0]["plano_id"]][1] if lp else None,
            periodos=papel.periodos_ligados(con, lig, pf, dia) if pf else [],
            fase=fase, conta_id=conta,
            contratos_conta=int(contratos) if contratos else None,
            ligada=bool(ligada), falha=r.get("falha"), desvio=desvio)
    contas = {int(r[0]): {"login": r[1], "servidor": r[2], "limite": r[3],
                          "envio": bool(r[4])}
              for r in con.execute(
                  "SELECT conta_id, login, servidor, limite_perda_dia, "
                  "coalesce(envio_ligado, false) FROM contas "
                  "WHERE arquivada_em IS NULL").fetchall()}
    return Retrato(dia=dia, lido_em=agora, ligacoes=ligs, contas=contas,
                   portfolio_de={lig: v[0] for lig, v in meta.items()})


def carregar_aquecimento(con, symbol: str, dia: date, retrato: Retrato) -> dict | None:
    """Os pregões ANTES do dia, uma vez por pregão: o maior aquecimento entre
    as ligações do retrato (mesma conta de `papel.pregoes_de_aquecimento`)."""
    pregoes = 1
    for lv in retrato.ligacoes.values():
        if lv.plano is None or lv.modulo is None:
            continue
        try:       # um plano quebrado não derruba o aquecimento dos outros
            estrat, perfil = papel.perfil_do_plano(lv.plano)
            pregoes = max(pregoes, papel.pregoes_de_aquecimento(lv.modulo, estrat, perfil))
        except Exception:
            continue
    ini = datetime.combine(dia, time())
    datas = con.execute(
        "SELECT DISTINCT CAST(ts AS DATE) AS d FROM bars_m1 WHERE symbol = ? "
        "AND ts < ? ORDER BY d DESC LIMIT ?", [symbol, ini, pregoes]).fetchall()
    if not datas:
        return None
    return prepare_bars(con, symbol, start=datetime.combine(min(r[0] for r in datas), time()),
                        end=ini - timedelta(microseconds=1))


def barras_de_hoje(df: pl.DataFrame) -> dict:
    """O que a captura buscou no MT5 (`mt5_source.barras_de_taxas`), no
    formato de `prepare_bars`. Preço com 0 casas (`price_decimals` do WIN)."""
    def inteiro(c):
        return np.rint(df[c].to_numpy()).astype(np.int64)
    return {"ts": df["ts"].to_numpy().astype("datetime64[ns]"),
            "open": inteiro("open"), "high": inteiro("high"),
            "low": inteiro("low"), "close": inteiro("close"),
            "tick_volume": inteiro("tick_volume"), "volume": inteiro("volume")}


def _juntar(a: dict, b: dict) -> dict:
    return {k: np.concatenate([a[k], b[k]]) for k in a}


def _ligada(agora: datetime, periodos) -> bool:
    return any(a <= agora < b for a, b in periodos)


def desejados(retrato: Retrato | None, aquecimento: dict | None, hoje: dict | None,
              provisoria: tuple[datetime, int] | None, inst: dict,
              agora_srv: datetime | None) -> tuple[dict, bool]:
    if (retrato is None or aquecimento is None or hoje is None
            or agora_srv is None or retrato.dia != agora_srv.date()):
        return {}, False
    barras = _juntar(aquecimento, hoje)
    if provisoria is not None and provisoria[0].date() == retrato.dia:
        barras = papel.com_barra_provisoria(barras, *provisoria)
    out: dict[int, Desejado] = {}
    calculados: dict[int, list] = {}
    for lig, lv in retrato.ligacoes.items():
        if lv.falha:
            # falha no preparo (plano, hash do código): não se sabe — protege
            out[lig] = Desejado(INDISPONIVEL, motivo=lv.falha)
            continue
        if lv.status != "rodando" or lv.plano is None:
            out[lig] = Desejado(ZERADO, motivo=lv.motivo or lv.status)
            continue
        if lv.fase != "demo":
            out[lig] = Desejado(ZERADO, motivo="fase papel")
            continue
        if not lv.ligada:
            out[lig] = Desejado(ZERADO, motivo="desligada")
            continue
        pid = lv.plano["plano_id"]
        try:
            if pid not in calculados:
                calculados[pid] = papel.calcular(barras, retrato.dia, lv.plano,
                                                 lv.modulo, inst)
        except Exception as erro:          # uma ligação não derruba as outras
            out[lig] = Desejado(INDISPONIVEL, motivo=f"falha no cálculo: {erro}")
            continue
        abertas = [o for o in calculados[pid]
                   if o["aberta"] and papel._conta(o["entry_ts"], lv.periodos)]
        if not abertas:
            out[lig] = Desejado(ZERADO)
            continue
        o = abertas[-1]
        out[lig] = Desejado(POSICAO, lado=int(o["side"]), entry_ts=o["entry_ts"],
                            entry_px=int(o["entry_px"]), stop_px=o["stop_px"],
                            alvo_px=o["alvo_px"],
                            contratos=lv.contratos_conta or int(lv.plano["contratos"]))
    return out, True
```

- [ ] **Step 4: Rodar** — `pytest -q tests/test_papel_vivo.py` → PASS.
- [ ] **Step 5: Teste de igualdade com o papel gravado** — acrescente a `tests/test_papel_vivo.py` um teste que, para a mesma base e o mesmo instante, compara `desejados(...)` com o que `papel.rodar_dia(..., provisoria=...)` grava como aberta (mesmo `entry_ts`, `side`, `entry_px`, `stop_px`, `alvo_px`). É ele que impede os dois caminhos de divergirem.
- [ ] **Step 6: Mutação** — agente `mutacao` em `desejados` (ex.: remover o `_ligada`, trocar `abertas[-1]` por `[0]`, ignorar `_conta`).
- [ ] **Step 7: Commit** — `core/papel_vivo.py tests/test_papel_vivo.py` (+ `tests/fabrica_ao_vivo.py` se criado) → `feat(ordens): papel vivo sem banco no caminho da ordem`.

---

### Task 7: `ordens.planejar` — desejado × corretora → ações

**Files:**
- Create: `core/ordens.py` (só `Acao`, constantes e `planejar` nesta tarefa)
- Test: `tests/test_ordens_planejar.py`

**Interfaces:**
- Consumes: `papel_vivo.Desejado/POSICAO/ZERADO/INDISPONIVEL`, `corretora.Fotografia/Posicao/Negocio/protecao`, `diario_ordens.Diario`.
- Produces:
  - `JANELA_ENTRADA_S = 30`, `GRACA_RECONEXAO_S = 5`, `INTERVALO_S = 1.0`, `INCERTA_ESPERA_S = 3.0`, `SEM_PROTECAO_S = 2.0`, `ORDEM_VELHA_S = 5.0`.
  - `@dataclass(frozen=True) Acao(tipo: str, ligacao_id: int, desejado=None, ticket=None, posicao=None, motivo=None)`; `tipo ∈ {"entrar", "sair", "proteger", "adotar", "saiu_antes", "perdida", "cancelar"}` (`cancelar`: `ticket` é o da ORDEM pendente).
  - Usa da Fotografia (Tarefa 3, correções): `ordens[i]["quando"]` e `historico_ordens`.
  - `planejar(desejados: dict, disponivel: bool, foto: Fotografia, diario: Diario, agora_srv: datetime | None, tick: int, conectado_ha_s: float) -> list[Acao]` — pura, sem MT5.

- [ ] **Step 1: Teste falhando** — `tests/test_ordens_planejar.py`. Um teste por linha da tabela do §5.1 e pelos casos 6, 7, 9, 11, 12, 13 do §6.4:

```python
"""Reconciliação (spec §5.1): uma linha da tabela, um teste."""
from datetime import date, datetime, timedelta

from core import corretora as K
from core.diario_ordens import Diario
from core.ordens import Acao, planejar
from core.papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado

T = datetime(2026, 10, 9, 10, 1)            # entrada do papel
D = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)


def pos(ticket, lig=4, lado=1, sl=188_800, tp=189_400, aberta=T):
    return K.Posicao(ticket=ticket, magic=K.magic(lig) if lig else 0, ligacao_id=lig,
                     simbolo="WINV26", lado=lado, volume=2, preco=189_005, sl=sl,
                     tp=tp, resultado=0.0, aberta_em=aberta)


def foto(posicoes=(), ordens=(), negocios=()):
    return K.Fotografia(posicoes=list(posicoes), ordens=list(ordens),
                        negocios=list(negocios), login=1, servidor="s",
                        hedging=True, margem_livre=1e4, algo_ligado=True)


def plan(tmp_path, desejados, f, agora=T + timedelta(seconds=1), disponivel=True,
         conectado=60.0, diario=None):
    d = diario or Diario(tmp_path, date(2026, 10, 9))
    return planejar(desejados, disponivel, f, d, agora, 5, conectado)


def tipos(acoes):
    return [(a.tipo, a.ligacao_id, a.ticket) for a in acoes]


def test_entra_dentro_dos_30_s(tmp_path):
    assert tipos(plan(tmp_path, {4: D}, foto())) == [("entrar", 4, None)]


def test_depois_de_30_s_registra_perdida_uma_vez(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    a = plan(tmp_path, {4: D}, foto(), agora=T + timedelta(seconds=31), diario=d)
    assert tipos(a) == [("perdida", 4, None)]
    assert a[0].motivo == "automação fora do ar"
    d.registrar("perdida", quando=T, ligacao_id=4, entry_ts=T)
    assert plan(tmp_path, {4: D}, foto(), agora=T + timedelta(seconds=40), diario=d) == []


def test_sem_entrada_nos_5_s_apos_reconectar(tmp_path):
    assert plan(tmp_path, {4: D}, foto(), conectado=2.0) == []


def test_posicao_com_o_ticket_e_protecao_certa_nao_faz_nada(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    assert plan(tmp_path, {4: D}, foto([pos(10)]), diario=d) == []


def test_stop_do_papel_mudou_pede_protecao(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    a = plan(tmp_path, {4: D}, foto([pos(10, sl=188_700)]), diario=d)
    assert tipos(a) == [("proteger", 4, 10)]


def test_stop_fora_do_tick_nao_vira_modificacao_por_volta(tmp_path):
    # caso 22: stop por ATR 188_803 -> corretora com 188_800 (arredondado)
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    atr = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_803,
                   alvo_px=189_400, contratos=2)
    assert plan(tmp_path, {4: atr}, foto([pos(10, sl=188_800)]), diario=d) == []


def test_zerado_com_posicao_sai(tmp_path):
    a = plan(tmp_path, {4: Desejado(ZERADO)}, foto([pos(10)]))
    assert tipos(a) == [("sair", 4, 10)]


def test_ligacao_fora_do_retrato_com_posicao_sai(tmp_path):
    # removida/fase papel/Envio desligado: o universo inclui a posição pelo magic
    assert tipos(plan(tmp_path, {}, foto([pos(10, lig=9)]))) == [("sair", 9, 10)]


def test_indisponivel_nao_entra_nem_sai(tmp_path):
    # caso 6: reinício antes do primeiro cálculo, com posições abertas
    assert plan(tmp_path, {}, foto([pos(10), pos(11, lig=5)]), disponivel=False) == []
    assert plan(tmp_path, {4: Desejado(INDISPONIVEL)}, foto([pos(10)])) == []


def test_posicao_a_mao_nunca_e_tocada(tmp_path):
    assert plan(tmp_path, {}, foto([pos(10, lig=None)])) == []


def test_ordem_em_transito_espera_e_a_velha_e_cancelada(tmp_path):
    em = {"ticket": 99, "magic": K.magic(4), "ligacao_id": 4, "simbolo": "WINV26",
          "volume": 2.0, "quando": T}
    assert plan(tmp_path, {4: D}, foto(ordens=[em])) == []
    # resto de parcial / PLACED esquecido há mais de 5 s: cancela
    a = plan(tmp_path, {4: D}, foto(ordens=[em]), agora=T + timedelta(seconds=6))
    assert tipos(a) == [("cancelar", 4, 99)]
    # papel zerado: cancela na hora (não pode prender o "Zerar tudo")
    a = plan(tmp_path, {4: Desejado(ZERADO)}, foto(ordens=[em]))
    assert tipos(a) == [("cancelar", 4, 99)]


def test_resposta_perdida_adota_a_posicao_em_vez_de_reenviar(tmp_path):
    # caso 3: executou, a resposta não chegou
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    a = plan(tmp_path, {4: D}, foto([pos(10)]), diario=d)
    assert tipos(a) == [("adotar", 4, 10)]


def saida(ticket, motivo=4, quando=T + timedelta(seconds=30)):
    return K.Negocio(ticket=900 + ticket, posicao=ticket, magic=K.magic(4),
                     ligacao_id=4, simbolo="WINV26", entrada=False, lado=-1,
                     volume=2, preco=188_800, resultado=-80.0, motivo=motivo,
                     quando=quando)


def test_ja_saiu_na_corretora_nao_reentra(tmp_path):
    # SL do servidor antes do papel, ou o usuário fechou à mão (caso 12)
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    a = plan(tmp_path, {4: D}, foto(negocios=[saida(10)]), diario=d)
    assert tipos(a) == [("saiu_antes", 4, 10)]
    d.registrar("saiu_antes", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    assert plan(tmp_path, {4: D}, foto(negocios=[saida(10)]), diario=d) == []


def test_lista_vazia_logo_apos_reconectar_nao_vira_saiu_antes(tmp_path):
    # I2: a posição está viva; o MT5 só não sincronizou — espera
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    assert plan(tmp_path, {4: D}, foto(), diario=d, conectado=1.0) == []
    # e sem negócio de saída, também não (pode ser só atraso da lista)
    assert plan(tmp_path, {4: D}, foto(), diario=d) == []


def test_executou_pelo_historico_mesmo_sem_ticket_nao_reentra(tmp_path):
    entrada = K.Negocio(ticket=1, posicao=10, magic=K.magic(4), ligacao_id=4,
                        simbolo="WINV26", entrada=True, lado=1, volume=2,
                        preco=189_005, resultado=0, motivo=3,
                        quando=T + timedelta(milliseconds=500))
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    a = plan(tmp_path, {4: D}, foto(negocios=[entrada, saida(10)]), diario=d)
    assert tipos(a) == [("saiu_antes", 4, 10)]


def test_papel_zerado_registra_a_saida_pelo_servidor(tmp_path):
    # I14 (caso 2): às 10:02 o papel já zerou e a posição saiu pelo SL
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    a = plan(tmp_path, {4: Desejado(ZERADO)}, foto(negocios=[saida(10)]), diario=d)
    assert tipos(a) == [("saiu_antes", 4, 10)]


def test_perdida_nao_volta_a_tentar_dentro_da_janela(tmp_path):
    # I3: sem margem -> perdida + chamado; nada de 300 order_check em 30 s
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    d.registrar("perdida", quando=T, ligacao_id=4, entry_ts=T, motivo="sem margem")
    assert plan(tmp_path, {4: D}, foto(), diario=d) == []


def test_intervalo_minimo_de_1_s_entre_tentativas(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T + timedelta(seconds=1), ligacao_id=4, entry_ts=T)
    d.registrar("recusada", quando=T + timedelta(seconds=1), ligacao_id=4, entry_ts=T)
    assert plan(tmp_path, {4: D}, foto(), diario=d,
                agora=T + timedelta(seconds=1, milliseconds=500)) == []
    assert tipos(plan(tmp_path, {4: D}, foto(), diario=d,
                      agora=T + timedelta(seconds=2))) == [("entrar", 4, None)]


def test_incerta_espera_3_s_e_nao_reenvia_se_o_historico_tem_a_ordem(tmp_path):
    # C2: timeout/None — a ordem pode ter executado
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    d.registrar("incerta", quando=T, ligacao_id=4, entry_ts=T)
    assert plan(tmp_path, {4: D}, foto(), diario=d, agora=T + timedelta(seconds=2)) == []
    hist = {"ticket": 77, "magic": K.magic(4), "ligacao_id": 4,
            "quando": T + timedelta(milliseconds=200)}
    f = foto()
    f.historico_ordens = [hist]
    assert plan(tmp_path, {4: D}, f, diario=d, agora=T + timedelta(seconds=4)) == []
    assert tipos(plan(tmp_path, {4: D}, foto(), diario=d,
                      agora=T + timedelta(seconds=4))) == [("entrar", 4, None)]


def test_posicao_sem_protecao_ha_mais_de_2_s_e_encerrada(tmp_path):
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T, ligacao_id=4, entry_ts=T, ticket=10)
    nua = pos(10, sl=0.0, tp=0.0)
    assert tipos(plan(tmp_path, {4: D}, foto([nua]), diario=d)) == [("proteger", 4, 10)]
    a = plan(tmp_path, {4: D}, foto([nua]), diario=d, agora=T + timedelta(seconds=3))
    assert tipos(a) == [("sair", 4, 10)]


def test_operacao_anterior_que_nao_saiu_sai_e_a_nova_entra(tmp_path):
    # caso 9: a de 10:00 foi stopada no papel mas não no servidor; a nova,
    # do mesmo lado, é de 10:01 — casa por ticket, não por lado
    d = Diario(tmp_path, date(2026, 10, 9))
    d.registrar("executada", quando=T - timedelta(minutes=1), ligacao_id=4,
                entry_ts=T - timedelta(minutes=1), ticket=10)
    velha = pos(10, aberta=T - timedelta(minutes=1))
    a = plan(tmp_path, {4: D}, foto([velha]), diario=d)
    assert tipos(a) == [("sair", 4, 10), ("entrar", 4, None)]


def test_sem_relogio_nao_entra(tmp_path):
    assert plan(tmp_path, {4: D}, foto(), agora=None) == []
```

- [ ] **Step 2: Rodar e ver falhar** → FAIL.

- [ ] **Step 3: Implementar** — `core/ordens.py`:

```python
"""O motor de ordens: o papel decide, a corretora executa, isto reconcilia.

Spec 2026-10-08-ao-vivo-ordens-design.md §5–6. `planejar` é puro: recebe o
desejado de cada ligação (papel_vivo), a fotografia da conta (corretora) e
o diário, e devolve ações. Idempotente: rodar duas vezes seguidas não pede
nada a mais. Quem executa é o `Motor` (mesmo arquivo).

Regras que este arquivo não pode esquecer:
- casar posição pela OPERAÇÃO (ticket gravado no diário), nunca pelo lado;
- INDISPONIVEL não entra nem sai (reinício não pode zerar posição boa);
- a saída vale para toda posição com magic da automação, mesmo de ligação
  que deixou de operar; posição sem o magic (à mão) nunca é tocada;
- ordem em trânsito (inclusive PLACED) bloqueia nova ordem da ligação.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import corretora as K
from .papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado

JANELA_ENTRADA_S = 30
GRACA_RECONEXAO_S = 5
INTERVALO_S = 1.0          # entre tentativas da mesma ação (evita o 10024)
INCERTA_ESPERA_S = 3.0     # sem resposta: espera o histórico antes de reenviar
SEM_PROTECAO_S = 2.0       # posição sem SL/TP além disso é encerrada
ORDEM_VELHA_S = 5.0        # ordem pendente com o magic além disso é cancelada


@dataclass(frozen=True)
class Acao:
    tipo: str          # entrar|sair|proteger|adotar|saiu_antes|perdida|cancelar
    ligacao_id: int
    desejado: Desejado | None = None
    ticket: int | None = None
    posicao: K.Posicao | None = None
    motivo: str | None = None


def _seg(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds()


def _pode(ultima, agora) -> bool:
    return ultima is None or _seg(agora, ultima) >= INTERVALO_S


def _executou(foto, lig, entry_ts) -> int | None:
    """Ticket da posição se o histórico do dia tem a entrada dela depois do
    início da operação (executou sem a resposta ter chegado)."""
    for n in foto.negocios:
        if n.entrada and n.ligacao_id == lig and n.quando >= entry_ts:
            return n.posicao
    return None


def _saiu(foto, ticket) -> bool:
    return any(not n.entrada and n.posicao == ticket for n in foto.negocios)


def planejar(desejados: dict, disponivel: bool, foto, diario, agora_srv,
             tick: int, conectado_ha_s: float) -> list[Acao]:
    if not disponivel or agora_srv is None:
        return []          # não dá para saber: só a proteção que já está lá vale
    estavel = conectado_ha_s >= GRACA_RECONEXAO_S
    acoes: list[Acao] = []
    pendentes: dict[int, list[dict]] = {}
    for o in foto.ordens:
        if o["ligacao_id"]:
            pendentes.setdefault(o["ligacao_id"], []).append(o)
    ligs = (set(desejados) | {p.ligacao_id for p in foto.posicoes if p.ligacao_id}
            | set(pendentes))
    for lig in sorted(ligs):
        d = desejados.get(lig) or Desejado(ZERADO, motivo="fora do papel de hoje")
        if d.estado == INDISPONIVEL:
            continue
        if lig in pendentes:
            # PLACED esperando a bolsa, ou resto de parcial: espera; velha ou
            # com o papel zerado, cancela (não pode prender a saída)
            for o in pendentes[lig]:
                if d.estado == ZERADO or _seg(agora_srv, o["quando"]) > ORDEM_VELHA_S:
                    acoes.append(Acao("cancelar", lig, ticket=o["ticket"],
                                      motivo="ordem pendente"))
            continue
        pos = [p for p in foto.posicoes if p.ligacao_id == lig]

        if d.estado == ZERADO:
            for p in pos:
                if _pode(diario.ultima_tentativa("saida_enviando", ticket=p.ticket),
                         agora_srv):
                    acoes.append(Acao("sair", lig, ticket=p.ticket, posicao=p,
                                      motivo=d.motivo or "papel zerado"))
            if estavel:
                vivos = {p.ticket for p in pos}
                for t, ts in diario.tickets_abertos(lig):
                    if t not in vivos and _saiu(foto, t):
                        acoes.append(Acao("saiu_antes", lig, ticket=t,
                                          desejado=Desejado(ZERADO, entry_ts=ts)))
            continue

        # POSICAO
        ts = d.entry_ts
        ticket = diario.ticket(lig, ts)
        minha = next((p for p in pos if p.ticket == ticket), None) if ticket else None
        if minha is None and ticket is None and diario.enviada(lig, ts):
            candidatas = [p for p in pos if p.lado == d.lado and p.aberta_em >= ts]
            if len(candidatas) == 1:
                minha = candidatas[0]
                acoes.append(Acao("adotar", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
        for p in pos:
            if (minha is None or p.ticket != minha.ticket) and _pode(
                    diario.ultima_tentativa("saida_enviando", ticket=p.ticket), agora_srv):
                acoes.append(Acao("sair", lig, ticket=p.ticket, posicao=p,
                                  motivo="posição que não é a operação atual"))
        if minha is not None:
            sl, tp = K.protecao(d.lado, d.stop_px, d.alvo_px, tick)
            nua = round(minha.sl) == 0 and round(minha.tp) == 0
            desde = diario.executada_em(lig, ts) or minha.aberta_em
            if nua and _seg(agora_srv, desde) > SEM_PROTECAO_S:
                acoes.append(Acao("sair", lig, ticket=minha.ticket, posicao=minha,
                                  motivo="posição sem proteção na corretora"))
            elif ((sl or 0) != round(minha.sl) or (tp or 0) != round(minha.tp)) and _pode(
                    diario.ultima_tentativa("protecao_enviando", ticket=minha.ticket),
                    agora_srv):
                acoes.append(Acao("proteger", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
            continue

        # a corretora não tem a posição desta operação
        ja = ticket or _executou(foto, lig, ts)
        if ja is not None:
            # executou: só registra a saída com o negócio de saída na mão e a
            # lista estável — logo após reconectar ela vem vazia por engano
            if estavel and _saiu(foto, ja) and not diario.registrado(lig, ts, "saiu_antes"):
                acoes.append(Acao("saiu_antes", lig, desejado=d, ticket=ja))
            continue
        if any(diario.registrado(lig, ts, t)
               for t in ("perdida", "nao_entrou", "seria_enviada")):
            continue
        ultimo = diario.ultimo(lig, ts)
        if ultimo is not None and ultimo["tipo"] == "incerta":
            if _seg(agora_srv, ultimo["quando"]) < INCERTA_ESPERA_S:
                continue
            if any(o["ligacao_id"] == lig and o["quando"] >= ts
                   for o in foto.historico_ordens):
                continue      # a ordem existe: o desfecho aparece nas próximas voltas
        if _seg(agora_srv, ts) <= JANELA_ENTRADA_S:
            if estavel and _pode(diario.ultima_tentativa("enviando", lig=lig, entry_ts=ts),
                                 agora_srv):
                acoes.append(Acao("entrar", lig, desejado=d))
        else:
            acoes.append(Acao("perdida", lig, desejado=d,
                              motivo=diario.ultimo_motivo(lig, ts)
                              or "automação fora do ar"))
    return acoes
```

- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Mutação** — agente `mutacao` em `planejar`: remover o `if not disponivel`, casar por lado, trocar `<=` por `<` na janela, remover o bloqueio de ordens pendentes, remover a graça de reconexão, remover a espera da `incerta`, remover o `_pode` (intervalo de 1 s), registrar `saiu_antes` sem o negócio de saída. Todas pegas.
- [ ] **Step 6: Commit** — `core/ordens.py tests/test_ordens_planejar.py` → `feat(ordens): reconciliacao desejado x corretora`.

---

### Task 8: `ordens.Motor` — executar ações

**Files:**
- Modify: `core/ordens.py` (classe `Motor`)
- Test: `tests/test_ordens_motor.py`

**Interfaces:**
- Consumes: Tarefas 2–7.
- Produces:
  - `class Motor(pasta: Path, inst: dict, origem: str = "demo")`:
    - `executar(mt5, acoes, *, foto, agora_srv, simbolo, desvio, pode_entrar: Callable[[Acao], tuple[bool, str | None]], envio: bool, conta_id) -> None` — executa a lista na ordem: saídas primeiro, depois proteções, adoções/registros, entradas.
    - `diario(dia) -> Diario` (um por dia, reaberto na virada).
    - `chamados: dict[str, dict]` — chave → `{"tipo", "texto", "ligacao_id", "ticket", "desde"}`.
  - Regras do executor (spec §5.2–5.3, §6):
    - **Relógio:** `Motor(pasta, inst, origem="demo", relogio=None)` — `relogio()` devolve a hora do servidor **agora** (a captura passa `lambda: self.relogio.agora(self.mono())`); `atraso_ms` é medido **depois** da resposta do `order_send` (inclui a rede, que é o que se quer medir). Sem `relogio`, usa `agora_srv`.
    - **entrar:** `pode_entrar(acao)` falso → `nao_entrou` (uma vez por operação) com o motivo; `envio` falso → `seria_enviada` (uma vez) com o pedido que sairia, sem enviar. Senão: registra **`enviando` antes** do `order_check`/`order_send`; `order_check` com `retcode != 0` → trata o `retcode` pela tabela; preenchimento: tenta os modos de `modos_preenchimento` em ordem, só passa ao seguinte se a classe for `PREENCHIMENTO` (se todos derem `PREENCHIMENTO` → `perdida` + chamado "modo de preenchimento recusado"); pedido **sem SL/TP**; `OK`/`PARCIAL` → `executada`/`parcial` com `ticket` (lido de `positions_get(ticket=res.order)`; se vazio, a posição da ligação mais nova do mesmo lado; senão `res.order`), `preco`, `atraso_ms`, `preco_papel = entry_px`, e **na mesma chamada** `pedido_protecao` com `corretora.protecao(...)` (registra `protecao_enviando`; `OK` → `protecao`; `STOPS_INVALIDOS` → sai na hora; passageira → `protecao_recusada`, e a reconciliação tenta de novo até os 2 s); `PARCIAL` → cancela (`pedido_cancelar`) toda ordem pendente com o magic e registra `cancelada`; `ACEITA` → `aceita`; `INCERTA` → `incerta` (a reconciliação espera e confere o histórico); `PASSAGEIRA` → `recusada` (retcode, texto); `USUARIO`/`DESCONHECIDO` → chamado **e depois** `perdida` (o último evento da operação é a `perdida`); `CLOSE_ONLY` (10044) também marca `self.so_encerrar[simbolo] = True` (sem entradas nesse contrato no resto do dia); `STOPS_INVALIDOS` → `nao_entrou` "stop ou alvo inválido".
    - **sair:** usa o **contrato da posição** (`a.posicao.simbolo`, não o do dia) e o preço dele; registra `saida_enviando` (com `tentativa`); `OK`/`PARCIAL` → `saida_executada`; `JA_SAIU` → `saida_executada` com motivo "já encerrada"; `SAIDA_EM_TRANSITO`/`VOLUME_FECHAMENTO` → nada (a próxima volta relê); `INCERTA` → `saida_recusada` com motivo "sem resposta" (a próxima volta relê a corretora antes de mandar de novo, pelo intervalo de 1 s); outros → `saida_recusada`; se `diario.saida_desde(ticket)` tem mais de **120 s** → chamado `saida_pendente:<ticket>` (e continua tentando).
    - **proteger:** registra `protecao_enviando`; `pedido_protecao` com `corretora.protecao`; `OK`/`SEM_MUDANCA` → `protecao`; `STOPS_INVALIDOS` → sai a mercado na mesma volta; `JA_SAIU` → nada; outros → `protecao_recusada`.
    - **cancelar** → `pedido_cancelar(ordem=ticket)`; `OK` → `cancelada`.
    - **adotar** → `adotada` com ticket. **saiu_antes** → `saiu_antes` com o ticket e o motivo do negócio de saída (`DEAL_REASON_SL` → "stop na corretora", `TP` → "alvo na corretora", outro → "encerrada fora da automação"), com o `entry_ts` do desejado. **perdida** → `perdida`.
    - **Fechar chamados** a cada `executar` (I5): `saida_pendente:<ticket>` fecha na hora em que a saída executa (`saida_executada`) ou quando o ticket não está mais em `foto.posicoes`; os de operação fecham quando a operação vira `perdida`/`saiu_antes`. `_chamar`/`_fechar` usam `self.diario(dia)` (nunca `self._diario` cru).

- [ ] **Step 1: Teste falhando** — `tests/test_ordens_motor.py`, com `MT5Ordens` e `Diario` em `tmp_path`. Casos (cada um com asserts sobre `mt5.enviados`, `mt5.posicoes` e os tipos do diário):

```python
"""Executor (spec §5.2–5.3, §6.4): cada caso com o MT5 falso."""
from datetime import date, datetime, timedelta
from pathlib import Path

from core import corretora as K
from core.ordens import Acao, Motor, planejar
from core.papel_vivo import POSICAO, ZERADO, Desejado
from tests.mt5_falso import MT5Ordens

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
AG = T + timedelta(seconds=1)
D = Desejado(POSICAO, lado=1, entry_ts=T, entry_px=189_000, stop_px=188_800,
             alvo_px=189_400, contratos=2)
INST = {"tick_size": 5, "point_value": 0.2}


def volta(m, mt5, desejados, agora=AG, envio=True, pode=lambda a: (True, None),
          disponivel=True):
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar(desejados, disponivel, foto, m.diario(DIA), agora, 5, 60.0)
    m.executar(mt5, acoes, foto=foto, agora_srv=agora, simbolo="WINV26", desvio=10,
               pode_entrar=pode, envio=envio, conta_id=2)
    return [e["tipo"] for e in m.diario(DIA).eventos]


def test_entrada_registra_antes_de_enviar_e_grava_o_ticket(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    tipos = volta(m, mt5, {4: D})
    assert tipos == ["enviando", "executada", "protecao_enviando", "protecao"]
    req, prot = mt5.enviados
    assert "sl" not in req and req["magic"] == K.magic(4)
    assert req["type_filling"] == mt5.ORDER_FILLING_IOC      # máscara 3 -> IOC primeiro
    assert prot["action"] == 6 and prot["sl"] == 188_800 and prot["tp"] == 189_400
    ev = [e for e in m.diario(DIA).eventos if e["tipo"] == "executada"][0]
    assert ev["ticket"] in mt5.posicoes and ev["atraso_ms"] >= 1000
    assert volta(m, mt5, {4: D}) == tipos                    # nada a mais


def test_saida_usa_o_contrato_da_posicao_nao_o_do_dia(tmp_path):
    # I12: posição em WINV26, contrato do dia já é WINZ26
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    t = mt5.abrir_manual(1, magic=K.magic(4), simbolo="WINV26")
    foto = K.fotografar(mt5, datetime(2026, 10, 9))
    acoes = planejar({4: Desejado(ZERADO)}, True, foto, m.diario(DIA), AG, 5, 60.0)
    m.executar(mt5, acoes, foto=foto, agora_srv=AG, simbolo="WINZ26", desvio=10,
               pode_entrar=lambda a: (True, None), envio=True, conta_id=2)
    assert mt5.enviados[-1]["symbol"] == "WINV26" and t not in mt5.posicoes


def test_passageira_tenta_de_novo_ate_30_s_e_depois_perdida(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10004, 10018]
    volta(m, mt5, {4: D})
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=20))
    assert len(mt5.enviados) == 2 and not mt5.posicoes
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=31))
    assert tipos[-1] == "perdida" and len(mt5.enviados) == 2


def test_timeout_que_executou_nao_duplica(tmp_path):
    # caso 3
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = ["executou_sem_resposta"]
    assert volta(m, mt5, {4: D})[-1] == "incerta"
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=3))
    assert len([r for r in mt5.enviados if r["action"] == 1]) == 1
    assert len(mt5.posicoes) == 1 and "adotada" in tipos


def test_queda_entre_enviando_e_o_envio_tenta_de_novo_na_janela(tmp_path):
    # caso 5: o diário tem "enviando", a corretora não tem nada (o envio
    # não chegou a sair) -> dentro dos 30 s tenta de novo, uma vez
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    m.diario(DIA).registrar("enviando", quando=T, ligacao_id=4, entry_ts=T)
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=4))
    assert len([r for r in mt5.enviados if r["action"] == 1]) == 1
    assert len(mt5.posicoes) == 1


def test_placed_espera_e_nao_reenvia(tmp_path):
    # caso 4
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10008]
    volta(m, mt5, {4: D})
    volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    assert len(mt5.enviados) == 1
    mt5.executar_pendente(next(iter(mt5.ordens)))
    assert "adotada" in volta(m, mt5, {4: D}, agora=T + timedelta(seconds=6))


def test_parcial_cancela_o_resto(tmp_path):
    # caso 20
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10010]
    tipos = volta(m, mt5, {4: D})
    assert "parcial" in tipos and "cancelada" in tipos and not mt5.ordens


def test_preenchimento_recusado_tenta_o_proximo_modo(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.roteiro = [10030, 10009]
    volta(m, mt5, {4: D})
    assert [r["type_filling"] for r in mt5.enviados if r["action"] == 1] == [1, 0]


def test_sem_margem_perde_e_chama(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    mt5.margem_livre = 0
    tipos = volta(m, mt5, {4: D})
    assert tipos[-1] == "perdida" and not mt5.enviados       # parou no order_check
    assert any(c["tipo"] == "usuario" for c in m.chamados.values())


def test_entrada_sem_protecao_na_corretora_e_encerrada(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    orig = mt5._executar
    def sem_stop(req, parcial=False):
        r = orig(req, parcial)
        for p in mt5.posicoes.values():
            p.sl = p.tp = 0.0
        return r
    mt5._executar = sem_stop
    mt5.roteiro = [10009, 10016]          # entrada ok, SLTP recusado
    volta(m, mt5, {4: D})
    assert not mt5.posicoes


def test_saida_pendente_vira_chamado_apos_120_s_e_continua(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.roteiro = [10018] * 10
    z = {4: Desejado(ZERADO)}
    volta(m, mt5, z, agora=T + timedelta(minutes=1))
    volta(m, mt5, z, agora=T + timedelta(minutes=3, seconds=1))
    assert any(c["tipo"] == "saida_pendente" for c in m.chamados.values())
    mt5.roteiro = []
    volta(m, mt5, z, agora=T + timedelta(minutes=3, seconds=2))
    assert not mt5.posicoes and not m.chamados


def test_envio_desligado_registra_seria_enviada_sem_mandar(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    tipos = volta(m, mt5, {4: D}, envio=False)
    assert tipos == ["seria_enviada"] and not mt5.enviados
    assert volta(m, mt5, {4: D}, envio=False) == ["seria_enviada"]


def test_pode_entrar_falso_registra_o_motivo_uma_vez(tmp_path):
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    pode = lambda a: (False, "preço longe demais do stop do papel")
    volta(m, mt5, {4: D}, pode=pode)
    tipos = volta(m, mt5, {4: D}, pode=pode)
    assert tipos == ["nao_entrou"] and not mt5.enviados


def test_sl_do_servidor_e_movimento_do_stop_no_mesmo_minuto(tmp_path):
    # caso 10: a posição saiu pelo SL; o papel ainda manda proteger
    mt5, m = MT5Ordens(), Motor(tmp_path, INST)
    volta(m, mt5, {4: D})
    mt5.stopar(next(iter(mt5.posicoes)))
    tipos = volta(m, mt5, {4: D}, agora=T + timedelta(seconds=5))
    assert tipos[-1] == "saiu_antes"
    assert m.diario(DIA).eventos[-1]["motivo"] == "stop na corretora"
```

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar `Motor`** em `core/ordens.py` seguindo as regras acima. Esqueleto obrigatório (complete os ramos exatamente como na lista de regras):

```python
from pathlib import Path
from .diario_ordens import Diario

PENDENTE_CHAMA_S = 120


class Motor:
    def __init__(self, pasta, inst: dict, origem: str = "demo"):
        self.pasta, self.origem = Path(pasta), origem
        self.tick = int(inst["tick_size"])
        self.ponto = float(inst["point_value"])
        self._diario: Diario | None = None
        self.chamados: dict[str, dict] = {}

    def diario(self, dia) -> Diario:
        if self._diario is None or self._diario.dia != dia:
            self._diario = Diario(self.pasta, dia, self.origem)
        return self._diario

    def _chamar(self, chave, tipo, texto, agora, **extra):
        if chave not in self.chamados:
            self.chamados[chave] = {"tipo": tipo, "texto": texto, "desde": agora, **extra}
            self._diario.registrar("chamado", quando=agora, motivo=texto, **extra)

    def _fechar(self, chave, agora):
        if self.chamados.pop(chave, None) is not None:
            self._diario.registrar("chamado_fechado", quando=agora, motivo=chave)

    def executar(self, mt5, acoes, *, foto, agora_srv, simbolo, desvio,
                 pode_entrar, envio, conta_id) -> None:
        ordem = {"sair": 0, "proteger": 1, "adotar": 2, "saiu_antes": 2,
                 "perdida": 2, "entrar": 3}
        self.diario(agora_srv.date())
        for a in sorted(acoes, key=lambda a: ordem[a.tipo]):
            getattr(self, f"_{a.tipo}")(mt5, a, foto=foto, agora=agora_srv,
                                        simbolo=simbolo, desvio=desvio,
                                        pode_entrar=pode_entrar, envio=envio,
                                        conta_id=conta_id)

    # _entrar, _sair, _proteger, _adotar, _saiu_antes, _perdida:
    # um método por tipo, cada um com a assinatura (mt5, a, **ctx), seguindo
    # as regras listadas em "Produces" desta tarefa.
```

Os textos de `motivo` vêm de `corretora.texto(resultado)`. `atraso_ms = int((agora_srv - d.entry_ts).total_seconds() * 1000)`. Preço do pedido: `symbol_info_tick(simbolo).ask` na compra e `.bid` na venda (entrada), o contrário na saída.

- [ ] **Step 4: Rodar** → PASS. Rodar também `tests/test_ordens_planejar.py`.
- [ ] **Step 5: Mutação** — agente `mutacao` em `Motor._entrar` e `Motor._sair`: tirar o `enviando` antes do envio, não cancelar o resto da parcial, desistir da saída, aceitar `PLACED` como erro e reenviar. Todas pegas.
- [ ] **Step 6: Commit** — `core/ordens.py tests/test_ordens_motor.py` → `feat(ordens): executor com tentativas, adocao e chamados`.

---

### Task 9: Limite do dia, trava, teto D1, envio e comandos

**Files:**
- Create: `core/comandos.py`
- Modify: `core/ordens.py` (funções `perda_do_dia`, `risco_entrada`, `checar_entrada`, e `Motor.passo`)
- Test: `tests/test_ordens_limite.py`, `tests/test_comandos.py`

**Interfaces:**
- Produces:
  - `comandos.escrever(pasta: Path, tipo: str, **dados) -> str` (arquivo atômico `AAAAMMDDHHMMSSffffff-<uuid>.json`: escreve `.tmp` e `os.replace`); `comandos.consumir(pasta) -> list[dict]` (em ordem, apaga cada um depois de ler); `comandos.TIPOS = {"zerar_tudo", "encerrar_posicao", "envio"}`.
  - `ordens.perda_do_dia(foto, portfolio_de: dict[int, int], portfolio_id: int | None) -> dict` → `{"total", "este", "outros", "fora"}` (R$, perda positiva; ganho conta como 0 no total: `total = max(0, -(realizado + aberto))`; a quebra usa o resultado com sinal de cada origem).
  - `ordens.risco_entrada(d: Desejado, preco: float, perfil_custos: dict, ponto: float) -> float` = `abs(preco − stop_px) × contratos × ponto + 2 × contratos × (corretagem + emolumentos)`.
  - `ordens.checar_entrada(d, preco, perda, limite, risco) -> tuple[bool, str | None]`: sem `stop_px` → falso "plano sem stop"; compra com `preco <= stop_px` ou `preco >= alvo_px` (venda espelhada) → "preço já além do stop/alvo do papel"; `abs(preco − stop_px) > 1,5 × abs(entry_px − stop_px)` → "preço longe demais do stop do papel"; `perda + risco > 0,9 × limite` → "passaria da trava do dia".
  - `Motor.passo(mt5, *, agora_srv, retrato, desejados, disponivel, comandos, simbolo, contrato_ok, conectado_ha_s) -> dict` — a volta inteira das ordens; devolve o bloco `ordens` do `estado.json` (spec §7.3).

`Motor.passo`, em ordem:
1. `foto = fotografar(...)`; `None` → estado `{"foto": "falhou"}` e nada mais.
2. Conta: a do retrato cujo `login`/`servidor` = `foto.login`/`foto.servidor`. Nenhuma → se existir ligação em fase demo, chamado `conta_errada`; **nenhuma ação** (nem saída). `not foto.hedging` → chamado `nao_hedging`, nenhuma ação. `not foto.algo_ligado` → chamado `algo_desligado`, nenhuma ação.
3. Comandos: `zerar_tudo` → `self.zerar = True` (todas as ligações ZERADO; envio considerado desligado) até o retrato mostrar `envio` falso em todas as contas; `envio` → `self.envio_forcado[conta_id] = ligado` até o retrato concordar; `encerrar_posicao(ticket)` → ação `sair` desse ticket nesta volta. Cada comando vira evento `comando` no diário e entra em `estado["comandos"]`.
4. Trava: `perda = perda_do_dia(...)`; `limite = conta["limite"]`; não travada e `limite` e `perda.total >= 0,9 × limite` → registra `conta_travada` (com perda e limite). Travada (pelo diário do dia) → desejados das ligações da conta viram ZERADO; entradas proibidas.
5. Envio: `envio = (envio_forcado.get(conta) if houver, senão conta["envio"])` e não travada e não `zerar`. Envio desligado → as ligações com POSICAO viram ZERADO para a corretora, mas o desejado original é guardado para registrar `seria_enviada` (Tarefa 8).
6. `acoes = planejar(...)`; `pode_entrar = lambda a: checar_entrada(...)` com preço do `symbol_info_tick(simbolo)` e `contrato_ok` (falso → "sem contrato operável hoje").
7. `executar(...)`; chamados de papel parado: `disponivel` falso há mais de 180 s no pregão → chamado `papel_parado`.
8. Estado: por ligação (desejado, posição na corretora, saída pendente desde, tentativas), perda (com quebra), limite, travada, envio, chamados, comandos, `ordens_em = agora_srv`.

**Correções da revisão (fazem parte desta tarefa — cada uma com teste):**
- `checar_entrada`: `if not limite: return False, "conta sem limite de perda do dia"` antes de qualquer conta; comparações com `alvo_px` só `if d.alvo_px is not None`.
- **Conta de outro portfólio (C4):** antes de `planejar`, toda ligação com `lv.conta_id != conta logada` vira `Desejado(ZERADO, motivo="conta de outro portfólio")` — nunca uma ordem de um portfólio na conta de outro. Teste: portfólio A (conta X) em demo, MT5 logado na conta Y do portfólio B → nenhum `order_send` de A.
- **Envio desligado (I4):** `planejar` recebe os desejados com POSICAO → ZERADO (gera as saídas do caso 14); **depois**, para cada POSICAO original com idade ≤ 30 s e sem `seria_enviada`/`perdida`/`nao_entrou`, acrescenta `Acao("entrar", lig, desejado=d)` e chama `executar(..., envio=False)` — é isso que grava o "seria enviada" do ensaio da Tarefa 17. Teste no `passo`.
- **Comandos persistidos (I10, C3):** `comandos.PASTA = db.DATA / "ao_vivo" / "comandos"` (constante de módulo); `tests/conftest.py` autouse desvia `comandos.PASTA` e a pasta do diário de ordens para `tmp_path`. Cada comando consumido é **primeiro** registrado como evento `comando` (motivo = tipo, campos do comando) no diário do dia, e só então apagado; `zerar` e o desligar forçado são **derivados do diário do dia** (`diario.comandos_do_dia(...)`), não de memória — sobrevivem a reinício. `envio` forçado só vale para **desligar**; ligar vem sempre do banco. O "zerar" vale até o retrato mostrar `envio` falso em todas as contas **ou** até o fim do dia.
- **Risco somado (I11):** na checagem 6a, `perda` = perda do dia + risco até o stop de cada posição aberta da automação na conta (`|preço corrente − SL| × volume × ponto`) + risco das entradas já aprovadas **nesta volta**.
- **Chamados de infraestrutura fecham sozinhos (I5):** `conta_errada`, `algo_desligado`, `nao_hedging` e `papel_parado` fecham na primeira volta em que a condição some.
- **Entradas isoladas das saídas (C1):** `passo` executa primeiro as ações que não são `entrar` e depois as `entrar` dentro de `try/except` próprio (exceção → log + chamado `ordens_falhou`, as saídas desta volta já foram).
- `estado["ordens_em"]` = hora do **último evento do diário** (não a hora da volta) — a tela só relê o banco quando algo aconteceu. A hora da volta vai em `estado["vivo_em"]` (para o "sinal de vida").
- Aviso `posicao_fora` (§5.3/§6.3) no estado quando há posição sem magic da automação na conta (não é chamado, não toca nela).
- `checar_entrada` recebe `stops_level` (`symbol_info(contrato).trade_stops_level`, em pontos): distância do preço ao SL ou ao TP menor que ele → "stop ou alvo perto demais do preço (regra da corretora)". E `self.so_encerrar[contrato]` (CLOSE_ONLY, Tarefa 8) → "contrato só aceita encerramento".

- [ ] **Step 1: Testes falhando** — `tests/test_comandos.py`:

```python
from core import comandos


def test_escreve_e_consome_em_ordem_e_apaga(tmp_path):
    comandos.escrever(tmp_path, "zerar_tudo")
    comandos.escrever(tmp_path, "encerrar_posicao", ticket=55)
    lidos = comandos.consumir(tmp_path)
    assert [c["tipo"] for c in lidos] == ["zerar_tudo", "encerrar_posicao"]
    assert lidos[1]["ticket"] == 55 and comandos.consumir(tmp_path) == []


def test_tipo_desconhecido_recusa(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        comandos.escrever(tmp_path, "inventado")


def test_arquivo_temporario_nao_e_consumido(tmp_path):
    (tmp_path / "x.json.tmp").write_text("{}")
    assert comandos.consumir(tmp_path) == []
```

`tests/test_ordens_limite.py` — `perda_do_dia` com posições/negócios de três origens (este portfólio, outro portfólio, à mão) e o total igual à soma; `checar_entrada` um teste por motivo (os quatro acima) e um caso que passa; `Motor.passo` com o MT5 falso para: trava a 90% zera e registra `conta_travada`; reinício (Motor novo, mesmo `tmp_path`) continua travado (caso 16); trava com saída pendente trava mesmo assim (caso 15); conta errada logada → nenhum `order_send`; não hedging → nenhum envio e chamado; Algo desligado → idem; comando `zerar_tudo` encerra todas as posições com magic e nenhuma entrada depois; `envio` desligado com posição aberta → sai (caso 14). Escreva cada teste por inteiro, no estilo de `tests/test_ordens_motor.py`.

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `core/comandos.py` e as funções/`passo` em `core/ordens.py`:

```python
"""Comandos da tela para a captura, por arquivo (spec §3, §5.8).

Não passam pelo banco: "Zerar tudo" com uma mineração segurando a escrita
não pode esperar. A tela escreve um arquivo atômico; a captura consome e
apaga na volta seguinte e devolve o resultado no estado.json.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from . import db_manager as db

TIPOS = frozenset({"zerar_tudo", "encerrar_posicao", "envio"})
# constante de módulo: o conftest a desvia — um teste não pode deixar um
# comando para a captura real do usuário consumir
PASTA = db.DATA / "ao_vivo" / "comandos"


def escrever(pasta, tipo: str, **dados) -> str:
    if tipo not in TIPOS:
        raise ValueError(f"comando desconhecido: {tipo}")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    cid = uuid.uuid4().hex
    nome = f"{datetime.now():%Y%m%d%H%M%S%f}-{cid}.json"
    tmp = pasta / (nome + ".tmp")
    tmp.write_text(json.dumps({"id": cid, "tipo": tipo, "criado_em":
                               datetime.now().isoformat(), **dados}),
                   encoding="utf-8")
    os.replace(tmp, pasta / nome)
    return cid


def consumir(pasta) -> list[dict]:
    pasta = Path(pasta)
    if not pasta.exists():
        return []
    out = []
    for arq in sorted(pasta.glob("*.json")):
        try:
            out.append(json.loads(arq.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        finally:
            arq.unlink(missing_ok=True)
    return out
```

- [ ] **Step 4: Rodar** → PASS (`tests/test_ordens_*.py tests/test_comandos.py`).
- [ ] **Step 5: Mutação** — agente `mutacao` em `checar_entrada`, `perda_do_dia` e no passo 4 do `passo` (trava).
- [ ] **Step 6: Commit** → `feat(ordens): limite do dia, trava, teto do stop e comandos da tela`.

---

### Task 10: Contrato do dia, vencimento e guarda de preço

**Files:**
- Create: `core/contrato_dia.py`
- Test: `tests/test_contrato_dia.py`

**Interfaces:**
- Produces:
  - `escolher(mt5, hoje: date, *, base="WIN$N", prefixo="WIN") -> dict` → `{"simbolo": str | None, "motivo": str | None, "vence_em": date | None, "amanha": str | None}`. Candidatos: `mt5.symbols_get(group=f"{prefixo}*")` com `name != base` e `trade_mode == SYMBOL_TRADE_MODE_FULL`; o escolhido tem `symbol_info_tick(s).last == symbol_info_tick(base).last`; reserva: maior volume diário do pregão anterior (`copy_rates_from_pos(s, TIMEFRAME_D1, 1, 1)`, campo `real_volume`) com motivo "pelo volume (preço diferente do WIN$N)". Vencimento = data de `expiration_time` (epoch, hora de Brasília como o resto). **Vence hoje → `simbolo=None`, motivo "vencimento do <contrato>: sem entradas hoje"**. Vence no próximo dia útil (calendário de `core/calendar.py` ou `rollovers`) → `amanha` = o próximo contrato que estará igual — use o de vencimento seguinte.
  - `class GuardaPreco(tick: int)` com `observar(agora: datetime, preco_contrato: float, preco_base: float) -> bool` (verdadeiro = entradas bloqueadas): bloqueia quando `abs(contrato − base) > 2 × tick` **continuamente** por mais de 60 s; desbloqueia na primeira observação dentro da faixa.
- Antes de implementar: conferir na documentação `symbols_get` (parâmetro `group`), `symbol_info` (`expiration_time`, `trade_mode`) e `copy_rates_from_pos`, e citar as URLs no relatório.

- [ ] **Step 1: Testes** — `tests/test_contrato_dia.py` com `MT5Ordens` (Tarefa 3: `precos`, `vencimentos`; acrescente a ele `copy_rates_from_pos` devolvendo `real_volume` configurável e `symbols_get(group)` filtrando por prefixo): escolhe WINV26 quando igual ao WIN$N; escolhe pelo volume quando nenhum é igual; vence hoje → `None` e motivo; véspera → `amanha == "WINZ26"`; `GuardaPreco` bloqueia só depois de 60 s contínuos e solta ao voltar.
- [ ] **Step 2: Ver falhar. Step 3: Implementar. Step 4: Ver passar.**
- [ ] **Step 5: Commit** → `feat(ordens): contrato do dia, vencimento e guarda de preco`.

---

### Task 11: Conferência diária papel × backtest

**Files:**
- Create: `core/papel_backtest.py`
- Test: `tests/test_papel_backtest.py`

**Interfaces:**
- Consumes: `papel.perfil_do_plano`, `papel._modulo`, `codigo.hash_estrategia`, `papel.periodos_ligados`, `papel._conta`, `run_strategy`, `prepare_bars`, `_plano.detalhes`.
- Produces:
  - `conferir(con, ligacao_id: int, dia: date, cache_codigo: dict, agora: datetime, *, symbol="WIN$N") -> dict` → `{"ok": bool, "n_papel": int, "n_backtest": int, "diferencas": list[dict]}`, e grava em `papel_backtest` (upsert). Backtest: `run_strategy` sobre **todo o histórico até o fim do dia** (sem `vela_aberta`), plano do pregão gravado em `papel_pregoes.plano_id`; compara as operações com entrada no dia e `conta` verdadeiro (as do backtest filtradas pelos mesmos `periodos_ligados`) pela tupla `(entry_ts, side, entry_px, exit_ts, exit_px, reason)`. Cada diferença: `{"entry_ts", "papel": tupla|None, "backtest": tupla|None}`.
  - `pendentes(con, symbol) -> list[tuple[int, date]]` — pares com `papel_pregoes.status = 'conferido'`, marca `reconferencia://<dia>` no `ingest_log` e sem linha em `papel_backtest` (ou com `conferido_em` anterior à reconferência).
  - `situacao(con, ligacao_id) -> dict` → `{"pregoes": n, "operacoes": n, "diferencas": n, "ok": bool | None}` (None = nenhum pregão conferido ainda).

- [ ] **Step 1: Testes** — base com a fábrica da Tarefa 6; papel gravado igual ao backtest → `ok` e zero diferenças; papel com uma operação a mais (insira à mão em `papel_operacoes`) → `ok` falso e a diferença listada com `backtest: None`; `pendentes` só traz dia com reconferência; `situacao` agrega.
- [ ] **Step 2–4: falhar, implementar, passar.**
- [ ] **Step 5: Mutação** — agente `mutacao` em `conferir` (ex.: ignorar `exit_px`, não filtrar `conta`).
- [ ] **Step 6: Commit** → `feat(papel): conferencia diaria papel x backtest`.

---

### Task 12: Ao vivo — fase, contratos da conta e Envio de ordens

**Files:**
- Modify: `core/ao_vivo.py`
- Test: `tests/test_ao_vivo_ordens.py`

**Interfaces:**
- Produces:
  - `mudar_fase(ligacao_id: int, fase: str, *, quando=None) -> None` — `fase ∈ {"papel", "demo"}` (real fica para a parte da conta real: `ValueError` "conta real ainda não disponível"). Para `demo` exige, senão `ValueError` com o motivo em português: portfólio com `conta_demo_id`; plano em vigor com stop (`perfil.stop_tipo == "atr"` ou `stop_pontos > 0`, via `papel.perfil_do_plano`); `papel_backtest.situacao(...)["ok"]` não falso (nenhuma diferença; sem pregão conferido ainda é permitido, e a ficha avisa). Atualiza `fase`, `fase_desde`; evento `fase_mudou` (de/para). Voltar para `papel` não exige nada — a reconciliação encerra a posição (decisão 12).
  - `definir_contratos(ligacao_id: int, contratos: int | None, *, tipo="demo") -> None` — `None` = volta ao plano; inteiro ≥ 1; evento `contratos_alterados` (de/para, motivo = tipo).
  - `ligar_envio(conta_id: int, ligado: bool) -> None` — ligar exige `limite_perda_dia > 0` (`ValueError` "cadastre o limite de perda do dia da conta antes de ligar o envio"); evento `envio_ligado`/`envio_desligado`. **Desligar escreve o comando `envio` (`comandos.escrever(comandos.PASTA, "envio", conta_id=…, ligado=False)`) ANTES da transação no banco** — com o banco ocupado, o desligar já vale pela captura. Ligar só pelo banco.
  - `editar_conta` (já existe): apagar o limite (`None`/0) com o Envio ligado desliga o Envio na mesma transação (evento `envio_desligado`, motivo "limite apagado").
  - `mudar_fase(..., "demo")` também recusa plano em **M1 com stop ou alvo por ATR** ("em M1 com ATR o motor ainda usa a própria barra de entrada; aguarde a correção do motor") — risco conhecido, ver Global Constraints.
  - `custo_de_um_stop(ligacao_id: int, contratos: int) -> dict` → `{"reais": float, "pct_limite": float | None}` — distância típica de stop do plano (`stop_pontos`, ou para ATR a mediana de `|entry_px − stop_px|` das operações do papel; sem nenhuma, `None`) × contratos × valor do ponto, contra o limite da conta demo do portfólio.

- [ ] **Step 1: Testes** — um por regra: cada recusa de `mudar_fase` com a mensagem; sucesso grava fase e evento; `definir_contratos` com 0 recusa, com `None` volta ao plano; `ligar_envio` sem limite recusa, com limite grava e cria arquivo de comando; `custo_de_um_stop` com stop em pontos (300 pts × 3 × 0,20 = R$ 180, 36% de R$ 500).
- [ ] **Step 2–4: falhar, implementar, passar.**
- [ ] **Step 5: Commit** → `feat(ao-vivo): fase demo, contratos da conta e envio de ordens`.

---

### Task 13: Integração na captura

**Files:**
- Modify: `captura.py`
- Test: `tests/test_captura_ordens.py`

**Interfaces:**
- Consumes: tudo acima.
- Produces (em `Servico`):
  - Novos atributos: `motor = ordens.Motor(PASTA / "ordens", inst)`, `retrato`, `retrato_em`, `aquecimento`, `aquecimento_chave` (tupla dos `plano_id`), `contrato` (dict de `contrato_dia.escolher`), `guarda = contrato_dia.GuardaPreco(tick)`, `conectado_desde` (mono), `ordens_estado`, `_minuto_calculado`, `_desejados`, `_disponivel`.
  - `_ordens(agora, m)` chamado em `volta()` **logo depois** de `relogio.observar` e **antes** de `_buscar_e_gravar`:
    1. Sem `agora_srv` ou fora do pregão e sem posição da automação → só publica.
    2. Retrato: a cada 5 s tenta `db.connect(read_only=True, tentativas=1)` → `papel_vivo.ler_retrato`; falhou = mantém o anterior (o estado mostra a idade). Virada do dia → `retrato = aquecimento = None` até reler.
    3. Aquecimento: quando `aquecimento_chave` muda ou é `None`, na mesma conexão de leitura → `papel_vivo.carregar_aquecimento`.
    4. Contrato do dia: `contrato_dia.escolher` na primeira volta conectada do pregão (e a cada nova conexão); evento `rolagem` no diário quando muda.
    5. Barras de hoje: `copy_rates_range(zero_do_dia, agora + 1 dia)` → `C.fechados(df, agora_srv)` → `papel_vivo.barras_de_hoje`; o último candle (em formação) vira `provisoria = (ts, open)`.
    6. Desejados: recalcula **só quando o minuto em formação muda** (ou o retrato mudou, ou na subida): `papel_vivo.desejados(...)`. Entre recálculos reaproveita.
    7. `comandos.consumir(PASTA / "comandos")`.
    8. `self.ordens_estado = self.motor.passo(...)` com `contrato_ok = contrato["simbolo"] is not None and not guarda.bloqueada`.
  - Espelho do diário: dentro do primeiro `with self._banco(agora, escrita=True)` da volta que já existe (gravação dos candles), chamar `self.motor.diario(dia).espelhar(con)` — nunca abrir uma escrita só para isso.
  - **Na subida**, `papel_pendente = True` para o papel gravado calcular sem esperar candle, e `_ordens` calcula os desejados na primeira volta (estado indisponível até lá).
  - `account_info()` a cada volta (hoje só no login: `captura.py:304`) — a conferência da conta fica no `Motor.passo` pela fotografia.
  - `_papel` passa `provisoria=(em["ts"], int(em["open"]))` (o `em_formacao` desta volta, que é dict) para `papel.rodar_dia`.
  - **Correções da revisão (fazem parte desta tarefa):**
    - `_ordens` inteiro em `try/except Exception` (log, `ordens_estado = {"erro": str(e), "vivo_em": agora}`, chamado `ordens_falhou` via `motor._chamar`); uma falha nas ordens nunca pula candles, papel e conferência.
    - O dict do contrato vai em **`self.contrato_dia`** (o `self.contrato` existente é a string publicada como `contrato_vigente`).
    - `conectado_desde` é reiniciado sempre que `mt5_estado` passa de qualquer outro valor para `"conectado"` (não só no `initialize`) — a graça de 5 s vale também quando a corretora cai e volta com o terminal aberto.
    - MT5 fechado/sem conexão com posição da automação aberta (pelo diário: `tickets_abertos`) → chamado `mt5_fora` (o motor não roda sem MT5; o chamado é aberto pelo `_ordens`).
    - Espelho do diário: `diario_ordens.espelhar_pendentes(PASTA_ORDENS, con)` na subida (primeira escrita), na virada do dia e dentro da escrita da conferência — não só na gravação de candles (os eventos depois do último candle do dia chegariam nunca).
    - `papel_backtest.conferir` só roda fora do pregão (antes das 08:59 ou depois do fechamento), dentro da escrita da conferência — o backtest do histórico inteiro não pode atrasar uma ordem.
    - O `Motor` recebe `relogio=lambda: self.relogio.agora(self.mono())`.
  - `volta()` devolve **0,1** quando no pregão e o segundo do servidor está em `[58, 60)` ou `[0, 10]`; senão o de hoje.
  - `publicar` ganha `"ordens": self.ordens_estado`.
  - Conferência papel × backtest: em `_conferir`, depois do papel/reconferência, para cada `papel_backtest.pendentes(con)` → `papel_backtest.conferir(...)` dentro da escrita que já existe.

- [ ] **Step 1: Testes** — `tests/test_captura_ordens.py`, combinando o `MT5Falso` de barras (`tests/test_captura_processo.py`) com o `MT5Ordens` (crie uma classe que herda dos dois, ou um `MT5Ordens` que também tem `copy_rates_range`/`symbol_select`/`initialize`). Casos de §6.4: 1 (sinal no fechamento das 10:00 → `order_send` na volta de 10:01:01, com `atraso_ms` ≤ 1500); 6 (reinício às 10:30:20 com posições: primeira volta não envia nada até os desejados calcularem, e nenhuma posição sai); 7 (lista vazia após reconectar: nenhuma entrada nos 5 s); 18 (`db.connect_write` e `db.connect` levantando "ocupado" por 2 min: entrada e saída saem igual; o espelho chega depois); 19 (sem tick → sem entrada); 2 (entra às 10:01:01 e o candle das 10:01 fecha batendo o stop: na volta de 10:02 a posição já saiu pelo SL do servidor → `saiu_antes`, ou ainda está aberta → `sair`; nunca reentra); 11 (o candle das 10:00 é revisado pela recuperação de lacuna e o sinal some com a demo aberta → sai); guarda de preço bloqueada por mais de 60 s → chamado `preco_contrato` (o `_ordens` chama `motor._chamar` com essa chave e a fecha quando a guarda solta); cadência 0,1 s no segundo 59 e 1 s no segundo 30; `estado.json` com o bloco `ordens`.
- [ ] **Step 2–4: falhar, implementar, passar.** Rodar a suíte inteira da captura: `pytest -q tests/test_captura*.py tests/test_papel*.py tests/test_ordens*.py`.
- [ ] **Step 5: Medir o orçamento** — teste (marcado `@pytest.mark.lento`, roda na suíte normal) com o aquecimento real da maior estratégia do portfólio do usuário (`rompimento_ema_abertura`, `ema_longa=600`, M7) em barras sintéticas do mesmo tamanho: `papel_vivo.desejados` < 300 ms. Se passar disso, registre no relatório e otimize antes de seguir (ex.: calcular só os planos das ligações em fase demo).
- [ ] **Step 6: Commit** → `feat(captura): ordens da demo antes do banco, volta rapida na virada do minuto`.

---

### Task 14: Tela — topo (selo, Zerar tudo) e alarme

**Files:**
- Modify: `ui/data.py` (leitor `ordens_do_estado(estado) -> dict`), `ui/app.py` (topbar: selo + botão + `dcc.Store`/div do alarme)
- Create: `ui/callbacks_ordens.py` (registrado em `ui/callbacks.py:register`), `ui/assets/alarme.js`
- Test: `tests/test_ui_ordens.py`, `tests/test_callbacks_sem_ciclo.py` (rodar)

**Interfaces:**
- Produces:
  - `ui.data.ordens_do_estado(e: dict | None) -> dict` → `{"selo": "enviando" | "desligado" | "travada" | "sem_captura" | "sem_demo", "texto": str, "chamados": list[dict], "alarme": bool}`. `sem_captura` quando o `estado.json` está velho (mesma régua de idade que a tela já usa para a captura).
  - Topbar: `html.Span(id="ord-selo")` ao lado do selo da captura e botão `id="ord-zerar"` "⏻ Zerar tudo e desligar envio". Dois cliques: reutilize o padrão de ação armada de `ui/callbacks_operacao.py` (`av-op-armado`/`acao`/`rotulos_op`): primeiro clique arma ("Confirmar: encerra N posição(ões)"), segundo escreve `comandos.escrever(PASTA_COMANDOS, "zerar_tudo")` **e** desliga `envio_ligado` de todas as contas no banco (via `ao_vivo.ligar_envio(id, False)`; banco ocupado → mostra que o comando por arquivo já vale).
  - `ui/assets/alarme.js`: lê o atributo `data-alarme` de `#ord-alarme` (div escondida atualizada pelo pulso de 2 s): `"1"` → toca um bipe (WebAudio, 3 bipes de 200 ms, uma vez por chamado novo) e pisca o título da aba entre "⚠ Precisa de você" e o título original a cada 1 s; `"0"` → restaura o título. Funciona em qualquer aba do app (a div fica no layout raiz).

```javascript
/* Alarme da parte 4: chamado aberto ou conta travada. O usuário pode estar
 * em outra aba do app ou em outra janela; o título da aba piscando e um
 * bipe curto o trazem de volta. Só toca uma vez por chamado NOVO — a lista
 * de chaves vem em data-chaves. */
(function () {
  var original = document.title, timer = null, vistos = {};
  function bipe() {
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.35, 0.7].forEach(function (t) {
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
        g.gain.setValueAtTime(0.15, ctx.currentTime + t);
        o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
      });
    } catch (e) { /* navegador sem áudio: fica o título */ }
  }
  function aplicar(el) {
    var ligado = el.getAttribute("data-alarme") === "1";
    var chaves = (el.getAttribute("data-chaves") || "").split("|").filter(Boolean);
    var novo = chaves.some(function (c) { return !vistos[c]; });
    chaves.forEach(function (c) { vistos[c] = true; });
    if (ligado && novo) bipe();
    if (ligado && !timer) {
      original = document.title;
      timer = setInterval(function () {
        document.title = document.title === original ? "⚠ Precisa de você" : original;
      }, 1000);
    } else if (!ligado && timer) {
      clearInterval(timer); timer = null; document.title = original;
    }
  }
  new MutationObserver(function () {
    var el = document.getElementById("ord-alarme");
    if (el) aplicar(el);
  }).observe(document.documentElement, { subtree: true, attributes: true,
                                         attributeFilter: ["data-alarme", "data-chaves"] });
})();
```

- [ ] **Step 1: Testes** — `ordens_do_estado` para cada selo e para `alarme` (chamado aberto ou travada → `True`); callback do zerar: primeiro clique só arma, segundo cria o arquivo em `tmp_path` (monkeypatch da pasta) e chama `ligar_envio(..., False)`.
- [ ] **Step 2–4: falhar, implementar, passar.** Rodar `tests/test_callbacks_sem_ciclo.py`.
- [ ] **Step 5: Ver na tela** — `preview_start` `dataframe`; screenshot do topo com o selo; armar e cancelar o Zerar (não confirmar: a captura do usuário pode estar ligada).
- [ ] **Step 6: Commit** → `feat(ui): selo das ordens, zerar tudo e alarme`.

---

### Task 15: Tela — Ao vivo › Operação com a demo

**Files:**
- Create: `ui/components/ordens_panel.py` (construtores puros de cada bloco)
- Modify: `ui/components/operacao_panel.py` (layout: novos contêineres), `ui/callbacks_operacao.py` (preencher), `core/papel_leitura.py` (leituras novas: operações da demo do dia a partir de `ordens_eventos`; papel × demo por contrato), `ui/assets/style.css`
- Test: `tests/test_ordens_panel.py`, `tests/test_callbacks_sem_ciclo.py`

**Interfaces:**
- Produces (todos puros, recebem dicts e devolvem componentes Dash; ids `av-op-ord-*`):
  - `faixa_saude(ordens: dict) -> html.Div` — MT5, Algo Trading, conta logada, margem livre, sinal de vida (idade de `ordens_em`), último candle, atraso médio (âmbar acima de 2 s).
  - `faixa_chamados(ordens: dict) -> html.Div | None` — uma linha por chamado, com botões "Encerrar posição" (`{"type": "av-op-ord-acao", "acao": "encerrar", "id": ticket}`, dois cliques, escreve comando `encerrar_posicao`) e "Manter e acompanhar" (só esconde o chamado na tela, guardado em `dcc.Store` local).
  - `posicoes_abertas(ordens: dict, nomes: dict[int, str], tick: int) -> html.Table` — variante, lado (etiqueta de contorno, venda **não** rosa), contratos, preço, proteção ✓ (SL e TP presentes), ticks até stop/alvo a partir do preço corrente, resultado aberto (ticks e R$), situação (`confere` | `saída pendente — tentando (Nª) · m:ss` | `indisponível`).
  - `numeros(ordens, resultado_portfolio: float, papel_portfolio: float) -> html.Div` — Resultado hoje na demo (do portfólio), Perda do dia **da conta** × limite (barra cinza < 60%, âmbar 60–85%, rosa ≥ 85%, marca nos 90%; rótulo abre em "este portfólio · outros portfólios · fora da automação"), Posições abertas (n, quantas conferem).
  - `operacoes_demo(linhas: list[dict]) -> html.Table` — Entrada, Saída, Variante, Lado, Contr., Preço entrada, Preço saída, **Derrapagem (ticks)**, Pontos, Resultado, Situação (etiqueta: "stop na corretora", "alvo na corretora", "sinal", "saiu na Nª tentativa (leilão, 6 s)", "entrada recusada · perdida", "não executada · automação fora do ar", "seria enviada").
  - `diario_do_dia(eventos: list[dict], nomes) -> html.Div` — hora, variante, texto; filtro "Tudo | Só problemas".
  - `avaliacao(situacao_backtest: dict, comparativo_demo: dict) -> html.Details` — recolhível; selo "papel = backtest ✓ (N pregões, M operações)" ou "K diferenças" (lista); tabela Papel × Demo por contrato (operações, pontos por operação, fator de lucro, sinal no mesmo minuto, derrapagem média por ponta em ticks, recusadas · resolvidas sozinha · chamados). A curva Papel × esperado que já existe vai para dentro dela.
  - Cartões das variantes: contratos da demo editáveis — botão "✎" abre um popover com campo numérico (`type="text"` + `inputMode="numeric"`, regra do `AGENTS.md`), o custo de um stop contra o limite (`ao_vivo.custo_de_um_stop`) e "vale a partir da próxima operação"; salvar chama `ao_vivo.definir_contratos`.
  - Leituras novas em `core/papel_leitura.py`: `operacoes_demo(con, portfolio_id, dia) -> list[dict]` (deriva de `ordens_eventos` + `papel_operacoes` pela chave `(ligacao_id, entry_ts)`), `comparativo_demo(con, portfolio_id) -> dict`. **Derrapagem por ponta, em ticks, positivo = pior para o trader:** entrada = `(preco_demo − preco_papel) × side / tick`; saída = `(preco_papel − preco_demo) × side / tick`. Teste com compra e com venda nas duas pontas.
  - Faixa de chamados também mostra, quando o comando ficou esperando (captura sem sinal de vida há mais de 10 s): "comando enviado, esperando a captura — o stop e o alvo seguem na corretora".
- Ordem na página (spec §8 / rascunho v2): faixa de saúde, faixa de chamados, cabeçalho (contrato do dia, interruptor Envio de ordens com a mesma confirmação de dois cliques quando há posição), três números, Posições abertas, cartões | gráfico (gráfico menor que hoje), Operações do dia, Diário do dia, Avaliação.
- Muitas variantes: Posições abertas e Operações do dia com rolagem própria (altura máxima), como já é o padrão `6.4` da parte 3.

- [ ] **Step 1: Testes** — um por construtor, com dicts de exemplo: situação "saída pendente" mostra tentativas e tempo; venda não usa a classe rosa; barra da perda muda de classe nos limites 60/85; derrapagem em ticks (10 pts = 2 ticks); "seria enviada" aparece com Envio desligado; `operacoes_demo` (leitura) casa evento e papel pela chave e calcula a derrapagem com o sinal certo na venda.
- [ ] **Step 2–4: falhar, implementar, passar.** `tests/test_callbacks_sem_ciclo.py`.
- [ ] **Step 5: Revisão visual** — agente `designer-ui` revisa a tela contra o rascunho `ordens-operacao-v2.html` (layout, textos, (?) com faixa boa/ruim, celular/tablet).
- [ ] **Step 6: Ver na tela contra o banco real** — `preview_start` `dataframe`, sub-tela Operação do "Portifolio-Mini-Indice-01": screenshot com o portfólio no papel (sem demo ainda: blocos da demo vazios e explicativos, não quebrados).
- [ ] **Step 7: Commit** → `feat(ui): operacao com a demo (saude, chamados, posicoes, diario, avaliacao)`.

---

### Task 16: Tela — ficha (fase, contratos, conta e Envio)

**Files:**
- Modify: `ui/components/ao_vivo_panel.py` (ficha), `ui/callbacks_ao_vivo.py`
- Test: `tests/test_ui_ficha_ordens.py`, `tests/test_callbacks_sem_ciclo.py`

**Interfaces:**
- Produces na ficha da variante (Ao vivo › Estratégias):
  - Linha **Fase**: "papel" com botão "Promover para demo" (dois cliques; recusa mostra o `ValueError` de `ao_vivo.mudar_fase` em português) e, em demo, "Voltar para papel" (aviso "isso encerra a posição aberta, se houver").
  - Selo **papel × backtest** (de `papel_backtest.situacao`): "✓ N pregões" | "K diferenças — não pode subir para a demo" | "ainda sem pregão conferido".
  - **Contratos na demo**: o mesmo editor da Tarefa 15.
- Na seção da conta do portfólio: **Limite de perda do dia** (editável, R$) e interruptor **Envio de ordens** — ligar sem limite mostra "cadastre o limite antes"; desligar com posição aberta pede a confirmação de dois cliques ("isso encerra N posição(ões)").

- [ ] **Step 1: Testes** dos callbacks (recusa e sucesso de cada ação; mensagens). **Step 2–4.** Ciclo.
- [ ] **Step 5: Ver na tela** — screenshot da ficha da variante de canal do usuário (fase papel, selo do backtest). **Não clicar em Promover** (é decisão do usuário).
- [ ] **Step 6: Commit** → `feat(ui): ficha com fase demo, contratos e envio de ordens`.

---

### Task 17: Documentação, revisão final e ensaio

**Files:**
- Modify: `AGENTS.md` (Onde estamos; armadilhas novas: barra provisória, caminho da ordem sem banco, desejado indisponível, tabela de retornos, filling por máscara, `None` com `last_error`; tabelas protegidas `ordens_eventos` e `papel_backtest`; o `data/ao_vivo/ordens/*.jsonl` não se apaga), `CHANGELOG.md`, `docs/superpowers/specs/2026-10-05-ao-vivo-ordens-decisoes.md` (marcar implementado).

- [ ] **Step 1:** agente `documentador` põe os documentos em dia.
- [ ] **Step 2:** suíte inteira verde: `.venv/Scripts/python.exe -m pytest -q`.
- [ ] **Step 3:** **Ensaio (operacional, com o usuário):** avisar em destaque que é preciso fechar a janela **Dataframe - Captura** e reabrir o `iniciar.bat`. Depois, um pregão inteiro com o portfólio em fase demo e **Envio de ordens desligado**: no fim do dia, conferir que cada operação do papel tem um "seria enviada" no mesmo minuto, com lado, volume e stop/alvo certos. Só então o usuário liga o Envio com 1 contrato.
- [ ] **Step 4: Commit** → `docs: parte 4 (ordens) no AGENTS e CHANGELOG`.

