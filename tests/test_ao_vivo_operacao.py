# tests/test_ao_vivo_operacao.py
"""Quem roda, quem não roda e por quê (spec Ao vivo §4.6)."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import codigo, db_manager as db, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = date(2026, 10, 1)


def _variante_com_plano(nome="v", run_id=1, hash_="__atual__",
                        agora=datetime(2026, 9, 1, 10), **extra):
    """Variante de rompimento_canal com plano gravado. `hash_="__atual__"`
    grava a impressão digital do código de hoje (confere)."""
    v = variantes.criar(nome, "rompimento_canal")
    mineracao(run_id, variante_id=v)
    wfa(run_id, run_id)
    h = codigo.hash_estrategia("rompimento_canal") if hash_ == "__atual__" else hash_
    pid = plano.salvar(**campos_plano(wfa_id=run_id, run_id=run_id,
                                      codigo_hash=h, **extra), agora=agora)
    return v, pid


def _portfolio(nome, *variantes_ids, ligado=True):
    pid = P.criar(nome)
    ligs = [P.adicionar_variante(pid, v) for v in variantes_ids]
    if ligado:
        AV.ligar_portfolio(pid)
    return pid, ligs


def _uma(hoje=QUI):
    [l] = AV.em_operacao(hoje)
    return l


def test_tudo_certo_roda(banco):
    v, pid = _variante_com_plano()
    _portfolio("p", v)
    l = _uma()
    assert l["roda"] is True and l["motivo"] is None
    assert l["plano"]["plano_id"] == pid and l["fase"] == "papel"
    assert l["avisos"] == []


def test_ordem_dos_motivos(banco):
    """Portfólio desligado ganha de tudo; depois disjuntor, pausa, plano,
    código — o primeiro que se aplica é o que a tela mostra."""
    v, _ = _variante_com_plano(hash_="outro")
    pf, [lig] = _portfolio("p", v, ligado=False)
    AV.desligar_membro(lig, por="disjuntor")
    assert _uma()["motivo"] == "portfólio desligado"
    AV.ligar_portfolio(pf)
    assert _uma()["motivo"].startswith("desligada pelo disjuntor em ")
    AV.ligar_membro(lig)
    AV.desligar_membro(lig)
    assert _uma()["motivo"] == "pausada por você"
    AV.ligar_membro(lig)
    assert _uma()["motivo"] == "código mudou desde o plano"


def test_sem_plano_em_vigor(banco):
    v = variantes.criar("v", "rompimento_canal")
    _portfolio("p", v)
    l = _uma()
    assert l["motivo"] == "sem plano em vigor" and l["plano"] is None


def test_codigo_nao_encontrado(banco):
    v = variantes.criar("v", "estrategia_que_nao_existe")
    mineracao(1, variante_id=v, strategy="estrategia_que_nao_existe")
    wfa(1, 1, strategy="estrategia_que_nao_existe")
    plano.salvar(**campos_plano(strategy="estrategia_que_nao_existe"),
                 agora=datetime(2026, 9, 1, 10))
    _portfolio("p", v)
    assert _uma()["motivo"] == "código da estratégia não encontrado"


def test_hash_nulo_e_aviso_nao_motivo(banco):
    v, _ = _variante_com_plano(hash_=None)
    _portfolio("p", v)
    l = _uma()
    assert l["roda"] is True
    assert "código não conferido (plano anterior a 30/09/2026)" in l["avisos"]


def test_plano_futuro_vencido_e_contagens(banco):
    v, velho = _variante_com_plano(reotimizar_em=date(2026, 9, 20))
    novo = plano.salvar(**campos_plano(), agora=datetime(2026, 10, 1, 14))
    _portfolio("p", v)
    l = _uma()
    assert l["plano"]["plano_id"] == velho
    assert l["plano_futuro"] == {"plano_id": novo, "vale_a_partir": date(2026, 10, 2)}
    assert f"plano #{novo} entra em 02/10" in l["avisos"]
    assert "plano vencido: reotimizar desde 20/09/2026" in l["avisos"]
    # pregões contam o que o papel rodou (tabela papel_pregoes), não dias
    # úteis: sem papel gravado, 0 (a contagem com papel: test_papel_dados)
    assert l["pregoes_com_plano"] == 0


def test_conta_da_fase(banco):
    v, _ = _variante_com_plano()
    pf, [lig] = _portfolio("p", v)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET fase = 'demo' "
                    "WHERE ligacao_id = ?", [lig])
    assert "conta demo não escolhida ou arquivada" in _uma()["avisos"]
    demo = AV.criar_conta("D", "demo")
    AV.definir_contas(pf, demo, None)
    assert "conta demo não escolhida ou arquivada" not in _uma()["avisos"]


def test_repetidas_so_entre_ligados(banco):
    v, _ = _variante_com_plano()
    _portfolio("A", v)
    _, [lig_b] = _portfolio("B", v)
    _portfolio("C", v, ligado=False)
    [r] = AV.repetidas()
    assert r["variante_id"] == v and sorted(r["portfolios"]) == ["A", "B"]
    avisos = [l["avisos"] for l in AV.em_operacao(QUI) if l["portfolio_nome"] == "A"][0]
    assert "também em 1 outro(s) portfólio(s) ligado(s) — os contratos somam na conta" in avisos
    AV.desligar_membro(lig_b)
    assert AV.repetidas() == []


def test_removida_nao_aparece(banco):
    v, _ = _variante_com_plano()
    pf, _ = _portfolio("p", v, ligado=False)
    P.remover_variante(pf, v)
    assert AV.em_operacao(QUI) == []


def test_planos_sem_variante(banco):
    wfa(1, 1)                         # sem mineração com variante
    pid = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    v, _ = _variante_com_plano(run_id=2)
    [o] = AV.planos_sem_variante()
    assert o["plano_id"] == pid and o["strategy"] == "rompimento_canal"
