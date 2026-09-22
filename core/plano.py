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
from datetime import date, datetime

from . import db_manager as db
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
            "capital_livre", "reotimizar_em")


def salvar(*, wfa_id, run_id, symbol, strategy, nome, params, profile,
           capital, contratos, risco_pedido_pct, risco_efetivo_pct,
           perda_referencia, de_onde, margem, uso_margem_pct,
           camada4_travada, disjuntor, expectativa, reotimizacao,
           definicoes, regua, motor_versao=None, base_ate=None,
           base_barras=None, capital_livre=None, reotimizar_em=None) -> int:
    """Grava um plano e devolve o id.

    Nunca substitui: dois planos do mesmo walk-forward com risco diferente
    são duas decisões, e as duas ficam.
    """
    with db.connect_write() as con, db.transacao(con):
        # só um plano ATIVO por walk-forward: dois ativos deixariam a
        # incubação sem saber qual obedecer, e um duplo clique já criava
        # esse caso. O anterior continua no banco, aposentado.
        con.execute("UPDATE planos_operacao SET estado = 'aposentado' "
                    "WHERE wfa_id = ? AND estado = 'ativo'", [wfa_id])
        pid = con.execute("SELECT nextval('seq_plano_id')").fetchone()[0]
        con.execute(
            f"INSERT INTO planos_operacao ({', '.join(_COLUNAS)}) "
            f"VALUES ({', '.join('?' * len(_COLUNAS))})",
            [pid, wfa_id, run_id, symbol, strategy, nome or None,
             datetime.now(),
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
             base_barras, capital_livre, reotimizar_em])
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


def aposentar(plano_id: int) -> bool:
    """Tira o plano de operação sem apagá-lo.

    É o caminho normal: trocou de parâmetro, mudou o risco ou o disjuntor
    disparou, aposenta este e grava outro. O que ficou gravado é o que foi
    decidido na época, e continua valendo como registro.
    """
    if detalhes(plano_id) is None:
        return False
    with db.connect_write() as con, db.transacao(con):
        con.execute("UPDATE planos_operacao SET estado = 'aposentado' "
                    "WHERE plano_id = ?", [plano_id])
    return True


def excluir(plano_id: int) -> bool:
    if detalhes(plano_id) is None:
        return False
    with db.connect_write() as con, db.transacao(con):
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
    "depois_de_desligar": "só volta a operar depois de reotimizar e gravar "
                          "um plano novo — nunca religando o mesmo",
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
        **retrato_da_base(d.get("symbol")),
    }
