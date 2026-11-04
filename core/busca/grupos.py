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
"""

from __future__ import annotations

import numpy as np

from .espaco import Combinacao, Espaco

DEGRAUS_PARAM = 2
DEGRAUS_GESTAO = 2
DEGRAUS_JANELA = 1
DIAS_DIFERENTES = 1
MAX_MEMBROS_GUARDADOS = 200


def _indice(lista, v) -> int:
    try:
        return lista.index(v)
    except ValueError:
        return -10**6        # fora da lista (espaço mudou): nunca parecido


def _traco(c: Combinacao, esp: Espaco) -> tuple[tuple, np.ndarray, int]:
    """(balde, vetor de degraus, máscara dos dias) de uma combinação."""
    balde = (c.timeframe, c.direcao, c.stop_tipo, c.alvo_tipo)
    p = dict(c.params)
    vet = [_indice(esp.params_vals[n], p.get(n)) for n in esp.nomes_params]
    vet += [_indice(esp.stops.get(c.stop_tipo, []), c.stop_valor),
            _indice(esp.alvos.get(c.alvo_tipo, []), c.alvo_valor),
            _indice(esp.horarios, c.ini), _indice(esp.horarios, c.fim)]
    dias = sum(1 << (d - 1) for d in c.dias)
    return balde, np.array(vet, dtype=np.int64), dias


def _limites(esp: Espaco) -> np.ndarray:
    return np.array([DEGRAUS_PARAM] * len(esp.nomes_params)
                    + [DEGRAUS_GESTAO, DEGRAUS_GESTAO, DEGRAUS_JANELA, DEGRAUS_JANELA])


def _bits(x: np.ndarray) -> np.ndarray:
    return np.array([bin(int(v)).count("1") for v in x], dtype=np.int64) \
        if x.ndim else np.int64(bin(int(x)).count("1"))


def parecidas(a: Combinacao, b: Combinacao, esp: Espaco) -> bool:
    ba, va, da = _traco(a, esp)
    bb, vb, db = _traco(b, esp)
    return (ba == bb and bool(np.all(np.abs(va - vb) <= _limites(esp)))
            and bin(da ^ db).count("1") <= DIAS_DIFERENTES)


class _Balde:
    """As combinações de um mesmo (tempo, direção, tipos de stop e alvo),
    como matriz: o teste de "parecida" com um líder vira uma conta só."""

    def __init__(self):
        self.vets, self.dias, self.linhas = [], [], []

    def fechar(self):
        self.V = np.array(self.vets, dtype=np.int64).reshape(len(self.vets), -1)
        self.D = np.array(self.dias, dtype=np.int64)
        return self

    def parecidas_com(self, vet: np.ndarray, dias: int, lim: np.ndarray) -> np.ndarray:
        if not len(self.linhas):
            return np.zeros(0, dtype=bool)
        perto = np.all(np.abs(self.V - vet) <= lim, axis=1)
        return perto & (_bits(self.D ^ dias) <= DIAS_DIFERENTES)


def agrupar(elites: list[dict], combos: list[dict], esp: Espaco) -> list[dict]:
    """`elites` e `combos` como o banco devolve (com `combo` = chave).

    Devolve os grupos em ordem de nota do líder:
    {grupo_id, lider_casa, lider, casas, membros (os melhores, até 200),
     n_membros, mediana_obj}.
    """
    lim = _limites(esp)
    baldes: dict[tuple, _Balde] = {}
    for c in combos:
        if not c.get("valida"):
            continue
        balde, vet, dias = _traco(Combinacao.de_chave(c["combo"]), esp)
        b = baldes.setdefault(balde, _Balde())
        b.vets.append(vet)
        b.dias.append(dias)
        b.linhas.append(c)
    for b in baldes.values():
        b.fechar()

    grupos: list[dict] = []
    tracos: list[tuple] = []
    validas = sorted((e for e in elites if e.get("valida")),
                     key=lambda e: e["objetivo"], reverse=True)
    for e in validas:
        balde, vet, dias = _traco(Combinacao.de_chave(e["combo"]), esp)
        dono = None
        for g, (gb, gv, gd) in zip(grupos, tracos):
            if gb == balde and np.all(np.abs(gv - vet) <= lim) \
                    and bin(gd ^ dias).count("1") <= DIAS_DIFERENTES:
                dono = g
                break
        if dono is not None:
            dono["casas"].append(e["casa"])
            continue
        grupos.append({"grupo_id": len(grupos) + 1, "lider_casa": e["casa"],
                       "lider": e, "casas": [e["casa"]]})
        tracos.append((balde, vet, dias))

    for g, (gb, gv, gd) in zip(grupos, tracos):
        b = baldes.get(gb)
        membros = []
        if b is not None:
            idx = np.flatnonzero(b.parecidas_com(gv, gd, lim))
            por_hash: dict = {}
            for i in idx:
                m = b.linhas[i]
                h = m.get("trades_hash") or m["combo"]
                if h not in por_hash or m["objetivo"] > por_hash[h]["objetivo"]:
                    por_hash[h] = m
            membros = sorted(por_hash.values(), key=lambda m: m["objetivo"], reverse=True)
        objs = [m["objetivo"] for m in membros]
        g["n_membros"] = len(membros)
        g["mediana_obj"] = float(np.median(objs)) if objs else None
        g["membros"] = [{k: m.get(k) for k in ("combo", "casa", "objetivo", "trades",
                                              "lucro", "pf", "dd", "fr", "trades_hash")}
                        for m in membros[:MAX_MEMBROS_GUARDADOS]]
    return grupos
