"""Conferência diária ordens × backtest (irmã da papel × backtest).

A papel × backtest prova que o papel GRAVADO é o backtest. Em 05/11/2026
isso não bastou: o papel gravado estava certo e as ORDENS saíram de um
cálculo em memória que divergiu dele (aquecimento velho). Esta conferência
olha o que de fato foi à corretora: toda manhã, com as mesmas condições da
papel × backtest (candles reconferidos, papel conferido, fora do pregão),
compara as entradas executadas do dia — por conta, `origem` "real" e "demo"
à parte — com o backtest do plano no histórico inteiro.

Compara o que o backtest garante: o minuto da entrada, o lado e que a
operação saiu no dia. Preço e minuto da saída não entram — derrapagem e a
saída a mercado depois do toque são da corretora e já têm o comparativo
deles na tela Operação.

Confere todo dia em que a ligação esteve na fase dessa conta e ligada —
inclusive o dia SEM nenhuma ordem: o backtest entrou e a conta não é
justamente "a automação deixou de entrar". Fica de fora o dia fora da fase
ou desligada o dia todo (sem nenhuma tentativa: com tentativa, o que entrou
fora da fase é diferença), e o dia de ensaio — só "seria enviada", o Envio
desligado. Do backtest, só as entradas enquanto a ligação estava na fase e
ligada: a promovida às 14h não deixou de fazer o que entrou às 10h.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import papel
from . import papel_backtest as _pb
from . import plano as _plano
from .captura import PREFIXO_RECONFERENCIA

ORIGENS = ("real", "demo")
# tentativas de verdade (sem o ensaio "seria_enviada"): mesma lista da tela
_TENTOU = ("enviando", "executada", "parcial", "adotada", "recusada",
           "perdida", "nao_entrou", "aceita")
_ENTROU = ("executada", "parcial", "adotada")
_SAIDA_FINAL = ("saida_executada", "saiu_antes")
# a fase que cada conta opera (real ⊃ demo, como em `papel_vivo.ler_retrato`)
_FASES_DA_ORIGEM = {"demo": ("demo", "real", "real_minimo"),
                    "real": ("real", "real_minimo")}


def ordens_do_dia(con, ligacao_id: int, dia: date, origem: str) -> dict | None:
    """`{entry_ts: {lado, entrou, fechada, situacao}}` das operações do dia
    nessa conta (vazio: nenhuma), ou None no dia de ensaio — só "seria
    enviada", sem tentativa de verdade. As saídas só trazem o ticket:
    casam com a entrada por ele."""
    ini = datetime.combine(dia, datetime.min.time())
    evs = con.execute(
        "SELECT tipo, entry_ts, lado, ticket FROM ordens_eventos "
        "WHERE ligacao_id = ? AND origem = ? AND quando >= ? AND quando < ? "
        "ORDER BY quando, evento_id",
        [ligacao_id, origem, ini, ini + timedelta(days=1)]).fetchall()
    if not any(t in _TENTOU for t, *_ in evs):
        return None if any(t == "seria_enviada" for t, *_ in evs) else {}
    ops: dict = {}
    dono: dict = {}
    for tipo, ts, lado, ticket in evs:
        if ts is not None:
            o = ops.setdefault(ts, {"lado": None, "entrou": False,
                                    "fechada": False, "situacao": None})
            if lado and o["lado"] is None:
                o["lado"] = int(lado)
            if tipo in _ENTROU:
                o["entrou"] = True
                if ticket:
                    dono[int(ticket)] = ts
            if tipo in _TENTOU:
                o["situacao"] = tipo
        elif tipo in _SAIDA_FINAL and ticket and int(ticket) in dono:
            ops[dono[int(ticket)]]["fechada"] = True
    return ops


def comparar(ordens: dict, backtest: list[tuple]) -> list[dict]:
    """As diferenças, pela entrada: `a_mais` (a conta entrou, o backtest
    não), `a_menos` (o backtest entrou, a conta não), `lado` (os dois
    entraram em lados opostos) e `sem_saida` (a conta entrou e a operação
    não saiu no dia). Só entrada EXECUTADA é entrada; a tentativa que não
    entrou vai junto na `situacao`, para a tela dizer o porquê."""
    do_bt = {o[0]: int(o[1]) for o in backtest}
    entrou = {ts: o for ts, o in ordens.items() if o["entrou"]}
    out = []
    for ts in sorted(do_bt.keys() | entrou.keys()):
        o, b = entrou.get(ts), do_bt.get(ts)
        base = {"entry_ts": ts, "ordem": o and o["lado"], "backtest": b,
                "situacao": (ordens.get(ts) or {}).get("situacao")}
        if o is None:
            out.append({**base, "tipo": "a_menos"})
        elif b is None:
            out.append({**base, "tipo": "a_mais"})
        elif o["lado"] != b:
            out.append({**base, "tipo": "lado"})
        elif not o["fechada"]:
            out.append({**base, "tipo": "sem_saida"})
    return out


def _fase_em(trocas: list[tuple], atual: str, desde: datetime | None,
             instante: datetime) -> str:
    """A fase da ligação num instante, pelos `fase_mudou` (quando, de,
    para). Antes da primeira troca vale o `de` dela; sem troca nenhuma no
    diário, a fase de agora desde `fase_desde` e papel antes — senão o
    histórico inteiro de uma ligação na real viraria "a menos"."""
    if not trocas:
        return atual if desde is None or instante >= desde else "papel"
    antes = [t for t in trocas if t[0] <= instante]
    return antes[-1][2] if antes else trocas[0][1]


def _regua(con, ligacao_id: int, dia: date, origem: str):
    """`(conta(entry_ts) -> bool, esteve)`: se uma entrada do backtest
    conta para essa conta (ligada E na fase dela) e se a ligação esteve
    assim em algum momento do dia."""
    pf, atual, desde = con.execute(
        "SELECT portfolio_id, fase, fase_desde FROM portfolio_membros "
        "WHERE ligacao_id = ?", [ligacao_id]).fetchone()
    periodos = papel.periodos_ligados(con, ligacao_id, pf, dia)
    trocas = con.execute(
        "SELECT quando, de, para FROM ao_vivo_eventos WHERE tipo = 'fase_mudou' "
        "AND ligacao_id = ? ORDER BY quando, evento_id", [ligacao_id]).fetchall()
    fases = _FASES_DA_ORIGEM[origem]

    def conta(t):
        return (papel._conta(t, periodos)
                and _fase_em(trocas, atual, desde, t) in fases)
    # a fase só muda nas trocas (e no `fase_desde`): basta olhar o começo de
    # cada trecho ligado e cada mudança dentro dele
    marcos = [a for a, _b in periodos] + [t[0] for t in trocas] + (
        [desde] if desde is not None else [])
    return conta, any(conta(m) for m in marcos)


def _json(diferencas: list[dict]) -> str:
    def iso(x):
        return x.isoformat(sep=" ") if isinstance(x, datetime) else x
    return json.dumps({"operacoes": [{k: iso(v) for k, v in d.items()}
                                     for d in diferencas]})


def conferir(con, ligacao_id: int, dia: date, origem: str, cache_codigo: dict,
             agora: datetime, *, symbol: str = papel.SIMBOLO) -> dict:
    """Compara as ordens do dia nessa conta com o backtest e grava em
    `ordens_backtest` (upsert por ligação, dia e origem).

    Não grava (volta `ok = None`) quando não há o que comparar: a conta não
    operou a ligação no dia (`sem_ordens`), ou o papel conferido é de outro
    motor/código (`outra_versao`/`outro_codigo`) — a mesma régua da papel ×
    backtest, pelo mesmo motivo: o backtest de hoje rodaria outro cálculo."""
    if origem not in ORIGENS:
        raise ValueError("origem deve ser 'real' ou 'demo'")
    r = con.execute(
        "SELECT pm.portfolio_id, pm.fase, ev.estrategia, pp.plano_id, "
        "pp.status, pp.motor_versao, pp.codigo_hash "
        "FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "LEFT JOIN papel_pregoes pp ON pp.ligacao_id = pm.ligacao_id "
        "     AND pp.dia = ? "
        "WHERE pm.ligacao_id = ?", [dia, ligacao_id]).fetchone()
    if r is None:
        raise ValueError(f"ligação #{ligacao_id} não existe")
    _pf, _fase, est_variante, plano_id, status, motor, hash_dia = r
    if status != "conferido" or plano_id is None:
        raise ValueError(f"pregão {dia} da ligação #{ligacao_id} "
                         "não está conferido")
    out = {"ok": None, "n_ordens": 0, "n_backtest": 0, "diferencas": [],
           "sem_ordens": False, "fora_da_fase": False,
           "outra_versao": False, "outro_codigo": False}
    ordens = ordens_do_dia(con, ligacao_id, dia, origem)
    if ordens is None:
        out["sem_ordens"] = True
        return out
    conta, esteve = _regua(con, ligacao_id, dia, origem)
    if not esteve and not ordens:
        out["fora_da_fase"] = True
        return out
    plano = _plano.detalhes(plano_id, con=con)
    estrategia = plano["strategy"] or est_variante
    hashes: dict = {}
    motivo = _pb._incomparavel(motor, hash_dia, estrategia, hashes)
    if motivo:
        out[motivo] = True
        return out

    mod = papel._modulo(estrategia, hashes[estrategia], cache_codigo)
    bt = [o for o in _pb._backtest(con, plano, mod, dia, symbol) if conta(o[0])]
    diferencas = comparar(ordens, bt)
    out.update(ok=not diferencas, n_backtest=len(bt), diferencas=diferencas,
               n_ordens=sum(1 for o in ordens.values() if o["entrou"]))
    con.execute(
        "INSERT INTO ordens_backtest (ligacao_id, dia, origem, conferido_em, ok, "
        "n_ordens, n_backtest, diferencas) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT (ligacao_id, dia, origem) DO UPDATE SET "
        "conferido_em = excluded.conferido_em, ok = excluded.ok, "
        "n_ordens = excluded.n_ordens, n_backtest = excluded.n_backtest, "
        "diferencas = excluded.diferencas",
        [ligacao_id, dia, origem, agora, out["ok"], out["n_ordens"],
         out["n_backtest"], _json(diferencas)])
    return out


def pendentes(con, symbol: str = papel.SIMBOLO) -> list[tuple[int, date, str]]:
    """Os `(ligacao_id, dia, origem)` que a manhã ainda precisa conferir: as
    condições da `papel_backtest.pendentes` (reconferência feita, papel
    conferido, checagem mais nova que os dois) e o dia ser conferível nessa
    conta (`conferir`: na fase e ligada, ou com tentativa; nunca ensaio).
    O dia que não é fica fora sem custo de backtest."""
    linhas = con.execute(
        "WITH reconf AS ("
        "  SELECT source_file, max(source_max_ts) AS quando FROM ingest_log "
        "  WHERE symbol = ? AND source_file LIKE ? GROUP BY source_file), "
        "origens AS (SELECT unnest(['real', 'demo']) AS origem) "
        "SELECT pp.ligacao_id, pp.dia, o.origem, pp.motor_versao, pp.codigo_hash, "
        "coalesce(p.strategy, ev.estrategia) FROM papel_pregoes pp "
        "CROSS JOIN origens o "
        "JOIN planos_operacao p ON p.plano_id = pp.plano_id "
        "JOIN portfolio_membros pm ON pm.ligacao_id = pp.ligacao_id "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "JOIN reconf r ON r.source_file = ? || strftime(pp.dia, '%Y-%m-%d') "
        "LEFT JOIN ordens_backtest ob ON ob.ligacao_id = pp.ligacao_id "
        "     AND ob.dia = pp.dia AND ob.origem = o.origem "
        "WHERE pp.status = 'conferido' AND p.symbol = ? "
        "  AND (ob.conferido_em IS NULL "
        "       OR ob.conferido_em < greatest(r.quando, pp.calculado_em)) "
        "ORDER BY pp.dia, pp.ligacao_id, o.origem DESC",
        [symbol, f"{PREFIXO_RECONFERENCIA}%", PREFIXO_RECONFERENCIA,
         symbol]).fetchall()
    hashes: dict = {}
    out = []
    for lig, d, origem, motor, hash_dia, est in linhas:
        if _pb._incomparavel(motor, hash_dia, est, hashes) is not None:
            continue
        ordens = ordens_do_dia(con, int(lig), d, origem)
        if ordens is None or not (ordens or _regua(con, int(lig), d, origem)[1]):
            continue
        out.append((int(lig), d, origem))
    return out


def situacao(con, ligacao_id: int) -> dict:
    """O selo da Avaliação: em quantos pregões as ordens já foram conferidas
    contra o backtest (real e demo no mesmo pregão contam uma vez), quantas
    diferenças, e se está tudo igual (`ok`; None = nada conferido ainda)."""
    pregoes, diferencas, ok = con.execute(
        "SELECT count(DISTINCT dia), "
        "coalesce(sum(json_array_length(diferencas, '$.operacoes')), 0), "
        "bool_and(ok) FROM ordens_backtest WHERE ligacao_id = ?",
        [ligacao_id]).fetchone()
    return {"pregoes": int(pregoes), "diferencas": int(diferencas),
            "ok": None if not pregoes else bool(ok)}


def falhas(con, ligacao_id: int, hash_atual: str | None, versao: str) -> tuple:
    """`(que valem hoje, mais antigas)`: dias com diferença entre ordens e
    backtest, pela mesma régua de `ao_vivo._falhas_da_conferencia` — só a
    do MESMO código e motor de hoje barra a promoção."""
    linhas = con.execute(
        "SELECT DISTINCT ob.dia, pp.codigo_hash, pp.motor_versao "
        "FROM ordens_backtest ob LEFT JOIN papel_pregoes pp "
        "ON pp.ligacao_id = ob.ligacao_id AND pp.dia = ob.dia "
        "WHERE ob.ligacao_id = ? AND NOT ob.ok ORDER BY ob.dia",
        [ligacao_id]).fetchall()
    atuais = sorted({d for d, h, m in linhas
                     if h is not None and h == hash_atual and m == versao})
    return atuais, sorted({d for d, _h, _m in linhas if d not in atuais})

