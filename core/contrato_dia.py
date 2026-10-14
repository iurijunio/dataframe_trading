"""Contrato do dia da automação (spec §5.6).

O papel olha a série contínua WIN$N; a ordem real vai para um contrato
negociável (WINV26, WINZ26...). Para o papel e a demo falarem do mesmo preço,
a automação opera o contrato cujo último preço é IGUAL ao do WIN$N. No dia do
vencimento desse contrato ela não entra (o papel segue), e na véspera avisa
qual será o de amanhã. A `GuardaPreco` vigia a divergência durante o pregão.

Funções do MetaTrader5 usadas (documentação oficial, conferida):
- symbols_get(group): https://www.mql5.com/en/docs/python_metatrader5/mt5symbolsget_py
- symbol_info (expiration_time, trade_mode): .../mt5symbolinfo_py
- symbol_info_tick (last): .../mt5symbolinfotick_py
- copy_rates_from_pos (real_volume): .../mt5copyratesfrompos_py
Todas devolvem None em erro; aqui isso vira motivo, nunca exceção.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

# papel e ordem precisam andar juntos: mais que isso por mais tempo = parar
TICKS_DE_FAIXA = 2
SEGUNDOS_DE_TOLERANCIA = 60


def _hora(epoch) -> datetime:
    # mesma regra de core.corretora._hora: o epoch do MT5 já é o relógio de Brasília
    from core.corretora import _hora
    return _hora(epoch)


def _resultado(simbolo=None, motivo=None, vence_em=None, amanha=None) -> dict:
    return {"simbolo": simbolo, "motivo": motivo, "vence_em": vence_em, "amanha": amanha}


def _vencimento(info) -> date | None:
    epoch = getattr(info, "expiration_time", 0) or 0
    return _hora(epoch).date() if epoch else None


def _ultimo(mt5, simbolo) -> float | None:
    t = mt5.symbol_info_tick(simbolo)
    if t is None or not getattr(t, "last", 0):
        return None            # last 0 = sem negócio: não serve para comparar
    return float(t.last)


def _volume_anterior(mt5, simbolo) -> int | None:
    """Volume do pregão anterior (barra D1 de índice 1). `None` = sem dado."""
    barras = mt5.copy_rates_from_pos(simbolo, mt5.TIMEFRAME_D1, 1, 1)
    if barras is None:
        erro = mt5.last_error()
        return 0 if erro and int(erro[0]) == 1 else None
    if len(barras) == 0:
        return 0
    return int(barras[0]["real_volume"])


def _proximo_dia_util(d: date) -> date:
    # só fins de semana: feriado de B3 não está no calendário do app (que é
    # montado das barras do banco); no máximo o aviso vem um dia depois
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def escolher(mt5, hoje: date, *, base: str = "WIN$N", prefixo: str = "WIN") -> dict:
    """Contrato que a automação opera hoje.

    Devolve {"simbolo", "motivo", "vence_em", "amanha"}. `simbolo=None` com
    `motivo` = não entrar hoje (erro de leitura ou vencimento)."""
    lidos = mt5.symbols_get(group=f"{prefixo}*")
    if lidos is None:
        return _resultado(motivo=f"não consegui listar os contratos: {mt5.last_error()}")
    cheio = mt5.SYMBOL_TRADE_MODE_FULL
    cands = []
    for i in lidos:
        # "$" é série contínua (WIN$N, WIN$): não se negocia
        if i.name == base or "$" in i.name or i.trade_mode != cheio:
            continue
        venc = _vencimento(i)
        if venc is not None and venc < hoje:
            continue           # já venceu: sobra de lista
        cands.append((i.name, venc))
    if not cands:
        return _resultado(motivo="nenhum contrato negociável encontrado")

    # vencimento mais próximo primeiro, para um empate nunca pegar o distante
    cands.sort(key=lambda c: (c[1] is None, c[1] or date.max, c[0]))

    preco_base = _ultimo(mt5, base)
    if preco_base is None:
        return _resultado(motivo=f"sem preço do {base}")

    escolhido, motivo = None, None
    for nome, venc in cands:
        if _ultimo(mt5, nome) == preco_base:
            escolhido = (nome, venc)
            break
    if escolhido is None:
        melhor = None
        for nome, venc in cands:
            v = _volume_anterior(mt5, nome)
            if v is not None and (melhor is None or v > melhor[0]):
                melhor = (v, nome, venc)
        if melhor is None:
            return _resultado(motivo="nenhum contrato igual ao WIN$N e sem volume do pregão anterior")
        escolhido, motivo = (melhor[1], melhor[2]), "pelo volume (preço diferente do WIN$N)"

    nome, venc = escolhido
    if venc == hoje:
        return _resultado(None, f"vencimento do {nome}: sem entradas hoje", venc)
    amanha = None
    if venc is not None and venc == _proximo_dia_util(hoje):
        # o contrato seguinte: o de vencimento logo depois do que vence
        depois = [c for c in cands if c[1] is not None and c[1] > venc]
        amanha = depois[0][0] if depois else None
    return _resultado(nome, motivo, venc, amanha)


class GuardaPreco:
    """Bloqueia entradas quando contrato e WIN$N se afastam mais de 2 ticks
    por mais de 60 s seguidos. Saídas nunca passam por aqui."""

    def __init__(self, tick: int):
        self.tick = tick
        self._desde: datetime | None = None    # início da divergência corrente

    def observar(self, agora: datetime, preco_contrato: float, preco_base: float) -> bool:
        if abs(preco_contrato - preco_base) <= TICKS_DE_FAIXA * self.tick:
            self._desde = None                 # voltou à faixa: zera a contagem
            return False
        if self._desde is None:
            self._desde = agora
        return (agora - self._desde).total_seconds() > SEGUNDOS_DE_TOLERANCIA
