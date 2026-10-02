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
    último número que existe —, mas não é posição de agora, não desenha
    stop/alvo e aparece como "não conferida".

Recebe a conexão de quem chama (a tela abre uma de leitura por releitura) e
nunca importa Dash. Cor é só um índice estável por ligação: a tela é quem
sabe a paleta.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from . import db_manager as db
from . import papel as _papel
from . import plano as _plano
from . import variantes as V

# Pregão que produziu papel (e por isso entra na curva do plano). O pulado
# não operou; o interrompido operou até o código mudar.
_PREGOES_QUE_CONTAM = ("rodando", "conferido", "interrompido")

# Início do pregão para a régua da expectativa; o fim é o fechamento do
# perfil do plano — a hora em que a variante para de operar.
_ABERTURA = time(9, 0)

_INSTRUMENTOS: dict[str, dict] = {}


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


def _instrumento(symbol: str) -> dict:
    # o YAML não muda com o app aberto, e a tela relê a cada volta da captura
    if symbol not in _INSTRUMENTOS:
        _INSTRUMENTOS[symbol] = db.load_instrument_yaml(symbol)
    return _INSTRUMENTOS[symbol]


def _ligacoes(con, portfolio_id: int, dia: date) -> list[dict]:
    """As ligações do portfólio que existiam no dia, com a cor de cada uma.

    A cor é o lugar da ligação entre TODAS as do portfólio, removidas
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


def _pregao(con, ligacao_id: int, dia: date):
    """(plano_id, status, motivo) gravados do pregão, ou Nones."""
    r = con.execute("SELECT plano_id, status, motivo FROM papel_pregoes "
                    "WHERE ligacao_id = ? AND dia = ?",
                    [ligacao_id, dia]).fetchone()
    return tuple(r) if r else (None, None, None)


def _plano_do_dia(con, variante_id: int, dia: date,
                  gravado: int | None) -> dict | None:
    """O plano com que o papel rodou no dia (o gravado no pregão manda: é o
    que o motor de fato usou), senão o que está em vigor."""
    pid = gravado
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
    """Papel que conta desde o plano em vigor. INCLUI a aberta provisória,
    para que acumulado menos ontem dê o resultado de hoje — diferente do
    `comparativo`, que só olha fechadas."""
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
            "stop_px", "alvo_px", "aberta", "conta")


def _ops_do_dia(con, ligacoes: list[int], dia: date) -> list[dict]:
    if not ligacoes:
        return []
    linhas = con.execute(
        f"SELECT {', '.join(_COLS_OP)} FROM papel_operacoes WHERE dia = ? "
        f"AND ligacao_id IN ({', '.join('?' * len(ligacoes))}) "
        "ORDER BY entry_ts, ligacao_id", [dia, *ligacoes]).fetchall()
    return [dict(zip(_COLS_OP, r)) for r in linhas]


_MOTIVO_PRESO = "pregão não foi conferido: números da última volta"


def _situacao(status: str | None, dia: date, hoje: date) -> tuple:
    """(status para a tela, vivo?). Pregão passado ainda `rodando` não é
    pregão vivo: é a conferência que não fechou o dia."""
    if status == "rodando" and dia < hoje:
        return "nao_conferido", False
    return status, status == "rodando" and dia >= hoje


def _por_ligacao(con, portfolio_id: int, dia: date, hoje: date) -> list[dict]:
    """O que a tela mostra de cada ligação no dia — base de `resumo`,
    `variantes` e `alertas`, para os três nunca discordarem."""
    ligs = _ligacoes(con, portfolio_id, dia)
    ops = _ops_do_dia(con, [l["ligacao_id"] for l in ligs], dia)
    out = []
    for l in ligs:
        lig = l["ligacao_id"]
        gravado, status, motivo = _pregao(con, lig, dia)
        p = _plano_do_dia(con, l["variante_id"], dia, gravado)
        status, vivo = _situacao(status, dia, hoje)
        if status == "nao_conferido":
            motivo = _MOTIVO_PRESO
        minhas = [o for o in ops if o["ligacao_id"] == lig and o["conta"]]
        fechadas = [o for o in minhas if not o["aberta"]]
        posicao = sum(int(o["side"]) * int(o["contratos"])
                      for o in minhas if o["aberta"]) if vivo else 0
        out.append({
            **l, "status": status, "motivo": motivo, "vivo": vivo,
            "posicao": posicao,
            "hoje": float(sum(o["liquido"] or 0.0 for o in minhas)),
            "n_ops": len(minhas),
            "acerto": (f"{sum(1 for o in fechadas if (o['liquido'] or 0) > 0)}"
                       f"/{len(fechadas)}"),
            "acumulado_det": _acumulado(con, lig, p, dia),
            "contratos": int(p["contratos"]) if p and p["contratos"] else None,
            "plano_id": p and p["plano_id"],
            "gravado_mesmo_assim": bool(p and p["gravado_mesmo_assim"]),
            "pendencias": (p and p["pendencias"]) or [],
            "_ops": minhas, "_plano": p,
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

    `situacao`: 'fechada' | 'aberta' (provisória) | 'nao_conferido' — a
    "aberta" de um pregão passado que a conferência não fechou: não é
    posição, não tem stop/alvo vigente.
    """
    hoje = _hoje(hoje)
    ligs = {l["ligacao_id"]: l for l in _ligacoes(con, portfolio_id, dia)}
    ids = [ligacao_id] if ligacao_id is not None else list(ligs)
    ids = [i for i in ids if i in ligs]
    status = {i: _situacao(_pregao(con, i, dia)[1], dia, hoje)[0]
              for i in ids}
    out = []
    for o in _ops_do_dia(con, ids, dia):
        l = ligs[o["ligacao_id"]]
        aberta = bool(o["aberta"])
        preso = aberta and status[o["ligacao_id"]] == "nao_conferido"
        situacao = ("nao_conferido" if preso
                    else "aberta" if aberta else "fechada")
        out.append({**o, "aberta": aberta and not preso,
                    "provisorio": aberta and not preso,
                    "situacao": situacao, "conta": bool(o["conta"]),
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


# ------------------------------------------------- papel × esperado
def _marcos(expectativa: dict | None) -> list[dict]:
    return sorted((m for m in (expectativa or {}).values()
                   if isinstance(m, dict) and m.get("pregoes")
                   and m.get("p50") is not None),
                  key=lambda m: int(m["pregoes"]))


def _mediana(marcos: list[dict], n: float) -> float:
    """Reta entre marcos, a partir de zero no dia em que o plano passou a
    valer; depois do último marco, segue a inclinação do último trecho."""
    pts = [(0, 0.0), *((int(m["pregoes"]), float(m["p50"])) for m in marcos)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if n <= x1:
            return y0 + (y1 - y0) * (n - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y1 + (y1 - y0) * (n - x1) / (x1 - x0)


def _interp(expectativa: dict | None, chave: str, n: float) -> float | None:
    """O valor esperado depois de `n` pregões do plano (n pode ser
    fracionário: o pregão de hoje conta pela parte já andada).

    A expectativa só tem marcos (3, 6, 12 meses — às vezes só o primeiro).
    A mediana cresce em reta: é a soma de n dias de mesma média. A largura
    da faixa NÃO: a dispersão de uma soma de n dias independentes cresce
    com √n, então p10/p90 = mediana(n) + (p_k(N) − p50(N))·√(n/N), com N o
    marco mais próximo. Faixa em reta a partir de zero seria estreita
    demais no começo — a primeira semana ruim pareceria "abaixo do p10".
    Depois do último marco vale a mesma regra, com a mediana estendida pela
    inclinação do último trecho e N = o último marco.
    """
    marcos = _marcos(expectativa)
    if not marcos:
        return None
    med = _mediana(marcos, n)
    if chave == "p50":
        return med
    com = [m for m in marcos if m.get(chave) is not None]
    if not com:
        return None
    perto = min(com, key=lambda m: (abs(n - int(m["pregoes"])),
                                    int(m["pregoes"])))
    N = int(perto["pregoes"])
    return med + (float(perto[chave]) - float(perto["p50"])) \
        * math.sqrt(max(n, 0) / N)


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


def _regua(con, ligacao_id: int, portfolio_id: int, plano: dict,
           dias: list[date], hoje: date,
           symbol: str = _papel.SIMBOLO) -> list[float]:
    """Quantos pregões a expectativa andou até cada dia da série.

    Só anda no pregão em que a variante esteve ligada (pelo menos 1 minuto
    dentro do pregão, pelos MESMOS trechos do diário que marcaram o `conta`
    das operações): desligada, ela não operou, e cobrar dela o resultado
    esperado do dia faria a curva parecer abaixo da faixa sem motivo. O
    pregão de hoje conta pela fração já andada (09:00 → fechamento do
    perfil, até o último candle gravado), não por um dia cheio.
    """
    fechamento = _papel.perfil_do_plano(plano)[1].fechamento
    hh, mm = (int(x) for x in fechamento.split(":"))
    periodos = _papel.periodos_ligados_dias(con, ligacao_id, portfolio_id,
                                            dias)
    out, n = [], 0.0
    for d in dias:
        s0 = datetime.combine(d, _ABERTURA)
        s1 = datetime.combine(d, time(hh, mm))
        fim, peso = s1, 1.0
        if d >= hoje:
            ini_d, fim_d = _limites(d)
            r = con.execute("SELECT max(ts) FROM bars_m1 WHERE symbol = ? "
                            "AND ts >= ? AND ts < ?",
                            [symbol, ini_d, fim_d]).fetchone()
            # o relógio do PC atrasa: o andamento do pregão é o do dado
            fim = min(s1, r[0] + timedelta(minutes=1)) if r and r[0] else s0
            total = (s1 - s0).total_seconds()
            peso = (min(max((fim - s0).total_seconds() / total, 0.0), 1.0)
                    if total > 0 else 0.0)
        ligado = sum(max((min(b, fim) - max(a, s0)).total_seconds(), 0)
                     for a, b in periodos.get(d, []))
        if ligado >= 60:
            n += peso
        out.append(n)
    return out


def _acumular(valores):
    out, s = [], 0.0
    for v in valores:
        s += v
        out.append(s)
    return out


def curva_vs_esperado(con, portfolio_id: int, ligacao_id: int | None = None,
                      *, hoje: date | None = None) -> dict:
    """Papel acumulado desde o plano em vigor contra o que o plano prometeu.

    Um ponto por pregão do plano. Por variante: faixa p10–p90 e mediana. No
    portfólio, só a soma das medianas (decisão 10): somar o p10 de cada
    variante não dá o p10 da soma — seria uma faixa falsa, larga demais.
    """
    hoje = _hoje(hoje)
    ligs = _ligacoes(con, portfolio_id, hoje)
    if ligacao_id is not None:
        ligs = [l for l in ligs if l["ligacao_id"] == ligacao_id]
    series = []
    for l in ligs:
        gravado = _pregao(con, l["ligacao_id"], hoje)[0]
        p = _plano_do_dia(con, l["variante_id"], hoje, gravado)
        s = _serie(con, l["ligacao_id"], p, hoje)
        regua = (_regua(con, l["ligacao_id"], portfolio_id, p,
                        [d for d, _ in s], hoje) if p else [])
        series.append((p, s, regua))

    if ligacao_id is not None:
        if not series:
            return {"dias": [], "papel": [], "mediana": None, "p10": None,
                    "p90": None, "faixa_atual": None,
                    "aviso": "variante fora deste portfólio"}
        p, serie, regua = series[0]
        exp = (p or {}).get("expectativa") or {}
        papel = _acumular(v for _, v in serie)
        curvas = {k: ([_interp(exp, k, n) for n in regua]
                      if _interp(exp, k, 0) is not None else None)
                  for k in ("p10", "p50", "p90")}
        faixa = None
        if papel and all(curvas[k] for k in curvas):
            faixa = _faixa(papel[-1], curvas["p10"][-1], curvas["p50"][-1],
                           curvas["p90"][-1])
        return {"dias": [d for d, _ in serie], "papel": papel,
                "mediana": curvas["p50"], "p10": curvas["p10"],
                "p90": curvas["p90"], "faixa_atual": faixa,
                "aviso": None if curvas["p50"] is not None else
                "plano sem expectativa gravada: só a curva do papel"}

    dias = sorted({d for _p, s, _r in series for d, _ in s})
    por_dia = {d: 0.0 for d in dias}
    for _p, s, _r in series:
        for d, v in s:
            por_dia[d] += v
    papel = _acumular(por_dia[d] for d in dias)
    com_exp = []
    for p, s, regua in series:
        if p and _interp(p.get("expectativa"), "p50", 0) is not None:
            com_exp.append((p["expectativa"], [d for d, _ in s], regua))

    def andado(seus, regua, d):
        # a régua da ligação no último pregão dela até `d` (0 antes do 1º)
        n = 0.0
        for x, r in zip(seus, regua):
            if x > d:
                break
            n = r
        return n

    mediana = None
    if com_exp:
        mediana = [sum(_interp(exp, "p50", andado(seus, regua, d))
                       for exp, seus, regua in com_exp) for d in dias]
    sem = len(series) - len(com_exp)
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
    plano em vigor. Papel = **só as operações fechadas** que contam, desde
    o plano em vigor: a aberta ainda não tem resultado, e média de
    operação por fazer não compara com trade do WFA. Por isso o `total`
    daqui pode ser menor que o `acumulado` do `resumo`, que inclui a aberta
    provisória — a (?) da tela explica. Demo/Real chegam na parte 4.
    """
    hoje = _hoje(hoje)
    wfas: set[int] = set()
    papel = []
    for l in _ligacoes(con, portfolio_id, hoje):
        gravado = _pregao(con, l["ligacao_id"], hoje)[0]
        p = _plano_do_dia(con, l["variante_id"], hoje, gravado)
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
    pulado ou interrompido, pregão passado do plano em vigor que não foi
    conferido e candle que mudou depois da conferência."""
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
