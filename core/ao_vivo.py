"""Tela Ao vivo: contas, interruptores e arrumação da cadeia.

Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md.
Toda mudança de estado grava o evento do diário NA MESMA transação.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import statistics

from . import codigo, comandos, engine
from . import db_manager as db
from . import diario
from . import diario_ordens
from . import optimizer as _optimizer
from . import papel
from . import papel_backtest as _pb
from . import plano as _plano
from . import variantes as V

_TIPOS_CONTA = ("demo", "real")
_COLS_CONTA = ("conta_id", "nome", "tipo", "limite_perda_dia", "criado_em",
               "arquivada_em", "login", "servidor", "terminal")
_NADA = object()


def _nome_livre(con, nome, ignorar_id=None):
    r = con.execute(
        "SELECT conta_id FROM contas WHERE nome = ? AND arquivada_em IS NULL "
        "AND conta_id IS DISTINCT FROM ?", [nome, ignorar_id]).fetchone()
    if r:
        raise ValueError(f"já existe uma conta ativa chamada '{nome}'")


def _texto_ou_none(v):
    if v is not None and not isinstance(v, str):
        raise ValueError("texto inválido: esperava um texto")
    return (v or "").strip() or None


def _limite_valido(v):
    """Limite de perda do dia: vazio/0 = sem limite (`None`), senão > 0.
    Negativo ligaria o envio com um limite que nunca é atingido."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise ValueError("o limite de perda do dia deve ser um número")
    if v < 0:
        raise ValueError("o limite de perda do dia não pode ser negativo")
    return float(v) if v else None


def _login_valido(v):
    if v is None:
        return None
    # bool é int em Python: True viraria conta 1 sem ninguém perceber
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ValueError("o número da conta deve ser um inteiro positivo")
    return int(v)


def _par_livre(con, login, servidor, ignorar_id=None):
    # o mesmo número pode existir em corretoras diferentes, então a chave é o
    # par; o DuckDB não tem UNIQUE parcial, por isso a checagem é aqui
    if login is None or servidor is None:
        return
    r = con.execute(
        "SELECT nome FROM contas WHERE login = ? AND servidor = ? "
        "AND arquivada_em IS NULL AND conta_id IS DISTINCT FROM ?",
        [login, servidor, ignorar_id]).fetchone()
    if r:
        raise ValueError(f"a conta {login} em {servidor} já está "
                         f"cadastrada como '{r[0]}'")


def criar_conta(nome, tipo, limite_perda_dia=None, *, login=None,
                servidor=None, terminal=None) -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("a conta precisa de um nome")
    if tipo not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    login = _login_valido(login)
    limite_perda_dia = _limite_valido(limite_perda_dia)
    servidor = _texto_ou_none(servidor)
    terminal = _texto_ou_none(terminal)
    with db.connect_write() as con, db.transacao(con):
        _nome_livre(con, nome)
        _par_livre(con, login, servidor)
        cid = con.execute("SELECT nextval('seq_conta_id')").fetchone()[0]
        con.execute(
            "INSERT INTO contas (conta_id, nome, tipo, limite_perda_dia, "
            "criado_em, arquivada_em, login, servidor, terminal) "
            "VALUES (?,?,?,?,?,NULL,?,?,?)",
            [cid, nome, tipo, limite_perda_dia, datetime.now(), login,
             servidor, terminal])
        diario.registrar(con, "conta_criada", "usuario", conta_id=cid,
                         para=nome, motivo=tipo)
    return int(cid)


_CAMPOS_EDITAVEIS = ("nome", "tipo", "limite_perda_dia", "login", "servidor",
                     "terminal")


