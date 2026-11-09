"""Leitura: eventos das ordens e cada operação da demo."""
from __future__ import annotations

import json
from datetime import date

from .base import _limites


# ======================================================================
# Parte 4: a demo ao lado do papel (spec ordens §8)
# ======================================================================
_COLS_EV = ("evento_id", "quando", "tipo", "conta_id", "ligacao_id", "entry_ts",
            "lado", "contratos", "simbolo", "ticket", "retcode", "preco_papel",
            "preco", "atraso_ms", "tentativa", "motivo")
# o que marca uma operação como tentada NA DEMO (o ensaio `seria_enviada`
# não é demo: com o Envio desligado nada foi à corretora)
_TENTOU = ("enviando", "executada", "parcial", "adotada", "recusada",
           "perdida", "nao_entrou", "aceita", "incerta")
_ENTROU = ("executada", "parcial", "adotada")
_SAIDA_FINAL = ("saida_executada", "saiu_antes")
# toda ordem que a corretora recusou: entrada, saída, proteção, cancelamento
_RECUSAS = ("recusada", "saida_recusada", "protecao_recusada",
            "cancelar_recusada")
# motivo da saída gravado pelo motor -> como a mesa chama
_MOTIVO_SAIDA = {"papel zerado": "sinal"}


def _ligs_do_portfolio(con, portfolio_id: int) -> list[int]:
    """Todas as ligações que o portfólio já teve, removidas inclusive: o
    diário de um dia passado pode ter eventos de uma que saiu depois."""
    return [int(r[0]) for r in con.execute(
        "SELECT ligacao_id FROM portfolio_membros WHERE portfolio_id = ?",
        [portfolio_id]).fetchall()]


def eventos_ordens(con, portfolio_id: int, dia: date, origem: str = "demo") -> list[dict]:
    """O diário das ordens do dia (o espelho `ordens_eventos`): os eventos
    das ligações do portfólio e os da automação sem ligação (chamado de
    infraestrutura, comando, trava da conta). Em ordem de tempo; os campos
    de `dados` vêm soltos no dicionário, como no arquivo do diário. Só a
    `origem` pedida ("demo" ou "real")."""
    ini, fim = _limites(dia)
    ligs = _ligs_do_portfolio(con, portfolio_id)
    filtro = "ligacao_id IS NULL"
    if ligs:
        filtro += f" OR ligacao_id IN ({', '.join('?' * len(ligs))})"
    linhas = con.execute(
        f"SELECT {', '.join(_COLS_EV)}, dados FROM ordens_eventos "
        f"WHERE quando >= ? AND quando < ? AND origem = ? AND ({filtro}) "
        "ORDER BY quando, evento_id", [ini, fim, origem, *ligs]).fetchall()
    out = []
    for r in linhas:
        e = dict(zip(_COLS_EV, r[:-1]))
        if r[-1]:
            try:
                extra = json.loads(r[-1])
            except (TypeError, ValueError):
                extra = {}
            if isinstance(extra, dict):
                # as colunas mandam: `dados` só traz o que não tem coluna
                e.update({k: v for k, v in extra.items() if k not in e})
        out.append(e)
    return out


def _derrapagem(preco_demo, preco_papel, lado, tick, ponta: str):
    """Ticks por ponta, positivo = pior para o operador. Entrada: pagar
    mais caro na compra (vender mais barato na venda) é pior; saída: o
    contrário. Sem um dos preços: None (não se inventa zero)."""
    if preco_demo is None or preco_papel is None or not lado or not tick:
        return None
    dif = float(preco_demo) - float(preco_papel)
    if ponta == "saida":
        dif = -dif
    return dif * int(lado) / float(tick)


def _preco_medio(saidas: list[dict]):
    """Preço médio das saídas (parciais e a final), pesado pelos contratos."""
    com = [(float(e["preco"]), float(e.get("contratos") or 0)) for e in saidas
           if e.get("preco")]          # 0 = sem preço (bolsa, diário antigo)
    if not com:
        return None
    peso = sum(c for _, c in com)
    if peso <= 0:
        return com[-1][0]
    return sum(p * c for p, c in com) / peso


