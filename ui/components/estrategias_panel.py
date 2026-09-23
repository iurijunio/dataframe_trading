"""Lista de estratégias e, dentro de cada uma, as variantes em uso.

Só a fatia de identidade (projeto D, parte 1) — metadados ricos por
estratégia (autor, perfil, o que cada parâmetro faz) ficam de fora, ver
docs/superpowers/specs/2026-09-23-identidade-estrategia-design.md §2.
"""
from __future__ import annotations

from dash import html


def painel():
    return html.Div(
        [
            html.Section([
                html.H2("Estratégias", className="panel-title"),
                html.Div(id="est-lista", className="est-lista"),
            ], className="panel"),
            html.Section(
                id="est-detalhe", className="panel", style={"display": "none"},
                children=[
                    html.H3(id="est-detalhe-titulo"),
                    html.Div(id="est-variantes"),
                ],
            ),
        ],
        id="painel-estrategias", className="modo-bloco",
        style={"display": "none"},
    )


def cartao_estrategia(modulo: str, label: str, n_params: int) -> html.Div:
    return html.Div(
        [html.Span(label, className="est-cartao-nome"),
         html.Span(f"{n_params} parâmetros", className="est-cartao-nota")],
        id={"type": "est-cartao", "modulo": modulo},
        className="est-cartao", n_clicks=0,
    )


def linha_variante(nome: str, ciclos: list[dict]) -> html.Div:
    ativo = next((c for c in reversed(ciclos) if c.get("plano_estado") == "ativo"), None)
    nota = (f"plano ativo (mineração #{ativo['run_id']})" if ativo
            else f"{len(ciclos)} ciclo(s), sem plano ativo" if ciclos
            else "sem minerações ainda")
    return html.Div(
        [html.Span(nome, className="est-variante-nome"),
         html.Span(nota, className="est-variante-nota")],
        className="est-variante",
    )
