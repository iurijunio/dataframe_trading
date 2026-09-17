"""Callbacks da tela Candidata.

Em arquivo próprio: `ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são
do walk-forward. Arquivo focado é o que permite o teste de ciclo apontar
para um lugar pequeno quando algo trava.
"""

from __future__ import annotations

from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from core import candidata, wfa_runner, wfa_store
from core import db_manager as db
from core import optimizer
from core.candidata_runner import TESTES

from .components import candidata_panel as CP
from .components import wfa_panel as WP

# o selo compartilha o HTML da aba Walk-Forward (`wfa_panel.selo`), só com
# uma pergunta diferente no título — a aba Walk-Forward continua com o
# título padrão dela
TITULO_SELO = "a estratégia está pronta para a incubação?"


def _texto_resumo(d: dict) -> str:
    """O cabeçalho ao lado do seletor, em palavras de quem opera.

    Avisa quando o walk-forward foi salvo com o holdout incluído: a curva
    que a tela analisa contém esses meses.
    """
    base = (f"{d.get('strategy', '—')} · {d.get('symbol', '—')} · "
            f"IS {d.get('is_meses')} meses / OOS {d.get('oos_meses')} meses · "
            f"inteligência {d.get('inteligencia', '—')}")
    return base + (" · holdout incluído" if d.get("holdout") else "")


def _rotulo_curto(w: dict) -> str:
    """Só o que identifica o walk-forward. WFE e janelas positivas já estão
    na aba Walk-Forward, e o holdout aparece no resumo ao lado."""
    quando = w.get("quando")
    data = f" · {quando:%d/%m}" if quando else ""
    return (f"#{w['wfa_id']} · {w.get('nome') or 'sem nome'} · "
            f"IS {w['is_meses']} / OOS {w['oos_meses']}{data}")


def _valor_do_seletor(atual, ids: set, aberto_no_wfa, padrao=None):
    """O que fica selecionado depois de a lista ser refeita — vale para o
    seletor de estratégia e para o de walk-forward.

    - a escolha atual continua valendo enquanto existir;
    - sem escolha (ou com uma que sumiu), herda a da aba Walk-Forward, se
      ela estiver na lista;
    - senão, o padrão (a primeira estratégia, no seletor de estratégia).
    """
    if atual in ids:
        return atual
    if aberto_no_wfa in ids:
        return aberto_no_wfa
    return padrao


def _gates_e_leitura(wfa_id: int, d: dict):
    """A leitura de robustez e a lista de portões (rápidos + os três
    demorados, prontos ou pendentes) deste walk-forward.

    Compartilhado pela tabela e pelo selo: os dois nascem do MESMO cálculo,
    para a linha "holdout" da tabela não rodar o bootstrap do portão do
    holdout (`candidata.portao_holdout`) uma segunda vez — são 2.000
    caminhos simulados, caro para pagar duas vezes por clique.

    `gates` vem `None` quando `leitura_robustez` recusou a amostra (menos
    de 100 trades fora da amostra): sem leitura não há platô, capital nem
    holdout para montar o resto dos portões.
    """
    capital = d.get("capital")
    trades = wfa_store.trades(wfa_id)
    horizonte = candidata.calcula_horizonte(d)
    de, ate = candidata.limites_oos(d.get("passos"))
    leitura = candidata.leitura_robustez(trades, capital, horizonte, de=de, ate=ate)
    if leitura.get("erro"):
        return leitura, None, de, ate

    run_id = d["run_id"]
    detalhes_mine = optimizer.detalhes_salva(run_id) or {}
    trials = optimizer.carregar_salva(run_id)
    espaco = detalhes_mine.get("espaco") or {}
    corte = detalhes_mine.get("holdout_de")
    deploy = (d.get("deploy") or {}).get("params") or {}
    # o mesmo carregador de YAML que o backtest usa — não o cache de
    # `ui/data.py`, que existe para as barras, não para o instrumento
    tick_value = float(db.load_instrument_yaml(d["symbol"]).get("tick_value") or 0.0)

    rapidos = candidata.portoes_rapidos(
        trades, leitura, trials, espaco, deploy, corte, tick_value, capital,
        de=de, ate=ate)
    resultado = TESTES.resultado_de(wfa_id)
    lentos = resultado["portoes"] if resultado else candidata.portoes_pendentes()
    return leitura, rapidos + lentos, de, ate


