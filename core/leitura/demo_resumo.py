"""Leitura: operações e comparativo da demo, situação do backtest e envio."""
from __future__ import annotations

import math
from datetime import date

from .. import db_manager as db
from .. import papel as _papel
from .. import plano as _plano
from .. import variantes as V

from .base import _hoje, _instrumento, _ligacoes, _limites
from .pregao import _ops_do_dia, _pregao
from .demo import _ENTROU, _TENTOU, _ligs_do_portfolio, _uma_operacao_demo, eventos_ordens


def operacoes_demo(con, portfolio_id: int, dia: date,
                   symbol: str = _papel.SIMBOLO, origem: str = "demo") -> list[dict]:
    """As operações do dia na demo, casadas com o papel pela chave
    `(ligacao_id, entry_ts)` (a mesma do `op_id` do papel e do diário).

    Derrapagem por ponta, em ticks, positivo = pior para o operador:
    entrada `(demo − papel) × lado / tick`, saída `(papel − demo) × lado /
    tick`. Papel = o preço gravado em `papel_operacoes`, que JÁ inclui a
    derrapagem que o plano supõe (`kernel._fill`): estes números são a
    derrapagem ALÉM do plano (0 = a demo derrapou o que o plano supôs). A
    do plano vai em `slippage_plano`; a absoluta é a soma das duas. Sem a
    operação no papel, o `preco_papel` do evento.
    Resultado em R$ é bruto (sem corretagem e emolumentos): é o que a
    corretora mostra na posição; `papel_mesmo_tamanho` é o papel bruto da
    mesma operação no tamanho da demo, para comparar na mesma base.
    """
    ligs = {l["ligacao_id"]: l for l in _ligacoes(con, portfolio_id, dia)}
    if not ligs:
        return []
    inst = _instrumento(symbol)
    tick = int(inst.get("tick_size", 1))
    pv = float(inst.get("point_value", 1.0))
    marcas = ", ".join("?" * len(ligs))
    cols = ("ligacao_id", "plano_id", "entry_ts", "side", "contratos",
            "entry_px", "exit_px", "bruto", "liquido")
    papel = {(o["ligacao_id"], o["entry_ts"]): o for o in (
        dict(zip(cols, r)) for r in con.execute(
            f"SELECT {', '.join(cols)} FROM papel_operacoes WHERE dia = ? "
            f"AND ligacao_id IN ({marcas})", [dia, *ligs]).fetchall())}
    # o plano de cada operação (o gravado nela; sem ela no papel, o do
    # pregão / em vigor da ligação) dá a derrapagem que o papel já supõe
    slips: dict = {}

    def slip(plano_id):
        if plano_id is None:
            return None
        if plano_id not in slips:
            try:
                p = _plano.detalhes(int(plano_id), con=con)
                slips[plano_id] = (None if p is None else
                                   float(_papel.perfil_do_plano(p)[1].slippage_ticks))
            except Exception:
                slips[plano_id] = None      # plano ilegível: sem régua
        return slips[plano_id]

    def plano_da_ligacao(lig):
        gravado = _pregao(con, lig, dia)[0]
        if gravado is not None:
            return gravado
        vigor = V.plano_em_vigor(ligs[lig]["variante_id"], dia, con=con)
        return vigor["plano_id"] if vigor else None
    dono: dict[int, tuple] = {}
    por_op: dict[tuple, list[dict]] = {}
    for e in eventos_ordens(con, portfolio_id, dia, origem):
        lig = e.get("ligacao_id")
        if lig not in ligs:
            continue
        ticket = e.get("ticket")
        if e.get("entry_ts") is not None:
            chave = (lig, e["entry_ts"])
            if e["tipo"] in _ENTROU and ticket:
                dono[int(ticket)] = chave
        elif ticket is not None and int(ticket) in dono:
            # saída, proteção e chamado de posição só trazem o ticket
            chave = dono[int(ticket)]
        else:
            continue
        por_op.setdefault(chave, []).append(e)
    out = []
    for k, evs in por_op.items():
        if not any(e["tipo"] in _TENTOU + ("seria_enviada",) for e in evs):
            continue
        p_op = papel.get(k)
        plano_id = p_op["plano_id"] if p_op is not None else plano_da_ligacao(k[0])
        linha = _uma_operacao_demo(k, evs, p_op, ligs[k[0]], tick, pv,
                                   slip(plano_id))
        linha["plano_id"] = None if plano_id is None else int(plano_id)
        out.append(linha)
    out.sort(key=lambda o: (o["entry_ts"], o["ligacao_id"]))
    return out


