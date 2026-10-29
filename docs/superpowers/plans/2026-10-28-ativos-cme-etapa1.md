# Ativos da CME — Etapa 1 (foto do WIN, fichas, importação, gráfico) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MES e MNQ importados dos arquivos do London Strategic Edge, visíveis no seletor "ativo" e no gráfico em hora de Nova York com preço em pontos, sem mudar nada do WIN.

**Architecture:** Uma ficha YAML por ativo; `core/ativo.py` concentra relógio de pregão (UTC → NY → +6 h) e escala de preço; `core/importar_lse.py` lê as partes, converte, separa pregões com falha e entrega ao `ingest_df` que já existe. O gráfico (`ui/data.candles`) converte de volta na saída. Antes de tudo, uma "foto" dos resultados do WIN que é conferida no fim.

**Tech Stack:** Python 3, polars, DuckDB, numpy, zoneinfo, Dash, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` (seções 1, 2, 3, 4 — só as funções de relógio e preço —, 9, "Garantia do WIN" e "Ordem de entrega" item 1).

## Global Constraints

- WIN e tudo o que está salvo para ele: resultado idêntico, número a número (foto conferida na Task 7).
- Para o WIN (`win.yaml` sem campos novos): toda função de `core/ativo.py` é identidade (escala 1, deslocamento 0).
- Relógio de pregão: UTC → `America/New_York` → `+ (24:00 − sessao_abertura)`; `sessao_abertura: "18:00"` → +360 min.
- Preço guardado = round(preço / tick) × tick × 10^`price_decimals`, inteiro (MES 5432,25 → 543225).
- `instruments.tick_size` (INTEGER) recebe `tick_unid` (MES 25), nunca 0,25.
- Pregão suspeito: vazio interno > 60 min; ou primeira barra > 60 min depois das 18:00 NY; ou última barra antes das 16:59 NY, exceto entre 12:59 e 13:14 NY (fechamentos antecipados oficiais da CME, 13:00/13:15); ou pregão ausente (dia útil entre o primeiro e o último pregão sem barras, fora Ano Novo, Sexta-feira Santa e Natal, com a regra de sábado/domingo). O último pregão do arquivo é tratado pela regra do incompleto, não por esta.
- Último pregão do arquivo incompleto (última barra antes das 16:59 NY) não é gravado.
- Telas: nada de texto explicativo visível; explicação só em "(?)". Nenhuma tela nova nesta etapa.
- Testes nunca tocam `data/database.duckdb` (conftest isola `DB_PATH`); `ativos_temp/` não vai para o git.
- Commits na branch `new-strategies`, mensagem terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Fora desta etapa: motor, estratégias, moeda, faixas, trades no gráfico. Backtest no MES/MNQ ainda dá números errados até a etapa 2 — não é bug desta etapa.

## Review Focus

1. Domingo à noite (18:00 NY) cai no pregão de **segunda**, nas duas épocas do horário de verão (UTC−4 e UTC−5) — teste na Task 2.
2. Pregão de véspera de feriado com fechamento às 13:15 NY (24/12) não é suspeito e é gravado — teste na Task 4.
3. Sobreposição de partes com uma barra divergente para a importação inteira, sem gravar nada — teste na Task 4.
4. Reimportar os mesmos arquivos não duplica nem altera barras (`rows_inserted == 0`) — teste na Task 5.
5. Gráfico do WIN continua com o mesmo epoch e o mesmo preço inteiro de hoje — teste na Task 6.

---

### Task 1: Foto do WIN

**Files:**
- Create: `scripts/foto_win.py`
- Test: `tests/test_foto_win.py`

**Interfaces:**
- Consumes: `scripts/reassinar_codigo.copiar_banco(origem, destino)`, `scripts/_trades_do_plano.main(raiz, banco, ids, saida)`, `strategies.registry.descobrir()`, `strategies.base.defaults(schema)`, `core.engine.execution.prepare_bars`, `run_strategy`, `ExecutionProfile()`.
- Produces: `comparar(antes: dict, depois: dict) -> list[str]` (lista vazia = idêntico); CLI `python scripts/foto_win.py gravar <nome>` e `python scripts/foto_win.py conferir <nome>` (exit 1 se houver diferença). Fotos em `data/foto_win/<nome>.pkl` (dentro de `data/`, fora do git).

- [ ] **Step 1: Write the failing test** — `tests/test_foto_win.py`:

```python
import numpy as np
from scripts.foto_win import comparar

