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
| `core/mt5_source.py` | `buscar_barras` sem offset; `sincronizar` só grava o último minuto com 10 min de folga; some `offset_servidor` |
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
- Produces:
  - `captura.fechados(barras: pl.DataFrame, agora_servidor: datetime) -> pl.DataFrame`
  - `captura.RelogioServidor` com `observar(tick: datetime | None, mono: float) -> None`, `agora(mono: float) -> datetime | None` e `desvio_s(agora_pc: datetime, mono: float) -> float | None`
  - `mt5_source.buscar_barras(symbol, desde, ate)`, agora sem offset
  - `mt5_source.MARGEM_SINCRONIZAR = timedelta(minutes=10)`

**Por que um relógio do servidor:** "fechado" não pode depender do relógio do PC. Com o PC adiantado 3 min, qualquer regra baseada nele grava o candle em formação. A hora do servidor estimada é o último tick **mais o tempo decorrido (monotonic) desde que esse valor de tick foi visto pela primeira vez**. Ela é sempre ≤ a hora real, então erra para o lado seguro: atrasa a gravação em alguns segundos, nunca grava aberto. Sem tick nenhum (`None`), não há referência e nada do último minuto é gravado.

- [ ] **Step 1: testes (falhando)** — `tests/test_captura.py`:

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
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 30))["ts"].to_list() == b["ts"].to_list()[:2]


def test_fechados_ultimo_vira_fechado_65s_depois_do_inicio():
    b = barras("10:00", "10:01")
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 4)).height == 1
    assert C.fechados(b, datetime(2026, 10, 1, 10, 2, 5)).height == 2


def test_fechados_sem_hora_do_servidor_nunca_grava_o_ultimo():
    assert C.fechados(barras("10:00", "10:01"), None).height == 1


def test_apos_queda_de_3h_devolve_tudo_menos_o_em_formacao():
    horas = [f"{h:02d}:{m:02d}" for h in range(10, 13) for m in range(60)]
    b = barras(*horas, "13:00")
    assert C.fechados(b, datetime(2026, 10, 1, 13, 0, 20)).height == 180


def test_fechados_sem_barras_devolve_vazio():
    assert C.fechados(barras("10:00").head(0), datetime(2026, 10, 1, 10, 5)).height == 0


# ------------------------------------------------------- relógio do servidor
T = datetime(2026, 10, 1, 10, 1, 29)


def test_relogio_soma_o_tempo_decorrido_desde_que_o_tick_mudou():
    r = C.RelogioServidor()
    r.observar(T, mono=100.0)
    r.observar(T, mono=130.0)            # mesmo tick: não reinicia a contagem
    assert r.agora(mono=140.0) == T + timedelta(seconds=40)
    r.observar(T + timedelta(seconds=45), mono=145.0)
    assert r.agora(mono=146.0) == T + timedelta(seconds=46)


def test_pc_adiantado_3_min_nao_deixa_passar_o_em_formacao():
    # o PC marca 10:04:29; a hora real (e o tick) é 10:01:29
    r = C.RelogioServidor()
    r.observar(T, mono=0.0)
    b = barras("10:00", "10:01")
    assert C.fechados(b, r.agora(mono=1.0))["ts"].to_list() == b["ts"].to_list()[:1]
    assert r.desvio_s(datetime(2026, 10, 1, 10, 4, 29), mono=1.0) == pytest.approx(179, abs=1)


def test_mercado_parado_fecha_o_ultimo_pelo_tempo_decorrido():
    r = C.RelogioServidor()
    r.observar(datetime(2026, 10, 1, 10, 1, 10), mono=0.0)   # último negócio
    b = barras("10:00", "10:01")
    assert C.fechados(b, r.agora(mono=50.0)).height == 1     # 10:02:00
    assert C.fechados(b, r.agora(mono=56.0)).height == 2     # 10:02:06


def test_relogio_sem_tick_nao_sabe_a_hora():
    r = C.RelogioServidor()
    r.observar(None, mono=0.0)
    assert r.agora(mono=5.0) is None and r.desvio_s(T, mono=5.0) is None
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
# entre o último negócio e a barra seguinte aparecer no MT5.
FECHA_APOS = timedelta(seconds=65)


def fechados(barras: pl.DataFrame, agora_servidor: datetime | None) -> pl.DataFrame:
    """Só os candles fechados. Todos menos o último já fecharam (existe
    barra depois deles); o último só fecha 65 s depois do início do minuto,
    pela hora do SERVIDOR — o relógio do PC pode estar adiantado."""
    if barras.height == 0:
        return barras
    barras = barras.sort("ts")
    if agora_servidor is not None and agora_servidor >= barras["ts"][-1] + FECHA_APOS:
        return barras
    return barras.head(barras.height - 1)


class RelogioServidor:
    """Hora da corretora estimada sem confiar no relógio do PC: o último
    tick mais o tempo decorrido (monotonic) desde que esse valor apareceu.
    Fica sempre um pouco atrás da hora real — erra para o lado seguro."""

    def __init__(self):
        self._tick = None
        self._visto = None

    def observar(self, tick: datetime | None, mono: float) -> None:
        if tick is None:
            self._tick = self._visto = None
        elif tick != self._tick:
            self._tick, self._visto = tick, mono

    def agora(self, mono: float) -> datetime | None:
        if self._tick is None:
            return None
        return self._tick + timedelta(seconds=mono - self._visto)

    def desvio_s(self, agora_pc: datetime, mono: float) -> float | None:
        """PC menos servidor, em segundos. Só vale com tick recente (< 10 s):
        com o mercado parado a estimativa fica para trás e o desvio mentiria."""
        if self._tick is None or mono - self._visto > 10:
            return None
        return (agora_pc - self.agora(mono)).total_seconds()
