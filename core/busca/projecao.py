"""O que o mapa e a lista mostram, a partir do banco da busca.

A busca guarda uma elite por casa da grade FINA (tempo × início × fim × dias
× direção). O mapa mostra PROJEÇÕES: linhas = tempo gráfico, colunas = o eixo
escolhido (início da janela, combinação de dias ou direção), e cada casa
exibe a melhor elite entre as casas finas que caem nela. Trocar o eixo só
muda a projeção, nunca a busca (desenho §9).

Estados de uma casa projetada:
  "ok"     - tem elite válida (≥ mínimo de trades e filtro da Varredura);
  "poucos" - só testou combinações abaixo do mínimo (listrada no mapa);
  "vazia"  - nada testado ali ainda.
"""

from __future__ import annotations

import math

import numpy as np

from . import banco
from .avaliador import INVALIDA
from .espaco import Combinacao, Espaco
from .motor import BONS

EIXOS = ("horario", "dias", "direcao")
NOME_EIXO = {"horario": "Horário de entrada", "dias": "Dias da semana",
             "direcao": "Direção"}
DIAS = {1: "seg", 2: "ter", 3: "qua", 4: "qui", 5: "sex"}
DIRECAO = {"compra": "compra", "venda": "venda", "ambas": "as duas"}

# Paradas de cor do protótipo B (valor, cor): rosa no fraco, cinza neutro,
# ciano até o claro. Valor acima da última (inclusive o +inf de quem nunca
# perdeu) pinta com a cor da ponta.
CORES = {
    "fr": {"nome": "Fator de recuperação", "casas": 1,
           "paradas": [(0, "#B8345F"), (1.5, "#262A30"), (3, "#0C5F6E"),
                       (4.5, "#1AA3BA"), (6, "#8AF3FF")]},
    "pf": {"nome": "Profit factor", "casas": 2,
           "paradas": [(0.8, "#B8345F"), (1.1, "#262A30"), (1.25, "#0C5F6E"),
                       (1.4, "#1AA3BA"), (1.55, "#8AF3FF")]},
    "trades": {"nome": "Trades", "casas": 0,
               "paradas": [(400, "#262A30"), (1000, "#0C5F6E"), (1600, "#1AA3BA"),
                           (2200, "#8AF3FF")]},
}
FRACO = {"fr": 1.5, "pf": 1.1}