def editar_conta(conta_id, *, nome=_NADA, tipo=_NADA, limite_perda_dia=_NADA,
                 login=_NADA, servidor=_NADA, terminal=_NADA,
                 tentativas: int = 40) -> None:
    novos = {k: v for k, v in (("nome", nome), ("tipo", tipo),
                               ("limite_perda_dia", limite_perda_dia),
                               ("login", login), ("servidor", servidor),
                               ("terminal", terminal))
             if v is not _NADA}
    if "nome" in novos:
        novos["nome"] = (novos["nome"] or "").strip()
        if not novos["nome"]:
            raise ValueError("a conta precisa de um nome")
    if "tipo" in novos and novos["tipo"] not in _TIPOS_CONTA:
        raise ValueError("tipo de conta deve ser 'demo' ou 'real'")
    if "login" in novos:
        novos["login"] = _login_valido(novos["login"])
    if "limite_perda_dia" in novos:
        novos["limite_perda_dia"] = _limite_valido(novos["limite_perda_dia"])
    for k in ("servidor", "terminal"):
        if k in novos:
            novos[k] = _texto_ou_none(novos[k])
    desligou_envio = None
    with db.connect_write(tentativas=tentativas) as con, db.transacao(con):
        r = con.execute(f"SELECT {', '.join(_CAMPOS_EDITAVEIS)} FROM contas "
                        "WHERE conta_id = ?", [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        atual = dict(zip(_CAMPOS_EDITAVEIS, r))
        trocou_acesso = ((("login" in novos and novos["login"] != atual["login"]))
                         or ("servidor" in novos
                             and novos["servidor"] != atual["servidor"]))
        if trocou_acesso and _conta_em_uso_com_posicao(con, conta_id,
                                                       atual["tipo"]):
            raise ValueError(f"a conta {atual['nome']} tem operação aberta: "
                             "feche a posição antes de trocar o login ou o "
                             "servidor")
        if "nome" in novos:
            _nome_livre(con, novos["nome"], conta_id)
        if "login" in novos or "servidor" in novos:
            _par_livre(con, novos.get("login", atual["login"]),
                       novos.get("servidor", atual["servidor"]), conta_id)
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
        # sem limite de perda não há envio: o limite é o que segura a conta
        if ("limite_perda_dia" in novos
                and not (novos["limite_perda_dia"] or 0) > 0):
            ligado = con.execute("SELECT coalesce(envio_ligado, false) FROM "
                                 "contas WHERE conta_id = ?",
                                 [conta_id]).fetchone()[0]
            if ligado:
                con.execute("UPDATE contas SET envio_ligado = false "
                            "WHERE conta_id = ?", [conta_id])
                diario.registrar(con, "envio_desligado", "usuario",
                                 conta_id=conta_id, motivo="limite apagado")
                # o tipo antes e depois da edição: se a troca de tipo veio
                # junto, o comando vai para as duas pastas em jogo
                desligou_envio = (atual["tipo"],
                                  novos.get("tipo", atual["tipo"]))
    if desligou_envio:
        # a captura não lê o banco para saber disso: vai por comando, para a
        # pasta da conta (o processo da real não lê a demo e vice-versa)
        for tipo in dict.fromkeys(desligou_envio):
            comandos.escrever(comandos.pasta_do_tipo(tipo), "envio",
                              conta_id=conta_id, ligado=False)


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
    r = con.execute("SELECT tipo, arquivada_em, nome FROM contas "
                    "WHERE conta_id = ?", [conta_id]).fetchone()
    if r is None:
        raise ValueError(f"conta #{conta_id} não existe")
    if r[0] != tipo:
        raise ValueError(f"a conta {r[2]} não é do tipo {tipo}")
    if r[1] is not None:
        raise ValueError(f"a conta {r[2]} está arquivada")


def _tem_operacao_aberta(tipo: str) -> bool:
    """Há ticket aberto no diário das ordens da origem `tipo` ("demo" ou
    "real")? Escolha desta tela: lê os arquivos do diário, que são a fonte
    que a automação mesmo usa para saber o que tem aberto. Não usa o banco
    (o espelho pode estar atrasado) nem o MT5 (a tela não o consulta). Um
    ticket conta como aberto se abriu em algum dia da pasta e não fechou em
    nenhum. Conservador: uma conta da origem com posição barra a troca de
    qualquer outra da mesma origem."""
    pasta = Path(diario_ordens.PASTA)
    if tipo == "real":
        pasta = pasta / "real"
    if not pasta.is_dir():
        return False
    abertos, fechados = set(), set()
    for arq in sorted(pasta.glob("*.jsonl")):
        try:
            dia = date.fromisoformat(arq.stem)
        except ValueError:
            continue
        for e in diario_ordens.Diario(pasta, dia, tipo).eventos:
            if not e.get("ticket"):
                continue
            if e["tipo"] in ("executada", "parcial", "adotada"):
                abertos.add(int(e["ticket"]))
            elif e["tipo"] in ("saida_executada", "saiu_antes"):
                fechados.add(int(e["ticket"]))
    return bool(abertos - fechados)


def _conta_em_uso_com_posicao(con, conta_id, tipo) -> bool:
    """A conta está escolhida num portfólio e a origem dela tem operação aberta."""
    if con.execute("SELECT 1 FROM portfolios WHERE conta_demo_id = ? "
                   "OR conta_real_id = ?", [conta_id, conta_id]).fetchone() is None:
        return False
    return _tem_operacao_aberta(tipo)


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
        # trocar a conta com posição aberta na origem deixaria a posição sem
        # quem a acompanhe na tela: recusa até fechar
        for tipo, velha, nova in (("demo", antes[0], conta_demo_id),
                                  ("real", antes[1], conta_real_id)):
            if velha is not None and velha != nova and _tem_operacao_aberta(tipo):
                raise ValueError(f"o portfólio tem operação aberta na conta "
                                 f"{tipo}: feche a posição antes de trocá-la")
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
        if len(ativos) > 1:
            # plano antigo tem vale_a_partir vazio = "em vigor desde sempre";
            # ao assumir o lugar do outro ele só passa a valer para ESTA
            # variante no dia em que o aposentado sai, e os pregões contam
            # daí; o plano que já era da variante não muda: ele já vale
            con.execute("UPDATE planos_operacao SET vale_a_partir = ? "
                        "WHERE plano_id = ? AND run_id = ? "
                        "AND vale_a_partir IS NULL",
                        [sai_em, manter_plano_id, run_id])
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
                plano_vigor.update(_plano.marca_mesmo_assim(
                    vigor["plano_id"], con=con))
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
            # pregões REAIS: os que o papel de fato rodou com este plano,
            # não os dias úteis desde a gravação (o serviço pode ter ficado
            # fora do ar)
            n_pregoes = 0
            if plano_vigor:
                n_pregoes = con.execute(
                    "SELECT count(*) FROM papel_pregoes WHERE ligacao_id = ? "
                    "AND plano_id = ? AND status IN ('rodando', 'conferido')",
                    [lig, plano_vigor["plano_id"]]).fetchone()[0]
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
                "pregoes_com_plano": n_pregoes,
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


# ------------------------------------- ordens: fase, contratos e envio
_FASES_ESCOLHA = ("papel", "demo", "real")


def _plano_do_membro(con, variante_id):
    vigor = V.plano_em_vigor(variante_id, con=con)
    return _plano.detalhes(vigor["plano_id"], con=con) if vigor else None


def _tem_stop(plano: dict) -> bool:
    _, perfil = papel.perfil_do_plano(plano)
    if perfil.stop_tipo == "atr":
        # ATR com multiplicador ou período zero não coloca stop nenhum
        return ((perfil.stop_atr_mult or 0) > 0
                and (perfil.stop_atr_periodo or 0) > 0)
    return (perfil.stop_pontos or 0) > 0


def _falhas_da_conferencia(con, ligacao_id, estrategia):
    """`(que valem hoje, mais antigas)`: dias com diferença entre papel e
    backtest. Só falha do MESMO código e do MESMO motor de hoje barra a
    promoção — a de uma versão antiga já foi tratada por quem mexeu."""
    hash_atual = codigo.hash_estrategia(estrategia)
    linhas = con.execute(
        "SELECT pb.dia, pp.codigo_hash, pp.motor_versao FROM papel_backtest pb "
        "LEFT JOIN papel_pregoes pp ON pp.ligacao_id = pb.ligacao_id "
        "AND pp.dia = pb.dia WHERE pb.ligacao_id = ? AND NOT pb.ok "
        "ORDER BY pb.dia", [ligacao_id]).fetchall()
    atuais = [d for d, h, m in linhas
              if h is not None and h == hash_atual and m == engine.VERSAO]
    return atuais, [d for d, _h, _m in linhas if d not in atuais]


def restricoes_para_demo(ligacao_id: int, *, tentativas: int = 40) -> dict:
    """O que impede (`motivos`) ou merece atenção (`avisos`) na promoção
    para a conta demo — a tela usa as mesmas frases que `mudar_fase`."""
    with db.connect(read_only=True, tentativas=tentativas) as con:
        return _restricoes(con, ligacao_id)


def _motivos_conta_real(con, pid) -> list[str]:
    """Para ir a real: o portfólio tem conta real e ela está pronta para
    mandar ordem (terminal, login, servidor e limite de perda do dia)."""
    r = con.execute("SELECT c.terminal, c.login, c.servidor, c.limite_perda_dia "
                    "FROM portfolios p JOIN contas c "
                    "ON c.conta_id = p.conta_real_id WHERE p.portfolio_id = ? "
                    "AND c.arquivada_em IS NULL", [pid]).fetchone()
    if r is None:
        return ["escolha uma conta real (não arquivada) para o portfólio "
                "antes de passar para real"]
    if not r[0] or r[1] is None or not r[2]:
        return ["a conta real precisa de terminal, login e servidor cadastrados"]
    if not (r[3] or 0) > 0:
        return ["a conta real precisa de limite de perda do dia"]
    return []


def _restricoes(con, ligacao_id, fase: str = "demo") -> dict:
    """O que impede a ligação de subir para `fase` ("demo" ou "real"). Real
    exige o que a demo exige (real ⊃ demo) e, além disso, a conta real pronta."""
    pid, vid, *_ = _membro(con, ligacao_id)
    motivos, avisos = [], []
    conta = con.execute("SELECT c.conta_id FROM portfolios p JOIN contas c "
                        "ON c.conta_id = p.conta_demo_id WHERE p.portfolio_id "
                        "= ? AND c.arquivada_em IS NULL", [pid]).fetchone()
    if conta is None:
        motivos.append("escolha uma conta demo (não arquivada) para o "
                       "portfólio antes de promover")
    plano = _plano_do_membro(con, vid)
    if plano is None:
        motivos.append("a variante não tem plano em vigor")
    elif not _tem_stop(plano):
        motivos.append("o plano em vigor não tem stop: sem stop não há como "
                       "limitar a perda de uma operação na conta")
    est = con.execute("SELECT estrategia FROM estrategia_variantes WHERE "
                      "variante_id = ?", [vid]).fetchone()[0]
    atuais, antigas = _falhas_da_conferencia(con, ligacao_id, est)
    if atuais:
        motivos.append(
            f"o papel diferiu do backtest em {len(atuais)} pregão(ões) com o "
            "código e o motor de hoje (último: "
            f"{atuais[-1]:%d/%m/%Y}): resolva a diferença antes de promover")
    if antigas:
        avisos.append(f"{len(antigas)} diferença(s) de antes da última mudança "
                      "de código ou motor: já não valem, mas confira")
    if not _pb.situacao(con, ligacao_id)["pregoes"]:
        avisos.append("nenhum pregão conferido contra o backtest ainda")
    if fase == "real":
        motivos.extend(_motivos_conta_real(con, pid))
    return {"motivos": motivos, "avisos": avisos}


def mudar_fase(ligacao_id: int, fase: str, *, quando=None,
               tentativas: int = 40) -> None:
    if fase not in _FASES_ESCOLHA:
        raise ValueError("fase deve ser 'papel', 'demo' ou 'real'")
    with db.connect_write(tentativas=tentativas) as con, db.transacao(con):
        pid, vid, _lig, _rem, _por = _membro(con, ligacao_id)
        atual = con.execute("SELECT fase FROM portfolio_membros WHERE "
                            "ligacao_id = ?", [ligacao_id]).fetchone()[0]
        if atual == fase:
            return
        # subir (papel→demo, papel→real, demo→real) exige o que a demo exige;
        # voltar (real→demo, qualquer→papel) não exige nada
        if fase == "real" or (fase == "demo" and atual == "papel"):
            motivos = _restricoes(con, ligacao_id, fase)["motivos"]
            if motivos:
                raise ValueError(motivos[0])
        agora = quando or datetime.now()
        # voltar ao papel não exige nada: a reconciliação encerra a posição
        con.execute("UPDATE portfolio_membros SET fase = ?, fase_desde = ? "
                    "WHERE ligacao_id = ?", [fase, agora, ligacao_id])
        vigor = V.plano_em_vigor(vid, con=con)
        diario.registrar(con, "fase_mudou", "usuario", portfolio_id=pid,
                         ligacao_id=ligacao_id, variante_id=vid,
                         plano_id=vigor and vigor["plano_id"], de=atual,
                         para=fase, quando=quando)


_COLUNA_CONTRATOS = {"demo": "contratos_demo", "real": "contratos_real"}


def definir_contratos(ligacao_id: int, contratos: int | None, *,
                      conta: str = "demo", tentativas: int = 40) -> None:
    """Contratos na conta `conta` ("demo" ou "real"), no lugar dos do plano
    (`None` volta ao plano). `tentativas`: a tela espera pouco pelo banco
    (ocupado = tente de novo)."""
    if conta not in _COLUNA_CONTRATOS:
        raise ValueError("conta deve ser 'demo' ou 'real'")
    coluna = _COLUNA_CONTRATOS[conta]
    if contratos is not None and (isinstance(contratos, bool)
                                  or not isinstance(contratos, int)
                                  or contratos < 1):
        raise ValueError("contratos deve ser um inteiro de 1 em diante "
                         "(ou vazio para usar os do plano)")
    with db.connect_write(tentativas=tentativas) as con, db.transacao(con):
        pid, vid, *_ = _membro(con, ligacao_id)
        antes = con.execute(f"SELECT {coluna} FROM portfolio_membros "
                            "WHERE ligacao_id = ?", [ligacao_id]).fetchone()[0]
        if antes == contratos:
            return
        con.execute(f"UPDATE portfolio_membros SET {coluna} = ? "
                    "WHERE ligacao_id = ?", [contratos, ligacao_id])
        diario.registrar(con, "contratos_alterados", "usuario",
                         portfolio_id=pid, ligacao_id=ligacao_id,
                         variante_id=vid,
                         de="plano" if antes is None else antes,
                         para="plano" if contratos is None else contratos,
                         motivo=conta)


def ligar_envio(conta_id: int, ligado: bool, *, tipo: str | None = None,
                tentativas: int = 40, espera: float = 0.25) -> None:
    """Interruptor do envio de ordens da conta. Desligar escreve o comando
    ANTES do banco: com ele ocupado (uma mineração), o desligar já vale.
    `tentativas`/`espera`: quem já garantiu o comando (o "Zerar tudo") não
    precisa segurar a tela 10 s esperando o banco.

    `tipo` diz a pasta de comandos da conta ("demo"/"real"). Sem ele, o
    desligar não lê o banco e vai para as DUAS pastas (o processo que não é
    dona da conta ignora). Ligar sempre lê o tipo do banco: o `tipo` passado
    precisa bater com ele."""
    ligado = bool(ligado)
    if not ligado:
        pastas = ([comandos.pasta_do_tipo(tipo)] if tipo is not None
                  else [comandos.PASTA, comandos.PASTA_REAL])
        for pasta in pastas:
            comandos.escrever(pasta, "envio", conta_id=conta_id, ligado=False)
    with db.connect_write(tentativas=tentativas, espera=espera) as con,             db.transacao(con):
        r = con.execute("SELECT limite_perda_dia, coalesce(envio_ligado, "
                        "false), arquivada_em, tipo FROM contas WHERE conta_id = ?",
                        [conta_id]).fetchone()
        if r is None:
            raise ValueError(f"conta #{conta_id} não existe")
        limite, atual, arquivada, tipo_banco = r
        if tipo is not None and tipo != tipo_banco:
            raise ValueError("o tipo informado não bate com o da conta")
        tipo = tipo_banco
        if ligado and tipo == "real":
            # até a parte 5 (processo próprio da conta real) existir
            raise ValueError("envio na conta real ainda não disponível")
        if ligado and arquivada is not None:
            raise ValueError("a conta está arquivada")
        if ligado and not (limite or 0) > 0:
            raise ValueError("cadastre o limite de perda do dia da conta "
                             "antes de ligar o envio")
        if bool(atual) != ligado:
            con.execute("UPDATE contas SET envio_ligado = ? WHERE conta_id = ?",
                        [ligado, conta_id])
            diario.registrar(con, "envio_ligado" if ligado
                             else "envio_desligado", "usuario",
                             conta_id=conta_id)
    if ligado:
        # a captura usa o comando para soltar um desligamento forçado do dia
        comandos.escrever(comandos.pasta_do_tipo(tipo), "envio",
                          conta_id=conta_id, ligado=True)


_LIMITE_DA_CONTA = {
    "demo": "SELECT c.limite_perda_dia FROM portfolios p JOIN contas c ON "
            "c.conta_id = p.conta_demo_id WHERE p.portfolio_id = ? "
            "AND c.arquivada_em IS NULL",
    "real": "SELECT c.limite_perda_dia FROM portfolios p JOIN contas c ON "
            "c.conta_id = p.conta_real_id WHERE p.portfolio_id = ? "
            "AND c.arquivada_em IS NULL",
}


def custo_de_um_stop(ligacao_id: int, contratos: int, *, conta: str = "demo",
                     tentativas: int = 60) -> dict:
    """Quanto custa UM stop com `contratos`, em reais e em % do limite de
    perda do dia da conta `conta` ("demo" ou "real") do portfólio. Sem
    distância de stop conhecida (ATR sem operação no papel) ou sem limite, o
    campo vem `None`."""
    if conta not in _LIMITE_DA_CONTA:
        raise ValueError("conta deve ser 'demo' ou 'real'")
    if (isinstance(contratos, bool) or not isinstance(contratos, int)
            or contratos < 1):
        raise ValueError("contratos deve ser um inteiro de 1 em diante")
    # a prévia da tela espera pouco: banco ocupado mostra "em seguida"
    with db.connect(read_only=True, tentativas=tentativas) as con:
        pid, vid, *_ = _membro(con, ligacao_id)
        plano = _plano_do_membro(con, vid)
        if plano is None:
            return {"reais": None, "pct_limite": None}
        _, perfil = papel.perfil_do_plano(plano)
        if perfil.stop_tipo == "atr":
            dists = [r[0] for r in con.execute(
                "SELECT abs(entry_px - stop_ini_px) FROM papel_operacoes "
                "WHERE ligacao_id = ? AND plano_id = ? "
                "AND stop_ini_px IS NOT NULL",
                [ligacao_id, plano["plano_id"]]).fetchall()]
            pontos = statistics.median(dists) if dists else None
        else:
            pontos = perfil.stop_pontos or None
        limite = con.execute(_LIMITE_DA_CONTA[conta], [pid]).fetchone()
    if pontos is None:
        return {"reais": None, "pct_limite": None}
    valor = float(db.load_instrument_yaml(
        plano.get("symbol") or papel.SIMBOLO)["point_value"])
    reais = float(pontos) * int(contratos) * valor
    lim = limite[0] if limite else None
    return {"reais": reais,
            "pct_limite": reais / lim * 100 if lim and lim > 0 else None}
