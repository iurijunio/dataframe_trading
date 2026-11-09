"""Pesquisa: ativo, abas e resumos do menu, contas do espaço de mineração."""
from __future__ import annotations

from datetime import datetime

from dash import no_update

from core import ativo as ativo_mod
from core.wfa_runner import VARREDURA
from core import optimizer
from core.optimizer import MINERACAO

from .. import data as D
from ..components import controls
from ..components.cartao import simbolo_moeda


def _simbolo(valor: str | None) -> str:
    """O ativo escolhido na tela, com o padrao de arranque como rede."""
    return valor or D.simbolo_padrao()


def _ativo_ao_entrar_wfa(do_menu, aberta, validos: set):
    """O ativo com que o Walk-Forward abre.

    O do menu, salvo quando há varredura na memória (a barra de progresso e
    o resultado são dela) e a mineração aberta é essa, ou nenhuma está aberta
    (depois de um F5): aí vale o ativo DELA, para a lista não esconder o que
    a tela está mostrando. Uma mineração só escolhida, sem varredura, não
    prende o seletor — trocar o ativo no menu volta a valer.
    """
    na_memoria = VARREDURA.estado.get("run_id")
    if na_memoria is not None and aberta in (None, na_memoria):
        dela = (optimizer.simbolo_salva(na_memoria)
                or VARREDURA.estado.get("simbolo"))
        if dela in validos:
            return dela
    return _simbolo(do_menu)


def _moeda_da_mineracao() -> str:
    """A moeda do ativo que a mineração em tela varreu (e não a do seletor)."""
    return ativo_mod.moeda_de(MINERACAO.estado.get("symbol"))


def _entrar_mineracao_salva(e: dict, run_id: int, d: dict) -> None:
    """Põe no estado uma mineração salva, pelo mesmo caminho de uma recém-rodada.
    `d` é `optimizer.detalhes_salva(run_id)`."""
    e["trials"] = optimizer.carregar_salva(run_id)
    # o banco nao trunca: aqui a tabela E o universo completo
    e["resumo"], e["fonte"] = e["trials"], "banco"
    e["fim_otimizacao"] = d.get("corte") or d["holdout_de"]
    e["symbol"] = d.get("symbol")
    # de qual salva ela é: depois de um F5, `_arranque` a recarrega inteira
    e["run_id"] = run_id
    e["mensagem"] = f"mineração #{run_id} carregada do banco"


def rotulos_moeda(ativo: str | None, n: int) -> list[str]:
    """O símbolo da moeda do ativo, repetido para os `n` rótulos da tela."""
    return [simbolo_moeda(ativo_mod.moeda_de(ativo))] * n


# ------------------------------------------------- menu: abas e gavetas
def menu_abas(aba, qual, subtela):
    """Qual painel do menu aparece; o que é só da varredura some fora dela.

    No Backtest não há aba Períodos nem gaveta Filtro de mineração: se a aba
    ativa era Períodos, cai para Entrada. Fora da Mineração o menu nem está
    na tela — nada muda, e a aba fica como o usuário deixou.
    Devolve (aba, opções, um estilo por aba de `ABAS_MENU`, estilo da gaveta
    Filtro de mineração).
    """
    abas = controls.ABAS_MENU
    if qual != "mineracao":
        return (no_update, no_update, *[no_update] * len(abas), no_update)
    # na Busca automática valem as abas da Varredura: Períodos traz treino,
    # teste, passo e holdout, e o "mínimo de operações" entra no filtro
    varredura = subtela in ("varredura", "busca")
    visiveis = [a for a in abas if varredura or a != "periodos"]
    efetiva = aba if aba in visiveis else "entrada"
    opcoes = [{"label": controls.ROTULOS_ABA[a], "value": a} for a in visiveis]
    return (efetiva if efetiva != aba else no_update, opcoes,
            *[VISIVEL if a == efetiva else OCULTO for a in abas],
            VISIVEL if varredura else OCULTO)


