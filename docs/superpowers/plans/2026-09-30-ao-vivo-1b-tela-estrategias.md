# Ao vivo 1b — Tela Ao vivo › Estratégias: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pôr no ar o 7º modo "Ao vivo" com a sub-tela Estratégias: portfólios com interruptor e contas, variantes com interruptor e o motivo de rodarem ou não, a ficha de rastreio (mineração → WFA → Candidata → plano → histórico), cadastro de contas e a arrumação (vincular plano órfão, renomear variante, aposentar plano).

**Architecture:** leituras novas em `core/ao_vivo.py` (`em_operacao`, `repetidas`, `planos_sem_variante`, `rastreio`), sem Dash. Tela em `ui/components/ao_vivo_panel.py` (funções que só desenham) e `ui/callbacks_ao_vivo.py` com **dois** callbacks: `agir` (todo clique → core → incrementa `av-versao`) e `desenhar` (lê o banco e redesenha as quatro seções). A lógica dos dois fica em funções testáveis (`acao`, `montar`) fora do decorator.

**Tech Stack:** Python 3.11, Dash 4.4.1, DuckDB 1.5.5, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md` §4.6, §4.7, §5 (e §4.5 para arrumação). A entrega 1a (plano `2026-09-30-ao-vivo-1a-blindagem.md`) já está no branch: `core/ao_vivo.py` tem contas, interruptores, `vincular_plano`; `core/variantes.py` tem `plano_em_vigor(variante_id, dia=None, con=None)` e `renomear`; `core/plano.py` tem `aposentar(plano_id, agora=None)`, `proximo_dia_util`; `core/codigo.py` tem `hash_estrategia`; `core/diario.py` tem `eventos(**filtros)`.

## Global Constraints

- Leia `CLAUDE.md` na raiz. Código, nomes, comentários e textos de tela em **português**, **sem jargão** (o usuário não é programador); comentário explica **por quê**.
- **Nada em `core/` importa Dash.** `core/` são contas; `ui/` liga a tela.
- Todo teste já é isolado do banco real por `tests/conftest.py` (autouse); mesmo assim use a fixture `banco` de `tests/_cadeia.py`.
- **Nunca abrir conexão nova com uma transação aberta no mesmo processo.** Leituras que chamam `V.plano_em_vigor` dentro de uma conexão passam `con=`.
- Toda recusa de regra é `ValueError` com texto em português; `RuntimeError` de `connect_write` vira "banco ocupado, tente de novo".
- Nomes de tela: **Variante**, **Plano**, **Fase** (papel · demo · real mínimo · real). Nunca "degrau", nunca "ligação" na tela (use "variante no portfólio").
- **NÃO tocar** em `ui/components/controls.py`, `ui/components/wfa_matriz.py`, `strategies/rompimento_abertura.py`. `git add` sempre por caminho.
- Git: mensagem em arquivo dentro de `.superpowers/sdd/2026-09-30-ao-vivo-1b-tela-estrategias/` + `git commit -F <arquivo>`, última linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem BOM (escreva o arquivo com a tool Write ou `printf`). Não faça push.
- Suíte: `.venv/Scripts/python.exe -m pytest -q`. Datas de teste: 2026-10-01 é **quinta**.
- Mutação ao fim de cada task de `core/`: quebrar 2–3 vezes, confirmar que um teste falha, restaurar.

---

### Task 1: Quem roda e por quê — `em_operacao`, `repetidas`, `planos_sem_variante`

**Files:**
- Modify: `core/ao_vivo.py` (acrescentar no fim)
- Test: `tests/test_ao_vivo_operacao.py`

**Interfaces:**
- Produces:
  - `ao_vivo.em_operacao(hoje: date | None = None) -> list[dict]` — uma entrada por variante-no-portfólio **não removida**, de **todos** os portfólios, ordenada por nome do portfólio e da variante. Chaves: `portfolio_id, portfolio_nome, portfolio_ligado, ligacao_id, variante_id, variante_nome, estrategia, fase, fase_desde, dias_na_fase, ligada, desligada_por, desligada_em, plano (dict|None), plano_futuro (dict|None), pregoes_com_plano, motivo (str|None), avisos (list[str]), roda (bool)`. `plano` = `{plano_id, symbol, reotimizar_em, vale_a_partir, created_at, codigo_hash}` do plano em vigor em `hoje`; `plano_futuro` = `{plano_id, vale_a_partir}` do plano ativo que ainda não vale.
  - `ao_vivo.repetidas(linhas: list[dict] | None = None) -> list[dict]` — `[{variante_id, variante_nome, portfolios: [nomes]}]` para variante **ligada** em 2+ portfólios **ligados**.
  - `ao_vivo.planos_sem_variante() -> list[dict]` — planos `estado='ativo'` com `variante_id IS NULL`: `{plano_id, run_id, wfa_id, strategy, nome, created_at}`.
  - Motivo (spec §4.6), primeiro que se aplica, nesta ordem: `"portfólio desligado"`, `"desligada pelo disjuntor em DD/MM"`, `"pausada por você"`, `"sem plano em vigor"`, `"código da estratégia não encontrado"`, `"código mudou desde o plano"`.
  - Avisos (não impedem rodar): `"código não conferido (plano anterior a 30/09/2026)"` (plano sem `codigo_hash`); `"também em N outro(s) portfólio(s) ligado(s) — os contratos somam na conta"`; `"conta demo não escolhida ou arquivada"` (fase `demo`); `"conta real não escolhida ou arquivada"` (fases `real_minimo`/`real`); `"plano vencido: reotimizar desde DD/MM/AAAA"`; `"plano #N entra em DD/MM"`.

- [ ] **Step 1: Write the failing test**

```python
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
    # velho vale desde 02/09 (qua): dias úteis 02/09..01/10 = 22
    assert l["pregoes_com_plano"] == 22


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_operacao.py`
Expected: FAIL — `AttributeError: module 'core.ao_vivo' has no attribute 'em_operacao'`

- [ ] **Step 3: Implementar — acrescentar ao fim de `core/ao_vivo.py`**

Imports no topo (junte aos existentes): `from datetime import date, datetime, timedelta` e `from . import codigo`.

```python
# ------------------------------------------------ quem roda, e por quê
_FASE_CONTA = {"demo": "demo", "real_minimo": "real", "real": "real"}


def _dias_uteis(de: date, ate: date) -> int:
    if de is None or de > ate:
        return 0
    return sum(1 for i in range((ate - de).days + 1)
               if (de + timedelta(days=i)).weekday() < 5)


def _motivo(pf_ligado, ligada, desligada_por, desligada_em, plano_vigor,
            hash_atual) -> str | None:
    """O PRIMEIRO motivo que impede rodar, na ordem da spec §4.6 — a tela
    mostra um só, e o mais estrutural ganha (portfólio antes de variante,
    variante antes de plano, plano antes de código)."""
    if not pf_ligado:
        return "portfólio desligado"
    if not ligada and desligada_por == "disjuntor":
        return f"desligada pelo disjuntor em {desligada_em:%d/%m}"
    if not ligada:
        return "pausada por você"
    if plano_vigor is None:
        return "sem plano em vigor"
    if hash_atual is None:
        return "código da estratégia não encontrado"
    if plano_vigor["codigo_hash"] and plano_vigor["codigo_hash"] != hash_atual:
        return "código mudou desde o plano"
    return None


