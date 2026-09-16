"""A ficha de uma configuração: tudo o que é preciso para operá-la.

Uma combinação vencedora não é só o punhado de parâmetros que a mineração
variou. Para colocá-la no mercado é preciso o ativo, o tempo gráfico, a
janela de horário, a direção, alvo e stop, os limites do dia, o custo, o
tamanho da posição — e errar qualquer um deles opera OUTRA estratégia.

Nada aqui é específico de uma estratégia. A ficha é montada de três fontes:

  - o `params_schema` da estratégia, com os rótulos dela;
  - TODOS os campos do `ExecutionProfile`, como foram gravados na mineração;
  - os parâmetros que a janela escolheu, que sobrescrevem os dois acima.

Um campo que a mineração variou ganha, embaixo do valor, a faixa testada e
onde o valor caiu nela.
"""

from __future__ import annotations

from dataclasses import MISSING, fields

import numpy as np
from dash import html

from core.engine.execution import ExecutionProfile

from . import catalogo as C
from .cartao import brl, dica, inteiro, num


# ----------------------------------------------------------- formatação
def valor(v) -> str:
    """Número sem o ".0" de ponto flutuante, no formato brasileiro."""
    if isinstance(v, bool) or not isinstance(v, (int, float, np.number)):
        return "—" if v is None else str(v)
    if float(v).is_integer():
        return inteiro(int(v))
    return num(float(v), 2)


def _dias(v) -> str:
    dias = sorted(int(x) for x in (v or []))
    if dias == [1, 2, 3, 4, 5]:
        return "seg a sex"
    nomes = dict((n, r) for r, n in C.DIAS)
    return " · ".join(nomes.get(d, str(d)) for d in dias) or "nenhum"


def formatar(campo: str, formato: str, v) -> str:
    if formato == "opcao":
        return next((r for r, x in C.OPCOES.get(campo, []) if x == v), str(v))
    if formato == "dias":
        return _dias(v)
    if formato == "brl":
        return "—" if v is None else brl(float(v))
    if formato in ("desliga", "brl_desliga", "pct_alvo") and not v:
        return "desligado"
    if formato == "brl_desliga":
        return brl(float(v))
    if formato == "pct_alvo":
        return f"{valor(v)}% do alvo"
    if formato == "ticks":
        return f"{valor(v)} tick" + ("" if v == 1 else "s")
    if formato == "texto":
        return str(v)
    return valor(v)


# --------------------------------------------------- posição na faixa
DICA_POSICAO = (
    "Em destaque, os parâmetros que a mineração VARREU. Embaixo de cada um, a "
    "faixa testada e onde o valor escolhido caiu nela. No meio, a otimização "
    "achou um ótimo cercado de vizinhos que também foram testados. NA BORDA "
    "é alerta: o melhor valor pode estar do lado de fora do que se testou — "
    "a faixa cortou o morro ao meio, e o que parece o pico é só a encosta. A "
    "saída não é aceitar o valor da borda, e sim minerar de novo alargando a "
    "faixa daquele lado. PERTO DA BORDA (último décimo da faixa) pede o "
    "mesmo cuidado: o vizinho do teto diz quase o mesmo que o teto.")


def _posicao(v, vals) -> html.Div:
    """Onde o valor caiu dentro do que a mineração varreu."""
    de, ate = vals[0], vals[-1]
    if not isinstance(v, (int, float, np.number)) or ate == de:
        return html.Span()
    pos = min(max((float(v) - de) / (ate - de), 0.0), 1.0)
    # "perto" é o último décimo da faixa: um 79 numa faixa que parou em 80
    # diz quase o mesmo que o próprio 80. Não "a um passo da borda" — numa
    # grade de três valores o do meio está a um passo das duas, e é
    # justamente o ótimo cercado de vizinhos testados
    if v <= de:
        rotulo, classe = "na borda de baixo", "pp-borda"
    elif v >= ate:
        rotulo, classe = "na borda de cima", "pp-borda"
    elif pos <= 0.1:
        rotulo, classe = f"perto da borda de baixo · {num(pos * 100, 0)}%", "pp-perto"
    elif pos >= 0.9:
        rotulo, classe = f"perto da borda de cima · {num(pos * 100, 0)}%", "pp-perto"
    else:
        rotulo, classe = f"{num(pos * 100, 0)}% da faixa", "pp-meio"
    return html.Div([
        html.Div(html.Span(className="pp-marca " + classe,
                           style={"left": f"{pos * 100:.1f}%"}),
                 className="pp-trilho"),
        html.Span(rotulo, className="pp-rotulo " + classe),
    ], className="pp-pos")


