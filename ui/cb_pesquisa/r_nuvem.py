"""Pesquisa: callbacks da nuvem, da região, da porteira e dos critérios."""
from __future__ import annotations

import numpy as np
from dash import ALL, Input, Output, State, ctx

from core import analytics
from core import mineracao_stats as MS
from core import porteira

from ..components import scatter
from ..components import mine_charts as MC
from ..components import mine_porteira as PT
from ..components import mine_regiao as RG
from ..components import mine_criterios as CR

from .menu import _moeda_da_mineracao
from .base import _linhas_tabela, _varredura
from .ativo import _esquecer_combinacao
from .combinacao import MENU_COMBINACAO, _carregar_combinacao, _linha_combinacao, _menu_atual, _reclique_mesma_linha


def register(app):
    # ---------------------------------------------- scatter da mineração
    @app.callback(
        Output("sc-x", "options"), Output("sc-y", "options"),
        Output("sc-z", "options"), Output("sc-x", "value"), Output("sc-y", "value"),
        Input("grid-mine", "rowData"),
        State("sc-x", "value"), State("sc-y", "value"),
    )
    def eixos(linhas, x_atual, y_atual):
        if not linhas:
            return [], [], [], None, None
        # só entram os parâmetros que de fato variaram: eixo com um valor só
        # não é dispersão, é uma linha
        variaram = [k for k in linhas[0]["params"]
                    if len({str(l["params"].get(k)) for l in linhas}) > 1]
        if not variaram:
            return [], [], [], None, None

        opts_p = [{"label": k, "value": k} for k in variaram]
        # o eixo Y tambem aceita metrica: numa varredura de um parametro so,
        # parametro no X e score no Y e a unica leitura util
        opts_y = opts_p + [{"label": f"↳ {r}", "value": v} for r, v in scatter.METRICAS]
        validos_y = variaram + [v for _, v in scatter.METRICAS]

        # Cuidado com a atualização incremental: no começo da varredura só um
        # parâmetro parece ter variado, e sem esta correção os dois eixos
        # ficam presos nele até o fim.
        x = x_atual if x_atual in variaram else variaram[0]
        if y_atual in validos_y and y_atual != x:
            y = y_atual
        # padrão do eixo Y é fator de recuperação (mesmo critério padrão de
        # otimização do MT5, ver scatter.METRICAS) - só cai num parâmetro
        # se "fr" não estiver disponível por algum motivo
        elif "fr" != x:
            y = "fr"
        else:
            y = next((k for k in variaram if k != x), "fr")
        return opts_p, opts_y, opts_p, x, y

    @app.callback(
        Output("scatter", "figure"),
        Input("grid-mine", "rowData"), Input("sc-x", "value"), Input("sc-y", "value"),
        Input("sc-z", "value"), Input("sc-metrica", "value"),
    )
    def desenhar_scatter(linhas, x, y, z, metrica):
        if not linhas:
            return scatter.vazio()
        if not x or not y:
            return scatter.vazio("Escolha os eixos para ver a nuvem.")
        return scatter.figura(linhas, x, y, z, metrica or "robusto",
                              moeda=_moeda_da_mineracao())

    # ------- cross-filtering: um caminho, dois gatilhos (nuvem e tabela)
    @app.callback(
        Output({"type": "val", "p": ALL}, "value"),
        Output("excluir-holdout", "value"),
        Output("btn-run", "n_clicks"),
        Output("mine-subtela", "value"),
        Output("store-combinacao", "data"),
        Input("grid-mine", "selectedRows"),
        Input("scatter", "clickData"),
        Input("grid-aprovadas", "selectedRows"),
        State({"type": "val", "p": ALL}, "id"),
        State("grid-mine", "rowData"),
        State("btn-run", "n_clicks"),
        State("mine-carregar", "value"),
        State({"type": "val", "p": ALL}, "value"),
        State({"type": "opt-on", "p": ALL}, "id"),
        State({"type": "opt-on", "p": ALL}, "value"),
        *[State(cid, prop) for cid, prop in MENU_COMBINACAO],
        prevent_initial_call=True,
    )
    def carregar_combinacao(selecionadas, clique, aprovadas, ids_val, linhas,
                            n_run, run_salva, valores_val, ids_on, ligados,
                            *menu):
        """Clique no ponto da nuvem, na linha da tabela OU na lista de
        aprovadas carrega os mesmos campos, dispara o mesmo backtest e pula
        para a subtela Backtest.

        Além dos parâmetros, alinha o PERÍODO — ligando a chave "excluir
        holdout" em vez de reescrever a data final. A tabela mede só até o
        começo do holdout; sem esse recorte o backtest rodaria 12 meses a
        mais que a linha clicada e mostraria outro lucro para a mesma
        combinação. O recorte é derivado na hora a partir das datas, que
        permanecem intocadas.

        A tabela reescrita durante a varredura (a cada 800 ms) e a mineração
        salva carregada chegam aqui com `selectedRows` vazio: não pulam.
        """
        return _carregar_combinacao(
            ctx.triggered_id, selecionadas, clique, aprovadas, ids_val, linhas,
            n_run, valores_val=valores_val, ids_on=ids_on, ligados=ligados,
            menu={cid: v for (cid, _p), v in zip(MENU_COMBINACAO, menu)})

    # ---- clicar de novo na linha já carregada só volta para o Backtest
    @app.callback(
        Output("mine-subtela", "value", allow_duplicate=True),
        Input("grid-mine", "cellClicked"),
        Input("grid-aprovadas", "cellClicked"),
        State("grid-mine", "selectedRows"),
        State("grid-aprovadas", "selectedRows"),
        State("store-combinacao", "data"),
        prevent_initial_call=True,
    )
    def reclique_combinacao(_mine, _apr, sel_mine, sel_apr, store):
        """Sem `grid-mine.rowData` como Input: a tabela é reescrita a cada
        800 ms durante a varredura."""
        return _reclique_mesma_linha(ctx.triggered_id, sel_mine, sel_apr, store)

    # a linha "linha #3 · stop_pontos=10" no alto da subtela Backtest; o
    # "editado" só se decide ao rodar, comparando o menu com o do clique
    @app.callback(
        Output("mine-combinacao", "children"),
        Input("btn-run", "n_clicks"),
        Input("store-combinacao", "data"),
        State({"type": "val", "p": ALL}, "id"),
        State({"type": "val", "p": ALL}, "value"),
        State("excluir-holdout", "value"),
        *[State(cid, prop) for cid, prop in MENU_COMBINACAO],
    )
    def linha_combinacao(_n, store, ids_val, valores_val, holdout, *menu):
        return _linha_combinacao(store, _menu_atual(
            ids_val, valores_val, holdout,
            {cid: v for (cid, _p), v in zip(MENU_COMBINACAO, menu)}))

    # trocar de estratégia, carregar mineração salva ou trocar o ativo: a
    # combinação aberta não é mais a da tela. Callback à parte —
    # `estrategia_ou_mineracao` indexa as saídas por posição
    @app.callback(
        Output("store-combinacao", "data", allow_duplicate=True),
        Input("estrategia", "value"),
        Input("mine-carregar", "value"),
        Input("ativo", "value"),
        # uma Varredura nova também: o corte que um campeão da Busca
        # automática trouxe não pode valer para o backtest dela
        Input("btn-minerar", "n_clicks"),
        prevent_initial_call=True,
    )
    def esquecer_combinacao(_estrategia, _run_id, _ativo, _minerar):
        return _esquecer_combinacao(ctx.triggered_id)

    # ------------------------------- passo 5: a regiao, e nao o campeao
    @app.callback(
        Output("mine-cards-dist", "children"),
        Output("g-mine-hist", "figure"),
        Output("g-mine-curva", "figure"),
        Input("store-mine", "data"),
        Input("dist-metrica", "value"),
    )
    def distribuicao_mine(marca, metrica):
        """A leitura do passo 5: como está a REGIÃO varrida.

        Roda sobre as linhas que a tabela já tem — nenhum backtest novo, e
        por isso acompanha a varredura enquanto ela corre.
        """
        if (marca or {}).get("fase") == "rodando":
            v = MC._vazio("Aguardando o fim da varredura…")
            return RG.cards({}, "Aguardando o fim da varredura…"), v, v
        linhas = _varredura(_linhas_tabela())
        if not linhas:
            v = MC._vazio("Rode uma mineração para ver a distribuição.")
            return RG.cards({}), v, v

        metrica = metrica or "lucro"
        rotulo = next((r for r, v in MS.METRICAS if v == metrica), metrica)
        # a moeda é a do ativo que foi minerado; métrica sem dinheiro é None
        moeda_ativo = _moeda_da_mineracao()
        moeda = moeda_ativo if metrica in MS.DINHEIRO else None
        valores = np.array([l[metrica] for l in linhas
                            if l.get(metrica) is not None], dtype=float)
        if not len(valores):
            v = MC._vazio("Nenhuma combinação tem esta métrica.")
            return RG.cards(MS.resumo(linhas), moeda=moeda_ativo), v, v

        return (
            RG.cards(MS.resumo(linhas), moeda=moeda_ativo),
            MC.histograma(analytics.distribuicao(valores), rotulo, moeda),
            MC.curva(MS.curva(linhas, metrica), rotulo, moeda),
        )

    # ------------------- a varredura inteira merece seguir? (a porteira)
    @app.callback(
        Output("aba-porteira", "children"),
        Input("store-mine", "data"),
    )
    def porteira_mine(marca):
        """O veredito sobre a VARREDURA, não sobre uma combinação.

        Roda sobre as linhas que a tabela já tem: acompanha a varredura
        enquanto ela corre, e o carimbo vai firmando conforme a amostra
        cresce.
        """
        if (marca or {}).get("fase") == "rodando":
            return PT.vazio("Aguardando o fim da varredura…")
        linhas = _linhas_tabela()
        todas = _varredura(linhas)
        if not todas:
            return PT.vazio()
        return PT.painel(porteira.avaliar(todas),
                         truncada=len(todas) - len(linhas),
                         moeda=_moeda_da_mineracao())

    # ---------------------------- passo 7: quem passa nos numeros fixados
    @app.callback(
        Output("crit-resumo", "children"),
        Output("g-crit-funil", "figure"),
        Output("grid-aprovadas", "rowData"),
        Input("store-mine", "data"),
        *[Input(f"crit-{c['id']}", "value") for c in MS.CRITERIOS],
    )
    def criterios(marca, *limites):
        """A CONTAGEM vale sobre a varredura inteira; a LISTA, sobre o que a
        tabela tem.

        Os dois conjuntos diferem quando a varredura passa de 5.000
        combinações: o extrato completo não carrega os parâmetros (são só
        oito números por linha), então a lista de aprovadas — que é clicável
        e precisa carregar a combinação — só pode sair das linhas exibidas.
        Contar por um e listar pelo outro é o que mantém o número honesto sem
        quebrar o clique.
        """
        if (marca or {}).get("fase") == "rodando":
            return (CR.vazio("Aguardando o fim da varredura…"),
                    MC._vazio("Aguardando o fim da varredura…"), [])
        linhas = _linhas_tabela()
        todas = _varredura(linhas)
        if not todas:
            return (CR.vazio(), MC._vazio("Rode uma mineração."), [])
        limiares = {c["id"]: v for c, v in zip(MS.CRITERIOS, limites)}
        av = MS.avaliar(todas, limiares)
        exibiveis = (MS.avaliar(linhas, limiares)["aprovadas"]
                     if linhas and len(linhas) != len(todas) else av["aprovadas"])
        return (CR.resumo(av, n_listadas=len(exibiveis)),
                MC.funil(av), exibiveis)