```

- [ ] **Step 4: rodar** → PASS.

- [ ] **Step 5: corrigir `core/mt5_source.py`.**
  - Apagar `offset_servidor` inteira.
  - `buscar_barras`: novo docstring (o `time` do MT5 já é hora de Brasília, e o pedido também vai em hora de Brasília). Pedir com `desde.replace(tzinfo=timezone.utc)` e `ate.replace(tzinfo=timezone.utc)`, porque o pacote converte datetime sem fuso pelo fuso do PC e deslocaria a janela pedida em 3 h. Devolver `pl.from_epoch("time", time_unit="s").alias("ts")` **sem** `+ offset`.
  - `MARGEM_SINCRONIZAR = timedelta(minutes=10)`, com este comentário: o botão é manual e não tem o relógio do servidor. Ele só grava o último minuto devolvido se o PC disser que ele começou há mais de 10 min, o que cobre um relógio errado em até 9 min. O minuto que ficar de fora entra na próxima sincronização ou pela captura.
  - Em `sincronizar`, logo depois do bloco `with _TERMINAL:`, `barras = captura.fechados(barras, datetime.now() - MARGEM_SINCRONIZAR + captura.FECHA_APOS)`, com o import `from . import captura`. O resultado é: o último minuto entra se `now >= ts + 10 min`. Se `barras.height == 0`, `raise MT5Error("nenhum candle fechado novo no MT5 — tente de novo em alguns minutos")`.
  - Reescrever o comentário de `ate = datetime.now() + timedelta(days=1)`: o MT5 nunca devolve barra do futuro, e a folga só garante que o pedido alcance o último minuto.

- [ ] **Step 6: atualizar `tests/test_mt5_source.py`.**
  - Apagar estes testes e auxiliares: os 5 testes de `offset_servidor`, `_FakeMT5Offset`, `_instalar_fake_mt5`, `_FakeMT5RatesComOffset` e `test_buscar_barras_pede_em_utc_e_devolve_em_hora_de_corretor`.
  - Novos testes:

```python
def test_buscar_barras_nao_desloca_a_hora(monkeypatch):
    """Achado real (01/10/2026): o MT5 devolve `time` já em hora de
    Brasília. Somar o fuso gravou seis meses de pregão de 06:00 a 15:24."""
    import numpy as np
    nove = int(datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc).timestamp())
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


def test_sincronizar_descarta_o_ultimo_minuto_recente(con, tmp_path, monkeypatch):
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
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)

    r = src.sincronizar(con, "WIN$N", price_decimals=0)

    assert r.ingest.rows_inserted == 1
    assert con.execute("SELECT max(ts) FROM bars_m1").fetchone()[0] == agora - timedelta(minutes=1)
```

  - Os testes antigos de `sincronizar` usam barra de 2026-09-02, que já tem mais de 10 min, e continuam passando. Confira.

- [ ] **Step 7: rodar** `tests/test_captura.py`, `tests/test_mt5_source.py` e `tests/test_mt5_ler_conta.py` → PASS. Depois, a suíte inteira.

- [ ] **Step 8: mutação.** Faça cada quebra abaixo, confirme que o teste indicado falha e desfaça:
  - (a) voltar a somar −3 h em `buscar_barras` → `test_buscar_barras_nao_desloca_a_hora` falha;
  - (b) `FECHA_APOS = 0` → os testes de `fechados` falham;
  - (c) `RelogioServidor.observar` reiniciando `_visto` a cada chamada → o teste do tempo decorrido falha;
  - (d) tirar a `MARGEM_SINCRONIZAR` → o teste do último minuto recente falha.

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
    # o formato real de 09–13/03 hoje: manhã do lote errado, tarde do CSV
    misto = serie(datetime(2026, 3, 10, 6, 0), 2) + serie(datetime(2026, 3, 10, 18, 23), 2)
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv", bom + torto + misto), "WIN$N")
    cal.rebuild_trading_days(con, "WIN$N")

    suspeitas = R.sessoes_suspeitas(con, "WIN$N", date(2026, 3, 1))

    assert [s["dia"] for s in suspeitas] == [date(2026, 3, 10), date(2026, 3, 16)]
    assert suspeitas[1]["abre"] == "06:00" and suspeitas[1]["fecha"] == "15:24"


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

    .venv/Scripts/python.exe corrigir_base.py             # simulação: só mostra
    .venv/Scripts/python.exe corrigir_base.py --executar  # faz
    .venv/Scripts/python.exe corrigir_base.py --retomar   # só refaz os passos 5-7

Antes: feche o app (iniciar.bat) e a captura; abra o MT5 logado.
"""
```

  Sem `--executar`/`--retomar`: faz o passo 0 (só leitura no MT5), imprime o que apagaria (contagens de `TABELAS_DERIVADAS`, barras dos lotes, arquivos a renomear) e sai com 0. Passos com `--executar`:
  0. **Conferir o MT5 antes de apagar qualquer coisa:** `src.conectar()`; `b = src.buscar_barras("WIN$N", datetime(2026, 3, 9), datetime(2026, 3, 17))`; `src.desconectar()`. Exigir barra em 09/03 e em 16/03, ambas com hora entre 09:00 e 09:15. Senão, abortar com a mensagem: "o MT5 não tem o histórico desde 09/03 (confira 'Máx. barras no gráfico' em Ferramentas › Opções › Gráficos) — nada foi apagado".
  1. Lotes errados = `ingest_id` do `ingest_log` cujo `source_file` contém `mt5_sync_2026092` (hoje: 3 e 4). Imprimir; se não forem exatamente `{3, 4}`, recusar, a menos que `--lotes 3,4` seja passado.
  2. **Backup consistente:**
     - `con = db.connect_write(tentativas=1)`; se falhar, o app ou a captura estão abertos: recusar.
     - `con.execute("CHECKPOINT")`; `con.close()`.
     - Copiar `database.duckdb` (e o `.wal`, se existir), `data/parquet` e `data/raw` para `ROOT.parent / "backups" / f"{hoje:%Y-%m-%d}-antes-correcao-hora"`.
     - Se essa pasta já existir, recusar (use `--retomar`).
  3. `with db.connect_write() as con:` + `with db.transacao(con):`
     - `apagar_derivados(con)`;
     - `apagar_lotes(con, "WIN$N", lotes)`;
     - `diario.registrar(con, "base_corrigida", "sistema", motivo="hora do MT5 deslocada em 3 h (16/03→23/09/2026); cadeia apagada; ingest_log 3 e 4 ficam como histórico, arquivos renomeados .hora-errada")`.

     **Não** reinicie sequências: o diário aponta para ids antigos.
  4. Renomear cada `source_file` desses lotes que exista para `<nome>.hora-errada`.
  5. **Fora de qualquer transação aberta** (`ingest_csv` faz o próprio BEGIN): `ing.ingest_csv(con, CSV, "WIN$N", price_decimals=0)`, com `CSV = db.RAW_DIR / "m1-hist-16-03-2026.csv"` (o argumento `--csv` troca o arquivo).
  6. `src.sincronizar(con, "WIN$N", price_decimals=0)`: baixa de `ultimo − 5 dias` até agora (≈80 mil candles), reconstrói `trading_days`/`rollovers` e o Parquet.
  7. Relatório:
     - total de candles e último candle;
     - `sessoes_suspeitas(con, "WIN$N", date(2026, 3, 9))`, uma por linha;
     - uma tabela dia → primeiro/último/candles de 09/03 até hoje;
     - a contagem de candles por dia abaixo de 500 em destaque, porque pode ser buraco.

  **Se qualquer passo de 5 a 7 falhar:**
  - rodar mesmo assim `cal.rebuild_trading_days`, `roll.rebuild_rollovers` e `db.export_parquet`, para não deixar Parquet com a hora errada nem calendário velho;
  - imprimir o erro, o caminho do backup e a instrução "corrija e rode `corrigir_base.py --retomar`".

  `--retomar` pula os passos 0–4 e roda 5–7. O passo 5 é idempotente: barras idênticas não mudam.

  A pasta `data/parquet/SEM_YAML`, resto de um teste antigo, é apagada no passo 3 com um aviso.