def _texto_pedido(e: dict) -> str:
    """"VENDA 2 WINV26 · stop 188.575 · alvo 187.495" — o que iria à
    corretora, para o ensaio com o Envio desligado ser conferível."""
    lado = "COMPRA" if (e.get("lado") or 0) > 0 else "VENDA"
    ctr = e.get("contratos")
    partes = [f"{lado} {'' if ctr is None else int(ctr)} {e.get('simbolo') or ''}"
              .replace("  ", " ").strip()]
    for rot, chave in (("stop", "stop_px"), ("alvo", "alvo_px")):
        if e.get(chave) is not None:
            partes.append(f"{rot} {int(e[chave]):,}".replace(",", "."))
    return " · ".join(partes)


def checagem_ensaio(e: dict) -> str | None:
    """O que o `order_check` disse do pedido do ensaio ("seria enviada"):
    None quando passou (retcode 0) ou o evento é de antes da conferência.
    O retcode 0 é o "Done" do exemplo oficial do order_check (mql5.com)."""
    erro = e.get("last_error")
    if erro:
        return f"conferência sem resposta do MT5 ({_texto_erro(erro)})"
    rc = e.get("retcode")
    if rc is None:
        return None
    try:
        rc = int(rc)
    except (TypeError, ValueError):
        return None
    if rc == 0:
        return None
    from ..corretora import TEXTOS
    return f"seria recusada: {e.get('comment') or TEXTOS.get(rc) or f'retorno {rc}'}"


def _texto_erro(erro) -> str:
    if isinstance(erro, (list, tuple)):
        return " ".join(str(x) for x in erro if x is not None)
    return str(erro)


def _ordinal(n: int) -> str:
    return f"{n}ª"