def em_operacao(hoje: date | None = None) -> list[dict]:
    """Cada variante de cada portfólio, com o plano que vale hoje e o
    motivo de rodar ou não. Leitura só: é o que a tela Ao vivo desenha e,
    na parte 3, o que o robô vai obedecer."""
    hoje = hoje or date.today()
    with db.connect(read_only=True) as con:
        linhas = con.execute(
            "SELECT pf.portfolio_id, pf.nome, coalesce(pf.ligado, false), "
            "pf.conta_demo_id, pf.conta_real_id, pm.ligacao_id, "
            "pm.variante_id, ev.nome, ev.estrategia, pm.fase, pm.fase_desde, "
            "pm.ligada, pm.desligada_por, pm.desligada_em "
            "FROM portfolio_membros pm "
            "JOIN portfolios pf ON pf.portfolio_id = pm.portfolio_id "
            "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
            "WHERE pm.removido_em IS NULL ORDER BY pf.nome, ev.nome").fetchall()
        contas_vivas = {r[0] for r in con.execute(
            "SELECT conta_id FROM contas WHERE arquivada_em IS NULL").fetchall()}
        hashes: dict[str, str | None] = {}
        out = []
        for (pf_id, pf_nome, pf_lig, c_demo, c_real, lig, vid, v_nome,
             estrategia, fase, fase_desde, ligada, por, em) in linhas:
            vigor = V.plano_em_vigor(vid, hoje, con=con)
            plano_vigor = None
            if vigor:
                r = con.execute(
                    "SELECT plano_id, symbol, reotimizar_em, vale_a_partir, "
                    "created_at, codigo_hash FROM planos_operacao "
                    "WHERE plano_id = ?", [vigor["plano_id"]]).fetchone()
                plano_vigor = dict(zip(("plano_id", "symbol", "reotimizar_em",
                                        "vale_a_partir", "created_at",
                                        "codigo_hash"), r))
            f = con.execute(
                "SELECT plano_id, vale_a_partir FROM planos_operacao "
                "WHERE variante_id = ? AND estado = 'ativo' "
                "AND vale_a_partir > ? ORDER BY plano_id DESC LIMIT 1",
                [vid, hoje]).fetchone()
            futuro = {"plano_id": f[0], "vale_a_partir": f[1]} if f else None
            if estrategia not in hashes:
                hashes[estrategia] = codigo.hash_estrategia(estrategia)
            motivo = _motivo(pf_lig, ligada, por, em, plano_vigor,
                             hashes[estrategia])
            avisos = []
            if plano_vigor and not plano_vigor["codigo_hash"]:
                avisos.append("código não conferido (plano anterior a 30/09/2026)")
            tipo = _FASE_CONTA.get(fase)
            if tipo:
                conta = c_demo if tipo == "demo" else c_real
                if conta is None or conta not in contas_vivas:
                    avisos.append(f"conta {tipo} não escolhida ou arquivada")
            if (plano_vigor and plano_vigor["reotimizar_em"]
                    and plano_vigor["reotimizar_em"] < hoje):
                avisos.append("plano vencido: reotimizar desde "
                              f"{plano_vigor['reotimizar_em']:%d/%m/%Y}")
            if futuro:
                avisos.append(f"plano #{futuro['plano_id']} entra em "
                              f"{futuro['vale_a_partir']:%d/%m}")
            inicio = None
            if plano_vigor:
                inicio = (plano_vigor["vale_a_partir"]
                          or _plano.proximo_dia_util(
                              plano_vigor["created_at"].date()))
            out.append({
                "portfolio_id": pf_id, "portfolio_nome": pf_nome,
                "portfolio_ligado": bool(pf_lig), "ligacao_id": lig,
                "variante_id": vid, "variante_nome": v_nome,
                "estrategia": estrategia, "fase": fase,
                "fase_desde": fase_desde,
                "dias_na_fase": (hoje - fase_desde.date()).days,
                "ligada": bool(ligada), "desligada_por": por,
                "desligada_em": em, "plano": plano_vigor,
                "plano_futuro": futuro,
                "pregoes_com_plano": _dias_uteis(inicio, hoje),
                "motivo": motivo, "avisos": avisos, "roda": motivo is None,
            })
    # a mesma variante ligada em 2+ portfólios ligados roda 2+ vezes na
    # MESMA conta — decisão do usuário: permitido, só avisa
    for rep in repetidas(out):
        outros = len(rep["portfolios"]) - 1
        for item in out:
            if (item["variante_id"] == rep["variante_id"]
                    and item["portfolio_ligado"] and item["ligada"]):
                item["avisos"].append(
                    f"também em {outros} outro(s) portfólio(s) ligado(s) — "
                    "os contratos somam na conta")
    return out


def repetidas(linhas: list[dict] | None = None) -> list[dict]:
    linhas = em_operacao() if linhas is None else linhas
    por_variante: dict[int, dict] = {}
    for l in linhas:
        if not (l["portfolio_ligado"] and l["ligada"]):
            continue
        d = por_variante.setdefault(l["variante_id"], {
            "variante_id": l["variante_id"],
            "variante_nome": l["variante_nome"], "portfolios": []})
        d["portfolios"].append(l["portfolio_nome"])
    return [d for d in por_variante.values() if len(d["portfolios"]) > 1]


def planos_sem_variante() -> list[dict]:
    """Planos ativos que não pertencem a nenhuma variante — não entram em
    portfólio nenhum até serem vinculados (caso real: plano #3)."""
    cols = ("plano_id", "run_id", "wfa_id", "strategy", "nome", "created_at")
    with db.connect(read_only=True) as con:
        return [dict(zip(cols, r)) for r in con.execute(
            f"SELECT {', '.join(cols)} FROM planos_operacao "
            "WHERE estado = 'ativo' AND variante_id IS NULL "
            "ORDER BY plano_id").fetchall()]
```

> `repetidas(out)` é chamada DENTRO de `em_operacao` com a lista já pronta — nunca sem argumento ali (recursão).

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_operacao.py` → 10 passed. Se `test_plano_futuro...` divergir na contagem 22, confira à mão: 02/09/2026 é quarta; de 02/09 a 01/10 há 22 dias úteis. Ajuste o teste só se a conta à mão der outro número (e registre no relatório).

- [ ] **Step 5: Mutation** — (a) troque a ordem `pausada` antes de `disjuntor` → `test_ordem_dos_motivos` falha; (b) em `repetidas`, tire `l["portfolio_ligado"] and` → `test_repetidas_so_entre_ligados` falha; (c) `_dias_uteis` sem o filtro `weekday() < 5` → contagem falha. Restaure.

- [ ] **Step 6: Commit** — `core/ao_vivo.py`, `tests/test_ao_vivo_operacao.py`; mensagem `feat(ao-vivo): quem roda e por que - em_operacao, repetidas, planos sem variante`.

---

### Task 2: A ficha de rastreio — `rastreio`

**Files:**
- Modify: `core/ao_vivo.py` (acrescentar no fim)
- Test: `tests/test_ao_vivo_rastreio.py`

**Interfaces:**
- Consumes: `em_operacao` (Task 1), `plano.detalhes`, `optimizer.detalhes_salva`, `diario.eventos`, `codigo.hash_estrategia`.
- Produces: `ao_vivo.rastreio(ligacao_id: int, hoje: date | None = None) -> dict` com chaves:
  - `ligacao` — o item de `em_operacao` desta ligação (ValueError se não existe ou foi removida);
  - `alcance` — `"plano" | "walk-forward" | "mineração" | "nada"` (até onde a variante chegou);
  - `plano` — `plano.detalhes(...)` do plano em vigor, ou do mais recente da variante se nenhum vale; `None` se a variante não tem plano;
  - `mineracao` — `{run_id, nome, created_at, n_combinacoes, espaco, holdout_de}` ou `None` (apagada ou inexistente);
  - `wfa` — `{wfa_id, nome, created_at, is_meses, oos_meses, inteligencia, holdout, oos_lucro, oos_trades, dd_oos, veredito}` ou `None`;
  - `candidata` — `plano["regua"]` (dict) ou `None`;
  - `codigo` — `{"gravado": str|None, "atual": str|None, "confere": bool|None}` (`None` quando não há o que comparar);
  - `planos` — todos os planos da variante, mais novo primeiro: `{plano_id, estado, created_at, vale_a_partir, aposentado_em, run_id, wfa_id, contratos}`;
  - `eventos` — eventos do diário desta ligação **e** desta variante, sem repetir, mais novo primeiro.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ao_vivo_rastreio.py
