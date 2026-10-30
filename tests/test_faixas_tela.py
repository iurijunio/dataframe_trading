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

from dash import no_update  # noqa: E402

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