def _uma_operacao_demo(chave, evs: list[dict], papel_op: dict | None,
                       lig: dict, tick: int, pv: float,
                       slip_plano: float | None = None) -> dict:
    """Uma linha da tabela "Operações do dia" da demo, a partir de todos os
    eventos da operação `(ligacao_id, entry_ts)` (os de saída casados pelo
    ticket). `slip_plano`: a derrapagem que o plano da operação supõe,
    em ticks por ponta (o preço do papel já a inclui)."""
    lig_id, entry_ts = chave
    tipos = [e["tipo"] for e in evs]
    com_lado = next((e for e in evs if e.get("lado")), None)
    lado = int(com_lado["lado"]) if com_lado else (
        int(papel_op["side"]) if papel_op else None)
    linha = {"ligacao_id": lig_id, "entry_ts": entry_ts,
             "variante": lig["nome"], "cor": lig["cor"], "lado": lado,
             "contratos": None, "preco_entrada": None, "preco_saida": None,
             "exit_ts": None, "derrapagem_entrada": None,
             "derrapagem_saida": None, "pontos": None, "resultado": None,
             "situacao": None, "saida_motivo": None, "nota": None,
             "pedido": None, "checagem": None, "atraso_ms": None,
             "mesmo_minuto": False,
             "recusas": tipos.count("recusada"),
             "rejeitadas": sum(tipos.count(t) for t in _RECUSAS),
             # o atraso de cada execução da entrada (a adoção não tem)
             "atrasos_ms": [float(e["atraso_ms"]) for e in evs
                            if e["tipo"] in ("executada", "parcial")
                            and e.get("atraso_ms") is not None],
             "slippage_plano": slip_plano, "papel_mesmo_tamanho": None,
             "papel_liquido": None if papel_op is None
             else float(papel_op["liquido"] or 0.0)}
    entradas = [e for e in evs if e["tipo"] in _ENTROU]
    if not entradas:
        if "seria_enviada" in tipos:
            e = next(e for e in evs if e["tipo"] == "seria_enviada")
            linha.update(situacao="seria_enviada", pedido=_texto_pedido(e),
                         checagem=checagem_ensaio(e))
            return linha
        perdida = next((e for e in reversed(evs) if e["tipo"] == "perdida"), None)
        if perdida is not None:
            motivo = perdida.get("motivo")
            if motivo == "automação fora do ar":
                linha["situacao"] = "fora_do_ar"
            elif "recusada" in tipos:
                linha["situacao"] = "recusada_perdida"
            else:
                linha["situacao"] = "perdida"
            linha["nota"] = motivo
        elif "nao_entrou" in tipos:
            e = next(e for e in evs if e["tipo"] == "nao_entrou")
            linha.update(situacao="nao_entrou", nota=e.get("motivo"))
        elif "recusada" in tipos and tipos[-1] == "recusada":
            linha["situacao"] = "recusada"      # segue tentando na janela
        else:
            linha["situacao"] = "enviando"
        return linha

    ent = entradas[0]
    contratos = sum(float(e.get("contratos") or 0) for e in entradas
                    if e["tipo"] != "adotada") or float(ent.get("contratos") or 0)
    # bolsa (conta real): a resposta da ordem vem sem preço; o motor grava o
    # do negócio depois, em `preco_confirmado` (um por ponta)
    conf = {e.get("ponta"): float(e["preco"]) for e in evs
            if e["tipo"] == "preco_confirmado" and e.get("preco")}
    # (0 = sem preço: o diário de antes do `preco_confirmado` gravou assim)
    preco_ent = float(ent["preco"]) if ent.get("preco") else conf.get("entrada")
    papel_ent = (papel_op["entry_px"] if papel_op is not None
                 else ent.get("preco_papel"))
    if papel_op is not None and papel_op.get("bruto") is not None \
            and papel_op.get("contratos"):
        # o papel no tamanho da demo e bruto como ela: o papel opera os
        # contratos do plano e desconta custos; a demo, os dela e sem custo
        linha["papel_mesmo_tamanho"] = round(
            float(papel_op["bruto"]) / int(papel_op["contratos"]) * contratos, 2)
    linha.update(contratos=contratos, preco_entrada=preco_ent,
                 atraso_ms=ent.get("atraso_ms"),
                 derrapagem_entrada=_derrapagem(preco_ent, papel_ent, lado,
                                                tick, "entrada"),
                 # a ordem saiu no mesmo minuto do sinal do papel?
                 mesmo_minuto=ent["quando"].replace(second=0, microsecond=0)
                 == entry_ts.replace(second=0, microsecond=0))
    finais = [e for e in evs if e["tipo"] in _SAIDA_FINAL]
    if not finais:
        linha["situacao"] = "aberta"
        return linha
    fim = finais[-1]
    saidas = [dict(e, preco=conf["saida"])
              if not e.get("preco") and e["tipo"] != "saiu_antes" and "saida" in conf
              else e
              for e in evs if e["tipo"] in ("saida_parcial", "saida_executada",
                                            "saiu_antes")]
    preco_sai = _preco_medio(saidas)
    papel_sai = (papel_op["exit_px"] if papel_op is not None
                 and papel_op.get("exit_px") is not None else None)
    pontos = (None if preco_sai is None or preco_ent is None
              else (preco_sai - preco_ent) * lado)
    motivo = fim.get("motivo") or ""
    # a corretora "executou" o stop/alvo sem negócio nesse preço: o preço da
    # saída não é de mercado, então não entra na derrapagem
    fora = any(e.get("fora_do_mercado") for e in saidas)
    linha.update(situacao="fechada", exit_ts=fim["quando"],
                 preco_saida=preco_sai,
                 derrapagem_saida=None if fora else _derrapagem(
                     preco_sai, papel_sai, lado, tick, "saida"),
                 pontos=None if pontos is None else round(pontos),
                 resultado=None if pontos is None
                 else round(pontos * contratos * pv, 2),
                 saida_motivo=_MOTIVO_SAIDA.get(motivo, motivo or None))
    envios = [e for e in evs if e["tipo"] == "saida_enviando"]
    if fora:
        linha["nota"] = "execução fora do mercado (corretora)"
    elif len(envios) > 1 and fim["tipo"] == "saida_executada":
        recusa = next((e.get("motivo") for e in reversed(evs)
                       if e["tipo"] == "saida_recusada" and e.get("motivo")), None)
        seg = round((fim["quando"] - envios[0]["quando"]).total_seconds())
        detalhe = f"{recusa}, {seg} s" if recusa else f"{seg} s"
        linha["nota"] = (f"saiu na {_ordinal(len(envios))} tentativa "
                         f"({detalhe})")
    return linha
