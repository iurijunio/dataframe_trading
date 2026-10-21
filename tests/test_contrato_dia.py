"""Contrato do dia: igual ao WIN$N, vencimento e guarda de preço (spec §5.6)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import contrato_dia as C  # noqa: E402
from tests.mt5_falso import MT5Ordens  # noqa: E402

HOJE = date(2026, 10, 9)


def test_escolhe_o_contrato_igual_ao_win_n():
    mt5 = MT5Ordens()                      # WINV26 == WIN$N; WINZ26 +1500
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] == "WINV26"
    assert r["motivo"] is None
    assert r["vence_em"] == date(2026, 10, 14)
    assert r["amanha"] is None             # vence daqui a 3 pregões


def test_escolhe_o_igual_mesmo_sendo_o_segundo_da_lista():
    mt5 = MT5Ordens()
    mt5.precos["WINV26"] = 190_000         # o do dia agora é o Z
    mt5.precos["WINZ26"] = mt5.precos["WIN$N"]
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] == "WINZ26"
    assert r["vence_em"] == date(2026, 12, 16)


def test_nenhum_igual_escolhe_pelo_volume():
    mt5 = MT5Ordens()
    mt5.precos["WINV26"] = 189_100
    mt5.precos["WINZ26"] = 190_500
    mt5.volumes = {"WINV26": 1_000, "WINZ26": 9_000}
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] == "WINZ26"
    assert r["motivo"] == "pelo volume (preço diferente do WIN$N)"


def test_nenhum_igual_e_sem_volume_nao_escolhe():
    mt5 = MT5Ordens()
    mt5.precos["WINV26"] = 189_100
    mt5.precos["WINZ26"] = 190_500
    mt5.sem_barras = True                  # copy_rates -> None
    mt5.last_error = lambda: (-10004, "IPC")   # erro de verdade, não vazio
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] is None and r["motivo"]


def test_vence_hoje_nao_entra():
    mt5 = MT5Ordens()
    r = C.escolher(mt5, date(2026, 10, 14))
    assert r["simbolo"] is None
    assert r["motivo"] == "vencimento do WINV26: sem entradas hoje"
    assert r["vence_em"] == date(2026, 10, 14)


def test_vespera_avisa_o_contrato_de_amanha():
    mt5 = MT5Ordens()
    r = C.escolher(mt5, date(2026, 10, 13))      # terça; vence quarta
    assert r["simbolo"] == "WINV26"
    assert r["amanha"] == "WINZ26"


def test_vespera_na_sexta_olha_a_segunda():
    mt5 = MT5Ordens()
    mt5.vencimentos["WINV26"] = datetime(2026, 10, 12, 18, 30)   # segunda
    r = C.escolher(mt5, date(2026, 10, 9))                        # sexta
    assert r["simbolo"] == "WINV26" and r["amanha"] == "WINZ26"


def test_contrato_fora_de_negociacao_normal_nunca_e_escolhido():
    mt5 = MT5Ordens()
    orig = mt5.symbol_info

    def info(s):
        i = orig(s)
        if s == "WINV26":
            i.trade_mode = 3               # só encerramento
        return i
    mt5.symbol_info = info
    mt5.volumes = {"WINZ26": 5}
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] == "WINZ26"        # o V, igual ao WIN$N, foi ignorado
    assert r["motivo"] == "pelo volume (preço diferente do WIN$N)"


def test_symbols_get_none_vira_motivo_sem_excecao():
    mt5 = MT5Ordens()
    mt5.symbols_get = lambda group=None: None
    mt5.last_error = lambda: (-10004, "IPC")
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] is None and r["motivo"]
    assert r["vence_em"] is None and r["amanha"] is None


def test_tick_do_win_n_indisponivel_vira_motivo():
    mt5 = MT5Ordens()
    mt5.symbol_info_tick = lambda s: None
    r = C.escolher(mt5, HOJE)
    assert r["simbolo"] is None and r["motivo"]


# ---------------------------------------------------------- guarda de preço
T0 = datetime(2026, 10, 9, 10, 0, 0)


def test_guarda_so_bloqueia_depois_de_60s_continuos():
    g = C.GuardaPreco(5)
    assert g.observar(T0, 189_020, 189_000) is False        # 4 ticks: começa
    assert g.observar(T0 + timedelta(seconds=30), 189_020, 189_000) is False
    assert g.observar(T0 + timedelta(seconds=60), 189_020, 189_000) is False  # 60 não é "mais de 60"
    assert g.observar(T0 + timedelta(seconds=61), 189_020, 189_000) is True


def test_guarda_solta_na_primeira_observacao_dentro_da_faixa():
    g = C.GuardaPreco(5)
    g.observar(T0, 189_020, 189_000)
    assert g.observar(T0 + timedelta(seconds=90), 189_020, 189_000) is True
    assert g.observar(T0 + timedelta(seconds=91), 189_010, 189_000) is False  # 2 ticks: dentro


def test_guarda_a_contagem_reinicia_se_voltou_a_faixa():
    g = C.GuardaPreco(5)
    g.observar(T0, 189_020, 189_000)
    g.observar(T0 + timedelta(seconds=50), 189_000, 189_000)      # voltou
    assert g.observar(T0 + timedelta(seconds=70), 189_020, 189_000) is False  # recomeçou aos 70
    assert g.observar(T0 + timedelta(seconds=120), 189_020, 189_000) is False
    assert g.observar(T0 + timedelta(seconds=131), 189_020, 189_000) is True


def test_guarda_dois_ticks_exatos_nao_bloqueiam_e_o_sinal_nao_importa():
    g = C.GuardaPreco(5)
    assert g.observar(T0, 189_010, 189_000) is False
    assert g.observar(T0 + timedelta(seconds=300), 189_010, 189_000) is False
    assert g.observar(T0, 188_985, 189_000) is False   # 3 ticks abaixo: começa
    assert g.observar(T0 + timedelta(seconds=61), 188_985, 189_000) is True
