"""Motor de backtest."""

# A versão do MOTOR, que vai gravada dentro de cada plano de operação.
#
# Sobe à mão, e só quando o resultado de um backtest pode mudar: regra de
# preenchimento, slippage, ordem de checagem dos limites do dia, tratamento de
# rolagem. Sem ela, um plano gravado hoje e um backtest rodado daqui a seis
# meses dão números diferentes e ninguém consegue dizer por quê.
#
# Formato: ano.mês.dia da mudança.
VERSAO = "2026.09.18"
