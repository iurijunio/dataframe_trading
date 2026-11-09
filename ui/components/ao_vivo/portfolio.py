"""Estratégias: cartão do portfólio e as contas dele."""
from __future__ import annotations

from dash import html

from .. import operacao_panel as OP
from ..cartao import dica
from ..icones import icone

from .base import _botao, _campo_dd, _campo_txt, _chip, _etiqueta, _plural
from .contas import limite_br


# -------------------------------------------------------------- portfólios
def cartao_portfolio(p: dict, contas: list[dict], armado,
                     n_liberadas: int | None = None) -> html.Div:
    # conta arquivada ainda gravada no portfólio continua na lista, marcada:
    # senão salvar apagaria a escolha sem ninguém perceber
    def opcoes(tipo):
        return [{"label": c["nome"] + (" (arquivada)" if c.get("arquivada_em")
                                       else ""), "value": c["conta_id"]}
                for c in contas if c["tipo"] == tipo
                and (not c.get("arquivada_em")
                     or c["conta_id"] in (p["conta_demo_id"], p["conta_real_id"]))]
    demo, real = opcoes("demo"), opcoes("real")
    pid = p["portfolio_id"]
    n = p["n_membros"]
    if p["ligado"]:
        estado = _etiqueta("ligado", "verde")
        interruptor = _botao("Desligar portfólio", "pf-desligar", pid, armado,
                             "btn-ghost av-btn-sec",
                             prefixo=icone("power", pequeno=True), so_icone=True)
        explica = "Ligado: as variantes dele que estão ligadas podem rodar."
    else:
        estado = _etiqueta("desligado", "cinza")
        interruptor = _botao("Ligar portfólio", "pf-ligar", pid, armado,
                             "btn-ghost av-btn-principal",
                             prefixo=icone("power", pequeno=True), so_icone=True)
        explica = "Desligado: nenhuma variante dele roda. Ligue para liberar."
    qtd = (_plural(n, "variante", "variantes") if n else "nenhuma variante")
    corpo = [
        html.Div([
            html.Div([html.Span(p["nome"], className="av-nome-fixo"), estado],
                     className="av-cab-esq"),
            # o power fica à parte, na ponta: ligar/desligar o portfólio inteiro
            html.Div(interruptor, className="av-pf-power"),
        ], className="av-cab"),
        html.P([html.Span(qtd, className="av-qtd"), dica(explica)],
               className="av-texto"),
    ]
    if not n:
        corpo.append(html.P("Este portfólio está vazio. Adicione variantes "
                            "nele na tela Portfólio.", className="av-vazio"))
    if p["ligado"] and n_liberadas == 0:
        corpo.append(html.P("⚠ nenhuma variante deste portfólio está rodando "
                            "— veja o motivo em Variantes",
                            className="av-alerta"))
    corpo.append(_tabela_contas_pf(p, contas, demo, real, armado))
    return html.Div(corpo, className="av-cartao av-cartao-pf"
                    + (" av-ligado" if p["ligado"] else ""))


