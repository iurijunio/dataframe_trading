"""Testes dos pedaços de `ui/callbacks_candidata.py` que não precisam do
app Dash montado — texto e regras de seleção, extraídos dos callbacks para
poderem ser testados direto.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui import callbacks_candidata as CC  # noqa: E402


def _detalhes(holdout: bool) -> dict:
    return {"strategy": "canal_donchian", "symbol": "WIN$N",
            "is_meses": 12, "oos_meses": 6, "inteligencia": "bayes",
            "holdout": holdout}


# ----------------------------------------------------------------- resumo
def test_texto_resumo_sem_holdout_nao_menciona_holdout():
    assert "holdout" not in CC._texto_resumo(_detalhes(False))


def test_texto_resumo_com_holdout_avisa():
    """A curva de um walk-forward salvo com o holdout inclui esses meses —
    quem lê a tela precisa saber disso."""
    assert "holdout incluído" in CC._texto_resumo(_detalhes(True))


def test_texto_resumo_diz_as_janelas_em_meses():
    """Legível para quem opera: 'IS 12 meses / OOS 6 meses', não 'IS12/OOS6'."""
    texto = CC._texto_resumo(_detalhes(False))
    assert "canal_donchian" in texto and "WIN$N" in texto
    assert "IS 12 meses" in texto and "OOS 6 meses" in texto
    assert "bayes" in texto


# ---------------------------------------------------------------- seletor
def _salvo(wfa_id, nome="teste", quando=datetime(2026, 9, 16, 10, 32)):
    return {"wfa_id": wfa_id, "nome": nome, "is_meses": 12, "oos_meses": 6,
            "quando": quando, "rotulo": "rótulo longo de antes"}


def test_rotulo_curto_so_com_o_que_identifica():
    """O rótulo antigo trazia WFE, janelas positivas e holdout: não cabia no
    seletor e repetia o que o resumo ao lado já diz."""
    r = CC._rotulo_curto(_salvo(8, "romp-canal-est-dd-12-6"))
    assert r == "#8 · romp-canal-est-dd-12-6 · IS 12 / OOS 6 · 16/09"


def test_rotulo_curto_sem_nome():
    assert "sem nome" in CC._rotulo_curto(_salvo(3, nome=None))


def test_valor_mantem_a_escolha_que_ainda_existe():
    """Não troca o que o usuário escolheu só porque abriu outro WFA na aba
    Walk-Forward."""
    assert CC._valor_do_seletor(atual=8, ids={3, 8}, aberto_no_wfa=3) == 8


def test_valor_vazio_herda_o_wfa_aberto_na_outra_aba():
    """Chegando do Walk-Forward, a tela já abre no mesmo walk-forward."""
    assert CC._valor_do_seletor(atual=None, ids={3, 8}, aberto_no_wfa=3) == 3


def test_valor_excluido_herda_o_aberto_ou_limpa():
    assert CC._valor_do_seletor(atual=5, ids={3, 8}, aberto_no_wfa=8) == 8
    assert CC._valor_do_seletor(atual=5, ids={3, 8}, aberto_no_wfa=None) is None


def test_valor_aberto_de_outra_estrategia_nao_entra():
    """O WFA aberto na outra aba pode ser de uma estratégia que não está na
    lista filtrada — aí não há o que herdar."""
    assert CC._valor_do_seletor(atual=None, ids={3, 8}, aberto_no_wfa=99) is None


def test_valor_sem_escolha_nem_aberto_usa_o_padrao():
    """Para o seletor de estratégia: sem escolha e sem a da outra aba na
    lista, cai na primeira que tem walk-forward — nunca numa lista vazia."""
    assert CC._valor_do_seletor(atual=None, ids={"a", "b"}, aberto_no_wfa="x",
                                padrao="a") == "a"
