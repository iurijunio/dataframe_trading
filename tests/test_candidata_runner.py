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

    def __init__(self, cache, run_id=None, pronto=False, rodando=False):
        self.estado = {"pronto": pronto, "rodando": rodando, "run_id": run_id,
                       "erro": None}
        self._cache = cache
        self.chamadas_iniciar: list[dict] = []
        self.parar_chamado = False

    @property
    def cache(self):
        return self._cache

    def iniciar(self, **kwargs):
        self.chamadas_iniciar.append(kwargs)
        self.estado.update(rodando=False, pronto=True, run_id=kwargs["run_id"],
                           erro=None)
        return True

    def parar(self):
        self.parar_chamado = True
        self.estado["rodando"] = False


class FakeVarreduraRecusaIniciar(FakeVarredura):
    """Simula uma corrida rara: `iniciar()` devolve `False` sem que
    `estado["rodando"]` estivesse `True` no instante em que o executor
    conferiu — o motivo exato não importa, só que o retorno falso não pode
    ser ignorado (IMPORTANTE 2 da rodada de correção 1)."""

    def iniciar(self, **kwargs):
        self.chamadas_iniciar.append(kwargs)
        return False


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


class FakeVarreduraProgresso(FakeVarredura):
    """Avança `feitos`/`total` de verdade ao longo de uma corrida curta, para
    provar que `_garantir_varredura` acompanha o progresso dela em `pct`."""

    def __init__(self, passos=10, intervalo=0.03):
        super().__init__(cache=_cache())
        self._passos = passos
        self._intervalo = intervalo

    def iniciar(self, **kwargs):
        self.chamadas_iniciar.append(kwargs)
        self.estado.update(rodando=True, pronto=False, run_id=kwargs["run_id"],
                           feitos=0, total=self._passos)

        def avancar():
            for i in range(1, self._passos + 1):
                time.sleep(self._intervalo)
                self.estado["feitos"] = i
            self.estado.update(rodando=False, pronto=True)
        threading.Thread(target=avancar, daemon=True).start()
        return True


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


def test_erro_e_publicado_sem_derrubar_a_thread(monkeypatch):
    """Uma falha ANTES de haver cache (aqui, `argumentos_da_mineracao`
    quebrada) não tem como virar portão pendente — nenhuma das três fases
    tem o que medir. Diferente de uma fase falhar DEPOIS do cache pronto
    (`test_erro_no_sorteio_nao_apaga_os_portoes_ja_calculados`, abaixo),
    onde as outras fases seguem e o resultado fica parcial."""
    def argumentos_quebrado(run_id, ativo=None):
        raise RuntimeError("mineração corrompida")
    monkeypatch.setattr(CR.wfa_runner, "argumentos_da_mineracao", argumentos_quebrado)

    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t = _executor(v)
    t.iniciar(7)
    _esperar(t)

    e = t.estado
    assert not e["rodando"]
    assert e["erro"] and "mineração corrompida" in e["erro"]
    assert e["resultado"] is None

    # a thread não travou o objeto: uma nova rodada continua funcionando
    monkeypatch.setattr(CR.wfa_runner, "argumentos_da_mineracao", _argumentos_fake)
    assert t.iniciar(7)
    _esperar(t)
    assert not t.estado["erro"]
    assert t.estado["resultado"] is not None


