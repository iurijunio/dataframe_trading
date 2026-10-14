"""Topo da parte 4: selo das ordens, "Zerar tudo e desligar envio" e alarme.

Spec: docs/superpowers/specs/2026-10-08-ao-vivo-ordens-design.md §5.8 e §8.
O estado é montado à mão no formato que `core.ordens.Motor.passo` (e o
`captura.py`, nos caminhos parados) publica em `estado.json["ordens"]`.
Nenhum teste escreve na pasta de comandos real: o conftest a desvia.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import comandos  # noqa: E402
from core import db_manager as db  # noqa: E402
from ui import callbacks_ordens as CO  # noqa: E402
from ui import data as D  # noqa: E402

AGORA = datetime(2026, 10, 14, 10, 30, 0)


def _ordens(**mudar):
    """Uma volta normal do passo: conta 1 logada, Envio ligado, uma demo."""
    o = {
        "falhou": False, "foto": "ok", "vivo_em": AGORA.isoformat(),
        "contrato": "WINZ26",
        "conta": {"conta_id": 1, "login": 123, "servidor": "Clear-Demo",
                  "confere": True, "hedging": True, "algo": True,
                  "margem_livre": 5000.0},
        "envio": True, "zerar": False, "travada": None,
        "perda": {"total": 0.0}, "limite": 500.0,
        "ligacoes": {"7": {"desejado": "posicao", "papel": "posicao",
                           "motivo": None, "posicoes": [
                               {"ticket": 11, "volume": 1.0},
                               {"ticket": 12, "volume": 2.0}]}},
        "comandos": [], "posicao_fora": [], "ordens_em": None, "chamados": [],
        "n_demo": 1,
    }
    o.update(mudar)
    return o


def _estado(ordens=None, idade_s=2, **mudar):
    e = {"atualizado_em": (AGORA - timedelta(seconds=idade_s)).isoformat(),
         "ordens": ordens}
    e.update(mudar)
    return e


# ------------------------------------------------------------ selo
def test_envio_ligado_e_demo_operando_e_enviando():
    r = D.ordens_do_estado(_estado(_ordens()), AGORA)
    assert r["selo"] == "enviando"
    assert "enviando" in r["texto"].lower()
    assert r["alarme"] is False
    assert r["chamados"] == []


def test_envio_desligado():
    r = D.ordens_do_estado(_estado(_ordens(envio=False)), AGORA)
    assert r["selo"] == "desligado"
    assert "envio desligado" in r["texto"].lower()
    assert r["alarme"] is False


def test_zerar_em_curso_mostra_desligado_zerando():
    r = D.ordens_do_estado(_estado(_ordens(envio=False, zerar=True)), AGORA)
    assert r["selo"] == "desligado"
    assert "zerando" in r["texto"].lower()


def test_conta_travada_vence_e_liga_o_alarme():
    trava = {"desde": AGORA.isoformat(), "perda": 460.0, "limite": 500.0}
    r = D.ordens_do_estado(_estado(_ordens(envio=False, travada=trava)), AGORA)
    assert r["selo"] == "travada"
    assert "travada" in r["texto"].lower()
    assert r["alarme"] is True
    # a trava tem chave própria: o bipe toca uma vez quando ela chega
    assert "travada" in r["chaves"]


def test_estado_velho_e_sem_captura():
    r = D.ordens_do_estado(_estado(_ordens(), idade_s=300), AGORA)
    assert r["selo"] == "sem_captura"
    assert r["alarme"] is False


def test_sem_estado_e_sem_captura():
    assert D.ordens_do_estado(None, AGORA)["selo"] == "sem_captura"


def test_captura_sem_bloco_de_ordens_nao_e_sem_demo():
    """Sem bloco não se sabe se há demo: "Sem demo" seria afirmar demais."""
    r = D.ordens_do_estado(_estado(None), AGORA)
    assert r["selo"] != "sem_demo" and r["selo"] != "enviando"


def test_mt5_em_conta_nao_cadastrada_mostra_a_conta():
    conta = {"conta_id": None, "login": 999, "servidor": "X", "confere": False}
    r = D.ordens_do_estado(_estado(_ordens(conta=conta, envio=False)), AGORA)
    assert r["selo"] == "desligado" and "999" in r["texto"]


def test_nenhuma_ligacao_na_demo_e_sem_demo():
    r = D.ordens_do_estado(_estado(_ordens(n_demo=0, envio=False)), AGORA)
    assert r["selo"] == "sem_demo"
    assert not r["texto"].startswith("Demo")


def test_desejados_indisponiveis_com_demo_nao_e_sem_demo():
    """Papel indisponível: `ligacoes` vem vazio, mas o retrato tem demo."""
    r = D.ordens_do_estado(_estado(_ordens(ligacoes={}, n_demo=2)), AGORA)
    assert r["selo"] == "enviando"


def test_n_demo_desconhecido_cai_nas_outras_regras():
    o = _ordens(ligacoes={}, envio=False)
    del o["n_demo"]
    assert D.ordens_do_estado(_estado(o), AGORA)["selo"] == "desligado"
    o["n_demo"] = None
    assert D.ordens_do_estado(_estado(o), AGORA)["selo"] == "desligado"


def _parado(**mudar):
    p = {"foto": None, "parado": "fora do pregão", "vivo_em": AGORA.isoformat(),
         "chamados": [], "n_demo": 1, "envio": None, "travada": None}
    p.update(mudar)
    return p


def test_fora_do_pregao_parado_nao_e_enviando():
    r = D.ordens_do_estado(_estado(_parado()), AGORA)
    assert r["selo"] == "desligado"
    assert "fora do pregão" in r["texto"]


def test_fora_do_pregao_mostra_o_interruptor_do_envio():
    r = D.ordens_do_estado(_estado(_parado(envio=True)), AGORA)
    assert r["texto"] == "Demo · fora do pregão · envio ligado"
    r = D.ordens_do_estado(_estado(_parado(envio=False)), AGORA)
    assert r["texto"] == "Demo · fora do pregão · envio desligado"


def test_fora_do_pregao_com_conta_travada():
    trava = {"desde": AGORA.isoformat(), "perda": 460.0, "limite": 500.0}
    r = D.ordens_do_estado(_estado(_parado(travada=trava, envio=True)), AGORA)
    assert r["selo"] == "travada" and r["alarme"] is True


def test_fora_do_pregao_sem_demo_sem_prefixo():
    r = D.ordens_do_estado(_estado(_parado(n_demo=0, envio=True)), AGORA)
    assert r["selo"] == "sem_demo" and not r["texto"].startswith("Demo")


def test_chamado_aberto_liga_o_alarme_e_vai_na_lista():
    ch = [{"tipo": "saida_pendente", "texto": "saída pendente há 2 min",
           "chave": "saida:11", "desde": AGORA.isoformat()}]
    r = D.ordens_do_estado(_estado(_ordens(chamados=ch)), AGORA)
    assert r["selo"] == "enviando"
    assert r["alarme"] is True
    assert r["chamados"] == ch
    assert "saida:11" in r["chaves"]


def test_chamado_que_reabre_e_chave_nova():
    """O bipe toca uma vez por chamado NOVO: o mesmo chamado reaberto mais
    tarde precisa de outra chave, senão o JS acharia que já o viu."""
    def chaves(desde):
        ch = [{"texto": "x", "chave": "papel_parado", "desde": desde}]
        return D.ordens_do_estado(_estado(_ordens(chamados=ch)), AGORA)["chaves"]
    assert chaves("2026-10-14T10:00:00") != chaves("2026-10-14T10:20:00")


def test_erro_no_caminho_das_ordens_liga_o_alarme():
    r = D.ordens_do_estado(_estado({"erro": "boom", "vivo_em": AGORA.isoformat()}),
                           AGORA)
    assert r["alarme"] is True
    assert r["selo"] != "enviando"


def test_o_mesmo_erro_repetido_bipa_uma_vez():
    """A cada volta o `vivo_em` muda; a chave não pode mudar junto."""
    def chaves(vivo, erro="boom"):
        return D.ordens_do_estado(_estado({"erro": erro, "vivo_em": vivo}),
                                  AGORA)["chaves"]
    assert chaves("2026-10-14T10:29:58") == chaves("2026-10-14T10:29:59")
    assert chaves("x", "boom") != chaves("x", "outro erro")


def test_alarme_desligado_sem_captura_mesmo_com_chamado_velho():
    ch = [{"texto": "x", "chave": "a", "desde": "2026-10-14T09:00:00"}]
    r = D.ordens_do_estado(_estado(_ordens(chamados=ch), idade_s=600), AGORA)
    assert r["alarme"] is False


def test_posicoes_da_automacao_contadas():
    assert D.ordens_do_estado(_estado(_ordens()), AGORA)["posicoes"] == 2
    assert D.ordens_do_estado(None, AGORA)["posicoes"] is None


# ------------------------------------------------------------ zerar tudo
@pytest.fixture
def contas_falsas(monkeypatch):
    chamadas = []

    def ligar_envio(cid, ligado, **k):
        # o comando "zerar_tudo" já tem de estar na pasta quando o banco é
        # tocado: banco ocupado não pode atrasar o zerar
        tipos = [json.loads(p.read_text(encoding="utf-8"))["tipo"]
                 for p in Path(comandos.PASTA).glob("*.json")]
        chamadas.append((cid, ligado, "zerar_tudo" in tipos))

    monkeypatch.setattr(AV, "ligar_envio", ligar_envio)
    monkeypatch.setattr(CO, "_contas_ativas", lambda: [1, 2])
    return chamadas


def _comandos():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(Path(comandos.PASTA).glob("*.json"))]


def test_primeiro_clique_so_arma(contas_falsas):
    armado, rotulo, aviso = CO.zerar(None, _estado(_ordens()), AGORA, agora_s=100.0)
    assert armado == 100.0
    assert "Confirmar" in rotulo and "2 posições" in rotulo
    assert _comandos() == []
    assert contas_falsas == []


def test_primeiro_clique_com_uma_posicao_no_singular(contas_falsas):
    ligs = {"7": {"motivo": None, "posicoes": [{"ticket": 1}]}}
    _, rotulo, _ = CO.zerar(None, _estado(_ordens(ligacoes=ligs)), AGORA,
                            agora_s=100.0)
    assert "1 posição" in rotulo and "posições" not in rotulo


def test_segundo_clique_escreve_o_comando_e_desliga_cada_conta(contas_falsas):
    armado, rotulo, aviso = CO.zerar(98.0, _estado(_ordens()), AGORA, agora_s=100.0)
    assert armado is None
    assert rotulo == CO.ROTULO
    assert [c["tipo"] for c in _comandos()] == ["zerar_tudo"]
    assert contas_falsas == [(1, False, True), (2, False, True)]
    assert "zer" in aviso.lower()


def test_banco_ocupado_avisa_que_o_comando_ja_vale(monkeypatch, contas_falsas):
    def ocupado(cid, ligado, **k):
        contas_falsas.append((cid, ligado))
        if cid == 1:
            raise RuntimeError("banco ocupado")
    monkeypatch.setattr(AV, "ligar_envio", ocupado)
    _, _, aviso = CO.zerar(98.0, _estado(_ordens()), AGORA, agora_s=100.0)
    # a segunda conta é tentada mesmo com a primeira falhando
    assert contas_falsas == [(1, False), (2, False)]
    assert "o comando já vale pela captura" in aviso
    assert [c["tipo"] for c in _comandos()] == ["zerar_tudo"]


def test_lista_de_contas_ilegivel_tambem_avisa(monkeypatch, contas_falsas):
    def ocupado():
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(CO, "_contas_ativas", ocupado)
    _, _, aviso = CO.zerar(98.0, _estado(_ordens()), AGORA, agora_s=100.0)
    assert "o comando já vale pela captura" in aviso
    assert [c["tipo"] for c in _comandos()] == ["zerar_tudo"]


def test_captura_fora_do_ar_diz_que_o_comando_espera(contas_falsas):
    _, _, aviso = CO.zerar(98.0, _estado(_ordens(), idade_s=600), AGORA, agora_s=100.0)
    assert "esperando a captura" in aviso
    assert "stop e alvo seguem na corretora" in aviso


def test_confirmacao_vencida_so_rearma(contas_falsas):
    """O servidor confere a idade do armado: o desarme de 5 s do navegador
    pode não rodar, e um clique minutos depois não pode zerar."""
    armado, rotulo, _ = CO.zerar(90.0, _estado(_ordens()), AGORA, agora_s=100.0)
    assert armado == 100.0 and "Confirmar" in rotulo
    assert _comandos() == [] and contas_falsas == []


def _banco_que_espera(monkeypatch):
    """Banco ocupado de verdade no tempo: cada tentativa dorme a espera e
    nenhuma consegue — quem usar o padrão (40-60 tentativas) leva 10-15 s."""
    import time as _t

    def ocupado(*a, tentativas=40, espera=0.25, **k):
        _t.sleep(tentativas * espera)
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect_write", ocupado)
    monkeypatch.setattr(db, "connect", ocupado)


def test_banco_ocupado_nao_congela_a_tela(monkeypatch):
    import time as _t
    monkeypatch.setattr(CO, "_contas_ativas", lambda: [1, 2])
    _banco_que_espera(monkeypatch)
    t0 = _t.monotonic()
    _, _, aviso = CO.zerar(98.0, _estado(_ordens()), AGORA, agora_s=100.0)
    assert _t.monotonic() - t0 < 2
    assert "o comando já vale pela captura" in aviso
    tipos = [c["tipo"] for c in _comandos()]
    assert tipos[0] == "zerar_tudo"


def test_lista_de_contas_com_banco_ocupado_nao_congela(monkeypatch):
    import time as _t
    _banco_que_espera(monkeypatch)
    t0 = _t.monotonic()
    _, _, aviso = CO.zerar(98.0, _estado(_ordens()), AGORA, agora_s=100.0)
    assert _t.monotonic() - t0 < 2
    assert "o comando já vale pela captura" in aviso
    assert [c["tipo"] for c in _comandos()] == ["zerar_tudo"]


def test_contas_ativas_ignora_arquivada():
    with db.connect_write() as con:
        db.init_schema(con)
    a = AV.criar_conta("demo A", "demo")
    b = AV.criar_conta("demo B", "demo")
    AV.arquivar_conta(b)
    assert CO._contas_ativas() == [a]


def test_segundo_clique_de_verdade_desliga_no_banco():
    """Sem monkeypatch no `ligar_envio`: a conta ligada sai desligada."""
    with db.connect_write() as con:
        db.init_schema(con)
    cid = AV.criar_conta("demo A", "demo", 500.0)
    AV.ligar_envio(cid, True)
    for p in Path(comandos.PASTA).glob("*.json"):
        p.unlink()
    CO.zerar(98.0, _estado(_ordens()), AGORA, agora_s=100.0)
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT envio_ligado FROM contas WHERE conta_id = ?",
                           [cid]).fetchone()[0] is False
    tipos = [c["tipo"] for c in _comandos()]
    # o zerar vai primeiro; o "envio desligado" de cada conta vem depois
    assert tipos[0] == "zerar_tudo" and "envio" in tipos


# ------------------------------------------------------------ desenho
def test_selo_do_topo_tem_classe_por_situacao():
    filhos, classe, titulo = CO.selo(D.ordens_do_estado(_estado(_ordens()), AGORA))
    assert "ord-selo-enviando" in classe
    assert "enviando" in str(filhos).lower()
    ch = [{"texto": "saída pendente há 2 min", "chave": "s", "desde": "x"}]
    _, _, titulo = CO.selo(D.ordens_do_estado(_estado(_ordens(chamados=ch)), AGORA))
    assert "saída pendente há 2 min" in titulo


def test_alarme_js_existe_e_le_os_atributos():
    js = (Path(__file__).resolve().parent.parent / "ui" / "assets" / "alarme.js"
          ).read_text(encoding="utf-8")
    assert "data-alarme" in js and "data-chaves" in js and "ord-alarme" in js


def test_layout_tem_selo_botao_e_alarme_na_raiz():
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) VALUES ('WIN$N', 't')")
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00',"
                    " 100, 101, 99, 100, 1)")
    from ui.app import build
    app = build()
    raiz = app.layout.children
    ids = {getattr(c, "id", None) for c in raiz}
    # a div do alarme fica na raiz: vale em qualquer aba do app
    assert "ord-alarme" in ids and "ord-intervalo" in ids
    texto = str(app.layout)
    assert "ord-selo" in texto and "ord-zerar" in texto
    assert CO.ROTULO in texto


def test_pulso_do_topo_responde_pelo_servidor(tmp_path):
    """O callback de verdade, pelo Flask: a saída `data-alarme` (atributo
    curinga) precisa sair serializada para o alarme.js."""
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) VALUES ('WIN$N', 't')")
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00',"
                    " 100, 101, 99, 100, 1)")
    agora = datetime.now()
    trava = {"desde": agora.isoformat(), "perda": 460.0, "limite": 500.0}
    estado = {"atualizado_em": agora.isoformat(),
              "ordens": _ordens(envio=False, travada=trava)}
    D.ESTADO_CAPTURA.parent.mkdir(parents=True, exist_ok=True)
    D.ESTADO_CAPTURA.write_text(json.dumps(estado), encoding="utf-8")
    from ui.app import build
    app = build()
    saidas = [("ord-selo", "children"), ("ord-selo", "className"),
              ("ord-selo", "title"), ("ord-alarme", "data-alarme"),
              ("ord-alarme", "data-chaves")]
    corpo = {
        "output": ".." + "...".join(f"{i}.{p}" for i, p in saidas) + "..",
        "outputs": [{"id": i, "property": p} for i, p in saidas],
        "inputs": [{"id": "ord-intervalo", "property": "n_intervals", "value": 1}],
        "changedPropIds": ["ord-intervalo.n_intervals"], "state": [],
    }
    r = app.server.test_client().post("/_dash-update-component", json=corpo)
    assert r.status_code == 200, r.data
    resp = r.get_json()["response"]
    assert resp["ord-alarme"]["data-alarme"] == "1"
    assert "travada" in resp["ord-alarme"]["data-chaves"]
    assert "ord-selo-travada" in resp["ord-selo"]["className"]
