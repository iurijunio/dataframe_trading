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


def _com_ajudante(pasta, corpo, ajudante=b"A1\n", outro=b"O1\n"):
    p = _pasta(pasta, corpo=corpo)
    (p / "saida.py").write_bytes(ajudante)
    (p / "outro.py").write_bytes(outro)
    return p


def test_ajudante_importado_entra_na_impressao(tmp_path):
    """`strategies/saida.py` decide a saída de quase toda estratégia: mudar
    ele muda os trades, e o plano tem de saber."""
    for k, corpo in enumerate((b"from . import saida as s\n",
                               b"from .saida import aplicar\n",
                               b"from strategies import saida\n",
                               b"from strategies.saida import aplicar\n",
                               b"import strategies.saida\n")):
        a = codigo.hash_estrategia("x", _com_ajudante(tmp_path / f"a{k}", corpo))
        b = codigo.hash_estrategia("x", _com_ajudante(tmp_path / f"b{k}", corpo,
                                                      ajudante=b"A2\n"))
        assert a != b, corpo


def test_ajudante_nao_importado_fica_fora(tmp_path):
    corpo = b"from . import saida\n"
    a = codigo.hash_estrategia("x", _com_ajudante(tmp_path / "a", corpo))
    b = codigo.hash_estrategia("x", _com_ajudante(tmp_path / "b", corpo,
                                                  outro=b"O2\n"))
    assert a == b


def test_ajudante_do_ajudante_tambem_entra(tmp_path):
    corpo = b"from . import saida\n"
    a = _com_ajudante(tmp_path / "a", corpo, ajudante=b"from . import outro\n")
    b = _com_ajudante(tmp_path / "b", corpo, ajudante=b"from . import outro\n",
                      outro=b"O2\n")
    assert codigo.hash_estrategia("x", a) != codigo.hash_estrategia("x", b)


def test_ordem_dos_ajudantes_e_fixa(tmp_path):
    a = _com_ajudante(tmp_path / "a", b"from . import saida, outro\n")
    b = _com_ajudante(tmp_path / "b", b"from . import outro\nfrom . import saida\n")
    assert codigo.ajudantes("x", a) == codigo.ajudantes("x", b) == ["outro", "saida"]


def test_sem_ajudante_a_impressao_e_a_de_antes(tmp_path):
    """Estratégia que só importa base.py mantém o hash de sempre: plano
    gravado dela não acusa "código mudou" à toa."""
    import hashlib
    corpo = b"from .base import Signals\n"
    h = hashlib.sha256()
    for parte in (b"BASE\n", corpo):
        h.update(parte)
        h.update(b"\0")
    assert codigo.hash_estrategia("x", _pasta(tmp_path, corpo=corpo)) == h.hexdigest()


def test_estrategias_do_projeto_e_seus_ajudantes():
    for e in ("setup_cruzamento", "rompimento_canal", "reversao_rsi",
              "rompimento_ema_abertura"):
        assert codigo.ajudantes(e) == ["saida"], e
    assert codigo.ajudantes("rompimento_abertura") == []


def test_estrategia_inexistente_devolve_none(tmp_path):
    assert codigo.hash_estrategia("nao_existe", _pasta(tmp_path)) is None


def test_pasta_padrao_e_strategies_do_projeto():
    assert codigo.hash_estrategia("setup_cruzamento") is not None


# ------------------------------------------------------------ reassinar
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from core import ao_vivo  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import plano as _plano  # noqa: E402
from tests._cadeia import banco, campos_plano  # noqa: E402,F401


def _res(n=3, **muda):
    trades = {"entry_i": np.arange(n), "side": np.ones(n, dtype=np.int8),
              "points": np.arange(n) * 5}
    trades.update(muda)
    return {"n_trades": n, "trades": trades, "bloqueios": 0}


