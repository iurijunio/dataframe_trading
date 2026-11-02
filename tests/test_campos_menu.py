"""Prova de que o menu não perdeu nem mudou nenhum campo (scripts/campos_menu.py).

`tests/dados/campos_menu.json` foi gravado do menu antigo e NUNCA é regravado.
"""
import json

from dash import dcc, html

from scripts import campos_menu as cm

# as únicas trocas de rótulo permitidas no menu novo (rascunho aprovado)
ROTULOS_NOVOS = {"Alvo (pontos)": "alvo", "Stop (pontos)": "stop",
                 "Trailing (pontos)": "trailing", "tempo gráfico": "tempo"}

# "sem entradas" virou um rótulo só sobre os três seletores: cada seletor
# perde o seu (fica sem rótulo, None)
ROTULOS_PERDIDOS = {"e-sem-ent1": "sem entradas · 1",
                    "e-sem-ent2": "sem entradas · 2",
                    "e-sem-ent3": "sem entradas · 3"}


# o menu antigo não tinha rótulo visível sobre estes dois seletores; o novo
# tem (rascunho aprovado). Só estes dois ganham rótulo onde não havia.
ROTULOS_GANHOS = {"ativo": "ativo", "estrategia": "estratégia"}


def _rotulo(c):
    if c["rotulo"] is None and c["id"] in ROTULOS_GANHOS:
        return ROTULOS_GANHOS[c["id"]]
    if ROTULOS_PERDIDOS.get(c["id"]) == c["rotulo"]:
        return None
    return ROTULOS_NOVOS.get(c["rotulo"], c["rotulo"])


def _normaliza(campos):
    return {c["id"]: {**c, "rotulo": _rotulo(c)} for c in campos}


def test_campos_do_menu_iguais_a_referencia():
    ref = json.loads(cm.ARQUIVO.read_text(encoding="utf-8"))
    assert ref, "referência vazia"
    problemas = []
    for chave, antigos in ref.items():
        simbolo, estrategia = chave.split("|")
        velho = _normaliza(antigos)
        novo = _normaliza(json.loads(json.dumps(cm.menu(simbolo, estrategia))))
        for i in sorted(set(velho) | set(novo)):
            if velho.get(i) != novo.get(i):
                problemas.append(f"{chave}: {i}\n  ref={velho.get(i)}\n  hoje={novo.get(i)}")
    assert not problemas, "campos diferem:\n" + "\n".join(problemas)


def test_extrair_ignora_estrutura():
    def a():
        return html.Div([html.Label("A rótulo"), dcc.Input(id="a", value=1)],
                        className="fld")

    def b():
        return html.Div([html.Label(["B ", html.Span("?", className="dica-mark")]),
                         dcc.Dropdown(id="b", value="x", options=["x", "y"])],
                        className="fld")

    plano = cm.extrair(html.Div([a(), b()]))
    aninhado = cm.extrair(html.Details([html.Summary("x"), html.Div([b()]), a()]))
    assert plano == aninhado
    assert [c["id"] for c in plano] == ["a", "b"]
    assert plano[1]["rotulo"] == "B"
    assert plano[1]["options"] == ["x", "y"]


def test_extrair_ignora_ids_novos():
    arv = html.Div([dcc.RadioItems(id="menu-aba", value="a", options=["a"]),
                    dcc.Input(id={"type": "gaveta", "i": 1}),
                    dcc.Input(id={"type": "menu-pane", "i": 1}),
                    dcc.Input(id="vale", value=2)])
    assert [c["id"] for c in cm.extrair(arv)] == ["vale"]
