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
- ordem em trânsito (inclusive PLACED) bloqueia só entrar/adotar; proteção e
  saída seguem; ordem contrária à posição é a saída em trânsito (não cancela).
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
    tipo: str          # entrar|sair|proteger|adotar|saiu_antes|perdida|cancelar|chamar
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


def _so_protecao(foto, diario, lig, agora) -> list[Acao]:
    """Sem papel (indisponível / sem relógio): só confere o stop que já deveria
    estar na corretora (spec §5.1). Nunca entra nem sai. Stop zerado: repõe o
    gravado no diário; sem ele no diário, pede chamado."""
    acoes: list[Acao] = []
    for p in foto.posicoes:
        if p.ligacao_id != lig or round(p.sl) != 0:
            continue
        reg = diario.protecao_registrada(p.ticket)
        if reg is None:
            acoes.append(Acao("chamar", lig, ticket=p.ticket, posicao=p,
                              motivo="posição sem stop e papel indisponível"))
        elif agora is None or _pode(
                diario.ultima_tentativa("protecao_enviando", ticket=p.ticket), agora):
            lado, stop, alvo = reg
            acoes.append(Acao("proteger", lig, ticket=p.ticket, posicao=p,
                              desejado=Desejado(POSICAO, lado=lado, stop_px=stop,
                                                alvo_px=alvo)))
    return acoes


def planejar(desejados: dict, disponivel: bool, foto, diario, agora_srv,
             tick: int, conectado_ha_s: float) -> list[Acao]:
    acoes: list[Acao] = []
    if not disponivel or agora_srv is None:
        # não dá para saber o que o papel quer: só a proteção (não precisa de relógio)
        for lig in sorted({p.ligacao_id for p in foto.posicoes if p.ligacao_id}):
            acoes += _so_protecao(foto, diario, lig, agora_srv)
        return acoes
    estavel = conectado_ha_s >= GRACA_RECONEXAO_S
    pendentes: dict[int, list[dict]] = {}
    for o in foto.ordens:
        if o["ligacao_id"]:
            pendentes.setdefault(o["ligacao_id"], []).append(o)
    ligs = (set(desejados) | {p.ligacao_id for p in foto.posicoes if p.ligacao_id}
            | set(pendentes) | diario.ligacoes_abertas())
    for lig in sorted(ligs):
        d = desejados.get(lig) or Desejado(ZERADO, motivo="fora do papel de hoje")
        if d.estado == INDISPONIVEL:
            acoes += _so_protecao(foto, diario, lig, agora_srv)
            continue
        pos = [p for p in foto.posicoes if p.ligacao_id == lig]
        pend = pendentes.get(lig, [])
        # ordem contrária a uma posição da ligação = a saída em trânsito: não
        # se cancela nem se pede outra saída para o mesmo ticket
        em_saida: set = set()
        for o in pend:
            for p in pos:
                if o.get("lado") and p.lado == -o["lado"]:
                    em_saida.add(p.ticket)
        for o in pend:
            if any(o.get("lado") and p.lado == -o["lado"] for p in pos):
                continue
            # resto de parcial / PLACED velho: cancela; papel zerado também
            # (não pode prender a saída)
            if (d.estado == ZERADO or _seg(agora_srv, o["quando"]) > ORDEM_VELHA_S) and _pode(
                    diario.ultima_tentativa("cancelar_enviando", ticket=o["ticket"]),
                    agora_srv):
                acoes.append(Acao("cancelar", lig, ticket=o["ticket"],
                                  motivo="ordem pendente"))

        def sair(p, motivo):
            if p.ticket not in em_saida and _pode(
                    diario.ultima_tentativa("saida_enviando", ticket=p.ticket), agora_srv):
                acoes.append(Acao("sair", lig, ticket=p.ticket, posicao=p, motivo=motivo))

        vivos = {p.ticket for p in pos}

        if d.estado == ZERADO:
            for p in pos:
                sair(p, d.motivo or "papel zerado")
            if estavel:
                for t, ts in diario.tickets_abertos(lig):
                    if t not in vivos and _saiu(foto, t):
                        acoes.append(Acao("saiu_antes", lig, ticket=t,
                                          desejado=Desejado(ZERADO, entry_ts=ts)))
            continue

        # POSICAO
        ts = d.entry_ts
        ticket = diario.ticket(lig, ts)
        minha = next((p for p in pos if p.ticket == ticket), None) if ticket else None
        candidatas = []
        if minha is None and ticket is None and diario.enviada(lig, ts):
            candidatas = [p for p in pos if p.lado == d.lado and p.aberta_em >= ts]
            # com ordem em trânsito não se adota: espera ela se resolver
            if len(candidatas) == 1 and not pend:
                minha = candidatas[0]
                acoes.append(Acao("adotar", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
        for p in pos:
            if (minha is None or p.ticket != minha.ticket) and not (
                    pend and p in candidatas):
                sair(p, "posição que não é a operação atual")
        if estavel:
            for t, ts_t in diario.tickets_abertos(lig):
                if t != ticket and t not in vivos and _saiu(foto, t):
                    acoes.append(Acao("saiu_antes", lig, ticket=t,
                                      desejado=Desejado(ZERADO, entry_ts=ts_t)))
        if minha is not None:
            sl, tp = K.protecao(d.lado, d.stop_px, d.alvo_px, tick)
            # o stop é obrigatório (o alvo pode faltar)
            if round(minha.sl) == 0:
                desde = diario.protecao_pendente_desde(minha.ticket)
                if desde is not None and _seg(agora_srv, desde) > SEM_PROTECAO_S:
                    sair(minha, "posição sem proteção na corretora")
                elif _pode(diario.ultima_tentativa("protecao_enviando", ticket=minha.ticket),
                           agora_srv):
                    acoes.append(Acao("proteger", lig, desejado=d, ticket=minha.ticket,
                                      posicao=minha))
            elif ((sl or 0) != round(minha.sl) or (tp or 0) != round(minha.tp)) and _pode(
                    diario.ultima_tentativa("protecao_enviando", ticket=minha.ticket),
                    agora_srv):
                acoes.append(Acao("proteger", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
            continue
        if pend:
            continue          # ordem em trânsito bloqueia nova entrada

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
        if _seg(agora_srv, ts) > JANELA_ENTRADA_S:
            # passou a janela sem posição nem negócio de entrada (mesmo com
            # ordem no histórico ou "aceita": não houve execução)
            acoes.append(Acao("perdida", lig, desejado=d,
                              motivo=diario.ultimo_motivo(lig, ts)
                              or "automação fora do ar"))
            continue
        if diario.desfecho(lig, ts) == "aceita":
            continue          # PLACED: nunca reenvia; espera a posição ou a janela
        sem = diario.tentativa_sem_desfecho(lig, ts)
        if sem is not None:
            # enviou e não sabe o que houve (timeout, queda): a ordem pode ter executado
            if _seg(agora_srv, sem) < INCERTA_ESPERA_S:
                continue
            if any(o["ligacao_id"] == lig and o["quando"] >= ts
                   for o in foto.historico_ordens):
                continue      # a ordem existe: o desfecho aparece nas próximas voltas
        if estavel and _pode(diario.ultima_tentativa("enviando", lig=lig, entry_ts=ts),
                             agora_srv):
            acoes.append(Acao("entrar", lig, desejado=d))
    return acoes
