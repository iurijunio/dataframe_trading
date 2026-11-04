"""Processo separado e controle pelo app.

O teste de ponta a ponta abre o `busca.py` de verdade, com os caminhos
explícitos em pastas temporárias (o monkeypatch do conftest não chega ao
processo filho)."""
import json
import subprocess
import sys
import time

import pytest

from core import db_manager as db
from core import walkforward  # noqa: F401
from core.busca import banco as B
from core.busca import controle as K
from core.busca import motor as M
from core.busca import prioridade
from core.busca.espaco import Espaco
from core.engine.execution import ExecutionProfile


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


def _config():
    esp = Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                 faixas={"timeframe": {"ligados": ["M5", "M15"]},
                         "di_periodo": {"de": 10, "ate": 14},
                         "adx_suavizacao": {"de": 10, "ate": 12}})
    return {"simbolo": "WIN$N", "estrategia": "adx_direcao", "espaco": esp.para_json(),
            "perfil_base": ExecutionProfile(min_operacoes=0).to_config(),
            "de": "2024-01-01", "ate": "2024-06-30",
            "wf_config": {"treino_meses": 2, "teste_meses": 1, "passo_meses": 1,
                          "holdout_meses": 1},
            "minimo": 30, "criterio": "fr", "semente": 1}


@pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")
def test_ponta_a_ponta_sem_abrir_o_banco_principal():
    assert not db.DB_PATH.exists()
    bid = K.iniciar(_config(), nucleos=2, parar_as_ligado=False, limite=100)
    fim = time.monotonic() + 240
    while time.monotonic() < fim:
        estado = K.ler(bid)
        if estado["status"] in ("concluida", "erro") and not estado["vivo"]:
            break
        time.sleep(0.5)
    log = (B.pasta_da(bid) / "processo.log").read_text(encoding="utf-8", errors="replace")
    assert estado["status"] == "concluida", log
    b = B.ler_busca(bid)
    assert b["distintos"] >= 100 and len(B.ler_combos(bid, so_validas=False)) == b["distintos"]
    assert len(B.ler_elites(bid)) > 0
    # a busca nunca abriu (nem criou) o banco principal
    assert not db.DB_PATH.exists()
    assert K.ativa() is None


def test_abre_sem_janela_e_com_prioridade_baixa(monkeypatch):
    chamadas = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: chamadas.append((a, k)))
    bid = K.iniciar(_config())
    (args,), kw = chamadas[0]
    assert kw["creationflags"] & K.CREATE_NO_WINDOW
    assert kw["creationflags"] & K.BELOW_NORMAL_PRIORITY_CLASS
    assert not kw["creationflags"] & 0x00000008          # nada de DETACHED_PROCESS
    assert args[1].endswith("busca.py") and args[2] == str(bid)
    assert args[args.index("--banco") + 1] == str(B.CAMINHO)
    assert args[args.index("--db-principal") + 1] == str(db.DB_PATH)


@pytest.mark.skipif(sys.platform != "win32", reason="só Windows")
def test_prioridade_abaixo_do_normal():
    saida = subprocess.run(
        [sys.executable, "-c", "from core.busca import prioridade as p; p.baixar(); print(p.atual())"],
        capture_output=True, text=True, cwd=str(K.RAIZ))
    assert int(saida.stdout.strip()) == prioridade.BELOW_NORMAL_PRIORITY_CLASS


def _segurar(bid):
    f = K.travar(B.PASTA / "rodando.lock")
    M.escrever_json(B.PASTA / "rodando.json", {"busca_id": bid})
    return f


def test_uma_por_vez(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    f = _segurar(99)
    try:
        assert K.ativa() == 99
        with pytest.raises(K.BuscaJaRodando):
            K.iniciar(_config())
    finally:
        K.soltar(f)
    assert K.ativa() is None


def test_interrompida_quando_o_processo_morre():
    bid = B.criar(_config())          # banco diz "rodando", ninguém com a trava
    assert K.ler(bid)["status"] == "interrompida"
    f = _segurar(bid)
    try:
        assert K.ler(bid)["status"] == "rodando" and K.ler(bid)["vivo"]
    finally:
        K.soltar(f)


def test_excluir_recusa_viva():
    bid = B.criar(_config())
    f = _segurar(bid)
    try:
        with pytest.raises(K.BuscaViva):
            K.excluir(bid)
    finally:
        K.soltar(f)
    K.excluir(bid)
    assert B.ler_busca(bid) is None


def test_comandos_vao_ao_controle(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    bid = K.iniciar(_config(), nucleos=20)
    K.ajustar(bid, nucleos=6, parar_as="07:00")
    K.pausar(bid)
    c = json.loads((B.pasta_da(bid) / "controle.json").read_text(encoding="utf-8"))
    assert (c["nucleos"], c["parar_as"], c["pedido"]) == (6, "07:00", "pausar")


def test_parar_sem_processo_conclui(monkeypatch):
    bid = B.criar(_config())
    K.parar(bid)
    assert B.ler_busca(bid)["status"] == "concluida"


def test_continuar_reabre_quando_nao_ha_processo(monkeypatch):
    abertos = []
    monkeypatch.setattr(K, "_abrir", abertos.append)
    bid = B.criar(_config())
    K.pausar(bid)
    K.continuar(bid)
    assert abertos == [bid] and M.ler_controle(B.pasta_da(bid))["pedido"] is None


def test_logo_depois_de_abrir_nao_e_interrompida(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    bid = K.iniciar(_config())       # processo "ainda subindo": sem trava
    e = K.ler(bid)
    assert e["status"] == "rodando" and e["abrindo"]
    monkeypatch.setattr(K.time, "time", lambda: 10**12)
    assert K.ler(bid)["status"] == "interrompida"


def test_parar_logo_depois_de_abrir_vira_pedido(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    bid = K.iniciar(_config())
    K.parar(bid)
    assert M.ler_controle(B.pasta_da(bid))["pedido"] == "parar"
    assert B.ler_busca(bid)["status"] == "rodando"     # o processo é quem conclui


@pytest.mark.skipif(not _tem_parquet(), reason="sem Parquet do WIN")
def test_iniciar_fixa_o_periodo(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    cfg = {**_config(), "de": "2024-01-01", "ate": None}
    bid = K.iniciar(cfg)
    c = B.ler_busca(bid)["config"]
    assert c["de"] == "2024-01-01" and c["ate"] and c["ate"] > "2024-06"


def test_ajustes_simultaneos_nao_se_apagam(monkeypatch):
    import threading
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    bid = K.iniciar(_config())
    ts = [threading.Thread(target=K.ajustar, args=(bid,), kwargs={f"k{i}": i})
          for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    c = M.ler_controle(B.pasta_da(bid))
    assert all(c[f"k{i}"] == i for i in range(12))



def test_pedidos_da_tela_ficam_no_diario(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    bid = K.iniciar(_config())
    K.pausar(bid)
    K.ajustar(bid, nucleos=3)
    log = (B.pasta_da(bid) / "acoes.log").read_text(encoding="utf-8")
    assert "'pedido': 'pausar'" in log and "'nucleos': 3" in log