"""A ficha: de onde veio o plano que a variante opera, e o que já mudou."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import codigo, db_manager as db, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401

QUI = date(2026, 10, 1)


def _cadeia_completa():
    v = variantes.criar("romp", "rompimento_canal")
    mineracao(47, variante_id=v)
    with db.connect_write() as con:
        con.execute("UPDATE mining_runs SET nome = 'mina', space = ? "
                    "WHERE run_id = 47", ['{"periodo_canal": [40, 80, 5]}'])
    wfa(13, 47)
    with db.connect_write() as con:
        con.execute("UPDATE wfa_runs SET nome = 'wfa', is_meses = 18, "
                    "oos_meses = 6, inteligencia = 'ulcer', oos_lucro = 942.5, "
                    "oos_trades = 120, dd_oos = 300.0, veredito = 'boa' "
                    "WHERE wfa_id = 13")
    h = codigo.hash_estrategia("rompimento_canal")
    pid = plano.salvar(**campos_plano(
        wfa_id=13, run_id=47, codigo_hash=h,
        regua={"veredito": "aprovada", "portoes": [
            {"nome": "Platô", "ok": True, "critico": True}]}),
        agora=datetime(2026, 9, 1, 10))
    pf = P.criar("pf")
    lig = P.adicionar_variante(pf, v)
    return v, pid, lig


def test_ficha_completa(banco):
    v, pid, lig = _cadeia_completa()
    r = AV.rastreio(lig, QUI)
    assert r["alcance"] == "plano"
    assert r["plano"]["plano_id"] == pid
    assert r["plano"]["params"] == {"periodo_canal": 78}
    assert r["mineracao"]["run_id"] == 47 and r["mineracao"]["nome"] == "mina"
    assert r["mineracao"]["espaco"] == {"periodo_canal": [40, 80, 5]}
    assert r["wfa"]["wfa_id"] == 13 and r["wfa"]["oos_lucro"] == 942.5
    assert r["wfa"]["veredito"] == "boa"
    assert r["candidata"]["veredito"] == "aprovada"
    assert r["codigo"]["confere"] is True
    assert [p["plano_id"] for p in r["planos"]] == [pid]
    tipos = {e["tipo"] for e in r["eventos"]}
    assert {"membro_adicionado", "plano_gravado"} <= tipos


def test_mineracao_apagada_usa_os_retratos(banco):
    """Com a variante fora de portfólio a proteção libera apagar; a ficha
    de outra ligação da MESMA variante, criada depois, ainda precisa ler o
    plano pelo variante_id do próprio plano."""
    v, pid, lig = _cadeia_completa()
    with db.connect_write() as con:
        con.execute("DELETE FROM mining_runs WHERE run_id = 47")
    r = AV.rastreio(lig, QUI)
    assert r["mineracao"] is None
    assert r["plano"]["plano_id"] == pid and r["alcance"] == "plano"


def test_codigo_divergente(banco):
    v, pid, lig = _cadeia_completa()
    with db.connect_write() as con:
        con.execute("UPDATE planos_operacao SET codigo_hash = 'velho'")
    assert AV.rastreio(lig, QUI)["codigo"]["confere"] is False


def test_sem_plano_mostra_ate_onde_chegou(banco):
    v = variantes.criar("nova", "rompimento_canal")
    mineracao(9, variante_id=v)
    pf = P.criar("pf")
    lig = P.adicionar_variante(pf, v)
    r = AV.rastreio(lig, QUI)
    assert r["alcance"] == "mineração" and r["plano"] is None
    assert r["mineracao"]["run_id"] == 9 and r["wfa"] is None
    assert r["codigo"]["confere"] is None
    wfa(9, 9)
    assert AV.rastreio(lig, QUI)["alcance"] == "walk-forward"


def test_nada_ainda(banco):
    v = variantes.criar("vazia", "rompimento_canal")
    lig = P.adicionar_variante(P.criar("pf"), v)
    r = AV.rastreio(lig, QUI)
    assert r["alcance"] == "nada" and r["mineracao"] is None


def test_lista_todos_os_planos(banco):
    v, p1, lig = _cadeia_completa()
    p2 = plano.salvar(**campos_plano(wfa_id=13, run_id=47),
                      agora=datetime(2026, 9, 10, 10))
    r = AV.rastreio(lig, QUI)
    assert [p["plano_id"] for p in r["planos"]] == [p2, p1]
    assert r["planos"][1]["estado"] == "aposentado"


def test_ligacao_inexistente(banco):
    with pytest.raises(ValueError):
        AV.rastreio(999, QUI)
```

> `optimizer.detalhes_salva` lê também `folds`, `wf_config` e `criterios`, que ficam nulos nesta mineração mínima. Se ele quebrar com nulos, o teste revela: trate em `rastreio` (capturar e seguir sem `espaco`) e registre no relatório — não mexa em `optimizer.py`.

- [ ] **Step 2: Run to verify it fails** — `AttributeError: ... 'rastreio'`.

- [ ] **Step 3: Implementar — acrescentar ao fim de `core/ao_vivo.py`**

Imports: `from . import optimizer as _optimizer` (confira que não há ciclo: `.venv/Scripts/python.exe -c "import core.ao_vivo"`).

```python
# ----------------------------------------------------- a ficha de rastreio
_COLS_PLANO_HIST = ("plano_id", "estado", "created_at", "vale_a_partir",
                    "aposentado_em", "run_id", "wfa_id", "contratos")
_COLS_WFA = ("wfa_id", "nome", "created_at", "is_meses", "oos_meses",
             "inteligencia", "holdout", "oos_lucro", "oos_trades", "dd_oos",
             "veredito")


def _mineracao(con, run_id):
    if run_id is None:
        return None
    r = con.execute("SELECT run_id, nome, created_at, n_combinacoes "
                    "FROM mining_runs WHERE run_id = ?", [run_id]).fetchone()
    return dict(zip(("run_id", "nome", "created_at", "n_combinacoes"), r)) if r else None


def _wfa(con, wfa_id):
    if wfa_id is None:
        return None
    r = con.execute(f"SELECT {', '.join(_COLS_WFA)} FROM wfa_runs "
                    "WHERE wfa_id = ?", [wfa_id]).fetchone()
    return dict(zip(_COLS_WFA, r)) if r else None


def rastreio(ligacao_id: int, hoje: date | None = None) -> dict:
    """Tudo o que explica o que esta variante vai operar, lido primeiro dos
    RETRATOS do plano (que sobrevivem à mineração) e só depois da mineração
    e do walk-forward, se ainda existirem (spec §5.2)."""
    hoje = hoje or date.today()
    item = next((l for l in em_operacao(hoje)
                 if l["ligacao_id"] == ligacao_id), None)
    if item is None:
        raise ValueError(f"a variante #{ligacao_id} não está em nenhum portfólio")
    vid = item["variante_id"]
    with db.connect(read_only=True) as con:
        planos = [dict(zip(_COLS_PLANO_HIST, r)) for r in con.execute(
            f"SELECT {', '.join(_COLS_PLANO_HIST)} FROM planos_operacao "
            "WHERE variante_id = ? ORDER BY plano_id DESC", [vid]).fetchall()]
        ultima = con.execute(
            "SELECT m.run_id, w.wfa_id FROM mining_runs m "
            "LEFT JOIN wfa_runs w ON w.run_id = m.run_id "
            "WHERE m.variante_id = ? ORDER BY m.created_at DESC, "
            "w.wfa_id DESC LIMIT 1", [vid]).fetchone()
    base_id = (item["plano"]["plano_id"] if item["plano"]
               else planos[0]["plano_id"] if planos else None)
    det = _plano.detalhes(base_id) if base_id else None
    run_id = det["run_id"] if det else (ultima[0] if ultima else None)
    wfa_id = det["wfa_id"] if det else (ultima[1] if ultima else None)
    with db.connect(read_only=True) as con:
        mina = _mineracao(con, run_id)
        wfa_d = _wfa(con, wfa_id)
    if mina:
        salva = _optimizer.detalhes_salva(run_id) or {}
        mina["espaco"] = salva.get("espaco") or {}
        mina["holdout_de"] = salva.get("holdout_de")
    alcance = ("plano" if det else "walk-forward" if wfa_d
               else "mineração" if mina else "nada")
    gravado = det.get("codigo_hash") if det else None
    atual = codigo.hash_estrategia(item["estrategia"])
    vistos, eventos = set(), []
    for e in (diario.eventos(ligacao_id=ligacao_id)
              + diario.eventos(variante_id=vid)):
        if e["evento_id"] not in vistos:
            vistos.add(e["evento_id"])
            eventos.append(e)
    eventos.sort(key=lambda e: e["evento_id"], reverse=True)
    return {
        "ligacao": item, "alcance": alcance, "plano": det,
        "mineracao": mina, "wfa": wfa_d,
        "candidata": det["regua"] if det else None,
        "codigo": {"gravado": gravado, "atual": atual,
                   "confere": None if not gravado else gravado == atual},
        "planos": planos, "eventos": eventos,
    }
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_rastreio.py tests/test_ao_vivo_operacao.py` → passam.

- [ ] **Step 5: Mutation** — (a) troque `planos[0]` por `planos[-1]` → `test_lista_todos...`/ficha falha se houver 2 planos; confirme que algum teste pega (se não, acrescente um que aposente o mais novo e cheque `r["plano"]`); (b) `confere` sempre `True` → `test_codigo_divergente` falha. Restaure.

- [ ] **Step 6: Commit** — `core/ao_vivo.py`, `tests/test_ao_vivo_rastreio.py`; mensagem `feat(ao-vivo): ficha de rastreio da variante`.

---

### Task 3: O 7º modo "Ao vivo" — esqueleto da tela

**Files:**
- Create: `ui/components/ao_vivo_panel.py` (só `painel()` nesta task)
- Modify: `ui/app.py` (opção do menu + `ao_vivo_panel.painel()` no `main`), `ui/callbacks.py` (callback `modo` + registro), `ui/assets/style.css`
- Create: `ui/callbacks_ao_vivo.py` (só `register(app)` vazio nesta task)
- Test: `tests/test_ao_vivo_tela.py`

**Interfaces:**
- Produces (ids de tela): `painel-aovivo`, stores `av-versao` (int, 0), `av-armado` (str|None), `av-aberta` (int|None), divs `av-aviso`, `av-portfolios`, `av-variantes`, `av-contas`, `av-arrumacao`, inputs `av-conta-nome`, `av-conta-tipo`, `av-conta-limite`, botão `av-btn-conta-criar`. Valor do modo: `"aovivo"`.

- [ ] **Step 1: Test**

```python
# tests/test_ao_vivo_tela.py
"""Tela Ao vivo: o que ela desenha a partir do que o core devolve."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import ao_vivo_panel as AP  # noqa: E402


