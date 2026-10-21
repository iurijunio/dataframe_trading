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

import json
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
        "pm.adicionado_em, pm.removido_em, pm.contratos_demo "
        "FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "WHERE pm.portfolio_id = ? ORDER BY pm.ligacao_id",
        [portfolio_id]).fetchall()
    out = []
    for i, (lig, vid, nome, fase, ligada, adic, rem, ctr_demo) in enumerate(linhas):
        if adic >= fim or (rem is not None and rem < ini):
            continue
        # contratos_demo NULL = a demo usa os contratos do plano
        out.append({"ligacao_id": int(lig), "variante_id": int(vid),
                    "nome": nome, "fase": fase, "ligada": bool(ligada),
                    "cor": i, "contratos_demo": None if ctr_demo is None
                    else int(ctr_demo)})
    return out


def _pregao(con, ligacao_id: int, dia: date):
    """(plano_id, status, motivo, falha) gravados do pregão, ou Nones."""
    r = con.execute("SELECT plano_id, status, motivo, falha FROM papel_pregoes "
                    "WHERE ligacao_id = ? AND dia = ?",
                    [ligacao_id, dia]).fetchone()
    return tuple(r) if r else (None, None, None, None)


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

# Situação, na tabela do dia, da operação que está `aberta` no banco mas
# não é posição de agora — pelo status do pregão para a tela. A "nota" diz
# o porquê na linha; stop/alvo dela não se desenham (não são os vigentes).
_ABERTA_PARADA = {"nao_conferido": ("nao_conferido", "pregão não conferido"),
                  "falha": ("nao_atualizada", "falha no cálculo"),
                  "interrompido": ("congelada", "código mudou")}


def _situacao(status: str | None, dia: date, hoje: date,
              falha: str | None = None) -> tuple:
    """(status para a tela, vivo?). Pregão passado ainda `rodando` não é
    pregão vivo: é a conferência que não fechou o dia. Nem o de hoje cujo
    último cálculo falhou: o gravado é de antes da falha, e a aberta dele
    tem o stop/alvo de quando o motor ainda rodava."""
    if status == "rodando" and dia < hoje:
        return "nao_conferido", False
    if status == "rodando" and falha:
        return "falha", False
    return status, status == "rodando" and dia >= hoje


def _por_ligacao(con, portfolio_id: int, dia: date, hoje: date) -> list[dict]:
    """O que a tela mostra de cada ligação no dia — base de `resumo`,
    `variantes` e `alertas`, para os três nunca discordarem."""
    ligs = _ligacoes(con, portfolio_id, dia)
    ops = _ops_do_dia(con, [l["ligacao_id"] for l in ligs], dia)
    out = []
    for l in ligs:
        lig = l["ligacao_id"]
        gravado, status, motivo, falha = _pregao(con, lig, dia)
        p = _plano_do_dia(con, l["variante_id"], dia, gravado)
        status, vivo = _situacao(status, dia, hoje, falha)
        if status == "nao_conferido":
            motivo = _MOTIVO_PRESO
        elif status == "falha":
            motivo = falha
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
                hoje: date | None = None) -> dict:
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
            "demo": _demo_do_comparativo(con, portfolio_id, dia, planos),
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
                         planos: dict[int, dict]) -> dict | None:
    """A coluna Demo: o recorte do papel (plano em vigor de cada ligação,
    desde que ele vale) aplicado às operações da demo.

    O resultado da demo vem BRUTO da corretora (`operacoes_demo`); aqui
    desconta-se o custo do plano como o papel desconta, senão a demo
    pareceria melhor só por não pagar corretagem. Derrapagem é a de
    `operacoes_demo` (ticks além do papel, por ponta; negativo = melhor
    que o papel), a mesma da tabela Papel × demo.
    """
    pregoes = _pregoes_demo(con, portfolio_id, dia)
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


