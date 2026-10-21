"""Opção de saída comum a todas as estratégias.

A estratégia decide ENTRADA; quando sair por sinal é uma escolha que vale
para qualquer setup, e por isso mora aqui, uma vez só. Cada estratégia põe
o parâmetro no schema com o padrão DELA (o que ela já fazia antes desta
opção existir — mudar o padrão mudaria o resultado de todo plano gravado) e
passa os sinais por `aplicar`.

Os modos, pelo número que a tela e a mineração usam:

- 0 sinal contrário: a entrada de venda encerra a compra, e vice-versa.
- 1 não sair: nenhuma saída por sinal; só stop, alvo, horário de
  fechamento ou tempo máximo encerram. Entrada nova só zerado.
- 2 virar a mão: sai no sinal contrário e entra do outro lado na mesma
  abertura, com os mesmos contratos. Quem decide se a entrada pode
  acontecer (direção, janela, horas sem entrada, limites do dia) é o motor;
  barrada, sobra só a saída.
- 3 saída da estratégia: a saída que a própria estratégia calcula. Só
  existe onde ela é diferente do sinal contrário (`reversao_rsi`, que sai
  na volta à média curta). Nas outras seria uma cópia do 0, e cópia na
  mineração cria platô falso.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .base import Signals

CONTRARIO = 0
NAO_SAIR = 1
VIRAR = 2
PROPRIA = 3

_ROTULO = "Saída · 0 sinal contrário · 1 não sai · 2 vira a mão"


def parametro(padrao: int, propria: bool = False) -> dict:
    """A entrada `saida` do `params_schema`, com o padrão da estratégia.

    `propria=True` só para quem tem saída própria diferente do sinal
    contrário: acrescenta o modo 3."""
    maximo = PROPRIA if propria else VIRAR
    rotulo = _ROTULO + (" · 3 própria" if propria else "")
    if not 0 <= padrao <= maximo:
        raise ValueError(f"saída padrão {padrao} fora de 0..{maximo}")
    return {"saida": {"label": rotulo, "default": int(padrao), "min": 0,
                      "max": maximo, "step": 1, "tipo": "int"}}


def modo(params: dict, schema: dict) -> int:
    """O modo pedido. Plano gravado antes desta opção não tem a chave: vale
    o padrão da estratégia, que é o comportamento com que ele foi aprovado."""
    v = params.get("saida")
    return int(schema["saida"]["default"] if v is None else round(v))


def aplicar(sinais: Signals, modo: int) -> Signals:
    """Reescreve as saídas (e liga a virada) conforme o modo."""
    modo = int(modo)
    if modo == PROPRIA:
        return sinais
    if modo == NAO_SAIR:
        n = len(sinais.entry_long)
        return replace(sinais, exit_long=np.zeros(n, dtype=np.bool_),
                       exit_short=np.zeros(n, dtype=np.bool_), virar=False)
    if modo in (CONTRARIO, VIRAR):
        return replace(sinais,
                       exit_long=np.asarray(sinais.entry_short, dtype=np.bool_).copy(),
                       exit_short=np.asarray(sinais.entry_long, dtype=np.bool_).copy(),
                       virar=modo == VIRAR)
    raise ValueError(f"modo de saída desconhecido: {modo}")
