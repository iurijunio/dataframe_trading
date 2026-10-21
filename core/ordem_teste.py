"""A "Ordem de teste": prova o caminho real de ordem na conta do processo
(demo ou real).

Brief: .superpowers/sdd/2026-10-09-ao-vivo-ordens/ordem-teste-brief.md.
Com o Envio desligado o ensaio só passa o pedido pelo `order_check`; aqui
uma ordem de verdade percorre entrada, proteção, conferência e saída, com
os MESMOS construtores de pedido, fallback de preenchimento e tabela de
retornos de `core/corretora.py`.

Quem executa é a captura (o `Motor`), a partir do comando-arquivo escrito
pelo clique. Três regras que este arquivo não pode esquecer:
- a sequência anda UMA etapa por volta, depois das ações das estratégias, e
  nunca com `sleep`: a espera de 10 s é contada pelo relógio monotônico e a
  volta segue livre para as ordens das ligações;
- o magic é `MAGIC_TESTE`, fora da faixa das ligações: nada da automação
  toca a posição — só esta sequência a encerra;
- posição de teste não pode sobrar: falha no meio (ou uma que sobrou de
  antes de reiniciar) é encerrada a cada 1 s, e recusada por mais de 10 s
  abre o chamado `teste_preso`.
"""
from __future__ import annotations

import logging
from datetime import datetime

from . import corretora as K

log = logging.getLogger(__name__)

MAGIC = K.MAGIC_TESTE
COMENTARIO = "df teste"
CONTRATOS = 1
DISTANCIA = 100            # pontos do SL e do TP até a entrada real
ESPERA_S = 10.0            # a posição protegida fica aberta isto (etapa 4)
LISTA_S = 5.0              # a lista de posições pode atrasar até isto
PRESO_S = 10.0             # saída recusada além disto chama o usuário
INTERVALO_S = 1.0          # entre saídas, como nas da automação (10024)
PEDIDO_VALE_S = 60.0       # clique mais velho que isto não roda
REPETIR_S = 5.0            # retorno passageiro na proteção/saída: tenta até isto
# retornos que não são falha da etapa: a mesma ordem vale de novo em 1 s
# (a tabela única de corretora.py diz quais; INCERTA: confere antes)
_DE_NOVO = (K.PASSAGEIRA, K.INCERTA)
CHAMADO = "teste_preso"
TEXTO_PRESO = "posição de teste não fecha — encerre no MT5"

ETAPAS = {1: "compra a mercado", 2: "stop e alvo", 3: "conferência do stop e do alvo",
          4: "espera de 10 s", 5: "saída"}


def _ms(segundos: float) -> int:
    return int(round(segundos * 1000))


def texto_ok(ms: dict) -> str:
    return (f"Teste ok — entrada {ms.get('entrada')} ms, proteção "
            f"{ms.get('protecao')} ms, saída {ms.get('saida')} ms")


def texto_falhou(etapa: int, motivo: str) -> str:
    if not etapa:
        return f"Teste recusado: {motivo}"
    return f"Teste falhou na etapa {etapa}: {motivo}"


