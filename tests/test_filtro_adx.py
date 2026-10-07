"""Filtro global de ADX: camada 4, minável, 0 = desligado.

O filtro é da camada 4 porque ele vale para QUALQUER estratégia — a
protegida `rompimento_abertura` entra junto sem o arquivo dela ser tocado.
A régua é a mesma pergunta da janela de horário (quando PODE entrar), com
a régua de mercado no lugar do relógio:

  - modo tendência: ADX >= limiar; DI e "subindo" só afinam esse lado;
  - modo rango: ADX < limiar (mean reversion pura); DI e "subindo" ficam
    de fora — fazem sentido só quando se procura tendência;
  - período 0 OU limiar 0 = filtro morto, bit a bit igual a não ter filtro.
    O zero ser minerável é o que permite comparar ligado x desligado na
    MESMA varredura — medir o quanto o filtro vale, em vez de supor.

O ADX é o de Wilder (com DI+/DI-), calculado na barra do timeframe da
estratégia — o mesmo dado que a estratégia viu; a ordem abre na barra
seguinte, então não há look-ahead. Aquecimento (2*periodo-2 barras) é NaN,
que a máscara lê como "fora da régua".
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine.execution import (  # noqa: E402
    ExecutionProfile, adx, backtest, resample,
)
from strategies.base import Signals, empty_like  # noqa: E402

WIN = {"tick_size": 5, "point_value": 0.20, "symbol": "TEST"}

N = 14          # período do ADX em quase todo teste
LIM = 25        # régua clássica; o cruzamento dela é conferido no fixture
ADXS = ("adx_periodo", "adx_limiar", "adx_filtro_di", "adx_subindo")


# ------------------------------------------------------------- construtores
def _barras(o, h, l, c) -> dict:
    n = len(o)
    inicio = datetime(2026, 1, 5, 9, 0)  # segunda-feira
    return {
        "ts": np.array([np.datetime64(inicio + timedelta(minutes=i), "ns")
                        for i in range(n)]),
        "open": np.asarray(o, dtype=np.int64),
        "high": np.asarray(h, dtype=np.int64),
        "low": np.asarray(l, dtype=np.int64),
        "close": np.asarray(c, dtype=np.int64),
        "tick_volume": np.full(n, 10, dtype=np.int64),
        "volume": np.full(n, 10, dtype=np.int64),
    }


def _sobe(n=120, base=100_000, passo=5) -> dict:
    """Alta contínua: ADX vira 100 exato e para de subir (DI- fica 0)."""
    i = np.arange(n)
    o = base + passo * i
    c = o + passo
    return _barras(o, c + 2, o - 2, c)


def _desce(n=120, base=100_000, passo=5) -> dict:
    """Baixa contínua: o espelho — DI+ fica 0, DI- é quem manda."""
    i = np.arange(n)
    o = base - passo * i
    c = o - passo
    return _barras(o, o + 2, c - 2, c)


def _plano_depois_sobe(n_plano=40, n_subida=80, base=100_000,
                       passo=5) -> dict:
    """Chato e depois alta: o ADX sobe de 0 a 100 — é a serie que tem o
    cruzamento exato da régua em barra conhecida (ver fixture abaixo)."""
    n = n_plano + n_subida
    o = np.full(n, base, dtype=np.int64)
    c = np.full(n, base, dtype=np.int64)
    h = np.full(n, base + 2, dtype=np.int64)
    l = np.full(n, base - 2, dtype=np.int64)
    if n_subida:
        k = np.arange(n_subida)
        idx = n_plano + k
        o[idx] = base + passo * k
        c[idx] = o[idx] + passo
        h[idx] = c[idx] + 2
        l[idx] = o[idx] - 2
    return _barras(o, h, l, c)


def _ziguezague() -> dict:
    """Série mista (cai, sobe, anda de lado, sobe, cai) para conferir o
    ADX contra a conta ingênua — série monocromática esconde erro de
    suavização."""
    segmentos = [(-4, 15), (5, 25), (0, 10), (3, 20), (-6, 20)]
    fechados = [100_000]
    for d, m in segmentos:
        for _ in range(m):
            fechados.append(fechados[-1] + d)
    closes = np.array(fechados[1:], dtype=np.int64)
    o = np.empty(len(closes), dtype=np.int64)
    o[0] = 100_000
    o[1:] = closes[:-1]
    h = np.maximum(o, closes) + 2
    l = np.minimum(o, closes) - 2
    return _barras(o, h, l, closes)


def _sinais(n, compras=(), vendas=()) -> Signals:
    s = empty_like(n)
    for i in compras:
        s["entry_long"][i] = True
    for i in vendas:
        s["entry_short"][i] = True
    return Signals(**s)


def perfil(**kw) -> ExecutionProfile:
    base = dict(entrada_inicio="09:00", entrada_fim="23:59",
                fechamento="23:59", slippage_ticks=0,
                corretagem_por_contrato=0.0, emolumentos_por_contrato=0.0,
                contratos=1, capital_inicial=10_000.0,
                stop_pontos=20, alvo_pontos=40)
    base.update(kw)
    return ExecutionProfile(**base)


def _regua(**kw) -> dict:
    """Tendência ligada com a régua padrão — o resto, zero (desligado)."""
    base = dict(filtro_adx="tendencia", adx_periodo=N, adx_limiar=LIM,
                adx_filtro_di=0, adx_subindo=0)
    base.update(kw)
    return base


# ------------------------------------------- a conta, de um jeito independente
def _adx_referencia(high, low, close, n):
    """Wilder puro, barra a barra, sem vetorizar nem numba.

    Escrito à mão no teste de propósito: é a conta que o motor tem de
    bater. Aqui não tem `cache=True`, nem suavização por soma parcial — se
    os dois lados errarem juntos, os testes de comportamento (a régua
    cruzando em barra conhecida) ainda acusam.
    """
    m = len(close)
    tr = np.zeros(m)
    pdm = np.zeros(m)
    ndm = np.zeros(m)
    tr[0] = float(high[0]) - float(low[0])
    for i in range(1, m):
        up = float(high[i]) - float(high[i - 1])
        dn = float(low[i - 1]) - float(low[i])
        pdm[i] = up if (up > dn and up > 0.0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0.0) else 0.0
        pc = float(close[i - 1])
        tr[i] = max(float(high[i]) - float(low[i]),
                    abs(float(high[i]) - pc), abs(float(low[i]) - pc))

    dip = np.full(m, np.nan)
    dim = np.full(m, np.nan)
    da = np.full(m, np.nan)
    if m < n:
        return da, dip, dim
    str_ = float(sum(tr[:n]))
    sp = float(sum(pdm[:n]))
    sn = float(sum(ndm[:n]))
    dx = np.zeros(m)
    for i in range(n - 1, m):
        if i > n - 1:
            str_ = str_ - str_ / n + tr[i]
            sp = sp - sp / n + pdm[i]
            sn = sn - sn / n + ndm[i]
        p = 100.0 * sp / str_ if str_ > 0.0 else 0.0
        q = 100.0 * sn / str_ if str_ > 0.0 else 0.0
        dip[i] = p
        dim[i] = q
        den = p + q
        dx[i] = 100.0 * abs(p - q) / den if den > 0.0 else 0.0
    if m >= 2 * n - 1:
        da[2 * n - 2] = float(sum(dx[n - 1:2 * n - 1]) / n)
        for i in range(2 * n - 1, m):
            da[i] = (da[i - 1] * (n - 1) + dx[i]) / n
    return da, dip, dim


# ================================================================== o ADX
def test_adx_em_alta_pura_e_100_exato_e_di_so_de_compra():
    """Alta contínua: DX = 100 em toda barra válida, logo o ADX é 100
    exato do começo ao fim (a suavização de Wilder de 100 dá 100). DI- é 0
    porque nunca houve baixa; é o que faz o filtro de DI separar os lados."""
    a, dp, dm = adx(_sobe(), N)

    assert np.isnan(a[:2 * N - 2]).all()      # aquecimento = NaN
    assert np.allclose(a[2 * N - 2:], 100.0, rtol=0, atol=1e-9)
    assert np.isnan(dp[:N - 1]).all()
    assert (dp[N - 1:] > 0).all()
    assert (dm[N - 1:] == 0).all()


def test_adx_em_mercado_chato_e_zero():
    a, dp, dm = adx(_plano_depois_sobe(n_plano=60, n_subida=0), N)
    assert np.allclose(a[2 * N - 2:], 0.0, rtol=0, atol=1e-9)
    assert (dp[N - 1:] == 0).all() and (dm[N - 1:] == 0).all()


def test_adx_bate_com_referencia_de_wilder_sem_vetorizar():
    b = _ziguezague()
    a, dp, dm = adx(b, N)
    ra, rdp, rdm = _adx_referencia(b["high"], b["low"], b["close"], N)
    np.testing.assert_allclose(a, ra, rtol=1e-9, atol=1e-9, equal_nan=True)
    np.testing.assert_allclose(dp, rdp, rtol=1e-9, atol=1e-9, equal_nan=True)
    np.testing.assert_allclose(dm, rdm, rtol=1e-9, atol=1e-9, equal_nan=True)


def test_fixture_cruza_a_regua_nas_barras_42_e_43():
    """O resto do arquivo se apoia neste cruzamento: na série "chato e
    depois sobe", o ADX está em 19,9 na barra 42 e em 25,7 na 43. Se o
    motor mudar de fórmula e o cruzamento sair do lugar, este teste avisa
    antes de os testes de comportamento virarem ruído."""
    a, _dp, _dm = adx(_plano_depois_sobe(), N)
    assert a[42] < LIM
    assert a[43] >= LIM
    assert a[41] < a[42] < a[43] < 100.0     # e ainda está subindo


# ============================================================== a régua
def test_tendencia_usa_o_adx_da_barra_do_sinal_nao_o_seguinte():
    """Barra 42 (25-): não entra; barra 43 (25+): entra. Se a máscara
    lesse a barra SEGUINTE — look-ahead — a 42 entraria, porque a 43 já
    passou da régua."""
    b = _plano_depois_sobe()
    fora = backtest(b, _sinais(120, compras=(42,)), perfil(**_regua()), WIN)
    dentro = backtest(b, _sinais(120, compras=(43,)), perfil(**_regua()), WIN)
    assert fora.n_trades == 0
    assert dentro.n_trades == 1
    assert int(dentro.trades["side"][0]) == 1


def test_rango_inverte_a_regua():
    """Mesmo ADX, régua ao contrário: abaixo do limiar entra (chato é o
    bom para quem fade), acima não entra."""
    b = _plano_depois_sobe()
    r = dict(filtro_adx="rango", adx_periodo=N, adx_limiar=LIM)
    dentro = backtest(b, _sinais(120, compras=(42,)), perfil(**r), WIN)
    fora = backtest(b, _sinais(120, compras=(43,)), perfil(**r), WIN)
    assert dentro.n_trades == 1
    assert fora.n_trades == 0


# ==================================================================== DI
def test_di_so_deixa_o_lado_da_tendencia():
    """Na alta: DI+ > DI- — compra passa, venda morre (e com DI desligado
    a venda entra e estoura no stop, provando que quem matou foi o DI). Na
    baixa, o espelho."""
    sobe, desce = _sobe(), _desce()

    longa = backtest(sobe, _sinais(120, compras=(60,)),
                     perfil(**_regua(adx_filtro_di=1)), WIN)
    curta_na_alta = backtest(sobe, _sinais(120, vendas=(60,)),
                             perfil(**_regua(adx_filtro_di=1)), WIN)
    curta_solta = backtest(sobe, _sinais(120, vendas=(60,)),
                           perfil(**_regua(adx_filtro_di=0)), WIN)
    assert longa.n_trades == 1
    assert curta_na_alta.n_trades == 0
    assert curta_solta.n_trades == 1

    curta = backtest(desce, _sinais(120, vendas=(60,)),
                     perfil(**_regua(adx_filtro_di=1)), WIN)
    longa_na_baixa = backtest(desce, _sinais(120, compras=(60,)),
                              perfil(**_regua(adx_filtro_di=1)), WIN)
    longa_solta = backtest(desce, _sinais(120, compras=(60,)),
                           perfil(**_regua(adx_filtro_di=0)), WIN)
    assert curta.n_trades == 1
    assert longa_na_baixa.n_trades == 0
    assert longa_solta.n_trades == 1


def test_di_e_subindo_valem_somente_na_tendencia():
    """No rango, DI e 'subindo' ficam de fora: o mercado é fraco por
    definição, pedir direção ou aceleração contradiz a própria régua. Já
    na tendência os dois valem — e na alta contínua o 'subindo' mata até a
    compra (ADX parado em 100 não está subindo)."""
    rango = dict(filtro_adx="rango", adx_periodo=N, adx_limiar=101,
                 adx_filtro_di=1, adx_subindo=1)
    venda_no_rango = backtest(_sobe(), _sinais(120, vendas=(60,)),
                              perfil(**rango), WIN)
    assert venda_no_rango.n_trades == 1, "no rango os ajustes finos não valem"

    compra_chata = backtest(_sobe(), _sinais(120, compras=(60,)),
                            perfil(**_regua(adx_subindo=1)), WIN)
    compra_sem_o_ajuste = backtest(_sobe(), _sinais(120, compras=(60,)),
                                   perfil(**_regua(adx_subindo=0)), WIN)
    assert compra_chata.n_trades == 0, "ADX parado em 100 não está subindo"
    assert compra_sem_o_ajuste.n_trades == 1


def test_subindo_permite_na_subida_e_mata_na_alta_chata():
    """Na série que sobe, o ADX sobe de verdade — 'subindo' deixa entrar.
    Na alta contínua (ADX colado em 100), mata."""
    em_subida = backtest(_plano_depois_sobe(), _sinais(120, compras=(60,)),
                         perfil(**_regua(adx_subindo=1)), WIN)
    alta_chata = backtest(_sobe(), _sinais(120, compras=(60,)),
                          perfil(**_regua(adx_subindo=1)), WIN)
    alta_solta = backtest(_sobe(), _sinais(120, compras=(60,)),
                          perfil(**_regua(adx_subindo=0)), WIN)
    assert em_subida.n_trades == 1
    assert alta_chata.n_trades == 0
    assert alta_solta.n_trades == 1


# ========================================================== 0 desliga tudo
def test_zero_em_periodo_ou_limiar_desliga_bit_a_bit():
    """A regra da tela: 0 em qualquer um dos dois mata o filtro — e mata
    SEM efeito colateral (sem aquecimento, sem modo). O sinal na barra 10
    cai dentro do aquecimento do ADX: se o filtro 'desligado' ainda
    mexesse em alguma coisa, ele sumiria."""
    b = _sobe()

    def roda(**f):
        return backtest(b, _sinais(120, compras=(10, 60)), perfil(**f), WIN)

    ref = roda()
    assert ref.n_trades == 2

    casos = [
        {},                                                   # padrão
        dict(adx_periodo=0, adx_limiar=101, adx_filtro_di=1,
             adx_subindo=1),                                  # período 0
        dict(adx_periodo=N, adx_limiar=0, adx_filtro_di=1,
             adx_subindo=1),                                  # limiar 0
        dict(filtro_adx="rango", adx_periodo=0, adx_limiar=25),
        dict(filtro_adx="rango", adx_periodo=N, adx_limiar=0),
    ]
    for caso in casos:
        r = roda(**caso)
        assert r.n_trades == 2, caso
        np.testing.assert_array_equal(r.trades["entry_i"],
                                      ref.trades["entry_i"], err_msg=str(caso))

    # contraste: ligado de verdade, o mesmo cenário fica sem trade nenhum
    # (aquecimento mata o da barra 10, régua 101 mata o da barra 60)
    assert roda(**_regua(adx_limiar=101)).n_trades == 0


def test_periodo_fracionario_nao_liga_o_filtro():
    """O guard do motor testa `> 0` e `adx()` trunpara em `int()`:
    0.5 passaria no guard e viraria período 0 lá dentro — filtro "morto"
    que bloqueia tudo em silêncio. O guard usa a mesma conversão, e 0,5
    vira exatamente o que é: desligado."""
    b = _sobe()
    r = backtest(b, _sinais(120, compras=(10, 60)),
                 perfil(**_regua(adx_periodo=0.5)), WIN)
    assert r.n_trades == 2


def test_filtro_nao_muta_os_sinais_do_chamador():
    """Os sinais pertencem a quem chamou o backtest (a mineração roda mil
    combinações com o mesmo objeto). '&=' no lugar errado apagaria o
    sinal para as próximas rodadas."""
    b = _sobe()
    s = _sinais(120, compras=(60,))
    antes_long = s.entry_long.copy()
    antes_short = s.entry_short.copy()

    backtest(b, s, perfil(**_regua(adx_limiar=101)), WIN)

    np.testing.assert_array_equal(s.entry_long, antes_long)
    np.testing.assert_array_equal(s.entry_short, antes_short)


# ========================================================== timeframe maior
def test_no_timeframe_maior_a_regua_e_da_barra_agregada():
    """Em M5 a máscara tem de ler o ADX das barras M5 (o `fechada` leva do
    minuto ao índice agregado), não o do M1. O chato dura 140 minutos —
    28 barras M5, mais que o aquecimento (26) —, então o cruzamento da
    régua em M5 cai nas barras 30/31, que terminam nos minutos 154 e 159:
    o sinal no 154 (ADX M5 em 19,9) não pode entrar, o do 159 (25,7) pode.
    Se a máscara lesse o ADX do M1, os dois entrariam — o M1 já cruzou a
    régua lá na barra 43."""
    b = _plano_depois_sobe(n_plano=140, n_subida=100)
    tf, _fechada, _fim = resample(b, 5)
    a5, _dp, _dm = adx(tf, N)
    assert a5[30] < LIM <= a5[31]          # M5 #30 termina no minuto 154

    fora = backtest(b, _sinais(240, compras=(154,)),
                    perfil(timeframe="M5", **_regua()), WIN)
    dentro = backtest(b, _sinais(240, compras=(159,)),
                      perfil(timeframe="M5", **_regua()), WIN)
    assert fora.n_trades == 0
    assert dentro.n_trades == 1


# ============================================== cano: schema, tela, plano
def test_adx_no_schema_da_varredura_e_filtro_com_dono_por_id():
    """No SCHEMA_EXECUCAO a faixa varre; fora do CAMPOS_PERFIL o valor não
    tem dois donos (regra do test_carregar_completo). O dropdown é o
    contrário: só CAMPOS_PERFIL, como alvo_tipo."""
    from ui.callbacks import CAMPOS_PERFIL, SCHEMA_EXECUCAO
    from core.wfa_runner import CAMPOS_EXECUCAO_NOMES

    assert set(ADXS) <= set(SCHEMA_EXECUCAO)
    por_id = {c for _, c in CAMPOS_PERFIL}
    assert not set(ADXS) & por_id
    assert dict(CAMPOS_PERFIL)["e-filtro-adx"] == "filtro_adx"
    # os quatro viajam no plano (papel/WFA/Candidata); o modo vai no
    # dicionário do perfil, junto de alvo_tipo
    assert set(ADXS) <= set(CAMPOS_EXECUCAO_NOMES)
    assert "filtro_adx" not in CAMPOS_EXECUCAO_NOMES


def test_linhas_de_faixa_e_dropdown_na_barra_lateral():
    from ui.components.controls import execucao

    def componentes(c):
        if isinstance(c, (list, tuple)):
            for x in c:
                yield from componentes(x)
            return
        if isinstance(c, (str, int, float, bool, type(None))):
            return
        yield c
        filhos = getattr(c, "children", None)
        if filhos is not None:
            yield from componentes(filhos)

    ids = [c.id for c in componentes(execucao()) if getattr(c, "id", None)]
    assert "e-filtro-adx" in ids
    for p in ADXS:
        assert {"type": "val", "p": p} in ids, p
        assert {"type": "opt-on", "p": p} in ids, p

    # min do valor fixo tem de deixar descer até 0: é o 0 que desliga o
    # filtro e é ele que a varredura compara ligado x desligado — um
    # min=1 tornaria o spinner incapaz de desligar
    for c in componentes(execucao()):
        if getattr(c, "id", None) == {"type": "val", "p": "adx_periodo"}:
            assert c.min == 0
            break
    else:
        raise AssertionError("valor fixo de adx_periodo não encontrado")


def test_espaco_de_varredura_cobre_os_quatro_campos():
    from core.optimizer import combinacoes, montar_espaco
    from ui.callbacks import SCHEMA_EXECUCAO

    ranges = {
        "adx_periodo": {"on": True, "valor": 14, "de": 7, "passo": 7,
                        "ate": 21},
        "adx_limiar": {"on": True, "valor": 25, "de": 10, "passo": 10,
                       "ate": 30},
        "adx_filtro_di": {"on": True, "valor": 0, "de": 0, "passo": 1,
                          "ate": 1},
        "adx_subindo": {"on": True, "valor": 0, "de": 0, "passo": 1,
                        "ate": 1},
    }
    espaco = montar_espaco(SCHEMA_EXECUCAO, ranges)
    assert espaco["adx_periodo"] == [7, 14, 21]
    assert espaco["adx_limiar"] == [10, 20, 30]
    assert espaco["adx_filtro_di"] == [0, 1]
    assert espaco["adx_subindo"] == [0, 1]
    combos = combinacoes(espaco)
    assert len(combos) == 3 * 3 * 2 * 2
    assert all(set(ADXS) <= set(c) for c in combos)

    # fora do ranges: valor fixo do padrão (0 = desligado), nunca some
    fixo = montar_espaco(SCHEMA_EXECUCAO, {})
    for p in ADXS:
        assert fixo[p] == [SCHEMA_EXECUCAO[p]["default"]], p


def test_catalogo_grupo_opcoes_e_formatos():
    from ui.components.catalogo import CAMPOS, GRUPOS, OPCOES
    from ui.components.ficha import formatar

    assert "Filtro de mercado" in GRUPOS
    # a ordem da ficha acompanha a barra lateral: filtro antes da janela
    assert GRUPOS.index("Filtro de mercado") < GRUPOS.index("Janela")

    assert CAMPOS["filtro_adx"][:3] == ("Filtro de mercado", "ADX · régua",
                                        "opcao")
    assert [v for _r, v in OPCOES["filtro_adx"]] == ["tendencia", "rango"]
    for campo in ("adx_periodo", "adx_limiar"):
        assert CAMPOS[campo][0] == "Filtro de mercado", campo
        assert CAMPOS[campo][2] == "desliga", campo
    for campo in ("adx_filtro_di", "adx_subindo"):
        assert CAMPOS[campo][0] == "Filtro de mercado", campo
        assert CAMPOS[campo][2] == "sim_nao", campo

    assert formatar("adx_periodo", "desliga", 0) == "desligado"
    assert formatar("adx_periodo", "desliga", 14) == "14"
    assert formatar("adx_filtro_di", "sim_nao", 1) == "sim"
    assert formatar("adx_filtro_di", "sim_nao", 0) == "não"
    assert formatar("filtro_adx", "opcao", "rango").startswith("rango")


def test_plano_antigo_desligado_e_params_de_execucao_valem_por_cima():
    """Plano gravado antes do filtro existir: nem as chaves tem — o
    dataclass entrega 0 = desligado, sem quebrar. E os quatro vêm nos
    `params` do plano (é assim que o papel os aplica); o modo fica no
    `profile`, senão vazaria para o schema da estratégia e o validate
    recusaria."""
    from core import papel

    velho = {"profile": {"timeframe": "M1", "stop_pontos": 300},
             "params": {"ema_curta": 5}, "contratos": 1}
    _estrat, p2 = papel.perfil_do_plano(velho)
    assert p2.adx_periodo == 0 and p2.adx_limiar == 0
    assert p2.filtro_adx == "tendencia"

    plano = {"profile": {"timeframe": "M1", "filtro_adx": "rango"},
             "params": {"ema_curta": 5, "adx_periodo": 21, "adx_limiar": 30,
                        "adx_filtro_di": 1, "adx_subindo": 1},
             "contratos": 1}
    estrat, p3 = papel.perfil_do_plano(plano)
    assert p3.adx_periodo == 21 and p3.adx_limiar == 30
    assert p3.adx_filtro_di == 1 and p3.adx_subindo == 1
    assert p3.filtro_adx == "rango"
    assert not any(k in estrat for k in ADXS + ("filtro_adx",))
