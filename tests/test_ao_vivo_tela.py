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
                 "av-conta-limite", "av-btn-conta-criar",
                 "av-conta-login", "av-conta-servidor", "av-conta-terminal",
                 "av-btn-mt5-puxar", "av-mt5-aviso"}
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


def test_resumo_do_topo(banco):
    _cenario()
    resumo, *_ = CA.montar(None, None, QUI, com_resumo=True)
    t = " ".join(textos(resumo).split())
    assert "0 de 1 portfólios ligados" in t
    assert "0 de 1 variantes liberadas" in t
    assert "1 plano para arrumar" in t


def test_ficha_mostra_disjuntor_em_palavras(banco):
    v = variantes.criar("romp-canal-02", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    plano.salvar(**campos_plano(
        wfa_id=13, run_id=47, disjuntor={
            "nivel1": {"queda": 300.0, "perdas_seguidas": 3, "acao": "x"},
            "nivel2": {"queda": 900.0, "acao": "y"}}),
        agora=datetime(2026, 9, 1, 10))
    lig = P.adicionar_variante(P.criar("pf"), v)
    _, vars_, _, _ = CA.montar(None, lig, QUI)
    t = textos(vars_)
    assert "reduz para 1 contrato se cair R$ 300,00 ou após 3 perdas seguidas" in t
    assert "desliga se cair R$ 900,00" in t


def test_plano_ainda_nao_vale_no_titulo(banco):
    v = variantes.criar("romp-canal-02", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                 agora=datetime(2026, 9, 1, 10))
    lig = P.adicionar_variante(P.criar("pf"), v)
    _, vars_, _, _ = CA.montar(None, lig, date(2026, 8, 20))
    assert "ainda não vale — entra em" in textos(vars_)


def test_plano_sem_risco_nem_capital_mostra_travessao(banco):
    v = variantes.criar("romp-canal-02", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    plano.salvar(**campos_plano(wfa_id=13, run_id=47, capital=None,
                                risco_efetivo_pct=None, disjuntor={}),
                 agora=datetime(2026, 9, 1, 10))
    lig = P.adicionar_variante(P.criar("pf"), v)
    _, vars_, _, _ = CA.montar(None, lig, QUI)
    t = " ".join(textos(vars_).split())      # rótulo e valor: espaço único
    assert "Capital —" in t and "Risco por pregão —" in t
    assert "Capital R$ 0,00" not in t and "Risco por pregão 0,00%" not in t


def test_dois_planos_orfaos_da_mesma_mineracao_uma_linha(banco):
    wfa(18, 50)
    wfa(19, 50)
    a = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                     agora=datetime(2026, 9, 1, 10))
    b = plano.salvar(**campos_plano(wfa_id=19, run_id=50),
                     agora=datetime(2026, 9, 1, 11))
    _, _, _, arruma = CA.montar(None, None, QUI)
    t = textos(arruma)
    assert f"#{a}" in t and f"#{b}" in t
    alvo = [i for i in ids(arruma) if "vincular-variante" in i]
    assert len(alvo) == 1


def test_portfolio_ligado_sem_variante_liberada_avisa(banco):
    v, pid, pf, lig, orfao = _cenario()
    AV.ligar_portfolio(pf)
    AV.desligar_membro(lig)
    portfolios, vars_, _, _ = CA.montar(None, None, QUI)
    assert "nenhuma variante deste portfólio está rodando" in textos(portfolios)
    AV.ligar_membro(lig)
    portfolios, vars_, _, _ = CA.montar(None, None, QUI)
    assert "nenhuma variante deste portfólio está rodando" not in textos(portfolios)
    assert "liberada" in textos(vars_)


def _opcoes(c):
    if c is None or isinstance(c, (str, int, float)):
        return []
    out = []
    if isinstance(c, (list, tuple)):
        for x in c:
            out += _opcoes(x)
        return out
    out += list(getattr(c, "options", None) or [])
    return out + _opcoes(getattr(c, "children", None))


def test_escolha_de_qual_plano_fica_tem_contexto(banco):
    v = variantes.criar("v7", "rompimento_canal")
    mineracao(53, variante_id=v)
    wfa(24, 53)
    p4 = plano.salvar(**campos_plano(wfa_id=24, run_id=53),
                      agora=datetime(2026, 9, 28, 10))
    mineracao(50)
    wfa(18, 50)
    p3 = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                      agora=datetime(2026, 9, 25, 11))
    _, _, _, arruma = CA.montar(None, None, QUI)
    t = " | ".join(o["label"] for o in _opcoes(arruma))
    assert "atual da variante v7" in t and "desta mineração" in t
    assert "gravado 28/09" in t and "gravado 25/09" in t


def test_ficha_sem_codigos_crus_e_datas_legiveis(banco):
    v = variantes.criar("v", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    pid = plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                       agora=datetime(2026, 9, 1, 10))   # terça
    from core import db_manager as db
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET vale_a_partir = NULL")
        con.execute("UPDATE wfa_runs SET inteligencia = 'centroide_mediana'")
    lig = P.adicionar_variante(P.criar("pf"), v)
    _, vars_, _, _ = CA.montar(None, lig, QUI)
    t = textos(vars_)
    assert "centroide (mediana)" in t and "centroide_mediana" not in t
    assert "desde 02/09/2026 (primeiro pregão após a gravação)" in t
    assert AP._data_iso("2026-03-27") == "27/03/2026"
    assert AP._data_iso("lixo") == "lixo" and AP._data_iso(None) == "—"
    assert AP._metodo("algo_novo") == "algo novo"


def test_conta_sem_login_mostra_etiqueta_ambar():
    base = {"conta_id": 1, "nome": "Demo", "tipo": "demo",
            "limite_perda_dia": None, "terminal": None}
    falta = textos(AP.linha_conta({**base, "login": None, "servidor": None}, None))
    assert "faltam os dados do MT5" in falta
    ok = textos(AP.linha_conta({**base, "login": 123, "servidor": "S"}, None))
    assert "faltam os dados do MT5" not in ok
    assert "123" in ok and "S" in ok