def textos(c) -> str:
    """Todo o texto de uma árvore de componentes Dash, numa string só —
    inclusive o `value` dos campos (nome da conta, limite)."""
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(textos(x) for x in c)
    valor = getattr(c, "value", None)
    extra = str(valor) if isinstance(valor, (str, int, float)) else ""
    return extra + " " + textos(getattr(c, "children", None))


def ids(c) -> set:
    out = set()
    if isinstance(c, (list, tuple)):
        for x in c:
            out |= ids(x)
        return out
    if hasattr(c, "id") and getattr(c, "id", None) is not None:
        out.add(c.id if isinstance(c.id, str) else str(c.id))
    filhos = getattr(c, "children", None)
    if filhos is not None:
        out |= ids(filhos)
    return out


def test_painel_tem_as_pecas():
    p = AP.painel()
    assert p.id == "painel-aovivo"
    esperados = {"av-versao", "av-armado", "av-aberta", "av-aviso",
                 "av-portfolios", "av-variantes", "av-contas",
                 "av-arrumacao", "av-conta-nome", "av-conta-tipo",
                 "av-conta-limite", "av-btn-conta-criar"}
    assert esperados <= ids(p)
    assert "Estratégias" in textos(p)
```

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_tela.py` → FAIL (`cannot import name 'ao_vivo_panel'`).

- [ ] **Step 2: `ui/components/ao_vivo_panel.py`**

```python
"""Tela Ao vivo › Estratégias: o que está (ou vai estar) rodando.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md §5.
Só desenha — quem lê o banco é `ui/callbacks_ao_vivo.py`. As outras
sub-telas (Pregão, Conta, Histórico) só entram quando a parte delas
existir: tela vazia confunde.
"""
from __future__ import annotations

from dash import dcc, html

FASES = {"papel": "papel", "demo": "demo", "real_minimo": "real mínimo",
         "real": "real"}


def _secao(titulo, nota, *filhos):
    return html.Section([
        html.Div([html.H3(titulo, className="panel-title"),
                  html.Span(nota, className="panel-note")],
                 className="panel-head"),
        *filhos,
    ], className="panel")


def painel():
    return html.Div([
        # um número que sobe a cada ação: é ele que manda redesenhar
        dcc.Store(id="av-versao", data=0),
        # o botão que está pedindo confirmação (segundo clique executa)
        dcc.Store(id="av-armado", data=None),
        # a variante com a ficha aberta
        dcc.Store(id="av-aberta", data=None),
        html.Section([
            html.Div([html.H2("Ao vivo", className="panel-title"),
                      html.Span("Estratégias", className="chip av-subtela")],
                     className="panel-head"),
            html.Div(id="av-aviso", className="av-aviso"),
        ], className="panel"),
        _secao("Portfólios", "ligue o portfólio para as variantes dele rodarem "
               "(por enquanto só no papel, sem enviar ordem)",
               html.Div(id="av-portfolios", className="av-lista")),
        _secao("Variantes", "clique no nome para abrir a ficha: de onde veio o "
               "plano, o que ele opera e o que já mudou",
               html.Div(id="av-variantes", className="av-lista-col")),
        _secao("Contas", "contas do MT5 onde as ordens vão cair a partir da "
               "fase demo — o limite de perda diária é da mesa",
               html.Div([
                   dcc.Input(id="av-conta-nome", type="text", className="inp",
                             placeholder="nome da conta (ex.: Demo XP)"),
                   dcc.Dropdown(id="av-conta-tipo", className="dd dd-sm",
                                clearable=False, value="demo",
                                options=[{"label": "demo", "value": "demo"},
                                         {"label": "real", "value": "real"}]),
                   dcc.Input(id="av-conta-limite", type="text",
                             inputMode="numeric", className="inp",
                             placeholder="limite de perda diária (R$, opcional)"),
                   html.Button("Criar conta", id="av-btn-conta-criar",
                               n_clicks=0, className="btn-ghost"),
               ], className="acoes"),
               html.Div(id="av-contas", className="av-lista-col")),
        _secao("Arrumação", "planos ativos que não pertencem a nenhuma "
               "variante — só entram em portfólio depois de vinculados",
               html.Div(id="av-arrumacao", className="av-lista-col")),
    ], id="painel-aovivo", className="modo-bloco", style={"display": "none"})
```

- [ ] **Step 3: `ui/callbacks_ao_vivo.py`** (esqueleto; as Tasks 4 e 5 preenchem)

```python
"""Callbacks da tela Ao vivo. Dois callbacks só: `agir` (todo clique vai
ao core e sobe `av-versao`) e `desenhar` (lê o banco e redesenha). Um
redesenho único evita um callback por botão escrevendo nas mesmas
saídas — que é como se chega a ciclo e a tela congelada sem erro."""
from __future__ import annotations


def register(app):
    return None
```

- [ ] **Step 4: Ligar o modo**
  - `ui/app.py`: no import `from ui.components import (...)` acrescente `ao_vivo_panel`; nas opções do `dcc.RadioItems(id="modo")` acrescente, depois de Portfólio, `{"label": "Ao vivo", "value": "aovivo"}`; no `main`, depois de `portfolio_panel.painel(),` acrescente `ao_vivo_panel.painel(),`.
  - `ui/callbacks.py`, callback `modo`: acrescente `Output("painel-aovivo", "style"),` logo depois de `Output("painel-portfolio", "style"),`; no `return`, depois de `v(qual == "portfolio"),` acrescente `v(qual == "aovivo"),`; na última linha troque `("wfa", "candidata", "estrategias", "portfolio")` por `("wfa", "candidata", "estrategias", "portfolio", "aovivo")`.
  - `ui/callbacks.py`, `register`: junto dos outros, `from ui import callbacks_ao_vivo` + `callbacks_ao_vivo.register(app)`.
  - `ui/assets/style.css`, no fim:

```css
/* ---- Ao vivo (mesma lição do #painel-portfolio: sem flex-shrink o
   painel era espremido e o conteúdo cortado em vez de rolar) */
#painel-aovivo .panel{flex-shrink:0;overflow:visible;}
.av-subtela{margin-left:12px;color:var(--accent);border-color:var(--accent);}
.av-aviso{font-family:var(--mono);font-size:12px;color:var(--warn);min-height:0;}
.av-aviso:empty{display:none;}
.av-lista{display:flex;flex-wrap:wrap;gap:10px;}
.av-lista-col{display:flex;flex-direction:column;gap:8px;margin-top:8px;}
.av-cartao{padding:12px 16px;border:1px solid var(--line);border-radius:8px;
  display:flex;flex-direction:column;gap:6px;min-width:260px;}
.av-cartao.av-ligado{border-color:var(--accent);}
.av-linha{display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
.av-nome{font-weight:600;cursor:pointer;}
.av-nome:hover{color:var(--accent);}
.av-nota{font-size:.85em;color:var(--muted);}
.av-roda{color:var(--pos);font-weight:600;}
.av-motivo{color:var(--warn);font-weight:600;}
.av-avisos{margin:0;padding-left:18px;font-size:.85em;color:var(--muted);}
.av-ficha{margin:6px 0 4px 12px;padding:10px 14px;border-left:2px solid var(--accent);
  display:flex;flex-direction:column;gap:12px;}
.av-ficha h4{margin:0 0 4px;font-size:13px;}
.av-ok{color:var(--pos);}
.av-nok{color:var(--neg);}
```

- [ ] **Step 5: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_tela.py tests/test_callbacks_sem_ciclo.py` → passam; depois a suíte inteira.

- [ ] **Step 6: Commit** — `ui/components/ao_vivo_panel.py`, `ui/callbacks_ao_vivo.py`, `ui/app.py`, `ui/callbacks.py`, `ui/assets/style.css`, `tests/test_ao_vivo_tela.py`; mensagem `feat(ao-vivo): setimo modo Ao vivo, esqueleto da tela`.

---

### Task 4: Desenhar — portfólios, variantes, ficha, contas, arrumação

**Files:**
- Modify: `ui/components/ao_vivo_panel.py` (funções de desenho), `ui/callbacks_ao_vivo.py` (`montar` + callback `desenhar`)
- Test: `tests/test_ao_vivo_tela.py` (acrescentar)

**Interfaces:**
- Consumes: `AV.em_operacao`, `AV.repetidas`, `AV.planos_sem_variante`, `AV.rastreio`, `AV.listar_contas`, `P.listar`, `V.listar`, `registry.carregar`, `ui/components/ficha.ficha`.
- Produces:
  - Botões de ação: `id={"type": "av-acao", "acao": <nome>, "id": <int>}`; campos: `id={"type": "av-campo", "campo": <nome>, "id": <int>}`.
  - Ações usadas: `pf-ligar`, `pf-desligar`, `pf-contas`, `membro-ligar`, `membro-desligar`, `abrir`, `conta-salvar`, `conta-arquivar`, `plano-aposentar`, `renomear`, `vincular`. Campos: `conta-demo`/`conta-real` (id = portfolio_id), `conta-nome`/`conta-limite` (id = conta_id), `renomear` (id = variante_id), `vincular-variante`/`vincular-manter` (id = run_id).
  - `ui.callbacks_ao_vivo.montar(armado: str | None, aberta: int | None, hoje=None) -> tuple` — `(portfolios, variantes, contas, arrumacao)` (quatro filhos).
  - Texto de confirmação: o botão armado (`armado == f"{acao}:{id}"`) mostra `"Confirmar?"`.

- [ ] **Step 1: Tests** — acrescente a `tests/test_ao_vivo_tela.py`:

```python
from datetime import date, datetime  # noqa: E402

from core import ao_vivo as AV, codigo, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401
from ui import callbacks_ao_vivo as CA  # noqa: E402

QUI = date(2026, 10, 1)


def _cenario():
    v = variantes.criar("romp-canal-02", "rompimento_canal")
    mineracao(47, variante_id=v)
    wfa(13, 47)
    pid = plano.salvar(**campos_plano(
        wfa_id=13, run_id=47,
        codigo_hash=codigo.hash_estrategia("rompimento_canal"),
        regua={"veredito": "aprovada",
               "portoes": [{"nome": "Platô", "ok": True, "critico": True}]}),
        agora=datetime(2026, 9, 1, 10))
    pf = P.criar("portifolio-teste")
    lig = P.adicionar_variante(pf, v)
    wfa(18, 50)                                   # plano órfão
    orfao = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                         agora=datetime(2026, 9, 1, 10))
    return v, pid, pf, lig, orfao


def test_montar_desenha_as_quatro_secoes(banco):
    v, pid, pf, lig, orfao = _cenario()
    AV.criar_conta("Demo XP", "demo", 500.0)
    portfolios, vars_, contas, arruma = CA.montar(None, None, QUI)
    t = textos(portfolios)
    assert "portifolio-teste" in t and "desligado" in t
    t = textos(vars_)
    assert "romp-canal-02" in t and "portfólio desligado" in t
    assert "papel" in t
    assert "Demo XP" in textos(contas) and "500" in textos(contas)
    assert f"#{orfao}" in textos(arruma)


def test_ficha_aberta(banco):
    v, pid, pf, lig, orfao = _cenario()
    _, vars_, _, _ = CA.montar(None, lig, QUI)
    t = textos(vars_)
    assert f"plano #{pid}" in t
    assert "walk-forward #13" in t and "mineração #47" in t
    assert "aprovada" in t and "Platô" in t
    assert "código confere" in t


def test_botao_armado_pede_confirmacao(banco):
    v, pid, pf, lig, orfao = _cenario()
    portfolios, _, _, _ = CA.montar(f"pf-ligar:{pf}", None, QUI)
    assert "Confirmar?" in textos(portfolios)


def test_repetida_aparece_no_topo(banco):
    v, pid, pf, lig, orfao = _cenario()
    pf2 = P.criar("outro")
    P.adicionar_variante(pf2, v)
    AV.ligar_portfolio(pf)
    AV.ligar_portfolio(pf2)
    _, vars_, _, _ = CA.montar(None, None, QUI)
    assert "está em 2 portfólios ligados" in textos(vars_)


def test_sem_nada(banco):
    portfolios, vars_, contas, arruma = CA.montar(None, None, QUI)
    assert "nenhum portfólio" in textos(portfolios)
    assert "nenhuma variante" in textos(vars_)
    assert "nenhuma conta" in textos(contas)
    assert "nada a arrumar" in textos(arruma)
```

Run → FAIL (`module 'ui.callbacks_ao_vivo' has no attribute 'montar'`).

- [ ] **Step 2: Funções de desenho — acrescentar a `ui/components/ao_vivo_panel.py`**

Imports no topo: `from .cartao import brl` e `from . import ficha as FI`.

```python
def _botao(rotulo, acao, alvo, armado, classe="btn-ghost btn-sm"):
    armado_aqui = armado == f"{acao}:{alvo}"
    return html.Button("Confirmar?" if armado_aqui else rotulo,
                       id={"type": "av-acao", "acao": acao, "id": alvo},
                       n_clicks=0, className=classe)


def _campo_dd(campo, alvo, valor, opcoes, placeholder):
    return dcc.Dropdown(id={"type": "av-campo", "campo": campo, "id": alvo},
                        value=valor, options=opcoes, placeholder=placeholder,
                        className="dd dd-sm", clearable=True)


def _campo_txt(campo, alvo, valor, placeholder, numerico=False):
    return dcc.Input(id={"type": "av-campo", "campo": campo, "id": alvo},
                     value=valor, placeholder=placeholder, type="text",
                     className="inp", **({"inputMode": "numeric"} if numerico else {}))


def _data(d, fmt="%d/%m/%Y"):
    return d.strftime(fmt) if d else "—"


def cartao_portfolio(p: dict, contas: list[dict], armado) -> html.Div:
    demo = [{"label": c["nome"], "value": c["conta_id"]}
            for c in contas if c["tipo"] == "demo"]
    real = [{"label": c["nome"], "value": c["conta_id"]}
            for c in contas if c["tipo"] == "real"]
    pid = p["portfolio_id"]
    estado = (html.Span("ligado", className="av-roda") if p["ligado"]
              else html.Span("desligado", className="av-nota"))
    interruptor = (_botao("Desligar", "pf-desligar", pid, armado) if p["ligado"]
                   else _botao("Ligar", "pf-ligar", pid, armado))
    return html.Div([
        html.Div([html.Span(p["nome"], className="av-nome"), estado,
                  html.Span(f"{p['n_membros']} variante(s)", className="av-nota"),
                  interruptor], className="av-linha"),
        html.Div([_campo_dd("conta-demo", pid, p["conta_demo_id"], demo,
                            "conta demo"),
                  _campo_dd("conta-real", pid, p["conta_real_id"], real,
                            "conta real"),
                  _botao("Salvar contas", "pf-contas", pid, armado)],
                 className="av-linha"),
    ], className="av-cartao" + (" av-ligado" if p["ligado"] else ""))


