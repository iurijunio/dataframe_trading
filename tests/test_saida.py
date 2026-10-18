"""Opção de saída compartilhada (`strategies/saida.py`) e a virada no motor.

O ponto mais caro desta opção é o padrão: com ele, toda estratégia tem de
dar EXATAMENTE os trades de antes — senão todo plano gravado, o papel e a
conferência papel × backtest passariam a mentir. A gravação de antes está
em `tests/dados/saida_antes.json` (ver `tests/_saida_casos.py`).
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pytest

from core.engine import kernel as K
from core.engine.execution import ExecutionProfile, backtest
from core import metrics
from strategies import base, registry
from strategies import saida as S
from strategies.base import Signals, empty_like
from tests import _saida_casos as C

ESTRATEGIAS = list(C.PARAMS)
PADRAO = {"setup_cruzamento": 0, "rompimento_canal": 0, "reversao_rsi": 3,
          "rompimento_abertura": 1, "rompimento_ema_abertura": 1}
MAXIMO = {"setup_cruzamento": 2, "rompimento_canal": 2, "reversao_rsi": 3,
          "rompimento_abertura": 2, "rompimento_ema_abertura": 2}


@pytest.fixture(scope="module")
def barras():
    return C.barras()


@pytest.fixture(scope="module")
def antes():
    return json.loads(C.ANTES.read_text(encoding="utf-8"))


# ------------------------------------------------------------ equivalência
CASOS = list(C.casos())


@pytest.mark.parametrize("nome,estrategia,params,perfil", CASOS,
                         ids=[c[0] for c in CASOS])
def test_padrao_da_os_mesmos_trades_de_antes(barras, antes, nome, estrategia,
                                             params, perfil):
    """Plano gravado antes da opção (sem a chave) e o padrão explícito."""
    assert C.impressao(C.rodar(barras, estrategia, params, perfil)) == antes[nome]
    explicito = dict(params, saida=PADRAO[estrategia])
    assert C.impressao(C.rodar(barras, estrategia, explicito, perfil)) == antes[nome]


def test_a_gravacao_de_antes_exercita_a_saida_por_sinal(antes):
    """Sem saída por sinal nos casos, a equivalência não provaria nada para
    as estratégias de padrão 0 e 3."""
    for e in ("setup_cruzamento", "rompimento_canal", "reversao_rsi"):
        assert sum(v["sinal"] for k, v in antes.items() if k.startswith(e)) > 20
    assert any("@m7_" in k and v["n"] > 0 for k, v in antes.items())


# ------------------------------------------------------- schema e tela
@pytest.mark.parametrize("estrategia", ESTRATEGIAS)
def test_cada_estrategia_traz_o_proprio_padrao(estrategia):
    meta = registry.carregar(estrategia).params_schema["saida"]
    assert meta["default"] == PADRAO[estrategia]
    assert (meta["min"], meta["max"], meta["step"], meta["tipo"]) == \
        (0, MAXIMO[estrategia], 1, "int")
    assert meta["label"].startswith("Saída")


@pytest.mark.parametrize("estrategia", ESTRATEGIAS)
def test_tela_mostra_o_padrao_da_estrategia_escolhida(estrategia):
    from ui.components import controls
    mod = registry.carregar(estrategia)
    achados = []

    def varrer(c):
        if getattr(c, "id", None) == {"type": "val", "p": "saida"}:
            achados.append(c.value)
        filhos = getattr(c, "children", None)
        for f in (filhos if isinstance(filhos, (list, tuple)) else [filhos]):
            if f is not None and not isinstance(f, (str, int, float)):
                varrer(f)
    for campo in controls.campos_da_estrategia(mod):
        varrer(campo)
    assert achados == [PADRAO[estrategia]]


def test_mineracao_varre_a_saida_como_qualquer_inteiro():
    from core.optimizer import montar_espaco
    schema = registry.carregar("rompimento_canal").params_schema
    faixa = {"saida": {"on": True, "de": 0, "passo": 1, "ate": 5}}
    assert base.grid(schema, faixa)["saida"] == [0, 1, 2, 3, 4, 5]
    # o máximo do schema corta a faixa da tela
    assert montar_espaco(schema, faixa)["saida"] == [0, 1, 2]
    assert base.grid(schema, {})["saida"] == [0]


def test_validate_recusa_modo_proprio_onde_ele_nao_existe():
    schema = registry.carregar("setup_cruzamento").params_schema
    with pytest.raises(ValueError):
        base.validate(schema, {"saida": 3})
    assert base.validate(registry.carregar("reversao_rsi").params_schema,
                         {"saida": 3})["saida"] == 3


def test_parametro_recusa_padrao_fora_da_faixa():
    with pytest.raises(ValueError):
        S.parametro(3)


# ------------------------------------------------------------- aplicar
def _sinais(n=6):
    s = empty_like(n)
    s["entry_long"][1] = True
    s["entry_short"][3] = True
    s["exit_long"][2] = True          # saída própria, diferente da contrária
    return Signals(**s)


def test_aplicar_reescreve_as_saidas_por_modo():
    s = _sinais()
    c = S.aplicar(s, S.CONTRARIO)
    assert c.exit_long.tolist() == s.entry_short.tolist()
    assert c.exit_short.tolist() == s.entry_long.tolist() and not c.virar
    n = S.aplicar(s, S.NAO_SAIR)
    assert not n.exit_long.any() and not n.exit_short.any() and not n.virar
    v = S.aplicar(s, S.VIRAR)
    assert v.exit_long.tolist() == s.entry_short.tolist() and v.virar
    p = S.aplicar(s, S.PROPRIA)
    assert p.exit_long.tolist() == s.exit_long.tolist() and not p.virar
    with pytest.raises(ValueError):
        S.aplicar(s, 7)


def test_modo_sem_a_chave_e_o_padrao_do_schema():
    schema = registry.carregar("reversao_rsi").params_schema
    assert S.modo({}, schema) == 3
    assert S.modo({"saida": 1.0}, schema) == 1


# ------------------------------------------------- modos com estratégia real
@pytest.mark.parametrize("estrategia", ESTRATEGIAS)
@pytest.mark.parametrize("perfil", list(C.PERFIS))
def test_modo_nao_sair_nunca_sai_por_sinal(barras, estrategia, perfil):
    for params in C.PARAMS[estrategia]:
        r = C.rodar(barras, estrategia, dict(params, saida=S.NAO_SAIR), perfil)
        assert not (r.trades["reason"] == K.EXIT_SIGNAL).any()


def test_abertura_ema_no_sinal_contrario_sai_pela_entrada_contraria(barras):
    mod = registry.carregar("rompimento_ema_abertura")
    params = dict(C.PARAMS["rompimento_ema_abertura"][0], saida=S.CONTRARIO)
    r = C.rodar(barras, "rompimento_ema_abertura", params, "m1_pontos")
    t = r.trades
    sinal = np.flatnonzero(t["reason"] == K.EXIT_SIGNAL)
    assert sinal.size > 0
    s = mod.signals(barras, params)
    for k in sinal:
        # o sinal da barra anterior à saída é a entrada do outro lado
        i = int(t["exit_i"][k]) - 1
        assert (s.entry_short if t["side"][k] == 1 else s.entry_long)[i]
    padrao = C.rodar(barras, "rompimento_ema_abertura",
                     C.PARAMS["rompimento_ema_abertura"][0], "m1_pontos")
    assert C.impressao(r) != C.impressao(padrao)


def test_abertura_no_sinal_contrario_reescreve_a_saida():
    """O rompimento da abertura só sinaliza o primeiro rompimento do dia:
    com uma posição aberta não há entrada contrária no mesmo pregão, e o
    modo 0 dá os mesmos trades do 1. A saída, porém, é a contrária."""
    mod = registry.carregar("rompimento_abertura")
    b = C.barras(dias=3)
    p = dict(C.PARAMS["rompimento_abertura"][0], saida=S.CONTRARIO)
    s = mod.signals(b, p)
    assert s.entry_long.any() or s.entry_short.any()
    assert s.exit_long.tolist() == s.entry_short.tolist()
    assert s.exit_short.tolist() == s.entry_long.tolist()


def test_virar_com_estrategia_real_vira_na_mesma_abertura(barras):
    params = dict(C.PARAMS["setup_cruzamento"][0], saida=S.VIRAR)
    r = C.rodar(barras, "setup_cruzamento", params, "m1_pontos")
    t = r.trades
    viradas = [k for k in range(1, r.n_trades)
               if t["reason"][k - 1] == K.EXIT_SIGNAL
               and t["entry_i"][k] == t["exit_i"][k - 1]]
    assert len(viradas) > 10
    for k in viradas:
        assert t["side"][k] == -t["side"][k - 1]
    din = metrics.monetize(r)
    assert np.all(np.asarray(din["contratos"]) == 1)


# ------------------------------------------------------ virada no motor
WIN = C.WIN


def _cenario(n=10, dia_quebra=None):
    preco = 100_000 + 10 * np.arange(n, dtype=np.int64)
    ts = [np.datetime64(datetime(2026, 1, 5, 9, i), "ns") for i in range(n)]
    if dia_quebra is not None:
        ts = [t + np.timedelta64(1, "D") if i >= dia_quebra else t
              for i, t in enumerate(ts)]
    bars = {"ts": np.array(ts), "open": preco.copy(), "high": preco + 5,
            "low": preco - 5, "close": preco.copy()}
    s = empty_like(n)
    s["entry_long"][0] = True          # compra na abertura da barra 1
    s["entry_short"][3] = True         # vira na abertura da barra 4
    return bars, Signals(**s)


def _perfil(**kw):
    base_ = dict(entrada_inicio="09:00", entrada_fim="09:30", fechamento="09:30",
                 slippage_ticks=0, stop_pontos=0, alvo_pontos=0, contratos=3)
    base_.update(kw)
    return ExecutionProfile(**base_)


def _lista(r):
    t = r.trades
    return [(int(t["entry_i"][k]), int(t["exit_i"][k]), int(t["side"][k]),
             int(t["reason"][k])) for k in range(r.n_trades)]


def test_virada_sai_e_entra_do_outro_lado_na_mesma_abertura():
    bars, s = _cenario()
    r = backtest(bars, S.aplicar(s, S.VIRAR), _perfil(), WIN)
    assert _lista(r) == [(1, 4, 1, K.EXIT_SIGNAL), (4, 9, -1, K.EXIT_CLOSE_TIME)]
    t = r.trades
    assert t["exit_px"][0] == t["entry_px"][1] == bars["open"][4]
    din = metrics.monetize(r)
    assert np.all(np.asarray(din["contratos"]) == 3)


def test_sinal_contrario_sem_virar_so_sai():
    bars, s = _cenario()
    r = backtest(bars, S.aplicar(s, S.CONTRARIO), _perfil(), WIN)
    assert _lista(r) == [(1, 4, 1, K.EXIT_SIGNAL)]


@pytest.mark.parametrize("perfil", [
    dict(direcao="compra"),                 # só compra: a venda não entra
    dict(entrada_fim="09:03"),              # fora da janela de entrada
    dict(max_trades_dia=1),                 # o trade que a saída fechou bate o limite
    dict(limite_perda_contrato=1.0),        # perda do dia: a compra perdeu 2 pts
], ids=["so_compra", "fora_da_janela", "limite_de_operacoes", "perda_do_dia"])
def test_virada_barrada_so_sai(perfil):
    bars, s = _cenario()
    if "limite_perda_contrato" in perfil:
        # a compra fecha no prejuízo: abertura da barra 4 abaixo da entrada
        bars["open"][4] = bars["open"][1] - 10
    r = backtest(bars, S.aplicar(s, S.VIRAR), _perfil(**perfil), WIN)
    assert _lista(r) == [(1, 4, 1, K.EXIT_SIGNAL)]


def test_virada_em_hora_sem_entrada_so_sai():
    bars, s = _cenario()
    # 08:56 … 09:05: a compra entra às 08:57; a virada cairia às 09:00,
    # dentro da hora sem entrada
    bars["ts"] = bars["ts"] - np.timedelta64(4, "m")
    p = _perfil(entrada_inicio="08:00", sem_entrada1="09:00")
    assert _lista(backtest(bars, S.aplicar(s, S.VIRAR), p, WIN)) ==         [(1, 4, 1, K.EXIT_SIGNAL)]
    livre = _perfil(entrada_inicio="08:00")
    assert len(_lista(backtest(bars, S.aplicar(s, S.VIRAR), livre, WIN))) == 2


def test_virada_nunca_atravessa_o_dia():
    """A trava do mesmo pregão vale na virada: direto no kernel, sem o
    fechamento do dia (que já encerraria a posição antes)."""
    n = 8
    preco = 100_000 + 10 * np.arange(n, dtype=np.int64)
    um = np.ones(n, dtype=np.bool_)
    zero = np.zeros(n, dtype=np.bool_)
    dia = np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.int64)
    el, es = zero.copy(), zero.copy()
    el[0] = True
    es[3] = True                       # última barra do dia 0
    out = K.allocate_outputs(n)
    z = np.zeros(n, dtype=np.int64)
    nt, _, _ = K.run(preco, preco + 5, preco - 5, preco, um, um, zero, dia,
                     el, es, es.copy(), el.copy(), z, z, z, z, z, z,
                     True, True, True, 0, 0, 0, 0, 0, 0,
                     out["entry_i"], out["exit_i"], out["side"], out["entry_px"],
                     out["exit_px"], out["reason"], out["mae"], out["mfe"],
                     out["points"], out["stop_fim"], out["alvo_fim"])
    lados = out["side"][:nt].tolist()
    assert lados == [1]
    assert out["reason"][0] == K.EXIT_SIGNAL and out["exit_i"][0] == 4
    # no mesmo dia a mesma virada acontece (prova de que o teste vira)
    dia[:] = 0
    nt, _, _ = K.run(preco, preco + 5, preco - 5, preco, um, um, zero, dia,
                     el, es, es.copy(), el.copy(), z, z, z, z, z, z,
                     True, True, True, 0, 0, 0, 0, 0, 0,
                     out["entry_i"], out["exit_i"], out["side"], out["entry_px"],
                     out["exit_px"], out["reason"], out["mae"], out["mfe"],
                     out["points"], out["stop_fim"], out["alvo_fim"])
    assert out["side"][:nt].tolist() == [1, -1]
