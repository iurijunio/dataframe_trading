# Serviço de captura + sub-tela Pregão — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** corrigir a base com hora deslocada (§0) e criar o serviço de captura
(processo à parte que grava cada candle M1 fechado do `WIN$N`, recupera
interrupções e confere o dia) com a sub-tela Ao vivo › Pregão.

**Architecture:** a lógica pura fica em `core/captura.py` (sem Dash, sem
MetaTrader5 importado no topo — tudo injetável); o processo `captura.py`
(raiz) roda o laço com MT5 de verdade e escreve `data/ao_vivo/estado.json`;
a tela só lê o banco (candles fechados) e o `estado.json` (candle em
formação, saúde). Gravação reaproveita o merge de `core/ingest.py`
via `ingest_df`.

**Tech Stack:** Python 3, polars 1.44, DuckDB 1.5.5, Dash 4.4.1,
dash_tvlwc (prop `tick`), MetaTrader5 5.0.

**Spec:** `docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md`

## Global Constraints

- Código, nomes, comentários e textos de tela em **português**. Comentário explica **por quê**, nunca o quê (tom de `core/wfa.py`).
- **Nada em `core/` importa Dash.** `core/captura.py` não importa `MetaTrader5` no topo: recebe o módulo por parâmetro.
- Vocabulário: "serviço de captura"/"Captura", "lacuna", "conferência do dia", "candle em formação". **Nunca "robô"** em código novo, texto de tela ou mensagem.
- O `time` das barras do MT5 **já é hora de Brasília**: nunca somar/subtrair offset. **Nunca gravar o candle em formação.**
- "Agora" = `datetime.now()` sem fuso (o PC está em Brasília; `tzdata` não está instalado — não use `zoneinfo`).
- Testes: o `tests/conftest.py` já desvia `db.DB_PATH`; **todo teste que exporta Parquet faz `monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")`**; nenhum teste toca `data/`.
- TDD em toda tarefa de lógica; mutação (quebrar de propósito, ver o teste falhar, desfazer) em `core/captura.py`, `ingest_df` e na correção de hora.
- Git **pela tool PowerShell**; `git add` **por caminho**; commit com `git commit -F <arquivo>` (mensagem num arquivo do scratchpad), terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem push.
- **Nunca editar, stagear ou commitar** `ui/components/controls.py`, `ui/components/wfa_matriz.py`, `strategies/rompimento_abertura.py`.
- `ui/components/ao_vivo_panel.py` tem uma remoção de 4 linhas feita pelo usuário (o parágrafo que falava em "robô de papel"). **Preserve-a**; ela entra no commit da Tarefa 9 junto com o resto do arquivo.
- Rodar a suíte: `.venv/Scripts/python.exe -m pytest -q` (≈1000 testes). Mexeu em Input/Output de callback: rodar `tests/test_callbacks_sem_ciclo.py`.

---

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `core/captura.py` (novo) | `fechados`, `gravar`, `lacunas`, `fechamento_esperado`, `em_pregao`, `dias_pendentes`, `conferir_dia`, `escrever_estado`/`ler_estado` |
| `core/mt5_source.py` | `buscar_barras` sem offset; `ultimo_tick`; `sincronizar` descarta o candle em formação; some `offset_servidor` |
| `core/ingest.py` | `validar` + `ingest_df` extraídos; `ingest_csv` passa a chamá-los; `sha256_df` |
| `core/reparo_base.py` (novo) | contas da correção §0: apagar derivados, apagar lotes, sessões suspeitas |
| `corrigir_base.py` (novo, raiz) | roteiro da §0 (simulação por padrão; `--executar` faz) |
| `core/db_manager.py` | `export_parquet` atômico (pasta nova + troca) |
| `core/diario.py` | tipo de evento `base_corrigida` |
| `captura.py` (novo, raiz) | o processo: trava, laço, MT5, conferência, estado, log |
| `captura.bat` (novo), `iniciar.bat` | janela própria com reabertura; o `iniciar.bat` a abre |
| `ui/data.py` | `estado_captura()` + invalidação do cache após conferência |
| `ui/components/pregao_panel.py` (novo) | desenho da sub-tela Pregão e do selo (funções puras) |
| `ui/callbacks_pregao.py` (novo) | callbacks do Pregão, do selo e da trava do "Sincronizar" |
| `ui/components/ao_vivo_panel.py`, `ui/app.py`, `ui/callbacks.py`, `ui/callbacks_mt5.py`, `ui/assets/style.css` | seletor Estratégias \| Pregão, selo no topo, registro |

---

### Task 1: Hora certa e "fechado" (correção de código da §0)

**Files:**
- Create: `core/captura.py`
- Modify: `core/mt5_source.py`
- Test: `tests/test_captura.py` (novo), `tests/test_mt5_source.py`

**Interfaces:**
- Produces: `captura.fechados(barras: pl.DataFrame, agora: datetime, ultimo_tick: datetime | None = None) -> pl.DataFrame`; `mt5_source.ultimo_tick(symbol: str) -> datetime | None`; `mt5_source.buscar_barras(symbol, desde, ate)` agora sem offset.

- [ ] **Step 1: testes de `fechados` (falhando)** — `tests/test_captura.py`:

```python
"""Serviço de captura: as contas (core/captura.py), com MT5 e relógio falsos."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import captura as C  # noqa: E402


def barras(*horas, base=100000):
    """Um candle por horário 'HH:MM' de 01/10/2026."""
    ts = [datetime(2026, 10, 1, int(h[:2]), int(h[3:])) for h in horas]
    n = len(ts)
    return pl.DataFrame({
        "ts": ts, "open": [base] * n, "high": [base + 50] * n,
        "low": [base - 50] * n, "close": [base + 10] * n,
        "tick_volume": [100] * n, "volume": [500] * n, "spread": [5] * n,
    })


def test_fechados_nunca_devolve_o_candle_em_formacao():
    b = barras("10:00", "10:01", "10:02")
    agora = datetime(2026, 10, 1, 10, 2, 30)
    assert C.fechados(b, agora)["ts"].to_list() == b["ts"].to_list()[:2]


def test_fechados_ultimo_vira_fechado_65s_depois_do_inicio():
    b = barras("10:00", "10:01")
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 4)).height == 1
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 5)).height == 2


def test_pc_adiantado_70s_nao_deixa_passar_o_em_formacao():
    # relógio real 10:01:30; o PC marca 10:02:40; o tick (hora do MT5) é real
    b = barras("10:00", "10:01")
    agora_pc = datetime(2026, 10, 1, 10, 2, 40)
    tick = datetime(2026, 10, 1, 10, 1, 30)
    assert C.fechados(b, agora_pc, tick)["ts"].to_list() == b["ts"].to_list()[:1]


def test_tick_parado_ha_mais_de_2_min_nao_segura_o_ultimo_candle():
    # mercado parado: o último negócio foi 10:01:10 e o relógio já passou
    b = barras("10:00", "10:01")
    agora = datetime(2026, 10, 1, 10, 3, 20)
    tick = datetime(2026, 10, 1, 10, 1, 10)
    assert C.fechados(b, agora, tick).height == 2


def test_apos_queda_de_3h_devolve_tudo_menos_o_em_formacao():
    horas = [f"{h:02d}:{m:02d}" for h in range(10, 13) for m in range(60)]
    b = barras(*horas, "13:00")
    agora = datetime(2026, 10, 1, 13, 0, 20)
    assert C.fechados(b, agora).height == 180


def test_fechados_sem_barras_devolve_vazio():
    vazio = barras("10:00").head(0)
    assert C.fechados(vazio, datetime(2026, 10, 1, 10, 5)).height == 0
```

- [ ] **Step 2: rodar** `.venv/Scripts/python.exe -m pytest tests/test_captura.py -q` → FAIL (`core.captura` não existe).

- [ ] **Step 3: implementar** `core/captura.py`:

```python
"""Serviço de captura: as contas, sem Dash e sem MetaTrader5 no topo.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §5.

O processo (`captura.py`, na raiz) é só o laço; tudo o que decide alguma
coisa mora aqui, para ser testado com MT5 e relógio falsos. A regra que
sustenta o resto: a captura nunca depende de ter "visto" cada minuto — a
cada volta pede ao MT5 tudo o que fechou desde o último candle salvo.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

# O minuto só fecha quando o seguinte começa; 5 s de folga cobrem o atraso
# entre o relógio do PC e o servidor da corretora.
FECHA_APOS = timedelta(seconds=65)
# Tick mais novo que isto é a melhor referência de "agora" (não depende do
# relógio do PC); mais velho, o mercado está parado e vale o relógio.
TICK_FRESCO = timedelta(minutes=2)


def fechados(barras: pl.DataFrame, agora: datetime,
             ultimo_tick: datetime | None = None) -> pl.DataFrame:
    """Só os candles fechados. Todos menos o último já fecharam (existe
    barra depois deles); o último só fecha 65 s depois do início do minuto
    — medido pelo tick do MT5 quando ele é recente, para um PC adiantado
    não gravar o candle em formação."""
    if barras.height == 0:
        return barras
    barras = barras.sort("ts")
    referencia = agora
    if ultimo_tick is not None and abs(agora - ultimo_tick) < TICK_FRESCO:
        referencia = ultimo_tick
    if referencia >= barras["ts"][-1] + FECHA_APOS:
        return barras
    return barras.head(barras.height - 1)
```

- [ ] **Step 4: rodar** → PASS.

- [ ] **Step 5: corrigir `core/mt5_source.py`.**
  - Apagar `offset_servidor` inteira.
  - `buscar_barras`: docstring nova (o `time` do MT5 já é hora de Brasília; o pedido também vai em hora de Brasília); pedir com `desde.replace(tzinfo=timezone.utc)` e `ate.replace(tzinfo=timezone.utc)` (o pacote converte datetime sem fuso pelo fuso do PC, o que deslocaria a janela pedida em 3 h; com `utc` o número enviado é o horário de parede, que é como o MT5 conta); devolver `pl.from_epoch("time", time_unit="s").alias("ts")` **sem** `+ offset`.
  - Nova função:

```python
def ultimo_tick(symbol: str) -> datetime | None:
    """Hora do último negócio, no relógio da corretora (Brasília). None se
    o terminal não responder — quem chama decide pelo relógio do PC."""
    try:
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(symbol)
    except Exception:  # noqa: BLE001 - sem tick, decide-se pelo relógio
        return None
    if tick is None:
        return None
    return datetime.fromtimestamp(tick.time, tz=timezone.utc).replace(tzinfo=None)
```

  - `sincronizar`: dentro do `with _TERMINAL:` (antes de `desconectar`), ler `tick = ultimo_tick(symbol)`; depois do bloco, `barras = captura.fechados(barras, datetime.now(), tick)` (import `from . import captura`); se `barras.height == 0`, `raise MT5Error("nenhum candle fechado novo no MT5 — tente de novo em um minuto")`. Reescrever o comentário do `ate = datetime.now() + timedelta(days=1)`: o MT5 nunca devolve barra do futuro, a folga só garante pegar até o último minuto.

- [ ] **Step 6: atualizar `tests/test_mt5_source.py`.**
  - Apagar os 5 testes de `offset_servidor`, `_FakeMT5Offset`, `_instalar_fake_mt5`, `_FakeMT5RatesComOffset` e `test_buscar_barras_pede_em_utc_e_devolve_em_hora_de_corretor`.
  - Fixture autouse no arquivo: `monkeypatch.setattr(src, "ultimo_tick", lambda s: None)`.
  - Novos testes:

```python
def test_buscar_barras_nao_desloca_a_hora(monkeypatch):
    """Achado real (01/10/2026): o MT5 devolve `time` já em hora de
    Brasília. Somar o fuso gravou seis meses de pregão de 06:00 a 15:24."""
    nove = int(datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc).timestamp())
    import numpy as np
    taxas = np.array([(nove, 1.0, 2.0, 0.5, 1.5, 10, 1, 0)], dtype=[
        ("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
        ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4"),
        ("real_volume", "i8")])
    pedido = {}

    class Fake(_FakeMT5Rates):
        def copy_rates_range(self, symbol, tf, desde, ate):
            pedido.update(desde=desde, ate=ate)
            return taxas

    monkeypatch.setitem(sys.modules, "MetaTrader5", Fake())
    df = src.buscar_barras("WIN$N", datetime(2026, 9, 22, 9, 0),
                           datetime(2026, 9, 22, 18, 30))
    assert df["ts"][0] == datetime(2026, 9, 22, 9, 0)
    assert pedido["desde"] == datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)


def test_mt5_source_nao_tem_mais_offset():
    assert not hasattr(src, "offset_servidor")


def test_sincronizar_descarta_o_candle_em_formacao(con, tmp_path, monkeypatch):
    seed = tmp_path / "seed.tsv"
    from tests.test_ingest import write_export
    write_export(seed, [(datetime(2026, 9, 1, 9, 0), 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)
    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    agora = datetime.now().replace(second=0, microsecond=0)
    monkeypatch.setattr(src, "buscar_barras", lambda s, d, a: pl.DataFrame({
        "ts": [agora - timedelta(minutes=1), agora],
        "open": [100010, 100020], "high": [100060, 100070],
        "low": [99960, 99970], "close": [100020, 100030],
        "tick_volume": [80, 5], "volume": [0, 0], "spread": [5, 5]}))
    monkeypatch.setattr(src, "ultimo_tick", lambda s: agora + timedelta(seconds=3))
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)

    r = src.sincronizar(con, "WIN$N", price_decimals=0)

    assert r.ingest.rows_inserted == 1
    assert con.execute("SELECT max(ts) FROM bars_m1").fetchone()[0] == agora - timedelta(minutes=1)
```

  - `test_buscar_barras_converte_epoch_e_renomeia_colunas`: o esperado passa a ser `datetime.fromtimestamp(1758441600, tz=timezone.utc).replace(tzinfo=None)` (já é — confira que continua passando sem offset).

- [ ] **Step 7: rodar** `tests/test_captura.py tests/test_mt5_source.py tests/test_mt5_ler_conta.py` → PASS; depois a suíte inteira.

- [ ] **Step 8: mutação** — (a) volte o `+ offset` em `buscar_barras` usando um offset fixo de −3 h → `test_buscar_barras_nao_desloca_a_hora` falha; (b) troque `FECHA_APOS` por 0 → testes de `fechados` falham; (c) ignore `ultimo_tick` em `fechados` → teste do PC adiantado falha. Desfaça cada uma.

- [ ] **Step 9: commit** — `core/captura.py core/mt5_source.py tests/test_captura.py tests/test_mt5_source.py`, mensagem `fix(mt5): hora do MT5 ja e Brasilia; Sincronizar nao grava o candle em formacao`.

---

### Task 2: Roteiro da correção da base (§0), sem executar

**Files:**
- Create: `core/reparo_base.py`, `corrigir_base.py` (raiz)
- Modify: `core/diario.py` (tipo `base_corrigida`)
- Test: `tests/test_reparo_base.py`

**Interfaces:**
- Consumes: `ing.ingest_csv`, `mt5_source.sincronizar` (Task 1), `diario.registrar`.
- Produces: `reparo_base.apagar_derivados(con) -> dict[str, int]`; `reparo_base.apagar_lotes(con, symbol, ids) -> int`; `reparo_base.sessoes_suspeitas(con, symbol, desde: date) -> list[dict]`; `reparo_base.TABELAS_DERIVADAS`.

- [ ] **Step 1: testes (falhando)** — `tests/test_reparo_base.py`:

```python
"""Correção da base com hora deslocada (spec captura §0)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario  # noqa: E402
from core import ingest as ing  # noqa: E402
from core import reparo_base as R  # noqa: E402
from core import calendar as cal  # noqa: E402
from tests.test_ingest import serie, write_export  # noqa: E402


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "t.duckdb")
    db.init_schema(c)
    yield c
    c.close()


def _semear_cadeia(con):
    con.execute("INSERT INTO estrategia_variantes VALUES (1, 'x', 'v', NULL, now())")
    con.execute("INSERT INTO mining_runs (run_id, variante_id) VALUES (1, 1)")
    con.execute("INSERT INTO mining_trials (run_id, trial_id) VALUES (1, 1)")
    con.execute("INSERT INTO wfa_runs (wfa_id, run_id) VALUES (1, 1)")
    con.execute("INSERT INTO wfa_trades (wfa_id, n) VALUES (1, 1)")
    con.execute("INSERT INTO planos_operacao (plano_id, wfa_id, run_id) VALUES (1, 1, 1)")
    con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) VALUES (1, 'p', now())")
    con.execute("INSERT INTO portfolio_variantes VALUES (1, 1, now())")
    con.execute("INSERT INTO portfolio_membros (ligacao_id, portfolio_id, variante_id, "
                "adicionado_em, fase, fase_desde, ligada) VALUES (1, 1, 1, now(), 'papel', now(), true)")
    con.execute("INSERT INTO contas (conta_id, nome, tipo, criado_em) VALUES (1, 'c', 'demo', now())")
    diario.registrar(con, "conta_criada", "usuario", conta_id=1)


def test_apagar_derivados_esvazia_a_cadeia_e_poupa_contas_diario_e_barras(con, tmp_path):
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", serie(datetime(2026, 3, 9, 9, 0), 3)), "WIN$N")
    _semear_cadeia(con)

    apagadas = R.apagar_derivados(con)

    for t in R.TABELAS_DERIVADAS:
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
    assert apagadas["mining_runs"] == 1 and apagadas["portfolios"] == 1
    assert con.execute("SELECT count(*) FROM contas").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM ao_vivo_eventos").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM bars_m1").fetchone()[0] == 3


def test_apagar_lotes_so_apaga_as_barras_daqueles_lotes(con, tmp_path):
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", serie(datetime(2026, 3, 9, 9, 0), 3)), "WIN$N")
    ing.ingest_csv(con, write_export(tmp_path / "b.tsv", serie(datetime(2026, 3, 16, 6, 0), 4)), "WIN$N")

    assert R.apagar_lotes(con, "WIN$N", (2,)) == 4
    assert con.execute("SELECT count(*), min(src_ingest_id) FROM bars_m1").fetchone() == (3, 1)


def test_sessoes_suspeitas_acusa_pregao_das_06h_e_poupa_o_normal(con, tmp_path):
    bom = serie(datetime(2026, 3, 9, 9, 0), 2) + serie(datetime(2026, 3, 9, 18, 23), 2)
    torto = serie(datetime(2026, 3, 16, 6, 0), 2) + serie(datetime(2026, 3, 16, 15, 23), 2)
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", bom + torto), "WIN$N")
    cal.rebuild_trading_days(con, "WIN$N")

    suspeitas = R.sessoes_suspeitas(con, "WIN$N", date(2026, 3, 1))

    assert [s["dia"] for s in suspeitas] == [date(2026, 3, 16)]
    assert suspeitas[0]["abre"] == "06:00" and suspeitas[0]["fecha"] == "15:24"


def test_diario_aceita_base_corrigida():
    assert "base_corrigida" in diario.TIPOS
```

  Confira os nomes reais das colunas obrigatórias de cada tabela em `core/schema.sql` (os INSERTs acima só preenchem chaves; ajuste se alguma coluna `NOT NULL` faltar).

- [ ] **Step 2: rodar** → FAIL (módulo ausente).

- [ ] **Step 3: implementar** `core/reparo_base.py`:

```python
"""Correção da base com hora deslocada (spec 2026-10-01-ao-vivo-captura §0).

A sincronização de 23/09/2026 subtraiu 3 h de cada candle vindo do MT5.
Tudo o que foi minerado e testado depois disso olhou para pregões de
06:00 a 15:24; o usuário decidiu apagar a cadeia inteira e recomeçar.
Feito por SQL direto, de propósito: as funções da tela recusam apagar
cadeia protegida (plano em vigor), e aqui apagar tudo é a decisão.
"""
from __future__ import annotations

from datetime import date, time

# ordem: filhos antes dos pais. Contas e o diário ficam — são registro do
# que existiu, não resultado calculado sobre a base errada.
TABELAS_DERIVADAS = (
    "mining_trials", "wfa_trades", "planos_operacao", "wfa_runs",
    "mining_runs", "portfolio_membros", "portfolio_variantes",
    "portfolios", "estrategia_variantes",
)

ABRE = ((time(9, 0), time(9, 15)), (time(13, 0), time(13, 15)))  # 13h: quarta de cinzas
FECHA = (time(17, 45), time(18, 30))


def apagar_derivados(con) -> dict[str, int]:
    apagadas = {}
    for t in TABELAS_DERIVADAS:
        apagadas[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        con.execute(f"DELETE FROM {t}")
    return apagadas


def apagar_lotes(con, symbol: str, ids) -> int:
    ids = [int(i) for i in ids]
    marcas = ",".join("?" * len(ids))
    n = con.execute(f"SELECT count(*) FROM bars_m1 WHERE symbol = ? "
                    f"AND src_ingest_id IN ({marcas})", [symbol, *ids]).fetchone()[0]
    con.execute(f"DELETE FROM bars_m1 WHERE symbol = ? AND src_ingest_id IN ({marcas})",
                [symbol, *ids])
    return n


def sessoes_suspeitas(con, symbol: str, desde: date) -> list[dict]:
    """Pregões cujo primeiro ou último candle está fora do horário da B3.
    É para um humano olhar, não para corrigir sozinho: dia de fechamento
    antecipado aparece aqui e é legítimo."""
    linhas = con.execute(
        "SELECT date, first_ts, last_ts, bar_count FROM trading_days "
        "WHERE symbol = ? AND date >= ? ORDER BY date", [symbol, desde]).fetchall()
    fora = []
    for dia, primeiro, ultimo, n in linhas:
        abre_ok = any(a <= primeiro.time() <= b for a, b in ABRE)
        fecha_ok = FECHA[0] <= ultimo.time() <= FECHA[1]
        if not (abre_ok and fecha_ok):
            fora.append({"dia": dia, "abre": f"{primeiro:%H:%M}",
                         "fecha": f"{ultimo:%H:%M}", "candles": n})
    return fora
```

  E em `core/diario.py`, acrescentar `"base_corrigida"` ao `TIPOS`.

- [ ] **Step 4: rodar** → PASS.

- [ ] **Step 5: roteiro** `corrigir_base.py` (raiz). Sem teste automático (é o roteiro de uma vez só; as contas estão testadas acima). Comportamento:

```python
"""Correção da base com hora deslocada — roda UMA vez (spec captura §0).

    .venv/Scripts/python.exe corrigir_base.py            # simulação: só mostra
    .venv/Scripts/python.exe corrigir_base.py --executar # faz

Antes: feche o app (iniciar.bat) e a captura; abra o MT5 logado.
"""
```

  Passos de `main()` com `--executar` (sem ele: imprime o que apagaria — contagens de `TABELAS_DERIVADAS`, barras dos lotes, arquivos a renomear — e sai com 0):
  1. Lotes errados = `ingest_id` do `ingest_log` cujo `source_file` contém `mt5_sync_2026092` (hoje: 3 e 4) — imprimir e recusar se não forem exatamente `{3, 4}`, a menos que `--lotes 3,4` seja passado.
  2. Backup: copiar `db.DB_PATH` e a pasta `db.PARQUET_DIR` para `ROOT.parent / "backups" / f"{hoje:%Y-%m-%d}-antes-correcao-hora"`; recusar continuar se a pasta já existir.
  3. `with db.connect_write() as con:` + `db.transacao(con)`: `apagar_derivados`, `apagar_lotes(con, "WIN$N", lotes)`, `diario.registrar(con, "base_corrigida", "sistema", motivo="hora do MT5 deslocada em 3 h (16/03→23/09/2026); cadeia apagada")`.
  4. Renomear cada `source_file` desses lotes que exista para `<nome>.hora-errada`.
  5. `ing.ingest_csv(con, CSV, "WIN$N", price_decimals=0)` com `CSV = db.RAW_DIR / "m1-hist-16-03-2026.csv"` (argumento `--csv` para trocar).
  6. `src.sincronizar(con, "WIN$N", price_decimals=0)` (baixa de `ultimo − 5 dias` até agora, reconstrói `trading_days`/`rollovers` e o Parquet).
  7. Relatório: total de candles, último candle, `sessoes_suspeitas(con, "WIN$N", date(2026, 3, 9))` uma por linha, e uma tabela dia → primeiro/último/candles de 09/03 até hoje.
  Cada passo imprime o que fez; qualquer erro para o roteiro com a mensagem e o lembrete de que o backup está em `<pasta>`.

- [ ] **Step 6: simulação** — com o app aberto ou não, rodar `.venv/Scripts/python.exe corrigir_base.py` (sem `--executar`) e conferir que só lê: espera-se ver lotes {3, 4}, 77.202 barras deles e as contagens atuais das 9 tabelas. **Não rodar com `--executar` nesta tarefa.**

- [ ] **Step 7: suíte inteira + mutação** (troque `ABRE` para aceitar 06:00 → o teste de sessões suspeitas falha; tire `portfolios` de `TABELAS_DERIVADAS` → o teste de apagar falha). Commit — `core/reparo_base.py core/diario.py corrigir_base.py tests/test_reparo_base.py`, mensagem `feat(base): roteiro da correcao da hora deslocada (spec captura §0)`.

---

### Task 3: Executar a correção da base (controlador, com o usuário)

**Destrutivo — o controlador para e pede o "pode rodar" do usuário antes**, e confirma: app fechado, MT5 aberto e logado.

- [ ] **Step 1:** `.venv/Scripts/python.exe corrigir_base.py --executar`; guardar a saída no ledger.
- [ ] **Step 2: conferir dia a dia** — a lista de sessões suspeitas deve trazer só dias de horário especial legítimo (ex.: fechamento antecipado); nenhum dia com abertura 06:xx. Último candle = último minuto fechado do MT5 (nunca o em formação).
- [ ] **Step 3:** subir o app (`preview_start` com `dataframe`), abrir o Backtest em 1D/5D e tirar screenshot mostrando o eixo das 09:00 às 18:2x. Mostrar ao usuário.
- [ ] **Step 4:** registrar no ledger o caminho do backup e os números. Sem commit (só dado).

---

### Task 4: `ingest_df` — o merge para candles que não vêm de arquivo

**Files:**
- Modify: `core/ingest.py`
- Test: `tests/test_ingest.py` (acrescentar no fim)

**Interfaces:**
- Produces: `ing.validar(df: pl.DataFrame, nome: str, price_decimals: int = 0) -> pl.DataFrame`; `ing.sha256_df(df) -> str`; `ing.ingest_df(con, df, symbol: str, origem: str, sha: str, source_max_ts: datetime | None = None, price_decimals: int = 0) -> IngestResult`.

- [ ] **Step 1: testes (falhando)**:

```python
# ------------------------------------------------------------- ingest_df
def _df(linhas):
    return pl.DataFrame(
        [(ts, o, h, lo, c, 100, 500, 5) for ts, o, h, lo, c in linhas],
        schema=["ts", "open", "high", "low", "close", "tick_volume", "volume", "spread"],
        orient="row")


def _barras(con):
    return con.execute("SELECT ts, open, high, low, close, tick_volume, volume, "
                       "spread FROM bars_m1 ORDER BY ts").fetchall()


def test_ingest_df_da_o_mesmo_que_ingest_csv(tmp_path):
    linhas = serie(datetime(2026, 3, 9, 9, 0), 5, passo=10)
    a = db.connect(tmp_path / "a.duckdb"); db.init_schema(a)
    b = db.connect(tmp_path / "b.duckdb"); db.init_schema(b)
    ing.ingest_csv(a, write_export(tmp_path / "x.tsv", linhas), "WIN$N")
    ing.ingest_df(b, _df(linhas), "WIN$N", "captura://1@srv", "sha-x")
    assert _barras(a) == _barras(b)
    a.close(); b.close()


def test_ingest_df_aceita_preco_float_inteiro_do_mt5(con):
    df = _df(serie(datetime(2026, 3, 9, 9, 0), 2)).with_columns(
        [pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close")])
    r = ing.ingest_df(con, df, "WIN$N", "captura://1@srv", "sha")
    assert r.rows_inserted == 2


def test_ingest_df_recusa_ohlc_incoerente_e_duplicata(con):
    ts = datetime(2026, 3, 9, 9, 0)
    with pytest.raises(ValueError, match="incoerente"):
        ing.ingest_df(con, _df([(ts, 100, 90, 95, 100)]), "WIN$N", "o", "s")
    with pytest.raises(ValueError, match="duplicados"):
        ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)] * 2), "WIN$N", "o", "s")
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 0


def test_source_max_ts_informado_vence_versao_do_mesmo_minuto(con):
    """A conferência do dia relê o mesmo minuto que a captura gravou: o
    `source_max_ts` dela (hora em que rodou) é o que a faz vencer."""
    ts = datetime(2026, 3, 9, 9, 0)
    ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)]), "WIN$N", "captura://", "b")
    r = ing.ingest_df(con, _df([(ts, 100, 120, 90, 105)]), "WIN$N",
                      "conferencia://2026-03-09", "a",
                      source_max_ts=datetime(2026, 3, 9, 18, 30))
    assert r.rows_updated == 1
    assert con.execute("SELECT high, close FROM bars_m1").fetchone() == (120, 105)
    assert con.execute("SELECT max(source_max_ts) FROM ingest_log").fetchone()[0] == datetime(2026, 3, 9, 18, 30)
```

  (`pl` já é importado em `tests/test_ingest.py`? Se não, `import polars as pl` no topo.)

- [ ] **Step 2: rodar** → FAIL.

- [ ] **Step 3: implementar** em `core/ingest.py`:
  - Extrair de `read_mt5_export` tudo o que vem depois do `drop("date_str", "time_str")` para `validar(df, nome, price_decimals=0)` (mensagens idênticas, trocando `path.name` por `nome`; antes das checagens, `df.select("ts", "open", "high", "low", "close", "tick_volume", "volume", "spread")` para recusar coluna faltando com `ValueError`). `read_mt5_export` passa a terminar em `return validar(df, path.name, price_decimals)`.
  - `sha256_df(df)`: `hashlib.sha256(df.sort("ts").write_csv().encode()).hexdigest()`.
  - `ingest_df(...)`: `df = validar(df, origem, price_decimals)`; mesmo bloco `BEGIN/COMMIT/ROLLBACK + DROP _stage` de `ingest_csv`; chama `_merge(con, origem, sha, symbol, df, source_max_ts)`.
  - `_merge(con, source_file: str, sha: str, symbol, df, source_max_ts=None)`: `src_max = source_max_ts or df["ts"].max()`; grava `source_file` como texto; o resto igual.
  - `ingest_csv`: `df = read_mt5_export(path, price_decimals)` e `return ingest_df(con, df, symbol, str(path), sha256_of(path), price_decimals=price_decimals)`. Atualizar o docstring do módulo (uma frase: candles da captura entram por `ingest_df`, mesma regra).

