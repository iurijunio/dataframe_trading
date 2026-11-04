"""O laço da busca, com um avaliador falso (rápido e determinístico)."""
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta

import pytest

from core.busca import banco as B
from core.busca import motor as M
from core.busca.espaco import Combinacao, Espaco
from core.engine.execution import ExecutionProfile


def _nota(chave: str) -> float:
    return int(hashlib.sha1(chave.encode()).hexdigest()[:6], 16) % 1000 / 100


class Falso:
    """Nota pseudoaleatória pela chave; registra chamadas."""

    def __init__(self, embaralhar=False, ao_chamar=None):
        self.vistas: list[str] = []
        self.ns: list[int] = []
        self.embaralhar = embaralhar
        self.ao_chamar = ao_chamar

    def __call__(self, grupos, config, n):
        self.ns.append(n)
        if self.ao_chamar:
            self.ao_chamar(len(self.ns))
        out = []
        for _chave, tarefas in grupos:
            for t, k in tarefas:
                self.vistas.append(k)
                o = _nota(k)
                out.append({"teste_n": t, "combo": k, "objetivo": o, "valida": o > 2,
                            "trades": 500, "lucro": o, "pf": 1.0, "dd": 1.0, "fr": o,
                            "consistencia": 0.5, "mediana_fold": 0.0, "score": o,
                            "trades_hash": k[:8], "descartada": None})
        return out[::-1] if self.embaralhar else out


@pytest.fixture(autouse=True)
def _salvar_todo_lote(monkeypatch):
    # nos testes de queda o arquivo é salvo a cada lote, como pior caso
    monkeypatch.setattr(M, "SALVAR_A_CADA_S", 0.0)


@pytest.fixture
def busca():
    esp = Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                 faixas={"di_periodo": {"de": 5, "ate": 30}})
    bid = B.criar({"simbolo": "WIN$N", "estrategia": "adx_direcao",
                   "espaco": esp.para_json(), "perfil_base": ExecutionProfile().to_config(),
                   "wf_config": {}, "minimo": 400, "criterio": "fr", "semente": 7})
    M.escrever_json(B.pasta_da(bid) / "controle.json",
                    {"parar_as_ligado": False, "nucleos": 3})
    return bid


def _elites(bid):
    return sorted((e["casa"], e["combo"], e["objetivo"]) for e in B.ler_elites(bid))


def _teste_ns(bid):
    return [c["teste_n"] for c in B.ler_combos(bid, so_validas=False)]


def test_lote_grava_e_atualiza_estado(busca):
    f = Falso()
    assert M.Busca(busca, avaliar=f).rodar(max_lotes=2) == "parada_teste"
    b = B.ler_busca(busca)
    assert b["lote_n"] == 2 and b["distintos"] == len(_teste_ns(busca)) > 0
    assert sorted(_teste_ns(busca)) == list(range(1, b["distintos"] + 1))
    est = json.loads((B.pasta_da(busca) / "estado.json").read_text(encoding="utf-8"))
    assert est["versao"] == 2 and est["distintos"] == b["distintos"]
    assert est["nichos"] == sum(1 for e in B.ler_elites(busca) if e["valida"])


def test_tell_na_ordem_do_ask(busca):
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=3)
    direto = _elites(busca)
    outra = B.criar(B.ler_busca(busca)["config"])
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False})
    M.Busca(outra, avaliar=Falso(embaralhar=True)).rodar(max_lotes=3)
    assert _elites(outra) == direto


def test_combinacao_repetida_nao_roda_de_novo(busca):
    f = Falso()
    M.Busca(busca, avaliar=f).rodar(max_lotes=5)
    assert len(f.vistas) == len(set(f.vistas))
    b = B.ler_busca(busca)
    assert b["testes"] >= b["distintos"] == len(f.vistas)


def test_elite_e_a_melhor_da_casa(busca):
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=4)
    por_casa = {}
    for c in B.ler_combos(busca, so_validas=False):
        por_casa[c["casa"]] = max(por_casa.get(c["casa"], -1e18), c["objetivo"])
    assert {e["casa"]: e["objetivo"] for e in B.ler_elites(busca)} == por_casa


def test_limite_de_testes(busca):
    M.escrever_json(B.pasta_da(busca) / "controle.json",
                    {"parar_as_ligado": False, "limite": 300})
    assert M.Busca(busca, avaliar=Falso()).rodar() == "concluida"
    b = B.ler_busca(busca)
    assert b["status"] == "concluida" and 300 <= b["distintos"] < 300 + 216


def test_parar_as(busca):
    relogio = {"t": datetime(2026, 11, 3, 8, 0)}

    def agora():
        relogio["t"] += timedelta(minutes=1)
        return relogio["t"]

    M.escrever_json(B.pasta_da(busca) / "controle.json",
                    {"parar_as_ligado": True, "parar_as": "08:30"})
    assert M.Busca(busca, avaliar=Falso(), agora=agora).rodar() == "concluida"
    assert relogio["t"] >= datetime(2026, 11, 3, 8, 30)
    est = json.loads((B.pasta_da(busca) / "estado.json").read_text(encoding="utf-8"))
    assert est["status"] == "concluida" and est["motivo"] == "horario"


def test_proximo_horario():
    assert M.proximo_horario("08:30", datetime(2026, 11, 3, 22, 0)) == datetime(2026, 11, 4, 8, 30)
    assert M.proximo_horario("08:30", datetime(2026, 11, 4, 7, 0)) == datetime(2026, 11, 4, 8, 30)


