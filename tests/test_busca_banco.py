"""Banco próprio da busca automática (`data/buscas.duckdb`)."""
import subprocess
import sys
import time

import pytest

from core.busca import banco as B

CONFIG = {"simbolo": "WIN$N", "estrategia": "adx_direcao", "minimo": 400}


def _combo(n, valida=True, casa="[0,0,0,0,0]"):
    return {"teste_n": n, "casa": casa, "combo": f'{{"n":{n}}}', "trades": 500,
            "lucro": 100.0, "pf": 1.2, "dd": 50.0, "fr": 2.0, "consistencia": 0.6,
            "mediana_fold": 10.0, "score": 1.0, "objetivo": 2.0, "valida": valida,
            "trades_hash": f"h{n}", "descartada": None}


def _elite(casa, obj, n=1):
    return {"casa": casa, "combo": "{}", "objetivo": obj, "valida": True, "trades": 500,
            "lucro": 1.0, "pf": 1.1, "dd": 1.0, "fr": obj, "achado_em": n}


def test_conftest_isola_o_banco_da_busca():
    from core import db_manager as db

    assert B.CAMINHO.parent != db.DATA and B.PASTA.parent != db.DATA
    assert db.DATA not in B.CAMINHO.parents


def test_criar_ler_listar():
    a = B.criar(CONFIG)
    b = B.criar({**CONFIG, "estrategia": "setup_cruzamento"})
    assert b == a + 1
    assert B.ler_busca(a)["config"] == CONFIG and B.ler_busca(a)["status"] == "rodando"
    assert [x["busca_id"] for x in B.listar()] == [b, a]
    assert [x["busca_id"] for x in B.listar(estrategia="adx_direcao")] == [a]
    assert B.ler_busca(999) is None


def test_leitura_sem_arquivo_nao_quebra():
    assert not B.CAMINHO.exists()
    assert B.listar() == [] and B.ler_elites(1) == []


def test_gravar_lote_e_elite_substituida():
    bid = B.criar(CONFIG)
    B.gravar_lote(bid, 1, [_combo(1), _combo(2, valida=False)], [_elite("c1", 2.0)],
                  [{"casa": "c1", "teste_n": 1, "objetivo": 2.0}],
                  {"testes": 2, "distintos": 2, "descartados": 0})
    B.gravar_lote(bid, 2, [_combo(3)], [_elite("c1", 5.0, 3)],
                  [{"casa": "c1", "teste_n": 3, "objetivo": 5.0}],
                  {"testes": 3, "distintos": 3, "descartados": 0})
    assert [e["objetivo"] for e in B.ler_elites(bid)] == [5.0]
    assert len(B.ler_combos(bid)) == 2 and len(B.ler_combos(bid, so_validas=False)) == 3
    assert B.ler_busca(bid)["lote_n"] == 2 and B.ler_busca(bid)["testes"] == 3


def test_gravar_lote_e_tudo_ou_nada():
    bid = B.criar(CONFIG)
    with pytest.raises(ValueError):
        B.gravar_lote(bid, 1, [_combo(1)], [_elite("c1", 2.0)], [],
                      {"campo_que_nao_existe": 1})
    assert B.ler_combos(bid) == [] and B.ler_elites(bid) == []
    assert B.ler_busca(bid)["lote_n"] == 0


def test_descartar_apos_tira_o_lote_que_nao_chegou_ao_arquivo():
    bid = B.criar(CONFIG)
    for lote in (1, 2, 3):
        B.gravar_lote(bid, lote, [_combo(lote)], [], [{"casa": "c", "teste_n": lote,
                                                      "objetivo": 1.0}], {})
    B.descartar_apos(bid, 2)
    assert [c["teste_n"] for c in B.ler_combos(bid)] == [1, 2]
    assert len(B.ler_hist(bid)) == 2 and B.ler_busca(bid)["lote_n"] == 2


def test_substituir_elites():
    bid = B.criar(CONFIG)
    B.gravar_lote(bid, 1, [], [_elite("a", 1.0), _elite("b", 2.0)], [], {})
    B.substituir_elites(bid, [_elite("a", 0.5)])
    assert [(e["casa"], e["objetivo"]) for e in B.ler_elites(bid)] == [("a", 0.5)]


def test_excluir_apaga_banco_e_so_a_propria_pasta():
    a, b = B.criar(CONFIG), B.criar(CONFIG)
    for bid in (a, b):
        B.pasta_da(bid).mkdir(parents=True)
        (B.pasta_da(bid) / "estado.json").write_text("{}")
    B.gravar_lote(a, 1, [_combo(1)], [_elite("c", 1.0)], [], {})
    B.excluir(a)
    assert B.ler_busca(a) is None and B.ler_combos(a) == [] and B.ler_elites(a) == []
    assert not B.pasta_da(a).exists() and B.pasta_da(b).exists()


def test_status_e_campos():
    bid = B.criar(CONFIG)
    B.marcar_status(bid, "pausada", historico=[[0, 1]])
    b = B.ler_busca(bid)
    assert b["status"] == "pausada" and b["historico"] == [[0, 1]]
    with pytest.raises(ValueError):
        B.marcar_status(bid, outra_coisa=1)


def test_leitura_com_escritor_ocupado():
    """Outro processo com o arquivo aberto para escrita: a leitura desiste em
    tempo limitado com BancoOcupado, sem travar a tela."""
    B.criar(CONFIG)
    segura = subprocess.Popen(
        [sys.executable, "-c",
         "import duckdb,sys,time; c=duckdb.connect(sys.argv[1]); "
         "print('ok', flush=True); time.sleep(20)", str(B.CAMINHO)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert segura.stdout.readline().strip() == "ok"
        t0 = time.monotonic()
        with pytest.raises(B.BancoOcupado):
            with B.conectar(False, tentativas=4, espera_s=0.1):
                pass
        assert time.monotonic() - t0 < 5
    finally:
        segura.kill()
        segura.wait()
