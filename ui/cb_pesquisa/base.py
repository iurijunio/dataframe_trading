"""Pesquisa: campos do perfil, tabela, detalhes, robustez e mineração salva."""
from __future__ import annotations

import numpy as np

from core import ativo as ativo_mod, detalhes, robustez
from core import mineracao_stats as MS
from core import wfa
from core import wfa_runner
from core import porteira
from core.engine import kernel as K
from core import optimizer
from core.optimizer import MINERACAO
from strategies import registry

from ..components import analytics_charts as AC
from ..components import detalhes_cards as DC
from ..components import robustez_cards as RC

from .menu import _simbolo


# schema dos campos da camada 4 que a mineracao tambem pode varrer. Os
# NOMES vêm de `wfa_runner.CAMPOS_EXECUCAO_NOMES` — fonte única com
# `argumentos_da_mineracao`/`trades_oos_detalhados`; aqui só se decora cada
# nome com o passo do slider e o tipo que a tela usa.
_SCHEMA_EXECUCAO_META = {
    "alvo_pontos": {"default": 600, "step": 10, "tipo": "int"},
    "stop_pontos": {"default": 300, "step": 10, "tipo": "int"},
    "breakeven_pct": {"default": 0, "step": 5, "tipo": "float"},
    "step_gatilho_pct": {"default": 0, "step": 5, "tipo": "float"},
    "step_distancia_pct": {"default": 0, "step": 5, "tipo": "float"},
    "trailing_pontos": {"default": 0, "step": 10, "tipo": "int"},
    "alvo_razao": {"default": 2.0, "step": 0.1, "tipo": "float"},
    "alvo_atr_periodo": {"default": 20, "step": 1, "tipo": "int"},
    "alvo_atr_mult": {"default": 3.0, "step": 0.1, "tipo": "float"},
    "stop_atr_periodo": {"default": 20, "step": 1, "tipo": "int"},
    "stop_atr_mult": {"default": 1.5, "step": 0.1, "tipo": "float"},
    # porcentagem do preco de entrada: passo de centesimo de ponto percentual
    "alvo_pct": {"default": 1.0, "step": 0.01, "tipo": "float"},
    "stop_pct": {"default": 0.5, "step": 0.01, "tipo": "float"},
    # filtro de mercado (ADX): 0 = desligado, e o zero ser mineravel e o
    # que deixa medir ligado x desligado na mesma varredura
    "adx_periodo": {"default": 0, "step": 1, "tipo": "int"},
    "adx_limiar": {"default": 0, "step": 5, "tipo": "int"},
    "adx_filtro_di": {"default": 0, "step": 1, "tipo": "int"},
    "adx_subindo": {"default": 0, "step": 1, "tipo": "int"},
}
SCHEMA_EXECUCAO = {nome: _SCHEMA_EXECUCAO_META[nome]
                   for nome in wfa_runner.CAMPOS_EXECUCAO_NOMES}

# Campos da camada 4 na tela <-> chaves do ExecutionProfile gravado.
# No topo do modulo, e nao dentro de register(), para o teste poder
# cobrar que NENHUMA chave do perfil fique de fora do carregamento.
CAMPOS_PERFIL = [
("e-timeframe", "timeframe"), ("e-ent-ini", "entrada_inicio"),
("e-ent-fim", "entrada_fim"), ("e-fechamento", "fechamento"),
("e-dias", "dias_semana"), ("e-direcao", "direcao"),
("e-filtro-adx", "filtro_adx"),
("e-sem-ent1", "sem_entrada1"), ("e-sem-ent2", "sem_entrada2"),
("e-sem-ent3", "sem_entrada3"),
("e-alvo-tipo", "alvo_tipo"), ("e-stop-tipo", "stop_tipo"),
("e-max-barras", "max_barras"), ("e-lim-ganho", "limite_ganho_contrato"),
("e-lim-perda", "limite_perda_contrato"), ("e-max-trades", "max_trades_dia"),
("e-max-loss", "max_prejuizos_dia"),
("e-corretagem", "corretagem_por_contrato"),
("e-emolumentos", "emolumentos_por_contrato"),
("e-slippage", "slippage_ticks"), ("e-modo", "modo_posicao"),
("e-contratos", "contratos"), ("e-risco", "risco_por_trade"),
("e-capital", "capital_inicial"), ("e-min-ops", "min_operacoes"),
]


# quando a tabela foi empurrada para o navegador pela última vez. A folga
# existe para a varredura não gastar o processador redesenhando: com passo
# fino são milhares de linhas viajando a cada batida do relógio.
_ULTIMA_TABELA: dict = {"t": 0.0, "feitos": -1}

