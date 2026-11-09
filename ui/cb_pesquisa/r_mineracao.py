"""Pesquisa: callbacks da mineração (minerar, salvar, carregar)."""
from __future__ import annotations

import time

from dash import ALL, Input, Output, State, ctx, no_update

from dash import html

from core import ativo as ativo_mod
from core import mineracao_stats as MS
from core.wfa_runner import VARREDURA
from core import optimizer
from core.optimizer import MINERACAO
from strategies import registry

from .menu import _COMBOS, _dt, _entrar_mineracao_salva, _por_campo, _simbolo
from .base import FOLGA_TABELA, SCHEMA_EXECUCAO, _ULTIMA_TABELA, _lista_salvas
from .ativo import _ativo_desligado
from .combinacao import MENU_PERFIL, perfil_do_menu


def register(app):
    # ------------------------------------------------------------- mineracao
    @app.callback(
        Output("wf-resumo", "children"),
        Input("btn-minerar", "n_clicks"),
        Input("tick", "n_intervals"),
        State("wf-treino", "value"), State("wf-teste", "value"),
        State("wf-passo", "value"), State("wf-holdout", "value"),
        State({"type": "opt-on", "p": ALL}, "value"),
        State({"type": "opt", "p": ALL, "k": ALL}, "value"),
        State({"type": "opt-on", "p": ALL}, "id"),
        State({"type": "opt", "p": ALL, "k": ALL}, "id"),
        State("d-de", "date"), State("d-ate", "date"),
        State({"type": "val", "p": ALL}, "value"),
        State({"type": "val", "p": ALL}, "id"),
        *[State(cid, prop) for cid, prop in MENU_PERFIL],
        State("wf-workers", "value"),
        State("ativo", "value"),
        prevent_initial_call=True,
    )
    def minerar(n, _tick, treino, teste, passo, holdout, ligados, faixas,
                ids_on, ids_faixa, de, ate, valores, ids_val, *resto):
        *menu, workers, ativo = resto
        e = MINERACAO.estado
        if ctx.triggered_id != "btn-minerar":
            return e.get("mensagem") or no_update
        if e["rodando"]:
            return "já está minerando"

        v = {i["p"]: val for i, val in zip(ids_val, valores)}
        campos = _por_campo(ids_faixa, faixas)
        for ident, on in zip(ids_on, ligados):
            campos.setdefault(ident["p"], {})["on"] = bool(on)
        for p, r in campos.items():
            r["valor"] = v.get(p)

        perfil = perfil_do_menu(v, {cid: val for (cid, _p), val
                                    in zip(MENU_PERFIL, menu)})

        erro_janela = ativo_mod.janela_valida(perfil.entrada_inicio, perfil.entrada_fim,
                                              ativo_mod.ficha(_simbolo(ativo)),
                                              perfil.fechamento)
        if erro_janela:
            return erro_janela

        MINERACAO.iniciar(
            symbol=_simbolo(ativo), estrategia_nome=registry.nome_atual(),
            schema=registry.atual().params_schema, ranges=campos,
            perfil_base=perfil.to_config(),
            campos_execucao_schema=SCHEMA_EXECUCAO,
            de=_dt(de), ate=_dt(ate, True),
            wf_config={"treino_meses": treino or 12, "teste_meses": teste or 3,
                       "passo_meses": passo or 3, "holdout_meses": holdout or 0},
            workers=(workers or None),
        )
        return "iniciando…"

    @app.callback(Output("btn-parar", "n_clicks"), Input("btn-parar", "n_clicks"),
                  prevent_initial_call=True)
    def parar(n):
        MINERACAO.parar()
        return 0

    # --------------------------------------------------- gatilho de reotimizar
    @app.callback(
        Output("reotimizar-selo", "children"),
        Output("reotimizar-selo", "className"),
        Output("reotimizar-selo", "style"),
        Output("reotimizar-lista", "children"),
        Input("modo", "value"),
    )
    def montar_selo_reotimizar(_qual):
        from core import plano as PL
        itens = PL.vencendo()
        if not itens:
            return "", "reotimizar-selo", {"display": "none"}, []

        vencidos = any(i["dias_restantes"] < 0 for i in itens)
        cor = "reotimizar-selo vencido" if vencidos else "reotimizar-selo proximo"
        linhas = [
            html.Div(
                f"{i['variante_nome'] or 'sem variante'} · {i['strategy']} · "
                + (f"venceu há {-i['dias_restantes']} dia(s)"
                   if i["dias_restantes"] < 0
                   else f"vence em {i['reotimizar_em']:%d/%m}"),
                className="reotimizar-item",
            )
            for i in itens
        ]
        return str(len(itens)), cor, {"display": "inline-flex"}, linhas

    @app.callback(
        Output("reotimizar-lista", "style"),
        Input("reotimizar-selo", "n_clicks"),
        State("reotimizar-lista", "style"),
        prevent_initial_call=True,
    )
    def alternar_lista_reotimizar(_n, estilo):
        aberto = (estilo or {}).get("display") == "block"
        return {"display": "none" if aberto else "block"}

    # --------------------------------------------------- salvar sob demanda
    @app.callback(
        Output("mine-variante", "options"),
        Input("estrategia", "value"),
    )
    def variantes_da_estrategia(modulo):
        if not modulo:
            return []
        from core import variantes as V
        return [{"label": v["nome"], "value": v["variante_id"]}
                for v in V.listar(modulo)]

    @app.callback(Output("btn-salvar", "n_clicks"),
                  Input("btn-salvar", "n_clicks"), State("mine-nome", "value"),
                  State("mine-variante", "value"),
                  State("mine-variante-nova", "value"),
                  State("estrategia", "value"),
                  *[State(f"crit-{c['id']}", "value") for c in MS.CRITERIOS],
                  prevent_initial_call=True)
    def salvar(n, nome, variante_id, variante_nova, modulo, *limites):
        from core import variantes as V
        nova = (variante_nova or "").strip()
        if nova:
            try:
                variante_id = V.criar(nova, modulo)
            except ValueError as erro:
                MINERACAO.estado["aviso_salvar"] = f"falhou ao salvar: {erro}"
                return 0
        # os critérios vão junto: o walk-forward desta mineração os aplica
        # dentro de cada janela IS
        MINERACAO.salvar((nome or "").strip() or None,
                         {c["id"]: v for c, v in zip(MS.CRITERIOS, limites)},
                         variante_id)
        return 0

    @app.callback(
        Output("btn-salvar", "disabled"), Output("mine-contagem", "children"),
        Output("mine-contagem", "className"),
        Input("tick", "n_intervals"), Input("btn-salvar", "n_clicks"),
        Input("btn-minerar", "n_clicks"), Input("mine-carregar", "value"),
    )
    def estado_salvar(_t, _s, _m, _c):
        e = MINERACAO.estado
        n = f"{MINERACAO.n_resultados:,}".replace(",", ".")
        if e["salvando"]:
            return True, "salvando…", "contagem"
        if e["salva"]:
            return True, e["aviso_salvar"], "contagem salva-ok"
        if MINERACAO.pode_salvar:
            return False, f"{n} combinações", "contagem nao-salva"
        if e["aviso_salvar"].startswith("falhou"):
            return True, e["aviso_salvar"], "contagem nao-salva"
        return True, "", "contagem"

    # ------------------------------------------- minerar: precisa de espaço
    @app.callback(
        Output("btn-minerar", "disabled"),
        Input("espaco-busca", "children"), Input("tick", "n_intervals"),
    )
    def pode_minerar(_texto, _t):
        """Varrer uma combinação só é backtest, não mineração — e sem duas
        janelas de comparação o score de vizinhança não existe."""
        return MINERACAO.estado["rodando"] or _COMBOS.get("n", 0) < 2

    # o ativo do menu fica desligado enquanto a mineração corre ou é salva.
    # O `pulso` mantém o relógio batendo nos dois casos, e `tick.disabled` é
    # Input para pegar o fim: o relógio para e este callback ainda roda uma
    # vez, já com a varredura terminada ou salva. Sem prevent_initial_call:
    # depois de um F5 a mineração continua viva.
    @app.callback(
        Output("ativo", "disabled"),
        Input("btn-minerar", "n_clicks"), Input("btn-salvar", "n_clicks"),
        Input("tick", "n_intervals"), Input("tick", "disabled"),
        State("ativo", "disabled"),
    )
    def ativo_desligado(_n, _s, _t, _parado, desligado):
        return _ativo_desligado(desligado)

    # ----------------------------------------- carregar mineração salva
    @app.callback(
        Output("mine-carregar", "options"),
        Input("tick", "n_intervals"), Input("btn-salvar", "n_clicks"),
        Input("modo", "value"), Input("estrategia", "value"),
        Input("ativo", "value"),
    )
    def listar_salvas(_t, _s, _modo, estrategia, ativo):
        """A lista é sempre da estratégia da tela, no ativo do menu.

        `estrategia` precisa ser Input, não apenas leitura: o relógio fica
        parado quando não há mineração, então sem este gatilho a lista
        continuava mostrando as varreduras da estratégia anterior — e
        carregar uma delas trazia combinações com parâmetros que nem
        existem nos campos. O `ativo` é Input pelo mesmo motivo.
        """
        return _lista_salvas(ctx.triggered_id, estrategia, ativo)

    # o relogio so bate enquanto ha o que atualizar
    @app.callback(Output("tick", "disabled"),
                  Input("btn-minerar", "n_clicks"), Input("tick", "n_intervals"),
                  Input("btn-salvar", "n_clicks"), Input("btn-wfa", "n_clicks"),
                  Input("store-wfa", "data"))
    def pulso(_a, _b, _c, _d, _e):
        # sem prevent_initial_call: depois de um F5 a mineração continua viva
        # no servidor, e é este disparo no carregamento que religa o relógio.
        # Sem ele a tela ficava congelada enquanto a varredura corria por baixo.
        # Salvar também precisa do relógio: é o que leva o "salvando…" até o
        # "salva" na tela.
        # O Executar do walk-forward também dispara uma varredura em thread.
        # E o relógio precisa continuar batendo até a tela DESENHAR o
        # resultado, não até a varredura terminar: com 41 combinações ela
        # acaba em 1,4 s, antes mesmo de o relógio ligar — e aí o resultado
        # ficava pronto no servidor com a tela parada em "varrendo…".
        v = VARREDURA.estado
        return not (MINERACAO.estado["rodando"] or MINERACAO.estado["salvando"]
                    or v["rodando"] or (v["pronto"] and not v["entregue"]))

    @app.callback(
        Output("grid-mine", "rowData"), Output("mine-info", "children"),
        Output("mine-bar", "style"), Output("store-mine", "data"),
        Input("tick", "n_intervals"), Input("btn-minerar", "n_clicks"),
        Input("mine-carregar", "value"),
    )
    def progresso(_tick, _n, run_id):
        """O progresso bate a cada 800 ms; a TABELA, não.

        O texto e a barra são baratos e valem a cadência cheia — é o que dá
        a sensação de que a varredura está viva. Já a tabela custa milhares
        de linhas por atualização, e a nuvem redesenha junto: as duas ganham
        uma folga de 2 s, e no fim sempre recebem a versão final.
        """
        e = MINERACAO.estado
        # carregar uma mineração salva entra pelo mesmo caminho de uma
        # recém-rodada: a tabela e a nuvem não sabem a diferença
        if ctx.triggered_id == "mine-carregar" and run_id and not e["rodando"]:
            d = optimizer.detalhes_salva(run_id)
            # de outra estratégia, não carrega: os parâmetros não existem nos
            # campos e a tabela viraria armadilha. Este callback só roda depois
            # de estrategia_ou_mineracao (que escreve `mine-carregar`, Input
            # daqui), então a troca de estratégia já aconteceu; se ainda assim
            # não bate, é porque a estratégia sumiu — quem avisa é ele.
            if not d or d["estrategia"] != registry.nome_atual():
                return [], no_update, {"width": "0%"}, {"fase": "vazia"}
            _entrar_mineracao_salva(e, run_id, d)
            _ULTIMA_TABELA.update(t=time.time(), feitos=-1)
            return (e["trials"], no_update, {"width": "100%"},
                    {"fase": "pronta", "n": len(e["trials"]),
                     "origem": f"banco:{run_id}"})
        total = max(1, e["total"])
        pct = min(100, e["feitos"] * 100 / total)
        if e["erro"]:
            texto = e["mensagem"]
        elif MINERACAO.parando:
            texto = f"parando… {e['feitos']:,}".replace(",", ".") + " já salvos"
        elif e["rodando"]:
            falta = ""
            if e["feitos"] and e["inicio"]:
                gasto = time.time() - e["inicio"]
                resta = gasto / e["feitos"] * (e["total"] - e["feitos"])
                falta = f" · ~{resta:.0f}s restantes"
            texto = f"{e['feitos']:,}/{e['total']:,}".replace(",", ".") + falta
        else:
            texto = e["mensagem"] or "pronta para minerar"

        # A tabela só desce quando a folga passou — ou quando a varredura
        # acabou, e aí ela desce inteira, uma vez.
        agora = time.time()
        if e["rodando"]:
            if agora - _ULTIMA_TABELA["t"] >= FOLGA_TABELA:
                _ULTIMA_TABELA.update(t=agora, feitos=e["feitos"])
                linhas = e["trials"]
            else:
                linhas = no_update
            # valor ESTÁVEL enquanto corre: o store não re-dispara, e as
            # análises pesadas ficam quietas até o fim
            marca = {"fase": "rodando"}
        else:
            linhas = e["trials"]
            _ULTIMA_TABELA.update(t=agora, feitos=e["feitos"])
            marca = ({"fase": "pronta", "n": len(e["trials"]),
                      "origem": f"memoria:{e['feitos']}"}
                     if e["trials"] else {"fase": "vazia"})
        return linhas, texto, {"width": f"{pct}%"}, marca
