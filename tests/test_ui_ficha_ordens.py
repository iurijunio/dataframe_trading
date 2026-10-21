"""Ficha da variante e conta do portfólio com as ordens (parte 4, tarefa 16).

Os cliques mexem em fase, contratos, limite e Envio — dinheiro de verdade
mais adiante —, então cada recusa e cada sucesso tem o seu teste, contra o
banco isolado (`banco`), e o arquivo de comando vai para a pasta de teste."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import comandos  # noqa: E402
from core import portfolio as P  # noqa: E402
from core import db_manager as db  # noqa: E402
from core.engine.execution import ExecutionProfile  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401
from tests.fabrica_ao_vivo import ligacao_com_plano  # noqa: E402
from ui import callbacks_ao_vivo as CA  # noqa: E402
from ui.components import ao_vivo_panel as AP  # noqa: E402

PARAMS = {"periodo_canal": 20, "folga_ticks": 0, "filtro_amplitude": 0}


def textos(c) -> str:
    """Todo o texto de uma árvore de componentes."""
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(textos(x) for x in c)
    return textos(getattr(c, "children", None))


def _montar(*, stop_pontos=300, limite=500.0, com_conta=True):
    perfil = ExecutionProfile(timeframe="M5", stop_tipo="pontos",
                              stop_pontos=stop_pontos).to_config()
    f = ligacao_com_plano("v", params=PARAMS, profile=perfil, contratos=3)
    conta = None
    if com_conta:
        conta = AV.criar_conta("demo-v", "demo", limite)
        AV.definir_contas(f.pf, conta, None)
    return f, conta


def _fase(lig):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT fase FROM portfolio_membros WHERE "
                           "ligacao_id = ?", [lig]).fetchone()[0]


def _contratos_demo(lig):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT contratos_demo FROM portfolio_membros "
                           "WHERE ligacao_id = ?", [lig]).fetchone()[0]


def _envio(conta):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT coalesce(envio_ligado, false) FROM contas "
                           "WHERE conta_id = ?", [conta]).fetchone()[0]


def _limite(conta):
    return next(c["limite_perda_dia"] for c in AV.listar_contas()
                if c["conta_id"] == conta)


# ----------------------------------------------------------------- promover
def test_promover_arma_no_primeiro_clique_e_muda_no_segundo(banco):
    f, _ = _montar()
    armado, _, aviso = CA.acao("fase-demo", f.lig, {}, None, None)
    assert armado == f"fase-demo:{f.lig}" and "confirme" in aviso
    assert _fase(f.lig) == "papel"
    armado, _, aviso = CA.acao("fase-demo", f.lig, {}, armado, None)
    assert armado is None and _fase(f.lig) == "demo"
    assert "demo" in aviso


def test_promover_recusado_mostra_a_frase_do_core(banco):
    f, _ = _montar(com_conta=False)
    armado, _, _ = CA.acao("fase-demo", f.lig, {}, None, None)
    armado, _, aviso = CA.acao("fase-demo", f.lig, {}, armado, None)
    assert armado is None and _fase(f.lig) == "papel"
    assert aviso == ("escolha uma conta demo (não arquivada) para o "
                     "portfólio antes de promover")


def test_voltar_para_papel_avisa_que_encerra_a_posicao(banco):
    f, _ = _montar()
    AV.mudar_fase(f.lig, "demo")
    armado, _, aviso = CA.acao("fase-papel", f.lig, {}, None, None)
    assert armado == f"fase-papel:{f.lig}"
    assert "isso encerra a posição aberta, se houver" in aviso
    assert _fase(f.lig) == "demo"
    armado, _, aviso = CA.acao("fase-papel", f.lig, {}, armado, None)
    assert armado is None and _fase(f.lig) == "papel"


def test_confirmacao_vencida_so_rearma(banco):
    f, _ = _montar()
    chave = f"fase-demo:{f.lig}"
    armado, _, _ = CA.acao("fase-demo", f.lig, {}, chave, None,
                           armado_em=100.0, agora_s=107.0)
    assert armado == chave and _fase(f.lig) == "papel"      # só rearmou
    armado, _, _ = CA.acao("fase-demo", f.lig, {}, chave, None,
                           armado_em=100.0, agora_s=105.0)
    assert armado is None and _fase(f.lig) == "demo"        # ainda valia


def test_banco_ocupado_na_fase_nao_congela(banco, monkeypatch):
    f, _ = _montar()

    vistos = []

    def ocupado(*a, **k):
        vistos.append(k)
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(AV, "mudar_fase", ocupado)
    armado, _, aviso = CA.acao("fase-demo", f.lig, {}, f"fase-demo:{f.lig}",
                               None)
    assert armado is None and "banco ocupado" in aviso
    # espera pouco pelo banco: a tela não congela 10 s
    assert vistos == [{"tentativas": CA.TENTATIVAS_BANCO}]


# ----------------------------------------------------------------- contratos
def test_contratos_salva_vazio_e_recusa(banco):
    f, _ = _montar()
    chave = ("contratos", f.lig)
    _, _, aviso = CA.acao("contratos-salvar", f.lig, {chave: "2"}, None, None)
    assert _contratos_demo(f.lig) == 2 and "gravados" in aviso
    _, _, aviso = CA.acao("contratos-salvar", f.lig, {chave: ""}, None, None)
    assert _contratos_demo(f.lig) is None and "plano" in aviso
    _, _, aviso = CA.acao("contratos-salvar", f.lig, {chave: "1,5"}, None, None)
    assert "número inteiro" in aviso and _contratos_demo(f.lig) is None


def test_contratos_com_banco_ocupado(banco, monkeypatch):
    f, _ = _montar()

    def ocupado(*a, **k):
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(AV, "definir_contratos", ocupado)
    _, _, aviso = CA.acao("contratos-salvar", f.lig, {("contratos", f.lig): "2"},
                          None, None)
    assert aviso == "banco ocupado, tente de novo"


def test_custo_do_stop_usa_o_texto_do_editor_da_operacao(banco):
    f, _ = _montar()                    # 300 pontos x R$ 0,20 x 2 = R$ 120
    saida = CA.custo_ficha(f.lig, "2")
    assert "R$ 120" in textos(saida) and "24%" in textos(saida)
    assert "inteiro" in textos(CA.custo_ficha(f.lig, "abc"))


# -------------------------------------------------------------------- limite
def test_limite_salva_em_reais_e_recusa_o_invalido(banco):
    f, conta = _montar(limite=500.0)
    _, _, aviso = CA.acao("pf-limite", f.pf, {("pf-limite", f.pf): "1.500,50"},
                          None, None)
    assert _limite(conta) == 1500.5 and "limite" in aviso
    for ruim in ("abc", "0", "-5", "1,500.50"):
        _, _, aviso = CA.acao("pf-limite", f.pf, {("pf-limite", f.pf): ruim},
                              None, None)
        assert "limite" in aviso
        assert _limite(conta) == 1500.5


def test_limite_sem_conta_demo_diz_o_que_fazer(banco):
    f, _ = _montar(com_conta=False)
    _, _, aviso = CA.acao("pf-limite", f.pf, {("pf-limite", f.pf): "500"},
                          None, None)
    assert "conta demo" in aviso


# --------------------------------------------------------------------- envio
def test_ligar_envio_sem_limite_nao_arma_e_manda_cadastrar(banco):
    f, conta = _montar(limite=None)
    alvo = f"{f.pf}:{conta}"
    armado, _, aviso = CA.acao("envio-ligar", alvo, {}, None, None)
    assert armado is None and "cadastre o limite antes" in aviso
    assert _envio(conta) is False


def test_ligar_envio_dois_cliques(banco):
    f, conta = _montar()
    alvo = f"{f.pf}:{conta}"
    armado, _, aviso = CA.acao("envio-ligar", alvo, {}, None, None)
    assert armado == f"envio-ligar:{alvo}" and "confirme" in aviso
    assert _envio(conta) is False
    armado, _, aviso = CA.acao("envio-ligar", alvo, {}, armado, None)
    assert armado is None and _envio(conta) is True and "ligado" in aviso


def test_ligar_envio_real_dois_cliques_e_comando_na_pasta_real(banco):
    f, demo = _montar()
    real = AV.criar_conta("real-v", "real", 500.0)
    AV.definir_contas(f.pf, demo, real)
    alvo = f"{f.pf}:{real}"
    armado, _, aviso = CA.acao("envio-real-ligar", alvo, {}, None, None)
    assert armado == f"envio-real-ligar:{alvo}" and "confirme" in aviso
    assert _envio(real) is False
    armado, _, aviso = CA.acao("envio-real-ligar", alvo, {}, armado, None)
    assert armado is None and _envio(real) is True and "ligado" in aviso
    assert not list(Path(comandos.PASTA).glob("*.json"))
    cmds = [json.loads(a.read_text(encoding="utf-8"))
            for a in Path(comandos.PASTA_REAL).glob("*.json")]
    assert [(c["conta_id"], c["ligado"]) for c in cmds] == [(real, True)]


def test_ligar_envio_real_sem_limite_nao_arma(banco):
    f, demo = _montar()
    real = AV.criar_conta("real-v", "real")
    AV.definir_contas(f.pf, demo, real)
    alvo = f"{f.pf}:{real}"
    armado, _, aviso = CA.acao("envio-real-ligar", alvo, {}, None, None)
    assert armado is None and "cadastre o limite antes" in aviso
    assert _envio(real) is False


def test_chave_do_envio_real_e_clicavel(banco):
    f, demo = _montar()
    real = AV.criar_conta("real-v", "real", 500.0)
    AV.definir_contas(f.pf, demo, real)
    botao = AP._envio_real(f.pf, {"conta_id": real, "envio_ligado": False}, None)
    assert not getattr(botao, "disabled", None)
    assert botao.id == {"type": "av-acao", "acao": "envio-real-ligar",
                        "id": f"{f.pf}:{real}"}
    botao = AP._envio_real(f.pf, {"conta_id": real, "envio_ligado": True}, None)
    assert botao.id["acao"] == "envio-real-desligar"


def test_ligar_envio_sem_conta_demo(banco):
    f, _ = _montar(com_conta=False)
    alvo = f"{f.pf}:1"
    armado, _, aviso = CA.acao("envio-ligar", alvo, {}, None, None)
    assert armado is None and "conta demo" in aviso


@pytest.mark.parametrize("n, trecho", [
    (2, "isso encerra 2 posições"), (1, "isso encerra 1 posição"),
    (0, "nenhuma posição aberta")])
def test_desligar_envio_conta_as_posicoes_abertas(banco, n, trecho):
    f, conta = _montar()
    alvo = f"{f.pf}:{conta}"
    AV.ligar_envio(conta, True)
    armado, _, aviso = CA.acao("envio-desligar", alvo, {}, None, None,
                               posicoes=n)
    assert armado == f"envio-desligar:{alvo}" and trecho in aviso
    assert _envio(conta) is True                       # só armou
    armado, _, _ = CA.acao("envio-desligar", alvo, {}, armado, None,
                           posicoes=n)
    assert armado is None and _envio(conta) is False


def test_desligar_envio_escreve_o_comando(banco):
    f, conta = _montar()
    alvo = f"{f.pf}:{conta}"
    AV.ligar_envio(conta, True)
    chave = f"envio-desligar:{alvo}"
    pasta = Path(comandos.PASTA)
    antes = set(pasta.glob("*.json")) if pasta.exists() else set()
    CA.acao("envio-desligar", alvo, {}, chave, None, posicoes=0)
    novos = set(pasta.glob("*.json")) - antes     # só o que ESTA chamada escreveu
    assert any('"ligado": false' in a.read_text(encoding="utf-8")
               for a in novos)


def _banco_ocupado(monkeypatch):
    def ocupado(*a, **k):
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect", ocupado)
    monkeypatch.setattr(db, "connect_write", ocupado)


def test_desligar_envio_com_banco_ocupado_ainda_escreve_o_comando(
        banco, monkeypatch):
    f, conta = _montar()
    AV.ligar_envio(conta, True)
    alvo = f"{f.pf}:{conta}"
    pasta = Path(comandos.PASTA)
    antes = set(pasta.glob("*.json"))
    _banco_ocupado(monkeypatch)             # nem leitura nem escrita
    armado, _, aviso = CA.acao("envio-desligar", alvo, {},
                               f"envio-desligar:{alvo}", None, posicoes=1)
    novos = set(pasta.glob("*.json")) - antes
    assert any('"ligado": false' in a.read_text(encoding="utf-8")
               for a in novos)
    assert armado is None and "comando enviado" in aviso


def test_limite_vazio_com_envio_ligado_e_recusado(banco):
    f, conta = _montar()
    AV.ligar_envio(conta, True)
    pasta = Path(comandos.PASTA)
    antes = set(pasta.glob("*.json"))
    for vazio in ("", None, "  "):
        _, _, aviso = CA.acao("pf-limite", f.pf, {("pf-limite", f.pf): vazio},
                              None, None)
        assert aviso == "para tirar o limite, desligue o envio de ordens antes"
    assert _envio(conta) is True and _limite(conta) == 500.0
    assert set(pasta.glob("*.json")) == antes       # nenhum "desligar"


def test_limite_vazio_com_envio_desligado_tira_o_limite(banco):
    f, conta = _montar()
    CA.acao("pf-limite", f.pf, {("pf-limite", f.pf): ""}, None, None)
    assert _limite(conta) is None


def test_pf_ligar_ainda_executa_no_segundo_clique_dentro_de_6s(banco):
    pf = P.criar("p")
    chave = f"pf-ligar:{pf}"
    armado, _, _ = CA.acao("pf-ligar", pf, {}, None, None)
    assert armado == chave
    armado, _, aviso = CA.acao("pf-ligar", pf, {}, chave, None,
                               armado_em=100.0, agora_s=105.5)
    assert armado is None and P.listar()[0]["ligado"] is True
    # vencido: só rearma
    P.listar()
    armado, _, _ = CA.acao("pf-ligar", pf, {}, chave, None,
                           armado_em=100.0, agora_s=107.0)
    assert armado == chave


def test_ordens_da_ficha_espera_pouco_pelo_banco(banco, monkeypatch):
    f, _ = _montar()
    vistos = []
    real = AV.restricoes_para_demo

    def espia(lig, **k):
        vistos.append(k)
        return real(lig, **k)
    monkeypatch.setattr(AV, "restricoes_para_demo", espia)
    assert CA.ordens_da_ficha(f.lig) is not None
    assert vistos == [{"tentativas": CA.TENTATIVAS_BANCO}]
    _banco_ocupado(monkeypatch)
    assert CA.ordens_da_ficha(f.lig) is None        # a ficha avisa e desenha


# ---------------------------------------------------------------------- leitura
def test_ordens_da_ficha_traz_fase_contratos_selo_e_restricoes(banco):
    f, _ = _montar(com_conta=False)
    AV.definir_contratos(f.lig, 2)
    o = CA.ordens_da_ficha(f.lig)
    assert o["contratos_demo"] == 2
    assert o["situacao"]["ok"] is None
    assert any("conta demo" in m for m in o["restricoes"]["motivos"])


def test_ordens_da_ficha_com_banco_ocupado_vira_none(banco, monkeypatch):
    def ocupado(*a, **k):
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(AV, "restricoes_para_demo", ocupado)
    assert CA.ordens_da_ficha(1) is None


# ----------------------------------------------------------------------- telas
@pytest.mark.parametrize("sit, trecho", [
    ({"pregoes": 12, "diferencas": 0, "ok": True}, "✓ 12 pregões"),
    ({"pregoes": 1, "diferencas": 0, "ok": True}, "✓ 1 pregão"),
    ({"pregoes": 3, "diferencas": 2, "ok": False},
     "2 diferenças — não pode subir para a demo"),
    ({"pregoes": 3, "diferencas": 1, "ok": False},
     "1 diferença — não pode subir para a demo"),
    ({"pregoes": 0, "diferencas": 0, "ok": None}, "ainda sem pregão conferido"),
])
def test_selo_papel_backtest(sit, trecho):
    assert trecho in textos(AP.selo_papel_backtest(sit))


def _ficha(fase, **mudar):
    ordens = {"contratos_demo": None, "contratos_plano": 3,
              "situacao": {"pregoes": 4, "diferencas": 0, "ok": True},
              "restricoes": {"motivos": [], "avisos": []}}
    ordens.update(mudar)
    return AP.bloco_ordens_ficha({"ligacao_id": 9, "fase": fase}, ordens, None)


def _ids(c, achados=None):
    achados = [] if achados is None else achados
    i = getattr(c, "id", None)
    if i is not None:
        achados.append(i)
    f = getattr(c, "children", None)
    for x in (f if isinstance(f, (list, tuple)) else [f]):
        if x is not None and not isinstance(x, (str, int, float)):
            _ids(x, achados)
    return achados


def test_ficha_em_papel_oferece_promover():
    t = textos(_ficha("papel"))
    assert "Promover para demo" in t and "Voltar para papel" not in t
    assert "✓ 4 pregões" in t


def test_ficha_em_demo_oferece_voltar():
    t = textos(_ficha("demo"))
    assert "Voltar para papel" in t and "Promover para demo" not in t


def test_ficha_lista_os_motivos_da_recusa():
    t = textos(_ficha("papel", restricoes={
        "motivos": ["a variante não tem plano em vigor"], "avisos": ["cuidado"]}))
    assert "a variante não tem plano em vigor" in t and "cuidado" in t


def test_ficha_sem_leitura_avisa_em_vez_de_quebrar():
    bloco = AP.bloco_ordens_ficha({"ligacao_id": 9, "fase": "papel"}, None, None)
    assert "banco ocupado" in textos(bloco)


def test_ficha_nao_repete_ids_da_tela_operacao():
    ids = [str(i) for i in _ids(_ficha("papel"))]
    assert not any("av-op-ord-ctr" in i for i in ids)


def test_cartao_do_portfolio_mostra_limite_e_envio():
    p = {"portfolio_id": 5, "nome": "pf", "ligado": True, "n_membros": 1,
         "conta_demo_id": 2, "conta_real_id": None}
    conta = {"conta_id": 2, "nome": "demo", "tipo": "demo",
             "limite_perda_dia": 500.0, "arquivada_em": None,
             "envio_ligado": False}
    t = textos(AP.cartao_portfolio(p, [conta], None, 1))
    assert "Limite de perda do dia" in t and "Envio de ordens" in t
    # a chave não tem texto: o que diz ligar/desligar é o id da ação
    assert "envio-ligar" in repr(AP.cartao_portfolio(p, [conta], None, 1))
    conta["envio_ligado"] = True
    arvore = AP.cartao_portfolio(p, [conta], None, 1)
    assert "envio-desligar" in repr(arvore) and "op-tg-on" in repr(arvore)


def test_cartao_do_portfolio_sem_conta_demo_explica():
    p = {"portfolio_id": 5, "nome": "pf", "ligado": True, "n_membros": 1,
         "conta_demo_id": None, "conta_real_id": None}
    # a explicação está no (?) (atributo data-dica), não no texto visível
    assert "escolha a conta demo" in repr(AP.cartao_portfolio(p, [], None, 1)).lower()


# ------------------------------------------------------ o callback de verdade
def test_previa_do_custo_pelo_despacho_do_dash(banco):
    """O callback de padrão (ALL) roda pelo despachante do Dash, com o corpo
    que o navegador manda: confere a ligação dos ids, não só a função."""
    from ui.app import build
    f, _ = _montar()
    with db.connect_write() as con:     # o layout lê o intervalo do gráfico
        con.execute("INSERT OR IGNORE INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00'"
                f" + INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")
    app = build()
    chave = next(k for k in app.callback_map if "av-ficha-custo" in k)
    ident = {"type": "av-ficha-custo", "id": f.lig}
    campo = {"type": "av-campo", "campo": "contratos", "id": f.lig}
    corpo = {"output": chave,
             "outputs": [{"id": ident, "property": "children"}],
             "inputs": [[{"id": campo, "property": "value", "value": "2"}]],
             "changedPropIds": []}
    r = app.server.test_client().post("/_dash-update-component", json=corpo)
    assert r.status_code == 200, r.get_data(as_text=True)
    resposta = r.get_json()["response"]
    assert "R$ 120" in str(resposta)


def test_clique_pelo_despacho_arma_com_a_hora_e_o_segundo_executa(banco):
    """`agir` inteiro: o primeiro clique guarda a chave e a hora (`av-armado-em`),
    o segundo, dentro dos 6 s, promove."""
    import json as _j
    import time
    from ui.app import build
    f, _ = _montar()
    with db.connect_write() as con:
        con.execute("INSERT OR IGNORE INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00'"
                f" + INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")
    app = build()
    chave = next(k for k in app.callback_map if "av-armado-em.data" in k)
    botao = {"type": "av-acao", "acao": "fase-demo", "id": f.lig}
    id_str = _j.dumps(botao, sort_keys=True, separators=(",", ":"))

    def clicar(armado, armado_em):
        estados = [[]] + [
            {"id": i, "property": "value", "value": None}
            for i in ("av-conta-nome", "av-conta-tipo", "av-conta-limite",
                      "av-conta-login", "av-conta-servidor",
                      "av-conta-terminal")] + [
            {"id": "av-versao", "property": "data", "value": 0},
            {"id": "av-armado", "property": "data", "value": armado},
            {"id": "av-aberta", "property": "data", "value": None},
            {"id": "av-armado-em", "property": "data", "value": armado_em}]
        corpo = {"output": chave,
                 "outputs": [{"id": o, "property": p} for o, p in (
                     ("av-versao", "data"), ("av-armado", "data"),
                     ("av-aberta", "data"), ("av-aviso", "children"),
                     ("av-armado-em", "data"))],
                 "inputs": [[{"id": botao, "property": "n_clicks", "value": 1}],
                            {"id": "av-btn-conta-criar", "property": "n_clicks",
                             "value": 0}],
                 "state": estados,
                 "changedPropIds": [f"{id_str}.n_clicks"]}
        r = app.server.test_client().post("/_dash-update-component", json=corpo)
        assert r.status_code == 200, r.get_data(as_text=True)
        resp = r.get_json()["response"]
        return {k: v["data"] if "data" in v else v["children"]
                for k, v in resp.items()}

    r1 = clicar(None, None)
    assert r1["av-armado"] == f"fase-demo:{f.lig}"
    assert abs(r1["av-armado-em"] - time.time()) < 5
    assert _fase(f.lig) == "papel"
    r2 = clicar(r1["av-armado"], r1["av-armado-em"])
    assert r2["av-armado"] is None and r2["av-armado-em"] is None
    assert _fase(f.lig) == "demo"