def pontinhos(ligados, ids, qual, subtela) -> str:
    """Classe das abas: `dot-<aba>` em cada aba com campo marcado para
    minerar. Só na Varredura — no Backtest não existe minerar."""
    base = "menu-abas"
    if qual != "mineracao" or subtela != "varredura":
        return base
    marcadas = {controls.ABA_DO_CAMPO.get(i["p"], "entrada")
                for i, v in zip(ids, ligados) if v}
    return " ".join([base] + [f"dot-{a}" for a in controls.ABAS_MENU
                              if a in marcadas])


def _n(v) -> str:
    """Número curto para o resumo: 8, 1,5 (sem ",0" à toa); vazio vira "—"."""
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return f"{f:g}".replace(".", ",")


def resumo_gestao(stop_tipo, alvo_tipo, stop, alvo, trailing,
                  stop_atr=(None, None), stop_pct=None, alvo_atr=(None, None),
                  alvo_razao=None, alvo_pct=None) -> str:
    if stop_tipo == "atr":
        s = f"stop ATR {_n(stop_atr[0])}×{_n(stop_atr[1])}"
    elif stop_tipo == "percentual":
        s = f"stop {_n(stop_pct)}%"
    else:
        s = f"stop {_n(stop)}"
    if alvo_tipo == "atr":
        a = f"alvo ATR {_n(alvo_atr[0])}×{_n(alvo_atr[1])}"
    elif alvo_tipo == "multiplicador":
        a = f"alvo {_n(alvo_razao)}× stop"
    elif alvo_tipo == "percentual":
        a = f"alvo {_n(alvo_pct)}%"
    else:
        a = f"alvo {_n(alvo)}"
    return f"{s} · {a} · trailing {_n(trailing)}"


def resumo_protecoes(breakeven, gatilho, trava, max_barras) -> str:
    partes = []
    if breakeven:
        partes.append(f"breakeven {_n(breakeven)}%")
    if gatilho:
        partes.append(f"stop móvel {_n(gatilho)}%→{_n(trava)}%")
    if max_barras:
        partes.append(f"máx. {_n(max_barras)} barras")
    return " · ".join(partes) or "desligadas"


def resumo_filtro_mercado(regua, periodo, limiar) -> str:
    if not periodo or not limiar:
        return "sem filtro"
    nome = "tendência" if regua == "tendencia" else "rango"
    return f"{nome} · ADX {_n(periodo)}/{_n(limiar)}"


def _dias(dias) -> str:
    from ..components.catalogo import DIAS
    nomes = {v: n for n, v in DIAS}
    d = sorted(dias or [])
    if not d:
        return "nenhum dia"
    if len(d) > 2 and d == list(range(d[0], d[-1] + 1)):
        return f"{nomes.get(d[0], d[0])}–{nomes.get(d[-1], d[-1])}"
    return ",".join(str(nomes.get(x, x)) for x in d)


def resumo_janela(ini, fim, fechamento, dias) -> str:
    return f"{ini or '—'}–{fim or '—'} · fecha {fechamento or '—'} · {_dias(dias)}"


def resumo_limites(ganho, perda, ops, prejuizos, moeda) -> str:
    partes = []
    if ganho:
        partes.append(f"ganho {moeda} {_n(ganho)}")
    if perda:
        partes.append(f"perda {moeda} {_n(perda)}")
    if ops:
        partes.append(f"{_n(ops)} ops")
    if prejuizos:
        partes.append(f"{_n(prejuizos)} prej.")
    return " · ".join(partes) or "sem limite"


def resumo_custos(corretagem, emolumentos, slippage, moeda) -> str:
    return (f"{moeda} {_n(corretagem)} + {_n(emolumentos)} · "
            f"slippage {_n(slippage)}")


def resumo_posicao(modo, contratos, risco, capital, moeda) -> str:
    if modo == "risco_fixo":
        p = f"risco {moeda} {_n(risco)}"
    else:
        p = f"{_n(contratos)} contrato{'' if contratos in (1, None) else 's'}"
    return f"{p} · capital {moeda} {_n(capital)}"