def _faixa(nome, v, espaco) -> html.Div | None:
    """A faixa minerada de um campo, ou nada se ele não foi minerado."""
    vals = sorted({float(x) for x in (espaco or {}).get(nome, [])
                   if isinstance(x, (int, float)) and not isinstance(x, bool)})
    if len(vals) < 2:
        return None
    passo = min(round(b - a, 6) for a, b in zip(vals, vals[1:]))
    return html.Div([
        html.Span(f"{valor(vals[0])} → {valor(vals[-1])} · passo {valor(passo)}",
                  className="fi-intervalo"),
        _posicao(v, vals),
    ], className="fi-faixa")


# ------------------------------------------------------------ montagem
def _linha(rotulo, texto, faixa=None, nome=None):
    return html.Div([
        html.Span(rotulo, className="fi-rotulo", title=nome or rotulo),
        html.Span(texto, className="fi-valor"),
        faixa,
    ], className="fi-linha" + (" fi-minerado" if faixa is not None else ""))


def _bloco(titulo, linhas):
    if not linhas:
        return None
    return html.Div([html.H4(titulo, className="fi-grupo"), *linhas],
                    className="fi-bloco")


def _padrao(f):
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:          # pragma: no cover
        return f.default_factory()
    return None


def perfil_efetivo(perfil: dict, params: dict) -> dict:
    """O perfil com que a janela opera: o padrão do motor, por cima o que a
    mineração gravou, por cima o que a janela escolheu."""
    campos = [f for f in fields(ExecutionProfile)]
    nomes = {f.name for f in campos}
    base = {f.name: _padrao(f) for f in campos}
    base.update({k: v for k, v in (perfil or {}).items() if k in nomes})
    base.update({k: v for k, v in (params or {}).items() if k in nomes})
    return base


def ficha(*, estrategia, params: dict, perfil: dict, espaco: dict,
          geral: dict[str, str] | None = None) -> html.Div:
    """A ficha inteira, em blocos.

    `estrategia` é o módulo (precisa de `params_schema`); `geral` são linhas
    livres do topo — ativo, mineração, o que o consumidor quiser mostrar.
    """
    efetivo = perfil_efetivo(perfil, params)
    nomes_perfil = set(efetivo)
    schema = getattr(estrategia, "params_schema", {}) or {}

    blocos = []
    if geral:
        blocos.append(_bloco("Geral", [_linha(k, v) for k, v in geral.items()]))

    # --- estratégia: o schema dá o rótulo; um parâmetro fora do schema
    # (estratégia que mudou depois da mineração) aparece com o nome cru
    linhas = []
    for nome, meta in schema.items():
        v = params.get(nome, meta.get("default"))
        linhas.append(_linha(meta.get("label", nome), valor(v),
                             _faixa(nome, v, espaco), nome))
    for nome, v in params.items():
        if nome not in schema and nome not in nomes_perfil:
            linhas.append(_linha(nome, valor(v), _faixa(nome, v, espaco), nome))
    blocos.append(_bloco("Estratégia", linhas))

    # --- execução: percorre os campos do PERFIL, não o catálogo
    por_grupo: dict[str, list] = {g: [] for g in C.GRUPOS}
    outros = []
    for nome, v in efetivo.items():
        entrada = C.CAMPOS.get(nome)
        if entrada is None:
            outros.append(_linha(nome, valor(v), _faixa(nome, v, espaco), nome))
            continue
        grupo, rotulo, formato, *cond = entrada
        if cond and efetivo.get(cond[0][0]) != cond[0][1]:
            continue          # ex.: ATR do alvo quando o alvo é em pontos
        por_grupo.setdefault(grupo, []).append(
            _linha(rotulo, formatar(nome, formato, v),
                   _faixa(nome, v, espaco), nome))
    blocos += [_bloco(g, ls) for g, ls in por_grupo.items()]
    blocos.append(_bloco("outros", outros))

    return html.Div([
        html.P(["parâmetros minerados em destaque, com a faixa testada e a "
                "posição do valor nela", dica(DICA_POSICAO)],
               className="fi-legenda"),
        html.Div([b for b in blocos if b is not None], className="fi-grade"),
    ], className="ficha")
