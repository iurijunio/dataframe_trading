"""Pesquisa: a combinação aberta no Backtest e o perfil do menu."""
from __future__ import annotations

from dash import no_update

from core.engine.execution import ExecutionProfile


# ------------------------------------- a combinação aberta na subtela Backtest
# O resto do menu que o backtest lê (além dos `val` e de "excluir holdout"):
# mexer em qualquer um deles e rodar de novo marca a linha como "editado".
MENU_COMBINACAO = (
    ("ativo", "value"), ("d-de", "date"), ("d-ate", "date"),
    ("e-timeframe", "value"), ("e-ent-ini", "value"), ("e-ent-fim", "value"),
    ("e-fechamento", "value"), ("e-dias", "value"), ("e-direcao", "value"),
    ("e-filtro-adx", "value"), ("e-sem-ent1", "value"),
    ("e-sem-ent2", "value"), ("e-sem-ent3", "value"),
    ("e-alvo-tipo", "value"), ("e-stop-tipo", "value"),
    ("e-max-barras", "value"), ("e-lim-ganho", "value"),
    ("e-lim-perda", "value"), ("e-max-trades", "value"),
    ("e-max-loss", "value"), ("e-corretagem", "value"),
    ("e-emolumentos", "value"), ("e-slippage", "value"), ("e-modo", "value"),
    ("e-contratos", "value"), ("e-risco", "value"), ("e-capital", "value"),
    ("e-min-ops", "value"),
)

ORIGEM_GATILHO = {"grid-mine": "linha", "scatter": "nuvem",
                  "grid-aprovadas": "aprovada"}

# Os campos do menu que montam o perfil de execução. A Varredura e a Busca
# automática leem OS MESMOS por `perfil_do_menu`: a busca tem de usar os
# fixos (custos, ADX, limites, proteções) que a Varredura usaria.
MENU_PERFIL = (
    ("e-timeframe", "value"), ("e-ent-ini", "value"), ("e-ent-fim", "value"),
    ("e-fechamento", "value"), ("e-dias", "value"), ("e-direcao", "value"),
    ("e-filtro-adx", "value"), ("e-sem-ent1", "value"), ("e-sem-ent2", "value"),
    ("e-sem-ent3", "value"), ("e-alvo-tipo", "value"), ("e-stop-tipo", "value"),
    ("e-max-barras", "value"), ("e-lim-ganho", "value"), ("e-lim-perda", "value"),
    ("e-max-trades", "value"), ("e-max-loss", "value"), ("e-corretagem", "value"),
    ("e-emolumentos", "value"), ("e-slippage", "value"), ("e-modo", "value"),
    ("e-contratos", "value"), ("e-risco", "value"), ("e-capital", "value"),
    ("e-min-ops", "value"),
)


def perfil_do_menu(v: dict, m: dict) -> ExecutionProfile:
    """O perfil que o menu descreve. `v` = valores dos campos `val` por
    parâmetro; `m` = os campos de `MENU_PERFIL` por id."""
    return ExecutionProfile(
        timeframe=m.get("e-timeframe") or "M1",
        entrada_inicio=m.get("e-ent-ini") or "09:00",
        entrada_fim=m.get("e-ent-fim") or "17:00",
        fechamento=m.get("e-fechamento") or "17:30",
        dias_semana=tuple(m.get("e-dias") or (1, 2, 3, 4, 5)),
        direcao=m.get("e-direcao"),
        sem_entrada1=m.get("e-sem-ent1") or "", sem_entrada2=m.get("e-sem-ent2") or "",
        sem_entrada3=m.get("e-sem-ent3") or "",
        filtro_adx=m.get("e-filtro-adx") or "tendencia",
        adx_periodo=v.get("adx_periodo") or 0,
        adx_limiar=v.get("adx_limiar") or 0,
        adx_filtro_di=v.get("adx_filtro_di") or 0,
        adx_subindo=v.get("adx_subindo") or 0,
        alvo_tipo=m.get("e-alvo-tipo"),
        alvo_atr_periodo=v.get("alvo_atr_periodo") or 20,
        alvo_atr_mult=v.get("alvo_atr_mult") or 0, stop_tipo=m.get("e-stop-tipo"),
        alvo_pct=v.get("alvo_pct") or 0,
        stop_atr_periodo=v.get("stop_atr_periodo") or 20,
        stop_atr_mult=v.get("stop_atr_mult") or 0,
        stop_pct=v.get("stop_pct") or 0,
        max_barras=m.get("e-max-barras") or 0,
        limite_ganho_contrato=m.get("e-lim-ganho") or 0,
        limite_perda_contrato=m.get("e-lim-perda") or 0,
        max_trades_dia=m.get("e-max-trades") or 0,
        max_prejuizos_dia=m.get("e-max-loss") or 0,
        corretagem_por_contrato=m.get("e-corretagem") or 0.0,
        emolumentos_por_contrato=m.get("e-emolumentos") or 0.0,
        slippage_ticks=m.get("e-slippage") or 0, modo_posicao=m.get("e-modo"),
        contratos=m.get("e-contratos") or 1, risco_por_trade=m.get("e-risco"),
        capital_inicial=m.get("e-capital") or 10_000.0,
        min_operacoes=m.get("e-min-ops") or 0,
    )


