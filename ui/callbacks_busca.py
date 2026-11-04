"""Callbacks da subtela Mineração › Busca automática.

O desenho é do `ui/assets/busca.js` (contrato: layout B); aqui só se monta o
que ele mostra (`dados_da_tela`) e se atende o que ele pede. Nada daqui roda
a busca: quem roda é o processo `busca.py`, comandado por `core.busca.controle`.

As contas pesadas (mapas, lista) só são refeitas quando a busca muda de
versão; o relógio de 2 s devolve `no_update` quando nada mudou.
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime

from dash import ALL, Input, Output, State, ctx, no_update

from core import ativo as ativo_mod
from core.busca import banco, controle, detalhe, projecao
from core.busca import catalogo as cat
from core.busca.espaco import CAMPO_ALVO, CAMPO_STOP, Espaco
from strategies import registry

from .callbacks import (MENU_COMBINACAO, MENU_PERFIL, _menu_atual, _simbolo,
                        menu_do_perfil, perfil_da_busca)

EIXOS = projecao.EIXOS
# o protótipo escreve em minutos (M60): o rótulo sai da duração no motor
from core.engine.execution import TIMEFRAMES as _TF_MOTOR  # noqa: E402

ROTULO_TF = {t: f"M{m}" for t, m in _TF_MOTOR.items()}
SAIDA = {0: "sai e fica zerado", 1: "não sai no sinal", 2: "vira a mão",
         3: "saída própria"}
DIRECAO = {"compra": "compra", "venda": "venda", "ambas": "as duas"}
NOME_META = {"fr": "Fator de recuperação", "pf": "Profit factor",
             "lucro": "Lucro líquido", "dd": "Menor drawdown"}
SIGLA_META = {"fr": "FR", "pf": "PF", "lucro": "lucro", "dd": "drawdown"}

DICA_ESTADO = {
    "parada": "Nada rodando. Confira o Espaço de busca e clique em Iniciar busca.",
    "rodando": "Testando num processo à parte. Pode fechar o app: ela continua. "
               "O mapa atualiza sozinho.",
    "pausada": "Parada no meio, sem perder nada. Continuar retoma do mesmo ponto. "
               "O horário de parar continua valendo.",
    "concluida": "Parou e guardou tudo. Continuar roda mais uma rodada na mesma "
                 "busca. Nova busca começa do zero; esta fica em Buscas salvas.",
    "interrompida": "A busca caiu (o PC desligou ou o processo fechou). O que foi "
                    "testado até ali está salvo. Continuar retoma de onde parou.",
}

_cache: dict = {}
# uma atualização da tela por vez: com a busca grande, uma leitura pode levar
# segundos, e pedidos empilhados ocupavam o servidor do app inteiro
_ATUALIZANDO = threading.Lock()
# no app a leitura do banco da busca desiste rápido (ver banco.LEITURA_TENTATIVAS)
banco.LEITURA_TENTATIVAS = 2


def _json_seguro(v):
    """Infinito e NaN não existem em JSON: o navegador recusaria a resposta
    inteira e o Dash a descartaria calado. Viram null (a tela lê como ∞)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _json_seguro(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_seguro(x) for x in v]
    return v


