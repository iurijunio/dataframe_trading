"""O kernel: um laco sobre as barras, compilado com Numba.

Este e o unico lugar do projeto que decide o que acontece numa operacao.
Estrategia nao sabe o que e custo, horario, stop ou tamanho de posicao -
so devolve sinais. Tudo o que e execucao esta aqui.

REGRAS DE EXECUCAO (explicitas de proposito - sao elas que separam um
backtest honesto de um bonito):

1. Sinal lido na barra i so executa na ABERTURA da barra i+1. A trava de
   look-ahead e do motor, nao da estrategia.

2. Janela de ENTRADA e horario de FECHAMENTO sao coisas diferentes. Entre um
   e outro a posicao segue viva, mas nenhuma nova e aberta.

3. Stop e alvo sao verificados dentro da barra, contra high e low. Quando os
   dois cabem na mesma barra, o dado OHLC nao diz qual veio primeiro:
   assume-se o STOP (pessimista) e a barra e contada em `ambiguous`.

4. Gap atravessando o nivel preenche na ABERTURA, nao no nivel. Um stop de
   200 pontos nao protege contra um gap de 500.

5. As tres protecoes (breakeven, stop movel e trailing) atualizam no FIM da
   barra e SO MELHORAM o stop, nunca o afrouxam. Usar o high da propria
   barra para mover o stop e depois testar o low dela seria look-ahead
   intrabarra.

6. Stop, alvo e gatilhos de protecao chegam como ARRAYS por barra e sao
   congelados no valor que tinham na barra de entrada. E isso que permite
   stop em ATR sem o kernel saber o que e ATR.

7. O kernel devolve trades em PONTOS. Dinheiro, contratos e capital entram
   depois, em metrics.py.
"""

from __future__ import annotations

import numpy as np
from numba import njit

EXIT_STOP = 0
EXIT_TARGET = 1
EXIT_SIGNAL = 2
EXIT_CLOSE_TIME = 3  # horario de fechamento de posicoes
EXIT_MAXBARS = 4
EXIT_DATA_END = 5

EXIT_LABELS = {
    EXIT_STOP: "stop",
    EXIT_TARGET: "alvo",
    EXIT_SIGNAL: "sinal",
    EXIT_CLOSE_TIME: "fechamento",
    EXIT_MAXBARS: "tempo maximo",
    EXIT_DATA_END: "fim dos dados",
}

BLOQUEIO_LABELS = {
    0: "—",
    1: "limite de operacoes",
    2: "limite de prejuizos",
    3: "perda maxima do dia",
    4: "ganho maximo do dia",
}


@njit(cache=True, inline="always")
def _fill(px, side, slippage, is_entry):
    """Slippage sempre contra o operador."""
    if (side == 1) == is_entry:
        return px + slippage
    return px - slippage


@njit(cache=True, inline="always")
def _melhora(stop_atual, candidato, side):
    """Protecao so aperta o stop; nunca afrouxa."""
    if stop_atual == 0:
        return candidato
    if side == 1:
        return candidato if candidato > stop_atual else stop_atual
    return candidato if candidato < stop_atual else stop_atual