- [ ] **Step 4: rodar** `tests/test_ingest.py tests/test_mt5_source.py` → PASS (os testes antigos de `ingest_csv` não mudam). Suíte inteira.
- [ ] **Step 5: mutação** — ignore `source_max_ts` em `_merge` → o último teste falha; tire a checagem de OHLC de `validar` → o teste de incoerente falha.
- [ ] **Step 6: commit** — `core/ingest.py tests/test_ingest.py`, `refactor(ingest): ingest_df para candles que nao vem de arquivo`.

---

### Task 5: As contas da captura (`core/captura.py`)

**Files:**
- Modify: `core/captura.py`, `.gitignore` (acrescentar `data/ao_vivo/`)
- Test: `tests/test_captura.py`

**Interfaces:**
- Consumes: `ing.ingest_df`, `ing.validar`, `ing.sha256_df` (Task 4); `fechados` (Task 1).
- Produces (usado pelas Tasks 7–9):
  - `PREFIXO_CAPTURA = "captura://"`, `PREFIXO_CONFERENCIA = "conferencia://"`
  - `origem_captura(login, servidor) -> str` → `"captura://<login>@<servidor>"`
  - `gravar(con, symbol, barras: pl.DataFrame, origem: str, price_decimals=0) -> dict` com `{"inseridos": int, "revisados": int}`
  - `lacunas(ts_mt5, ts_banco) -> list[datetime]`
  - `fechamento_esperado(con, symbol) -> time` (padrão `time(18, 24)`)
  - `em_pregao(agora: datetime, fechamento: time) -> bool`
  - `dias_pendentes(con, symbol, hoje: date, fechou_hoje: bool) -> list[date]`
  - `conferir_dia(con, symbol, dia: date, barras_mt5: pl.DataFrame, agora: datetime, price_decimals=0) -> dict` com `{"revisados", "faltantes"}`
  - `escrever_estado(caminho: Path, dados: dict) -> None`; `ler_estado(caminho: Path) -> dict | None`

- [ ] **Step 1: testes (falhando)** — acrescentar a `tests/test_captura.py`:

```python
from datetime import date, time  # noqa: E402
import json  # noqa: E402
from core import calendar as cal  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "t.duckdb")
    db.init_schema(c)
    yield c
    c.close()


def _contar(con):
    return con.execute("SELECT count(*) FROM bars_m1").fetchone()[0]


# ---------------------------------------------------------------- gravar
def test_gravar_insere_e_registra_a_origem(con):
    r = C.gravar(con, "WIN$N", barras("10:00", "10:01"), "captura://1@srv")
    assert r == {"inseridos": 2, "revisados": 0}
    assert con.execute("SELECT source_file FROM ingest_log").fetchone()[0] == "captura://1@srv"


def test_gravar_repetido_nao_grava_nem_cria_lote(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    r = C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    assert r == {"inseridos": 0, "revisados": 0}
    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 1


def test_gravar_candle_diferente_vira_revisao(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    r = C.gravar(con, "WIN$N", barras("10:00", "10:01", base=100020), "captura://1@srv")
    assert r == {"inseridos": 1, "revisados": 1}


# --------------------------------------------------------------- lacunas
def test_lacunas_so_o_que_o_mt5_tem_e_o_banco_nao():
    m = lambda *h: barras(*h)["ts"].to_list()  # noqa: E731
    assert C.lacunas(m("09:03", "09:04", "09:05"), m("09:03", "09:04", "09:05")) == []
    assert C.lacunas(m("09:03", "09:04", "09:05"), m("09:03", "09:05")) == m("09:04")
    # minuto que ninguém tem (leilão 09:00–09:02, mercado parado) não é lacuna
    assert C.lacunas(m("09:03", "09:06"), m("09:03", "09:06")) == []


# --------------------------------------------- fechamento e horário de pregão
def _dia(con, d, fecha):
    df = barras("09:00", fecha).with_columns(
        pl.col("ts").map_elements(lambda t: t.replace(year=d.year, month=d.month, day=d.day),
                                  return_dtype=pl.Datetime("us")))
    ing.ingest_df(con, df, "WIN$N", f"t{d}", f"s{d}")


def test_fechamento_esperado_e_o_mais_frequente_dos_ultimos_10(con):
    for i in range(1, 9):
        _dia(con, date(2026, 9, i), "17:54")
    _dia(con, date(2026, 9, 9), "18:24")
    cal.rebuild_trading_days(con, "WIN$N")
    assert C.fechamento_esperado(con, "WIN$N") == time(17, 54)


def test_fechamento_esperado_sem_historico_e_18_24(con):
    assert C.fechamento_esperado(con, "WIN$N") == time(18, 24)


def test_em_pregao():
    f = time(17, 54)
    assert C.em_pregao(datetime(2026, 10, 1, 9, 0), f)          # quinta
    assert C.em_pregao(datetime(2026, 10, 1, 17, 59), f)        # folga de 6 min
    assert not C.em_pregao(datetime(2026, 10, 1, 18, 1), f)
    assert not C.em_pregao(datetime(2026, 10, 1, 8, 50), f)
    assert not C.em_pregao(datetime(2026, 10, 3, 10, 0), f)     # sábado


# ------------------------------------------------------------ conferência
def test_conferencia_vence_a_captura_do_mesmo_minuto(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    r = C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00", "10:01", base=100020),
                       agora=datetime(2026, 10, 1, 18, 30))
    assert r == {"revisados": 1, "faltantes": 1}
    assert con.execute("SELECT DISTINCT open FROM bars_m1").fetchall() == [(100020,)]


def test_exportacao_manual_posterior_vence_a_conferencia(con, tmp_path):
    from tests.test_ingest import write_export
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00"),
                   agora=datetime(2026, 10, 1, 18, 30))
    ing.ingest_csv(con, write_export(tmp_path / "m.tsv", [
        (datetime(2026, 10, 1, 10, 0), 99000, 99100, 98900, 99050),
        (datetime(2026, 10, 2, 18, 24), 99000, 99100, 98900, 99050)]), "WIN$N")
    assert con.execute("SELECT open FROM bars_m1 WHERE ts = '2026-10-01 10:00'").fetchone()[0] == 99000


def test_conferencia_sem_nada_novo_ainda_marca_o_dia(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    C.conferir_dia(con, "WIN$N", date(2026, 10, 1), barras("10:00"),
                   agora=datetime(2026, 10, 1, 18, 30))
    assert C.dias_pendentes(con, "WIN$N", date(2026, 10, 2), fechou_hoje=False) == []


def test_conferencia_recusa_dia_sem_candle_do_mt5(con):
    with pytest.raises(ValueError, match="não devolveu"):
        C.conferir_dia(con, "WIN$N", date(2026, 10, 2), barras("10:00"),
                       agora=datetime(2026, 10, 2, 18, 30))


def test_recuperacao_de_3_dias_deixa_os_3_pendentes(con):
    for d in (date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)):
        df = barras("10:00").with_columns(pl.lit(datetime(d.year, d.month, d.day, 10, 0)).alias("ts"))
        C.gravar(con, "WIN$N", df, "captura://1@srv")
    hoje = date(2026, 10, 1)
    assert C.dias_pendentes(con, "WIN$N", hoje, fechou_hoje=False) == [
        date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]


def test_hoje_so_fica_pendente_depois_do_fechamento(con):
    C.gravar(con, "WIN$N", barras("10:00"), "captura://1@srv")
    hoje = date(2026, 10, 1)
    assert C.dias_pendentes(con, "WIN$N", hoje, fechou_hoje=False) == []
    assert C.dias_pendentes(con, "WIN$N", hoje, fechou_hoje=True) == [hoje]


# ----------------------------------------------------------------- estado
def test_estado_ida_e_volta(tmp_path):
    p = tmp_path / "ao_vivo" / "estado.json"
    C.escrever_estado(p, {"mt5": "conectado", "ultimo_salvo": datetime(2026, 10, 1, 10, 0)})
    assert C.ler_estado(p) == {"mt5": "conectado", "ultimo_salvo": "2026-10-01T10:00:00"}
    assert not p.with_suffix(".tmp").exists()


def test_estado_ilegivel_ou_ausente_devolve_none(tmp_path):
    p = tmp_path / "estado.json"
    assert C.ler_estado(p) is None
    p.write_text("{meio arquivo", encoding="utf-8")
    assert C.ler_estado(p) is None


def test_escrever_estado_tenta_de_novo_se_o_windows_recusar(tmp_path, monkeypatch):
    p = tmp_path / "estado.json"
    real = C.os.replace
    falhas = {"n": 0}

    def replace_teimoso(a, b):
        if falhas["n"] < 2:
            falhas["n"] += 1
            raise PermissionError("arquivo em uso")
        return real(a, b)

    monkeypatch.setattr(C.os, "replace", replace_teimoso)
    C.escrever_estado(p, {"ok": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": 1}
```

- [ ] **Step 2: rodar** → FAIL.

- [ ] **Step 3: implementar** — acrescentar a `core/captura.py` (imports: `json`, `os`, `time as _t`, `date`, `time` de datetime, `Path`, `from . import ingest as ing`):

