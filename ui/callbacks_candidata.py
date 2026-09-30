"""Callbacks da tela Candidata.

Em arquivo próprio: `ui/callbacks.py` já tem 1.771 linhas, das quais ~700 são
do walk-forward. Arquivo focado é o que permite o teste de ciclo apontar
para um lugar pequeno quando algo trava.
"""

from __future__ import annotations

import numpy as np
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from core import (candidata, codigo, diario, plano, tamanho, wfa, wfa_runner,
                  wfa_store)
from core import db_manager as db
from core import optimizer
from core.candidata_runner import TESTES

from strategies import registry

from .components import candidata_panel as CP
from .components import wfa_panel as WP

# o selo compartilha o HTML da aba Walk-Forward (`wfa_panel.selo`), só com
# uma pergunta diferente no título — a aba Walk-Forward continua com o
# título padrão dela
TITULO_SELO = "a estratégia está pronta para a incubação?"

# A leitura de robustez de cada walk-forward, guardada por id.
#
# São 2.000 caminhos sorteados duas vezes (curva inteira e últimos 12 meses),
# ~0,35 s. Sem guardar, cada mexida no dial de risco — que não muda a curva,
# só o tamanho da posição — refazia tudo: arrastar 1% para 2% de 0,1 em 0,1
# custava quase quatro segundos de conta repetida. Não dá para usar um
# `dcc.Store`: a leitura carrega arrays do numpy (as quedas sorteadas, a
# faixa por pregão) que não viram JSON.
#
# A chave é o `wfa_id`, e ele nunca é reaproveitado: regravar o mesmo
# walk-forward cria um id novo (ver `wfa_store.salvar`). Guarda os três
# últimos — a tela compara poucos de cada vez.
_LEITURAS: dict[int, dict] = {}
_LEITURAS_MAX = 3


def leitura_do_wfa(wfa_id: int, d: dict) -> dict:
    """A leitura de robustez deste walk-forward, calculada uma vez só.

    Devolve `{"leitura", "trades", "de", "ate"}` — os trades vêm junto
    porque quem dimensiona precisa deles e lê-los de novo do banco seria a
    segunda consulta pela mesma coisa no mesmo clique.
    """
    if wfa_id in _LEITURAS:
        return _LEITURAS[wfa_id]
    capital = d.get("capital")
    trades = wfa_store.trades(wfa_id)
    horizonte = candidata.calcula_horizonte(d)
    de, ate = candidata.limites_oos(d.get("passos"))
    leitura = candidata.leitura_robustez(trades, capital, horizonte,
                                         de=de, ate=ate)
    if len(_LEITURAS) >= _LEITURAS_MAX:
        _LEITURAS.pop(next(iter(_LEITURAS)))
    _LEITURAS[wfa_id] = {"leitura": leitura, "trades": trades,
                         "de": de, "ate": ate}
    return _LEITURAS[wfa_id]


def _nome_da_estrategia(modulo: str | None) -> str:
    """O nome que a estratégia mostra na tela, não o do arquivo.

    O banco guarda o módulo (`rompimento_canal`); a tela toda mostra o nome
    declarado pela estratégia (`label`/`name`), e os dois precisam bater —
    ler "rompimento_canal" aqui e "Rompimento de Canal" nas outras abas faz
    o operador duvidar se está olhando a mesma coisa.
    """
    if not modulo:
        return "—"
    for e in registry.descobrir():
        if e["modulo"] == modulo:
            return e.get("label") or modulo
    return modulo


def _nome_da_inteligencia(chave: str | None) -> str:
    """O rótulo da inteligência de seleção, como aparece no Walk-Forward.

    O banco guarda a chave (`ulcer`, `vizinhanca`); quem escolheu na aba
    Walk-Forward escolheu "Estabilidade de Drawdown" e "Platô Pessimista".
    Mostrar a chave aqui parece outra inteligência.
    """
    if not chave:
        return "—"
    return dict((q, r) for r, q in wfa.INTELIGENCIAS).get(chave, chave)


