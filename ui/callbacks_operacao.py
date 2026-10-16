"""Callbacks da sub-tela Ao vivo › Operação.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

O caminho é o do Pregão, com uma trava a mais: a tela não abre o banco a
cada 2 s. O pulso (`av-op-intervalo`) lê SÓ o estado.json e escreve três
coisas — a situação, o candle em formação (`tick`) e duas marcas:
`av-op-versao` (o `papel.calculado_em`) e `av-op-ultimo` (o último candle
gravado). Quem lê o banco ouve essas marcas, o seletor e os filtros, e
nunca o pulso: com a captura recalculando o papel uma vez por minuto, a
tela relê uma vez por minuto, não trinta. `test_operacao_tela` confere.

Ações (ligar/pausar variante, ligar/desligar portfólio) são as da seção 1
(`core.ao_vivo`), com o segundo clique confirmando. Ids próprios
(`av-op-acao`): repetir o `av-acao` da Estratégias duplicaria ids na
página.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import duckdb
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import comandos
from core import db_manager as db
from core import papel_leitura as PL

from . import data as D
from .callbacks_ordens import TENTATIVAS_BANCO
from .callbacks_pregao import janela_inicial, juntar, voltar_para_agora
from .components import charts
from .components import operacao_panel as OP
from .components import ordens_panel as OR
from .components import pregao_panel as PP

SIMBOLO = "WIN$N"

# o que o pulso pode escrever — tudo sai do estado.json (a parte 4 junta a
# saúde, os chamados, as posições e os três números da demo, e a marca
# `ordens_em` que manda reler o diário das ordens no banco)
SAIDAS_DO_PULSO = ("av-op-situacao.children", "av-op-versao.data",
                   "av-op-ultimo.data", "av-op-grafico.tick",
                   "av-op-ord-saude.children", "av-op-ord-chamados.children",
                   "av-op-ord-posicoes.children", "av-op-ord-numeros.children",
                   "av-op-ord-versao.data")
# a confirmação do "Encerrar posição" vale até 6 s depois de armar,
# conferida no SERVIDOR (o desarme de 5 s do navegador pode não rodar)
ARMADO_VALE_S = 6.0
# comando "Encerrar posição" enviado há menos disto ainda pode estar
# esperando a captura
COMANDO_RECENTE_S = 300.0

_ACOES = {
    "membro-desligar": (AV.desligar_membro,
                        "variante pausada — as operações dela deixam de "
                        "contar a partir de agora"),
    "membro-ligar": (AV.ligar_membro,
                     "variante ligada — as operações dela voltam a contar"),
    "pf-desligar": (AV.desligar_portfolio,
                    "portfólio desligado — nenhuma operação conta a partir "
                    "de agora"),
    "pf-ligar": (AV.ligar_portfolio,
                 "portfólio ligado — as variantes ligadas voltam a contar"),
    # o Envio espera pouco pelo banco (como o Zerar tudo): desligar já vale
    # pelo comando escrito antes do banco; ligar precisa do banco
    "envio-desligar": (lambda cid: AV.ligar_envio(cid, False,
                                                  tentativas=TENTATIVAS_BANCO),
                       "Envio de ordens desligado — a captura encerra as "
                       "posições da automação na próxima volta; o papel segue"),
    "envio-ligar": (lambda cid: AV.ligar_envio(cid, True,
                                               tentativas=TENTATIVAS_BANCO),
                    "Envio de ordens ligado — as variantes na fase demo "
                    "passam a operar na conta demo"),
}
_CONFIRME = {
    "envio-desligar": "confirme: clique de novo para DESLIGAR o envio de ordens "
                      "— isso encerra as posições abertas da automação",
    "envio-ligar": "confirme: clique de novo para LIGAR o envio de ordens na "
                   "conta demo",
    "membro-desligar": "confirme: clique de novo em Confirmar? para PAUSAR a variante",
    "membro-ligar": "confirme: clique de novo em Confirmar? para LIGAR a variante",
    "pf-desligar": "confirme: clique de novo em Confirmar? para DESLIGAR o portfólio",
    "pf-ligar": "confirme: clique de novo em Confirmar? para LIGAR o portfólio",
}


def _visivel(qual, modo) -> bool:
    return qual == OP.SUBTELA and modo == "aovivo"


def pulso(estado: dict | None, visto_versao, visto_ultimo, tf: str,
          base: dict | None, agora: datetime) -> tuple:
    """(situação, versão, último candle, tick) — só a partir do estado.json.

    A versão e o último candle só mudam quando mudam de verdade: escrever o
    mesmo valor dispararia a releitura do banco à toa."""
    papel = (estado or {}).get("papel") or {}
    versao = papel.get("calculado_em")
    ultimo = (estado or {}).get("ultimo_salvo")
    t = OP.tick_operacao(estado, tf or "M1", base, agora)
    return (OP.faixa_situacao(estado, agora),
            no_update if versao is None or versao == visto_versao else versao,
            no_update if ultimo is None or ultimo == visto_ultimo else ultimo,
            t if t is not None else no_update)


def _armado_valido(armado, agora_s) -> str | None:
    """A chave armada do "Encerrar posição", se ainda vale."""
    if not isinstance(armado, dict) or not armado.get("chave"):
        return None
    em = armado.get("em")
    if em is None or not 0 <= agora_s - float(em) <= ARMADO_VALE_S:
        return None
    return armado["chave"]


def pulso_ordens(estado: dict | None, visto_ordens_em, vars_, pid, dados,
                 escondidos, enviados, armado, agora: datetime,
                 agora_s: float) -> tuple:
    """(saúde, chamados, posições, três números, ordens_em) — só a partir
    do estado.json e dos Stores: nada de banco a cada 2 s.

    As idades (sinal de vida, saída pendente) usam a hora do SERVIDOR, a dos
    carimbos do estado: o relógio do PC pode andar ~1 min atrás."""
    o = (estado or {}).get("ordens")
    o = o if isinstance(o, dict) else {}
    ativa = PP.captura_ativa(estado, agora)
    desvio = (estado or {}).get("relogio_desvio_s") or 0
    try:
        agora_srv = agora - timedelta(seconds=float(desvio))
    except (TypeError, ValueError):
        agora_srv = agora
    nomes = {int(v["ligacao_id"]): v["nome"] for v in vars_ or []}
    inst = D.instrument(SIMBOLO)
    tick = int(inst.get("tick_size", 5))
    ponto = float(inst.get("point_value", 0.2))
    # números do banco de outro portfólio (troca no meio do caminho) não valem
    dados = dados if isinstance(dados, dict) and dados.get("pid") == pid else {}

    saude = OR.faixa_saude(o, ultimo_candle=(estado or {}).get("ultimo_salvo"),
                           atraso_ms=dados.get("atraso_ms"), agora=agora_srv)
    recentes = [t for t in enviados or []
                if 0 <= agora_s - float(t) <= COMANDO_RECENTE_S]
    idade = OR._idade_s(o.get("vivo_em"), agora_srv)
    esperando = bool(recentes) and (not ativa or idade is None
                                    or idade > OR.SEM_VIDA_S)
    # com a captura parada os chamados gravados são de quando ela parou e
    # podem já ter fechado: só o aviso de comando esperando aparece
    chamados = OR.faixa_chamados(o if ativa else {}, nomes,
                                 escondidos=escondidos or [],
                                 armado=_armado_valido(armado, agora_s),
                                 esperando=esperando)
    posicoes = OR.posicoes_abertas(o, nomes, tick, ponto=ponto, agora=agora_srv)
    aberto = sum(float(p.get("resultado") or 0)
                 for _lig, _l, p in OR._posicoes(o, list(nomes)))
    numeros = OR.numeros(o, float(dados.get("realizado") or 0) + aberto,
                         float(dados.get("papel") or 0), portfolio_id=pid,
                         ligacoes=list(nomes))
    versao = o.get("ordens_em")
    return (saude, chamados if chamados is not None else [], posicoes, numeros,
            no_update if versao is None or versao == visto_ordens_em else versao)


def dados_demo(ops: list[dict], evs: list[dict], pid) -> dict:
    """O que o pulso precisa do banco para os três números: o realizado da
    demo (bruto), o papel das MESMAS operações executadas no tamanho da demo
    (bruto também — a mesma base) e o atraso médio da ordem."""
    demo = [o for o in ops if o["situacao"] != "seria_enviada"]
    atrasos = [e["atraso_ms"] for e in evs
               if e["tipo"] in ("executada", "parcial") and e.get("atraso_ms") is not None]
    return {"pid": pid,
            "realizado": sum(o["resultado"] or 0 for o in demo
                             if o["situacao"] == "fechada"),
            "papel": sum(o["papel_mesmo_tamanho"] or 0 for o in demo
                         if o.get("papel_mesmo_tamanho") is not None),
            "atraso_ms": sum(atrasos) / len(atrasos) if atrasos else None}


def ler_ordens(pid) -> tuple:
    """(operações da demo, selo papel = backtest, papel × demo, dados para
    o pulso) do pregão que a tela mostra. O diário é outro callback: trocar
    o filtro dele não refaz o selo nem o comparativo."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)

    def ler(con):
        return (PL.operacoes_demo(con, pid, dia), PL.eventos_ordens(con, pid, dia),
                PL.situacao_backtest(con, pid, dia),
                PL.comparativo_demo(con, pid, dia=dia))
    ops, evs, sit, cmp = _ler(ler)
    return (OR.operacoes_demo(ops), OR.selo_backtest(sit),
            OR.tabela_papel_demo(cmp), dados_demo(ops, evs, pid))


