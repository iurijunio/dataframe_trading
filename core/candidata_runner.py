"""O executor em segundo plano dos três testes demorados da tela Candidata.

O portão 2 ("ganha de entradas sorteadas ao acaso?"), o portão 6 ("aguenta o
desconto por muitas tentativas?") e o alerta "reotimizar compensou?" juntos
levam cerca de um minuto — tempo demais para caber num callback do Dash sem
travar a tela. Este módulo roda os três numa thread, publica o progresso em
`estado` (um dicionário sob lock, no mesmo desenho de `wfa_runner.Varredura`)
e guarda o resultado em memória por `wfa_id`. A tela que lê isto é a tarefa
seguinte — aqui só existe o executor.

As quatro dependências que tocam o motor, o banco ou uma conta pesada — a
varredura, o rodador do sorteio, o SPA e o contrafactual de parâmetros
fixos — são injetáveis no construtor, com o padrão de produção como default.
Os testes passam versões falsas e nunca abrem o banco real nem chamam o
motor de verdade.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import numpy as np

from . import aleatorio
from . import candidata
from . import db_manager as db
from . import spa as spa_mod
from . import wfa
from . import wfa_runner
from . import wfa_store
from .engine.execution import ExecutionProfile

N_SORTEIO_PADRAO = 1000


def _percentil_fixas_padrao(cache: list[dict], janelas: list[wfa.Janela],
                            capital: float, lucro_real: float) -> float | None:
    """Produção do alerta de reotimização: a faixa de todas as combinações
    fixas no mesmo intervalo do walk-forward, e o percentil em que a curva
    real caiu nela — ver `wfa.faixa_fixas`/`wfa.percentil_na_faixa`."""
    faixa = wfa.faixa_fixas(cache, janelas, capital)
    return wfa.percentil_na_faixa(faixa, lucro_real)


def _janelas_validas(passos: list[dict]) -> list[wfa.Janela]:
    """As janelas do walk-forward que entram nos três testes — a mesma régua
    de `wfa_runner.trades_oos_detalhados`: sem a linha DEPLOY (o OOS dela é o
    futuro, ainda não aconteceu), sem passo fora do mercado e sem passo sem
    parâmetro escolhido (nada para rodar de novo). As datas vêm como texto de
    `wfa_store.detalhes` (JSON não tem tipo de data) — reconstruídas aqui
    como `datetime64[s]`, o mesmo dtype que `wfa.Janela` usa em memória.
    """
    out = []
    for p in passos:
        if p.get("step") == "DEPLOY" or not p.get("params") or p.get("fora_do_mercado"):
            continue
        out.append(wfa.Janela(
            int(p["step"]),
            np.datetime64(p["is_de"], "s"), np.datetime64(p["is_ate"], "s"),
            np.datetime64(p["oos_de"], "s"), np.datetime64(p["oos_ate"], "s"),
            False))
    return out


def _perfil_por_step(passos_validos: list[dict], perfil_base: dict,
                     campos_execucao_nomes: set) -> dict[int, ExecutionProfile]:
    """Um `ExecutionProfile` por janela, com a mesma separação
    execução/estratégia que `wfa_runner.trades_oos_detalhados` já faz para
    salvar os trades do walk-forward — não é uma segunda régua."""
    out = {}
    for p in passos_validos:
        exec_ = {k: v for k, v in p["params"].items()
                 if k in campos_execucao_nomes}
        out[int(p["step"])] = replace(ExecutionProfile(**perfil_base), **exec_)
    return out


def _matriz_tentativas(cache: list[dict], trades_wfa: list[dict],
                       passos: list[dict], capital: float) -> np.ndarray | None:
    """A matriz do portão 6: uma coluna por combinação do cache da varredura
    mais a coluna da curva do walk-forward, pregão a pregão, no intervalo
    fora da amostra (`candidata.limites_oos`). `None` quando os passos não
    dão nem um limite (nenhuma janela real) — quem chama trata como falta de
    dado, não reprovação.
    """
    de, ate = candidata.limites_oos(passos)
    if de is None:
        return None
    colunas = []
    n_dias = None
    for c in cache:
        _, pnl = candidata.por_pregao(c["exit_ts"], c["liquido"], de, ate)
        if n_dias is None:
            n_dias = len(pnl)
        elif len(pnl) != n_dias:
            # mesmo de/ate para toda coluna: comprimentos diferentes só
            # aconteceriam com um bug na grade de dias — melhor recusar a
            # matriz do que deixar o `spa.teste` comparar colunas desalinhadas
            raise ValueError(
                "colunas do teste de tentativas com tamanhos diferentes — "
                "o cache e a curva do walk-forward precisam do mesmo eixo "
                "de dias")
        colunas.append(pnl)
    exit_wfa = [t["exit_ts"] for t in trades_wfa]
    liq_wfa = [t["liquido"] for t in trades_wfa]
    _, pnl_wfa = candidata.por_pregao(exit_wfa, liq_wfa, de, ate)
    if n_dias is not None and len(pnl_wfa) != n_dias:
        raise ValueError(
            "a curva do walk-forward tem eixo de dias diferente do cache — "
            "conferir de/ate de candidata.limites_oos")
    colunas.append(pnl_wfa)
    return np.column_stack(colunas)


FASES = ("preparando", "refazendo a varredura", "testando tentativas",
         "comparando com parâmetros fixos", "sorteando entradas")


class TestesCompletos:
    """Roda em segundo plano; a tela lê `estado` e nada mais — mesmo desenho
    de `wfa_runner.Varredura`: geração que descarta resposta velha, `parar()`
    cooperativo, estado publicado sob lock.
    """

    def __init__(self, *, varredura=None, montar_rodador=None, spa_teste=None,
                calcular_percentil=None):
        self._varredura = wfa_runner.VARREDURA if varredura is None else varredura
        self._montar_rodador = (aleatorio.rodador_do_motor if montar_rodador is None
                                else montar_rodador)
        self._spa_teste = spa_mod.teste if spa_teste is None else spa_teste
        self._calcular_percentil = (_percentil_fixas_padrao if calcular_percentil is None
                                    else calcular_percentil)

        self.estado = {"rodando": False, "fase": "", "pct": 0, "geracao": 0,
                       "wfa_id": None, "resultado": None, "erro": None}
        # resultado guardado em memória por wfa_id — não no banco nesta etapa
        self._resultados: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._geracao = 0

    def resultado_de(self, wfa_id: int) -> dict | None:
        return self._resultados.get(wfa_id)

    def parar(self):
        if self.estado["rodando"]:
            self._parar.set()

    def iniciar(self, wfa_id: int, *, n_sorteio: int = N_SORTEIO_PADRAO,
               semente: int = 7, workers: int = 8) -> bool:
        """Dispara os três testes numa thread. `False` se já há uma rodada em
        curso — o botão da tela fica desligado enquanto isso, mas a chamada
        em si não quebra se disparada duas vezes."""
        with self._lock:
            if self.estado["rodando"]:
                return False
            self._parar.clear()
            self._geracao += 1
            geracao = self._geracao
            self.estado.update(rodando=True, fase="preparando", pct=0,
                               geracao=geracao, wfa_id=wfa_id, resultado=None,
                               erro=None)
        self._thread = threading.Thread(
            target=self._rodar, daemon=True,
            args=(wfa_id, geracao, n_sorteio, semente, workers))
        self._thread.start()
        return True

    # -------------------------------------------------------------- motor
    def _rodar(self, wfa_id, geracao, n_sorteio, semente, workers):
        e = self.estado
        viva = lambda: geracao == self._geracao
        parou = lambda: self._parar.is_set() or not viva()
        try:
            detalhes = wfa_store.detalhes(wfa_id)
            if not detalhes:
                raise ValueError(f"walk-forward #{wfa_id} não encontrado")
            run_id = detalhes["run_id"]
            passos = detalhes["passos"]
            trades_wfa = wfa_store.trades(wfa_id)
            capital = float(detalhes.get("capital") or 10_000.0)

            # a mesma função que a aba Walk-Forward usa para reproduzir a
            # mineração — perfil_base e os nomes dos campos de execução vêm
            # só daqui, sem uma segunda fonte (ver `wfa_runner.argumentos_da_mineracao`)
            args_mineracao = wfa_runner.argumentos_da_mineracao(run_id)

            e["fase"] = "refazendo a varredura"
            cache = self._garantir_varredura(run_id, args_mineracao, workers, parou)
            if parou():
                return
            if not cache:
                raise ValueError("a varredura não produziu combinação com trades")

            janelas = _janelas_validas(passos)
            passos_validos = [p for p in passos
                              if p.get("step") != "DEPLOY" and p.get("params")
                              and not p.get("fora_do_mercado")]
            perfil_por_step = _perfil_por_step(
                passos_validos, args_mineracao["perfil_base"],
                args_mineracao["campos_execucao_nomes"])

            e["fase"] = "testando tentativas"
            e["pct"] = 30
            matriz = _matriz_tentativas(cache, trades_wfa, passos, capital)
            resultado_spa = (self._spa_teste(matriz) if matriz is not None
                             else {"erro": "sem janela real para medir"})
            if parou():
                return

            e["fase"] = "comparando com parâmetros fixos"
            e["pct"] = 55
            lucro_real = float(sum(t["liquido"] for t in trades_wfa))
            percentil = self._calcular_percentil(cache, janelas, capital, lucro_real)
            if parou():
                return

            e["fase"] = "sorteando entradas"
            e["pct"] = 60
            resultado_aleatorio = self._rodar_aleatorio(
                janelas, trades_wfa, perfil_por_step, args_mineracao,
                n_sorteio, semente, lucro_real, parou)
            if parou():
                return

            portoes = [
                candidata.portao_aleatorio(resultado_aleatorio),
                candidata.portao_tentativas(resultado_spa),
                candidata.alerta_reotimizar(percentil),
            ]
            resultado = {
                "portoes": portoes,
                "leituras": {
                    "p_aleatorio": (resultado_aleatorio or {}).get("p"),
                    "p_tentativas": (resultado_spa or {}).get("p"),
                    "percentil_fixas": percentil,
                    "calibracao_ok": (resultado_aleatorio or {}).get("calibracao_ok"),
                },
            }
            with self._lock:
                if not viva():
                    return
                self._resultados[wfa_id] = resultado
                e["resultado"] = resultado
                e["pct"] = 100
        except Exception as erro:      # publica sem derrubar a thread
            if viva():
                e["erro"] = str(erro)
        finally:
            if viva():
                e["rodando"] = False

    def _garantir_varredura(self, run_id, args_mineracao, workers, parou) -> list[dict]:
        """Reusa `self._varredura.cache` quando o `estado` mostra o mesmo
        `run_id` e ela não está rodando; senão inicia com os argumentos de
        `argumentos_da_mineracao` e espera, checando `parar` a cada meio
        segundo."""
        v = self._varredura
        serve = (v.estado.get("pronto") and v.estado.get("run_id") == run_id
                and not v.estado.get("rodando"))
        if not serve:
            args = dict(args_mineracao)
            args["workers"] = workers
            v.iniciar(**args)
            while v.estado.get("rodando"):
                if parou():
                    v.parar()
                    return []
                time.sleep(0.5)
            if v.estado.get("run_id") != run_id or not v.estado.get("pronto"):
                raise RuntimeError(
                    v.estado.get("erro")
                    or "a varredura terminou sem produzir esta mineração")
        return v.cache

    def _rodar_aleatorio(self, janelas, trades_wfa, perfil_por_step,
                         args_mineracao, n_sorteio, semente, lucro_real,
                         parou) -> dict:
        """Monta o despachante `{janela: rodador_do_motor(...)}` (uma barra
        carregada uma vez só, reusada por todas as janelas) e chama
        `aleatorio.teste_janelas` — o portão 2."""
        simbolo = args_mineracao["symbol"]
        d = db.read_bars_parquet(simbolo, None, None)
        bars = {
            "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
            **{c: np.ascontiguousarray(d[c], dtype=np.int64)
               for c in ("open", "high", "low", "close", "tick_volume", "volume")},
        }
        inst = db.load_instrument_yaml(simbolo)
        mod = __import__(f"strategies.{args_mineracao['estrategia_nome']}",
                         fromlist=["x"])

        trades_por_step: dict[int, list[dict]] = {}
        for t in trades_wfa:
            trades_por_step.setdefault(t["step"], []).append(t)

        despachante = {}
        for j in janelas:
            despachante[j] = self._montar_rodador(
                bars, mod, perfil_por_step[j.step], inst,
                trades_por_step.get(j.step, []))

        def rodar_janela(janela, n_sinais, semente_):
            if janela not in despachante:
                raise ValueError(
                    f"janela do step {janela.step} não está no despachante")
            return despachante[janela](janela, n_sinais, semente_)

        alvos = [len(trades_por_step.get(j.step, [])) for j in janelas]

        def progresso(rep, n):
            self.estado["pct"] = 60 + int(40 * rep / n)

        return aleatorio.teste_janelas(
            rodar_janela, janelas, alvos, lucro_real, n=n_sorteio,
            semente=semente, progresso=progresso, parar=parou)


TESTES = TestesCompletos()
