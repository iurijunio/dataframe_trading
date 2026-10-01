"""Serviço de captura: as contas, sem Dash e sem MetaTrader5 no topo.

Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §5.

O processo (`captura.py`, na raiz) é só o laço; tudo o que decide alguma
coisa mora aqui, para ser testado com MT5 e relógio falsos. A regra que
sustenta o resto: a captura nunca depende de ter "visto" cada minuto — a
cada volta pede ao MT5 tudo o que fechou desde o último candle salvo.
"""
from __future__ import annotations

import json
import os
import time as _t
from datetime import date, datetime, time, timedelta
from pathlib import Path

import polars as pl

from . import ingest as ing

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
    # Traz junto o source_max_ts do lote dono de cada candle: é com ele que o
    # ingest decide quem vence, e um candle que vai perder não pode chegar lá
    # (cada tentativa perdedora deixaria um lote vazio no ingest_log, a cada
    # volta de 1 s).
    linhas = con.execute(
        f"SELECT {', '.join('b.' + c for c in _COLUNAS)}, l.source_max_ts "
        "FROM bars_m1 b JOIN ingest_log l ON l.ingest_id = b.src_ingest_id "
        "WHERE b.symbol = ? AND b.ts BETWEEN ? AND ?",
        [symbol, barras["ts"].min(), barras["ts"].max()]).fetchall()
    if linhas:
        banco = pl.DataFrame(linhas, schema=[*_COLUNAS, "_dono"], orient="row").with_columns(
            [pl.col(c).cast(barras.schema[c]) for c in _COLUNAS])
        barras = barras.join(banco.select(_COLUNAS), on=list(_COLUNAS), how="anti")
        donos = banco.select("ts", "_dono")
        # O lote novo carrega como source_max_ts o maior ts que sobrar; tirar
        # um perdedor pode baixar esse máximo e transformar outro em perdedor.
        # Só descarto com `>` estrito: o empate depende do sha do lote final
        # e, na dúvida, deixo o ingest decidir em vez de descartar um vencedor.
        while barras.height:
            mx = barras["ts"].max()
            perde = barras.join(donos, on="ts", how="left").filter(pl.col("_dono") > mx)
            if perde.height == 0:
                break
            barras = barras.join(perde.select("ts"), on="ts", how="anti")
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


# O serviço publica o estado a cada volta (segundos no pregão, ~30 s fora);
# um minuto sem publicar é processo morto.
ESTADO_FRESCO_S = 60


def captura_ativa_em(caminho: Path, agora: datetime) -> bool:
    """A captura está gravando? Para os comandos que reconstroem a base
    (cli.py verify, corrigir_base.py): rodando junto, eles apagariam os
    candles de hoje, que o Parquet e o data/raw ainda não têm. Estado com
    hora no futuro (relógio do PC voltou) conta como ativa: na dúvida, recusa."""
    estado = ler_estado(caminho)
    try:
        feito = datetime.fromisoformat(str(estado["atualizado_em"]))
    except (TypeError, KeyError, ValueError):
        return False
    return (agora - feito).total_seconds() < ESTADO_FRESCO_S
