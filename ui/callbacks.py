"""Reatividade.

Quatro fluxos, e nenhum deles reinicia o estado global:

  rodar         -> backtest, cartoes, curva de capital, tabela e grafico
  navegar       -> so o grafico de preco muda (faixa e timeframe)
  clicar trade  -> grafico vai ate o trade e desenha entrada, stop e alvo
  mexer na faixa-> recalcula o tamanho do espaco de busca da mineracao

O resultado do backtest fica num cache do processo, indexado por um token que
circula pelo dcc.Store. Arrays numpy de 20 mil trades nao viajam para o
navegador: so as linhas da tabela viajam.
"""
from __future__ import annotations

# Casca: o código mora em `ui/cb_pesquisa/`; quem importa este arquivo segue funcionando.
# Módulos e objetos que os testes leem pela casca (`CB.D`, `CB.optimizer`...): o mesmo objeto.
from core import optimizer  # noqa: F401
from core.optimizer import MINERACAO  # noqa: F401
from strategies import registry  # noqa: F401

from . import data as D  # noqa: F401
from .components import detalhes_cards as DC  # noqa: F401
from .cb_pesquisa.menu import (  # noqa: F401
    ENTRADAS_RESUMO,
    OCULTO,
    VISIVEL,
    VISIVEL_GRADE,
    _COMBOS,
    _ativo_ao_entrar_wfa,
    _br,
    _combinacoes,
    _dias,
    _dt,
    _entrar_mineracao_salva,
    _moeda_da_mineracao,
    _n,
    _por_campo,
    _runs,
    _simbolo,
    menu_abas,
    pontinhos,
    resumo_custos,
    resumo_filtro_mercado,
    resumo_filtro_mineracao,
    resumo_gestao,
    resumo_janela,
    resumo_limites,
    resumo_posicao,
    resumo_protecoes,
    resumos,
    rotulos_moeda,
)
from .cb_pesquisa.base import (  # noqa: F401
    CAMPOS_PERFIL,
    FOLGA_TABELA,
    SCHEMA_EXECUCAO,
    _MATRIZ_LOCK,
    _SCHEMA_EXECUCAO_META,
    _ULTIMA_TABELA,
    _WFA,
    _chave_matriz,
    _criterios_wfa,
    _detalhes,
    _linhas_tabela,
    _lista_salvas,
    _mineracao_na_tela,
    _mineracao_rodando,
    _referencias_operadas,
    _robustez,
    _varredura,
)
from .cb_pesquisa.ativo import (  # noqa: F401
    CAMPOS_C4,
    SAIDAS_C4,
    SAIDAS_C4_STEP,
    _INICIO_STEP,
    _arranque,
    _ativo_desligado,
    _camada4_do_ativo,
    _carregar_mineracao,
    _esquecer_combinacao,
    _estrategia_ou_mineracao,
    _perfil_do_ativo,
    _periodo_do_ativo,
    _tabela_c4,
    _tela_sem_mineracao,
    _trocar_ativo,
    _trocar_estrategia,
)
from .cb_pesquisa.combinacao import (  # noqa: F401
    MENU_COMBINACAO,
    MENU_PERFIL,
    ORIGEM_GATILHO,
    PROTECOES,
    VAL_DO_PERFIL,
    _carregar_combinacao,
    _igual,
    _linha_combinacao,
    _menu_atual,
    _reclique_mesma_linha,
    menu_do_perfil,
    perfil_da_busca,
    perfil_do_menu,
)
from .cb_pesquisa import r_menu, r_backtest, r_mineracao, r_nuvem, r_wfa, r_wfa_salvos, r_resto


def register(app):
    r_menu.register(app)
    r_backtest.register(app)
    r_mineracao.register(app)
    r_nuvem.register(app)
    r_wfa.register(app)
    r_wfa_salvos.register(app)
    r_resto.register(app)
