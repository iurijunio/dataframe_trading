"""Número de uma casa nunca vira "-0,0" nem "3,0" na tela.

-0,04 tick de derrapagem arredonda para zero; o sinal de menos sobrando
fazia a tela dizer "-0,0 tick", que parece defeito. O teste de zero e de
inteiro tem de olhar o número JÁ arredondado.
"""
import pytest

from ui.components import operacao_panel as OP
from ui.components import ordens_panel as OR


def _texto(no) -> str:
    if no is None:
        return ""
    if isinstance(no, (str, int, float)):
        return str(no)
    if isinstance(no, (list, tuple)):
        return "".join(_texto(x) for x in no)
    return _texto(getattr(no, "children", None))


@pytest.mark.parametrize("v, esperado", [
    (-0.04, "0"), (0.04, "0"), (-0.0, "0"), (0.0, "0"),
    (-0.06, "-0,1"), (0.06, "0,1"), (1.0, "1"), (-2.0, "-2"),
    (2.96, "3"), (-2.96, "-3"), (1.3, "1,3"), (None, "—"),
])
def test_decimal_arredonda_antes_de_olhar_zero_e_inteiro(v, esperado):
    assert OR._decimal(v) == esperado


def test_decimal_com_duas_casas():
    assert OR._decimal(-0.004, 2) == "0"
    assert OR._decimal(1.996, 2) == "2"
    assert OR._decimal(1.25, 2) == "1,25"


def test_papel_x_demo_da_operacao_sem_menos_zero():
    cel = OP._papel_x_demo({"derrapagem_entrada": -0.04,
                            "derrapagem_saida": 2.96})
    assert _texto(cel) == "0 · 3 ticks"


def test_contratos_da_demo_sem_virgula_sobrando():
    assert OP._ctr_demo({"contratos": 2.0}) == "2"
    assert OP._ctr_demo({"contratos": 1.5}) == "1,5"
    assert OP._ctr_demo({"contratos": None}) == "—"


@pytest.mark.parametrize("extra, esperado", [
    (0.04, "0"), (-0.04, "0"), (0.3, "+0,3"), (-0.5, "-0,5")])
def test_papel_x_demo_diferenca_sem_mais_zero(extra, esperado):
    cmp = {"pregoes": 2,
           "papel": {"n": 2, "derrapagem": 1.0},
           "demo": {"n": 2, "derrapagem": 1.0 + extra, "derrapagem_extra": extra}}
    t = _texto(OR.tabela_papel_demo(cmp))
    i = t.index("Derrapagem média por ponta")
    trecho = t[i:i + 70]
    assert "+0 " not in trecho and "+0tick" not in trecho and "-0,0" not in trecho
    assert trecho.rstrip().endswith(esperado) or f"tick{esperado}" in trecho


def _derrapagem_media(v) -> str:
    demo = {"n": 2, "resultado_por_contrato": 59.0, "pontos_por_operacao": 302.5,
            "fator_lucro": 2.0, "acerto": 1.0, "contratos_por_operacao": 1.0,
            "total": 118.0, "mesmo_minuto": 1.0, "derrapagem_extra": v,
            "atraso_ms": 65.0, "rejeitadas": 0}
    arv = OP.tabela_comparativo({"esperado_wfa": None, "papel": None,
                                 "demo": demo, "real": None})
    t = _texto(arv)
    i = t.index("Derrapagem média")
    return t[i:i + 60]


@pytest.mark.parametrize("v, esperado", [
    (-0.04, "0 tick"), (0.04, "0 tick"), (-0.5, "-0,5 tick"), (0.3, "+0,3 tick"),
    (1.0, "+1 tick"),
])
def test_derrapagem_media_do_comparativo(v, esperado):
    trecho = _derrapagem_media(v)
    assert ",0 tick" not in trecho
    assert esperado in trecho