# ======================================================================
# Parte 4: a demo ao lado do papel (spec ordens §8)
# ======================================================================
_COLS_EV = ("evento_id", "quando", "tipo", "conta_id", "ligacao_id", "entry_ts",
            "lado", "contratos", "simbolo", "ticket", "retcode", "preco_papel",
            "preco", "atraso_ms", "tentativa", "motivo")
# o que marca uma operação como tentada NA DEMO (o ensaio `seria_enviada`
# não é demo: com o Envio desligado nada foi à corretora)
_TENTOU = ("enviando", "executada", "parcial", "adotada", "recusada",
           "perdida", "nao_entrou", "aceita", "incerta")
_ENTROU = ("executada", "parcial", "adotada")
_SAIDA_FINAL = ("saida_executada", "saiu_antes")
# toda ordem que a corretora recusou: entrada, saída, proteção, cancelamento
_RECUSAS = ("recusada", "saida_recusada", "protecao_recusada",
            "cancelar_recusada")
# motivo da saída gravado pelo motor -> como a mesa chama
_MOTIVO_SAIDA = {"papel zerado": "sinal"}


def _ligs_do_portfolio(con, portfolio_id: int) -> list[int]:
    """Todas as ligações que o portfólio já teve, removidas inclusive: o
    diário de um dia passado pode ter eventos de uma que saiu depois."""
    return [int(r[0]) for r in con.execute(
        "SELECT ligacao_id FROM portfolio_membros WHERE portfolio_id = ?",
        [portfolio_id]).fetchall()]


def eventos_ordens(con, portfolio_id: int, dia: date) -> list[dict]:
    """O diário das ordens do dia (o espelho `ordens_eventos`): os eventos
    das ligações do portfólio e os da automação sem ligação (chamado de
    infraestrutura, comando, trava da conta). Em ordem de tempo; os campos
    de `dados` vêm soltos no dicionário, como no arquivo do diário."""
    ini, fim = _limites(dia)
    ligs = _ligs_do_portfolio(con, portfolio_id)
    filtro = "ligacao_id IS NULL"
    if ligs:
        filtro += f" OR ligacao_id IN ({', '.join('?' * len(ligs))})"
    linhas = con.execute(
        f"SELECT {', '.join(_COLS_EV)}, dados FROM ordens_eventos "
        f"WHERE quando >= ? AND quando < ? AND ({filtro}) "
        "ORDER BY quando, evento_id", [ini, fim, *ligs]).fetchall()
    out = []
    for r in linhas:
        e = dict(zip(_COLS_EV, r[:-1]))
        if r[-1]:
            try:
                extra = json.loads(r[-1])
            except (TypeError, ValueError):
                extra = {}
            if isinstance(extra, dict):
                # as colunas mandam: `dados` só traz o que não tem coluna
                e.update({k: v for k, v in extra.items() if k not in e})
        out.append(e)
    return out


def _derrapagem(preco_demo, preco_papel, lado, tick, ponta: str):
    """Ticks por ponta, positivo = pior para o operador. Entrada: pagar
    mais caro na compra (vender mais barato na venda) é pior; saída: o
    contrário. Sem um dos preços: None (não se inventa zero)."""
    if preco_demo is None or preco_papel is None or not lado or not tick:
        return None
    dif = float(preco_demo) - float(preco_papel)
    if ponta == "saida":
        dif = -dif
    return dif * int(lado) / float(tick)


def _preco_medio(saidas: list[dict]):
    """Preço médio das saídas (parciais e a final), pesado pelos contratos."""
    com = [(float(e["preco"]), float(e.get("contratos") or 0)) for e in saidas
           if e.get("preco") is not None]
    if not com:
        return None
    peso = sum(c for _, c in com)
    if peso <= 0:
        return com[-1][0]
    return sum(p * c for p, c in com) / peso