def register(app):
    @app.callback(
        Output("cand-estrategia", "options"),
        Output("cand-estrategia", "value"),
        Input("modo", "value"),
        Input("store-wfa-lista", "data"),
        State("cand-estrategia", "value"),
        State("wfa-estrategia", "value"),
    )
    def cand_estrategias(qual, _lista, atual, na_aba_wfa):
        """Só as estratégias que têm walk-forward salvo — as outras abririam
        uma lista vazia. Começa pela estratégia aberta na aba Walk-Forward.

        O valor só é reescrito quando muda: devolver o mesmo valor faria o
        Dash recalcular a tela inteira a cada entrada no modo.
        """
        if qual != "candidata":
            return no_update, no_update
        nomes = wfa_store.estrategias()
        valor = _valor_do_seletor(atual, set(nomes), na_aba_wfa,
                                  padrao=nomes[0] if nomes else None)
        return ([{"label": n, "value": n} for n in nomes],
                no_update if valor == atual else valor)

    @app.callback(
        Output("cand-wfa", "options"),
        Output("cand-wfa", "value"),
        Input("cand-estrategia", "value"),
        Input("store-wfa-lista", "data"),
        State("cand-wfa", "value"),
        State("wfa-salvos", "value"),
    )
    def cand_opcoes(estrategia, _lista, atual, aberto):
        """Os walk-forwards salvos da estratégia escolhida, refeitos também
        quando um é salvo ou excluído na aba Walk-Forward."""
        salvos = wfa_store.listar(estrategia) if estrategia else []
        opcoes = [{"label": _rotulo_curto(w), "value": w["wfa_id"]}
                  for w in salvos]
        valor = _valor_do_seletor(atual, {w["wfa_id"] for w in salvos}, aberto)
        return opcoes, (no_update if valor == atual else valor)

    @app.callback(
        Output("cand-resumo", "children"),
        Input("cand-wfa", "value"),
    )
    def cand_resumo(wfa_id):
        if not wfa_id:
            return "escolha um walk-forward salvo"
        d = wfa_store.detalhes(int(wfa_id)) or {}
        return _texto_resumo(d)

    @app.callback(
        Output("cand-blocos", "children"),
        Output("cand-portoes", "children"),
        Input("cand-wfa", "value"),
        # o Store que `cand_fim_dos_testes` escreve UMA vez por geração: é
        # ele, e não o relógio, quem faz o selo ser recalculado com o
        # resultado novo dos três testes demorados
        Input("cand-testes", "data"),
    )
    def cand_conteudo(wfa_id, _testes):
        if not wfa_id:
            vazio = CP.vazio("escolha um walk-forward salvo para analisar")
            return vazio, html.Div()
        wid = int(wfa_id)
        d = wfa_store.detalhes(wid) or {}
        capital = d.get("capital")
        if capital is None:
            vazio = CP.vazio(
                "este walk-forward foi salvo antes desta tela: não tem "
                "capital nem perfil gravados. Rode e salve o walk-forward "
                "de novo para analisá-lo.")
            return vazio, html.Div()

        leitura, gates, de, ate = _gates_e_leitura(wid, d)
        holdout_gate = (next((g for g in gates if g["nome"] == "O holdout confirma?"),
                             None) if gates else None)
        blocos = CP.bloco_robustez(leitura, capital, holdout=bool(d.get("holdout")),
                                   de=de, ate=ate, holdout_gate=holdout_gate)
        if gates is None:
            return blocos, CP.vazio(leitura.get("erro") or
                                    "sem dado suficiente para medir os portões")
        ver = candidata.veredito(gates)
        return blocos, WP.selo(ver, titulo=TITULO_SELO)

    # ------------------------------------------ os três testes demorados
    @app.callback(
        Output("btn-cand-testes", "children"),
        Output("btn-cand-testes", "disabled"),
        Output("cand-tick", "disabled"),
        Output("cand-aviso-testes", "children"),
        Input("btn-cand-testes", "n_clicks"),
        Input("cand-wfa", "value"),
        Input("cand-tick", "n_intervals"),
        State("btn-cand-testes", "children"),
    )
    def cand_botao_testes(_n, wfa_id, _t, rotulo):
        """O botão e o relógio PRÓPRIO da Candidata (`cand-tick`).

        O `dcc.Interval` `tick` já tem dono único (`pulso`, em
        `ui/callbacks.py`); ligar nele faria a barra da Candidata reagir a
        toda batida da mineração e da varredura do Walk-Forward, sem
        relação nenhuma com os testes completos.

        Clicar sobre uma varredura pronta de OUTRA mineração pede
        confirmação — mesmo padrão de dois cliques da exclusão de mineração
        e de walk-forward salvo, em `ui/callbacks.py`: rodar os testes vai
        substituir aquele cache, e a aba Walk-Forward vai precisar rodar de
        novo.

        Sem `prevent_initial_call`: depois de um F5, os testes podem
        continuar rodando no servidor (mesmo desenho de
        `wfa_runner.Varredura`), e é este disparo no carregamento que
        corrige o botão e o relógio para o estado real.
        """
        e = TESTES.estado
        gatilho = ctx.triggered_id
        if gatilho == "btn-cand-testes":
            if not wfa_id or e["rodando"]:
                raise PreventUpdate
            wid = int(wfa_id)
            d = wfa_store.detalhes(wid) or {}
            v = wfa_runner.VARREDURA
            # "há cache de outra mineração": pronta e de um run_id diferente
            # do desta — rodando para outro run_id já dá erro sozinho
            # dentro de `TESTES` (`_garantir_varredura`), sem precisar de
            # aviso prévio aqui
            colide = (v.estado.get("run_id") not in (None, d.get("run_id"))
                     and v.estado.get("pronto"))
            if colide and rotulo != "Confirmar?":
                return ("Confirmar?", False, True,
                        "isto refaz a varredura e a aba Walk-Forward vai "
                        "pedir para executar de novo")
            TESTES.iniciar(wid)
            # `iniciar` já deixou `rodando=True` (chamada síncrona): o
            # relógio liga nesta mesma resposta, sem esperar o próximo tick
            return "Rodando…", True, False, ""

        # troca de walk-forward ou batida do relógio: só reflete o estado
        # atual dos testes — nenhum dos dois dispara nada sozinho
        rodando = e["rodando"]
        texto = "Rodando…" if rodando else "Rodar testes completos"
        desabilitado = rodando or not wfa_id
        aviso = "" if gatilho == "cand-wfa" else no_update
        return texto, desabilitado, not rodando, aviso

    @app.callback(
        Output("cand-prog", "className"),
        Output("cand-prog-txt", "children"),
        Output("cand-prog-pct", "children"),
        Output("cand-prog-bar", "style"),
        Input("cand-tick", "n_intervals"),
        Input("cand-wfa", "value"),
    )
    def cand_progresso(_t, _wfa):
        est = CP.estado_testes(TESTES.estado)
        pct_txt = f"{est['pct']:.0f}%" if est["ocupado"] else ""
        return (f"wfa-prog {est['fase']}", est["txt"], pct_txt,
                {"width": f"{est['pct']:.0f}%"})

    @app.callback(
        Output("cand-testes", "data"),
        Input("cand-tick", "n_intervals"),
        State("cand-testes", "data"),
        prevent_initial_call=True,
    )
    def cand_fim_dos_testes(_t, anunciado):
        """Anuncia o fim dos testes completos UMA vez por geração — sucesso
        ou erro. É este Store, e não o relógio, quem `cand_conteudo` ouve
        para recalcular o selo (mesmo padrão de `wfa_fim_da_varredura`, em
        `ui/callbacks.py`)."""
        e = TESTES.estado
        pronto = e.get("resultado") is not None or e.get("erro")
        if e["rodando"] or not pronto or (anunciado or {}).get("g") == e.get("geracao"):
            raise PreventUpdate
        return {"g": e.get("geracao")}