def cartao_variante(l: dict, armado, ficha=None) -> html.Div:
    lig = l["ligacao_id"]
    plano = l["plano"]
    situacao = (html.Span("roda", className="av-roda") if l["roda"]
                else html.Span(l["motivo"], className="av-motivo"))
    interruptor = (_botao("Pausar", "membro-desligar", lig, armado) if l["ligada"]
                   else _botao("Ligar", "membro-ligar", lig, armado))
    partes = [l["estrategia"],
              (plano or {}).get("symbol") or "—",
              f"Fase: {FASES.get(l['fase'], l['fase'])} há {l['dias_na_fase']} dia(s)",
              (f"plano #{plano['plano_id']} · {l['pregoes_com_plano']} pregão(ões) "
               f"com este plano · reotimizar até {_data(plano['reotimizar_em'])}"
               if plano else "sem plano em vigor")]
    filhos = [html.Div([
        html.Span(l["variante_nome"], className="av-nome",
                  id={"type": "av-acao", "acao": "abrir", "id": lig}, n_clicks=0),
        html.Span(" · ".join(partes), className="av-nota"),
        situacao, interruptor], className="av-linha")]
    if l["avisos"]:
        filhos.append(html.Ul([html.Li(a) for a in l["avisos"]],
                              className="av-avisos"))
    if ficha is not None:
        filhos.append(ficha)
    return html.Div(filhos, className="av-cartao")


def ficha_rastreio(r: dict, estrategia_mod, armado) -> html.Div:
    l, det, mina, w = r["ligacao"], r["plano"], r["mineracao"], r["wfa"]
    vid = l["variante_id"]
    blocos = [html.Div([
        _campo_txt("renomear", vid, l["variante_nome"], "novo nome da variante"),
        _botao("Renomear", "renomear", vid, armado),
        *([_botao("Aposentar plano", "plano-aposentar", det["plano_id"], armado)]
          if det and det["estado"] == "ativo" else []),
    ], className="av-linha")]
    alcance = {"plano": None,
               "walk-forward": "chegou até o walk-forward — ainda sem plano gravado",
               "mineração": "chegou até a mineração — ainda sem walk-forward",
               "nada": "ainda não foi minerada"}[r["alcance"]]
    if alcance:
        blocos.append(html.P(alcance, className="av-motivo"))
    # 1. origem
    blocos.append(html.Div([
        html.H4("1. Origem — mineração"),
        html.P(f"mineração #{mina['run_id']} · {mina['nome'] or 'sem nome'} · "
               f"{_data(mina['created_at'])} · {mina['n_combinacoes']} "
               f"combinações testadas · holdout a partir de "
               f"{mina.get('holdout_de') or '—'}")
        if mina else html.P("mineração apagada ou anterior às variantes",
                            className="av-nota"),
    ]))
    # 2. walk-forward
    blocos.append(html.Div([
        html.H4("2. Walk-Forward"),
        html.P(f"walk-forward #{w['wfa_id']} · {w['nome'] or 'sem nome'} · "
               f"IS {w['is_meses']} / OOS {w['oos_meses']} meses · "
               f"{w['inteligencia'] or '—'} · lucro fora da amostra "
               f"{brl(w['oos_lucro'] or 0)} em {w['oos_trades'] or 0} trades · "
               f"queda máx. {brl(w['dd_oos'] or 0)} · veredito "
               f"{w['veredito'] or '—'}")
        if w else html.P("sem walk-forward", className="av-nota"),
    ]))
    # 3. candidata
    reg = r["candidata"] or {}
    blocos.append(html.Div([
        html.H4("3. Candidata"),
        html.P(f"veredito no dia da gravação: {reg.get('veredito') or '—'}"),
        html.Ul([html.Li([html.Span("✔ " if p.get("ok") else "✖ ",
                                    className="av-ok" if p.get("ok") else "av-nok"),
                          p.get("nome") or "—"])
                 for p in reg.get("portoes") or []], className="av-avisos"),
    ]))
    # 4. plano em vigor
    if det:
        cod = r["codigo"]
        conf = ("código confere" if cod["confere"] else
                "⚠ código mudou desde o plano" if cod["confere"] is False else
                "código não conferido (plano anterior a 30/09/2026)")
        corpo = [html.P(
            f"plano #{det['plano_id']} · capital {brl(det['capital'] or 0)} · "
            f"{det['contratos']} contrato(s) · risco por pregão "
            f"{det['risco_efetivo_pct'] or 0:.2f}% · vale a partir de "
            f"{_data(det['vale_a_partir'])} · reotimizar até "
            f"{_data(det['reotimizar_em'])} · {conf}")]
        if estrategia_mod is not None:
            corpo.append(FI.ficha(estrategia=estrategia_mod,
                                  params=det["params"], perfil=det["profile"],
                                  espaco=(mina or {}).get("espaco") or {}))
        else:
            corpo.append(html.P("código da estratégia não encontrado",
                                className="av-motivo"))
        blocos.append(html.Div([html.H4("4. Plano"), *corpo]))
    # 5. histórico
    blocos.append(html.Div([
        html.H4("5. Histórico"),
        html.Ul([html.Li(
            f"plano #{p['plano_id']} · {p['estado']} · gravado "
            f"{_data(p['created_at'])} · vale de {_data(p['vale_a_partir'])}"
            + (f" até {_data(p['aposentado_em'])}" if p['aposentado_em'] else ""))
            for p in r["planos"]] or [html.Li("nenhum plano ainda")],
            className="av-avisos"),
        html.Ul([html.Li(f"{_data(e['quando'], '%d/%m/%Y %H:%M')} · "
                         f"{e['tipo'].replace('_', ' ')}"
                         + (f" · {e['motivo']}" if e['motivo'] else ""))
                 for e in r["eventos"][:30]], className="av-avisos"),
    ]))
    return html.Div(blocos, className="av-ficha")


def linha_conta(c: dict, armado) -> html.Div:
    cid = c["conta_id"]
    return html.Div([
        html.Span(c["tipo"], className="av-nota"),
        _campo_txt("conta-nome", cid, c["nome"], "nome"),
        _campo_txt("conta-limite", cid,
                   "" if c["limite_perda_dia"] is None
                   else f"{c['limite_perda_dia']:.0f}",
                   "limite de perda diária (R$)", numerico=True),
        _botao("Salvar", "conta-salvar", cid, armado),
        _botao("Arquivar", "conta-arquivar", cid, armado),
    ], className="av-linha")


def linha_orfao(o: dict, opcoes_variante: list[dict],
                opcoes_manter: list[dict], armado) -> html.Div:
    rid = o["run_id"]
    return html.Div([
        html.Span(f"plano #{o['plano_id']} · {o['strategy']} · "
                  f"{o['nome'] or 'sem nome'} · mineração #{rid}",
                  className="av-nome"),
        _campo_dd("vincular-variante", rid, None, opcoes_variante,
                  "vincular a qual variante?"),
        _campo_dd("vincular-manter", rid, None, opcoes_manter,
                  "se a variante já tiver plano ativo: qual fica"),
        _botao("Vincular", "vincular", rid, armado),
    ], className="av-linha")
```

- [ ] **Step 3: `montar` e o callback `desenhar` em `ui/callbacks_ao_vivo.py`** (substitua o esqueleto)

```python
"""Callbacks da tela Ao vivo. Dois callbacks só: `agir` (todo clique vai
ao core e sobe `av-versao`) e `desenhar` (lê o banco e redesenha). Um
redesenho único evita um callback por botão escrevendo nas mesmas
saídas — que é como se chega a ciclo e a tela congelada sem erro."""
from __future__ import annotations

from dash import Input, Output, html, no_update
from dash.exceptions import PreventUpdate

from core import ao_vivo as AV
from core import plano as PL
from core import portfolio as P
from core import variantes as V
from strategies import registry

