"""Ficha do ativo: relogio de pregao e escala de preco.

Tres unidades, cada lugar usa so uma:
- humana: pontos e hora local do ativo (tela, YAML, parametros e perfis salvos);
- guardada: preco x 10^price_decimals e relogio de pregao (banco, motor, trades);
- dinheiro: moeda do ativo (resultados, custos, point_value/tick_value).
Para o WIN (sem campos novos) todas as conversoes daqui sao identidade.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import polars as pl

from core.db_manager import load_instrument_yaml


def hora_para_minuto(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _min_para_hora(minutos: int) -> str:
    minutos %= 1440
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


@dataclass(frozen=True)
class Ficha:
    symbol: str
    currency: str
    timezone: str
    price_decimals: int
    tick_size: float
    point_value: float
    tick_value: float
    sessao_abertura: str | None = None
    abertura_referencia: str | None = None
    pregoes_descartados: dict[str, str] = field(default_factory=dict)
    pregoes_mantidos: dict[str, str] = field(default_factory=dict)
    perfil_padrao: dict | None = field(default=None, hash=False, compare=False)

    @property
    def escala(self) -> int:
        return 10 ** self.price_decimals

    @property
    def tick_unid(self) -> int:
        return round(self.tick_size * self.escala)

    @property
    def valor_por_unid(self) -> float:
        return self.point_value / self.escala

    @property
    def deslocamento_min(self) -> int:
        if not self.sessao_abertura:
            return 0
        return (1440 - hora_para_minuto(self.sessao_abertura)) % 1440

    @property
    def abertura_min(self) -> int | None:
        if not self.abertura_referencia:
            return None
        return (hora_para_minuto(self.abertura_referencia) + self.deslocamento_min) % 1440


def ficha_de(cfg: dict) -> Ficha:
    return Ficha(
        symbol=cfg["symbol"],
        currency=cfg["currency"],
        timezone=cfg["timezone"],
        price_decimals=int(cfg["price_decimals"]),
        tick_size=cfg["tick_size"],
        point_value=cfg["point_value"],
        tick_value=cfg["tick_value"],
        sessao_abertura=cfg.get("sessao_abertura"),
        abertura_referencia=cfg.get("abertura_referencia"),
        pregoes_descartados={str(k): v for k, v in (cfg.get("pregoes_descartados") or {}).items()},
        pregoes_mantidos={str(k): v for k, v in (cfg.get("pregoes_mantidos") or {}).items()},
        perfil_padrao=cfg.get("perfil_padrao"),
    )


@lru_cache(maxsize=None)
def ficha(symbol: str) -> Ficha:
    return ficha_de(load_instrument_yaml(symbol))


def utc_para_pregao(col: pl.Expr, f: Ficha) -> pl.Expr:
    """UTC -> hora local do ativo -> relogio de pregao (+ deslocamento)."""
    return (
        col.dt.convert_time_zone(f.timezone).dt.replace_time_zone(None)
        + pl.duration(minutes=f.deslocamento_min)
    )


def hora_para_exibir(ts: datetime, f: Ficha) -> datetime:
    if f.deslocamento_min == 0:
        return ts
    return ts - timedelta(minutes=f.deslocamento_min)


def hora_para_motor(hhmm: str, f: Ficha) -> str:
    if f.deslocamento_min == 0:
        return hhmm
    return _min_para_hora(hora_para_minuto(hhmm) + f.deslocamento_min)


def preco_para_exibir(v: int, f: Ficha) -> int | float:
    return v if f.escala == 1 else v / f.escala


def _identidade(f: Ficha | None) -> bool:
    return f is None or (f.escala == 1 and f.deslocamento_min == 0)


def ficha_do_instrumento(instr: dict) -> Ficha | None:
    """Ficha do dicionario do instrumento; None se for de teste/WIN antigo ou ja convertido."""
    if instr.get("_unidade") == "guardada":
        instr = instr.get("_original", instr)  # perfil e parametros chegam sempre em unidade humana
    if "price_decimals" not in instr and "sessao_abertura" not in instr:
        return None
    return ficha_de(instr)


def instrumento_para_motor(instr: dict, f: Ficha | None) -> dict:
    if _identidade(f) or instr.get("_unidade") == "guardada":
        return instr
    return {**instr, "tick_size": f.tick_unid, "point_value": f.valor_por_unid,
            "_unidade": "guardada", "_original": instr}


def perfil_para_motor(p: "ExecutionProfile", f: Ficha | None) -> "ExecutionProfile":
    if _identidade(f):
        return p
    mudancas: dict = {
        c: int(round(getattr(p, c) * f.escala))
        for c in ("alvo_pontos", "stop_pontos", "trailing_pontos")
    }
    for c in ("entrada_inicio", "entrada_fim", "fechamento",
              "sem_entrada1", "sem_entrada2", "sem_entrada3"):
        v = getattr(p, c)
        if v:
            mudancas[c] = hora_para_motor(v, f)
    return replace(p, **mudancas)


def params_para_motor(params: dict, schema: dict, f: Ficha | None) -> dict:
    if _identidade(f):
        return params
    out = dict(params)
    for k, v in params.items():
        if (schema.get(k) or {}).get("unidade") == "pontos":
            out[k] = int(round(v * f.escala))
    return out


def trades_para_exibir(trades: dict, f: Ficha | None) -> dict:
    if _identidade(f):
        return trades
    out = dict(trades)
    desl = np.timedelta64(f.deslocamento_min, "m")
    for k in ("entry_ts", "exit_ts"):
        if k in out:
            out[k] = out[k] - desl
    for k in ("entry_px", "exit_px", "points", "mae", "mfe"):
        if k in out:
            out[k] = np.asarray(out[k], dtype=float) / f.escala
    return out


def pontos_para_exibir(v, f: Ficha | None):
    if _identidade(f) or f.escala == 1:
        return v
    return v / f.escala


def hora_do_pregao_para_exibir(h: int, f: Ficha | None) -> int:
    if f is None:
        return h
    return (h - f.deslocamento_min // 60) % 24


def perfil_padrao(f: Ficha) -> dict | None:
    return f.perfil_padrao
