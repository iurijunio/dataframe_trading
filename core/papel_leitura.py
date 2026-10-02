"""O que a sub-tela Ao vivo › Operação lê do papel. Só leitura.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

Três regras atravessam todas as contas daqui:

  - **só conta o que conta** (decisão 4): o papel calcula o dia inteiro de
    toda ligação, ligada ou não; operação com `conta = false` aparece na
    tabela e no gráfico, apagada, mas fica fora de todo total. Somá-la
    seria dizer que a variante ganhou um dinheiro que ela não ia operar;
  - **acumulado recomeça a cada plano** (§6.6): parâmetro novo é outra
    aposta. Somar o papel do plano anterior misturaria o resultado de duas
    configurações e a comparação com a faixa do plano atual não diria nada;
  - **pregão preso não é ao vivo**: um dia passado que ficou `rodando`
    (a conferência falhou) ainda tem a operação "aberta" gravada com o
    resultado provisório da última volta. Ela entra no resultado — é o
    último número que existe —, mas não é posição de agora.

Recebe a conexão de quem chama (a tela abre uma de leitura por releitura) e
nunca importa Dash.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from . import db_manager as db
from . import papel as _papel
from . import plano as _plano
from . import variantes as V

# Pregão que produziu papel (e por isso conta como pregão do plano). O
# pulado não operou; o interrompido operou até o código mudar.
_PREGOES_QUE_CONTAM = ("rodando", "conferido", "interrompido")

# Uma cor por variante, pelo lugar da ligação no portfólio. Valores do tema
# do app (`ui/theme.py`) repetidos aqui porque `core/` não importa `ui/`;
# verde e rosa ficam de fora: no gráfico eles querem dizer ganho e perda.
PALETA = ("#22E4FF", "#B96BFF", "#FFC93C", "#FF8A3D", "#4D8BFF", "#E85DFF",
          "#7CFFCB", "#C3CEE4")
CINZA = "#4A5570"        # operação fora do período ligado


# ------------------------------------------------------------ utilidades
def _hoje(hoje: date | None) -> date:
    return hoje or date.today()


def _limites(dia: date) -> tuple[datetime, datetime]:
    ini = datetime.combine(dia, time())
    return ini, ini + timedelta(days=1)


def _epoch(ts: datetime) -> int:
    # horário de parede como se fosse UTC, a convenção do gráfico
    # (`ui.data.to_epoch`): o eixo mostra 09:00 quando o pregão abriu 09:00
    return int((ts - datetime(1970, 1, 1)).total_seconds())


def _ligacoes(con, portfolio_id: int, dia: date) -> list[dict]:
    """As ligações do portfólio que existiam no dia, com a cor de cada uma.

    A cor sai do lugar da ligação entre TODAS as do portfólio, removidas
    inclusive: remover uma variante não pode repintar as outras no meio do
    pregão.
    """
    ini, fim = _limites(dia)
    linhas = con.execute(
        "SELECT pm.ligacao_id, pm.variante_id, ev.nome, pm.fase, pm.ligada, "
        "pm.adicionado_em, pm.removido_em FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "WHERE pm.portfolio_id = ? ORDER BY pm.ligacao_id",
        [portfolio_id]).fetchall()
    out = []
    for i, (lig, vid, nome, fase, ligada, adic, rem) in enumerate(linhas):
        if adic >= fim or (rem is not None and rem < ini):
            continue
        out.append({"ligacao_id": int(lig), "variante_id": int(vid),
                    "nome": nome, "fase": fase, "ligada": bool(ligada),
                    "cor": i})
    return out


def _plano_do_dia(con, ligacao_id: int, variante_id: int,
                  dia: date) -> dict | None:
    """O plano com que o papel rodou no dia (o gravado no pregão manda: é o
    que o motor de fato usou), senão o que está em vigor."""
    r = con.execute("SELECT plano_id FROM papel_pregoes WHERE ligacao_id = ? "
                    "AND dia = ?", [ligacao_id, dia]).fetchone()
    pid = r[0] if r and r[0] is not None else None
    if pid is None:
        vigor = V.plano_em_vigor(variante_id, dia, con=con)
        pid = vigor["plano_id"] if vigor else None
    return None if pid is None else _plano.detalhes(int(pid), con=con)


def _desde_o_plano(plano: dict) -> tuple[str, list]:
    """Filtro SQL "papel deste plano, desde que ele vale"."""
    vale = plano.get("vale_a_partir")
    return ("plano_id = ? AND (CAST(? AS DATE) IS NULL OR dia >= ?)",
            [plano["plano_id"], vale, vale])


def _acumulado(con, ligacao_id: int, plano: dict | None, ate: date) -> dict:
    """Papel que conta desde o plano em vigor — inclui a aberta provisória,
    para que acumulado menos ontem dê o resultado de hoje."""
    if plano is None:
        return {"valor": 0.0, "operacoes": 0, "dias": set()}
    filtro, args = _desde_o_plano(plano)
    valor, n = con.execute(
        "SELECT coalesce(sum(liquido), 0), count(*) FROM papel_operacoes "
        f"WHERE ligacao_id = ? AND conta AND dia <= ? AND {filtro}",
        [ligacao_id, ate, *args]).fetchone()
    dias = {r[0] for r in con.execute(
        "SELECT dia FROM papel_pregoes WHERE ligacao_id = ? AND dia <= ? "
        f"AND status IN {_PREGOES_QUE_CONTAM} AND {filtro}",
        [ligacao_id, ate, *args]).fetchall()}
    return {"valor": float(valor), "operacoes": int(n), "dias": dias}


_COLS_OP = ("op_id", "ligacao_id", "plano_id", "entry_ts", "exit_ts", "side",
            "contratos", "entry_px", "exit_px", "points", "liquido", "reason",
            "stop_px", "alvo_px", "aberta", "conta", "calculado_em")


def _ops_do_dia(con, ligacoes: list[int], dia: date) -> list[dict]:
    if not ligacoes:
        return []
    linhas = con.execute(
        f"SELECT {', '.join(_COLS_OP)} FROM papel_operacoes WHERE dia = ? "
        f"AND ligacao_id IN ({', '.join('?' * len(ligacoes))}) "
        "ORDER BY entry_ts, ligacao_id", [dia, *ligacoes]).fetchall()
    return [dict(zip(_COLS_OP, r)) for r in linhas]


def _por_ligacao(con, portfolio_id: int, dia: date, hoje: date) -> list[dict]:
    """O que a tela mostra de cada ligação no dia — base de `resumo` e de
    `variantes`, para os dois nunca discordarem."""
    ligs = _ligacoes(con, portfolio_id, dia)
    ops = _ops_do_dia(con, [l["ligacao_id"] for l in ligs], dia)
    out = []
    for l in ligs:
        lig = l["ligacao_id"]
        p = _plano_do_dia(con, lig, l["variante_id"], dia)
        pp = con.execute("SELECT status, motivo FROM papel_pregoes "
                         "WHERE ligacao_id = ? AND dia = ?",
                         [lig, dia]).fetchone()
        status, motivo = (pp[0], pp[1]) if pp else (None, None)
        if status == "rodando" and dia < hoje:
            # a conferência daquele dia não rodou ou falhou: o que está
            # gravado é a última volta, não um pregão que segue vivo
            status = "nao_conferido"
            motivo = "pregão não foi conferido: números da última volta"
        vivo = status == "rodando" and dia >= hoje
        minhas = [o for o in ops if o["ligacao_id"] == lig and o["conta"]]
        fechadas = [o for o in minhas if not o["aberta"]]
        posicao = sum(int(o["side"]) * int(o["contratos"])
                      for o in minhas if o["aberta"]) if vivo else 0
        marca = _plano.marca_mesmo_assim(p and p["plano_id"], con=con)
        out.append({
            **l, "status": status, "motivo": motivo, "posicao": posicao,
            "hoje": float(sum(o["liquido"] or 0.0 for o in minhas)),
            "n_ops": len(minhas),
            "acerto": (f"{sum(1 for o in fechadas if (o['liquido'] or 0) > 0)}"
                       f"/{len(fechadas)}"),
            "acumulado_det": _acumulado(con, lig, p, dia),
            "contratos": int(p["contratos"]) if p and p["contratos"] else None,
            "plano_id": p and p["plano_id"],
            "gravado_mesmo_assim": marca["gravado_mesmo_assim"],
            "pendencias": marca["pendencias"],
            "_ops": minhas,
        })
    return out


# ------------------------------------------------------------- seletor
def portfolios_com_papel(con) -> list[dict]:
    """Todos os portfólios, para o seletor — inclusive o sem ligação, que a
    tela mostra vazio com a explicação (spec §7)."""
    return [{"portfolio_id": int(r[0]), "nome": r[1], "ligado": bool(r[2])}
            for r in con.execute(
                "SELECT portfolio_id, nome, coalesce(ligado, false) "
                "FROM portfolios ORDER BY nome, portfolio_id").fetchall()]


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


def _pior_momento(con, ops: list[dict], dia: date,
                  symbol: str = _papel.SIMBOLO) -> dict:
    """O ponto mais baixo do dia, minuto a minuto.

    Fechada entra pelo resultado na barra da saída. A aberta é marcada pelo
    fechamento de cada barra desde a entrada, a partir da marcação que o
    motor gravou: só o preço muda de uma barra para outra — derrapagem e
    custo já estão no provisório —, então cada barra é o provisório mais a
    diferença de preço até a barra em que ele foi calculado. Depois dessa
    barra não há conta feita: o valor fica parado.
    """
    ini, fim = _limites(dia)
    barras = con.execute("SELECT ts, close FROM bars_m1 WHERE symbol = ? "
                         "AND ts >= ? AND ts < ? ORDER BY ts",
                         [symbol, ini, fim]).fetchall()
    if not barras:
        return {"valor": 0.0, "quando": None}
    pv = float(db.load_instrument_yaml(symbol).get("point_value", 1.0))
    fechadas = [(o["exit_ts"], float(o["liquido"] or 0.0))
                for o in ops if not o["aberta"]]
    abertas = []
    for o in ops:
        if not o["aberta"]:
            continue
        ate = [c for ts, c in barras if ts < o["calculado_em"]]
        ancora = ate[-1] if ate else barras[-1][1]
        abertas.append((o, ancora))
    pior, quando = None, None
    for ts, close in barras:
        v = sum(liq for saida, liq in fechadas if saida <= ts)
        for o, ancora in abertas:
            if o["entry_ts"] > ts:
                continue
            preco = close if ts < o["calculado_em"] else ancora
            v += (float(o["liquido"] or 0.0) + int(o["side"]) * (preco - ancora)
                  * pv * int(o["contratos"]))
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
    demo = _conta(con, demo_id)
    dias: set = set()
    for l in linhas:
        dias |= l["acumulado_det"]["dias"]
    return {
        "resultado_hoje": float(sum(l["hoje"] for l in linhas)),
        "posicao": {"liquida": sum(l["posicao"] for l in linhas),
                    "por_ligacao": {l["ligacao_id"]: l["posicao"]
                                    for l in linhas}},
        "pior_momento": _pior_momento(con, todas, dia),
        "limite_dia": demo["limite_perda_dia"] if demo else None,
        "acumulado": {
            "valor": float(sum(l["acumulado_det"]["valor"] for l in linhas)),
            "pregoes": len(dias),
            "operacoes": sum(l["acumulado_det"]["operacoes"] for l in linhas)},
        "n_variantes": len(linhas),
        "n_operando": sum(1 for l in linhas
                          if pf_ligado and l["ligada"]
                          and l["status"] not in ("pulado", "interrompido")),
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
        acum = l.pop("acumulado_det")
        l.pop("_ops")
        l["acumulado"] = acum["valor"]
        out.append(l)
    out.sort(key=lambda v: (v["posicao"] == 0, -v["hoje"], v["ligacao_id"]))
    return out


# ------------------------------------------------------------ operações
def operacoes_do_dia(con, portfolio_id: int, dia: date,
                     ligacao_id: int | None = None) -> list[dict]:
    """Linhas da tabela do dia (spec §6.5) — todas, inclusive as que não
    contam (`conta = false`: a tela as pinta de cinza, "fora do período
    ligado")."""
    ligs = {l["ligacao_id"]: l for l in _ligacoes(con, portfolio_id, dia)}
    ids = [ligacao_id] if ligacao_id is not None else list(ligs)
    ids = [i for i in ids if i in ligs]
    out = []
    for o in _ops_do_dia(con, ids, dia):
        l = ligs[o["ligacao_id"]]
        out.append({**{k: o[k] for k in _COLS_OP if k != "calculado_em"},
                    "aberta": bool(o["aberta"]), "conta": bool(o["conta"]),
                    "provisorio": bool(o["aberta"]),
                    "variante": l["nome"], "cor": l["cor"]})
    return out


def _cor(cor: int, conta: bool) -> str:
    return PALETA[cor % len(PALETA)] if conta else CINZA


def marcadores(con, portfolio_id: int, dia: date) -> dict:
    """`{"marcadores", "linhas_abertas"}` para o gráfico do dia.

    Marcadores no formato de `ui.components.charts.trade_markers` (▲ compra
    abaixo da barra, ▼ venda acima, a saída do lado oposto com os pontos),
    pintados pela cor da variante — com mais de 8 variantes a cor repete e
    a saída muda de forma (círculo → quadrado). `ligacao_id` vai junto para
    a legenda esconder uma variante. Linhas: stop e alvo vigentes de cada
    operação aberta.
    """
    mk, linhas = [], []
    for o in operacoes_do_dia(con, portfolio_id, dia):
        compra = int(o["side"]) == 1
        cor = _cor(o["cor"], o["conta"])
        mk.append({"time": _epoch(o["entry_ts"]),
                   "position": "belowBar" if compra else "aboveBar",
                   "shape": "arrowUp" if compra else "arrowDown",
                   "color": cor, "text": "C" if compra else "V",
                   "ligacao_id": o["ligacao_id"]})
        if o["aberta"]:
            for tipo, preco in (("stop", o["stop_px"]), ("alvo", o["alvo_px"])):
                if preco is not None:
                    linhas.append({"ligacao_id": o["ligacao_id"], "tipo": tipo,
                                   "price": int(preco), "color": cor,
                                   "title": f"{tipo} {o['variante']}"})
            continue
        pts = int(o["points"] or 0)
        mk.append({"time": _epoch(o["exit_ts"]),
                   "position": "aboveBar" if compra else "belowBar",
                   "shape": "circle" if (o["cor"] // len(PALETA)) % 2 == 0
                   else "square",
                   "color": cor, "text": f"{pts:+d}",
                   "ligacao_id": o["ligacao_id"]})
    mk.sort(key=lambda m: m["time"])
    return {"marcadores": mk, "linhas_abertas": linhas}


# ------------------------------------------------- papel × esperado
def _interp(expectativa: dict | None, chave: str, n: int) -> float | None:
    """O valor esperado depois de `n` pregões do plano.

    A expectativa só tem marcos (3, 6, 12 meses — às vezes só o primeiro):
    entre eles, reta; antes do primeiro, reta a partir de zero no dia em que
    o plano passou a valer; depois do último, segue a inclinação do último
    trecho. Reta é o que um sorteio de dias independentes dá na mediana —
    e é a leitura honesta de "ainda não chegamos ao marco".
    """
    marcos = sorted((int(m["pregoes"]), float(m[chave]))
                    for m in (expectativa or {}).values()
                    if isinstance(m, dict) and m.get("pregoes")
                    and m.get(chave) is not None)
    if not marcos:
        return None
    pts = [(0, 0.0), *marcos]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if n <= x1:
            return y0 + (y1 - y0) * (n - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y1 + (y1 - y0) * (n - x1) / (x1 - x0)


def _faixa(v: float, p10: float, p50: float, p90: float) -> str:
    if v < p10:
        return "abaixo_p10"
    if v < p50:
        return "p10_p50"
    if v <= p90:
        return "p50_p90"
    return "acima_p90"


def _serie(con, ligacao_id: int, plano: dict | None,
           ate: date) -> list[tuple[date, float]]:
    """(dia, resultado que conta) de cada pregão do plano em vigor."""
    if plano is None:
        return []
    filtro, args = _desde_o_plano(plano)
    dias = [r[0] for r in con.execute(
        "SELECT dia FROM papel_pregoes WHERE ligacao_id = ? AND dia <= ? "
        f"AND status IN {_PREGOES_QUE_CONTAM} AND {filtro} ORDER BY dia",
        [ligacao_id, ate, *args]).fetchall()]
    soma = dict(con.execute(
        "SELECT dia, sum(liquido) FROM papel_operacoes WHERE ligacao_id = ? "
        f"AND conta AND dia <= ? AND {filtro} GROUP BY dia",
        [ligacao_id, ate, *args]).fetchall())
    return [(d, float(soma.get(d) or 0.0)) for d in dias]


def _acumular(valores):
    out, s = [], 0.0
    for v in valores:
        s += v
        out.append(s)
    return out


def curva_vs_esperado(con, portfolio_id: int, ligacao_id: int | None = None,
                      *, hoje: date | None = None) -> dict:
    """Papel acumulado desde o plano em vigor contra o que o plano prometeu.

    Por variante: faixa p10–p90 e mediana. No portfólio, só a soma das
    medianas (decisão 10): somar o p10 de cada variante não dá o p10 da
    soma — seria uma faixa falsa, larga demais.
    """
    hoje = _hoje(hoje)
    ligs = _ligacoes(con, portfolio_id, hoje)
    if ligacao_id is not None:
        ligs = [l for l in ligs if l["ligacao_id"] == ligacao_id]
    series = []
    for l in ligs:
        p = _plano_do_dia(con, l["ligacao_id"], l["variante_id"], hoje)
        series.append((l, p, _serie(con, l["ligacao_id"], p, hoje)))

    if ligacao_id is not None:
        if not series:
            return {"dias": [], "papel": [], "mediana": None, "p10": None,
                    "p90": None, "faixa_atual": None,
                    "aviso": "variante fora deste portfólio"}
        _l, p, serie = series[0]
        exp = (p or {}).get("expectativa") or {}
        dias = [d for d, _ in serie]
        papel = _acumular(v for _, v in serie)
        curvas = {k: ([_interp(exp, k, n) for n in range(1, len(dias) + 1)]
                      if _interp(exp, k, 0) is not None else None)
                  for k in ("p10", "p50", "p90")}
        faixa = None
        if papel and all(curvas[k] for k in curvas):
            faixa = _faixa(papel[-1], curvas["p10"][-1], curvas["p50"][-1],
                           curvas["p90"][-1])
        return {"dias": dias, "papel": papel, "mediana": curvas["p50"],
                "p10": curvas["p10"], "p90": curvas["p90"],
                "faixa_atual": faixa,
                "aviso": None if curvas["p50"] is not None else
                "plano sem expectativa gravada: só a curva do papel"}

    dias = sorted({d for _l, _p, s in series for d, _ in s})
    por_dia = {d: 0.0 for d in dias}
    for _l, _p, s in series:
        for d, v in s:
            por_dia[d] += v
    papel = _acumular(por_dia[d] for d in dias)
    com_exp = [(p["expectativa"], [d for d, _ in s]) for _l, p, s in series
               if p and _interp(p.get("expectativa"), "p50", 0) is not None]
    sem = len(series) - len(com_exp)
    mediana = None
    if com_exp:
        mediana = [sum(_interp(exp, "p50", sum(1 for x in seus if x <= d))
                       for exp, seus in com_exp) for d in dias]
    aviso = None
    if sem:
        aviso = (f"{sem} variante{'s' if sem > 1 else ''} sem expectativa "
                 "gravada fica" + ("m" if sem > 1 else "")
                 + " fora da mediana")
    return {"dias": dias, "papel": papel, "mediana": mediana, "p10": None,
            "p90": None, "faixa_atual": None,
            "diferenca_mediana": (papel[-1] - mediana[-1]
                                  if papel and mediana else None),
            "aviso": aviso}


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


def comparativo(con, portfolio_id: int, *, hoje: date | None = None) -> dict:
    """Esperado (WFA) × Papel × Demo × Real (spec §6.7, decisão 9).

    Esperado = os trades fora da amostra do walk-forward que gerou cada
    plano em vigor. Papel = as operações fechadas que contam, desde o plano
    em vigor (a aberta ainda não tem resultado). Demo/Real chegam na parte 4.
    """
    hoje = _hoje(hoje)
    wfas: set[int] = set()
    papel = []
    for l in _ligacoes(con, portfolio_id, hoje):
        p = _plano_do_dia(con, l["ligacao_id"], l["variante_id"], hoje)
        if p is None:
            continue
        if p.get("wfa_id") is not None:
            wfas.add(int(p["wfa_id"]))
        filtro, args = _desde_o_plano(p)
        papel += con.execute(
            "SELECT liquido, contratos, points FROM papel_operacoes "
            "WHERE ligacao_id = ? AND conta AND NOT aberta AND dia <= ? "
            f"AND {filtro}", [l["ligacao_id"], hoje, *args]).fetchall()
    esperado = []
    if wfas:
        esperado = con.execute(
            "SELECT liquido, contratos, points FROM wfa_trades WHERE wfa_id "
            f"IN ({', '.join('?' * len(wfas))})", sorted(wfas)).fetchall()
    return {"esperado_wfa": _metricas(esperado), "papel": _metricas(papel),
            "demo": None, "real": None}


# ---------------------------------------------------------------- alertas
def alertas(con, portfolio_id: int, dia: date, *,
            hoje: date | None = None) -> list[dict]:
    """O que pede atenção (spec §6.8): plano gravado mesmo assim, pregão
    pulado ou interrompido, pregão passado que não foi conferido e candle
    que mudou depois da conferência."""
    hoje = _hoje(hoje)
    out = []
    ligs = _ligacoes(con, portfolio_id, dia)
    nomes = {l["ligacao_id"]: l["nome"] for l in ligs}
    for l in _por_ligacao(con, portfolio_id, dia, hoje):
        lig, nome = l["ligacao_id"], l["nome"]
        if l["gravado_mesmo_assim"]:
            out.append({"tipo": "mesmo_assim", "ligacao_id": lig,
                        "texto": f"{nome}: plano #{l['plano_id']} "
                        + _plano.texto_pendencias(l["pendencias"])})
        if l["status"] in ("pulado", "interrompido"):
            out.append({"tipo": l["status"], "ligacao_id": lig,
                        "texto": f"{nome}: pregão {l['status']} — "
                        f"{l['motivo'] or 'sem motivo gravado'}"})
    if nomes:
        ids = list(nomes)
        marcas = ", ".join("?" * len(ids))
        # inclusive o próprio `dia` quando ele já passou: `_por_ligacao` só
        # renomeia o status, quem avisa é aqui
        for lig, d in con.execute(
                "SELECT ligacao_id, dia FROM papel_pregoes WHERE status = "
                f"'rodando' AND dia < ? AND ligacao_id IN ({marcas}) "
                "ORDER BY dia, ligacao_id", [hoje, *ids]).fetchall():
            out.append({"tipo": "nao_conferido", "ligacao_id": int(lig),
                        "texto": f"{nomes[lig]}: pregão de {d:%d/%m} não foi "
                        "conferido — números da última volta"})
        for dv in _papel.divergencias(con):
            if dv["ligacao_id"] in nomes:
                out.append({"tipo": "divergencia",
                            "ligacao_id": int(dv["ligacao_id"]),
                            "texto": f"{nomes[dv['ligacao_id']]}: candles de "
                            f"{dv['dia']:%d/%m} mudaram depois da "
                            "conferência — o papel daquele dia foi calculado "
                            "sobre outras barras"})
    return out