def _f(pnl):
    return {"planos": {7: {False: {"n_trades": 1, "trades": {"pnl": np.array(pnl)}}}},
            "estrategias": {"reversao_rsi": {"n_trades": 1, "trades": {"pnl": np.array(pnl)}}}}

def test_identico_nao_tem_diferenca():
    assert comparar(_f([1.0, 2.0]), _f([1.0, 2.0])) == []

def test_diferenca_e_apontada_com_o_caminho():
    difs = comparar(_f([1.0, 2.0]), _f([1.0, 2.5]))
    assert difs and all("pnl" in d for d in difs)
    assert any("planos/7" in d for d in difs) and any("estrategias/reversao_rsi" in d for d in difs)

def test_chave_que_some_e_diferenca():
    a = _f([1.0]); b = _f([1.0]); del b["planos"][7]
    assert any("planos/7" in d for d in comparar(a, b))
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_foto_win.py -v` — Expected: FAIL (`No module named scripts.foto_win` ou `comparar` ausente). Se `scripts` não for importável como pacote, criar `scripts/__init__.py` vazio.

- [ ] **Step 3: Implement `scripts/foto_win.py`**
  - `comparar`: percorre os dois dicionários recursivamente; arrays numpy comparados com `np.array_equal(a, b, equal_nan=True)` (exato, sem tolerância); cada diferença vira uma linha `"<caminho>: <antes> != <depois>"` (caminho com `/`), chave ausente de um lado também.
  - `gerar() -> dict`: copia `db.DB_PATH` para uma pasta temporária com `copiar_banco`; `{"planos": ...}` = todos os `plano_id` de `planos_operacao`, rodados via `_trades_do_plano.main(str(RAIZ), copia, ids, pkl_temp)` e lidos do pickle; `{"estrategias": ...}` = para cada estratégia de `descobrir()`, `run_strategy(prepare_bars(con, "WIN$N"), mod, defaults(mod.params_schema), ExecutionProfile(), db.load_instrument_yaml("WIN$N"))`, guardando `n_trades`, `trades` (dict de arrays), `sl_at_entry`, `tp_at_entry`, `ambiguous_bars`, `bloqueios`. Banco da cópia aberto `read_only=True`.
  - `gravar <nome>`: `gerar()` → pickle em `data/foto_win/<nome>.pkl`; não sobrescreve se já existir (sai com mensagem).
  - `conferir <nome>`: `gerar()`, `comparar(salva, nova)`; imprime "foto <nome>: idêntica (N planos, M estratégias)" ou as diferenças (até 30) e sai com código 1.

- [ ] **Step 4: Run** os testes — Expected: PASS.

- [ ] **Step 5: Gravar a foto de base** — `.venv/Scripts/python.exe scripts/foto_win.py gravar antes_cme` e depois `... conferir antes_cme`. Expected: "idêntica". Anotar no relatório o número de planos e estratégias.

- [ ] **Step 6: Commit** `scripts/foto_win.py`, `tests/test_foto_win.py` (e `scripts/__init__.py` se criado): `feat(cme): foto do WIN para conferir resultado identico`.

---

### Task 2: `core/ativo.py` — ficha, relógio de pregão e preço

**Files:**
- Create: `core/ativo.py`
- Test: `tests/test_ativo.py`

**Interfaces:**
- Consumes: `core.db_manager.load_instrument_yaml(symbol) -> dict`.
- Produces (usadas nas Tasks 3–6 e nas próximas etapas):
  - `@dataclass(frozen=True) class Ficha` com `symbol: str`, `currency: str`, `timezone: str`, `price_decimals: int`, `tick_size: float`, `point_value: float`, `tick_value: float`, `sessao_abertura: str | None`, `abertura_referencia: str | None`, `pregoes_descartados: dict[str, str]`, `pregoes_mantidos: dict[str, str]`; propriedades `escala: int`, `tick_unid: int`, `valor_por_unid: float`, `deslocamento_min: int`, `abertura_min: int | None`.
  - `ficha_de(cfg: dict) -> Ficha`; `ficha(symbol: str) -> Ficha` (cache por símbolo).
  - `utc_para_pregao(col: pl.Expr, f: Ficha) -> pl.Expr`
  - `hora_para_exibir(ts: datetime, f: Ficha) -> datetime`
  - `hora_para_motor(hhmm: str, f: Ficha) -> str`
  - `preco_para_exibir(v: int, f: Ficha) -> int | float`
  - `hora_para_minuto(hhmm: str) -> int` ("18:00" → 1080)

- [ ] **Step 1: Write the failing tests** — `tests/test_ativo.py`, com fichas montadas em memória (não dependem dos YAML da Task 3):

```python
from datetime import datetime, timezone
import polars as pl
from core import ativo

