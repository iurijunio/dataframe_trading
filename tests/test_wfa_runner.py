"""Testes da varredura em memória que alimenta o walk-forward.

Não roda backtest: o pool de processos é trocado por um executor falso que
devolve trades sintéticos. O que se testa é o CONTRATO com a tela — quando o
cache pode ser entregue como pronto, e quando não pode.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import wfa_runner as R  # noqa: E402


def _trades(n=200):
    ts = np.datetime64("2022-01-03T10:00", "s") + np.arange(n) * np.timedelta64(1, "D")
    return {"entry_ts": ts, "exit_ts": ts + np.timedelta64(1, "h"),
            "liquido": np.full(n, 10.0), "custo": np.full(n, 1.0)}


class _Pool:
    """Executor falso: mesmo contrato do ProcessPoolExecutor que a varredura usa."""
    atraso = 0.0

    def __init__(self, *a, **k):
        pass

    def map(self, fn, tarefas, chunksize=1):
        for t in tarefas:
            if self.atraso:
                time.sleep(self.atraso)
            yield {"trial_id": t[0], "params": {**t[1], **t[2]}, "erro": None, **_trades()}

    def shutdown(self, **k):
        pass


@pytest.fixture
def varredura(monkeypatch):
    monkeypatch.setattr(R, "ProcessPoolExecutor", _Pool)
    _Pool.atraso = 0.0
    return R.Varredura()


def _iniciar(v, n_valores=10):
    return v.iniciar(symbol="X", estrategia_nome="rompimento_canal",
                     espaco={"p": list(range(n_valores))}, perfil_base={},
                     de="2022-01-01", ate="2023-01-01",
                     campos_execucao_nomes=set(), run_id=1, workers=1)


def _esperar(v, limite=10):
    t = time.time()
    while v.estado["rodando"] and time.time() - t < limite:
        time.sleep(0.02)


def test_varredura_completa_fica_pronta(varredura):
    assert _iniciar(varredura)
    _esperar(varredura)
    e = varredura.estado
    assert e["pronto"] and e["uteis"] == 10 and not e["erro"]
    assert len(varredura.cache) == 10


def test_acima_do_teto_aborta_e_nao_entrega_cache(varredura, monkeypatch):
    """O teto era só um aviso: a barra dizia erro e a matriz rodava assim mesmo."""
    monkeypatch.setattr(R, "TETO_MB", 0.02)            # ~3 combinações de 200 trades
    _iniciar(varredura, n_valores=50)
    _esperar(varredura)
    e = varredura.estado
    assert not e["pronto"] and e["erro"] == "acima do teto"
    assert varredura.cache == [] and e["feitos"] < 50


def test_interrompida_nao_e_entregue_como_completa(varredura):
    """parar() no meio entregava 32 de 164 como se fossem todas."""
    _Pool.atraso = 0.02
    _iniciar(varredura, n_valores=200)
    time.sleep(0.2)
    varredura.parar()
    _esperar(varredura)
    e = varredura.estado
    assert not e["pronto"] and e["erro"] == "interrompida"
    assert "interrompida" in e["mensagem"] and varredura.cache == []


def test_duas_chamadas_simultaneas_abrem_uma_varredura_so(varredura):
    _Pool.atraso = 0.01
    resultados = []
    threads = [threading.Thread(target=lambda: resultados.append(_iniciar(varredura, 30)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert resultados.count(True) == 1
    _esperar(varredura)
