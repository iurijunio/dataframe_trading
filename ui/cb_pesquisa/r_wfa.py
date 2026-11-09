"""Pesquisa: callbacks do Walk-Forward (rodar e montar)."""
from __future__ import annotations

from dash import Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

from dash import html

from core import analytics, ativo as ativo_mod, candidata, codigo
from core import wfa
from core import wfa_runner
from core.wfa_runner import VARREDURA
from core import optimizer
from strategies import registry

from .. import data as D
from ..components import analytics_charts as AC
from ..components import wfa_panel as WP

from .menu import _ativo_ao_entrar_wfa, _n, _simbolo
from .base import _WFA, _criterios_wfa


def register(app):
    # ================================================== WALK-FORWARD (WFA)
    @app.callback(
        Output("wfa-estrategia", "options"), Output("wfa-estrategia", "value"),
        Input("modo", "value"),
        State("wfa-estrategia", "value"),
    )
    def wfa_estrategias(qual, atual):
        """A lista de estratégias, montada ao entrar no modo."""
        if qual != "wfa":
            return no_update, no_update
        opts = [{"label": e["label"], "value": e["modulo"]}
                for e in registry.descobrir()]
        # depois de um F5 a tela volta vazia, mas a varredura continua na
        # memória: a estratégia DELA vem antes da que está no Backtest
        na_memoria = VARREDURA.estado.get("estrategia")
        if not atual and any(o["value"] == na_memoria for o in opts):
            atual = na_memoria
        return opts, atual or registry.nome_atual()

    @app.callback(
        Output("wfa-ativo", "options"), Output("wfa-ativo", "value"),
        Input("modo", "value"),
        State("ativo", "value"),
        State("wfa-mineracao", "value"),
        State("wfa-ativo", "value"),
    )
    def wfa_ativo_ao_entrar(qual, do_menu, aberta, atual):
        """O ativo do Walk-Forward, escolhido ao entrar no modo.

        Só escreve no seletor daqui: o do menu continua sendo do Backtest e
        da Mineração, e trocar este não o mexe."""
        if qual != "wfa":
            return no_update, no_update
        opts = D.opcoes_ativo()
        valor = _ativo_ao_entrar_wfa(do_menu, aberta, {o["value"] for o in opts})
        return opts, (no_update if valor == atual else valor)

    @app.callback(
        Output("wfa-mineracao", "options"), Output("wfa-mineracao", "value"),
        Input("wfa-estrategia", "value"),
        Input("wfa-ativo", "value"),
        State("wfa-mineracao", "value"),
    )
    def wfa_mineracoes(estrategia, ativo, atual):
        """Minerações salvas DA estratégia escolhida, no ativo escolhido.

        O espaço de busca que o walk-forward reotimiza vem da mineração: é
        ela que gravou as faixas de cada parâmetro. Por isso a lista é
        filtrada — uma varredura de rompimento de canal não tem espaço que
        sirva a um cruzamento de médias, nem uma do MES ao WIN.
        """
        if not estrategia or not ativo:
            return [], None
        salvas = optimizer.listar_salvas(estrategia, simbolo=ativo)
        opts = [{"label": s["rotulo"], "value": s["run_id"]} for s in salvas]
        # a que já está escolhida fica, se for desta estratégia: é o caso de
        # um walk-forward salvo que acabou de escrever estratégia e mineração
        # juntas. Sem ela, vem a mais recente — o passo seguinte é sempre
        # "Executar", e obrigar a abrir o menu para a única opção é atrito.
        if any(o["value"] == atual for o in opts):
            return opts, atual
        # depois de um F5, a que está NA MEMÓRIA vale mais que a mais recente:
        # é ela que a barra de progresso está mostrando
        na_memoria = VARREDURA.estado.get("run_id")
        if any(o["value"] == na_memoria for o in opts):
            return opts, na_memoria
        return opts, (opts[0]["value"] if opts else None)

    @app.callback(
        Output("wfa-trava-varredura", "className"),
        Output("wfa-prog", "className"),
        Output("wfa-prog-txt", "children"),
        Output("wfa-prog-pct", "children"),
        Output("wfa-prog-bar", "style"),
        Output("btn-wfa", "disabled"),
        Output("wfa-veu", "className"),
        Output("wfa-veu-txt", "children"),
        Input("wfa-mineracao", "value"),
        Input("tick", "n_intervals"),
        Input("btn-wfa", "n_clicks"),
        Input("store-wfa", "data"),
    )
    def wfa_progresso(run_id, _t, _n, _store):
        """A barra, o botão e o véu da matriz, todos lidos do mesmo estado.

        Um callback só para os três de propósito: se o botão fosse liberado
        por um e o véu apagado por outro, haveria um instante com o botão
        clicável e a varredura ainda correndo.

        Ele cuida da VARREDURA, que roda em thread e só se enxerga pelo
        relógio. O cálculo das janelas e da matriz, que são callbacks, trava
        a tela pelo `running=` de cada um.
        """
        import time as _time

        est = WP.estado_progresso({**VARREDURA.estado, "agora": _time.time()},
                                  run_id, wfa_runner.TETO_MB)
        ocupado = est["ocupado"]
        return ("wfa-trava" + (" on" if ocupado else ""),
                f"wfa-prog {est['fase']}",
                est["txt"], est["pct_txt"],
                {"width": f"{est['pct']:.1f}%"},
                ocupado or not run_id,
                "veu on" if est["veu"] else "veu",
                est["veu"] or "")

    @app.callback(
        Output("store-varredura", "data"),
        Input("tick", "n_intervals"),
        State("store-varredura", "data"),
        prevent_initial_call=True,
    )
    def wfa_fim_da_varredura(_t, anunciada):
        """Anuncia o fim da varredura UMA vez, com a geração dela.

        O cálculo das janelas escuta este Store, e não o relógio: com o
        relógio, cada batida que caía durante o cálculo disparava outro, o
        servidor enfileirava e a barra congelava esperando.

        Callback à parte, e não uma saída da barra, para não fechar um CICLO:
        a barra ouve `store-wfa`, que o cálculo escreve. Se a barra também
        escrevesse o que dispara o cálculo, o Dash (sem debug) não acusa o
        ciclo — só para de atualizar a tela.
        """
        e = VARREDURA.estado
        if (e["rodando"] or not e["pronto"] or e["entregue"]
                or (anunciada or {}).get("g") == e.get("geracao")):
            raise PreventUpdate
        return {"g": e.get("geracao"), "run": e.get("run_id")}

    @app.callback(
        Output("wfa-info", "children"),
        Output("g-wfa-curva", "figure"),
        Output("wfa-kpis", "children"),
        Output("grid-wfa-steps", "rowData"),
        Output("wfa-resumo", "children"),
        Output("wfa-veredito", "children"),
        Output("wfa-drift", "children"),
        Output("g-wfa-fita", "figure"),
        Output("wfa-cards-mes", "children"),
        Output("g-wfa-mes", "figure"), Output("g-wfa-dia", "figure"),
        Output("g-wfa-hora", "figure"),
        Output("grid-wfa-trades", "rowData"),
        Output("store-wfa", "data"),
        Input("btn-wfa", "n_clicks"),
        Input("store-varredura", "data"),
        Input("store-wfa-carregar", "data"),
        Input("wfa-is", "value"), Input("wfa-oos", "value"),
        Input("wfa-inteligencia", "value"),
        Input("wfa-holdout", "value"),
        Input("wfa-travar-camada4", "value"),
        State("wfa-mineracao", "value"),
        State("ativo", "value"),
        State("store-wfa", "data"),
        prevent_initial_call=True,
        # enquanto calcula: controles travados e véu na matriz. O véu só
        # aparece se o cálculo passar de um quarto de segundo (é o CSS que
        # espera).
        running=[(Output("wfa-trava-janelas", "className"),
                  "wfa-trava on", "wfa-trava"),
                 (Output("wfa-veu-janelas", "className"), "veu on", "veu")],
    )
    def wfa_executar(_n, _fim, _carregado, is_m, oos_m, inteligencia, holdout,
                     travar, run_id, ativo, store_atual):
        """Monta o walk-forward da configuração aberta sobre o cache.

        Trocar IS, OOS ou a inteligência NÃO roda backtest de novo: o cache
        de trades já está na memória, e cada janela é uma máscara sobre ele.

        Três regras que vieram de travamentos reais:

          - NÃO escuta o relógio. O fim da varredura chega por
            `store-varredura`, que muda uma vez só (a versão pelo relógio
            entrava num laço que não saía mais).
          - QUALQUER saída marca o resultado como entregue — sucesso, aviso
            ou exceção. Só o caminho de sucesso marcava, e um F5 no meio da
            varredura (mineração vazia na tela recarregada) deixava a barra
            em "montando as janelas…" para sempre, com o Executar desligado.
          - Varredura só começa por PEDIDO: o Executar ou um walk-forward
            salvo. Antes, trocar de mineração no meio de uma varredura fazia
            o fim dela disparar outra, sem clique nenhum.
        """
        e = VARREDURA.estado
        if ctx.triggered_id == "store-varredura" and e["entregue"]:
            raise PreventUpdate

        v = AC._vazio("Rode o walk-forward.")
        vazio = (WP.curva([], [], [], [], 0.0), WP.kpis([], [], [], {}, 0.0),
                 [], "", html.Div(), html.Div(), v, html.Div(), v, v, v, [],
                 no_update)
        try:
            return _wfa_montar(ctx.triggered_id, _n, is_m, oos_m, inteligencia,
                               holdout, travar, run_id, ativo, store_atual, vazio)
        except PreventUpdate:
            raise
        except Exception as erro:          # banco travado, mineração corrompida…
            return (f"falhou ao montar o walk-forward: {erro}", *vazio)
        finally:
            if not e["rodando"] and e["pronto"]:
                e["entregue"] = True

    def _regiao_de_hoje(run_id, espaco, passos, moeda="BRL"):
        """O bloco "Parâmetros de hoje: a região é larga?", com a conta da
        Candidata sobre os trials que a própria mineração gravou — os mesmos
        que a Candidata carrega (`optimizer.carregar_salva`)."""
        linha = next((p for p in passos if p.janela.deploy), None)
        if linha is None or not linha.params:
            return WP.regiao_larga(None, None, run_id, sem_deploy=linha is None,
                                   moeda=moeda)
        perfil = candidata.perfil_plato(optimizer.carregar_salva(run_id),
                                        espaco or {}, linha.params)
        return WP.regiao_larga(perfil, candidata.portoes_plato(perfil), run_id,
                               moeda=moeda)

    def _wfa_montar(gatilho, _n, is_m, oos_m, inteligencia, holdout, travar,
                    run_id, ativo, store_atual, vazio):
        e = VARREDURA.estado
        if not run_id:
            return ("escolha uma mineração salva", *vazio)

        d = optimizer.detalhes_salva(run_id)
        if not d:
            return ("mineração não encontrada — ela pode ter sido excluída", *vazio)

        if e["rodando"]:
            return ("", *vazio)

        simbolo = d.get("symbol") or _simbolo(ativo)
        # o cache serve se é desta mineração, NESTE ativo
        serve = (e["pronto"] and e["run_id"] == run_id
                 and e.get("simbolo") == simbolo)
        pediu = gatilho in ("btn-wfa", "store-wfa-carregar")
        if not serve:
            if not pediu:
                return (("a mineração mudou — clique em Executar"
                         if e.get("run_id") not in (None, run_id)
                         else "clique em Executar para varrer esta mineração"),
                        *vazio)
            # A varredura vai até o FIM DA BASE, inclusive sobre o holdout:
            # ter os trades em memória faz o botão "estender ao holdout"
            # responder na hora, sem varredura nova. `argumentos_da_mineracao`
            # é a mesma função que o executor de testes completos da
            # Candidata usa para reproduzir esta mineração — uma fonte só.
            VARREDURA.iniciar(**wfa_runner.argumentos_da_mineracao(
                run_id, ativo=simbolo))
            # a geração da varredura faz o Store MUDAR — é isso que acorda o
            # relógio; um valor repetido não acordaria nada
            return ("", *vazio[:-1],
                    {"fase": "varrendo", "g": VARREDURA.estado.get("geracao")})

        cache = VARREDURA.cache
        if not cache:
            return ("", *vazio)

        capital = float(e["capital"] or 10_000.0)
        estende = "on" in (holdout or [])
        fim = e["ate"] if estende else e["ate_holdout"]
        janelas = wfa.montar_janelas(e["de"], fim, int(is_m or 12),
                                     int(oos_m or 6))
        if not janelas:
            return (f"a base não cabe IS {is_m} + OOS {oos_m} meses — reduza "
                    "a janela", *vazio)

        qual = inteligencia or "centroide_mediana"
        crit, origem_crit = _criterios_wfa(d, e)
        # a camada 4 travada: a primeira janela escolhe stop, alvo e
        # proteções, e as seguintes ficam com eles (ver `wfa.rodar`)
        travados = (set(wfa_runner.CAMPOS_EXECUCAO_NOMES)
                    if "on" in (travar or []) else None)
        passos = wfa.rodar(cache, janelas, capital, qual, crit,
                           travar_execucao=travados)
        # o que ESTA configuração travou, para a matriz das 12 usar o mesmo
        # stop em todas as células em vez de cada uma aprender o seu
        camada4_valores = None
        if travados:
            operou = next((p for p in passos if p.params), None)
            camada4_valores = (
                {k: v for k, v in operou.params.items() if k in travados}
                if operou else None)
        oos = wfa.trades_oos_campos(cache, passos,
                                    ("entry_ts", "exit_ts", "liquido", "custo"))
        ts, liq, steps = oos["entry_ts"], oos["liquido"], oos["step"]
        # o Sharpe agrega pela SAÍDA — mesma convenção de metrics.resumo e
        # wfa_store.serie_diaria — para não divergir do cartão de KPI
        ag = wfa.agregar(passos, capital, liq, ts, oos["exit_ts"])
        # o contrafactual: a faixa de TODAS as combinações fixas da região no
        # mesmo intervalo — reotimizar só vale se a curva sair de cima dela
        fixas = wfa.faixa_fixas(cache, janelas, capital)
        ver = wfa.portoes_wfa(ag, passos, capital)
        mes = wfa.mensal(ts, liq, wfa.meses_oos(passos))

        rotulo = next((r for r, x in wfa.INTELIGENCIAS if x == inteligencia),
                      inteligencia)
        _WFA.update(run_id=run_id, symbol=simbolo,
                    strategy=d["estrategia"], is_meses=int(is_m or 12),
                    oos_meses=int(oos_m or 6), inteligencia=qual,
                    holdout=estende, agregado=ag, veredito=ver, passos=passos,
                    capital=capital, camada4_travada=travados is not None,
                    camada4_valores=camada4_valores,
                    # impressão digital do código NO MOMENTO DA CORRIDA: se o
                    # arquivo mudar até o Salvar, o registro deve dizer com
                    # qual código o número foi de fato medido
                    codigo_hash=codigo.hash_estrategia(d["estrategia"]),
                    deploy=next((p.params for p in passos if p.janela.deploy),
                                None))
        # O Store só é regravado quando MUDA. O dcc.Store redispara quem o
        # ouve a cada escrita, mesmo com o mesmo valor — e cada clique em
        # IS/OOS refazia a matriz, a lista de salvos e a ficha à toa.
        # a configuração aberta entra na marca: a ficha e a lista de salvos
        # precisam acordar quando ELA muda — e só quando ela muda
        marca = {"fase": "pronta", "run": e["run_id"], "g": e.get("geracao"),
                 "n": len(cache),
                 "cfg": f"{is_m}-{oos_m}-{qual}-{int(estende)}"}
        moeda = ativo_mod.moeda_de(simbolo)
        return ("",
                WP.curva(ts, liq, steps, passos, capital, fixas,
                         holdout_de=e["ate_holdout"] if estende else None,
                         moeda=moeda),
                WP.kpis(passos, ts, liq, ag, capital,
                        custo=oos["custo"], saida=oos["exit_ts"],
                        moeda=moeda),
                WP.linhas_steps(passos, d["espaco"]),
                f"{ag.get('steps', 0)} janelas · IS {is_m}/OOS {oos_m} · {rotulo}"
                + (" · holdout incluído" if estende else " · até o holdout")
                + f" · {origem_crit} · {simbolo}",
                html.Div([WP.selo(ver, moeda=moeda),
                          _regiao_de_hoje(run_id, d["espaco"], passos,
                                          moeda)]),
                WP.drift_figs(wfa.drift(passos, d["espaco"])),
                WP.fita(passos, moeda),
                WP.cards_mensais(mes, moeda),
                WP.mensal_fig(mes, moeda),
                AC.ganho_perda(analytics.por_dia_semana(ts, liq),
                               "Lucro × prejuízo por dia da semana (OOS)",
                               moeda=moeda),
                AC.ganho_perda(analytics.por_hora(ts, liq, ativo_mod.ficha(simbolo)),
                               "Lucro × prejuízo por hora de entrada (OOS)",
                               moeda=moeda),
                WP.linhas_trades(ts, liq, steps, capital,
                                 saida=oos["exit_ts"], custo=oos["custo"],
                                 f=ativo_mod.ficha(simbolo)),
                marca if marca != store_atual else no_update)
