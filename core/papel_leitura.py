"""O que a sub-tela Ao vivo › Operação lê do papel. Só leitura.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

Três regras atravessam todas as contas daqui:

  - **só conta o que conta** (decisão 4): o papel calcula o dia inteiro de
    toda ligação, ligada ou não; operação com `conta = false` aparece na
    tabela e no gráfico, apagada, mas fica fora de todo total. Somá-la
    seria dizer que a variante ganhou um dinheiro que ela não ia operar;
  - **acumulado recomeça a cada plano** (§6.6): parâmetro novo é outra
    aposta. Somar o papel do plano anterior misturaria o resultado de duas
    configurações e a comparação com a faixa do plano atual não diria nada;
  - **pregão preso não é ao vivo**: um dia passado que ficou `rodando`
    (a conferência falhou) ainda tem a operação "aberta" gravada com o
    resultado provisório da última volta. Ela entra no resultado — é o
    último número que existe —, mas não é posição de agora, não desenha
    stop/alvo e aparece como "não conferida".

Recebe a conexão de quem chama (a tela abre uma de leitura por releitura) e
nunca importa Dash. Cor é só um índice estável por ligação: a tela é quem
sabe a paleta.
"""
from __future__ import annotations

# Casca: o código mora em `core/leitura/`; quem importa este arquivo segue funcionando.
from .leitura.base import (  # noqa: F401
    _ABERTURA,
    _INSTRUMENTOS,
    _PREGOES_QUE_CONTAM,
    _epoch,
    _hoje,
    _instrumento,
    _ligacoes,
    _limites,
)
from .leitura.total import (  # noqa: F401
    total_por_ligacao,
)
from .leitura.pregao import (  # noqa: F401
    _ABERTA_PARADA,
    _COLS_OP,
    _MOTIVO_PRESO,
    _acumulado,
    _desde_o_plano,
    _ops_do_dia,
    _plano_do_dia,
    _por_ligacao,
    _pregao,
    _situacao,
    portfolios_com_papel,
)
from .leitura.resumo import (  # noqa: F401
    _conta,
    _fechamento_marcado,
    _pior_momento,
    marcadores,
    operacoes_do_dia,
    resumo,
    variantes,
)
from .leitura.esperado import (  # noqa: F401
    _acumular,
    _faixa,
    _interp,
    _marcos,
    _mediana,
    _regua,
    _serie,
    curva_vs_esperado,
)
from .leitura.comparativo import (  # noqa: F401
    _como_data,
    _custo_por_contrato,
    _demo_do_comparativo,
    _metricas,
    alertas,
    comparativo,
)
from .leitura.demo import (  # noqa: F401
    _COLS_EV,
    _ENTROU,
    _MOTIVO_SAIDA,
    _RECUSAS,
    _SAIDA_FINAL,
    _TENTOU,
    _derrapagem,
    _ligs_do_portfolio,
    _ordinal,
    _preco_medio,
    _texto_erro,
    _texto_pedido,
    _uma_operacao_demo,
    checagem_ensaio,
    eventos_ordens,
)
from .leitura.demo_resumo import (  # noqa: F401
    _CACHE_DEMO_DIA,
    _demo_do_dia,
    _fator_pontos,
    _impressao_do_dia,
    _pregoes_demo,
    comparativo_demo,
    envio_da_conta,
    nomes,
    operacoes_demo,
    situacao_backtest,
)