def _texto_pedido(e: dict) -> str:
    """"VENDA 2 WINV26 · stop 188.575 · alvo 187.495" — o que iria à
    corretora, para o ensaio com o Envio desligado ser conferível."""
    lado = "COMPRA" if (e.get("lado") or 0) > 0 else "VENDA"
    ctr = e.get("contratos")
    partes = [f"{lado} {'' if ctr is None else int(ctr)} {e.get('simbolo') or ''}"
              .replace("  ", " ").strip()]
    for rot, chave in (("stop", "stop_px"), ("alvo", "alvo_px")):
        if e.get(chave) is not None:
            partes.append(f"{rot} {int(e[chave]):,}".replace(",", "."))
    return " · ".join(partes)


def checagem_ensaio(e: dict) -> str | None:
    """O que o `order_check` disse do pedido do ensaio ("seria enviada"):
    None quando passou (retcode 0) ou o evento é de antes da conferência.
    O retcode 0 é o "Done" do exemplo oficial do order_check (mql5.com)."""
    erro = e.get("last_error")
    if erro:
        return f"conferência sem resposta do MT5 ({_texto_erro(erro)})"
    rc = e.get("retcode")
    if rc is None:
        return None
    try:
        rc = int(rc)
    except (TypeError, ValueError):
        return None
    if rc == 0:
        return None
    from .corretora import TEXTOS
    return f"seria recusada: {e.get('comment') or TEXTOS.get(rc) or f'retorno {rc}'}"


def _texto_erro(erro) -> str:
    if isinstance(erro, (list, tuple)):
        return " ".join(str(x) for x in erro if x is not None)
    return str(erro)


def _ordinal(n: int) -> str:
    return f"{n}ª"