```python
PREFIXO_CAPTURA = "captura://"
PREFIXO_CONFERENCIA = "conferencia://"
_COLUNAS = ("ts", "open", "high", "low", "close", "tick_volume", "volume", "spread")
FOLGA_FECHAMENTO = timedelta(minutes=6)
ABERTURA_ANTES = time(8, 55)
FECHAMENTO_PADRAO = time(18, 24)


def origem_captura(login, servidor) -> str:
    return f"{PREFIXO_CAPTURA}{login}@{servidor}"


def gravar(con, symbol: str, barras: pl.DataFrame, origem: str,
           price_decimals: int = 0) -> dict:
    """Grava só o que é novo ou diferente do banco. Sem isso cada volta de
    1 s criaria um lote no ingest_log mesmo sem candle novo."""
    zero = {"inseridos": 0, "revisados": 0}
    if barras.height == 0:
        return zero
    barras = ing.validar(barras, origem, price_decimals)
    linhas = con.execute(
        f"SELECT {', '.join(_COLUNAS)} FROM bars_m1 "
        "WHERE symbol = ? AND ts BETWEEN ? AND ?",
        [symbol, barras["ts"].min(), barras["ts"].max()]).fetchall()
    if linhas:
        banco = pl.DataFrame(linhas, schema=list(_COLUNAS), orient="row").with_columns(
            [pl.col(c).cast(barras.schema[c]) for c in _COLUNAS])
        barras = barras.join(banco, on=list(_COLUNAS), how="anti")
    if barras.height == 0:
        return zero
    r = ing.ingest_df(con, barras, symbol, origem, ing.sha256_df(barras),
                      price_decimals=price_decimals)
    return {"inseridos": r.rows_inserted, "revisados": r.rows_updated}


def lacunas(ts_mt5, ts_banco) -> list[datetime]:
    """Minuto que o MT5 tem e o banco não. Minuto que nenhum dos dois tem
    (leilão, mercado parado) é minuto sem negócio, não alerta."""
    return sorted(set(ts_mt5) - set(ts_banco))


def fechamento_esperado(con, symbol: str) -> time:
    """O mais frequente dos últimos 10 pregões: a B3 alterna 17:54/18:24
    com o horário de verão americano, e um relógio fixo erraria metade do ano."""
    linha = con.execute(
        "SELECT CAST(last_ts AS TIME) AS t, count(*) AS n FROM ("
        "  SELECT last_ts FROM trading_days WHERE symbol = ? "
        "  ORDER BY date DESC LIMIT 10) GROUP BY 1 ORDER BY n DESC, t DESC LIMIT 1",
        [symbol]).fetchone()
    return linha[0] if linha else FECHAMENTO_PADRAO


def em_pregao(agora: datetime, fechamento: time) -> bool:
    if agora.weekday() >= 5:
        return False
    fim = (datetime.combine(agora.date(), fechamento) + FOLGA_FECHAMENTO).time()
    return ABERTURA_ANTES <= agora.time() <= fim


def dias_pendentes(con, symbol: str, hoje: date, fechou_hoje: bool) -> list[date]:
    """Dias com candle gravado pela captura e ainda sem conferência. O
    registro da conferência é uma linha no ingest_log — sobrevive a
    reinício, sem tabela nova."""
    dias = [r[0] for r in con.execute(
        "SELECT DISTINCT CAST(b.ts AS DATE) AS d FROM bars_m1 b "
        "JOIN ingest_log l ON l.ingest_id = b.src_ingest_id "
        "WHERE b.symbol = ? AND l.source_file LIKE ? "
        "AND NOT EXISTS (SELECT 1 FROM ingest_log c WHERE c.symbol = ? "
        "  AND c.source_file = ? || strftime(CAST(b.ts AS DATE), '%Y-%m-%d')) "
        "ORDER BY d",
        [symbol, PREFIXO_CAPTURA + "%", symbol, PREFIXO_CONFERENCIA]).fetchall()]
    return [d for d in dias if d < hoje or (d == hoje and fechou_hoje)]


def conferir_dia(con, symbol: str, dia: date, barras_mt5: pl.DataFrame,
                 agora: datetime, price_decimals: int = 0) -> dict:
    """Relê o dia inteiro do MT5 depois do fechamento. `source_max_ts` =
    hora em que rodou: vence a captura do mesmo dia sem depender do
    desempate por sha256; uma exportação manual posterior continua vencendo."""
    do_dia = barras_mt5.filter(pl.col("ts").dt.date() == dia)
    if do_dia.height == 0:
        raise ValueError(f"o MT5 não devolveu candles de {dia:%d/%m/%Y}")
    r = ing.ingest_df(con, do_dia, symbol, f"{PREFIXO_CONFERENCIA}{dia:%Y-%m-%d}",
                      ing.sha256_df(do_dia), source_max_ts=agora,
                      price_decimals=price_decimals)
    return {"revisados": r.rows_updated, "faltantes": r.rows_inserted}


def escrever_estado(caminho: Path, dados: dict, tentativas: int = 3,
                    espera: float = 0.05) -> None:
    """.tmp + os.replace: quem lê nunca vê meio arquivo. No Windows o
    replace falha se a tela estiver lendo naquele instante — tenta de novo."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, default=_json, ensure_ascii=False), encoding="utf-8")
    for i in range(tentativas):
        try:
            os.replace(tmp, caminho)
            return
        except PermissionError:
            if i == tentativas - 1:
                raise
            _t.sleep(espera)


def _json(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    raise TypeError(f"não serializável: {type(v).__name__}")


def ler_estado(caminho: Path) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
```

  Acrescentar `data/ao_vivo/` ao `.gitignore`.

- [ ] **Step 4: rodar** `tests/test_captura.py` → PASS; suíte inteira.
- [ ] **Step 5: mutação** — (a) em `gravar`, pule o anti-join → o teste "repetido não grava" falha; (b) em `conferir_dia`, não passe `source_max_ts` → "conferência vence" falha; (c) em `dias_pendentes`, troque `d < hoje` por `d <= hoje` → "hoje só depois do fechamento" falha; (d) em `lacunas`, devolva a diferença simétrica → falha.
- [ ] **Step 6: commit** — `core/captura.py tests/test_captura.py .gitignore`, `feat(captura): gravar, lacunas, conferencia do dia e estado`.

---

### Task 6: Parquet trocado de uma vez

**Files:**
- Modify: `core/db_manager.py` (`export_parquet`)
- Test: `tests/test_db_parquet_atomico.py` (novo)

**Interfaces:**
- Produces: `db.export_parquet(con, symbol) -> Path` com a mesma assinatura, agora atômico.

- [ ] **Step 1: testes (falhando)**:

```python
"""O espelho Parquet nunca fica pela metade: a mineração lê dele enquanto
a captura reexporta depois da conferência do dia."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from tests.test_ingest import serie, write_export  # noqa: E402


def test_export_troca_a_pasta_inteira_e_nao_deixa_sobra(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    con = db.connect(tmp_path / "t.duckdb"); db.init_schema(con)
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", serie(datetime(2025, 12, 31, 9, 0), 2)), "WIN$N")
    db.export_parquet(con, "WIN$N")
    ing.ingest_csv(con, write_export(tmp_path / "b.tsv", serie(datetime(2026, 1, 2, 9, 0), 3)), "WIN$N")

    out = db.export_parquet(con, "WIN$N")

    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 5
    assert sorted(p.name for p in (tmp_path / "parquet").iterdir()) == [out.name]
    con.close()
```

- [ ] **Step 2: rodar** → FAIL? (Pode passar se o export atual já cobrir; se passar, acrescente a asserção de que o `COPY` grava numa pasta `<simbolo>.novo` — por monkeypatch de `con.execute` não vale; em vez disso confira o código e siga.) O teste fica como regressão.
- [ ] **Step 3: implementar**:

```python
def export_parquet(con, symbol: str) -> Path:
    """Reescreve o espelho Parquet do simbolo, particionado por ano.

    Grava numa pasta nova e troca de uma vez: a mineração e o walk-forward
    leem este espelho enquanto a captura reexporta depois da conferência do
    dia, e um COPY por cima da pasta em uso deixava um ano pela metade."""
    import shutil
    import time as _t

    out = PARQUET_DIR / safe_symbol(symbol)
    novo = out.with_name(out.name + ".novo")
    velho = out.with_name(out.name + ".velho")
    shutil.rmtree(novo, ignore_errors=True)
    novo.mkdir(parents=True)
    con.execute(f"""COPY (SELECT *, year(ts) AS year FROM bars_m1 WHERE symbol = ?
                    ORDER BY ts) TO {_sql_str(novo)}
                    (FORMAT PARQUET, PARTITION_BY (year), OVERWRITE_OR_IGNORE 1,
                     COMPRESSION zstd)""", [symbol])
    if not list(novo.rglob("*.parquet")):
        raise RuntimeError(f"COPY nao gravou nenhum arquivo em {novo}")
    # No Windows uma pasta com arquivo aberto (leitor no meio) não se
    # renomeia: espera o leitor soltar.
    for i in range(40):
        try:
            shutil.rmtree(velho, ignore_errors=True)
            if out.exists():
                out.rename(velho)
            novo.rename(out)
            break
        except PermissionError:
            if i == 39:
                raise
            _t.sleep(0.25)
    shutil.rmtree(velho, ignore_errors=True)
    return out
```

- [ ] **Step 4: rodar** o teste novo, `tests/test_mt5_source.py`, e a suíte inteira → PASS.
- [ ] **Step 5: commit** — `core/db_manager.py tests/test_db_parquet_atomico.py`, `fix(db): espelho Parquet trocado de uma vez`.

---

### Task 7: O processo `captura.py` e a janela própria

**Files:**
- Create: `captura.py` (raiz), `captura.bat` (raiz)
- Modify: `iniciar.bat`
- Test: `tests/test_captura_processo.py` (novo)

**Interfaces:**
- Consumes: tudo de `core/captura.py` (Tasks 1, 5); `db.connect_write`, `db.connect`, `db.export_parquet` (Task 6); `cal.rebuild_trading_days`, `roll.rebuild_rollovers`.
- Produces: o arquivo `data/ao_vivo/estado.json` com as chaves (lidas pelas Tasks 8–9):
  `pid, atualizado_em, mt5 ("conectado"|"sem_conexao"|"fechado"), mt5_desde, conta {login, servidor}, contrato_vigente, simbolo, fechamento_esperado ("HH:MM"), em_pregao, ultimo_salvo, em_formacao ({ts, open, high, low, close} | null), lacunas_hoje [iso], gravados_hoje, recuperados_hoje, revisados_hoje, conferencia {status: "pendente"|"concluida"|"falhou", em, dias}, banco_ocupado_desde, relogio_atrasado_s, erro`.
  Códigos de saída: `0` normal (Ctrl+C), `3` não reabrir, outros = reabrir.

