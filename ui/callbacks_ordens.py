"""Topo da parte 4 (todas as abas): selo das ordens, "Zerar tudo e desligar
envio" e o alarme.

Spec: docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md §5.8 e §8.

O pulso (`ord-intervalo`, 2 s) lê só o estado.json e escreve o selo e os
atributos da div `ord-alarme`; quem toca o bipe e pisca o título é o
`assets/alarme.js`, observando esses atributos. O botão é de mão única: o
clique escreve `ord-armado` e o próprio rótulo, e ninguém ouve o que ele
escreve — não há como fechar ciclo com o pulso.
"""
from __future__ import annotations

import time
from datetime import datetime

import duckdb
from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import comandos
from core import db_manager as db

from . import data as D

ROTULO = "⏻ Zerar tudo e desligar envio"
# a confirmação só vale até 6 s depois de armar, conferido no SERVIDOR: o
# desarme de 5 s do navegador pode não rodar (aba em segundo plano, JS
# atrasado) e um "Confirmar" esquecido viraria um zerar por engano
ARMADO_VALE_S = 6.0
# banco ocupado: duas tentativas e desiste — o comando por arquivo já vale,
# e a tela não pode congelar ~10 s por conta esperando a mineração
TENTATIVAS_BANCO = 2
_CLASSE_SELO = "ord-selo"


def _contas_ativas() -> list[int]:
    """Os ids das contas não arquivadas. Espera pouco: o comando por arquivo
    já foi escrito, e segurar a tela 15 s pelo banco não ajuda ninguém."""
    with db.connect(read_only=True, tentativas=TENTATIVAS_BANCO) as con:
        return [int(r[0]) for r in con.execute(
            "SELECT conta_id FROM contas WHERE arquivada_em IS NULL "
            "ORDER BY conta_id").fetchall()]


def _rotulo_armado(n: int | None) -> str:
    if n is None:
        return "Confirmar: encerra as posições da automação e desliga o envio"
    if n == 0:
        return "Confirmar: desliga o envio (nenhuma posição aberta)"
    return f"Confirmar: encerra {n} {'posição' if n == 1 else 'posições'}"


def zerar(armado_em: float | None, estado: dict | None, agora: datetime,
          agora_s: float | None = None) -> tuple:
    """Um clique no botão. Devolve (armado_em, rótulo, aviso): `armado_em` é
    a hora (time.time) em que o primeiro clique armou, ou None.

    Primeiro clique só arma. O segundo escreve o comando "zerar_tudo"
    ANTES de tocar o banco — com uma mineração gravando, o arquivo já vale
    na volta seguinte da captura — e depois desliga o Envio de cada conta no
    banco. Sem esse desligar no banco o zerar duraria o dia inteiro: a
    captura só o dá por cumprido quando o banco mostra o Envio desligado."""
    info = D.ordens_do_estado(estado, agora)
    agora_s = time.time() if agora_s is None else agora_s
    if not armado_em or not 0 <= agora_s - float(armado_em) <= ARMADO_VALE_S:
        # sem armar, ou armado há tempo demais: este clique só (re)arma
        return (agora_s, _rotulo_armado(info["posicoes"]),
                "clique de novo em 5 s para confirmar")

    # as duas pastas (demo e real), sem banco: o zerar vale mesmo com a
    # mineração segurando a escrita
    comandos.escrever_zerar_tudo()
    ocupado = False
    try:
        contas = _contas_ativas()
    except (duckdb.Error, RuntimeError):
        contas, ocupado = [], True
    for cid in contas:
        # cada conta na sua tentativa: uma que falha não deixa a outra ligada
        try:
            AV.ligar_envio(cid, False, tentativas=TENTATIVAS_BANCO)
        except ValueError:
            pass            # conta apagada entre a lista e aqui: nada a desligar
        except (duckdb.Error, RuntimeError):
            ocupado = True

    if info["selo"] == "sem_captura":
        aviso = ("Comando gravado, esperando a captura voltar — stop e alvo "
                 "seguem na corretora")
    elif info["posicoes"] == 0:
        # nada a encerrar: o efeito é o Envio desligado no banco (feito
        # acima). Fora do pregão o comando só é lido na manhã seguinte e lá
        # é descartado (core/ordens.py `_de_outro_dia`)
        aviso = ("Envio de ordens desligado — nenhuma posição da automação "
                 "aberta para encerrar")
        if ocupado:
            aviso = ("Nenhuma posição da automação aberta · banco ocupado: o "
                     "Envio NÃO foi desligado no banco — desligue na ficha da "
                     "conta quando o banco liberar")
        return None, ROTULO, aviso
    else:
        aviso = "Zerando tudo: a captura encerra as posições na próxima volta"
    if ocupado:
        aviso += (" · banco ocupado: o Envio não foi desligado no banco, mas "
                  "o comando já vale pela captura")
    return None, ROTULO, aviso


