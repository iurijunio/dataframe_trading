"""Carregar uma mineração salva tem que repor a tela INTEIRA.

O risco aqui não é quebrar: é um campo ficar de fora em silêncio. A tela
mostra o perfil da varredura, um campo continua com o valor antigo, e o
backtest roda com uma configuração que nunca existiu — sem erro nenhum.

Por isso o teste não confere uma lista escrita à mão: ele varre as chaves
reais do `ExecutionProfile` e cobra que cada uma tenha destino. Campo novo
no perfil que ninguém ligou na tela faz este teste falhar, que é o momento
certo de descobrir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import optimizer as opt  # noqa: E402
from core.engine.execution import ExecutionProfile  # noqa: E402
from strategies import registry  # noqa: E402
from ui.callbacks import CAMPOS_PERFIL, SCHEMA_EXECUCAO  # noqa: E402

# Chaves que deliberadamente NÃO são repostas, e por quê. Vazio hoje: o
# conjunto existe para que qualquer exceção futura precise ser escrita aqui,
# com justificativa, em vez de passar despercebida.
FORA: set[str] = set()


def test_todo_campo_do_perfil_tem_destino_na_tela():
    """Nenhuma chave do ExecutionProfile pode ficar sem quem a reponha."""
    do_perfil = set(ExecutionProfile().to_config())
    por_id = {chave for _, chave in CAMPOS_PERFIL}
    por_faixa = set(SCHEMA_EXECUCAO)          # alvo, stop, proteções

    sem_destino = do_perfil - por_id - por_faixa - FORA
    assert not sem_destino, (
        "campos do perfil que ninguém repõe ao carregar uma mineração: "
        f"{sorted(sem_destino)}"
    )


def test_nenhum_campo_da_tela_aponta_para_chave_inexistente():
    """O contrário: id na tela que aponta para chave que o perfil não tem
    ficaria calado, repondo `no_update` para sempre."""
    do_perfil = set(ExecutionProfile().to_config())
    orfaos = [(cid, chave) for cid, chave in CAMPOS_PERFIL
              if chave not in do_perfil]
    assert not orfaos, f"ids apontando para chaves inexistentes: {orfaos}"


def test_nao_ha_id_repetido_no_mapeamento():
    ids = [cid for cid, _ in CAMPOS_PERFIL]
    assert len(ids) == len(set(ids))
    chaves = [c for _, c in CAMPOS_PERFIL]
    assert len(chaves) == len(set(chaves))


def test_campos_de_faixa_nao_se_repetem_no_mapeamento_por_id():
    """Alvo e stop são repostos pela faixa (têm interruptor de mineração);
    repor também por id criaria dois donos para o mesmo campo."""
    por_id = {chave for _, chave in CAMPOS_PERFIL}
    assert not (por_id & set(SCHEMA_EXECUCAO))


def test_perfil_salvo_reconstroi_um_execution_profile_valido():
    """O que volta do banco tem que montar um perfil sem faltar argumento."""
    gravado = ExecutionProfile(
        timeframe="M15", entrada_inicio="09:00", entrada_fim="17:00",
        fechamento="17:30", dias_semana=(1, 3, 5), direcao="compra",
        alvo_tipo="atr", alvo_atr_periodo=14, alvo_atr_mult=2.5,
        stop_tipo="atr", stop_atr_periodo=10, stop_atr_mult=1.2,
        breakeven_pct=40.0, step_gatilho_pct=60.0, step_distancia_pct=25.0,
        trailing_pontos=150, max_barras=40,
        limite_ganho_contrato=900.0, limite_perda_contrato=450.0,
        max_trades_dia=4, max_prejuizos_dia=2,
        corretagem_por_contrato=1.5, emolumentos_por_contrato=0.33,
        slippage_ticks=2, modo_posicao="risco_fixo", contratos=3,
        risco_por_trade=350.0, capital_inicial=25_000.0, min_operacoes=80,
    ).to_config()

    refeito = ExecutionProfile(**gravado)
    assert refeito.to_config() == gravado


def test_ida_e_volta_de_todos_os_campos_pela_tela():
    """Simula o carregamento: cada campo da tela recebe o valor gravado."""
    gravado = ExecutionProfile(
        timeframe="H1", direcao="venda", alvo_tipo="atr", stop_tipo="atr",
        breakeven_pct=30.0, trailing_pontos=90, max_barras=25,
        limite_perda_contrato=600.0, max_prejuizos_dia=3,
        slippage_ticks=4, modo_posicao="risco_fixo", risco_por_trade=500.0,
        capital_inicial=50_000.0, min_operacoes=120,
    ).to_config()

    # é assim que o callback preenche os campos por id
    na_tela = {cid: gravado.get(chave) for cid, chave in CAMPOS_PERFIL}

    assert na_tela["e-timeframe"] == "H1"
    assert na_tela["e-direcao"] == "venda"
    assert na_tela["e-alvo-tipo"] == "atr" and na_tela["e-stop-tipo"] == "atr"
    assert na_tela["e-max-barras"] == 25
    assert na_tela["e-lim-perda"] == 600.0
    assert na_tela["e-max-loss"] == 3
    assert na_tela["e-slippage"] == 4
    assert na_tela["e-modo"] == "risco_fixo"
    assert na_tela["e-risco"] == 500.0
    assert na_tela["e-capital"] == 50_000.0
    assert na_tela["e-min-ops"] == 120
    # nenhum campo mapeado pode voltar vazio quando o perfil tem a chave
    assert all(v is not None or gravado[c] is None
               for (cid, c), v in zip(CAMPOS_PERFIL, na_tela.values()))


def test_estrategia_da_varredura_existe_no_registro():
    """Carregar uma mineração troca a estratégia; se o módulo sumiu da pasta,
    isso precisa ser detectável e não explodir."""
    disponiveis = {e["modulo"] for e in registry.descobrir()}
    assert "setup_cruzamento" in disponiveis
    with pytest.raises(Exception):
        registry.carregar("estrategia_que_nao_existe")


def test_faixas_repoem_parametros_da_estrategia_e_da_gestao():
    """Os parâmetros varridos voltam como faixa; os fixos, como valor."""
    espaco = {"periodo_canal": [40, 50, 60], "folga_ticks": [9],
              "alvo_pontos": [1150], "stop_pontos": [100, 150, 200]}
    f = opt.faixas_do_espaco(espaco)

    assert f["periodo_canal"] == {"on": True, "valor": 40, "de": 40,
                                  "ate": 60, "passo": 10}
    assert f["folga_ticks"] == {"on": False, "valor": 9}
    assert f["alvo_pontos"] == {"on": False, "valor": 1150}
    assert f["stop_pontos"]["on"] and f["stop_pontos"]["passo"] == 50
