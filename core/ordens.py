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

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import comandos as comandos_mod
from . import corretora as K
from . import papel
from .diario_ordens import Diario
from .ordem_teste import OrdemTeste
from .papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado

JANELA_ENTRADA_S = 30
GRACA_RECONEXAO_S = 5
INTERVALO_S = 1.0          # entre tentativas da mesma ação (evita o 10024)
INCERTA_ESPERA_S = 3.0     # sem resposta: espera o histórico antes de reenviar
SEM_PROTECAO_S = 2.0       # posição sem SL/TP além disso é encerrada
ORDEM_VELHA_S = 5.0        # ordem pendente com o magic além disso é cancelada
PENDENTE_CHAMA_S = 120     # saída pendente além disso chama o usuário (e segue)
CLOSE_ONLY = 10044         # só encerramento: sem entradas no contrato no resto do dia
# perdida de uma entrada que a corretora deu por executada sem a posição
# aparecer: pode haver posição que a automação não vê — chama o usuário
SEM_CONFIRMACAO = "executada sem confirmação da posição"
# entrada barrada só por instantes (sem tick): volta a tentar na janela
SEM_COTACAO = "sem cotação do contrato"
# o contrato do dia ainda não foi escolhido (WIN$N com último 0 às 09:00):
# passageira como a de cima — a volta seguinte escolhe e a entrada sai
SEM_CONTRATO = "contrato do dia ainda não escolhido"
SEM_CONTRATO_HOJE = "sem contrato operável hoje"
GUARDA_PRECO = "preço do contrato não confere com o WIN$N"
PASSAGEIRAS = (SEM_COTACAO, SEM_CONTRATO)
SEM_LEITURA_S = 30         # foto incompleta além disso no pregão chama
ZERAR_DESCARTADO = "zerar de outro dia, descartado"
TRAVA = 0.9               # fração do limite do dia que trava a conta (§5.7)
TETO_STOP = 1.5            # D1: distância ao stop até 1,5× a do plano
PAPEL_PARADO_S = 180       # papel indisponível além disso no pregão chama
# zerado no toque do stop/alvo: a corretora tem este tempo para executar o
# stop/alvo da operação tocada; depois disso a posição sai a mercado e chama
CARENCIA_TOQUE_S = 1.0

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Acao:
    tipo: str          # entrar|sair|proteger|adotar|saiu_antes|perdida|cancelar|chamar
    ligacao_id: int
    desejado: Desejado | None = None
    ticket: int | None = None
    posicao: K.Posicao | None = None
    motivo: str | None = None


def _de_outro_dia(criado_em, hoje) -> bool:
    """O comando foi escrito num dia anterior a `hoje` (o do servidor)?
    `criado_em` é a hora do PC em ISO; ilegível ou ausente = vale (na dúvida
    o zerar segue valendo, que é o lado seguro)."""
    if not criado_em:
        return False
    try:
        return datetime.fromisoformat(str(criado_em)).date() < hoje
    except ValueError:
        return False


