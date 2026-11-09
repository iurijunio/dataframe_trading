"""Pesquisa: camada 4 e período do ativo, arranque, troca de ativo e estratégia."""
from __future__ import annotations

from dash import no_update

from core import ativo as ativo_mod
from core.engine.execution import ExecutionProfile
from core import optimizer
from core.optimizer import MINERACAO
from strategies import registry

from .. import data as D
from ..components import controls, scatter, stats_cards

from .menu import _simbolo
from .base import CAMPOS_PERFIL, _mineracao_na_tela, _mineracao_rodando


# Saídas da camada 4 que seguem o ativo, na ordem de `_camada4_do_ativo`:
# primeiro os valores fixos (stop e alvo abrem a lista, como antes vinham do
# perfil), depois as células da faixa e por fim o `step` de todas as caixas,
# como `controls._opt` faz (Dash 4.4.1: valor digitado fora do `step` vira
# None; os micros andam em pontos inteiros, e o passo de mineração 2 numa
# caixa de step 10 seria recusado).
CAMPOS_C4 = ("stop_pontos", "alvo_pontos", "trailing_pontos")
SAIDAS_C4 = (
    [({"type": "val", "p": c}, "value", "valor") for c in CAMPOS_C4]
    + [({"type": "opt", "p": c, "k": k}, "value", k)
       for c in CAMPOS_C4 for k in ("de", "passo", "ate")]
    + [({"type": "val", "p": c}, "step", "step") for c in CAMPOS_C4]
    + [({"type": "opt", "p": c, "k": k}, "step", "step")
       for c in CAMPOS_C4 for k in ("de", "passo", "ate")]
)
# Só o `step` das 12 caixas: `estrategia_ou_mineracao` também o escreve, ao
# carregar uma mineração salva (a escala é a do ativo DELA, não a do seletor).
SAIDAS_C4_STEP = [s for s in SAIDAS_C4 if s[1] == "step"]


def _tabela_c4(simbolo) -> dict:
    """{campo: {valor, de, passo, ate, step}} de stop, alvo e trailing no
    ativo: a faixa da ficha (step 1, pontos inteiros) ou, sem faixa (o WIN,
    ou símbolo nenhum), `controls.PADRAO_C4` com o step de hoje."""
    faixas = ativo_mod.faixas_do_ativo(simbolo)
    tabela = {}
    for c in CAMPOS_C4:
        valor, de, passo, ate, step = controls.PADRAO_C4[c]
        f = faixas.get(c)
        tabela[c] = ({"valor": valor, "de": de, "passo": passo, "ate": ate,
                      "step": step} if not f else
                     {"valor": f.get("valor", valor), "de": f.get("de", de),
                      "passo": f.get("passo", passo), "ate": f.get("ate", ate),
                      "step": 1})
    return tabela


def _camada4_do_ativo(simbolo) -> list:
    """Valores de `SAIDAS_C4` para o ativo (`_tabela_c4`) — é o que faz a
    volta do MES para o WIN restaurar a tela.

    Com mineração rodando nada muda: os campos são os da varredura. Parada,
    ela sai da tela na mesma troca (`_trocar_ativo`), então os campos seguem
    o ativo — a guarda não pode olhar a tabela: os dois callbacks do `ativo`
    correm juntos, e ela pode ainda não ter sido esquecida."""
    if _mineracao_rodando():
        return [no_update] * len(SAIDAS_C4)
    tabela = _tabela_c4(_simbolo(simbolo))
    return [tabela[ident["p"]][chave] for ident, _prop, chave in SAIDAS_C4]


def _perfil_do_ativo(simbolo) -> tuple:
    """Saída de `aplicar_perfil_do_ativo`: horários e custos do perfil padrão
    e a camada 4 (`_camada4_do_ativo`). Com a mineração rodando nada muda —
    fecha a janela do começo da varredura, antes de o seletor desligar."""
    if _mineracao_rodando():
        return (no_update,) * (6 + len(SAIDAS_C4))
    p = ativo_mod.perfil_padrao(ativo_mod.ficha(_simbolo(simbolo)))
    perfil = (no_update,) * 6 if not p else tuple(p.get(c, no_update) for c in (
        "entrada_inicio", "entrada_fim", "fechamento", "corretagem",
        "emolumentos", "slippage_ticks"))
    return perfil + tuple(_camada4_do_ativo(simbolo))


def _periodo_do_ativo(simbolo) -> tuple:
    """Saída de `periodo_do_ativo`: (de, de.min, de.max, até, até.min,
    até.max) da base do ativo — o período inteiro, como na abertura.

    O calendário era montado uma vez, na subida, com a base do ativo padrão:
    o MNQ (base desde 2019) abria em 16/03/2021, a do WIN, e nem deixava
    escolher antes. Com a mineração rodando nada muda (o seletor do ativo
    fica desligado; isto cobre a corrida)."""
    if _mineracao_rodando():
        return (no_update,) * 6
    inicio, fim = D.span(_simbolo(simbolo))
    de, ate = inicio.date(), fim.date()
    return de, de, ate, ate, de, ate


