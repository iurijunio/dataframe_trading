"""A impressão digital do código: o plano precisa saber qual versão da
estratégia gerou os números que ele promete."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import codigo  # noqa: E402


def _pasta(tmp_path, estrategia="x", corpo=b"a = 1\nb = 2\n", base=b"BASE\n"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "base.py").write_bytes(base)
    (tmp_path / f"{estrategia}.py").write_bytes(corpo)
    return tmp_path


def test_lf_e_crlf_dao_a_mesma_impressao(tmp_path):
    """O git converte LF<->CRLF nesta máquina: sem normalizar, todo checkout
    daria 'código mudou' sem ninguém ter mexido."""
    a = codigo.hash_estrategia("x", _pasta(tmp_path / "a", corpo=b"a = 1\nb = 2\n"))
    b = codigo.hash_estrategia("x", _pasta(tmp_path / "b", corpo=b"a = 1\r\nb = 2\r\n"))
    assert a == b and len(a) == 64


def test_mudar_uma_linha_da_estrategia_muda_a_impressao(tmp_path):
    a = codigo.hash_estrategia("x", _pasta(tmp_path / "a", corpo=b"a = 1\n"))
    b = codigo.hash_estrategia("x", _pasta(tmp_path / "b", corpo=b"a = 2\n"))
    assert a != b


def test_mudar_base_py_muda_a_impressao(tmp_path):
    """base.py é o contrato de toda estratégia: mexer nele muda o sinal."""
    a = codigo.hash_estrategia("x", _pasta(tmp_path / "a", base=b"B1\n"))
    b = codigo.hash_estrategia("x", _pasta(tmp_path / "b", base=b"B2\n"))
    assert a != b


def test_estrategia_inexistente_devolve_none(tmp_path):
    assert codigo.hash_estrategia("nao_existe", _pasta(tmp_path)) is None


def test_pasta_padrao_e_strategies_do_projeto():
    assert codigo.hash_estrategia("setup_cruzamento") is not None