WIN = ativo.ficha_de({"symbol": "WIN$N", "currency": "BRL", "timezone": "America/Sao_Paulo",
                      "price_decimals": 0, "tick_size": 5, "point_value": 0.20, "tick_value": 1.0})
MES = ativo.ficha_de({"symbol": "MES", "currency": "USD", "timezone": "America/New_York",
                      "price_decimals": 2, "tick_size": 0.25, "point_value": 5.0, "tick_value": 1.25,
                      "sessao_abertura": "18:00", "abertura_referencia": "09:30"})

def _pregao(utc):
    df = pl.DataFrame({"t": [utc]}).with_columns(pl.col("t").dt.replace_time_zone("UTC"))
    return df.select(ativo.utc_para_pregao(pl.col("t"), MES)).item()

def test_derivados_mes():
    assert (MES.escala, MES.tick_unid, MES.deslocamento_min, MES.abertura_min) == (100, 25, 360, 930)
    assert MES.valor_por_unid == 0.05

def test_win_e_identidade():
    assert (WIN.escala, WIN.tick_unid, WIN.deslocamento_min, WIN.abertura_min) == (1, 5, 0, None)
    t = datetime(2026, 10, 28, 9, 0)
    assert ativo.hora_para_exibir(t, WIN) == t
    assert ativo.hora_para_motor("09:00", WIN) == "09:00"
    assert ativo.preco_para_exibir(197760, WIN) == 197760 and isinstance(ativo.preco_para_exibir(197760, WIN), int)

def test_domingo_18h_ny_cai_na_segunda_no_verao():          # UTC-4
    assert _pregao(datetime(2024, 6, 16, 22, 0)) == datetime(2024, 6, 17, 0, 0)

def test_domingo_18h_ny_cai_na_segunda_no_inverno():        # UTC-5
    assert _pregao(datetime(2024, 1, 7, 23, 0)) == datetime(2024, 1, 8, 0, 0)

def test_ultima_barra_16h59_ny_e_23h59_do_pregao():
    assert _pregao(datetime(2024, 6, 17, 20, 59)) == datetime(2024, 6, 17, 22, 59)

def test_virada_do_horario_de_verao_marco_2024():
    # domingo 10/03/2024: NY passa a UTC-4; o pregão de segunda abre 22:00 UTC
    assert _pregao(datetime(2024, 3, 10, 22, 0)) == datetime(2024, 3, 11, 0, 0)
    # sexta anterior (UTC-5): 16:59 NY = 21:59 UTC
    assert _pregao(datetime(2024, 3, 8, 21, 59)) == datetime(2024, 3, 8, 22, 59)

def test_ida_e_volta_de_hora():
    assert ativo.hora_para_motor("09:30", MES) == "15:30"
    assert ativo.hora_para_motor("18:00", MES) == "00:00"
    assert ativo.hora_para_exibir(datetime(2024, 6, 17, 15, 30), MES) == datetime(2024, 6, 17, 9, 30)
    assert ativo.hora_para_exibir(datetime(2024, 6, 17, 1, 0), MES) == datetime(2024, 6, 16, 19, 0)

