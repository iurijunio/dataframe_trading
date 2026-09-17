"""Reatividade.

Quatro fluxos, e nenhum deles reinicia o estado global:

  rodar         -> backtest, cartoes, curva de capital, tabela e grafico
  navegar       -> so o grafico de preco muda (faixa e timeframe)
  clicar trade  -> grafico vai ate o trade e desenha entrada, stop e alvo
  mexer na faixa-> recalcula o tamanho do espaco de busca da mineracao

O resultado do backtest fica num cache do processo, indexado por um token que
circula pelo dcc.Store. Arrays numpy de 20 mil trades nao viajam para o
navegador: so as linhas da tabela viajam.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
from dash import ALL, Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

from dash import html

from core import analytics, detalhes, metrics, robustez
from core import mineracao_stats as MS
from core import wfa
from core import wfa_store
from core import wfa_runner
from core.wfa_runner import VARREDURA
from core import porteira
from core import walkforward as wf
from core.engine import kernel as K
from core.engine.execution import (TIMEFRAMES, ExecutionProfile,
                                   run_strategy)
from core import optimizer
from core.optimizer import MINERACAO
from strategies import registry
from strategies.base import validate

from . import data as D
from .components import analytics_charts as AC
from .components import charts, controls, results_grid, scatter, stats_cards
from .components import detalhes_cards as DC
from .components import mine_charts as MC
from .components import mine_porteira as PT
from .components import mine_regiao as RG
from .components import wfa_panel as WP
from .components import ficha as FI
from .components import wfa_matriz as WM
from .components import mine_criterios as CR
from .components import robustez_cards as RC

def _simbolo(valor: str | None) -> str:
    """O ativo escolhido na tela, com o primeiro do banco como rede."""
    if valor:
        return valor
    lista = D.instrumentos()
    return lista[0]["symbol"] if lista else "WIN$N"
_runs: dict[str, dict] = {}


def _dt(valor, fim_do_dia=False):
    d = datetime.fromisoformat(str(valor)[:10])
    return d.replace(hour=23, minute=59, second=59) if fim_do_dia else d


def _por_campo(ids, valores):
    """Junta os inputs pattern-matching num dicionario por parametro."""
    out: dict[str, dict] = {}
    for ident, v in zip(ids, valores):
        out.setdefault(ident["p"], {})[ident.get("k", "on")] = v
    return out


def _combinacoes(campos: dict) -> int:
    total = 1
    for r in campos.values():
        if not r.get("on"):
            continue
        de, passo, ate = r.get("de"), r.get("passo"), r.get("ate")
        if de is None or ate is None or not passo:
            continue
        total *= max(1, int((ate - de) / passo) + 1)
    return total


OCULTO = {"display": "none"}
VISIVEL = {"display": "block"}

# tamanho do espaco de busca atual, escrito pelo callback `espaco` e lido por
# `pode_minerar` - evita recalcular o produto cartesiano so para saber se o
# botao pode acender
_COMBOS: dict[str, int] = {"n": 0}


def _br(iso: str) -> str:
    """2026-03-13 -> 13/03/2026"""
    p = (iso or "").split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else (iso or "")

# schema dos campos da camada 4 que a mineracao tambem pode varrer. Os
# NOMES vêm de `wfa_runner.CAMPOS_EXECUCAO_NOMES` — fonte única com
# `argumentos_da_mineracao`/`trades_oos_detalhados`; aqui só se decora cada
# nome com o passo do slider e o tipo que a tela usa.
_SCHEMA_EXECUCAO_META = {
    "alvo_pontos": {"default": 600, "step": 10, "tipo": "int"},
    "stop_pontos": {"default": 300, "step": 10, "tipo": "int"},
    "breakeven_pct": {"default": 0, "step": 5, "tipo": "float"},
    "step_gatilho_pct": {"default": 0, "step": 5, "tipo": "float"},
    "step_distancia_pct": {"default": 0, "step": 5, "tipo": "float"},
    "trailing_pontos": {"default": 0, "step": 10, "tipo": "int"},
}
SCHEMA_EXECUCAO = {nome: _SCHEMA_EXECUCAO_META[nome]
                   for nome in wfa_runner.CAMPOS_EXECUCAO_NOMES}

# Campos da camada 4 na tela <-> chaves do ExecutionProfile gravado.
# No topo do modulo, e nao dentro de register(), para o teste poder
# cobrar que NENHUMA chave do perfil fique de fora do carregamento.
CAMPOS_PERFIL = [
("e-timeframe", "timeframe"), ("e-ent-ini", "entrada_inicio"),
("e-ent-fim", "entrada_fim"), ("e-fechamento", "fechamento"),
("e-dias", "dias_semana"), ("e-direcao", "direcao"),
("e-alvo-tipo", "alvo_tipo"), ("e-alvo-atr-per", "alvo_atr_periodo"),
("e-alvo-atr-mult", "alvo_atr_mult"), ("e-stop-tipo", "stop_tipo"),
("e-stop-atr-per", "stop_atr_periodo"), ("e-stop-atr-mult", "stop_atr_mult"),
("e-max-barras", "max_barras"), ("e-lim-ganho", "limite_ganho_contrato"),
("e-lim-perda", "limite_perda_contrato"), ("e-max-trades", "max_trades_dia"),
("e-max-loss", "max_prejuizos_dia"),
("e-corretagem", "corretagem_por_contrato"),
("e-emolumentos", "emolumentos_por_contrato"),
("e-slippage", "slippage_ticks"), ("e-modo", "modo_posicao"),
("e-contratos", "contratos"), ("e-risco", "risco_por_trade"),
("e-capital", "capital_inicial"), ("e-min-ops", "min_operacoes"),
]


# quando a tabela foi empurrada para o navegador pela última vez. A folga
# existe para a varredura não gastar o processador redesenhando: com passo
# fino são milhares de linhas viajando a cada batida do relógio.
_ULTIMA_TABELA: dict = {"t": 0.0, "feitos": -1}

# O último walk-forward desenhado. Fica no servidor porque é de lá que ele
# vai para o banco: mandar as janelas até o navegador só para devolvê-las no
# clique do Salvar seria trafegar dados que nunca saíram daqui.
_WFA: dict = {}
# o cálculo das matrizes é caro e pode ser pedido por dois callbacks ao mesmo
# tempo (holdout ligado e desligado em sequência)
_MATRIZ_LOCK = __import__("threading").Lock()
FOLGA_TABELA = 2.0          # segundos


def _linhas_tabela() -> list[dict]:
    """As linhas que a tabela mostra, lidas do servidor.

    As análises não precisam recebê-las pelo callback: elas já estão em
    memória, e trafegar 5.000 dicionários de volta só para recalcular é
    justamente o que travava a tela.
    """
    return MINERACAO.estado.get("trials") or []



def _criterios_wfa(d: dict | None, e: dict):
    """Os critérios de aceite da mineração, prontos para cada janela IS.

    Vêm da mineração salva; as salvas antes de a plataforma gravá-los usam os
    padrões da tela de Critérios. A régua é a da mineração inteira (do início
    da base até o corte do holdout) e `wfa.criterios_por_janela` a traz para
    o tamanho de cada janela.

    Devolve (critérios, origem) — a origem vai para o resumo, para não
    esconder de onde veio o filtro.
    """
    salvos = (d or {}).get("criterios")
    base = salvos or {c["id"]: c["padrao"] for c in MS.CRITERIOS}
    try:
        meses = float((np.datetime64(str(e["ate_holdout"])[:10], "M")
                       - np.datetime64(str(e["de"])[:10], "M")).astype(int))
    except Exception:
        meses = 0.0
    return (wfa.criterios_por_janela(base, meses),
            "critérios da mineração" if salvos else "critérios padrão")


def _varredura(linhas):
    """As combinações que a ESTATÍSTICA deve enxergar.

    A tabela é truncada em 5.000 linhas pelo ranking, e truncada pelo topo:
    julgar a varredura por ela seria julgar só a metade boa. `estado["resumo"]`
    carrega todas as combinações válidas, com os campos que estas contas leem.
    O `fonte` evita o pior dos casos — uma varredura antiga ainda em memória
    descrevendo a mineração que você acabou de carregar do banco.
    """
    e = MINERACAO.estado
    completo = e.get("resumo")
    if completo and e.get("fonte"):
        return completo
    return linhas or []


def _detalhes(res, run, liq):
    """Monta a aba Detalhes: o que MEXER, em oposição ao "isto é sorte?" da
    Robustez. Sai tudo dos mesmos arrays — nenhum backtest roda de novo."""
    p, t, m = run["profile"], res.trades, run["metrics"]
    if not m.get("trades"):
        return DC.vazio("Nenhum trade para detalhar.")

    # o slippage ja esta embutido em points: sem descontá-lo aqui, TODA saida
    # por stop apareceria como stop furado
    folga = int(p.slippage_ticks * int(res.instrument.get("tick_size", 1)))

    return DC.render(
        m,
        detalhes.sequencias(liq),
        detalhes.eficiencia(t["mae"], t["mfe"], t["points"],
                            res.tp_at_entry, t["reason"], K.EXIT_TARGET),
        detalhes.risco_trade(liq, t["points"], res.sl_at_entry,
                             t["reason"], K.EXIT_STOP, folga),
        detalhes.ritmo(t["entry_ts"], liq, int(t["bars_held"].sum()),
                       res.n_bars, run["pregoes"]),
        AC.barras(detalhes.resultado_por_volume(t["entry_ts"], liq),
                  "Resultado por nº de trades no pregão"),
    )


def _robustez(res, run, liq):
    """Monta a aba de triagem. Tudo sai dos trades que já existem — nenhum
    backtest roda de novo, e por isso cabe recalcular a cada execução."""
    p = run["profile"]
    t = res.trades
    if len(liq) < 10:
        return RC.vazio("Poucos trades para avaliar robustez.")

    capital = p.capital_inicial
    dias = int((t["exit_ts"][-1] - t["entry_ts"][0]).astype("timedelta64[D]")
               .astype(int))
    dinheiro = run["dinheiro"]
    custo_ponta = p.corretagem_por_contrato + p.emolumentos_por_contrato

    return RC.render(
        robustez.monte_carlo(liq, capital),
        robustez.significancia(liq),
        robustez.teste_runs(liq),
        robustez.correlacao_lr(liq, capital),
        robustez.concentracao(liq),
        robustez.ulcer_mar(liq, capital, dias),
        robustez.meses_positivos(t["entry_ts"], liq),
        robustez.custo_que_zera(float(dinheiro["bruto"].sum()),
                                dinheiro["contratos"], custo_ponta),
        robustez.drawdowns(t["entry_ts"], liq, capital),
        porteira.sqn(liq),
    )


def register(app):
    # ------------------------------------------------------ modal do grafico
    @app.callback(
        Output("modal", "className"),
        Input("btn-chart", "n_clicks"),
        Input("grid-trades", "selectedRows"),
        Input("btn-close", "n_clicks"),
        Input("modal-fundo", "n_clicks"),
        prevent_initial_call=True,
    )
    def abrir_fechar(_a, selecionadas, _c, _d):
        gatilho = ctx.triggered_id
        if gatilho in ("btn-close", "modal-fundo"):
            return "modal"
        if gatilho == "grid-trades" and not selecionadas:
            return no_update
        return "modal aberto"

    # --------------------------- so o bloco do tipo escolhido fica na tela
    @app.callback(
        Output("blk-alvo-pontos", "style"), Output("blk-alvo-atr", "style"),
        Output("blk-stop-pontos", "style"), Output("blk-stop-atr", "style"),
        Input("e-alvo-tipo", "value"), Input("e-stop-tipo", "value"),
    )
    def tipos(alvo, stop):
        return (OCULTO if alvo == "atr" else VISIVEL,
                VISIVEL if alvo == "atr" else OCULTO,
                OCULTO if stop == "atr" else VISIVEL,
                VISIVEL if stop == "atr" else OCULTO)

    # ------------------------------------------------- backtest ou mineração
    @app.callback(
        Output("painel-backtest", "style"), Output("painel-mineracao", "style"),
        Output("painel-wfa", "style"), Output("painel-candidata", "style"),
        Output("acao-backtest", "style"), Output("sec-mineracao", "style"),
        Output("sidebar", "style"),
        Input("modo", "value"),
    )
    def modo(qual):
        """Três atividades diferentes, não três abas do mesmo painel.

        Backtest: a estratégia faz o que você desenhou? Um conjunto de
        parâmetros, curva de capital, trade a trade.
        Mineração: existe região boa no espaço? Milhares de conjuntos, nuvem
        e ranking.
        Walk-Forward: o meu PROCESSO de escolher parâmetro funciona? Aqui a
        combinação muda a cada janela, e o que se vê é a curva que o
        otimizador nunca enxergou. Misturar as três na mesma tela era o que
        confundia.
        """
        # flex, nao block: `display:block` sobrescreve o `display:flex` da
        # classe .modo-bloco e os paineis filhos perdem a altura - foi o que
        # deixava a tabela de mineracao invisivel, com altura zero.
        BLOCO = {"display": "flex"}
        v = lambda cond: BLOCO if cond else OCULTO
        # A barra lateral inteira sai no Walk-Forward E na Candidata: nos
        # dois os parâmetros não são escolhidos à mão. No WFA eles MUDAM a
        # cada janela, escolhidos pela inteligência de seleção; na Candidata
        # vêm do walk-forward salvo escolhido no topo do próprio painel.
        # Deixar os campos da barra lateral na tela convidaria a editá-los
        # achando que mudam alguma coisa.
        return (v(qual == "backtest"), v(qual == "mineracao"), v(qual == "wfa"),
                v(qual == "candidata"),
                VISIVEL if qual == "backtest" else OCULTO,
                VISIVEL if qual == "mineracao" else OCULTO,
                # BLOCK, e não flex: a barra lateral é um <aside> comum com
                # largura fixa. Devolvê-la como flex a transformava em
                # container de LINHA, e as seções (Período, Estratégia,
                # Parâmetros, Execução) se enfileiravam na horizontal — só a
                # primeira cabia, e o resto sumia no corte do overflow.
                OCULTO if qual in ("wfa", "candidata") else {"display": "block"})

    # ---- ou o valor fixo, ou a faixa de/passo/até - nunca os dois na tela
    @app.callback(
        Output({"type": "optrow", "p": ALL}, "style"),
        Output({"type": "valwrap", "p": ALL}, "style"),
        Output({"type": "opt-on", "p": ALL}, "style"),
        Input({"type": "opt-on", "p": ALL}, "value"),
        Input("modo", "value"),
    )
    def faixas(ligados, qual):
        minerando = qual == "mineracao"
        # em modo backtest não existe faixa nem interruptor: só o valor
        marcar = [bool(v) and minerando for v in ligados]
        return ([VISIVEL if m else OCULTO for m in marcar],
                [OCULTO if m else VISIVEL for m in marcar],
                [VISIVEL if minerando else OCULTO] * len(ligados))

    # -------------------------------------- tamanho do espaco de mineracao
    @app.callback(
        Output("espaco-busca", "children"),
        Input({"type": "opt-on", "p": ALL}, "value"),
        Input({"type": "opt", "p": ALL, "k": ALL}, "value"),
        State({"type": "opt-on", "p": ALL}, "id"),
        State({"type": "opt", "p": ALL, "k": ALL}, "id"),
    )
    def espaco(ligados, faixas, ids_on, ids_faixa):
        campos = _por_campo(ids_faixa, faixas)
        for ident, v in zip(ids_on, ligados):
            campos.setdefault(ident["p"], {})["on"] = bool(v)
        marcados = [p for p, r in campos.items() if r.get("on")]
        if not marcados:
            return "nenhum parâmetro marcado para minerar"
        n = _combinacoes(campos)
        _COMBOS["n"] = n     # lido por `pode_minerar`
        return (f"{len(marcados)} parâmetro(s) · "
                f"{n:,}".replace(",", ".") + " combinações na varredura")

    # ------------------------- trocar estratégia / carregar mineração salva
    @app.callback(
        [Output("estrategia", "value"),
         Output("mine-carregar", "value"),
         Output("params-body", "children"),
         Output("estrategia-nota", "children"),
         Output("grid-mine", "rowData", allow_duplicate=True),
         Output("scatter", "figure", allow_duplicate=True),
         Output("cards", "children", allow_duplicate=True),
         Output("grid-trades", "rowData", allow_duplicate=True),
         Output("chart-capital", "series", allow_duplicate=True),
         Output({"type": "val", "p": ALL}, "value", allow_duplicate=True),
         Output({"type": "opt", "p": ALL, "k": ALL}, "value"),
         Output({"type": "opt-on", "p": ALL}, "value"),
         Output("mine-info", "children", allow_duplicate=True),
         Output("wf-treino", "value"), Output("wf-teste", "value"),
         Output("wf-passo", "value"), Output("wf-holdout", "value")]
        + [Output(cid, "value", allow_duplicate=True) for cid, _ in CAMPOS_PERFIL],
        Input("estrategia", "value"),
        Input("mine-carregar", "value"),
        State({"type": "val", "p": ALL}, "id"),
        State({"type": "opt", "p": ALL, "k": ALL}, "id"),
        State({"type": "opt-on", "p": ALL}, "id"),
        prevent_initial_call=True,
    )
    def estrategia_ou_mineracao(nome, run_id, ids_val, ids_faixa, ids_on):
        """Único dono de `estrategia` e `mine-carregar`: um mexe no outro.

        Eram dois callbacks — trocar a estratégia limpava o seletor, carregar
        do seletor trocava a estratégia — e cada um era Input do outro. O
        Dash retém um callback enquanto um Input dele é Output de outro
        pendente; se os dois disparassem juntos, os dois esperariam para
        sempre, sem erro nenhum (foi assim que a barra do walk-forward
        congelou). Um callback só nunca espera por si mesmo: o renderer
        desconta dos Inputs as próprias Outputs, e escrever `estrategia`
        daqui não o dispara de novo.
        """
        sem_mudanca = [no_update] * (17 + len(CAMPOS_PERFIL))
        sem_mudanca[9:12] = ([no_update] * len(ids_val),
                             [no_update] * len(ids_faixa),
                             [no_update] * len(ids_on))
        if ctx.triggered_id == "mine-carregar":
            return _carregar_mineracao(run_id, ids_val, ids_faixa, ids_on,
                                       sem_mudanca)
        return _trocar_estrategia(nome, sem_mudanca)

    def _trocar_estrategia(nome, r):
        """Troca a estratégia e zera TUDO que veio da anterior.

        Não é higiene: os parâmetros mudam de nome e de significado entre
        estratégias, então uma tabela de mineração antiga ao lado dos campos
        novos seria um convite a clicar numa combinação que não existe mais.
        Melhor a tela vazia — inclusive o seletor da mineração carregada.
        """
        mod = registry.definir(nome)
        MINERACAO.esquecer()
        r[1:9] = (None, controls.campos_da_estrategia(mod), "", [],
                  scatter.vazio("Rode uma mineração para ver a nuvem de parâmetros."),
                  stats_cards.vazio(), [], [])
        return r

    def _carregar_mineracao(run_id, ids_val, ids_faixa, ids_on, r):
        """Carregar uma mineração repõe a TELA INTEIRA como ela estava.

        Não bastam as linhas da tabela: sem o perfil de execução e as faixas
        de volta nos campos, clicar numa combinação rodaria o backtest com o
        que estiver na tela agora — outro timeframe, outro custo, outra
        janela — e o resultado não bateria com a linha clicada.
        """
        if not run_id:
            return r
        d = optimizer.detalhes_salva(run_id)
        if not d:
            return r

        # A mineração manda: ela carrega a própria estratégia junto. Antes
        # isto era recusado, e a tela ficava mostrando "Cruzamento de médias"
        # com uma varredura de rompimento de canal carregada.
        try:
            mod = registry.definir(d["estrategia"])
        except Exception:
            r[12] = (f"mineração #{run_id} é da estratégia “{d['estrategia']}”, "
                     "que não está mais em strategies/")
            return r
        MINERACAO.estado["estrategia"] = d["estrategia"]

        faixas = optimizer.faixas_do_espaco(d["espaco"])
        perfil = d["perfil"] or {}

        # os parâmetros da estratégia vão embutidos na seção reconstruída;
        # os outputs por id cuidam só dos campos da camada 4
        r[0] = d["estrategia"]
        r[2] = controls.campos_da_estrategia(mod, faixas)
        r[3] = ""
        r[9] = [faixas.get(i["p"], {}).get("valor",
                                          perfil.get(i["p"], no_update))
                for i in ids_val]
        r[10] = [faixas.get(i["p"], {}).get(i["k"], no_update) for i in ids_faixa]
        r[11] = [["on"] if faixas.get(i["p"], {}).get("on") else []
                 for i in ids_on]
        r[12] = (f"mineração #{run_id} carregada"
                 + (f" · “{d['nome']}”" if d["nome"] else ""))

        # o walk-forward volta junto: é ele que define o corte do holdout,
        # e o backtest único precisa medir a mesma janela que a tabela mediu
        w = d.get("wf_config") or {}
        r[13:17] = (w.get("treino_meses", no_update), w.get("teste_meses", no_update),
                    w.get("passo_meses", no_update), w.get("holdout_meses", no_update))
        r[17:] = [perfil.get(chave, no_update) for _, chave in CAMPOS_PERFIL]
        return r

    # ------------------------------------------------------------------ rodar
    @app.callback(
        Output("store-run", "data"),
        Output("cards", "children"),
        Output("grid-trades", "rowData"),
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
        State("e-fechamento", "value"), State("e-dias", "value"),
        State("e-direcao", "value"),
        State("e-alvo-tipo", "value"), State("e-alvo-atr-per", "value"),
        State("e-alvo-atr-mult", "value"),
        State("e-stop-tipo", "value"), State("e-stop-atr-per", "value"),
        State("e-stop-atr-mult", "value"),
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
        prevent_initial_call=False,
    )
    def rodar(n, ativo, de, ate, tf, valores, ids_val, ent_ini, ent_fim, fechamento,
              dias, direcao, alvo_tipo, alvo_per, alvo_mult, stop_tipo, stop_per,
              stop_mult, max_barras, lim_ganho, lim_perda, max_trades, max_loss,
              corretagem, emolumentos, slippage, modo, contratos, risco, capital,
              min_ops, sem_holdout, holdout_m, treino_m, teste_m, passo_m):
        v = {i["p"]: val for i, val in zip(ids_val, valores)}
        mod = registry.atual()

        try:
            params = validate(mod.params_schema,
                              {k: v.get(k) for k in mod.params_schema})
        except ValueError as erro:
            return no_update, stats_cards.vazio(str(erro)), [], [], no_update, ""

        profile = ExecutionProfile(
            timeframe=tf or "M1",
            entrada_inicio=ent_ini or "09:00", entrada_fim=ent_fim or "17:00",
            fechamento=fechamento or "17:30",
            dias_semana=tuple(dias or (1, 2, 3, 4, 5)), direcao=direcao,
            alvo_tipo=alvo_tipo, alvo_pontos=v.get("alvo_pontos") or 0,
            alvo_atr_periodo=alvo_per or 20, alvo_atr_mult=alvo_mult or 0,
            stop_tipo=stop_tipo, stop_pontos=v.get("stop_pontos") or 0,
            stop_atr_periodo=stop_per or 20, stop_atr_mult=stop_mult or 0,
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
            return no_update, stats_cards.vazio("Sem barras no período."), [], [], no_update, ""

        t0 = time.perf_counter()
        try:
            res = run_strategy(bars, mod, params, profile, D.instrument(simbolo))
        except ValueError as erro:
            return no_update, stats_cards.vazio(str(erro)), [], [], no_update, ""
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
                "metrics": m,
                # pregoes do PERIODO, nao os operados: a aba Detalhes
                # compara um com o outro para medir seletividade
                "pregoes": int(len(np.unique(
                    bars["ts"].astype("datetime64[D]"))))}

        equity = charts.equity_series(res.trades, dinheiro["liquido"], profile.capital_inicial)
        linhas = results_grid.rows(res.trades, dinheiro)

        fim_janela = bars["ts"][-1].astype("datetime64[s]").item()
        janela = {"de": (fim_janela - timedelta(days=5)).isoformat(),
                  "ate": fim_janela.isoformat(), "trade": None}

        # A curva nasce enquadrada no backtest inteiro, não no zoom que a
        # biblioteca escolhe. O nonce muda a cada execução: sem ele o segundo
        # backtest repetiria o mesmo comando e o componente o ignoraria,
        # deixando o gráfico no zoom que você tinha dado no anterior.
        enquadrar = {"action": "fitContent", "nonce": token}

        return ({"token": token, "n_trades": res.n_trades}, stats_cards.render(m),
                linhas, equity, enquadrar, janela,
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
        State("e-timeframe", "value"), State("e-ent-ini", "value"),
        State("e-ent-fim", "value"), State("e-fechamento", "value"),
        State("e-dias", "value"), State("e-direcao", "value"),
        State("e-alvo-tipo", "value"), State("e-alvo-atr-per", "value"),
        State("e-alvo-atr-mult", "value"), State("e-stop-tipo", "value"),
        State("e-stop-atr-per", "value"), State("e-stop-atr-mult", "value"),
        State("e-max-barras", "value"), State("e-lim-ganho", "value"),
        State("e-lim-perda", "value"), State("e-max-trades", "value"),
        State("e-max-loss", "value"), State("e-corretagem", "value"),
        State("e-emolumentos", "value"), State("e-slippage", "value"),
        State("e-modo", "value"), State("e-contratos", "value"),
        State("e-risco", "value"), State("e-capital", "value"),
        State("e-min-ops", "value"), State("wf-workers", "value"),
        State("ativo", "value"),
        prevent_initial_call=True,
    )
    def minerar(n, _tick, treino, teste, passo, holdout, ligados, faixas,
                ids_on, ids_faixa, de, ate, valores, ids_val, tf, ent_ini,
                ent_fim, fechamento, dias, direcao, alvo_tipo, alvo_per,
                alvo_mult, stop_tipo, stop_per, stop_mult, max_barras,
                lim_ganho, lim_perda, max_trades, max_loss, corretagem,
                emolumentos, slippage, modo, contratos, risco, capital,
                min_ops, workers, ativo):
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

        perfil = ExecutionProfile(
            timeframe=tf or "M1",
            entrada_inicio=ent_ini or "09:00", entrada_fim=ent_fim or "17:00",
            fechamento=fechamento or "17:30",
            dias_semana=tuple(dias or (1, 2, 3, 4, 5)), direcao=direcao,
            alvo_tipo=alvo_tipo, alvo_atr_periodo=alvo_per or 20,
            alvo_atr_mult=alvo_mult or 0, stop_tipo=stop_tipo,
            stop_atr_periodo=stop_per or 20, stop_atr_mult=stop_mult or 0,
            max_barras=max_barras or 0,
            limite_ganho_contrato=lim_ganho or 0, limite_perda_contrato=lim_perda or 0,
            max_trades_dia=max_trades or 0, max_prejuizos_dia=max_loss or 0,
            corretagem_por_contrato=corretagem or 0.0,
            emolumentos_por_contrato=emolumentos or 0.0,
            slippage_ticks=slippage or 0, modo_posicao=modo,
            contratos=contratos or 1, risco_por_trade=risco,
            capital_inicial=capital or 10_000.0, min_operacoes=min_ops or 0,
        )

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

    # --------------------------------------------------- salvar sob demanda
    @app.callback(Output("btn-salvar", "n_clicks"),
                  Input("btn-salvar", "n_clicks"), State("mine-nome", "value"),
                  *[State(f"crit-{c['id']}", "value") for c in MS.CRITERIOS],
                  prevent_initial_call=True)
    def salvar(n, nome, *limites):
        # os critérios vão junto: o walk-forward desta mineração os aplica
        # dentro de cada janela IS
        MINERACAO.salvar((nome or "").strip() or None,
                         {c["id"]: v for c, v in zip(MS.CRITERIOS, limites)})
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

    # ----------------------------------------- carregar mineração salva
    @app.callback(
        Output("mine-carregar", "options"),
        Input("tick", "n_intervals"), Input("btn-salvar", "n_clicks"),
        Input("modo", "value"), Input("estrategia", "value"),
    )
    def listar_salvas(_t, _s, _modo, _estrategia):
        """A lista é sempre da estratégia ATIVA.

        `estrategia` precisa ser Input, não apenas leitura: o relógio fica
        parado quando não há mineração, então sem este gatilho a lista
        continuava mostrando as varreduras da estratégia anterior — e
        carregar uma delas trazia combinações com parâmetros que nem
        existem nos campos.
        """
        return [{"label": r["rotulo"], "value": r["run_id"]}
                for r in optimizer.listar_salvas(registry.nome_atual())]

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
            e["trials"] = optimizer.carregar_salva(run_id)
            # o banco nao trunca: aqui a tabela E o universo completo
            e["resumo"], e["fonte"] = e["trials"], "banco"
            e["fim_otimizacao"] = d.get("corte") or d["holdout_de"]
            e["mensagem"] = f"mineração #{run_id} carregada do banco"
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
        return scatter.figura(linhas, x, y, z, metrica or "robusto")

    # ------- cross-filtering: um caminho, dois gatilhos (nuvem e tabela)
    @app.callback(
        Output({"type": "val", "p": ALL}, "value"),
        Output("excluir-holdout", "value"),
        Output("btn-run", "n_clicks"),
        Input("grid-mine", "selectedRows"),
        Input("scatter", "clickData"),
        Input("grid-aprovadas", "selectedRows"),
        State({"type": "val", "p": ALL}, "id"),
        State("grid-mine", "rowData"),
        State("btn-run", "n_clicks"),
        State("mine-carregar", "value"),
        prevent_initial_call=True,
    )
    def carregar_combinacao(selecionadas, clique, aprovadas, ids_val, linhas,
                            n_run, run_salva):
        """Clique no ponto da nuvem, na linha da tabela OU na lista de
        aprovadas carrega os mesmos campos e dispara o mesmo backtest.

        Além dos parâmetros, alinha o PERÍODO — ligando a chave "excluir
        holdout" em vez de reescrever a data final. A tabela mede só até o
        começo do holdout; sem esse recorte o backtest rodaria 12 meses a
        mais que a linha clicada e mostraria outro lucro para a mesma
        combinação. O recorte é derivado na hora a partir das datas, que
        permanecem intocadas.
        """
        p = None
        if ctx.triggered_id == "scatter" and clique:
            alvo = clique["points"][0].get("customdata")
            p = next((l["params"] for l in (linhas or [])
                      if l["trial_id"] == alvo), None)
        elif ctx.triggered_id == "grid-aprovadas" and aprovadas:
            p = aprovadas[0].get("params")
        elif selecionadas:
            p = selecionadas[0].get("params")
        if not p:
            return [no_update] * len(ids_val), no_update, no_update
        return ([p.get(i["p"], no_update) for i in ids_val],
                ["on"], (n_run or 0) + 1)

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
        moeda = metrica in MS.DINHEIRO
        valores = np.array([l[metrica] for l in linhas
                            if l.get(metrica) is not None], dtype=float)
        if not len(valores):
            v = MC._vazio("Nenhuma combinação tem esta métrica.")
            return RG.cards(MS.resumo(linhas)), v, v

        return (
            RG.cards(MS.resumo(linhas)),
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
                         truncada=len(todas) - len(linhas))

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
        Output("wfa-mineracao", "options"), Output("wfa-mineracao", "value"),
        Input("wfa-estrategia", "value"),
        State("wfa-mineracao", "value"),
    )
    def wfa_mineracoes(estrategia, atual):
        """Minerações salvas DA estratégia escolhida.

        O espaço de busca que o walk-forward reotimiza vem da mineração: é
        ela que gravou as faixas de cada parâmetro. Por isso a lista é
        filtrada — uma varredura de rompimento de canal não tem espaço que
        sirva a um cruzamento de médias.
        """
        if not estrategia:
            return [], None
        salvas = optimizer.listar_salvas(estrategia)
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
                     run_id, ativo, store_atual):
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
                               holdout, run_id, ativo, store_atual, vazio)
        except PreventUpdate:
            raise
        except Exception as erro:          # banco travado, mineração corrompida…
            return (f"falhou ao montar o walk-forward: {erro}", *vazio)
        finally:
            if not e["rodando"] and e["pronto"]:
                e["entregue"] = True

    def _wfa_montar(gatilho, _n, is_m, oos_m, inteligencia, holdout, run_id,
                    ativo, store_atual, vazio):
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
        passos = wfa.rodar(cache, janelas, capital, qual, crit)
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
                    capital=capital,
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
        return ("",
                WP.curva(ts, liq, steps, passos, capital, fixas,
                         holdout_de=e["ate_holdout"] if estende else None),
                WP.kpis(passos, ts, liq, ag, capital,
                        custo=oos["custo"], saida=oos["exit_ts"]),
                WP.linhas_steps(passos),
                f"{ag.get('steps', 0)} janelas · IS {is_m}/OOS {oos_m} · {rotulo}"
                + (" · holdout incluído" if estende else " · até o holdout")
                + f" · {origem_crit} · {simbolo}",
                WP.selo(ver),
                WP.drift_figs(wfa.drift(passos, d["espaco"])),
                WP.fita(passos),
                WP.cards_mensais(mes),
                WP.mensal_fig(mes),
                AC.ganho_perda(analytics.por_dia_semana(ts, liq),
                               "Lucro × prejuízo por dia da semana (OOS)"),
                AC.ganho_perda(analytics.por_hora(ts, liq),
                               "Lucro × prejuízo por hora de entrada (OOS)"),
                WP.linhas_trades(ts, liq, steps, capital,
                                 saida=oos["exit_ts"], custo=oos["custo"]),
                marca if marca != store_atual else no_update)

    # ------------------------------------------- a matriz das 12 configurações
    @app.callback(
        Output("store-matriz", "data"),
        Input("store-wfa", "data"),
        Input("wfa-holdout", "value"),
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
    def wfa_matriz(store, holdout):
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
        chave = f"{e.get('run_id')}-{e.get('geracao')}-{int(estende)}"
        guardadas = _WFA.setdefault("matrizes", {})
        with _MATRIZ_LOCK:          # duas threads não calculam a mesma matriz
            return _matriz_guardada(guardadas, chave, cache, e, estende)

    def _matriz_guardada(guardadas, chave, cache, e, estende):
        if chave not in guardadas:
            fim = e["ate"] if estende else e["ate_holdout"]
            d = optimizer.detalhes_salva(e.get("run_id")) if e.get("run_id") else None
            por_q = wfa.matrizes(cache, e["de"], fim,
                                 float(e["capital"] or 10_000.0),
                                 criterios=_criterios_wfa(d, e)[0])
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
        """
        if ctx.triggered_id == "mine-carregar":
            return (not run_id), "Excluir", no_update
        if not run_id:
            return True, "Excluir", no_update
        if rotulo != "Confirmar?":
            return False, "Confirmar?", no_update
        optimizer.excluir_salva(int(run_id))
        MINERACAO.esquecer()
        return True, "Excluir", None

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
        State("wfa-nome", "value"),
    )
    def wfa_guardar(_s, _lista, estrategia, _store, nome):
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
            # configuração — sem casar run/geração/holdout, os sharpes
            # viriam de outra varredura ou do outro lado do holdout
            chave = (f"{_WFA.get('run_id')}-{(_store or {}).get('g')}-"
                    f"{int(_WFA.get('holdout', False))}")
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
                capital=_WFA.get("capital"), sharpes_matriz=sharpes)
            aviso = (f"walk-forward #{wid} salvo · "
                     f"{len(trades)} trades gravados para o portfólio")
        elif gatilho == "store-wfa-lista":
            aviso = no_update           # quem excluiu já escreveu o aviso

        # o dropdown lê label/value; `listar` devolve o registro inteiro,
        # que serve para gravar mas não para desenhar
        salvos = wfa_store.listar(estrategia or registry.nome_atual())
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
        wfa_store.excluir(int(wfa_id))
        return ("Excluir", None, f"walk-forward #{wfa_id} excluído",
                {"excluido": int(wfa_id), "t": __import__("time").time()})

    @app.callback(
        Output("wfa-estrategia", "value", allow_duplicate=True),
        Output("wfa-mineracao", "value", allow_duplicate=True),
        Output("wfa-is", "value", allow_duplicate=True),
        Output("wfa-oos", "value", allow_duplicate=True),
        Output("wfa-inteligencia", "value"),
        Output("wfa-holdout", "value"),
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
            return (*[no_update] * 8,
                    f"a mineração #{d['run_id']} deste walk-forward foi excluída")
        return (d["strategy"], d["run_id"], d["is_meses"], d["oos_meses"],
                d["inteligencia"], ["on"] if d["holdout"] else [],
                d.get("nome") or "", {"wfa_id": int(wfa_id)}, "")

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
                                geral=geral)

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
        t, p = res.trades, run["profile"]

        diag = analytics.calor_mae_mfe(t["mae"], t["mfe"], liq)
        dicas = analytics.sugestoes(diag, p.stop_pontos, p.alvo_pontos)

        return (
            AC.ganho_perda(analytics.por_hora(t["entry_ts"], liq),
                           "Lucro × prejuízo por hora de entrada"),
            AC.ganho_perda(analytics.por_dia_semana(t["entry_ts"], liq),
                           "Lucro × prejuízo por dia da semana"),
            AC.ganho_perda(analytics.por_mes(t["entry_ts"], liq),
                           "Lucro × prejuízo por mês do ano"),
            AC.calendario(analytics.calendario_mensal(t["entry_ts"], liq)),
            AC.mae_mfe(diag, p.stop_pontos, p.alvo_pontos),
            AC.barras(analytics.por_duracao(t["bars_held"], liq,
                                            TIMEFRAMES.get(p.timeframe, 1)),
                      f"Lucro por tempo em posição (barras {p.timeframe})"),
            AC.barras(analytics.por_motivo(t["reason"], liq, K.EXIT_LABELS),
                      "Lucro por motivo de saída", com_expectativa=False),
            AC.histograma(analytics.distribuicao(liq)),
            [html.P(d, className="dica") for d in dicas],
            _detalhes(res, run, liq),
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
        dados = D.candles(_simbolo(ativo), de, ate, tf or "auto")
        if not dados["candles"]:
            return [], no_update, "sem barras nesta janela", ""

        marcas, linhas, nota = [], [], ""
        if run and run.get("token") in _runs:
            r = _runs[run["token"]]
            t0 = dados["candles"][0]["time"]
            t1 = dados["candles"][-1]["time"]
            marcas = charts.trade_markers(r["res"].trades, t0, t1)
            i = janela.get("trade")
            if i is not None:
                linhas = charts.trade_price_lines(r["res"], i)
                nota = f"trade #{i + 1} em foco"
            else:
                nota = f"{len(marcas) // 2} operações nesta janela"

        info = (f"{de:%d/%m/%Y %H:%M} — {ate:%d/%m/%Y %H:%M}"
                + (f" · {nota}" if nota else ""))
        # enquadra a janela que acabou de ser carregada, em vez de herdar o
        # zoom da anterior; o nonce e a propria janela, entao trocar de faixa
        # ou de timeframe reenquadra
        enquadrar = {"action": "fitContent",
                     "nonce": f"{janela['de']}|{janela['ate']}|{tf}"}
        return (charts.price_series(dados, marcas, linhas), enquadrar, info,
                f"{dados['timeframe']} · {len(dados['candles'])} candles")

    from ui import callbacks_candidata
    callbacks_candidata.register(app)
