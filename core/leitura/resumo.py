"""Leitura: resumo do papel, variantes e operações do dia."""
from __future__ import annotations

from datetime import date

from .. import papel as _papel

from .base import _epoch, _hoje, _instrumento, _ligacoes, _limites
from .pregao import _ABERTA_PARADA, _ops_do_dia, _por_ligacao, _pregao, _situacao


# --------------------------------------------------------------- resumo
def _conta(con, conta_id) -> dict | None:
    if conta_id is None:
        return None
    r = con.execute("SELECT conta_id, nome, limite_perda_dia FROM contas "
                    "WHERE conta_id = ?", [conta_id]).fetchone()
    if r is None:
        return None
    return {"conta_id": int(r[0]), "nome": r[1],
            "limite_perda_dia": None if r[2] is None else float(r[2])}


def _fechamento_marcado(o: dict, plano: dict | None, tick: int) -> int:
    """O fechamento da barra em que o motor marcou a aberta.

    Sai do próprio provisório, não do relógio: o motor marca pelo
    fechamento da última barra com a derrapagem contra o operador, então
    `entrada + lado·pontos` é esse fechamento já derrapado — desfazer a
    derrapagem do perfil devolve o fechamento. Inferir a barra por
    `calculado_em` errava: o relógio do PC anda ~1 min atrás da corretora,
    e com o papel pendente a barra mais nova ainda não foi calculada.
    """
    lado = int(o["side"])
    marca = int(o["entry_px"]) + lado * int(o["points"] or 0)
    desliz = 0
    if plano is not None:
        desliz = int(_papel.perfil_do_plano(plano)[1].slippage_ticks) * tick
    return marca + lado * desliz


def _pior_momento(con, ops: list[dict], planos: dict,
                  dia: date, symbol: str = _papel.SIMBOLO) -> dict:
    """O ponto mais baixo do dia, minuto a minuto.

    Fechada entra pelo resultado na barra da saída. A aberta é marcada pelo
    fechamento de cada barra desde a entrada, a partir do provisório
    gravado: de uma barra para outra só o preço muda (derrapagem e custo já
    estão no provisório), então cada barra é o provisório mais a diferença
    entre o fechamento dela e o fechamento que o motor marcou. Barra mais
    nova que o último cálculo também é marcada — é preço real.
    """
    ini, fim = _limites(dia)
    barras = con.execute("SELECT ts, close FROM bars_m1 WHERE symbol = ? "
                         "AND ts >= ? AND ts < ? ORDER BY ts",
                         [symbol, ini, fim]).fetchall()
    if not barras:
        return {"valor": 0.0, "quando": None}
    inst = _instrumento(symbol)
    pv = float(inst.get("point_value", 1.0))
    tick = int(inst.get("tick_size", 1))
    fechadas = [(o["exit_ts"], float(o["liquido"] or 0.0))
                for o in ops if not o["aberta"]]
    abertas = [(o, _fechamento_marcado(o, planos.get(o["ligacao_id"]), tick))
               for o in ops if o["aberta"]]
    pior, quando = None, None
    for ts, close in barras:
        v = sum(liq for saida, liq in fechadas if saida <= ts)
        for o, ancora in abertas:
            if o["entry_ts"] <= ts:
                v += (float(o["liquido"] or 0.0) + int(o["side"])
                      * (close - ancora) * pv * int(o["contratos"]))
        if pior is None or v < pior:
            pior, quando = v, ts
    return {"valor": float(pior), "quando": quando}