def test_preco_mes():
    assert ativo.preco_para_exibir(543225, MES) == 5432.25
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_ativo.py -v` — Expected: FAIL (`core.ativo` não existe).

- [ ] **Step 3: Implement `core/ativo.py`**
  - `deslocamento_min = (1440 - hora_para_minuto(sessao_abertura)) % 1440` se houver `sessao_abertura`, senão 0.
  - `abertura_min = (hora_para_minuto(abertura_referencia) + deslocamento_min) % 1440` se houver, senão `None`.
  - `escala = 10 ** price_decimals`; `tick_unid = round(tick_size * escala)`; `valor_por_unid = point_value / escala`.
  - `utc_para_pregao`: `col.dt.convert_time_zone(f.timezone).dt.replace_time_zone(None) + pl.duration(minutes=f.deslocamento_min)`.
  - `preco_para_exibir`: devolve `v` inalterado se `escala == 1`, senão `v / escala`.
  - Ficha ausente de campos novos: `pregoes_descartados`/`pregoes_mantidos` viram `{}`; chaves no formato `"AAAA-MM-DD"` (data do pregão).
  - Docstring do módulo: a regra de unidades da spec em 4 linhas (humana × guardada × relógio).

- [ ] **Step 4: Run** os testes — Expected: PASS.

- [ ] **Step 5: Commit** `feat(cme): core/ativo - ficha, relogio de pregao e escala de preco`.

---

### Task 3: Fichas `mes.yaml` e `mnq.yaml` e `tick_size` em unidades guardadas no banco

**Files:**
- Create: `configs/instruments/mes.yaml`, `configs/instruments/mnq.yaml`
- Modify: `core/db_manager.py:190-201` (`upsert_instrument`)
- Test: `tests/test_ativo.py` (acrescentar)

**Interfaces:**
- Consumes: `ativo.ficha_de`.
- Produces: fichas carregáveis por `ativo.ficha("MES")` / `ativo.ficha("MNQ")`; `instruments.tick_size` = `tick_unid`.

- [ ] **Step 1: Write the failing tests** (acrescentar em `tests/test_ativo.py`):

```python
from core import db_manager as db

def test_fichas_dos_micros():
    mes, mnq = ativo.ficha("MES"), ativo.ficha("MNQ")
    assert (mes.point_value, mes.tick_value, mes.tick_unid, mes.currency) == (5.0, 1.25, 25, "USD")
    assert (mnq.point_value, mnq.tick_value, mnq.tick_unid) == (2.0, 0.50, 25)
    assert mes.deslocamento_min == mnq.deslocamento_min == 360
    assert set(mes.pregoes_descartados) == {"2020-02-27", "2020-02-28", "2020-03-02", "2020-03-03", "2022-06-21", "2026-10-12"}

def test_banco_guarda_tick_em_unidades_guardadas():
    with db.connect() as con:
        db.init_schema(con); db.sync_instruments(con)
        lin = dict(con.execute("SELECT symbol, tick_size FROM instruments").fetchall())
    assert lin["MES"] == 25 and lin["WIN$N"] == 5