- [ ] **Step 6: simulação** — rodar `.venv/Scripts/python.exe corrigir_base.py` (sem `--executar`) e conferir que só lê. Espera-se ver:
  - o passo 0 OK, se o MT5 estiver aberto; se não estiver, a mensagem de aborto;
  - os lotes {3, 4} e as 77.202 barras deles;
  - as contagens atuais das 9 tabelas.

  **Não rodar com `--executar` nesta tarefa.**

- [ ] **Step 7: suíte inteira + mutação** (troque `ABRE` para aceitar 06:00 → o teste de sessões suspeitas falha; tire `portfolios` de `TABELAS_DERIVADAS` → o teste de apagar falha). Commit — `core/reparo_base.py core/diario.py corrigir_base.py tests/test_reparo_base.py`, mensagem `feat(base): roteiro da correcao da hora deslocada (spec captura §0)`.

---

### Task 3: Executar a correção da base (controlador, com o usuário)

**Destrutivo — o controlador para e pede o "pode rodar" do usuário antes**, e confirma: app fechado, MT5 aberto e logado.

- [ ] **Step 1:** `.venv/Scripts/python.exe corrigir_base.py --executar`; guardar a saída no ledger.
- [ ] **Step 2: conferir dia a dia.** Na lista de sessões suspeitas:
  - só podem aparecer dias de horário especial legítimo. Já se sabe que **12/03 aparece**: o CSV original tem candle às 18:31, o que é legítimo;
  - nenhum dia pode abrir às 06:xx;
  - nenhum dia útil de 16/03 até hoje pode faltar.

  O último candle tem de ser um minuto que já fechou há mais de 10 min.
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

  - Docstring de `ingest_df`: "faz o próprio BEGIN/COMMIT — nunca chame dentro de uma transação aberta (o DuckDB recusa BEGIN aninhado)".

- [ ] **Step 3b: reescrever `test_falha_no_meio_nao_deixa_rastro`** em `tests/test_ingest.py`. Hoje ele chama `ing._merge(con, p, SYMBOL, quebrado)` com a assinatura antiga e passaria por TypeError, sem testar nada. A versão nova quebra **depois** do INSERT no `ingest_log`:

```python
def test_falha_no_meio_nao_deixa_rastro(con, monkeypatch):
    ts = datetime(2026, 3, 9, 9, 0)
    ing.ingest_df(con, _df([(ts, 100, 110, 90, 100)]), SYMBOL, "a", "sa")
    lotes, barras = (con.execute("SELECT count(*) FROM ingest_log").fetchone()[0],
                     _barras(con))

    def boom(*a, **k):
        raise RuntimeError("falha proposital depois do INSERT no ingest_log")

    monkeypatch.setattr(ing.json, "dumps", boom)  # roda só quando há divergência
    with pytest.raises(RuntimeError, match="proposital"):
        ing.ingest_df(con, _df([(ts, 100, 120, 90, 105)]), SYMBOL, "b", "sb",
                      source_max_ts=datetime(2026, 3, 10))

    assert con.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == lotes
    assert _barras(con) == barras
```

  (`SYMBOL` é o que o arquivo já usa; se o nome for outro, use o do arquivo.)

- [ ] **Step 4: rodar** `tests/test_ingest.py tests/test_mt5_source.py` → PASS (os outros testes antigos de `ingest_csv` não mudam). Suíte inteira.
- [ ] **Step 5: mutação** — ignore `source_max_ts` em `_merge` → o teste do `source_max_ts` falha; tire a checagem de OHLC de `validar` → o teste de incoerente falha; tire o `ROLLBACK` de `ingest_df` → `test_falha_no_meio_nao_deixa_rastro` falha.
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
    desempate por sha256. Uma exportação manual vence a conferência só se
    tiver candle mais novo que a hora em que a conferência rodou (feita na
    mesma noite, perde: o "mais novo" é medido pela barra mais nova)."""
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
- Modify: `core/db_manager.py` (`export_parquet`, `read_bars_parquet`)
- Test: `tests/test_db_parquet_atomico.py` (novo)

**Interfaces:**
- Produces: `db.export_parquet(con, symbol) -> Path` com a mesma assinatura, agora atômico; `read_bars_parquet` tolera a troca em andamento.

**Dois defeitos do código atual que isto resolve:**
- `COPY … OVERWRITE_OR_IGNORE` por cima da pasta em uso deixa um ano pela metade para quem estiver lendo.
- Um ano que deixou de ter barras fica órfão no espelho.

- [ ] **Step 1: testes (falhando)**:

```python
"""O espelho Parquet nunca fica pela metade nem com ano órfão: a mineração
lê dele enquanto a captura reexporta depois da conferência do dia."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from tests.test_ingest import serie, write_export  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    con = db.connect(tmp_path / "t.duckdb"); db.init_schema(con)
    ing.ingest_csv(con, write_export(tmp_path / "a.tsv",
                   serie(datetime(2025, 12, 31, 9, 0), 2) + serie(datetime(2026, 1, 2, 9, 0), 3)), "WIN$N")
    yield con, tmp_path
    con.close()


def test_export_nao_deixa_ano_orfao_nem_pasta_de_sobra(base):
    con, tmp = base
    db.export_parquet(con, "WIN$N")
    con.execute("DELETE FROM bars_m1 WHERE year(ts) = 2025")

    out = db.export_parquet(con, "WIN$N")

    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 3
    assert sorted(p.name for p in (tmp / "parquet").iterdir()) == [out.name]


