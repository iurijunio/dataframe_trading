"""Leitura: curva do papel contra o esperado do backtest."""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from .. import papel as _papel

from .base import _ABERTURA, _PREGOES_QUE_CONTAM, _hoje, _ligacoes, _limites
from .pregao import _desde_o_plano, _plano_do_dia, _pregao


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
                      *, dia: date | None = None,
                      hoje: date | None = None) -> dict:
    """Papel acumulado desde o plano em vigor contra o que o plano prometeu.

    Um ponto por pregão do plano. Por variante: faixa p10–p90 e mediana. No
    portfólio, só a soma das medianas (decisão 10): somar o p10 de cada
    variante não dá o p10 da soma — seria uma faixa falsa, larga demais.

    `dia` é o pregão que a tela mostra (padrão: `hoje`). Antes da abertura
    ela mostra o de ontem, e a curva tem de ser a desse dia — com o plano
    que vigorava nele —, senão o topo diria um número e a curva outro.
    `hoje` só decide se o último pregão conta inteiro ou pela fração.
    """
    hoje = _hoje(hoje)
    dia = dia or hoje
    ligs = _ligacoes(con, portfolio_id, dia)
    if ligacao_id is not None:
        ligs = [l for l in ligs if l["ligacao_id"] == ligacao_id]
    series = []
    for l in ligs:
        gravado = _pregao(con, l["ligacao_id"], dia)[0]
        p = _plano_do_dia(con, l["variante_id"], dia, gravado)
        s = _serie(con, l["ligacao_id"], p, dia)
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
