"""Painel estatistico: as métricas que decidem se vale olhar o resto.

Numero grande e para ser lido de longe; a cor codifica o sinal, nao enfeita.
O que é diagnóstico — sequências, motivo de saída, ambiguidade do motor —
mora na aba Detalhes: aqui só entra o que se lê antes de decidir se a
estratégia merece mais tempo.

Os cartões servem a QUALQUER sequência de trades, não só ao backtest: o
walk-forward monta os seus com `cartoes(m, dicas)` sobre a curva fora da
amostra, e troca só o texto do (?) onde a leitura muda. A conta e o desenho
são um só — dois cartões "sharpe" na plataforma nunca discordam.
"""

from __future__ import annotations

from dash import html

from .cartao import brl, card, inteiro, num, sinal_de
from .cartao import vazio as _vazio

# reexportados: results_grid e robustez_cards importam daqui desde antes
__all__ = ["brl", "num", "inteiro", "cartoes", "render", "vazio"]

_sinal = sinal_de


def vazio(mensagem="Rode um backtest para ver as métricas."):
    return _vazio(mensagem)


def cartoes(m: dict, dicas: dict[str, str] | None = None) -> dict[str, html.Div]:
    """Os cartões, chaveados pelo rótulo e na ordem de leitura.

    `m` é o dicionário de `metrics.resumo` (ou de `compute`, que o contém).
    `dicas` troca o texto do (?) de um cartão pelo rótulo — o número é o
    mesmo, mas "lucro líquido" de um backtest otimizado e de uma curva fora
    da amostra não se leem do mesmo jeito.

    Devolver um dicionário deixa quem consome escolher a ordem e intercalar
    cartões próprios sem reescrever nenhum destes.
    """
    dicas = dicas or {}
    saida: dict[str, html.Div] = {}

    def c(rotulo, valor, explica=None, *args, **kw):
        saida[rotulo] = card(rotulo, valor, dicas.get(rotulo, explica),
                             *args, **kw)

    pf = m["profit_factor"]
    pf_txt = "∞" if pf == float("inf") else num(pf)

    c("período", m.get("periodo", "—"),
      "A janela de barras que estes números cobrem. Quando uma "
      "mineração é carregada, o período encolhe para a MESMA "
      "janela em que ela otimizou — o holdout fica de fora, senão "
      "o cartão e a linha da tabela mostrariam coisas diferentes.",
      nota=m.get("periodo_nota", ""), largo=True)
    c("lucro líquido", brl(m["lucro_liquido"]),
      "Resultado depois de corretagem, emolumentos e slippage. É o "
      "único número de lucro que vale: estratégia de giro alto "
      "quase sempre parece lucrativa no bruto.",
      _sinal(m["lucro_liquido"]),
      f"bruto {brl(m['lucro_bruto'])} − custo {brl(m['custo_total'])}",
      largo=True)
    # valores em dinheiro ocupam duas colunas: sao os mais longos e os mais
    # importantes de ler de longe
    c("max drawdown", brl(m["max_drawdown"]),
      "O maior mergulho em DINHEIRO, do topo até o fundo da curva "
      "de capital — o 'Balance Drawdown Maximal' do MT5. Os dois "
      "percentuais ao lado descrevem esse mesmo mergulho em bases "
      "diferentes: '% do pico' divide pelo topo alcançado até ali, "
      "'% do capital' divide pelo que você depositou. Eles "
      "divergem assim que a curva sobe. "
      "Não confundir com o 'Balance Drawdown Relative', que é o "
      "maior mergulho em PERCENTUAL e pode estar em outro ponto da "
      f"curva — aqui ele é {num(m.get('max_drawdown_rel_pct', 0), 2)}%. "
      "Acima de 20% do capital, o tamanho de posição provavelmente "
      "está grande demais.",
      "neg" if m["max_drawdown"] else None,
      f"{num(m['max_drawdown_pct'], 1)}% do pico · "
      f"{num(m.get('max_drawdown_pct_capital', 0), 1)}% do capital",
      largo=True)
    c("profit factor", pf_txt,
      "Quanto se ganha para cada R$ 1 perdido. Abaixo de 1,0 a "
      "estratégia perde dinheiro. De 1,2 a 1,6 é o normal de um "
      "sistema real de day trade; acima de 2,0 com poucos trades "
      "costuma ser sobreajuste, não descoberta.",
      _sinal(pf - 1))
    c("win rate", f"{num(m['win_rate'], 1)}%",
      "Percentual de trades vencedores. Sozinho não diz nada: 90% "
      "de acerto com payoff 0,1 quebra a conta, e 35% com payoff "
      "3,0 é excelente. Leia sempre junto do payoff.")
    c("payoff", num(m["payoff"]),
      "Ganho médio dividido pela perda média. Multiplicado pelo win "
      "rate é o que define se a expectativa é positiva. Com 50% de "
      "acerto, qualquer payoff acima de 1,0 lucra antes do custo.")
    c("expectativa", brl(m["expectativa"]),
      "Quanto a estratégia devolve, em média, por operação, já "
      "líquido. É o número que multiplica pelo giro: R$ 5 por "
      "trade com 2.000 trades é um sistema; R$ 80 com 12 trades é "
      "uma amostra.",
      _sinal(m["expectativa"]), "por trade", largo=True)
    c("fator recuperação", num(m["fator_recuperacao"]),
      "Lucro líquido dividido pelo max drawdown: quantas vezes a "
      "estratégia repôs o pior mergulho que deu. Abaixo de 1,0 o "
      "lucro do período inteiro não cobre um drawdown. Acima de "
      "3,0 é bom.",
      _sinal(m["fator_recuperacao"]))
    c("sharpe", num(m["sharpe"]),
      "Retorno anualizado dividido pela volatilidade do retorno "
      "DIÁRIO. Acima de 1,0 é bom, acima de 2,0 é raro. O Sortino "
      "é a mesma conta punindo só a oscilação para baixo — se ele "
      "for muito maior que o Sharpe, a volatilidade da estratégia "
      "é principalmente a favor, o que é ótimo.",
      _sinal(m["sharpe"]), f"sortino {num(m['sortino'])}")
    c("trades", inteiro(m["trades"]),
      "Tamanho da amostra. Abaixo de ~100 quase nada aqui é "
      "conclusivo — a aba Robustez diz quantos trades faltariam "
      "para o resultado sair do terreno do acaso.",
      nota=f"{num(m['trades_por_dia'])} por pregão")
    return saida


def render(m: dict) -> html.Div:
    if not m or not m.get("trades"):
        return vazio("Nenhum trade no período e nas condições atuais.")
    return html.Div(list(cartoes(m).values()), className="cards")
