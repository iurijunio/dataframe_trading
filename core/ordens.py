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

from . import corretora as K
from .diario_ordens import Diario
from .papel_vivo import INDISPONIVEL, POSICAO, ZERADO, Desejado

JANELA_ENTRADA_S = 30
GRACA_RECONEXAO_S = 5
INTERVALO_S = 1.0          # entre tentativas da mesma ação (evita o 10024)
INCERTA_ESPERA_S = 3.0     # sem resposta: espera o histórico antes de reenviar
SEM_PROTECAO_S = 2.0       # posição sem SL/TP além disso é encerrada
ORDEM_VELHA_S = 5.0        # ordem pendente com o magic além disso é cancelada
PENDENTE_CHAMA_S = 120     # saída pendente além disso chama o usuário (e segue)
CLOSE_ONLY = 10044         # só encerramento: sem entradas no contrato no resto do dia

log = logging.getLogger(__name__)


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
            # ordem no histórico ou "aceita": não houve execução); logo após
            # reconectar a lista pode vir vazia: espera estabilizar
            if not estavel:
                continue
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


# ======================================================================
# Motor: executa as ações de `planejar` no MT5, com o diário adiantado.
# ======================================================================
# saídas antes de tudo (uma posição a mais é risco; uma entrada a menos não);
# o cancelamento de resto vem antes da saída para o resto não abrir mais
# volume enquanto se sai; a adoção grava o ticket antes da proteção dele
_ORDEM_ACOES = {"cancelar": 0, "sair": 1, "adotar": 2, "proteger": 3,
                "saiu_antes": 4, "perdida": 4, "chamar": 4, "entrar": 5}
_METODO = {"chamar": "_chamado_do_plano"}     # `_chamar` é quem abre o chamado