def test_trades_iguais_campo_a_campo():
    assert codigo.trades_iguais(_res(), _res()) is None
    assert "points" in codigo.trades_iguais(
        _res(), _res(points=np.array([0, 5, 15])))
    assert "trades" in codigo.trades_iguais(_res(3), _res(4))
    sem_side = _res()
    del sem_side["trades"]["side"]
    assert "campos" in codigo.trades_iguais(_res(), sem_side)
    outro = _res()
    outro["bloqueios"] = 2
    assert "bloqueios" in codigo.trades_iguais(_res(), outro)


def _cenario(tmp_path, antigo="a" * 64):
    """Dois planos com o hash antigo da estratégia `x` e pregões de papel
    com o antigo, com outro hash e de outro plano."""
    pasta = _pasta(tmp_path / "codigo")
    novo = codigo.hash_estrategia("x", pasta)
    p1 = _plano.salvar(**campos_plano(strategy="x", wfa_id=1,
                                      codigo_hash=antigo))
    p2 = _plano.salvar(**campos_plano(strategy="x", wfa_id=2,
                                      codigo_hash=antigo))
    with db.connect_write() as con:
        for lig, dia, pid, h in [(1, "2026-10-14", p1, antigo),
                                 (1, "2026-10-15", p1, antigo),
                                 (1, "2026-10-16", p1, "b" * 64),
                                 (2, "2026-10-16", p2, antigo)]:
            con.execute("INSERT INTO papel_pregoes (ligacao_id, dia, "
                        "plano_id, codigo_hash, status) VALUES (?,?,?,?,?)",
                        [lig, dia, pid, h, "conferido"])
    return pasta, novo, p1, p2


def _hashes():
    with db.connect(read_only=True) as con:
        return (con.execute("SELECT plano_id, codigo_hash FROM planos_operacao "
                            "ORDER BY 1").fetchall(),
                con.execute("SELECT ligacao_id, dia, codigo_hash FROM "
                            "papel_pregoes ORDER BY 1, 2").fetchall())


def test_reassinar_troca_so_o_plano_provado_e_seus_pregoes(banco, tmp_path):
    antigo = "a" * 64
    pasta, novo, p1, p2 = _cenario(tmp_path, antigo)
    with db.connect_write() as con:
        feito = codigo.reassinar(con, [{
            "plano_id": p1, "hash_antigo": antigo, "hash_novo": novo,
            "identicos": True, "n_trades": 10}], pasta=pasta)
    assert feito == [{"plano_id": p1, "hash_antigo": antigo,
                      "hash_novo": novo, "planos": 1, "pregoes": 2}]
    planos, pregoes = _hashes()
    assert dict(planos) == {p1: novo, p2: antigo}
    assert [h for *_, h in pregoes] == [novo, novo, "b" * 64, antigo]


@pytest.mark.parametrize("muda", [
    {"identicos": False}, {"identicos": None}, {"n_trades": 0},
    {"hash_antigo": "c" * 64},       # o plano não tem esse hash
    {"hash_novo": "d" * 64},         # não é o do código no disco
])
def test_reassinar_recusa_sem_prova_e_nao_grava_nada(banco, tmp_path, muda):
    antigo = "a" * 64
    pasta, novo, p1, p2 = _cenario(tmp_path, antigo)
    bom = {"plano_id": p1, "hash_antigo": antigo, "hash_novo": novo,
           "identicos": True, "n_trades": 10}
    ruim = dict(bom, plano_id=p2, **muda)
    antes = _hashes()
    with db.connect_write() as con, pytest.raises(ValueError):
        # o item bom vem antes: a recusa tem de valer para o lote inteiro
        codigo.reassinar(con, [bom, ruim], pasta=pasta)
    assert _hashes() == antes


def test_plano_reassinado_volta_a_rodar(tmp_path):
    """O motivo que a tela Ao vivo (e o papel) mostra some com o hash novo."""
    vigor = {"codigo_hash": "a" * 64}
    assert ao_vivo._motivo(True, True, None, None, vigor, "f" * 64) == \
        "código mudou desde o plano"
    vigor["codigo_hash"] = "f" * 64
    assert ao_vivo._motivo(True, True, None, None, vigor, "f" * 64) is None