def test_falha_na_troca_devolve_a_copia_antiga(base, monkeypatch):
    con, tmp = base
    db.export_parquet(con, "WIN$N")
    con.execute("DELETE FROM bars_m1 WHERE year(ts) = 2025")
    real = Path.rename

    def rename_que_falha(self, alvo):
        if self.name.endswith(".novo"):
            raise PermissionError("pasta em uso")
        return real(self, alvo)

    monkeypatch.setattr(Path, "rename", rename_que_falha)
    with pytest.raises(PermissionError):
        db.export_parquet(con, "WIN$N")
    monkeypatch.setattr(Path, "rename", real)

    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 5   # a cópia antiga voltou
```

- [ ] **Step 2: rodar** → FAIL. O primeiro teste falha porque `year=2025` fica órfão.

- [ ] **Step 3: implementar**:

```python
def export_parquet(con, symbol: str) -> Path:
    """Reescreve o espelho Parquet do simbolo, particionado por ano.

    Grava numa pasta nova e troca de uma vez: a mineração e o walk-forward
    leem este espelho enquanto a captura reexporta depois da conferência do
    dia. Um COPY por cima da pasta em uso deixava um ano pela metade, e um
    ano que deixou de ter barras ficava órfão."""
    import shutil
    import time as _t

    out = PARQUET_DIR / safe_symbol(symbol)
    novo = out.with_name(out.name + ".novo")
    velho = out.with_name(out.name + ".velho")
    shutil.rmtree(novo, ignore_errors=True)
    if velho.exists() and out.exists():
        shutil.rmtree(velho)          # sobra de troca anterior já concluída
    elif velho.exists():
        velho.rename(out)             # troca anterior interrompida: a cópia boa é a velha
    novo.mkdir(parents=True)
    con.execute(f"""COPY (SELECT *, year(ts) AS year FROM bars_m1 WHERE symbol = ?
                    ORDER BY ts) TO {_sql_str(novo)}
                    (FORMAT PARQUET, PARTITION_BY (year), OVERWRITE_OR_IGNORE 1,
                     COMPRESSION zstd)""", [symbol])
    if not list(novo.rglob("*.parquet")):
        raise RuntimeError(f"COPY nao gravou nenhum arquivo em {novo}")
    # No Windows uma pasta com arquivo aberto (leitor no meio) não se
    # renomeia: espera o leitor soltar. Só este passo se repete.
    if out.exists():
        for i in range(40):
            try:
                out.rename(velho)
                break
            except PermissionError:
                if i == 39:
                    raise
                _t.sleep(0.25)
    try:
        novo.rename(out)
    except OSError:
        if velho.exists():
            velho.rename(out)         # desfaz: o espelho antigo volta inteiro
        raise
    shutil.rmtree(velho, ignore_errors=True)
    return out
```

  Em `read_bars_parquet`: se a pasta `src` não existir mas existir `<src>.novo` ou `<src>.velho`, a troca está em andamento. Nesse caso, tentar de novo a cada 0,1 s por até 2 s antes de levantar `FileNotFoundError`. O comentário deve explicar: a captura troca o espelho entre dois renames.

- [ ] **Step 4: rodar** os testes novos, `tests/test_mt5_source.py` e a suíte inteira → PASS.
- [ ] **Step 5: mutação** — tire o `velho.rename(out)` do `except` → `test_falha_na_troca…` falha.
- [ ] **Step 6: commit** — `core/db_manager.py tests/test_db_parquet_atomico.py`, mensagem `fix(db): espelho Parquet trocado de uma vez, sem ano orfao`.

---

### Task 7: O processo `captura.py` e a janela própria

**Files:**
- Create: `captura.py` (raiz), `captura.bat` (raiz)
- Modify: `iniciar.bat`
- Test: `tests/test_captura_processo.py` (novo)

**Interfaces:**
- Consumes: tudo de `core/captura.py` (Tasks 1, 5); `db.connect_write`, `db.connect`, `db.export_parquet` (Task 6); `cal.rebuild_trading_days`, `roll.rebuild_rollovers`.
- Produces: o arquivo `data/ao_vivo/estado.json` com as chaves (lidas pelas Tasks 8–9):
  `pid, atualizado_em, mt5 ("conectado"|"sem_conexao"|"fechado"), mt5_desde, conta {login, servidor}, contrato_vigente, simbolo, fechamento_esperado ("HH:MM"), em_pregao, ultimo_salvo, em_formacao ({ts, open, high, low, close} | null), lacunas_hoje [iso], gravados_hoje, recuperados_hoje, revisados_hoje, conferencia {status: "pendente"|"concluida"|"falhou", em, dias, erro}, banco_ocupado_desde, relogio_desvio_s, primeiro_candle_hoje, erro`.
  Códigos de saída: `0` normal (Ctrl+C), `3` configuração (não reabrir, mostra aviso), `4` outra instância (o .bat sai calado), outros = reabrir.

**Desenho do `captura.py`** (classe com tudo injetável, para testar sem MT5 real):

```python
"""Serviço de captura — grava cada candle M1 fechado do WIN$N, ao vivo.

    .venv/Scripts/python.exe captura.py      (o iniciar.bat abre numa janela própria)

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md.
Processo à parte da tela de propósito: a tela reinicia a cada mudança e
trava em mineração; um laço contínuo dentro dela perderia candle (e, na
parte 4, ordem). Toda decisão mora em core/captura.py; aqui só o laço.
"""
SAIR_SEM_REABRIR = 3      # configuração: reabrir não resolve
OUTRA_INSTANCIA = 4       # já há uma captura rodando: o .bat sai calado
PASTA = db.DATA / "ao_vivo"


class ErroDeConfiguracao(RuntimeError):
    """Erro que reabrir não resolve: o .bat não deve tentar de novo."""


def travar(caminho: Path):
    """Trava de instância pelo Windows (msvcrt.locking): se o processo
    morrer, o sistema solta sozinho — um arquivo .pid ficaria órfão.
    Quem chama guarda o objeto devolvido pela vida inteira do processo."""
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
                 mono=time.monotonic, pasta=PASTA, terminal_aberto=None,
                 price_decimals=0): ...
    def volta(self) -> float:   # uma volta; devolve quantos segundos esperar
    def rodar(self) -> None:    # laço: volta(); sleep(espera)
