"""Testes dos pedaços de `ui/callbacks_candidata.py` que não precisam do
app Dash montado — texto puro, extraído do callback para poder ser testado
direto (I3 da rodada de correção final).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui import callbacks_candidata as CC  # noqa: E402


def _detalhes(holdout: bool) -> dict:
    return {"strategy": "canal_donchian", "symbol": "WIN$N",
            "is_meses": 12, "oos_meses": 6, "inteligencia": "bayes",
            "holdout": holdout}


def test_texto_resumo_sem_holdout_nao_menciona_holdout():
    assert "holdout" not in CC._texto_resumo(_detalhes(False))


def test_texto_resumo_com_holdout_avisa():
    """Os WFAs #3 e #8 foram salvos com holdout incluído na base: os
    'últimos 12 meses' do bloco 1 são, na prática, metade holdout. Sem
    avisar aqui, a tela sugere um número medido em dado nunca visto."""
    texto = CC._texto_resumo(_detalhes(True))
    assert "holdout incluído" in texto


def test_texto_resumo_preserva_os_campos_de_sempre():
    texto = CC._texto_resumo(_detalhes(False))
    assert "canal_donchian" in texto and "WIN$N" in texto
    assert "IS12/OOS6" in texto and "bayes" in texto
