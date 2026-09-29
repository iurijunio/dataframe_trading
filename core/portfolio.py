"""Portfólio: agrupar variantes de estratégia e medir correlação/risco.

O portfólio referencia só a VARIANTE, nunca plano/wfa/mineração
diretamente — "o que está ativo hoje" é sempre resolvido na hora via
variantes.plano_ativo, a mesma filosofia de "recalcula na hora" que o
WFA/Mineração já usa (core/wfa_runner.py:_span). Reotimizar uma variante
atualiza o portfólio sozinho, sem precisar mexer em nada aqui. Ver
docs/superpowers/specs/2026-09-23-portfolio-correlacao-design.md.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import numpy as np

from . import db_manager as db
from . import variantes as V

_MIN_DIAS_COMUNS = 20
_N_SIMULACOES = 2000
_PERCENTIL_RISCO = 10  # "so e ultrapassado em 10% dos cenarios" - ver spec §5.3


def criar(nome: str) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome do portfólio não pode ser vazio")
    with db.connect_write() as con, db.transacao(con):
        pid = con.execute("SELECT nextval('seq_portfolio_id')").fetchone()[0]
        con.execute(
            "INSERT INTO portfolios (portfolio_id, nome, criado_em) "
            "VALUES (?,?,?)", [pid, nome, datetime.now()])
    return int(pid)


def listar() -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT p.portfolio_id, p.nome, p.criado_em, p.capital, "
            "count(pv.variante_id) "
            "FROM portfolios p "
            "LEFT JOIN portfolio_variantes pv "
            "ON pv.portfolio_id = p.portfolio_id "
            "GROUP BY p.portfolio_id, p.nome, p.criado_em, p.capital "
            "ORDER BY p.nome"
        ).fetchall()
    return [{"portfolio_id": r[0], "nome": r[1], "criado_em": r[2],
             "capital": r[3], "n_membros": r[4]} for r in rows]


def definir_capital(portfolio_id: int, capital: float) -> None:
    """Capital da CONTA que roda o portfólio inteiro - independente do
    capital de cada plano individual (esse só dimensiona a posição
    daquela variante sozinha). É a partir dele que a curva combinada e
    as métricas do portfólio partem."""
    if capital is None or capital <= 0:
        raise ValueError("capital do portfólio precisa ser um valor positivo")
    with db.connect_write() as con, db.transacao(con):
        con.execute("UPDATE portfolios SET capital = ? WHERE portfolio_id = ?",
                    [float(capital), portfolio_id])


def adicionar_variante(portfolio_id: int, variante_id: int) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute(
            "INSERT OR IGNORE INTO portfolio_variantes "
            "(portfolio_id, variante_id, adicionado_em) VALUES (?,?,?)",
            [portfolio_id, variante_id, datetime.now()])


def remover_variante(portfolio_id: int, variante_id: int) -> None:
    with db.connect_write() as con, db.transacao(con):
        con.execute(
            "DELETE FROM portfolio_variantes "
            "WHERE portfolio_id = ? AND variante_id = ?",
            [portfolio_id, variante_id])


def membros(portfolio_id: int) -> list[dict]:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT ev.variante_id, ev.nome, ev.estrategia "
            "FROM portfolio_variantes pv "
            "JOIN estrategia_variantes ev ON ev.variante_id = pv.variante_id "
            "WHERE pv.portfolio_id = ? ORDER BY ev.nome", [portfolio_id]
        ).fetchall()
    out = []
    for vid, nome, estrategia in rows:
        ativo = V.plano_ativo(vid)
        out.append({
            "variante_id": vid, "nome": nome, "estrategia": estrategia,
            "wfa_id": ativo["wfa_id"] if ativo else None,
            "sem_plano_ativo": ativo is None,
        })
    return out


def _retornos_diarios(wfa_id: int) -> dict:
    with db.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT exit_ts, liquido FROM wfa_trades WHERE wfa_id = ?",
            [wfa_id]).fetchall()
    diario: dict = defaultdict(float)
    for exit_ts, liquido in rows:
        diario[exit_ts.date()] += liquido
    return dict(diario)


def correlacao(portfolio_id: int) -> dict:
    ms = membros(portfolio_id)
    ativos = [m for m in ms if not m["sem_plano_ativo"]]
    avisos = [f"{m['nome']}: sem plano ativo" for m in ms if m["sem_plano_ativo"]]

    series = {m["nome"]: _retornos_diarios(m["wfa_id"]) for m in ativos}
    nomes = list(series)
    n = len(nomes)
    matriz = [[1.0 if i == j else None for j in range(n)] for i in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            a, b = series[nomes[i]], series[nomes[j]]
            comuns = sorted(set(a) & set(b))
            if len(comuns) < _MIN_DIAS_COMUNS:
                avisos.append(
                    f"{nomes[i]} × {nomes[j]}: período curto demais para correlação")
                continue
            xa = np.array([a[d] for d in comuns])
            xb = np.array([b[d] for d in comuns])
            if xa.std() == 0 or xb.std() == 0:
                # retorno constante no periodo (ex.: so um trade fechando
                # sempre o mesmo valor) - corrcoef daria 0/0 = nan, um
                # numero "real" mas sem sentido, silenciosamente
                avisos.append(
                    f"{nomes[i]} × {nomes[j]}: sem variação suficiente no "
                    f"período para correlação")
                continue
            r = float(np.corrcoef(xa, xb)[0, 1])
            matriz[i][j] = matriz[j][i] = r

    return {"variantes": nomes, "matriz": matriz,
            "risco_diario": _risco_diario(ativos), "avisos": avisos}


def _trades_para_risco(wfa_id: int) -> list[dict]:
    with db.connect(read_only=True) as con:
        symbol = con.execute(
            "SELECT symbol FROM wfa_runs WHERE wfa_id = ?", [wfa_id]
        ).fetchone()[0]
        r = con.execute(
            "SELECT point_value FROM instruments WHERE symbol = ?", [symbol]
        ).fetchone()
        # mesmo padrao de fallback ja usado em core/engine/execution.py -
        # sem cotacao cadastrada assume 1 ponto = R$ 1
        ponto = float(r[0]) if r and r[0] else 1.0
        rows = con.execute(
            "SELECT entry_ts, exit_ts, mae, contratos, liquido "
            "FROM wfa_trades WHERE wfa_id = ? ORDER BY entry_ts",
            [wfa_id]).fetchall()
    return [
        {"entry_ts": r[0], "exit_ts": r[1],
         "mae_reais": abs(r[2] or 0) * ponto * (r[3] or 1),
         "liquido": r[4] or 0.0}
        for r in rows if r[0] and r[1]
    ]


def _simular_pior_ponto(trades: list[dict], rng) -> float:
    # trade com entry_ts == exit_ts (fechamento na mesma barra) fica de
    # fora - caso raro; o liquido dele nao entra no risco do dia
    partes = []
    for t in trades:
        ini, fim = t["entry_ts"].timestamp(), t["exit_ts"].timestamp()
        if fim <= ini:
            continue
        t_mae = rng.uniform(ini, fim)
        partes.append((ini, t_mae, fim, -t["mae_reais"], t["liquido"]))
    if not partes:
        return 0.0

    def valor(p, inst):
        ini, t_mae, fim, fundo, liquido = p
        if inst < ini:
            return 0.0
        if inst >= fim:
            return liquido
        if inst <= t_mae:
            frac = (inst - ini) / (t_mae - ini) if t_mae > ini else 1.0
            return fundo * frac
        frac = (inst - t_mae) / (fim - t_mae) if fim > t_mae else 1.0
        return fundo + (liquido - fundo) * frac

    candidatos = [p[1] for p in partes]
    return min(sum(valor(p, inst) for p in partes) for inst in candidatos)


def _risco_diario(membros_ativos: list[dict]) -> dict | None:
    todos = []
    for m in membros_ativos:
        todos.extend(_trades_para_risco(m["wfa_id"]))
    if not todos:
        return None

    por_dia: dict = defaultdict(list)
    for t in todos:
        por_dia[t["entry_ts"].date()].append(t)

    rng = np.random.default_rng(0)
    piores_por_dia = {}
    for dia, trades in por_dia.items():
        if len(trades) < 2:
            continue
        amostras = [_simular_pior_ponto(trades, rng) for _ in range(_N_SIMULACOES)]
        piores_por_dia[dia] = float(np.percentile(amostras, _PERCENTIL_RISCO))

    if not piores_por_dia:
        return None
    pior_dia = min(piores_por_dia, key=piores_por_dia.get)
    return {"p90": piores_por_dia[pior_dia], "pior_dia": str(pior_dia)}


def _trades_liquido(wfa_id: int) -> list[tuple]:
    with db.connect(read_only=True) as con:
        return con.execute(
            "SELECT exit_ts, liquido, custo FROM wfa_trades "
            "WHERE wfa_id = ? ORDER BY exit_ts, n", [wfa_id]).fetchall()


def _capital_do_membro(m: dict) -> tuple[float | None, str | None]:
    """(capital, aviso) - aviso vem preenchido quando não há capital pra
    usar como ponto de partida (sem plano ativo, ou plano sem capital
    gravado)."""
    from . import plano as PL

    if m["sem_plano_ativo"]:
        return None, f"{m['nome']}: sem plano ativo"
    ativo = V.plano_ativo(m["variante_id"])
    d = PL.detalhes(ativo["plano_id"]) if ativo else None
    capital = d["capital"] if d else None
    if capital is None:
        return None, f"{m['nome']}: sem capital gravado no plano"
    return capital, None


def _capital_do_portfolio(portfolio_id: int) -> float | None:
    with db.connect(read_only=True) as con:
        r = con.execute("SELECT capital FROM portfolios WHERE portfolio_id = ?",
                        [portfolio_id]).fetchone()
    return r[0] if r else None


def curvas(portfolio_id: int) -> dict:
    """Curva de capital de cada variante ativa, trade a trade, em R$, mais
    a curva COMBINADA do portfólio (todas as variantes intercaladas em
    ordem cronológica de fechamento, partindo do capital DO PORTFÓLIO -
    a mesma conta rodando as duas juntas, não a soma do capital de cada
    plano, que assumiria contas separadas por variante).

    Começa no capital inicial gravado no plano ativo de cada variante e
    acumula o `liquido` real dos trades OOS, na ordem em que fecharam -
    mesma leitura da curva do walk-forward, só que uma linha por membro
    do portfólio (mais uma linha extra, a combinada) em vez de uma
    janela só.
    """
    ms = membros(portfolio_id)
    avisos = []
    series = {}
    todos_trades = []  # (exit_ts, liquido) de TODAS as variantes, pra combinada

    for m in ms:
        capital, aviso = _capital_do_membro(m)
        if aviso:
            avisos.append(aviso)
            continue
        rows = _trades_liquido(m["wfa_id"])
        acumulado = capital
        pontos = []
        for ts, liquido, _custo in rows:
            acumulado += liquido or 0.0
            pontos.append({"ts": ts, "capital": acumulado})
            todos_trades.append((ts, liquido or 0.0))
        series[m["nome"]] = {"capital_inicial": capital, "pontos": pontos}

    combinada = None
    capital_portfolio = _capital_do_portfolio(portfolio_id)
    if todos_trades and capital_portfolio is None:
        avisos.append("defina o capital do portfólio para ver a curva combinada")
    elif todos_trades:
        todos_trades.sort(key=lambda t: t[0])
        acumulado = capital_portfolio
        pontos = []
        for ts, liquido in todos_trades:
            acumulado += liquido
            pontos.append({"ts": ts, "capital": acumulado})
        combinada = {"capital_inicial": capital_portfolio, "pontos": pontos}

    return {"series": series, "combinada": combinada, "avisos": avisos}


def _trades_combinados_ordenados(portfolio_id: int) -> list[tuple]:
    """(exit_ts, liquido, custo) de TODAS as variantes ativas, na ordem
    cronológica REAL de fechamento - não "todos os trades de uma variante,
    depois todos da outra" (a ordem natural de iterar os membros), que
    mediria drawdown/Sharpe sobre um caminho que nunca existiu de verdade
    (achado real do usuário: "888,94 de drawdown, é isso mesmo?" - não
    era). Base compartilhada por `resumo()` e `simulacao_capital()`."""
    todos_trades = []
    for m in membros(portfolio_id):
        _capital, aviso = _capital_do_membro(m)
        if aviso:
            continue
        for ts, liq, cst in _trades_liquido(m["wfa_id"]):
            todos_trades.append((ts, liq or 0.0, cst or 0.0))
    todos_trades.sort(key=lambda t: t[0])
    return todos_trades


def resumo(portfolio_id: int) -> dict | None:
    """As métricas do portfólio como um todo (fator de recuperação, max
    drawdown, sharpe, profit factor...) - a mesma régua do Backtest e do
    Walk-Forward (`core.metrics.resumo`), aplicada na curva COMBINADA:
    todos os trades de todas as variantes ativas, juntos, a partir do
    capital DO PORTFÓLIO (não a soma do capital de cada plano).

    `None` quando não há trade nenhum pra medir, ou quando o capital do
    portfólio ainda não foi definido - sem ele, drawdown %, Sharpe etc.
    não têm uma base de verdade pra dividir."""
    from . import metrics

    capital_portfolio = _capital_do_portfolio(portfolio_id)
    if capital_portfolio is None:
        return None

    todos_trades = _trades_combinados_ordenados(portfolio_id)
    if not todos_trades:
        return None
    saida_ts, liquido, custo = zip(*todos_trades)
    return metrics.resumo(liquido, custo, saida_ts, capital_portfolio)


def resumo_membros(portfolio_id: int) -> dict[str, dict]:
    """As mesmas métricas de `resumo()`, mas uma por VARIANTE isolada (com
    o capital do próprio plano dela) - pra comparar lado a lado com o
    portfólio combinado e ver se juntar as estratégias realmente compensa
    (achado real do usuário: "preciso comparar ao menos o DD de cada uma
    e do portfólio pra ver se compensa"). Só entram membros com plano
    ativo e pelo menos um trade OOS; os demais ficam de fora (mesmo
    critério de `curvas()`)."""
    from . import metrics

    out = {}
    for m in membros(portfolio_id):
        capital, aviso = _capital_do_membro(m)
        if aviso:
            continue
        rows = _trades_liquido(m["wfa_id"])
        if not rows:
            continue
        saida_ts, liquido, custo = zip(*rows)
        out[m["nome"]] = {"capital_inicial": capital,
                          **metrics.resumo(liquido, custo, saida_ts, capital)}
    return out


_N_SIM_RUINA = 2000
_FATORES_CAPITAL_TESTADOS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)
_N_TRADES_MAX = 20_000


def simulacao_capital(portfolio_id: int, limiar_dd_pct: float = 40.0,
                      prob_max_pct: float = 10.0) -> dict | None:
    """Critério de Kelly e risco de ruína do portfólio COMBINADO - pra
    responder "esse conjunto de estratégias compensa, e com quanto
    capital?" (pedido real do usuário depois de ver a tela pela primeira
    vez).

    Kelly: fração ótima de capital a arriscar por trade, a partir do
    win_rate e do payoff já calculados em `resumo()` - f* = p - (1-p)/b.
    Também devolve meio-Kelly (metade da fração): Kelly cheio é agressivo
    demais pra qualquer curva real, é o meio-Kelly que a maioria usa.

    Risco de ruína: aqui "ruína" é o drawdown simulado passar de
    `limiar_dd_pct` do capital, NÃO o capital chegar a zero - na prática
    ninguém opera até zerar, para bem antes (escolha do usuário,
    29/09/2026). Reembaralha (bootstrap, com reposição) os trades reais
    do portfólio combinado, simula a curva pra uma faixa de capitais ao
    redor do capital atual, e recomenda o menor capital testado que
    mantém a probabilidade de ruína em `prob_max_pct` ou menos.

    `None` quando `resumo()` também seria `None` (sem trade ou sem
    capital do portfólio definido)."""
    m = resumo(portfolio_id)
    capital_atual = _capital_do_portfolio(portfolio_id)
    if m is None or capital_atual is None:
        return None

    p = m["win_rate"] / 100.0
    b = m["payoff"]
    # payoff=0.0 e um valor sentinela sobrecarregado: tanto "nenhuma perda
    # registrada ainda" (b indefinido, NAO zero de verdade) quanto "nenhum
    # ganho registrado" (aí sim, sem vantagem nenhuma) caem nele. Tratar
    # os dois como Kelly=0% escondia o primeiro caso - que é bom (edge
    # forte demais pra fórmula calcular), não neutro (achado do usuário:
    # "13% o quê? não ficou claro").
    kelly_indefinido = b == 0 and p > 0
    if kelly_indefinido:
        kelly_pct = None
    elif b == 0:
        kelly_pct = 0.0
    else:
        kelly_pct = max(p - (1 - p) / b, 0.0) * 100.0

    liquido = np.array([t[1] for t in _trades_combinados_ordenados(portfolio_id)])
    n = liquido.size
    rng = np.random.default_rng(0)

    def prob_ruina(capital: float) -> float:
        amostras = rng.choice(liquido, size=(_N_SIM_RUINA, n), replace=True)
        equity = capital + np.cumsum(amostras, axis=1)
        pico = np.maximum.accumulate(equity, axis=1)
        dd_pct = np.divide(pico - equity, pico, out=np.zeros_like(equity),
                           where=pico > 0) * 100.0
        return float((dd_pct.max(axis=1) > limiar_dd_pct).mean() * 100.0)

    prob_atual = prob_ruina(capital_atual)
    capital_recomendado = None
    for fator in _FATORES_CAPITAL_TESTADOS:
        c = capital_atual * fator
        if prob_ruina(c) <= prob_max_pct:
            capital_recomendado = c
            break

    return {
        "kelly_pct": kelly_pct,
        "kelly_meio_pct": None if kelly_pct is None else kelly_pct / 2,
        "kelly_indefinido": kelly_indefinido,
        "capital_atual": capital_atual,
        "prob_ruina_atual_pct": prob_atual,
        "capital_recomendado": capital_recomendado,
        "limiar_dd_pct": limiar_dd_pct,
        "prob_max_pct": prob_max_pct,
    }


def simular_crescimento(portfolio_id: int, capital_inicial: float,
                        risco_pct: float, n_trades: int,
                        n_simulacoes: int = 2000) -> dict | None:
    """Projeta a curva de capital pra FRENTE, simulando `n_trades` trades
    futuros com o `risco_pct` escolhido pelo usuário - pedido real:
    "um gráfico que simule o aumento de capital de acordo com os dados
    que eu informar".

    A distribuição de resultados vem dos trades REAIS do portfólio
    combinado (a mesma base do risco de ruína), não de uma média
    abstrata: cada trade histórico vira um múltiplo de "1R" (liquido
    dividido pela perda média histórica, a mesma convenção de R-múltiplo
    da literatura de gestão de risco) e é reembaralhado (bootstrap) pra
    simular o futuro. Em cada trade simulado, o valor arriscado é
    `capital_do_momento * risco_pct` - o risco em R$ cresce e encolhe
    junto com o capital, a mesma composição que faz o critério de Kelly
    funcionar de verdade (rode com `risco_pct = kelly_pct` de
    `simulacao_capital()` pra ver o crescimento geométrico ótimo).

    `None` sem trade histórico nenhum, ou sem nenhuma perda registrada
    (sem perda não dá pra medir o tamanho de 1R - mesma situação do
    Kelly indefinido)."""
    if capital_inicial is None or capital_inicial <= 0:
        raise ValueError("capital inicial precisa ser positivo")
    if risco_pct is None or risco_pct <= 0:
        raise ValueError("risco por trade precisa ser positivo")
    if n_trades is None or n_trades <= 0:
        raise ValueError("número de trades precisa ser positivo")
    if n_trades > _N_TRADES_MAX:
        # sem teto, um numero digitado por engano (ex.: "1000000" em vez
        # de "100") aloca uma matriz de dezenas de GB em rng.choice e
        # trava o servidor inteiro (achado da revisao)
        raise ValueError(f"número de trades não pode passar de {_N_TRADES_MAX}")

    todos = _trades_combinados_ordenados(portfolio_id)
    if not todos:
        return None
    liquido = np.array([t[1] for t in todos])
    perdas = liquido[liquido < 0]
    if perdas.size == 0:
        return None
    r_unidade = float(-perdas.mean())  # "1R" = perda média histórica
    r_multiplos = liquido / r_unidade

    rng = np.random.default_rng(0)
    amostras = rng.choice(r_multiplos, size=(n_simulacoes, n_trades), replace=True)

    f = risco_pct / 100.0
    trajetorias = np.empty((n_simulacoes, n_trades + 1))
    trajetorias[:, 0] = capital_inicial
    capital = np.full(n_simulacoes, capital_inicial, dtype=np.float64)
    for t in range(n_trades):
        capital = np.maximum(capital + amostras[:, t] * capital * f, 0.0)
        trajetorias[:, t + 1] = capital

    p10, p50, p90 = np.percentile(trajetorias, [10, 50, 90], axis=0)
    finais = trajetorias[:, -1]
    return {
        "p10": p10.tolist(),
        "p50": p50.tolist(),
        "p90": p90.tolist(),
        "capital_final_mediana": float(p50[-1]),
        "prob_dobrar_pct": float((finais >= capital_inicial * 2).mean() * 100.0),
        "prob_zerar_pct": float((finais <= 0.0).mean() * 100.0),
    }
