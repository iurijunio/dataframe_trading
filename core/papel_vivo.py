"""Papel ao vivo para as ordens: o desejado de cada ligação, sem banco.

Spec 2026-10-08-ao-vivo-ordens-design.md §3 e §5.1. O papel gravado no
banco (`papel.rodar_dia` + `gravar`) continua sendo o da tela e da
conferência; este módulo calcula A MESMA COISA, com as mesmas funções, só
que de um retrato da configuração e de barras em memória — uma mineração
segurando o banco não pode atrasar uma saída. Quem escolhe as ligações e o
plano do dia é `papel.preparar_dia`, a mesma régua do papel gravado.

Três estados por ligação: POSICAO (o papel tem operação aberta que conta e
a ligação opera agora), ZERADO (sabidamente não tem — a corretora deve
estar zerada) e INDISPONIVEL (não dá para saber; a automação só protege).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

import numpy as np
import polars as pl

from . import db_manager as db
from . import papel
from .engine.execution import prepare_bars

POSICAO, ZERADO, INDISPONIVEL = "posicao", "zerado", "indisponivel"


@dataclass(frozen=True)
class Desejado:
    estado: str
    lado: int = 0
    entry_ts: datetime | None = None
    entry_px: int | None = None
    stop_px: int | None = None
    alvo_px: int | None = None
    contratos: int = 0
    motivo: str | None = None
    toque_em: datetime | None = None


@dataclass
class LigacaoViva:
    ligacao_id: int
    portfolio_id: int | None
    status: str
    motivo: str | None
    plano: dict | None
    modulo: object | None
    periodos: list = field(default_factory=list)
    fase: str = "papel"
    conta_id: int | None = None
    contratos_conta: int | None = None
    ligada: bool = False          # pm.ligada AND portfolio.ligado, AGORA
    falha: str | None = None      # o preparo do papel falhou (não é "zerado")
    desvio: int = 0               # deviation da ordem, em pontos


@dataclass
class Retrato:
    dia: date
    lido_em: datetime
    ligacoes: dict
    contas: dict
    portfolio_de: dict
    # lido do arquivo local (banco ocupado na subida), não do banco: sem
    # plano nem código, só serve para saber a conta e proteger (M3)
    antigo: bool = False


# campos da LigacaoViva que o retrato salvo guarda: o plano e o módulo não
# (o papel não se calcula com o retrato antigo — só se protege e sai)
_CAMPOS_LIG = ("ligacao_id", "portfolio_id", "status", "motivo", "fase", "conta_id",
               "contratos_conta", "ligada", "falha", "desvio")


def retrato_para_json(r: Retrato) -> dict:
    return {
        "dia": r.dia.isoformat(), "lido_em": r.lido_em.isoformat(),
        "ligacoes": [dict({k: getattr(lv, k) for k in _CAMPOS_LIG},
                          periodos=[[a.isoformat() if a else None,
                                     b.isoformat() if b else None]
                                    for a, b in lv.periodos])
                     for lv in r.ligacoes.values()],
        "contas": {str(k): v for k, v in r.contas.items()},
        "portfolio_de": {str(k): v for k, v in r.portfolio_de.items()},
    }


def retrato_de_json(d: dict) -> Retrato:
    """O retrato salvo, marcado `antigo`. As chaves voltam a int (o JSON as
    guarda como texto)."""
    def hora(x):
        return datetime.fromisoformat(x) if x else None
    ligs = {}
    for x in d["ligacoes"]:
        lv = LigacaoViva(plano=None, modulo=None,
                         periodos=[(hora(a), hora(b)) for a, b in x.get("periodos") or []],
                         **{k: x.get(k) for k in _CAMPOS_LIG})
        ligs[int(lv.ligacao_id)] = lv
    return Retrato(dia=date.fromisoformat(d["dia"]), lido_em=hora(d["lido_em"]),
                   ligacoes=ligs, contas={int(k): v for k, v in d["contas"].items()},
                   portfolio_de={int(k): v for k, v in d["portfolio_de"].items()},
                   antigo=True)


def ler_retrato(con, dia: date, agora: datetime, cache_codigo: dict, *,
                symbol: str = papel.SIMBOLO, tipo: str = "demo") -> Retrato:
    """O retrato de UM processo: `tipo="demo"` lê a conta demo (ligação em
    fase demo ou real, porque real ⊃ demo) e `tipo="real"` lê a conta real
    (só ligação em fase real). Fora da fase desta conta a ligação sai como
    "papel", e `desejados` a zera."""
    if tipo not in ("demo", "real"):
        raise ValueError("tipo do retrato deve ser 'demo' ou 'real'")
    resultados, fila, planos = papel.preparar_dia(con, dia, agora, cache_codigo,
                                                  symbol=symbol)
    na_fila = {l["ligacao_id"]: (r, p) for r, l, p in fila}
    # "ligada agora" vem do estado atual das duas chaves, não dos períodos
    # do diário: o diário usa a hora do PC, e com o PC adiantado uma
    # variante desligada ainda entraria por alguns segundos (os períodos
    # ficam só para o `conta` de cada operação, como no papel gravado)
    meta = {r[0]: r[1:] for r in con.execute(
        "SELECT pm.ligacao_id, pm.portfolio_id, pm.fase, p.conta_demo_id, "
        "p.conta_real_id, pm.contratos_demo, pm.contratos_real, "
        "pm.ligada AND coalesce(p.ligado, false) "
        "FROM portfolio_membros pm "
        "JOIN portfolios p ON p.portfolio_id = pm.portfolio_id").fetchall()}
    tick = int(db.load_instrument_yaml(symbol)["tick_size"])
    ligs = {}
    for r in resultados:
        lig = r["ligacao_id"]
        pf, fase_banco, c_demo, c_real, k_demo, k_real, ligada = meta.get(
            lig, (None, "papel", None, None, None, None, False))
        if tipo == "real":
            fase_ok, conta, contratos = (fase_banco == "real", c_real, k_real)
        else:
            fase_ok, conta, contratos = (fase_banco in ("demo", "real"),
                                         c_demo, k_demo)
        # "papel" fora da fase desta conta: a desejados zera como papel
        fase = fase_banco if fase_ok else "papel"
        lp = na_fila.get(lig)
        plano = lp[1] if lp else None
        falha = r.get("falha")
        desvio = 2 * tick
        if plano is not None:
            try:
                _, perfil = papel.perfil_do_plano(plano)
                desvio += int(round(float(perfil.slippage_ticks or 0) * tick))
            except Exception as erro:
                # plano que não monta perfil também não calcula papel: o
                # `rodar_dia` daria falha a esta ligação, aqui também — e
                # um plano quebrado não derruba o retrato das outras
                falha = f"falha no cálculo: {erro}"
        ligs[lig] = LigacaoViva(
            ligacao_id=lig, portfolio_id=pf, status=r["status"], motivo=r["motivo"],
            plano=plano,
            modulo=planos[plano["plano_id"]][1] if plano is not None else None,
            periodos=papel.periodos_ligados(con, lig, pf, dia) if pf else [],
            fase=fase, conta_id=conta,
            contratos_conta=int(contratos) if contratos else None,
            ligada=bool(ligada), falha=falha, desvio=desvio)
    # `tipo` (demo/real): a "Ordem de teste" só roda na conta cadastrada demo
    contas = {int(r[0]): {"login": r[1], "servidor": r[2], "limite": r[3],
                          "envio": bool(r[4]), "tipo": r[5]}
              for r in con.execute(
                  "SELECT conta_id, login, servidor, limite_perda_dia, "
                  "coalesce(envio_ligado, false), tipo FROM contas "
                  "WHERE arquivada_em IS NULL").fetchall()}
    return Retrato(dia=dia, lido_em=agora, ligacoes=ligs, contas=contas,
                   portfolio_de={lig: v[0] for lig, v in meta.items()})


@dataclass(frozen=True)
class Aquecimento:
    """As barras dos pregões antes do dia e QUANTOS pregões foram pedidos.

    O número viaja junto porque o aquecimento é lido uma vez por pregão, e
    uma ligação de janela mais longa promovida no meio do dia calcularia
    com passado de menos — sinal diferente do papel gravado, sem aviso.
    Com ele, `desejados` recusa essa ligação até o aquecimento ser relido.
    """
    barras: dict
    pregoes: int


def _pregoes(lv: LigacaoViva) -> int:
    estrat, perfil = papel.perfil_do_plano(lv.plano)
    return papel.pregoes_de_aquecimento(lv.modulo, estrat, perfil)


def pregoes_necessarios(retrato: Retrato) -> int:
    """O maior aquecimento entre as ligações do retrato (mesma conta de
    `papel.pregoes_de_aquecimento`). Quem chama relê o aquecimento quando
    isto passar do `Aquecimento.pregoes` carregado."""
    pregoes = 1
    for lv in retrato.ligacoes.values():
        if lv.plano is None or lv.modulo is None:
            continue
        try:       # um plano quebrado não derruba o aquecimento dos outros
            pregoes = max(pregoes, _pregoes(lv))
        except Exception:
            continue
    return pregoes


def carregar_aquecimento(con, symbol: str, dia: date,
                         retrato: Retrato) -> Aquecimento | None:
    """Os pregões ANTES do dia, uma vez por pregão, para a ligação de maior
    aquecimento do retrato. `pregoes` é o pedido, não o achado: com menos
    histórico no banco o `papel.barras_do_dia` também usa o que há."""
    pregoes = pregoes_necessarios(retrato)
    ini = datetime.combine(dia, time())
    datas = con.execute(
        "SELECT DISTINCT CAST(ts AS DATE) AS d FROM bars_m1 WHERE symbol = ? "
        "AND ts < ? ORDER BY d DESC LIMIT ?", [symbol, ini, pregoes]).fetchall()
    if not datas:
        return None
    return Aquecimento(
        barras=prepare_bars(con, symbol,
                            start=datetime.combine(min(r[0] for r in datas), time()),
                            end=ini - timedelta(microseconds=1)),
        pregoes=pregoes)


def barras_de_hoje(df: pl.DataFrame) -> dict:
    """O que a captura buscou no MT5 (`mt5_source.barras_de_taxas`), no
    formato de `prepare_bars`. Preço com 0 casas (`price_decimals` do WIN)."""
    def inteiro(c):
        return np.rint(df[c].to_numpy()).astype(np.int64)
    return {"ts": df["ts"].to_numpy().astype("datetime64[ns]"),
            "open": inteiro("open"), "high": inteiro("high"),
            "low": inteiro("low"), "close": inteiro("close"),
            "tick_volume": inteiro("tick_volume"), "volume": inteiro("volume")}


def _juntar(a: dict, b: dict) -> dict:
    return {k: np.concatenate([a[k], b[k]]) for k in a}


# o pregão começa às 09:00; do minuto seguinte em diante tem de haver candle
_ABERTURA = time(9, 1)
# um minuto que fecha atrasado no MT5 não derruba o papel; dois, sim
_ATRASO_MAX = timedelta(minutes=2)


def _hoje_velho(hoje: dict, agora_srv: datetime) -> bool:
    """As barras de hoje não chegam até agora: logo depois de (re)conectar o
    `copy_rates_range` pode vir vazio ou cortado. Calculado assim, o papel
    não acharia a operação aberta e o desejado seria ZERADO — a automação
    encerraria a posição e não entraria de novo."""
    if agora_srv.time() < _ABERTURA:
        return False
    if not len(hoje["ts"]):
        return True
    minuto = np.datetime64(agora_srv.replace(second=0, microsecond=0), "ns")
    return hoje["ts"][-1] < minuto - np.timedelta64(_ATRASO_MAX)


def aplicar_toque(desejados: dict, maxima: int | None,
                  minima: int | None) -> dict:
    """Zera no toque a posição cujo stop ou alvo já foi tocado pelo candle
    em formação (máxima e mínima dele até agora). Devolve um dict NOVO.

    Compra: mínima <= stop zera (stop no toque); senão máxima >= alvo zera
    (alvo no toque). Venda é o espelho. Se stop e alvo forem tocados no mesmo
    candle, vale o stop. Só mexe em POSICAO com stop ou alvo; `maxima`/`minima`
    None não muda nada. O ZERADO mantém os campos da operação para a
    execução saber o que foi tocado.
    """
    if maxima is None or minima is None:
        return dict(desejados)
    out = {}
    for lig, d in desejados.items():
        if d.estado != POSICAO or (d.stop_px is None and d.alvo_px is None):
            out[lig] = d
            continue
        # plano sem alvo (ou sem stop) ainda vigia o outro lado
        stop, alvo = d.stop_px, d.alvo_px
        if d.lado == 1:
            stop_toca = stop is not None and minima <= stop
            alvo_toca = alvo is not None and maxima >= alvo
        elif d.lado == -1:
            stop_toca = stop is not None and maxima >= stop
            alvo_toca = alvo is not None and minima <= alvo
        else:
            out[lig] = d
            continue
        if stop_toca:
            out[lig] = replace(d, estado=ZERADO, motivo="stop no toque")
        elif alvo_toca:
            out[lig] = replace(d, estado=ZERADO, motivo="alvo no toque")
        else:
            out[lig] = d
    return out


def desejados(retrato: Retrato | None, aquecimento: Aquecimento | None,
              hoje: dict | None, provisoria: tuple[datetime, int] | None,
              inst: dict, agora_srv: datetime | None) -> tuple[dict, bool]:
    """O desejado de cada ligação e se o papel está disponível.

    `({}, False)` sem retrato do dia, aquecimento, barras ou relógio do
    servidor, com as barras de hoje atrasadas (`_hoje_velho`) ou com a
    provisória que não cola (buraco entre o último candle e o minuto em
    formação): nada se sabe e a automação só confere a proteção.

    O stop/alvo é o que vale DURANTE o minuto em formação. O motor roda as
    proteções (breakeven, stop móvel, trailing) no fim de toda barra,
    inclusive da provisória, e com ela subiria o stop um minuto antes do
    backtest. Por isso cada plano é calculado duas vezes: com a provisória
    (decide entradas e saídas) e sem ela (o stop do fim da última barra
    fechada). A operação que entrou na provisória ainda não passou por fim
    de barra nenhum: vale o stop/alvo da entrada.
    """
    if (retrato is None or aquecimento is None or hoje is None
            or agora_srv is None or retrato.dia != agora_srv.date()
            or _hoje_velho(hoje, agora_srv)):
        return {}, False
    barras = _juntar(aquecimento.barras, hoje)
    com = barras
    prov_do_dia = provisoria is not None and provisoria[0].date() == retrato.dia
    if prov_do_dia:
        com = papel.com_barra_provisoria(barras, *provisoria)
    usou = len(com["ts"]) > len(barras["ts"])
    if prov_do_dia and not usou and len(hoje["ts"]):
        # candle faltando antes do minuto em formação: sem a provisória a
        # entrada deste minuto não apareceria e a posição pareceria zerada
        return {}, False
    out: dict[int, Desejado] = {}
    # plano_id -> (operações decididas, {entry_ts: operação sem a provisória})
    calculados: dict[int, tuple[list, dict | None]] = {}
    for lig, lv in retrato.ligacoes.items():
        # desligada ou fora da demo sai sem precisar de cálculo nenhum: vem
        # antes da falha, senão uma estratégia quebrada prenderia a posição
        if lv.fase not in ("demo", "real"):
            out[lig] = Desejado(ZERADO, motivo="fase papel")
            continue
        if not lv.ligada:
            out[lig] = Desejado(ZERADO, motivo="desligada")
            continue
        if lv.falha:
            # falha no preparo (plano, hash do código): não se sabe — protege
            out[lig] = Desejado(INDISPONIVEL, motivo=lv.falha)
            continue
        if lv.status != "rodando" or lv.plano is None:
            out[lig] = Desejado(ZERADO, motivo=lv.motivo or lv.status)
            continue
        try:
            precisa = _pregoes(lv)
        except Exception as erro:
            out[lig] = Desejado(INDISPONIVEL, motivo=f"falha no cálculo: {erro}")
            continue
        if precisa > aquecimento.pregoes:
            # passado de menos muda o sinal: até o aquecimento ser relido
            out[lig] = Desejado(INDISPONIVEL, motivo="aquecimento insuficiente")
            continue
        pid = lv.plano["plano_id"]
        try:
            if pid not in calculados:
                ops = papel.calcular(com, retrato.dia, lv.plano, lv.modulo,
                                     inst, None, usou)
                vigente = None
                if usou:
                    vigente = {o["entry_ts"]: o for o in papel.calcular(
                        barras, retrato.dia, lv.plano, lv.modulo, inst)}
                calculados[pid] = (ops, vigente)
        except Exception as erro:          # uma ligação não derruba as outras
            out[lig] = Desejado(INDISPONIVEL, motivo=f"falha no cálculo: {erro}")
            continue
        ops, vigente = calculados[pid]
        abertas = [o for o in ops
                   if o["aberta"] and papel._conta(o["entry_ts"], lv.periodos)]
        if not abertas:
            out[lig] = Desejado(ZERADO)
            continue
        o = abertas[-1]
        stop, alvo = o["stop_px"], o["alvo_px"]
        if vigente is not None:
            antes = vigente.get(o["entry_ts"])
            if antes is not None:
                # já existia no fim da última barra fechada: o stop de lá
                stop, alvo = antes["stop_px"], antes["alvo_px"]
            else:
                # entrou na provisória: o da entrada
                stop, alvo = o["stop_ini_px"], o["alvo_ini_px"]
        out[lig] = Desejado(POSICAO, lado=int(o["side"]), entry_ts=o["entry_ts"],
                            entry_px=int(o["entry_px"]), stop_px=stop,
                            alvo_px=alvo,
                            contratos=lv.contratos_conta or int(lv.plano["contratos"]))
    return out, True
