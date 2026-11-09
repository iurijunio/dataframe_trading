"""Leitura: comparativo papel × backtest e alertas."""
from __future__ import annotations

import math
from datetime import date, datetime

from .. import papel as _papel
from .. import plano as _plano

from .base import _hoje, _ligacoes
from .pregao import _desde_o_plano, _plano_do_dia, _por_ligacao, _pregao
from .demo_resumo import _pregoes_demo, nomes


# ------------------------------------------------------------ comparativo
def _metricas(linhas) -> dict:
    """Médias por operação e por contrato de `(liquido, contratos, pontos)`.

    Por contrato porque o papel opera os contratos do plano e o WFA os do
    backtest (decisão 8): comparar o total seria comparar tamanhos.
    """
    linhas = [(float(l or 0.0), max(int(c or 1), 1), int(p or 0))
              for l, c, p in linhas]
    n = len(linhas)
    if n == 0:
        return {"n": 0, "resultado_por_contrato": None,
                "pontos_por_operacao": None, "fator_lucro": None,
                "acerto": None, "contratos_por_operacao": None, "total": 0.0}
    por_ctr = [l / c for l, c, _ in linhas]
    ganho = sum(v for v in por_ctr if v > 0)
    perda = -sum(v for v in por_ctr if v < 0)
    return {
        "n": n,
        "resultado_por_contrato": sum(por_ctr) / n,
        "pontos_por_operacao": sum(p for _, _, p in linhas) / n,
        # sem nenhuma perda o fator é infinito (como no Portfólio), não 0
        "fator_lucro": (ganho / perda if perda > 0
                        else (math.inf if ganho > 0 else None)),
        "acerto": sum(1 for v in por_ctr if v > 0) / n,
        "contratos_por_operacao": sum(c for _, c, _ in linhas) / n,
        "total": float(sum(l for l, _, _ in linhas)),
    }


def comparativo(con, portfolio_id: int, *, dia: date | None = None,
                hoje: date | None = None, origem: str = "demo") -> dict:
    """Esperado (WFA) × Papel × Demo × Real (spec §6.7, decisão 9).

    Esperado = os trades fora da amostra do walk-forward que gerou cada
    plano em vigor. Papel = **só as operações fechadas** que contam, desde
    o plano em vigor: a aberta ainda não tem resultado, e média de
    operação por fazer não compara com trade do WFA. Por isso o `total`
    daqui pode ser menor que o `acumulado` do `resumo`, que inclui a aberta
    provisória — a (?) da tela explica.

    Demo = as operações da conta demo pelo mesmo recorte do papel (fechadas,
    desde o plano em vigor de cada ligação), líquidas dos custos do plano
    como o papel, e mais as linhas de execução (`_demo_do_comparativo`).
    None quando o portfólio nunca operou na demo. Real fica para depois.

    `dia`: o pregão que a tela mostra (ver `curva_vs_esperado`).
    """
    dia = dia or _hoje(hoje)
    wfas: set[int] = set()
    papel = []
    planos: dict[int, dict] = {}
    for l in _ligacoes(con, portfolio_id, dia):
        gravado = _pregao(con, l["ligacao_id"], dia)[0]
        p = _plano_do_dia(con, l["variante_id"], dia, gravado)
        if p is None:
            continue
        planos[l["ligacao_id"]] = p
        if p.get("wfa_id") is not None:
            wfas.add(int(p["wfa_id"]))
        filtro, args = _desde_o_plano(p)
        papel += con.execute(
            "SELECT liquido, contratos, points FROM papel_operacoes "
            "WHERE ligacao_id = ? AND conta AND NOT aberta AND dia <= ? "
            f"AND {filtro}", [l["ligacao_id"], dia, *args]).fetchall()
    esperado = []
    if wfas:
        esperado = con.execute(
            "SELECT liquido, contratos, points FROM wfa_trades WHERE wfa_id "
            f"IN ({', '.join('?' * len(wfas))})", sorted(wfas)).fetchall()
    return {"esperado_wfa": _metricas(esperado), "papel": _metricas(papel),
            "demo": _demo_do_comparativo(con, portfolio_id, dia, planos, origem),
            "real": None}


def _como_data(v) -> date | None:
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])


def _custo_por_contrato(plano: dict) -> float:
    """Corretagem + emolumentos de uma operação inteira (as duas pontas),
    por contrato — a mesma conta do `metrics.monetize` que o papel usa."""
    perfil = _papel.perfil_do_plano(plano)[1]
    return (float(perfil.corretagem_por_contrato)
            + float(perfil.emolumentos_por_contrato)) * 2