def ler_diario(pid, so_problemas: bool):
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)
    evs, nomes = _ler(lambda con: (PL.eventos_ordens(con, pid, dia),
                                   PL.nomes(con, pid)))
    return OR.diario_do_dia(evs, nomes, so_problemas=so_problemas)


def acao_chamado(nome, alvo, armado, escondidos, enviados,
                 agora_s: float) -> tuple:
    """Um clique na faixa de chamados. Devolve (armado, escondidos,
    enviados, aviso).

    "Manter e acompanhar" só esconde o chamado nesta tela — nenhum comando
    (o chamado volta se fechar e abrir de novo). "Encerrar posição" arma no
    primeiro clique e, no segundo (até 6 s), escreve o comando
    `encerrar_posicao` para a captura: ela sai daquele ticket a cada volta
    até ele sumir."""
    escondidos = list(escondidos or [])
    enviados = list(enviados or [])
    if nome == "manter":
        if alvo not in escondidos:
            escondidos.append(alvo)
        return (None, escondidos, enviados,
                "aviso escondido nesta tela — a automação segue como está")
    chave = f"encerrar:{alvo}"
    if _armado_valido(armado, agora_s) != chave:
        return ({"chave": chave, "em": agora_s}, escondidos, enviados,
                "clique de novo em 5 s para encerrar a posição a mercado")
    comandos.escrever(comandos.PASTA, "encerrar_posicao", ticket=int(alvo))
    enviados.append(agora_s)
    return (None, escondidos, enviados,
            "Encerrar posição enviado: a captura encerra na próxima volta — o "
            "stop e o alvo seguem na corretora até lá")


