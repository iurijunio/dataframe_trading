"""Catálogo da busca automática: o que ela varre vem de uma declaração, não
de código espalhado — parâmetro novo entra sozinho."""
import pytest

from core.busca import catalogo as C


def _por_nome(estrategia, simbolo):
    return {i.nome: i for i in C.montar_catalogo(estrategia, simbolo)}


def test_degraus_proporcionais():
    v = C.degraus_proporcionais(2, 300)
    assert v[:12] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    assert C.degraus_proporcionais(250, 300)[:2] == [250, 270]
    # lá em cima o passo é de ~8%, nunca mais de 9%
    for a, b in zip(v, v[1:]):
        assert b - a <= max(1, round(a * 0.09)), (a, b)
    assert v[-1] == 300 and v == sorted(set(v)) and len(v) < 80


def test_degraus_proporcionais_a_partir_de_zero():
    assert C.degraus_proporcionais(0, 4) == [0, 1, 2, 3, 4]


def test_catalogo_adx_tem_os_itens_do_prototipo():
    cat = _por_nome("adx_direcao", "WIN$N")
    assert {"timeframe", "direcao", "janela", "dias", "stop", "alvo",
            "di_periodo", "adx_suavizacao", "amplitude_max", "saida"} == set(cat)
    assert cat["di_periodo"].degrau == cat["adx_suavizacao"].degrau == "proporcional"
    assert cat["amplitude_max"].degrau == "fixo"


def test_estrategia_de_abertura_sem_regua_movel():
    assert "abertura" not in _por_nome("rompimento_ema_abertura", "MES")
    assert "saida" not in _por_nome("rompimento_abertura", "WIN$N")


def test_camadas():
    cat = _por_nome("adx_direcao", "WIN$N")
    assert cat["di_periodo"].camada == cat["timeframe"].camada == "essencial"
    assert cat["saida"].camada == "essencial"
    for nome in ("janela", "dias", "direcao", "stop", "alvo"):
        assert cat[nome].camada == "filtro", nome


def test_faixa_do_ativo_manda_sobre_o_schema():
    cat = _por_nome("adx_direcao", "MES")
    assert cat["amplitude_max"].padrao == {"de": 5, "ate": 80, "passo": 5}
    # o WIN não tem faixas: vale o schema
    assert _por_nome("adx_direcao", "WIN$N")["amplitude_max"].padrao == \
        {"de": 0, "ate": 10000, "passo": 5}


def test_mes_stop_e_alvo_do_ativo_e_janela_ny():
    cat = _por_nome("adx_direcao", "MNQ")
    assert cat["stop"].padrao["tipos"]["pontos"] == {"on": True, "de": 15, "ate": 90, "passo": 5}
    assert cat["alvo"].padrao["tipos"]["pontos"] == {"on": True, "de": 30, "ate": 180, "passo": 10}
    assert cat["janela"].padrao == {"de": "09:30", "ate": "16:00", "passo": 30, "minima": 30}
    assert _por_nome("adx_direcao", "WIN$N")["janela"].padrao["de"] == "09:00"


def test_timeframes_do_prototipo():
    tf = _por_nome("adx_direcao", "WIN$N")["timeframe"].padrao
    assert tf["valores"] == ["M1", "M2", "M3", "M5", "M10", "M15", "M30", "H1"]
    assert tf["ligados"] == ["M2", "M3", "M5", "M10", "M15", "M30"]


def test_valores_de_cada_tipo():
    cat = _por_nome("adx_direcao", "WIN$N")
    assert C.valores(cat["di_periodo"], {"de": 2, "ate": 5})[:4] == [2, 3, 4, 5]
    assert C.valores(cat["amplitude_max"], {"de": 0, "ate": 20, "passo": 5}) == [0, 5, 10, 15, 20]
    assert C.valores(cat["direcao"], {"ligados": ["compra", "ambas"]}) == ["compra", "ambas"]
    assert C.valores(cat["saida"], cat["saida"].padrao) == [0, 1, 2]
    assert C.valores(cat["janela"], {"de": "09:00", "ate": "10:00", "passo": 30,
                                      "minima": 30}) == ["09:00", "09:30", "10:00"]
    dias = C.valores(cat["dias"], cat["dias"].padrao)
    assert len(dias) == 31 and (2, 3, 4) in dias and dias[0] == (1,)
    stop = C.valores(cat["stop"], cat["stop"].padrao)
    assert stop["atr"][:3] == [0.5, 0.75, 1.0] and stop["atr"][-1] == 3.0


def test_faixa_decimal_nao_perde_o_ultimo_valor():
    cat = _por_nome("adx_direcao", "WIN$N")
    alvo = C.valores(cat["alvo"], {"tipos": {"multiplicador": {"on": True, "de": 1.0,
                                                               "ate": 2.3, "passo": 0.1}}})
    assert alvo["multiplicador"][-1] == 2.3 and len(alvo["multiplicador"]) == 14


def test_sem_alvo_e_tipo_desligado():
    cat = _por_nome("adx_direcao", "WIN$N")
    padrao = cat["alvo"].padrao["tipos"]
    assert padrao["sem"]["on"] is False and padrao["percentual"]["on"] is False
    assert C.valores(cat["alvo"], {"tipos": {"sem": {"on": True}}}) == {"sem": [0]}


def test_faixa_nao_fura_o_schema():
    cat = _por_nome("adx_direcao", "WIN$N")
    assert C.valores(cat["di_periodo"], {"de": 0, "ate": 500})[0] == 2
    assert C.valores(cat["di_periodo"], {"de": 0, "ate": 500})[-1] == 100


def test_parametro_novo_entra_sozinho(monkeypatch):
    from strategies import registry

    mod = registry.carregar("adx_direcao")
    novo = {**mod.params_schema, "preco_medio": {"label": "Preço médio", "default": 0,
                                                 "min": 0, "max": 3, "step": 1, "tipo": "int"}}
    monkeypatch.setattr(mod, "params_schema", novo)
    cat = _por_nome("adx_direcao", "WIN$N")
    assert cat["preco_medio"].camada == "essencial"
    assert C.valores(cat["preco_medio"], cat["preco_medio"].padrao) == [0, 1, 2, 3]


def test_declaracao_no_modulo_tem_prioridade(monkeypatch):
    from strategies import registry

    mod = registry.carregar("adx_direcao")
    monkeypatch.setattr(mod, "busca", {"proporcional": ["amplitude_max"]}, raising=False)
    assert _por_nome("adx_direcao", "WIN$N")["amplitude_max"].degrau == "proporcional"
