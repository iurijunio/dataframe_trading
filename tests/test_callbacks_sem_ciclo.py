"""Nenhum ciclo entre callbacks.

Um ciclo (A escreve o que dispara B, B escreve o que dispara A) com o
servidor em `debug=False` não dá erro nenhum: o Dash simplesmente para de
atualizar as saídas envolvidas. Foi assim que a barra de progresso do
walk-forward ficou congelada em "varrendo 0 de 41" com a varredura já
terminada no servidor. Este teste monta o grafo de dependências do app
inteiro e acusa o ciclo antes de ele chegar à tela.

O modelo é o do próprio renderer (`getReadyCallbacks` em dash-renderer):
um callback fica RETIDO enquanto algum Input dele está a jusante — direta
ou indiretamente — das Outputs de outro callback pendente. Só que os Inputs
que são também Outputs do próprio callback não contam. Por isso um callback
que lê e escreve as mesmas propriedades (limpar o seletor depois de excluir;
ser o dono único de `estrategia` e `mine-carregar`) não trava: ele nunca
espera por ninguém. O que trava é um anel de retenções entre callbacks
DIFERENTES, cada um esperando o outro terminar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.app import build  # noqa: E402


def _no(d) -> str:
    i = d["id"]
    return f"{json.dumps(i, sort_keys=True) if isinstance(i, dict) else i}.{d['property']}"


def _saidas(chave: str) -> list[str]:
    """`..a.x...b.y..` (várias saídas) ou `a.x`; `@hash` é allow_duplicate."""
    partes = chave.strip(".").split("...") if chave.startswith("..") else [chave]
    return [p.split("@")[0] for p in partes]


# Ciclos que já existiam quando este teste nasceu, como pares de callbacks
# (quem segura, quem fica retido). Ficam listados, e não ignorados em
# silêncio: qualquer ciclo NOVO reprova, e o teste de baixo avisa quando um
# destes for desfeito (aí a linha sai daqui).
#
# Vazio desde que `trocar_estrategia` e `restaurar_config` viraram um callback
# só (`estrategia_ou_mineracao`), dono de `estrategia` e `mine-carregar`.
CICLOS_CONHECIDOS: set[tuple[str, str]] = set()


def _callbacks(app):
    """[(nome, entradas, saídas)] — o nome é o da função, para a mensagem."""
    out = []
    for chave, cb in app.callback_map.items():
        func = cb.get("callback")
        nome = getattr(func, "__name__", None) or chave
        out.append((nome, {_no(e) for e in cb["inputs"]}, set(_saidas(chave))))
    return out


def _grafo_de_retencao(callbacks, ignorar=CICLOS_CONHECIDOS):
    """{quem segura: {quem fica retido}}.

    `alcance(B)` é o que o renderer chama de getAllSubsequentOutputsForCallback:
    as saídas de B, mais as saídas de todo callback disparado por elas, até o
    fim. A fica retido por B se um Input de A que não é saída do próprio A
    está nesse alcance.
    """
    por_entrada: dict[str, list[int]] = {}
    for i, (_, entradas, _s) in enumerate(callbacks):
        for e in entradas:
            por_entrada.setdefault(e, []).append(i)

    def alcance(i):
        tocadas, fila = set(), [i]
        while fila:
            novas = callbacks[fila.pop()][2] - tocadas
            tocadas |= novas
            fila.extend(j for s in novas for j in por_entrada.get(s, ()))
        return tocadas

    arestas: dict[str, set[str]] = {}
    for b, (nome_b, _e, _s) in enumerate(callbacks):
        alc = alcance(b)
        for a, (nome_a, entradas_a, saidas_a) in enumerate(callbacks):
            if a != b and (entradas_a - saidas_a) & alc \
                    and (nome_b, nome_a) not in ignorar:
                arestas.setdefault(nome_b, set()).add(nome_a)
    return arestas


def _grafo(ignorar=CICLOS_CONHECIDOS):
    return _grafo_de_retencao(_callbacks(build()), ignorar)


def _ciclo(arestas):
    BRANCO, CINZA, PRETO = 0, 1, 2
    cor: dict[str, int] = {}
    pilha: list[str] = []

    def visita(n):
        cor[n] = CINZA
        pilha.append(n)
        for m in arestas.get(n, ()):
            if cor.get(m, BRANCO) == CINZA:
                return pilha[pilha.index(m):] + [m]
            if cor.get(m, BRANCO) == BRANCO:
                achado = visita(m)
                if achado:
                    return achado
        pilha.pop()
        cor[n] = PRETO
        return None

    for n in list(arestas):
        if cor.get(n, BRANCO) == BRANCO:
            achado = visita(n)
            if achado:
                return achado
    return None


def test_o_app_nao_tem_ciclo_entre_callbacks():
    ciclo = _ciclo(_grafo())
    assert ciclo is None, "ciclo: " + " → ".join(ciclo)


def test_o_modo_candidata_existe_e_tem_painel():
    app = build()
    texto = str(app.layout)
    assert "'Candidata'" in texto and "'candidata'" in texto
    assert "painel-candidata" in texto


def test_os_ciclos_conhecidos_ainda_existem():
    """Quando um deles for desfeito, este teste falha para lembrar de tirá-lo
    da lista — senão a lista vira um lugar para esconder ciclos novos."""
    arestas = _grafo(ignorar=set())
    for origem, destino in CICLOS_CONHECIDOS:
        assert destino in arestas.get(origem, set()), (origem, destino)


def test_o_detector_acha_um_ciclo_de_verdade():
    """Sem este, um detector quebrado passaria o teste de cima para sempre."""
    assert _ciclo({"a.x": {"b.y"}, "b.y": {"c.z"}, "c.z": {"a.x"}})
    assert _ciclo({"a.x": {"b.y"}, "b.y": {"c.z"}}) is None


def test_dois_callbacks_escrevendo_um_o_gatilho_do_outro_travam():
    """O desenho antigo: trocar a estratégia limpa o seletor, carregar do
    seletor troca a estratégia — cada um retém o outro."""
    cbs = [("trocar", {"estrategia.value"}, {"mine.value", "params.children"}),
           ("restaurar", {"mine.value"}, {"estrategia.value", "campos.value"})]
    assert _ciclo(_grafo_de_retencao(cbs, ignorar=set()))


def test_um_dono_unico_das_duas_propriedades_nao_trava():
    """O desenho novo: um callback lê e escreve as duas; quem só lê fica
    retido por ele, mas ele não espera por ninguém."""
    cbs = [("dono", {"estrategia.value", "mine.value"},
            {"estrategia.value", "mine.value", "params.children"}),
           ("progresso", {"tick.n", "mine.value"}, {"grid.rowData"}),
           ("listar", {"estrategia.value"}, {"mine.options"})]
    assert _ciclo(_grafo_de_retencao(cbs, ignorar=set())) is None


def test_o_anel_passando_por_um_terceiro_tambem_trava():
    """A retenção é transitiva: B segura A mesmo que um C fique no meio."""
    cbs = [("a", {"x.v"}, {"y.v"}),
           ("c", {"y.v"}, {"z.v"}),
           ("b", {"z.v"}, {"x.v"})]
    assert _ciclo(_grafo_de_retencao(cbs, ignorar=set()))
