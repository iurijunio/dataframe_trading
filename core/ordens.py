"""O motor de ordens: o papel decide, a corretora executa, isto reconcilia.

Spec 2026-10-08-ao-vivo-ordens-design.md §5–6. `planejar` é puro: recebe o
desejado de cada ligação (papel_vivo), a fotografia da conta (corretora) e
o diário, e devolve ações. Idempotente: rodar duas vezes seguidas não pede
nada a mais. Quem executa é o `Motor` (mesmo arquivo).

Regras que este arquivo não pode esquecer:
- casar posição pela OPERAÇÃO (ticket gravado no diário), nunca pelo lado;
- INDISPONIVEL não entra nem sai (reinício não pode zerar posição boa);
- a saída vale para toda posição com magic da automação, mesmo de ligação
  que deixou de operar; posição sem o magic (à mão) nunca é tocada;
- ordem em trânsito (inclusive PLACED) bloqueia nova ordem da ligação.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import corretora as K
from .papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado

JANELA_ENTRADA_S = 30
GRACA_RECONEXAO_S = 5
INTERVALO_S = 1.0          # entre tentativas da mesma ação (evita o 10024)
INCERTA_ESPERA_S = 3.0     # sem resposta: espera o histórico antes de reenviar
SEM_PROTECAO_S = 2.0       # posição sem SL/TP além disso é encerrada
ORDEM_VELHA_S = 5.0        # ordem pendente com o magic além disso é cancelada


@dataclass(frozen=True)
class Acao:
    tipo: str          # entrar|sair|proteger|adotar|saiu_antes|perdida|cancelar
    ligacao_id: int
    desejado: Desejado | None = None
    ticket: int | None = None
    posicao: K.Posicao | None = None
    motivo: str | None = None


def _seg(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds()


def _pode(ultima, agora) -> bool:
    return ultima is None or _seg(agora, ultima) >= INTERVALO_S


def _executou(foto, lig, entry_ts) -> int | None:
    """Ticket da posição se o histórico do dia tem a entrada dela depois do
    início da operação (executou sem a resposta ter chegado)."""
    for n in foto.negocios:
        if n.entrada and n.ligacao_id == lig and n.quando >= entry_ts:
            return n.posicao
    return None


def _saiu(foto, ticket) -> bool:
    return any(not n.entrada and n.posicao == ticket for n in foto.negocios)


def planejar(desejados: dict, disponivel: bool, foto, diario, agora_srv,
             tick: int, conectado_ha_s: float) -> list[Acao]:
    if not disponivel or agora_srv is None:
        return []          # não dá para saber: só a proteção que já está lá vale
    estavel = conectado_ha_s >= GRACA_RECONEXAO_S
    acoes: list[Acao] = []
    pendentes: dict[int, list[dict]] = {}
    for o in foto.ordens:
        if o["ligacao_id"]:
            pendentes.setdefault(o["ligacao_id"], []).append(o)
    ligs = (set(desejados) | {p.ligacao_id for p in foto.posicoes if p.ligacao_id}
            | set(pendentes))
    for lig in sorted(ligs):
        d = desejados.get(lig) or Desejado(ZERADO, motivo="fora do papel de hoje")
        if d.estado == INDISPONIVEL:
            continue
        if lig in pendentes:
            # PLACED esperando a bolsa, ou resto de parcial: espera; velha ou
            # com o papel zerado, cancela (não pode prender a saída)
            for o in pendentes[lig]:
                if d.estado == ZERADO or _seg(agora_srv, o["quando"]) > ORDEM_VELHA_S:
                    acoes.append(Acao("cancelar", lig, ticket=o["ticket"],
                                      motivo="ordem pendente"))
            continue
        pos = [p for p in foto.posicoes if p.ligacao_id == lig]

        if d.estado == ZERADO:
            for p in pos:
                if _pode(diario.ultima_tentativa("saida_enviando", ticket=p.ticket),
                         agora_srv):
                    acoes.append(Acao("sair", lig, ticket=p.ticket, posicao=p,
                                      motivo=d.motivo or "papel zerado"))
            if estavel:
                vivos = {p.ticket for p in pos}
                for t, ts in diario.tickets_abertos(lig):
                    if t not in vivos and _saiu(foto, t):
                        acoes.append(Acao("saiu_antes", lig, ticket=t,
                                          desejado=Desejado(ZERADO, entry_ts=ts)))
            continue

        # POSICAO
        ts = d.entry_ts
        ticket = diario.ticket(lig, ts)
        minha = next((p for p in pos if p.ticket == ticket), None) if ticket else None
        if minha is None and ticket is None and diario.enviada(lig, ts):
            candidatas = [p for p in pos if p.lado == d.lado and p.aberta_em >= ts]
            if len(candidatas) == 1:
                minha = candidatas[0]
                acoes.append(Acao("adotar", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
        for p in pos:
            if (minha is None or p.ticket != minha.ticket) and _pode(
                    diario.ultima_tentativa("saida_enviando", ticket=p.ticket), agora_srv):
                acoes.append(Acao("sair", lig, ticket=p.ticket, posicao=p,
                                  motivo="posição que não é a operação atual"))
        if minha is not None:
            sl, tp = K.protecao(d.lado, d.stop_px, d.alvo_px, tick)
            nua = round(minha.sl) == 0 and round(minha.tp) == 0
            desde = diario.executada_em(lig, ts) or minha.aberta_em
            if nua and _seg(agora_srv, desde) > SEM_PROTECAO_S:
                acoes.append(Acao("sair", lig, ticket=minha.ticket, posicao=minha,
                                  motivo="posição sem proteção na corretora"))
            elif ((sl or 0) != round(minha.sl) or (tp or 0) != round(minha.tp)) and _pode(
                    diario.ultima_tentativa("protecao_enviando", ticket=minha.ticket),
                    agora_srv):
                acoes.append(Acao("proteger", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
            continue

        # a corretora não tem a posição desta operação
        ja = ticket or _executou(foto, lig, ts)
        if ja is not None:
            # executou: só registra a saída com o negócio de saída na mão e a
            # lista estável — logo após reconectar ela vem vazia por engano
            if estavel and _saiu(foto, ja) and not diario.registrado(lig, ts, "saiu_antes"):
                acoes.append(Acao("saiu_antes", lig, desejado=d, ticket=ja))
            continue
        if any(diario.registrado(lig, ts, t)
               for t in ("perdida", "nao_entrou", "seria_enviada")):
            continue
        ultimo = diario.ultimo(lig, ts)
        if ultimo is not None and ultimo["tipo"] == "incerta":
            if _seg(agora_srv, ultimo["quando"]) < INCERTA_ESPERA_S:
                continue
            if any(o["ligacao_id"] == lig and o["quando"] >= ts
                   for o in foto.historico_ordens):
                continue      # a ordem existe: o desfecho aparece nas próximas voltas
        if _seg(agora_srv, ts) <= JANELA_ENTRADA_S:
            if estavel and _pode(diario.ultima_tentativa("enviando", lig=lig, entry_ts=ts),
                                 agora_srv):
                acoes.append(Acao("entrar", lig, desejado=d))
        else:
            acoes.append(Acao("perdida", lig, desejado=d,
                              motivo=diario.ultimo_motivo(lig, ts)
                              or "automação fora do ar"))
    return acoes