# O último walk-forward desenhado. Fica no servidor porque é de lá que ele
# vai para o banco: mandar as janelas até o navegador só para devolvê-las no
# clique do Salvar seria trafegar dados que nunca saíram daqui.
_WFA: dict = {}
# o cálculo das matrizes é caro e pode ser pedido por dois callbacks ao mesmo
# tempo (holdout ligado e desligado em sequência)
_MATRIZ_LOCK = __import__("threading").Lock()
FOLGA_TABELA = 2.0          # segundos


def _linhas_tabela() -> list[dict]:
    """As linhas que a tabela mostra, lidas do servidor.

    As análises não precisam recebê-las pelo callback: elas já estão em
    memória, e trafegar 5.000 dicionários de volta só para recalcular é
    justamente o que travava a tela.
    """
    return MINERACAO.estado.get("trials") or []



def _criterios_wfa(d: dict | None, e: dict):
    """Os critérios de aceite da mineração, prontos para cada janela IS.

    Vêm da mineração salva; as salvas antes de a plataforma gravá-los usam os
    padrões da tela de Critérios. A régua é a da mineração inteira (do início
    da base até o corte do holdout) e `wfa.criterios_por_janela` a traz para
    o tamanho de cada janela.

    Devolve (critérios, origem) — a origem vai para o resumo, para não
    esconder de onde veio o filtro.
    """
    salvos = (d or {}).get("criterios")
    base = salvos or {c["id"]: c["padrao"] for c in MS.CRITERIOS}
    try:
        meses = float((np.datetime64(str(e["ate_holdout"])[:10], "M")
                       - np.datetime64(str(e["de"])[:10], "M")).astype(int))
    except Exception:
        meses = 0.0
    return (wfa.criterios_por_janela(base, meses),
            "critérios da mineração" if salvos else "critérios padrão")


def _varredura(linhas):
    """As combinações que a ESTATÍSTICA deve enxergar.

    A tabela é truncada em 5.000 linhas pelo ranking, e truncada pelo topo:
    julgar a varredura por ela seria julgar só a metade boa. `estado["resumo"]`
    carrega todas as combinações válidas, com os campos que estas contas leem.
    O `fonte` evita o pior dos casos — uma varredura antiga ainda em memória
    descrevendo a mineração que você acabou de carregar do banco.
    """
    e = MINERACAO.estado
    completo = e.get("resumo")
    if completo and e.get("fonte"):
        return completo
    return linhas or []


def _referencias_operadas(res, perfil, f=None):
    """Stop e alvo que o motor operou, mediana por trade.

    O perfil pode guardar valores que nunca entraram em jogo (alvo por
    multiplicador do stop, ATR, stop da estratégia) — as sugestões e as
    linhas do MAE/MFE precisam do operado, senão o "% do alvo" que a tela
    mostra estaria errado no número em que o usuário decide o que mexer.
    Sem trades, cai no perfil (não há mediana para tirar). Sai sempre em
    pontos (o perfil da tela já é humano; sl/tp guardados voltam por `f`).
    """
    sl, tp = res.sl_at_entry, res.tp_at_entry
    stop = (ativo_mod.pontos_para_exibir(int(np.median(sl)), f)
            if len(sl) else perfil.stop_pontos)
    alvo = (ativo_mod.pontos_para_exibir(int(np.median(tp)), f)
            if len(tp) else perfil.alvo_pontos)
    return stop, alvo


def _detalhes(res, run, liq, f=None):
    """Monta a aba Detalhes: o que MEXER, em oposição ao "isto é sorte?" da
    Robustez. Sai tudo dos mesmos arrays — nenhum backtest roda de novo."""
    p, t, m = run["profile"], res.trades, run["metrics"]
    if not m.get("trades"):
        return DC.vazio("Nenhum trade para detalhar.")

    # o slippage ja esta embutido em points: sem descontá-lo aqui, TODA saida
    # por stop apareceria como stop furado
    # (em ativo com centavos, tudo em pontos: o tick vem da ficha, nao do
    # instrumento guardado)
    if ativo_mod._identidade(f):
        folga = int(p.slippage_ticks * int(res.instrument.get("tick_size", 1)))
    else:
        folga = p.slippage_ticks * f.tick_size
    moeda = getattr(f, "currency", "BRL")
    t = ativo_mod.trades_para_exibir(t, f)
    tp_ent = ativo_mod.pontos_para_exibir(res.tp_at_entry, f)
    sl_ent = ativo_mod.pontos_para_exibir(res.sl_at_entry, f)

    return DC.render(
        m,
        detalhes.sequencias(liq),
        detalhes.eficiencia(t["mae"], t["mfe"], t["points"],
                            tp_ent, t["reason"], K.EXIT_TARGET),
        detalhes.risco_trade(liq, t["points"], sl_ent,
                             t["reason"], K.EXIT_STOP, folga),
        detalhes.ritmo(res.trades["entry_ts"], liq, int(t["bars_held"].sum()),
                       res.n_bars, run["pregoes"]),
        AC.barras(detalhes.resultado_por_volume(res.trades["entry_ts"], liq),
                  "Resultado por nº de trades no pregão", moeda=moeda),
        casas=0 if ativo_mod._identidade(f) else f.price_decimals,
        moeda=moeda,
    )