```

- [ ] **Step 2: Run** — Expected: FAIL (YAML ausente).

- [ ] **Step 3: Escrever os YAML e ajustar `upsert_instrument`**
  - `mes.yaml`: exatamente o bloco da spec seção 1 (sem `perfil_padrao` e `faixas`, que são das etapas 2 e 4), com `description: "Micro E-mini S&P 500 - serie continua (London Strategic Edge)"`, `pregoes_descartados` com as 4 datas acima e motivo em português curto (ex.: `"2020-03-02": "falha da fonte: pregao inteiro ausente"`), e `pregoes_mantidos: {}`. Comentários no estilo do `win.yaml`.
  - `mnq.yaml`: igual, `symbol: "MNQ"`, `description: "Micro E-mini Nasdaq-100 - serie continua (London Strategic Edge)"`, `point_value: 2.00`, `tick_value: 0.50`.
  - `upsert_instrument`: grava `tick_size = ativo.ficha_de(cfg).tick_unid` em vez de `cfg["tick_size"]`. Para o WIN dá 5, igual a hoje.

- [ ] **Step 4: Run** `tests/test_ativo.py` e `tests/test_ingest.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(cme): fichas do MES e MNQ`.

---

### Task 4: `core/importar_lse.py` — leitura, conversão e pregões com falha

**Files:**
- Create: `core/importar_lse.py`
- Create: `tests/dados/lse/` (recortes; ver Step 1)
- Test: `tests/test_importar_lse.py`

**Interfaces:**
- Consumes: `ativo.Ficha`, `ativo.utc_para_pregao`.
- Produces:
  - `ler_partes(paths: list[Path]) -> pl.DataFrame` — colunas `time` (UTC), `open, high, low, close, volume, trades`; sem duplicados; `ValueError` se uma sobreposição divergir.
  - `preparar(df: pl.DataFrame, f: Ficha) -> pl.DataFrame` — colunas `ts, open, high, low, close, tick_volume, volume, spread` no formato de `core/ingest.validar` (preços Int64 em unidades guardadas, `tick_volume = trades`, `spread` nulo Int32), ordenado por `ts`.
  - `pregoes_suspeitos(df: pl.DataFrame, f: Ficha) -> dict[str, str]` — data do pregão `"AAAA-MM-DD"` → motivo legível em hora de NY (ex.: `"vazio de 312 min a partir de 11:05 NY"`, `"comecou as 09:40 NY"`).
  - `pregao_incompleto(df: pl.DataFrame) -> str | None` — data do último pregão se a última barra for antes de 22:59 no relógio de pregão.

- [ ] **Step 1: Criar os recortes** a partir de `ativos_temp/` (script descartável, não commitado), salvando Parquet pequeno com o mesmo esquema do original:
  - `tests/dados/lse/mes_2020_03.parquet`: `time` de 2020-02-26 00:00 a 2020-03-04 23:59 UTC (contém o buraco de 27/02 a 03/03).
  - `tests/dados/lse/mes_2024_12.parquet`: 2024-12-23 00:00 a 2024-12-27 23:59 UTC (véspera de Natal, fechamento 13:15 NY).
  - `tests/dados/lse/mnq_parte_a.parquet` e `mnq_parte_b.parquet`: duas partes do MNQ que se sobrepõem em 2019-09-19 22:00 a 2019-09-20 20:59 UTC (pegar 2019-09-18..09-20 da parte antiga e 2019-09-19..09-23 da nova).
  Conferir que somam menos de 2 MB.

- [ ] **Step 2: Write the failing tests** — `tests/test_importar_lse.py`:

```python
from pathlib import Path
import polars as pl, pytest
from core import ativo, importar_lse as lse

D = Path(__file__).parent / "dados" / "lse"
MES = ativo.ficha("MES")

def test_partes_sobrepostas_identicas_emendam():
    df = lse.ler_partes([D / "mnq_parte_a.parquet", D / "mnq_parte_b.parquet"])
    assert df["time"].is_unique().all() and df["time"].is_sorted()

def test_sobreposicao_divergente_para(tmp_path):
    b = pl.read_parquet(D / "mnq_parte_b.parquet")
    b = b.with_columns(pl.when(pl.int_range(pl.len()) == 0).then(pl.col("close") + 0.25)
                       .otherwise(pl.col("close")).alias("close"))
    b.write_parquet(tmp_path / "b.parquet")
    with pytest.raises(ValueError, match="diverg"):
        lse.ler_partes([D / "mnq_parte_a.parquet", tmp_path / "b.parquet"])

def test_preparar_arredonda_ao_tick_e_escala():
    df = pl.DataFrame({"time": [pl.datetime(2026, 9, 15, 20, 59, time_zone="UTC")],
                       "open": [7665.25], "high": [7665.499999999999], "low": [7664.999999999999],
                       "close": [7665.499999999999], "volume": [78.0], "trades": [40]})
    out = lse.preparar(df.with_columns(pl.col("time").dt.cast_time_unit("us")), MES)
    assert out.row(0, named=True)["high"] == 766550 and out["low"][0] == 766500
    assert out["tick_volume"][0] == 40 and out["volume"][0] == 78

def test_buraco_de_marco_2020_e_suspeito():
    s = lse.pregoes_suspeitos(lse.preparar(lse.ler_partes([D / "mes_2020_03.parquet"]), MES), MES)
    assert {"2020-02-27", "2020-02-28", "2020-03-02", "2020-03-03"} <= set(s)
    assert "2020-02-26" not in s and "2020-03-04" not in s

def test_vespera_de_natal_nao_e_suspeita():
    s = lse.pregoes_suspeitos(lse.preparar(lse.ler_partes([D / "mes_2024_12.parquet"]), MES), MES)
    assert "2024-12-24" not in s and "2024-12-26" not in s

def test_ultimo_pregao_incompleto():
    df = lse.preparar(lse.ler_partes([D / "mnq_parte_a.parquet"]), MES)  # termina 20/09 16:59 NY
    assert lse.pregao_incompleto(df) is None
    assert lse.pregao_incompleto(df.filter(pl.col("ts").dt.hour() < 20)) == str(df["ts"].dt.date().max())