# posição, na saída de `estrategia_ou_mineracao`, do primeiro `step` da
# camada 4 (depois dos 17 fixos e de CAMPOS_PERFIL)
_INICIO_STEP = 17 + len(CAMPOS_PERFIL)


def _estrategia_ou_mineracao(gatilho, nome, run_id, simbolo, ids_val,
                             ids_faixa, ids_on):
    """Corpo de `estrategia_ou_mineracao`, fora do `register` para os testes."""
    sem_mudanca = [no_update] * (_INICIO_STEP + len(SAIDAS_C4_STEP))
    sem_mudanca[9:12] = ([no_update] * len(ids_val),
                         [no_update] * len(ids_faixa),
                         [no_update] * len(ids_on))
    if gatilho == "mine-carregar":
        return _carregar_mineracao(run_id, ids_val, ids_faixa, ids_on,
                                   sem_mudanca)
    if gatilho == "ativo":
        return _trocar_ativo(nome, simbolo, sem_mudanca)
    if gatilho == "arranque":
        return _arranque(nome, simbolo, ids_val, ids_faixa, ids_on,
                         sem_mudanca)
    return _trocar_estrategia(nome, sem_mudanca, simbolo=_simbolo(simbolo))


def _arranque(nome, simbolo, ids_val, ids_faixa, ids_on, r):
    """A página acabou de abrir: o menu segue a mineração da memória.

    O layout é estático — depois de um F5 o menu nasce na estratégia padrão,
    mas a mineração que ficou na memória (e a estratégia do servidor, com que
    o clique numa linha roda) pode ser de outra: era a tabela da ADX debaixo
    do Cruzamento. Salva e parada, volta a tela inteira, como se escolhida no
    seletor. Rodando ou não salva, o menu passa à estratégia dela, com a
    seção nas faixas que ela varreu. Sem mineração, nada muda."""
    e = MINERACAO.estado
    if not _mineracao_na_tela():
        return r
    if e.get("run_id") and not e.get("rodando"):
        r = _carregar_mineracao(e["run_id"], ids_val, ids_faixa, ids_on, r)
        if r[0] is not no_update:        # carregou (a salva ainda existe)
            r[1] = e["run_id"]
        return r
    est = e.get("estrategia")
    if not est or est == nome:
        return r
    mod = registry.definir(est)
    espaco = MINERACAO._contexto.get("espaco")
    simbolo = (e.get("symbol") or MINERACAO._contexto.get("symbol")
               or _simbolo(simbolo))
    r[0] = est
    r[2] = controls.campos_da_estrategia(
        mod, optimizer.faixas_do_espaco(espaco) if espaco else None,
        ativo_mod.faixas_do_ativo(simbolo, est))
    return r


def _trocar_ativo(nome, simbolo, r):
    """Refaz a seção de parâmetros na escala do ativo novo.

    Com mineração rodando não mexe em nada: nem seção, nem `esquecer`/`parar`
    (o seletor do ativo fica desligado enquanto ela corre). Com uma tabela
    parada na tela — carregada do banco ou recém-rodada, salva ou não — ela
    sai, como na troca de estratégia: a varredura é de outro ativo, e os
    campos vão seguir o novo. Sem mineração, só a seção."""
    if _mineracao_rodando():
        return r
    nome = nome or registry.nome_atual()
    secao = controls.campos_da_estrategia(
        registry.carregar(nome), None,
        ativo_mod.faixas_do_ativo(_simbolo(simbolo), nome))
    if _mineracao_na_tela():
        MINERACAO.esquecer()
        r[1:9] = _tela_sem_mineracao(secao)
    else:
        r[2] = secao
    return r


# Para o `progresso` esvaziar as análises, conta-se com o Dash 4.4.1
# disparar os callbacks seguintes para TODA prop devolvida, mesmo com o valor
# igual (dash_renderer, executedCallbacks não compara): com a mineração
# recém-rodada e não salva, `mine-carregar` já era None.
def _tela_sem_mineracao(secao) -> tuple:
    """`r[1:9]` de `estrategia_ou_mineracao` com a mineração fora da tela:
    seletor vazio (o `progresso` refaz a marca e as análises esvaziam), a
    seção dada, nota, tabela, nuvem, cards, trades e curva."""
    return (None, secao, "", [],
            scatter.vazio("Rode uma mineração para ver a nuvem de parâmetros."),
            stats_cards.vazio(), [], [])


def _trocar_estrategia(nome, r, simbolo=None):
    """Troca a estratégia e zera TUDO que veio da anterior.

    Não é higiene: os parâmetros mudam de nome e de significado entre
    estratégias, então uma tabela de mineração antiga ao lado dos campos
    novos seria um convite a clicar numa combinação que não existe mais.
    Melhor a tela vazia — inclusive o seletor da mineração carregada.
    """
    mod = registry.definir(nome)
    MINERACAO.esquecer()
    r[1:9] = _tela_sem_mineracao(controls.campos_da_estrategia(
        mod, None, ativo_mod.faixas_do_ativo(simbolo, nome)))
    return r