def _robustez(res, run, liq):
    """Monta a aba de triagem. Tudo sai dos trades que já existem — nenhum
    backtest roda de novo, e por isso cabe recalcular a cada execução."""
    p = run["profile"]
    t = res.trades
    if len(liq) < 10:
        return RC.vazio("Poucos trades para avaliar robustez.")

    capital = p.capital_inicial
    dias = int((t["exit_ts"][-1] - t["entry_ts"][0]).astype("timedelta64[D]")
               .astype(int))
    dinheiro = run["dinheiro"]
    custo_ponta = p.corretagem_por_contrato + p.emolumentos_por_contrato
    moeda = ativo_mod.moeda_de(run.get("simbolo"))

    return RC.render(
        robustez.monte_carlo(liq, capital),
        robustez.significancia(liq),
        robustez.teste_runs(liq),
        robustez.correlacao_lr(liq, capital),
        robustez.concentracao(liq),
        robustez.ulcer_mar(liq, capital, dias),
        robustez.meses_positivos(t["entry_ts"], liq),
        robustez.custo_que_zera(float(dinheiro["bruto"].sum()),
                                dinheiro["contratos"], custo_ponta),
        robustez.drawdowns(t["entry_ts"], liq, capital),
        porteira.sqn(liq),
        moeda=moeda,
    )


def _chave_matriz(run_id, geracao, estende, trava, valores=None) -> str:
    """A chave do cache da matriz — um lugar só.

    Quem guarda e quem lê montavam a string cada um por sua conta, e bastou
    a camada 4 entrar na conta de um lado para o outro nunca mais achar a
    matriz: `sharpes_matriz` passou a ser gravado vazio em todo walk-forward
    salvo, sem erro nenhum aparecer.

    Os VALORES travados entram na chave porque a matriz agora depende deles:
    trocar de inteligência pode travar noutro stop, e a matriz guardada seria
    de outra camada 4 — certa na aparência, errada no conteúdo.
    """
    marca = "-".join(f"{k}={valores[k]}" for k in sorted(valores or {}))
    return (f"{run_id}-{geracao}-{int(bool(estende))}-{int(bool(trava))}"
            + (f"-{marca}" if marca else ""))


def _mineracao_na_tela() -> bool:
    """Há uma mineração rodando, ou uma tabela dela (recém-rodada ou
    carregada do banco) na tela."""
    e = MINERACAO.estado
    return bool(e.get("rodando") or e.get("trials"))


def _lista_salvas(gatilho, estrategia, ativo) -> list[dict]:
    """Corpo de `listar_salvas`: as salvas da estratégia que está NA TELA.

    Não da memória do servidor (`registry.nome_atual`): ela guarda a última
    estratégia usada, e ao reabrir a página a tela volta no padrão — a lista
    mostrava as salvas da outra. E na troca este callback corre junto com
    `estrategia_ou_mineracao`, que é quem troca a memória: lendo dela, a lista
    saía um passo atrás. Ao abrir a página (sem gatilho) é aqui que a memória
    se acerta com a tela — o Rodar e o Minerar leem dela —, menos com uma
    mineração na tela (rodando, ou parada depois de um F5): aí é o menu que
    segue a mineração (`_arranque`), e a lista é da estratégia dela."""
    nome = estrategia or registry.nome_atual()
    if gatilho is None and _mineracao_na_tela():
        # o menu vai seguir a mineração (`_arranque`); a lista já nasce na
        # estratégia dela, senão o seletor apagaria a marca da salva
        nome = MINERACAO.estado.get("estrategia") or registry.nome_atual()
    elif gatilho is None:
        registry.definir(nome)
    return [{"label": r["rotulo"], "value": r["run_id"]}
            for r in optimizer.listar_salvas(nome, simbolo=_simbolo(ativo))]


def _mineracao_rodando() -> bool:
    """Trocar o ativo com a varredura correndo não pode refazer campos nem
    interromper nada (o seletor fica desligado; isto cobre a corrida). Parada,
    a troca tira a mineração da tela (`_trocar_ativo`) e os campos seguem o
    ativo novo — reescrevê-los com ela na tela deixaria a tabela descrevendo
    outra coisa."""
    return bool(MINERACAO.estado.get("rodando"))