def _texto_resumo(d: dict) -> str:
    """O cabeçalho ao lado do seletor, em palavras de quem opera.

    Avisa quando o walk-forward foi salvo com o holdout incluído: a curva
    que a tela analisa contém esses meses.
    """
    base = (f"{_nome_da_estrategia(d.get('strategy'))} · "
            f"{d.get('symbol', '—')} · "
            f"IS {d.get('is_meses')} meses / OOS {d.get('oos_meses')} meses · "
            f"inteligência {_nome_da_inteligencia(d.get('inteligencia'))}")
    return base + (" · holdout incluído" if d.get("holdout") else "")


def _rotulo_curto(w: dict) -> str:
    """Só o que identifica o walk-forward. WFE e janelas positivas já estão
    na aba Walk-Forward, e o holdout aparece no resumo ao lado."""
    quando = w.get("quando")
    data = f" · {quando:%d/%m}" if quando else ""
    return (f"#{w['wfa_id']} · {w.get('nome') or 'sem nome'} · "
            f"IS {w['is_meses']} / OOS {w['oos_meses']}{data}"
            + (" · tem plano" if w.get("tem_plano") else ""))


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
    guardado = leitura_do_wfa(wfa_id, d)
    leitura, trades = guardado["leitura"], guardado["trades"]
    de, ate = guardado["de"], guardado["ate"]
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
    #
    # `... or 0.0` fingia tick zero quando o YAML não declara `tick_value` —
    # o portão de custo passava sem cobrar tick nenhum. Sem o dado, `None`
    # segue adiante e `candidata.portao_custo` fica pendente, não aprovado.
    tick_value_yaml = db.load_instrument_yaml(d["symbol"]).get("tick_value")
    tick_value = float(tick_value_yaml) if tick_value_yaml is not None else None

    rapidos = candidata.portoes_rapidos(
        trades, leitura, trials, espaco, deploy, corte, tick_value, capital,
        de=de, ate=ate)
    resultado = TESTES.resultado_de(wfa_id)
    lentos = resultado["portoes"] if resultado else candidata.portoes_pendentes()
    return leitura, rapidos + lentos, de, ate


def _dimensionar(trades: list[dict], d: dict, leitura: dict, de, ate,
                 risco_pct, margem, uso_margem_pct) -> tuple[dict, dict, dict]:
    """A perda de referência, os contratos e o disjuntor deste walk-forward.

    Separado do callback para poder ser testado sem montar o app Dash. Não
    decide nada: junta o que o banco tem (trades, perfil, instrumento) e
    entrega a `core/tamanho.py`.
    """
    perfil = d.get("profile") or {}
    inst = db.load_instrument_yaml(d["symbol"])
    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liq = np.array([t["liquido"] for t in trades], dtype=float)
    custo = float(np.mean([t.get("custo") or 0.0 for t in trades])) if trades else 0.0
    dias, pnl = candidata.por_pregao(saida, liq, de=de, ate=ate)
    # Quantas operações teve o pregão mais movimentado — a reserva para o dia
    # ruim quando o perfil não tem limite diário nenhum. Conta pela data de
    # SAÍDA, como o resto da tela, o que só casa com o limite do motor porque
    # a estratégia é intradiária. E conta DENTRO do mesmo recorte de/até que
    # produziu o resto da conta: um pregão movimentado fora da janela não
    # pertence a esta curva.
    dentro = saida.astype("datetime64[D]")
    if len(dias):
        dentro = dentro[(dentro >= dias[0]) & (dentro <= dias[-1])]
    por_dia = np.unique(dentro, return_counts=True)[1]

    ref = tamanho.perda_referencia(
        pnl, perfil.get("contratos") or 1, perfil, inst.get("point_value"),
        piso=inst.get("tick_value"), custo_por_trade=custo,
        trades_no_dia=int(por_dia.max()) if len(por_dia) else None)
    dim = tamanho.contratos(d.get("capital"), risco_pct, ref.get("valor"),
                            margem=margem,
                            uso_margem_pct=uso_margem_pct or tamanho.USO_MARGEM)
    # com zero contratos o disjuntor não existe; a tela mostra a conta de 1
    # contrato, avisando que é mais do que o risco pedido permite — vazio
    # ali seria esconder informação medida de quem mais precisa dela
    # os contratos do BACKTEST: o sorteio saiu da curva dele, e sem isto os
    # limites de um backtest de 2 contratos saíam do dobro do tamanho real
    disj = tamanho.disjuntor(leitura, d.get("capital"), dim["n"] or 1, perfil,
                             contratos_backtest=perfil.get("contratos") or 1)
    return ref, dim, disj


