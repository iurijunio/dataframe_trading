"""Mineracao: varrer o espaco de parametros sem travar a interface.

Desenho, e o porque de cada peca:

WORKERS. Threads, nao processos. O kernel Numba roda com `nogil=True`, entao
solta o GIL enquanto trabalha - que e onde esta o tempo. Threads ainda evitam
tres problemas que o pool de processos trouxe no Windows: o `spawn` reimporta
o modulo principal (e trava dentro do servidor web), cada worker teria que
recarregar 688 mil barras, e nada disso se paga num laco que ja e rapido.

ESCRITOR UNICO. DuckDB aceita um escritor por vez. Os workers nao abrem o
banco: devolvem resultado pela fila do pool e o processo principal grava em
lote. E a unica regra que nao pode ser relaxada aqui.

PROGRESSO. A interface le um dicionario em memoria, nao o banco - assim a
tabela aparece enquanto a varredura corre, sem disputa de arquivo.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime

import numpy as np

from . import db_manager as db
from . import metrics, walkforward as wf
from .engine.execution import ExecutionProfile, run_strategy

_BARS: dict | None = None
_INST: dict | None = None
_ESTRATEGIA = None


# ------------------------------------------------------------ espaco de busca
def montar_espaco(schema: dict, ranges: dict, extras: dict | None = None) -> dict[str, list]:
    """Transforma as faixas da tela em listas de valores.

    Parametro nao marcado vira lista de um elemento so - o valor atual da
    tela. Assim a varredura sempre percorre um produto cartesiano bem
    definido, mesmo com um parametro so ligado.
    """
    espaco: dict[str, list] = {}
    for nome, meta in {**schema, **(extras or {})}.items():
        r = ranges.get(nome) or {}
        atual = r.get("valor", meta.get("default"))
        if not r.get("on"):
            espaco[nome] = [atual]
            continue
        de, ate = r.get("de"), r.get("ate")
        passo = r.get("passo")
        if passo is None:
            passo = meta.get("step") or 1
        # cuidado com `or`: passo 0 e um valor legitimo digitado na tela e
        # nao pode virar 1 silenciosamente - faixa invalida vira valor unico
        if de is None or ate is None or passo <= 0 or ate < de:
            espaco[nome] = [atual]
            continue
        # A faixa da tela nao pode furar os limites que a estrategia declara.
        # Sem isto, um "ate" digitado a mais varria media_lenta=274 num
        # parametro cujo schema diz max=200 - e o resultado parecia legitimo.
        lo, hi = meta.get("min"), meta.get("max")
        if lo is not None:
            de = max(de, lo)
        if hi is not None:
            ate = min(ate, hi)
        if ate < de:
            espaco[nome] = [atual]
            continue

        n = int((ate - de) / passo) + 1
        vals = [de + i * passo for i in range(n)]
        if meta.get("tipo", "int") == "int":
            vals = sorted({int(round(v)) for v in vals})
        espaco[nome] = vals
    return espaco


def _num(v):
    """Valor para a tela: -inf e NaN viram vazio, não texto quebrado."""
    return round(float(v), 3) if v is not None and np.isfinite(v) else None


def combinacoes(espaco: dict[str, list]) -> list[dict]:
    nomes = list(espaco)
    return [dict(zip(nomes, vals)) for vals in itertools.product(*espaco.values())]


# ------------------------------------------------------------------- worker
def _init(symbol: str, de, ate, estrategia_nome: str):
    """Arranque de cada worker.

    As barras vêm do espelho PARQUET, não do database.duckdb. Isso não é
    detalhe: o DuckDB aceita vários leitores ou um escritor, nunca os dois -
    se os workers abrissem o banco, o processo que grava os resultados não
    conseguiria entrar.
    """
    global _BARS, _INST, _ESTRATEGIA
    import importlib

    import numpy as np

    d = db.read_bars_parquet(symbol, de, ate)
    _BARS = {
        "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
        **{c: np.ascontiguousarray(d[c], dtype=np.int64)
           for c in ("open", "high", "low", "close", "tick_volume", "volume")},
    }
    _INST = db.load_instrument_yaml(symbol)
    _ESTRATEGIA = importlib.import_module(f"strategies.{estrategia_nome}")


def _uma(args):
    """Uma combinacao: um backtest sobre o periodo inteiro, depois repartido
    entre as janelas de treino e teste."""
    trial_id, params_estrategia, campos_execucao, perfil_base, janelas = args
    try:
        perfil = ExecutionProfile(**{**perfil_base, **campos_execucao})
        res = run_strategy(_BARS, _ESTRATEGIA, params_estrategia, perfil, _INST)
        if res.n_trades == 0:
            vazio = wf.resumo(np.empty(0), perfil.capital_inicial)
            return {"trial_id": trial_id,
                    "params": {**params_estrategia, **campos_execucao},
                    "geral": vazio, "holdout": vazio,
                    "folds": {"n": 0, "com_trades": 0, "positivos": 0,
                              "mediana_fr": 0.0, "mediana_lucro": 0.0},
                    "consistencia": 0.0,
                    "passa_filtro": False, "score": float("-inf"), "erro": None}

        liq = metrics.monetize(res)["liquido"]
        aval = wf.avaliar(res.trades["entry_ts"], liq, janelas,
                          perfil.capital_inicial, perfil.min_operacoes)
        aval["trial_id"] = trial_id
        aval["params"] = {**params_estrategia, **campos_execucao}
        aval["erro"] = None
        return aval
    except Exception as erro:  # nunca derruba a varredura inteira
        return {"trial_id": trial_id, "params": {**params_estrategia, **campos_execucao},
                "erro": str(erro), "score": float("-inf"), "passa_filtro": False,
                "geral": {}, "holdout": {}, "folds": {}, "consistencia": 0.0}


# ------------------------------------------------------------------ mineracao
class Mineracao:
    """Roda em segundo plano. A interface le `estado` e nada mais."""

    def __init__(self):
        self.estado = {"rodando": False, "feitos": 0, "total": 0,
                       "run_id": None, "inicio": None, "erro": None,
                       "mensagem": "", "trials": [],
                       # A TABELA e truncada em `_ranking`; a ESTATISTICA nao
                       # pode ser. `resumo` carrega as combinacoes inteiras,
                       # so com os campos que a porteira e a distribuicao
                       # leem - e `fonte` diz de onde ele veio, para uma
                       # varredura antiga em memoria nao descrever uma
                       # mineracao recem-carregada do banco.
                       "resumo": [], "fonte": None,
                       # salva: a varredura atual ja foi para o banco?
                       "salva": False, "salvando": False, "aviso_salvar": "",
                       # de qual estrategia e a varredura que esta na tela
                       "fim_otimizacao": None, "estrategia": None}
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._resultados: list[dict] = []   # varredura em memoria, nao salva
        self._contexto: dict = {}
        # Toda varredura carrega o numero da geracao em que nasceu. Trocar de
        # estrategia (ou comecar outra) incrementa o contador, e a thread
        # antiga descobre que ficou obsoleta antes de escrever o resultado -
        # sem isto ela repovoava a tabela depois do reset.
        self._geracao = 0

    # ------------------------------------------------------------- controle
    def parar(self):
        if self.estado["rodando"]:
            self.estado["mensagem"] = "parando…"
        self._parar.set()

    @property
    def parando(self) -> bool:
        return self._parar.is_set() and self.estado["rodando"]

    def iniciar(self, **kw) -> bool:
        if self.estado["rodando"]:
            return False
        self._parar.clear()
        # marcado AQUI, e nao dentro da thread: a interface decide se liga o
        # relogio de progresso no mesmo instante do clique, e a thread pode
        # nem ter comecado a rodar ainda. Sem isto o relogio nasce desligado
        # e a tabela nunca aparece.
        # nova varredura descarta a anterior nao salva - de propósito
        self._resultados = []
        self._contexto = {}
        self.estado.update(rodando=True, feitos=0, total=0, trials=[],
                           resumo=[], fonte=None,
                           erro=None, mensagem="iniciando…", run_id=None,
                           salva=False, salvando=False, aviso_salvar="")
        self._thread = threading.Thread(target=self._rodar, kwargs=kw, daemon=True)
        self._thread.start()
        return True

    def esquecer(self):
        """Descarta a varredura em memória. Usado ao trocar de estratégia:
        os parâmetros mudam de nome e de significado, então manter o
        resultado antigo na tela só induziria ao erro."""
        self.parar()
        self._geracao += 1
        self._resultados = []
        self._contexto = {}
        self.estado.update(feitos=0, total=0, trials=[], resumo=[], fonte=None,
                           run_id=None,
                           salva=False, salvando=False, aviso_salvar="",
                           erro=None, mensagem="", fim_otimizacao=None,
                           estrategia=None, rodando=False)

    # --------------------------------------------------------------- salvar
    @property
    def n_resultados(self) -> int:
        return len(self._resultados)

    @property
    def pode_salvar(self) -> bool:
        return bool(self._resultados) and not self.estado["rodando"] \
            and not self.estado["salva"] and not self.estado["salvando"]

    def salvar(self, nome: str | None = None,
               criterios: dict | None = None) -> bool:
        """Persiste a varredura em memória. Só acontece se você mandar.

        Roda em thread própria: gravar 300 mil combinações leva segundos, e
        a interface não pode congelar enquanto isso.
        """
        if not self.pode_salvar:
            return False
        self.estado["salvando"] = True
        self.estado["aviso_salvar"] = "salvando…"
        threading.Thread(target=self._persistir, args=(nome, criterios),
                         daemon=True).start()
        return True

    def _persistir(self, nome: str | None, criterios: dict | None = None):
        e = self.estado
        try:
            ctx = self._contexto
            bons = [r for r in self._resultados if not r.get("erro")]
            status = "interrompida" if ctx.get("interrompida") else "concluida"

            linhas = [self._linha(0, r) for r in self._resultados]
            with db.connect_write() as con, db.transacao(con):
                run_id = con.execute("SELECT nextval('seq_run_id')").fetchone()[0]
                # colunas nomeadas: a tabela ganha colunas com o tempo
                # (ALTER TABLE), e um INSERT posicional quebra a cada uma
                con.execute(
                    "INSERT INTO mining_runs (run_id, symbol, strategy, "
                    "created_at, profile, space, folds, holdout_de, "
                    "n_combinacoes, status, nome, wf_config, criterios) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [run_id, ctx["symbol"], ctx["estrategia"], datetime.now(),
                     json.dumps(ctx["perfil"], default=str),
                     json.dumps({k: list(map(float, v))
                                 for k, v in ctx["espaco"].items()}),
                     json.dumps([asdict(f) for f in ctx["janelas"].folds], default=str),
                     str(ctx["janelas"].holdout_de), len(self._resultados), status,
                     nome or None,
                     json.dumps(ctx.get("wf_config") or {}, default=str),
                     json.dumps(criterios) if criterios else None],
                )
                # Em LOTE, por uma tabela Arrow: o executemany confirmava
                # linha a linha, ~9 ms por combinação — 300 mil levariam 45
                # minutos com o banco trancado para a tela.
                _inserir_trials(con, run_id, linhas)

            e["run_id"] = run_id
            e["salva"] = True
            rotulo = f"“{nome}” · " if nome else ""
            e["aviso_salvar"] = (f"salva: {rotulo}mineração #{run_id} · "
                                 f"{len(bons):,} combinações".replace(",", "."))
        except Exception as erro:
            e["aviso_salvar"] = f"falhou ao salvar: {erro}"
        finally:
            e["salvando"] = False

    @staticmethod
    def _linha(run_id: int, r: dict) -> tuple:
        """Ordem das colunas de mining_trials — ver core/schema.sql."""
        def fin(v):
            return float(v) if v is not None and np.isfinite(v) else None

        g = r.get("geral", {})
        f = r.get("folds", {})
        h = r.get("holdout") or {}
        return (
            run_id, r["trial_id"], json.dumps(r["params"], default=str),
            g.get("trades", 0), float(g.get("lucro", 0)),
            fin(g.get("profit_factor")), float(g.get("max_dd", 0)),
            f.get("com_trades", 0), f.get("positivos", 0),
            float(f.get("mediana_lucro", 0)),
            h.get("trades", 0) if h else None,
            float(h.get("lucro", 0)) if h else None,
            fin(r.get("score")), bool(r.get("passa_filtro")), r.get("erro"),
            fin(r.get("score_robusto")),
        )

    # --------------------------------------------------------------- motor
    def _rodar(self, symbol, estrategia_nome, schema, ranges, perfil_base,
               campos_execucao_schema, de, ate, wf_config, workers=None):
        e = self.estado
        geracao = self._geracao          # a que esta varredura pertence
        viva = lambda: self._geracao == geracao   # noqa: E731
        try:
            e.update(inicio=time.time(), mensagem="montando espaço de busca")

            espaco_p = montar_espaco(schema, ranges)
            espaco_e = montar_espaco(campos_execucao_schema, ranges)
            combos_p = combinacoes(espaco_p)
            combos_e = combinacoes(espaco_e)
            tarefas_params = [(p, x) for p in combos_p for x in combos_e]
            e["total"] = len(tarefas_params)

            amostra = db.read_bars_parquet(symbol, de, ate)["ts"]
            inicio_dados = np.datetime64(de or amostra[0], "s")
            fim_dados = np.datetime64(ate or amostra[-1], "s")
            janelas = wf.montar_janelas(inicio_dados, fim_dados, **wf_config)

            if not janelas.folds:
                raise ValueError(
                    "período curto demais para o walk-forward pedido: "
                    "reduza treino/teste ou o holdout."
                )

            # A varredura NAO grava nada no banco. Minerar e exploratorio:
            # dezenas de tentativas ate achar cluster, e a maioria e lixo.
            # Salvar so acontece quando voce pede, no botao - o que de quebra
            # tira a escrita de dentro do laco de coleta, que era o que
            # segurava a varredura por segundos a cada lote.
            self._contexto = {
                "symbol": symbol, "estrategia": estrategia_nome,
                "perfil": perfil_base, "espaco": espaco_p | espaco_e,
                "janelas": janelas, "total": len(tarefas_params),
                "wf_config": dict(wf_config),
            }
            e["run_id"] = None
            e["salva"] = False
            e["estrategia"] = estrategia_nome
            # a tabela mede só até aqui; o clique usa isto para o backtest
            # único cair na MESMA janela, senão os dois painéis mostram
            # números diferentes da mesma combinação
            e["fim_otimizacao"] = str(janelas.fim_otimizacao)[:10]
            e["mensagem"] = f"{len(janelas.folds)} folds · {e['total']} combinações"

            tarefas = [(i, p, x, perfil_base, janelas)
                       for i, (p, x) in enumerate(tarefas_params)]

            resultados: list[dict] = []
            _init(symbol, de, ate, estrategia_nome)   # uma vez, compartilhado

            # Sem `with`: a saida do context manager chama shutdown(wait=True),
            # que ESPERA todas as tarefas ja submetidas terminarem. Com 300 mil
            # combinacoes na fila, "Parar" so parava de coletar resultado - a
            # varredura seguia rodando por baixo. Aqui o cancelamento e de
            # verdade: o que ainda nao comecou e descartado.
            pool = ThreadPoolExecutor(max_workers=workers or 8)
            interrompida = False
            try:
                futuros = {pool.submit(_uma, t): t[0] for t in tarefas}
                for fut in as_completed(futuros):
                    if self._parar.is_set() or not viva():
                        interrompida = True
                        break
                    r = fut.result()
                    resultados.append(r)
                    e["feitos"] = len(resultados)
                    if len(resultados) % 25 == 0:
                        e["trials"] = self._ranking(resultados)
                        e["resumo"] = self._extrato(resultados)
                        e["fonte"] = "memoria"
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            # trocou de estratégia no meio: o resultado é de um espaço que
            # não está mais na tela, então some sem deixar rastro
            if not viva():
                return

            if resultados:
                nomes = list(espaco_p) + list(espaco_e)
                wf.score_vizinhanca([r for r in resultados if not r.get("erro")], nomes)

            self._resultados = resultados
            self._contexto["interrompida"] = interrompida
            e["trials"] = self._ranking(resultados)
            e["resumo"] = self._extrato(resultados)
            e["fonte"] = "memoria"
            if interrompida:
                e["mensagem"] = (f"interrompida em {len(resultados)} de {e['total']} "
                                 "— o que já rodou está salvo")
            else:
                e["mensagem"] = (
                    f"{len(resultados)} combinações · {len(janelas.folds)} folds · "
                    f"{time.time() - e['inicio']:.0f}s"
                )
        except Exception as erro:
            e["erro"] = str(erro)
            e["mensagem"] = f"falhou: {erro}"
        finally:
            # uma varredura obsoleta nao mexe mais no estado: quem a
            # aposentou ja deixou a tela no ponto certo
            if viva():
                e["rodando"] = False

    # Campos que a porteira, a distribuicao e os criterios leem. Sao 8
    # numeros por combinacao: 100 mil delas cabem em memoria sem incomodar,
    # e nada disto viaja para o navegador.
    @staticmethod
    def _extrato(resultados: list[dict]) -> list[dict]:
        """TODAS as combinacoes validas, sem o corte do ranking.

        O `_ranking` corta em 5.000 porque a tabela e a nuvem nao aguentam
        mais que isso - e corta pelo TOPO, ordenado por qualidade. Alimentar
        a porteira com esse recorte seria pedir a ela que julgasse a
        varredura olhando so a metade boa: uma regiao mediocre de 8 mil
        pontos passava a "aprovada com ressalva" porque os 3 mil piores
        ficavam de fora da conta.
        """
        return [
            {
                "lucro": round(r["geral"].get("lucro", 0), 2),
                "trades": r["geral"].get("trades", 0),
                "dd": round(r["geral"].get("max_dd", 0), 2),
                "pf": _num(r["geral"].get("profit_factor")),
                "fr": _num(r["geral"].get("fator_recuperacao")),
                "consistencia": round(r["consistencia"] * 100, 1),
                "mediana_fold": round(r["folds"].get("mediana_lucro", 0), 2),
                "robusto": _num(r.get("score_robusto")),
                "filtro": "ok" if r["passa_filtro"] else "amostra fraca",
            }
            for r in resultados if not r.get("erro")
        ]

    # ------------------------------------------------------------ ranking
    # A nuvem precisa das combinacoes RUINS tambem: sem o vermelho em volta
    # nao da para ver se o verde e uma regiao ou um acidente. Cortar no topo
    # do ranking transformaria o scatter num grafico so de vencedores.
    @staticmethod
    def _ranking(resultados: list[dict], limite: int = 5000) -> list[dict]:
        bons = [r for r in resultados if not r.get("erro")]
        bons.sort(key=lambda r: (r.get("score_robusto", r["score"]), r["score"]),
                  reverse=True)
        # O holdout NAO entra aqui de proposito: exibir o holdout de mil
        # combinacoes e escolher a melhor e o mesmo que nao ter holdout.
        return [
            {
                "n": i + 1,
                "trial_id": r["trial_id"],
                "params": r["params"],
                "params_txt": " · ".join(f"{k}={v}" for k, v in r["params"].items()),
                "lucro": round(r["geral"].get("lucro", 0), 2),
                # criterio padrao de otimizacao do MT5: lucro dividido pelo
                # drawdown que foi preciso aguentar para consegui-lo
                "fr": _num(r["geral"].get("fator_recuperacao")),
                # pelo _num como os demais: profit factor e infinito quando
                # nao houve perda, e a linha vinda do banco ja usava _num -
                # a mesma combinacao aparecia diferente conforme a origem
                "pf": _num(r["geral"].get("profit_factor")),
                "dd": round(r["geral"].get("max_dd", 0), 2),
                "trades": r["geral"].get("trades", 0),
                "folds": f"{r['folds'].get('positivos', 0)}/{r['folds'].get('com_trades', 0)}",
                "consistencia": round(r["consistencia"] * 100, 1),
                "mediana_fold": round(r["folds"].get("mediana_lucro", 0), 2),
                "score": round(r["score"], 3) if np.isfinite(r["score"]) else None,
                # O score de vizinhanca so existe com a grade inteira, entao
                # durante a varredura esta coluna fica VAZIA - e nao com o
                # score cru no lugar dela. Preencher com o cru fazia valores
                # como 1,86 aparecerem e depois "sumirem" no fim: eram picos
                # isolados cuja mediana de vizinhos e mais baixa. Mesmo nome,
                # duas medidas diferentes - parecia dado se perdendo.
                "robusto": _num(r.get("score_robusto")),
                "filtro": "ok" if r["passa_filtro"] else "amostra fraca",
            }
            for i, r in enumerate(bons[:limite])
        ]


def listar_salvas(estrategia: str | None = None) -> list[dict]:
    """Minerações da estratégia pedida, mais recentes primeiro.

    Uma varredura de rompimento de canal não tem o que fazer na lista de um
    cruzamento de médias: os parâmetros não existem lá. A troca de estratégia
    é Input do callback que monta esta lista, para ela nunca ficar mostrando
    as da estratégia anterior.
    """
    where, args = "", []
    if estrategia:
        where, args = "WHERE strategy = ?", [estrategia]
    with db.connect(read_only=True) as con:
        linhas = con.execute(
            f"SELECT run_id, created_at, nome, n_combinacoes, status, strategy "
            f"FROM mining_runs {where} ORDER BY run_id DESC LIMIT 50", args
        ).fetchall()
    return [
        {"run_id": r[0],
         "estrategia": r[5],
         "rotulo": (f"#{r[0]} · {r[2] or 'sem nome'} · "
                    f"{r[3]:,} comb · {r[1]:%d/%m %H:%M}".replace(",", ".")
                    + ("" if r[4] == "concluida" else f" · {r[4]}"))}
        for r in linhas
    ]


def fim_otimizacao_salva(run_id: int) -> str | None:
    with db.connect(read_only=True) as con:
        r = con.execute("SELECT holdout_de FROM mining_runs WHERE run_id = ?",
                        [run_id]).fetchone()
    return r[0][:10] if r and r[0] and r[0] != "None" else None


def detalhes_salva(run_id: int) -> dict | None:
    """Contexto de uma mineração salva: estratégia, perfil e espaço varrido.

    A tabela sozinha não basta para reproduzir a varredura. O perfil de
    execução (timeframe, custos, janela, gestão) foi gravado junto por um
    motivo: sem ele, clicar numa combinação roda o backtest com o que está
    na tela AGORA, que pode ser outra coisa - e os números não batem com a
    linha clicada.
    """
    with db.connect(read_only=True) as con:
        r = con.execute(
            "SELECT strategy, profile, space, holdout_de, nome, folds, wf_config, "
            "criterios, symbol "
            "FROM mining_runs WHERE run_id = ?", [run_id]
        ).fetchone()
    if not r:
        return None
    folds = json.loads(r[5]) if r[5] else []
    wf_config = json.loads(r[6]) if r[6] else _wf_dos_folds(folds, r[3])
    return {
        "estrategia": r[0],
        "perfil": json.loads(r[1]) if r[1] else {},
        "espaco": json.loads(r[2]) if r[2] else {},
        "holdout_de": r[3][:10] if r[3] and r[3] != "None" else None,
        "corte": r[3] if r[3] and r[3] != "None" else None,
        "nome": r[4],
        "folds": folds,
        "wf_config": wf_config,
        # None nas minerações salvas antes da coluna existir
        "criterios": json.loads(r[7]) if r[7] else None,
        # o ativo em que a mineração varreu — o walk-forward usa ESTE, e não o
        # que estiver na barra do topo
        "symbol": r[8],
    }


def _wf_dos_folds(folds: list, holdout_de: str | None) -> dict:
    """Runs gravadas antes da coluna `wf_config` existir: reconstrói o que dá
    a partir das janelas. O holdout não sai daqui — vem do corte gravado."""
    if not folds:
        return {}
    import numpy as np
    def meses(a, b):
        return int(round((np.datetime64(b) - np.datetime64(a))
                         / np.timedelta64(30, "D")))
    f0 = folds[0]
    out = {"treino_meses": meses(f0["treino_de"], f0["treino_ate"]),
           "teste_meses": meses(f0["teste_de"], f0["teste_ate"])}
    if len(folds) > 1:
        out["passo_meses"] = meses(f0["treino_de"], folds[1]["treino_de"])
    return out


def faixas_do_espaco(espaco: dict) -> dict[str, dict]:
    """Converte o espaço gravado de volta em faixas de / passo / até.

    Um parâmetro com um valor só não foi minerado: volta desmarcado, com o
    valor fixo. Com vários, volta marcado e com a faixa reconstruída.
    """
    out: dict[str, dict] = {}
    for nome, vals in espaco.items():
        vals = sorted(set(vals))
        if len(vals) <= 1:
            out[nome] = {"on": False, "valor": vals[0] if vals else None}
            continue
        passos = {round(b - a, 6) for a, b in zip(vals, vals[1:])}
        out[nome] = {
            "on": True, "valor": vals[0], "de": vals[0], "ate": vals[-1],
            # grade irregular (raro): usa o menor passo, que reproduz a faixa
            # inteira mesmo que gere alguns pontos a mais
            "passo": min(passos),
        }
    return out


def carregar_salva(run_id: int) -> list[dict]:
    """Traz uma mineração do banco de volta para a tela.

    Devolve linhas no mesmo formato de `_ranking`, para que a tabela e a nuvem
    não saibam a diferença entre uma varredura recém-rodada e uma recuperada.
    """
    with db.connect(read_only=True) as con:
        linhas = con.execute(
            "SELECT trial_id, params, trades, lucro, profit_factor, max_dd, "
            "folds_positivos, folds_com_trades, mediana_fold, score, "
            "score_robusto, passa_filtro "
            "FROM mining_trials WHERE run_id = ? AND erro IS NULL "
            "ORDER BY coalesce(score_robusto, score) DESC NULLS LAST",
            [run_id],
        ).fetchall()

    out = []
    for i, r in enumerate(linhas):
        params = json.loads(r[1])
        out.append({
            "n": i + 1, "trial_id": r[0], "params": params,
            "params_txt": " · ".join(f"{k}={v}" for k, v in params.items()),
            "trades": r[2], "lucro": _num(r[3]), "pf": _num(r[4]),
            "dd": _num(r[5]),
            "fr": (round(r[3] / r[5], 2) if r[3] is not None and r[5] else None),
            "folds": f"{r[6]}/{r[7]}",
            "consistencia": round((r[6] / r[7] * 100) if r[7] else 0.0, 1),
            "mediana_fold": _num(r[8]), "score": _num(r[9]),
            "robusto": _num(r[10] if r[10] is not None else r[9]),
            "filtro": "ok" if r[11] else "amostra fraca",
        })
    return out


COLUNAS_TRIALS = ("run_id", "trial_id", "params", "trades", "lucro",
                  "profit_factor", "max_dd", "folds_com_trades",
                  "folds_positivos", "mediana_fold", "holdout_trades",
                  "holdout_lucro", "score", "passa_filtro", "erro",
                  "score_robusto")


def _inserir_trials(con, run_id: int, linhas: list[tuple]) -> None:
    """As combinações de uma mineração, de uma vez, com colunas nomeadas."""
    import pyarrow as pa

    if not linhas:
        return
    colunas = list(zip(*linhas))
    tabela = pa.table({nome: list(vals) for nome, vals in zip(COLUNAS_TRIALS, colunas)})
    tabela = tabela.set_column(0, "run_id", pa.array([run_id] * len(linhas), pa.int64()))
    con.register("_trials_novos", tabela)
    try:
        cols = ", ".join(COLUNAS_TRIALS)
        con.execute(f"INSERT OR REPLACE INTO mining_trials ({cols}) "
                    f"SELECT {cols} FROM _trials_novos")
    finally:
        con.unregister("_trials_novos")


def sanear_runs_orfas() -> int:
    """Fecha runs que ficaram marcadas como 'rodando' de um processo morto.

    Chamada no arranque da aplicação: se o processo está subindo agora, não
    existe mineração em andamento — qualquer 'rodando' no banco é resto de
    uma execução que morreu (crash, janela fechada, servidor reiniciado).
    Sem isto elas ficam ali para sempre, e o histórico mente.
    """
    with db.connect_write() as con:
        # Gravações de ANTES da transação podem ter parado no meio: o run
        # dizia 'concluida' com parte das combinações. Quem tem menos
        # combinações gravadas do que declarou vira 'incompleta'.
        incompletas = con.execute(
            """
            UPDATE mining_runs SET status = 'incompleta'
            WHERE status IN ('concluida', 'interrompida')
              AND n_combinacoes > (SELECT count(*) FROM mining_trials t
                                   WHERE t.run_id = mining_runs.run_id)
            RETURNING run_id
            """).fetchall()
        orfas = con.execute(
            "SELECT count(*) FROM mining_runs WHERE status = 'rodando'"
        ).fetchone()[0] + len(incompletas)
        if orfas:
            con.execute(
                """
                UPDATE mining_runs SET status =
                    CASE WHEN run_id IN (SELECT DISTINCT run_id FROM mining_trials)
                         THEN 'interrompida' ELSE 'abandonada' END
                WHERE status = 'rodando'
                """
            )
    return orfas


MINERACAO = Mineracao()


def excluir_salva(run_id: int) -> bool:
    """Apaga uma mineracao e todos os trials dela.

    A mineracao e exploratoria: dezenas de varreduras ate achar cluster, e a
    maioria e lixo que so foi salva por engano ou deixou de interessar. Sem
    poder apagar, a lista vira um deposito e o seletor deixa de servir.

    O historico de BARRAS continua intocado - o que se apaga aqui e um
    resultado de busca, nao dado de mercado.
    """
    with db.connect_write() as con, db.transacao(con):
        con.execute("DELETE FROM mining_trials WHERE run_id = ?", [run_id])
        # os TRADES dos walk-forwards dela antes dos registros: apagar só
        # `wfa_runs` deixava todos os trades órfãos (551 na #40)
        con.execute("DELETE FROM wfa_trades WHERE wfa_id IN "
                    "(SELECT wfa_id FROM wfa_runs WHERE run_id = ?)", [run_id])
        con.execute("DELETE FROM wfa_runs WHERE run_id = ?", [run_id])
        con.execute("DELETE FROM mining_runs WHERE run_id = ?", [run_id])
    return True