def rotulo_dias(dias, curto: bool = True) -> str:
    """(2, 3, 4) -> "ter–qui" (curto) ou "ter a qui"; (1, 3, 5) ->
    "seg, qua, sex" / "seg, qua e sex"; um dia só -> "ter"."""
    dias = sorted(dias)
    nomes = [DIAS[d] for d in dias]
    if len(dias) == 1:
        return nomes[0]
    if len(dias) >= 3 and dias == list(range(dias[0], dias[-1] + 1)):
        return f"{nomes[0]}–{nomes[-1]}" if curto else f"{nomes[0]} a {nomes[-1]}"
    if curto:
        return ", ".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def cor(metrica: str, valor) -> str | None:
    """Cor contínua entre as paradas (interpolação RGB, como o protótipo)."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    paradas = CORES[metrica]["paradas"]
    v = float(valor)
    if v <= paradas[0][0]:
        return paradas[0][1]
    for (a, ca), (b, cb) in zip(paradas, paradas[1:]):
        if v <= b:
            t = (v - a) / (b - a)
            x = [int(ca[i:i + 2], 16) for i in (1, 3, 5)]
            y = [int(cb[i:i + 2], 16) for i in (1, 3, 5)]
            return "#" + "".join(f"{round(p + (q - p) * t):02X}" for p, q in zip(x, y))
    return paradas[-1][1]


def _colunas(esp: Espaco, eixo: str) -> list:
    if eixo == "horario":
        return list(esp.inicios)
    if eixo == "dias":
        return [tuple(d) for d in esp.dias]
    return list(esp.direcoes)


def _rotulo_coluna(eixo: str, v) -> str:
    if eixo == "dias":
        return rotulo_dias(v)
    if eixo == "direcao":
        return DIRECAO.get(v, v)
    return v


def _valor_coluna(eixo: str, c: Combinacao):
    return {"horario": c.ini, "dias": tuple(c.dias), "direcao": c.direcao}[eixo]


def dims(c: Combinacao, eixo: str) -> list[tuple[str, str]]:
    """O que a casa não diz pelo eixo: direção, dias e horário do campeão."""
    out = []
    if eixo != "direcao":
        out.append(("Direção", DIRECAO.get(c.direcao, c.direcao)))
    if eixo != "dias":
        out.append(("Dias", rotulo_dias(c.dias, curto=False)))
    if eixo != "horario":
        out.append(("Horário", f"{c.ini} a {c.fim}"))
    return out


def _grupos_por_casa(busca_id: int) -> dict:
    out = {}
    for g in banco.ler_grupos(busca_id):
        for casa in g["casas"]:
            out[casa] = g
    return out


def mapa(busca_id: int, eixo: str = "horario", metrica: str = "fr") -> dict:
    b = banco.ler_busca(busca_id)
    esp = Espaco.de_json(b["config"]["espaco"])
    crit = b["config"].get("criterio", "fr")
    colunas = _colunas(esp, eixo)
    linhas = list(esp.timeframes)
    melhor: dict[tuple, dict] = {}
    for e in banco.ler_elites(busca_id):
        c = Combinacao.de_chave(e["combo"])
        k = (c.timeframe, _valor_coluna(eixo, c))
        atual = melhor.get(k)
        if atual is None or e["objetivo"] > atual["objetivo"]:
            melhor[k] = {**e, "_c": c}
    grupos = _grupos_por_casa(busca_id)
    corte = BONS.get(crit)
    validas = [m for m in melhor.values() if m["valida"]]
    campeao = max(validas, key=lambda m: m["objetivo"], default=None)

    casas = []
    for li, tf in enumerate(linhas):
        for ci, col in enumerate(colunas):
            m = melhor.get((tf, col))
            casa = {"linha": li, "coluna": ci, "estado": "vazia", "valor": None,
                    "cor": None, "trades": None, "membros": None, "mediana": None,
                    "melhor": False, "casa_fina": None, "dims": [], "fr": None, "pf": None}
            if m is not None:
                c = m["_c"]
                g = grupos.get(m["casa"])
                casa.update(casa_fina=m["casa"], trades=m["trades"], dims=dims(c, eixo),
                            fr=m["fr"], pf=m["pf"])
                if m["valida"]:
                    valor = {"fr": m["fr"], "pf": m["pf"], "trades": m["trades"]}[metrica]
                    if valor is None and metrica in ("fr", "pf"):
                        valor = float("inf")      # nunca perdeu: ponta da escala
                    casa.update(estado="ok", valor=valor, cor=cor(metrica, valor),
                                objetivo=m["objetivo"], melhor=m is campeao,
                                membros=g["n_membros"] if g else None,
                                mediana=g["mediana_obj"] if g else None)
                else:
                    casa.update(estado="poucos", trades=m["trades"]
                                if m["trades"] is not None else int(m["objetivo"] - INVALIDA))
            casas.append(casa)
    ok = [c for c in casas if c["estado"] == "ok"]
    return {"eixo": eixo, "metrica": metrica, "nome_eixo": NOME_EIXO[eixo],
            "linhas": linhas, "colunas": [_rotulo_coluna(eixo, v) for v in colunas],
            "casas": casas, "n_com_resultado": len(ok), "n_casas": len(casas),
            "bons": (sum(1 for c in ok if c["objetivo"] >= corte) if corte is not None
                     else None),
            "melhor": next((c for c in casas if c["melhor"]), None),
            "legenda": CORES[metrica]}


def evolucao(busca_id: int, casas_finas: list[str], pontos: int = 10) -> list[float]:
    """Como o melhor da casa subiu ao longo da busca (até `pontos` pontos)."""
    hist = [h for h in banco.ler_hist(busca_id)
            if h["casa"] in set(casas_finas) and h["objetivo"] > INVALIDA / 2]
    if not hist:
        return []
    hist.sort(key=lambda h: h["teste_n"])
    total = max(banco.ler_busca(busca_id)["distintos"], hist[-1]["teste_n"])
    marcas = np.linspace(total / pontos, total, pontos)
    out, i, atual = [], 0, None
    for t in marcas:
        while i < len(hist) and hist[i]["teste_n"] <= t:
            atual = hist[i]["objetivo"] if atual is None else max(atual, hist[i]["objetivo"])
            i += 1
        if atual is not None:
            out.append(float(atual))
    return out


def lista(busca_id: int, eixo: str = "horario", metrica: str = "fr") -> list[dict]:
    """Uma linha por casa projetada com resultado, na ordem do critério.
    (A tela reordena por FR, PF, trades ou membros.)"""
    m = mapa(busca_id, eixo, metrica)
    finas_por_proj: dict[tuple, list[str]] = {}
    b = banco.ler_busca(busca_id)
    esp = Espaco.de_json(b["config"]["espaco"])
    colunas = _colunas(esp, eixo)
    for e in banco.ler_elites(busca_id):
        c = Combinacao.de_chave(e["combo"])
        k = (esp.timeframes.index(c.timeframe), colunas.index(_valor_coluna(eixo, c)))
        finas_por_proj.setdefault(k, []).append(e["casa"])
    out = []
    for casa in m["casas"]:
        if casa["estado"] != "ok":
            continue
        out.append({**casa, "tf": m["linhas"][casa["linha"]],
                    "coluna_rotulo": m["colunas"][casa["coluna"]],
                    "evolucao": evolucao(busca_id, finas_por_proj.get(
                        (casa["linha"], casa["coluna"]), []))})
    out.sort(key=lambda c: c.get("objetivo", -1e18), reverse=True)
    return out


def e_bom(criterio: str, valor) -> bool | None:
    corte = BONS.get(criterio)
    return None if corte is None or valor is None else valor >= corte


def e_fraco(criterio: str, valor) -> bool | None:
    corte = FRACO.get(criterio)
    return None if corte is None or valor is None else valor < corte

