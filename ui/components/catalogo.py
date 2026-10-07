"""O catálogo da camada 4: como cada campo do perfil de execução se apresenta.

O `ExecutionProfile` diz O QUE existe; este arquivo diz como mostrar — o
rótulo, o grupo, o formato e quando o campo faz sentido. Quem monta uma ficha
percorre os campos do perfil, e não esta lista: um campo novo no motor
aparece na tela mesmo sem entrada aqui (no grupo "outros", com o nome cru), e
o teste acusa que falta catalogá-lo.

As opções de `select` moram aqui também, para que o texto da barra lateral e
o da ficha sejam o mesmo — "compra e venda", e não "ambas" num lugar e
"compra e venda" no outro.
"""

from __future__ import annotations

DIAS = [("seg", 1), ("ter", 2), ("qua", 3), ("qui", 4), ("sex", 5)]

OPCOES = {
    "direcao": [("compra e venda", "ambas"), ("só compra", "compra"),
                ("só venda", "venda")],
    "alvo_tipo": [("pontos fixos", "pontos"), ("múltiplo de ATR", "atr"),
                  ("múltiplo do stop", "multiplicador")],
    "stop_tipo": [("pontos fixos", "pontos"), ("múltiplo de ATR", "atr")],
    "modo_posicao": [("contratos fixos", "contratos_fixos"),
                     ("risco fixo", "risco_fixo")],
    # o rotulo ja diz a regua inteira: o value e so a chave do motor
    "filtro_adx": [("tendência · ADX ≥ limiar", "tendencia"),
                   ("rango · ADX < limiar", "rango")],
    # (rótulo, value): a tela mostra "13h"; o value é "HH:00" para o motor
    # parsear com _minutes
    "hora": [("—", "")] + [(f"{h:02d}h", f"{h:02d}:00") for h in range(24)],
}


def opcoes(campo: str) -> list[dict]:
    """No formato do `dcc.Dropdown`."""
    return [{"label": r, "value": v} for r, v in OPCOES[campo]]


# A ordem dos grupos é a ordem de leitura da ficha.
GRUPOS = ["Filtro de mercado", "Janela", "Gestão", "Proteções",
          "Limites diários", "Custos", "Posição", "Filtro de mineração"]

# campo -> (grupo, rótulo, formato[, (campo, valor) em que ele vale])
#
# formatos: texto · int · num · opcao · dias · brl · desliga (0 = desligado)
#           · brl_desliga · pct_alvo · ticks · sim_nao (0/1 = não/sim)
CAMPOS: dict[str, tuple] = {
    "filtro_adx": ("Filtro de mercado", "ADX · régua", "opcao"),
    "adx_periodo": ("Filtro de mercado", "ADX · período", "desliga"),
    "adx_limiar": ("Filtro de mercado", "ADX · limiar", "desliga"),
    "adx_filtro_di": ("Filtro de mercado", "DI confirma o lado", "sim_nao",
                      ("filtro_adx", "tendencia")),
    "adx_subindo": ("Filtro de mercado", "ADX subindo", "sim_nao",
                    ("filtro_adx", "tendencia")),

    "timeframe": ("Janela", "tempo gráfico", "texto"),
    "entrada_inicio": ("Janela", "entradas de", "texto"),
    "entrada_fim": ("Janela", "entradas até", "texto"),
    "fechamento": ("Janela", "fechar posições às", "texto"),
    "dias_semana": ("Janela", "dias da semana", "dias"),
    "direcao": ("Janela", "direção", "opcao"),
    "sem_entrada1": ("Janela", "sem entradas · 1", "hora"),
    "sem_entrada2": ("Janela", "sem entradas · 2", "hora"),
    "sem_entrada3": ("Janela", "sem entradas · 3", "hora"),

    "alvo_tipo": ("Gestão", "tipo de alvo", "opcao"),
    "alvo_pontos": ("Gestão", "alvo (pontos)", "int", ("alvo_tipo", "pontos")),
    "alvo_atr_periodo": ("Gestão", "alvo · ATR período", "int", ("alvo_tipo", "atr")),
    "alvo_atr_mult": ("Gestão", "alvo · ATR multiplicador", "num", ("alvo_tipo", "atr")),
    "alvo_razao": ("Gestão", "alvo · vezes o stop", "num",
                   ("alvo_tipo", "multiplicador")),
    "stop_tipo": ("Gestão", "tipo de stop", "opcao"),
    "stop_pontos": ("Gestão", "stop (pontos)", "int", ("stop_tipo", "pontos")),
    "stop_atr_periodo": ("Gestão", "stop · ATR período", "int", ("stop_tipo", "atr")),
    "stop_atr_mult": ("Gestão", "stop · ATR multiplicador", "num", ("stop_tipo", "atr")),

    "breakeven_pct": ("Proteções", "breakeven · gatilho", "pct_alvo"),
    "step_gatilho_pct": ("Proteções", "stop móvel · gatilho", "pct_alvo"),
    "step_distancia_pct": ("Proteções", "stop móvel · trava", "pct_alvo"),
    "trailing_pontos": ("Proteções", "trailing (pontos)", "desliga"),
    "max_barras": ("Proteções", "tempo máximo (barras)", "desliga"),

    "limite_ganho_contrato": ("Limites diários", "ganho máx. por contrato", "brl_desliga"),
    "limite_perda_contrato": ("Limites diários", "perda máx. por contrato", "brl_desliga"),
    "max_trades_dia": ("Limites diários", "máx. operações", "desliga"),
    "max_prejuizos_dia": ("Limites diários", "máx. prejuízos", "desliga"),

    "corretagem_por_contrato": ("Custos", "corretagem por contrato", "brl"),
    "emolumentos_por_contrato": ("Custos", "emolumentos por contrato", "brl"),
    "slippage_ticks": ("Custos", "slippage", "ticks"),

    "modo_posicao": ("Posição", "modo", "opcao"),
    "contratos": ("Posição", "contratos", "int", ("modo_posicao", "contratos_fixos")),
    "risco_por_trade": ("Posição", "risco por trade", "brl", ("modo_posicao", "risco_fixo")),
    "capital_inicial": ("Posição", "capital inicial", "brl"),

    "min_operacoes": ("Filtro de mineração", "mínimo de operações", "desliga"),
}