def _retcode(res) -> int | None:
    return None if res is None else int(res.retcode)


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

    # ---------------------------------------------------------- diário
    def diario(self, dia) -> Diario:
        if self._diario is None or self._diario.dia != dia:
            self._diario = Diario(self.pasta, dia, self.origem)
            # "só encerramento" vale para o resto do DIA
            self.so_encerrar = {}
            self._envios = {}
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

    def _fechar_resolvidos(self, foto, agora):
        """Chamado de posição fecha quando a posição sumiu da corretora; o de
        posição sem stop, também quando o stop apareceu."""
        if foto is None:
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

    # -------------------------------------------------------- executar
    def executar(self, mt5, acoes, *, foto, agora_srv, simbolo, desvio,
                 pode_entrar, envio, conta_id) -> None:
        agora = self._quando(agora_srv)
        self._sem_relogio = agora_srv is None
        self.diario(agora.date())
        self._fechar_resolvidos(foto, agora)
        ctx = dict(foto=foto, agora=agora, simbolo=simbolo, desvio=desvio,
                   pode_entrar=pode_entrar, envio=envio, conta_id=conta_id)
        erros = []
        for a in sorted(acoes, key=lambda a: _ORDEM_ACOES[a.tipo]):
            # uma ação que estoura não pode impedir as outras (a saída de uma
            # ligação não espera a entrada da outra); o erro sobe no fim
            try:
                getattr(self, _METODO.get(a.tipo, f"_{a.tipo}"))(mt5, a, **ctx)
            except Exception as erro:
                log.exception("ação %s da ligação %s falhou", a.tipo, a.ligacao_id)
                erros.append(erro)
        if erros:
            raise erros[0]

    # ---------------------------------------------------------- entrar
    def _entrar(self, mt5, a, *, agora, simbolo, desvio, pode_entrar, envio,
                conta_id, **_):
        d, lig = a.desejado, a.ligacao_id
        dia = self.diario(agora.date())
        op = {"ligacao_id": lig, "entry_ts": d.entry_ts}
        if self.so_encerrar.get(simbolo):
            ok, motivo = False, K.TEXTOS[CLOSE_ONLY]
        else:
            ok, motivo = pode_entrar(a)
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
                info, tk = mt5.symbol_info(simbolo), mt5.symbol_info_tick(simbolo)
                modo = K.modos_preenchimento(info.filling_mode if info else 0, mt5)[0]
                preco = 0.0 if tk is None else (tk.ask if d.lado > 0 else tk.bid)
                dia.registrar("seria_enviada", quando=agora, pedido=pedido(preco, modo),
                              **base)
            return

        # escrita adiantada: daqui em diante a ordem pode chegar à corretora
        dia.registrar("enviando", quando=agora,
                      tentativa=dia.tentativas(lig, d.entry_ts) + 1, **base)
        info, tk = mt5.symbol_info(simbolo), mt5.symbol_info_tick(simbolo)
        if info is None or tk is None:
            dia.registrar("recusada", quando=self._depois(agora),
                          motivo="sem cotação do contrato", **op)
            return
        preco = tk.ask if d.lado > 0 else tk.bid
        for modo in K.modos_preenchimento(info.filling_mode, mt5):
            req = pedido(preco, modo)
            chk = mt5.order_check(req)
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

    def _desfecho_entrada(self, mt5, classe, res, d, lig, simbolo, desvio, agora,
                          base, op):
        dia = self.diario(agora.date())
        quando = self._depois(agora)
        rc, texto = _retcode(res), K.texto(res)
        if classe in (K.OK, K.PARCIAL):
            ticket = self._ticket_da_posicao(mt5, res, lig, d.lado)
            vol = float(res.volume) if getattr(res, "volume", 0) else float(d.contratos)
            atraso = int((quando - d.entry_ts).total_seconds() * 1000)
            dia.registrar("executada" if classe == K.OK else "parcial", quando=quando,
                          ticket=ticket, preco=float(res.price), atraso_ms=atraso,
                          retcode=rc, motivo=texto, **dict(base, contratos=vol))
            if classe == K.PARCIAL:
                # D3: resto de ordem nunca fica vivo
                self._cancelar_resto(mt5, lig, agora)
            self._proteger_ticket(mt5, lig, ticket, simbolo, d.lado, base["stop_px"],
                                  base["alvo_px"], vol, agora, desvio)
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

    def _ticket_da_posicao(self, mt5, res, lig, lado) -> int:
        """Em hedging o ticket da posição é o da ordem que a abriu; se a lista
        não confirmar, a posição mais nova da ligação do mesmo lado."""
        ordem = int(res.order or 0)
        if ordem:
            lista = mt5.positions_get(ticket=ordem)
            if any(int(p.ticket) == ordem for p in lista or ()):
                return ordem
        lado_mt5 = mt5.POSITION_TYPE_BUY if lado > 0 else mt5.POSITION_TYPE_SELL
        minhas = [p for p in mt5.positions_get() or ()
                  if int(p.magic) == K.magic(lig) and int(p.type) == lado_mt5]
        if minhas:
            return int(max(minhas, key=lambda p: (int(p.time), int(p.ticket))).ticket)
        return ordem

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
                                  "preço além do stop", agora, desvio)

    # ------------------------------------------------------------ sair
    def _sair(self, mt5, a, *, agora, desvio, **_):
        p = a.posicao
        # o contrato da POSIÇÃO, não o do dia (a de ontem pode ser outro)
        self._sair_ticket(mt5, a.ligacao_id, a.ticket, p.simbolo, p.lado, p.volume,
                          a.motivo, agora, desvio)

    def _sair_ticket(self, mt5, lig, ticket, simbolo, lado, volume, motivo, agora,
                     desvio):
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
            dia.registrar("saida_recusada", quando=self._depois(agora),
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
            if classe in (K.OK, K.PARCIAL):
                dia.registrar("saida_executada", quando=quando, preco=float(res.price),
                              retcode=rc, motivo=motivo, **campos)
            elif classe == K.JA_SAIU:
                dia.registrar("saida_executada", quando=quando, retcode=rc,
                              motivo="já encerrada", **campos)
            elif classe in (K.SAIDA_EM_TRANSITO, K.VOLUME_FECHAMENTO):
                pass          # a próxima volta relê a posição e as ordens
            elif classe == K.INCERTA:
                # a próxima volta relê a corretora antes de mandar de novo
                dia.registrar("saida_recusada", quando=quando, retcode=rc,
                              motivo="sem resposta", **campos)
            else:
                dia.registrar("saida_recusada", quando=quando, retcode=rc,
                              motivo=K.texto(res), **campos)
                if classe in (K.USUARIO, K.DESCONHECIDO, K.PREENCHIMENTO):
                    self._chamar(f"saida_erro:{ticket}", "usuario",
                                 f"saída recusada: {K.texto(res)}", agora,
                                 ligacao_id=lig, ticket=ticket)
        if classe in (K.OK, K.PARCIAL, K.JA_SAIU):
            self._fechar(f"saida_pendente:{ticket}", agora)
            self._fechar(f"saida_erro:{ticket}", agora)
            return
        # nunca desiste: passou de 2 min chama, e a próxima volta tenta de novo
        desde = dia.saida_desde(ticket)
        if desde is not None and _seg(agora, desde) > PENDENTE_CHAMA_S:
            self._chamar(f"saida_pendente:{ticket}", "saida_pendente",
                         f"saída pendente há mais de 2 min (tentativa {tentativa})",
                         agora, ligacao_id=lig, ticket=ticket)

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
        extra = {"preco": n.preco} if n else {}
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

    def _chamado_do_plano(self, mt5, a, *, agora, **_):
        # planejar repete o "chamar" a cada volta: a chave deduplica
        tipo = "sem_stop" if a.ticket is not None else "plano"
        alvo = a.ticket if a.ticket is not None else a.ligacao_id
        self._chamar(f"{tipo}:{alvo}:{a.motivo}", tipo, a.motivo, agora,
                     ligacao_id=a.ligacao_id, ticket=a.ticket)
