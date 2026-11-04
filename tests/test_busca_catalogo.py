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
            "di_periodo", "adx_suavizacao", "amplitude_max", "saida"} == \
        {n for n, i in cat.items() if i.onde != "extra"}
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


def test_stop_e_alvo_em_pontos_saem_do_padrao_da_ficha():
    """Mesma proporção em todo ativo: passo = padrão/6, até = padrão × 20/3
    (WIN 300/600 -> 50–2.000 e 100–4.000; MNQ 45/90; MES 8/16)."""
    def pontos(simbolo):
        cat = _por_nome("adx_direcao", simbolo)
        return (cat["stop"].padrao["tipos"]["pontos"], cat["alvo"].padrao["tipos"]["pontos"])

    st, al = pontos("WIN$N")
    assert (st["de"], st["ate"], st["passo"]) == (50, 2000, 50)
    assert (al["de"], al["ate"], al["passo"]) == (100, 4000, 100)
    st, al = pontos("MNQ")
    assert (st["de"], st["ate"], st["passo"]) == (8, 304, 8)
    assert (al["de"], al["ate"], al["passo"]) == (15, 600, 15)
    st, al = pontos("MES")
    assert (st["de"], st["ate"], st["passo"]) == (1, 53, 1)
    assert (al["de"], al["ate"], al["passo"]) == (3, 108, 3)


def test_janela_ny_nos_micros():
    cat = _por_nome("adx_direcao", "MNQ")
    assert cat["janela"].padrao == {"de": "09:30", "ate": "16:00", "passo": 30, "minima": 30}
    assert _por_nome("adx_direcao", "WIN$N")["janela"].padrao["de"] == "09:00"


def test_timeframes_espelham_o_motor():
    """Todo tempo gráfico do motor entra na busca sozinho (escala): nenhuma
    lista copiada à mão."""
    from core.engine.execution import TIMEFRAMES as MOTOR

    tf = _por_nome("adx_direcao", "WIN$N")["timeframe"].padrao
    assert set(tf["valores"]) == set(MOTOR)
    assert [MOTOR[t] for t in tf["valores"]] == sorted(MOTOR.values())
    assert tf["ligados"] == [t for t in tf["valores"] if 2 <= MOTOR[t] <= 30]
    assert {"M7", "M9", "M11", "M13", "M17", "M20", "H2", "H4"} <= set(tf["valores"])


def test_tipos_de_stop_e_alvo_espelham_o_menu():
    """Tipo novo de stop ou alvo no menu tem de entrar na busca também."""
    from ui.components.catalogo import OPCOES

    cat = _por_nome("adx_direcao", "WIN$N")
    assert set(cat["stop"].padrao["tipos"]) == {v for _r, v in OPCOES["stop_tipo"]}
    assert set(cat["alvo"].padrao["tipos"]) - {"sem"} == {v for _r, v in OPCOES["alvo_tipo"]}


def test_faixas_largas_no_win():
    cat = _por_nome("adx_direcao", "WIN$N")
    st, al = cat["stop"].padrao["tipos"], cat["alvo"].padrao["tipos"]
    assert (st["pontos"]["de"], st["pontos"]["ate"]) == (50, 2000)
    assert (al["pontos"]["de"], al["pontos"]["ate"]) == (100, 4000)
    assert (st["percentual"]["de"], st["percentual"]["ate"]) == (0.05, 1.5)
    assert (al["percentual"]["de"], al["percentual"]["ate"]) == (0.1, 3.0)


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
    assert stop["atr"][:3] == [0.25, 0.5, 0.75] and stop["atr"][-1] == 6.0


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



def test_atr_tem_periodo_proporcional():
    cat = _por_nome("adx_direcao", "WIN$N")
    for item in ("stop", "alvo"):
        per = C.periodos_atr(cat[item].padrao["tipos"]["atr"])
        assert per[0] == 5 and per[-1] == 60 and per == sorted(set(per))
    assert C.periodos_atr(cat["stop"].padrao["tipos"]["pontos"]) is None



def test_todo_campo_do_motor_esta_classificado():
    """Campo novo no motor quebra aqui até alguém dizer se a busca o varre."""
    from core.engine.execution import ExecutionProfile

    extras = {i.nome for i in C.montar_catalogo("adx_direcao", "WIN$N") if i.onde == "extra"}
    todos = set(ExecutionProfile.__dataclass_fields__)
    assert C.JA_NA_BUSCA | C.NAO_MINERAVEIS | extras == todos
    assert not (C.JA_NA_BUSCA & extras) and not (C.NAO_MINERAVEIS & extras)