def abrir_editor(lig, vars_) -> tuple:
    """(estilo, alvo, valor, título, antes) do editor de contratos."""
    v = next((x for x in vars_ or [] if x.get("ligacao_id") == lig), None)
    if v is None:
        raise PreventUpdate
    proprio = v.get("contratos_demo")
    plano = v.get("contratos")
    return ({"display": "flex"}, lig, "" if proprio is None else str(proprio),
            f"Contratos na demo · {v.get('nome')}",
            OR.contratos_antes(proprio, plano))


def custo_editor(lig, valor):
    """O custo de um stop com os contratos digitados, contra o limite."""
    if lig is None:
        return []           # editor fechado
    try:
        n = OR.ler_contratos(valor)
    except ValueError as e:
        return html.Span(str(e), className="aviso")
    if n is None:
        return html.Span("Vazio: a demo usa os contratos do plano.",
                         className="mut")
    try:
        custo = AV.custo_de_um_stop(int(lig), n, tentativas=TENTATIVAS_BANCO)
    except ValueError as e:
        return html.Span(str(e), className="aviso")
    except (duckdb.Error, RuntimeError):
        return html.Span("banco ocupado — o custo aparece em seguida",
                         className="mut")
    return OR.custo_stop_texto(n, custo)


def salvar_editor(lig, valor) -> tuple[bool, str]:
    """(gravou, mensagem)."""
    if lig is None:
        return False, "nenhuma variante escolhida"
    try:
        n = OR.ler_contratos(valor)
        AV.definir_contratos(int(lig), n, tentativas=TENTATIVAS_BANCO)
    except ValueError as e:
        return False, str(e)
    except (duckdb.Error, RuntimeError):
        return False, "banco ocupado, tente de novo"
    return True, ("contratos da demo gravados — valem a partir da próxima "
                  "operação" if n is not None else
                  "a demo volta a usar os contratos do plano na próxima operação")


def acao(nome, alvo, armado, posicoes: int | None = None
         ) -> tuple[str | None, str, bool]:
    """Um clique. Devolve (armado, aviso, executou). `posicoes`: quantas a
    automação tem abertas (do estado.json), para o aviso do desligar."""
    chave = f"{nome}:{alvo}"
    if armado != chave:
        aviso = _CONFIRME[nome]
        if nome == "envio-desligar" and posicoes is not None:
            aviso = ("confirme: clique de novo para DESLIGAR o envio de ordens "
                     + ("(nenhuma posição aberta)" if posicoes == 0 else
                        f"— isso encerra {posicoes} "
                        f"{'posição' if posicoes == 1 else 'posições'}"))
        return chave, aviso, False
    funcao, texto = _ACOES[nome]
    try:
        funcao(alvo)
    except ValueError as e:
        return None, str(e), False
    except RuntimeError:
        if nome == "envio-desligar":
            # o comando foi escrito ANTES do banco: a captura já desliga
            return (None, "comando enviado — a captura desliga o envio na "
                    "próxima volta; o banco será atualizado depois", False)
        return None, "banco ocupado, tente de novo", False
    return None, texto, True


