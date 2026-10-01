# tests/test_ao_vivo_acoes.py
"""Os cliques da tela Ao vivo, sem navegador: `acao` chama o core e diz o
que aconteceu em português."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV, diario, plano, variantes  # noqa: E402,F401
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401
from ui.callbacks_ao_vivo import acao  # noqa: E402


def test_ligar_portfolio_pede_confirmacao(banco):
    pf = P.criar("p")
    armado, _, aviso = acao("pf-ligar", pf, {}, None, None)
    assert armado == f"pf-ligar:{pf}" and "confirm" in aviso.lower()
    assert P.listar()[0]["ligado"] is False
    armado, _, aviso = acao("pf-ligar", pf, {}, armado, None)
    assert armado is None and P.listar()[0]["ligado"] is True
    assert "ligado" in aviso


def test_desligar_e_imediato(banco):
    pf = P.criar("p")
    AV.ligar_portfolio(pf)
    armado, _, _ = acao("pf-desligar", pf, {}, None, None)
    assert armado is None and P.listar()[0]["ligado"] is False


def test_abrir_e_fechar_ficha(banco):
    assert acao("abrir", 7, {}, None, None)[1] == 7
    assert acao("abrir", 7, {}, None, 7)[1] is None


def test_criar_conta_com_limite_em_formato_brasileiro(banco):
    campos = {("conta-nome", 0): "Mesa A", ("conta-tipo", 0): "real",
              ("conta-limite", 0): "1.500,50"}
    _, _, aviso = acao("conta-criar", 0, campos, None, None)
    [c] = AV.listar_contas()
    assert c["limite_perda_dia"] == 1500.5 and "criada" in aviso


def test_limite_invalido_vira_aviso(banco):
    campos = {("conta-nome", 0): "X", ("conta-tipo", 0): "demo",
              ("conta-limite", 0): "abc"}
    _, _, aviso = acao("conta-criar", 0, campos, None, None)
    assert "limite" in aviso and AV.listar_contas() == []


def test_recusa_do_core_vira_aviso(banco):
    pf = P.criar("p")
    real = AV.criar_conta("Mesa A", "real")
    _, _, aviso = acao("pf-contas", pf, {("conta-demo", pf): real,
                                         ("conta-real", pf): None}, None, None)
    assert "a conta Mesa A não é do tipo demo" in aviso


def test_banco_ocupado_vira_aviso(banco, monkeypatch):
    pf = P.criar("p")

    def ocupado(*a, **k):
        raise RuntimeError("banco ocupado após 10s de espera: x")
    monkeypatch.setattr(AV, "desligar_portfolio", ocupado)
    _, _, aviso = acao("pf-desligar", pf, {}, None, None)
    assert aviso == "banco ocupado, tente de novo"


def test_pausar_e_ligar_variante(banco):
    pf = P.criar("p")
    v = variantes.criar("v", "rompimento_canal")
    lig = P.adicionar_variante(pf, v)
    acao("membro-desligar", lig, {}, None, None)
    assert P.membros(pf)[0]["ligada"] is False
    acao("membro-ligar", lig, {}, None, None)
    assert P.membros(pf)[0]["ligada"] is True


def test_aposentar_plano_duplo_clique(banco):
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    armado, _, _ = acao("plano-aposentar", pid, {}, None, None)
    assert plano.detalhes(pid)["estado"] == "ativo"
    _, _, aviso = acao("plano-aposentar", pid, {}, armado, None)
    assert plano.detalhes(pid)["estado"] == "aposentado"
    assert "sai de vigor" in aviso


def test_renomear_e_vincular(banco):
    v = variantes.criar("errado", "rompimento_canal")
    _, _, aviso = acao("renomear", v, {("renomear", v): "certo"}, None, None)
    assert variantes.listar()[0]["nome"] == "certo" and "renomeada" in aviso
    mineracao(50)
    wfa(18, 50)
    pid = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                       agora=datetime(2026, 9, 1, 10))
    campos = {("vincular-variante", 50): v, ("vincular-manter", 50): None}
    _, _, aviso = acao("vincular", 50, campos, "vincular:50", None)
    assert plano.detalhes(pid)["variante_id"] == v and "vinculad" in aviso


def test_numero_formatos_aceitos():
    from ui.callbacks_ao_vivo import _numero
    assert _numero("1.500") == 1500.0
    assert _numero("1.500,50") == 1500.5
    assert _numero("1500.5") == 1500.5
    assert _numero("1500") == 1500.0
    assert _numero("R$ 500,5") == 500.5
    assert _numero("  ") is None


def test_limites_ambiguos_ou_invalidos_nao_salvam(banco):
    for ruim in ["1,500.50", "nan", "inf", "-5", "0", "abc"]:
        campos = {("conta-nome", 0): "X", ("conta-tipo", 0): "demo",
                  ("conta-limite", 0): ruim}
        _, _, aviso = acao("conta-criar", 0, campos, None, None)
        assert "limite" in aviso, ruim
    assert AV.listar_contas() == []


def test_limite_exibido_volta_identico(banco):
    from ui.callbacks_ao_vivo import _numero
    from ui.components.ao_vivo_panel import limite_br, linha_conta
    for v in (1500.5, 500.0, 1234567.25, 0.5):
        assert _numero(limite_br(v)) == v
    assert limite_br(500.0) == "500" and limite_br(1500.5) == "1.500,50"
    AV.criar_conta("M", "real", 1500.5)
    [c] = AV.listar_contas()
    assert "1.500,50" in str(linha_conta(c, None))


def test_aposentar_plano_inexistente_vira_aviso(banco):
    _, _, aviso = acao("plano-aposentar", 999, {}, "plano-aposentar:999", None)
    assert aviso == "plano #999 não existe"


def test_vincular_pede_confirmacao_antes_de_mexer(banco):
    v = variantes.criar("v", "rompimento_canal")
    mineracao(50)
    wfa(18, 50)
    pid = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                       agora=datetime(2026, 9, 1, 10))
    campos = {("vincular-variante", 50): v, ("vincular-manter", 50): None}
    armado, _, aviso = acao("vincular", 50, campos, None, None)
    assert armado == "vincular:50" and "confirme" in aviso
    assert plano.detalhes(pid)["variante_id"] is None
    armado, _, aviso = acao("vincular", 50, campos, armado, None)
    assert armado is None and plano.detalhes(pid)["variante_id"] == v


def test_criar_conta_com_login_e_servidor(banco):
    campos = {("conta-nome", 0): "Demo", ("conta-tipo", 0): "demo",
              ("conta-login", 0): " 123456 ",
              ("conta-servidor", 0): "Clear-DEMO",
              ("conta-terminal", 0): "C:\\MT5\\terminal64.exe"}
    _, _, aviso = acao("conta-criar", 0, campos, None, None)
    [c] = AV.listar_contas()
    assert "criada" in aviso
    assert (c["login"], c["servidor"]) == (123456, "Clear-DEMO")
    assert c["terminal"] == "C:\\MT5\\terminal64.exe"


def test_login_com_letra_vira_aviso(banco):
    campos = {("conta-nome", 0): "X", ("conta-tipo", 0): "demo",
              ("conta-login", 0): "12a45"}
    _, _, aviso = acao("conta-criar", 0, campos, None, None)
    assert aviso == "número da conta deve ter só números"
    assert AV.listar_contas() == []


def test_salvar_conta_edita_login(banco):
    cid = AV.criar_conta("Demo", "demo", login=1, servidor="S")
    campos = {("conta-nome", cid): "Demo", ("conta-limite", cid): "",
              ("conta-login", cid): "2", ("conta-servidor", cid): "S",
              ("conta-terminal", cid): ""}
    _, _, aviso = acao("conta-salvar", cid, campos, None, None)
    assert "salva" in aviso and AV.listar_contas()[0]["login"] == 2


def test_puxar_preenche_e_sugere_nome(monkeypatch):
    from core import mt5_source
    from ui.callbacks_ao_vivo import puxar
    visto = []
    monkeypatch.setattr(mt5_source, "ler_conta", lambda t=None: (
        visto.append(t) or {"login": 77, "servidor": "S-REAL", "tipo": "real",
                            "titular": "F", "corretora": "Clear"}))
    login, serv, tipo, nome, aviso = puxar(" C:\\x.exe ", "")
    assert (login, serv, tipo, nome) == ("77", "S-REAL", "real", "Clear real 77")
    assert visto == ["C:\\x.exe"]
    assert aviso == ("lido do MT5: conta 77 (real, informado pela corretora) "
                     "— confira e clique em Criar conta")


def test_puxar_nao_sobrescreve_nome_digitado(monkeypatch):
    from dash import no_update
    from core import mt5_source
    from ui.callbacks_ao_vivo import puxar
    monkeypatch.setattr(mt5_source, "ler_conta", lambda t=None: {
        "login": 1, "servidor": "S", "tipo": "demo", "titular": "F",
        "corretora": "C"})
    assert puxar(None, "Meu nome")[3] is no_update


def test_puxar_erro_do_mt5_vira_aviso_e_nao_banco_ocupado(monkeypatch):
    from dash import no_update
    from core import mt5_source
    from ui.callbacks_ao_vivo import puxar

    def estoura(t=None):
        raise mt5_source.MT5Error("o MT5 está aberto mas não está logado")
    monkeypatch.setattr(mt5_source, "ler_conta", estoura)
    *campos, aviso = puxar(None, "")
    assert all(c is no_update for c in campos)
    assert aviso == "o MT5 está aberto mas não está logado"
