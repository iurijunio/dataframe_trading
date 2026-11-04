"""O motor em camadas tem de dar os mesmos trades do motor de antes.

O gabarito (`tests/dados/motor_camadas.json`) foi gravado com o motor antigo,
por `scripts/gabarito_motor.py`; cada caso é um hash dos trades.
"""
import json

import pytest

from core import db_manager as db
from scripts.gabarito_motor import ARQUIVO, assinatura, casos


def _tem_parquet():
    try:
        db.read_bars_parquet("WIN$N", "2024-01-02", "2024-01-03")
        db.read_bars_parquet("MES", "2024-01-02", "2024-01-03")
        return True
    except FileNotFoundError:
        return False


precisa_parquet = pytest.mark.skipif(not _tem_parquet(),
                                     reason="sem espelho Parquet do WIN/MES")


@pytest.fixture(scope="module")
def todos_os_casos():
    return list(casos())


@precisa_parquet
def test_motor_bate_com_o_gabarito(todos_os_casos):
    from core.engine.execution import run_strategy

    gabarito = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    assert len(gabarito) == len(todos_os_casos)
    for chave, bars, mod, params, perfil, inst, va in todos_os_casos:
        res = run_strategy(bars, mod, params, perfil, inst, vela_aberta=va)
        assert assinatura(res) == gabarito[chave], chave
