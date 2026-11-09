"""A prova de divisão tem de aprovar mudança só de lugar e reprovar cada defeito plantado."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("provar_divisao", RAIZ / "scripts" / "provar_divisao.py")
pd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pd)

ANTES = {
    "pkg/grande.py": '''"""Módulo grande."""
import math

LIMITE = 10
log = object()


def area(r):
    return math.pi * r * r


def _ajuda(x):
    return x + LIMITE


class Motor:
    TIPO = "a"

    def passo(self, x):
        return _ajuda(x)

    def sair(self):
        return area(1)


def register(app):
    """Liga a tela."""
    ESTADO = {}

    @app.callback("a")
    def um(v):
        return v

    @app.callback("b")
    def dois(v):
        return ESTADO.get(v)
''',
}

# Divisão correta: funções em dois arquivos novos, o antigo reexporta.
CERTO = {
    "pkg/grande.py": '''"""Agora só reexporta."""
from pkg.contas import LIMITE, area, _ajuda, log
from pkg.motor import Motor
from pkg.telas import register
''',
    "pkg/contas.py": '''"""Contas."""
import math

LIMITE = 10
log = object()


def area(r):
    return math.pi * r * r


def _ajuda(x):
    return x + LIMITE
''',
    "pkg/motor.py": '''from pkg.contas import _ajuda, area


class Motor:
    TIPO = "a"

    def passo(self, x):
        return _ajuda(x)

    def sair(self):
        return area(1)
''',
    "pkg/telas.py": '''def register(app):
    ESTADO = {}

    @app.callback("a")
    def um(v):
        return v

    @app.callback("b")
    def dois(v):
        return ESTADO.get(v)
''',
}


def _com(arquivo, de, para):
    novo = dict(CERTO)
    assert novo[arquivo].count(de) == 1
    novo[arquivo] = novo[arquivo].replace(de, para)
    return novo


def test_divisao_certa_passa():
    problemas, _ = pd.comparar(ANTES, CERTO)
    assert problemas == []


def test_sem_mudar_nada_passa():
    assert pd.comparar(ANTES, ANTES)[0] == []


@pytest.mark.parametrize("arquivo,de,para,trecho", [
    ("pkg/contas.py", "return x + LIMITE", "return x - LIMITE", "_ajuda: o código mudou"),
    ("pkg/contas.py", "LIMITE = 10", "LIMITE = 11", "constante LIMITE: o código mudou"),
    ("pkg/motor.py", "    def sair(self):\n        return area(1)\n", "", "Motor.sair: sumiu"),
    ("pkg/motor.py", 'TIPO = "a"', 'TIPO = "b"', "classe Motor: o código mudou"),
    ("pkg/motor.py", "from pkg.contas import _ajuda, area", "from pkg.contas import _ajuda", "nomes indefinidos area"),
    ("pkg/telas.py", '    @app.callback("b")', '    @app.callback("c")', "register/dois: o código mudou"),
    ("pkg/telas.py", "    ESTADO = {}\n", "", "register/<linha>"),
    ("pkg/grande.py", "from pkg.motor import Motor\n", "", "deixou de oferecer Motor"),
    ("pkg/contas.py", "def _ajuda(x):", "def _ajudante(x):", "_ajuda: sumiu"),
])
def test_defeito_plantado_reprova(arquivo, de, para, trecho):
    problemas, _ = pd.comparar(ANTES, _com(arquivo, de, para))
    assert any(trecho in p for p in problemas), problemas


def test_import_trocado_por_outro_de_mesmo_nome_reprova():
    antes = {"pkg/a.py": "from math import pi\n\n\ndef f():\n    return pi\n"}
    depois = {"pkg/a.py": "from pkg.b import f\n", "pkg/b.py": "from cmath import pi\n\n\ndef f():\n    return pi\n"}
    assert any("f: nome agora vem de outro lugar: pi" in p for p in pd.comparar(antes, depois)[0])
    certo = {"pkg/a.py": "from pkg.b import f\n", "pkg/b.py": "from math import pi\n\n\ndef f():\n    return pi\n"}
    assert pd.comparar(antes, certo)[0] == []


def test_import_relativo_resolve_igual_de_outra_pasta():
    antes = {"ui/c/x.py": "from .. import theme as T\n\n\ndef f():\n    return T\n"}
    depois = {"ui/c/x.py": "from .p.m import f\n", "ui/c/p/m.py": "from ... import theme as T\n\n\ndef f():\n    return T\n",
              "ui/c/p/__init__.py": ""}
    assert pd.comparar(antes, depois)[0] == []
    errado = dict(depois, **{"ui/c/p/m.py": "from .. import theme as T\n\n\ndef f():\n    return T\n"})
    assert any("nome agora vem de outro lugar: T" in p for p in pd.comparar(antes, errado)[0])


def test_casca_reexportando_outro_objeto_reprova():
    novo = _com("pkg/grande.py", "from pkg.motor import Motor", "from pkg.motor import Motor\nfrom pkg.contas import area as _ajuda")
    novo["pkg/grande.py"] = novo["pkg/grande.py"].replace("area, _ajuda, log", "area, log")
    assert any("_ajuda agora aponta para def:area" in p for p in pd.comparar(ANTES, novo)[0])


REG_ANTES = {"ui/cb.py": '''def register(app):
    @app.callback("a")
    def um(v):
        return v

    @app.callback("b")
    def dois(v):
        return v
'''}
REG_DEPOIS = {
    "ui/cb.py": "from .cbp import p1, p2\n\n\ndef register(app):\n    p1.register(app)\n    p2.register(app)\n",
    "ui/cbp/__init__.py": "",
    "ui/cbp/p1.py": 'def register(app):\n    @app.callback("a")\n    def um(v):\n        return v\n',
    "ui/cbp/p2.py": 'def register(app):\n    @app.callback("b")\n    def dois(v):\n        return v\n',
}


def test_register_dividido_em_partes_passa():
    assert pd.comparar(REG_ANTES, REG_DEPOIS)[0] == []


def test_parte_de_register_esquecida_reprova():
    depois = dict(REG_DEPOIS, **{"ui/cb.py": "from .cbp import p1, p2\n\n\ndef register(app):\n    p1.register(app)\n"})
    assert any("ninguém o chama" in p for p in pd.comparar(REG_ANTES, depois)[0])


def test_delegacao_com_outro_argumento_conta_como_codigo_novo():
    depois = dict(REG_DEPOIS, **{"ui/cb.py": "from .cbp import p1, p2\n\n\ndef register(app):\n"
                                              "    p1.register(app)\n    p2.register(None)\n"})
    problemas = pd.comparar(REG_ANTES, depois)[0]
    assert any("linhas soltas mudaram" in p for p in problemas)


def test_funcao_repetida_reprova():
    novo = dict(CERTO)
    novo["pkg/extra.py"] = "def area(r):\n    return math.pi * r * r\n\nimport math\n"
    assert any("area: repetido" in p for p in pd.comparar(ANTES, novo)[0])


def test_codigo_novo_reprova():
    novo = _com("pkg/contas.py", "def area(r):", "def nova():\n    return 1\n\n\ndef area(r):")
    assert any("nova: é novo" in p for p in pd.comparar(ANTES, novo)[0])


def test_arquivo_antigo_apagado_reprova():
    novo = {k: v for k, v in CERTO.items() if k != "pkg/grande.py"}
    assert any("arquivo apagado" in p for p in pd.comparar(ANTES, novo)[0])


def test_alerta_quando_codigo_muda_para_arquivo_com_file():
    novo = _com("pkg/contas.py", '"""Contas."""', '"""Contas."""\nAQUI = __file__')
    novo["pkg/grande.py"] += "AQUI = 1\n"
    antes = dict(ANTES)
    antes["pkg/grande.py"] += "AQUI = __file__\n"
    _, alertas = pd.comparar(antes, novo)
    assert any("__file__" in a for a in alertas)


def test_indefinidos_entende_escopos():
    fonte = '''import os
from x import y as z
G = 1


class C:
    A = 2
    B = A + G

    def m(self):
        return [i for i in range(G)] + [os, z, C, self]


def f(a, *b, **c):
    def g():
        return a + G
    try:
        pass
    except ValueError as e:
        print(e)
    return g, nao_existe
'''
    assert pd.indefinidos(fonte) == {"nao_existe"}


def test_nenhum_falso_alarme_nos_arquivos_do_projeto():
    rastreados = subprocess.run(["git", "ls-files", "*.py"], cwd=RAIZ, capture_output=True, text=True).stdout.split()
    alarmes = {}
    for a in rastreados:
        if (RAIZ / a).exists():
            faltam = pd.indefinidos((RAIZ / a).read_text(encoding="utf-8"), a)
            if faltam:
                alarmes[a] = faltam
    assert alarmes == {}
