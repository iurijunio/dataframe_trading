"""O detalhe de um nicho (a gaveta) e a ponte para a Varredura e o Backtest.

Roda no processo do APP, só lendo o banco da busca e o Parquet; nunca
disputa nada com o processo da busca. Os backtests daqui (até 24 membros)
usam o mesmo `preparar`/`executar` da busca e o mesmo `metrics.monetize` da
Varredura — o FR do campeão na gaveta é o FR da elite.

Os membros vêm do GRUPO da elite (`grupos.py`): o que dá a ideia de região,
não de ponto. Sem grupo ainda (a busca reagrupa de tempos em tempos), o
detalhe usa só o campeão.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np

from core import ativo, metrics
from core.engine.execution import executar

from . import avaliador, banco
from .espaco import CAMPO_ALVO, CAMPO_STOP, Combinacao, Espaco

MAX_MEMBROS = 24
MIN_TRADES_HORA_DIA = 40
MAX_PONTOS_CURVA = 400

_CARREGADO: tuple | None = None


def _garantir_barras(c: dict) -> None:
    global _CARREGADO
    chave = (c["simbolo"], c["de"], c["ate"], c["estrategia"])
    if _CARREGADO != chave:
        avaliador.iniciar_nucleo(*chave)
        _CARREGADO = chave


def _contexto(busca_id: int):
    b = banco.ler_busca(busca_id)
    if b is None:
        raise ValueError(f"busca {busca_id} não existe")
    c = b["config"]
    return b, c, Espaco.de_json(c["espaco"])


def _grupo_da(busca_id: int, casa: str) -> dict | None:
    for g in banco.ler_grupos(busca_id):
        if casa in g["casas"]:
            return g
    return None


def _elite(busca_id: int, casa: str) -> dict:
    for e in banco.ler_elites(busca_id):
        if e["casa"] == casa:
            return e
    raise ValueError(f"casa {casa} sem elite")


def _membros(busca_id: int, elite: dict) -> tuple[list[dict], dict | None]:
    """Campeão primeiro, depois os melhores do grupo, sem repetir trades."""
    g = _grupo_da(busca_id, elite["casa"])
    vistos, out = set(), []
    for m in [elite, *((g or {}).get("membros") or [])]:
        k = m.get("trades_hash") or m["combo"]
        if k in vistos or m["combo"] in {x["combo"] for x in out}:
            continue
        vistos.add(k)
        out.append(m)
    return out, g


def _rodar(esp: Espaco, c: Combinacao, perfil_base: dict, **troca):
    perfil = esp.perfil(c, perfil_base)
    if troca:
        perfil = perfil.__class__(**{**perfil.to_config(), **troca})
    prep = avaliador._preparado(c.chave_essencial())
    res = executar(prep, perfil)
    liq = metrics.monetize(res)["liquido"] if res.n_trades else np.empty(0)
    return res, np.asarray(liq, dtype=float)


def _janelas(c: dict):
    from core import walkforward as wf

    return wf.montar_janelas(np.datetime64(c["de"], "s"), np.datetime64(c["ate"], "s"),
                             **c["wf_config"])


# --------------------------------------------------------------- partes
def _hora_dia(esp, campeao: Combinacao, membros, perfil_base, ficha, fim_otim, passo):
    """Média líquida por trade por degrau de hora de entrada × dia, com os
    membros rodando no horário INTEIRO e nos 5 dias: mostra onde a vantagem
    mora, dentro e fora da região do nicho."""
    ini0 = esp.inicios[0]
    fim0 = esp.fins_de[ini0][-1]
    desloc = ficha.deslocamento_min if ficha and ficha.sessao_abertura else 0
    soma: dict[tuple, list] = {}
    for m in membros:
        c = Combinacao.de_chave(m["combo"])
        res, liq = _rodar(esp, c, perfil_base, entrada_inicio=ini0, entrada_fim=fim0,
                          dias_semana=(1, 2, 3, 4, 5))
        if not len(liq):
            continue
        ts = res.trades["entry_ts"]
        dentro = ts < fim_otim
        minuto = (ts.astype("datetime64[m]").astype(np.int64) % 1440 - desloc) % 1440
        dow = ((ts.astype("datetime64[D]").astype(np.int64) + 3) % 7) + 1
        for mi, d, v, ok in zip(minuto, dow, liq, dentro):
            if ok:
                soma.setdefault((int(mi), int(d)), []).append(v)

    def hm(h):
        return ativo.hora_para_minuto(h)

    a, z = hm(campeao.ini), hm(campeao.fim)
    lo, hi = max(hm(esp.horarios[0]), a - passo), min(hm(esp.horarios[-1]), z + passo)
    horas = list(range(lo - (lo - hm(esp.horarios[0])) % passo, hi + 1, passo))
    valores, marca = [], []
    for h in horas:
        lv, lm = [], []
        for d in (1, 2, 3, 4, 5):
            vs = [v for (mi, dd), lista in soma.items() if dd == d and h <= mi < h + passo
                  for v in lista]
            lv.append(float(np.mean(vs)) if len(vs) >= MIN_TRADES_HORA_DIA else None)
            lm.append(a <= h <= z and d in campeao.dias)
        valores.append(lv)
        marca.append(lm)
    return {"horas": [f"{h // 60:02d}:{h % 60:02d}" for h in horas],
            "dias": ["seg", "ter", "qua", "qui", "sex"], "valores": valores,
            "dentro": marca}


def _por_ano(esp, membros, perfil_base, c_cfg, janelas):
    anos = range(int(c_cfg["de"][:4]), int(c_cfg["ate"][:4]) + 1)
    holdout = janelas.holdout_de
    lucros = {a: [] for a in anos}
    for m in membros:
        res, liq = _rodar(esp, Combinacao.de_chave(m["combo"]), perfil_base)
        if not len(liq):
            continue
        ts = res.trades["entry_ts"]
        dentro = ts < janelas.fim_otimizacao
        ano = ts.astype("datetime64[Y]").astype(np.int64) + 1970
        for a in anos:
            sel = dentro & (ano == a)
            if sel.any():
                lucros[a].append(float(liq[sel].sum()))
    out = []
    for a in anos:
        so_holdout = holdout is not None and np.datetime64(f"{a}-01-01", "s") >= holdout
        vs = lucros[a]
        out.append({"ano": a, "holdout": bool(so_holdout),
                    "pct_lucro": (None if so_holdout or not vs
                                  else round(100.0 * sum(v > 0 for v in vs) / len(vs)))})
    return out


def _espalhamento(esp, campeao: Combinacao, membros):
    combos = [Combinacao.de_chave(m["combo"]) for m in membros]
    itens = []

    def linha(rotulo, testada, vals, camp):
        vals = [v for v in vals if v is not None]
        if not vals or not testada:
            return
        itens.append({"item": rotulo, "testada": (min(testada), max(testada)),
                      "membros": (min(vals), max(vals)),
                      "mediana": float(np.median(vals)), "campeao": camp})

    for n in esp.nomes_params:
        if n == "saida":
            continue
        rot = esp.catalogo[n].rotulo
        linha(rot, esp.params_vals[n], [dict(c.params)[n] for c in combos],
              dict(campeao.params)[n])
    if campeao.stop_tipo in esp.stops:
        linha(f"Stop ({campeao.stop_tipo})", esp.stops[campeao.stop_tipo],
              [c.stop_valor for c in combos if c.stop_tipo == campeao.stop_tipo],
              campeao.stop_valor)
    if campeao.alvo_tipo in esp.alvos and campeao.alvo_tipo != "sem":
        linha(f"Alvo ({campeao.alvo_tipo})", esp.alvos[campeao.alvo_tipo],
              [c.alvo_valor for c in combos if c.alvo_tipo == campeao.alvo_tipo],
              campeao.alvo_valor)
    return itens


def _curva(esp, campeao, perfil_base, fim_otim):
    res, liq = _rodar(esp, campeao, perfil_base)
    if not len(liq):
        return {"x": [], "y": []}
    sel = res.trades["entry_ts"] < fim_otim
    ordem = np.argsort(res.trades["exit_ts"][sel], kind="stable")
    x = res.trades["exit_ts"][sel][ordem]
    y = np.cumsum(liq[sel][ordem])
    if len(y) > MAX_PONTOS_CURVA:
        idx = np.unique(np.linspace(0, len(y) - 1, MAX_PONTOS_CURVA).astype(int))
        x, y = x[idx], y[idx]
    return {"x": [str(v)[:10] for v in x], "y": [round(float(v), 2) for v in y]}


# --------------------------------------------------------------- públicas
def detalhe(busca_id: int, casa_fina: str) -> dict:
    b, c, esp = _contexto(busca_id)
    _garantir_barras(c)
    elite = _elite(busca_id, casa_fina)
    campeao = Combinacao.de_chave(elite["combo"])
    membros, grupo = _membros(busca_id, elite)
    uso = membros[:MAX_MEMBROS]
    janelas = _janelas(c)
    ficha = ativo.ficha(c["simbolo"]) if c["simbolo"] != "WIN$N" else None
    passo = int((esp.faixas.get("janela") or esp.catalogo["janela"].padrao)["passo"])
    frs = [m["fr"] for m in membros if m.get("fr") is not None]
    return {
        "busca_id": busca_id, "casa": casa_fina, "campeao": elite,
        "combinacao": json.loads(elite["combo"]),
        "kpis": {"fr": elite["fr"], "fr_mediano": float(np.median(frs)) if frs else None,
                 "pf": elite["pf"], "trades": elite["trades"], "maior_queda": elite["dd"],
                 "membros": grupo["n_membros"] if grupo else len(membros)},
        "hora_dia": _hora_dia(esp, campeao, uso, c["perfil_base"], ficha,
                              janelas.fim_otimizacao, passo),
        "por_ano": _por_ano(esp, uso, c["perfil_base"], c, janelas),
        "espalhamento": _espalhamento(esp, campeao, membros),
        "curva": _curva(esp, campeao, c["perfil_base"], janelas.fim_otimizacao),
        "moeda": ativo.moeda_de(c["simbolo"]),
        "versao_grupos": b.get("versao_grupos"),
        "calculado_em": datetime.now().isoformat(timespec="seconds"),
    }


def regiao_para_varredura(busca_id: int, casa_fina: str) -> dict:
    """Os campos do menu para minerar a região do nicho à mão: tempo, janela,
    dias e direção do campeão (janela de = menor início, até = maior fim dos
    membros) e, por campo minerável, a faixa dos membros com o passo da TELA
    (não o proporcional da busca)."""
    _b, c, esp = _contexto(busca_id)
    elite = _elite(busca_id, casa_fina)
    camp = Combinacao.de_chave(elite["combo"])
    membros, _g = _membros(busca_id, elite)
    combos = [Combinacao.de_chave(m["combo"]) for m in membros]
    mesmos = [x for x in combos if x.timeframe == camp.timeframe] or [camp]
    from strategies import registry

    schema = registry.carregar(c["estrategia"]).params_schema

    def faixa(vals, passo, valor):
        vals = sorted(set(vals))
        return {"on": len(vals) > 1, "de": vals[0], "ate": vals[-1], "passo": passo,
                "valor": valor}

    campos = {}
    for n in esp.nomes_params:
        campos[n] = faixa([dict(x.params)[n] for x in combos],
                          schema[n].get("step") or 1, dict(camp.params)[n])
    pst = (esp.faixas.get("stop") or esp.catalogo["stop"].padrao)["tipos"]
    campos[CAMPO_STOP[camp.stop_tipo]] = faixa(
        [x.stop_valor for x in combos if x.stop_tipo == camp.stop_tipo],
        pst[camp.stop_tipo]["passo"], camp.stop_valor)
    if camp.alvo_tipo == "sem":
        campos["alvo_pontos"] = {"on": False, "valor": 0}
    else:
        pal = (esp.faixas.get("alvo") or esp.catalogo["alvo"].padrao)["tipos"]
        campos[CAMPO_ALVO[camp.alvo_tipo]] = faixa(
            [x.alvo_valor for x in combos if x.alvo_tipo == camp.alvo_tipo],
            pal[camp.alvo_tipo]["passo"], camp.alvo_valor)
    return {"timeframe": camp.timeframe,
            "entrada_inicio": min(x.ini for x in mesmos),
            "entrada_fim": max(x.fim for x in mesmos),
            "dias_semana": list(camp.dias), "direcao": camp.direcao,
            "stop_tipo": camp.stop_tipo,
            "alvo_tipo": "pontos" if camp.alvo_tipo == "sem" else camp.alvo_tipo,
            "campos": campos, "simbolo": c["simbolo"], "estrategia": c["estrategia"]}


def campeao_para_backtest(busca_id: int, casa_fina: str) -> dict:
    _b, c, esp = _contexto(busca_id)
    camp = Combinacao.de_chave(_elite(busca_id, casa_fina)["combo"])
    return {"simbolo": c["simbolo"], "estrategia": c["estrategia"],
            "params": esp.params(camp),
            "perfil": esp.perfil(camp, c["perfil_base"]).to_config(),
            "de": c["de"], "ate": c["ate"],
            "fim_otimizacao": str(_janelas(c).fim_otimizacao)[:10]}