**Desenho do `captura.py`** (classe com tudo injetável, para testar sem MT5 real):

```python
"""Serviço de captura — grava cada candle M1 fechado do WIN$N, ao vivo.

    .venv/Scripts/python.exe captura.py      (o iniciar.bat abre numa janela própria)

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md.
Processo à parte da tela de propósito: a tela reinicia a cada mudança e
trava em mineração; um laço contínuo dentro dela perderia candle (e, na
parte 4, ordem). Toda decisão mora em core/captura.py; aqui só o laço.
"""
SAIR_SEM_REABRIR = 3
PASTA = db.DATA / "ao_vivo"


class ErroDeConfiguracao(RuntimeError):
    """Erro que reabrir não resolve: o .bat não deve tentar de novo."""


def travar(caminho: Path):
    """Trava de instância pelo Windows (msvcrt.locking): se o processo
    morrer, o sistema solta sozinho — um arquivo .pid ficaria órfão."""
    import msvcrt
    caminho.parent.mkdir(parents=True, exist_ok=True)
    f = open(caminho, "a+")
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except OSError:
        f.close()
        return None


class Servico:
    def __init__(self, mt5, simbolo="WIN$N", terminal=None, agora=datetime.now,
                 pasta=PASTA, terminal_aberto=None, price_decimals=0): ...
    def volta(self) -> float:   # uma volta; devolve quantos segundos esperar
    def rodar(self) -> None:    # laço: volta(); sleep(espera); erro inesperado → log + estado["erro"]
```

`volta()`, nesta ordem:
1. `agora = self.agora()`; `self.fechamento` (lido do banco na primeira volta e a cada troca de dia, via `fechamento_esperado` numa conexão `db.connect(read_only=True)` curta); `pregao = em_pregao(agora, fechamento)`.
2. **MT5:** se ainda não conectado → só chama `mt5.initialize(path=terminal)` (ou `initialize()` sem caminho) **se `terminal_aberto()` for verdadeiro** (padrão: `tasklist /FI "IMAGENAME eq terminal64.exe"` contém `terminal64.exe`) — chamar sem o MT5 aberto abriria um terminal sozinho. Falhou ou fechado → `mt5="fechado"`, grava estado, devolve 30. `terminal_info()` `None` → marca desconectado (próxima volta reinicializa), `mt5="fechado"`. `connected False` → `mt5="sem_conexao"` (guarda `mt5_desde` na primeira vez), devolve 5. Na primeira conexão: `symbol_select(simbolo, True)` falso → `ErroDeConfiguracao(f"o MT5 não tem {simbolo}")`; `account_info()` → `conta`; `symbol_info(simbolo).basis` (se existir) → `contrato_vigente`.
3. **Último salvo:** na primeira volta, `SELECT max(ts)` (conexão de leitura curta); sem barra nenhuma → `ErroDeConfiguracao("base vazia — rode corrigir_base.py / cli.py ingest antes")`.
4. **Busca:** `copy_rates_range(simbolo, M1, (ultimo + 1 min) com tzinfo=utc, (agora + 1 dia) com tzinfo=utc)` → DataFrame igual ao de `mt5_source.buscar_barras` (sem offset; `None`/vazio = nada novo). `tick = symbol_info_tick` convertido como em `mt5_source.ultimo_tick`. `prontos = fechados(df, agora, tick)`; `em_formacao` = última linha de `df` se não estiver em `prontos`, senão `None`. `relogio_atrasado_s = (tick − agora).total_seconds()` se `> 30`, senão `None`.
5. **Grava** (se `prontos`): `con = db.connect_write(tentativas=4, espera=0.25)` (≈1 s); `RuntimeError` (banco ocupado) → `banco_ocupado_desde = banco_ocupado_desde or agora`, **não** avança `ultimo`, devolve 1. Senão `gravar(con, simbolo, prontos, origem_captura(login, servidor))`, fecha, avança `ultimo = prontos.ts.max()`, `banco_ocupado_desde=None`; soma `gravados_hoje += inseridos`, `revisados_hoje += revisados`, `recuperados_hoje += (#prontos com ts < agora − 2 min)`. Contadores zeram na troca de dia.
6. **Lacunas** (a cada 60 s, no pregão): candles de hoje do MT5 (`copy_rates_range` do dia, `fechados`) × `SELECT ts FROM bars_m1` de hoje → `lacunas_hoje`. Lacuna achada → regrava pelo mesmo `gravar` (é a recuperação sozinha).
7. **Conferência** (a cada 5 min, e sempre na primeira volta conectada): `fechou = agora.time() > fechamento + 6 min`; `dias = dias_pendentes(con, simbolo, agora.date(), fechou)`. Para cada dia: candles do dia no MT5 (`copy_rates_range` 00:00→23:59 do dia, `fechados`), `conferir_dia(..., agora=agora)`. Se algum dia foi conferido: `cal.rebuild_trading_days`, `roll.rebuild_rollovers(con, simbolo, inst.get("rollover_policy"))`, `db.export_parquet`; `conferencia = {"status": "concluida", "em": agora, "dias": [...]}`. Erro → `{"status": "falhou", ...}` + log, tenta de novo na próxima janela de 5 min. Sem nada pendente e já fechou hoje → `status` fica o que estava; antes do fechamento → `"pendente"`.
8. **Hibernação:** no pregão `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)`; fora, `SetThreadExecutionState(0x80000000)`. (Ignorar se `ctypes.windll` não existir.)
9. **Estado:** `escrever_estado(pasta / "estado.json", {...})` com todas as chaves acima, `atualizado_em = agora`, `pid = os.getpid()`.
10. Devolve `1` no pregão, `30` fora.

`rodar()`: `ErroDeConfiguracao` **sobe** (o `main` transforma em código 3); qualquer outra exceção na volta → log com traceback, `estado["erro"] = str(e)`, espera 5 s e segue. Falha de banco ocupado na conferência ou nas lacunas não é erro: tenta na janela seguinte.

