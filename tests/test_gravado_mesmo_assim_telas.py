"""A marca "gravado mesmo assim" chega ao cartão da variante (Ao vivo ›
Estratégias) e à linha do membro (Portfólio) — sempre do plano EM VIGOR
naquele dia, não do mais novo gravado."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401
from ui.components import ao_vivo_panel as AP  # noqa: E402
from ui.components import portfolio_panel as PP  # noqa: E402

PEND = [{"nome": "Aguenta custo maior?", "motivo": "reprovado"},
        {"nome": "Ganha de entradas sorteadas ao acaso?", "motivo": "não medido"}]


def _textos(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(_textos(x) for x in c)
    return _textos(getattr(c, "children", None))


def _cenario():
    """Plano forçado vale de 02/09; um plano normal gravado em 30/09 vale de
    01/10 e aposenta o forçado a partir daí."""
    v = variantes.criar("romp-canal-02", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    forcado = plano.salvar(**campos_plano(wfa_id=13, run_id=47,
                                          gravado_mesmo_assim=True,
                                          pendencias=PEND),
                           agora=datetime(2026, 9, 1, 10))
    pf = P.criar("pf")
    P.adicionar_variante(pf, v)
    return v, pf, forcado


def _item(hoje):
    return next(l for l in AV.em_operacao(hoje))


def test_em_operacao_leva_a_marca_do_plano_em_vigor(banco):
    _, _, forcado = _cenario()
    item = _item(date(2026, 9, 15))
    assert item["plano"]["plano_id"] == forcado
    assert item["plano"]["gravado_mesmo_assim"] is True
    assert item["plano"]["pendencias"] == PEND


def test_vale_o_plano_em_vigor_nao_o_mais_novo(banco):
    _, _, forcado = _cenario()
    normal = plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                          agora=datetime(2026, 9, 30, 10))
    # 30/09: o normal já foi gravado mas só vale amanhã — o forçado segue
    antes = _item(date(2026, 9, 30))
    assert antes["plano"]["plano_id"] == forcado
    assert antes["plano"]["gravado_mesmo_assim"] is True
    depois = _item(date(2026, 10, 1))
    assert depois["plano"]["plano_id"] == normal
    assert depois["plano"]["gravado_mesmo_assim"] is False
    assert depois["plano"]["pendencias"] == []


def test_membros_do_portfolio_levam_a_marca_do_plano_em_vigor(banco):
    _, pf, _ = _cenario()
    plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                 agora=datetime(2026, 9, 30, 10))
    m = P.membros(pf, hoje=date(2026, 9, 30))[0]
    assert m["gravado_mesmo_assim"] is True and m["pendencias"] == PEND
    m = P.membros(pf, hoje=date(2026, 10, 1))[0]
    assert m["gravado_mesmo_assim"] is False and m["pendencias"] == []


def test_cartao_da_variante_mostra_a_etiqueta(banco):
    _cenario()
    cartao = AP.cartao_variante(_item(date(2026, 9, 15)), None)
    assert "gravado mesmo assim" in _textos(cartao)
    assert "Aguenta custo maior? (reprovado)" in repr(cartao)


def test_cartao_sem_plano_forcado_nao_mostra(banco):
    _cenario()
    plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                 agora=datetime(2026, 9, 30, 10))
    cartao = AP.cartao_variante(_item(date(2026, 10, 1)), None)
    assert "gravado mesmo assim" not in _textos(cartao)


def test_linha_do_membro_mostra_a_etiqueta():
    com = PP.linha_membro(1, "romp-canal-02", "rompimento_canal", False,
                          pendencias=PEND, gravado_mesmo_assim=True)
    assert "gravado mesmo assim" in _textos(com)
    assert "Ganha de entradas sorteadas ao acaso? (não medido)" in repr(com)
    sem = PP.linha_membro(1, "romp-canal-02", "rompimento_canal", False)
    assert "gravado mesmo assim" not in _textos(sem)
