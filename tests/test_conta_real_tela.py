"""Conta real na tela (parte 5, W3-A): faixa de saúde REAL/DEMO, chamados com
a conta de origem, "Zerar tudo" somando as duas contas e o encerramento de
um chamado da real indo para a pasta da real.

Os blocos `ordens` são montados à mão (formato de `core.ordens.Motor.passo`).
O conftest desvia `ESTADO_REAL` e as pastas de comando: nada toca a conta
real do usuário.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import comandos  # noqa: E402
from ui import callbacks_operacao as CO  # noqa: E402
from ui import callbacks_ordens as CZ  # noqa: E402
from ui import data as D  # noqa: E402
from ui.components import ordens_panel as OR  # noqa: E402

AGORA = datetime(2026, 10, 21, 10, 0, 0)
VARS = [{"ligacao_id": 7, "nome": "variante-canal-M7"}]


def _bloco(idade_s=2, **mudar):
    """Um bloco `ordens` de uma conta com uma posição aberta na automação."""
    o = {
        "falhou": False, "foto": "ok",
        "vivo_em": (AGORA - timedelta(seconds=idade_s)).isoformat(),
        "conta": {"conta_id": 9, "login": 1014062283, "servidor": "Clear-Real",
                  "confere": True, "hedging": True, "algo": True,
                  "margem_livre": 12430.0},
        "envio": True, "zerar": False, "travada": None, "limite": 500.0,
        "ligacoes": {"7": {"desejado": "posicao", "papel": "posicao",
                           "motivo": None, "posicoes": [
                               {"ticket": 501, "volume": 1.0, "lado": 1,
                                "resultado": 10.0, "saida_desde": None,
                                "tentativas": 0}]}},
        "chamados": [], "comandos": [], "posicao_fora": [], "n_demo": 1,
    }
    o.update(mudar)
    return o


def _estado(ordens=None):
    """estado.json da captura, com a volta de agora (captura ativa)."""
    return {"atualizado_em": (AGORA - timedelta(seconds=2)).isoformat(),
            "ordens": ordens}


def _chamado(chave, ticket, desde="2026-10-21T09:50:00"):
    return {"chave": chave, "tipo": "sem_stop", "texto": "posição sem stop",
            "ligacao_id": 7, "ticket": ticket, "desde": desde, "entry_ts": None}


def _textos(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(_textos(x) for x in c)
    return _textos(getattr(c, "children", None))


def _todos(c):
    if c is None or isinstance(c, (str, int, float)):
        return []
    if isinstance(c, (list, tuple)):
        return [x for y in c for x in _todos(y)]
    return [c] + _todos(getattr(c, "children", None))


def _classes(c) -> str:
    return getattr(c, "className", "") or ""


def _linhas_saude(f) -> list:
    return [x for x in _todos(f) if "ord-saude-linha" in _classes(x)
            and "ord-saude-cab" not in _classes(x)]


# ------------------------------------------------------------- dados da real
def test_estado_real_ausente_e_none():
    assert D.estado_real() is None


def test_estado_real_le_o_bloco_da_real():
    D.ESTADO_REAL.parent.mkdir(parents=True, exist_ok=True)
    import json
    D.ESTADO_REAL.write_text(json.dumps({"pid": 1, "ordens": _bloco()}, ensure_ascii=False), encoding="utf-8")
    assert D.estado_real()["conta"]["login"] == 1014062283


# ------------------------------------------------------------- faixa de saúde
def test_sem_conta_real_nao_aparece_linha_real():
    f = OR.faixa_saude(_bloco(), agora=AGORA)
    tags = [_textos(x) for x in _todos(f) if "ord-conta-real" in _classes(x)]
    assert tags == []
    assert len(_linhas_saude(f)) == 1          # só a DEMO


def test_conta_real_cadastrada_sem_arquivo_fica_parada():
    f = OR.faixa_saude(_bloco(), agora=AGORA, real=None, com_real=True)
    real = _linhas_saude(f)[0]
    assert "ord-conta-real" in _classes(real.children[0])
    assert _textos(real.children[1]) == "parado"
    assert "rosa" in _classes(real.children[1])
    assert "rosa" not in _classes(_linhas_saude(f)[1].children[1])


def test_conta_real_com_mais_de_10s_fica_parada():
    real = _bloco(idade_s=11)
    f = OR.faixa_saude(_bloco(), agora=AGORA, real=real)
    assert _textos(_linhas_saude(f)[0].children[1]) == "parado"


def test_conta_real_fresca_mostra_os_valores_da_real():
    f = OR.faixa_saude(_bloco(), agora=AGORA, real=_bloco(idade_s=3))
    t = _textos(_linhas_saude(f)[0])
    assert "conectado" in t and "1014062283" in t and "R$ 12.430" in t
    assert "parado" not in t


# ----------------------------------------------------------------- chamados
def test_chamados_da_real_e_da_demo_com_chip_de_conta():
    est = _estado(_bloco(chamados=[_chamado("sem_stop:7", 601)]))
    real = _bloco(chamados=[_chamado("sem_stop:7", 501)])
    out = CO.pulso_ordens(est, None, VARS, 1, {}, [], [], None, AGORA, 1000.0,
                          real=real)
    chamados = out[1]
    origens = [_textos(x) for x in _todos(chamados) if "ord-conta" in _classes(x)]
    assert origens == ["demo", "real"]
    assert _textos(chamados).count("precisa de você") == 2


def test_chamado_da_real_parada_nao_aparece():
    est = _estado(_bloco())
    real = _bloco(idade_s=30, chamados=[_chamado("sem_stop:7", 501)])
    out = CO.pulso_ordens(est, None, VARS, 1, {}, [], [], None, AGORA, 1000.0,
                          real=real)
    assert _textos(out[1]) == ""


def test_chave_do_chamado_da_real_nao_colide_com_a_da_demo():
    demo = _chamado("sem_stop:7", 601)
    real = _chamado("sem_stop:7", 501)
    da_demo = CO._chamados_de({"chamados": [demo]}, "demo")[0]
    da_real = CO._chamados_de({"chamados": [real]}, "real")[0]
    assert OR.chave_chamado(da_demo) != OR.chave_chamado(da_real)


def test_encerrar_chamado_da_real_vai_para_a_pasta_real(monkeypatch):
    monkeypatch.setattr(D, "estado_captura", lambda: _estado(_bloco()))
    monkeypatch.setattr(D, "estado_real", lambda: _bloco(chamados=[_chamado("sem_stop:7", 501)]))
    assert CO._conta_do_chamado(501) == "real"
    assert CO._conta_do_chamado(601) == "demo"
    assert CO._conta_do_chamado("manter-x") == "demo"


# ------------------------------------------------------------------ zerar
def test_zerar_soma_as_posicoes_das_duas_contas():
    # demo com 1 posição (_bloco), real com 1 posição: a contagem é 2
    _, rotulo, _ = CZ.zerar(None, _estado(_bloco()), AGORA, agora_s=100.0,
                            real=_bloco())
    assert rotulo == "Confirmar: encerra 2 posições"


def test_zerar_sem_real_conta_so_a_demo():
    _, rotulo, _ = CZ.zerar(None, _estado(_bloco()), AGORA, agora_s=100.0)
    assert rotulo == "Confirmar: encerra 1 posição"


def test_zerar_escreve_nas_duas_pastas(monkeypatch):
    # segundo clique dentro de 6 s: o comando vai para a demo e para a real
    monkeypatch.setattr(CZ, "_contas_ativas", lambda: [])
    CZ.zerar(98.0, _estado(_bloco()), AGORA, agora_s=100.0, real=_bloco())
    assert any(comandos.PASTA.glob("*"))
    assert any(comandos.PASTA_REAL.glob("*"))


def test_estado_real_devolve_o_bloco_ordens_do_arquivo(tmp_path, monkeypatch):
    # bug de 21/10: o arquivo é o estado inteiro; sem pegar o bloco
    # `ordens` a linha REAL ficava sempre "parado"
    import json
    from ui import data as D
    arq = tmp_path / "estado_real.json"
    arq.write_text(json.dumps({"pid": 1, "ordens": {"vivo_em": "2026-10-21T13:00:00",
                                                    "conta": {"login": 7}}}), encoding="utf-8")
    monkeypatch.setattr(D, "ESTADO_REAL", arq)
    assert D.estado_real()["vivo_em"] == "2026-10-21T13:00:00"
