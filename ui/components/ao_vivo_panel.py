"""Tela Ao vivo: seletor no topo entre duas sub-telas.

- Estratégias — o que está (ou vai estar) rodando. Spec:
  docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md §5.
- Pregão — o serviço de captura e o gráfico do dia ao vivo; desenhada em
  `pregao_panel.py`. Spec: docs/superpowers/specs/2026-10-01-ao-vivo-captura-design.md §6.
- Operação — o papel do portfólio ao vivo; desenhada em
  `operacao_panel.py`. Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §6.

Só desenha — quem lê o banco é `ui/callbacks_ao_vivo.py` (Estratégias) e
`ui/callbacks_pregao.py` (Pregão). As outras sub-telas (Conta, Histórico)
só entram quando a parte delas existir: tela vazia confunde.

Desenho: cada bloco mostra primeiro o nome e a situação (etiqueta
colorida), depois os detalhes como rótulo → valor. Cores das etiquetas,
iguais na tela inteira: verde = ligado/liberada, cinza = desligado/parada,
âmbar = atenção, rosa = problema.
"""
from __future__ import annotations

# Casca: o código mora em `ui/components/ao_vivo/`; quem importa este arquivo segue funcionando.
from .ao_vivo.base import (  # noqa: F401
    _EVENTOS,
    _METODOS,
    _botao,
    _campo_dd,
    _campo_txt,
    _chip,
    _data,
    _data_iso,
    _disjuntor_texto,
    _estrategias,
    _etiqueta,
    _kv,
    _metodo,
    _num,
    _pct,
    _plural,
    _reais,
    _rotulado,
    _secao,
    _vale_legado,
    painel,
    resumo_topo,
)
from .ao_vivo.portfolio import (  # noqa: F401
    _chave_envio,
    _envio_demo,
    _envio_real,
    _limite_conta,
    _tabela_contas_pf,
    cartao_portfolio,
)
from .ao_vivo.ficha import (  # noqa: F401
    _aviso_tag,
    _demo_ate_agora,
    _etapa,
    _linha_contratos,
    _sem,
    _tick,
    _tom_motivo,
    _trilha,
    bloco_ordens_ficha,
    cartao_variante,
    ficha_rastreio,
    selo_ordens_backtest,
    selo_papel_backtest,
)
from .ao_vivo.contas import (  # noqa: F401
    _pasta_curta,
    _planos_txt,
    limite_br,
    linha_conta,
    linha_orfao,
    tabela_contas,
)
