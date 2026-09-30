"""Callbacks da tela Ao vivo. Dois callbacks só: `agir` (todo clique vai
ao core e sobe `av-versao`) e `desenhar` (lê o banco e redesenha). Um
redesenho único evita um callback por botão escrevendo nas mesmas
saídas — que é como se chega a ciclo e a tela congelada sem erro."""
from __future__ import annotations


def register(app):
    return None
