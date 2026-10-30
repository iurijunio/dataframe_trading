"""Os parâmetros da estratégia nascem na escala do ativo escolhido.

O filtro de amplitude do WIN anda de 50 em 50 pontos até 3.000; no MES isso
é metade do índice. A tela tem que montar os campos com as faixas da ficha do
ativo (`faixas_do_ativo`), sem que uma mineração carregada perca para elas e
sem que o WIN mude um caractere sequer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dash import ALL, no_update  # noqa: E402

from core import ativo as ativo_mod  # noqa: E402
from core import optimizer  # noqa: E402
from core.optimizer import MINERACAO  # noqa: E402
from scripts import referencia_telas as R  # noqa: E402
from strategies import registry  # noqa: E402
from ui import callbacks as CB  # noqa: E402
from ui.components import controls  # noqa: E402


def _inputs(no, saida=None):
    """Todos os dcc.Input de id-dicionário da árvore, por (p, k)."""
    saida = {} if saida is None else saida
    if isinstance(no, (list, tuple)):
        for x in no:
            _inputs(x, saida)
        return saida
    ident = getattr(no, "id", None)
    if isinstance(ident, dict) and ident.get("type") in ("val", "opt"):
        saida[(ident["p"], ident.get("k", "valor"))] = no
    filhos = getattr(no, "children", None)
    if filhos is not None:
        _inputs(filhos, saida)
    return saida


def _ligado(campos, p):
    def busca(no):
        if isinstance(no, (list, tuple)):
            return next((r for r in map(busca, no) if r is not None), None)
        ident = getattr(no, "id", None)
        if isinstance(ident, dict) and ident == {"type": "opt-on", "p": p}:
            return no.value
        filhos = getattr(no, "children", None)
        return busca(filhos) if filhos is not None else None
    return busca(campos)


def _faixa(campos, p):
    i = _inputs(campos)
    return {k: i[(p, k)].value for k in ("valor", "de", "passo", "ate")}


def _steps(campos, p):
    i = _inputs(campos)
    return {k: i[(p, k)].step for k in ("valor", "de", "ate")}


def _canonico(campos):
    return R._jsonavel([R._c(c) for c in campos])


def _referencia(chave):
    dados = json.loads((R.PASTA / "parametros.json").read_text(encoding="utf-8"))
    return dados[chave]


def _r_vazio(n_val=0, n_faixa=0, n_on=0):
    r = [no_update] * (17 + len(CB.CAMPOS_PERFIL))
    r[9:12] = ([no_update] * n_val, [no_update] * n_faixa, [no_update] * n_on)
    return r


@pytest.fixture(autouse=True)
def _isola(monkeypatch):
    """Nada daqui pode deixar estratégia trocada ou mineração esquecida."""
    monkeypatch.setattr(registry, "_atual", registry._atual)
    monkeypatch.setattr(MINERACAO, "estado", dict(MINERACAO.estado))


@pytest.fixture
def espiao(monkeypatch):
    chamadas = []
    monkeypatch.setattr(MINERACAO, "esquecer", lambda: chamadas.append("esquecer"))
    monkeypatch.setattr(MINERACAO, "parar", lambda: chamadas.append("parar"))
    return chamadas


# --------------------------------------------------------- campos_da_estrategia
def test_canal_no_mes_usa_a_faixa_do_ativo_com_step_1():
    canal = registry.carregar("rompimento_canal")
    campos = controls.campos_da_estrategia(
        canal, None, ativo_mod.faixas_do_ativo("MES", "rompimento_canal"))
    assert _faixa(campos, "filtro_amplitude") == {"valor": 0, "de": 0,
                                                  "passo": 2, "ate": 80}
    assert _steps(campos, "filtro_amplitude") == {"valor": 1, "de": 1, "ate": 1}


def test_parametro_sem_faixa_do_ativo_fica_com_o_step_do_schema():
    canal = registry.carregar("rompimento_canal")
    campos = controls.campos_da_estrategia(
        canal, None, ativo_mod.faixas_do_ativo("MES", "rompimento_canal"))
    passo = canal.params_schema["periodo_canal"]["step"]
    assert _steps(campos, "periodo_canal") == {"valor": passo, "de": passo,
                                               "ate": passo}


def test_mineracao_carregada_vence_a_faixa_do_ativo():
    canal = registry.carregar("rompimento_canal")
    mina = {"filtro_amplitude": {"valor": 100, "de": 50, "passo": 50,
                                 "ate": 300, "on": True}}
    campos = controls.campos_da_estrategia(
        canal, mina, ativo_mod.faixas_do_ativo("MES", "rompimento_canal"))
    assert _faixa(campos, "filtro_amplitude") == {"valor": 100, "de": 50,
                                                  "passo": 50, "ate": 300}
    assert _ligado(campos, "filtro_amplitude") == ["on"]


def test_prioridade_e_chave_por_chave():
    canal = registry.carregar("rompimento_canal")
    campos = controls.campos_da_estrategia(
        canal, {"filtro_amplitude": {"valor": 4}},
        ativo_mod.faixas_do_ativo("MES", "rompimento_canal"))
    assert _faixa(campos, "filtro_amplitude") == {"valor": 4, "de": 0,
                                                  "passo": 2, "ate": 80}


def test_adx_no_mes():
    adx = registry.carregar("adx_direcao")
    campos = controls.campos_da_estrategia(
        adx, None, ativo_mod.faixas_do_ativo("MES", "adx_direcao"))
    assert _faixa(campos, "amplitude_max") == {"valor": 25, "de": 5,
                                               "passo": 5, "ate": 80}


def test_valor_none_cai_na_faixa_do_ativo_ou_no_default_sem_erro():
    adx = registry.carregar("adx_direcao")
    nulo = {"amplitude_max": {"valor": None}}
    com = controls.campos_da_estrategia(
        adx, nulo, ativo_mod.faixas_do_ativo("MES", "adx_direcao"))
    assert _faixa(com, "amplitude_max")["valor"] == 25
    sem = controls.campos_da_estrategia(adx, nulo)
    meta = adx.params_schema["amplitude_max"]
    assert _faixa(sem, "amplitude_max") == {
        "valor": meta["default"], "de": meta["min"], "passo": meta["step"],
        "ate": controls._ate_padrao(meta, meta["default"])}


def test_cruzamento_no_mes_igual_a_hoje():
    cruz = registry.carregar("setup_cruzamento")
    no_mes = controls.campos_da_estrategia(
        cruz, None, ativo_mod.faixas_do_ativo("MES", "setup_cruzamento"))
    assert _canonico(no_mes) == _referencia("campos.setup_cruzamento")


@pytest.mark.parametrize("vazio", [None, {}])
def test_sem_faixa_do_ativo_a_saida_e_a_de_hoje(vazio):
    for e in registry.descobrir():
        mod = registry.carregar(e["modulo"])
        assert _canonico(controls.campos_da_estrategia(mod, None, vazio)) \
            == _referencia(f"campos.{e['modulo']}"), e["modulo"]


# ------------------------------------------------------------ troca de estratégia
def test_trocar_estrategia_usa_as_faixas_do_ativo(espiao):
    r = CB._trocar_estrategia("rompimento_canal", _r_vazio(), simbolo="MES")
    assert _faixa(r[2], "filtro_amplitude") == {"valor": 0, "de": 0,
                                                "passo": 2, "ate": 80}


def test_trocar_estrategia_no_win_igual_a_referencia(espiao):
    r = CB._trocar_estrategia("rompimento_canal", _r_vazio(), simbolo="WIN$N")
    assert _canonico(r[2]) == _referencia("campos.rompimento_canal")


# --------------------------------------------------------------- troca de ativo
def test_trocar_ativo_sem_mineracao_reconstroi_a_secao(espiao):
    MINERACAO.estado.update(rodando=False, trials=[])
    r = CB._estrategia_ou_mineracao("ativo", "rompimento_canal", None, "MES",
                                    [], [], [])
    assert _faixa(r[2], "filtro_amplitude")["ate"] == 80
    # só a seção: estratégia, seletor da mineração e resultados ficam
    assert r[0] is no_update and r[1] is no_update
    assert all(x is no_update for x in r[3:9])
    assert espiao == []


@pytest.mark.parametrize("estado", [{"rodando": True, "trials": []},
                                    {"rodando": False, "trials": [{"x": 1}]}])
def test_trocar_ativo_com_mineracao_na_tela_nao_mexe(espiao, estado):
    MINERACAO.estado.update(estado)
    assert CB._mineracao_na_tela()
    r = CB._estrategia_ou_mineracao("ativo", "rompimento_canal", None, "MES",
                                    [{"p": "a"}], [], [])
    assert r[2] is no_update
    assert r == _r_vazio(1)
    assert espiao == []


def test_sem_mineracao_nada_na_tela():
    MINERACAO.estado.update(rodando=False, trials=[])
    assert not CB._mineracao_na_tela()


def test_gatilho_da_estrategia_passa_o_ativo(espiao):
    r = CB._estrategia_ou_mineracao("estrategia", "rompimento_canal", None,
                                    "MES", [], [], [])
    assert _faixa(r[2], "filtro_amplitude")["ate"] == 80
    assert espiao == ["esquecer"]


# ------------------------------------------------------- carregar mineração salva
def test_mineracao_do_mes_usa_as_faixas_do_mes_com_seletor_no_win(monkeypatch):
    d = {"estrategia": "rompimento_canal", "symbol": "MES", "nome": "",
         "espaco": {"periodo_canal": [40, 50, 60]}, "perfil": {},
         "wf_config": {}}
    monkeypatch.setattr(optimizer, "detalhes_salva", lambda run_id: d)
    r = CB._carregar_mineracao(7, [], [], [], _r_vazio())
    assert _faixa(r[2], "filtro_amplitude") == {"valor": 0, "de": 0,
                                                "passo": 2, "ate": 80}
    # o que a mineração varreu continua mandando
    assert _faixa(r[2], "periodo_canal") == {"valor": 40, "de": 40,
                                             "passo": 10, "ate": 60}


def test_mineracao_do_win_carrega_igual_a_hoje(monkeypatch):
    d = {"estrategia": "rompimento_canal", "symbol": "WIN$N", "nome": "",
         "espaco": {"filtro_amplitude": [4, 6, 8, 10, 12]}, "perfil": {},
         "wf_config": {}}
    monkeypatch.setattr(optimizer, "detalhes_salva", lambda run_id: d)
    r = CB._carregar_mineracao(7, [], [], [], _r_vazio())
    canal = registry.carregar("rompimento_canal")
    esperado = controls.campos_da_estrategia(
        canal, optimizer.faixas_do_espaco(d["espaco"]))
    assert _canonico(r[2]) == _canonico(esperado)


# ------------------------------------------- camada 4: stop, alvo e trailing
def _c4(simbolo):
    """{(campo, chave): valor} de `_camada4_do_ativo`, com `step` por célula."""
    saida = {}
    for (ident, prop, chave), v in zip(CB.SAIDAS_C4,
                                       CB._camada4_do_ativo(simbolo)):
        celula = ident.get("k", "valor")
        saida[(ident["p"], chave if prop == "value" else f"step_{celula}")] = v
    return saida


def _campo_c4(saida, campo):
    return {k: saida[(campo, k)] for k in ("valor", "de", "passo", "ate",
                                           "step_valor", "step_de",
                                           "step_passo", "step_ate")}


TABELA_C4 = {
    "MES": {"stop_pontos": (8, 3, 1, 16), "alvo_pontos": (16, 6, 2, 32),
            "trailing_pontos": (0, 0, 2, 14)},
    "MNQ": {"stop_pontos": (45, 15, 5, 90), "alvo_pontos": (90, 30, 10, 180),
            "trailing_pontos": (0, 0, 10, 80)},
}


@pytest.mark.parametrize("simbolo", ["MES", "MNQ"])
def test_camada4_no_micro_segue_a_tabela_com_step_1(simbolo):
    MINERACAO.estado.update(rodando=False, trials=[])
    saida = _c4(simbolo)
    for campo, (valor, de, passo, ate) in TABELA_C4[simbolo].items():
        assert _campo_c4(saida, campo) == {
            "valor": valor, "de": de, "passo": passo, "ate": ate,
            "step_valor": 1, "step_de": 1, "step_passo": 1,
            "step_ate": 1}, campo


def test_camada4_no_win_volta_ao_padrao_de_hoje():
    MINERACAO.estado.update(rodando=False, trials=[])
    saida = _c4("WIN$N")
    for campo, (valor, de, passo, ate, step) in controls.PADRAO_C4.items():
        assert _campo_c4(saida, campo) == {
            "valor": valor, "de": de, "passo": passo, "ate": ate,
            "step_valor": step, "step_de": step, "step_passo": step,
            "step_ate": step}, campo


def test_padrao_c4_sao_os_literais_de_hoje():
    assert controls.PADRAO_C4 == {
        "alvo_pontos": (600, 200, 100, 1200, 10),
        "stop_pontos": (300, 100, 50, 600, 10),
        "trailing_pontos": (0, 0, 50, 500, 10)}


@pytest.mark.parametrize("estado", [{"rodando": True, "trials": []},
                                    {"rodando": False, "trials": [{"x": 1}]}])
def test_camada4_com_mineracao_na_tela_nao_mexe(estado):
    MINERACAO.estado.update(estado)
    r = CB._camada4_do_ativo("MES")
    assert len(r) == len(CB.SAIDAS_C4)
    assert all(x is no_update for x in r)


def test_camada4_cobre_valor_faixa_e_step_dos_tres_campos():
    pares = {(ident.get("k", "valor"), ident["p"], prop)
             for ident, prop, _ in CB.SAIDAS_C4}
    assert len(pares) == len(CB.SAIDAS_C4) == 24
    for campo in ("stop_pontos", "alvo_pontos", "trailing_pontos"):
        for k in ("valor", "de", "passo", "ate"):
            assert (k, campo, "value") in pares
            # toda caixa, a do passo inclusive, como `controls._opt` (step
            # único por campo): o passo de mineração vai só no valor dela
            assert (k, campo, "step") in pares


# ------------------------------------------------- saídas sem conflito no app
@pytest.fixture
def app(_banco_isolado):
    from core import db_manager as db
    from ui.app import build
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        for i in range(10):
            con.execute(
                "INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 09:00:00'"
                f" + INTERVAL {i} MINUTE, 100, 101, 99, 100, 1)")
    return build()


def _ident(cid):
    if isinstance(cid, str) and cid.startswith("{"):
        return json.loads(cid)
    return cid


def _curinga(v):
    return v is ALL or v == ["ALL"]


def _coincidem(a, b):
    """Mesmo id contando ALL como curinga (a regra do Dash para sobreposição)."""
    if isinstance(a, dict) != isinstance(b, dict):
        return False
    if not isinstance(a, dict):
        return a == b
    if set(a) != set(b):
        return False
    return all(_curinga(a[k]) or _curinga(b[k]) or a[k] == b[k] for k in a)


def _e_all(ident):
    return isinstance(ident, dict) and any(map(_curinga, ident.values()))


def test_saidas_dos_callbacks_do_ativo_sem_conflito(app):
    saidas = []  # (callback, id, propriedade, allow_duplicate)
    for chave, cb in app.callback_map.items():
        if not any(i["id"] == "ativo" for i in cb["inputs"]):
            continue
        outs = cb["output"] if isinstance(cb["output"], list) else [cb["output"]]
        for o in outs:
            if isinstance(o, str):  # saída única guardada como texto
                cid, prop = o.split("@")[0].rsplit(".", 1)
                saidas.append((chave, _ident(cid), prop, "@" in o))
            else:
                saidas.append((chave, _ident(o.component_id),
                               o.component_property, o.allow_duplicate))
    assert any(_ident(s[1]) == {"type": "val", "p": "trailing_pontos"}
               for s in saidas)
    for i, a in enumerate(saidas):
        for b in saidas[i + 1:]:
            if a[2] != b[2] or not _coincidem(a[1], b[1]):
                continue
            # no mesmo callback, nunca; entre dois, só com allow_duplicate —
            # e quem coincide com uma ALL de outro é quem duplica (perfil e
            # `estrategia_ou_mineracao` já dividiam e-ent-ini & cia. assim)
            assert a[0] != b[0], (a, b)
            if _e_all(a[1]) or _e_all(b[1]):
                especifica = b if _e_all(a[1]) else a
                assert especifica[3], (a, b)
            else:
                assert a[3] or b[3], (a, b)
