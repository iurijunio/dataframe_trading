"""Tela Ao vivo: o que ela desenha a partir do que o core devolve."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import ao_vivo_panel as AP  # noqa: E402


def textos(c) -> str:
    """Todo o texto de uma árvore de componentes Dash, numa string só —
    inclusive o `value` dos campos (nome da conta, limite)."""
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(textos(x) for x in c)
    valor = getattr(c, "value", None)
    extra = str(valor) if isinstance(valor, (str, int, float)) else ""
    return extra + " " + textos(getattr(c, "children", None))


def ids(c) -> set:
    out = set()
    if isinstance(c, (list, tuple)):
        for x in c:
            out |= ids(x)
        return out
    if hasattr(c, "id") and getattr(c, "id", None) is not None:
        out.add(c.id if isinstance(c.id, str) else str(c.id))
    filhos = getattr(c, "children", None)
    if filhos is not None:
        out |= ids(filhos)
    return out


def test_painel_tem_as_pecas():
    p = AP.painel()
    assert p.id == "painel-aovivo"
    esperados = {"av-versao", "av-armado", "av-aberta", "av-aviso",
                 "av-portfolios", "av-variantes", "av-contas",
                 "av-arrumacao", "av-conta-nome", "av-conta-tipo",
                 "av-conta-limite", "av-btn-conta-criar"}
    assert esperados <= ids(p)
    assert "Estratégias" in textos(p)


from datetime import date, datetime  # noqa: E402

from core import ao_vivo as AV, codigo, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401
from ui import callbacks_ao_vivo as CA  # noqa: E402

QUI = date(2026, 10, 1)


def _cenario():
    v = variantes.criar("romp-canal-02", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    pid = plano.salvar(**campos_plano(
        wfa_id=13, run_id=47,
        codigo_hash=codigo.hash_estrategia("rompimento_canal"),
        regua={"veredito": "aprovada",
               "portoes": [{"nome": "Platô", "ok": True, "critico": True}]}),
        agora=datetime(2026, 9, 1, 10))
    pf = P.criar("portifolio-teste")
    lig = P.adicionar_variante(pf, v)
    wfa(18, 50)                                   # plano órfão
    orfao = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                         agora=datetime(2026, 9, 1, 10))
    return v, pid, pf, lig, orfao


def test_montar_desenha_as_quatro_secoes(banco):
    v, pid, pf, lig, orfao = _cenario()
    AV.criar_conta("Demo XP", "demo", 500.0)
    portfolios, vars_, contas, arruma = CA.montar(None, None, QUI)
    t = textos(portfolios)
    assert "portifolio-teste" in t and "desligado" in t
    t = textos(vars_)
    assert "romp-canal-02" in t and "portfólio desligado" in t
    assert "papel" in t
    assert "Demo XP" in textos(contas) and "500" in textos(contas)
    assert f"#{orfao}" in textos(arruma)


def test_ficha_aberta(banco):
    v, pid, pf, lig, orfao = _cenario()
    _, vars_, _, _ = CA.montar(None, lig, QUI)
    t = textos(vars_)
    assert f"plano #{pid}" in t
    assert "walk-forward #13" in t and "mineração #47" in t
    assert "aprovada" in t and "Platô" in t
    assert "código confere" in t


def test_botao_armado_pede_confirmacao(banco):
    v, pid, pf, lig, orfao = _cenario()
    portfolios, _, _, _ = CA.montar(f"pf-ligar:{pf}", None, QUI)
    assert "Confirmar?" in textos(portfolios)


def test_repetida_aparece_no_topo(banco):
    v, pid, pf, lig, orfao = _cenario()
    pf2 = P.criar("outro")
    P.adicionar_variante(pf2, v)
    AV.ligar_portfolio(pf)
    AV.ligar_portfolio(pf2)
    _, vars_, _, _ = CA.montar(None, None, QUI)
    assert "está em 2 portfólios ligados" in textos(vars_)


def test_sem_nada(banco):
    portfolios, vars_, contas, arruma = CA.montar(None, None, QUI)
    assert "nenhum portfólio" in textos(portfolios)
    assert "nenhuma variante" in textos(vars_)
    assert "nenhuma conta" in textos(contas)
    assert "nada a arrumar" in textos(arruma)
