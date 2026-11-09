"""Operação: o pulso, a leitura das ordens e do diário e as ações dos botões."""
from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
from dash import html, no_update
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import comandos
from core import db_manager as db
from core import papel_leitura as PL

from .. import data as D
from ..callbacks_ordens import TENTATIVAS_BANCO
from ..components import operacao_panel as OP
from ..components import ordens_panel as OR
from ..components import pregao_panel as PP


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
    "envio-desligar": (lambda cid: AV.ligar_envio(cid, False, tipo="demo",
                                                  tentativas=TENTATIVAS_BANCO),
                       "Envio de ordens desligado — a captura encerra as "
                       "posições da automação na próxima volta; o papel segue"),
    "envio-ligar": (lambda cid: AV.ligar_envio(cid, True, tipo="demo",
                                               tentativas=TENTATIVAS_BANCO),
                    "Envio de ordens ligado — as variantes na fase demo "
                    "passam a operar na conta demo"),
    "envio-real-desligar": (lambda cid: AV.ligar_envio(cid, False, tipo="real",
                                                       tentativas=TENTATIVAS_BANCO),
                            "Envio de ordens da conta real desligado — o "
                            "processo da real encerra as posições reais; o "
                            "papel e a demo seguem"),
    "envio-real-ligar": (lambda cid: AV.ligar_envio(cid, True, tipo="real",
                                                    tentativas=TENTATIVAS_BANCO),
                         "Envio de ordens da conta real ligado — as variantes "
                         "na fase real passam a operar na conta real"),
}
# os desligamentos do envio (com posições abertas pedem a contagem)
_DESLIGAR_ENVIO = ("envio-desligar", "envio-real-desligar")
_CONFIRME = {
    "envio-desligar": "confirme: clique de novo para DESLIGAR o envio de ordens "
                      "— isso encerra as posições abertas da automação",
    "envio-ligar": "confirme: clique de novo para LIGAR o envio de ordens na "
                   "conta demo",
    "envio-real-desligar": "confirme: clique de novo para DESLIGAR o envio de "
                           "ordens da conta real — isso encerra as posições reais",
    "envio-real-ligar": "confirme: clique de novo para LIGAR o envio de ordens na "
                        "conta real",
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


def _chamados_de(bloco: dict | None, origem: str) -> list[dict]:
    """Os chamados de uma conta, com a origem ("demo" ou "real"). Os da real
    ganham prefixo na chave: um chamado da real com a mesma chave de um da
    demo não pode ser escondido junto com ele ("Manter e acompanhar")."""
    out = []
    for c in (bloco or {}).get("chamados") or []:
        if not isinstance(c, dict):
            continue
        chave = c.get("chave") if origem == "demo" else f"real:{c.get('chave')}"
        out.append({**c, "origem": origem, "chave": chave})
    return out


def pulso_ordens(estado: dict | None, visto_ordens_em, vars_, pid, dados,
                 escondidos, enviados, armado, agora: datetime,
                 agora_s: float, real: dict | None = None) -> tuple:
    """(saúde, chamados, posições, três números, ordens_em) — só a partir
    do estado.json, do estado_real.json (`real`, o bloco da conta real) e dos
    Stores: nada de banco a cada 2 s.

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

    # a linha REAL aparece com a conta real cadastrada (o banco diz, no
    # `dados`) ou com o arquivo da real, mesmo que ele esteja parado
    com_real = bool(dados.get("real_cadastrada"))
    saude = OR.faixa_saude(o, ultimo_candle=(estado or {}).get("ultimo_salvo"),
                           atraso_ms=dados.get("atraso_ms"), agora=agora_srv,
                           real=real, com_real=com_real)
    recentes = [t for t in enviados or []
                if 0 <= agora_s - float(t) <= COMANDO_RECENTE_S]
    idade = OR._idade_s(o.get("vivo_em"), agora_srv)
    esperando = bool(recentes) and (not ativa or idade is None
                                    or idade > OR.SEM_VIDA_S)
    # com a captura parada os chamados gravados são de quando ela parou e
    # podem já ter fechado: só o aviso de comando esperando aparece. O mesmo
    # vale para a conta real: sem publicar há mais de 10 s, nada dela aparece
    da_real = [] if OR.real_parada(real, agora_srv) else _chamados_de(real, "real")
    chamados = OR.faixa_chamados({"chamados": (_chamados_de(o, "demo") if ativa else [])
                                  + da_real}, nomes,
                                 escondidos=escondidos or [],
                                 armado=_armado_valido(armado, agora_s),
                                 esperando=esperando)
    # a conta real só entra viva: parada, o que ela mostra não vale mais
    real_viva = real if com_real and not OR.real_parada(real, agora_srv) else None
    posicoes = OR.posicoes_abertas(o, nomes, tick, ponto=ponto, agora=agora_srv,
                                   real=real_viva)
    aberto = sum(float(p.get("resultado") or 0)
                 for _lig, _l, p in OR._posicoes(o, list(nomes)))
    aberto_real = sum(float(p.get("resultado") or 0)
                      for _lig, _l, p in OR._posicoes(real_viva or {}, list(nomes)))
    numeros = OR.numeros(
        o, float(dados.get("realizado") or 0) + aberto,
        float(dados.get("papel") or 0), portfolio_id=pid, ligacoes=list(nomes),
        real=real_viva, com_real=com_real,
        real_parada=com_real and real_viva is None,
        resultado_real=(float(dados.get("realizado_real") or 0) + aberto_real
                        if real_viva is not None else None),
        total_demo=dados.get("total_demo"), total_real=dados.get("total_real"),
        pior=dados.get("pior"))
    versao = o.get("ordens_em")
    return (saude, chamados if chamados is not None else [], posicoes, numeros,
            no_update if versao is None or versao == visto_ordens_em else versao)


def dados_demo(ops: list[dict], evs: list[dict], pid,
               real_cadastrada: bool = False) -> dict:
    """O que o pulso precisa do banco para os três números: o realizado da
    demo (bruto), o papel das MESMAS operações executadas no tamanho da demo
    (bruto também — a mesma base), o atraso médio da ordem e se o portfólio
    tem conta real cadastrada (a linha REAL da saúde)."""
    demo = [o for o in ops if o["situacao"] != "seria_enviada"]
    atrasos = [e["atraso_ms"] for e in evs
               if e["tipo"] in ("executada", "parcial") and e.get("atraso_ms") is not None]
    return {"pid": pid, "real_cadastrada": bool(real_cadastrada),
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
        # a conta real cadastrada no portfólio (a linha REAL da saúde)
        real = con.execute("SELECT conta_real_id FROM portfolios "
                           "WHERE portfolio_id = ?", [pid]).fetchone()
        comp = PL.comparativo(con, pid, dia=dia)
        comp_real = PL.comparativo(con, pid, dia=dia, origem="real")
        return (PL.operacoes_demo(con, pid, dia), PL.eventos_ordens(con, pid, dia),
                PL.situacao_backtest(con, pid, dia),
                PL.comparativo_demo(con, pid, dia=dia),
                bool(real and real[0] is not None),
                PL.operacoes_demo(con, pid, dia, origem="real"),
                comp_real, comp, PL.resumo(con, pid, dia)["pior_momento"])
    ops, evs, sit, cmp, tem_real, ops_real, comp_real, comp, pior = _ler(ler)
    dados = dados_demo(ops, evs, pid, tem_real)
    # o que a tira de números precisa do banco: o realizado da real, os
    # totais desde o plano (demo e real) e o pior momento do dia
    dados.update(realizado_real=sum(o["resultado"] or 0 for o in ops_real
                                    if o["situacao"] == "fechada"),
                 total_demo=(comp.get("demo") or {}).get("total"),
                 total_real=(comp_real.get("demo") or {}).get("total"),
                 pior=pior)
    return (OR.operacoes_demo(ops), OR.selo_backtest(sit),
            OR.tabela_papel_demo(cmp), dados,
            OR.operacoes_demo(ops_real, origem="real") if tem_real
            else OR._vazio("sem conta real neste portfólio",
                           "Sem conta real cadastrada no portfólio, a tabela "
                           "fica vazia. Cadastre-a na tela Estratégias › Contas."),
            OR.tabela_papel_demo(comp_real, "real") if tem_real
            else OR._vazio("sem conta real neste portfólio",
                           "Sem conta real cadastrada no portfólio não há o que "
                           "comparar com o papel."))


def ler_diario(pid, so_problemas: bool):
    """O diário das duas contas, do mais antigo para o mais novo (a tela
    inverte): cada evento leva a origem ("real" ou "demo") para a coluna
    Conta."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)
    demo, real, nomes = _ler(lambda con: (PL.eventos_ordens(con, pid, dia),
                                          PL.eventos_ordens(con, pid, dia, "real"),
                                          PL.nomes(con, pid)))
    evs = ([{**e, "origem": "demo"} for e in demo]
           + [{**e, "origem": "real"} for e in real])
    evs.sort(key=lambda e: str(e.get("quando") or ""))
    return OR.diario_do_dia(evs, nomes, so_problemas=so_problemas)


def acao_chamado(nome, alvo, armado, escondidos, enviados,
                 agora_s: float, tipo: str = "demo") -> tuple:
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
    # a pasta é a da conta de origem da posição (hoje sempre a demo)
    comandos.escrever(comandos.pasta_do_tipo(tipo), "encerrar_posicao",
                      ticket=int(alvo))
    enviados.append(agora_s)
    return (None, escondidos, enviados,
            "Encerrar posição enviado: a captura encerra na próxima volta — o "
            "stop e o alvo seguem na corretora até lá")


def abrir_editor(lig, vars_, conta: str = "demo") -> tuple:
    """(estilo, alvo, valor, título, antes) do editor de contratos."""
    v = next((x for x in vars_ or [] if x.get("ligacao_id") == lig), None)
    if v is None:
        raise PreventUpdate
    proprio = v.get("contratos_real" if conta == "real" else "contratos_demo")
    plano = v.get("contratos")
    return ({"display": "flex"}, lig, "" if proprio is None else str(proprio),
            f"Contratos na {conta} · {v.get('nome')}",
            OR.contratos_antes(proprio, plano))


def custo_editor(lig, valor, conta: str = "demo"):
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
        custo = AV.custo_de_um_stop(int(lig), n, tentativas=TENTATIVAS_BANCO,
                                    **_so_real(conta))
    except ValueError as e:
        return html.Span(str(e), className="aviso")
    except (duckdb.Error, RuntimeError):
        return html.Span("banco ocupado — o custo aparece em seguida",
                         className="mut")
    return OR.custo_stop_texto(n, custo)


def _so_real(conta: str) -> dict:
    """O argumento `conta` só vai às funções quando é a real (a demo usa o padrão
    delas, e assim as chamadas da Estratégias continuam as mesmas)."""
    return {} if conta == "demo" else {"conta": conta}


def salvar_editor(lig, valor, conta: str = "demo") -> tuple[bool, str]:
    """(gravou, mensagem)."""
    if lig is None:
        return False, "nenhuma variante escolhida"
    try:
        n = OR.ler_contratos(valor)
        AV.definir_contratos(int(lig), n, tentativas=TENTATIVAS_BANCO,
                             **_so_real(conta))
    except ValueError as e:
        return False, str(e)
    except (duckdb.Error, RuntimeError):
        return False, "banco ocupado, tente de novo"
    return True, (f"contratos da {conta} gravados — valem a partir da próxima "
                  "operação" if n is not None else
                  "a demo volta a usar os contratos do plano na próxima operação")


def acao(nome, alvo, armado, posicoes: int | None = None
         ) -> tuple[str | None, str, bool]:
    """Um clique. Devolve (armado, aviso, executou). `posicoes`: quantas a
    automação tem abertas (do estado.json), para o aviso do desligar."""
    chave = f"{nome}:{alvo}"
    if armado != chave:
        aviso = _CONFIRME[nome]
        if nome in _DESLIGAR_ENVIO and posicoes is not None:
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
        if nome in _DESLIGAR_ENVIO:
            # o comando foi escrito ANTES do banco: a captura já desliga
            return (None, "comando enviado — a captura desliga o envio na "
                    "próxima volta; o banco será atualizado depois", False)
        return None, "banco ocupado, tente de novo", False
    return None, texto, True


def _ler(fn):
    with db.connect(read_only=True, tentativas=4) as con:
        return fn(con)
