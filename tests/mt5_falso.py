"""MT5 falso de ORDENS: posições, ordens pendentes, negócios do dia e um
roteiro de retornos para o order_send. Nada aqui fala com terminal.

As constantes são as do pacote MetaTrader5 5.0.6180 (conferidas): o código
de produção as lê do objeto `mt5`, então o falso precisa dos mesmos valores.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace as NS

import numpy as np


def _epoch(d: datetime) -> int:
    return int(d.replace(tzinfo=timezone.utc).timestamp())


class MT5Ordens:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 6, 8
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
    DEAL_REASON_CLIENT, DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 3, 4, 5
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
    SYMBOL_TRADE_MODE_FULL = 4
    TIMEFRAME_M1 = 1
    TIMEFRAME_D1 = 16408

    def __init__(self, *, login=1193398927, servidor="ClearInvestimentos-DEMO",
                 preco=189_000, agora=datetime(2026, 10, 9, 10, 1, 1)):
        self.login, self.servidor = login, servidor
        self.preco = preco
        self.agora = agora                 # hora dos negócios criados
        self.posicoes: dict[int, NS] = {}
        self.ordens: dict[int, NS] = {}
        self.historico: list[NS] = []      # toda ordem enviada (DEAL e PLACED)
        self.negocios: list[NS] = []
        self.enviados: list[dict] = []
        self.checados: list[dict] = []
        self.roteiro: list = []
        self.margem_livre = 10_000.0
        self.algo = True
        self.conectado = True
        self.hedging = True
        self.vazio_uma_vez = False         # lista vazia logo após reconectar
        self.erro_leitura = False          # positions_get/orders_get/... -> None
        # só estas leituras falham (nomes dos métodos): a corretora meio
        # ilegível — ex.: {"history_deals_get"} lê posições e não o histórico
        self.falhar: set = set()
        self.erro_check = None             # order_check -> None com este last_error
        self.check_retcode = None          # order_check devolve este retcode
        self.check_comment = ""
        self.filling = 3                   # máscara FOK|IOC
        self.parcial_volume = 1.0
        self.stops_level = 0               # SYMBOL_TRADE_STOPS_LEVEL, em pontos
        self.precos = {"WIN$N": preco, "WINV26": preco, "WINZ26": preco + 1500}
        self.vencimentos = {"WINV26": datetime(2026, 10, 14, 18, 30),
                            "WINZ26": datetime(2026, 12, 16, 18, 30)}
        self.volumes = {}                  # simbolo -> real_volume do pregão anterior
        self.sem_barras = False            # copy_rates_from_pos -> None
        self._ticket = 1000

    # ---------------------------------------------------------- leitura
    def last_error(self):
        if self.erro_check is not None:
            return self.erro_check
        return (-10004, "IPC") if self.erro_leitura or self.falhar else (1, "Success")

    def _falha(self, nome):
        return self.erro_leitura or nome in self.falhar

    def positions_get(self, **k):
        if self._falha("positions_get"):
            return None
        if self.vazio_uma_vez:
            self.vazio_uma_vez = False
            return ()
        return tuple(self.posicoes.values())

    def orders_get(self, **k):
        return None if self._falha("orders_get") else tuple(self.ordens.values())

    def history_deals_get(self, de, ate, **k):
        return None if self._falha("history_deals_get") else tuple(self.negocios)

    def history_orders_get(self, de, ate, **k):
        return None if self._falha("history_orders_get") else tuple(self.historico)

    def account_info(self):
        if "account_info" in self.falhar:
            return None
        return NS(login=self.login, server=self.servidor,
                  margin_mode=2 if self.hedging else 0,
                  margin_free=self.margem_livre)

    def terminal_info(self):
        if "terminal_info" in self.falhar:
            return None
        return NS(connected=self.conectado, trade_allowed=self.algo)

    def symbol_info(self, s):
        venc = self.vencimentos.get(s)
        return NS(name=s, filling_mode=self.filling,
                  trade_stops_level=self.stops_level, point=1.0,
                  trade_tick_size=5.0, trade_mode=4, basis="",
                  expiration_time=_epoch(venc) if venc else 0)

    def symbol_info_tick(self, s):
        p = self.precos.get(s, self.preco)
        return NS(time=_epoch(self.agora), last=float(p), bid=float(p),
                  ask=float(p + 5))

    def symbols_get(self, group=None):
        # grupo "WIN*": só o prefixo importa nos testes
        pref = (group or "").rstrip("*")
        return tuple(self.symbol_info(s) for s in self.precos if s.startswith(pref))

    def copy_rates_from_pos(self, simbolo, timeframe, inicio, quantidade):
        if self.sem_barras or simbolo not in self.volumes:
            return None
        # como o pacote real: array numpy estruturado, a barra mais antiga primeiro
        return np.array([(0, 0.0, 0.0, 0.0, 0.0, 0, 0, self.volumes[simbolo])] * quantidade,
                        dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                               ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4"),
                               ("real_volume", "i8")])

    def order_check(self, req):
        self.checados.append(dict(req))
        if self.erro_check is not None:
            return None
        if self.check_retcode is not None:
            return NS(retcode=self.check_retcode, comment=self.check_comment,
                      margin_free=self.margem_livre)
        sem = self.margem_livre <= 0
        return NS(retcode=10019 if sem else 0, comment="No money" if sem else "Done",
                  margin_free=self.margem_livre)

    # ----------------------------------------------------------- envio
    def _novo(self):
        self._ticket += 1
        return self._ticket

    def _registrar(self, ticket, req):
        self.historico.append(NS(ticket=ticket, magic=req.get("magic", 0),
                                 time_setup=_epoch(self.agora),
                                 symbol=req["symbol"]))

    def order_send(self, req):
        self.enviados.append(dict(req))
        r = self.roteiro.pop(0) if self.roteiro else 10009
        if r is None:
            return None
        if r == "executou_sem_resposta":
            self._executar(req)
            return None
        if r == 10008:                      # PLACED: fica como ordem pendente
            t = self._novo()
            self.ordens[t] = NS(ticket=t, magic=req.get("magic", 0),
                                symbol=req["symbol"], volume_current=req["volume"],
                                time_setup=_epoch(self.agora), type=req["type"], req=dict(req))
            # ativa: só está em orders_get; vai ao histórico ao sair de self.ordens
            return NS(retcode=10008, order=t, deal=0, volume=0.0, price=0.0, comment="")
        if r in (10009, 10010):
            return self._executar(req, parcial=r == 10010)
        return NS(retcode=r, order=0, deal=0, volume=0.0, price=0.0, comment="")

    def _executar(self, req, parcial=False, registrar=True):
        acao = req["action"]
        if acao == self.TRADE_ACTION_SLTP:
            p = self.posicoes.get(req["position"])
            if p is None:
                return NS(retcode=10036, order=0, deal=0, volume=0.0, price=0.0, comment="")
            p.sl, p.tp = req["sl"], req["tp"]
            return NS(retcode=10009, order=0, deal=0, volume=0.0, price=0.0, comment="")
        if acao == self.TRADE_ACTION_REMOVE:
            o = self.ordens.pop(req["order"], None)
            if o is not None:
                self._registrar(o.ticket, o.req)
            return NS(retcode=10009, order=req["order"], deal=0, volume=0.0, price=0.0, comment="")
        if "position" in req:               # saída
            p = self.posicoes.get(req["position"])
            if p is None:
                return NS(retcode=10036, order=0, deal=0, volume=0.0, price=0.0, comment="")
            # saída parcial: sai `parcial_volume`, a posição segue com o resto
            vol = min(self.parcial_volume, p.volume) if parcial else p.volume
            if vol >= p.volume:
                self.posicoes.pop(req["position"])
            else:
                p.volume -= vol
            if registrar:
                self._registrar(self._novo(), req)
            deal = self._novo()
            self.negocios.append(NS(ticket=deal, order=0,
                                    time=_epoch(self.agora), type=req["type"], entry=1,
                                    magic=p.magic, position_id=p.ticket, reason=3,
                                    volume=vol, price=float(self.preco),
                                    commission=0.0, swap=0.0, fee=0.0,
                                    profit=p.profit, symbol=p.symbol))
            return NS(retcode=10010 if parcial and vol < req["volume"] else 10009,
                      order=deal, deal=deal, volume=vol, price=float(self.preco),
                      comment="")
        vol = self.parcial_volume if parcial else req["volume"]
        t = self._novo()
        if registrar:
            self._registrar(t, req)
        # como a ordem real: sem sl/tp no pedido, a posição nasce sem proteção
        self.posicoes[t] = NS(ticket=t, identifier=t, magic=req["magic"],
                              symbol=req["symbol"], type=req["type"], volume=vol,
                              price_open=float(self.preco),
                              sl=req.get("sl", 0.0), tp=req.get("tp", 0.0),
                              profit=0.0, time=_epoch(self.agora))
        deal = self._novo()
        self.negocios.append(NS(ticket=deal, order=t, time=_epoch(self.agora),
                                type=req["type"], entry=0, magic=req["magic"],
                                position_id=t, reason=3, volume=vol,
                                price=float(self.preco), commission=0.0, swap=0.0,
                                fee=0.0, profit=0.0, symbol=req["symbol"]))
        if parcial:                          # o resto fica vivo (RETURN)
            o = self._novo()
            self.ordens[o] = NS(ticket=o, magic=req["magic"], symbol=req["symbol"],
                                volume_current=req["volume"] - vol,
                                time_setup=_epoch(self.agora), type=req["type"],
                                req=dict(req, volume=req["volume"] - vol))
        return NS(retcode=10010 if parcial else 10009, order=t, deal=deal,
                  volume=vol, price=float(self.preco), comment="")

    # ------------------------------------------------------- cenários
    def abrir_manual(self, lado, volume=1.0, magic=0, simbolo="WINV26"):
        return self._executar({"action": 1, "symbol": simbolo, "volume": volume,
                               "type": 0 if lado > 0 else 1, "sl": 0.0, "tp": 0.0,
                               "magic": magic}).order

    def stopar(self, ticket, motivo=4):
        """O servidor executou o SL (4) ou o TP (5)."""
        p = self.posicoes.pop(ticket)
        self.negocios.append(NS(ticket=self._novo(), order=0, time=_epoch(self.agora),
                                type=1 - p.type, entry=1, magic=p.magic,
                                position_id=p.ticket, reason=motivo, volume=p.volume,
                                price=float(self.preco), commission=0.0, swap=0.0,
                                fee=0.0, profit=p.profit, symbol=p.symbol))

    def executar_pendente(self, ordem):
        o = self.ordens.pop(ordem)
        self._registrar(o.ticket, o.req)     # saiu das ativas: vai ao histórico
        return self._executar(o.req, registrar=False)   # a ordem já está no histórico
