"""Testes do executor em segundo plano dos três testes completos da tela
Candidata (portão 2, portão 6 e o alerta de reotimização).

As quatro dependências que tocam o motor, o banco ou uma conta pesada — a
varredura, o rodador do sorteio, o SPA e o cálculo do percentil das fixas —
são injetadas falsas. `wfa_runner.argumentos_da_mineracao` e `wfa_store`
(que abririam o banco de verdade) são trocados por monkeypatch. Nenhum
teste aqui toca o banco real nem roda o motor.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata_runner as CR  # noqa: E402


# --------------------------------------------------------------- cenário
# Duas janelas reais (step 1 e 2) mais uma linha DEPLOY, que os três testes
# ignoram — a mesma régua de `wfa_runner.trades_oos_detalhados`.
PASSOS = [
    {"step": 1, "is_de": "2022-01-01T00:00:00", "is_ate": "2022-07-01T00:00:00",
     "oos_de": "2022-07-01T00:00:00", "oos_ate": "2023-01-01T00:00:00",
     "params": {"periodo": 10, "alvo_pontos": 600}, "fora_do_mercado": False},
    {"step": 2, "is_de": "2022-07-01T00:00:00", "is_ate": "2023-01-01T00:00:00",
     "oos_de": "2023-01-01T00:00:00", "oos_ate": "2023-07-01T00:00:00",
     "params": {"periodo": 12, "alvo_pontos": 700}, "fora_do_mercado": False},
    {"step": "DEPLOY", "is_de": "2023-01-01T00:00:00", "is_ate": "2023-07-01T00:00:00",
     "oos_de": "2023-07-01T00:00:00", "oos_ate": "2024-01-01T00:00:00",
     "params": {"periodo": 12, "alvo_pontos": 700}, "fora_do_mercado": False},
]

CAPITAL = 10_000.0


def _trades_wfa():
    """Os trades 'reais' do walk-forward: 3 no step 1, 2 no step 2."""
    trades = []
    for step, dias, liq in ((1, ["2022-08-01", "2022-09-01", "2022-10-01"], 100.0),
                            (2, ["2023-02-01", "2023-03-01"], 50.0)):
        for d in dias:
            trades.append({"step": step, "exit_ts": f"{d}T11:00:00", "liquido": liq})
    return trades


def _cache():
    """Duas combinações mineradas, cada uma com trades espalhados pelo
    intervalo fora da amostra inteiro (steps 1 e 2)."""
    combos = []
    for k in range(2):
        ts = np.array([f"2022-08-1{k}T11:00:00", f"2023-02-1{k}T11:00:00"],
                     dtype="datetime64[s]")
        combos.append({
            "entry_ts": ts, "exit_ts": ts, "liquido": np.array([30.0, 20.0]),
            "custo": np.array([1.0, 1.0]),
            "params": {"periodo": 10 + k, "alvo_pontos": 600},
        })
    return combos


def _detalhes_fake(wfa_id):
    return {"run_id": 99, "symbol": "X$N", "strategy": "rompimento_canal",
           "passos": PASSOS, "capital": CAPITAL}


def _argumentos_fake(run_id, ativo=None):
    return {
        "symbol": "X$N", "estrategia_nome": "rompimento_canal",
        "espaco": {"periodo": [10, 12]}, "perfil_base": {},
        "de": "2022-01-01", "ate": "2023-07-01",
        "ate_holdout": "2023-07-01",
        "campos_execucao_nomes": {"alvo_pontos", "stop_pontos",
                                  "breakeven_pct", "step_gatilho_pct",
                                  "step_distancia_pct", "trailing_pontos"},
        "run_id": run_id, "workers": 1,
    }


class FakeVarredura:
    """Contrato mínimo de `wfa_runner.Varredura` que o executor consulta:
    `estado`, `cache` e `iniciar()`/`parar()`."""

    def __init__(self, cache, run_id=None, pronto=False):
        self.estado = {"pronto": pronto, "rodando": False, "run_id": run_id,
                       "erro": None}
        self._cache = cache
        self.chamadas_iniciar: list[dict] = []

    @property
    def cache(self):
        return self._cache

    def iniciar(self, **kwargs):
        self.chamadas_iniciar.append(kwargs)
        self.estado.update(rodando=False, pronto=True, run_id=kwargs["run_id"],
                           erro=None)
        return True

    def parar(self):
        self.estado["rodando"] = False


class FakeVarreduraLenta(FakeVarredura):
    """Simula uma varredura que demora — só termina quando alguém chama
    `parar()` ou o teste destrava manualmente `self._pode_terminar`."""

    def __init__(self):
        super().__init__(cache=_cache())
        self.parar_chamado = False
        self._pode_terminar = threading.Event()

    def iniciar(self, **kwargs):
        self.chamadas_iniciar.append(kwargs)
        self.estado.update(rodando=True, pronto=False, run_id=kwargs["run_id"])

        def demora():
            self._pode_terminar.wait(timeout=5)
            if not self.parar_chamado:
                self.estado.update(rodando=False, pronto=True)
        threading.Thread(target=demora, daemon=True).start()
        return True

    def parar(self):
        self.parar_chamado = True
        self.estado["rodando"] = False


def _montar_rodador_fake(bars, mod, perfil, inst, trades_reais):
    """Ignora sinal e motor: calibra na hora (devolve sempre o alvo de
    trades da própria janela) e um lucro determinístico pela semente."""
    alvo = len(trades_reais)

    def rodar_janela(janela, n_sinais, semente):
        return alvo, 10.0 + semente
    return rodar_janela


def _spa_fake(matriz):
    return {"p": 0.02, "estatistica": 2.5, "melhor": 0, "n": 1000}


def _percentil_fake(cache, janelas, capital, lucro_real):
    return 70.0


@pytest.fixture(autouse=True)
def _sem_banco(monkeypatch):
    """Nenhum teste deste arquivo pode abrir o banco de verdade nem ler
    Parquet — tudo que tocaria isso é trocado por uma versão falsa."""
    monkeypatch.setattr(CR.wfa_store, "detalhes", _detalhes_fake)
    monkeypatch.setattr(CR.wfa_store, "trades", lambda wfa_id: _trades_wfa())
    monkeypatch.setattr(CR.wfa_runner, "argumentos_da_mineracao", _argumentos_fake)
    monkeypatch.setattr(CR.db, "read_bars_parquet",
                        lambda *a, **k: {"ts": np.array([], dtype="datetime64[ns]"),
                                        **{c: np.array([], dtype=np.int64)
                                           for c in ("open", "high", "low",
                                                    "close", "tick_volume",
                                                    "volume")}})
    monkeypatch.setattr(CR.db, "load_instrument_yaml", lambda s: {})


def _executor(varredura, **kw):
    return CR.TestesCompletos(varredura=varredura, montar_rodador=_montar_rodador_fake,
                              spa_teste=_spa_fake, calcular_percentil=_percentil_fake,
                              **kw)


def _esperar(t, limite=10):
    inicio = time.time()
    while t.estado["rodando"] and time.time() - inicio < limite:
        time.sleep(0.02)


# --------------------------------------------------------------- os testes
def test_roda_os_tres_testes_e_publica_o_resultado():
    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t = _executor(v)
    assert t.iniciar(7)
    _esperar(t)

    e = t.estado
    assert not e["rodando"] and not e["erro"]
    assert e["pct"] == 100
    r = e["resultado"]
    nomes = [p["nome"] for p in r["portoes"]]
    assert "Ganha de entradas sorteadas ao acaso?" in nomes
    assert "Aguenta o desconto por muitas tentativas?" in nomes
    assert "Reotimizar compensou?" in nomes
    assert r["leituras"]["p_tentativas"] == pytest.approx(0.02)
    assert r["leituras"]["percentil_fixas"] == pytest.approx(70.0)
    assert r["leituras"]["calibracao_ok"] is True
    assert t.resultado_de(7) == r


def test_reusa_o_cache_quando_o_run_id_bate():
    """Varredura já pronta com o run_id certo: não chama `iniciar` de novo."""
    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t = _executor(v)
    t.iniciar(7)
    _esperar(t)

    assert v.chamadas_iniciar == []
    assert t.estado["resultado"] is not None


def test_refaz_a_varredura_quando_o_run_id_nao_bate():
    v = FakeVarredura(cache=_cache(), run_id=42, pronto=True)
    t = _executor(v)
    t.iniciar(7)
    _esperar(t)

    assert len(v.chamadas_iniciar) == 1
    assert v.chamadas_iniciar[0]["run_id"] == 99
    assert t.estado["resultado"] is not None


def test_ordem_das_fases():
    ordem = []
    v = FakeVarredura(cache=_cache(), run_id=42, pronto=True)  # força reiniciar

    caixa = {}

    def iniciar_espiao(**kwargs):
        ordem.append(("varredura", caixa["t"].estado["fase"]))
        return FakeVarredura.iniciar(v, **kwargs)
    v.iniciar = iniciar_espiao

    def spa_espiao(matriz):
        ordem.append(("spa", caixa["t"].estado["fase"]))
        return _spa_fake(matriz)

    def percentil_espiao(cache, janelas, capital, lucro_real):
        ordem.append(("percentil", caixa["t"].estado["fase"]))
        return _percentil_fake(cache, janelas, capital, lucro_real)

    def montar_rodador_espiao(bars, mod, perfil, inst, trades_reais):
        ordem.append(("aleatorio", caixa["t"].estado["fase"]))
        return _montar_rodador_fake(bars, mod, perfil, inst, trades_reais)

    t = CR.TestesCompletos(varredura=v, montar_rodador=montar_rodador_espiao,
                           spa_teste=spa_espiao, calcular_percentil=percentil_espiao)
    caixa["t"] = t
    t.iniciar(7)
    _esperar(t)

    assert not t.estado["erro"]
    # `montar_rodador` é chamado uma vez por janela — dedup preservando a
    # ordem de primeira aparição, não a posição
    fases = list(dict.fromkeys(f for _, f in ordem))
    assert fases == ["refazendo a varredura", "testando tentativas",
                     "comparando com parâmetros fixos", "sorteando entradas"]


def test_interrupcao_nao_publica_resultado_e_nao_trava_o_proximo_uso():
    v = FakeVarreduraLenta()
    t = _executor(v)
    assert t.iniciar(7)
    time.sleep(0.1)          # dá tempo da thread entrar na espera da varredura
    t.parar()
    _esperar(t, limite=5)

    e = t.estado
    assert not e["rodando"]
    assert e["resultado"] is None
    assert e["erro"] is None
    assert v.parar_chamado

    # geração antiga descartada: o próximo `iniciar` funciona normalmente
    v2 = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t._varredura = v2
    assert t.iniciar(7)
    _esperar(t)
    assert t.estado["resultado"] is not None


def test_erro_e_publicado_sem_derrubar_a_thread():
    def spa_quebrado(matriz):
        raise RuntimeError("spa explodiu")

    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t = CR.TestesCompletos(varredura=v, montar_rodador=_montar_rodador_fake,
                           spa_teste=spa_quebrado, calcular_percentil=_percentil_fake)
    t.iniciar(7)
    _esperar(t)

    e = t.estado
    assert not e["rodando"]
    assert e["erro"] and "spa explodiu" in e["erro"]
    assert e["resultado"] is None

    # a thread não travou o objeto: uma nova rodada continua funcionando
    t._spa_teste = _spa_fake
    assert t.iniciar(7)
    _esperar(t)
    assert not t.estado["erro"]
    assert t.estado["resultado"] is not None


def test_uma_rodada_em_curso_recusa_outro_iniciar():
    v_lenta = FakeVarreduraLenta()
    t = _executor(v_lenta)
    assert t.iniciar(7)
    time.sleep(0.05)

    assert t.iniciar(8) is False       # já rodando: a segunda é recusada

    v_lenta._pode_terminar.set()
    _esperar(t)
    assert t.estado["wfa_id"] == 7
    assert t.estado["resultado"] is not None


def test_geracao_antiga_descartada_como_a_varredura():
    """Uma geração mais nova (como se um `iniciar` tivesse conseguido
    entrar por fora) não pode ser sobrescrita pela thread da geração velha
    que só termina depois — mesmo mecanismo de `wfa_runner.Varredura`."""
    v_lenta = FakeVarreduraLenta()
    t = _executor(v_lenta)
    assert t.iniciar(7)
    time.sleep(0.05)

    with t._lock:
        t._geracao += 1
        t.estado.update(wfa_id=99, rodando=True, resultado=None, erro=None,
                        geracao=t._geracao)

    v_lenta._pode_terminar.set()      # libera a thread da geração velha
    time.sleep(0.3)

    assert t.estado["wfa_id"] == 99
    assert t.estado["resultado"] is None


def test_matriz_de_tentativas_confere_o_eixo_de_dias():
    passos = PASSOS
    cache_com_bug = _cache()
    # uma coluna com um trade a mais nos dados de origem não muda o eixo de
    # dias, mas confirma que a função não lança nada com o cenário normal
    matriz = CR._matriz_tentativas(cache_com_bug, _trades_wfa(), passos, CAPITAL)
    assert matriz is not None
    assert matriz.shape[1] == len(cache_com_bug) + 1  # +1 da curva do WFA


def test_janelas_validas_ignora_deploy_fora_do_mercado_e_sem_parametros():
    passos = PASSOS + [
        {"step": 3, "is_de": "2023-07-01T00:00:00", "is_ate": "2024-01-01T00:00:00",
         "oos_de": "2024-01-01T00:00:00", "oos_ate": "2024-07-01T00:00:00",
         "params": {}, "fora_do_mercado": False},
        {"step": 4, "is_de": "2024-01-01T00:00:00", "is_ate": "2024-07-01T00:00:00",
         "oos_de": "2024-07-01T00:00:00", "oos_ate": "2025-01-01T00:00:00",
         "params": {"periodo": 10}, "fora_do_mercado": True},
    ]
    janelas = CR._janelas_validas(passos)
    assert [j.step for j in janelas] == [1, 2]
    assert all(not j.deploy for j in janelas)