# ------------------------------------------------------------ textos
def _hm(segundos) -> str:
    if segundos is None:
        return "—"
    m = int(segundos // 60)
    return f"{m // 60}h{m % 60:02d}"


def _hora(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def _data_hora(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return ""


def _milhar(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _quando(st: str, est: dict, b: dict | None) -> str:
    if st == "rodando":
        return f"desde {_hora(est.get('inicio'))}" if est.get("inicio") else ""
    if st == "pausada" and est.get("pausada_em"):
        mins = int((datetime.now() - datetime.fromisoformat(est["pausada_em"]))
                   .total_seconds() // 60)
        return f"às {_hora(est['pausada_em'])}, há {mins} min"
    if st == "concluida":
        ini, fim = est.get("inicio") or (b or {}).get("inicio"), est.get("fim") or (b or {}).get("fim")
        return f"de {_data_hora(ini)} até {_data_hora(fim)}" if ini and fim else ""
    if st == "interrompida":
        return f"caiu às {_hora(est.get('vivo_em'))}, testes salvos" if est.get("vivo_em") else ""
    return ""


# ------------------------------------------------------------ escolha
def _busca_da_tela(sel, estrategia, simbolo):
    """A busca mostrada: a escolhida; senão a viva desta estratégia e ativo;
    senão a mais recente delas. "nova" = tela parada, espaço editável."""
    if sel == "nova":
        return None
    if isinstance(sel, int):
        # a escolhida só vale enquanto é da estratégia e do ativo do menu:
        # trocar o menu mostra as buscas DELES (e "Abrir o campeão" nunca
        # leva os números de uma estratégia para outra)
        b = banco.ler_busca(sel)
        if b and b["estrategia"] == estrategia and b["simbolo"] == simbolo:
            return sel
    try:
        lista = banco.listar(estrategia, simbolo)
    except banco.BancoOcupado:
        return None
    viva = controle.ativa()
    if viva is not None and any(x["busca_id"] == viva for x in lista):
        return viva
    return lista[0]["busca_id"] if lista else None


# ------------------------------------------------------------ espaço
def _faixa_txt(f, casas=None) -> str:
    def n(v):
        if isinstance(v, float) and casas is not None:
            return f"{v:.{casas}f}".replace(".", ",")
        return str(v).replace(".", ",")
    return f"{n(f['de'])} a {n(f['ate'])}"


def _itens_espaco(estrategia: str, simbolo: str, faixas: dict) -> list[dict]:
    """O catálogo na forma que a aba Espaço de busca desenha (desenho §6:
    item novo no catálogo aparece aqui sem mudar a tela)."""
    out = []
    for it in cat.montar_catalogo(estrategia, simbolo):
        f = {**it.padrao, **(faixas.get(it.nome) or {})}
        d = {"nome": it.nome, "rotulo": it.rotulo, "tipo": it.tipo,
             "degrau": it.degrau, "onde": it.onde, "faixa": f}
        if it.tipo == "lista":
            rot = {"timeframe": lambda v: ROTULO_TF.get(v, v),
                   "direcao": lambda v: DIRECAO.get(v, v),
                   "saida": lambda v: SAIDA.get(v, str(v))}.get(it.nome, str)
            d["opcoes"] = [{"valor": v, "rotulo": rot(v)} for v in it.padrao["valores"]]
        elif it.tipo == "dias":
            d["opcoes"] = [{"valor": v, "rotulo": projecao.DIAS[v]} for v in it.padrao["valores"]]
        elif it.tipo == "gestao":
            nomes = {"pontos": "pontos", "atr": "ATR", "percentual": "%",
                     "multiplicador": "× stop", "sem": "sem alvo"}
            casas = {"pontos": None, "atr": 2, "percentual": 2, "multiplicador": 1}
            d["opcoes"] = [{"tipo": t, "rotulo": nomes[t], **ff}
                           for t, ff in f["tipos"].items()]
        out.append(d)
    return out


def _num_br(v) -> str:
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _fixos(p, moeda: str = "") -> list[list[str]]:
    """O que vale igual para todas as combinações (bloco "Fixos")."""
    adx = ("—" if not (int(p.adx_periodo or 0) and int(p.adx_limiar or 0))
           else f"{'tendência' if p.filtro_adx == 'tendencia' else 'rango'} "
                f"{p.adx_periodo}/{p.adx_limiar}")
    sem = ", ".join(h[:2] + "h" for h in (p.sem_entrada1, p.sem_entrada2, p.sem_entrada3) if h) or "—"
    lim = [f"ganho {p.limite_ganho_contrato:g}" if p.limite_ganho_contrato else "",
           f"perda {p.limite_perda_contrato:g}" if p.limite_perda_contrato else "",
           f"{p.max_trades_dia} op." if p.max_trades_dia else "",
           f"{p.max_prejuizos_dia} prej." if p.max_prejuizos_dia else ""]
    return [["Filtro de mercado", adx], ["Sem entradas", sem],
            ["Limites diários", ", ".join(x for x in lim if x) or "—"],
            ["Breakeven", f"{p.breakeven_pct:g}% do alvo" if p.breakeven_pct else "desligado"],
            ["Stop móvel", f"{p.step_gatilho_pct:g}% / {p.step_distancia_pct:g}%"
             if p.step_gatilho_pct else "desligado"],
            ["Custos", f"{moeda} {_num_br(p.corretagem_por_contrato + p.emolumentos_por_contrato)}"
             f" + {p.slippage_ticks} tick{'s' if p.slippage_ticks != 1 else ''}".strip()]]


# ------------------------------------------------------------ dados
MAPA_A_CADA_S = 10.0


def _mapas(busca_id: int, versao, rodando: bool) -> dict | None:
    """Os três eixos, com a evolução pendurada em cada casa. Caro (segundos
    numa busca grande): com a busca rodando, refeito no máximo a cada 10 s.

    Sem esse teto a tela travava: a versão muda a cada lote, cada leitura
    levava mais que o relógio de 2 s, e o Dash descarta a resposta que chega
    depois do pedido seguinte — nenhuma chegava a tempo. Banco ocupado pela
    busca: fica o último mapa."""
    chave = (busca_id, versao)
    cache_ok = _cache.get("mapas_busca") == busca_id
    if cache_ok and (_cache.get("mapas_chave") == chave or (
            rodando and time.monotonic() - _cache.get("mapas_em", 0) < MAPA_A_CADA_S)):
        return _cache["mapas"]
    try:
        mapas = projecao.mapas_todos(busca_id, "fr")
    except banco.BancoOcupado:
        return _cache["mapas"] if cache_ok else None
    for m in mapas.values():
        for c in m["casas"]:
            c["dims"] = [list(d) for d in c["dims"]]
        m["linhas"] = [ROTULO_TF.get(t, t) for t in m["linhas"]]
    _cache.update(mapas_chave=chave, mapas_busca=busca_id, mapas=mapas,
                  mapas_em=time.monotonic())
    return mapas


def _salvas(estrategia, simbolo, viva) -> list[dict]:
    try:
        lista = banco.listar(estrategia, simbolo)
    except banco.BancoOcupado:
        return _cache.get(("salvas", estrategia, simbolo), [])
    out = []
    for x in lista:
        st = x["status"]
        if st in ("rodando", "pausada") and x["busca_id"] != viva:
            st = "interrompida"
        out.append({"id": x["busca_id"], "data": f"{x['criada_em']:%d/%m}",
                    "status": st, "testes": _milhar(x["testes"] or 0)})
    _cache[("salvas", estrategia, simbolo)] = out
    return out


def dados_da_tela(sel, estrategia, simbolo, perfil, menu_ok=True) -> dict:
    bid = _busca_da_tela(sel, estrategia, simbolo)
    viva = controle.ativa()
    moeda = ativo_mod.SIMBOLOS_MOEDA.get(ativo_mod.moeda_de(simbolo), "")
    base = {"cpu_total": os.cpu_count() or 24, "moeda": moeda,
            "salvas": _salvas(estrategia, simbolo, viva), "menu_ok": menu_ok,
            "metas": [{"valor": k, "rotulo": v} for k, v in NOME_META.items()]}
    base.update(estrategia=estrategia, simbolo=simbolo)
    if bid is None:
        return {**base, "busca_id": None, "status": "parada",
                "dica": DICA_ESTADO["parada"], "quando": "",
                "criterio": "fr", "sigla": "FR", "minimo": 400,
                "espaco": {"itens": _itens_espaco(estrategia, simbolo, {}),
                           "fixos": _fixos(perfil, moeda), "travado": False},
                "controle": {"nucleos": 20, "parar_as": "08:30",
                             "parar_as_ligado": True, "limite": None},
                "mapas": None}
    e = controle.ler(bid)
    try:
        b = e.get("busca") or banco.ler_busca(bid) or {}
    except banco.BancoOcupado:          # a busca gravando: vale o estado.json
        b = {}
    cfg = b.get("config") or {}
    st = e["status"]
    if st == "erro":          # falhou e parou: na tela, como a que caiu
        st = "interrompida"
    crit = cfg.get("criterio", "fr")
    estimativa = e.get("estimativa_total")
    distintos = e.get("distintos") or b.get("distintos") or 0
    if st == "concluida":
        de_txt, barra = "feitos", 100
    elif estimativa:
        de_txt = f"de ~{_milhar(estimativa)}"
        barra = min(100, round(100 * distintos / max(estimativa, 1)))
    else:
        de_txt, barra = "", 0
    if st == "rodando":
        faltam = f"faltam ~{_hm(e['restante_s'])}" if e.get("restante_s") else ""
    elif st == "pausada":
        faltam = "pausada"
    elif st == "concluida":
        motivo = {"horario": f"parou às {(e.get('controle') or {}).get('parar_as', '')}",
                  "limite": "limite de testes", "parar": "parada por você"}
        faltam = motivo.get(e.get("motivo"), "")
    elif st == "interrompida":
        faltam = f"caiu às {_hora(e.get('vivo_em'))}" if e.get("vivo_em") else ""
    else:
        faltam = ""
    mapas = (_mapas(bid, (e.get("versao"), b.get("versao_grupos")), st == "rodando")
             if distintos else None)
    return {**base, "busca_id": bid, "status": st, "vivo": e.get("vivo"),
            "versao_grupos": b.get("versao_grupos"),
            "dica": DICA_ESTADO.get(st, ""), "quando": _quando(st, e, b),
            "criterio": crit, "sigla": SIGLA_META.get(crit, crit),
            "minimo": cfg.get("minimo", 400),
            "testes": _milhar(distintos), "de_txt": de_txt, "barra": barra,
            "decorrido": _hm(e.get("decorrido_s") or b.get("duracao_s")),
            "rotulo_tempo": "Duração" if st == "concluida" else "Decorrido",
            "faltam": faltam, "historico": e.get("historico_nichos") or b.get("historico") or [],
            "espaco": {"itens": _itens_espaco(cfg.get("estrategia", estrategia),
                                              cfg.get("simbolo", simbolo),
                                              (cfg.get("espaco") or {}).get("faixas") or {}),
                       "fixos": _fixos(perfil.__class__(**cfg["perfil_base"]), moeda)
                       if cfg.get("perfil_base") else _fixos(perfil, moeda),
                       "travado": True},
            "controle": {k: (e.get("controle") or {}).get(k)
                         for k in ("nucleos", "parar_as", "parar_as_ligado", "limite")},
            "mapas": mapas, "legendas": projecao.CORES}


# ------------------------------------------------------------ ações
def _config(acao: dict, estrategia, simbolo, de, ate, wf, perfil) -> dict:
    esp = Espaco(estrategia, simbolo, fechamento=perfil.fechamento,
                 faixas=acao.get("faixas") or {})
    return {"simbolo": simbolo, "estrategia": estrategia, "espaco": esp.para_json(),
            "perfil_base": perfil.to_config(),
            "de": f"{str(de)[:10]}T00:00:00" if de else None,
            "ate": f"{str(ate)[:10]}T23:59:59" if ate else None,
            "wf_config": wf, "minimo": int(acao.get("minimo") or 400),
            "criterio": acao.get("criterio") or "fr", "semente": 0}


def atender(acao: dict, sel, estrategia, simbolo, de, ate, wf, perfil):
    """Uma ação da tela. Devolve (nova seleção, aviso)."""
    a, bid = acao.get("acao"), acao.get("id")
    try:
        if a == "iniciar":
            erro = ativo_mod.janela_valida(perfil.entrada_inicio, perfil.entrada_fim,
                                           ativo_mod.ficha(simbolo), perfil.fechamento)
            if erro:
                return no_update, erro
            novo = controle.iniciar(
                _config(acao, estrategia, simbolo, de, ate, wf, perfil),
                nucleos=int(acao.get("nucleos") or 4),
                parar_as=acao.get("parar_as") or "08:30",
                parar_as_ligado=bool(acao.get("parar_as_ligado")),
                limite=acao.get("limite") or None)
            return novo, ""
        if a == "pausar":
            controle.pausar(bid)
        elif a == "continuar":
            controle.continuar(bid)
        elif a == "parar":
            controle.parar(bid)
        elif a == "ajustar":
            controle.ajustar(bid, **{k: v for k, v in (acao.get("campos") or {}).items()
                                     if k in ("nucleos", "parar_as", "parar_as_ligado",
                                              "limite")})
        elif a == "nova":
            return "nova", ""
        elif a == "abrir":
            return bid, ""
        elif a == "excluir":
            controle.excluir(bid)
            return (None if sel == bid else no_update), f"Busca #{bid} excluída"
    except (controle.BuscaJaRodando, controle.BuscaViva, ValueError) as erro:
        return no_update, str(erro)
    return no_update, ""


def register(app):
    # os dados vão ao desenho do layout B (ui/assets/busca.js); o Output é
    # um atributo inofensivo — o JS devolve sempre no_update
    app.clientside_callback(
        """function (d) { if (window.buscaTela) window.buscaTela.dados(d);
                          return window.dash_clientside.no_update; }""",
        Output("busca-raiz", "title"), Input("busca-dados", "data"))
    app.clientside_callback(
        """function (d) { if (window.buscaTela) window.buscaTela.detalhe(d);
                          return window.dash_clientside.no_update; }""",
        Output("busca-raiz", "lang"), Input("busca-detalhe", "data"))

    @app.callback(
        Output("busca-dados", "data"),
        Input("busca-relogio", "n_intervals"), Input("busca-feito", "data"),
        Input("busca-sel", "data"), Input("modo", "value"),
        Input("mine-subtela", "value"), Input("estrategia", "value"),
        Input("ativo", "value"),
        State({"type": "val", "p": ALL}, "value"), State({"type": "val", "p": ALL}, "id"),
        *[State(cid, prop) for cid, prop in MENU_PERFIL],
    )
    def atualizar(*args):
        if not _ATUALIZANDO.acquire(blocking=False):
            return no_update             # a anterior ainda está montando
        try:
            return _atualizar(*args)
        finally:
            _ATUALIZANDO.release()

    def _atualizar(_n, feito, sel, qual, subtela, estrategia, ativo, valores, ids_val, *menu):
        if qual != "mineracao" or subtela != "busca":
            return no_update
        simbolo = _simbolo(ativo)
        estrategia = estrategia or registry.nome_atual()
        perfil = perfil_da_busca({i["p"]: v for i, v in zip(ids_val, valores)},
                                 {cid: v for (cid, _p), v in zip(MENU_PERFIL, menu)})
        try:
            d = dados_da_tela(sel, estrategia, simbolo, perfil)
        except banco.BancoOcupado as erro:
            print(f"busca: banco ocupado, tela mantida ({erro})", flush=True)
            return no_update
        d["aviso"] = (feito or {}).get("aviso", "")
        d["feito"] = (feito or {}).get("n")
        # Sempre manda, com a assinatura; quem descarta o repetido é o
        # navegador. Descartar aqui ("igual à última que mandei") prendia a
        # tela: uma resposta velha que chegasse por último ficava para sempre.
        d["assinatura"] = str(hash(repr(sorted((k, repr(v)) for k, v in d.items()))))
        return _json_seguro(d)

    @app.callback(
        Output("busca-sel", "data"), Output("busca-feito", "data"),
        Input("busca-acao", "data"),
        State("busca-sel", "data"), State("estrategia", "value"), State("ativo", "value"),
        State("d-de", "date"), State("d-ate", "date"),
        State("wf-treino", "value"), State("wf-teste", "value"),
        State("wf-passo", "value"), State("wf-holdout", "value"),
        State({"type": "val", "p": ALL}, "value"), State({"type": "val", "p": ALL}, "id"),
        *[State(cid, prop) for cid, prop in MENU_PERFIL],
        prevent_initial_call=True,
    )
    def agir(acao, sel, estrategia, ativo, de, ate, treino, teste, passo, holdout,
             valores, ids_val, *menu):
        if not acao:
            return no_update, no_update
        perfil = perfil_da_busca({i["p"]: v for i, v in zip(ids_val, valores)},
                                 {cid: v for (cid, _p), v in zip(MENU_PERFIL, menu)})
        wf = {"treino_meses": treino or 12, "teste_meses": teste or 3,
              "passo_meses": passo or 3, "holdout_meses": holdout or 0}
        novo, aviso = atender(acao, sel, estrategia or registry.nome_atual(),
                              _simbolo(ativo), de, ate, wf, perfil)
        return novo, {"n": time.time(), "aviso": aviso}

    @app.callback(
        Output("busca-detalhe", "data"),
        Input("busca-pedido", "data"),
        prevent_initial_call=True,
    )
    def pedir_detalhe(pedido):
        if not pedido or not pedido.get("casa"):
            return no_update
        try:
            d = detalhe.detalhe(int(pedido["id"]), pedido["casa"])
        except (ValueError, banco.BancoOcupado) as erro:
            return {"casa": pedido["casa"], "erro": str(erro), "n": pedido.get("n")}
        return _json_seguro({**d, "n": pedido.get("n")})

    # -------------------------------------------- abrir no Backtest / minerar
    @app.callback(
        Output({"type": "val", "p": ALL}, "value", allow_duplicate=True),
        Output({"type": "opt-on", "p": ALL}, "value", allow_duplicate=True),
        Output({"type": "opt", "p": ALL, "k": ALL}, "value", allow_duplicate=True),
        *[Output(cid, prop, allow_duplicate=True) for cid, prop in MENU_PERFIL],
        Output("d-de", "date", allow_duplicate=True),
        Output("d-ate", "date", allow_duplicate=True),
        Output("excluir-holdout", "value", allow_duplicate=True),
        Output("btn-run", "n_clicks", allow_duplicate=True),
        Output("mine-subtela", "value", allow_duplicate=True),
        Output("store-combinacao", "data", allow_duplicate=True),
        Input("busca-ir", "data"),
        State({"type": "val", "p": ALL}, "id"), State({"type": "val", "p": ALL}, "value"),
        State({"type": "opt-on", "p": ALL}, "id"), State({"type": "opt-on", "p": ALL}, "value"),
        State({"type": "opt", "p": ALL, "k": ALL}, "id"),
        State({"type": "opt", "p": ALL, "k": ALL}, "value"),
        State("btn-run", "n_clicks"),
        State("estrategia", "value"), State("ativo", "value"),
        *[State(cid, prop) for cid, prop in MENU_COMBINACAO],
        prevent_initial_call=True,
    )
    def ir(pedido, ids_val, vals, ids_on, ons, ids_opt, opts, n_run, estrategia,
           ativo, *menu):
        nada = (no_update,) * (9 + len(MENU_PERFIL))
        if not pedido or not pedido.get("casa"):
            return nada
        bid, casa = int(pedido["id"]), pedido["casa"]
        try:
            cfg = (banco.ler_busca(bid) or {}).get("config") or {}
            # números de uma estratégia ou ativo nunca vão para o menu de outro
            if (cfg.get("estrategia"), cfg.get("simbolo")) != \
                    (estrategia or registry.nome_atual(), _simbolo(ativo)):
                return nada
            if pedido.get("acao") == "regiao":
                return _ir_regiao(detalhe.regiao_para_varredura(bid, casa), cfg,
                                  ids_val, vals, ids_on, ons, ids_opt, opts)
            return _ir_backtest(detalhe.campeao_para_backtest(bid, casa), bid,
                                ids_val, vals, ids_on, ons, ids_opt, opts, n_run,
                                {cid: v for (cid, _p), v in zip(MENU_COMBINACAO, menu)})
        except (banco.BancoOcupado, ValueError) as erro:
            print(f"busca: não deu para abrir a casa {casa}: {erro}", flush=True)
            return nada


def _menu_saida(m: dict) -> list:
    """Os campos de `MENU_PERFIL` na ordem dos Outputs (no_update no que
    `m` não traz)."""
    return [m.get(cid, no_update) for cid, _p in MENU_PERFIL]


def _data(v):
    return str(v)[:10] if v else no_update


def _ir_backtest(cb, bid, ids_val, vals, ids_on, ons, ids_opt, opts, n_run,
                 menu: dict | None = None):
    """Abre o campeão no Backtest com o perfil INTEIRO da busca: tempo,
    janela, dias, direção, stop e alvo do campeão e os fixos com que a busca
    rodou (custos, ADX, limites, proteções, período) — o menu pode ter mudado
    desde o início. O corte do holdout vai junto (`corte`): o Backtest o
    prefere ao da Varredura na memória."""
    m, val_perfil = menu_do_perfil(cb["perfil"])
    novos = {**val_perfil, **cb["params"]}
    val = [novos.get(i["p"], v) for i, v in zip(ids_val, vals)]
    escritos = {**m, "d-de": _data(cb["de"]), "d-ate": _data(cb["ate"])}
    # a foto do menu DEPOIS desta escrita (o menu inteiro, como o clique na
    # Varredura): sem os demais campos, a linha nasceria "editado"
    store = {"origem": "busca", "n": bid, "params": cb["params"],
             "corte": cb["fim_otimizacao"],
             "menu": _menu_atual(ids_val, val, ["on"],
                                 {**(menu or {}), **{k: v for k, v in escritos.items()
                                                     if v is not no_update}})}
    return (val, [no_update] * len(ids_on), [no_update] * len(ids_opt),
            *_menu_saida(m), escritos["d-de"], escritos["d-ate"], ["on"],
            (n_run or 0) + 1, "backtest", store)


def _ir_regiao(r, cfg, ids_val, vals, ids_on, ons, ids_opt, opts):
    """Minerar a região: as faixas do grupo nos campos da Varredura, sobre o
    mesmo período e os mesmos fixos com que a busca rodou. Campo fora da
    região sai do "minerar" (senão uma marca velha varreria o que a busca
    nunca variou). A combinação aberta no Backtest é esquecida: o corte
    dela não vale para a mineração nova."""
    campos = r["campos"]
    m, val_perfil = menu_do_perfil(cfg.get("perfil_base") or {}) \
        if cfg.get("perfil_base") else ({}, {})
    m.update({"e-timeframe": r["timeframe"], "e-ent-ini": r["entrada_inicio"],
              "e-ent-fim": r["entrada_fim"], "e-dias": r["dias_semana"],
              "e-direcao": r["direcao"], "e-stop-tipo": r["stop_tipo"],
              "e-alvo-tipo": r["alvo_tipo"]})
    novos = {**val_perfil, **{k: f["valor"] for k, f in campos.items()}}
    val = [novos.get(i["p"], v) for i, v in zip(ids_val, vals)]
    on = [["on"] if campos.get(i["p"], {}).get("on") else [] for i in ids_on]
    opt = [campos[i["p"]].get(i["k"], o) if i["p"] in campos else o
           for i, o in zip(ids_opt, opts)]
    return (val, on, opt, *_menu_saida(m), _data(cfg.get("de")), _data(cfg.get("ate")),
            no_update, no_update, "varredura", None)
