"""Espaço da busca: vetor da pyribs <-> combinação <-> perfil do motor."""
import numpy as np
import pytest

from core import ativo
from core.busca import catalogo as C
from core.busca.espaco import Combinacao, Espaco
from core.engine.execution import ExecutionProfile

PERFIL_BASE = ExecutionProfile(corretagem_por_contrato=0.5, fechamento="17:30",
                               stop_atr_periodo=14).to_config()


@pytest.fixture
def espaco():
    return Espaco("adx_direcao", "WIN$N", fechamento="17:30")


def _min_motor(h, f):
    return ativo.hora_para_minuto(ativo.hora_para_motor(h, f) if f else h)


def test_pontas_do_vetor(espaco):
    assert espaco.decodificar(np.zeros(espaco.n_genes)).timeframe == "M2"
    # a pyribs corta nos limites: x = 1,0 acontece e não pode estourar
    c = espaco.decodificar(np.ones(espaco.n_genes))
    assert c.timeframe == "M30" and c.direcao == "ambas"


def test_decodificar_e_deterministico(espaco):
    x = np.random.default_rng(3).random(espaco.n_genes)
    assert espaco.decodificar(x) == espaco.decodificar(x.copy())


@pytest.mark.parametrize("simbolo,fech", [("WIN$N", "17:30"), ("MES", "16:50")])
def test_janela_sempre_valida(simbolo, fech):
    esp = Espaco("adx_direcao", simbolo, fechamento=fech)
    f = None if simbolo == "WIN$N" else ativo.ficha(simbolo)
    for x in np.random.default_rng(1).random((3000, esp.n_genes)):
        c = esp.decodificar(x)
        assert _min_motor(c.fim, f) - _min_motor(c.ini, f) >= 30
        assert ativo.janela_valida(c.ini, c.fim, f, fech) is None


def test_janela_respeita_o_fechamento():
    # busca antiga: o fechamento do menu manda
    esp = Espaco("adx_direcao", "WIN$N", fechamento="12:00", com_extras=False)
    for x in np.random.default_rng(2).random((500, esp.n_genes)):
        assert esp.decodificar(x).fim <= "12:00"
    # fechamento minerado: cada combinação fecha no seu, nunca antes do fim
    esp = Espaco("adx_direcao", "WIN$N", fechamento="12:00",
                 faixas={"fechamento": {"de": "09:00", "ate": "12:00"}})
    for x in np.random.default_rng(2).random((500, esp.n_genes)):
        c = esp.decodificar(x)
        assert c.fim <= dict(c.extras)["fechamento"] <= "12:00"


def test_cobre_todos_os_valores(espaco):
    vistos = {"timeframe": set(), "dias": set(), "stop_tipo": set(), "alvo_tipo": set()}
    for x in np.random.default_rng(5).random((5000, espaco.n_genes)):
        c = espaco.decodificar(x)
        vistos["timeframe"].add(c.timeframe)
        vistos["dias"].add(c.dias)
        vistos["stop_tipo"].add(c.stop_tipo)
        vistos["alvo_tipo"].add(c.alvo_tipo)
    assert vistos["timeframe"] == set(C.TIMEFRAMES_LIGADOS)
    assert len(vistos["dias"]) == 31
    assert vistos["stop_tipo"] == {"pontos", "atr", "percentual"}
    assert vistos["alvo_tipo"] == {"pontos", "multiplicador", "atr"}


def _comb(**kw):
    base = dict(timeframe="M5", ini="10:00", fim="11:30", dias=(2, 4), direcao="compra",
                stop_tipo="atr", stop_valor=1.5, alvo_tipo="multiplicador", alvo_valor=2.0,
                params=(("adx_suavizacao", 14), ("amplitude_max", 1000),
                        ("di_periodo", 14), ("saida", 1)))
    return Combinacao(**{**base, **kw})


def test_perfil_igual_ao_do_menu(espaco):
    p = espaco.perfil(_comb(), PERFIL_BASE)
    assert (p.timeframe, p.entrada_inicio, p.entrada_fim) == ("M5", "10:00", "11:30")
    assert tuple(p.dias_semana) == (2, 4) and p.direcao == "compra"
    assert (p.stop_tipo, p.stop_atr_mult, p.stop_atr_periodo) == ("atr", 1.5, 14)
    assert (p.alvo_tipo, p.alvo_razao) == ("multiplicador", 2.0)
    assert p.corretagem_por_contrato == 0.5 and p.fechamento == "17:30"


def test_perfil_stop_pontos_e_sem_alvo(espaco):
    p = espaco.perfil(_comb(stop_tipo="pontos", stop_valor=250, alvo_tipo="sem",
                            alvo_valor=0), PERFIL_BASE)
    assert (p.stop_tipo, p.stop_pontos) == ("pontos", 250)
    assert (p.alvo_tipo, p.alvo_pontos) == ("pontos", 0)
    p = espaco.perfil(_comb(stop_tipo="percentual", stop_valor=0.2,
                            alvo_tipo="percentual", alvo_valor=0.4), PERFIL_BASE)
    assert (p.stop_pct, p.alvo_pct) == (0.2, 0.4)