```

**Regras gerais do `Servico`:**
- **Nenhum passo retorna antes do passo 9.** Os passos marcam o que aconteceu e pulam o resto, mas o estado é sempre escrito.
- **Toda conexão ao banco usa no máximo ~1 s:** `db.connect_write(tentativas=4, espera=0.25)` e `db.connect(read_only=True, tentativas=4)`.
  - `RuntimeError` de banco ocupado em **qualquer** passo → `banco_ocupado_desde = banco_ocupado_desde or agora` e o passo é pulado, sem ser tratado como erro.
  - `banco_ocupado_desde` volta a `None` quando uma gravação dá certo.
- `self.inst = db.load_instrument_yaml(simbolo)`, carregado no `__init__`. Se o YAML não existir → `ErroDeConfiguracao`.
- `self.relogio = captura.RelogioServidor()` (Task 1).

**Na primeira volta** (conexão de leitura curta; banco ocupado → tenta de novo na volta seguinte):
- `ultimo = SELECT max(ts)`. Base vazia → `ErroDeConfiguracao("base vazia — rode corrigir_base.py ou cli.py ingest antes")`.
- `fechamento = fechamento_esperado(...)`. Relido a cada troca de dia.
- Contadores de hoje, para um reinício não zerá-los:
  - `gravados_hoje` = candles de hoje cuja origem começa com `captura://`;
  - `conferencia` = `{"status": "concluida", "em": ingested_at}` se existir `conferencia://<hoje>` no `ingest_log`, senão `{"status": "pendente"}`.
- `recuperados_hoje` e `revisados_hoje` começam em 0. Isso é aceitável e está documentado no estado.

**`volta()`, nesta ordem:**
1. `agora = self.agora()`; `m = self.mono()`.
2. **MT5:**
   - **Ainda não conectado:** só chama `mt5.initialize(path=terminal)` (ou `initialize()`, sem caminho) **se `terminal_aberto()` for verdadeiro**. O padrão é: a saída de `tasklist /FI "IMAGENAME eq terminal64.exe"` contém `terminal64.exe`. Chamar sem o MT5 aberto abriria um terminal sozinho. Limitação conhecida: com dois MT5 instalados, o `tasklist` não confere qual deles está aberto.
   - **Falhou ou está fechado:** `mt5 = "fechado"` e pula para o passo 8.
   - **`terminal_info()` devolveu `None`:** marca desconectado (a volta seguinte reinicializa), `mt5 = "fechado"` e pula.
   - **`connected` é `False`:** `mt5 = "sem_conexao"`; guarda `mt5_desde = agora` só na primeira vez; pula.
   - **Conectado:** `mt5_desde = None`.
   - **Na primeira conexão:**
     - `symbol_select(simbolo, True)` falso → `ErroDeConfiguracao(f"o MT5 não tem {simbolo}")`;
     - `account_info()` → `conta`;
     - `getattr(symbol_info(simbolo), "basis", None)` → `contrato_vigente`.
3. **Relógio:** `tick = symbol_info_tick` convertido como em `mt5_source` (epoch → `datetime` sem fuso); `relogio.observar(tick, m)`; `agora_srv = relogio.agora(m)`; `relogio_desvio_s = relogio.desvio_s(agora, m)` (vai ao estado só se `abs > 30`).
4. **Busca:**
   - `copy_rates_range(simbolo, M1, (ultimo + 1 min).replace(tzinfo=utc), (agora + 1 dia).replace(tzinfo=utc))` → DataFrame igual ao de `buscar_barras`. `None` ou vazio significa nada novo.
   - `prontos = fechados(df, agora_srv)`.
   - `em_formacao` = a última linha de `df` se ela não estiver em `prontos`; senão `None`.
   - Se veio candle com `ts` maior que o maior já visto, guarda `self.candle_mais_novo = esse ts`.
5. **Grava** (se houver `prontos`):
   - `gravar(con, simbolo, prontos, origem_captura(login, servidor), price_decimals)` e fecha a conexão.
   - Avança `ultimo = prontos.ts.max()`.
   - Soma:
     - `gravados_hoje += inseridos`;
     - `revisados_hoje += revisados`;
     - `recuperados_hoje +=` quantos `prontos` têm `ts < agora_srv − 2 min`.
   - Com o banco ocupado, **não** avança `ultimo`: a volta seguinte pede de novo ao MT5.
   - Os contadores zeram na troca de dia.
6. **Lacunas** (a cada 60 s de `mono`, só no pregão):
   - candles fechados de hoje no MT5 (`copy_rates_range` de 00:00 até agora e `fechados`) × `SELECT ts FROM bars_m1` de hoje → `lacunas_hoje`;
   - se houver lacuna, regrava pelo mesmo `gravar`: é a recuperação sozinha.
7. **Conferência** (a cada 5 min de `mono`, e na primeira volta conectada):
   - `fechou` = `agora > combine(hoje, fechamento) + 6 min` **e** `candle_mais_novo` (de hoje) é `None` ou `<= (agora_srv or agora) − 10 min`.

     O segundo critério cobre a troca de horário dos EUA: por uns 5 pregões a moda ainda diz 17:54 com o mercado indo até 18:24, e conferir às 18:00 deixaria 18:00–18:24 sem conferência.
   - `dias = dias_pendentes(con, simbolo, agora.date(), fechou)`.
   - Para cada dia: candles do dia no MT5 (`copy_rates_range` 00:00→23:59 do dia, depois `fechados(…, agora_srv)`) e `conferir_dia(..., agora=agora)`.
   - Se algum dia foi conferido:
     - `cal.rebuild_trading_days`;
     - `roll.rebuild_rollovers(con, simbolo, self.inst.get("rollover_policy"))`;
     - `db.export_parquet`;
     - `conferencia = {"status": "concluida", "em": agora, "dias": [...]}`.
   - Erro que não seja banco ocupado → `{"status": "falhou", "em": agora, "erro": str(e)}` + log; tenta de novo na janela seguinte.
8. **Pregão e hibernação:**
   - `pregao = em_pregao(agora, fechamento) or (candle_mais_novo de hoje e agora_srv − candle_mais_novo < 10 min)`.
   - No pregão: `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)`. Fora: `SetThreadExecutionState(0x80000000)`. Se `ctypes.windll` não existir, ignorar.
9. **Estado:** `escrever_estado(pasta / "estado.json", {...})` com todas as chaves, mais:
   - `atualizado_em = agora`, `pid = os.getpid()`;
   - `em_pregao = pregao`;
   - `fechamento_esperado = "HH:MM"`;
   - `primeiro_candle_hoje` (ts do primeiro candle de hoje no banco, ou `None`);
   - `erro = None` quando a volta não teve exceção.

   Falha ao escrever o estado → só vai para o log; o laço segue.
