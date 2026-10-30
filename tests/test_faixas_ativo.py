"""Faixas de mineração por ativo (etapa 4, opção B): a ficha do micro guarda
valor, de, passo e até; a tela só lê. O WIN não tem faixas."""
from __future__ import annotations

import pytest

from core import ativo
from strategies import registry

# (ativo, estratégia, campo, valor, de, passo, até) — tabela aprovada em 30/10/2026
TABELA = [
    ("MES", None, "stop_pontos", 8, 3, 1, 16),
    ("MES", None, "alvo_pontos", 16, 6, 2, 32),
    ("MES", None, "trailing_pontos", 0, 0, 2, 14),
    ("MES", "rompimento_abertura", "filtro_amplitude", 0, 0, 2, 40),
    ("MES", "rompimento_canal", "filtro_amplitude", 0, 0, 2, 80),
    ("MES", "rompimento_ema_abertura", "distancia_abertura", 0, 0, 2, 80),
    ("MES", "adx_direcao", "amplitude_max", 25, 5, 5, 80),
    ("MNQ", None, "stop_pontos", 45, 15, 5, 90),
    ("MNQ", None, "alvo_pontos", 90, 30, 10, 180),
    ("MNQ", None, "trailing_pontos", 0, 0, 10, 80),
    ("MNQ", "rompimento_abertura", "filtro_amplitude", 0, 0, 10, 220),
    ("MNQ", "rompimento_canal", "filtro_amplitude", 0, 0, 10, 460),
    ("MNQ", "rompimento_ema_abertura", "distancia_abertura", 0, 0, 10, 400),
    ("MNQ", "adx_direcao", "amplitude_max", 150, 25, 25, 450),
]


@pytest.mark.parametrize("simbolo,estrategia,campo,valor,de,passo,ate", TABELA)
def test_tabela_aprovada(simbolo, estrategia, campo, valor, de, passo, ate):
    f = ativo.faixas_do_ativo(simbolo, estrategia)
    assert f[campo] == {"valor": valor, "de": de, "passo": passo, "ate": ate}


def test_sem_estrategia_so_traz_o_comum():
    assert set(ativo.faixas_do_ativo("MES")) == {
        "stop_pontos", "alvo_pontos", "trailing_pontos"}


def test_comum_e_da_estrategia_juntos():
    f = ativo.faixas_do_ativo("MNQ", "rompimento_canal")
    assert set(f) == {"stop_pontos", "alvo_pontos", "trailing_pontos",
                      "filtro_amplitude"}


@pytest.mark.parametrize("simbolo,estrategia", [
    ("WIN$N", "rompimento_canal"), ("WIN$N", None), (None, "rompimento_canal"),
    (None, None), ("XYZ", None), ("XYZ", "rompimento_canal")])
def test_sem_faixas_devolve_vazio(simbolo, estrategia):
    assert ativo.faixas_do_ativo(simbolo, estrategia) == {}


def test_estrategia_sem_bloco_so_traz_o_comum():
    f = ativo.faixas_do_ativo("MES", "setup_cruzamento")
    assert set(f) == {"stop_pontos", "alvo_pontos", "trailing_pontos"}


def test_devolve_copia():
    a = ativo.faixas_do_ativo("MES", "rompimento_canal")
    a["filtro_amplitude"]["ate"] = 999
    a["stop_pontos"]["valor"] = 999
    a["lixo"] = {}
    b = ativo.faixas_do_ativo("MES", "rompimento_canal")
    assert b["filtro_amplitude"]["ate"] == 80
    assert b["stop_pontos"]["valor"] == 8
    assert "lixo" not in b


def test_win_nao_tem_faixas_na_ficha():
    assert ativo.ficha("WIN$N").faixas is None


@pytest.mark.parametrize("simbolo", ["MES", "MNQ"])
def test_chaves_validas_contra_o_registro(simbolo):
    bloco = ativo.ficha(simbolo).faixas
    nomes = {e["modulo"] for e in registry.descobrir()}
    for estrategia, itens in bloco.items():
        if estrategia == "comum":
            assert set(itens) == {"stop_pontos", "alvo_pontos", "trailing_pontos"}
            continue
        assert estrategia in nomes
        schema = registry.carregar(estrategia).params_schema
        for param, f in itens.items():
            meta = schema[param]
            assert set(f) == {"valor", "de", "passo", "ate"}
            for k in ("valor", "de", "ate"):
                assert meta["min"] <= f[k] <= meta["max"], (estrategia, param, k)
            assert f["de"] <= f["ate"] and f["passo"] > 0


@pytest.mark.parametrize("simbolo,stop,alvo", [("MES", 8, 16), ("MNQ", 45, 90)])
def test_perfil_padrao_igual_ao_valor_das_faixas(simbolo, stop, alvo):
    p = ativo.perfil_padrao(ativo.ficha(simbolo))
    comum = ativo.ficha(simbolo).faixas["comum"]
    assert (p["stop_pontos"], p["alvo_pontos"]) == (stop, alvo)
    assert p["stop_pontos"] == comum["stop_pontos"]["valor"]
    assert p["alvo_pontos"] == comum["alvo_pontos"]["valor"]
