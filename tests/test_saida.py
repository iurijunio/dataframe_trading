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

# o rompimento da abertura fica de fora: um sinal por dia, então com
# posição aberta nunca há entrada contrária no mesmo pregão e os modos
# 0/1/2 dariam os mesmos trades (cópias na mineração = platô falso)
SEM_SAIDA = {"rompimento_abertura"}
ESTRATEGIAS = [e for e in C.PARAMS if e not in SEM_SAIDA]
PADRAO = {"setup_cruzamento": 0, "rompimento_canal": 0, "reversao_rsi": 3,
          "rompimento_ema_abertura": 1}
MAXIMO = {"setup_cruzamento": 2, "rompimento_canal": 2, "reversao_rsi": 3,
          "rompimento_ema_abertura": 2}


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
    if estrategia in SEM_SAIDA:
        return
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


def _faixa_da_tela(mod, faixas=None):
    """(de, até) que a tela preenche em cada campo minerável."""
    from ui.components import controls
    achados: dict = {}

    def varrer(c):
        i = getattr(c, "id", None)
        if isinstance(i, dict) and i.get("type") == "opt":
            achados.setdefault(i["p"], {})[i["k"]] = c.value
        filhos = getattr(c, "children", None)
        for f in (filhos if isinstance(filhos, (list, tuple)) else [filhos]):
            if f is not None and not isinstance(f, (str, int, float)):
                varrer(f)
    for campo in controls.campos_da_estrategia(mod, faixas):
        varrer(campo)
    return {p: (v["de"], v["ate"]) for p, v in achados.items()}


@pytest.mark.parametrize("estrategia", ESTRATEGIAS)
def test_ate_da_mineracao_da_saida_vai_ao_ultimo_modo(estrategia):
    """Padrão × 3 dava 0 a 0 no cruzamento e no canal (padrão 0): ligar
    "minerar" na saída não varria modo nenhum. Campo de poucos valores
    (categoria) abre a faixa inteira."""
    mod = registry.carregar(estrategia)
    assert _faixa_da_tela(mod)["saida"] == (0, MAXIMO[estrategia])


def test_ate_dos_outros_parametros_segue_padrao_vezes_tres():
    for estrategia in C.PARAMS:
        mod = registry.carregar(estrategia)
        faixa = _faixa_da_tela(mod)
        for nome, meta in mod.params_schema.items():
            if nome == "saida":
                continue
            assert faixa[nome] == (meta["min"],
                                   min(meta["max"], meta["default"] * 3)), nome


def test_ate_de_qualquer_inteiro_de_poucos_valores_e_o_maximo():
    """A regra é do campo, não do nome `saida`: inteiro com até 10 valores
    é categoria; com mais, padrão × 3 como sempre (e decimal nunca)."""
    from types import SimpleNamespace

    def meta(mn, mx, passo, padrao, tipo="int"):
        return {"label": "x", "default": padrao, "min": mn, "max": mx,
                "step": passo, "tipo": tipo}
    mod = SimpleNamespace(params_schema={
        "modo": meta(0, 4, 1, 1),              # 5 valores: categoria
        "dez": meta(1, 10, 1, 2),              # 10 valores: ainda categoria
        "onze": meta(0, 10, 1, 2),             # 11 valores: faixa comum
        "passo_largo": meta(0, 900, 100, 100), # 10 valores pelo passo
        "decimal": meta(0.0, 2.0, 0.5, 0.5, "float"),
    })
    assert _faixa_da_tela(mod) == {"modo": (0, 4), "dez": (1, 10),
                                   "onze": (0, 6), "passo_largo": (0, 900),
                                   "decimal": (0.0, 1.5)}


def test_ate_da_mineracao_salva_prevalece():
    mod = registry.carregar("rompimento_canal")
    faixas = {"saida": {"on": True, "de": 0, "passo": 1, "ate": 1}}
    assert _faixa_da_tela(mod, faixas)["saida"] == (0, 1)


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


@pytest.mark.parametrize("estrategia", sorted(SEM_SAIDA))
def test_sem_opcao_de_saida_onde_ela_seria_copia(estrategia):
    """O rompimento da abertura só sinaliza o primeiro rompimento do dia:
    a opção não existe nele, e pedi-la é erro (não um modo ignorado)."""
    mod = registry.carregar(estrategia)
    assert "saida" not in mod.params_schema
    with pytest.raises(ValueError):
        base.validate(mod.params_schema, {"saida": S.CONTRARIO})
    s = mod.signals(C.barras(dias=3), C.PARAMS[estrategia][0])
    assert s.entry_long.any() or s.entry_short.any()
    assert not s.exit_long.any() and not s.exit_short.any() and not s.virar


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