from .components import ao_vivo_panel as AP


def _modulo(estrategia):
    try:
        return registry.carregar(estrategia)
    except Exception:           # arquivo sumiu ou não carrega: a ficha avisa
        return None


def montar(armado, aberta, hoje=None):
    """As quatro seções da tela, lidas do banco agora."""
    contas = AV.listar_contas()
    pfs = P.listar()
    portfolios = ([AP.cartao_portfolio(p, contas, armado) for p in pfs]
                  or [html.P("nenhum portfólio ainda — crie na tela Portfólio",
                             className="av-nota")])

    linhas = AV.em_operacao(hoje)
    blocos = []
    for rep in AV.repetidas(linhas):
        blocos.append(html.P(
            f"⚠ {rep['variante_nome']} está em {len(rep['portfolios'])} "
            f"portfólios ligados ({', '.join(rep['portfolios'])}) — os "
            "contratos somam na conta", className="av-motivo"))
    atual = None
    for l in linhas:
        if l["portfolio_nome"] != atual:
            atual = l["portfolio_nome"]
            blocos.append(html.H4(atual, className="panel-title"))
        ficha = None
        if aberta == l["ligacao_id"]:
            r = AV.rastreio(l["ligacao_id"], hoje)
            ficha = AP.ficha_rastreio(r, _modulo(l["estrategia"]), armado)
        blocos.append(AP.cartao_variante(l, armado, ficha))
    variantes = blocos or [html.P("nenhuma variante em portfólio ainda",
                                  className="av-nota")]

    contas_div = ([AP.linha_conta(c, armado) for c in contas]
                  or [html.P("nenhuma conta cadastrada", className="av-nota")])

    orfaos = AV.planos_sem_variante()
    arruma = []
    for o in orfaos:
        mesmas = V.listar(o["strategy"])
        op_var = [{"label": v["nome"], "value": v["variante_id"]} for v in mesmas]
        ativos = [p for p in PL.listar(apenas_ativos=True)
                  if p["strategy"] == o["strategy"]]
        op_manter = [{"label": f"plano #{p['plano_id']}", "value": p["plano_id"]}
                     for p in ativos]
        arruma.append(AP.linha_orfao(o, op_var, op_manter, armado))
    arruma = arruma or [html.P("nada a arrumar", className="av-nota")]
    return portfolios, variantes, contas_div, arruma


def register(app):
    @app.callback(
        Output("av-portfolios", "children"), Output("av-variantes", "children"),
        Output("av-contas", "children"), Output("av-arrumacao", "children"),
        Input("modo", "value"), Input("av-versao", "data"),
        Input("av-armado", "data"), Input("av-aberta", "data"),
    )
    def desenhar(modo, _versao, armado, aberta):
        if modo != "aovivo":
            raise PreventUpdate
        return montar(armado, aberta)
```

> `PL.listar(apenas_ativos=True)` devolve dicts com a chave `strategy` (colunas de `planos_operacao`). `no_update` fica importado para a Task 5.

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_tela.py tests/test_callbacks_sem_ciclo.py` → passam. Depois a suíte inteira.

- [ ] **Step 5: Commit** — `ui/components/ao_vivo_panel.py`, `ui/callbacks_ao_vivo.py`, `tests/test_ao_vivo_tela.py`; mensagem `feat(ao-vivo): tela desenha portfolios, variantes, ficha, contas e arrumacao`.

---

### Task 5: Agir — todo clique da tela

**Files:**
- Modify: `ui/callbacks_ao_vivo.py` (`acao`, `_numero`, callback `agir`)
- Test: `tests/test_ao_vivo_acoes.py`

**Interfaces:**
- Consumes: `AV.ligar_portfolio/desligar_portfolio/definir_contas/ligar_membro/desligar_membro/criar_conta/editar_conta/arquivar_conta/vincular_plano`, `V.renomear`, `PL.aposentar`.
- Produces: `acao(nome: str, alvo: int, campos: dict, armado: str | None, aberta: int | None) -> tuple[str | None, int | None, str]` → `(novo_armado, nova_aberta, aviso)`. Duplo clique (primeiro arma, segundo executa) em `pf-ligar`, `plano-aposentar`, `conta-arquivar`. `campos` é `{(campo, id): valor}`; a criação de conta usa `alvo=0` e campos `("conta-nome", 0)`, `("conta-tipo", 0)`, `("conta-limite", 0)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ao_vivo_acoes.py
"""Os cliques da tela Ao vivo, sem navegador: `acao` chama o core e diz o
que aconteceu em português."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV, diario, plano, variantes  # noqa: E402
from core import portfolio as P  # noqa: E402
from tests._cadeia import banco, campos_plano, mineracao, wfa  # noqa: E402,F401
from ui.callbacks_ao_vivo import acao  # noqa: E402


def test_ligar_portfolio_pede_confirmacao(banco):
    pf = P.criar("p")
    armado, _, aviso = acao("pf-ligar", pf, {}, None, None)
    assert armado == f"pf-ligar:{pf}" and "confirm" in aviso.lower()
    assert P.listar()[0]["ligado"] is False
    armado, _, aviso = acao("pf-ligar", pf, {}, armado, None)
    assert armado is None and P.listar()[0]["ligado"] is True
    assert "ligado" in aviso


def test_desligar_e_imediato(banco):
    pf = P.criar("p")
    AV.ligar_portfolio(pf)
    armado, _, _ = acao("pf-desligar", pf, {}, None, None)
    assert armado is None and P.listar()[0]["ligado"] is False


def test_abrir_e_fechar_ficha(banco):
    assert acao("abrir", 7, {}, None, None)[1] == 7
    assert acao("abrir", 7, {}, None, 7)[1] is None


def test_criar_conta_com_limite_em_formato_brasileiro(banco):
    campos = {("conta-nome", 0): "Mesa A", ("conta-tipo", 0): "real",
              ("conta-limite", 0): "1.500,50"}
    _, _, aviso = acao("conta-criar", 0, campos, None, None)
    [c] = AV.listar_contas()
    assert c["limite_perda_dia"] == 1500.5 and "criada" in aviso


def test_limite_invalido_vira_aviso(banco):
    campos = {("conta-nome", 0): "X", ("conta-tipo", 0): "demo",
              ("conta-limite", 0): "abc"}
    _, _, aviso = acao("conta-criar", 0, campos, None, None)
    assert "limite" in aviso and AV.listar_contas() == []


def test_recusa_do_core_vira_aviso(banco):
    pf = P.criar("p")
    real = AV.criar_conta("R", "real")
    _, _, aviso = acao("pf-contas", pf, {("conta-demo", pf): real,
                                         ("conta-real", pf): None}, None, None)
    assert "não é do tipo demo" in aviso


def test_banco_ocupado_vira_aviso(banco, monkeypatch):
    pf = P.criar("p")
    def ocupado(*a, **k):
        raise RuntimeError("banco ocupado após 10s de espera: x")
    monkeypatch.setattr(AV, "desligar_portfolio", ocupado)
    _, _, aviso = acao("pf-desligar", pf, {}, None, None)
    assert aviso == "banco ocupado, tente de novo"


def test_pausar_e_ligar_variante(banco):
    pf = P.criar("p")
    v = variantes.criar("v", "rompimento_canal")
    lig = P.adicionar_variante(pf, v)
    acao("membro-desligar", lig, {}, None, None)
    assert P.membros(pf)[0]["ligada"] is False
    acao("membro-ligar", lig, {}, None, None)
    assert P.membros(pf)[0]["ligada"] is True


def test_aposentar_plano_duplo_clique(banco):
    wfa(1, 1)
    pid = plano.salvar(**campos_plano(), agora=datetime(2026, 9, 1, 10))
    armado, _, _ = acao("plano-aposentar", pid, {}, None, None)
    assert plano.detalhes(pid)["estado"] == "ativo"
    _, _, aviso = acao("plano-aposentar", pid, {}, armado, None)
    assert plano.detalhes(pid)["estado"] == "aposentado"
    assert "sai de vigor" in aviso


def test_renomear_e_vincular(banco):
    v = variantes.criar("errado", "rompimento_canal")
    _, _, aviso = acao("renomear", v, {("renomear", v): "certo"}, None, None)
    assert variantes.listar()[0]["nome"] == "certo" and "renomeada" in aviso
    mineracao(50)
    wfa(18, 50)
    pid = plano.salvar(**campos_plano(wfa_id=18, run_id=50),
                       agora=datetime(2026, 9, 1, 10))
    _, _, aviso = acao("vincular", 50, {("vincular-variante", 50): v,
                                        ("vincular-manter", 50): None},
                       None, None)
    assert plano.detalhes(pid)["variante_id"] == v and "vinculad" in aviso
```