def resumo_filtro_mineracao(min_ops) -> str:
    return f"mín. {_n(min_ops)} operações" if min_ops else "sem mínimo"


# o que `resumos` lê, na ordem dos argumentos
ENTRADAS_RESUMO = [
    ("e-stop-tipo", "value"), ("e-alvo-tipo", "value"),
    *[({"type": "val", "p": p}, "value")
      for p in ("stop_pontos", "alvo_pontos", "trailing_pontos",
                "stop_atr_periodo", "stop_atr_mult", "stop_pct",
                "alvo_atr_periodo", "alvo_atr_mult", "alvo_razao", "alvo_pct",
                "breakeven_pct", "step_gatilho_pct", "step_distancia_pct")],
    ("e-max-barras", "value"),
    ("e-filtro-adx", "value"),
    ({"type": "val", "p": "adx_periodo"}, "value"),
    ({"type": "val", "p": "adx_limiar"}, "value"),
    ("e-ent-ini", "value"), ("e-ent-fim", "value"), ("e-fechamento", "value"),
    ("e-dias", "value"),
    ("e-min-ops", "value"),
    ("e-lim-ganho", "value"), ("e-lim-perda", "value"),
    ("e-max-trades", "value"), ("e-max-loss", "value"),
    ("e-corretagem", "value"), ("e-emolumentos", "value"),
    ("e-slippage", "value"),
    ("e-modo", "value"), ("e-contratos", "value"), ("e-risco", "value"),
    ("e-capital", "value"),
    ("ativo", "value"),
]


def resumos(stop_tipo, alvo_tipo, stop, alvo, trailing, s_atr_p, s_atr_m,
            s_pct, a_atr_p, a_atr_m, a_razao, a_pct, breakeven, gatilho, trava,
            max_barras, regua, adx_p, adx_l, ini, fim, fech, dias, min_ops,
            ganho, perda, ops, prej, corretagem, emolumentos, slippage,
            modo_pos, contratos, risco, capital, simbolo):
    """O resumo de cada gaveta, na ordem de `controls.GRUPOS_GAVETA`."""
    moeda = rotulos_moeda(simbolo, 1)[0]
    por_grupo = {
        "gestao": resumo_gestao(stop_tipo, alvo_tipo, stop, alvo, trailing,
                                (s_atr_p, s_atr_m), s_pct, (a_atr_p, a_atr_m),
                                a_razao, a_pct),
        "protecoes": resumo_protecoes(breakeven, gatilho, trava, max_barras),
        "filtro-mercado": resumo_filtro_mercado(regua, adx_p, adx_l),
        "janela": resumo_janela(ini, fim, fech, dias),
        "filtro-mineracao": resumo_filtro_mineracao(min_ops),
        "limites": resumo_limites(ganho, perda, ops, prej, moeda),
        "custos": resumo_custos(corretagem, emolumentos, slippage, moeda),
        "posicao": resumo_posicao(modo_pos, contratos, risco, capital, moeda),
    }
    return [por_grupo[g] for g in controls.GRUPOS_GAVETA]


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
        # round: (2,3 - 2,0) / 0,1 = 2,9999... e o int() perdia um valor
        total *= max(1, int(round((ate - de) / passo, 9)) + 1)
    return total


OCULTO = {"display": "none"}
VISIVEL = {"display": "block"}
VISIVEL_GRADE = {"display": "grid"}   # blocos `.grid-2` que o callback mostra

# tamanho do espaco de busca atual, escrito pelo callback `espaco` e lido por
# `pode_minerar` - evita recalcular o produto cartesiano so para saber se o
# botao pode acender
_COMBOS: dict[str, int] = {"n": 0}


def _br(iso: str) -> str:
    """2026-03-13 -> 13/03/2026"""
    p = (iso or "").split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else (iso or "")