def resumo(con, portfolio_id: int, dia: date, *,
           hoje: date | None = None) -> dict:
    """Os indicadores do topo (spec §6.2). Só operações que contam."""
    hoje = _hoje(hoje)
    pf = con.execute("SELECT coalesce(ligado, false), conta_demo_id, "
                     "conta_real_id, capital FROM portfolios "
                     "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
    if pf is None:
        raise ValueError(f"portfólio #{portfolio_id} não existe")
    pf_ligado, demo_id, real_id, capital = pf
    linhas = _por_ligacao(con, portfolio_id, dia, hoje)
    todas = [o for l in linhas for o in l["_ops"]]
    planos = {l["ligacao_id"]: l["_plano"] for l in linhas}
    demo = _conta(con, demo_id)
    dias: set = set()
    for l in linhas:
        dias |= l["acumulado_det"]["dias"]
    return {
        "resultado_hoje": float(sum(l["hoje"] for l in linhas)),
        "posicao": {"liquida": sum(l["posicao"] for l in linhas),
                    "por_ligacao": {l["ligacao_id"]: l["posicao"]
                                    for l in linhas}},
        "pior_momento": _pior_momento(con, todas, planos, dia),
        "limite_dia": demo["limite_perda_dia"] if demo else None,
        "acumulado": {
            "valor": float(sum(l["acumulado_det"]["valor"] for l in linhas)),
            "pregoes": len(dias),
            "operacoes": sum(l["acumulado_det"]["operacoes"] for l in linhas)},
        "n_variantes": len(linhas),
        # operando = pregão vivo hoje, com a variante e o portfólio ligados
        "n_operando": sum(1 for l in linhas
                          if pf_ligado and l["ligada"] and l["vivo"]),
        "contas": {"demo": demo, "real": _conta(con, real_id)},
        "capital": None if capital is None else float(capital),
    }


# ------------------------------------------------------------ variantes
def variantes(con, portfolio_id: int, dia: date, *,
              hoje: date | None = None) -> list[dict]:
    """Um cartão por ligação. Posição aberta primeiro — é o que precisa de
    olho agora —, depois o resultado do dia, do maior para o menor."""
    out = []
    for l in _por_ligacao(con, portfolio_id, dia, _hoje(hoje)):
        l["acumulado"] = l.pop("acumulado_det")["valor"]
        for interno in ("_ops", "_plano", "vivo"):
            l.pop(interno)
        out.append(l)
    out.sort(key=lambda v: (v["posicao"] == 0, -v["hoje"], v["ligacao_id"]))
    return out


# ------------------------------------------------------------ operações
def operacoes_do_dia(con, portfolio_id: int, dia: date,
                     ligacao_id: int | None = None, *,
                     hoje: date | None = None) -> list[dict]:
    """Linhas da tabela do dia (spec §6.5) — todas, inclusive as que não
    contam (`conta = false`: a tela as pinta de cinza, "fora do período
    ligado").

    `situacao`: 'fechada' | 'aberta' (provisória, pregão vivo) | uma
    "aberta" do banco que não é posição de agora e não tem stop/alvo
    vigente — 'nao_conferido' (pregão passado que a conferência não
    fechou), 'nao_atualizada' (o último cálculo falhou) ou 'congelada'
    (pregão interrompido: código mudou ou variante removida). `nota` diz o
    porquê nesses três.
    """
    hoje = _hoje(hoje)
    ligs = {l["ligacao_id"]: l for l in _ligacoes(con, portfolio_id, dia)}
    ids = [ligacao_id] if ligacao_id is not None else list(ligs)
    ids = [i for i in ids if i in ligs]
    pregoes = {i: _pregao(con, i, dia) for i in ids}
    status = {i: _situacao(p[1], dia, hoje, p[3])[0]
              for i, p in pregoes.items()}
    out = []
    for o in _ops_do_dia(con, ids, dia):
        lig = o["ligacao_id"]
        l = ligs[lig]
        aberta = bool(o["aberta"])
        parada = _ABERTA_PARADA.get(status[lig]) if aberta else None
        nota = None
        if parada:
            situacao, nota = parada
            if pregoes[lig][2] == _papel.MOTIVO_REMOVIDA:
                nota = "variante removida"
        else:
            situacao = "aberta" if aberta else "fechada"
        viva = aberta and not parada
        out.append({**o, "aberta": viva, "provisorio": viva,
                    "situacao": situacao, "nota": nota,
                    "conta": bool(o["conta"]),
                    "variante": l["nome"], "cor": l["cor"]})
    return out


def marcadores(con, portfolio_id: int, dia: date, *,
               hoje: date | None = None) -> dict:
    """`{"marcadores", "linhas_abertas"}` para o gráfico do dia.

    Marcadores no formato de `ui.components.charts.trade_markers` (▲ compra
    abaixo da barra, ▼ venda acima, a saída do lado oposto com os pontos),
    sem `color`: vão `cor` (índice estável da variante) e `conta`, e a tela
    pinta — cinza quando não conta; com mais variantes que cores, ela varia
    a forma. `ligacao_id` vai junto para a legenda esconder uma variante.
    Linhas: stop e alvo vigentes de cada operação aberta de pregão vivo.
    """
    mk, linhas = [], []
    for o in operacoes_do_dia(con, portfolio_id, dia, hoje=hoje):
        compra = int(o["side"]) == 1
        comum = {"cor": o["cor"], "conta": o["conta"],
                 "ligacao_id": o["ligacao_id"]}
        mk.append({"time": _epoch(o["entry_ts"]),
                   "position": "belowBar" if compra else "aboveBar",
                   "shape": "arrowUp" if compra else "arrowDown",
                   "text": "C" if compra else "V", **comum})
        if o["situacao"] == "aberta":
            for tipo, preco in (("stop", o["stop_px"]), ("alvo", o["alvo_px"])):
                if preco is not None:
                    linhas.append({"tipo": tipo, "price": int(preco),
                                   "title": f"{tipo} {o['variante']}",
                                   **comum})
        if o["exit_ts"] is None:
            continue
        pts = int(o["points"] or 0)
        mk.append({"time": _epoch(o["exit_ts"]),
                   "position": "aboveBar" if compra else "belowBar",
                   "shape": "circle", "text": f"{pts:+d}", **comum})
    mk.sort(key=lambda m: m["time"])
    return {"marcadores": mk, "linhas_abertas": linhas}
