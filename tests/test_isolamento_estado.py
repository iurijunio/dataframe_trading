"""A captura do usuário está sempre rodando: nenhum teste pode ler (nem
escrever) o data/ao_vivo/estado.json real — o resultado mudaria com a
hora do dia e com o pregão."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402

REAL = db.DATA / "ao_vivo" / "estado.json"


def test_nenhum_caminho_do_estado_aponta_para_o_real():
    import cli
    import corrigir_base
    from ui import data as D
    for caminho in (D.ESTADO_CAPTURA, cli.ESTADO_CAPTURA, corrigir_base.ESTADO_CAPTURA):
        assert Path(caminho).resolve() != REAL.resolve()
        assert not Path(caminho).exists()
    assert D.estado_captura() is None
    assert cli._captura_ativa() is False


def test_memoria_do_estado_comeca_vazia():
    from ui import data as D
    assert D._estado_ultimo is None and D._conferencia_vista is None
