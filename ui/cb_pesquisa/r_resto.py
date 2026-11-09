"""Pesquisa: vencedora, diagnóstico, gráfico de preço e os outros arquivos de callbacks."""
from __future__ import annotations

from datetime import datetime

from dash import Input, Output, State, no_update

from dash import html

from core import analytics, ativo as ativo_mod
from core.engine import kernel as K
from core.engine.execution import TIMEFRAMES
from core import optimizer
from strategies import registry

from .. import data as D
from ..components import analytics_charts as AC
from ..components import charts
from ..components import detalhes_cards as DC
from ..components import wfa_panel as WP
from ..components import ficha as FI
from ..components import robustez_cards as RC

from .menu import _runs, _simbolo
from .base import _WFA, _detalhes, _referencias_operadas, _robustez


def register(app):
    # ------------------------------ os parâmetros da vencedora, no WFA
    @app.callback(
        Output("wfa-bt-titulo", "children"),
        Output("wfa-params", "children"),
        Input("grid-wfa-steps", "selectedRows"),
        Input("store-wfa", "data"),
    )
    def wfa_vencedora(linhas, store):
        """Os parâmetros de uma janela, ao lado da faixa que foi minerada.

        Sem linha escolhida, mostra os do **DEPLOY** — a última otimização,
        cujo OOS ainda não aconteceu, que é literalmente a configuração que
        se colocaria para operar hoje. Clicar numa linha das Janelas troca
        para a daquele passo.

        Não roda backtest nenhum. A versão anterior rodava um sobre a base
        inteira com esses parâmetros, e mostrava uma curva OTIMIZADA logo
        abaixo da fora da amostra — dois números de lucro para a mesma
        estratégia, e o maior deles era justamente o que não vale.
        """
        if (store or {}).get("fase") != "pronta" or not _WFA.get("passos"):
            return "", html.P("Rode o walk-forward para ver a vencedora.",
                              className="empty")

        escolhido = None
        if linhas:
            alvo = linhas[0].get("step")
            escolhido = next(
                (p for p in _WFA["passos"]
                 if ("DEPLOY" if p.janela.deploy else f"Step {p.janela.step}")
                 == alvo), None)
        if escolhido is None:
            escolhido = next((p for p in _WFA["passos"] if p.janela.deploy),
                             None)
        if escolhido is None:
            return "", html.P("Nenhuma janela no walk-forward.",
                              className="empty")

        # a mineração do CÁLCULO, e não a do seletor: trocar o seletor sem
        # executar juntava os parâmetros antigos com a faixa da mineração nova
        run_id = _WFA.get("run_id")
        d = optimizer.detalhes_salva(run_id) if run_id else None
        j = escolhido.janela
        titulo = html.Span([
            html.Strong("DEPLOY" if j.deploy else f"Step {j.step}"),
            f" · otimizada em {WP._br(j.is_de)} → {WP._br(j.is_ate)}",
            html.Span(" · esta é a configuração para operar hoje"
                      if j.deploy else
                      f" · testada em {WP._br(j.oos_de)} → {WP._br(j.oos_ate)}",
                      className="wfa-bt-nota"),
        ])
        if not escolhido.params:
            return titulo, html.P("Nenhuma combinação passou nos critérios "
                                  "nesta janela — a estratégia ficou fora do "
                                  "mercado.", className="empty")
        try:
            mod = registry.carregar(_WFA["strategy"])
        except Exception:
            mod = None
        geral = {
            "ativo": _WFA.get("symbol") or "—",
            "estratégia": (getattr(mod, "label", None) or _WFA["strategy"]),
            "mineração": (f"#{run_id} · {d['nome']}" if d and d.get("nome")
                          else f"#{run_id}"),
        }
        return titulo, FI.ficha(estrategia=mod, params=escolhido.params,
                                perfil=(d or {}).get("perfil", {}),
                                espaco=(d or {}).get("espaco", {}),
                                geral=geral,
                                moeda=ativo_mod.moeda_de(_WFA.get("symbol")))

    # ------------------------------------------------------------ diagnóstico
    @app.callback(
        Output("g-hora", "figure"), Output("g-dia", "figure"),
        Output("g-mes", "figure"), Output("g-calendario", "figure"),
        Output("g-maemfe", "figure"), Output("g-duracao", "figure"),
        Output("g-motivo", "figure"), Output("g-distribuicao", "figure"),
        Output("diag-sugestoes", "children"),
        Output("aba-detalhes", "children"),
        Output("aba-robustez", "children"),
        Input("store-run", "data"),
    )
    def diagnostico(store):
        """Os recortes que dizem O QUE MEXER na estratégia.

        Roda sobre os arrays que o backtest já devolveu — nenhum backtest
        novo. Por isso cabe atualizar tudo de uma vez, a cada execução.
        """
        # o store carrega {"token": ..., "n_trades": ...}, não o token cru
        run = _runs.get((store or {}).get("token", ""))
        if not run:
            v = AC._vazio()
            return v, v, v, v, v, v, v, v, "", DC.vazio(
                "Rode um backtest para ver os detalhes."), RC.vazio()

        res, liq = run["res"], run["dinheiro"]["liquido"]
        p = run["profile"]
        f = ativo_mod.ficha(run.get("simbolo") or _simbolo(None))
        moeda = ativo_mod.moeda_de(run.get("simbolo"))
        t = ativo_mod.trades_para_exibir(res.trades, f)

        diag = analytics.calor_mae_mfe(t["mae"], t["mfe"], liq)
        stop_ref, alvo_ref = _referencias_operadas(res, p, f)
        dicas = analytics.sugestoes(diag, stop_ref, alvo_ref)

        return (
            AC.ganho_perda(analytics.por_hora(res.trades["entry_ts"], liq, f),
                           "Lucro × prejuízo por hora de entrada", moeda),
            AC.ganho_perda(analytics.por_dia_semana(res.trades["entry_ts"], liq),
                           "Lucro × prejuízo por dia da semana", moeda),
            AC.ganho_perda(analytics.por_mes(res.trades["entry_ts"], liq),
                           "Lucro × prejuízo por mês do ano", moeda),
            AC.calendario(analytics.calendario_mensal(res.trades["entry_ts"], liq),
                          moeda=moeda),
            AC.mae_mfe(diag, stop_ref, alvo_ref, moeda),
            AC.barras(analytics.por_duracao(t["bars_held"], liq,
                                            TIMEFRAMES.get(p.timeframe, 1)),
                      f"Lucro por tempo em posição (barras {p.timeframe})",
                      moeda=moeda),
            AC.barras(analytics.por_motivo(t["reason"], liq, K.EXIT_LABELS),
                      "Lucro por motivo de saída", com_expectativa=False,
                      moeda=moeda),
            AC.histograma(analytics.distribuicao(liq), moeda=moeda),
            [html.P(d, className="dica") for d in dicas],
            _detalhes(res, run, liq, f),
            _robustez(res, run, liq),
        )

    # ------------------------------------------------------- grafico de preco
    @app.callback(
        Output("chart-preco", "series"),
        Output("chart-preco", "timeScaleAction"),
        Output("chart-info", "children"),
        Output("tf-info", "children"),
        Input("store-window", "data"),
        Input("tf", "value"),
        State("store-run", "data"),
        State("ativo", "value"),
    )
    def desenhar(janela, tf, run, ativo):
        if not janela:
            return [], no_update, "", ""

        de = datetime.fromisoformat(janela["de"])
        ate = datetime.fromisoformat(janela["ate"])
        simbolo = _simbolo(ativo)
        dados = D.candles(simbolo, de, ate, tf or "auto")
        if not dados["candles"]:
            return [], no_update, "sem barras nesta janela", ""

        marcas, linhas, nota = [], [], ""
        if run and run.get("token") in _runs:
            r = _runs[run["token"]]
            fr = ativo_mod.ficha(r.get("simbolo") or simbolo)
            t0 = dados["candles"][0]["time"]
            t1 = dados["candles"][-1]["time"]
            marcas = charts.trade_markers(r["res"].trades, t0, t1, f=fr,
                                          d1=dados["timeframe"] == "D1")
            i = janela.get("trade")
            if i is not None:
                linhas = charts.trade_price_lines(r["res"], i, fr)
                nota = f"trade #{i + 1} em foco"
            else:
                nota = f"{len(marcas) // 2} operações nesta janela"

        ficha = ativo_mod.ficha(simbolo)
        de_x = ativo_mod.hora_para_exibir(de, ficha)
        ate_x = ativo_mod.hora_para_exibir(ate, ficha)
        info = (f"{de_x:%d/%m/%Y %H:%M} — {ate_x:%d/%m/%Y %H:%M}"
                + (f" · {nota}" if nota else ""))
        # enquadra a janela que acabou de ser carregada, em vez de herdar o
        # zoom da anterior; o nonce e a propria janela, entao trocar de faixa
        # ou de timeframe reenquadra
        enquadrar = {"action": "fitContent",
                     "nonce": f"{janela['de']}|{janela['ate']}|{tf}"}
        return (charts.price_series(dados, marcas, linhas, simbolo), enquadrar, info,
                f"{dados['timeframe']} · {len(dados['candles'])} candles")

    from ui import callbacks_candidata
    callbacks_candidata.register(app)

    from ui import callbacks_busca
    callbacks_busca.register(app)

    from ui import callbacks_estrategias
    callbacks_estrategias.register(app)

    from ui import callbacks_portfolio
    callbacks_portfolio.register(app)

    from ui import callbacks_ao_vivo
    callbacks_ao_vivo.register(app)

    from ui import callbacks_pregao
    callbacks_pregao.register(app)

    from ui import callbacks_operacao
    callbacks_operacao.register(app)

    from ui import callbacks_ordens
    callbacks_ordens.register(app)