- [ ] **Step 2: Run** → FAIL (`cannot import name 'acao'`).

- [ ] **Step 3: Implementar em `ui/callbacks_ao_vivo.py`**

Imports: acrescente `from dash import ALL, State, ctx` ao import do dash existente.

```python
# o segundo clique confirma: ligar põe estratégia para rodar, aposentar e
# arquivar não se desfazem pela tela. Desligar/pausar são imediatos — o
# caminho seguro não pede confirmação.
_DUPLO = {"pf-ligar": "confirme: clique de novo para LIGAR o portfólio",
          "plano-aposentar": "confirme: clique de novo para aposentar o plano "
                             "(ele sai de vigor no próximo pregão)",
          "conta-arquivar": "confirme: clique de novo para arquivar a conta"}


def _numero(texto):
    """"1.500,50", "1500.5" ou vazio (None). Texto que não é número vira
    recusa — um limite de mesa digitado errado não pode virar 'sem limite'."""
    if texto is None or not str(texto).strip():
        return None
    limpo = str(texto).strip().replace("R$", "").replace(" ", "")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        raise ValueError("limite de perda diária inválido: digite só o valor "
                         "em reais (ex.: 500 ou 1.500,00)") from None


def _executar(nome, alvo, campos) -> str:
    c = lambda campo: campos.get((campo, alvo))
    if nome == "pf-ligar":
        AV.ligar_portfolio(alvo)
        return "portfólio ligado — as variantes dele rodam no papel"
    if nome == "pf-desligar":
        AV.desligar_portfolio(alvo)
        return "portfólio desligado"
    if nome == "pf-contas":
        AV.definir_contas(alvo, c("conta-demo"), c("conta-real"))
        return "contas do portfólio salvas"
    if nome == "membro-ligar":
        AV.ligar_membro(alvo)
        return "variante ligada"
    if nome == "membro-desligar":
        AV.desligar_membro(alvo)
        return "variante pausada"
    if nome == "conta-criar":
        AV.criar_conta(c("conta-nome"), c("conta-tipo"), _numero(c("conta-limite")))
        return "conta criada"
    if nome == "conta-salvar":
        AV.editar_conta(alvo, nome=c("conta-nome"),
                        limite_perda_dia=_numero(c("conta-limite")))
        return "conta salva"
    if nome == "conta-arquivar":
        AV.arquivar_conta(alvo)
        return "conta arquivada"
    if nome == "plano-aposentar":
        PL.aposentar(alvo)
        d = PL.detalhes(alvo)
        return f"plano #{alvo} sai de vigor em {d['aposentado_em']:%d/%m/%Y}"
    if nome == "renomear":
        V.renomear(alvo, c("renomear"))
        return "variante renomeada"
    if nome == "vincular":
        var = c("vincular-variante")
        if var is None:
            raise ValueError("escolha a variante antes de vincular")
        manter = c("vincular-manter")
        AV.vincular_plano(alvo, int(var),
                          manter_plano_id=int(manter) if manter else None)
        return f"mineração #{alvo} vinculada à variante"
    raise ValueError(f"ação desconhecida: {nome}")


def acao(nome, alvo, campos, armado, aberta):
    """Um clique da tela. Devolve (armado, aberta, aviso)."""
    if nome == "abrir":
        return None, (None if aberta == alvo else alvo), ""
    chave = f"{nome}:{alvo}"
    if nome in _DUPLO and armado != chave:
        return chave, aberta, _DUPLO[nome]
    try:
        aviso = _executar(nome, alvo, campos)
    except ValueError as e:
        aviso = str(e)
    except RuntimeError:            # connect_write desistiu: mineração gravando
        aviso = "banco ocupado, tente de novo"
    return None, aberta, aviso
```

E dentro de `register(app)`, depois de `desenhar`:

```python
    @app.callback(
        Output("av-versao", "data"), Output("av-armado", "data"),
        Output("av-aberta", "data"), Output("av-aviso", "children"),
        Input({"type": "av-acao", "acao": ALL, "id": ALL}, "n_clicks"),
        Input("av-btn-conta-criar", "n_clicks"),
        State({"type": "av-campo", "campo": ALL, "id": ALL}, "value"),
        State("av-conta-nome", "value"), State("av-conta-tipo", "value"),
        State("av-conta-limite", "value"),
        State("av-versao", "data"), State("av-armado", "data"),
        State("av-aberta", "data"),
        prevent_initial_call=True,
    )
    def agir(_cliques, _criar, _campos, nome, tipo, limite, versao, armado,
             aberta):
        # botão recém-desenhado aparece com n_clicks=0 e dispara o Input de
        # padrão sem ninguém ter clicado: só vale clique de verdade
        gat = ctx.triggered_id
        valor = ctx.triggered[0]["value"] if ctx.triggered else None
        if not gat or not valor:
            raise PreventUpdate
        campos = {(s["id"]["campo"], s["id"]["id"]): s.get("value")
                  for s in ctx.states_list[0]}
        if gat == "av-btn-conta-criar":
            campos.update({("conta-nome", 0): nome, ("conta-tipo", 0): tipo,
                           ("conta-limite", 0): limite})
            nome_acao, alvo = "conta-criar", 0
        else:
            nome_acao, alvo = gat["acao"], gat["id"]
        armado, aberta, aviso = acao(nome_acao, alvo, campos, armado, aberta)
        return (versao or 0) + 1, armado, aberta, aviso
```

- [ ] **Step 4: Run** — `.venv/Scripts/python.exe -m pytest -q tests/test_ao_vivo_acoes.py tests/test_ao_vivo_tela.py tests/test_callbacks_sem_ciclo.py` → passam. Depois a suíte inteira.

- [ ] **Step 5: Mutation** — (a) tire `pf-ligar` de `_DUPLO` → `test_ligar_portfolio_pede_confirmacao` falha; (b) `_numero` devolvendo `None` para texto inválido → `test_limite_invalido...` falha. Restaure.

- [ ] **Step 6: Commit** — `ui/callbacks_ao_vivo.py`, `tests/test_ao_vivo_acoes.py`; mensagem `feat(ao-vivo): cliques da tela - ligar, pausar, contas, aposentar, vincular, renomear`.

---

### Task 6: Fechamento — revisão, conferência na tela, documentação

- [ ] **Step 1:** suíte inteira verde; revisão final do diff (`git diff <base>..HEAD`).
- [ ] **Step 2: Conferência na tela contra o banco real — SÓ LEITURA.** Backup antes (`Copy-Item data\database.duckdb C:\Users\mrRobot\Documents\Neturna\backups\database-antes-1b.duckdb` com o app parado). Suba `preview_start dataframe`, abra **Ao vivo**:
  1. Portfólios: "portifolio-mini-indice" e "portifolio-teste", ambos **desligados**, com 0 e 2 variantes.
  2. Variantes (grupo portifolio-teste): romp-canal-02 e variante-romp-canal-M15-28, motivo "portfólio desligado", fase papel.
  3. Clicar em romp-canal-02 → ficha: mineração #47, walk-forward #13, veredito da Candidata, plano #1 com os parâmetros, aviso "código não conferido".
  4. Arrumação: plano #3 listado.
  **Não clicar em Ligar, Salvar, Vincular, Renomear, Aposentar, Arquivar nem Criar conta** — essas ações são do usuário. Screenshots de 1–4.
- [ ] **Step 3:** documentação (CHANGELOG `[Não lançado]` → "Tela Ao vivo, entrega 1b"; CLAUDE.md "Onde estamos": 1b ✅, próximo = parte 2, candles ao vivo; modos da tabela de arquitetura ganham "Ao vivo"). Commit `docs(ao-vivo): changelog e estado da entrega 1b`.
- [ ] **Step 4:** push `git push origin candidata`.
