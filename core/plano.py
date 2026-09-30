"""Guardar e recuperar um plano de operação.

O plano é o fim do passo 10: o documento que a incubação vai ler e que a
operação vai obedecer. Diferente do walk-forward, ele não é recalculável —
é decisão tomada num dia, com os números daquele dia.

Por isso tudo aqui é **retrato**: os parâmetros, o perfil de execução, o
capital e os limiares vão copiados para dentro da linha. Mineração apagada
não pode mudar o tamanho de posição de quem já está operando.

E plano não se edita: **aposenta-se** e grava-se outro. Histórico de decisão
reescrito não é histórico.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import db_manager as db
from . import diario
from . import engine

_JSON = ("params", "profile", "disjuntor", "expectativa", "reotimizacao",
         "definicoes", "regua")


def _padrao(obj):
    """O que o `json` padrão não sabe escrever e chega aqui de verdade.

    Os portões e o disjuntor vêm do numpy (`np.float64`, `np.bool_`, arrays):
    sem isto, o clique em "Gravar" quebrava justamente no plano mais
    completo — o que tem todos os números preenchidos.
    """
    import numpy as np
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _js(obj) -> str:
    return json.dumps(obj or {}, default=_padrao)

_COLUNAS = ("plano_id", "wfa_id", "run_id", "symbol", "strategy", "nome",
            "created_at", "params", "profile", "capital", "contratos",
            "risco_pedido_pct", "risco_efetivo_pct", "perda_referencia",
            "de_onde", "margem", "uso_margem_pct", "camada4_travada",
            "disjuntor", "expectativa", "reotimizacao", "definicoes",
            "regua", "estado", "motor_versao", "base_ate", "base_barras",
            "capital_livre", "reotimizar_em", "variante_id", "vale_a_partir",
            "aposentado_em", "codigo_hash")


def proximo_dia_util(d: date) -> date:
    """O próximo dia de semana depois de `d`. Feriado não precisa de
    calendário: sem pregão, o plano simplesmente começa no seguinte."""
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def salvar(*, wfa_id, run_id, symbol, strategy, nome, params, profile,
           capital, contratos, risco_pedido_pct, risco_efetivo_pct,
           perda_referencia, de_onde, margem, uso_margem_pct,
           camada4_travada, disjuntor, expectativa, reotimizacao,
           definicoes, regua, motor_versao=None, base_ate=None,
           base_barras=None, capital_livre=None, reotimizar_em=None,
           codigo_hash=None, agora: datetime | None = None) -> int:
    """Grava um plano e devolve o id.

    Nunca substitui: dois planos do mesmo walk-forward com risco diferente
    são duas decisões, e as duas ficam. O novo só vale a partir do próximo
    pregão — nunca se troca de parâmetro no meio do dia — e o anterior
    continua valendo até lá.
    """
    agora = agora or datetime.now()
    vale = proximo_dia_util(agora.date())
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT variante_id FROM mining_runs WHERE run_id = ?",
                        [run_id]).fetchone()
        variante_id = r[0] if r else None
        # um plano ativo por VARIANTE: reotimizar com mineração nova deixava
        # o antigo ativo, e se o novo sumisse o antigo voltava a valer
        # sozinho. Sem variante, vale a regra antiga (por walk-forward).
        alvo, arg = (("variante_id = ?", variante_id) if variante_id is not None
                     else ("wfa_id = ?", wfa_id))
        saem = [x[0] for x in con.execute(
            f"SELECT plano_id FROM planos_operacao WHERE {alvo} "
            "AND (estado = 'ativo' OR aposentado_em > ?)", [arg, vale]
        ).fetchall()]
        if saem:
            con.execute(
                "UPDATE planos_operacao SET estado = 'aposentado', "
                "aposentado_em = ? "
                f"WHERE plano_id IN ({', '.join('?' * len(saem))})",
                [vale, *saem])
        pid = con.execute("SELECT nextval('seq_plano_id')").fetchone()[0]
        con.execute(
            f"INSERT INTO planos_operacao ({', '.join(_COLUNAS)}) "
            f"VALUES ({', '.join('?' * len(_COLUNAS))})",
            [pid, wfa_id, run_id, symbol, strategy, nome or None, agora,
             _js(params), _js(profile),
             float(capital) if capital is not None else None,
             int(contratos) if contratos is not None else None,
             risco_pedido_pct, risco_efetivo_pct, perda_referencia, de_onde,
             float(margem) if margem is not None else None,
             uso_margem_pct,
             None if camada4_travada is None else bool(camada4_travada),
             _js(disjuntor), _js(expectativa),
             _js(reotimizacao), _js(definicoes),
             _js(regua), "ativo", motor_versao, base_ate,
             base_barras, capital_livre, reotimizar_em,
             variante_id, vale, None, codigo_hash])
        diario.registrar(con, "plano_gravado", "usuario", plano_id=pid,
                         variante_id=variante_id,
                         motivo=f"vale a partir de {vale:%d/%m/%Y}")
        for antigo in saem:
            diario.registrar(con, "plano_aposentado", "sistema",
                             plano_id=antigo, variante_id=variante_id,
                             de="ativo", para="aposentado",
                             motivo=f"substituído pelo plano #{pid}")
    return int(pid)


def retrato_da_base(symbol: str) -> dict:
    """Até onde ia a base, e com quantas barras, na hora de gravar o plano.

    Junto com a versão do motor, é o que permite refazer a mesma conta daqui
    a seis meses e saber por que o número mudou: a base cresce a cada
    exportação do MT5, e uma reimportação pode corrigir barras antigas.
    """
    with db.connect(read_only=True) as con:
        r = con.execute(
            "SELECT max(ts), count(*) FROM bars_m1 WHERE symbol = ?",
            [symbol]).fetchone()
    return {"motor_versao": engine.VERSAO,
            "base_ate": r[0] if r else None,
            "base_barras": int(r[1]) if r and r[1] else None}


def _linha(r) -> dict:
    d = dict(zip(_COLUNAS, r))
    for c in _JSON:
        d[c] = json.loads(d[c]) if d[c] else {}
    if d["camada4_travada"] is not None:
        d["camada4_travada"] = bool(d["camada4_travada"])
    return d


def listar(wfa_id: int | None = None, apenas_ativos: bool = False
           ) -> list[dict]:
    """Os planos gravados, mais recentes primeiro."""
    onde, args = [], []
    if wfa_id is not None:
        onde.append("wfa_id = ?")
        args.append(wfa_id)
    if apenas_ativos:
        onde.append("estado = 'ativo'")
    sql = (f"SELECT {', '.join(_COLUNAS)} FROM planos_operacao"
           + (" WHERE " + " AND ".join(onde) if onde else "")
           + " ORDER BY plano_id DESC")
    with db.connect(read_only=True) as con:
        return [_linha(r) for r in con.execute(sql, args).fetchall()]


def detalhes(plano_id: int) -> dict | None:
    with db.connect(read_only=True) as con:
        r = con.execute(
            f"SELECT {', '.join(_COLUNAS)} FROM planos_operacao "
            "WHERE plano_id = ?", [plano_id]).fetchone()
    return _linha(r) if r else None


def motivo_protecao(con, plano_ids, hoje: date | None = None) -> str | None:
    """Por que estes planos não podem sumir — ou None se podem.

    Protegido é o que opera ou pode operar: (a) ativo; (b) aposentado mas
    ainda em vigor (o pregão de hoje pode estar usando); (c) de uma
    variante que está em algum portfólio, ligado ou não. Recebe `con`
    porque é chamada de dentro da transação que ia apagar.
    """
    ids = [int(p) for p in plano_ids or []]
    if not ids:
        return None
    hoje = hoje or date.today()
    linhas = con.execute(
        "SELECT p.plano_id, p.estado, p.aposentado_em, ev.nome, pf.nome "
        "FROM planos_operacao p "
        "LEFT JOIN estrategia_variantes ev ON ev.variante_id = p.variante_id "
        "LEFT JOIN portfolio_membros pm ON pm.variante_id = p.variante_id "
        "     AND pm.removido_em IS NULL "
        "LEFT JOIN portfolios pf ON pf.portfolio_id = pm.portfolio_id "
        f"WHERE p.plano_id IN ({', '.join('?' * len(ids))}) "
        "ORDER BY p.plano_id", ids).fetchall()
    for pid, estado, _apos, variante, _pf in linhas:
        if estado == "ativo":
            return (f"o plano #{pid} está ativo"
                    + (f" na variante {variante}" if variante else ""))
    for pid, _estado, apos, _var, _pf in linhas:
        if apos is not None and apos > hoje:
            return f"o plano #{pid} ainda vale até {apos - timedelta(days=1):%d/%m}"
    for pid, _estado, _apos, variante, pf in linhas:
        if pf is not None:
            return (f"o plano #{pid} é da variante {variante}, que está no "
                    f"portfólio {pf}")
    return None


def aposentar(plano_id: int, agora: datetime | None = None) -> bool:
    """Tira o plano de operação sem apagá-lo — a partir do PRÓXIMO pregão.

    O pregão em curso termina com o plano com que começou; para parar
    agora, o caminho é o interruptor da ligação. Se já estava marcado para
    sair antes, fica a data mais cedo: aposentar de novo não prolonga.
    """
    agora = agora or datetime.now()
    data = proximo_dia_util(agora.date())
    with db.connect_write() as con, db.transacao(con):
        r = con.execute("SELECT estado, aposentado_em, variante_id "
                        "FROM planos_operacao WHERE plano_id = ?",
                        [plano_id]).fetchone()
        if r is None:
            return False
        estado, atual, variante_id = r
        nova = min(atual, data) if atual is not None else data
        con.execute("UPDATE planos_operacao SET estado = 'aposentado', "
                    "aposentado_em = ? WHERE plano_id = ?", [nova, plano_id])
        diario.registrar(con, "plano_aposentado", "usuario", plano_id=plano_id,
                         variante_id=variante_id, de=estado, para="aposentado",
                         motivo=f"sai de vigor em {nova:%d/%m/%Y}")
    return True


def excluir(plano_id: int) -> bool:
    with db.connect_write() as con, db.transacao(con):
        if con.execute("SELECT 1 FROM planos_operacao WHERE plano_id = ?",
                       [plano_id]).fetchone() is None:
            return False
        motivo = motivo_protecao(con, [plano_id])
        if motivo:
            raise ValueError(f"o plano #{plano_id} não pode ser apagado: {motivo}")
        con.execute("DELETE FROM planos_operacao WHERE plano_id = ?",
                    [plano_id])
    return True


# --------------------------------------------------- montar pela tela Candidata
# O que o plano diz em palavras, não só em números. Cada uma destas frases já
# causou prejuízo a alguém que achava que ela era óbvia.
REGRAS = [
    "Reotimizar imediatamente antes de ligar, com dado até a véspera: o "
    "walk-forward só mediu parâmetros com idade entre zero e o tamanho da "
    "janela fora da amostra, e entre aprovar e ligar passa-se um tempo que "
    "nenhum teste mediu.",
    "Nunca trocar parâmetro com posição aberta: reotimiza-se fora do pregão, "
    "e o parâmetro novo vale a partir da abertura seguinte. Se a "
    "reotimização mudar os parâmetros, este plano é aposentado e outro é "
    "gravado — contratos e limites juntos.",
]

DEFINICOES = {
    "novo_topo": "o maior saldo de fechamento de pregão desde que o plano "
                 "foi ligado",
    "queda": "medida do último topo até o FECHAMENTO do pregão, em reais, e "
             "comparada com o capital do plano — é assim que os limites foram "
             "calibrados",
    "posicao_aberta": "não conta durante o pregão: medir a oscilação de "
                      "dentro do dia dispararia antes do limite calibrado. O "
                      "risco intradiário é coberto pelo limite do dia",
    "depois_de_reduzir": "volta ao número de contratos do plano quando o "
                         "saldo fizer um topo novo",
    "depois_de_desligar": "volta a operar quando o usuário religar",
}


# A ressalva que muda o que o plano promete: se reotimizar não compensou, a
# receita de reotimização do plano contradiz o que a própria tela mediu.
# Decisão do usuário (19/09/2026): grava, com o aviso em destaque, e a
# ressalva vai escrita dentro do plano — quem decide é a incubação, olhando o
# resultado real.
RESSALVA_REOTIMIZAR = "Reotimizar compensou?"


def aviso_ao_gravar(veredito: dict) -> str | None:
    """O que precisa ser dito ANTES de gravar, mesmo podendo gravar."""
    nomes = [p if isinstance(p, str) else p.get("nome")
             for p in (veredito or {}).get("ressalvas_nomes")
             or (veredito or {}).get("ressalvas") or []]
    if RESSALVA_REOTIMIZAR in nomes:
        return ("atenção: neste walk-forward reotimizar NÃO compensou — a "
                "curva ficou abaixo da maioria das combinações fixas. O plano "
                "grava a receita de reotimização mesmo assim, e a ressalva vai "
                "dentro dele; vale conferir na incubação se operar parâmetro "
                "fixo não seria melhor")
    return None


def pode_gravar(veredito: dict, dim: dict, params: dict | None = None) -> str | None:
    """`None` quando o plano pode ser gravado; senão, o porquê, em palavras.

    O botão não pode só aparecer apagado: quem está na tela precisa saber
    qual das três travas está segurando, porque o remédio de cada uma é
    diferente — rodar os testes, mudar a estratégia ou mudar o capital.
    """
    estado = (veredito or {}).get("estado")
    if estado == "reprovada":
        nomes = " · ".join(veredito.get("reprovados") or [])
        return ("a estratégia foi reprovada"
                + (f" em: {nomes}" if nomes else "")
                + " — plano de operação é para estratégia aprovada")
    if estado != "aprovada" and estado != "aprovada com ressalva":
        return ("rode os testes completos antes de gravar: teste que não "
                "rodou não aprova nada")
    if params is not None and not params:
        # o DEPLOY pode sair "fora do mercado" (ninguém aprovado na janela, ou
        # a camada 4 travada sem candidata que case): gravar isso daria um
        # plano de operação que não diz o que operar
        return ("a última janela do walk-forward ficou fora do mercado: não "
                "há parâmetro para operar")
    if not dim or (dim.get("n") or 0) <= 0:
        # o motivo de `tamanho.contratos` já diz qual conta zerou; repetir
        # "não cabe nem 1 contrato" na frente dele só dobrava a frase
        return ((dim or {}).get("motivo")
                or "com o capital e o risco de agora não cabe nem 1 contrato")
    return None


# Os três prazos que o plano promete, em pregões. Um mês de pregão são ~21.
MARCOS = {"3_meses": 63, "6_meses": 126, "12_meses": 252}


def expectativa(pnl_dia, capital: float, fator: float = 1.0,
                boot: dict | None = None) -> dict:
    """Onde o lucro acumulado deve estar em 3, 6 e 12 meses, na faixa que
    vai do pior décimo ao melhor décimo dos caminhos sorteados.

    É contra ESTA faixa que a incubação vai comparar o resultado real: ficar
    dentro dela é a estratégia se comportando como o teste prometeu.

    `boot` é o sorteio que a tela **já fez** — o mesmo recorte e os mesmos
    caminhos do disjuntor. Sem ele, o plano gravava dois números diferentes
    para a mesma pergunta: R$ 39 no disjuntor e R$ 376 na faixa, para a mesma
    curva e o mesmo prazo, e a incubação receberia respostas contraditórias.
    Só os marcos ALÉM do prazo do sorteio da tela precisam de sorteio próprio
    — sobre a mesma série, para continuar sendo a mesma régua.

    `fator` é `contratos do plano ÷ contratos do backtest`: o sorteio saiu da
    curva do backtest, que pode não ter rodado com um contrato.
    """
    from . import robustez

    pronto = boot or {}
    env = pronto.get("envelope_p10")
    horizonte = len(env) if env is not None else 0
    estendido = None
    fora = {}
    for rotulo, pregao in MARCOS.items():
        usado = pronto
        if pregao > horizonte:
            if estendido is None:
                estendido = robustez.bootstrap(
                    pnl_dia, capital, horizonte=max(MARCOS.values())) or {}
            usado = estendido
        disponivel = usado.get("envelope_p10")
        if disponivel is None or pregao > len(disponivel):
            continue        # curva curta demais para prometer este prazo
        i = pregao - 1
        fora[rotulo] = {"pregoes": pregao,
                        "p10": float(usado["envelope_p10"][i]) * fator,
                        "p50": float(usado["envelope_p50"][i]) * fator,
                        "p90": float(usado["envelope_p90"][i]) * fator}
    return fora


def _quando_reotimizar(oos_meses) -> date | None:
    """A data da próxima reotimização, contada da gravação."""
    if not oos_meses:
        return None
    hoje = datetime.now().date()
    mes = hoje.month - 1 + int(oos_meses)
    ano = hoje.year + mes // 12
    dia = min(hoje.day, 28)          # evita 31/02 e afins
    return date(ano, mes % 12 + 1, dia)


def _portao_para_json(p: dict) -> dict:
    return {"nome": p.get("nome"), "ok": p.get("ok"),
            "critico": p.get("critico"), "valor": p.get("valor"),
            "exigido": p.get("exigido")}


def montar(wfa_id: int, d: dict, ref: dict, dim: dict, disj: dict,
           veredito: dict, expect: dict) -> dict:
    """Todos os campos de `salvar`, a partir do que a tela Candidata já
    calculou. Não recalcula nada: o plano grava o que o operador viu.
    """
    deploy = d.get("deploy") or {}
    n = int(dim.get("n") or 0)
    margem = dim.get("margem")
    capital = d.get("capital")
    capital_livre = (capital - n * float(margem)
                     if capital is not None and margem else capital)
    return {
        # identidade
        "wfa_id": wfa_id, "run_id": d.get("run_id"), "symbol": d.get("symbol"),
        "strategy": d.get("strategy"), "nome": d.get("nome"),
        # retratos
        "params": deploy.get("params") or {}, "profile": d.get("profile") or {},
        "capital": capital,
        # tamanho
        "contratos": n, "risco_pedido_pct": dim.get("risco_pedido_pct"),
        "risco_efetivo_pct": dim.get("risco_efetivo_pct"),
        "perda_referencia": ref.get("valor"), "de_onde": ref.get("de_onde"),
        "margem": margem, "uso_margem_pct": dim.get("uso_margem_pct"),
        "capital_livre": capital_livre,
        # quando parar, e o que se espera
        "disjuntor": disj or {}, "expectativa": expect or {},
        # a receita inteira da reotimização, não só a data
        "camada4_travada": d.get("camada4_travada"),
        "reotimizacao": {
            "run_id": d.get("run_id"), "inteligencia": d.get("inteligencia"),
            "is_meses": d.get("is_meses"), "oos_meses": d.get("oos_meses"),
            "camada4_travada": d.get("camada4_travada"),
            "criterios": "os critérios de aceite gravados na mineração "
                         f"#{d.get('run_id')}",
            "sem_combinacao_aprovada": "fica fora do mercado até a próxima "
                                       "reotimização",
        },
        # A data de reotimizar NÃO é o fim da janela do DEPLOY: com holdout,
        # essa janela começa no corte dos dados e costuma já ter vencido na
        # hora de gravar. A regra 1 manda reotimizar imediatamente antes de
        # ligar, então o prazo conta a partir de HOJE — e o campo fica em
        # branco quando não há quantos meses contar.
        "reotimizar_em": _quando_reotimizar(d.get("oos_meses")),
        "definicoes": {**DEFINICOES, "regras": list(REGRAS)},
        # a régua congelada: o veredito e cada portão como estava no dia
        "regua": {"veredito": (veredito or {}).get("estado"),
                  "portoes": [_portao_para_json(p)
                              for p in (veredito or {}).get("portoes") or []]},
        # reprodutibilidade
        "codigo_hash": d.get("codigo_hash"),
        **retrato_da_base(d.get("symbol")),
    }


def vencendo(dias_aviso: int = 7, hoje: date | None = None) -> list[dict]:
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=dias_aviso)
    sql = """
        SELECT p.plano_id, p.nome, p.symbol, p.strategy, p.reotimizar_em,
               ev.nome
        FROM planos_operacao p
        LEFT JOIN wfa_runs w ON w.wfa_id = p.wfa_id
        LEFT JOIN mining_runs m ON m.run_id = w.run_id
        LEFT JOIN estrategia_variantes ev ON ev.variante_id = m.variante_id
        WHERE p.estado = 'ativo'
          AND p.reotimizar_em IS NOT NULL
          AND p.reotimizar_em <= ?
        ORDER BY p.reotimizar_em
    """
    with db.connect(read_only=True) as con:
        rows = con.execute(sql, [limite]).fetchall()
    return [
        {"plano_id": r[0], "nome": r[1], "symbol": r[2], "strategy": r[3],
         "reotimizar_em": r[4], "variante_nome": r[5],
         "dias_restantes": (r[4] - hoje).days}
        for r in rows
    ]