def _uma_operacao_demo(chave, evs: list[dict], papel_op: dict | None,
                       lig: dict, tick: int, pv: float,
                       slip_plano: float | None = None) -> dict:
    """Uma linha da tabela "Operações do dia" da demo, a partir de todos os
    eventos da operação `(ligacao_id, entry_ts)` (os de saída casados pelo
    ticket). `slip_plano`: a derrapagem que o plano da operação supõe,
    em ticks por ponta (o preço do papel já a inclui)."""
    lig_id, entry_ts = chave
    tipos = [e["tipo"] for e in evs]
    com_lado = next((e for e in evs if e.get("lado")), None)
    lado = int(com_lado["lado"]) if com_lado else (
        int(papel_op["side"]) if papel_op else None)
    linha = {"ligacao_id": lig_id, "entry_ts": entry_ts,
             "variante": lig["nome"], "cor": lig["cor"], "lado": lado,
             "contratos": None, "preco_entrada": None, "preco_saida": None,
             "exit_ts": None, "derrapagem_entrada": None,
             "derrapagem_saida": None, "pontos": None, "resultado": None,
             "situacao": None, "saida_motivo": None, "nota": None,
             "pedido": None, "checagem": None, "atraso_ms": None,
             "mesmo_minuto": False,
             "recusas": tipos.count("recusada"),
             "rejeitadas": sum(tipos.count(t) for t in _RECUSAS),
             # o atraso de cada execução da entrada (a adoção não tem)
             "atrasos_ms": [float(e["atraso_ms"]) for e in evs
                            if e["tipo"] in ("executada", "parcial")
                            and e.get("atraso_ms") is not None],
             "slippage_plano": slip_plano, "papel_mesmo_tamanho": None,
             "papel_liquido": None if papel_op is None
             else float(papel_op["liquido"] or 0.0)}
    entradas = [e for e in evs if e["tipo"] in _ENTROU]
    if not entradas:
        if "seria_enviada" in tipos:
            e = next(e for e in evs if e["tipo"] == "seria_enviada")
            linha.update(situacao="seria_enviada", pedido=_texto_pedido(e),
                         checagem=checagem_ensaio(e))
            return linha
        perdida = next((e for e in reversed(evs) if e["tipo"] == "perdida"), None)
        if perdida is not None:
            motivo = perdida.get("motivo")
            if motivo == "automação fora do ar":
                linha["situacao"] = "fora_do_ar"
            elif "recusada" in tipos:
                linha["situacao"] = "recusada_perdida"
            else:
                linha["situacao"] = "perdida"
            linha["nota"] = motivo
        elif "nao_entrou" in tipos:
            e = next(e for e in evs if e["tipo"] == "nao_entrou")
            linha.update(situacao="nao_entrou", nota=e.get("motivo"))
        elif "recusada" in tipos and tipos[-1] == "recusada":
            linha["situacao"] = "recusada"      # segue tentando na janela
        else:
            linha["situacao"] = "enviando"
        return linha

    ent = entradas[0]
    contratos = sum(float(e.get("contratos") or 0) for e in entradas
                    if e["tipo"] != "adotada") or float(ent.get("contratos") or 0)
    preco_ent = float(ent["preco"]) if ent.get("preco") is not None else None
    papel_ent = (papel_op["entry_px"] if papel_op is not None
                 else ent.get("preco_papel"))
    if papel_op is not None and papel_op.get("bruto") is not None \
            and papel_op.get("contratos"):
        # o papel no tamanho da demo e bruto como ela: o papel opera os
        # contratos do plano e desconta custos; a demo, os dela e sem custo
        linha["papel_mesmo_tamanho"] = round(
            float(papel_op["bruto"]) / int(papel_op["contratos"]) * contratos, 2)
    linha.update(contratos=contratos, preco_entrada=preco_ent,
                 atraso_ms=ent.get("atraso_ms"),
                 derrapagem_entrada=_derrapagem(preco_ent, papel_ent, lado,
                                                tick, "entrada"),
                 # a ordem saiu no mesmo minuto do sinal do papel?
                 mesmo_minuto=ent["quando"].replace(second=0, microsecond=0)
                 == entry_ts.replace(second=0, microsecond=0))
    finais = [e for e in evs if e["tipo"] in _SAIDA_FINAL]
    if not finais:
        linha["situacao"] = "aberta"
        return linha
    fim = finais[-1]
    saidas = [e for e in evs if e["tipo"] in ("saida_parcial", "saida_executada",
                                              "saiu_antes")]
    preco_sai = _preco_medio(saidas)
    papel_sai = (papel_op["exit_px"] if papel_op is not None
                 and papel_op.get("exit_px") is not None else None)
    pontos = (None if preco_sai is None or preco_ent is None
              else (preco_sai - preco_ent) * lado)
    motivo = fim.get("motivo") or ""
    # a corretora "executou" o stop/alvo sem negócio nesse preço: o preço da
    # saída não é de mercado, então não entra na derrapagem
    fora = any(e.get("fora_do_mercado") for e in saidas)
    linha.update(situacao="fechada", exit_ts=fim["quando"],
                 preco_saida=preco_sai,
                 derrapagem_saida=None if fora else _derrapagem(
                     preco_sai, papel_sai, lado, tick, "saida"),
                 pontos=None if pontos is None else round(pontos),
                 resultado=None if pontos is None
                 else round(pontos * contratos * pv, 2),
                 saida_motivo=_MOTIVO_SAIDA.get(motivo, motivo or None))
    envios = [e for e in evs if e["tipo"] == "saida_enviando"]
    if fora:
        linha["nota"] = "execução fora do mercado (corretora)"
    elif len(envios) > 1 and fim["tipo"] == "saida_executada":
        recusa = next((e.get("motivo") for e in reversed(evs)
                       if e["tipo"] == "saida_recusada" and e.get("motivo")), None)
        seg = round((fim["quando"] - envios[0]["quando"]).total_seconds())
        detalhe = f"{recusa}, {seg} s" if recusa else f"{seg} s"
        linha["nota"] = (f"saiu na {_ordinal(len(envios))} tentativa "
                         f"({detalhe})")
    return linha


