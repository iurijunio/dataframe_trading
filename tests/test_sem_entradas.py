"""Três selects de "sem entradas às" na seção Janela da barra lateral.

O campo vive no ExecutionProfile (camada 4), então ele viaja sozinho para
mineração, walk-forward, papel e plano — o que este teste tranca é a ponte
da tela: id existindo, apontando para a chave certa, com opções de hora
para escolher.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.callbacks import CAMPOS_PERFIL  # noqa: E402
from ui.components.catalogo import OPCOES  # noqa: E402

PARES = (("sem_entrada1", "e-sem-ent1"),
         ("sem_entrada2", "e-sem-ent2"),
         ("sem_entrada3", "e-sem-ent3"))


def _ids_da_barra_lateral() -> list:
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

    return [c.id for c in componentes(execucao()) if getattr(c, "id", None)]


def test_tres_campos_no_perfil_com_o_id_certo():
    """Todo campo novo do perfil tem de ter destino (regra do
    test_carregar_completo) — aqui, o id da tela apontando para a chave."""
    por_id = {cid: chave for cid, chave in CAMPOS_PERFIL}
    for campo, cid in PARES:
        assert por_id.get(cid) == campo, (cid, campo)
        assert cid in _ids_da_barra_lateral(), cid


def test_opcoes_de_hora_vao_de_00h_a_23h_com_desligado():
    """(rótulo, value): a tela mostra "13h", o value gravado é "13:00" —
    o que o motor parseia com _minutes. Inverter os dois colava "13h" no
    perfil e estourava o backtest na hora de operar."""
    from core.engine.execution import _minutes

    opcoes = OPCOES["hora"]
    assert opcoes[0] == ("—", "")                 # desligado = não bloqueia
    assert [r for r, _ in opcoes[1:]] == [f"{h:02d}h" for h in range(24)]
    assert [v for _, v in opcoes[1:]] == \
        [f"{h:02d}:00" for h in range(24)]
    assert all(_minutes(v) == h * 60 for h, (_r, v) in enumerate(opcoes[1:]))


def test_hora_selecionada_na_ficha_mostra_13h_e_vazio_mostra_traco():
    from ui.components.ficha import formatar

    assert formatar("sem_entrada1", "hora", "13:00") == "13h"
    assert formatar("sem_entrada1", "hora", "") == "—"
    assert formatar("sem_entrada1", "hora", None) == "—"


def test_rotulos_dizem_sem_entradas_e_nao_um_horario_qualquer():
    """As três horas podem ser iguais na ficha; o rótulo é que as
    diferencia."""
    from ui.components.catalogo import CAMPOS
    for campo, _cid in PARES:
        grupo, rotulo, _fmt, *_ = CAMPOS[campo]
        assert grupo == "Janela"
        assert rotulo.startswith("sem entradas ·")