@pytest.mark.parametrize("nivel,reason,px", [
    ("stop", K.EXIT_STOP, 100_060),       # venda em 100.040, stop 20 acima
    ("alvo", K.EXIT_TARGET, 100_000),     # alvo 40 abaixo
])
def test_virada_com_stop_ou_alvo_na_propria_barra_da_virada(nivel, reason, px):
    """B entra na abertura da barra 4 e a mesma barra já toca o stop (ou o
    alvo) dele: B sai ali mesmo, com os níveis da própria entrada."""
    bars, s = _cenario()
    if nivel == "stop":
        bars["high"][4] = bars["open"][4] + 30
    else:
        bars["low"][4] = bars["open"][4] - 50
    r = backtest(bars, S.aplicar(s, S.VIRAR),
                 _perfil(stop_pontos=20, alvo_pontos=40), WIN)
    assert _lista(r) == [(1, 4, 1, K.EXIT_SIGNAL), (4, 4, -1, reason)]
    t = r.trades
    assert t["entry_px"][1] == bars["open"][4] and t["exit_px"][1] == px
    assert (t["stop_fim"][1], t["alvo_fim"][1]) == (100_060, 100_000)


def test_virada_com_max_barras_conta_do_zero_em_b():
    """O tempo máximo de B conta da entrada de B, não da de A: com 3
    barras, A (barra 1) sai pela virada na 4 e B dura até a 7."""
    bars, s = _cenario()
    r = backtest(bars, S.aplicar(s, S.VIRAR), _perfil(max_barras=3), WIN)
    assert _lista(r) == [(1, 4, 1, K.EXIT_SIGNAL), (4, 7, -1, K.EXIT_MAXBARS)]


def test_max_barras_encerra_a_antes_da_virada():
    """A atinge o tempo máximo na barra do sinal contrário: sai no
    fechamento dela (tempo), e a venda entra zerada na abertura seguinte
    — e também dura só 2 barras."""
    bars, s = _cenario()
    r = backtest(bars, S.aplicar(s, S.VIRAR), _perfil(max_barras=2), WIN)
    assert _lista(r) == [(1, 3, 1, K.EXIT_MAXBARS), (4, 6, -1, K.EXIT_MAXBARS)]


def _subida(n=60):
    preco = 100_000 + 10 * np.arange(n, dtype=np.int64)
    ts = [np.datetime64(datetime(2026, 1, 5, 9, 0), "ns")
          + np.timedelta64(i, "m") for i in range(n)]
    bars = {"ts": np.array(ts), "open": preco.copy(), "high": preco + 5,
            "low": preco - 5, "close": preco.copy()}
    s = empty_like(n)
    s["entry_long"][20] = True
    s["entry_short"][30] = True        # contra a subida: DI− abaixo do DI+
    return bars, Signals(**s)


def test_adx_barra_a_entrada_da_virada_e_sobra_so_a_saida():
    """A régua de mercado corta a ENTRADA da virada (o kernel tem de
    receber os sinais filtrados), nunca a saída: com o DI pedindo o lado
    da subida, a venda da virada não entra, mas a compra sai."""
    from core.engine.execution import adx
    bars, s = _subida()
    _, dip, dim = adx(bars, 5)
    assert dip[20] > dim[20] and not dim[30] > dip[30]
    longe = dict(entrada_fim="10:30", fechamento="10:30")
    livre = backtest(bars, S.aplicar(s, S.VIRAR), _perfil(**longe), WIN)
    assert _lista(livre) == [(21, 31, 1, K.EXIT_SIGNAL),
                             (31, 59, -1, K.EXIT_CLOSE_TIME)]
    filtro = _perfil(filtro_adx="tendencia", adx_periodo=5, adx_limiar=10,
                     adx_filtro_di=1, **longe)
    r = backtest(bars, S.aplicar(s, S.VIRAR), filtro, WIN)
    assert _lista(r) == [(21, 31, 1, K.EXIT_SIGNAL)]