# Campos `val` da camada 4 que um perfil completo define (os demais `val` são
# parâmetros da estratégia).
VAL_DO_PERFIL = ("adx_periodo", "adx_limiar", "adx_filtro_di", "adx_subindo",
                 "alvo_atr_periodo", "alvo_atr_mult", "alvo_pct", "stop_atr_periodo",
                 "stop_atr_mult", "stop_pct", "stop_pontos", "alvo_pontos", "alvo_razao",
                 "breakeven_pct", "step_gatilho_pct", "step_distancia_pct",
                 "trailing_pontos")
PROTECOES = ("breakeven_pct", "step_gatilho_pct", "step_distancia_pct", "trailing_pontos")


def perfil_da_busca(v: dict, m: dict) -> ExecutionProfile:
    """O perfil fixo de uma Busca automática: o do menu MAIS as proteções.
    Na Varredura as proteções viajam como campos mineráveis (`campos`); a
    busca não as varre, então elas entram fixas — senão a busca rodaria sem
    breakeven e o Backtest do campeão, com."""
    p = perfil_do_menu(v, m)
    for k in PROTECOES:
        if v.get(k) is not None:
            setattr(p, k, v[k])
    return p


def menu_do_perfil(p: dict) -> tuple[dict, dict]:
    """O caminho de volta de `perfil_do_menu`: (campos do menu por id,
    valores `val` por parâmetro) que reproduzem o perfil `p`."""
    m = {"e-timeframe": p["timeframe"], "e-ent-ini": p["entrada_inicio"],
         "e-ent-fim": p["entrada_fim"], "e-fechamento": p["fechamento"],
         "e-dias": list(p["dias_semana"]), "e-direcao": p["direcao"],
         "e-filtro-adx": p["filtro_adx"], "e-sem-ent1": p["sem_entrada1"],
         "e-sem-ent2": p["sem_entrada2"], "e-sem-ent3": p["sem_entrada3"],
         "e-alvo-tipo": p["alvo_tipo"], "e-stop-tipo": p["stop_tipo"],
         "e-max-barras": p["max_barras"], "e-lim-ganho": p["limite_ganho_contrato"],
         "e-lim-perda": p["limite_perda_contrato"], "e-max-trades": p["max_trades_dia"],
         "e-max-loss": p["max_prejuizos_dia"], "e-corretagem": p["corretagem_por_contrato"],
         "e-emolumentos": p["emolumentos_por_contrato"], "e-slippage": p["slippage_ticks"],
         "e-modo": p["modo_posicao"], "e-contratos": p["contratos"],
         "e-risco": p["risco_por_trade"], "e-capital": p["capital_inicial"],
         "e-min-ops": p["min_operacoes"]}
    return m, {k: p[k] for k in VAL_DO_PERFIL if k in p}


