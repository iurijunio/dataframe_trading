"""Casos da equivalência da opção de saída (`strategies/saida.py`).

A impressão de cada caso foi gravada em `tests/dados/saida_antes.json` com o
código de ANTES da opção existir. Com a saída no padrão de cada estratégia,
os trades têm de sair idênticos — barra a barra, preço a preço. Mudar este
arquivo invalida a gravação: as barras e os casos são o contrato.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from core.engine.execution import ExecutionProfile, run_strategy

WIN = {"tick_size": 5, "point_value": 0.20, "symbol": "TEST"}
ANTES = Path(__file__).resolve().parent / "dados" / "saida_antes.json"


def barras(dias: int = 12, semente: int = 7) -> dict:
    """Passeio aleatório em ticks de 5, 09:00–18:00, só dias úteis."""
    rng = np.random.default_rng(semente)
    ts, o, h, l, c = [], [], [], [], []
    preco = 120_000
    d = np.datetime64("2024-03-04")
    feitos = 0
    while feitos < dias:
        dow = (d.astype("datetime64[D]").astype(np.int64) + 3) % 7
        if dow < 5:
            base = d.astype("datetime64[m]") + np.timedelta64(9 * 60, "m")
            for m in range(9 * 60 + 1):
                abre = preco
                fecha = abre + int(round(rng.normal(0, 6))) * 5
                sobe = int(abs(rng.normal(0, 3))) * 5
                desce = int(abs(rng.normal(0, 3))) * 5
                ts.append(base + np.timedelta64(m, "m"))
                o.append(abre)
                h.append(max(abre, fecha) + sobe)
                l.append(min(abre, fecha) - desce)
                c.append(fecha)
                preco = fecha
            feitos += 1
        d = d + np.timedelta64(1, "D")
    n = len(ts)
    return {
        "ts": np.array(ts, dtype="datetime64[ns]"),
        "open": np.asarray(o, dtype=np.int64),
        "high": np.asarray(h, dtype=np.int64),
        "low": np.asarray(l, dtype=np.int64),
        "close": np.asarray(c, dtype=np.int64),
        "tick_volume": np.ones(n, dtype=np.int64),
        "volume": np.ones(n, dtype=np.int64),
    }


PARAMS = {
    "setup_cruzamento": [
        {"media_rapida": 9, "media_lenta": 21},
        {"media_rapida": 5, "media_lenta": 50},
        {"media_rapida": 20, "media_lenta": 60},
    ],
    "rompimento_canal": [
        {"periodo_canal": 20, "folga_ticks": 1, "filtro_amplitude": 0},
        {"periodo_canal": 10, "folga_ticks": 0, "filtro_amplitude": 100},
        {"periodo_canal": 40, "folga_ticks": 3, "filtro_amplitude": 0},
    ],
    "reversao_rsi": [
        {"periodo_rsi": 2, "limite_extremo": 10, "periodo_tendencia": 200,
         "periodo_saida": 5},
        {"periodo_rsi": 3, "limite_extremo": 15, "periodo_tendencia": 0,
         "periodo_saida": 5},
        {"periodo_rsi": 2, "limite_extremo": 20, "periodo_tendencia": 50,
         "periodo_saida": 10},
    ],
    "rompimento_abertura": [
        {"barras_abertura": 6, "folga_ticks": 1, "filtro_amplitude": 0},
        {"barras_abertura": 15, "folga_ticks": 0, "filtro_amplitude": 100},
        {"barras_abertura": 3, "folga_ticks": 2, "filtro_amplitude": 0},
    ],
    "rompimento_ema_abertura": [
        {"ema_curta": 9, "ema_longa": 21, "distancia_abertura": 0},
        {"ema_curta": 5, "ema_longa": 30, "distancia_abertura": 100},
        {"ema_curta": 12, "ema_longa": 50, "distancia_abertura": 0},
    ],
}

PERFIS = {
    "m1_pontos": dict(timeframe="M1", entrada_inicio="09:00",
                      entrada_fim="17:00", fechamento="17:30",
                      stop_pontos=200, alvo_pontos=400, slippage_ticks=1),
    "m5_atr_limites": dict(timeframe="M5", entrada_inicio="09:15",
                           entrada_fim="16:30", fechamento="17:00",
                           stop_tipo="atr", stop_atr_periodo=14,
                           stop_atr_mult=1.5, alvo_tipo="multiplicador",
                           alvo_razao=2.0, max_trades_dia=4,
                           max_prejuizos_dia=2, sem_entrada1="13:00",
                           slippage_ticks=1),
    "m7_compra_protecoes": dict(timeframe="M7", entrada_inicio="09:00",
                                entrada_fim="17:00", fechamento="17:40",
                                direcao="compra", stop_pontos=300,
                                alvo_pontos=600, breakeven_pct=50,
                                trailing_pontos=200, max_barras=60,
                                adx_periodo=14, adx_limiar=20,
                                slippage_ticks=0),
    "m15_sem_stop": dict(timeframe="M15", entrada_inicio="09:00",
                         entrada_fim="17:30", fechamento="17:50",
                         stop_pontos=0, alvo_pontos=0,
                         limite_perda_contrato=100.0, slippage_ticks=1),
}


def casos():
    for estrategia, lista in PARAMS.items():
        for k, params in enumerate(lista):
            for perfil in PERFIS:
                yield f"{estrategia}#{k}@{perfil}", estrategia, params, perfil


def rodar(bars, estrategia: str, params: dict, perfil: str):
    from strategies import registry
    mod = registry.carregar(estrategia)
    return run_strategy(bars, mod, dict(params),
                        ExecutionProfile(**PERFIS[perfil]), WIN)


def impressao(res) -> dict:
    t = res.trades
    colunas = ("entry_i", "exit_i", "side", "entry_px", "exit_px", "reason",
               "points", "mae", "mfe", "stop_fim", "alvo_fim")
    linhas = [[int(t[c][i]) for c in colunas] for i in range(res.n_trades)]
    bruto = json.dumps(linhas, separators=(",", ":")).encode()
    return {"n": int(res.n_trades),
            "pontos": int(t["points"].sum()) if res.n_trades else 0,
            "sinal": int((t["reason"] == 2).sum()) if res.n_trades else 0,
            "sha": hashlib.sha256(bruto).hexdigest()}