def _tabela_contas_pf(p: dict, contas: list[dict], demo, real, armado) -> html.Div:
    """Uma linha por conta do portfólio: chip real/demo · conta do MT5 ·
    Envio de ordens · limite do dia. Os ids levam o id do PORTFÓLIO (a mesma
    conta pode ser a demo de dois portfólios, e id repetido quebra a página);
    a conta é resolvida no clique."""
    pid = p["portfolio_id"]
    demo_c = next((c for c in contas if c["conta_id"] == p["conta_demo_id"]
                   and not c.get("arquivada_em")), None)
    real_c = next((c for c in contas if c["conta_id"] == p["conta_real_id"]
                   and not c.get("arquivada_em")), None)
    cab = html.Div([
        html.Span("Conta", className="av-pf-cab-c"),
        html.Span("Conta do MT5", className="av-pf-cab-c"),
        html.Span(["Envio de ordens", dica(
            "É o interruptor que deixa a automação mandar ordens para a conta "
            "demo. Desligado, o papel segue normal e nada vai à corretora. "
            "Para ligar, a conta precisa de um limite de perda do dia: ao "
            "chegar nele a automação para de entrar.")], className="av-pf-cab-c"),
        html.Span(["Limite de perda do dia", dica(
            "Quanto a conta pode perder no dia antes da automação parar de "
            "entrar. Vazio = sem limite (e então o envio não liga).")],
            className="av-pf-cab-c"),
    ], className="av-pf-linha av-pf-cab")
    linha_demo = html.Div([
        html.Div(_chip("demo", "demo"), className="av-pf-c"),
        html.Div(_campo_dd("conta-demo", pid, p["conta_demo_id"], demo,
                           "escolha…" if demo else "nenhuma conta demo"),
                 className="av-pf-c"),
        html.Div(_envio_demo(pid, demo_c, armado), className="av-pf-c"),
        html.Div(_limite_conta(pid, demo_c, "pf-limite", "pf-limite", armado),
                 className="av-pf-c"),
    ], className="av-pf-linha")
    linha_real = html.Div([
        html.Div(_chip("real", "real"), className="av-pf-c"),
        html.Div(_campo_dd("conta-real", pid, p["conta_real_id"], real,
                           "escolha…" if real else "nenhuma conta real"),
                 className="av-pf-c"),
        html.Div(_envio_real(pid, real_c, armado), className="av-pf-c"),
        html.Div(_limite_conta(pid, real_c, "pf-limite-real", "pf-limite-real",
                               armado), className="av-pf-c"),
    ], className="av-pf-linha")
    rodape = html.Div(_botao("Salvar contas", "pf-contas", pid, armado,
                             "btn-ghost av-btn-sec"), className="av-pf-rodape")
    # a real vem primeiro, como no v2
    return html.Div([cab, linha_real, linha_demo, rodape], className="av-pf-tab")


def _chave_envio(acao, alvo, armado):
    """A chave do Envio de ordens, a mesma da tela Operação: as classes e o
    "Confirmar?" vêm de `OP.estado_botao`, o nome e o texto dos dois cliques
    de `OP._NOMES_BOTAO` e `OP._TITULO_ENVIO`. Sem texto na chave: a cor e a
    bolinha dizem. O id é o da Ao vivo (`av-acao`), e o clique cai no `agir`,
    que confirma em dois cliques pelo `OPC.acao`."""
    _rotulo, classe = OP.estado_botao(acao, alvo, armado)
    nome = OP._NOMES_BOTAO[acao]
    tipo = "real" if acao.startswith("envio-real-") else "demo"
    titulo = OP._TITULO_ENVIO[tipo]["desligar" if acao.endswith("-desligar")
                                    else "ligar"]
    return html.Button("", n_clicks=0, title=f"{nome}: {titulo}",
                       className=classe, **{"aria-label": nome},
                       id={"type": "av-acao", "acao": acao, "id": alvo})


def _envio_demo(pid, conta: dict | None, armado):
    """O Envio da conta demo: a chave de liga/desliga, em dois cliques.
    Os ids levam a CONTA junto ("portfólio:conta"): desligar não depende de
    uma leitura do banco antes de escrever o comando."""
    if conta is None:
        return html.Span(["—", dica("Escolha a conta demo e salve: o limite e "
                                    "a chave de envio são dela.")],
                         className="mut")
    alvo = f"{pid}:{conta['conta_id']}"
    acao = "envio-desligar" if conta.get("envio_ligado") else "envio-ligar"
    return _chave_envio(acao, alvo, armado)


def _envio_real(pid, conta: dict | None, armado):
    """O Envio da conta real: a chave de liga/desliga, em dois cliques, como
    a da demo. O id leva a conta junto ("portfólio:conta") e a ação
    `envio-real-*` leva a pasta de comandos da real no core."""
    if conta is None:
        return html.Span("—", className="mut")
    alvo = f"{pid}:{conta['conta_id']}"
    acao = ("envio-real-desligar" if conta.get("envio_ligado")
            else "envio-real-ligar")
    return _chave_envio(acao, alvo, armado)


def _limite_conta(pid, conta: dict | None, campo: str, acao: str, armado):
    """Limite de perda do dia de uma conta do portfólio: campo + Salvar."""
    if conta is None:
        return html.Span("—", className="mut")
    return html.Div([
        _campo_txt(campo, pid, limite_br(conta["limite_perda_dia"]),
                   "sem limite", numerico=True),
        _botao("Salvar", acao, pid, armado, "btn-ghost btn-sm av-btn-sec"),
    ], className="av-pf-limite-campo")