def test_extras_incluem_o_desligado():
    cat = _por_nome("adx_direcao", "WIN$N")
    for nome in ("max_barras", "adx_periodo", "adx_limiar", "breakeven_pct",
                 "step_gatilho_pct", "trailing_pontos", "limite_perda_contrato",
                 "max_trades_dia"):
        assert C.valores(cat[nome], cat[nome].padrao)[0] == 0, nome
    assert "" in C.valores(cat["sem_entrada1"], cat["sem_entrada1"].padrao)
    fech = C.valores(cat["fechamento"], cat["fechamento"].padrao)
    assert fech[0] == "09:00" and fech[-1] == "17:30"


def test_canonico_junta_copias():
    assert C.canonico({"adx_periodo": 0, "adx_limiar": 20, "filtro_adx": "rango",
                       "adx_filtro_di": 1, "adx_subindo": 1}) == \
        {"adx_periodo": 0, "adx_limiar": 0, "filtro_adx": "tendencia",
         "adx_filtro_di": 0, "adx_subindo": 0}
    assert C.canonico({"filtro_adx": "rango", "adx_periodo": 14, "adx_limiar": 20,
                       "adx_filtro_di": 1, "adx_subindo": 1})["adx_filtro_di"] == 0
    assert C.canonico({"step_gatilho_pct": 0.0, "step_distancia_pct": 30.0})["step_distancia_pct"] == 0
    assert C.canonico({"sem_entrada1": "", "sem_entrada2": "13:00", "sem_entrada3": "13:00"}) == \
        {"sem_entrada1": "13:00", "sem_entrada2": "", "sem_entrada3": ""}



def test_canonico_com_contexto_e_faixa():
    # sem alvo: breakeven e stop móvel (% do alvo) não fazem nada
    e = C.canonico({"breakeven_pct": 30.0, "step_gatilho_pct": 50.0, "step_distancia_pct": 20.0},
                   sem_alvo=True)
    assert set(e.values()) == {0.0}
    # hora fora da janela não bloqueia nada
    assert C.canonico({"sem_entrada1": "15:00", "sem_entrada2": "", "sem_entrada3": ""},
                      fora_da_janela=lambda h: h == "15:00")["sem_entrada1"] == ""
    # prejuízos >= operações nunca dispara
    assert C.canonico({"max_trades_dia": 2, "max_prejuizos_dia": 3})["max_prejuizos_dia"] == 0
    # o canônico é sempre um valor da faixa (só "rango" ligado)
    e = C.canonico({"adx_periodo": 0, "adx_limiar": 20, "filtro_adx": "rango",
                    "adx_filtro_di": 0, "adx_subindo": 0},
                   listas={"filtro_adx": ["rango"], "adx_limiar": [5, 10, 20]})
    assert e["filtro_adx"] == "rango" and e["adx_limiar"] == 5 and e["adx_periodo"] == 0


def test_fechamento_chega_ao_ate_fora_do_passo():
    it = _por_nome("adx_direcao", "WIN$N")["fechamento"]
    assert C.valores(it, {"de": "09:00", "ate": "16:50", "passo": 30})[-1] == "16:50"


def test_trailing_segue_a_faixa_da_ficha():
    from core import ativo

    ff = ativo.faixas_do_ativo("MES", "adx_direcao").get("trailing_pontos")
    if not ff:
        pytest.skip("ficha do MES sem faixa de trailing")
    it = _por_nome("adx_direcao", "MES")["trailing_pontos"]
    assert it.padrao["de"] == 0 and it.padrao["ate"] == ff["ate"] and it.padrao["passo"] == ff["passo"]


def test_canonico_prejuizos_e_ordem_das_horas():
    assert C.canonico({"max_trades_dia": 3, "max_prejuizos_dia": 3})["max_prejuizos_dia"] == 0
    assert C.canonico({"max_trades_dia": 3, "max_prejuizos_dia": 2})["max_prejuizos_dia"] == 2
    assert C.canonico({"sem_entrada1": "11:00", "sem_entrada2": "10:00", "sem_entrada3": ""}) == \
        {"sem_entrada1": "10:00", "sem_entrada2": "11:00", "sem_entrada3": ""}


def test_sem_entrada_vai_ate_a_hora_do_fechamento():
    cat = _por_nome("adx_direcao", "WIN$N")
    assert cat["sem_entrada1"].padrao["valores"][-1] == "17:00"