`main(argv=None) -> int`: argparse (`--simbolo` padrão `WIN$N`, `--terminal`); log em `PASTA / "captura.log"` (`RotatingFileHandler`, 5 MB, 3 cópias, e também no console); `trava = travar(PASTA / "captura.lock")` → `None` → log "outra janela da captura já está aberta" e `return 3`; `import MetaTrader5` falhou → estado com `erro` e `return 3`; sem `--terminal`, usa o `terminal` da conta não arquivada mais recente que tiver um (`SELECT terminal FROM contas WHERE arquivada_em IS NULL AND terminal IS NOT NULL ORDER BY conta_id DESC LIMIT 1`); `Servico(...).rodar()`; `KeyboardInterrupt` → `mt5.shutdown()`, `return 0`; `ErroDeConfiguracao` → estado com `erro`, log, `return 3`. Fim do arquivo: `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 1: testes (falhando)** — `tests/test_captura_processo.py` com um MT5 falso:

```python
"""O processo da captura com MT5 e relógio falsos (sem terminal de verdade)."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import captura as P  # noqa: E402
from core import captura as C  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from tests.test_ingest import write_export  # noqa: E402

_DT = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
       ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")]


def _epoch(ts):
    return int(ts.replace(tzinfo=timezone.utc).timestamp())


class MT5Falso:
    TIMEFRAME_M1 = 1

    def __init__(self, minutos, tick, conectado=True, aberto=True):
        self.minutos, self.tick = minutos, tick
        self.conectado, self.aberto = conectado, aberto
        self.inits = 0

    def initialize(self, path=None):
        self.inits += 1
        return self.aberto

    def terminal_info(self):
        return SimpleNamespace(connected=self.conectado) if self.aberto else None

    def symbol_select(self, s, on):
        return s == "WIN$N"

    def account_info(self):
        return SimpleNamespace(login=123, server="Srv-DEMO")

    def symbol_info(self, s):
        return SimpleNamespace(basis="WINV26")

    def symbol_info_tick(self, s):
        return SimpleNamespace(time=_epoch(self.tick))

    def copy_rates_range(self, s, tf, desde, ate):
        d, a = desde.replace(tzinfo=None), ate.replace(tzinfo=None)
        linhas = [(_epoch(t), 100000, 100050, 99950, 100010, 50, 5, 0)
                  for t in self.minutos if d <= t <= a]
        return np.array(linhas, dtype=_DT) if linhas else None

    def shutdown(self):
        pass


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    with db.connect_write() as con:
        db.init_schema(con)
        db.sync_instruments(con)
        ing.ingest_csv(con, write_export(tmp_path / "s.tsv", [
            (datetime(2026, 9, 30, 18, 24), 100000, 100050, 99950, 100010)]), "WIN$N")
    return tmp_path


def _servico(mt5, agora, pasta):
    return P.Servico(mt5=mt5, agora=lambda: agora, pasta=pasta,
                     terminal_aberto=lambda: True)


def _minutos(inicio, n):
    return [inicio + timedelta(minutes=i) for i in range(n)]


def test_volta_grava_os_fechados_e_publica_o_em_formacao(base):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")

    s.volta()

    with db.connect(read_only=True) as con:
        assert con.execute("SELECT max(ts) FROM bars_m1").fetchone()[0] == datetime(2026, 10, 1, 9, 4)
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["mt5"] == "conectado" and e["em_formacao"]["ts"] == "2026-10-01T09:05:00"
    assert e["ultimo_salvo"] == "2026-10-01T09:04:00" and e["gravados_hoje"] == 5


def test_banco_ocupado_nao_avanca_e_a_volta_seguinte_grava_sem_duplicar(base, monkeypatch):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    real = db.connect_write
    monkeypatch.setattr(db, "connect_write", lambda **k: (_ for _ in ()).throw(RuntimeError("ocupado")))
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["banco_ocupado_desde"] is not None and e["ultimo_salvo"] == "2026-09-30T18:24:00"

    monkeypatch.setattr(db, "connect_write", real)
    s.volta()
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT count(*) FROM bars_m1").fetchone()[0] == 6


def test_mt5_fechado_nao_inicializa_e_avisa(base):
    agora = datetime(2026, 10, 1, 10, 0)
    mt5 = MT5Falso([], tick=agora, aberto=False)
    s = P.Servico(mt5=mt5, agora=lambda: agora, pasta=base / "ao_vivo",
                  terminal_aberto=lambda: False)
    s.volta()
    assert mt5.inits == 0
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["mt5"] == "fechado"


def test_sem_conexao_com_a_corretora(base):
    agora = datetime(2026, 10, 1, 10, 0)
    s = _servico(MT5Falso([], tick=agora, conectado=False), agora, base / "ao_vivo")
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["mt5"] == "sem_conexao" and e["mt5_desde"] == "2026-10-01T10:00:00"


def test_simbolo_ausente_e_erro_de_configuracao(base):
    agora = datetime(2026, 10, 1, 10, 0)
    s = P.Servico(mt5=MT5Falso([], tick=agora), simbolo="XXX$N", agora=lambda: agora,
                  pasta=base / "ao_vivo", terminal_aberto=lambda: True)
    with pytest.raises(P.ErroDeConfiguracao):
        s.volta()


def test_depois_do_fechamento_confere_o_dia_e_exporta_o_parquet(base):
    dia = _minutos(datetime(2026, 10, 1, 9, 0), 3)
    agora = datetime(2026, 10, 1, 18, 40)
    s = _servico(MT5Falso(dia, tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo")
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "concluida"
    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 4


def test_segunda_instancia_sai_com_3(base):
    trava = P.travar(base / "ao_vivo" / "captura.lock")
    assert trava is not None
    assert P.travar(base / "ao_vivo" / "captura.lock") is None
    trava.close()
    assert P.travar(base / "ao_vivo" / "captura.lock") is not None


def test_trava_solta_quando_o_processo_morre_a_forca(tmp_path):
    lock = tmp_path / "captura.lock"
    filho = subprocess.Popen([sys.executable, "-c",
        f"import sys,time; sys.path.insert(0, {str(RAIZ)!r}); import captura as P; "
        f"t=P.travar(__import__('pathlib').Path({str(lock)!r})); print('ok', flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE, text=True)
    assert filho.stdout.readline().strip() == "ok"
    assert P.travar(lock) is None
    filho.kill(); filho.wait()
    assert P.travar(lock) is not None
```

  (Se `copy_rates_range` do falso receber datetimes com `tzinfo`, a comparação já remove o fuso. Ajuste o `MT5Falso` só se o `Servico` precisar de outro método do pacote; nunca afrouxe as asserções.)

- [ ] **Step 2: rodar** → FAIL.
- [ ] **Step 3: implementar** `captura.py` conforme o desenho acima.
- [ ] **Step 4: rodar** `tests/test_captura_processo.py` → PASS; suíte inteira.
- [ ] **Step 5: `captura.bat`**:

```bat
@echo off
REM Serviço de captura: grava cada candle M1 fechado do WIN$N.
REM Aberto pelo iniciar.bat. Se cair, reabre sozinho com espera crescente.
cd /d "%~dp0"
title Dataframe - Captura
set ESPERA=10
:laco
.venv\Scripts\python.exe captura.py
set CODIGO=%ERRORLEVEL%
if "%CODIGO%"=="0" exit /b 0
if "%CODIGO%"=="3" (
    echo.
    echo  A captura parou e nao vai reabrir sozinha: outra janela da captura
    echo  ja esta aberta, ou falta configuracao. Detalhes em data\ao_vivo\captura.log
    echo.
    pause
    exit /b 3
)
echo  A captura caiu (codigo %CODIGO%). Reabrindo em %ESPERA% s...
timeout /t %ESPERA% /nobreak >nul
if %ESPERA%==10 (set ESPERA=30) else if %ESPERA%==30 (set ESPERA=60) else if %ESPERA%==60 (set ESPERA=120) else (set ESPERA=300)
goto laco
```

  `iniciar.bat`: logo antes do `echo.` que anuncia o endereço, acrescentar
  `start "Dataframe - Captura" /min cmd /c captura.bat` com um `REM` explicando
  (janela própria: fechar a tela não para a captura; a captura só para fechando a janela dela).

- [ ] **Step 6: conferência real (mercado fechado ou aberto, tanto faz)** — rodar `.venv/Scripts/python.exe captura.py` por ~1 min com o MT5 aberto; conferir em `data/ao_vivo/estado.json` `mt5 = conectado`, `ultimo_salvo` = último minuto fechado, sem erro; Ctrl+C sai com 0. Rodar duas vezes ao mesmo tempo → a segunda sai com 3.
- [ ] **Step 7: mutação** — tire o `if terminal_aberto()` → `test_mt5_fechado...` falha; avance `ultimo` mesmo com banco ocupado → o teste do banco ocupado falha.
- [ ] **Step 8: commit** — `captura.py captura.bat iniciar.bat tests/test_captura_processo.py`, `feat(captura): processo do servico de captura e janela propria`.

---

### Task 8: Estado na tela — selo no topo e "Sincronizar" travado com a captura ativa

**Files:**
- Modify: `ui/data.py`, `ui/app.py` (topbar + Interval), `ui/callbacks_mt5.py`, `ui/callbacks.py` (registro), `ui/assets/style.css`
- Create: `ui/components/pregao_panel.py` (só a parte do selo/situação nesta tarefa), `ui/callbacks_pregao.py`
- Test: `tests/test_pregao_tela.py` (novo)

**Interfaces:**
- Consumes: chaves do `estado.json` (Task 7); `captura.ler_estado`, `captura.em_pregao`.
- Produces:
  - `D.ESTADO_CAPTURA: Path` (= `db.DATA / "ao_vivo" / "estado.json"`); `D.estado_captura() -> dict | None` (última leitura válida; limpa `_bars_cache` quando `conferencia.em` muda).
  - `pregao_panel.situacao(estado: dict | None, agora: datetime) -> dict` com `{"tom": "verde"|"ambar"|"rosa"|"cinza", "texto": str, "acao": str | None, "ativa": bool, "pregao": bool}`.
  - `pregao_panel.captura_ativa(estado, agora) -> bool` (estado com `atualizado_em` < 60 s).

**Regras de `situacao`** (primeira que casar):
1. `estado is None` → âmbar, "Captura nunca rodou neste computador", ação "abra pelo iniciar.bat".
2. `pregao` = `em_pregao(agora, fechamento)` (fechamento do estado, padrão 18:24). Estado velho (> 60 s): no pregão → rosa "Captura parada há N min" + ação "confira a janela “Dataframe - Captura”"; fora → cinza "Captura parada (fora do pregão)", `ativa False`.
3. `erro` → rosa, o texto do erro.
4. `mt5 == "fechado"` → rosa "MT5 fechado", ação "abra e faça login; a captura recupera o período sozinha".
5. `mt5 == "sem_conexao"` → âmbar "Sem conexão com a corretora desde HH:MM".
6. `banco_ocupado_desde` há mais de 2 min → âmbar "Banco ocupado há N s" (ação: "uma mineração está gravando; nada se perde").
7. `relogio_atrasado_s` → âmbar "Relógio do PC atrasado N s".
8. Senão → verde "Captura ativa" (fora do pregão: verde "Captura ativa — mercado fechado").

- [ ] **Step 1: testes (falhando)** — `tests/test_pregao_tela.py`: um teste por regra acima (montando dicionários de estado à mão, `agora = datetime(2026, 10, 1, 10, 0)` numa quinta), mais:

```python
def test_estado_captura_guarda_a_ultima_leitura_valida(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    monkeypatch.setattr(D, "_estado_ultimo", None)
    assert D.estado_captura() is None
    p.write_text('{"mt5": "conectado"}', encoding="utf-8")
    assert D.estado_captura() == {"mt5": "conectado"}
    p.write_text("{meio", encoding="utf-8")
    assert D.estado_captura() == {"mt5": "conectado"}


def test_conferencia_nova_limpa_o_cache_de_barras(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    monkeypatch.setattr(D, "_conferencia_vista", None)
    p.write_text('{"conferencia": {"em": "2026-10-01T18:30:00"}}', encoding="utf-8")
    D.estado_captura()
    D._bars_cache["WIN$N"] = {"x": 1}
    p.write_text('{"conferencia": {"em": "2026-10-02T18:30:00"}}', encoding="utf-8")
    D.estado_captura()
    assert "WIN$N" not in D._bars_cache


def test_sincronizar_recusa_com_a_captura_ativa(monkeypatch):
    from ui import callbacks_mt5 as CM
    monkeypatch.setattr(CM.D, "estado_captura",
                        lambda: {"atualizado_em": datetime.now().isoformat()})
    assert "captura" in CM.motivo_bloqueio()
    monkeypatch.setattr(CM.D, "estado_captura", lambda: None)
    assert CM.motivo_bloqueio() is None
```

- [ ] **Step 2: rodar** → FAIL.
- [ ] **Step 3: implementar.**
  - `ui/data.py`: `from core import captura as CAP`; `ESTADO_CAPTURA = db.DATA / "ao_vivo" / "estado.json"`; `_estado_ultimo = None`, `_conferencia_vista = None`; `estado_captura()`: arquivo ausente → `None` (e zera `_estado_ultimo`); ilegível → `_estado_ultimo`; válido → guarda; se `(e.get("conferencia") or {}).get("em")` difere de `_conferencia_vista` e esta não é `None` → `_bars_cache.clear()`; atualiza `_conferencia_vista`. Comentário: a mineração/backtest passam a ver o dia conferido.
  - `ui/components/pregao_panel.py` (cabeçalho: spec §6; só desenha, sem ler arquivo): `situacao`, `captura_ativa`, `selo(sit) -> (children, className, style)` — esconde (`display: none`) quando `sit["tom"] == "cinza"`; senão `html.Span([● , texto])` com classe `captura-selo captura-selo-<tom>` e `title` = ação.
  - `ui/app.py` topbar: antes do `mt5-sync-wrap`, `html.Span(id="captura-selo", className="captura-selo", style={"display": "none"})`; no layout, `dcc.Interval(id="captura-intervalo", interval=30_000)`.
  - `ui/callbacks_mt5.py`: `motivo_bloqueio()` → `"a captura ao vivo já mantém a base em dia"` se `PP.captura_ativa(D.estado_captura(), datetime.now())`, senão `None`; no início de `sincronizar_mt5`, se houver motivo → devolve `(motivo, "mt5-sync-status", no_update×3)`.
  - `ui/callbacks_pregao.py` com `register(app)`; nesta tarefa um callback: `Input("captura-intervalo", "n_intervals")` → `Output("captura-selo", "children")`, `("captura-selo", "className")`, `("captura-selo", "style")`, `("captura-selo", "title")`, `("btn-mt5-sync", "disabled")`, `("btn-mt5-sync", "title")`. Registrar em `ui/callbacks.py:register` como os outros (`from ui import callbacks_pregao; callbacks_pregao.register(app)`).
  - CSS no fim de `ui/assets/style.css`, bloco `/* ---- Captura: selo no topo ---- */`, com as variáveis existentes (`--pos`, `--warn`, `--neg`, `--muted`).
- [ ] **Step 4: rodar** `tests/test_pregao_tela.py tests/test_callbacks_sem_ciclo.py` → PASS; suíte inteira.
- [ ] **Step 5: commit** — `ui/data.py ui/app.py ui/callbacks.py ui/callbacks_mt5.py ui/callbacks_pregao.py ui/components/pregao_panel.py ui/assets/style.css tests/test_pregao_tela.py`, `feat(ao-vivo): selo da captura no topo e Sincronizar travado com a captura ativa`.

---

### Task 9: Sub-tela Pregão (layout A)

Siga também `.claude/agents/designer-ui.md` (sistema visual, rótulo + valor, pílulas, CSS por bloco).

**Files:**
- Modify: `ui/components/ao_vivo_panel.py`, `ui/components/pregao_panel.py`, `ui/callbacks_pregao.py`, `ui/data.py`, `ui/assets/style.css`
- Test: `tests/test_pregao_tela.py`, `tests/test_ao_vivo_tela.py` (se conferir o chip "Estratégias")

**Interfaces:**
- Consumes: `D.estado_captura`, `situacao` (Task 8); `D.candles(symbol, inicio, fim, tf)` existente; `charts.price_series`.
- Produces: ids `av-subtela`, `av-bloco-estrategias`, `av-bloco-pregao`, `av-pg-intervalo`, `av-pg-ultimo`, `av-pg-faixa`, `av-pg-placar`, `av-pg-tf`, `av-pg-agora`, `av-pg-cheia`, `av-pg-grafico`, `av-pg-grafico-caixa`; funções puras `pregao_panel.faixa(estado, agora)`, `pregao_panel.placar(estado)`, `pregao_panel.idade_tom(segundos: float, pregao: bool) -> str`, `pregao_panel.tick_formacao(estado, tf: str, balde: list[dict]) -> dict | None`, `D.dia_do_pregao(estado) -> date`.

**Desenho:**
- `ao_vivo_panel.painel()`: troca o `html.Span("Estratégias", className="chip av-subtela")` por `dcc.RadioItems(id="av-subtela", value="estrategias", persistence=True, persistence_type="local", className="av-subtelas", options=[Estratégias, Pregão])`; tudo o que hoje vem depois do cabeçalho vai para `html.Div(id="av-bloco-estrategias")`; acrescenta `pregao_panel.bloco()` (`id="av-bloco-pregao"`, `display: none`). **Preserve a remoção do parágrafo "robô de papel" feita pelo usuário.** Atualize o docstring do módulo (a sub-tela Pregão existe agora).
- `pregao_panel.bloco()`: `dcc.Interval(id="av-pg-intervalo", interval=2000, disabled=True)`, `dcc.Store(id="av-pg-ultimo")`; linha de 4 cartões `av-pg-faixa` (Captura · MT5 · Último candle · Lacunas hoje) + faixa de alerta quando `situacao` não é verde; painel do gráfico com barra: `dcc.RadioItems(id="av-pg-tf", value="M1", options 1 min/5 min/15 min)`, botões "Voltar para agora" (`av-pg-agora`) e "Tela cheia" (`av-pg-cheia`), e `html.Div(Tvlwc(id="av-pg-grafico", series=[], chartOptions=T.CHART_OPTIONS, height="100%"), id="av-pg-grafico-caixa", className="pg-grafico")` (zoom e arrastar já vêm do componente; logo da TradingView fica); 4 cartões `av-pg-placar` (Gravados hoje · Recuperados · Correções da corretora · Conferência do dia: "pendente"/"concluída às HH:MM"/"falhou — tenta de novo em 5 min").
- `idade_tom`: fora do pregão → `"cinza"`; ≤ 90 s verde; ≤ 180 s âmbar; depois rosa.
- `tick_formacao(estado, tf, balde)`: sem `em_formacao` → `None`. M1 → `{"id": "preco", "bar": {time: to_epoch(ts), open, high, low, close}}`. M5/M15 → início do balde = minuto de `em_formacao` arredondado para baixo no múltiplo; `balde` = candles M1 fechados (`{"ts", "open", "high", "low", "close"}`) desde o início do balde; abre = open do primeiro (ou do em formação, se o balde vier vazio), máxima/mínima de todos, fecha = close do em formação; `time` = início do balde.
- `D.dia_do_pregao(estado)`: data de `ultimo_salvo` (ou hoje, sem estado). Fora do pregão o gráfico mostra esse último dia e a faixa diz "Mercado fechado".
- Callbacks (`ui/callbacks_pregao.py`):
  1. `subtela`: `Input("av-subtela", "value")`, `Input("modo", "value")` → `Output("av-bloco-estrategias", "style")`, `Output("av-bloco-pregao", "style")`, `Output("av-pg-intervalo", "disabled")` (ligado só com modo `aovivo` e sub-tela `pregao`).
  2. `pulso`: `Input("av-pg-intervalo", "n_intervals")`, `State("av-pg-ultimo", "data")`, `State("av-pg-tf", "value")` → `Output("av-pg-faixa", "children")`, `Output("av-pg-placar", "children")`, `Output("av-pg-ultimo", "data")` (`no_update` se `ultimo_salvo` não mudou), `Output("av-pg-grafico", "tick")`. **Nunca escreve `series`** — é isso que preserva o zoom. Para M5/M15 lê do banco só os M1 do balde atual (conexão de leitura curta).
  3. `serie`: `Input("av-pg-ultimo", "data")`, `Input("av-pg-tf", "value")`, `Input("av-subtela", "value")` → `Output("av-pg-grafico", "series")` = `charts.price_series(D.candles("WIN$N", dia 00:00, dia 23:59, tf))`.
  4. `agora`: `Input("av-pg-agora", "n_clicks")` → `Output("av-pg-grafico", "timeScaleAction")` = `{"action": "scrollToRealTime", "nonce": n}`.
  5. Tela cheia: `app.clientside_callback` com `Input("av-pg-cheia", "n_clicks")`, `Output("av-pg-grafico-caixa", "title")`, JS: se `n`, `document.getElementById('av-pg-grafico-caixa').requestFullscreen()`; devolve `window.dash_clientside.no_update`.
- CSS: bloco `/* ---- Ao vivo › Pregão ---- */` no fim de `style.css` — cartões de estado em grade de 4, faixa de alerta, `.pg-grafico { height: 460px }`, `.pg-grafico:fullscreen { background: var(--bg); padding: 12px; height: 100vh }`, seletor `.av-subtelas` no estilo dos chips. Cores só das variáveis existentes.

- [ ] **Step 1: testes (falhando)** em `tests/test_pregao_tela.py`: `idade_tom` (4 faixas), `tick_formacao` M1 e M5 (balde com 2 fechados + em formação → máxima/mínima/abertura certas, `time` = início do balde), sem `em_formacao` → `None`, `faixa` mostra "Mercado fechado" fora do pregão e "Lacunas hoje" com a contagem; e um teste estrutural: nenhum callback registrado tem `av-pg-grafico.series` e `av-pg-grafico.tick` como saída juntos (montar o app com `ui.app.build()` e varrer `app.callback_map`; o layout lê barras na montagem — copie a fixture que semeia o banco isolado de `tests/test_callbacks_sem_ciclo.py`).
- [ ] **Step 2: rodar** → FAIL. **Step 3: implementar.** **Step 4:** testes da tela + `tests/test_callbacks_sem_ciclo.py` + suíte inteira → PASS.
- [ ] **Step 5: conferir na tela** (`preview_start` `dataframe`; captura rodando de verdade): Ao vivo › Pregão mostra os 4 cartões, gráfico do último dia, placar; trocar 1/5/15 min; "Voltar para agora"; zoom não salta a cada 2 s; selo no topo; "Sincronizar" desativado com título explicando. Screenshot para o usuário. Sem a captura rodando: faixa "Captura nunca rodou…" ou "parada".
- [ ] **Step 6: commit** — `ui/components/ao_vivo_panel.py ui/components/pregao_panel.py ui/callbacks_pregao.py ui/data.py ui/assets/style.css tests/test_pregao_tela.py` (+ `tests/test_ao_vivo_tela.py` se mudou), `feat(ao-vivo): sub-tela Pregao com grafico ao vivo`. Avisar em destaque: **feche e abra o `iniciar.bat`**.

---

### Task 10: Documentação

**Files:** `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1:** `CLAUDE.md` — tabela de modos (linha Ao vivo: `captura.py` + `core/captura.py`, `callbacks_pregao.py` + `components/pregao_panel.py`); "Rodar": `captura.bat` abre pelo `iniciar.bat`; "Onde estamos": parte 2 ✅, próximo passo = parte 3 (incubação em papel, spec própria, começar pelo brainstorming); armadilha da hora: trocar "correção: spec §0" por "corrigida em <data da Task 3>; backup em `<caminho>`"; acrescentar: "Captura ativa → o botão Sincronizar fica desativado; a mineração só vê o dia de hoje depois da conferência do dia (Parquet)".
- [ ] **Step 2:** `CHANGELOG.md` — entrada "Ao vivo, parte 2: serviço de captura e sub-tela Pregão", com a correção da base (o que foi apagado e por quê) em linguagem de usuário.
- [ ] **Step 3: commit** — `CLAUDE.md CHANGELOG.md`, `docs: servico de captura e correcao da base`.

---

## Depois de todas as tarefas

Revisão final da branch inteira (agente no modelo mais forte). Conferência real
com o mercado **aberto** (spec §8): candles entrando minuto a minuto, candle em
formação mexendo sem perder o zoom, lacunas = 0, fechar o MT5 e ver o aviso,
reabrir e ver recuperar, conferência do dia depois do fechamento.
