"""Leituras finas do backtest: onde a estratégia está deixando dinheiro.

A aba Robustez pergunta "isto é sorte?". Aqui a pergunta é outra: **o que
ajustar**. Cada bloco aponta para um campo da camada 4 ou para a lógica do
sinal.

    sequencias   -> perda puxa perda? stop diário resolve?
    eficiencia   -> o problema é a entrada ou a saída?
    risco_trade  -> quanto arriscar por operação, com número
    ritmo        -> a estratégia opera pouco e bem, ou muito e mal?

Tudo sai dos arrays que o kernel já devolveu — nenhum backtest roda de novo.
"""

from __future__ import annotations

import numpy as np


def _corridas(sinais: np.ndarray) -> tuple[list[int], list[int]]:
    """Comprimento de cada sequência de ganhos e de cada sequência de perdas."""
    if not len(sinais):
        return [], []
    troca = np.flatnonzero(sinais[1:] != sinais[:-1]) + 1
    blocos = np.split(sinais, troca)
    ganhos = [len(b) for b in blocos if b[0]]
    perdas = [len(b) for b in blocos if not b[0]]
    return ganhos, perdas


def sequencias(liquido: np.ndarray) -> dict:
    """Quanto tempo a estratégia passa ganhando ou perdendo em fila.

    A média das sequências importa mais que o máximo: um recorde de 13
    perdas seguidas assusta, mas se a média é 1,6 aquilo foi um evento. Se a
    média for 4, o drawdown é estrutural e o stop diário deixa de ser
    exagero.

    `depois_de` responde se perda puxa perda: a expectativa do trade seguinte
    a 1, 2 e 3 derrotas em fila. Se despencar, existe dependência e vale
    pausar o dia; se ficar igual, as perdas são independentes e pausar só
    tira trades bons.
    """
    n = len(liquido)
    if n < 10:
        return {}
    venceu = liquido > 0
    g, p = _corridas(venceu)

    depois = {}
    for k in (1, 2, 3):
        seguintes = []
        for i in range(k, n):
            if not venceu[i - k:i].any():          # k derrotas em fila
                seguintes.append(liquido[i])
        if len(seguintes) >= 20:
            depois[k] = {"n": len(seguintes),
                         "expectativa": float(np.mean(seguintes))}

    return {
        "media_ganhos": float(np.mean(g)) if g else 0.0,
        "media_perdas": float(np.mean(p)) if p else 0.0,
        "max_ganhos": max(g) if g else 0,
        "max_perdas": max(p) if p else 0,
        "n_sequencias_ganho": len(g),
        "n_sequencias_perda": len(p),
        "expectativa_geral": float(liquido.mean()),
        "depois_de": depois,
    }


def eficiencia(mae: np.ndarray, mfe: np.ndarray, pontos: np.ndarray,
               tp_entrada: np.ndarray, motivos: np.ndarray,
               cod_alvo: int) -> dict:
    """Quanto do movimento disponível o trade capturou.

    Duas perguntas diferentes, e é a separação delas que aponta o culpado:

      ENTRADA — de todo o intervalo que o trade percorreu (a favor mais
      contra), quanto foi a favor? Baixo significa que você entra e o preço
      vai contra antes de virar: o gatilho está adiantado.

      SAÍDA — do melhor ponto que o trade alcançou, quanto sobrou no
      fechamento? Baixo significa que o lucro apareceu e você devolveu:
      o alvo está longe, ou falta trailing.
    """
    if not len(pontos):
        return {}
    mae_abs = np.abs(mae).astype(float)
    mfe = mfe.astype(float)
    amplitude = mfe + mae_abs

    # Sem amplitude nenhuma nao existe fracao a medir: devolver 0.0 pintava
    # a tela de vermelho ("eficiencia pessima") quando a resposta certa e
    # "indisponivel".
    ok = amplitude > 0
    ent = float((mfe[ok] / amplitude[ok]).mean() * 100) if ok.any() else None

    # A media da saida so pode ser tirada de quem TEVE pico a devolver.
    # Trades que nunca andaram a favor nao tem denominador - mas sao os
    # piores, e omitir quantos ficaram de fora fazia a media parecer da
    # amostra inteira. `n_saida` e `n_trades` vao para a tela.
    com_mfe = mfe > 0
    sai = (float((pontos[com_mfe] / mfe[com_mfe]).clip(-1, 1).mean() * 100)
           if com_mfe.any() else None)

    tocou = (mfe >= tp_entrada) & (tp_entrada > 0)
    nao_saiu_no_alvo = tocou & (motivos != cod_alvo)
    return {
        "entrada": ent,
        "saida": sai,
        "n_trades": int(len(pontos)),
        "n_saida": int(com_mfe.sum()),
        "mfe_medio": float(mfe.mean()),
        "mae_medio": float(mae_abs.mean()),
        "razao_mfe_mae": float(mfe.mean() / mae_abs.mean()) if mae_abs.mean() else None,
        "tocou_alvo": int(tocou.sum()),
        "tocou_e_nao_saiu": int(nao_saiu_no_alvo.sum()),
        "pct_devolvido": (float(nao_saiu_no_alvo.sum() / tocou.sum() * 100)
                          if tocou.sum() else 0.0),
    }


