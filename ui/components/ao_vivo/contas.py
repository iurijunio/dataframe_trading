"""Estratégias: tabela de contas e linhas órfãs."""
from __future__ import annotations

import re

from dash import html

from ..cartao import dica

from .base import _botao, _campo_dd, _campo_txt, _chip, _etiqueta, _kv, _rotulado


# ------------------------------------------------------------------- contas
def limite_br(v) -> str:
    """Limite no formato que o campo aceita de volta, sem arredondar:
    1500.5 -> "1.500,50", 500.0 -> "500"."""
    if v is None:
        return ""
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pasta_curta(caminho) -> str:
    """"C:\\MT5 Terminal - Real\\terminal64.exe" → "…MT5 Terminal - Real": só a
    última pasta (o terminal64.exe não conta). O caminho inteiro fica no
    `title` da célula. Vazio → travessão."""
    if not caminho or not str(caminho).strip():
        return "—"
    partes = [p for p in re.split(r"[\\/]+", str(caminho).strip()) if p]
    if partes and partes[-1].lower().endswith(".exe"):
        partes = partes[:-1]
    return f"…{partes[-1]}" if partes else "—"


def tabela_contas(contas: list[dict], armado) -> html.Div:
    """A lista de contas: uma linha por conta (Tipo · Nome · Número · Servidor ·
    Pasta do MT5 · Limite · Editar). Editar abre o formulário da própria conta
    logo abaixo da linha (`linha_conta`)."""
    if not contas:
        return html.P("nenhuma conta cadastrada", className="av-vazio")
    cab = html.Div([
        html.Span("Tipo", className="av-conta-cab-c"),
        html.Span("Nome", className="av-conta-cab-c"),
        html.Span("Número", className="av-conta-cab-c"),
        html.Span("Servidor", className="av-conta-cab-c"),
        html.Span(["Pasta do MT5", dica(
            "Só se você tiver mais de um MT5 instalado: a pasta do terminal64.exe "
            "desta conta.")], className="av-conta-cab-c"),
        html.Span(["Limite do dia", dica(
            "Quanto a conta pode perder no dia, em reais. Sem limite, o envio "
            "de ordens não liga.")], className="av-conta-cab-c"),
        html.Span("", className="av-conta-cab-c"),
    ], className="av-conta-grade av-conta-cab")
    return html.Div([cab, *[linha_conta(c, armado) for c in contas]],
                    className="av-tab-contas")


def linha_conta(c: dict, armado) -> html.Details:
    """Uma conta: a linha da tabela (o próprio resumo do `<details>`) e, ao
    clicar Editar, o formulário dela. Sem número e servidor a automação não
    consegue conferir em qual conta o MT5 está logado, então não pode mandar
    ordem: a etiqueta avisa na linha."""
    cid = c["conta_id"]
    faltam = not c.get("login") or not c.get("servidor")
    limite = c["limite_perda_dia"]
    tipo = [_chip(c["tipo"], c["tipo"])]
    if faltam:
        tipo.append(_etiqueta("faltam os dados do MT5 — não poderá receber "
                              "ordens", "ambar"))
    resumo = html.Span([
        html.Span(tipo, className="av-conta-c av-conta-tipo"),
        html.Span(c["nome"], className="av-conta-c av-conta-nome"),
        html.Span("—" if c.get("login") is None else str(c["login"]),
                  className="av-conta-c mono"),
        html.Span(c.get("servidor") or "—", className="av-conta-c"),
        html.Span(_pasta_curta(c.get("terminal")),
                  className="av-conta-c av-conta-pasta mono",
                  title=c.get("terminal") or None),
        html.Span("sem limite" if limite is None else f"R$ {limite_br(limite)}",
                  className="av-conta-c mono"),
        html.Span("Editar ▾", className="btn-ghost btn-sm av-btn-sec av-conta-editar"),
    ], className="av-conta-grade av-conta-linha")
    form = html.Div([
        _rotulado("Nome", _campo_txt("conta-nome", cid, c["nome"], "nome"),
                  classe="av-campo-nome"),
        _rotulado("Limite de perda diária (R$)",
                  _campo_txt("conta-limite", cid,
                             limite_br(c["limite_perda_dia"]),
                             "sem limite", numerico=True),
                  classe="av-campo-limite"),
        _rotulado("Número da conta",
                  _campo_txt("conta-login", cid,
                             "" if c.get("login") is None else str(c["login"]),
                             "número no MT5", numerico=True),
                  classe="av-campo-limite"),
        _rotulado("Servidor",
                  _campo_txt("conta-servidor", cid, c.get("servidor") or "",
                             "servidor"),
                  classe="av-campo-nome"),
        _rotulado("Pasta do MT5",
                  _campo_txt("conta-terminal", cid, c.get("terminal") or "",
                             "opcional"),
                  classe="av-campo-largo"),
        html.Div([_botao("Salvar", "conta-salvar", cid, armado,
                         "btn-ghost btn-sm av-btn-sec"),
                  _botao("Arquivar", "conta-arquivar", cid, armado,
                         "btn-ghost btn-sm av-btn-perigo")],
                 className="av-campo-botao av-botoes"),
    ], className="av-form-linha av-conta")
    return html.Details([
        html.Summary(resumo, className="av-conta-sum"),
        html.Div(form, className="av-conta-corpo"),
    ], className="av-conta-det")


# ---------------------------------------------------------------- arrumação
# ---------------------------------------------------------------- arrumação
def _planos_txt(o):
    ids = o.get("plano_ids") or [o["plano_id"]]
    return ("plano " if len(ids) == 1 else "planos ") + ", ".join(f"#{i}" for i in ids)


def linha_orfao(o: dict, opcoes_variante: list[dict],
                opcoes_manter: list[dict], armado) -> html.Div:
    rid = o["run_id"]
    txt = _planos_txt(o)
    varios = len(o.get("plano_ids") or [o["plano_id"]]) > 1
    return html.Div([
        html.Div([html.Div([html.Span(txt[0].upper() + txt[1:],
                                      className="av-nome-fixo"),
                            _etiqueta("sem variante", "ambar")],
                           className="av-cab-esq")], className="av-cab"),
        html.P(("Estes planos não pertencem" if varios else
                "Este plano não pertence") + " a nenhuma variante.",
               className="av-texto"),
        _kv([("Estratégia", o["strategy"]),
             ("Mineração", f"#{rid} · {o['nome'] or 'sem nome'}")]),
        html.Div([
            _rotulado("1. Escolha a variante",
                      _campo_dd("vincular-variante", rid, None,
                                opcoes_variante, "escolha a variante…"),
                      classe="av-campo-largo"),
            _rotulado("2. Se ela já tiver um plano ativo, qual fica?",
                      _campo_dd("vincular-manter", rid, None, opcoes_manter,
                                "deixe vazio se ela não tiver"),
                      explica="Uma variante só pode ter um plano em vigor. "
                              "Escolha qual continua; o outro sai de vigor "
                              "no próximo pregão.",
                      classe="av-campo-largo"),
            html.Div(_botao("Vincular", "vincular", rid, armado,
                            "btn-ghost av-btn-principal"),
                     className="av-campo-botao"),
        ], className="av-form-linha"),
    ], className="av-cartao av-orfao")
