"""Grupos: campeões parecidos viram um só (desenho §4.6).

Anti-objetivo do desenho: "lista com 30 variações do mesmo ponto". O mapa
mostra uma elite por casa, mas casas vizinhas costumam ter a MESMA ideia com
o horário meia hora deslocado. O grupo junta isso e diz se a região é sólida:
quantas combinações parecidas também passaram e a mediana delas.

"Parecidas", medido em degraus da lista que a busca percorreu (não em
valores: 2 pontos de stop no MES são muito, no WIN nada):
  - mesmo tempo gráfico, direção, tipo de stop e tipo de alvo;
  - cada parâmetro da estratégia a no máximo 2 degraus;
  - valor do stop e do alvo a no máximo 2 degraus;
  - início e fim da janela a no máximo 1 degrau;
  - dias com no máximo 1 dia de diferença.

O líder é a elite de maior nota; cada elite entra no primeiro grupo cujo
líder se parece com ela, senão abre o seu. Membros são TODAS as combinações
válidas testadas parecidas com o líder, contando uma vez cada conjunto de
trades idêntico (`trades_hash`: dois parâmetros que dão os mesmos trades não
são dois membros).

CUSTO. Uma noite gera centenas de milhares de elites e milhões de
combinações; comparar todas com todas levaria horas. Como início, fim e dias
têm de estar a 1 degrau, cada combinação mora numa CÉLULA (balde, início,
fim, dias) e só se compara com as 3 × 3 × 6 células vizinhas — o resto é
vetor contra matriz no NumPy.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .espaco import Combinacao, Espaco

DEGRAUS_PARAM = 2
DEGRAUS_GESTAO = 2
DEGRAUS_JANELA = 1
DIAS_DIFERENTES = 1
MAX_MEMBROS_GUARDADOS = 200
FORA = -10**6            # valor fora da lista (espaço mudou): nunca parecido

_BITS = np.array([bin(i).count("1") for i in range(32)], dtype=np.int64)


class _Indices:
    """Posição de cada valor nas listas do espaço, em dicionário (list.index
    em milhões de combinações era o gargalo)."""

    def __init__(self, esp: Espaco):
        self.params = {n: {v: i for i, v in enumerate(esp.params_vals[n])}
                       for n in esp.nomes_params}
        self.stops = {t: {v: i for i, v in enumerate(vs)} for t, vs in esp.stops.items()}
        self.alvos = {t: {v: i for i, v in enumerate(vs)} for t, vs in esp.alvos.items()}
        self.horas = {v: i for i, v in enumerate(esp.horarios)}
        self.nomes = esp.nomes_params
        self.per_stop = {v: i for i, v in enumerate(esp.stop_periodos or [])}
        self.per_alvo = {v: i for i, v in enumerate(esp.alvo_periodos or [])}


def _traco(c: Combinacao, ix: _Indices) -> tuple[tuple, np.ndarray, int]:
    """(balde, vetor de degraus, máscara dos dias). O vetor termina em
    (início, fim) da janela."""
    balde = (c.timeframe, c.direcao, c.stop_tipo, c.alvo_tipo)
    p = dict(c.params)
    vet = [ix.params[n].get(p.get(n), FORA) for n in ix.nomes]
    vet += [ix.stops.get(c.stop_tipo, {}).get(c.stop_valor, FORA),
            ix.alvos.get(c.alvo_tipo, {}).get(c.alvo_valor, FORA),
            # período do ATR (-1 sem ATR: igual entre combinações sem ele)
            ix.per_stop.get(c.stop_atr_periodo, -1), ix.per_alvo.get(c.alvo_atr_periodo, -1),
            ix.horas.get(c.ini, FORA), ix.horas.get(c.fim, FORA)]
    dias = sum(1 << (d - 1) for d in c.dias)
    return balde, np.array(vet, dtype=np.int64), dias


def _limites(n_params: int) -> np.ndarray:
    return np.array([DEGRAUS_PARAM] * n_params
                    + [DEGRAUS_GESTAO, DEGRAUS_GESTAO, DEGRAUS_PARAM, DEGRAUS_PARAM,
                       DEGRAUS_JANELA, DEGRAUS_JANELA])


def parecidas(a: Combinacao, b: Combinacao, esp: Espaco) -> bool:
    ix = _Indices(esp)
    ba, va, da = _traco(a, ix)
    bb, vb, db = _traco(b, ix)
    return (ba == bb and bool(np.all(np.abs(va - vb) <= _limites(len(ix.nomes))))
            and _BITS[da ^ db] <= DIAS_DIFERENTES)


def _celula(balde, vet, dias) -> tuple:
    return (balde, int(vet[-2]), int(vet[-1]), dias)


def _vizinhas(balde, vet, dias):
    ini, fim = int(vet[-2]), int(vet[-1])
    mascaras = [dias] + [dias ^ (1 << k) for k in range(5)]
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for m in mascaras:
                yield (balde, ini + di, fim + dj, m)


class _Tabela:
    """Itens (vetor + linha) indexados por célula, com a matriz montada uma
    vez para o teste vetorizado."""

    def __init__(self):
        self.vets, self.linhas = [], []
        self.por_celula: dict[tuple, list[int]] = defaultdict(list)

    def por(self, balde, vet, dias, linha):
        self.por_celula[_celula(balde, vet, dias)].append(len(self.linhas))
        self.vets.append(vet)
        self.linhas.append(linha)

    def fechar(self, d: int):
        self.V = np.array(self.vets, dtype=np.int64).reshape(len(self.vets), d)
        self.por_celula = {k: np.array(v, dtype=np.int64) for k, v in self.por_celula.items()}
        return self

    def parecidos(self, balde, vet, dias, lim) -> np.ndarray:
        cand = [self.por_celula[k] for k in _vizinhas(balde, vet, dias)
                if k in self.por_celula]
        if not cand:
            return np.zeros(0, dtype=np.int64)
        idx = np.concatenate(cand)
        ok = np.all(np.abs(self.V[idx] - vet) <= lim, axis=1)
        return idx[ok]


def _resumo_membros(membros: list[dict], esp: Espaco, lider: Combinacao) -> dict:
    """Mediana de FR e faixa de cada item numérico sobre TODOS os membros —
    só os 200 melhores ficam guardados, e a mediana deles enganaria (viraria
    "região sólida" o pico isolado)."""
    frs = [m["fr"] for m in membros if m.get("fr") is not None]
    vals: dict[str, list] = defaultdict(list)
    for m in membros:
        c = Combinacao.de_chave(m["combo"])
        for n, v in c.params:
            if n != "saida":
                vals[n].append(v)
        if c.stop_tipo == lider.stop_tipo:
            vals["_stop"].append(c.stop_valor)
        if c.alvo_tipo == lider.alvo_tipo and c.alvo_tipo != "sem":
            vals["_alvo"].append(c.alvo_valor)
        if c.stop_atr_periodo is not None:
            vals["_stop_per"].append(c.stop_atr_periodo)
        if c.alvo_atr_periodo is not None:
            vals["_alvo_per"].append(c.alvo_atr_periodo)
    faixas = {n: [min(v), max(v), float(np.median(v))] for n, v in vals.items() if v}
    return {"mediana_fr": float(np.median(frs)) if frs else None, "faixas": faixas}


def agrupar(elites: list[dict], combos: list[dict], esp: Espaco) -> list[dict]:
    """`elites` e `combos` como o banco devolve (com `combo` = chave).

    Devolve os grupos em ordem de nota do líder:
    {grupo_id, lider_casa, lider, casas, membros (os melhores, até 200),
     n_membros, mediana_obj, mediana_fr, faixas}.
    """
    ix = _Indices(esp)
    d = len(ix.nomes) + 6
    lim = _limites(len(ix.nomes))

    tab = _Tabela()
    for c in combos:
        if c.get("valida"):
            balde, vet, dias = _traco(Combinacao.de_chave(c["combo"]), ix)
            tab.por(balde, vet, dias, c)
    tab.fechar(d)

    lideres = _Tabela()
    grupos: list[dict] = []
    tracos: list[tuple] = []
    validas = sorted((e for e in elites if e.get("valida")),
                     key=lambda e: e["objetivo"], reverse=True)
    for e in validas:
        balde, vet, dias = _traco(Combinacao.de_chave(e["combo"]), ix)
        cand = [lideres.por_celula[k] for k in _vizinhas(balde, vet, dias)
                if k in lideres.por_celula]
        dono = None
        if cand:
            idx = sorted(i for lista in cand for i in lista)
            V = np.array([lideres.vets[i] for i in idx], dtype=np.int64)
            ok = np.flatnonzero(np.all(np.abs(V - vet) <= lim, axis=1))
            if len(ok):
                dono = grupos[idx[ok[0]]]          # o líder mais antigo = maior nota
        if dono is not None:
            dono["casas"].append(e["casa"])
            continue
        lideres.por(balde, vet, dias, e)
        grupos.append({"grupo_id": len(grupos) + 1, "lider_casa": e["casa"],
                       "lider": e, "casas": [e["casa"]]})
        tracos.append((balde, vet, dias))

    for g, (balde, vet, dias) in zip(grupos, tracos):
        por_hash: dict = {}
        for i in tab.parecidos(balde, vet, dias, lim):
            m = tab.linhas[i]
            h = m.get("trades_hash") or m["combo"]
            if h not in por_hash or m["objetivo"] > por_hash[h]["objetivo"]:
                por_hash[h] = m
        membros = sorted(por_hash.values(), key=lambda m: m["objetivo"], reverse=True)
        objs = [m["objetivo"] for m in membros]
        g["n_membros"] = len(membros)
        g["mediana_obj"] = float(np.median(objs)) if objs else None
        g.update(_resumo_membros(membros, esp, Combinacao.de_chave(g["lider"]["combo"])))
        g["membros"] = [{k: m.get(k) for k in ("combo", "casa", "objetivo", "trades",
                                              "lucro", "pf", "dd", "fr", "trades_hash")}
                        for m in membros[:MAX_MEMBROS_GUARDADOS]]
    return grupos