def _ler(fn):
    with db.connect(read_only=True, tentativas=4) as con:
        return fn(con)


def montar(pid, armado, filtro_atual, curva_atual) -> tuple:
    """As partes da tela que leem o banco por portfólio. Treze saídas, na
    ordem do callback `desenhar_op`."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)

    def ler(con):
        pfs = PL.portfolios_com_papel(con)
        pf = next((p for p in pfs if p["portfolio_id"] == pid), None)
        if pf is None:
            return pfs, None, None, None, None, None, None, None, None, None
        res = PL.resumo(con, pid, dia)
        vs = PL.variantes(con, pid, dia)
        ops = PL.operacoes_do_dia(con, pid, dia)
        alertas = PL.alertas(con, pid, dia)
        # o mesmo `dia` dos indicadores: antes da abertura a tela mostra o
        # pregão de ontem, e a curva/comparativo de "hoje" (sem pregão,
        # talvez com outro plano) desmentiriam o topo
        comp = PL.comparativo(con, pid, dia=dia)
        c_pf = PL.curva_vs_esperado(con, pid, dia=dia)
        faixas = [PL.curva_vs_esperado(con, pid, v["ligacao_id"],
                                       dia=dia)["faixa_atual"]
                  for v in vs]
        demo = (res.get("contas") or {}).get("demo")
        envio = PL.envio_da_conta(con, demo["conta_id"]) if demo else None
        return pfs, pf, res, vs, ops, alertas, comp, c_pf, faixas, envio

    pfs, pf, res, vs, ops, alertas, comp, c_pf, faixas, envio = _ler(ler)
    if pf is None:
        msg = ("nenhum portfólio ainda — crie um na tela Portfólio e ligue em "
               "Ao vivo › Estratégias" if not pfs else "escolha um portfólio")
        vazio = [html.P(msg, className="av-vazio op-vazio")]
        return ([], [], vazio, [], [], [], [], [], [], _opcoes_filtro([]),
                "todas", [], None)

    ordens = (estado or {}).get("ordens") or {}
    cab = OP.cabecalho(pf, res, contrato=ordens.get("contrato_dia")
                       or ordens.get("contrato"), dia=dia)
    demo = (res.get("contas") or {}).get("demo")
    botoes = OP.botoes_portfolio(pf, armado, conta_id=demo and demo["conta_id"],
                                 envio=envio)
    nomes = {v["ligacao_id"]: v["nome"] for v in vs}
    # contratos e fase vão junto: o editor do ✎ abre sem reler o banco
    vars_ = [{"ligacao_id": v["ligacao_id"], "nome": v["nome"], "cor": v["cor"],
              "contratos": v.get("contratos"),
              "contratos_demo": v.get("contratos_demo"), "fase": v.get("fase")}
             for v in vs]
    filtro = filtro_atual if filtro_atual in [str(l) for l in nomes] else "todas"
    curva = curva_atual if curva_atual in nomes else (vs[0]["ligacao_id"]
                                                      if vs else None)
    if not vs:
        kpis = [OP._SEM_VARIANTES]
    else:
        esperado = {"diferenca": c_pf.get("diferenca_mediana"),
                    "faixas": faixas, "aviso": c_pf.get("aviso")}
        kpis = OP.kpis(res, ops, esperado, nomes)
    return (cab, botoes, kpis,
            OP.cabecalho_colunas() if vs else [], OP.cartoes(vs, armado),
            OP.risco_dia(res) if vs else [],
            OP.lista_alertas(alertas), OP.tabela_comparativo(comp), vars_,
            _opcoes_filtro(vars_), filtro,
            [{"label": v["nome"], "value": v["ligacao_id"]} for v in vars_],
            curva)


def juntar_demo(ops: list[dict], demo: list[dict]) -> list[dict]:
    """Põe em cada operação do papel o que a demo fez nela (mesma chave
    `(ligacao_id, entry_ts)`): contratos executados e a derrapagem além do
    plano por ponta — a coluna "Papel × demo" da tabela do papel."""
    por = {(o["ligacao_id"], o["entry_ts"]): o for o in demo
           if o["situacao"] != "seria_enviada"}
    out = []
    for o in ops:
        d = por.get((o["ligacao_id"], o["entry_ts"]))
        out.append({**o, "demo": d} if d else o)
    return out


def ler_curva(pid, lig) -> dict:
    """A curva papel × esperado do pregão que a tela mostra (o mesmo `dia`
    de `montar`); `lig` None é o portfólio inteiro."""
    dia = D.dia_do_pregao(D.estado_captura())
    return _ler(lambda con: PL.curva_vs_esperado(con, pid, lig, dia=dia))


def _opcoes_filtro(vars_):
    # o valor é texto: "todas" e o id da ligação convivem no mesmo campo
    return ([{"label": "Todas as variantes", "value": "todas"}]
            + [{"label": v["nome"], "value": str(v["ligacao_id"])}
               for v in vars_])


def serie_do_dia(pid, tf, ocultas, agora) -> tuple[list, dict | None]:
    """(series, último candle do banco) do gráfico do dia, com os
    marcadores do papel."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)
    inicio = datetime.combine(dia, datetime.min.time())
    dados = D.candles(SIMBOLO, inicio, inicio + timedelta(hours=23, minutes=59),
                      tf)
    base = dados["candles"][-1] if dados["candles"] else None
    t = OP.tick_operacao(estado, tf, base, agora)
    dados["candles"] = juntar(dados["candles"], t["bar"] if t else None)
    mk, linhas = [], []
    if pid is not None:
        m = _ler(lambda con: PL.marcadores(con, pid, dia))
        mk, linhas = OP.marcadores_tela(m, ocultas, tf)
    return charts.price_series(dados, mk, linhas), base


