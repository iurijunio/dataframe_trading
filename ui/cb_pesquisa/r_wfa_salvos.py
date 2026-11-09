"""Pesquisa: matriz do Walk-Forward, excluir e salvar."""
from __future__ import annotations

from dash import Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

from core import codigo
from core import wfa
from core import wfa_store
from core import wfa_runner
from core.wfa_runner import VARREDURA
from core import optimizer
from core.optimizer import MINERACAO
from strategies import registry

from ..components import wfa_matriz as WM

from .base import SCHEMA_EXECUCAO, _MATRIZ_LOCK, _WFA, _chave_matriz, _criterios_wfa


def register(app):
    # ------------------------------------------- a matriz das 12 configurações
    @app.callback(
        Output("store-matriz", "data"),
        Input("store-wfa", "data"),
        Input("wfa-holdout", "value"),
        Input("wfa-travar-camada4", "value"),
        running=[(Output("wfa-trava-matriz", "className"),
                  "wfa-trava on", "wfa-trava"),
                 (Output("wfa-veu-matriz", "className"), "veu on", "veu"),
                 # o holdout não fica sob a trava de CSS (está no cabeçalho da
                 # própria matriz): desligado de verdade enquanto ela calcula
                 (Output("wfa-holdout", "options"),
                  [{"label": "estender ao holdout", "value": "on",
                    "disabled": True}],
                  [{"label": "estender ao holdout", "value": "on"}])],
    )
    def wfa_matriz(store, holdout, travar):
        """As sete inteligências × 12 configurações, de uma vez, no servidor.

        Não depende de IS, OOS nem da inteligência escolhida — ela é quem os
        propõe. As métricas de cada janela são calculadas uma vez e divididas
        entre as sete (`wfa.matrizes`): 0,9 s na #40, contra 4,3 s se cada
        uma refizesse a conta. O resultado fica guardado por varredura e
        estado do holdout; ligar e desligar o holdout de novo, ou trocar de
        aba, não recalcula nada.

        **Sem `tick` entre os Inputs, de propósito**: quem avisa que a
        varredura acabou é o `store-wfa`, que muda uma vez só.
        """
        if not store:
            return no_update
        if store.get("fase") != "pronta":
            # varredura nova: a matriz da anterior some, em vez de ficar
            # visível e clicável por cima de um cache que já não é o dela
            return None
        cache = VARREDURA.cache
        if not cache:
            return None

        e = VARREDURA.estado
        estende = "on" in (holdout or [])
        trava = "on" in (travar or [])
        # a trava entra na chave do cache: com e sem camada 4 travada são
        # duas matrizes diferentes, e reaproveitar uma pela outra mostraria
        # números de um walk-forward que não foi o pedido
        chave = _chave_matriz(e.get("run_id"), e.get("geracao"), estende, trava,
                              _WFA.get("camada4_valores") if trava else None)
        guardadas = _WFA.setdefault("matrizes", {})
        with _MATRIZ_LOCK:          # duas threads não calculam a mesma matriz
            return _matriz_guardada(guardadas, chave, cache, e, estende, trava)

    def _matriz_guardada(guardadas, chave, cache, e, estende, trava):
        if chave not in guardadas:
            fim = e["ate"] if estende else e["ate_holdout"]
            d = optimizer.detalhes_salva(e.get("run_id")) if e.get("run_id") else None
            # TODAS as células usam a camada 4 da configuração aberta, não a
            # que cada uma aprenderia da própria primeira janela: sete
            # inteligências × doze configurações travariam em até doze stops
            # diferentes, e a matriz passaria a misturar "de que tamanho de
            # janela a estratégia precisa" com "que stop aquela célula calhou
            # de pegar"
            valores = _WFA.get("camada4_valores") if trava else None
            por_q = wfa.matrizes(cache, e["de"], fim,
                                 float(e["capital"] or 10_000.0),
                                 criterios=_criterios_wfa(d, e)[0],
                                 travar_execucao=(
                                     set(wfa_runner.CAMPOS_EXECUCAO_NOMES)
                                     if trava and not valores else None),
                                 valores_travados=valores)
            # só as da varredura atual: holdout ligado e desligado
            for velha in [k for k in guardadas
                          if not k.startswith(f"{e.get('run_id')}-{e.get('geracao')}-")]:
                guardadas.pop(velha)
            guardadas[chave] = {"por_q": por_q, "consenso": wfa.consenso(por_q)}
        return {"chave": chave}

    @app.callback(
        Output("grid-wfa-matriz", "columnDefs"),
        Output("grid-wfa-matriz", "rowData"),
        Output("wfa-matriz-sobre", "children"),
        Output("wfa-matriz-aberta", "children"),
        Input("store-matriz", "data"),
        Input("abas-matriz", "value"),
        Input("wfa-is", "value"), Input("wfa-oos", "value"),
        Input("wfa-inteligencia", "value"),
    )
    def wfa_matriz_aba(store, aba, is_m, oos_m, inteligencia):
        """Desenha a aba escolhida. Barato: nada é calculado aqui.

        Também é quem marca a linha ATUAL — a configuração aberta no detalhe
        de baixo —, por isso ouve IS, OOS e a inteligência. As colunas só
        mudam quando muda a aba; reenviá-las a cada clique faria a grade
        piscar.
        """
        aba = aba or WM.CONSENSO
        dados = _WFA.get("matrizes", {}).get((store or {}).get("chave"))
        muda_aba = ctx.triggered_id in (None, "abas-matriz", "store-matriz")
        return (WM.colunas(aba) if muda_aba else no_update,
                WM.linhas(aba, dados, is_m, oos_m, inteligencia),
                WM.sobre(aba) if muda_aba else no_update,
                WM.aberta(is_m, oos_m, inteligencia))

    @app.callback(
        Output("wfa-is", "value"), Output("wfa-oos", "value"),
        Output("wfa-inteligencia", "value", allow_duplicate=True),
        Input("grid-wfa-matriz", "selectedRows"),
        State("abas-matriz", "value"),
        prevent_initial_call=True,
    )
    def wfa_da_matriz(linhas, aba):
        """Clicar numa linha abre aquela configuração no detalhe de baixo.

        Na aba de uma inteligência, abre também a inteligência: a mesma
        IS/OOS escolhida por outra inteligência é outra sequência de
        parâmetros. No Consenso a linha é de todas, e a inteligência aberta
        fica como está.
        """
        if not linhas:
            raise PreventUpdate
        r = linhas[0]
        return (r["is_meses"], r["oos_meses"],
                no_update if (aba or WM.CONSENSO) == WM.CONSENSO else aba)

    # ---------------------------------------- excluir uma mineração salva
    @app.callback(
        Output("btn-excluir-mine", "disabled"),
        Output("btn-excluir-mine", "children"),
        Output("mine-carregar", "value", allow_duplicate=True),
        Output("mine-aviso", "children"),
        Input("mine-carregar", "value"),
        Input("btn-excluir-mine", "n_clicks"),
        State("btn-excluir-mine", "children"),
        prevent_initial_call=True,
    )
    def excluir_mineracao(run_id, _n, rotulo):
        """Dois cliques para apagar: o primeiro vira "confirmar?".

        Apagar é irreversível e o alvo mora num seletor onde a linha errada
        está a um pixel da certa. Escolher outra mineração desarma a
        confirmação — se você mexeu no seletor, não estava confirmando nada.
        Recusada (plano em operação), diz o motivo e não mexe no seletor nem
        esquece a mineração aberta.
        """
        if ctx.triggered_id == "mine-carregar":
            return (not run_id), "Excluir", no_update, ""
        if not run_id:
            return True, "Excluir", no_update, ""
        if rotulo != "Confirmar?":
            return False, "Confirmar?", no_update, ""
        try:
            optimizer.excluir_salva(int(run_id))
        except ValueError as e:
            return False, "Excluir", no_update, str(e)
        except RuntimeError:
            return False, "Excluir", no_update, "banco ocupado, tente de novo"
        MINERACAO.esquecer()
        return True, "Excluir", None, ""

    # ------------------------------------------- salvar / excluir um WFA
    @app.callback(
        Output("btn-wfa-salvar", "disabled"),
        Input("store-wfa", "data"),
    )
    def wfa_pode_guardar(store):
        # o botão de "mandar ao Backtest" saiu: a vencedora agora é vista
        # na sub-aba daqui, sem mexer no estado do outro modo
        return (store or {}).get("fase") != "pronta"

    @app.callback(
        Output("wfa-salvos", "options"),
        Output("wfa-aviso", "children"),
        Output("btn-wfa-salvar", "children"),
        Input("btn-wfa-salvar", "n_clicks"),
        Input("store-wfa-lista", "data"),
        Input("wfa-estrategia", "value"),
        Input("store-wfa", "data"),
        Input("wfa-ativo", "value"),
        State("wfa-nome", "value"),
    )
    def wfa_guardar(_s, _lista, estrategia, _store, ativo, nome):
        """Salvar grava o REGISTRO da decisão, não a performance.

        O resultado é barato de recalcular — o custo está na varredura. O que
        vale guardar é qual mineração, com que janela, que inteligência e o
        que deu: o histórico de "já testei isto assim" que evita refazer o
        mesmo caminho daqui a três meses.
        """
        aviso = ""
        gatilho = ctx.triggered_id

        if gatilho == "btn-wfa-salvar" and _WFA.get("passos"):
            d = optimizer.detalhes_salva(_WFA["run_id"])
            # os trades da curva OOS só são reconstruídos AQUI, na hora de
            # salvar: são uns oito backtests, meio segundo, e em troca fica
            # gravado o que o portfólio vai precisar — entrada, saída, lado,
            # contratos e custo de cada operação
            trades = wfa_runner.trades_oos_detalhados(
                d["perfil"], _WFA["strategy"], _WFA["symbol"],
                _WFA["passos"], set(SCHEMA_EXECUCAO)) if d else []
            # a mesma chave com que `_matriz_guardada` guardou a matriz desta
            # configuração — sem casar run, geração, holdout E camada 4,
            # os sharpes viriam de outra varredura, do outro lado do holdout,
            # ou simplesmente não seriam encontrados: montar a chave à mão
            # nos dois lugares já fez `sharpes_matriz` gravar vazio
            chave = _chave_matriz(_WFA.get("run_id"), (_store or {}).get("g"),
                                  _WFA.get("holdout", False),
                                  _WFA.get("camada4_travada", False),
                                  _WFA.get("camada4_valores"))
            por_q = (_WFA.get("matrizes", {}).get(chave) or {}).get("por_q", {})
            sharpes = [r["sharpe"] for linhas in por_q.values()
                      for r in linhas if r.get("sharpe") is not None]
            wid = wfa_store.salvar(
                run_id=_WFA["run_id"], symbol=_WFA["symbol"],
                strategy=_WFA["strategy"], nome=nome,
                is_meses=_WFA["is_meses"], oos_meses=_WFA["oos_meses"],
                inteligencia=_WFA["inteligencia"], holdout=_WFA["holdout"],
                agregado=_WFA["agregado"], veredito=_WFA["veredito"],
                passos=_WFA["passos"], trades=trades,
                profile=d["perfil"] if d else None,
                capital=_WFA.get("capital"), sharpes_matriz=sharpes,
                camada4_travada=_WFA.get("camada4_travada"),
                codigo_hash=_WFA.get("codigo_hash"))
            aviso = (f"walk-forward #{wid} salvo · "
                     f"{len(trades)} trades gravados para o portfólio")
            if (_WFA.get("codigo_hash")
                    and codigo.hash_estrategia(_WFA["strategy"])
                    != _WFA["codigo_hash"]):
                aviso += (" · ⚠ o código da estratégia mudou desde que "
                          "este walk-forward rodou")
        elif gatilho == "store-wfa-lista":
            aviso = no_update           # quem excluiu já escreveu o aviso

        # o dropdown lê label/value; `listar` devolve o registro inteiro,
        # que serve para gravar mas não para desenhar. Sem ativo, lista
        # vazia, como `wfa_mineracoes`: `symbol=None` seria a lista inteira
        salvos = wfa_store.listar(estrategia or registry.nome_atual(),
                                  symbol=ativo) if ativo else []
        return ([{"label": w["rotulo"], "value": w["wfa_id"]} for w in salvos],
                aviso, "Salvar")

    @app.callback(
        Output("btn-wfa-excluir", "disabled"),
        Input("wfa-salvos", "value"),
    )
    def wfa_pode_excluir(wfa_id):
        return not wfa_id

    @app.callback(
        Output("btn-wfa-excluir", "children"),
        Output("wfa-salvos", "value", allow_duplicate=True),
        Output("wfa-aviso", "children", allow_duplicate=True),
        Output("store-wfa-lista", "data"),
        Input("btn-wfa-excluir", "n_clicks"),
        Input("wfa-salvos", "value"),
        State("btn-wfa-excluir", "children"),
        prevent_initial_call=True,
    )
    def wfa_excluir(_n, wfa_id, rotulo):
        """Dois cliques para apagar, como na mineração: o primeiro vira
        "Confirmar?". Escolher outro registro desarma. Depois de apagar, o
        seletor é limpo — o id apagado ficava selecionado, com o Excluir
        ainda habilitado."""
        if ctx.triggered_id == "wfa-salvos" or not wfa_id:
            return "Excluir", no_update, no_update, no_update
        if rotulo != "Confirmar?":
            return "Confirmar?", no_update, no_update, no_update
        try:
            wfa_store.excluir(int(wfa_id))
        except ValueError as e:
            return "Excluir", no_update, str(e), no_update
        except RuntimeError:
            return ("Excluir", no_update, "banco ocupado, tente de novo",
                    no_update)
        return ("Excluir", None, f"walk-forward #{wfa_id} excluído",
                {"excluido": int(wfa_id), "t": __import__("time").time()})

    @app.callback(
        Output("wfa-estrategia", "value", allow_duplicate=True),
        Output("wfa-mineracao", "value", allow_duplicate=True),
        Output("wfa-is", "value", allow_duplicate=True),
        Output("wfa-oos", "value", allow_duplicate=True),
        Output("wfa-inteligencia", "value"),
        Output("wfa-holdout", "value"),
        Output("wfa-travar-camada4", "value"),
        Output("wfa-nome", "value"),
        Output("store-wfa-carregar", "data"),
        Output("wfa-aviso", "children", allow_duplicate=True),
        Input("wfa-salvos", "value"),
        prevent_initial_call=True,
    )
    def wfa_carregar_salvo(wfa_id):
        """Escolher um walk-forward salvo devolve a tela ao estado dele.

        O registro guarda a DECISÃO — mineração, IS, OOS, inteligência e se
        o holdout entrou —, e não os gráficos: com esses cinco valores nos
        campos, o cálculo refaz tudo igual. Se o cache na memória já é daquela
        mineração, sai em milissegundos; se não, a varredura roda de novo.

        O Store no fim força o cálculo mesmo quando os valores gravados já
        são os da tela — sem ele, abrir a página e escolher um registro com
        IS 12 / OOS 6 (os padrões) não dispararia nada.
        """
        d = wfa_store.detalhes(int(wfa_id)) if wfa_id else None
        if not d:
            raise PreventUpdate
        if not optimizer.detalhes_salva(d["run_id"]):
            # sem a mineração não há espaço de busca para refazer nada; trocar
            # por outra em silêncio mostraria um resultado que não é o dele
            return (*[no_update] * 9,
                    f"a mineração #{d['run_id']} deste walk-forward foi excluída")
        # registro anterior a esta coluna volta com a caixa MARCADA, que é o
        # padrão de hoje — e o resumo da Candidata diz que não foi informado
        travada = d.get("camada4_travada")
        return (d["strategy"], d["run_id"], d["is_meses"], d["oos_meses"],
                d["inteligencia"], ["on"] if d["holdout"] else [],
                [] if travada is False else ["on"],
                d.get("nome") or "", {"wfa_id": int(wfa_id)}, "")