def _fator_pontos(pontos: list[float]):
    ganho = sum(p for p in pontos if p > 0)
    perda = -sum(p for p in pontos if p < 0)
    if perda > 0:
        return ganho / perda
    return math.inf if ganho > 0 else None


# (banco, portfólio, dia, impressão do dia) -> o pedaço do comparativo
# daquele pregão. Só pregão PASSADO: o de hoje ainda muda a cada volta. A
# impressão (quantos eventos e operações, e o último cálculo do papel)
# invalida o pregão cujo diário chegou atrasado ao banco (espelho na subida).
_CACHE_DEMO_DIA: dict[tuple, tuple] = {}


def _impressao_do_dia(con, ligs: list[int], d: date, origem: str = "demo") -> tuple:
    ini, fim = _limites(d)
    marcas = ", ".join("?" * len(ligs))
    n_ev = con.execute(
        f"SELECT count(*) FROM ordens_eventos WHERE quando >= ? AND quando < ? "
        f"AND origem = ? AND (ligacao_id IS NULL OR ligacao_id IN ({marcas}))",
        [ini, fim, origem, *ligs]).fetchone()[0]
    n_op, calc = con.execute(
        f"SELECT count(*), max(calculado_em) FROM papel_operacoes WHERE dia = ? "
        f"AND ligacao_id IN ({marcas})", [d, *ligs]).fetchone()
    return int(n_ev), int(n_op), calc


def _demo_do_dia(con, portfolio_id: int, d: date, origem: str = "demo") -> tuple:
    """(pontos do papel, operações da demo, chamados) de um pregão — só as
    ligações que tentaram operar na demo nele."""
    linhas = operacoes_demo(con, portfolio_id, d, origem=origem)
    demo_ops = [o for o in linhas if o["situacao"] != "seria_enviada"]
    tentaram = {o["ligacao_id"] for o in demo_ops}
    papel_pts = [float(o["points"] or 0) for o in _ops_do_dia(con, sorted(tentaram), d)
                 if o["conta"] and not o["aberta"]]
    chamados = sum(1 for e in eventos_ordens(con, portfolio_id, d, origem)
                   if e["tipo"] == "chamado" and e.get("ligacao_id") in tentaram)
    return papel_pts, demo_ops, chamados


def _pregoes_demo(con, portfolio_id: int, dia: date, origem: str = "demo") -> list[tuple]:
    """`[(dia, parte do _demo_do_dia)]` dos pregões até `dia` em que alguma
    ligação do portfólio TENTOU operar na demo (o ensaio não conta).

    Pregão passado sai do `_CACHE_DEMO_DIA`; o de `dia` é sempre relido —
    ainda muda a cada volta da captura. A chave do cache leva a `origem`:
    demo e real nunca dividem o mesmo pregão guardado."""
    ligs = _ligs_do_portfolio(con, portfolio_id)
    if not ligs:
        return []
    marcas = ", ".join("?" * len(ligs))
    tentou = ", ".join(f"'{t}'" for t in _TENTOU)
    dias = [r[0] for r in con.execute(
        f"SELECT DISTINCT CAST(quando AS DATE) AS d FROM ordens_eventos "
        f"WHERE origem = ? AND ligacao_id IN ({marcas}) AND tipo IN ({tentou}) "
        "AND CAST(quando AS DATE) <= ? ORDER BY d", [origem, *ligs, dia]).fetchall()]
    out = []
    for d in dias:
        chave = None
        if d < dia:
            chave = (str(db.DB_PATH), portfolio_id, origem, d,
                     _impressao_do_dia(con, ligs, d, origem))
        parte = _CACHE_DEMO_DIA.get(chave) if chave else None
        if parte is None:
            parte = _demo_do_dia(con, portfolio_id, d, origem)
            if chave:
                _CACHE_DEMO_DIA[chave] = parte
        out.append((d, parte))
    return out


