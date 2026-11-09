"""Callbacks da sub-tela Ao vivo › Operação.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

O caminho é o do Pregão, com uma trava a mais: a tela não abre o banco a
cada 2 s. O pulso (`av-op-intervalo`) lê SÓ o estado.json e escreve três
coisas — a situação, o candle em formação (`tick`) e duas marcas:
`av-op-versao` (o `papel.calculado_em`) e `av-op-ultimo` (o último candle
gravado). Quem lê o banco ouve essas marcas, o seletor e os filtros, e
nunca o pulso: com a captura recalculando o papel uma vez por minuto, a
tela relê uma vez por minuto, não trinta. `test_operacao_tela` confere.

Ações (ligar/pausar variante, ligar/desligar portfólio) são as da seção 1
(`core.ao_vivo`), com o segundo clique confirmando. Ids próprios
(`av-op-acao`): repetir o `av-acao` da Estratégias duplicaria ids na
página.
"""
from __future__ import annotations

# Casca: o código mora em `ui/cb_operacao/`; quem importa este arquivo segue funcionando.
# Módulos que os testes leem pela casca (`CO.AV`, `CO.D`, `CO.PL`): o mesmo objeto, trocar um atributo vale para todos.
from core import ao_vivo as AV  # noqa: F401
from core import papel_leitura as PL  # noqa: F401

from . import data as D  # noqa: F401
from .cb_operacao.dados import (  # noqa: F401
    ARMADO_VALE_S,
    COMANDO_RECENTE_S,
    SAIDAS_DO_PULSO,
    SIMBOLO,
    _ACOES,
    _CONFIRME,
    _DESLIGAR_ENVIO,
    _armado_valido,
    _chamados_de,
    _ler,
    _so_real,
    _visivel,
    abrir_editor,
    acao,
    acao_chamado,
    custo_editor,
    dados_demo,
    ler_diario,
    ler_ordens,
    pulso,
    pulso_ordens,
    salvar_editor,
)
from .cb_operacao.montagem import (  # noqa: F401
    _conta_do_chamado,
    _opcoes_filtro,
    juntar_demo,
    ler_curva,
    montar,
    serie_do_dia,
)
from .cb_operacao import tela, ordens


def register(app):
    tela.register(app)
    ordens.register(app)