def veredito_para_tela(wfa_id: int, ver: dict) -> dict:
    """O veredito no formato que viaja para o navegador e volta.

    Só o que o botão de gravar precisa: o estado, os nomes do que reprovou ou
    não foi medido (para o motivo em palavras) e os portões como estavam no
    dia, que viram a régua congelada do plano. Os valores passam por JSON de
    ida e volta para chegar ao `dcc.Store` sem número do numpy.
    """
    import json
    portoes = json.loads(plano._js([plano._portao_para_json(p)
                                    for p in ver.get("portoes") or []]))
    return {"wfa_id": wfa_id, "estado": ver.get("estado"),
            "reprovados": [p["nome"] for p in ver.get("reprovados") or []],
            "pendentes": [p["nome"] for p in ver.get("pendentes") or []],
            "ressalvas_nomes": [p["nome"] for p in ver.get("ressalvas") or []],
            "portoes": portoes}


def gravar_plano(ver: dict, risco, margem, uso_margem,
                 wfa_aberto=None) -> str:
    """Grava o plano do walk-forward do veredito e devolve o aviso da tela.

    Confere as travas de novo aqui, no servidor: o botão desligado no
    navegador não é garantia de nada. Fora do callback para poder ser
    testada com banco temporário.
    """
    wid = int(ver["wfa_id"])
    if wfa_aberto is not None and int(wfa_aberto) != wid:
        # o veredito é recalculado pelo bloco lento dos portões: trocando de
        # walk-forward, o clique podia gravar o plano do ANTERIOR com os
        # diais da tela nova
        return ("não gravado: o veredito ainda é do walk-forward anterior — "
                "espere o selo terminar")
    d = wfa_store.detalhes(wid) or {}
    guardado = leitura_do_wfa(wid, d)
    if guardado["leitura"].get("erro"):
        return f"não gravado: {guardado['leitura']['erro']}"
    ref, dim, disj = _dimensionar(guardado["trades"], d, guardado["leitura"],
                                  guardado["de"], guardado["ate"],
                                  risco, margem, uso_margem)
    params = (d.get("deploy") or {}).get("params")
    motivo = plano.pode_gravar(ver, dim, params=params)
    if motivo:
        return f"não gravado: {motivo}"
    # a faixa esperada sai do MESMO sorteio que o disjuntor usou (mesmo
    # recorte, mesmos caminhos): dois sorteios davam dois números para a
    # mesma pergunta dentro do mesmo plano
    recorte = disj.get("recorte")
    boot = ((guardado["leitura"].get("boot_12m")
             if recorte == "últimos 12 meses" else None)
            or guardado["leitura"].get("boot"))
    pnl = _pnl_do_wfa(guardado["trades"], guardado["de"], guardado["ate"])
    fator = dim["n"] / max(int((d.get("profile") or {}).get("contratos") or 1), 1)
    expect = plano.expectativa(pnl, d.get("capital"), fator, boot=boot)
    campos = plano.montar(wid, d, ref, dim, disj, ver, expect)
    pid = plano.salvar(**campos)
    quando = campos.get("reotimizar_em")
    aviso = plano.aviso_ao_gravar(ver)
    vale = plano.detalhes(pid)["vale_a_partir"]
    trocados = [e["plano_id"] for e in diario.eventos(
        tipo="plano_aposentado", motivo=f"substituído pelo plano #{pid}")]
    atual = codigo.hash_estrategia(campos.get("strategy") or "")
    mudou = bool(campos.get("codigo_hash")) and atual != campos["codigo_hash"]
    return (f"plano #{pid} gravado · vale a partir de {vale:%d/%m/%Y} · "
            f"{dim['n']} contrato(s) · reotimizar até "
            f"{quando.strftime('%d/%m/%Y') if quando else '—'}"
            + (" · aposentou " + ", ".join(f"#{p}" for p in trocados)
               if trocados else "")
            + (" · ⚠ o código da estratégia mudou desde o walk-forward"
               if mudou else "")
            + (f" · {aviso}" if aviso else ""))


