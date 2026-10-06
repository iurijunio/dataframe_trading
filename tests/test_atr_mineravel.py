"""Stop e alvo por ATR entram na varredura como qualquer outro campo da
camada 4.

Antes disto os quatro campos ATR existiam só como inputs fixos na barra
lateral: a mineração não os varria. Um campo de execução fora do schema é
exatamente o tipo de coisa que fica calada — a tela roda, a tabela aparece,
e ninguém percebe que o ATR nunca mudou.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.optimizer import combinacoes, montar_espaco  # noqa: E402
from ui.callbacks import CAMPOS_PERFIL, SCHEMA_EXECUCAO  # noqa: E402

ATR = ("stop_atr_periodo", "stop_atr_mult",
       "alvo_atr_periodo", "alvo_atr_mult")

# os inputs fixos que a faixa substitui — se algum voltar, a tela tem dnv
# um campo que a varredura não enxerga
ANTIGOS_IDS = ("e-alvo-atr-per", "e-alvo-atr-mult",
               "e-stop-atr-per", "e-stop-atr-mult")


def test_atr_esta_no_schema_da_mineracao_e_nao_tem_dono_por_id():
    """No schema = a varredura sabe varrer; fora de CAMPOS_PERFIL = o
    valor é reposto pela faixa, não por dois donos (regra do
    test_carregar_completo)."""
    assert set(ATR) <= set(SCHEMA_EXECUCAO)
    por_id = {c for _, c in CAMPOS_PERFIL}
    assert not set(ATR) & por_id


def test_atr_vira_linha_de_faixa_na_barra_lateral():
    """Os inputs fixos viraram campo com faixa (de/passo/até + interruptor)
    — é o `_opt` que a mineração lê pelo padrão {type: val|opt|opt-on}."""
    from ui.components.controls import execucao

    def componentes(c):
        if isinstance(c, (list, tuple)):
            for x in c:
                yield from componentes(x)
            return
        if isinstance(c, (str, int, float, bool, type(None))):
            return
        yield c
        filhos = getattr(c, "children", None)
        if filhos is not None:
            yield from componentes(filhos)

    ids = [c.id for c in componentes(execucao()) if getattr(c, "id", None)]
    ainda_fixos = [c for c in ids if c in ANTIGOS_IDS]
    assert ainda_fixos == [], f"inputs fixos de ATR ainda na tela: {ainda_fixos}"
    for p in ATR:
        assert {"type": "val", "p": p} in ids, p
        assert {"type": "opt-on", "p": p} in ids, p


def test_faixa_de_atr_vira_espaco_de_varredura():
    """Faixa ligada na tela -> lista de valores no produto cartesiano da
    varredura, com o tipo certo (período inteiro, multiplicador quebrado)."""
    ranges = {p: {"on": True, "valor": 20, "de": 5, "passo": 5, "ate": 15}
              for p in ATR}
    espaco = montar_espaco(SCHEMA_EXECUCAO, ranges)
    for p in ATR:
        assert espaco[p] == [5, 10, 15], p
    combos = combinacoes(espaco)
    assert combos and all(set(ATR) <= set(c) for c in combos)


def test_atr_fora_do_ranges_vira_valor_fixo_do_padrao():
    """Ranges vindo de mineração antiga (sem ATR): a varredura continua
    definida — cada campo cai no valor fixo, não some do produto."""
    espaco = montar_espaco(SCHEMA_EXECUCAO, {})
    for p in ATR:
        assert len(espaco[p]) == 1, p


def test_caixa_limpa_na_tela_cai_no_padrao_do_campo():
    """O campo limpo chega como {valor: None}; sem a queda para o default,
    montar_espaco devolve [None] e CADA combinação estoura dentro de _uma —
    a varredura acaba vazia e sem aviso nenhum na tela."""
    campos = list(ATR) + ["alvo_razao"]
    espaco = montar_espaco(SCHEMA_EXECUCAO,
                           {p: {"valor": None} for p in campos})
    for p in campos:
        assert espaco[p] == [SCHEMA_EXECUCAO[p]["default"]], p