def register(app):
    @app.callback(
        Output("av-op-situacao", "children"),
        Output("av-op-versao", "data"),
        Output("av-op-ultimo", "data"),
        Output("av-op-grafico", "tick"),
        Output("av-op-ord-saude", "children"),
        Output("av-op-ord-chamados", "children"),
        Output("av-op-ord-posicoes", "children"),
        Output("av-op-ord-numeros", "children"),
        Output("av-op-ord-versao", "data"),
        Input("av-op-intervalo", "n_intervals"),
        State("av-op-versao", "data"),
        State("av-op-ultimo", "data"),
        State("av-op-tf", "value"),
        State("av-op-base", "data"),
        State("av-op-ord-versao", "data"),
        State("av-op-vars", "data"),
        State("av-op-portfolio", "value"),
        State("av-op-ord-dados", "data"),
        State("av-op-ord-escondidos", "data"),
        State("av-op-ord-enviados", "data"),
        State("av-op-ord-armado", "data"),
    )
    def pulso_op(_n, versao, ultimo, tf, base, ordens_em, vars_, pid, dados,
                 escondidos, enviados, armado):
        # um pulso só (o teste exige um único ouvinte do intervalo): o
        # papel e as ordens saem da MESMA leitura do estado.json
        estado = D.estado_captura()
        agora = datetime.now()
        return (*pulso(estado, versao, ultimo, tf, base, agora),
                *pulso_ordens(estado, ordens_em, vars_, pid, dados, escondidos,
                              enviados, armado, agora, time.time()))

    @app.callback(
        Output("av-op-portfolio", "options"),
        Output("av-op-portfolio", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
        Input("av-op-acao-versao", "data"),
        State("av-op-portfolio", "value"),
    )
    def portfolios_op(qual, modo, _v, atual):
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            pfs = _ler(PL.portfolios_com_papel)
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        ops = [{"label": p["nome"] + ("" if p["ligado"] else " (desligado)"),
                "value": p["portfolio_id"]} for p in pfs]
        ids = [p["portfolio_id"] for p in pfs]
        if atual in ids:
            return ops, no_update
        ligados = [p["portfolio_id"] for p in pfs if p["ligado"]]
        return ops, (ligados or ids or [None])[0]

    @app.callback(
        Output("av-op-cabecalho", "children"),
        Output("av-op-botoes", "children"),
        Output("av-op-kpis", "children"),
        Output("av-op-var-cab", "children"),
        Output("av-op-var-lista", "children"),
        Output("av-op-risco", "children"),
        Output("av-op-alertas", "children"),
        Output("av-op-comparativo", "children"),
        Output("av-op-vars", "data"),
        Output("av-op-filtro", "options"),
        Output("av-op-filtro", "value"),
        Output("av-op-curva-variante", "options"),
        Output("av-op-curva-variante", "value"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-acao-versao", "data"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
        # State, não Input: armar um botão só troca o rótulo (`rotulos_op`);
        # o armado entra aqui para um redesenho no meio do caminho não
        # mostrar "Pausar" num botão que já está pedindo confirmação
        State("av-op-armado", "data"),
        State("av-op-filtro", "value"),
        State("av-op-curva-variante", "value"),
    )
    def desenhar_op(_versao, pid, _acoes, qual, modo, armado, filtro, curva):
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            return montar(pid, armado, filtro, curva)
        except (duckdb.Error, RuntimeError) as e:
            motivo = ("banco ocupado" if isinstance(e, RuntimeError)
                      else "erro ao ler o banco")
            sem = (no_update,) * 13
            return (*sem[:6], [html.P(
                f"não foi possível ler agora: {motivo} — a tela tenta de novo "
                "no próximo cálculo do papel", className="av-alerta")],
                *sem[7:])

    @app.callback(
        Output("av-op-operacoes", "children"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-filtro", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def operacoes_op(_versao, pid, filtro, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        lig = None if filtro in (None, "todas") else int(filtro)
        dia = D.dia_do_pregao(D.estado_captura())
        try:
            ops, demo = _ler(lambda con: (PL.operacoes_do_dia(con, pid, dia, lig),
                                          PL.operacoes_demo(con, pid, dia)))
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        return OP.tabela_operacoes(juntar_demo(ops, demo))

    @app.callback(
        Output("av-op-curva", "series"),
        Output("av-op-curva-nota", "children"),
        Output("av-op-curva-variante", "disabled"),
        Output("av-op-curva-enquadrar", "data"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-curva-modo", "value"),
        Input("av-op-curva-variante", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def curva_op(_versao, pid, modo_curva, lig, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        por_variante = modo_curva == "variante"
        if por_variante and lig is None:
            return [], "escolha a variante ao lado", False, no_update
        try:
            c = ler_curva(pid, lig if por_variante else None)
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        # poucos pregões ficavam espremidos num canto: enquadra a curva
        # inteira, depois de desenhada (ver o callback do navegador abaixo)
        return (OP.curva_series(c), OP.curva_nota(c), not por_variante,
                time.time())

    @app.callback(
        Output("av-op-grafico", "series"),
        Output("av-op-grafico", "timeScaleAction"),
        Output("av-op-grafico", "visibleLogicalRange"),
        Output("av-op-base", "data"),
        Output("av-op-enquadrar", "data"),
        Input("av-op-ultimo", "data"),
        Input("av-op-versao", "data"),
        Input("av-op-tf", "value"),
        Input("av-subtela", "value"),
        Input("av-op-agora", "n_clicks"),
        Input("av-op-portfolio", "value"),
        Input("av-op-ocultas", "data"),
        Input("modo", "value"),
    )
    def serie_op(_ultimo, _versao, tf, qual, _cliques, pid, ocultas, modo):
        # dados e posição no mesmo callback, como no Pregão: separados, a
        # posição podia chegar antes dos dados e ser desfeita por eles
        quem = ctx.triggered_id
        if quem == "av-op-agora":
            return no_update, voltar_para_agora(), no_update, no_update, no_update
        if not _visivel(qual, modo):
            raise PreventUpdate
        try:
            series, base = serie_do_dia(pid, tf or "M1", ocultas,
                                        datetime.now())
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate
        if quem in ("av-op-ultimo", "av-op-versao", "av-op-ocultas"):
            # candle novo, papel novo ou legenda: o usuário pode estar
            # olhando a manhã — a posição fica. Trocar de portfólio (e a
            # escolha automática dele ao abrir a tela) reenquadra.
            return series, no_update, no_update, base, no_update
        janela = janela_inicial(len(series[0]["data"]))
        return series, no_update, janela, base, janela

    @app.callback(
        Output("av-op-armado", "data"),
        Output("av-op-acao-versao", "data"),
        Output("av-op-aviso", "children"),
        Output("av-versao", "data", allow_duplicate=True),
        Input({"type": "av-op-acao", "acao": ALL, "id": ALL}, "n_clicks"),
        State("av-op-armado", "data"),
        State("av-op-acao-versao", "data"),
        State("av-versao", "data"),
        prevent_initial_call=True,
    )
    def acao_op(_cliques, armado, versao, versao_av):
        # botão recém-desenhado chega com n_clicks=0: só clique de verdade
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        posicoes = None
        if gat["acao"] == "envio-desligar":
            posicoes = D.ordens_do_estado(D.estado_captura())["posicoes"]
        armado, aviso, feito = acao(gat["acao"], gat["id"], armado, posicoes)
        if not feito:
            return armado, no_update, aviso, no_update
        # a sub-tela Estratégias também mostra ligado/pausado: redesenha
        return armado, (versao or 0) + 1, aviso, (versao_av or 0) + 1

    @app.callback(
        Output({"type": "av-op-acao", "acao": ALL, "id": ALL}, "children"),
        Output({"type": "av-op-acao", "acao": ALL, "id": ALL}, "className"),
        Input("av-op-armado", "data"),
        prevent_initial_call=True,
    )
    def rotulos_op(armado):
        # sem banco: só "Confirmar?" no botão armado e o rótulo normal nos
        # outros (inclusive o que deixou de estar armado)
        estados = [OP.estado_botao(o["id"]["acao"], o["id"]["id"], armado)
                   for o in ctx.outputs_list[0]]
        return [e[0] for e in estados], [e[1] for e in estados]

    # O botão armado desarma sozinho depois de 5 s: um "Confirmar?"
    # esquecido viraria uma ação por engano no próximo clique, minutos depois.
    app.clientside_callback(
        """function (armado) {
            window._avOpArmado = armado || null;
            if (armado) {
                setTimeout(function () {
                    if (window._avOpArmado === armado) {
                        window._avOpArmado = null;
                        window.dash_clientside.set_props('av-op-armado', {data: null});
                        window.dash_clientside.set_props('av-op-aviso', {children: ''});
                    }
                }, 5000);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-aviso", "role"),
        Input("av-op-armado", "data"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("av-subtela", "value"),
        Input("av-op-ficha", "n_clicks"),
        prevent_initial_call=True,
    )
    def ver_ficha_op(n):
        if not n:
            raise PreventUpdate
        return "estrategias"

    @app.callback(
        Output("av-op-ocultas", "data"),
        Input({"type": "av-op-chip", "id": ALL}, "n_clicks"),
        State("av-op-ocultas", "data"),
        prevent_initial_call=True,
    )
    def chip_op(_cliques, ocultas):
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        ocultas = list(ocultas or [])
        lig = gat["id"]
        if lig in ocultas:
            ocultas.remove(lig)
        else:
            ocultas.append(lig)
        return ocultas

    @app.callback(
        Output("av-op-chips", "children"),
        Input("av-op-vars", "data"),
        Input("av-op-ocultas", "data"),
    )
    def legenda_op(vars_, ocultas):
        return OP.chips(vars_ or [], ocultas)

    # Enquadrar de novo um instante depois. A sub-tela nasce escondida: o
    # gráfico ainda tem largura zero quando a primeira posição chega, e ao
    # crescer mantém o espaçamento das barras daquela largura — os candles
    # ficavam espremidos à direita com a metade esquerda vazia.
    app.clientside_callback(
        """function (janela) {
            if (janela) {
                // + 0,001: o Dash ignora um valor igual ao que o servidor
                // acabou de mandar, e o gráfico não reaplicaria
                setTimeout(function () {
                    window.dash_clientside.set_props('av-op-grafico',
                        {visibleLogicalRange: {from: janela.from,
                                               to: janela.to + 0.001}});
                }, 350);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-grafico-caixa", "role"),
        Input("av-op-enquadrar", "data"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        """function (nonce) {
            if (nonce) {
                setTimeout(function () {
                    window.dash_clientside.set_props('av-op-curva',
                        {timeScaleAction: {action: 'fitContent', nonce: nonce}});
                }, 350);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-curva-caixa", "role"),
        Input("av-op-curva-enquadrar", "data"),
        prevent_initial_call=True,
    )

    # As abas Operações | Diário | Avaliação: as três ficam montadas e só a
    # classe do contêiner diz qual aparece (dcc.Tabs desmontaria a fechada,
    # recriaria a curva e perderia a rolagem). Ao abrir a Avaliação a curva
    # é enquadrada de novo: desenhada com a aba fechada, as barras ficavam
    # espremidas. Só navegador: não lê o banco nem ouve o pulso.
    app.clientside_callback(
        """function (aba) {
            var qual = aba || 'operacoes';
            if (qual === 'avaliacao') {
                setTimeout(function () {
                    window.dash_clientside.set_props('av-op-curva',
                        {timeScaleAction: {action: 'fitContent',
                                           nonce: Date.now()}});
                }, 50);
            }
            return 'op-abas-corpo op-aba-' + qual;
        }""",
        Output("av-op-abas", "className"),
        Input("av-op-aba", "value"),
    )

    app.clientside_callback(
        """function (n) {
            if (n) {
                var caixa = document.getElementById('av-op-grafico-caixa');
                if (caixa && caixa.requestFullscreen) { caixa.requestFullscreen(); }
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-grafico-caixa", "title"),
        Input("av-op-cheia", "n_clicks"),
        prevent_initial_call=True,
    )

    # ------------------------------------------------- parte 4: a demo
    @app.callback(
        Output("av-op-ord-operacoes", "children"),
        Output("av-op-ord-selo", "children"),
        Output("av-op-ord-cmp", "children"),
        Output("av-op-ord-dados", "data"),
        # o diário das ordens só muda quando `ordens_em` muda; o papel (o
        # par de cada operação) quando `av-op-versao` muda — nunca o pulso
        Input("av-op-ord-versao", "data"),
        Input("av-op-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-acao-versao", "data"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def ordens_op(_ordens_em, _versao, pid, _acoes, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        try:
            return ler_ordens(pid)
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate

    @app.callback(
        Output("av-op-ord-diario", "children"),
        Input("av-op-ord-versao", "data"),
        Input("av-op-portfolio", "value"),
        Input("av-op-ord-diario-filtro", "value"),
        Input("av-subtela", "value"),
        Input("modo", "value"),
    )
    def diario_op(_ordens_em, pid, filtro, qual, modo):
        if not _visivel(qual, modo) or pid is None:
            raise PreventUpdate
        try:
            return ler_diario(pid, filtro == "problemas")
        except (duckdb.Error, RuntimeError):
            raise PreventUpdate

    @app.callback(
        Output("av-op-ord-armado", "data"),
        Output("av-op-ord-escondidos", "data"),
        Output("av-op-ord-enviados", "data"),
        Output("av-op-aviso", "children", allow_duplicate=True),
        Input({"type": "av-op-ord-acao", "acao": ALL, "id": ALL}, "n_clicks"),
        State("av-op-ord-armado", "data"),
        State("av-op-ord-escondidos", "data"),
        State("av-op-ord-enviados", "data"),
        prevent_initial_call=True,
    )
    def chamado_op(_cliques, armado, escondidos, enviados):
        # o pulso redesenha os botões a cada 2 s com n_clicks=0: só clique
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        return acao_chamado(gat["acao"], gat["id"], armado, escondidos,
                            enviados, time.time())

    @app.callback(
        Output({"type": "av-op-ord-acao", "acao": ALL, "id": ALL}, "children"),
        Output({"type": "av-op-ord-acao", "acao": ALL, "id": ALL}, "className"),
        Input("av-op-ord-armado", "data"),
        prevent_initial_call=True,
    )
    def rotulos_ord(armado):
        chave = _armado_valido(armado, time.time())
        estados = [OR.rotulo_botao(o["id"]["acao"], o["id"]["id"], chave)
                   for o in ctx.outputs_list[0]]
        return [e[0] for e in estados], [e[1] for e in estados]

    # desarma sozinho depois de 5 s, como os outros botões de dois cliques
    app.clientside_callback(
        """function (armado) {
            window._avOpOrdArmado = armado || null;
            var marca = window._avOpOrdArmado;
            if (armado) {
                setTimeout(function () {
                    if (window._avOpOrdArmado === marca) {
                        window._avOpOrdArmado = null;
                        window.dash_clientside.set_props('av-op-ord-armado', {data: null});
                    }
                }, 5000);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("av-op-ord-chamados", "role"),
        Input("av-op-ord-armado", "data"),
        prevent_initial_call=True,
    )

    # ------------------------------------- contratos da demo (o ✎)
    @app.callback(
        Output("av-op-ord-ctr-pop", "style"),
        Output("av-op-ord-ctr-alvo", "data"),
        Output("av-op-ord-ctr-valor", "value"),
        Output("av-op-ord-ctr-titulo", "children"),
        Output("av-op-ord-ctr-antes", "children"),
        Output("av-op-ord-ctr-erro", "children"),
        Input({"type": "av-op-ord-ctr", "id": ALL}, "n_clicks"),
        Input("av-op-ord-ctr-cancelar", "n_clicks"),
        State("av-op-vars", "data"),
        prevent_initial_call=True,
    )
    def editor_ctr(_lapis, _cancelar, vars_):
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        if gat == "av-op-ord-ctr-cancelar":
            return ({"display": "none"}, None, no_update, no_update, no_update, "")
        return (*abrir_editor(gat["id"], vars_), "")

    @app.callback(
        Output("av-op-ord-ctr-custo", "children"),
        Input("av-op-ord-ctr-valor", "value"),
        # Input também: abrir outra variante com o mesmo valor no campo
        # não muda o `value`, e o custo ficaria o da anterior
        Input("av-op-ord-ctr-alvo", "data"),
        prevent_initial_call=True,
    )
    def custo_ctr(valor, lig):
        return custo_editor(lig, valor)

    @app.callback(
        Output("av-op-ord-ctr-pop", "style", allow_duplicate=True),
        Output("av-op-ord-ctr-erro", "children", allow_duplicate=True),
        Output("av-op-acao-versao", "data", allow_duplicate=True),
        Output("av-op-aviso", "children", allow_duplicate=True),
        Input("av-op-ord-ctr-salvar", "n_clicks"),
        State("av-op-ord-ctr-alvo", "data"),
        State("av-op-ord-ctr-valor", "value"),
        State("av-op-acao-versao", "data"),
        prevent_initial_call=True,
    )
    def salvar_ctr(n, lig, valor, versao):
        if not n:
            raise PreventUpdate
        ok, msg = salvar_editor(lig, valor)
        if not ok:
            return no_update, msg, no_update, no_update
        # sobe a versão: os cartões redesenham com o número novo
        return {"display": "none"}, "", (versao or 0) + 1, msg
