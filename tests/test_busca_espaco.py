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
    esp = Espaco("adx_direcao", "WIN$N", fechamento="12:00")
    for x in np.random.default_rng(2).random((500, esp.n_genes)):
        assert esp.decodificar(x).fim <= "12:00"


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
