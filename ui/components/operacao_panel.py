"""Sub-tela Ao vivo › Operação: o papel do portfólio, ao vivo.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6–§7.

Só desenha. Quem lê é `ui/callbacks_operacao.py`: o estado.json a cada 2 s
(situação e candle em formação) e o banco, via `core.papel_leitura`, só
quando a captura recalcula o papel. Por isso tudo aqui recebe dicionários
no formato do core — dá para testar cada frase sem banco.

Muitas variantes (spec §6.4) é o caso normal, não o raro: um portfólio de
clusters passa fácil de dez. Daí as regras do desenho — nome numa linha só
com reticências e o nome inteiro no `title`; a coluna de variantes e a
tabela rolam por dentro, sem empurrar o resto da tela; a legenda é uma
fileira de chips que rola de lado e esconde a variante no gráfico.
"""
from __future__ import annotations

# Casca: o código mora em `ui/components/operacao/`; quem importa este arquivo segue funcionando.
from .operacao.base import (  # noqa: F401
    CHART_CURVA,
    CINZA,
    SUBTELA,
    _FAIXAS,
    _ROTULOS_MAX,
    _SAIU_POR,
    _TITULO_MAX,
    _etiqueta,
    _hora,
    _lado_pos,
    _preco,
    _rotulo,
    _rs,
    _sinal,
    amostra,
    cor,
    forma,
)
from .operacao.kpis import (  # noqa: F401
    _barra,
    _kpi,
    _kpi_papel,
    kpis,
)
from .operacao.variantes import (  # noqa: F401
    _APAGADO,
    _BOTOES,
    _CHAVE,
    _NOMES_BOTAO,
    _SEM_VARIANTES,
    _STATUS,
    _ST_VAZIO,
    _acerto,
    _botao,
    _contratos_txt,
    _fase,
    _lapis,
    _lapis_conta,
    _parte_titulo,
    _seta_posicao,
    cabecalho_colunas,
    cabecalho_colunas_conta,
    cartao_variante,
    cartoes,
    cartoes_por_conta,
    chips,
    coluna_variantes,
    estado_botao,
    estatisticas,
    legenda,
    linha_da_conta,
    risco_dia,
)
from .operacao.operacoes import (  # noqa: F401
    _ABERTA_PARADA,
    _cel,
    _ctr_demo,
    _papel_x_demo,
    linha_operacao,
    marcadores_tela,
    tabela_operacoes,
    tick_operacao,
)
from .operacao.situacao import (  # noqa: F401
    _SO_CONTA,
    _TIPO_ALERTA,
    _TOM_ETIQUETA,
    _atraso,
    _epoch_dia,
    _fator,
    _linha,
    _seg,
    _sep,
    _tom_execucao,
    curva_nota,
    curva_series,
    faixa_situacao,
    lista_alertas,
    tabela_comparativo,
)
from .operacao.bloco import (  # noqa: F401
    ABAS,
    _TITULO_ENVIO,
    _aba_diario,
    _aba_operacoes,
    _conta_curta,
    _curva_papel_esperado,
    _sec_head,
    bloco,
    botoes_portfolio,
    cabecalho,
    interruptor_envio,
)