def comparativo_demo(con, portfolio_id: int, *, dia: date | None = None,
                     hoje: date | None = None, origem: str = "demo") -> dict:
    """Papel × demo por contrato, nos mesmos pregões (spec ordens §8).

    Entram os pregões em que alguma ligação do portfólio TENTOU operar na
    demo (o ensaio com o Envio desligado não conta) e, em cada um, só as
    ligações que tentaram: papel e demo olham as mesmas variantes nos
    mesmos dias. Pontos por contrato; fator de lucro pelos pontos (o papel
    tem custos do plano, a demo não — em pontos os dois comparam).
    """
    dia = dia or _hoje(hoje)
    pregoes = _pregoes_demo(con, portfolio_id, dia, origem)
    if not pregoes:
        return {"pregoes": 0, "papel": None, "demo": None}
    papel_pts: list[float] = []
    demo_ops: list[dict] = []
    chamados = 0
    for _d, parte in pregoes:
        papel_pts += parte[0]
        demo_ops += parte[1]
        chamados += parte[2]
    fechadas = [o for o in demo_ops if o["situacao"] == "fechada"
                and o["pontos"] is not None]
    # por ponta: (além do plano, a do plano). O preço do papel já traz a
    # derrapagem do plano; a absoluta da demo é a soma das duas
    pontas = [(x, o["slippage_plano"]) for o in demo_ops
              for x in (o["derrapagem_entrada"], o["derrapagem_saida"])
              if x is not None]
    com_plano = [(x, s) for x, s in pontas if s is not None]

    def media(vs):
        vs = list(vs)
        return sum(vs) / len(vs) if vs else None
    pts = [float(o["pontos"]) for o in fechadas]
    return {
        "pregoes": len(pregoes),
        "papel": {"n": len(papel_pts),
                  "pontos_por_operacao": media(papel_pts),
                  "fator_lucro": _fator_pontos(papel_pts),
                  # a que o plano supõe, nas mesmas pontas da demo
                  "derrapagem": media(s for _, s in com_plano)},
        "demo": {"n": len(fechadas),
                 "pontos_por_operacao": media(pts),
                 "fator_lucro": _fator_pontos(pts),
                 "mesmo_minuto": sum(1 for o in demo_ops if o["mesmo_minuto"]),
                 # absoluta = além do plano + a do plano
                 "derrapagem": media(x + s for x, s in com_plano),
                 "derrapagem_extra": media(x for x, _ in pontas),
                 "perdidas": sum(1 for o in demo_ops if o["situacao"] in (
                     "perdida", "recusada_perdida", "fora_do_ar", "nao_entrou")),
                 "recusadas": sum(1 for o in demo_ops if o["recusas"]),
                 # recusada e depois executada: a automação resolveu sozinha
                 "resolvidas": sum(1 for o in demo_ops if o["recusas"]
                                   and o["preco_entrada"] is not None),
                 "chamados": chamados},
    }


def situacao_backtest(con, portfolio_id: int, dia: date) -> dict:
    """O selo "papel = backtest" do portfólio: a soma de
    `papel_backtest.situacao` das ligações do dia e a lista dos pregões
    que diferiram (variante, dia, quantas operações)."""
    from .. import papel_backtest as _pb       # pesado (motor): só aqui
    out = {"pregoes": 0, "operacoes": 0, "diferencas": 0, "ok": None,
           "lista": []}
    oks = []
    for l in _ligacoes(con, portfolio_id, dia):
        s = _pb.situacao(con, l["ligacao_id"])
        out["pregoes"] += s["pregoes"]
        out["operacoes"] += s["operacoes"]
        out["diferencas"] += s["diferencas"]
        if s["ok"] is not None:
            oks.append(s["ok"])
        for d, n in con.execute(
                "SELECT dia, coalesce(json_array_length(diferencas, "
                "'$.operacoes'), 0) FROM papel_backtest WHERE ligacao_id = ? "
                "AND NOT ok ORDER BY dia", [l["ligacao_id"]]).fetchall():
            out["lista"].append({"nome": l["nome"], "dia": d, "n": int(n)})
    out["ok"] = all(oks) if oks else None
    return out


def envio_da_conta(con, conta_id) -> bool | None:
    """O interruptor Envio de ordens gravado na conta (None = sem conta)."""
    if conta_id is None:
        return None
    r = con.execute("SELECT coalesce(envio_ligado, false) FROM contas "
                    "WHERE conta_id = ?", [conta_id]).fetchone()
    return None if r is None else bool(r[0])


def nomes(con, portfolio_id: int) -> dict[int, str]:
    """Ligação → nome da variante, removidas inclusive (o diário de hoje
    pode citar uma que saiu do portfólio no meio do dia)."""
    return {int(l): n for l, n in con.execute(
        "SELECT pm.ligacao_id, ev.nome FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "WHERE pm.portfolio_id = ?", [portfolio_id]).fetchall()}
