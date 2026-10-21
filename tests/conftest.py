"""Isolamento global: nenhum teste pode alcancar o data/database.duckdb real.

Por que autouse: basta um teste esquecer a fixture `banco` (ou importar
`ui.app.build`, que roda init_schema e saneamento) para gravar no banco do
usuario, onde moram contas, ligacoes e o diario. Aqui so o DB_PATH e desviado;
PARQUET_DIR fica como esta porque testes leem barras reais do espelho.

O estado.json da captura tambem: o servico do usuario fica sempre rodando,
e um teste que o lesse mudaria de resultado com a hora do dia e o pregao.
Os modulos que o leem sao importados aqui mesmo (custa ~0,4 s uma vez):
desviar so os ja importados deixaria escapar o teste que importa um deles
dentro da propria funcao.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cli  # noqa: E402
import corrigir_base  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import comandos  # noqa: E402
from core import diario_ordens  # noqa: E402
from ui import data as ui_data  # noqa: E402


def pytest_configure(config):
    # medição de tempo (orçamento da ordem, spec ao-vivo-ordens §3.1): roda
    # na suíte normal; a marca só permite separá-la (-m "not lento")
    config.addinivalue_line("markers", "lento: teste que mede tempo de cálculo")


@pytest.fixture(autouse=True)
def _banco_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "isolado.duckdb")
    estado = tmp_path / "ao_vivo" / "estado.json"
    for modulo in (ui_data, cli, corrigir_base):
        monkeypatch.setattr(modulo, "ESTADO_CAPTURA", estado)
    # diario das ordens: a captura real le essa pasta ao subir, e um teste
    # que escrevesse nela mudaria o que ela acha que ja enviou
    monkeypatch.setattr(diario_ordens, "PASTA", tmp_path / "ao_vivo" / "ordens")
    # comandos da tela: um teste que escrevesse na pasta real seria consumido
    # pela captura do usuario (ex.: um "zerar_tudo" de verdade)
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "ao_vivo" / "comandos")
    # a conta real tem a sua pasta: um teste não pode deixar comando para o
    # processo da conta real do usuário
    monkeypatch.setattr(comandos, "PASTA_REAL",
                        tmp_path / "ao_vivo" / "comandos_real")
    # memoria da ultima leitura: sem zerar, um teste herdaria o estado do outro
    monkeypatch.setattr(ui_data, "_estado_ultimo", None)
    monkeypatch.setattr(ui_data, "_conferencia_vista", None)
