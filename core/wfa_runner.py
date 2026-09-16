"""A varredura que alimenta o Walk-Forward: uma vez, e só uma.

`core/wfa.py` não roda backtest — recebe, por combinação, os arrays dos
`CAMPOS` (entrada, saída, líquido e custo de cada trade) de uma execução sobre
o histórico inteiro. Este módulo é quem produz esses arrays.

O ganho está aí: as 12 configurações do operador somam **135 janelas**.
Rodadas uma a uma seriam `135 × espaço` backtests; com o cache, é `1 ×
espaço`, e cada janela vira uma máscara. Com 41 combinações a varredura leva
segundos e as 12 configurações inteiras, milissegundos.

Os workers leem do espelho **Parquet**, nunca do `.duckdb` — mesma razão da
mineração: o DuckDB aceita vários leitores OU um escritor, e o processo que
grava não conseguiria entrar.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from . import db_manager as db
from . import metrics
from .engine.execution import ExecutionProfile, run_strategy

_BARS: dict | None = None
_INST: dict | None = None
_ESTRATEGIA = None

# Teto de segurança do cache. Cada trade custa 32 bytes (entrada, saída,
# líquido e custo); 400 MB são ~12 milhões de trades somados, o que já é
# espaço grande demais para caber numa tela de qualquer jeito.
TETO_MB = 400.0

# O que cada combinação guarda de cada trade. Entrada para fatiar as janelas;
# líquido para escolher; saída e custo para os cartões OOS medirem com a
# mesma régua do backtest — Sharpe agrega pelo dia da SAÍDA, e o cartão de
# lucro mostra bruto e custo. Um campo novo aqui aparece em
# `wfa.trades_oos_campos` sem mexer em mais nada.
CAMPOS = {"entry_ts": "datetime64[s]", "exit_ts": "datetime64[s]",
          "liquido": np.float64, "custo": np.float64}


def _sem_trades() -> dict:
    return {c: np.empty(0, dtype=t) for c, t in CAMPOS.items()}


def _init(symbol: str, de, ate, estrategia_nome: str):
    global _BARS, _INST, _ESTRATEGIA
    import importlib

    d = db.read_bars_parquet(symbol, de, ate)
    _BARS = {
        "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
        **{c: np.ascontiguousarray(d[c], dtype=np.int64)
           for c in ("open", "high", "low", "close", "tick_volume", "volume")},
    }
    _INST = db.load_instrument_yaml(symbol)
    _ESTRATEGIA = importlib.import_module(f"strategies.{estrategia_nome}")


def _uma(args):
    """Uma combinação: um backtest, e os trades voltam inteiros.

    Volta só os `CAMPOS` — é o que o WFA consulta. Mandar o resto dos arrays
    de volta pelo pipe do processo custaria memória sem uso.
    """
    trial_id, params_estrategia, campos_execucao, perfil_base = args
    params = {**params_estrategia, **campos_execucao}
    try:
        perfil = ExecutionProfile(**{**perfil_base, **campos_execucao})
        res = run_strategy(_BARS, _ESTRATEGIA, params_estrategia, perfil, _INST)
        if res.n_trades == 0:
            return {"trial_id": trial_id, "params": params, "erro": None,
                    **_sem_trades()}
        din = metrics.monetize(res)
        return {
            "trial_id": trial_id, "params": params, "erro": None,
            "entry_ts": res.trades["entry_ts"].astype("datetime64[s]"),
            "exit_ts": res.trades["exit_ts"].astype("datetime64[s]"),
            "liquido": din["liquido"].astype(np.float64),
            "custo": np.asarray(din["custo"], dtype=np.float64),
        }
    except Exception as erro:          # uma combinação ruim não derruba a varredura
        return {"trial_id": trial_id, "params": params, "erro": str(erro),
                **_sem_trades()}


def tamanho_mb(cache: list[dict]) -> float:
    return sum(c[k].nbytes for c in cache for k in CAMPOS if k in c) / 1e6


class Varredura:
    """Roda em segundo plano; a tela lê `estado` e nada mais.

    Mesmo desenho da `Mineracao`, e pelo mesmo motivo: uma varredura de
    milhares de combinações não pode congelar a interface, e trocar de
    estratégia no meio precisa poder aposentar a que está correndo.
    """

    def __init__(self):
        self.estado = {"rodando": False, "feitos": 0, "total": 0,
                       "erro": None, "mensagem": "", "segundos": 0.0,
                       "mb": 0.0, "run_id": None, "estrategia": None,
                       "simbolo": None, "de": None, "ate": None,
                       # o corte do holdout e o fim real dos dados. A varredura
                       # sempre roda ate o FIM: assim ligar e desligar o
                       # holdout na tela nao pede varredura nova - so muda o
                       # limite da escadinha de janelas.
                       "ate_holdout": None,
                       "capital": 10_000.0, "pronto": False,
                       # a tela ja desenhou este resultado? Sem esta marca
                       # havia corrida: uma varredura de 1,4s termina ANTES
                       # de o relogio ligar, o resultado ficava pronto no
                       # servidor e a tela nunca ia busca-lo - travada num
                       # "varrendo... 0/41" eterno.
                       "entregue": False}
        self._cache: list[dict] = []
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._geracao = 0

    # ------------------------------------------------------------ controle
    @property
    def cache(self) -> list[dict]:
        """Só as combinações que produziram trades. Uma sem nenhum trade não
        tem o que dizer em janela nenhuma, e carregá-la só faria a escolha
        percorrer lixo."""
        return [c for c in self._cache if not c["erro"] and len(c["entry_ts"])]

    def parar(self):
        if self.estado["rodando"]:
            self._parar.set()
            self.estado["mensagem"] = "parando…"

    def esquecer(self):
        self.parar()
        self._geracao += 1
        self._cache = []
        self.estado.update(rodando=False, feitos=0, total=0, erro=None,
                           mensagem="", pronto=False, entregue=False,
                           run_id=None, mb=0.0)

    def iniciar(self, *, symbol, estrategia_nome, espaco, perfil_base,
                de, ate, campos_execucao_nomes, ate_holdout=None,
                run_id=None, workers=8):
        # "confere e age" dentro do lock: dois callbacks ao mesmo tempo
        # abririam dois pools de 8 processos
        with self._lock:
            if self.estado["rodando"]:
                return False
            return self._iniciar(symbol=symbol, estrategia_nome=estrategia_nome,
                                 espaco=espaco, perfil_base=perfil_base, de=de,
                                 ate=ate, campos_execucao_nomes=campos_execucao_nomes,
                                 ate_holdout=ate_holdout, run_id=run_id,
                                 workers=workers)

    def _iniciar(self, *, symbol, estrategia_nome, espaco, perfil_base, de, ate,
                 campos_execucao_nomes, ate_holdout, run_id, workers):
        self._parar.clear()
        self._geracao += 1
        self._cache = []
        self.estado.update(rodando=True, feitos=0, total=0, erro=None,
                           pronto=False, entregue=False,
                           mensagem="preparando…", mb=0.0, uteis=0,
                           # quando começou: é o que a barra usa para estimar
                           # quanto falta
                           inicio=time.time(), segundos=0.0,
                           # identifica ESTA varredura: a tela usa para
                           # entregar o resultado uma vez só
                           geracao=self._geracao,
                           run_id=run_id, estrategia=estrategia_nome,
                           simbolo=symbol, de=str(de), ate=str(ate),
                           ate_holdout=str(ate_holdout or ate),
                           capital=perfil_base.get("capital_inicial", 10_000.0))
        self._thread = threading.Thread(
            target=self._rodar, daemon=True,
            args=(symbol, estrategia_nome, espaco, perfil_base, de, ate,
                  campos_execucao_nomes, self._geracao, workers))
        self._thread.start()
        return True

    # -------------------------------------------------------------- motor
    def _rodar(self, symbol, estrategia_nome, espaco, perfil_base, de, ate,
               campos_execucao_nomes, geracao, workers):
        from .optimizer import combinacoes

        e = self.estado
        viva = lambda: geracao == self._geracao
        inicio = time.time()
        try:
            combos = combinacoes(espaco)
            e["total"] = len(combos)
            tarefas = []
            for i, p in enumerate(combos):
                exec_ = {k: v for k, v in p.items() if k in campos_execucao_nomes}
                estrat = {k: v for k, v in p.items()
                          if k not in campos_execucao_nomes}
                tarefas.append((i, estrat, exec_, perfil_base))

            resultados, mb, estourou = [], 0.0, False
            pool = ProcessPoolExecutor(
                max_workers=max(1, workers), initializer=_init,
                initargs=(symbol, de, ate, estrategia_nome))
            try:
                for r in pool.map(_uma, tarefas, chunksize=4):
                    if self._parar.is_set() or not viva():
                        break
                    resultados.append(r)
                    e["feitos"] = len(resultados)
                    # o teto é conferido DURANTE: conferido no fim, a memória
                    # já tinha sido toda ocupada, e o resultado seguia em uso
                    mb += sum(r[k].nbytes for k in CAMPOS if k in r) / 1e6
                    if mb > TETO_MB:
                        estourou = True
                        break
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            parada = self._parar.is_set()
            # a publicação também sob o lock: uma varredura velha que chega
            # aqui depois de uma nova começar não pode sobrescrever o cache
            with self._lock:
                if not viva():
                    return
                e["mb"] = mb
                e["segundos"] = time.time() - inicio
                if estourou or parada:
                    # nem cache parcial nem "pronto": uma varredura que não
                    # foi até o fim não pode ser entregue como se tivesse ido
                    self._cache = []
                    e["pronto"] = False
                    e["uteis"] = 0
                    e["erro"] = ("acima do teto" if estourou else "interrompida")
                    e["mensagem"] = (
                        f"passou de {TETO_MB:.0f} MB em {len(resultados)} de "
                        f"{len(combos)} combinações — estreite o espaço de busca"
                        if estourou else
                        f"varredura interrompida em {len(resultados)} de {len(combos)}")
                    return
                self._cache = resultados
                uteis = len(self.cache)
                e["pronto"] = bool(uteis)
                e["uteis"] = uteis
                e["mensagem"] = ("nenhuma combinação produziu trades" if not uteis
                                 else f"{uteis} combinações com trades · "
                                      f"{e['segundos']:.1f}s · {mb:.1f} MB")
        except Exception as erro:
            e["erro"] = str(erro)
            e["mensagem"] = f"falhou: {erro}"
        finally:
            if viva():
                e["rodando"] = False


VARREDURA = Varredura()


def trades_oos_detalhados(perfil_base: dict, estrategia_nome: str,
                          simbolo: str, passos, campos_execucao_nomes) -> list[dict]:
    """Os trades da curva OOS, com tudo que o portfólio vai precisar.

    O cache da varredura guarda só os `CAMPOS` (entrada, saída, líquido e
    custo) — de propósito, para caber na memória com milhares de combinações.
    Aqui, na hora de SALVAR, vale rodar de novo: um backtest por janela (um por janela com combinação
    escolhida), meio segundo, e em troca fica gravado entrada, saída, lado,
    preços, contratos, custo, motivo de saída e excursão de cada operação.

    Cada janela contribui **apenas com os trades do seu OOS** — é a mesma
    costura que `wfa.trades_oos` faz, agora com o trade inteiro em vez de só
    o resultado.
    """
    from dataclasses import replace

    bars = db.read_bars_parquet(simbolo, None, None)
    barras = {
        "ts": np.asarray(bars["ts"], dtype="datetime64[ns]"),
        **{c: np.ascontiguousarray(bars[c], dtype=np.int64)
           for c in ("open", "high", "low", "close", "tick_volume", "volume")},
    }
    inst = db.load_instrument_yaml(simbolo)
    mod = __import__(f"strategies.{estrategia_nome}", fromlist=["x"])

    fora, n = [], 0
    for p in passos:
        j = p.janela
        if j.deploy or not p.params or p.fora_do_mercado:
            continue

        exec_ = {k: v for k, v in p.params.items() if k in campos_execucao_nomes}
        estrat = {k: v for k, v in p.params.items()
                  if k not in campos_execucao_nomes}
        perfil = replace(ExecutionProfile(**perfil_base), **exec_)
        res = run_strategy(barras, mod, estrat, perfil, inst)
        if res.n_trades == 0:
            continue

        din = metrics.monetize(res)
        t = res.trades
        dentro = ((t["entry_ts"] >= j.oos_de) & (t["entry_ts"] < j.oos_ate))
        for i in np.flatnonzero(dentro):
            n += 1
            fora.append({
                "n": n, "step": int(j.step),
                "entry_ts": t["entry_ts"][i].astype("datetime64[s]").item(),
                "exit_ts": t["exit_ts"][i].astype("datetime64[s]").item(),
                "side": int(t["side"][i]),
                "entry_px": int(t["entry_px"][i]),
                "exit_px": int(t["exit_px"][i]),
                "points": int(t["points"][i]),
                "contratos": int(din["contratos"][i]),
                "bruto": float(din["bruto"][i]),
                "custo": float(din["custo"][i]),
                "liquido": float(din["liquido"][i]),
                "reason": int(t["reason"][i]),
                "mae": int(t["mae"][i]), "mfe": int(t["mfe"][i]),
                "bars_held": int(t["bars_held"][i]),
            })
    fora.sort(key=lambda r: r["entry_ts"])
    for i, r in enumerate(fora, 1):
        r["n"] = i
    return fora