```

  (O pregão de 02/03/2020 tem só a primeira hora — domingo 18:00–18:59 NY — e cai na regra "terminou antes das 16:59 NY"; o de 03/03 cai em "começo tardio".)

- [ ] **Step 3: Run** — Expected: FAIL (`core.importar_lse` não existe).

- [ ] **Step 4: Implement `core/importar_lse.py`**
  - `ler_partes`: `pl.read_parquet` de cada arquivo, exige as 7 colunas (mensagem com o nome do arquivo se faltar), `time` em `us` UTC; concatena; nas linhas com `time` repetido, compara OHLC+volume e levanta `ValueError("... diverge ...")` com até 5 exemplos; senão `unique(subset="time")` e ordena.
  - `preparar`: `round(x / tick_size) * tick_unid` → Int64; `volume` e `trades` → Int64 (recusa volume não inteiro); `ts = utc_para_pregao(time)`.
  - `pregoes_suspeitos`: agrupa por `ts.dt.date()`; minuto do pregão = `hour*60+minute`; suspeito se `max(diff entre barras consecutivas do mesmo pregão) > 60 min`, se o primeiro minuto > 60, ou se o último minuto < `hora_para_minuto("16:59") + deslocamento_min` fora da janela 12:59–13:14 NY; mais a regra de pregão ausente (dias úteis sem barras, exceto feriados de fechamento total). O último pregão do DataFrame fica fora desta checagem (é assunto de `pregao_incompleto`). Motivos em hora de NY usando `hora_para_exibir` (ex.: `"terminou as 18:59 NY"`).
  - Docstring: de onde vêm os dados, o limite de 2,5 M linhas por download e a regra dos suspeitos.

- [ ] **Step 5: Run** — Expected: PASS.

- [ ] **Step 6: Commit** `feat(cme): leitura e conversao dos arquivos do London Strategic Edge` (inclui `tests/dados/lse/*.parquet`).

---

### Task 5: Importação completa e subcomando `importar-lse`

**Files:**
- Modify: `core/importar_lse.py` (acrescentar `importar`)
- Modify: `core/schema.sql` (`ALTER TABLE ingest_log ADD COLUMN IF NOT EXISTS observacao VARCHAR`)
- Modify: `cli.py` (subcomando `importar-lse`)
- Test: `tests/test_importar_lse.py` (acrescentar)

**Interfaces:**
- Consumes: Task 4; `core.ingest.ingest_df(con, df, symbol, origem, sha, price_decimals=0)`; `core.calendar.rebuild_trading_days`; `core.rollovers.rebuild_rollovers`; `db.export_parquet`; `db.sync_instruments`.
- Produces:
  - `class SuspeitoNovo(Exception)` com atributo `pregoes: dict[str, str]`.
  - `@dataclass class ResultadoLSE`: `ingest: IngestResult`, `descartados: dict[str, str]`, `incompleto: str | None`.
  - `importar(con, symbol: str, paths: list[Path]) -> ResultadoLSE`.
  - CLI: `python cli.py importar-lse --symbol MES <arquivos...>`.

- [ ] **Step 1: Write the failing tests**:

```python
from core import db_manager as db

def _con():
    con = db.connect(); db.init_schema(con); db.sync_instruments(con); return con

def test_importar_descarta_os_da_lista_e_grava_o_resto():
    con = _con()
    r = lse.importar(con, "MES", [D / "mes_2020_03.parquet"])
    datas = {str(d) for (d,) in con.execute("SELECT DISTINCT CAST(ts AS DATE) FROM bars_m1 WHERE symbol='MES'").fetchall()}
    assert "2020-03-03" not in datas and "2020-03-04" in datas
    assert "2020-03-03" in r.descartados
    obs = con.execute("SELECT observacao FROM ingest_log WHERE symbol='MES'").fetchone()[0]
    assert "2020-03-03" in obs

def test_suspeito_fora_da_lista_para_sem_gravar(monkeypatch):
    con = _con()
    monkeypatch.setattr(lse, "_ficha", lambda s: ativo.ficha_de({**db.load_instrument_yaml("MES"), "pregoes_descartados": {}}))
    with pytest.raises(lse.SuspeitoNovo) as e:
        lse.importar(con, "MES", [D / "mes_2020_03.parquet"])
    assert "2020-03-03" in e.value.pregoes
    assert con.execute("SELECT count(*) FROM bars_m1 WHERE symbol='MES'").fetchone()[0] == 0

def test_mantido_pela_lista_e_gravado(monkeypatch):
    con = _con()
    cfg = {**db.load_instrument_yaml("MES"), "pregoes_descartados": {},
           "pregoes_mantidos": {"2020-03-02": "teste", "2020-03-03": "teste"}}
    monkeypatch.setattr(lse, "_ficha", lambda s: ativo.ficha_de(cfg))
    lse.importar(con, "MES", [D / "mes_2020_03.parquet"])
    assert con.execute("SELECT count(*) FROM bars_m1 WHERE symbol='MES' AND CAST(ts AS DATE)='2020-03-03'").fetchone()[0] > 0

def test_reimportar_nao_altera_nada():
    con = _con()
    lse.importar(con, "MES", [D / "mes_2024_12.parquet"])
    r = lse.importar(con, "MES", [D / "mes_2024_12.parquet"])
    assert r.ingest.rows_inserted == 0 and r.ingest.rows_updated == 0

def test_win_nao_e_tocado():
    con = _con()
    lse.importar(con, "MES", [D / "mes_2024_12.parquet"])
    assert con.execute("SELECT count(*) FROM bars_m1 WHERE symbol='WIN$N'").fetchone()[0] == 0
```

  `export_parquet` escreve em `db.PARQUET_DIR`, que o conftest **não** isola: nos testes, `monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")` numa fixture local deste arquivo (autouse).

- [ ] **Step 2: Run** — Expected: FAIL.

- [ ] **Step 3: Implement**
  - `_ficha(symbol)` = `ativo.ficha(symbol)` (ponto de troca para os testes).
  - `importar`: `ler_partes` → `preparar` → `pregoes_suspeitos`; `novos = suspeitos − descartados − mantidos` → se houver, `raise SuspeitoNovo(novos)` antes de qualquer escrita; remove do DataFrame os pregões em `descartados` e o `pregao_incompleto`; `sha` = sha256 da concatenação dos sha256 dos arquivos (ordenados por nome); `origem = "lse:" + ";".join(nomes)`; `ingest_df(con, df, symbol, origem, sha, price_decimals=0)`; depois `UPDATE ingest_log SET observacao = ? WHERE ingest_id = ?` com JSON `{"descartados": {...}, "incompleto": ...}`; `rebuild_trading_days`, `rebuild_rollovers(con, symbol, "none")`, `export_parquet`.
  - `cli.py`: `cmd_importar_lse(args)` no estilo de `cmd_ingest` — `init_schema`, `sync_instruments`, `importar`, imprime `ingest.summary()`, a lista de descartados (data + motivo) e o incompleto; em `SuspeitoNovo`, imprime cada pregão com o motivo e a instrução "acrescente em pregoes_descartados ou pregoes_mantidos de configs/instruments/<arquivo>.yaml e rode de novo", e sai com código 1. Parser: `sub.add_parser("importar-lse")`, `--symbol` obrigatório, `arquivos` com `nargs="+"`.

- [ ] **Step 4: Run** `tests/test_importar_lse.py`, `tests/test_ingest.py`, `tests/test_db_parquet_atomico.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(cme): importacao do London Strategic Edge (cli importar-lse)`.

---

### Task 6: Gráfico em hora de NY e preço em pontos

**Files:**
- Modify: `ui/data.py:247-305` (`candles`)
- Test: `tests/test_ui_candles_ativo.py` (novo)

**Interfaces:**
- Consumes: `ativo.ficha`, `ativo.hora_para_exibir`, `ativo.preco_para_exibir`.
- Produces: `candles(symbol, inicio, fim, tf)` com `time` em epoch do relógio de parede **do ativo** (WIN: Brasília, igual a hoje; MES: NY) e OHLC em pontos. `inicio`/`fim` continuam no relógio de pregão (é o que o `store-window` guarda); só a saída muda. `to_epoch` não muda (usado pelo ao vivo).

- [ ] **Step 1: Write the failing tests** — banco isolado com barras gravadas à mão via `ingest_df` (uma de WIN, uma de MES):

```python
from datetime import datetime
import polars as pl
from core import db_manager as db, ingest
from ui import data as D

def _barra(con, symbol, ts, preco):
    df = pl.DataFrame({"ts": [ts], "open": [preco], "high": [preco], "low": [preco], "close": [preco],
                       "tick_volume": [1], "volume": [1], "spread": [None]},
                      schema_overrides={"spread": pl.Int32})
    ingest.ingest_df(con, df, symbol, "teste", f"sha-{symbol}")

def test_mes_sai_em_hora_de_ny_e_pontos():
    with db.connect() as con:
        db.init_schema(con); db.sync_instruments(con)
        _barra(con, "MES", datetime(2024, 6, 17, 15, 30), 543225)
    out = D.candles("MES", datetime(2024, 6, 17), datetime(2024, 6, 17, 23, 59), "M1")
    c = out["candles"][0]
    assert c["time"] == D.to_epoch(datetime(2024, 6, 17, 9, 30)) and c["open"] == 5432.25

def test_win_igual_a_hoje():
    with db.connect() as con:
        db.init_schema(con); db.sync_instruments(con)
        _barra(con, "WIN$N", datetime(2024, 6, 17, 9, 0), 130005)
    c = D.candles("WIN$N", datetime(2024, 6, 17), datetime(2024, 6, 17, 23, 59), "M1")["candles"][0]
    assert c["time"] == D.to_epoch(datetime(2024, 6, 17, 9, 0)) and c["open"] == 130005
    assert isinstance(c["open"], int)
```

- [ ] **Step 2: Run** — Expected: `test_mes_...` FAIL; `test_win_...` PASS.

- [ ] **Step 3: Implement** em `candles`: carregar `f = ativo.ficha(symbol)` uma vez; `time = to_epoch(ativo.hora_para_exibir(r[0], f))`; OHLC via `ativo.preco_para_exibir`. Mesmo tratamento na série de volume (`time`). Nada muda quando `f` é do WIN.

- [ ] **Step 4: Run** o arquivo novo e `tests/test_ui*.py`/`tests/test_charts*.py` existentes — Expected: PASS.

- [ ] **Step 5: Commit** `feat(cme): grafico em hora de NY e preco em pontos`.

---

### Task 7: Importação real, conferência no app e foto do WIN

**Files:** nenhum novo (pode atualizar `pregoes_descartados`/`pregoes_mantidos` nos YAML após decisão do usuário).

- [ ] **Step 1: Importar o MES** — com a captura fechada ou não (o `connect_write` espera a vez):
  `.venv/Scripts/python.exe cli.py importar-lse --symbol MES ativos_temp/MICROSP500_futures_1m_2019-05-05_2019-09-14.parquet ativos_temp/MICROSP500_futures_1m_2019-09-14_2026-10-28.parquet`
  Expected: termina com resumo, ou para com `SuspeitoNovo`. **Se parar, levar a lista ao usuário (data, motivo em hora de NY) e só seguir com a decisão dele** registrada no YAML.

- [ ] **Step 2: Importar o MNQ** — mesmo comando com `--symbol MNQ` e os dois arquivos `MICRONASDAQ100_*`. Mesmo tratamento.

- [ ] **Step 3: Conferir números** — `cli.py status --symbol MES` e `--symbol MNQ`: ~2,6 M barras cada, período 2019-05-05 → 2026-10-28, pregões descartados = os confirmados.

- [ ] **Step 4: Conferir no app** — `preview_start` com nome `dataframe`; trocar o seletor "ativo" para MES: o gráfico abre, o eixo mostra hora de NY (abertura do pregão às 18:00, pausa 17:00–18:00), preços com 2 casas. Repetir para MNQ e voltar ao WIN (inalterado). Screenshot de cada um.

- [ ] **Step 5: Foto do WIN** — `.venv/Scripts/python.exe scripts/foto_win.py conferir antes_cme`. Expected: "idêntica". Se não for, a etapa **não** é entregue: diagnosticar.

- [ ] **Step 6: Suíte inteira** em segundo plano (`.venv/Scripts/python.exe -m pytest -q`, ~13 min). Expected: tudo passa.

- [ ] **Step 7: Commit** dos YAML se mudaram: `chore(cme): pregoes com falha confirmados na primeira importacao`. Avisar o usuário para reabrir o `iniciar.bat` antes de olhar a tela.
