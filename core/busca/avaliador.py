"""O trabalho de um núcleo: avaliar combinações com a conta da Varredura.

Cada núcleo é um processo que carrega as barras uma vez (do Parquet — nunca
do banco principal, que a captura grava) e guarda os últimos sinais
preparados. O motor manda ao mesmo núcleo as combinações do mesmo sinal
(`chave_essencial`), então o caro (agregar, calcular o indicador) é feito
uma vez e o resto — janela, dias, direção, stop, alvo — roda por cima.

A nota é `optimizer.avaliar_resultado`, a mesma da linha da Varredura: o
número de um nicho tem de bater exatamente com o que a Varredura mostraria.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

import numpy as np

from core import ativo, db_manager as db
from core import optimizer
from core.engine.execution import build_session_arrays, executar, preparar, relogio

from .espaco import Combinacao, Espaco

# meta da busca -> campo do resumo `geral` (período de otimização, holdout fora)
METAS = {"fr": "fator_recuperacao", "pf": "profit_factor", "lucro": "lucro",
         "dd": "max_dd"}
TETO_OBJETIVO = 1e6          # FR/PF infinitos (nenhuma perda) viram isto
INVALIDA = -1e9              # abaixo do mínimo: nunca bate uma válida
N_PREPARADOS = 4

_BARS: dict | None = None
_INST: dict | None = None
_MOD = None
_PREPS: OrderedDict = OrderedDict()
_ESPACOS: dict = {}


def iniciar_nucleo(simbolo: str, de, ate, estrategia: str) -> None:
    """Barras do espelho Parquet, como os workers da Varredura (`optimizer._init`)."""
    global _BARS, _INST, _MOD
    from strategies import registry

    d = db.read_bars_parquet(simbolo, de, ate)
    _BARS = {
        "ts": np.asarray(d["ts"], dtype="datetime64[ns]"),
        **{c: np.ascontiguousarray(d[c], dtype=np.int64)
           for c in ("open", "high", "low", "close", "tick_volume", "volume")},
    }
    _INST = db.load_instrument_yaml(simbolo)
    _MOD = registry.carregar(estrategia)
    _PREPS.clear()
    _ESPACOS.clear()


def _preparado(chave: tuple):
    if chave in _PREPS:
        _PREPS.move_to_end(chave)
        return _PREPS[chave]
    tf, params = chave
    prep = preparar(_BARS, _MOD, dict(params), tf, _INST)
    _PREPS[chave] = prep
    while len(_PREPS) > N_PREPARADOS:
        _PREPS.popitem(last=False)
    return prep


def _espaco(d: dict) -> Espaco:
    k = json.dumps(d, sort_keys=True)
    if k not in _ESPACOS:
        _ESPACOS[k] = Espaco.de_json(d)
    return _ESPACOS[k]


def objetivo(aval: dict, criterio: str, minimo: int) -> tuple[float, bool]:
    """O número que a pyribs persegue, e se a combinação vale como campeã.

    Válida = mínimo de trades no período de otimização E o filtro da Varredura
    (presença em quase todos os períodos). Inválida vale `INVALIDA + trades`:
    a busca ainda prefere quem chega mais perto do mínimo, sem que nenhuma
    inválida passe à frente de uma válida.
    """
    g = aval.get("geral") or {}
    trades = int(g.get("trades", 0))
    valida = trades >= minimo and bool(aval.get("passa_filtro"))
    if not valida:
        return INVALIDA + trades, False
    v = float(g.get(METAS[criterio], 0.0))
    if criterio == "dd":
        v = -v
    if np.isnan(v):
        return INVALIDA + trades, False
    return float(np.clip(v, -TETO_OBJETIVO, TETO_OBJETIVO)), True


def teto_de_trades(prep, perfil, fim_otimizacao) -> int:
    """Limite superior EXATO de trades no período de otimização.

    Toda entrada nasce de um sinal na barra i com `arm_window[i]` (dentro da
    janela e do dia) e executa em i+1; virar a mão também. Filtro ADX, horas
    sem entrada e limites diários só tiram entradas. Então nº de minutos com
    sinal do lado pedido, armados, antes do fim da otimização >= trades.
    Como a janela e os dias são os da PRÓPRIA combinação, nada é descartado
    por ser ruim no dia inteiro (desenho §4.3).
    """
    perfil_m = ativo.perfil_para_motor(perfil, prep.ficha)
    rel = prep.cache.get(("relogio",))
    if rel is None:
        rel = relogio(prep.bars["ts"])
    sess = build_session_arrays(prep.bars["ts"], perfil_m, rel)
    s = prep.sinais
    if perfil.direcao == "compra":
        sinal = s.entry_long
    elif perfil.direcao == "venda":
        sinal = s.entry_short
    else:
        sinal = s.entry_long | s.entry_short
    antes = prep.bars["ts"] < np.datetime64(fim_otimizacao, "ns")
    return int(np.count_nonzero(sinal & sess.arm_window & antes))


def _hash_trades(res) -> str:
    h = hashlib.sha1()
    for c in ("entry_i", "side", "exit_i"):
        h.update(np.ascontiguousarray(res.trades[c]).astype(np.int64).tobytes())
    return h.hexdigest()


def _num(v):
    v = float(v)
    return v if np.isfinite(v) else None


def avaliar_grupo(chave_essencial: tuple, tarefas: list[tuple[int, str]],
                  ctx: dict) -> list[dict]:
    """Avalia combinações do mesmo sinal. `tarefas` = [(teste_n, chave)].

    ctx = {"espaco": dict, "perfil_base": dict, "janelas": Janelas,
           "minimo": int, "criterio": str}
    """
    esp = _espaco(ctx["espaco"])
    janelas = ctx["janelas"]
    prep = _preparado(chave_essencial)
    out = []
    for teste_n, chave in tarefas:
        c = Combinacao.de_chave(chave)
        perfil = esp.perfil(c, ctx["perfil_base"])
        params = esp.params(c)
        r = {"teste_n": teste_n, "combo": chave,
             "casa": json.dumps(list(esp.casa(c))), "descartada": None,
             "trades_hash": None, "aval": None}
        try:
            if teto_de_trades(prep, perfil, janelas.fim_otimizacao) < ctx["minimo"]:
                r.update(descartada="poucos sinais", objetivo=INVALIDA, valida=False)
                out.append(r)
                continue
            res = executar(prep, perfil)
            aval = optimizer.avaliar_resultado(res, perfil, janelas, teste_n, params)
            obj, valida = objetivo(aval, ctx["criterio"], ctx["minimo"])
            g = aval["geral"]
            r.update(aval=aval, objetivo=obj, valida=valida,
                     trades_hash=_hash_trades(res), trades=int(g["trades"]),
                     lucro=_num(g["lucro"]), pf=_num(g["profit_factor"]),
                     dd=_num(g["max_dd"]), fr=_num(g["fator_recuperacao"]),
                     consistencia=_num(aval["consistencia"]),
                     mediana_fold=_num(aval["folds"]["mediana_lucro"]),
                     score=_num(aval["score"]))
        except Exception as erro:   # uma combinação ruim não derruba o lote
            r.update(descartada=f"erro: {erro}", objetivo=INVALIDA, valida=False)
        out.append(r)
    return out