class OrdemTeste:
    """O estado da sequência, em memória: um reinício perde o teste em
    andamento, mas a posição dele (magic `MAGIC_TESTE`) é achada na foto e
    encerrada — a corretora é a fonte, não esta memória."""

    def __init__(self, motor, agora_pc=datetime.now):
        self.m = motor
        # a conta do processo (demo ou real): a mesma do Motor que a executa
        self.origem = motor.origem
        # relógio do PC: o mesmo que carimbou o `criado_em` do comando
        self.agora_pc = agora_pc
        self.atual: dict | None = None
        self.ultimo: dict | None = None
        self._no_pregao = True
        # os últimos pedidos já tratados (começou ou recusado): a tela sabe
        # que o clique dela chegou à captura mesmo quando o texto mostrado é
        # o do teste que segue em andamento
        self.vistos: list = []

    # ------------------------------------------------------------ tela
    def estado(self) -> dict | None:
        """O que a tela mostra ao lado do botão (só textos e números)."""
        if self.ultimo is None and not self.vistos:
            return None
        return dict(self.ultimo or {}, pedidos=list(self.vistos))

    def _visto(self, c):
        if c.get("id") is not None:
            self.vistos = (self.vistos + [c["id"]])[-10:]

    def _publicar(self, situacao, etapa, texto, agora, teste_id):
        self.ultimo = {"id": teste_id, "situacao": situacao, "etapa": etapa,
                       "texto": texto, "quando": agora}

    # -------------------------------------------------------- recusar
    def recusar(self, pedidos, dia, agora, motivo) -> None:
        """Pedido que não pode rodar: evento no diário e texto na tela."""
        for c in pedidos:
            dia.registrar("teste_falhou", quando=agora, etapa=0, motivo=motivo,
                          teste_id=c.get("id"), conta_id=c.get("conta_id"))
            self._visto(c)
            # com um teste em andamento a tela segue mostrando ele; a recusa
            # do clique repetido fica no diário
            if self.atual is None:
                self._publicar("recusado", 0, texto_falhou(0, motivo), agora,
                               c.get("id"))

    def _idade_s(self, c) -> float | None:
        try:
            return (self.agora_pc() - datetime.fromisoformat(str(c["criado_em"]))
                    ).total_seconds()
        except (KeyError, TypeError, ValueError):
            return None

    def _pre_condicao(self, mt5, c, *, foto, cid, conta, no_pregao, simbolo,
                      contrato_ok, travada, zerar) -> str | None:
        """Por que o teste não pode começar agora (None = pode). O Envio
        não entra: o teste é pedido explícito e independe dele."""
        idade = self._idade_s(c)
        if idade is None or idade > PEDIDO_VALE_S:
            return "pedido antigo (mais de 60 s) — clique de novo"
        if self.atual is not None:
            return "já há um teste em andamento"
        if c.get("conta_id") is None or int(c["conta_id"]) != cid:
            return f"o MT5 não está logado na conta {self._nome()} deste pedido"
        if (conta or {}).get("tipo") != self.origem:
            return f"a conta logada não está cadastrada como {self._nome()}"
        # ACCOUNT_TRADE_MODE_DEMO / _REAL (mql5.com: constants/environment_state/
        # accountinformation; account_info() traz trade_mode — python_metatrader5/
        # mt5accountinfo_py). Lido agora, não da foto: é a última barreira
        # antes de uma ordem de verdade
        info = mt5.account_info()
        if info is None:
            return "dados da conta ilegíveis"
        if not self._conta_do_processo(mt5, info):
            return f"a conta do MT5 não é {self._nome().upper()}"
        if not no_pregao:
            return "fora do pregão"
        if not foto.algo_ligado:
            return "Algo Trading desligado no MT5"
        if travada:
            return "conta travada pelo limite de perda do dia"
        if not simbolo:
            return "contrato do dia ainda não escolhido"
        if not contrato_ok:
            return "preço do contrato não confere com o WIN$N (guarda de preço)"
        if zerar:
            return "Zerar tudo em andamento"
        if foto.parcial:
            return "leitura parcial da corretora"
        if any(p.magic == MAGIC for p in foto.posicoes):
            return "ainda há posição de teste aberta"
        if any(o.get("magic") == MAGIC for o in foto.ordens):
            return "ainda há ordem de teste pendente"
        return None

    # ------------------------------------------------------------ volta
    def volta(self, mt5, *, foto, dia, agora, pedidos, cid, conta, no_pregao,
              simbolo, contrato_ok, travada, zerar) -> None:
        """Uma etapa por chamada. Pedido novo começa pela compra (etapa 1)
        nesta mesma volta — as ações das estratégias já foram."""
        self._no_pregao = no_pregao
        for c in pedidos:
            motivo = self._pre_condicao(mt5, c, foto=foto, cid=cid, conta=conta,
                                        no_pregao=no_pregao, simbolo=simbolo,
                                        contrato_ok=contrato_ok, travada=travada,
                                        zerar=zerar)
            if motivo is not None:
                self.recusar([c], dia, agora, motivo)
                continue
            self._visto(c)
            self.atual = {"id": c.get("id"), "conta_id": cid, "fase": "entrada",
                          "simbolo": simbolo, "ms": {}, "desde": self.m.mono()}
            dia.registrar("teste", quando=agora, etapa=0, motivo="teste iniciado",
                          teste_id=c.get("id"), conta_id=cid, simbolo=simbolo)
            self._publicar("andamento", 1, "Teste em andamento — etapa 1: "
                           + ETAPAS[1], agora, c.get("id"))
        if self.atual is None:
            self._sobra(mt5, foto, dia, agora)
            if self.atual is None:
                return
        t = self.atual
        if zerar and t["fase"] in ("protecao", "confere", "espera", "aguarda"):
            self._falhou(dia, agora, ETAPA_DA_FASE[t["fase"]], "Zerar tudo pedido na tela")
        fase = self.atual["fase"]
        getattr(self, f"_{fase}")(mt5, foto, dia, agora)

    def erro(self, dia, agora, erro) -> None:
        """Exceção no meio da sequência: falha na etapa em que estava, e a
        posição que houver segue para o encerramento (o encerramento que
        estoura tenta de novo na volta seguinte)."""
        t = self.atual
        if t is None or t["fase"] == "encerrando":
            return
        self._falhou(dia, agora, ETAPA_DA_FASE.get(t["fase"], 0) or 1, repr(erro))

    # ----------------------------------------------------- auxiliares
    def _ev(self, dia, agora, etapa, **campos):
        t = self.atual
        dia.registrar("teste", quando=agora, etapa=etapa, teste_id=t["id"],
                      conta_id=t.get("conta_id"), simbolo=t.get("simbolo"),
                      ticket=t.get("ticket"), **campos)
        if etapa < 5:
            self._publicar("andamento", etapa + 1, f"Teste em andamento — etapa "
                           f"{etapa + 1}: {ETAPAS[etapa + 1]}", agora, t["id"])

    def _falhou(self, dia, agora, etapa, motivo, res=None, min_s=LISTA_S):
        """Desfecho de falha; a posição que houver é encerrada a seguir.
        `min_s`: o encerramento só se dá por limpo depois disto sem nada
        com o magic (entrada sem resposta: a posição pode aparecer depois —
        um clique novo antes abriria uma segunda)."""
        t = self.atual
        extra = {}
        if res is not None:
            extra = {"retcode": int(res.retcode),
                     "comment": str(getattr(res, "comment", "") or "")}
        dia.registrar("teste_falhou", quando=agora, etapa=etapa, motivo=motivo,
                      teste_id=t["id"], conta_id=t.get("conta_id"),
                      ticket=t.get("ticket"), **extra)
        self._publicar("falhou", etapa, texto_falhou(etapa, motivo), agora, t["id"])
        self.atual = {"id": t["id"], "conta_id": t.get("conta_id"),
                      "simbolo": t.get("simbolo"), "fase": "encerrando",
                      "desde": self.m.mono(), "ultimo_envio": None,
                      "recusa_desde": None, "min_s": min_s}

    def _da_foto(self, foto):
        tk = self.atual.get("ticket")
        return next((p for p in foto.posicoes if p.ticket == tk), None)

    def _passou(self, segundos) -> bool:
        return self.m.mono() - self.atual["desde"] > segundos

    def _de_novo(self, chave) -> str:
        """Depois de um retorno passageiro: "agora" (tenta de novo), "espera"
        (menos de 1 s da última) ou "desiste" (passou de REPETIR_S)."""
        t, m = self.atual, self.m.mono()
        if m - t[chave + "_desde"] > REPETIR_S:
            return "desiste"
        if m - t[chave + "_ult"] < INTERVALO_S:
            return "espera"
        return "agora"

    def _nome(self) -> str:
        return "real" if self.origem == "real" else "demo"

    def _conta_do_processo(self, mt5, info) -> bool:
        """`info` é a conta do MT5 agora: o trade_mode tem de ser o da conta do
        processo (REAL no processo da real, DEMO no da demo)."""
        esperado = (mt5.ACCOUNT_TRADE_MODE_REAL if self.origem == "real"
                    else mt5.ACCOUNT_TRADE_MODE_DEMO)
        return int(getattr(info, "trade_mode", -1)) == int(esperado)

    def _na_conta_do_processo(self, mt5) -> bool:
        """A conta do MT5 é a do processo agora? Só nela a sequência encerra
        uma posição com o magic do teste (numa conta de outro tipo o mesmo
        número pode ser de outra coisa)."""
        try:
            info = mt5.account_info()
        except Exception:
            return False
        return info is not None and self._conta_do_processo(mt5, info)

    def _enviar_com_preenchimento(self, mt5, montar, info):
        """O fallback de preenchimento do caminho real: modo recusado com
        10030 passa ao seguinte. Devolve (resposta, classe, ms do envio)."""
        res, classe, ms = None, None, None
        for modo in K.modos_preenchimento(info.filling_mode, mt5):
            req = montar(modo)
            t0 = self.m.mono()
            res = mt5.order_send(req)
            ms = _ms(self.m.mono() - t0)
            classe = K.classificar(res)
            if classe != K.PREENCHIMENTO:
                break
        return res, classe, ms

    # ------------------------------------------------- etapa 1: compra
    def _entrada(self, mt5, foto, dia, agora):
        t = self.atual
        simbolo = t["simbolo"]
        info, tk = mt5.symbol_info(simbolo), mt5.symbol_info_tick(simbolo)
        if info is None or tk is None:
            return self._falhou(dia, agora, 1, "sem cotação do contrato")
        preco = float(tk.ask)

        def montar(modo):
            return K.pedido_entrada(mt5, simbolo=simbolo, lado=1, volume=CONTRATOS,
                                    preco=preco, magic_=MAGIC, comentario=COMENTARIO,
                                    desvio=2 * self.m.tick, preenchimento=modo)
        # como a entrada real: o order_check antes, e o modo que ele recusa
        # por preenchimento passa ao seguinte
        modos = K.modos_preenchimento(info.filling_mode, mt5)
        res, classe, ms = None, K.PREENCHIMENTO, None
        for modo in modos:
            req = montar(modo)
            chk = mt5.order_check(req)
            if chk is None:
                return self._falhou(dia, agora, 1, "sem resposta do MT5 na checagem")
            if int(chk.retcode) != 0:
                if K.classificar(chk) == K.PREENCHIMENTO:
                    continue
                return self._falhou(dia, agora, 1, K.texto(chk), chk)
            t0 = self.m.mono()
            res = mt5.order_send(req)
            ms = _ms(self.m.mono() - t0)
            classe = K.classificar(res)
            if classe != K.PREENCHIMENTO:
                break
        if classe == K.PREENCHIMENTO:
            return self._falhou(dia, agora, 1, K.TEXTOS[10030], res)
        t["ms"]["entrada"] = ms
        if classe in (K.OK, K.PARCIAL):
            ordem = int(getattr(res, "order", 0) or 0)
            t["ticket"] = ordem or None
            t["preco"] = float(getattr(res, "price", 0) or 0) or None
            self._ev(dia, agora, 1, retcode=int(res.retcode),
                     comment=str(getattr(res, "comment", "") or ""),
                     preco=t["preco"], atraso_ms=ms, motivo=K.texto(res))
            t["fase"], t["desde"] = "protecao", self.m.mono()
        elif classe == K.ACEITA:
            # PLACED: a bolsa recebeu; a posição vem depois (nunca reenvia)
            dia.registrar("teste", quando=agora, etapa=1, teste_id=t["id"],
                          retcode=int(res.retcode), atraso_ms=ms,
                          motivo="aceita, aguardando a bolsa")
            t["fase"], t["desde"] = "aguarda", self.m.mono()
        else:
            # INCERTA pode ter executado: o encerramento procura a posição
            # pelo magic e a fecha se ela aparecer — e segura um teste novo
            # por ESPERA_S, para um clique não abrir uma segunda
            self._falhou(dia, agora, 1, K.texto(res), res,
                         min_s=ESPERA_S if classe == K.INCERTA else LISTA_S)

    def _aguarda(self, mt5, foto, dia, agora):
        p = next((p for p in foto.posicoes if p.magic == MAGIC), None)
        if p is None:
            if self._passou(ESPERA_S):
                self._falhou(dia, agora, 1, "a corretora aceitou, mas a posição não "
                             "apareceu em 10 s")
            return
        t = self.atual
        t["ticket"], t["preco"] = p.ticket, p.preco
        self._ev(dia, agora, 1, preco=p.preco, atraso_ms=t["ms"].get("entrada"),
                 motivo="executada")
        t["fase"], t["desde"] = "protecao", self.m.mono()
        # a proteção é a etapa seguinte: na próxima volta

    # ---------------------------------------------- etapa 2: proteção
    def _protecao(self, mt5, foto, dia, agora):
        t = self.atual
        p = self._da_foto(foto) if t.get("ticket") else next(
            (p for p in foto.posicoes if p.magic == MAGIC), None)
        if p is None:
            if self._passou(LISTA_S):
                self._falhou(dia, agora, 2, "a posição de teste não apareceu na corretora")
            return
        t["ticket"] = p.ticket
        entrada = t.get("preco") or p.preco
        t["preco"] = entrada
        sl, tp = K.protecao(1, entrada - DISTANCIA, entrada + DISTANCIA, self.m.tick)
        t["sl"], t["tp"] = sl, tp
        if t.get("prot_ult") is not None:
            if round(p.sl) == sl and round(p.tp) == tp:
                # a tentativa anterior (sem resposta) chegou: não reenvia
                t["ms"]["protecao"] = t.get("prot_ms")
                self._ev(dia, agora, 2, preco=entrada, stop_px=sl, alvo_px=tp,
                         atraso_ms=t.get("prot_ms"), motivo="stop e alvo já na posição")
                t["fase"], t["desde"] = "confere", self.m.mono()
                return
            quando = self._de_novo("prot")
            if quando == "espera":
                return
            if quando == "desiste":
                return self._falhou(dia, agora, 2, t["prot_motivo"], t.get("prot_res"))
        req = K.pedido_protecao(mt5, simbolo=p.simbolo, ticket=p.ticket, sl=sl, tp=tp,
                                magic_=MAGIC)
        t0 = self.m.mono()
        res = mt5.order_send(req)
        ms = _ms(self.m.mono() - t0)
        classe = K.classificar(res)
        if classe in _DE_NOVO:
            # passageira (requote, preço mudou, sem cotação, travado...) ou
            # sem resposta: não é falha da etapa — de novo em 1 s, até 5 s
            t.setdefault("prot_desde", t0)
            t["prot_ult"], t["prot_ms"] = self.m.mono(), ms
            t["prot_motivo"], t["prot_res"] = K.texto(res), res
            if self.m.mono() - t["prot_desde"] > REPETIR_S:
                return self._falhou(dia, agora, 2, K.texto(res), res)
            return
        if classe not in (K.OK, K.SEM_MUDANCA):
            return self._falhou(dia, agora, 2, K.texto(res), res)
        t["ms"]["protecao"] = ms
        self._ev(dia, agora, 2, retcode=int(res.retcode),
                 comment=str(getattr(res, "comment", "") or ""), preco=entrada,
                 stop_px=sl, alvo_px=tp, atraso_ms=ms, motivo=K.texto(res))
        t["fase"], t["desde"] = "confere", self.m.mono()

    # ------------------------------------------- etapa 3: conferência
    def _confere(self, mt5, foto, dia, agora):
        t = self.atual
        p = self._da_foto(foto)
        if p is None:
            return self._falhou(dia, agora, 3, "a posição de teste sumiu da corretora")
        if round(p.sl) == t["sl"] and round(p.tp) == t["tp"]:
            self._ev(dia, agora, 3, stop_px=t["sl"], alvo_px=t["tp"],
                     motivo="stop e alvo conferidos na posição")
            t["fase"], t["desde"] = "espera", self.m.mono()
        elif self._passou(LISTA_S):
            self._falhou(dia, agora, 3, f"a posição está com stop {round(p.sl)} e alvo "
                         f"{round(p.tp)}, não {t['sl']} e {t['tp']}")

    # ---------------------------------------------------- etapa 4: espera
    def _espera(self, mt5, foto, dia, agora):
        if self._da_foto(foto) is None:
            return self._falhou(dia, agora, 4, "a posição saiu na corretora antes do "
                                "fim da espera (stop ou alvo)")
        if self.m.mono() - self.atual["desde"] >= ESPERA_S:
            self._ev(dia, agora, 4, motivo="10 s com a posição protegida")
            self.atual["fase"], self.atual["desde"] = "saida", self.m.mono()

    # ---------------------------------------------------- etapa 5: saída
    def _saida(self, mt5, foto, dia, agora):
        t = self.atual
        p = self._da_foto(foto)
        if p is None:
            if t.get("saida_ult") is not None:
                # a tentativa anterior (sem resposta) saiu: confere e fecha
                t["ms"]["saida"] = t.get("saida_ms")
                t["fase"], t["desde"] = "saida_confere", self.m.mono()
                return self._saida_confere(mt5, foto, dia, agora)
            return self._falhou(dia, agora, 5, "a posição saiu na corretora antes da "
                                "saída (stop ou alvo)")
        if t.get("saida_ult") is not None:
            quando = self._de_novo("saida")
            if quando == "espera":
                return
            if quando == "desiste":
                desde, ult = t["saida_desde"], t["saida_ult"]
                self._falhou(dia, agora, 5, t["saida_motivo"], t.get("saida_res"))
                self.atual["recusa_desde"], self.atual["ultimo_envio"] = desde, ult
                return
        t0 = self.m.mono()
        res, classe, ms = self._sair(mt5, p)
        if classe in (K.OK, K.ACEITA, K.JA_SAIU):
            # executada; aceita pela bolsa (o negócio vem depois); ou já
            # encerrada: a volta seguinte confere que a posição sumiu
            # (aceita: a posição pode levar mais que a lista para sumir)
            t["confere_s"] = ESPERA_S if classe == K.ACEITA else LISTA_S
            t["ms"]["saida"] = ms
            dia.registrar("teste", quando=agora, etapa=5, teste_id=t["id"],
                          conta_id=t.get("conta_id"), ticket=p.ticket,
                          retcode=int(res.retcode),
                          comment=str(getattr(res, "comment", "") or ""),
                          preco=float(getattr(res, "price", 0) or 0) or None,
                          atraso_ms=ms, motivo=K.texto(res))
            t["fase"], t["desde"] = "saida_confere", self.m.mono()
            return
        if classe in _DE_NOVO:
            t.setdefault("saida_desde", t0)
            t["saida_ult"], t["saida_ms"] = self.m.mono(), ms
            t["saida_motivo"], t["saida_res"] = K.texto(res), res
            if self.m.mono() - t["saida_desde"] <= REPETIR_S:
                return
        self._falhou(dia, agora, 5, "sem cotação do contrato" if res is None
                     else K.texto(res), None if res is None else res)
        # a saída acabou de ser recusada: o prazo do chamado conta daqui
        self.atual["recusa_desde"] = self.atual["ultimo_envio"] = self.m.mono()

    def _saida_confere(self, mt5, foto, dia, agora):
        t = self.atual
        if self._da_foto(foto) is not None:
            if self._passou(t.get("confere_s", LISTA_S)):
                self._falhou(dia, agora, 5, "a saída executou, mas a posição continua "
                             "na corretora")
            return
        texto = texto_ok(t["ms"])
        dia.registrar("teste_ok", quando=agora, teste_id=t["id"],
                      conta_id=t.get("conta_id"), ticket=t.get("ticket"),
                      entrada_ms=t["ms"].get("entrada"),
                      protecao_ms=t["ms"].get("protecao"),
                      saida_ms=t["ms"].get("saida"), motivo=texto)
        self._publicar("ok", 5, texto, agora, t["id"])
        self.atual = None

    def _sair(self, mt5, p):
        """Saída pelo ticket com o fallback de preenchimento: (resposta,
        classe, ms do envio); (None, None, None) = sem cotação."""
        info, tk = mt5.symbol_info(p.simbolo), mt5.symbol_info_tick(p.simbolo)
        if info is None or tk is None:
            return None, None, None
        preco = float(tk.bid if p.lado > 0 else tk.ask)

        def montar(modo):
            return K.pedido_saida(mt5, simbolo=p.simbolo, lado_posicao=p.lado,
                                  volume=p.volume, preco=preco, ticket=p.ticket,
                                  magic_=MAGIC, desvio=2 * self.m.tick,
                                  preenchimento=modo)
        return self._enviar_com_preenchimento(mt5, montar, info)

    # ------------------------------------------------ encerrar o que sobrou
    def _sobra(self, mt5, foto, dia, agora):
        """Sem teste em andamento, posição ou ordem com o magic do teste é
        resto (reinício no meio, entrada sem resposta que executou depois):
        encerra."""
        if not any(p.magic == MAGIC for p in foto.posicoes) and \
                not any(o.get("magic") == MAGIC for o in foto.ordens):
            return
        if not self._na_conta_do_processo(mt5):
            return            # conta fora do processo: o magic não é necessariamente nosso
        tickets = [p.ticket for p in foto.posicoes if p.magic == MAGIC]
        dia.registrar("teste", quando=agora, etapa=0, ticket=tickets[0] if tickets else None,
                      motivo="posição de teste que sobrou: encerrando")
        self.atual = {"id": None, "conta_id": None, "simbolo": None,
                      "fase": "encerrando", "desde": self.m.mono(),
                      "ultimo_envio": None, "recusa_desde": None,
                      "min_s": LISTA_S}

    def _encerrando(self, mt5, foto, dia, agora):
        t = self.atual
        pos = [p for p in foto.posicoes if p.magic == MAGIC]
        ords = [o for o in foto.ordens if o.get("magic") == MAGIC]
        if not pos and not ords:
            # a lista pode atrasar logo depois de uma entrada sem resposta:
            # só se dá por limpo depois de LISTA_S sem nada
            if self._passou(t.get("min_s", LISTA_S)):
                self.m._fechar(CHAMADO, agora)
                self.atual = None
            return
        m = self.m.mono()
        if t["recusa_desde"] is not None and m - t["recusa_desde"] > PRESO_S:
            # o chamado fica aberto enquanto houver o que encerrar, mesmo sem
            # reenviar (fora do pregão)
            self.m._chamar(CHAMADO, CHAMADO, TEXTO_PRESO, agora)
        if t["ultimo_envio"] is not None and m - t["ultimo_envio"] < INTERVALO_S:
            return
        if t["ultimo_envio"] is not None and not self._no_pregao:
            return            # mercado fechado: só a 1ª tentativa; o resto no pregão
        if not self._na_conta_do_processo(mt5):
            return            # nunca mexe no magic do teste fora da conta do processo
        t["ultimo_envio"] = m
        recusou = False
        for o in ords:
            res = mt5.order_send(K.pedido_cancelar(mt5, ordem=o["ticket"]))
            ok = K.classificar(res) == K.OK
            recusou = recusou or not ok
            if ok or t["recusa_desde"] is None:
                dia.registrar("teste", quando=agora, etapa="encerrar", ticket=o["ticket"],
                              retcode=None if res is None else int(res.retcode),
                              motivo="ordem de teste pendente cancelada" if ok
                              else "cancelamento da ordem de teste recusado: "
                              + K.texto(res))
        for p in pos:
            res, classe, _ = self._sair(mt5, p)
            if classe in (K.OK, K.JA_SAIU, K.ACEITA):
                # aceita pela bolsa: o negócio vem depois (a próxima foto diz)
                dia.registrar("teste", quando=agora, etapa="encerrar", ticket=p.ticket,
                              retcode=int(res.retcode),
                              preco=float(getattr(res, "price", 0) or 0) or None,
                              motivo="saída da posição de teste aceita, aguardando a "
                              "bolsa" if classe == K.ACEITA
                              else "posição de teste encerrada")
                continue
            recusou = True
            if t["recusa_desde"] is None:
                # a primeira recusa vai ao diário; as seguintes (a cada 1 s)
                # não o enchem — o chamado diz que segue presa
                t["recusa_desde"] = m
                dia.registrar("teste", quando=agora, etapa="encerrar", ticket=p.ticket,
                              retcode=None if res is None else int(res.retcode),
                              motivo="saída da posição de teste recusada: " + (
                                  "sem cotação do contrato" if res is None
                                  else K.texto(res)))
        if not recusou:
            t["recusa_desde"] = None
        else:
            if t["recusa_desde"] is None:
                t["recusa_desde"] = m
            if m - t["recusa_desde"] > PRESO_S:
                self.m._chamar(CHAMADO, CHAMADO, TEXTO_PRESO, agora)


# em que etapa está quem é interrompido pelo Zerar tudo
ETAPA_DA_FASE = {"entrada": 1, "aguarda": 1, "protecao": 2, "confere": 3,
                 "espera": 4, "saida": 5, "saida_confere": 5}
