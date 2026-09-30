"""Tela Ao vivo: contas, interruptores e arrumação da cadeia.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md.
Toda mudança de estado grava o evento do diário NA MESMA transação.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import codigo
from . import db_manager as db
from . import diario
from . import optimizer as _optimizer
from . import plano as _plano
from . import variantes as V

_TIPOS_CONTA = ("demo", "real")
_COLS_CONTA = ("conta_id", "nome", "tipo", "limite_perda_dia", "criado_em",
               "arquivada_em")
_NADA = object()


def _nome_livre(con, nome, ignorar_id=None):
    r = con.execute(
        "SELECT conta_id FROM contas WHERE nome = ? AND arquivada_em IS NULL "
        "AND conta_id IS DISTINCT FROM ?", [nome, ignorar_id]).fetchone()
    if r:
        raise ValueError(f"já existe uma conta ativa chamada '{nome}'")


def criar_conta(nome, tipo, limite_perda_dia=None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("a conta precisa de um nome")
    if tipo not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    with db.connect_write() as con, db.transacao(con):
        _nome_livre(con, nome)
        cid = con.execute("SELECT nextval('seq_conta_id')").fetchone()[0]
        con.execute("INSERT INTO contas VALUES (?,?,?,?,?,NULL)",
                    [cid, nome, tipo, limite_perda_dia, datetime.now()])
        diario.registrar(con, "conta_criada", "usuario", conta_id=cid,
                         para=nome, motivo=tipo)
    return int(cid)


def editar_conta(conta_id, *, nome=_NADA, tipo=_NADA,
                 limite_perda_dia=_NADA) -> None:
    novos = {k: v for k, v in (("nome", nome), ("tipo", tipo),
                               ("limite_perda_dia", limite_perda_dia))
             if v is not _NADA}
    if "nome" in novos:
        novos["nome"] = (novos["nome"] or "").strip()
        if not novos["nome"]:
            raise ValueError("a conta precisa de um nome")
    if "tipo" in novos and novos["tipo"] not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT nome, tipo, limite_perda_dia FROM contas "
                        "WHERE conta_id = ?", [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        atual = dict(zip(("nome", "tipo", "limite_perda_dia"), r))
        if "nome" in novos:
            _nome_livre(con, novos["nome"], conta_id)
        if "tipo" in novos and novos["tipo"] != atual["tipo"]:
            # a fase das variantes decide para qual conta vai a ordem: trocar
            # o tipo de uma conta já escolhida mandaria demo para o real
            if con.execute("SELECT 1 FROM portfolios WHERE conta_demo_id = ? "
                           "OR conta_real_id = ?",
                           [conta_id, conta_id]).fetchone():
                raise ValueError("a conta está escolhida num portfólio: "
                                 "tire-a de lá antes de trocar o tipo")
        for campo, valor in novos.items():
            if valor == atual[campo]:
                continue
            con.execute(f"UPDATE contas SET {campo} = ? WHERE conta_id = ?",
                        [valor, conta_id])
            diario.registrar(con, "conta_editada", "usuario",
                             conta_id=conta_id, de=atual[campo], para=valor,
                             motivo=campo)


def arquivar_conta(conta_id) -> None:
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT arquivada_em FROM contas WHERE conta_id = ?",
                        [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        if r[0] is not None:
            return                        # já arquivada: sem evento repetido
        con.execute("UPDATE contas SET arquivada_em = ? WHERE conta_id = ?",
                    [datetime.now(), conta_id])
        diario.registrar(con, "conta_arquivada", "usuario", conta_id=conta_id)


def listar_contas(incluir_arquivadas: bool = False) -> list[dict]:
    sql = (f"SELECT {', '.join(_COLS_CONTA)} FROM contas"
           + ("" if incluir_arquivadas else " WHERE arquivada_em IS NULL")
           + " ORDER BY nome")
    with db.connect(read_only=True) as con:
        return [dict(zip(_COLS_CONTA, r)) for r in con.execute(sql).fetchall()]


def _mudar_portfolio(portfolio_id, ligado: bool) -> None:
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT coalesce(ligado, false) FROM portfolios "
                        "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        if r is None:
            raise ValueError(f"portfólio #{portfolio_id} não existe")
        if bool(r[0]) == ligado:
            return
        con.execute("UPDATE portfolios SET ligado = ? WHERE portfolio_id = ?",
                    [ligado, portfolio_id])
        diario.registrar(con, "portfolio_ligado" if ligado
                         else "portfolio_desligado", "usuario",
                         portfolio_id=portfolio_id)


def ligar_portfolio(portfolio_id) -> None:
    _mudar_portfolio(portfolio_id, True)


def desligar_portfolio(portfolio_id) -> None:
    _mudar_portfolio(portfolio_id, False)


def _conta_valida(con, conta_id, tipo):
    if conta_id is None:
        return
    r = con.execute("SELECT tipo, arquivada_em FROM contas WHERE conta_id = ?",
                    [conta_id]).fetchone()
    if r is None:
        raise ValueError(f"conta #{conta_id} não existe")
    if r[0] != tipo:
        raise ValueError(f"a conta #{conta_id} não é do tipo {tipo}")
    if r[1] is not None:
        raise ValueError(f"a conta #{conta_id} está arquivada")


def definir_contas(portfolio_id, conta_demo_id, conta_real_id) -> None:
    with db.connect_write() as con, db.transacao(con):
        _conta_valida(con, conta_demo_id, "demo")
        _conta_valida(con, conta_real_id, "real")
        antes = con.execute("SELECT conta_demo_id, conta_real_id FROM portfolios "
                            "WHERE portfolio_id = ?", [portfolio_id]).fetchone()
        if antes is None:
            raise ValueError(f"portfólio #{portfolio_id} não existe")
        if tuple(antes) == (conta_demo_id, conta_real_id):
            return
        con.execute("UPDATE portfolios SET conta_demo_id = ?, conta_real_id = ? "
                    "WHERE portfolio_id = ?",
                    [conta_demo_id, conta_real_id, portfolio_id])
        diario.registrar(con, "portfolio_conta_mudou", "usuario",
                         portfolio_id=portfolio_id,
                         de=f"demo:{antes[0]} real:{antes[1]}",
                         para=f"demo:{conta_demo_id} real:{conta_real_id}")


_POR = ("usuario", "disjuntor")


def _membro(con, ligacao_id):
    r = con.execute("SELECT portfolio_id, variante_id, ligada, removido_em, "
                    "desligada_por FROM portfolio_membros WHERE ligacao_id = ?",
                    [ligacao_id]).fetchone()
    if r is None:
        raise ValueError(f"ligação #{ligacao_id} não existe")
    if r[3] is not None:
        raise ValueError(f"a ligação #{ligacao_id} foi removida do portfólio")
    return r


def desligar_membro(ligacao_id, por: str = "usuario") -> None:
    if por not in _POR:
        raise ValueError("desligar só 'usuario' ou 'disjuntor'")
    with db.connect_write() as con, db.transacao(con):
        pid, vid, ligada, _rem, _por = _membro(con, ligacao_id)
        if not ligada:
            return
        vigor = V.plano_em_vigor(vid, con=con)
        con.execute("UPDATE portfolio_membros SET ligada = false, "
                    "desligada_por = ?, desligada_em = ?, "
                    "desligada_plano_id = ? WHERE ligacao_id = ?",
                    [por, datetime.now(), vigor and vigor["plano_id"],
                     ligacao_id])
        diario.registrar(con, "membro_desligado", por, portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         plano_id=vigor and vigor["plano_id"])


def ligar_membro(ligacao_id) -> None:
    """Livre a qualquer momento, inclusive depois do disjuntor (decisão do
    usuário, 30/09/2026) — o evento guarda que foi religada depois dele."""
    with db.connect_write() as con, db.transacao(con):
        pid, vid, ligada, _rem, por = _membro(con, ligacao_id)
        if ligada:
            return
        vigor = V.plano_em_vigor(vid, con=con)
        con.execute("UPDATE portfolio_membros SET ligada = true, "
                    "desligada_por = NULL, desligada_em = NULL, "
                    "desligada_plano_id = NULL WHERE ligacao_id = ?",
                    [ligacao_id])
        diario.registrar(con, "membro_ligado", "usuario", portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         plano_id=vigor and vigor["plano_id"],
                         motivo="religada após disjuntor"
                         if por == "disjuntor" else None)


def vincular_plano(run_id, variante_id, manter_plano_id=None,
                   agora: datetime | None = None) -> None:
    """Põe uma mineração sem variante (e todos os planos dela) numa variante
    da mesma estratégia. Se a variante acabar com dois planos ativos, o
    usuário escolhe qual fica; o outro sai de vigor no próximo pregão."""
    agora = agora or datetime.now()
    sai_em = _plano.proximo_dia_util(agora.date())
    with db.connect_write() as con, db.transacao(con):
        m = con.execute("SELECT strategy, variante_id FROM mining_runs "
                        "WHERE run_id = ?", [run_id]).fetchone()
        v = con.execute("SELECT estrategia, nome FROM estrategia_variantes "
                        "WHERE variante_id = ?", [variante_id]).fetchone()
        if m is None or v is None:
            raise ValueError("mineração ou variante não existe")
        if m[1] is not None:
            raise ValueError(f"a mineração #{run_id} já é da variante #{m[1]}")
        if m[0] != v[0]:
            raise ValueError(f"a variante {v[1]} é de outra estratégia ({v[0]})")
        ativos = [r[0] for r in con.execute(
            "SELECT plano_id FROM planos_operacao WHERE estado = 'ativo' "
            "AND (variante_id = ? OR run_id = ?) ORDER BY plano_id",
            [variante_id, run_id]).fetchall()]
        if len(ativos) > 1 and manter_plano_id not in ativos:
            raise ValueError(
                "a variante ficaria com dois planos ativos: escolha qual fica ("
                + " ou ".join(f"#{p}" for p in ativos) + ")")
        planos = [r[0] for r in con.execute(
            "SELECT plano_id FROM planos_operacao WHERE run_id = ?",
            [run_id]).fetchall()]
        con.execute("UPDATE mining_runs SET variante_id = ? WHERE run_id = ?",
                    [variante_id, run_id])
        con.execute("UPDATE planos_operacao SET variante_id = ? "
                    "WHERE run_id = ?", [variante_id, run_id])
        for p in planos:
            diario.registrar(con, "plano_vinculado", "usuario", plano_id=p,
                             variante_id=variante_id,
                             motivo=f"mineração #{run_id}")
        for p in ativos:
            if len(ativos) > 1 and p != manter_plano_id:
                con.execute("UPDATE planos_operacao SET estado = 'aposentado', "
                            "aposentado_em = ? WHERE plano_id = ?", [sai_em, p])
                diario.registrar(con, "plano_aposentado", "usuario",
                                 plano_id=p, variante_id=variante_id,
                                 de="ativo", para="aposentado",
                                 motivo=f"fica o plano #{manter_plano_id}")


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
        try:
            salva = _optimizer.detalhes_salva(run_id) or {}
        except Exception:  # mineração antiga/incompleta: segue sem o espaço
            salva = {}
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