def operacoes_demo(con, portfolio_id: int, dia: date,
                   symbol: str = _papel.SIMBOLO) -> list[dict]:
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
    for e in eventos_ordens(con, portfolio_id, dia):
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


def _impressao_do_dia(con, ligs: list[int], d: date) -> tuple:
    ini, fim = _limites(d)
    marcas = ", ".join("?" * len(ligs))
    n_ev = con.execute(
        f"SELECT count(*) FROM ordens_eventos WHERE quando >= ? AND quando < ? "
        f"AND (ligacao_id IS NULL OR ligacao_id IN ({marcas}))",
        [ini, fim, *ligs]).fetchone()[0]
    n_op, calc = con.execute(
        f"SELECT count(*), max(calculado_em) FROM papel_operacoes WHERE dia = ? "
        f"AND ligacao_id IN ({marcas})", [d, *ligs]).fetchone()
    return int(n_ev), int(n_op), calc


def _demo_do_dia(con, portfolio_id: int, d: date) -> tuple:
    """(pontos do papel, operações da demo, chamados) de um pregão — só as
    ligações que tentaram operar na demo nele."""
    linhas = operacoes_demo(con, portfolio_id, d)
    demo_ops = [o for o in linhas if o["situacao"] != "seria_enviada"]
    tentaram = {o["ligacao_id"] for o in demo_ops}
    papel_pts = [float(o["points"] or 0) for o in _ops_do_dia(con, sorted(tentaram), d)
                 if o["conta"] and not o["aberta"]]
    chamados = sum(1 for e in eventos_ordens(con, portfolio_id, d)
                   if e["tipo"] == "chamado" and e.get("ligacao_id") in tentaram)
    return papel_pts, demo_ops, chamados


def _pregoes_demo(con, portfolio_id: int, dia: date) -> list[tuple]:
    """`[(dia, parte do _demo_do_dia)]` dos pregões até `dia` em que alguma
    ligação do portfólio TENTOU operar na demo (o ensaio não conta).

    Pregão passado sai do `_CACHE_DEMO_DIA`; o de `dia` é sempre relido —
    ainda muda a cada volta da captura."""
    ligs = _ligs_do_portfolio(con, portfolio_id)
    if not ligs:
        return []
    marcas = ", ".join("?" * len(ligs))
    tentou = ", ".join(f"'{t}'" for t in _TENTOU)
    dias = [r[0] for r in con.execute(
        f"SELECT DISTINCT CAST(quando AS DATE) AS d FROM ordens_eventos "
        f"WHERE ligacao_id IN ({marcas}) AND tipo IN ({tentou}) "
        "AND CAST(quando AS DATE) <= ? ORDER BY d", [*ligs, dia]).fetchall()]
    out = []
    for d in dias:
        chave = None
        if d < dia:
            chave = (str(db.DB_PATH), portfolio_id, d,
                     _impressao_do_dia(con, ligs, d))
        parte = _CACHE_DEMO_DIA.get(chave) if chave else None
        if parte is None:
            parte = _demo_do_dia(con, portfolio_id, d)
            if chave:
                _CACHE_DEMO_DIA[chave] = parte
        out.append((d, parte))
    return out


def comparativo_demo(con, portfolio_id: int, *, dia: date | None = None,
                     hoje: date | None = None) -> dict:
    """Papel × demo por contrato, nos mesmos pregões (spec ordens §8).

    Entram os pregões em que alguma ligação do portfólio TENTOU operar na
    demo (o ensaio com o Envio desligado não conta) e, em cada um, só as
    ligações que tentaram: papel e demo olham as mesmas variantes nos
    mesmos dias. Pontos por contrato; fator de lucro pelos pontos (o papel
    tem custos do plano, a demo não — em pontos os dois comparam).
    """
    dia = dia or _hoje(hoje)
    pregoes = _pregoes_demo(con, portfolio_id, dia)
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
    from . import papel_backtest as _pb       # pesado (motor): só aqui
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
