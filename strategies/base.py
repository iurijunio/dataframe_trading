"""Camada 2 - o contrato de uma estrategia.

Uma estrategia devolve APENAS sinais. Ela nao sabe o que e custo, horario,
sessao, contrato, stop, alvo ou tamanho de posicao - nada disso e decisao
dela. Quem executa e o kernel.

Isso nao e purismo: e o que garante que a trava de look-ahead, o
encerramento no horario e a contabilidade de custo valham para TODA
estrategia, inclusive as que voce escrever com pressa daqui a seis meses.

`params_schema` descreve cada parametro com default, minimo, maximo e passo -
os mesmos quatro campos que a tela de otimizacao do MT5 pede, e o que a
mineracao vai usar para montar o espaco de busca.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass
class Signals:
    """Arrays booleanos alinhados as barras do TIMEFRAME da estrategia.

    sl_points / tp_points existem para o caso de a estrategia querer um stop
    proprio, dependente do sinal. Deixados em 0, valem o stop e o alvo do
    perfil de execucao - que e o caso normal.
    """

    entry_long: np.ndarray
    entry_short: np.ndarray
    exit_long: np.ndarray
    exit_short: np.ndarray
    sl_points: int | np.ndarray = 0
    tp_points: int | np.ndarray = 0

    def __post_init__(self):
        n = len(self.entry_long)
        for nome in ("entry_short", "exit_long", "exit_short"):
            if len(getattr(self, nome)) != n:
                raise ValueError(f"Signals.{nome} tem tamanho diferente de entry_long.")


def empty_like(n: int) -> dict[str, np.ndarray]:
    return {k: np.zeros(n, dtype=np.bool_)
            for k in ("entry_long", "entry_short", "exit_long", "exit_short")}


@runtime_checkable
class Strategy(Protocol):
    name: str
    params_schema: dict

    def signals(self, bars: dict, params: dict) -> Signals:
        ...


def defaults(schema: dict) -> dict:
    return {k: v["default"] for k, v in schema.items()}


def validate(schema: dict, params: dict) -> dict:
    """Preenche defaults e recusa parametro fora dos limites declarados."""
    out = defaults(schema)
    for k, v in params.items():
        if v is None:
            continue
        if k not in schema:
            raise ValueError(f"parametro desconhecido: {k!r}. Conhecidos: {list(schema)}")
        lo, hi = schema[k].get("min"), schema[k].get("max")
        if lo is not None and v < lo:
            raise ValueError(f"{schema[k].get('label', k)} = {v} abaixo do mínimo {lo}.")
        if hi is not None and v > hi:
            raise ValueError(f"{schema[k].get('label', k)} = {v} acima do máximo {hi}.")
        out[k] = v
    return out


def grid(schema: dict, ranges: dict) -> dict[str, list]:
    """Espaco de busca da mineracao.

    `ranges` traz, por parametro, {'on': bool, 'de':, 'passo':, 'ate':}.
    Parametro desligado vira uma lista de um valor so - o valor atual.
    """
    espaco = {}
    for nome, meta in schema.items():
        r = ranges.get(nome) or {}
        if not r.get("on"):
            espaco[nome] = [r.get("valor", meta["default"])]
            continue
        de = r.get("de", meta.get("min", meta["default"]))
        ate = r.get("ate", meta.get("max", meta["default"]))
        passo = max(r.get("passo") or meta.get("step", 1), 1e-9)
        n = int((ate - de) / passo) + 1
        valores = [de + i * passo for i in range(max(n, 1))]
        if meta.get("tipo", "int") == "int":
            valores = sorted({int(round(v)) for v in valores})
        espaco[nome] = valores
    return espaco
