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
                   "de": "2024-01-01", "ate": "2024-06-30T17:59:00",
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
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False, "nucleos": 3})
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
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False, "nucleos": 3})
    M.Busca(outra, avaliar=Falso()).rodar(max_lotes=2)
    M.Busca(outra, avaliar=Falso()).rodar(max_lotes=1)      # "outro dia"
    assert _elites(outra) == direto and sorted(_teste_ns(outra)) == ns_direto


def test_queda_entre_banco_e_pickle_nao_duplica(busca, monkeypatch):
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=3)
    direto, ns_direto = _elites(busca), sorted(_teste_ns(busca))

    outra = B.criar(B.ler_busca(busca)["config"])
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False, "nucleos": 3})
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
    M.escrever_json(B.pasta_da(outra) / "controle.json", {"parar_as_ligado": False, "nucleos": 3})
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


def test_poucos_sinais_por_lote_e_arquivo_coerente(busca):
    """Cada lote só traz núcleos × SINAIS_POR_NUCLEO sinais novos, e o que a
    pyribs guarda no arquivo é a combinação que foi de fato avaliada."""
    grupos_por_lote = []

    def conta(grupos, config, n):
        grupos_por_lote.append(len(grupos))
        return Falso()(grupos, config, n)

    busca_obj = M.Busca(busca, avaliar=conta)
    busca_obj.rodar(max_lotes=3)
    assert all(g <= 3 * M.SINAIS_POR_NUCLEO for g in grupos_por_lote)

    import pickle
    with open(B.pasta_da(busca) / "arquivo.pkl", "rb") as f:
        s = pickle.load(f)
    dados = s["scheduler"].archive.data()
    elites = {e["casa"]: e["combo"] for e in B.ler_elites(busca)}
    for x in dados["solution"]:
        c = busca_obj.esp.decodificar(x)
        casa = json.dumps(list(busca_obj.esp.casa(c)))
        assert elites[casa] == c.chave()


def test_parar_as_religado_conta_a_partir_de_agora(busca):
    """Desligado de manhã e religado à tarde: não para na hora por causa da
    manhã que já passou."""
    pasta = B.pasta_da(busca)
    relogio = {"t": datetime(2026, 11, 3, 22, 0)}

    def agora():
        return relogio["t"]

    b = M.Busca(busca, avaliar=Falso(), agora=agora)
    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": True, "parar_as": "08:30"})
    b._controle()
    assert b._parar_em == datetime(2026, 11, 4, 8, 30)
    relogio["t"] = datetime(2026, 11, 4, 7, 0)
    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": False, "parar_as": "08:30"})
    b._controle()
    relogio["t"] = datetime(2026, 11, 5, 15, 0)
    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": True, "parar_as": "08:30"})
    ctl = b._controle()
    assert b._parar_em == datetime(2026, 11, 6, 8, 30)
    assert not b._deve_parar({"distintos": 0}, ctl)


def test_parar_as_mudado_durante_a_pausa(busca):
    pasta = B.pasta_da(busca)
    relogio = {"t": datetime(2026, 11, 4, 8, 0)}

    def agora():
        relogio["t"] += timedelta(seconds=30)
        return relogio["t"]

    M.escrever_json(pasta / "controle.json", {"parar_as_ligado": True, "parar_as": "08:30",
                                              "pedido": "pausar"})
    dormidas = {"n": 0}

    def dormir(_s):
        dormidas["n"] += 1
        if dormidas["n"] == 2:     # pausada às ~08:01: muda para 12:00
            M.escrever_json(pasta / "controle.json", {"parar_as_ligado": True,
                                                      "parar_as": "12:00", "pedido": "pausar"})
        if relogio["t"] >= datetime(2026, 11, 4, 9, 0):
            M.escrever_json(pasta / "controle.json", {"parar_as_ligado": True,
                                                      "parar_as": "12:00", "pedido": "parar"})

    import core.busca.motor as mod
    original = mod.time.sleep
    mod.time.sleep = dormir
    try:
        M.Busca(busca, avaliar=Falso(), agora=agora).rodar()
    finally:
        mod.time.sleep = original
    est = M.ler_json(pasta / "estado.json")
    assert est["motivo"] == "parar"            # não parou às 08:30


def test_controle_ilegivel_mantem_o_ultimo(busca, monkeypatch):
    pasta = B.pasta_da(busca)
    M.escrever_json(pasta / "controle.json", {"pedido": "pausar", "nucleos": 9})
    ultimo = M.ler_controle(pasta)
    (pasta / "controle.json").write_text("{meio arquiv", encoding="utf-8")
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    assert M.ler_controle(pasta, ultimo) == ultimo
    assert M.ler_controle(pasta, ultimo)["pedido"] == "pausar"


