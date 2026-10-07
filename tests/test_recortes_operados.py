"""Os recortes do Diagnóstico (sugestões e linhas do gráfico MAE/MFE)
precisam do stop e do alvo que o motor realmente operou.

O perfil pode guardar um alvo que nunca entrou em jogo: com alvo tipo
multiplicador, a caixa "Alvo (pontos)" fica parada e o alvo real sai do
stop x razão (ou do ATR). Usar o valor do perfil no "% do alvo" mente no
próprio número que o usuário usa para decidir o que mexer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.callbacks import _referencias_operadas  # noqa: E402


def test_usa_o_stop_e_o_alvo_operados_quando_diferem_do_perfil():
    # multiplicador: razao 2,3 -> alvo operado 460; o perfil ainda guarda
    # 600 do campo de pontos fixos, que nunca entrou em jogo. Stop e alvo
    # diferentes entre si: trocar um pelo outro tem de falhar
    res = SimpleNamespace(
        sl_at_entry=np.array([200, 200, 200], dtype=np.int64),
        tp_at_entry=np.array([460, 460, 460], dtype=np.int64),
    )
    perfil = SimpleNamespace(stop_pontos=300, alvo_pontos=600)

    assert _referencias_operadas(res, perfil) == (200, 460)


def test_sem_trades_cai_no_perfil_para_nao_dividir_por_zero():
    res = SimpleNamespace(
        sl_at_entry=np.empty(0, dtype=np.int64),
        tp_at_entry=np.empty(0, dtype=np.int64),
    )
    perfil = SimpleNamespace(stop_pontos=300, alvo_pontos=600)

    assert _referencias_operadas(res, perfil) == (300, 600)