10. Devolve `1` no pregão e `30` fora dele. Se o MT5 estiver fechado ou sem conexão: `5`.

**`rodar()`:**
- `ErroDeConfiguracao` **sobe**, e o `main` a transforma no código 3.
- Qualquer outra exceção na volta → log com traceback; escreve o estado com `erro = str(e)` (em try/except próprio); espera 5 s e segue.

**`main(argv=None) -> int`:**
1. `argparse`: `--simbolo` (padrão `WIN$N`) e `--terminal`.
2. **Primeiro a trava**, antes de abrir o log: `trava = travar(PASTA / "captura.lock")`. Se vier `None`, imprime só no console "outra janela da captura já está aberta" e `return OUTRA_INSTANCIA`.
3. Abre o log em `PASTA / "captura.log"` (`RotatingFileHandler`, 5 MB, 3 cópias), espelhado no console.
4. Se `import MetaTrader5` falhar → estado com `erro` e `return 3`.
5. Sem `--terminal`, usa o `terminal` da conta não arquivada mais recente que tiver um: `SELECT terminal FROM contas WHERE arquivada_em IS NULL AND terminal IS NOT NULL ORDER BY conta_id DESC LIMIT 1`.
6. `Servico(...).rodar()`, tratando a saída assim:
   - `KeyboardInterrupt` → `mt5.shutdown()`, `return 0`;
   - `ErroDeConfiguracao` → estado com `erro`, log, `return 3`.