def test_banco_ocupado_ao_pausar_nao_derruba(busca, monkeypatch):
    pasta = B.pasta_da(busca)
    original = B.marcar_status
    falhas = {"n": 0}

    def ocupado(bid, status=None, **campos):
        if status == "pausada" and falhas["n"] < 3:
            falhas["n"] += 1
            raise B.BancoOcupado("app lendo")
        return original(bid, status, **campos)

    monkeypatch.setattr(B, "marcar_status", ocupado)
    chamadas = {"n": 0}

    def no_lote(n):
        if n == 1:
            M.escrever_json(pasta / "controle.json", {"parar_as_ligado": False, "pedido": "pausar"})

    monkeypatch.setattr(M.time, "sleep", lambda s: (
        chamadas.__setitem__("n", chamadas["n"] + 1),
        chamadas["n"] > 5 and M.escrever_json(
            pasta / "controle.json", {"parar_as_ligado": False, "pedido": "parar"})))
    assert M.Busca(busca, avaliar=Falso(ao_chamar=no_lote)).rodar() == "concluida"
    assert falhas["n"] == 3 and B.ler_busca(busca)["status"] == "concluida"


def test_busca_sem_periodo_fixo_recusa(busca):
    cfg = {**B.ler_busca(busca)["config"], "ate": None}
    outra = B.criar(cfg)
    with pytest.raises(ValueError, match="período fixo"):
        M.Busca(outra)


def test_fechamento_de_uma_fonte_so(busca):
    cfg = B.ler_busca(busca)["config"]
    cfg = {**cfg, "perfil_base": {**cfg["perfil_base"], "fechamento": "16:00"}}
    with pytest.raises(ValueError, match="fechamento"):
        M.Busca(B.criar(cfg))


def test_retomada_corta_os_pendentes_ja_gravados(busca):
    """Arquivo salvo com lotes 4 e 5 pendentes, mas o 4 chegou ao banco logo
    antes da queda: a retomada tira 4 e 5 do banco (voltam a ser gravados
    uma vez só pelos pendentes)."""
    import pickle

    for lote in range(1, 6):
        B.gravar_lote(busca, lote, [{"teste_n": lote, "casa": "c", "combo": f"k{lote}",
                                     "objetivo": 1.0, "valida": True}], [], [], {})
    b = M.Busca(busca, avaliar=Falso())
    s = b._novo()
    s.update(lote_n=5, pendentes=[{"lote_n": 4}, {"lote_n": 5}])
    with open(B.pasta_da(busca) / "arquivo.pkl", "wb") as f:
        pickle.dump(s, f)
    b._carregar()
    assert sorted(c["teste_n"] for c in B.ler_combos(busca)) == [1, 2, 3]


def test_reagrupa_ao_parar_e_de_tempos_em_tempos(busca, monkeypatch):
    monkeypatch.setattr(M, "REAGRUPAR_A_CADA_S", 0.0)
    M.escrever_json(B.pasta_da(busca) / "controle.json",
                    {"parar_as_ligado": False, "nucleos": 3, "limite": 400})
    M.Busca(busca, avaliar=Falso()).rodar()
    b = B.ler_busca(busca)
    gs = B.ler_grupos(busca)
    assert b["versao_grupos"] >= 2 and gs
    validas = {e["casa"] for e in B.ler_elites(busca) if e["valida"]}
    assert {c for g in gs for c in g["casas"]} == validas
    est = M.ler_json(B.pasta_da(busca) / "estado.json")
    assert est["versao_grupos"] == b["versao_grupos"]



def test_erro_no_agrupamento_nao_derruba_a_busca(busca, monkeypatch):
    from core.busca import grupos

    def quebra(*a, **k):
        raise MemoryError("grupos demais")

    monkeypatch.setattr(grupos, "agrupar", quebra)
    monkeypatch.setattr(M, "REAGRUPAR_A_CADA_S", 0.0)
    M.escrever_json(B.pasta_da(busca) / "controle.json",
                    {"parar_as_ligado": False, "nucleos": 3, "limite": 300})
    assert M.Busca(busca, avaliar=Falso()).rodar() == "concluida"
    assert B.ler_busca(busca)["status"] == "concluida"


def test_elite_guarda_o_hash_dos_trades(busca):
    M.Busca(busca, avaliar=Falso()).rodar(max_lotes=1)
    assert all(e["trades_hash"] for e in B.ler_elites(busca))