def test_pausar_continuar_e_parar(busca):
    pasta = B.pasta_da(busca)

    def lento(grupos, config, n):
        time.sleep(0.05)
        return Falso()(grupos, config, n)

    resultado = {}
    t = threading.Thread(target=lambda: resultado.update(
        s=M.Busca(busca, avaliar=lento).rodar()))
    t.start()

    def esperar(status):
        for _ in range(200):
            if M.ler_json(pasta / "estado.json").get("status") == status:
                return True
            time.sleep(0.05)
        return False

    assert esperar("rodando")
    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": False, "pedido": "pausar"})
    assert esperar("pausada") and B.ler_busca(busca)["status"] == "pausada"
    lote = B.ler_busca(busca)["lote_n"]
    time.sleep(1.5)
    assert B.ler_busca(busca)["lote_n"] == lote          # pausada não anda
    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": False, "pedido": None})
    assert esperar("rodando")
    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": False, "pedido": "parar"})
    t.join(timeout=20)
    assert resultado["s"] == "concluida" and B.ler_busca(busca)["status"] == "concluida"


def test_nucleos_mudam_no_proximo_lote(busca):
    pasta = B.pasta_da(busca)

    def no_primeiro(n_chamada):
        if n_chamada == 1:
            M.escrever_json(pasta / "controle.json", {"parar_as_ligado": False, "nucleos": 7})

    f = Falso(ao_chamar=no_primeiro)
    M.Busca(busca, avaliar=f).rodar(max_lotes=3)
    assert f.ns == [3, 7, 7]


def test_retomar_apos_queda(busca):
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=3)
    direto, ns_direto = _elites(busca), sorted(_teste_ns(busca))

    outra = B.criar(B.ler_busca(busca)["config"])
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False})
    M.Busca(outra, avaliar=Falso()).rodar(max_lotes=2)
    M.Busca(outra, avaliar=Falso()).rodar(max_lotes=1)      # "outro dia"
    assert _elites(outra) == direto and sorted(_teste_ns(outra)) == ns_direto


def test_queda_entre_banco_e_pickle_nao_duplica(busca, monkeypatch):
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=3)
    direto, ns_direto = _elites(busca), sorted(_teste_ns(busca))

    outra = B.criar(B.ler_busca(busca)["config"])
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False})
    original = M.Busca._salvar
    chamadas = {"n": 0}

    def cai_no_terceiro(self, s, ja=False):
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            raise KeyboardInterrupt("PC desligou")
        original(self, s, ja)

    monkeypatch.setattr(M.Busca, "_salvar", cai_no_terceiro)
    with pytest.raises(KeyboardInterrupt):
        M.Busca(outra, avaliar=Falso()).rodar(max_lotes=3)
    assert B.ler_busca(outra)["lote_n"] == 3                # o banco viu o lote 3
    monkeypatch.setattr(M.Busca, "_salvar", original)
    M.Busca(outra, avaliar=Falso()).rodar(max_lotes=1)
    ns = _teste_ns(outra)
    assert len(ns) == len(set(ns)) and sorted(ns) == ns_direto
    assert _elites(outra) == direto


def test_banco_ocupado_nao_derruba(busca, monkeypatch):
    original = B.gravar_lote
    falhas = {"n": 0}

    def ocupado(*a, **k):
        falhas["n"] += 1
        if falhas["n"] <= 2:
            raise B.BancoOcupado("app lendo")
        return original(*a, **k)

    monkeypatch.setattr(B, "gravar_lote", ocupado)
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=3)
    b = B.ler_busca(busca)
    assert b["lote_n"] == 3 and sorted(_teste_ns(busca)) == list(range(1, b["distintos"] + 1))


def test_erro_marca_a_busca(busca):
    def quebra(grupos, config, n):
        raise ValueError("estratégia quebrou")

    with pytest.raises(ValueError):
        M.Busca(busca, avaliar=quebra).rodar()
    b = B.ler_busca(busca)
    assert b["status"] == "erro" and "quebrou" in b["erro"]


def test_queda_entre_salvamentos_refaz_so_o_que_faltou(busca, monkeypatch):
    """Arquivo salvo de 30 em 30 s: a queda perde os lotes desde o último
    salvamento, que rodam de novo sem ficar em dobro no banco."""
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=4)
    direto, ns_direto = _elites(busca), sorted(_teste_ns(busca))

    outra = B.criar(B.ler_busca(busca)["config"])
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False})
    monkeypatch.setattr(M, "SALVAR_A_CADA_S", 1e9)     # só o 1º lote é salvo
    original = M.Busca._gravar_pendentes
    chamadas = {"n": 0}

    def cai_no_terceiro(self, s):
        original(self, s)
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            raise KeyboardInterrupt("PC desligou")

    monkeypatch.setattr(M.Busca, "_gravar_pendentes", cai_no_terceiro)
    with pytest.raises(KeyboardInterrupt):
        M.Busca(outra, avaliar=Falso()).rodar(max_lotes=4)
    monkeypatch.setattr(M.Busca, "_gravar_pendentes", original)
    M.Busca(outra, avaliar=Falso()).rodar(max_lotes=3)
    ns = _teste_ns(outra)
    assert len(ns) == len(set(ns)) and sorted(ns) == ns_direto
    assert _elites(outra) == direto


def test_digital_estavel():
    assert M.digital("abc") == M.digital("abc") != M.digital("abd")
    assert 0 <= M.digital("abc") < 2**64