def _seg(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds()


def _pode(ultima, agora) -> bool:
    return ultima is None or _seg(agora, ultima) >= INTERVALO_S


def _executou(foto, diario, lig, entry_ts) -> int | None:
    """Ticket da posição se o histórico do dia tem a entrada dela depois do
    PRIMEIRO envio desta operação (executou sem a resposta ter chegado).

    Nunca o ticket que o diário já deu a OUTRA operação da ligação: a
    entrada de uma operação antiga (que pode ter executado depois do
    `entry_ts` da nova, no mesmo minuto ou numa entrada tardia) não é esta.
    Sem envio desta operação no diário, nada dela pode ter executado. O
    `time` do negócio vem em segundos inteiros e a hora do envio é a
    estimativa do relógio do servidor: 1 s de folga, depois de truncar."""
    envios = diario._da(lig, entry_ts, "enviando")
    if not envios:
        return None
    desde = max(entry_ts, min(e["quando"] for e in envios).replace(microsecond=0)
                - timedelta(seconds=1))
    de_outras = {int(e["ticket"]) for e in diario.eventos
                 if e["tipo"] in ("executada", "parcial", "adotada") and e.get("ticket")
                 and (e.get("ligacao_id"), e.get("entry_ts")) != (lig, entry_ts)}
    for n in foto.negocios:
        if n.entrada and n.ligacao_id == lig and n.quando >= desde \
                and n.posicao not in de_outras:
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


def _envio_da_orfa(diario, lig, entry_ts, p):
    """O `enviando` desta operação que abriu a posição `p`: só do lado dela
    (ou sem lado gravado) e com stop; o mais recente até a abertura — uma
    tentativa posterior pode ter saído com outro stop. O `time` da posição
    vem em segundos inteiros: compara com a hora do envio truncada. Sem
    nenhum até a abertura (relógio estimado adiantado): o último com stop."""
    envios = [e for e in diario._da(lig, entry_ts, "enviando")
              if e.get("stop_px") is not None and e.get("lado") in (None, p.lado)]
    antes = [e for e in envios if e["quando"].replace(microsecond=0) <= p.aberta_em]
    return (antes or envios or [None])[-1]


def _saida_recusada(diario, ticket) -> bool:
    """A última tentativa de saída deste ticket foi recusada?"""
    ult = None
    for e in diario.eventos:
        if e.get("ticket") == ticket and e["tipo"] in (
                "saida_enviando", "saida_recusada", "saida_executada", "saida_parcial"):
            ult = e["tipo"]
    return ult == "saida_recusada"


def _orfa_na_parcial(candidatas, d, diario, lig, agora, sair) -> list[Acao]:
    """Foto parcial com a entrada que executou sem resposta: a candidata não
    se adota (a adoção confere o histórico), mas também não pode ficar sem
    stop enquanto a leitura seguir parcial. Uma só: recebe o stop/alvo do
    `enviando` que a abriu (o que de fato foi à corretora, já arredondado;
    nunca o do papel agora). Mais de uma, ou nada gravado no envio: não se
    sabe qual é nem qual stop — chamado, como no `_so_protecao`.

    Como na foto completa: proteção pedida sem sucesso há mais de
    SEM_PROTECAO_S encerra a posição (sair não depende do histórico); se a
    própria saída é recusada, chama também — ela segue sem stop."""
    acoes: list[Acao] = []
    sem_sl = [p for p in candidatas if round(p.sl) == 0]
    restantes = []
    for p in sem_sl:
        desde = diario.protecao_pendente_desde(p.ticket)
        if desde is not None and _seg(agora, desde) > SEM_PROTECAO_S:
            if _saida_recusada(diario, p.ticket):
                acoes.append(Acao("chamar", lig, ticket=p.ticket, posicao=p,
                                  motivo="posição sem stop: a corretora recusou o "
                                         "stop e a saída (leitura parcial)"))
            sair(p, "posição sem proteção na corretora")
        else:
            restantes.append(p)
    if not restantes:
        return acoes
    envio = None if len(candidatas) > 1 else _envio_da_orfa(
        diario, lig, d.entry_ts, restantes[0])
    if envio is not None:
        p = restantes[0]
        if _pode(diario.ultima_tentativa("protecao_enviando", ticket=p.ticket), agora):
            acoes.append(Acao("proteger", lig, ticket=p.ticket, posicao=p,
                              desejado=Desejado(POSICAO, lado=p.lado,
                                                stop_px=envio["stop_px"],
                                                alvo_px=envio.get("alvo_px"))))
        return acoes
    motivo = ("posição sem stop e leitura parcial: mais de uma candidata à entrada "
              "sem resposta" if len(candidatas) > 1 else
              "posição sem stop e leitura parcial: entrada sem resposta sem stop gravado")
    return acoes + [Acao("chamar", lig, ticket=p.ticket, posicao=p, motivo=motivo)
                    for p in restantes]


def planejar(desejados: dict, disponivel: bool, foto, diario, agora_srv,
             tick: int, conectado_ha_s: float) -> list[Acao]:
    """Com a foto PARCIAL (histórico/negócios/conta ilegíveis) só saídas e
    proteção: entrar, adotar, "perdida" e "saiu antes" dependem do
    histórico, e decidir sem ele duplicaria uma entrada ou daria por saída
    uma posição que só não apareceu na lista. A candidata da entrada sem
    resposta não é adotada, mas recebe o stop do envio — e, recusado,
    encerra como na foto completa (`_orfa_na_parcial`)."""
    acoes: list[Acao] = []
    parcial = bool(getattr(foto, "parcial", False))
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
        # ordem contrária a uma posição cuja saída está aberta no diário = a
        # saída em trânsito (não se repete a saída enquanto ela vive). Contrária
        # sem saída aberta é resto de uma entrada nova: segue a regra de cancelar.
        em_saida: set = set()
        ordem_de_saida: set = set()
        for o in pend:
            for p in pos:
                if o.get("lado") and p.lado == -o["lado"] and \
                        diario.saida_desde(p.ticket) is not None:
                    em_saida.add(p.ticket)
                    ordem_de_saida.add(o["ticket"])
        for o in pend:
            if o.get("lado") == 0:
                continue          # tipo desconhecido (ex.: CLOSE_BY): nunca tocada
            velha = _seg(agora_srv, o["quando"]) > ORDEM_VELHA_S
            # saída em trânsito só se cancela quando travou (> 5 s); o resto de
            # entrada também quando o papel zerou (não pode prender a saída)
            if (velha or (d.estado == ZERADO and o["ticket"] not in ordem_de_saida)) \
                    and _pode(diario.ultima_tentativa("cancelar_enviando", ticket=o["ticket"]),
                              agora_srv):
                acoes.append(Acao("cancelar", lig, ticket=o["ticket"],
                                  motivo="ordem pendente"))

        saindo: set = set()

        def sair(p, motivo):
            if p.ticket not in em_saida and _pode(
                    diario.ultima_tentativa("saida_enviando", ticket=p.ticket), agora_srv):
                acoes.append(Acao("sair", lig, ticket=p.ticket, posicao=p, motivo=motivo))
                saindo.add(p.ticket)

        vivos = {p.ticket for p in pos}

        if d.estado == ZERADO:
            no_toque = (d.motivo in ("stop no toque", "alvo no toque")
                        and d.toque_em is not None and d.entry_ts is not None)
            ticket_toque = diario.ticket(lig, d.entry_ts) if no_toque else None
            for p in pos:
                if ticket_toque is not None and p.ticket == ticket_toque:
                    if _seg(agora_srv, d.toque_em) < CARENCIA_TOQUE_S:
                        continue      # a corretora ainda tem o prazo de executar
                    motivo = ("stop da corretora não executou"
                              if d.motivo == "stop no toque"
                              else "alvo da corretora não executou")
                    sair(p, motivo)
                    acoes.append(Acao("chamar", lig, ticket=p.ticket, posicao=p,
                                      motivo=motivo))
                else:
                    sair(p, d.motivo or "papel zerado")
            if estavel and not parcial:
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
            # com ordem em trânsito não se adota: espera ela se resolver;
            # com a foto parcial também não (a adoção confere o histórico)
            if len(candidatas) == 1 and not pend and not parcial:
                minha = candidatas[0]
                acoes.append(Acao("adotar", lig, desejado=d, ticket=minha.ticket,
                                  posicao=minha))
        for p in pos:
            # candidata não adotada (ordem em trânsito, foto parcial) pode
            # ser a própria operação: nunca sai por "não é a atual"
            if (minha is None or p.ticket != minha.ticket) and not (
                    (pend or parcial) and p in candidatas):
                sair(p, "posição que não é a operação atual")
        if estavel and not parcial:
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
        if parcial and candidatas:
            acoes += _orfa_na_parcial(candidatas, d, diario, lig, agora_srv, sair)
        if pend or parcial:
            continue          # ordem em trânsito / sem histórico: nada de entrar
        # virada de mão (ou qualquer contrária da ligação): a posição
        # contrária segue na conta sem saída pedida NESTA volta (em trânsito,
        # ou no intervalo entre tentativas). Entrar agora deixaria compra e
        # venda vivas na conta hedging; a entrada espera a saída — a janela
        # de 30 s sobra, a saída leva menos de 1 s. Só a ENTRADA espera: a
        # janela segue valendo, e passou dela a operação é "perdida" mesmo
        # com a contrária presa. A anterior do MESMO lado (caso 9) segue a
        # regra de antes: sai e a nova entra na mesma volta.
        contraria = any(p.lado == -d.lado and p.ticket not in saindo for p in pos)

        # a corretora não tem a posição desta operação
        ja = ticket or _executou(foto, diario, lig, ts)
        if ja is not None:
            # executou: só registra a saída com o negócio de saída na mão e a
            # lista estável — logo após reconectar ela vem vazia por engano.
            # E só se o diário não a viu sair: a saída da própria automação
            # ("Encerrar posição", posição sem proteção) já fechou o ticket,
            # e o negócio de saída dela não é "saiu antes". Ticket do
            # diário: só se ainda aberto. Ticket que o diário nunca teve
            # (executou sem resposta e saiu antes da adoção): só se nenhuma
            # saída da automação o tocou.
            abertos = {t for t, _ in diario.tickets_abertos(lig)}
            conhecido = any(e.get("ticket") == ja and e["tipo"] in (
                "executada", "parcial", "adotada", "saida_executada", "saiu_antes")
                for e in diario.eventos)
            if estavel and (ja in abertos or not conhecido) and _saiu(foto, ja) \
                    and not diario.registrado(lig, ts, "saiu_antes"):
                acoes.append(Acao("saiu_antes", lig, desejado=d, ticket=ja))
            continue
        if any(diario.registrado(lig, ts, t)
               for t in ("perdida", "nao_entrou", "seria_enviada")):
            continue
        # a corretora disse que executou, mas sem ticket e sem a posição/negócio
        # nas listas (atrasadas): reenviar duplicaria. Espera a adoção ou a janela.
        executou_sem_ticket = diario.desfecho(lig, ts) in ("executada", "parcial")
        if _seg(agora_srv, ts) > JANELA_ENTRADA_S:
            # passou a janela sem posição nem negócio de entrada (mesmo com
            # ordem no histórico ou "aceita": não houve execução); logo após
            # reconectar a lista pode vir vazia: espera estabilizar
            if not estavel:
                continue
            acoes.append(Acao("perdida", lig, desejado=d,
                              motivo=SEM_CONFIRMACAO if executou_sem_ticket else (
                                  diario.ultimo_motivo(lig, ts) or "automação fora do ar")))
            continue
        if executou_sem_ticket:
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
        if contraria:
            continue
        if estavel and _pode(diario.ultima_tentativa("enviando", lig=lig, entry_ts=ts),
                             agora_srv):
            acoes.append(Acao("entrar", lig, desejado=d))
    return acoes


# ======================================================================
# Limite do dia da conta (§5.7, D2) e checagem antes de entrar (6a, D1)
# ======================================================================
def perda_do_dia(foto, portfolio_de: dict, portfolio_id) -> dict:
    """Perda do dia da CONTA inteira (D2), lida da corretora: realizado nos
    negócios do dia (com custos) + resultado aberto das posições.

    `total` é a perda (positiva), com ganho valendo 0 — é ela que trava.
    A quebra (`este` portfólio, `outros` portfólios, `fora` da automação)
    usa o resultado com sinal de cada origem: um ganho aparece negativo, e
    a soma das três é o que a corretora mostra. Posição com magic de uma
    ligação que já não está em portfólio nenhum é da automação: `outros`."""
    quebra = {"este": 0.0, "outros": 0.0, "fora": 0.0}
    por_portfolio: dict = {}
    itens = ([(p.ligacao_id, p.resultado) for p in foto.posicoes]
             + [(n.ligacao_id, n.resultado) for n in foto.negocios])
    for lig, resultado in itens:
        perda = -float(resultado)
        if lig is None:
            quebra["fora"] += perda
            continue
        pf = portfolio_de.get(lig)
        quebra["este" if portfolio_id is not None and pf == portfolio_id
               else "outros"] += perda
        if pf is not None:
            por_portfolio[pf] = por_portfolio.get(pf, 0.0) + perda
    # + 0.0: um -0.0 viraria "-R$ 0,00" na tela
    out = {k: round(v, 2) + 0.0 for k, v in quebra.items()}
    out["total"] = round(max(0.0, sum(quebra.values())), 2) + 0.0
    out["por_portfolio"] = {k: round(v, 2) + 0.0 for k, v in por_portfolio.items()}
    return out


def risco_entrada(d: Desejado, preco: float, perfil_custos: dict, ponto: float, *,
                  tick: int | None = None) -> float:
    """R$ que a entrada arrisca até o stop a partir do preço corrente, mais
    os custos de entrada e saída (6a). Com `tick`, o stop é o que vai à
    corretora (arredondado para longe da entrada, `K.protecao`)."""
    custo = float(perfil_custos.get("corretagem") or 0) + float(
        perfil_custos.get("emolumentos") or 0)
    stop = d.stop_px
    if stop is not None and tick:
        stop = K.protecao(d.lado, stop, None, tick)[0]
    distancia = 0.0 if stop is None else abs(float(preco) - float(stop))
    return distancia * d.contratos * float(ponto) + 2 * d.contratos * custo


def checar_entrada(d: Desejado, preco: float, perda: float, limite, risco: float, *,
                   stops_level: float = 0.0, so_encerrar: bool = False
                   ) -> tuple[bool, str | None]:
    """Pode entrar a este preço? `perda` já soma a perda do dia, o risco das
    posições abertas e o das entradas aprovadas nesta volta. `stops_level`
    em preço (SYMBOL_TRADE_STOPS_LEVEL × point)."""
    if not limite:
        # sem limite não há trava possível: a conta não opera (§5.7)
        return False, "conta sem limite de perda do dia"
    if d.stop_px is None:
        return False, "plano sem stop"
    if so_encerrar:
        return False, "contrato só aceita encerramento"
    preco = float(preco)
    if d.lado > 0:
        alem = preco <= d.stop_px or (d.alvo_px is not None and preco >= d.alvo_px)
    else:
        alem = preco >= d.stop_px or (d.alvo_px is not None and preco <= d.alvo_px)
    if alem:
        return False, "preço já além do stop/alvo do papel"
    if d.entry_px is not None and \
            abs(preco - d.stop_px) > TETO_STOP * abs(d.entry_px - d.stop_px):
        return False, "preço longe demais do stop do papel"
    if stops_level and (abs(preco - d.stop_px) < stops_level or (
            d.alvo_px is not None and abs(d.alvo_px - preco) < stops_level)):
        # a corretora recusaria o SL/TP depois de a entrada executar: a
        # posição nasceria sem stop e seria encerrada na hora
        return False, "stop ou alvo perto demais do preço (regra da corretora)"
    if perda + risco > TRAVA * float(limite):
        return False, "passaria da trava do dia"
    return True, None


def _custos(lv) -> dict:
    """Corretagem e emolumentos por contrato do plano da ligação (o mesmo
    perfil do papel). Sem plano legível: sem custos (a distância domina)."""
    if lv is None or lv.plano is None:
        return {}
    try:
        _, perfil = papel.perfil_do_plano(lv.plano)
    except Exception:
        return {}
    return {"corretagem": perfil.corretagem_por_contrato,
            "emolumentos": perfil.emolumentos_por_contrato}


def n_demo(retrato) -> int | None:
    """Quantas ligações estão na fase demo no retrato; None sem retrato (não
    se sabe). A tela decide o "Sem demo" por este número, e nunca por
    `ligacoes` do estado: sem desejados (papel indisponível) aquela lista
    vem vazia mesmo com demo ligada."""
    if retrato is None:
        return None
    # real ⊃ demo: no retrato de cada conta, "real" também opera nela
    return sum(1 for lv in retrato.ligacoes.values() if lv.fase in ("demo", "real"))


def _conta_logada(retrato, foto):
    """(conta_id, conta) do retrato cujo login/servidor é o do MT5 agora."""
    for cid, c in (retrato.contas if retrato else {}).items():
        if c.get("login") is None:
            continue
        if str(c["login"]).strip() == str(foto.login).strip() and \
                str(c.get("servidor") or "").strip() == str(foto.servidor or "").strip():
            return cid, c
    return None, None


# ======================================================================
# Motor: executa as ações de `planejar` no MT5, com o diário adiantado.
# ======================================================================
# saídas antes de tudo (uma posição a mais é risco; uma entrada a menos não);
# o cancelamento de resto vem antes da saída para o resto não abrir mais
# volume enquanto se sai; a adoção grava o ticket antes da proteção dele
_ORDEM_ACOES = {"cancelar": 0, "sair": 1, "adotar": 2, "proteger": 3,
                "saiu_antes": 4, "perdida": 4, "chamar": 4, "entrar": 5}
_METODO = {"chamar": "_chamado_do_plano"}     # `_chamar` é quem abre o chamado


def _preco_res(res) -> float | None:
    """O preço da resposta do `order_send`; 0 (bolsa: o preço vem no negócio,
    depois) = None, e o `preco_confirmado` completa."""
    preco = float(getattr(res, "price", 0) or 0)
    return preco or None


def _retcode(res) -> int | None:
    return None if res is None else int(res.retcode)


# ACCOUNT_TRADE_MODE_DEMO / _REAL (pacote MetaTrader5 5.0.6180, conferido)
_TM_DEMO, _TM_REAL = 0, 2
_NOME_TM = {0: "demo", 1: "concurso", 2: "real"}


class Motor:
    """Quem fala com o MT5. Cada envio tem a sua linha `*_enviando` no
    diário ANTES de sair (escrita adiantada): uma queda entre o envio e a
    resposta aparece na próxima subida como tentativa sem desfecho, e
    `planejar` espera o histórico em vez de duplicar a ordem."""

    def __init__(self, pasta, inst: dict, origem: str = "demo", relogio=None,
                 mono=None):
        self.pasta, self.origem = Path(pasta), origem
        self.tick = int(inst["tick_size"])
        self.ponto = float(inst["point_value"])
        # relogio() = hora do servidor AGORA (para o atraso medido depois da
        # resposta, rede incluída); mono = relógio local que não volta atrás
        self.relogio = relogio
        self.mono = mono or time.monotonic
        self._diario: Diario | None = None
        self.chamados: dict[str, dict] = {}
        self.so_encerrar: dict[str, bool] = {}
        # (tipo, ticket) -> mono do último envio: sem relógio do servidor o
        # diário não serve para o intervalo de 1 s, e a volta de 0,1 s
        # provocaria o "pedidos demais" (10024)
        self._envios: dict[tuple, float] = {}
        self._srv: tuple[datetime, float] | None = None
        self._sem_relogio = False
        # estado derivado do diário a cada volta (só para leitura/estado):
        # quem manda é o diário, que sobrevive a reinício
        self.zerar = False
        self.envio_forcado: dict[int, bool] = {}
        self._parado_desde: datetime | None = None
        # desde quando a foto não vem completa (I2b) e a última conta lida
        # numa foto completa: (login, servidor, hedging, algo, margem, mono)
        self._incompleta_desde: datetime | None = None
        self._conta_vista: tuple | None = None
        # a "Ordem de teste" (core/ordem_teste.py): anda uma etapa por volta,
        # depois das ações das estratégias
        self.teste = OrdemTeste(self)

    # ---------------------------------------------------------- diário
    def diario(self, dia) -> Diario:
        if self._diario is None or self._diario.dia != dia:
            self._diario = Diario(self.pasta, dia, self.origem)
            # "só encerramento" vale para o resto do DIA; chamados também
            # não atravessam a noite (nada fica aberto de um pregão ao outro)
            self.so_encerrar = {}
            self._envios = {}
            self.chamados = {}
        return self._diario

    def _quando(self, agora_srv):
        """Hora dos eventos desta volta. Sem relógio do servidor: a última
        hora vista mais o tempo local decorrido (o mesmo raciocínio do
        RelogioServidor) — só para datar o evento, nenhuma janela usa."""
        m = self.mono()
        if agora_srv is not None:
            self._srv = (agora_srv, m)
            return agora_srv
        if self._srv is not None:
            return self._srv[0] + timedelta(seconds=m - self._srv[1])
        return datetime.now()

    def _depois(self, agora):
        """Hora do servidor depois de uma resposta do MT5."""
        if self.relogio is not None:
            try:
                h = self.relogio()
            except Exception:
                h = None
            if h is not None:
                return max(h, agora)
        return agora

    def _pode_enviar(self, tipo, ticket) -> bool:
        ult = self._envios.get((tipo, ticket))
        return not (self._sem_relogio and ult is not None
                    and self.mono() - ult < INTERVALO_S)

    def _marcar(self, tipo, ticket):
        self._envios[(tipo, ticket)] = self.mono()

    # -------------------------------------------------------- chamados
    def _chamar(self, chave, tipo, texto, agora, *, ligacao_id=None, ticket=None,
                entry_ts=None):
        if chave in self.chamados:
            return
        self.chamados[chave] = {"tipo": tipo, "texto": texto, "ligacao_id": ligacao_id,
                                "ticket": ticket, "desde": agora, "entry_ts": entry_ts}
        extra = {k: v for k, v in (("ligacao_id", ligacao_id), ("ticket", ticket),
                                   ("entry_ts", entry_ts)) if v is not None}
        self.diario(agora.date()).registrar("chamado", quando=agora, motivo=texto,
                                            chave=chave, **extra)

    def _fechar(self, chave, agora):
        if self.chamados.pop(chave, None) is not None:
            self.diario(agora.date()).registrar("chamado_fechado", quando=agora,
                                                motivo=chave)
            return True
        return False

    def fechar(self, chave, agora=None) -> bool:
        """Fecha um chamado de fora (botão "Manter e acompanhar"). Sem hora,
        usa a estimativa da hora do servidor."""
        return self._fechar(chave, agora or self._quando(None))

    def _fechar_resolvidos(self, foto, agora, estavel):
        """Chamado de posição fecha quando a posição sumiu da corretora; o de
        posição sem stop, também quando o stop apareceu. Logo após reconectar
        a lista pode vir vazia por engano: aí não fecha nada."""
        if foto is None or not estavel:
            return
        vivas = {p.ticket: p for p in foto.posicoes}
        for chave, c in list(self.chamados.items()):
            if c.get("ticket") is None:
                continue
            p = vivas.get(c["ticket"])
            if p is None or (c["tipo"] == "sem_stop" and round(p.sl) != 0):
                self._fechar(chave, agora)

    def _fechar_da_operacao(self, lig, entry_ts, agora):
        if entry_ts is None:
            return
        for chave, c in list(self.chamados.items()):
            if c.get("ligacao_id") == lig and c.get("entry_ts") == entry_ts:
                self._fechar(chave, agora)

    def _fechar_operacoes_encerradas(self, agora_srv):
        """Chamado de entrada (sem margem, Algo desligado...) cai quando a
        janela de entrada passou e a operação já tem desfecho final: não há
        mais nada a decidir sobre ela."""
        if agora_srv is None:
            return
        dia = self.diario(agora_srv.date())
        for chave, c in list(self.chamados.items()):
            ts = c.get("entry_ts")
            if ts is None or _seg(agora_srv, ts) <= JANELA_ENTRADA_S:
                continue
            if dia.desfecho(c.get("ligacao_id"), ts) is not None:
                self._fechar(chave, agora_srv)

    def _condicao(self, chave, falha: bool, texto, agora) -> bool:
        """Chamado de infraestrutura: abre enquanto a condição falha e fecha
        sozinho na primeira volta em que ela some."""
        if falha:
            self._chamar(chave, chave, texto, agora)
        else:
            self._fechar(chave, agora)
        return falha

    # ------------------------------------------------------------ passo
    def passo(self, mt5, *, agora_srv, retrato, desejados, disponivel, comandos,
              simbolo, contrato_ok, conectado_ha_s, no_pregao: bool = True,
              contrato_motivo: str | None = None) -> dict:
        """A volta inteira das ordens; devolve o bloco `ordens` do estado.json.

        `comandos`: a pasta dos comandos da tela (consumidos aqui, cada um
        gravado no diário ANTES de o arquivo sumir) ou a lista já lida.
        `no_pregao`: papel indisponível fora do pregão não é alarme.
        `contrato_motivo`: por que o contrato não opera agora (None = o texto
        padrão); SEM_CONTRATO é passageiro (a entrada tenta de novo).
        Retrato com `antigo=True` (lido do arquivo, banco ocupado na
        subida): nada entra, a proteção e as saídas por comando seguem."""
        agora = self._quando(agora_srv)
        dia = self.diario(agora.date())
        falhas: list = []
        foto = K.fotografar(mt5, datetime.combine(agora.date(), datetime.min.time()),
                            falhas)
        foto = self._completar_conta(foto, conectado_ha_s)
        self._vigiar_leitura(foto, falhas, dia, agora, no_pregao)
        if foto is None:
            # sem posições/ordens nada se decide (§5.1); nem comando se consome
            # foto que falha não é erro das ordens (o MT5 devolveu None):
            # `falhou` diz só se o passo estourou alguma exceção
            self.recusar_testes(comandos, dia, agora, "corretora sem leitura")
            return {"foto": "falhou", "vivo_em": agora, "falhou": False,
                    "n_demo": n_demo(retrato), "falhas": falhas,
                    "teste": self.teste.estado(),
                    "chamados": [dict(c, chave=k) for k, c in self.chamados.items()]}
        antigo = bool(getattr(retrato, "antigo", False))

        # papel parado: indisponível há mais de 3 min no pregão (§5.1)
        if disponivel or not no_pregao:
            self._parado_desde = None
            self._fechar("papel_parado", agora)
        elif self._parado_desde is None:
            self._parado_desde = agora
        elif _seg(agora, self._parado_desde) > PAPEL_PARADO_S:
            self._chamar("papel_parado", "papel_parado", (
                "papel parado há mais de 3 min: banco ocupado desde a subida, "
                "com a configuração salva (só protege e sai por comando; nada entra)"
                if antigo else
                "papel parado há mais de 3 min (só protege e sai por comando; "
                "nada entra)"), agora)

        # os retornos antecipados também mostram o zerar desta volta
        self.zerar = self._zerar_ativo(dia, retrato, agora)

        # 2. a conta: nenhuma ordem (nem saída) fora da conta certa, hedging,
        # com o Algo Trading ligado
        cid, conta = _conta_logada(retrato, foto)
        est = self._estado_base(foto, agora, cid, simbolo, retrato)
        if conta is None:
            if foto.login is None:
                # conta ilegível (foto parcial sem a conta de antes): não se
                # sabe em que conta o MT5 está — nada sai, e não é "conta
                # errada": o chamado `sem_leitura` já diz o que falha
                self.recusar_testes(comandos, dia, agora, "conta do MT5 ilegível")
                return self._estado_fim(est, dia)
            demo = bool(retrato) and any(lv.fase in ("demo", "real")
                                         for lv in retrato.ligacoes.values())
            self._condicao("conta_errada", demo,
                           f"MT5 logado em outra conta ({foto.login} · {foto.servidor})",
                           agora)
            self.recusar_testes(comandos, dia, agora,
                                "o MT5 não está logado numa conta cadastrada")
            return self._estado_fim(est, dia)
        # 2b. o tipo da conta (demo ou real) tem de ser o da origem do motor:
        # conta errada não sai nada, nem saída nem proteção nem ordem de teste
        recusa = self._conta_certa(foto)
        if recusa:
            self._condicao("conta_errada", True, recusa, agora)
            # mesmo texto da "Ordem de teste" para a conta que não é a do motor
            motivo = ("a conta do MT5 não é " + ("REAL" if self.origem == "real" else "DEMO")
                      if foto.trade_mode is not None else "conta do MT5 ilegível")
            self.recusar_testes(comandos, dia, agora, motivo)
            return self._estado_fim(est, dia)
        self._fechar("conta_errada", agora)
        nao_hedging = self._condicao("nao_hedging", not foto.hedging,
                                     "conta não é hedging", agora)
        sem_algo = self._condicao("algo_desligado", not foto.algo_ligado,
                                  "Algo Trading desligado no MT5", agora)
        if nao_hedging or sem_algo:
            self.recusar_testes(comandos, dia, agora, "conta não é hedging"
                                if nao_hedging else "Algo Trading desligado no MT5")
            return self._estado_fim(est, dia)

        try:
            self._confirmar_precos(mt5, foto, dia, agora)
        except Exception:
            # só a tela perde o preço: comandos, zerar e trava seguem
            log.exception("preço confirmado falhou")

        # 3. comandos: primeiro no diário, depois apagados; zerar e o
        # desligar forçado são derivados do diário (sobrevivem a reinício)
        falhou = False
        try:
            est["comandos"] = self._consumir(comandos, dia, agora)
        except Exception as erro:
            log.exception("comandos da tela falharam")
            self._chamar("ordens_falhou", "ordens_falhou", f"erro nas ordens: {erro}", agora)
            falhou = True
        self.zerar = self._zerar_ativo(dia, retrato, agora)
        forcado = self._envio_forcado(dia, retrato, cid, conta, agora)
        self.envio_forcado = {cid: False} if forcado else {}
        encerrar = {int(e["ticket"]) for e in dia.comandos_do_dia("encerrar_posicao")
                    if e.get("ticket") is not None}

        # 4. trava a 90% do limite (6b: até o próximo pregão, sem destravar)
        perda = perda_do_dia(foto, retrato.portfolio_de, None)
        limite = conta.get("limite")
        travada = dia.travada(cid)
        if travada is None and limite and perda["total"] >= TRAVA * float(limite):
            travada = dia.registrar("conta_travada", quando=agora, conta_id=cid,
                                    perda=perda["total"], limite=float(limite))

        # 5. Envio de ordens
        # sem limite cadastrado o Envio não liga (§5.7) — nem com o limite
        # apagado no meio do dia: a trava não teria como agir
        ligado = bool(conta.get("envio")) and bool(limite) and not forcado \
            and not travada and not self.zerar
        # entra só com a foto completa e a configuração lida agora
        envio = ligado and not antigo and not foto.parcial
        geral = "zerar tudo" if self.zerar else ("conta travada" if travada else None)
        if antigo and not geral and forcado:
            geral = "envio desligado"
        finais = {}
        for lig, d in desejados.items():
            lv = retrato.ligacoes.get(lig)
            if geral:
                d = Desejado(ZERADO, motivo=geral)
            elif antigo:
                continue
            elif lv is None or lv.conta_id != cid:
                # C4: nunca uma ordem de um portfólio na conta de outro
                d = Desejado(ZERADO, motivo="conta de outro portfólio")
            elif not ligado and d.estado != ZERADO:
                d = Desejado(ZERADO, motivo="envio desligado")
            finais[lig] = d
        # retrato antigo (banco ocupado desde a subida): fase, ligada e Envio
        # dele podem ter mudado depois — só zerar, trava e o desligar por
        # comando (todos do diário) encerram; o resto fica indisponível (só
        # protege). Foto parcial: o Envio decide a saída como sempre; a
        # entrada é o planejar que barra.
        zera_tudo = bool(geral) or (not ligado and not antigo)
        if zera_tudo:
            # o papel nem precisa estar disponível: tudo da automação sai
            for lig in ({p.ligacao_id for p in foto.posicoes if p.ligacao_id}
                        | dia.ligacoes_abertas()) - set(finais):
                finais[lig] = Desejado(ZERADO, motivo=geral or "envio desligado")

        # 6. planejar e a régua de cada entrada. Se isso estoura, a proteção
        # ainda sai (7): posição sem stop não pode ficar esperando o erro
        # passar. Nesse caminho nunca há entrada.
        try:
            acoes = planejar(finais, (disponivel and not antigo) or zera_tudo, foto, dia,
                             agora_srv, self.tick, conectado_ha_s)
            acoes = self._encerrar_pedidos(acoes, foto, encerrar, dia, agora_srv)
            seria = []
            if not envio and not geral and not antigo and not foto.parcial:
                seria = self._seria_enviadas(desejados, retrato, cid, dia, agora_srv,
                                             disponivel, conectado_ha_s)
            pode_entrar = self._regua(mt5, foto, retrato, perda, limite, simbolo,
                                      contrato_ok, dia, desejados, agora, contrato_motivo)
        except Exception as erro:
            log.exception("planejar das ordens falhou")
            self._chamar("ordens_falhou", "ordens_falhou", f"erro nas ordens: {erro}", agora)
            falhou = True
            acoes = []
            for lig in sorted({p.ligacao_id for p in foto.posicoes if p.ligacao_id}):
                acoes += _so_protecao(foto, dia, lig, agora_srv)
            seria = []
            pode_entrar = lambda a: (False, "planejar falhou")

        # 7. executar: saídas primeiro, entradas à parte — uma falha nas
        # entradas não impede as saídas desta volta (e vice-versa)
        ctx = dict(foto=foto, agora_srv=agora_srv, simbolo=simbolo,
                   desvio={l: (lv.desvio or 2 * self.tick)
                           for l, lv in retrato.ligacoes.items()},
                   pode_entrar=pode_entrar, envio=envio, conta_id=cid,
                   conectado_ha_s=conectado_ha_s)
        for lote in ([a for a in acoes if a.tipo != "entrar"],
                     [a for a in acoes if a.tipo == "entrar"] + seria):
            try:
                self.executar(mt5, lote, **ctx)
            except Exception as erro:
                log.exception("ordens da volta falharam")
                self._chamar("ordens_falhou", "ordens_falhou", f"erro nas ordens: {erro}",
                             agora)
                falhou = True
        # 8. a "Ordem de teste": DEPOIS das ações das estratégias, uma etapa
        # por volta — nunca atrasa uma entrada nem uma saída delas
        # vale na conta do processo (demo ou real): a OrdemTeste confere login,
        # tipo cadastrado e trade_mode do MT5 contra `self.origem` antes de
        # enviar (liberado na real a pedido do usuário em 21/10/2026)
        pedidos = [c for c in est.get("comandos") or [] if c.get("tipo") == "ordem_teste"]
        try:
            self.teste.volta(mt5, foto=foto, dia=dia, agora=agora, pedidos=pedidos,
                             cid=cid, conta=conta, no_pregao=no_pregao,
                             simbolo=simbolo, contrato_ok=contrato_ok,
                             travada=travada is not None, zerar=self.zerar)
        except Exception as erro:
            log.exception("ordem de teste falhou")
            self.teste.erro(dia, agora, erro)
        if not falhou:
            self._fechar("ordens_falhou", agora)

        # 9. estado
        est.update(
            falhou=falhou,
            envio=ligado, zerar=self.zerar, perda=perda,
            limite=float(limite) if limite else None,
            travada=None if travada is None else {
                "desde": travada["quando"], "perda": travada.get("perda"),
                "limite": travada.get("limite")},
            ligacoes=self._estado_ligacoes(foto, dia, desejados, finais))
        return self._estado_fim(est, dia)

    # ---------------------------------------------------- passo: partes
    def _conta_certa(self, foto) -> str | None:
        """Motivo de recusa se a conta do MT5 não é a da origem do motor
        (demo exige ACCOUNT_TRADE_MODE_DEMO; real exige REAL), None se é.
        Tipo desconhecido (None) recusa: a foto parcial já herdou o tipo da
        mesma conexão em `_completar_conta`, então o que sobra é não saber."""
        real = self.origem == "real"
        nome = "real" if real else "demo"
        if foto.trade_mode is None:
            return f"tipo da conta do MT5 desconhecido (motor {nome})"
        if foto.trade_mode != (_TM_REAL if real else _TM_DEMO):
            return (f"MT5 numa conta {_NOME_TM.get(foto.trade_mode, foto.trade_mode)} "
                    f"({foto.login} · {foto.servidor}): motor {nome} não opera aqui")
        return None

    def _completar_conta(self, foto, conectado_ha_s):
        """Foto parcial sem a conta (ou o terminal): vale a última lida numa
        foto completa SE a conexão não caiu desde então (trocar de conta no
        MT5 derruba a conexão). Sem isso a conta fica desconhecida e nada
        sai — nunca uma ordem numa conta que não se sabe qual é."""
        if foto is None:
            return None
        m = self.mono()
        if not foto.parcial:
            self._conta_vista = (foto.login, foto.servidor, foto.hedging,
                                 foto.algo_ligado, foto.margem_livre, m,
                                 foto.trade_mode)
            return foto
        v = self._conta_vista
        mesma_conexao = v is not None and conectado_ha_s >= m - v[5]
        if foto.login is None and mesma_conexao:
            foto.login, foto.servidor, foto.hedging, foto.margem_livre = \
                v[0], v[1], v[2], v[4]
        if foto.trade_mode is None and mesma_conexao:
            # sem account_info: o tipo (demo/real) é o último visto na mesma conexão
            foto.trade_mode = v[6]
        if "dados do terminal" in foto.falhas:
            # Algo Trading desconhecido: o último visto na mesma conexão; sem
            # ele, tenta — Algo desligado volta 10027 e vira chamado, e sair
            # é justamente o que se quer da foto parcial
            foto.algo_ligado = v[3] if mesma_conexao else True
        return foto

    def _vigiar_leitura(self, foto, falhas, dia, agora, no_pregao):
        """Chamado `sem_leitura` (I2b): no pregão, a foto incompleta por mais
        de 30 s chama; sem nem a foto parcial e com posição da automação
        aberta no diário, chama na hora (nada sai). Fecha sozinho na
        primeira foto completa. Fora do pregão não abre."""
        if foto is not None and not foto.parcial:
            self._incompleta_desde = None
            self._fechar("sem_leitura", agora)
            return
        if self._incompleta_desde is None:
            self._incompleta_desde = agora
        if not no_pregao:
            return
        oque = ", ".join(falhas) or "leitura da corretora"
        if foto is None and dia.ligacoes_abertas():
            self._chamar("sem_leitura", "sem_leitura",
                         f"corretora sem leitura ({oque}) com posição da automação "
                         "aberta: nada sai até voltar (stop e alvo seguem na corretora)",
                         agora)
        elif _seg(agora, self._incompleta_desde) > SEM_LEITURA_S:
            self._chamar("sem_leitura", "sem_leitura", (
                f"corretora sem leitura ({oque}) há mais de 30 s: nada entra nem sai"
                if foto is None else
                f"corretora com leitura parcial ({oque}) há mais de 30 s: só sai "
                "e protege; na posição de uma entrada sem resposta (sem adotá-la) "
                "tenta pôr o stop enviado; se a corretora recusar, encerra (mais "
                "de uma, ou sem stop gravado: chamado de posição sem stop); "
                "nada entra"), agora)

    def recusar_testes(self, comandos, dia, agora, motivo) -> None:
        """Volta que não chega à "Ordem de teste" (MT5 fora, fora do pregão,
        conta errada, Algo desligado): consome só os pedidos de teste e os
        recusa com o motivo — o clique nunca fica esperando calado nem roda
        minutos depois. Os outros comandos ficam para a volta que os cumpre."""
        try:
            pedidos = self._consumir(comandos, dia, agora, tipos={"ordem_teste"})
            if pedidos:
                self.teste.recusar(pedidos, dia, agora, motivo)
        except Exception:
            log.exception("recusa da ordem de teste falhou")

    def _consumir(self, comandos, dia, agora, tipos=None) -> list[dict]:
        vistos = {e.get("comando_id") for e in dia.eventos
                  if e["tipo"] == "comando" and e.get("comando_id")}

        def registrar(c):
            # o unlink pode falhar no Windows e o arquivo voltar na volta
            # seguinte: um "zerar" repetido depois de cumprido zeraria de novo
            if c.get("id") and c["id"] in vistos:
                return False
            vistos.add(c.get("id"))
            campos = {k: v for k, v in c.items() if k not in ("tipo", "id", "quando")}
            if c.get("tipo") == "zerar_tudo" and _de_outro_dia(c.get("criado_em"), dia.dia):
                # clicado fora do pregão sem posição, o arquivo só é lido na
                # manhã seguinte: valendo, desligaria o Envio o dia inteiro.
                # O desligar no banco o clique já fez; aqui só se registra.
                dia.registrar("comando", quando=agora, motivo=ZERAR_DESCARTADO,
                              comando="zerar_tudo", comando_id=c.get("id"), **campos)
                return False
            dia.registrar("comando", quando=agora, motivo=c["tipo"],
                          comando_id=c.get("id"), **campos)
        if comandos is None:
            return []
        if isinstance(comandos, (str, Path)):
            return comandos_mod.consumir(comandos, registrar=registrar, tipos=tipos)
        return [c for c in comandos if (tipos is None or c.get("tipo") in tipos)
                and registrar(c) is not False]

    def _zerar_ativo(self, dia, retrato, agora) -> bool:
        """"Zerar tudo" vale até o retrato (lido DEPOIS do comando) mostrar o
        Envio desligado em todas as contas, ou até o fim do dia. O fim é
        gravado no diário: o usuário pode religar o Envio no mesmo dia."""
        ativo = None
        for e in dia.eventos:
            if e["tipo"] == "comando" and e.get("motivo") == "zerar_tudo":
                ativo = e
            elif e["tipo"] == "comando" and e.get("motivo") == "zerar_tudo_cumprido":
                ativo = None
        # o retrato antigo (do arquivo) nunca dá o zerar por cumprido: ele
        # não viu o desligar no banco que o clique fez
        if ativo is not None and retrato is not None \
                and not getattr(retrato, "antigo", False) \
                and retrato.lido_em >= ativo["quando"] \
                and not any(c.get("envio") for c in retrato.contas.values()):
            dia.registrar("comando", quando=agora, motivo="zerar_tudo_cumprido")
            ativo = None
        return ativo is not None

    def _envio_forcado(self, dia, retrato, cid, conta, agora) -> bool:
        """Desligar o Envio vem também por comando (o banco pode estar
        ocupado); vale até o retrato lido depois dele concordar. O comando
        só DESLIGA: ligar vem sempre do banco — um `ligado` verdadeiro só
        solta o desligar forçado anterior."""
        ativo = None
        for e in dia.eventos:
            if e["tipo"] != "comando" or e.get("conta_id") != cid:
                continue
            if e.get("motivo") == "envio":
                ativo = None if e.get("ligado") else e
            elif e.get("motivo") == "envio_cumprido":
                ativo = None
        if ativo is not None and not getattr(retrato, "antigo", False) \
                and retrato.lido_em >= ativo["quando"] and not conta.get("envio"):
            dia.registrar("comando", quando=agora, motivo="envio_cumprido", conta_id=cid)
            ativo = None
        return ativo is not None

    def _encerrar_pedidos(self, acoes, foto, encerrar, dia, agora_srv) -> list:
        """"Encerrar posição" (chamado): sai daquele ticket da automação a
        cada volta até ele sumir — o comando está no diário, a saída nunca
        desiste. Posição sem o magic nunca é tocada."""
        alvo = {p.ticket: p for p in foto.posicoes
                if p.ticket in encerrar and p.ligacao_id is not None}
        if not alvo:
            return acoes
        out = [a for a in acoes if not (a.ticket in alvo and a.tipo in ("sair", "proteger"))]
        for t, p in alvo.items():
            if agora_srv is None or _pode(dia.ultima_tentativa("saida_enviando", ticket=t),
                                          agora_srv):
                out.append(Acao("sair", p.ligacao_id, ticket=t, posicao=p,
                                motivo="encerrada pelo usuário"))
        return out

    def _seria_enviadas(self, desejados, retrato, cid, dia, agora_srv, disponivel,
                        conectado_ha_s) -> list:
        """Envio desligado: a entrada que iria agora vira "seria enviada"
        (o ensaio), com a mesma régua da entrada de verdade."""
        if not disponivel or agora_srv is None or conectado_ha_s < GRACA_RECONEXAO_S:
            return []
        out = []
        for lig, d in sorted(desejados.items()):
            lv = retrato.ligacoes.get(lig)
            if d.estado != POSICAO or lv is None or lv.conta_id != cid:
                continue
            if _seg(agora_srv, d.entry_ts) > JANELA_ENTRADA_S or dia.enviada(lig, d.entry_ts):
                continue
            if any(dia.registrado(lig, d.entry_ts, t)
                   for t in ("seria_enviada", "perdida", "nao_entrou")):
                continue
            out.append(Acao("entrar", lig, desejado=d))
        return out

    def _regua(self, mt5, foto, retrato, perda, limite, simbolo, contrato_ok, dia,
               desejados, agora=None, contrato_motivo=None):
        """`pode_entrar` da volta (6a + D1). O que já está em risco soma: a
        perda do dia, o caminho até o stop de cada posição aberta da
        automação (sem SL na corretora: o stop da operação), cada entrada
        ainda sem desfecho ou aguardando a bolsa, cada ordem pendente com o
        magic e cada entrada aprovada nesta volta — senão duas ligações que
        entram em voltas seguidas passariam juntas da trava. Lê o MT5 só
        quando uma entrada pede (dentro do executar, que isola o erro)."""
        acumulado: list = []
        ticks: dict = {}

        def preco(sim, lado, saida, reserva):
            if sim not in ticks:
                ticks[sim] = mt5.symbol_info_tick(sim) if sim else None
            tk = ticks[sim]
            if tk is None:
                return float(reserva)
            # saída de compra no bid, entrada de compra no ask (venda espelhada)
            return float(tk.bid if (lado > 0) == saida else tk.ask)

        def stop_da_operacao(lig, ate=None, ordem=None):
            """O stop enviado (já arredondado) da operação a que a posição ou
            a ordem pertence: a da ordem pelo ticket gravado na `aceita`;
            senão a última entrada da ligação que começou até `ate` (a
            posição/ordem não nasce antes da operação); senão a última da
            ligação; senão o do papel agora. Uma operação nova da mesma
            ligação não pode emprestar o stop dela a uma posição antiga."""
            envios = [e for e in dia.eventos
                      if e.get("ligacao_id") == lig and e["tipo"] == "enviando"
                      and e.get("stop_px") is not None]
            if ordem is not None:
                ts = next((e.get("entry_ts") for e in reversed(dia.eventos)
                           if e["tipo"] == "aceita" and e.get("ligacao_id") == lig
                           and e.get("ordem") == ordem), None)
                da = [e for e in envios if ts is not None and e.get("entry_ts") == ts]
                if da:
                    return float(da[-1]["stop_px"])
            if ate is not None:
                antes = [e for e in envios if e.get("entry_ts") and e["entry_ts"] <= ate]
                if antes:
                    return float(antes[-1]["stop_px"])
            if envios:
                return float(envios[-1]["stop_px"])
            d = desejados.get(lig)
            if d is not None and d.estado == POSICAO and d.stop_px is not None:
                return float(K.protecao(d.lado, d.stop_px, None, self.tick)[0])
            return None

        def em_risco() -> float:
            total = 0.0
            minhas = [p for p in foto.posicoes if p.ligacao_id is not None]
            for p in minhas:
                stop = float(p.sl) if round(p.sl) != 0 else None
                if stop is None:
                    reg = dia.protecao_registrada(p.ticket)
                    stop = float(reg[1]) if reg else stop_da_operacao(
                        p.ligacao_id, ate=p.aberta_em)
                if stop is None:
                    continue      # stop desconhecido: sem proteção, ela sai em 2 s
                total += abs(preco(p.simbolo, p.lado, True, p.preco) - stop) \
                    * p.volume * self.ponto
            # entradas em trânsito: enviadas, ainda sem posição
            em_transito = set()
            ops = {(e["ligacao_id"], e["entry_ts"]): e for e in dia.eventos
                   if e["tipo"] == "enviando" and e.get("ligacao_id") is not None}
            for (lig, ts), e in ops.items():
                if dia.ticket(lig, ts) is not None or any(
                        p.ligacao_id == lig and p.aberta_em >= ts for p in minhas):
                    continue      # virou posição (contada acima) ou já saiu
                if dia.tentativa_sem_desfecho(lig, ts) is None and \
                        dia.desfecho(lig, ts) not in ("aceita", "executada", "parcial"):
                    continue      # recusada / perdida / não entrou: não há ordem viva
                # só enquanto viva: o papel ainda quer ESTA operação e ela está
                # na janela. Papel zerado, operação nova, zerar ou trava antes
                # da perdida deixariam o risco preso até a meia-noite; ordem
                # ou posição que de fato existam seguem contadas pela foto
                d_lig = desejados.get(lig)
                if d_lig is None or d_lig.estado != POSICAO or d_lig.entry_ts != ts:
                    continue
                ultimo = max(x["quando"] for x in dia._da(lig, ts, "enviando", "incerta",
                                                         "aceita"))
                if agora is None or _seg(agora, ultimo) > JANELA_ENTRADA_S + 5:
                    continue
                if e.get("stop_px") is None:
                    continue
                em_transito.add(lig)
                total += abs(preco(e.get("simbolo"), e.get("lado") or 1, False,
                                   e.get("preco_papel") or e["stop_px"])
                             - float(e["stop_px"])) * float(e.get("contratos") or 0) \
                    * self.ponto
            # ordem pendente com o magic que não é a entrada já contada nem a
            # saída em trânsito de uma posição (ex.: resto de parcial)
            for o in foto.ordens:
                lig = o.get("ligacao_id")
                if lig is None or lig in em_transito or not o.get("lado"):
                    continue
                if any(p.ligacao_id == lig and p.lado == -o["lado"] for p in minhas):
                    continue
                stop = stop_da_operacao(lig, ate=o.get("quando"), ordem=o.get("ticket"))
                if stop is None:
                    continue
                total += abs(preco(o.get("simbolo"), o["lado"], False, stop) - stop) \
                    * float(o.get("volume") or 0) * self.ponto
            return total

        def pode_entrar(a):
            if not contrato_ok or not simbolo:
                # SEM_CONTRATO (ainda não escolhido) é passageiro; vencimento
                # hoje e a guarda de preço trazem o próprio texto
                return False, contrato_motivo or SEM_CONTRATO_HOJE
            if not acumulado:
                info = mt5.symbol_info(simbolo)
                stops = 0.0 if info is None else float(info.trade_stops_level or 0) * float(
                    getattr(info, "point", 1.0) or 1.0)
                acumulado[:] = [perda["total"] + em_risco(), stops]
            d = a.desejado
            tk = mt5.symbol_info_tick(simbolo)
            if tk is None:
                return False, SEM_COTACAO
            preco_ = float(tk.ask if d.lado > 0 else tk.bid)
            risco = risco_entrada(d, preco_, _custos(retrato.ligacoes.get(a.ligacao_id)),
                                  self.ponto, tick=self.tick)
            ok, motivo = checar_entrada(d, preco_, acumulado[0], limite, risco,
                                        stops_level=acumulado[1],
                                        so_encerrar=bool(self.so_encerrar.get(simbolo)))
            if ok:
                acumulado[0] += risco
            return ok, motivo
        return pode_entrar

    def _estado_base(self, foto, agora, cid, simbolo, retrato=None) -> dict:
        return {
            "n_demo": n_demo(retrato),
            # o passo terminou sem exceção? Os retornos antecipados (conta
            # errada, sem hedging, Algo desligado) são limpos: quem chama
            # fecha o chamado `ordens_falhou` aberto fora do passo
            "falhou": False,
            "foto": "parcial" if foto.parcial else "ok", "falhas": list(foto.falhas),
            "retrato_antigo": bool(getattr(retrato, "antigo", False)),
            "vivo_em": agora, "contrato": simbolo,
            "conta": {"conta_id": cid, "login": foto.login, "servidor": foto.servidor,
                      "confere": cid is not None, "hedging": foto.hedging,
                      "algo": foto.algo_ligado, "margem_livre": foto.margem_livre},
            "envio": False, "zerar": self.zerar, "travada": None, "perda": None,
            "limite": None, "ligacoes": {}, "comandos": [],
            # §6.3: aviso, não chamado — a automação nunca toca nelas
            "posicao_fora": [{"ticket": p.ticket, "simbolo": p.simbolo, "lado": p.lado,
                              "volume": p.volume, "resultado": p.resultado}
                             # a de teste não é "fora": a sequência dela a encerra
                             for p in foto.posicoes
                             if p.ligacao_id is None and p.magic != K.MAGIC_TESTE],
        }

    def _estado_fim(self, est, dia) -> dict:
        # a tela só relê o banco quando `ordens_em` muda: é a hora do último
        # evento do diário, não a da volta (essa é o `vivo_em`)
        est["ordens_em"] = dia.eventos[-1]["quando"] if dia.eventos else None
        est["chamados"] = [dict(c, chave=k) for k, c in self.chamados.items()]
        est["teste"] = self.teste.estado()
        return est

    def _estado_ligacoes(self, foto, dia, desejados, finais) -> dict:
        ligs = (set(desejados) | set(finais) | dia.ligacoes_abertas()
                | {p.ligacao_id for p in foto.posicoes if p.ligacao_id})
        out = {}
        for lig in sorted(ligs):
            d = finais.get(lig) or Desejado(ZERADO, motivo="fora do papel de hoje")
            orig = desejados.get(lig)
            out[lig] = {
                "desejado": d.estado, "papel": orig.estado if orig else None,
                "motivo": d.motivo, "lado": d.lado, "entry_ts": d.entry_ts,
                "stop_px": d.stop_px, "alvo_px": d.alvo_px, "contratos": d.contratos,
                "tentativas": dia.tentativas(lig, d.entry_ts) if d.entry_ts else 0,
                "posicoes": [{
                    "ticket": p.ticket, "simbolo": p.simbolo, "lado": p.lado,
                    "volume": p.volume, "preco": p.preco, "sl": p.sl, "tp": p.tp,
                    "resultado": p.resultado, "saida_desde": dia.saida_desde(p.ticket),
                    "tentativas": sum(1 for e in dia.eventos
                                      if e["tipo"] == "saida_enviando"
                                      and e.get("ticket") == p.ticket)}
                    for p in foto.posicoes if p.ligacao_id == lig],
            }
        return out

    # -------------------------------------------------------- executar
    def executar(self, mt5, acoes, *, foto, agora_srv, simbolo, desvio,
                 pode_entrar, envio, conta_id, conectado_ha_s) -> None:
        agora = self._quando(agora_srv)
        self._sem_relogio = agora_srv is None
        self.diario(agora.date())
        self._fechar_resolvidos(foto, agora, conectado_ha_s >= GRACA_RECONEXAO_S)
        self._fechar_operacoes_encerradas(agora_srv)
        ctx = dict(foto=foto, agora=agora, simbolo=simbolo,
                   pode_entrar=pode_entrar, envio=envio, conta_id=conta_id)
        erros = []
        # ligação cuja saída CONTRÁRIA desta volta não se confirmou: a
        # entrada dela espera (virada de mão — a anterior pode seguir aberta)
        saida_pendente: set = set()
        lado_entrada = {a.ligacao_id: a.desejado.lado for a in acoes
                        if a.tipo == "entrar"}
        for a in sorted(acoes, key=lambda a: _ORDEM_ACOES[a.tipo]):
            if a.tipo == "entrar" and a.ligacao_id in saida_pendente:
                continue
            # deviation é da ligação (derrapagem do plano dela + folga); sem
            # ela no dicionário, a folga mínima de 2 ticks
            d_a = desvio.get(a.ligacao_id, 2 * self.tick) if isinstance(desvio, dict) \
                else desvio
            # uma ação que estoura não pode impedir as outras (a saída de uma
            # ligação não espera a entrada da outra); o erro sobe no fim
            try:
                r = getattr(self, _METODO.get(a.tipo, f"_{a.tipo}"))(mt5, a, desvio=d_a,
                                                                      **ctx)
                if a.tipo == "sair" and r not in (K.OK, K.JA_SAIU)                         and a.posicao.lado == -lado_entrada.get(a.ligacao_id, 0):
                    saida_pendente.add(a.ligacao_id)
            except Exception as erro:
                if a.tipo == "sair" and a.posicao is not None                         and a.posicao.lado == -lado_entrada.get(a.ligacao_id, 0):
                    saida_pendente.add(a.ligacao_id)
                log.exception("ação %s da ligação %s falhou", a.tipo, a.ligacao_id)
                erros.append(erro)
        if erros:
            raise erros[0]

    # ---------------------------------------------------- preço confirmado
    def _confirmar_precos(self, mt5, foto, dia, agora) -> None:
        """Na bolsa (conta real) o `order_send` volta com `price` 0: o preço
        só existe no negócio, que aparece depois (doc do MqlTradeResult:
        "deal price, confirmed by broker"). Execução sem preço ganha UM
        `preco_confirmado` por ticket e ponta, com o preço médio dos negócios
        da posição (a entrada cai no `price_open` da posição se o negócio
        ainda não veio). Saída pelo stop/alvo da corretora não conta: tem o
        próprio `saiu_antes` com preço."""
        if foto.parcial:
            return
        # saída só com o ticket encerrado: a parcial sozinha gravaria o preço
        # dela para a saída inteira
        fechados = {int(e["ticket"]) for e in dia.eventos if e.get("ticket")
                    and e["tipo"] in ("saida_executada", "saiu_antes")}
        faltam = {}
        for e in dia.eventos:
            t = e.get("ticket")
            if not t:
                continue
            if e["tipo"] == "preco_confirmado":
                faltam[(int(t), e.get("ponta"))] = None
                continue
            ponta = ("entrada" if e["tipo"] in ("executada", "parcial") else
                     "saida" if e["tipo"] in ("saida_executada", "saida_parcial")
                     else None)
            # 0 também: o diário de antes desta correção gravou o price cru
            if ponta == "saida" and int(t) not in fechados:
                continue
            if ponta and not e.get("preco"):
                faltam.setdefault((int(t), ponta), e)
        corretora = {getattr(mt5, "DEAL_REASON_SL", 4),
                     getattr(mt5, "DEAL_REASON_TP", 5)}
        for (t, ponta), e in faltam.items():
            if e is None:
                continue
            negs = [n for n in foto.negocios if n.posicao == t
                    and n.entrada == (ponta == "entrada")
                    and (ponta == "entrada" or n.motivo not in corretora)]
            peso = sum(n.volume for n in negs)
            if negs and peso > 0:
                preco = sum(n.preco * n.volume for n in negs) / peso
            elif ponta == "entrada":
                p = next((p for p in foto.posicoes if p.ticket == t), None)
                if p is None or not p.preco:
                    continue
                preco = p.preco
            else:
                continue
            dia.registrar("preco_confirmado", quando=agora, ticket=t, ponta=ponta,
                          preco=float(preco), ligacao_id=e.get("ligacao_id"),
                          entry_ts=e.get("entry_ts"))

    # ---------------------------------------------------------- entrar
    def _entrar(self, mt5, a, *, agora, simbolo, desvio, pode_entrar, envio,
                conta_id, **_):
        d, lig = a.desejado, a.ligacao_id
        dia = self.diario(agora.date())
        op = {"ligacao_id": lig, "entry_ts": d.entry_ts}
        if self.so_encerrar.get(simbolo):
            ok, motivo = False, K.TEXTOS[CLOSE_ONLY]
        elif not d.contratos or d.contratos <= 0:
            # volume zero a corretora recusa ("volume inválido"): nem pede
            ok, motivo = False, "sem contratos"
        else:
            ok, motivo = pode_entrar(a)
        if not ok and motivo in PASSAGEIRAS:
            # passageira: "recusada" (desfecho que deixa tentar de novo), uma
            # vez seguida — a volta de 0,1 s não enche o diário
            ult = dia.ultimo(lig, d.entry_ts)
            if not (ult and ult["tipo"] == "recusada" and ult.get("motivo") == motivo):
                dia.registrar("recusada", quando=agora, motivo=motivo, simbolo=simbolo,
                              conta_id=conta_id, **op)
            return
        if not ok:
            if not dia.registrado(lig, d.entry_ts, "nao_entrou"):
                dia.registrar("nao_entrou", quando=agora, motivo=motivo or "entrada barrada",
                              simbolo=simbolo, conta_id=conta_id, **op)
            return
        sl, tp = K.protecao(d.lado, d.stop_px, d.alvo_px, self.tick)
        base = dict(op, lado=d.lado, contratos=d.contratos, simbolo=simbolo,
                    conta_id=conta_id, preco_papel=d.entry_px, stop_px=sl, alvo_px=tp)

        def pedido(preco, modo):
            return K.pedido_entrada(mt5, simbolo=simbolo, lado=d.lado,
                                    volume=d.contratos, preco=preco, magic_=K.magic(lig),
                                    comentario=f"df {d.entry_ts:%H:%M}", desvio=desvio,
                                    preenchimento=modo)

        if not envio:
            if not dia.registrado(lig, d.entry_ts, "seria_enviada"):
                self._ensaio(mt5, pedido, d, simbolo, dia, agora, base)
            return

        # escrita adiantada: daqui em diante a ordem pode chegar à corretora
        dia.registrar("enviando", quando=agora,
                      tentativa=dia.tentativas(lig, d.entry_ts) + 1, **base)
        def antes_do_envio(f, *args):
            # erro ANTES do order_send: nada saiu, então o desfecho é certo
            # (recusada) — sem isto a tentativa ficaria "sem desfecho" e a
            # perdida diria "automação fora do ar". Erro no próprio order_send
            # não passa por aqui: a ordem pode ter saído (incerta).
            try:
                return f(*args)
            except Exception as erro:
                dia.registrar("recusada", quando=self._depois(agora), motivo=repr(erro),
                              **op)
                raise

        info = antes_do_envio(mt5.symbol_info, simbolo)
        tk = antes_do_envio(mt5.symbol_info_tick, simbolo)
        if info is None or tk is None:
            dia.registrar("recusada", quando=self._depois(agora),
                          motivo="sem cotação do contrato", **op)
            return
        preco = tk.ask if d.lado > 0 else tk.bid
        modos = antes_do_envio(K.modos_preenchimento, info.filling_mode, mt5)
        for modo in modos:
            req = antes_do_envio(pedido, preco, modo)
            chk = antes_do_envio(mt5.order_check, req)
            if chk is None:
                dia.registrar("recusada", quando=self._depois(agora),
                              motivo="sem resposta do MT5 na checagem", **op)
                return
            if int(chk.retcode) != 0:
                classe = K.classificar(chk)
                if classe == K.PREENCHIMENTO:
                    continue
                if classe in (K.OK, K.PARCIAL, K.ACEITA, K.INCERTA):
                    classe = K.PASSAGEIRA       # nada foi enviado: só tenta de novo
                self._desfecho_entrada(mt5, classe, chk, d, lig, simbolo, desvio,
                                       agora, base, op)
                return
            res = mt5.order_send(req)
            classe = K.classificar(res)
            if classe == K.PREENCHIMENTO:
                continue                        # este modo não vale: o seguinte
            self._desfecho_entrada(mt5, classe, res, d, lig, simbolo, desvio,
                                   agora, base, op)
            return
        texto = K.TEXTOS[10030]
        self._chamar(f"entrada:{lig}:{d.entry_ts.isoformat()}", "usuario", texto, agora,
                     ligacao_id=lig, entry_ts=d.entry_ts)
        dia.registrar("perdida", quando=self._depois(agora), retcode=10030,
                      motivo=texto, **op)

    def _ensaio(self, mt5, pedido, d, simbolo, dia, agora, base):
        """Envio desligado: o pedido que iria passa pelo `order_check` — o
        mesmo request, no mesmo modo de preenchimento que o caminho real
        acabaria usando (o modo recusado com 10030 passa ao seguinte) — e
        vira "seria enviada" com o retcode e o comment da corretora. Assim o
        ensaio também confere o FORMATO da ordem, não só a decisão.

        `order_check` só confere fundos e parâmetros e devolve um
        MqlTradeCheckResult (retcode 0 = passou, como no exemplo oficial);
        nada vai à corretora — quem envia é o `order_send` (mql5.com:
        python_metatrader5/mt5ordercheck_py, trading/ordercheck). `None` =
        sem resposta: grava o `last_error()`."""
        info, tk = mt5.symbol_info(simbolo), mt5.symbol_info_tick(simbolo)
        preco = 0.0 if tk is None else (tk.ask if d.lado > 0 else tk.bid)
        modos = K.modos_preenchimento(info.filling_mode if info else 0, mt5)
        req, chk, quebrou = None, None, None
        for modo in modos:
            req = pedido(preco, modo)
            try:
                chk = mt5.order_check(req)
            except Exception as erro:
                # o ensaio nunca derruba a volta: fica registrado e não se
                # repete a cada 0,1 s
                log.exception("order_check do ensaio falhou")
                chk, quebrou = None, repr(erro)
            if chk is None or K.classificar(chk) != K.PREENCHIMENTO:
                break
        extra = {}
        if quebrou is not None:
            extra["last_error"] = [None, quebrou]
        elif chk is None:
            try:
                extra["last_error"] = list(mt5.last_error() or ())
            except Exception as erro:
                extra["last_error"] = [None, repr(erro)]
        else:
            extra["retcode"] = int(chk.retcode)
            extra["comment"] = str(getattr(chk, "comment", "") or "")
        dia.registrar("seria_enviada", quando=agora, pedido=req, **extra, **base)

    def _desfecho_entrada(self, mt5, classe, res, d, lig, simbolo, desvio, agora,
                          base, op):
        dia = self.diario(agora.date())
        quando = self._depois(agora)
        rc, texto = _retcode(res), K.texto(res)
        if classe in (K.OK, K.PARCIAL):
            ticket = self._ticket_da_posicao(mt5, res, lig, d.lado, dia, d.entry_ts)
            vol = float(res.volume) if getattr(res, "volume", 0) else float(d.contratos)
            atraso = int((quando - d.entry_ts).total_seconds() * 1000)
            dia.registrar("executada" if classe == K.OK else "parcial", quando=quando,
                          ticket=ticket, preco=_preco_res(res), atraso_ms=atraso,
                          retcode=rc, motivo=texto, **dict(base, contratos=vol))
            # o que vem depois da resposta usa a hora de depois dela: o diário
            # fica em ordem de tempo (e a proteção pendente conta daqui)
            if classe == K.PARCIAL:
                # D3: resto de ordem nunca fica vivo
                self._cancelar_resto(mt5, lig, quando)
                quando = self._depois(quando)
            if ticket is None:
                # sem o ticket não há SLTP possível: planejar adota a posição
                # na próxima volta e a proteção sai por lá
                log.warning("entrada da ligação %s executou sem ticket conhecido", lig)
                return
            self._proteger_ticket(mt5, lig, ticket, simbolo, d.lado, base["stop_px"],
                                  base["alvo_px"], vol, quando, desvio)
        elif classe == K.ACEITA:
            # PLACED: nunca reenvia; planejar espera a posição ou a janela
            dia.registrar("aceita", quando=quando, ordem=int(res.order or 0),
                          retcode=rc, motivo=texto, **op)
        elif classe == K.INCERTA:
            dia.registrar("incerta", quando=quando, retcode=rc, motivo=texto, **op)
        elif classe == K.PASSAGEIRA:
            dia.registrar("recusada", quando=quando, retcode=rc, motivo=texto, **op)
        elif classe == K.STOPS_INVALIDOS:
            dia.registrar("nao_entrou", quando=quando, retcode=rc,
                          motivo="stop ou alvo inválido", **op)
        else:
            # configuração (sem margem, Algo desligado...) ou desconhecido:
            # a entrada não volta a ser tentada; chama o usuário ANTES da
            # perdida (o último evento da operação é a perdida)
            if rc == CLOSE_ONLY:
                self.so_encerrar[simbolo] = True
            self._chamar(f"entrada:{lig}:{d.entry_ts.isoformat()}", "usuario", texto,
                         agora, ligacao_id=lig, entry_ts=d.entry_ts)
            dia.registrar("perdida", quando=quando, retcode=rc, motivo=texto, **op)

    def _ticket_da_posicao(self, mt5, res, lig, lado, dia, entry_ts) -> int | None:
        """Em hedging o identificador da posição é o ticket da ordem que a
        abriu: com `order` na resposta, é ele (a lista de posições pode ainda
        não ter a nova). Sem ele, a posição mais nova da ligação do mesmo lado
        que o diário ainda não conhece — nunca o ticket de uma operação
        anterior (caso 9: a antiga ainda saindo) nem uma aberta antes desta
        operação (posição herdada). Nada → None."""
        ordem = int(res.order or 0)
        if ordem:
            return ordem
        conhecidos = {int(e["ticket"]) for e in dia.eventos
                      if e.get("ligacao_id") == lig and e.get("ticket")
                      and e["tipo"] in ("executada", "parcial", "adotada")}
        lado_mt5 = mt5.POSITION_TYPE_BUY if lado > 0 else mt5.POSITION_TYPE_SELL
        minhas = [p for p in mt5.positions_get() or ()
                  if int(p.magic) == K.magic(lig) and int(p.type) == lado_mt5
                  and int(p.ticket) not in conhecidos
                  and K._hora(p.time) >= entry_ts]
        if minhas:
            return int(max(minhas, key=lambda p: (int(p.time), int(p.ticket))).ticket)
        return None

    # -------------------------------------------------------- cancelar
    def _cancelar_resto(self, mt5, lig, agora):
        ordens = mt5.orders_get()
        # None = leitura falhou: planejar cancela na volta seguinte (> 5 s)
        for o in ordens or ():
            if int(o.magic) == K.magic(lig):
                self._cancelar_ticket(mt5, lig, int(o.ticket), "resto da parcial", agora)

    def _cancelar(self, mt5, a, *, agora, **_):
        self._cancelar_ticket(mt5, a.ligacao_id, a.ticket, a.motivo, agora)

    def _cancelar_ticket(self, mt5, lig, ticket, motivo, agora):
        if not self._pode_enviar("cancelar", ticket):
            return
        dia = self.diario(agora.date())
        dia.registrar("cancelar_enviando", quando=agora, ligacao_id=lig, ticket=ticket,
                      motivo=motivo)
        self._marcar("cancelar", ticket)
        res = mt5.order_send(K.pedido_cancelar(mt5, ordem=ticket))
        if K.classificar(res) == K.OK:
            dia.registrar("cancelada", quando=self._depois(agora), ligacao_id=lig,
                          ticket=ticket, retcode=_retcode(res), motivo=motivo)
        else:
            # a próxima volta relê orders_get: se a ordem ainda vive, tenta de novo
            dia.registrar("cancelar_recusada", quando=self._depois(agora), ligacao_id=lig,
                          ticket=ticket, retcode=_retcode(res), motivo=K.texto(res))

    # -------------------------------------------------------- proteger
    def _proteger(self, mt5, a, *, agora, desvio, **_):
        p, d = a.posicao, a.desejado
        sl, tp = K.protecao(d.lado, d.stop_px, d.alvo_px, self.tick)
        self._proteger_ticket(mt5, a.ligacao_id, a.ticket, p.simbolo, d.lado, sl, tp,
                              p.volume, agora, desvio)

    def _proteger_ticket(self, mt5, lig, ticket, simbolo, lado, sl, tp, contratos,
                         agora, desvio):
        if sl is None:
            # nunca manda SL/TP sem stop (zeraria o stop da corretora)
            self._chamar(f"sem_stop:{ticket}", "sem_stop", "posição sem stop no papel",
                         agora, ligacao_id=lig, ticket=ticket)
            return
        if not self._pode_enviar("proteger", ticket):
            return
        dia = self.diario(agora.date())
        campos = dict(ligacao_id=lig, ticket=ticket, simbolo=simbolo, lado=lado,
                      stop_px=sl, alvo_px=tp, contratos=contratos)
        dia.registrar("protecao_enviando", quando=agora, **campos)
        self._marcar("proteger", ticket)
        res = mt5.order_send(K.pedido_protecao(mt5, simbolo=simbolo, ticket=ticket,
                                               sl=sl, tp=tp, magic_=K.magic(lig)))
        classe, quando = K.classificar(res), self._depois(agora)
        if classe in (K.OK, K.SEM_MUDANCA):
            dia.registrar("protecao", quando=quando, retcode=_retcode(res), **campos)
        elif classe == K.JA_SAIU:
            return            # saiu (SL/TP do servidor): planejar registra o saiu_antes
        else:
            dia.registrar("protecao_recusada", quando=quando, retcode=_retcode(res),
                          motivo=K.texto(res), **campos)
            if classe == K.STOPS_INVALIDOS:
                # o preço já passou do stop: posição sem stop não pode existir
                self._sair_ticket(mt5, lig, ticket, simbolo, lado, contratos,
                                  "preço além do stop", quando, desvio)

    # ------------------------------------------------------------ sair
    def _sair(self, mt5, a, *, agora, desvio, **_):
        p = a.posicao
        # o contrato da POSIÇÃO, não o do dia (a de ontem pode ser outro)
        return self._sair_ticket(mt5, a.ligacao_id, a.ticket, p.simbolo, p.lado, p.volume,
                                 a.motivo, agora, desvio)

    def _sair_ticket(self, mt5, lig, ticket, simbolo, lado, volume, motivo, agora,
                     desvio):
        """Devolve a classe da resposta quando a posição deixou a conta (OK,
        ou já encerrada); `None` quando ela pode seguir aberta."""
        if not self._pode_enviar("sair", ticket):
            return
        dia = self.diario(agora.date())
        campos = dict(ligacao_id=lig, ticket=ticket, simbolo=simbolo, lado=lado,
                      contratos=volume)
        tentativa = 1 + sum(1 for e in dia.eventos
                            if e["tipo"] == "saida_enviando" and e.get("ticket") == ticket)
        dia.registrar("saida_enviando", quando=agora, tentativa=tentativa, motivo=motivo,
                      **campos)
        self._marcar("sair", ticket)
        info, tk = mt5.symbol_info(simbolo), mt5.symbol_info_tick(simbolo)
        res, classe = None, None
        if info is None or tk is None:
            quando = self._depois(agora)
            dia.registrar("saida_recusada", quando=quando,
                          motivo="sem cotação do contrato", **campos)
        else:
            preco = tk.bid if lado > 0 else tk.ask
            for modo in K.modos_preenchimento(info.filling_mode, mt5):
                res = mt5.order_send(K.pedido_saida(
                    mt5, simbolo=simbolo, lado_posicao=lado, volume=volume, preco=preco,
                    ticket=ticket, magic_=K.magic(lig), desvio=desvio,
                    preenchimento=modo))
                classe = K.classificar(res)
                if classe != K.PREENCHIMENTO:
                    break
            quando, rc = self._depois(agora), _retcode(res)
            # contratos = o que a corretora executou, não o pedido
            feito = dict(campos, contratos=float(getattr(res, "volume", 0) or 0)) \
                if res is not None else campos
            if classe == K.OK:
                dia.registrar("saida_executada", quando=quando, preco=_preco_res(res),
                              retcode=rc, motivo=motivo, **feito)
            elif classe == K.PARCIAL:
                # a posição segue viva com o resto: a saída continua pendente
                dia.registrar("saida_parcial", quando=quando, preco=_preco_res(res),
                              retcode=rc, motivo=motivo, **feito)
            elif classe == K.JA_SAIU:
                # NÃO é saida_executada: esconderia a saída real do servidor
                # (preço, motivo, volume). planejar registra o saiu_antes com o
                # negócio de saída quando ele aparecer.
                dia.registrar("saida_recusada", quando=quando, retcode=rc,
                              motivo="já encerrada na corretora", **feito)
                return classe
            elif classe in (K.SAIDA_EM_TRANSITO, K.VOLUME_FECHAMENTO):
                pass          # a próxima volta relê a posição e as ordens
            elif classe == K.INCERTA:
                # a próxima volta relê a corretora antes de mandar de novo
                dia.registrar("saida_recusada", quando=quando, retcode=rc,
                              motivo="sem resposta", **feito)
            else:
                dia.registrar("saida_recusada", quando=quando, retcode=rc,
                              motivo=K.texto(res), **feito)
                if classe in (K.USUARIO, K.DESCONHECIDO, K.PREENCHIMENTO):
                    self._chamar(f"saida_erro:{ticket}", "usuario",
                                 f"saída recusada: {K.texto(res)}", quando,
                                 ligacao_id=lig, ticket=ticket)
        # chamados com a hora de depois da resposta: o diário fica em ordem
        if classe == K.OK:
            self._fechar(f"saida_pendente:{ticket}", quando)
            self._fechar(f"saida_erro:{ticket}", quando)
            return classe
        # nunca desiste: passou de 2 min chama, e a próxima volta tenta de novo
        desde = dia.saida_desde(ticket)
        if desde is not None and _seg(quando, desde) > PENDENTE_CHAMA_S:
            self._chamar(f"saida_pendente:{ticket}", "saida_pendente",
                         f"saída pendente há mais de 2 min (tentativa {tentativa})",
                         quando, ligacao_id=lig, ticket=ticket)

    # ------------------------------------------------------- registros
    def _adotar(self, mt5, a, *, agora, conta_id, **_):
        d, p = a.desejado, a.posicao
        sl, tp = K.protecao(d.lado, d.stop_px, d.alvo_px, self.tick)
        self.diario(agora.date()).registrar(
            "adotada", quando=agora, ligacao_id=a.ligacao_id, entry_ts=d.entry_ts,
            ticket=a.ticket, lado=d.lado, stop_px=sl, alvo_px=tp, contratos=p.volume,
            preco=p.preco, preco_papel=d.entry_px, simbolo=p.simbolo, conta_id=conta_id,
            motivo="executou sem a resposta chegar")

    def _saiu_antes(self, mt5, a, *, foto, agora, **_):
        n = next((n for n in reversed(foto.negocios if foto else [])
                  if not n.entrada and n.posicao == a.ticket), None)
        motivos = {getattr(mt5, "DEAL_REASON_SL", 4): "stop na corretora",
                   getattr(mt5, "DEAL_REASON_TP", 5): "alvo na corretora"}
        motivo = motivos.get(n.motivo if n else None, "encerrada fora da automação")
        ts = a.desejado.entry_ts if a.desejado else None
        # contratos = o que saiu pelo servidor (o resto, depois de uma parcial)
        extra = {"preco": n.preco, "contratos": n.volume} if n else {}
        if n and motivo in ("stop na corretora", "alvo na corretora"):
            # a corretora "executou" o stop/alvo sem negócio nesse preço?
            try:
                no_preco = K.negociou_no_preco(
                    mt5, n.simbolo, n.preco, n.lado, n.quando,
                    alvo=n.motivo == getattr(mt5, "DEAL_REASON_TP", 5))
            except Exception:
                no_preco = None
            if no_preco is False:
                extra["fora_do_mercado"] = True
                motivo += " (fora do mercado)"
        self.diario(agora.date()).registrar(
            "saiu_antes", quando=agora, ligacao_id=a.ligacao_id, entry_ts=ts,
            ticket=a.ticket, motivo=motivo, **extra)
        self._fechar_da_operacao(a.ligacao_id, ts, agora)

    def _perdida(self, mt5, a, *, agora, **_):
        ts = a.desejado.entry_ts if a.desejado else None
        self.diario(agora.date()).registrar(
            "perdida", quando=agora, ligacao_id=a.ligacao_id, entry_ts=ts,
            motivo=a.motivo)
        self._fechar_da_operacao(a.ligacao_id, ts, agora)
        if a.motivo == SEM_CONFIRMACAO:
            # sem entry_ts no chamado de propósito: não cai com a operação
            # (a posição pode existir); fecha à mão ou na virada do dia
            self._chamar(f"sem_confirmacao:{a.ligacao_id}:{ts.isoformat()}", "usuario",
                         a.motivo, agora, ligacao_id=a.ligacao_id)

    def _chamado_do_plano(self, mt5, a, *, agora, **_):
        # planejar repete o "chamar" a cada volta: a chave deduplica
        # mesma chave do "sem stop" do _proteger_ticket: um chamado só por posição
        if a.ticket is not None:
            chave, tipo = f"sem_stop:{a.ticket}", "sem_stop"
        else:
            chave, tipo = f"plano:{a.ligacao_id}:{a.motivo}", "plano"
        self._chamar(chave, tipo, a.motivo, agora, ligacao_id=a.ligacao_id,
                     ticket=a.ticket)
