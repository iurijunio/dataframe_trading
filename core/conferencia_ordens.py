"""Conferência no mesmo dia: o que as ordens querem × o papel gravado.

As ordens decidem pelo papel AO VIVO (`papel_vivo.desejados`, em memória);
a tela e a conferência com o backtest usam o papel GRAVADO
(`papel.rodar_dia`). Os dois são o mesmo cálculo e têm de dar o mesmo
resultado. Em 05/11/2026 não deram — o aquecimento em memória era o de
antes da reconferência — e a automação comprou às 10:15 na conta real com o
papel vendido desde 09:45, sem nenhum aviso. Este módulo só AVISA: nada
aqui manda, cancela ou zera ordem.

Puro: quem chama (a captura) entrega os desejados, as ligações do retrato e
o resultado do papel do MESMO minuto de barras, e abre/fecha os chamados que
a `Vigia` disser.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .papel_vivo import INDISPONIVEL, POSICAO, ZERADO

TIPO = "divergencia_papel"

# Persistência: a divergência só vira chamado quando aparece em comparações
# de 3 minutos de barra diferentes, sem nenhuma comparação igual no meio
# (cerca de 2 minutos inteiros). Por minuto, e não por número de
# comparações, porque o desencontro legítimo mora DENTRO do minuto: o toque
# do stop/alvo no candle em formação (o papel regrava várias vezes no mesmo
# minuto) e o segundo da virada. Contar comparações deixaria um toque só
# virar alarme; três minutos distintos já implicam três comparações.
MINUTOS_PARA_CHAMAR = 3

# eligível, mas sem como comparar agora (desejado indisponível, papel sem
# cálculo): não conta a favor nem contra a persistência
INCOMPARAVEL = "incomparavel"


@dataclass(frozen=True)
class Divergencia:
    ligacao_id: int
    ordem: tuple | None         # (lado, entry_ts) do desejado; None = zerado
    papel: tuple | None         # (lado, entry_ts) da aberta que conta; None = zerado

    def chave(self, dia: date) -> str:
        """Estável por (ligação, dia, entrada): a mesma divergência a cada
        volta é o mesmo chamado — o alarme bipa uma vez só."""
        ts = (self.papel or self.ordem)[1]
        return f"{TIPO}:{self.ligacao_id}:{dia:%Y-%m-%d}:{ts:%H:%M}"

    def texto(self) -> str:
        return (f"ordem ≠ papel: ligação {self.ligacao_id} — ordens "
                f"{_lado(self.ordem)}, papel {_lado(self.papel)}")


def _lado(p: tuple | None) -> str:
    if p is None:
        return "zerado"
    lado, ts = p
    return f"{'comprado' if lado == 1 else 'vendido'} desde {ts:%H:%M}"


def _aberta_do_papel(r: dict | None):
    """(lado, entry_ts) da operação aberta que conta, None se não há, ou
    INCOMPARAVEL sem cálculo nesta volta (falha, pulado, congelado)."""
    if r is None or r.get("operacoes") is None:
        return INCOMPARAVEL
    abertas = [o for o in r["operacoes"] if o.get("aberta") and o.get("conta")]
    if not abertas:
        return None
    # a mesma escolha do `papel_vivo.desejados`: a última aberta que conta
    o = abertas[-1]
    return (int(o["side"]), o["entry_ts"])


def comparar(desejados: dict, ligacoes: dict, resultados: list[dict]) -> dict:
    """Por ligação em fase demo/real e ligada: None (bate), `Divergencia`
    ou INCOMPARAVEL. Ligação fora disso não aparece — o desejado dela é
    ZERADO por regra (fase papel, desligada), não pelo papel.

    Diverge: desejado em POSICAO com (lado, entry_ts) diferente da aberta
    que conta no papel (ou sem aberta); ou desejado ZERADO com aberta que
    conta no papel. INDISPONIVEL não entra (a automação só protege)."""
    do_papel = {r["ligacao_id"]: r for r in resultados}
    out: dict = {}
    for lig, lv in ligacoes.items():
        if lv.fase not in ("demo", "real") or not lv.ligada:
            continue
        d = desejados.get(lig)
        if d is None or d.estado not in (POSICAO, ZERADO):
            out[lig] = INCOMPARAVEL
            continue
        papel = _aberta_do_papel(do_papel.get(lig))
        if papel == INCOMPARAVEL:
            out[lig] = INCOMPARAVEL
            continue
        ordem = (int(d.lado), d.entry_ts) if d.estado == POSICAO else None
        out[lig] = None if ordem == papel else Divergencia(lig, ordem, papel)
    return out


class Vigia:
    """A persistência por ligação. `observar` devolve os chamados que devem
    estar ABERTOS agora, `{chave: (ligacao_id, texto)}`; quem chama fecha
    os do tipo que não estão na lista. Não guarda o que já foi chamado:
    abrir e fechar ficam idempotentes do lado do motor."""

    def __init__(self, minutos: int = MINUTOS_PARA_CHAMAR):
        self.minutos = minutos
        self._dia: date | None = None
        # ligação -> (minutos de barra em que divergiu, última divergência)
        self._seq: dict[int, tuple[set, Divergencia]] = {}

    def observar(self, dia: date, minuto: datetime, comparacoes: dict) -> dict:
        if dia != self._dia:
            self._dia, self._seq = dia, {}
        for lig in list(self._seq):
            if lig not in comparacoes:
                del self._seq[lig]          # saiu da fase ou foi desligada
        for lig, c in comparacoes.items():
            if c is None:
                self._seq.pop(lig, None)
            elif isinstance(c, Divergencia):
                vistos = self._seq.get(lig, (set(), c))[0]
                self._seq[lig] = (vistos | {minuto}, c)
        return {d.chave(dia): (lig, d.texto())
                for lig, (vistos, d) in self._seq.items()
                if len(vistos) >= self.minutos}