`trava` é referenciada até o fim do `main`. Fim do arquivo: `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 1: testes (falhando)** — `tests/test_captura_processo.py` com um MT5 falso:

```python
"""O processo da captura com MT5 e relógio falsos (sem terminal de verdade)."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
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


class Mono:
    """monotonic controlado pelo teste"""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _servico(mt5, agora, pasta, mono=None):
    return P.Servico(mt5=mt5, agora=lambda: agora, mono=mono or Mono(), pasta=pasta,
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
    s = P.Servico(mt5=mt5, agora=lambda: agora, mono=Mono(), pasta=base / "ao_vivo",
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
                  mono=Mono(), pasta=base / "ao_vivo", terminal_aberto=lambda: True)
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


def test_reinicio_nao_zera_o_placar_do_dia(base):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    _servico(mt5, agora, base / "ao_vivo").volta()
    _servico(mt5, agora + timedelta(seconds=5), base / "ao_vivo").volta()   # reabriu
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["gravados_hoje"] == 5


def test_erro_passageiro_some_na_volta_seguinte(base, monkeypatch):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    original = mt5.copy_rates_range
    mt5.copy_rates_range = lambda *a: (_ for _ in ()).throw(RuntimeError("falha do terminal"))
    s.passo_seguro()                       # o que o rodar() faz a cada volta
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["erro"] == "falha do terminal"
    mt5.copy_rates_range = original
    s.passo_seguro()
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["erro"] is None


def test_mercado_ainda_aberto_apos_o_fechamento_esperado_nao_confere(base):
    # troca de horário dos EUA: a moda diz 17:54, mas o mercado vai até 18:24
    agora = datetime(2026, 10, 1, 18, 5)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 17, 50), 15), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    s.fechamento = time(17, 54)           # como se o histórico dissesse 17:54
    s.volta()
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["conferencia"]["status"] != "concluida"


def test_main_com_outra_instancia_devolve_4_sem_abrir_log(base, monkeypatch):
    monkeypatch.setattr(P, "PASTA", base / "ao_vivo")
    trava = P.travar(base / "ao_vivo" / "captura.lock")
    assert P.main([]) == P.OUTRA_INSTANCIA
    assert not (base / "ao_vivo" / "captura.log").exists()
    trava.close()


def test_segunda_instancia_nao_pega_a_trava(base):
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

  Notas para o implementador:
  - `copy_rates_range` do falso remove o fuso dos datetimes que recebe.
  - Ajuste o `MT5Falso` só se o `Servico` precisar de outro método do pacote. Nunca afrouxe as asserções.
  - `passo_seguro()` é a volta com o tratamento de exceção que o `rodar()` usa. Separe-a do `sleep` para poder testá-la.
  - O teste do fechamento atrasado atribui `s.fechamento` antes da primeira volta. A leitura do banco na primeira volta só preenche `fechamento` se ele ainda for `None`.

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
REM 4 = ja ha uma captura aberta (iniciar.bat reaberto): sai sem incomodar
if "%CODIGO%"=="4" exit /b 0
if "%CODIGO%"=="3" (
    echo.
    echo  A captura parou e nao vai reabrir sozinha: falta configuracao.
    echo  Detalhes em data\ao_vivo\captura.log
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

- [ ] **Step 6: conferência real (mercado fechado ou aberto, tanto faz)** — rodar `.venv/Scripts/python.exe captura.py` por ~1 min com o MT5 aberto; conferir em `data/ao_vivo/estado.json` `mt5 = conectado`, `ultimo_salvo` = último minuto fechado, sem erro; Ctrl+C sai com 0 (o Windows ainda pergunta "Terminate batch job?" na janela do .bat — normal). Rodar duas vezes ao mesmo tempo → a segunda sai com 4, calada.
- [ ] **Step 7: mutação** — tire o `if terminal_aberto()` → `test_mt5_fechado...` falha; avance `ultimo` mesmo com banco ocupado → o teste do banco ocupado falha; tire o segundo critério do `fechou` → o teste do mercado aberto após o fechamento esperado falha; não limpe `erro` → o teste do erro passageiro falha.
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
2. `pregao` = `estado["em_pregao"]` se o estado está fresco; senão `em_pregao(agora, fechamento do estado ou 18:24)` (o serviço morto não sabe dizer). Estado velho (> 60 s): no pregão → rosa "Captura parada há N min" + ação "confira a janela “Dataframe - Captura”"; fora → cinza "Captura parada (fora do pregão)", `ativa False`.
3. `erro` → rosa, o texto do erro.
4. `mt5 == "fechado"` → rosa "MT5 fechado", ação "abra e faça login; a captura recupera o período sozinha".
5. `mt5 == "sem_conexao"` → âmbar "Sem conexão com a corretora desde HH:MM".
6. `banco_ocupado_desde` há mais de 2 min → âmbar "Banco ocupado há N s" (ação: "uma mineração está gravando; nada se perde").
7. `relogio_desvio_s` → âmbar "Relógio do PC adiantado N s" (positivo) ou "atrasado N s" (negativo).
8. Dia útil, captura em dia, mas nenhum candle de hoje ainda (`primeiro_candle_hoje` nulo): antes das 10:00 → cinza "Aguardando a abertura"; depois das 10:00 → cinza "Sem pregão hoje (feriado?)". Sem alarme — a B3 tem feriados que o código não conhece (12/10, 02/11, 20/11…).
9. Senão → verde "Captura ativa" (fora do pregão: verde "Captura ativa — mercado fechado").

- [ ] **Step 1: testes (falhando)** — `tests/test_pregao_tela.py`: um teste por regra acima (montando dicionários de estado à mão, `agora = datetime(2026, 10, 1, 10, 0)` numa quinta), mais:

```python
@pytest.fixture(autouse=True)
def _estado_limpo(monkeypatch):
    # globais de módulo: sem isto um teste vaza estado para o seguinte
    from ui import data as D
    monkeypatch.setattr(D, "_estado_ultimo", None)
    monkeypatch.setattr(D, "_conferencia_vista", None)


def test_estado_captura_guarda_a_ultima_leitura_valida(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
    assert D.estado_captura() is None
    p.write_text('{"mt5": "conectado"}', encoding="utf-8")
    assert D.estado_captura() == {"mt5": "conectado"}
    p.write_text("{meio", encoding="utf-8")
    assert D.estado_captura() == {"mt5": "conectado"}


def test_conferencia_nova_limpa_o_cache_de_barras(tmp_path, monkeypatch):
    from ui import data as D
    p = tmp_path / "estado.json"
    monkeypatch.setattr(D, "ESTADO_CAPTURA", p)
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
  - `ui/data.py` — `bars()` passa a ser à prova de corrida com o `clear()` (o Flask atende em várias threads): `b = _bars_cache.get(symbol)`; se `None`, carrega, guarda e devolve `b` (nunca `return _bars_cache[symbol]` depois de guardar).
  - `ui/data.py`: `from core import captura as CAP`; `ESTADO_CAPTURA = db.DATA / "ao_vivo" / "estado.json"`; `_estado_ultimo = None`, `_conferencia_vista = None`; `estado_captura()`: arquivo ausente → `None` (e zera `_estado_ultimo`); ilegível → `_estado_ultimo`; válido → guarda; se `(e.get("conferencia") or {}).get("em")` difere de `_conferencia_vista` e esta não é `None` → `_bars_cache.clear()`; atualiza `_conferencia_vista`. Comentário: a mineração/backtest passam a ver o dia conferido.
  - `ui/components/pregao_panel.py` (cabeçalho: spec §6; só desenha, sem ler arquivo): `situacao`, `captura_ativa`, `selo(sit) -> (children, className, style)` — esconde (`display: none`) quando `sit["tom"] == "cinza"`; senão `html.Span([● , texto])` com classe `captura-selo captura-selo-<tom>` e `title` = ação.
  - `ui/app.py` topbar: antes do `mt5-sync-wrap`, `html.Span(id="captura-selo", className="captura-selo", style={"display": "none"})`; no layout, `dcc.Interval(id="captura-intervalo", interval=30_000)`.
  - `ui/callbacks_mt5.py`: `motivo_bloqueio()` → `"a captura ao vivo já mantém a base em dia"` se `PP.captura_ativa(D.estado_captura(), datetime.now())`, senão `None`; no início de `sincronizar_mt5`, se houver motivo → devolve `(motivo, "mt5-sync-status", no_update×3)`.
  - **Calendário do Backtest:** `d-ate.date`, `d-ate.max_date_allowed` e `d-de.max_date_allowed` são calculados no `build()`; o `sincronizar_mt5` já os reescreve. Um segundo callback em `ui/callbacks_pregao.py`, `Input("captura-intervalo", "n_intervals")`, escreve as três props com `allow_duplicate=True` e `prevent_initial_call=True` **só quando `conferencia.em` mudou** desde a última vez (guardar em `dcc.Store(id="captura-conferencia-vista")`; senão `no_update`), usando `D.span(simbolo)` depois da invalidação. Teste: com `conferencia.em` novo, o callback devolve a data nova; repetido, `no_update`.
  - `ui/callbacks_pregao.py` com `register(app)`; o callback do selo: `Input("captura-intervalo", "n_intervals")` → `Output("captura-selo", "children")`, `("captura-selo", "className")`, `("captura-selo", "style")`, `("captura-selo", "title")`, `("btn-mt5-sync", "disabled")`, `("btn-mt5-sync", "title")`. Registrar em `ui/callbacks.py:register` como os outros (`from ui import callbacks_pregao; callbacks_pregao.register(app)`).
  - CSS no fim de `ui/assets/style.css`, bloco `/* ---- Captura: selo no topo ---- */`, com as variáveis existentes (`--pos`, `--warn`, `--neg`, `--muted`).
- [ ] **Step 4: rodar** `tests/test_pregao_tela.py tests/test_callbacks_sem_ciclo.py` → PASS; suíte inteira.
- [ ] **Step 5: commit** — `ui/data.py ui/app.py ui/callbacks.py ui/callbacks_mt5.py ui/callbacks_pregao.py ui/components/pregao_panel.py ui/assets/style.css tests/test_pregao_tela.py`, `feat(ao-vivo): selo da captura no topo e Sincronizar travado com a captura ativa`.

---

### Task 9: Sub-tela Pregão (layout A)

Siga também `.claude/agents/designer-ui.md` (sistema visual, rótulo + valor, pílulas, CSS por bloco).

**Files:**
- Modify: `ui/components/ao_vivo_panel.py`, `ui/components/pregao_panel.py`, `ui/callbacks_pregao.py`, `ui/data.py`, `ui/assets/style.css`
- Test: `tests/test_pregao_tela.py`, `tests/test_ao_vivo_tela.py` (**obrigatório**: o `assert "Estratégias" in textos(p)` da linha ~50 quebra, porque `textos` não lê `options` de RadioItems — troque por achar o `RadioItems` de id `av-subtela` e conferir `[o["label"] for o in options] == ["Estratégias", "Pregão"]`)

**Interfaces:**
- Consumes: `D.estado_captura`, `situacao` (Task 8); `D.candles(symbol, inicio, fim, tf)` existente; `charts.price_series`.
- Produces: ids `av-subtela`, `av-bloco-estrategias`, `av-bloco-pregao`, `av-pg-intervalo`, `av-pg-ultimo`, `av-pg-faixa`, `av-pg-placar`, `av-pg-tf`, `av-pg-agora`, `av-pg-cheia`, `av-pg-grafico`, `av-pg-grafico-caixa`; funções puras `pregao_panel.faixa(estado, agora)`, `pregao_panel.placar(estado)`, `pregao_panel.idade_tom(segundos: float, pregao: bool) -> str`, `pregao_panel.tick_formacao(estado, tf: str, balde: list[dict]) -> dict | None`, `D.dia_do_pregao(estado) -> date`.

**Desenho:**
- `ao_vivo_panel.painel()`: troca o `html.Span("Estratégias", className="chip av-subtela")` por `dcc.RadioItems(id="av-subtela", value="estrategias", persistence=True, persistence_type="local", className="av-subtelas", options=[Estratégias, Pregão])`; tudo o que hoje vem depois do cabeçalho vai para `html.Div(id="av-bloco-estrategias")`; acrescenta `pregao_panel.bloco()` (`id="av-bloco-pregao"`, `display: none`). **Preserve a remoção do parágrafo "robô de papel" feita pelo usuário.** Atualize o docstring do módulo (a sub-tela Pregão existe agora).
- `pregao_panel.bloco()`: `dcc.Interval(id="av-pg-intervalo", interval=2000, disabled=True)`, `dcc.Store(id="av-pg-ultimo")`; linha de 4 cartões `av-pg-faixa` (Captura · MT5 · Último candle · Lacunas hoje) + faixa de alerta quando `situacao` não é verde; painel do gráfico com barra: `dcc.RadioItems(id="av-pg-tf", value="M1", options 1 min/5 min/15 min)`, botões "Voltar para agora" (`av-pg-agora`) e "Tela cheia" (`av-pg-cheia`), e `html.Div(Tvlwc(id="av-pg-grafico", series=[], chartOptions=T.CHART_OPTIONS, height="100%"), id="av-pg-grafico-caixa", className="pg-grafico")` (zoom e arrastar já vêm do componente; logo da TradingView fica); 4 cartões `av-pg-placar` (Gravados hoje · Recuperados · Correções da corretora · Conferência do dia: "pendente"/"concluída às HH:MM"/"falhou — tenta de novo em 5 min").
- `idade_tom`: fora do pregão → `"cinza"`; ≤ 90 s verde; ≤ 180 s âmbar; depois rosa. A idade é medida contra `primeiro_candle_hoje`/`ultimo_salvo` de **hoje**: sem candle de hoje, o cartão "Último candle" mostra o de ontem em cinza com "aguardando a abertura" (mesma regra 8 da `situacao`), nunca rosa.
- `tick_formacao(estado, tf, balde)`: sem `em_formacao` → `None`. M1 → `{"id": "preco", "bar": {time: to_epoch(ts), open, high, low, close}}`. M5/M15 → início do balde = minuto de `em_formacao` arredondado para baixo no múltiplo; `balde` = candles M1 fechados (`{"ts", "open", "high", "low", "close"}`) desde o início do balde; abre = open do primeiro (ou do em formação, se o balde vier vazio), máxima/mínima de todos, fecha = close do em formação; `time` = início do balde.
- `D.dia_do_pregao(estado)`: data de `ultimo_salvo` (ou hoje, sem estado). Fora do pregão o gráfico mostra esse último dia e a faixa diz "Mercado fechado".
- Callbacks (`ui/callbacks_pregao.py`):
  1. `subtela`: `Input("av-subtela", "value")`, `Input("modo", "value")` → `Output("av-bloco-estrategias", "style")`, `Output("av-bloco-pregao", "style")`, `Output("av-pg-intervalo", "disabled")` (ligado só com modo `aovivo` e sub-tela `pregao`).
  2. `pulso`: `Input("av-pg-intervalo", "n_intervals")`, `State("av-pg-ultimo", "data")`, `State("av-pg-tf", "value")` → `Output("av-pg-faixa", "children")`, `Output("av-pg-placar", "children")`, `Output("av-pg-ultimo", "data")` (`no_update` se `ultimo_salvo` não mudou), `Output("av-pg-grafico", "tick")`. **Nunca escreve `series`** — é isso que preserva o zoom. Para M5/M15 lê do banco só os M1 do balde atual (conexão de leitura curta).
  3. `serie`: `Input("av-pg-ultimo", "data")`, `Input("av-pg-tf", "value")`, `Input("av-subtela", "value")` → `Output("av-pg-grafico", "series")` = `charts.price_series(D.candles("WIN$N", dia 00:00, dia 23:59, tf))`.
  4. `agora`: `Input("av-pg-agora", "n_clicks")` **e** `Input("av-pg-tf", "value")` → `Output("av-pg-grafico", "timeScaleAction")` = `{"action": "scrollToRealTime", "nonce": <contador ou time.time()>}`, `prevent_initial_call=True`. Trocar o tempo gráfico também volta para agora: o componente preserva o intervalo LÓGICO (índices de barra) ao trocar `series`, e em 5 min o mesmo índice cai num horário diferente.
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
- [ ] **Step 1b:** docstring de `core/db_manager.py` e do `cli.py verify`/`derive`: as barras de HOJE gravadas pela captura só existem no banco até a conferência do dia (o Parquet e o `data/raw` não as têm). `cli.py verify` com a captura rodando apaga o dia. Acrescentar ao `cmd_verify` uma recusa se `data/ao_vivo/estado.json` tiver `atualizado_em` < 60 s ("feche a captura antes"), e a mesma frase na armadilha do CLAUDE.md.
- [ ] **Step 2:** `CHANGELOG.md` — entrada "Ao vivo, parte 2: serviço de captura e sub-tela Pregão", com a correção da base (o que foi apagado e por quê) em linguagem de usuário.
- [ ] **Step 3: commit** — `CLAUDE.md CHANGELOG.md core/db_manager.py cli.py`, `docs: servico de captura e correcao da base`.

---

## Depois de todas as tarefas

Revisão final da branch inteira (agente no modelo mais forte). Conferência real
com o mercado **aberto** (spec §8): candles entrando minuto a minuto, candle em
formação mexendo sem perder o zoom, lacunas = 0, fechar o MT5 e ver o aviso,
reabrir e ver recuperar, conferência do dia depois do fechamento.
