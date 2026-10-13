"""A corretora vista pela automação: retornos, pedidos e fotografia.

Spec: docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md §5–6.
Aqui não se decide operar nada — só se traduz. A tabela de retornos é a
peça mais perigosa da parte 4: tratar um "aceita, aguardando" (PLACED) como
erro e reenviar duplica a posição; tratar um "sem margem" como passageiro
fica tentando para sempre. Por isso ela é única, por número (o pacote
5.0.6180 nem tem todas as constantes, ex.: HEDGE_PROHIBITED) e testada
código a código contra a documentação oficial
(mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

OK = "ok"
INCERTA = "incerta"                # sem resposta: pode ter executado
ACEITA = "aceita"                  # PLACED: a bolsa recebeu, o negócio vem depois
PARCIAL = "parcial"
PASSAGEIRA = "passageira"          # resolve sozinha: tentar de novo
USUARIO = "usuario"                # configuração: chamar o usuário
JA_SAIU = "ja_saiu"                # a posição já não existe
SEM_MUDANCA = "sem_mudanca"        # SL/TP já estão como pedido
SAIDA_EM_TRANSITO = "saida_em_transito"
PREENCHIMENTO = "preenchimento"    # modo de preenchimento recusado
VOLUME_FECHAMENTO = "volume_fechamento"
STOPS_INVALIDOS = "stops_invalidos"
DESCONHECIDO = "desconhecido"

RETORNOS: dict[int, str] = {
    10004: PASSAGEIRA,   # requote
    10006: PASSAGEIRA,   # pedido rejeitado
    10007: PASSAGEIRA,   # cancelado
    10008: ACEITA,       # ordem colocada (execução em bolsa)
    10009: OK,
    10010: PARCIAL,
    10011: PASSAGEIRA,   # erro de processamento
    10012: INCERTA,      # timeout: pode ter executado
    10013: USUARIO,      # pedido inválido
    10014: USUARIO,      # volume inválido
    10015: USUARIO,      # preço inválido
    10016: STOPS_INVALIDOS,
    10017: USUARIO,      # negociação desabilitada
    10018: PASSAGEIRA,   # mercado fechado (leilão, por instantes)
    10019: USUARIO,      # sem margem
    10020: PASSAGEIRA,   # preço mudou
    10021: PASSAGEIRA,   # sem cotação
    10022: USUARIO,      # validade inválida
    10023: PASSAGEIRA,   # ordem mudou de estado
    10024: PASSAGEIRA,   # pedidos demais
    10025: SEM_MUDANCA,
    10026: USUARIO,      # Algo Trading desligado no servidor
    10027: USUARIO,      # Algo Trading desligado no terminal
    10028: PASSAGEIRA,   # travado para processamento
    10029: PASSAGEIRA,   # ordem/posição congelada
    10030: PREENCHIMENTO,
    10031: PASSAGEIRA,   # sem conexão com o servidor
    10032: USUARIO,      # só conta real
    10033: USUARIO,      # limite de ordens pendentes
    10034: USUARIO,      # limite de volume
    10035: USUARIO,      # tipo de ordem proibido
    10036: JA_SAIU,
    10038: VOLUME_FECHAMENTO,
    10039: SAIDA_EM_TRANSITO,
    10040: USUARIO,      # limite de posições
    10041: PASSAGEIRA,   # ativação recusada, ordem cancelada
    10042: USUARIO,      # só compra
    10043: USUARIO,      # só venda
    10044: USUARIO,      # só encerramento (vencimento)
    10045: USUARIO,      # regra FIFO
    10046: USUARIO,      # posição contrária proibida (conta não é hedging)
}

TEXTOS: dict[int, str] = {
    10004: "requote", 10006: "recusada pela corretora", 10007: "cancelada",
    10008: "aceita, aguardando a bolsa", 10009: "executada",
    10010: "executada em parte", 10011: "erro na corretora",
    10012: "sem resposta a tempo", 10013: "pedido inválido",
    10014: "volume inválido", 10015: "preço inválido",
    10016: "stop ou alvo inválido", 10017: "negociação desabilitada",
    10018: "mercado fechado (leilão)", 10019: "sem margem",
    10020: "preço mudou", 10021: "sem cotação", 10022: "validade inválida",
    10023: "ordem mudou de estado", 10024: "pedidos demais",
    10025: "nada a mudar", 10026: "Algo Trading desligado na corretora",
    10027: "Algo Trading desligado no MT5", 10028: "em processamento",
    10029: "posição congelada", 10030: "modo de preenchimento recusado",
    10031: "sem conexão com a corretora", 10032: "só conta real",
    10033: "limite de ordens", 10034: "limite de volume",
    10035: "tipo de ordem proibido", 10036: "posição já encerrada",
    10038: "volume maior que a posição", 10039: "saída já em andamento",
    10040: "limite de posições", 10041: "ordem cancelada pela corretora",
    10042: "só compra permitida", 10043: "só venda permitida",
    10044: "só encerramento (vencimento)", 10045: "regra FIFO",
    10046: "conta não aceita posições contrárias",
}


def classificar(resultado) -> str:
    """`None` acontece com o terminal sem resposta: INCERTA — a ordem pode
    ter executado; a reconciliação só reenvia depois de conferir o
    histórico de ordens."""
    if resultado is None:
        return INCERTA
    return RETORNOS.get(int(resultado.retcode), DESCONHECIDO)


def texto(resultado) -> str:
    if resultado is None:
        return "sem resposta do MT5"
    c = int(resultado.retcode)
    return TEXTOS.get(c, f"retorno desconhecido {c}")


# ---------------------------------------------------------------- magic
MAGIC_BASE = 7_000_000
_MAGIC_FIM = 7_999_999


def magic(ligacao_id: int) -> int:
    return MAGIC_BASE + int(ligacao_id)


def ligacao_do_magic(m) -> int | None:
    """Fora da faixa = posição que a automação não abriu (à mão, outro
    robô): nunca é tocada (D4)."""
    m = int(m or 0)
    return m - MAGIC_BASE if MAGIC_BASE < m <= _MAGIC_FIM else None


# --------------------------------------------------------- preenchimento
# SYMBOL_FILLING_MODE é máscara de bits (FOK = 1, IOC = 2) — não o valor de
# ORDER_FILLING_* (FOK 0, IOC 1, RETURN 2). Em execução em bolsa RETURN vale
# sempre, mas deixa o resto da ordem viva (D3 manda cancelar): fica por último.
_BIT_FOK, _BIT_IOC = 1, 2


def modos_preenchimento(mascara: int, mt5) -> list[int]:
    modos = []
    if int(mascara) & _BIT_IOC:
        modos.append(mt5.ORDER_FILLING_IOC)
    if int(mascara) & _BIT_FOK:
        modos.append(mt5.ORDER_FILLING_FOK)
    modos.append(mt5.ORDER_FILLING_RETURN)
    return modos


# ------------------------------------------------------------ ao tick
def ao_tick(preco, tick: int, para_cima: bool) -> int:
    q = float(preco) / tick
    return int((math.ceil(q) if para_cima else math.floor(q)) * tick)


def protecao(lado: int, stop_px, alvo_px, tick: int):
    """Sempre para LONGE da entrada: o stop nunca fica mais apertado que o
    do papel, e a comparação com a corretora usa este mesmo valor — senão
    um stop por ATR fora do tick viraria uma modificação por volta."""
    sl = None if stop_px is None else ao_tick(stop_px, tick, para_cima=lado < 0)
    tp = None if alvo_px is None else ao_tick(alvo_px, tick, para_cima=lado > 0)
    return sl, tp


# -------------------------------------------------------------- pedidos
def pedido_entrada(mt5, *, simbolo, lado, volume, preco, magic_,
                   comentario, desvio, preenchimento) -> dict:
    """Sem sl/tp: em execução em bolsa a documentação de MqlTradeRequest só
    garante action/symbol/volume/type/type_filling na ordem a mercado. A
    proteção sai logo depois, em TRADE_ACTION_SLTP (`pedido_protecao`)."""
    return {"action": mt5.TRADE_ACTION_DEAL, "symbol": simbolo,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if lado > 0 else mt5.ORDER_TYPE_SELL,
            "price": float(preco),
            "deviation": int(desvio), "magic": int(magic_),
            "comment": str(comentario)[:31], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(preenchimento)}


def pedido_saida(mt5, *, simbolo, lado_posicao, volume, preco, ticket, magic_,
                 desvio, preenchimento) -> dict:
    """Hedging: fecha a posição pelo ticket (`position`), com ordem contrária
    — o exemplo oficial do order_send faz exatamente assim."""
    return {"action": mt5.TRADE_ACTION_DEAL, "symbol": simbolo,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_SELL if lado_posicao > 0 else mt5.ORDER_TYPE_BUY,
            "position": int(ticket), "price": float(preco),
            "deviation": int(desvio), "magic": int(magic_),
            "comment": "df saida", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(preenchimento)}


def pedido_protecao(mt5, *, simbolo, ticket, sl, tp, magic_) -> dict:
    return {"action": mt5.TRADE_ACTION_SLTP, "symbol": simbolo,
            "position": int(ticket), "sl": float(sl or 0), "tp": float(tp or 0),
            "magic": int(magic_)}


def pedido_cancelar(mt5, *, ordem) -> dict:
    return {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ordem)}


# ---------------------------------------------------------- fotografia
@dataclass
class Posicao:
    ticket: int
    magic: int
    ligacao_id: int | None
    simbolo: str
    lado: int                 # +1 comprado, -1 vendido
    volume: float
    preco: float
    sl: float
    tp: float
    resultado: float          # R$ aberto, como a corretora calcula
    aberta_em: datetime


@dataclass
class Negocio:
    ticket: int
    posicao: int
    magic: int
    ligacao_id: int | None
    simbolo: str
    entrada: bool
    lado: int
    volume: float
    preco: float
    resultado: float          # lucro + comissão + swap + taxa
    motivo: int               # DEAL_REASON_* (4 = SL, 5 = TP)
    quando: datetime


@dataclass
class Fotografia:
    posicoes: list = field(default_factory=list)
    ordens: list = field(default_factory=list)      # dicts: ticket, magic, ligacao_id, simbolo, volume, lado, quando
    negocios: list = field(default_factory=list)
    login: int | None = None
    servidor: str | None = None
    hedging: bool = False
    margem_livre: float = 0.0
    algo_ligado: bool = False
    # ordens do dia, executadas ou não: prova de que uma entrada "sem
    # resposta" chegou à corretora (dicts: ticket, magic, ligacao_id, quando)
    historico_ordens: list = field(default_factory=list)


def _hora(epoch) -> datetime:
    # mesma regra das barras: o epoch do MT5 já é o relógio de Brasília
    return datetime.fromtimestamp(int(epoch), timezone.utc).replace(tzinfo=None)


def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc)


class _Falha(Exception):
    pass


def _lista(mt5, valor):
    """`None` é erro (documentação: "Return None in case of an error") —
    a não ser que o last_error diga sucesso (1), quando é "nenhuma": a
    documentação não garante o que volta sem itens. Erro = `_Falha`."""
    if valor is not None:
        return list(valor)
    erro = mt5.last_error()
    if erro and int(erro[0]) == 1:
        return []
    raise _Falha(erro)


def fotografar(mt5, inicio_dia: datetime) -> Fotografia | None:
    """A conta numa leitura só. `None` = volta perdida: sem foto confiável
    a automação não decide nada (spec §5.1)."""
    de, ate = _utc(inicio_dia), _utc(inicio_dia + timedelta(days=1))
    try:
        pos = _lista(mt5, mt5.positions_get())
        ords = _lista(mt5, mt5.orders_get())
        deals = _lista(mt5, mt5.history_deals_get(de, ate))
        hist = _lista(mt5, mt5.history_orders_get(de, ate))
    except _Falha:
        return None
    conta, term = mt5.account_info(), mt5.terminal_info()
    if conta is None or term is None:
        return None
    f = Fotografia(login=int(conta.login), servidor=conta.server,
                   hedging=int(conta.margin_mode) == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
                   margem_livre=float(conta.margin_free),
                   algo_ligado=bool(term.trade_allowed))
    for p in pos:
        f.posicoes.append(Posicao(
            ticket=int(p.ticket), magic=int(p.magic),
            ligacao_id=ligacao_do_magic(p.magic), simbolo=p.symbol,
            lado=1 if int(p.type) == mt5.POSITION_TYPE_BUY else -1,
            volume=float(p.volume), preco=float(p.price_open),
            sl=float(p.sl or 0), tp=float(p.tp or 0), resultado=float(p.profit),
            aberta_em=_hora(p.time)))
    for o in ords:
        f.ordens.append({"ticket": int(o.ticket), "magic": int(o.magic),
                         "ligacao_id": ligacao_do_magic(o.magic),
                         "simbolo": o.symbol, "volume": float(o.volume_current),
                         # compra: BUY/BUY_LIMIT/BUY_STOP/BUY_STOP_LIMIT (0,2,4,6);
                         # venda: 1,3,5,7; o resto (CLOSE_BY...) = 0, nunca tocado
                         "lado": {0: 1, 2: 1, 4: 1, 6: 1,
                                  1: -1, 3: -1, 5: -1, 7: -1}.get(int(o.type), 0),
                         "quando": _hora(o.time_setup)})
    for o in hist:
        f.historico_ordens.append({"ticket": int(o.ticket), "magic": int(o.magic),
                                   "ligacao_id": ligacao_do_magic(o.magic),
                                   "quando": _hora(o.time_setup)})
    for d in deals:
        # depósito/saldo (type 2...) não é negócio: viraria lucro do dia
        if int(d.type) not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue
        f.negocios.append(Negocio(
            ticket=int(d.ticket), posicao=int(d.position_id), magic=int(d.magic),
            ligacao_id=ligacao_do_magic(d.magic), simbolo=d.symbol,
            entrada=int(d.entry) == mt5.DEAL_ENTRY_IN,
            lado=1 if int(d.type) == mt5.DEAL_TYPE_BUY else -1,
            volume=float(d.volume), preco=float(d.price),
            resultado=float(d.profit) + float(d.commission) + float(d.swap)
            + float(getattr(d, "fee", 0.0)),
            motivo=int(d.reason), quando=_hora(d.time)))
    return f