def _menu_atual(ids_val, valores_val, holdout, menu) -> dict:
    """O menu numa forma comparável: `val:<p>`, `excluir-holdout` e os
    demais campos por id (`menu` já vem como {id: valor})."""
    m = {f"val:{i['p']}": v for i, v in zip(ids_val or [], valores_val or [])}
    m["excluir-holdout"] = holdout or []
    m.update(menu or {})
    return m


def _igual(a, b) -> bool:
    # a ordem de uma Checklist (dias) é a ordem em que se marcou
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return a == b


def _carregar_combinacao(gatilho, selecionadas, clique, aprovadas, ids_val,
                         linhas, n_run, valores_val=None, ids_on=None,
                         ligados=None, menu=None):
    """Corpo de `carregar_combinacao`, fora do `register` para os testes.

    Devolve (vals, excluir-holdout, btn-run, mine-subtela, store-combinacao).
    `selectedRows` vazio — o que `progresso` deixa ao carregar uma mineração
    salva — não carrega nada e não troca de subtela.
    """
    linha = None
    if gatilho == "scatter" and clique:
        alvo = clique["points"][0].get("customdata")
        linha = next((l for l in (linhas or []) if l["trial_id"] == alvo), None)
    elif gatilho == "grid-aprovadas" and aprovadas:
        linha = aprovadas[0]
    elif gatilho == "grid-mine" and selecionadas:
        linha = selecionadas[0]
    p = (linha or {}).get("params")
    if not p:
        return ([no_update] * len(ids_val), no_update, no_update, no_update,
                no_update)

    marcados = {i["p"] for i, v in zip(ids_on or [], ligados or []) if v}
    varridos = {k: v for k, v in p.items() if k in marcados} or dict(p)

    # o snapshot é o menu DEPOIS desta escrita: os States antigos marcariam
    # "editado" já na primeira rodada
    atuais = valores_val if valores_val is not None else [None] * len(ids_val)
    novos = [p.get(i["p"], atual) for i, atual in zip(ids_val, atuais)]
    store = {"origem": ORIGEM_GATILHO[gatilho], "n": linha.get("n"),
             "params": varridos,
             "menu": _menu_atual(ids_val, novos, ["on"], menu)}
    return ([p.get(i["p"], no_update) for i in ids_val], ["on"],
            (n_run or 0) + 1, "backtest", store)


def _reclique_mesma_linha(gatilho, selecionadas_mine, selecionadas_apr, store):
    """Clique de novo na linha JÁ carregada volta para a subtela Backtest.

    O AG Grid não dispara `selectedRows` quando a linha clicada já estava
    selecionada, então `carregar_combinacao` não reage. Aqui só a subtela
    muda — nada de `btn-run` (o backtest daquela linha já está na tela). Se
    a linha é outra (ou nada foi carregado), quem age é o caminho da seleção.
    """
    selecionadas = {"grid-mine": selecionadas_mine,
                    "grid-aprovadas": selecionadas_apr}.get(gatilho)
    if not store or not selecionadas or gatilho not in ORIGEM_GATILHO:
        return no_update
    linha = selecionadas[0] or {}
    params = linha.get("params") or {}
    if (store.get("origem") == ORIGEM_GATILHO[gatilho]
            and store.get("n") is not None and store.get("n") == linha.get("n")
            and all(params.get(k) == v
                    for k, v in (store.get("params") or {}).items())):
        return "backtest"
    return no_update


def _linha_combinacao(store, atual) -> str:
    """"linha #3 · stop_pontos=10", com " · editado" se o menu mudou."""
    if not store:
        return ""
    origem, n = store.get("origem"), store.get("n")
    rotulo = origem if origem == "nuvem" or n is None else f"{origem} #{n}"
    partes = [rotulo] + [f"{k}={v}" for k, v in (store.get("params") or {}).items()]
    snap = store.get("menu") or {}
    if atual is not None and any(not _igual(snap.get(k), atual.get(k))
                                 for k in set(snap) | set(atual)):
        partes.append("editado")
    return " · ".join(partes)