# nogil=True: o laco nao toca em objeto Python nenhum, entao pode soltar o
# GIL. E isso que deixa a mineracao paralelizar com threads em vez de
# processos - sem recarregar as barras nem repicklar nada por worker.
@njit(cache=True, nogil=True)
def run(
    open_, high, low, close,
    in_entry_window, is_close_time, day_id,
    entry_long, entry_short, exit_long, exit_short,
    sl_points, tp_points, be_trigger, step_trigger, step_dist, trail_dist,
    allow_long, allow_short,
    max_trades_day, max_losses_day, daily_stop, daily_target,
    max_bars, slippage,
    o_entry_i, o_exit_i, o_side, o_entry_px, o_exit_px,
    o_reason, o_mae, o_mfe, o_points,
):
    n = open_.shape[0]

    pos = 0
    entry_i = 0
    entry_px = 0
    stop_px = 0
    tgt_px = 0
    best = 0
    mae = 0
    mfe = 0
    # gatilhos congelados na entrada
    t_be = 0
    t_step = 0
    d_step = 0
    d_trail = 0

    n_trades = 0
    ambiguous = 0
    bloqueios = 0

    cur_day = -1
    trades_today = 0
    losses_today = 0
    pnl_today = 0
    blocked = 0

    pend_entry = 0
    pend_exit = False

    for i in range(n):
        if day_id[i] != cur_day:
            cur_day = day_id[i]
            trades_today = 0
            losses_today = 0
            pnl_today = 0
            blocked = 0

        # ---------------------------------------- 1. saida por sinal, na abertura
        if pos != 0 and pend_exit:
            px = _fill(open_[i], pos, slippage, False)
            pts = pos * (px - entry_px)
            o_entry_i[n_trades] = entry_i
            o_exit_i[n_trades] = i
            o_side[n_trades] = pos
            o_entry_px[n_trades] = entry_px
            o_exit_px[n_trades] = px
            o_reason[n_trades] = EXIT_SIGNAL
            o_mae[n_trades] = mae
            o_mfe[n_trades] = mfe
            o_points[n_trades] = pts
            n_trades += 1
            trades_today += 1
            if pts < 0:
                losses_today += 1
            pnl_today += pts
            pos = 0
            if max_trades_day > 0 and trades_today >= max_trades_day:
                blocked = 1
            elif max_losses_day > 0 and losses_today >= max_losses_day:
                blocked = 2
            elif daily_stop < 0 and pnl_today <= daily_stop:
                blocked = 3
            elif daily_target > 0 and pnl_today >= daily_target:
                blocked = 4
            if blocked != 0:
                bloqueios += 1
        pend_exit = False

        # ------------------------------------------ 2. entrada, na abertura
        if pos == 0 and pend_entry != 0 and in_entry_window[i] and blocked == 0:
            pos = pend_entry
            entry_i = i
            entry_px = _fill(open_[i], pos, slippage, True)
            sl = sl_points[i]
            tp = tp_points[i]
            stop_px = entry_px - pos * sl if sl > 0 else 0
            tgt_px = entry_px + pos * tp if tp > 0 else 0
            best = entry_px
            mae = 0
            mfe = 0
            t_be = be_trigger[i]
            t_step = step_trigger[i]
            d_step = step_dist[i]
            d_trail = trail_dist[i]
        pend_entry = 0

        # ------------------------------------------- 3. gestao dentro da barra
        if pos != 0:
            if pos == 1:
                up = high[i] - entry_px
                dn = low[i] - entry_px
            else:
                up = entry_px - low[i]
                dn = entry_px - high[i]
            if up > mfe:
                mfe = up
            if dn < mae:
                mae = dn

            hit_stop = False
            hit_tgt = False
            if pos == 1:
                if stop_px > 0 and low[i] <= stop_px:
                    hit_stop = True
                if tgt_px > 0 and high[i] >= tgt_px:
                    hit_tgt = True
            else:
                if stop_px > 0 and high[i] >= stop_px:
                    hit_stop = True
                if tgt_px > 0 and low[i] <= tgt_px:
                    hit_tgt = True

            if hit_stop and hit_tgt:
                ambiguous += 1
                hit_tgt = False  # pessimista: o stop vem primeiro

            if hit_stop or hit_tgt:
                if hit_stop:
                    lvl = stop_px
                    reason = EXIT_STOP
                else:
                    lvl = tgt_px
                    reason = EXIT_TARGET
                if pos == 1:
                    raw = open_[i] if (
                        (hit_stop and open_[i] < lvl) or (hit_tgt and open_[i] > lvl)
                    ) else lvl
                else:
                    raw = open_[i] if (
                        (hit_stop and open_[i] > lvl) or (hit_tgt and open_[i] < lvl)
                    ) else lvl

                px = _fill(raw, pos, slippage, False)
                pts = pos * (px - entry_px)
                o_entry_i[n_trades] = entry_i
                o_exit_i[n_trades] = i
                o_side[n_trades] = pos
                o_entry_px[n_trades] = entry_px
                o_exit_px[n_trades] = px
                o_reason[n_trades] = reason
                o_mae[n_trades] = mae
                o_mfe[n_trades] = mfe
                o_points[n_trades] = pts
                n_trades += 1
                trades_today += 1
                if pts < 0:
                    losses_today += 1
                pnl_today += pts
                pos = 0
                if max_trades_day > 0 and trades_today >= max_trades_day:
                    blocked = 1
                elif max_losses_day > 0 and losses_today >= max_losses_day:
                    blocked = 2
                elif daily_stop < 0 and pnl_today <= daily_stop:
                    blocked = 3
                elif daily_target > 0 and pnl_today >= daily_target:
                    blocked = 4
                if blocked != 0:
                    bloqueios += 1
            else:
                # --- protecoes: so no fim da barra, e so apertando o stop
                if t_be > 0 and mfe >= t_be:
                    stop_px = _melhora(stop_px, entry_px, pos)
                if t_step > 0 and mfe >= t_step:
                    stop_px = _melhora(stop_px, entry_px + pos * d_step, pos)
                if d_trail > 0:
                    if pos == 1:
                        if high[i] > best:
                            best = high[i]
                        stop_px = _melhora(stop_px, best - d_trail, pos)
                    else:
                        if low[i] < best:
                            best = low[i]
                        stop_px = _melhora(stop_px, best + d_trail, pos)

        # -------------------- 4. encerramento forcado: horario, tempo ou fim dos dados
        if pos != 0:
            force = False
            reason = EXIT_CLOSE_TIME
            if is_close_time[i]:
                force = True
            elif max_bars > 0 and (i - entry_i) >= max_bars:
                force = True
                reason = EXIT_MAXBARS
            elif i == n - 1:
                force = True
                reason = EXIT_DATA_END

            if force:
                px = _fill(close[i], pos, slippage, False)
                pts = pos * (px - entry_px)
                o_entry_i[n_trades] = entry_i
                o_exit_i[n_trades] = i
                o_side[n_trades] = pos
                o_entry_px[n_trades] = entry_px
                o_exit_px[n_trades] = px
                o_reason[n_trades] = reason
                o_mae[n_trades] = mae
                o_mfe[n_trades] = mfe
                o_points[n_trades] = pts
                n_trades += 1
                trades_today += 1
                if pts < 0:
                    losses_today += 1
                pnl_today += pts
                pos = 0
                if max_trades_day > 0 and trades_today >= max_trades_day:
                    blocked = 1
                elif max_losses_day > 0 and losses_today >= max_losses_day:
                    blocked = 2
                elif daily_stop < 0 and pnl_today <= daily_stop:
                    blocked = 3
                elif daily_target > 0 and pnl_today >= daily_target:
                    blocked = 4

        # ------------------------------ 5. sinais desta barra, para a proxima
        if pos != 0:
            if (pos == 1 and exit_long[i]) or (pos == -1 and exit_short[i]):
                pend_exit = True
        elif (in_entry_window[i] and blocked == 0 and i + 1 < n
              and in_entry_window[i + 1] and day_id[i + 1] == day_id[i]):
            # A ordem a mercado entra na barra seguinte - que, num sinal
            # fechado no ultimo minuto de um candle de 15, e exatamente a
            # abertura do proximo candle de 15.
            # Duas travas: a proxima barra tem que estar na janela de entrada
            # e ser do MESMO pregao. Sem a segunda, um sinal no fim do dia
            # abriria posicao na abertura do dia seguinte.
            if entry_long[i] and allow_long:
                pend_entry = 1
            elif entry_short[i] and allow_short:
                pend_entry = -1

    return n_trades, ambiguous, bloqueios


def allocate_outputs(n: int) -> dict:
    """Buffers de saida. O kernel nunca aloca - Numba fica mais rapido e o
    consumo de memoria da mineracao fica previsivel."""
    return {
        "entry_i": np.empty(n, dtype=np.int64),
        "exit_i": np.empty(n, dtype=np.int64),
        "side": np.empty(n, dtype=np.int64),
        "entry_px": np.empty(n, dtype=np.int64),
        "exit_px": np.empty(n, dtype=np.int64),
        "reason": np.empty(n, dtype=np.int64),
        "mae": np.empty(n, dtype=np.int64),
        "mfe": np.empty(n, dtype=np.int64),
        "points": np.empty(n, dtype=np.int64),
    }
