"""O diário da tela Ao vivo: só recebe linhas novas, nunca apaga."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import diario  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401

RAIZ = Path(__file__).resolve().parent.parent


def test_registrar_e_ler(banco):
    with db.connect_write() as con, db.transacao(con):
        eid = diario.registrar(con, "conta_criada", "usuario", conta_id=4,
                               para="Demo XP")
    [e] = diario.eventos(conta_id=4)
    assert e["evento_id"] == eid and e["tipo"] == "conta_criada"
    assert e["origem"] == "usuario" and e["para"] == "Demo XP"
    assert e["quando"] is not None


def test_filtros(banco):
    with db.connect_write() as con, db.transacao(con):
        diario.registrar(con, "membro_ligado", "usuario", ligacao_id=1)
        diario.registrar(con, "membro_desligado", "disjuntor", ligacao_id=1)
        diario.registrar(con, "membro_ligado", "usuario", ligacao_id=2)
    assert [e["tipo"] for e in diario.eventos(ligacao_id=1)] == [
        "membro_ligado", "membro_desligado"]
    assert len(diario.eventos(tipo="membro_ligado")) == 2


@pytest.mark.parametrize("tipo,origem", [("inventado", "usuario"),
                                         ("conta_criada", "robo")])
def test_tipo_ou_origem_desconhecidos_sao_recusados(banco, tipo, origem):
    with db.connect_write() as con, db.transacao(con):
        with pytest.raises(ValueError):
            diario.registrar(con, tipo, origem)


def test_nenhum_codigo_altera_ou_apaga_o_diario():
    """A garantia de 'só inserção' é esta varredura: qualquer UPDATE ou
    DELETE no diário, em core/ ou ui/, quebra aqui."""
    padrao = re.compile(r"(UPDATE|DELETE\s+FROM)\s+ao_vivo_eventos", re.I)
    achados = [str(p) for pasta in ("core", "ui")
               for p in (RAIZ / pasta).rglob("*.py")
               if padrao.search(p.read_text(encoding="utf-8"))]
    assert achados == []