def risco_trade(liquido: np.ndarray, pontos: np.ndarray,
                sl_entrada: np.ndarray, motivos: np.ndarray,
                cod_stop: int, folga: int = 0) -> dict:
    """O tamanho do risco de uma operação, em número.

    VaR e CVaR respondem coisas diferentes: o VaR é a perda que só 5% dos
    trades superam; o CVaR é a média desses 5% piores — quanto dói quando
    passa da linha. Dimensionar posição pelo VaR ignora justamente a cauda
    que quebra conta.

    `folga` é o slippage configurado, em pontos. O motor já o embute no
    resultado, então sem descontá-lo aqui TODA saída por stop seria contada
    como stop furado e a métrica não diria nada.
    """
    if len(liquido) < 20:
        return {}
    perdas = liquido[liquido < 0]
    var = float(np.percentile(liquido, 5))
    # Os k PIORES, e nao `liquido <= var`. Com stop fixo em pontos dezenas de
    # trades empatam exatamente no valor do percentil, e o `<=` arrastava
    # todos eles para a cauda: num caso real de 100 trades a "media dos 5%
    # piores" saia da media de 31 deles, puxada na direcao do VaR. O erro era
    # para o lado otimista, justamente no numero que dimensiona posicao.
    k = max(1, int(np.ceil(0.05 * len(liquido))))
    piores = np.sort(liquido)[:k]

    # stop furado: fechou pior do que o stop mandava, ja fora o slippage -
    # ou seja, gap ou barra que abriu atravessada
    limite = sl_entrada + int(folga)
    por_stop = motivos == cod_stop
    furou = por_stop & (pontos < -limite) & (sl_entrada > 0)

    return {
        "desvio": float(liquido.std(ddof=1)),
        "var95": var,
        "cvar95": float(piores.mean()),
        "n_cauda": int(k),
        "maior_perda": float(liquido.min()),
        "perda_media": float(perdas.mean()) if len(perdas) else 0.0,
        "razao_pior_media": (float(liquido.min() / perdas.mean())
                             if len(perdas) and perdas.mean() else None),
        "stops_furados": int(furou.sum()),
        "pct_furados": (float(furou.sum() / por_stop.sum() * 100)
                        if por_stop.sum() else 0.0),
        "excesso_medio": (float(np.mean(-pontos[furou] - limite[furou]))
                          if furou.any() else 0.0),
    }


def ritmo(entry_ts: np.ndarray, liquido: np.ndarray, barras_em_posicao: int,
          barras_totais: int, pregoes_totais: int) -> dict:
    """A estratégia opera pouco e bem, ou muito e mal?

    Exposição é o contexto que falta a todo Sharpe: o mesmo número com 3% de
    tempo posicionado ou com 60% descreve estratégias que não se parecem em
    nada — inclusive no risco de um evento fora do horário.
    """
    if not len(liquido):
        return {}
    dias = entry_ts.astype("datetime64[D]")
    unicos, inv = np.unique(dias, return_inverse=True)
    por_dia = np.bincount(inv)
    soma_dia = np.zeros(len(unicos))
    np.add.at(soma_dia, inv, liquido)

    return {
        "exposicao_pct": (float(barras_em_posicao / barras_totais * 100)
                          if barras_totais else 0.0),
        "pregoes_operados": int(len(unicos)),
        "pregoes_totais": int(pregoes_totais),
        "pct_pregoes": (float(len(unicos) / pregoes_totais * 100)
                        if pregoes_totais else 0.0),
        "trades_por_dia": float(np.mean(por_dia)),
        "max_trades_dia": int(por_dia.max()),
        "dias_positivos": int((soma_dia > 0).sum()),
        "pct_dias_positivos": float((soma_dia > 0).mean() * 100),
        "melhor_dia": float(soma_dia.max()),
        "pior_dia": float(soma_dia.min()),
    }


def resultado_por_volume(entry_ts: np.ndarray, liquido: np.ndarray,
                         faixas=(1, 2, 3, 5, 10)) -> dict:
    """Resultado conforme QUANTOS trades houve naquele pregão.

    Dia de muitos sinais costuma ser dia de mercado picado. Se as faixas
    altas concentram prejuízo, um limite de operações por dia para de ser
    palpite e vira decisão com dado.
    """
    if not len(liquido):
        return {}
    dias = entry_ts.astype("datetime64[D]")
    unicos, inv = np.unique(dias, return_inverse=True)
    por_dia = np.bincount(inv)
    qtd_do_trade = por_dia[inv]

    # right=True: o trade de um dia com exatamente 3 operacoes pertence a
    # faixa que TERMINA em 3, nao a seguinte
    grupo = np.digitize(qtd_do_trade, np.array(faixas), right=True)

    nomes, ant = [], 0
    for b in faixas:
        nomes.append(f"{ant + 1}" if b == ant + 1 else f"{ant + 1}–{b}")
        ant = b
    nomes.append(f"{faixas[-1] + 1}+")

    g_unicos, g_inv = np.unique(grupo, return_inverse=True)
    k = len(g_unicos)
    total, ganho, perda = np.zeros(k), np.zeros(k), np.zeros(k)
    np.add.at(total, g_inv, liquido)
    np.add.at(ganho, g_inv, np.maximum(liquido, 0))
    np.add.at(perda, g_inv, np.minimum(liquido, 0))
    n = np.bincount(g_inv, minlength=k)
    vit = np.zeros(k)
    np.add.at(vit, g_inv, (liquido > 0).astype(float))

    return {
        "chaves": [nomes[int(g)] for g in g_unicos],
        "liquido": total.tolist(),
        "trades": n.tolist(),
        "expectativa": (total / np.maximum(n, 1)).tolist(),
        "ganhos": ganho.tolist(),
        "perdas": (-perda).tolist(),
        "win_rate": (vit / np.maximum(n, 1) * 100).tolist(),
    }