def test_erro_no_sorteio_nao_apaga_os_portoes_ja_calculados():
    """MENOR (c): o motor levantando exceção na fase de sorteio não pode
    apagar o que as fases de tentativas e de parâmetros fixos já mediram —
    só o portão do sorteio fica pendente, com o motivo."""
    def montar_rodador_quebrado(bars, mod, perfil, inst, trades_reais):
        raise RuntimeError("motor explodiu no sorteio")

    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t = CR.TestesCompletos(varredura=v, montar_rodador=montar_rodador_quebrado,
                           spa_teste=_spa_fake, calcular_percentil=_percentil_fake)
    t.iniciar(7)
    _esperar(t)

    e = t.estado
    assert not e["rodando"]
    assert e["erro"] is None       # não é uma falha do executor, é uma fase pendente
    r = e["resultado"]
    assert r is not None
    por_nome = {p["nome"]: p for p in r["portoes"]}

    tentativas = por_nome["Aguenta o desconto por muitas tentativas?"]
    fixas = por_nome["Reotimizar compensou?"]
    aleatorio_ = por_nome["Ganha de entradas sorteadas ao acaso?"]

    assert tentativas["ok"] is True and tentativas["valor"] == pytest.approx(0.02)
    assert fixas["ok"] is True and fixas["valor"] == pytest.approx(70.0)
    assert aleatorio_["ok"] is None
    assert "não rodou" in aleatorio_["valor"] and "motor explodiu" in aleatorio_["valor"]
    assert r["leituras"]["p_aleatorio"] is None
    assert r["leituras"]["calibracao_ok"] is None


def test_erro_nas_fixas_nao_apaga_tentativas_nem_aleatorio():
    """A mesma isolação, agora quebrando só o cálculo do percentil das
    combinações fixas."""
    def percentil_quebrado(cache, janelas, capital, lucro_real):
        raise RuntimeError("faixa explodiu")

    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)
    t = CR.TestesCompletos(varredura=v, montar_rodador=_montar_rodador_fake,
                           spa_teste=_spa_fake, calcular_percentil=percentil_quebrado)
    t.iniciar(7)
    _esperar(t)

    r = t.estado["resultado"]
    assert r is not None
    por_nome = {p["nome"]: p for p in r["portoes"]}
    # o valor exato do portão aleatório depende da matemática da fake de
    # sorteio (não é o que este teste prova) — só importa que ele RODOU
    assert por_nome["Ganha de entradas sorteadas ao acaso?"]["ok"] is not None
    assert por_nome["Aguenta o desconto por muitas tentativas?"]["ok"] is True
    fixas = por_nome["Reotimizar compensou?"]
    assert fixas["ok"] is None and "não rodou" in fixas["valor"]
    assert r["leituras"]["percentil_fixas"] is None


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


# -------------------------------------------- IMPORTANTE 1 (rodada de correção 1)
def test_parar_nao_derruba_varredura_iniciada_pela_aba():
    """A varredura já está rodando (a aba Walk-Forward a começou), com o
    MESMO run_id que o executor precisa — ele só espera, sem chamar
    `iniciar()`. `parar()` no executor não pode derrubar uma varredura que
    ele não começou."""
    v = FakeVarredura(cache=[], run_id=99, pronto=False, rodando=True)
    t = _executor(v)
    assert t.iniciar(7)
    time.sleep(0.1)
    t.parar()
    _esperar(t, limite=3)

    assert not v.parar_chamado
    assert v.estado["rodando"] is True     # a varredura da aba segue viva
    assert t.estado["rodando"] is False
    assert t.estado["resultado"] is None
    assert v.chamadas_iniciar == []        # nunca tentamos iniciar por cima


# -------------------------------------------- IMPORTANTE 2 (rodada de correção 1)
def test_varredura_rodando_com_outra_mineracao_recusa_na_hora():
    v = FakeVarredura(cache=[], run_id=123, pronto=False, rodando=True)
    t = _executor(v)
    t.iniciar(7)
    _esperar(t, limite=3)

    e = t.estado
    assert not e["rodando"]
    assert e["erro"] and "outra mineração" in e["erro"]
    assert e["resultado"] is None
    assert v.chamadas_iniciar == []        # recusou na hora, sem esperar nada


def test_iniciar_falso_por_outro_motivo_recusa_com_mensagem_clara():
    v = FakeVarreduraRecusaIniciar(cache=[], run_id=None, pronto=False)
    t = _executor(v)
    t.iniciar(7)
    _esperar(t, limite=3)

    e = t.estado
    assert not e["rodando"]
    assert e["erro"] and "não foi possível iniciar a varredura" in e["erro"]
    assert e["resultado"] is None
    assert len(v.chamadas_iniciar) == 1