def _demo_do_comparativo(con, portfolio_id: int, dia: date,
                         planos: dict[int, dict], origem: str = "demo") -> dict | None:
    """A coluna Demo: o recorte do papel (plano em vigor de cada ligação,
    desde que ele vale) aplicado às operações da demo.

    O resultado da demo vem BRUTO da corretora (`operacoes_demo`); aqui
    desconta-se o custo do plano como o papel desconta, senão a demo
    pareceria melhor só por não pagar corretagem. Derrapagem é a de
    `operacoes_demo` (ticks além do papel, por ponta; negativo = melhor
    que o papel), a mesma da tabela Papel × demo.
    """
    pregoes = _pregoes_demo(con, portfolio_id, dia, origem)
    if not pregoes:
        return None
    custos: dict[int, float] = {}
    ops = []
    for d, parte in pregoes:
        for o in parte[1]:
            p = planos.get(o["ligacao_id"])
            if p is None or o.get("plano_id") != int(p["plano_id"]):
                continue
            vale = _como_data(p.get("vale_a_partir"))
            if vale is not None and d < vale:
                continue
            ops.append((o, p))
    linhas = []
    for o, p in ops:
        if o["situacao"] != "fechada" or o["resultado"] is None:
            continue
        pid = int(p["plano_id"])
        if pid not in custos:
            custos[pid] = _custo_por_contrato(p)
        ctr = float(o["contratos"] or 0)
        linhas.append((o["resultado"] - custos[pid] * ctr, ctr, o["pontos"]))
    m = _metricas(linhas)

    def media(vs):
        vs = list(vs)
        return sum(vs) / len(vs) if vs else None
    executadas = [o for o, _ in ops if o["situacao"] in ("fechada", "aberta")]
    m.update(
        mesmo_minuto=(sum(1 for o in executadas if o["mesmo_minuto"])
                      / len(executadas) if executadas else None),
        derrapagem_extra=media(x for o, _ in ops
                               for x in (o["derrapagem_entrada"],
                                         o["derrapagem_saida"])
                               if x is not None),
        atraso_ms=media(a for o, _ in ops for a in o.get("atrasos_ms") or []),
        rejeitadas=sum(int(o.get("rejeitadas") or 0) for o, _ in ops))
    return m


# ---------------------------------------------------------------- alertas
def alertas(con, portfolio_id: int, dia: date, *,
            hoje: date | None = None) -> list[dict]:
    """O que pede atenção (spec §6.8): plano gravado mesmo assim, pregão
    pulado ou interrompido, cálculo de hoje que falhou, pregão passado do
    plano em vigor que não foi conferido e candle que mudou depois da
    conferência."""
    hoje = _hoje(hoje)
    out = []
    linhas = _por_ligacao(con, portfolio_id, dia, hoje)
    nomes = {l["ligacao_id"]: l["nome"] for l in linhas}
    for l in linhas:
        lig, nome = l["ligacao_id"], l["nome"]
        if l["gravado_mesmo_assim"]:
            out.append({"tipo": "mesmo_assim", "ligacao_id": lig,
                        "texto": f"{nome}: plano #{l['plano_id']} "
                        + _plano.texto_pendencias(l["pendencias"])})
        if l["status"] in ("pulado", "interrompido"):
            out.append({"tipo": l["status"], "ligacao_id": lig,
                        "texto": f"{nome}: pregão {l['status']} — "
                        f"{l['motivo'] or 'sem motivo gravado'}"})
        if l["status"] == "falha":
            # sem este aviso a variante parecia viva, com a aberta e o
            # stop/alvo de antes da falha no gráfico
            out.append({"tipo": "falha", "ligacao_id": lig,
                        "texto": f"{nome}: {l['motivo']} — números parados "
                        "na última volta que deu certo"})
    # pregão preso de plano antigo é história encerrada: o plano não opera
    # mais e o aviso não teria o que pedir
    em_vigor = [(l["ligacao_id"], l["plano_id"]) for l in linhas
                if l["plano_id"] is not None]
    for lig, pid in em_vigor:
        for (d,) in con.execute(
                "SELECT dia FROM papel_pregoes WHERE status = 'rodando' "
                "AND dia < ? AND ligacao_id = ? AND plano_id = ? ORDER BY dia",
                [hoje, lig, pid]).fetchall():
            out.append({"tipo": "nao_conferido", "ligacao_id": lig,
                        "texto": f"{nomes[lig]}: pregão de {d:%d/%m} não foi "
                        "conferido — números da última volta"})
    for dv in _papel.divergencias(con, ligacoes=list(nomes)):
        out.append({"tipo": "divergencia", "ligacao_id": int(dv["ligacao_id"]),
                    "texto": f"{nomes[dv['ligacao_id']]}: candles de "
                    f"{dv['dia']:%d/%m} mudaram depois da conferência — o "
                    "papel daquele dia foi calculado sobre outras barras"})
    return out
