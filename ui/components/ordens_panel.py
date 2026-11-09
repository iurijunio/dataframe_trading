"""Ao vivo › Operação com a demo (spec ordens §8, rascunho v2).

Construtores puros: recebem o bloco `ordens` do estado.json (o que
`core.ordens.Motor.passo` publica) ou as leituras de `core.papel_leitura`
e devolvem componentes. Quem lê é `ui/callbacks_operacao.py`: o estado a
cada 2 s (saúde, chamados, posições, os três números) e o banco só quando
`ordens_em` ou o papel mudam (operações, diário, avaliação).

Duas regras de cor atravessam o arquivo: rosa é PROBLEMA — nunca o lado
da venda (venda é azul, compra verde, em contorno); e toda métrica nova
leva um (?) com a faixa boa e a ruim, porque o usuário decide olhando a
tela, não lendo código.

Sem demo ainda (tudo no papel), cada bloco aparece vazio e explicando o
porquê — nunca quebrado nem com "None".
"""
from __future__ import annotations

# Casca: o código mora em `ui/components/ordens/`; quem importa este arquivo segue funcionando.
from .ordens.base import (  # noqa: F401
    ATENCAO_PCT,
    ATRASO_LENTO_MS,
    PERIGO_PCT,
    PROBLEMAS,
    SEM_VIDA_S,
    TRAVA_PCT,
    _COMANDOS_INTERNOS,
    _INTERNOS,
    _data,
    _decimal,
    _etiqueta,
    _hora,
    _idade_s,
    _int_sinal,
    _lado,
    _ligacoes,
    _mmss,
    _nome,
    _nome_tab,
    _preco,
    _reais,
    _rs,
    _sinal,
    _vazio,
    subtitulo,
)
from .ordens.saude import (  # noqa: F401
    _COLUNAS_SAUDE,
    _EXPLICA_CANDLE,
    _EXPLICA_VIDA,
    _SUBTEXTO,
    _celula,
    _linha_conta,
    _valores_conta,
    chave_chamado,
    faixa_chamados,
    faixa_saude,
    real_parada,
    rotulo_botao,
)
from .ordens.posicoes import (  # noqa: F401
    _cel_hoje,
    _celula_conta,
    _chip_conta,
    _kpi,
    _parte,
    _posicoes,
    _quebra,
    _situacao_posicao,
    _th,
    _total,
    numeros,
    perda_do_dia,
    posicoes_abertas,
    tom_da_perda,
)
from .ordens.operacoes import (  # noqa: F401
    _SITUACOES,
    _derrap,
    _saida_demo,
    _situacao_demo,
    _texto_evento,
    _texto_teste,
    _tom_derrap,
    diario_do_dia,
    operacoes_demo,
)
from .ordens.avaliacao import (  # noqa: F401
    _fator,
    avaliacao,
    contratos_antes,
    custo_stop_texto,
    editor_contratos,
    ler_contratos,
    selo_backtest,
    tabela_papel_demo,
)
