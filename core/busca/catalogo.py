"""O que a busca automática pode varrer, declarado num lugar só.

A tela de configuração, a busca e o relatório percorrem ESTA lista; nenhum
deles conhece um parâmetro pelo nome. Parâmetro novo da estratégia entra pelo
`params_schema`; parâmetro global novo (ex.: preço médio) entra como mais um
`Item` aqui. É o requisito de escala do desenho (§6).

Cada item diz a sua CAMADA. "essencial" muda o sinal e obriga a recalcular o
indicador (`engine.preparar`); "filtro" só roda por cima do sinal pronto
(`engine.executar`). É o que deixa a busca calcular uma vez e testar muitas.

As declarações por estratégia (que parâmetro anda em degrau proporcional)
moram aqui, e não no arquivo da estratégia: mexer no arquivo muda o
`codigo_hash`, e um plano operando na conta real passaria a acusar "código
mudou". Estratégia nova pode trazer `busca = {...}` no próprio módulo.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from core import ativo
from core.engine.execution import TIMEFRAMES as _TF_MOTOR

# Parâmetros de período: 250 e 251 dão quase o mesmo, então o degrau cresce
# com o valor (desenho §4.4).
POR_ESTRATEGIA: dict[str, dict] = {
    "adx_direcao": {"proporcional": ["di_periodo", "adx_suavizacao"]},
    "setup_cruzamento": {"proporcional": ["media_rapida", "media_lenta"]},
    "reversao_rsi": {"proporcional": ["periodo_rsi", "periodo_tendencia",
                                      "periodo_saida"]},
    "rompimento_abertura": {"proporcional": ["barras_abertura"]},
    "rompimento_ema_abertura": {"proporcional": ["ema_curta", "ema_longa"]},
    "rompimento_canal": {"proporcional": ["periodo_canal"]},
}

# Espelho do motor: todo tempo gráfico que o motor conhece entra aqui sozinho,
# em ordem de duração. Marcados de saída: de 2 a 30 minutos.
TIMEFRAMES = sorted(_TF_MOTOR, key=_TF_MOTOR.get)
TIMEFRAMES_LIGADOS = [t for t in TIMEFRAMES if 2 <= _TF_MOTOR[t] <= 30]
DIRECOES = ["compra", "venda", "ambas"]

# A sessão de ENTRADAS que a busca percorre. Nos micros é o pregão diurno de
# Nova York: a ficha vai de 18:00 a 16:30, atravessando a meia-noite, e uma
# janela "das 20:00 às 03:00" não é o que se procura aqui.
JANELA_PADRAO = {"WIN$N": ("09:00", "17:00")}
JANELA_CME = ("09:30", "16:00")
PASSO_JANELA = 30
JANELA_MINIMA = 30

# Stop e alvo em pontos do ativo sem `faixas` na ficha (o WIN), na escala dele.
# Largos de propósito (decisão do usuário, 04/11/2026): a busca não testa
# tudo, escolhe onde testar — faixa estreita só esconde trade bom de 1.200 pts.
PONTOS_SEM_FAIXA = {
    "stop_pontos": {"de": 50, "ate": 2000, "passo": 50},
    "alvo_pontos": {"de": 100, "ate": 4000, "passo": 100},
}
# Múltiplos e porcentagens valem para qualquer ativo.
STOP_TIPOS = {
    "atr": {"on": True, "de": 0.25, "ate": 6.0, "passo": 0.25},
    "percentual": {"on": True, "de": 0.05, "ate": 1.50, "passo": 0.05},
}
ALVO_TIPOS = {
    "multiplicador": {"on": True, "de": 0.5, "ate": 6.0, "passo": 0.5},
    "atr": {"on": True, "de": 0.5, "ate": 10.0, "passo": 0.25},
    "percentual": {"on": False, "de": 0.10, "ate": 3.0, "passo": 0.10},
    # alvo em pontos = 0: o kernel trata como "sem alvo"
    "sem": {"on": False},
}


@dataclass(frozen=True)
class Item:
    nome: str
    rotulo: str
    tipo: str      # "lista" | "inteiro" | "real" | "hora" | "dias" | "gestao"
    camada: str    # "essencial" | "filtro"
    degrau: str    # "fixo" | "proporcional" | "minutos" | "-"
    padrao: dict = field(hash=False, compare=False)
    onde: str = "perfil"   # "param" (params da estratégia) | "perfil" (camada 4)
    limites: tuple | None = None   # min/max duros do schema


def degraus_proporcionais(de: int, ate: int) -> list[int]:
    """Perto de zero anda de 1 em 1; lá em cima ~8% (250 -> 270)."""
    out, v = [], int(de)
    while v <= ate:
        out.append(v)
        v = max(v + 1, int(round(v * 1.08)))
    if out and out[-1] != ate and ate > out[-1]:
        out.append(int(ate))
    return out


def _grade(de, ate, passo, inteiro: bool) -> list:
    """Mesma régua de `optimizer.montar_espaco`: (2,3 - 2,0) / 0,1 dá
    2,9999… e o int() cortaria o último valor; arredondar antes."""
    if passo is None or passo <= 0 or ate < de:
        return [de]
    n = int(round((ate - de) / passo, 9)) + 1
    casas = max(len(f"{passo:.10f}".rstrip("0").split(".")[1]),
                len(f"{de:.10f}".rstrip("0").split(".")[1]))
    vals = [round(de + i * passo, casas) for i in range(n)]
    if inteiro:
        return sorted({int(round(v)) for v in vals})
    return vals


def _min(hhmm: str) -> int:
    return ativo.hora_para_minuto(hhmm)


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _mascaras(dias: list[int]) -> list[tuple[int, ...]]:
    """Toda combinação não vazia dos dias ligados: 1 dia, depois 2… e, dentro
    de cada tamanho, de segunda para sexta."""
    dias = sorted(dias)
    return [c for k in range(1, len(dias) + 1)
            for c in itertools.combinations(dias, k)]


def valores(item: Item, faixa: dict):
    """A lista que a busca percorre para `item` com a `faixa` da tela.

    Gestão (stop/alvo) devolve {tipo: [valores]} só dos tipos ligados.
    """
    if item.tipo == "lista":
        ligados = faixa.get("ligados", item.padrao.get("ligados", item.padrao["valores"]))
        return [v for v in item.padrao["valores"] if v in ligados]
    if item.tipo == "dias":
        return _mascaras(faixa.get("ligados", item.padrao["ligados"]))
    if item.tipo == "hora":
        de, ate = _min(faixa["de"]), _min(faixa["ate"])
        passo = int(faixa.get("passo") or PASSO_JANELA)
        return [_hhmm(m) for m in range(de, ate + 1, passo)]
    if item.tipo == "gestao":
        out = {}
        for tipo, f in (faixa.get("tipos") or {}).items():
            if not f.get("on"):
                continue
            if tipo == "sem":
                out[tipo] = [0]
            else:
                out[tipo] = _grade(f["de"], f["ate"], f["passo"],
                                   inteiro=(tipo == "pontos"))
        return out
    # inteiro / real
    de, ate = faixa["de"], faixa["ate"]
    if item.limites:
        lo, hi = item.limites
        de = max(de, lo) if lo is not None else de
        ate = min(ate, hi) if hi is not None else ate
    if item.degrau == "proporcional":
        return degraus_proporcionais(int(de), int(ate))
    return _grade(de, ate, faixa.get("passo", item.padrao.get("passo")),
                  inteiro=(item.tipo == "inteiro"))


def _declaracao(mod, estrategia: str) -> dict:
    return getattr(mod, "busca", None) or POR_ESTRATEGIA.get(estrategia, {})


def _janela_padrao(simbolo: str) -> tuple[str, str]:
    if simbolo in JANELA_PADRAO:
        return JANELA_PADRAO[simbolo]
    try:
        f = ativo.ficha(simbolo)
    except FileNotFoundError:
        return JANELA_PADRAO["WIN$N"]
    if f.sessao_abertura:
        return JANELA_CME
    p = f.perfil_padrao or {}
    return p.get("entrada_inicio", "09:00"), p.get("entrada_fim", "17:00")


def _pontos(faixas_ativo: dict, campo: str) -> dict:
    f = faixas_ativo.get(campo) or PONTOS_SEM_FAIXA[campo]
    return {"on": True, "de": f["de"], "ate": f["ate"], "passo": f["passo"]}


def montar_catalogo(estrategia: str, simbolo: str) -> list[Item]:
    """Itens na ordem da aba "Espaço de busca": tempo, direção, janela, dias,
    stop, alvo e os parâmetros da estratégia."""
    from strategies import registry

    mod = registry.carregar(estrategia)
    faixas_ativo = ativo.faixas_do_ativo(simbolo, estrategia)
    proporcionais = set(_declaracao(mod, estrategia).get("proporcional", []))
    ini, fim = _janela_padrao(simbolo)

    itens = [
        Item("timeframe", "Tempo gráfico", "lista", "essencial", "-",
             {"valores": TIMEFRAMES, "ligados": TIMEFRAMES_LIGADOS}),
        Item("direcao", "Direção", "lista", "filtro", "-",
             {"valores": DIRECOES, "ligados": DIRECOES}),
        Item("janela", "Horário de entrada", "hora", "filtro", "minutos",
             {"de": ini, "ate": fim, "passo": PASSO_JANELA, "minima": JANELA_MINIMA}),
        Item("dias", "Dias da semana", "dias", "filtro", "-",
             {"valores": [1, 2, 3, 4, 5], "ligados": [1, 2, 3, 4, 5]}),
        Item("stop", "Stop", "gestao", "filtro", "fixo",
             {"tipos": {"pontos": _pontos(faixas_ativo, "stop_pontos"),
                        **{k: dict(v) for k, v in STOP_TIPOS.items()}}}),
        Item("alvo", "Alvo", "gestao", "filtro", "fixo",
             {"tipos": {"pontos": _pontos(faixas_ativo, "alvo_pontos"),
                        **{k: dict(v) for k, v in ALVO_TIPOS.items()}}}),
    ]
    for nome, meta in mod.params_schema.items():
        lo, hi = meta.get("min"), meta.get("max")
        if nome == "saida":
            # modos de saída são categorias: varre todos, como chips
            modos = list(range(int(lo or 0), int(hi) + 1))
            itens.append(Item(nome, meta.get("label", nome), "lista", "essencial",
                              "-", {"valores": modos, "ligados": modos},
                              onde="param", limites=(lo, hi)))
            continue
        f = faixas_ativo.get(nome) or {}
        padrao = {"de": f.get("de", lo if lo is not None else meta["default"]),
                  "ate": f.get("ate", hi if hi is not None else meta["default"]),
                  "passo": f.get("passo", meta.get("step") or 1)}
        tipo = "inteiro" if meta.get("tipo", "int") == "int" else "real"
        degrau = "proporcional" if nome in proporcionais else "fixo"
        itens.append(Item(nome, meta.get("label", nome), tipo, "essencial", degrau,
                          padrao, onde="param", limites=(lo, hi)))
    return itens