def test_params_e_chaves(espaco):
    c = _comb()
    assert espaco.params(c) == {"adx_suavizacao": 14, "amplitude_max": 1000,
                                "di_periodo": 14, "saida": 1}
    assert c.chave_essencial() == ("M5", c.params)
    assert _comb(ini="09:30").chave_essencial() == c.chave_essencial()
    assert _comb(ini="09:30").chave() != c.chave()


def test_casa_e_dimensoes(espaco):
    dims = espaco.dims_arquivo()
    assert len(dims) == 5
    for x in np.random.default_rng(4).random((500, espaco.n_genes)):
        casa = espaco.casa(espaco.decodificar(x))
        assert all(0 <= i < n for i, n in zip(casa, dims))


def test_dimensoes_configuraveis():
    esp = Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                 dims_nicho=("timeframe", "di_periodo"))
    assert esp.dims_arquivo()[0] == len(C.TIMEFRAMES_LIGADOS) and len(esp.dims_arquivo()) == 2


def test_genes_essenciais(espaco):
    m = espaco.genes_essenciais()
    assert m.dtype == bool and m.sum() == 1 + 4   # tempo + 4 parâmetros


def test_json_ida_e_volta(espaco):
    x = np.random.default_rng(9).random(espaco.n_genes)
    de_novo = Espaco.de_json(espaco.para_json())
    assert de_novo.decodificar(x) == espaco.decodificar(x)


def test_faixa_da_tela_muda_a_lista():
    esp = Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                 faixas={"timeframe": {"ligados": ["M5"]},
                         "direcao": {"ligados": ["venda"]}})
    for x in np.random.default_rng(6).random((200, esp.n_genes)):
        c = esp.decodificar(x)
        assert (c.timeframe, c.direcao) == ("M5", "venda")



def test_periodo_do_atr_entra_na_combinacao_e_no_perfil(espaco):
    vistos = set()
    for x in np.random.default_rng(8).random((3000, espaco.n_genes)):
        c = espaco.decodificar(x)
        if c.stop_tipo == "atr":
            assert c.stop_atr_periodo in espaco.stop_periodos
            vistos.add(c.stop_atr_periodo)
            p = espaco.perfil(c, PERFIL_BASE)
            assert p.stop_atr_periodo == c.stop_atr_periodo
        else:
            assert c.stop_atr_periodo is None
    assert len(vistos) > 5


def test_busca_antiga_reabre_sem_o_periodo(espaco):
    """Busca gravada antes do período do ATR: mesmo vetor, mesma chave."""
    antigo = {k: v for k, v in espaco.para_json().items() if k != "com_periodo_atr"}
    velho = Espaco.de_json(antigo)
    assert velho.n_genes == espaco.n_genes - 2 and velho.stop_periodos is None
    c = velho.decodificar(np.full(velho.n_genes, 0.3))
    assert "stop_atr_periodo" not in c.chave() and Combinacao.de_chave(c.chave()) == c



def test_extras_viram_perfil_e_fechamento_depois_das_entradas(espaco):
    for x in np.random.default_rng(12).random((2000, espaco.n_genes)):
        c = espaco.decodificar(x)
        p = espaco.perfil(c, PERFIL_BASE)
        e = dict(c.extras)
        assert set(e) == set(espaco.nomes_extras)
        assert p.fechamento >= p.entrada_fim                    # WIN: mesma ordem
        assert (p.max_barras, p.breakeven_pct) == (e["max_barras"], e["breakeven_pct"])


def test_busca_antiga_reabre_sem_extras(espaco):
    antigo = {k: v for k, v in espaco.para_json().items() if k != "com_extras"}
    velho = Espaco.de_json(antigo)
    assert velho.nomes_extras == [] and velho.n_genes == espaco.n_genes - len(espaco.nomes_extras)
    c = velho.decodificar(np.full(velho.n_genes, 0.4))
    assert "extras" not in c.chave() and Combinacao.de_chave(c.chave()) == c


def test_fechamento_invalido_sai_da_faixa():
    try:
        esp = Espaco("adx_direcao", "MES", fechamento="16:50",
                     faixas={"fechamento": {"de": "09:30", "ate": "17:30", "passo": 30}})
    except FileNotFoundError:
        pytest.skip("sem ficha do MES")
    vals = esp.extras_vals["fechamento"]
    assert "17:30" not in vals and "17:00" in vals      # 17:30 cai na pausa da CME


# ------------------------------------------------ ajustes de 04/11/2026
ADX = ("adx_periodo", "adx_limiar", "adx_filtro_di", "adx_subindo")