def _pnl_do_wfa(trades: list[dict], de, ate):
    saida = np.array([t["exit_ts"] for t in trades], dtype="datetime64[s]")
    liq = np.array([t["liquido"] for t in trades], dtype=float)
    return candidata.por_pregao(saida, liq, de=de, ate=ate)[1]


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
        # o valor é o módulo (o que o banco guarda); o rótulo é o nome que
        # a estratégia mostra nas outras abas
        return ([{"label": _nome_da_estrategia(n), "value": n} for n in nomes],
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
        Output("cand-veredito", "data"),
        Input("cand-wfa", "value"),
        # o Store que `cand_fim_dos_testes` escreve UMA vez por geração: é
        # ele, e não o relógio, quem faz o selo ser recalculado com o
        # resultado novo dos três testes demorados
        Input("cand-testes", "data"),
    )
    def cand_conteudo(wfa_id, _testes):
        if not wfa_id:
            vazio = CP.vazio("escolha um walk-forward salvo para analisar")
            return vazio, html.Div(), None
        wid = int(wfa_id)
        d = wfa_store.detalhes(wid) or {}
        capital = d.get("capital")
        if capital is None:
            vazio = CP.vazio(
                "este walk-forward foi salvo antes desta tela: não tem "
                "capital nem perfil gravados. Rode e salve o walk-forward "
                "de novo para analisá-lo.")
            return vazio, html.Div(), None

        leitura, gates, de, ate = _gates_e_leitura(wid, d)
        holdout_gate = (next((g for g in gates if g["nome"] == "O holdout confirma?"),
                             None) if gates else None)
        blocos = CP.bloco_robustez(leitura, capital, holdout=bool(d.get("holdout")),
                                   de=de, ate=ate, holdout_gate=holdout_gate)
        if gates is None:
            return blocos, CP.vazio(leitura.get("erro") or
                                    "sem dado suficiente para medir os portões"), None
        ver = candidata.veredito(gates)
        return blocos, WP.selo(ver, titulo=TITULO_SELO), veredito_para_tela(wid, ver)

    # ------------------------------------- bloco 5: tamanho e disjuntor
    @app.callback(
        Output("cand-tamanho", "children"),
        Input("cand-wfa", "value"),
        Input("cand-risco", "value"),
        Input("cand-margem", "value"),
        Input("cand-uso-margem", "value"),
    )
    def cand_tamanho(wfa_id, risco, margem, uso_margem):
        """Quantos contratos e quando parar.

        Separado do bloco dos portões de propósito: mexer no risco por pregão
        não pode recalcular o holdout nem os portões (são 2.000 caminhos
        simulados por clique), e o dimensionamento não muda o veredito —
        aprovar ou reprovar é sobre a estratégia, tamanho é sobre o bolso.
        """
        if not wfa_id:
            return CP.vazio("escolha um walk-forward salvo para dimensionar")
        wid = int(wfa_id)
        d = wfa_store.detalhes(wid) or {}
        capital = d.get("capital")
        if capital is None:
            return CP.vazio("este walk-forward não tem capital gravado")

        guardado = leitura_do_wfa(wid, d)
        leitura = guardado["leitura"]
        if leitura.get("erro"):
            return CP.vazio(leitura["erro"])
        ref, dim, disj = _dimensionar(guardado["trades"], d, leitura,
                                      guardado["de"], guardado["ate"],
                                      risco, margem, uso_margem)
        return CP.bloco_tamanho(dim, ref, disj, capital)

    # ----------------------------------------- gravar o plano de operação
    @app.callback(
        Output("btn-cand-gravar", "disabled"),
        Output("btn-cand-gravar", "children"),
        Output("cand-gravar-motivo", "children"),
        Input("cand-veredito", "data"),
        Input("cand-risco", "value"),
        Input("cand-margem", "value"),
        Input("cand-uso-margem", "value"),
        # depois de gravar, o rótulo vira "gravar outro plano"
        Input("cand-gravar-aviso", "children"),
    )
    def cand_pode_gravar(ver, risco, margem, uso_margem, _aviso):
        """Liga o botão só quando dá para gravar — e diz por que não dá."""
        if not ver:
            return True, "Gravar plano de operação", ""
        wid = int(ver["wfa_id"])
        d = wfa_store.detalhes(wid) or {}
        guardado = leitura_do_wfa(wid, d)
        if guardado["leitura"].get("erro"):
            return True, "Gravar plano de operação", guardado["leitura"]["erro"]
        _, dim, _ = _dimensionar(guardado["trades"], d, guardado["leitura"],
                                 guardado["de"], guardado["ate"],
                                 risco, margem, uso_margem)
        motivo = plano.pode_gravar(
            ver, dim, params=(d.get("deploy") or {}).get("params"))
        rotulo = ("Gravar outro plano" if plano.listar(wfa_id=wid)
                  else "Gravar plano de operação")
        # o aviso da ressalva aparece ANTES do clique, não depois: é com ele
        # que se decide se vale gravar
        return (motivo is not None, rotulo,
                motivo or plano.aviso_ao_gravar(ver) or "")

    @app.callback(
        Output("cand-gravar-aviso", "children"),
        Input("btn-cand-gravar", "n_clicks"),
        State("cand-veredito", "data"),
        State("cand-risco", "value"),
        State("cand-margem", "value"),
        State("cand-uso-margem", "value"),
        State("cand-wfa", "value"),
        prevent_initial_call=True,
    )
    def cand_gravar(n, ver, risco, margem, uso_margem, wfa_aberto):
        """Grava o que a tela mostra. Confere as travas de novo no servidor:
        o botão desligado no navegador não é garantia de nada."""
        if not n or not ver:
            raise PreventUpdate
        return gravar_plano(ver, risco, margem, uso_margem, wfa_aberto)

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
        State("cand-testes", "data"),
    )
    def cand_botao_testes(_n, wfa_id, _t, rotulo, store_testes):
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

        O relógio (`cand-tick.disabled`) nunca é `not e["rodando"]` direto
        — passa por `CP.relogio_ligado`, que só deixa desligar depois que
        `cand-testes` (o Store que `cand_fim_dos_testes` escreve) já tem a
        geração atual. Rodada de correção 1: sem isso, este callback podia
        ler "parado" um instante depois de `cand_fim_dos_testes` ler
        "rodando" na MESMA batida do relógio — o relógio desligava antes do
        anúncio, e o selo ficava preso em "aguardando" para sempre.
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
            # `iniciar` já deixou `rodando=True` (chamada síncrona):
            # `relogio_ligado` já enxerga isso e liga o relógio nesta mesma
            # resposta, sem esperar o próximo tick
            return "Rodando…", True, not CP.relogio_ligado(e, store_testes), ""

        # troca de walk-forward ou batida do relógio: só reflete o estado
        # atual dos testes — nenhum dos dois dispara nada sozinho
        rodando = e["rodando"]
        texto = "Rodando…" if rodando else "Rodar testes completos"
        desabilitado = rodando or not wfa_id
        aviso = "" if gatilho == "cand-wfa" else no_update
        return texto, desabilitado, not CP.relogio_ligado(e, store_testes), aviso

    @app.callback(
        Output("cand-prog", "className"),
        Output("cand-prog-txt", "children"),
        Output("cand-prog-pct", "children"),
        Output("cand-prog-bar", "style"),
        Input("cand-tick", "n_intervals"),
        Input("cand-wfa", "value"),
    )
    def cand_progresso(_t, _wfa):
        est = CP.estado_testes(TESTES.estado, _wfa)
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