def selo(info: dict) -> tuple:
    """(children, className, title) do selo das ordens no topo."""
    dica = info["texto"]
    if info["chamados"]:
        dica += " — precisa de você: " + "; ".join(
            str(c.get("texto") or c.get("tipo") or "chamado")
            for c in info["chamados"])
    elif info["selo"] == "travada":
        dica += (" — a perda do dia chegou a 90% do limite; as posições da "
                 "automação foram encerradas e nada entra até o próximo pregão")
    filhos = [html.Span("●", className="ord-selo-ponto"),
              html.Span(info["texto"], className="ord-selo-texto")]
    if info["chamados"]:
        n = len(info["chamados"])
        filhos.append(html.Span(f"⚠ {n}", className="ord-selo-chamados"))
    return filhos, f"{_CLASSE_SELO} ord-selo-{info['selo']}", dica


def register(app):
    @app.callback(
        Output("ord-selo", "children"),
        Output("ord-selo", "className"),
        Output("ord-selo", "title"),
        Output("ord-alarme", "data-alarme"),
        Output("ord-alarme", "data-chaves"),
        Input("ord-intervalo", "n_intervals"),
    )
    def selo_ordens(_n):
        info = D.ordens_do_estado(D.estado_captura(), datetime.now())
        filhos, classe, dica = selo(info)
        return (filhos, classe, dica, "1" if info["alarme"] else "0",
                info["chaves"])

    @app.callback(
        Output("ord-armado", "data"),
        Output("ord-zerar", "children"),
        Output("ord-zerar", "className"),
        Output("ord-zerar-aviso", "children"),
        Input("ord-zerar", "n_clicks"),
        State("ord-armado", "data"),
        prevent_initial_call=True,
    )
    def zerar_clique(n, armado):
        if not n:
            raise PreventUpdate
        armado, rotulo, aviso = zerar(armado, D.estado_captura(),
                                      datetime.now())
        classe = "ord-zerar" + (" ord-armado" if armado else "")
        return armado, rotulo, classe, aviso

    # Desarma sozinho depois de 5 s, como os botões da Operação: um
    # "Confirmar" esquecido viraria um zerar por engano no próximo clique.
    app.clientside_callback(
        """function (armado) {
            window._ordArmado = armado || null;
            var marca = window._ordArmado;
            if (armado) {
                setTimeout(function () {
                    if (window._ordArmado === marca) {
                        window._ordArmado = null;
                        window.dash_clientside.set_props('ord-armado', {data: null});
                        window.dash_clientside.set_props('ord-zerar',
                            {children: '""" + ROTULO + """', className: 'ord-zerar'});
                        window.dash_clientside.set_props('ord-zerar-aviso', {children: ''});
                    }
                }, 5000);
            } else {
                // o resultado do zerar fica 20 s à vista e some sozinho
                setTimeout(function () {
                    if (window._ordArmado === null) {
                        window.dash_clientside.set_props('ord-zerar-aviso', {children: ''});
                    }
                }, 20000);
            }
            return window.dash_clientside.no_update;
        }""",
        Output("ord-zerar-aviso", "role"),
        Input("ord-armado", "data"),
        prevent_initial_call=True,
    )
