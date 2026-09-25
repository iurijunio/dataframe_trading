"""Testes do rompimento da abertura (Opening Range Breakout).

Estratégia de day trade clássica: o range das primeiras barras do pregão
vira o alvo do primeiro rompimento do dia — só um sinal por dia, sem
saída própria (fecha no stop/alvo do perfil ou no fim do pregão, que é
decisão de camada 4, não da estratégia).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies import rompimento_abertura as R  # noqa: E402


def _barras(closes_por_dia: list[list[int]]) -> dict:
    """Cada item da lista é um pregão; vira barras de 1 minuto a partir das
    09:00, um dia de calendário por pregão (dias corridos, não úteis — não
    importa aqui, só que sejam datas diferentes)."""
    ts, o, h, l, c = [], [], [], [], []
    for dia, closes in enumerate(closes_por_dia):
        base = np.datetime64(f"2026-03-{4 + dia:02d}T09:00", "m")
        for i, preco in enumerate(closes):
            ts.append(base + np.timedelta64(i, "m"))
            o.append(preco)
            h.append(preco)
            l.append(preco)
            c.append(preco)
    return {
        "ts": np.array(ts),
        "open": np.array(o, dtype=np.int64), "high": np.array(h, dtype=np.int64),
        "low": np.array(l, dtype=np.int64), "close": np.array(c, dtype=np.int64),
    }


def _params(**troca):
    p = {"barras_abertura": 3, "folga_ticks": 0, "filtro_amplitude": 0}
    p.update(troca)
    return p


def test_rompe_para_cima_depois_da_abertura():
    """Abertura (3 barras): 100, 105, 95 -> range [95,105]. Na 4ª barra
    fecha a 110, rompendo o teto."""
    s = R.signals(_barras([[100, 105, 95, 110]]), _params())
    assert s.entry_long[3] and not s.entry_short[3]


def test_rompe_para_baixo_depois_da_abertura():
    s = R.signals(_barras([[100, 105, 95, 90]]), _params())
    assert s.entry_short[3] and not s.entry_long[3]


def test_nao_entra_dentro_da_propria_janela_de_abertura():
    """As 3 primeiras barras estão FORMANDO o range — não podem, elas
    mesmas, ser um rompimento dele."""
    s = R.signals(_barras([[100, 105, 95, 110]]), _params())
    assert not s.entry_long[:3].any() and not s.entry_short[:3].any()


def test_so_o_primeiro_rompimento_do_dia_conta():
    """Depois do rompimento de cima na barra 3, a barra 5 (mais alta
    ainda) não é um sinal novo — é o mesmo dia, já rompeu."""
    s = R.signals(_barras([[100, 105, 95, 110, 120]]), _params())
    assert s.entry_long[3]
    assert not s.entry_long[4]


def test_reversao_no_mesmo_dia_nao_gera_segundo_sinal():
    """Depois do rompimento de cima, uma queda que rompe o piso do MESMO
    range no MESMO dia também não é sinal novo — é reversão, não um
    segundo rompimento válido."""
    s = R.signals(_barras([[100, 105, 95, 110, 80]]), _params())
    assert s.entry_long[3]
    assert not s.entry_short[4]


def test_range_e_reiniciado_a_cada_dia():
    """Um dia novo forma um range novo — o que rompeu ontem não vale
    hoje."""
    dia1 = [100, 105, 95, 110]          # rompe pra cima na barra 3
    dia2 = [200, 205, 195, 210]         # range bem diferente, rompe de novo
    s = R.signals(_barras([dia1, dia2]), _params())
    assert s.entry_long[3]              # rompimento do dia 1
    assert s.entry_long[7]              # rompimento do dia 2 (barra 3 dele)


def test_folga_em_ticks_exige_romper_alem_do_teto():
    barras = _barras([[100, 105, 95, 106]])   # rompe teto (105) por só 1
    sem_folga = R.signals(barras, _params(folga_ticks=0))
    com_folga = R.signals(barras, _params(folga_ticks=5))   # 5 ticks = 25 pontos
    assert sem_folga.entry_long[3]
    assert not com_folga.entry_long[3]


def test_filtro_de_amplitude_descarta_abertura_estreita_demais():
    """Range de 5 pontos (100 a 105 já não, mas 100/101/100) é estreito
    demais para valer rompimento em mercado parado."""
    barras = _barras([[100, 101, 100, 110]])   # range = 1
    sem_filtro = R.signals(barras, _params(filtro_amplitude=0))
    com_filtro = R.signals(barras, _params(filtro_amplitude=50))
    assert sem_filtro.entry_long[3]
    assert not com_filtro.entry_long[3]


def test_sem_range_formado_nao_ha_sinal():
    """Pregão mais curto que a janela de abertura nunca forma range —
    não pode inventar rompimento de um range que não existe."""
    s = R.signals(_barras([[100, 105]]), _params(barras_abertura=3))
    assert not s.entry_long.any() and not s.entry_short.any()


def test_nenhum_sinal_olha_o_futuro():
    rng = np.random.default_rng(7)
    dias = [list(100_000 + np.cumsum(rng.integers(-50, 51, 60)))
            for _ in range(3)]
    inteiro = R.signals(_barras(dias), _params())
    cortado = R.signals(_barras(dias[:2] + [dias[2][:30]]), _params())
    limite = 120  # 2 dias inteiros de 60 barras
    for campo in ("entry_long", "entry_short", "exit_long", "exit_short"):
        assert np.array_equal(getattr(inteiro, campo)[:limite],
                              getattr(cortado, campo)[:limite]), campo


def test_a_estrategia_nao_decide_stop_nem_alvo_nem_saida():
    """Sem saída própria: fecha no stop/alvo do perfil ou no fim do
    pregão — decisão de camada 4, igual às outras estratégias."""
    s = R.signals(_barras([[100, 105, 95, 110, 108, 107]]), _params())
    assert s.sl_points == 0 and s.tp_points == 0
    assert not s.exit_long.any() and not s.exit_short.any()


def test_contrato_da_estrategia():
    assert R.name and R.label
    assert set(R.params_schema) == {"barras_abertura", "folga_ticks",
                                    "filtro_amplitude"}
    for meta in R.params_schema.values():
        assert {"label", "default", "min", "max", "step", "tipo"} <= set(meta)