# -------------------------------------------- MENOR (a): varredura_substituida
def test_varredura_substituida_registra_o_run_id_antigo():
    v = FakeVarredura(cache=_cache(), run_id=42, pronto=True)   # outra mineração
    t = _executor(v)
    t.iniciar(7)
    _esperar(t)
    assert t.estado["varredura_substituida"] == 42


def test_varredura_substituida_fica_none_quando_reusa_o_cache():
    v = FakeVarredura(cache=_cache(), run_id=99, pronto=True)   # já é a nossa
    t = _executor(v)
    t.iniciar(7)
    _esperar(t)
    assert t.estado["varredura_substituida"] is None


def test_varredura_substituida_fica_none_quando_nao_havia_nenhuma_antes():
    v = FakeVarredura(cache=[], run_id=None, pronto=False)      # nunca rodou
    t = _executor(v)
    t.iniciar(7)
    _esperar(t)
    assert t.estado["varredura_substituida"] is None
    assert len(v.chamadas_iniciar) == 1


# -------------------------------------------- MENOR (b): pct da varredura
def test_pct_acompanha_o_progresso_da_varredura_entre_0_e_40():
    # o executor só reconfere feitos/total a cada 0,5s (ver `_garantir_varredura`);
    # a varredura falsa precisa durar mais que isso para o teste enxergar
    # mais de uma leitura de progresso
    v = FakeVarreduraProgresso(passos=6, intervalo=0.3)
    t = _executor(v)
    t.iniciar(7)

    vistos = set()
    while t.estado["rodando"]:
        if t.estado["fase"] == "refazendo a varredura":
            vistos.add(t.estado["pct"])
        time.sleep(0.05)

    assert all(0 <= p <= 40 for p in vistos)
    assert len(vistos) > 1                 # realmente avançou, não ficou parado


# -------------------------------------------- MENOR (d): eixo de dias da matriz
def test_matriz_de_tentativas_tem_uma_coluna_por_combinacao_mais_o_wfa():
    matriz = CR._matriz_tentativas(_cache(), _trades_wfa(), PASSOS, CAPITAL)
    assert matriz is not None
    assert matriz.shape[1] == len(_cache()) + 1    # +1 da curva do WFA


def test_matriz_de_tentativas_recusa_coluna_do_cache_com_eixo_diferente(monkeypatch):
    """Prova a proteção: se uma coluna do CACHE sair com um número de dias
    diferente das outras (só aconteceria com um bug em `por_pregao`/`de`-`ate`
    divergindo entre chamadas), `_matriz_tentativas` recusa com um erro
    claro em vez de deixar `spa.teste` comparar colunas desalinhadas."""
    real = CR.candidata.por_pregao
    chamadas = {"n": 0}

    def por_pregao_bugado(exit_ts, liquido, de=None, ate=None):
        dias, pnl = real(exit_ts, liquido, de, ate)
        chamadas["n"] += 1
        if chamadas["n"] == 2:             # a segunda coluna do cache
            return dias[:-1], pnl[:-1]     # um dia a menos, de propósito
        return dias, pnl

    monkeypatch.setattr(CR.candidata, "por_pregao", por_pregao_bugado)
    with pytest.raises(ValueError, match="tamanhos diferentes"):
        CR._matriz_tentativas(_cache(), _trades_wfa(), PASSOS, CAPITAL)


def test_matriz_de_tentativas_recusa_curva_do_wfa_com_eixo_diferente(monkeypatch):
    """A mesma proteção, agora na última coluna (a curva do walk-forward),
    que é montada separado do laço do cache."""
    real = CR.candidata.por_pregao
    chamadas = {"n": 0}

    def por_pregao_bugado(exit_ts, liquido, de=None, ate=None):
        dias, pnl = real(exit_ts, liquido, de, ate)
        chamadas["n"] += 1
        if chamadas["n"] == len(_cache()) + 1:      # a coluna do WFA
            return dias[:-1], pnl[:-1]
        return dias, pnl

    monkeypatch.setattr(CR.candidata, "por_pregao", por_pregao_bugado)
    with pytest.raises(ValueError, match="eixo de dias diferente do cache"):
        CR._matriz_tentativas(_cache(), _trades_wfa(), PASSOS, CAPITAL)


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