def _carregar_mineracao(run_id, ids_val, ids_faixa, ids_on, r):
    """Carregar uma mineração repõe a TELA INTEIRA como ela estava.

    Não bastam as linhas da tabela: sem o perfil de execução e as faixas
    de volta nos campos, clicar numa combinação rodaria o backtest com o
    que estiver na tela agora — outro timeframe, outro custo, outra
    janela — e o resultado não bateria com a linha clicada.
    """
    if not run_id:
        return r
    d = optimizer.detalhes_salva(run_id)
    if not d:
        return r

    # A mineração manda: ela carrega a própria estratégia junto. Antes
    # isto era recusado, e a tela ficava mostrando "Cruzamento de médias"
    # com uma varredura de rompimento de canal carregada.
    try:
        mod = registry.definir(d["estrategia"])
    except Exception:
        r[12] = (f"mineração #{run_id} é da estratégia “{d['estrategia']}”, "
                 "que não está mais em strategies/")
        return r
    MINERACAO.estado["estrategia"] = d["estrategia"]

    faixas = optimizer.faixas_do_espaco(d["espaco"])
    perfil = d["perfil"] or {}
    # a reserva é a escala do ativo DA MINERAÇÃO, não a do seletor: uma
    # varredura do MES aberta com o WIN no topo não pode ganhar os 50 em 50
    # do WIN no parâmetro que ela não varreu. Só os da estratégia: a camada 4
    # tem dono próprio.
    do_ativo = {p: f for p, f in ativo_mod.faixas_do_ativo(
        d.get("symbol"), d["estrategia"]).items() if p in mod.params_schema}
    # stop, alvo e trailing também na escala da mineração: sem isto as
    # caixas ficavam com o step do ativo anterior (10 do WIN) recebendo o
    # 8 do MES, e o Dash 4.4.1 apaga o valor fora do step ao sair da caixa
    c4 = _tabela_c4(d.get("symbol"))

    def de_faixa(p, k, senao):
        for fonte in (faixas.get(p) or {}, do_ativo.get(p) or {}):
            if fonte.get(k) is not None:
                return fonte[k]
        return senao

    # os parâmetros da estratégia vão embutidos na seção reconstruída;
    # os outputs por id cuidam só dos campos da camada 4
    r[0] = d["estrategia"]
    r[2] = controls.campos_da_estrategia(mod, faixas, do_ativo)
    r[3] = ""
    # campo que a mineração antiga nem conhecia (sem entradas, ADX) cai
    # no padrão do motor - com no_update ficava o que estava na tela, e
    # o backtest do clique dava outro lucro que o da tabela
    padrao = ExecutionProfile().to_config()
    def valor_c4(p):
        v = perfil.get(p)
        return v if v is not None else c4[p]["valor"]

    r[9] = [de_faixa(i["p"], "valor", valor_c4(i["p"])) if i["p"] in c4 else
            de_faixa(i["p"], "valor",
                     perfil.get(i["p"], padrao.get(i["p"], no_update)))
            for i in ids_val]
    r[10] = [de_faixa(i["p"], i["k"],
                      c4[i["p"]][i["k"]] if i["p"] in c4 else no_update)
             for i in ids_faixa]
    r[11] = [["on"] if faixas.get(i["p"], {}).get("on") else []
             for i in ids_on]
    r[12] = (f"mineração #{run_id} carregada"
             + (f" · “{d['nome']}”" if d["nome"] else ""))

    # o walk-forward volta junto: é ele que define o corte do holdout,
    # e o backtest único precisa medir a mesma janela que a tabela mediu
    w = d.get("wf_config") or {}
    r[13:17] = (w.get("treino_meses", no_update), w.get("teste_meses", no_update),
                w.get("passo_meses", no_update), w.get("holdout_meses", no_update))
    r[17:_INICIO_STEP] = [perfil.get(chave, padrao.get(chave, no_update))
                          for _, chave in CAMPOS_PERFIL]
    r[_INICIO_STEP:] = [c4[ident["p"]]["step"]
                        for ident, _prop, _chave in SAIDAS_C4_STEP]
    return r


def _esquecer_combinacao(gatilho):
    """O `store-combinacao` depois da troca. O ativo trocado com a varredura
    correndo não tira nada da tela (`_trocar_ativo`), então a combinação
    aberta continua valendo."""
    if gatilho == "ativo" and _mineracao_rodando():
        return no_update
    return None


def _ativo_desligado(desligado_agora):
    """`ativo.disabled`: desligado enquanto a mineração corre ou está sendo
    salva — trocar o ativo no meio da varredura mudaria os campos que ela
    lê, e no meio do salvar tiraria da tela a mineração sendo gravada.
    `no_update` quando não muda, para o dropdown não redesenhar a cada
    800 ms."""
    e = MINERACAO.estado
    novo = bool(e.get("rodando") or e.get("salvando"))
    return no_update if bool(desligado_agora) == novo else novo