def test_busca_nova_sem_adx_nem_sem_entradas(espaco):
    """Saíram da busca (04/11/2026): valem o do menu."""
    fora = {"sem_entrada1", "sem_entrada2", "sem_entrada3", "filtro_adx", *ADX}
    assert not (fora & set(espaco.nomes_extras))
    base = {**PERFIL_BASE, "adx_periodo": 14, "adx_limiar": 20, "sem_entrada1": "10:00"}
    for x in np.random.default_rng(23).random((100, espaco.n_genes)):
        p = espaco.perfil(espaco.decodificar(x), base)
        assert (p.adx_periodo, p.adx_limiar, p.sem_entrada1) == (14, 20, "10:00")


def test_sem_stop_vira_stop_zero():
    esp = Espaco("reversao_rsi", "WIN$N", fechamento="17:30",
                 faixas={"stop": {"tipos": {"sem": {"on": True}}}})
    assert esp.stops == {"sem": [0]}
    for x in np.random.default_rng(24).random((50, esp.n_genes)):
        c = esp.decodificar(x)
        p = esp.perfil(c, PERFIL_BASE)
        assert c.stop_tipo == "sem" and (p.stop_tipo, p.stop_pontos) == ("pontos", 0)
        assert Combinacao.de_chave(c.chave()) == c


def _antigo(**kw):
    """Busca gravada quando o ADX e "sem entradas" ainda eram varridos."""
    from core.busca.espaco import EXTRAS_04_11
    return Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                  nomes_extras=list(EXTRAS_04_11), **kw)


def test_padrao_sem_entradas_e_adx_desligados():
    espaco = _antigo()
    v = espaco.extras_vals
    for n in ("sem_entrada1", "sem_entrada2", "sem_entrada3"):
        assert v[n] == [""], n
    assert v["filtro_adx"] == ["tendencia"]
    for n in ADX:
        assert v[n] == [0], n
        assert "x:" + n in espaco._genes        # mesmo número de genes
    for x in np.random.default_rng(21).random((300, espaco.n_genes)):
        e = dict(espaco.decodificar(x).extras)
        assert (e["adx_periodo"], e["adx_limiar"], e["sem_entrada1"]) == (0, 0, "")


def test_regua_desmarcada_ignora_as_faixas_do_adx():
    esp = _antigo(faixas={"filtro_adx": {"ligados": []},
                         "adx_periodo": {"de": 5, "ate": 30, "passo": 1},
                         "adx_limiar": {"de": 10, "ate": 40, "passo": 5},
                         "adx_filtro_di": {"ligados": [0, 1]}})
    assert all(esp.extras_vals[n] == [0] for n in ADX)
    assert esp.extras_vals["filtro_adx"] == ["tendencia"]


def test_regua_marcada_varre_o_adx():
    esp = _antigo(faixas={"filtro_adx": {"ligados": ["rango"]}})
    assert esp.extras_vals["filtro_adx"] == ["rango"]
    assert 0 in esp.extras_vals["adx_periodo"] and len(esp.extras_vals["adx_periodo"]) > 1


def test_sem_entrada_marcada_varre_as_horas():
    esp = _antigo(faixas={"sem_entrada1": {"ligados": ["", "10:00"]}})
    assert esp.extras_vals["sem_entrada1"] == ["", "10:00"]


def test_stop_movel_e_trailing_valem_o_do_menu(espaco):
    assert not (C.FORA_DA_BUSCA & set(espaco.nomes_extras))
    base = {**PERFIL_BASE, "step_gatilho_pct": 40.0, "step_distancia_pct": 10.0,
            "trailing_pontos": 150}
    for x in np.random.default_rng(22).random((200, espaco.n_genes)):
        p = espaco.perfil(espaco.decodificar(x), base)
        assert (p.step_gatilho_pct, p.step_distancia_pct, p.trailing_pontos) == (40.0, 10.0, 150)


def test_extras_gravados_reabrem_iguais(espaco):
    d = espaco.para_json()
    assert d["nomes_extras"] == espaco.nomes_extras
    de_novo = Espaco.de_json(d)
    assert de_novo.nomes_extras == espaco.nomes_extras and de_novo.n_genes == espaco.n_genes


def test_busca_de_hoje_cedo_reabre_com_stop_movel_e_trailing(espaco):
    """Criada antes de FORA_DA_BUSCA (com_extras, sem a lista gravada): os três
    campos seguem no vetor dela."""
    antigo = {k: v for k, v in espaco.para_json().items() if k != "nomes_extras"}
    velho = Espaco.de_json(antigo)
    assert C.FORA_DA_BUSCA <= set(velho.nomes_extras)
    assert velho.n_genes == espaco.n_genes + len(C.FORA_DA_BUSCA)
    c = velho.decodificar(np.full(velho.n_genes, 0.6))
    assert "trailing_pontos" in dict(c.extras) and Combinacao.de_chave(c.chave()) == c
