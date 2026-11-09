"""Pesquisa: callbacks do Backtest (rodar, navegar, clique na tabela)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
from dash import ALL, Input, Output, State, ctx, no_update

from core import ativo as ativo_mod, metrics
from core import walkforward as wf
from core.engine.execution import ExecutionProfile, run_strategy
from core.optimizer import MINERACAO
from strategies import registry
from strategies.base import validate

from .. import data as D
from ..components import charts, results_grid, stats_cards

from .menu import _br, _dt, _runs, _simbolo


def register(app):
    # ------------------------------------------------------------------ rodar
    @app.callback(
        Output("store-run", "data"),
        Output("cards", "children"),
        Output("grid-trades", "rowData"),
        Output("grid-trades", "columnDefs"),
        Output("chart-capital", "series"),
        Output("chart-capital", "timeScaleAction"),
        Output("store-window", "data"),
        Output("meta-tempo", "children"),
        Input("btn-run", "n_clicks"),
        State("ativo", "value"),
        State("d-de", "date"), State("d-ate", "date"), State("e-timeframe", "value"),
        State({"type": "val", "p": ALL}, "value"),
        State({"type": "val", "p": ALL}, "id"),
        State("e-ent-ini", "value"), State("e-ent-fim", "value"),
        State("e-fechamento", "value"),         State("e-dias", "value"),
        State("e-direcao", "value"),
        State("e-filtro-adx", "value"),
        State("e-sem-ent1", "value"), State("e-sem-ent2", "value"),
        State("e-sem-ent3", "value"),
        State("e-alvo-tipo", "value"), State("e-stop-tipo", "value"),
        State("e-max-barras", "value"),
        State("e-lim-ganho", "value"), State("e-lim-perda", "value"),
        State("e-max-trades", "value"), State("e-max-loss", "value"),
        State("e-corretagem", "value"), State("e-emolumentos", "value"),
        State("e-slippage", "value"),
        State("e-modo", "value"), State("e-contratos", "value"),
        State("e-risco", "value"), State("e-capital", "value"),
        State("e-min-ops", "value"),
        State("excluir-holdout", "value"), State("wf-holdout", "value"),
        State("wf-treino", "value"), State("wf-teste", "value"),
        State("wf-passo", "value"),
        State("store-combinacao", "data"),
        prevent_initial_call=False,
    )
    def rodar(n, ativo, de, ate, tf, valores, ids_val, ent_ini, ent_fim, fechamento,
              dias, direcao, filtro, sem1, sem2, sem3, alvo_tipo, stop_tipo, max_barras,
              lim_ganho, lim_perda, max_trades, max_loss, corretagem,
              emolumentos, slippage, modo, contratos, risco, capital, min_ops,
              sem_holdout, holdout_m, treino_m, teste_m, passo_m, combinacao=None):
        v = {i["p"]: val for i, val in zip(ids_val, valores)}
        mod = registry.atual()
        # 0 e um valor legitimo (sem alvo); so o vazio cai no padrao
        razao = v.get("alvo_razao")
        razao = 2.0 if razao is None else razao

        try:
            params = validate(mod.params_schema,
                              {k: v.get(k) for k in mod.params_schema})
        except ValueError as erro:
            return no_update, stats_cards.vazio(str(erro)), [], no_update, [], no_update, "", no_update

        profile = ExecutionProfile(
            timeframe=tf or "M1",
            entrada_inicio=ent_ini or "09:00", entrada_fim=ent_fim or "17:00",
            fechamento=fechamento or "17:30",
            dias_semana=tuple(dias or (1, 2, 3, 4, 5)), direcao=direcao,
            sem_entrada1=sem1 or "", sem_entrada2=sem2 or "",
            sem_entrada3=sem3 or "",
            filtro_adx=filtro or "tendencia",
            # 0 e legitimo (desligado); so o vazio cai no padrao
            adx_periodo=v.get("adx_periodo") or 0,
            adx_limiar=v.get("adx_limiar") or 0,
            adx_filtro_di=v.get("adx_filtro_di") or 0,
            adx_subindo=v.get("adx_subindo") or 0,
            alvo_tipo=alvo_tipo, alvo_pontos=v.get("alvo_pontos") or 0,
            alvo_atr_periodo=v.get("alvo_atr_periodo") or 20,
            alvo_atr_mult=v.get("alvo_atr_mult") or 0,
            alvo_razao=razao, alvo_pct=v.get("alvo_pct") or 0,
            stop_tipo=stop_tipo, stop_pontos=v.get("stop_pontos") or 0,
            stop_atr_periodo=v.get("stop_atr_periodo") or 20,
            stop_atr_mult=v.get("stop_atr_mult") or 0,
            stop_pct=v.get("stop_pct") or 0,
            breakeven_pct=v.get("breakeven_pct") or 0,
            step_gatilho_pct=v.get("step_gatilho_pct") or 0,
            step_distancia_pct=v.get("step_distancia_pct") or 0,
            trailing_pontos=v.get("trailing_pontos") or 0,
            max_barras=max_barras or 0,
            limite_ganho_contrato=lim_ganho or 0, limite_perda_contrato=lim_perda or 0,
            max_trades_dia=max_trades or 0, max_prejuizos_dia=max_loss or 0,
            corretagem_por_contrato=corretagem or 0.0,
            emolumentos_por_contrato=emolumentos or 0.0,
            slippage_ticks=slippage or 0,
            modo_posicao=modo, contratos=contratos or 1,
            risco_por_trade=risco, capital_inicial=capital or 10_000.0,
            min_operacoes=min_ops or 0,
        )

        simbolo = _simbolo(ativo)
        erro_janela = ativo_mod.janela_valida(profile.entrada_inicio, profile.entrada_fim,
                                              ativo_mod.ficha(simbolo),
                                              profile.fechamento)
        if erro_janela:
            return no_update, stats_cards.vazio(erro_janela), [], no_update, [], no_update, "", no_update
        todas = D.bars(simbolo)
        de_dt, ate_dt = _dt(de), _dt(ate, True)

        # O corte do holdout é DERIVADO das datas, nunca gravado nelas -
        # e pela mesma função que a mineração usa, para os números baterem.
        cortado = False
        if sem_holdout:
            # Quando há uma mineração carregada, o corte é O DELA — gravado
            # junto com a varredura. Recalcular com os campos da tela usava
            # outro holdout e devolvia outro lucro para a MESMA combinação:
            # 6.165 na tabela contra 5.491 no card, porque a varredura tinha
            # rodado com holdout de 6 meses e a tela estava em 12.
            # só vale enquanto há uma varredura na tela; sem isso um corte
            # velho continuaria mandando num backtest avulso
            corte = (MINERACAO.estado.get("fim_otimizacao")
                     if MINERACAO.estado.get("trials") else None)
            # o campeão de uma Busca automática traz o corte DELA (com a
            # hora): a Varredura na memória é outra conta, com outro holdout
            if (combinacao or {}).get("origem") == "busca":
                corte = combinacao.get("corte")
            novo = None
            if corte:
                try:
                    novo = datetime.fromisoformat(str(corte)[:19])
                except ValueError:
                    novo = None
            if novo is None and (holdout_m or 0) > 0:
                janelas = wf.montar_janelas(
                    de_dt, ate_dt, treino_meses=treino_m or 12,
                    teste_meses=teste_m or 3, passo_meses=passo_m or 3,
                    holdout_meses=holdout_m,
                )
                novo = janelas.fim_otimizacao.astype("datetime64[s]").item()
            if novo is not None and de_dt < novo < ate_dt:
                ate_dt, cortado = novo, True
        corte = (todas["ts"] >= np.datetime64(de_dt)) & (todas["ts"] <= np.datetime64(ate_dt))
        bars = {k: val[corte] for k, val in todas.items()}
        if not len(bars["open"]):
            return no_update, stats_cards.vazio("Sem barras no período."), [], no_update, [], no_update, "", no_update

        t0 = time.perf_counter()
        try:
            res = run_strategy(bars, mod, params, profile, D.instrument(simbolo))
        except ValueError as erro:
            return no_update, stats_cards.vazio(str(erro)), [], no_update, [], no_update, "", no_update
        dinheiro = metrics.monetize(res)
        m = metrics.compute(res)
        ms = (time.perf_counter() - t0) * 1000

        # deixa explícito qual janela estes números cobrem: sem isso, comparar
        # o card com a linha da mineração é comparar coisas diferentes
        m["periodo"] = f"{_br(str(de)[:10])} → {_br(str(ate_dt)[:10])}"
        m["periodo_nota"] = ("mesma janela da mineração — holdout excluído"
                             if cortado else "base inteira, holdout incluído")

        token = f"r{n or 0}-{int(time.time() * 1000)}"
        _runs.clear()
        _runs[token] = {"res": res, "dinheiro": dinheiro, "profile": profile,
                "metrics": m, "simbolo": simbolo,
                # pregoes do PERIODO, nao os operados: a aba Detalhes
                # compara um com o outro para medir seletividade
                "pregoes": int(len(np.unique(
                    bars["ts"].astype("datetime64[D]"))))}

        equity = charts.equity_series(res.trades, dinheiro["liquido"], profile.capital_inicial)
        linhas = results_grid.rows(res.trades, dinheiro, ativo_mod.ficha(simbolo))

        fim_janela = bars["ts"][-1].astype("datetime64[s]").item()
        janela = {"de": (fim_janela - timedelta(days=5)).isoformat(),
                  "ate": fim_janela.isoformat(), "trade": None}

        # A curva nasce enquadrada no backtest inteiro, não no zoom que a
        # biblioteca escolhe. O nonce muda a cada execução: sem ele o segundo
        # backtest repetiria o mesmo comando e o componente o ignoraria,
        # deixando o gráfico no zoom que você tinha dado no anterior.
        enquadrar = {"action": "fitContent", "nonce": token}

        moeda = ativo_mod.moeda_de(simbolo)
        return ({"token": token, "n_trades": res.n_trades},
                stats_cards.render(m, moeda), linhas,
                results_grid.colunas(moeda), equity, enquadrar, janela,
                f"{ms:.0f} ms · {tf} · {len(bars['open']):,}".replace(",", ".") + " barras")

    # -------------------------------------------------------------- navegacao
    @app.callback(
        Output("store-window", "data", allow_duplicate=True),
        Input({"type": "rng", "dias": ALL}, "n_clicks"),
        State("store-window", "data"),
        State("ativo", "value"),
        prevent_initial_call=True,
    )
    def mudar_faixa(_, janela, ativo):
        if not ctx.triggered_id or not janela:
            return no_update
        dias = ctx.triggered_id["dias"]
        base, _fim = D.span(_simbolo(ativo))
        ate = datetime.fromisoformat(janela["ate"])
        de = base if dias == 0 else ate - timedelta(days=dias)
        return {**janela, "de": max(de, base).isoformat(), "trade": None}

    # ------------------------------------------- clique numa linha da tabela
    @app.callback(
        Output("store-window", "data", allow_duplicate=True),
        Input("grid-trades", "selectedRows"),
        State("store-window", "data"),
        prevent_initial_call=True,
    )
    def ir_para_trade(selecionadas, janela):
        if not selecionadas or not janela:
            return no_update
        linha = selecionadas[0]
        ent = datetime.fromisoformat(linha["t_ent"])
        sai = datetime.fromisoformat(linha["t_sai"])
        folga = max(timedelta(minutes=45), (sai - ent) * 2)
        return {"de": (ent - folga).isoformat(), "ate": (sai + folga).isoformat(),
                "trade": linha["idx"]}
