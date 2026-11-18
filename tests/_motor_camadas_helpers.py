"""Cases and hashing for the layered-engine golden file (`tests/dados/motor_camadas.json`).

The golden file was recorded with the old engine and is never re-recorded:
re-recording with the new code would turn the proof into a mirror.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

ARQUIVO = Path(__file__).resolve().parent / "dados" / "motor_camadas.json"
PERIODO = ("2024-01-01", "2024-06-30")

# (nome, campos do perfil). Pontos na escala do WIN; no MES a escala muda e
# os casos de pontos usam os valores da ficha (8/16).
PERFIS_WIN = [
    ("padrao", {}),
    ("stop_atr_alvo_mult", {"stop_tipo": "atr", "stop_atr_periodo": 14,
                            "stop_atr_mult": 1.5, "alvo_tipo": "multiplicador",
                            "alvo_razao": 2.0}),
    ("stop_pct_alvo_pct", {"stop_tipo": "percentual", "stop_pct": 0.2,
                           "alvo_tipo": "percentual", "alvo_pct": 0.4}),
    ("alvo_atr", {"alvo_tipo": "atr", "alvo_atr_periodo": 20,
                  "alvo_atr_mult": 2.5}),
    ("janela_dias", {"entrada_inicio": "10:00", "entrada_fim": "11:30",
                     "dias_semana": (2, 4)}),
    ("compra", {"direcao": "compra"}),
    ("venda", {"direcao": "venda"}),
    ("adx_tendencia", {"filtro_adx": "tendencia", "adx_periodo": 14,
                       "adx_limiar": 20, "adx_filtro_di": 1, "adx_subindo": 1}),
    ("adx_rango", {"filtro_adx": "rango", "adx_periodo": 14, "adx_limiar": 25}),
    ("sem_entrada", {"sem_entrada1": "12:00", "sem_entrada2": "15:00"}),
    ("limites", {"limite_ganho_contrato": 150.0, "limite_perda_contrato": 100.0,
                 "max_trades_dia": 3, "max_prejuizos_dia": 2}),
    ("protecoes", {"breakeven_pct": 40.0, "step_gatilho_pct": 60.0,
                   "step_distancia_pct": 30.0, "trailing_pontos": 150,
                   "max_barras": 60}),
    ("tf_m1", {"timeframe": "M1"}),
    ("tf_m5", {"timeframe": "M5"}),
    ("tf_m15", {"timeframe": "M15", "stop_tipo": "atr", "stop_atr_mult": 1.0}),
]
BASE_WIN = {"timeframe": "M5", "corretagem_por_contrato": 0.5,
            "emolumentos_por_contrato": 0.25}

PERFIS_MES = [
    ("padrao", {}),
    ("stop_atr_alvo_mult", {"stop_tipo": "atr", "stop_atr_mult": 1.5,
                            "alvo_tipo": "multiplicador", "alvo_razao": 2.0}),
    ("stop_pct", {"stop_tipo": "percentual", "stop_pct": 0.1}),
    ("janela_dias", {"entrada_inicio": "10:00", "entrada_fim": "12:00",
                     "dias_semana": (1, 3, 5)}),
    ("compra", {"direcao": "compra"}),
]
BASE_MES = {"timeframe": "M5", "entrada_inicio": "09:30", "entrada_fim": "15:30",
            "fechamento": "15:55", "stop_pontos": 8, "alvo_pontos": 16,
            "corretagem_por_contrato": 0.6}

CAMPOS = ("entry_i", "exit_i", "side", "entry_px", "exit_px", "reason", "points")


def assinatura(res) -> str:
    """Hash of the trades: changes if any entry, exit, side, price, reason
    or result changes."""
    h = hashlib.sha256()
    h.update(str(int(res.n_trades)).encode())
    for c in CAMPOS:
        h.update(c.encode())
        h.update(np.ascontiguousarray(res.trades[c]).astype(np.int64).tobytes())
    return h.hexdigest()


def _barras(simbolo: str) -> dict:
    from core import db_manager
    d = db_manager.read_bars_parquet(simbolo, *PERIODO)
    return {
        "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
        **{c: np.ascontiguousarray(d[c], dtype=np.int64)
           for c in ("open", "high", "low", "close", "tick_volume", "volume")},
    }


def casos():
    """(key, bars, module, params, profile, instrument, open_candle).

    Besides the profile grid: "flip the position" (`saida` = 2) where the strategy
    has the option, and the live paper's open candle (`vela_aberta=True`)."""
    from core import db_manager
    from core.engine.execution import ExecutionProfile
    from strategies import registry
    from strategies.base import defaults

    for simbolo, base, perfis in (("WIN$N", BASE_WIN, PERFIS_WIN),
                                  ("MES", BASE_MES, PERFIS_MES)):
        bars = _barras(simbolo)
        inst = db_manager.load_instrument_yaml(simbolo)
        for e in registry.descobrir():
            mod = registry.carregar(e["modulo"])
            params = defaults(mod.params_schema)
            for nome, campos in perfis:
                perfil = ExecutionProfile(**{**base, **campos})
                yield (f"{simbolo}|{e['modulo']}|{nome}", bars, mod, params,
                       perfil, inst, False)
            padrao = ExecutionProfile(**base)
            if "saida" in mod.params_schema:
                yield (f"{simbolo}|{e['modulo']}|virar", bars, mod,
                       {**params, "saida": 2}, padrao, inst, False)
            yield (f"{simbolo}|{e['modulo']}|vela_aberta", bars, mod, params,
                   padrao, inst, True)
