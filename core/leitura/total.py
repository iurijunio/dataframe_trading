"""Leitura: total por ligação desde o plano em vigor."""
from __future__ import annotations

from datetime import date

from .base import _ligacoes
from .pregao import _plano_do_dia, _pregao
from .comparativo import _como_data, _custo_por_contrato, _metricas
from .demo_resumo import _pregoes_demo


def total_por_ligacao(con, portfolio_id: int, dia: date,
                      origem: str = "demo") -> dict[int, dict]:
    """O total de cada variante na conta `origem`, no mesmo recorte da coluna
    Demo/Real do Esperado × Papel × Demo × Real: só fechadas, desde o plano em
    vigor, líquidas dos custos do plano. {ligacao_id: métricas}, com `total`,
    `acerto` e `n`. Variante sem operação fechada nesse recorte não aparece."""
    planos: dict[int, dict] = {}
    for l in _ligacoes(con, portfolio_id, dia):
        gravado = _pregao(con, l["ligacao_id"], dia)[0]
        p = _plano_do_dia(con, l["variante_id"], dia, gravado)
        if p is not None:
            planos[l["ligacao_id"]] = p
    linhas: dict[int, list] = {}
    for d, parte in _pregoes_demo(con, portfolio_id, dia, origem):
        for o in parte[1]:
            p = planos.get(o["ligacao_id"])
            if p is None or o.get("plano_id") != int(p["plano_id"]):
                continue
            vale = _como_data(p.get("vale_a_partir"))
            if vale is not None and d < vale:
                continue
            if o["situacao"] != "fechada" or o["resultado"] is None:
                continue
            ctr = float(o["contratos"] or 0)
            liq = o["resultado"] - _custo_por_contrato(p) * ctr
            linhas.setdefault(o["ligacao_id"], []).append((liq, ctr, o["pontos"]))
    return {lig: _metricas(v) for lig, v in linhas.items()}
