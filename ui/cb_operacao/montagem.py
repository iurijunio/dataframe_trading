"""Operação: montagem do bloco a partir do papel e da demo."""
from __future__ import annotations

from datetime import datetime, timedelta

from dash import html

from core import papel_leitura as PL

from .. import data as D
from ..callbacks_pregao import juntar
from ..components import charts
from ..components import operacao_panel as OP

from .dados import SIMBOLO, _chamados_de, _ler


def montar(pid, armado, filtro_atual, curva_atual) -> tuple:
    """As partes da tela que leem o banco por portfólio. Treze saídas, na
    ordem do callback `desenhar_op`."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)

    def ler(con):
        pfs = PL.portfolios_com_papel(con)
        pf = next((p for p in pfs if p["portfolio_id"] == pid), None)
        if pf is None:
            return pfs, None, None, None, None, None, None, None, None, None, \
                None, None, None
        res = PL.resumo(con, pid, dia)
        vs = PL.variantes(con, pid, dia)
        ops = PL.operacoes_do_dia(con, pid, dia)
        alertas = PL.alertas(con, pid, dia)
        # o mesmo `dia` dos indicadores: antes da abertura a tela mostra o
        # pregão de ontem, e a curva/comparativo de "hoje" (sem pregão,
        # talvez com outro plano) desmentiriam o topo
        comp = PL.comparativo(con, pid, dia=dia)
        c_pf = PL.curva_vs_esperado(con, pid, dia=dia)
        faixas = [PL.curva_vs_esperado(con, pid, v["ligacao_id"],
                                       dia=dia)["faixa_atual"]
                  for v in vs]
        demo = (res.get("contas") or {}).get("demo")
        envio = PL.envio_da_conta(con, demo["conta_id"]) if demo else None
        # a conta real: o comparativo dela (coluna Real) e o Envio da chave
        real_c = (res.get("contas") or {}).get("real")
        comp_real = PL.comparativo(con, pid, dia=dia, origem="real")
        envio_real = PL.envio_da_conta(con, real_c["conta_id"]) if real_c else None
        # as operações de hoje e o total desde o plano, por conta: o painel de
        # variantes em partes (REAL e DEMO) mostra o resultado de cada uma
        contas = {origem: (PL.operacoes_demo(con, pid, dia, origem=origem),
                           PL.total_por_ligacao(con, pid, dia, origem))
                  for origem in ("demo", "real")}
        return (pfs, pf, res, vs, ops, alertas, comp, c_pf, faixas, envio,
                comp_real, envio_real, contas)

    (pfs, pf, res, vs, ops, alertas, comp, c_pf, faixas, envio,
     comp_real, envio_real, contas) = _ler(ler)
    if pf is None:
        msg = ("nenhum portfólio ainda — crie um na tela Portfólio e ligue em "
               "Ao vivo › Estratégias" if not pfs else "escolha um portfólio")
        vazio = [html.P(msg, className="av-vazio op-vazio")]
        return ([], [], vazio, [], [], [], [], [], [], _opcoes_filtro([]),
                "todas", [], None)

    ordens = (estado or {}).get("ordens") or {}
    cab = OP.cabecalho(pf, res, contrato=ordens.get("contrato_dia")
                       or ordens.get("contrato"), dia=dia)
    demo = (res.get("contas") or {}).get("demo")
    real_c = (res.get("contas") or {}).get("real")
    botoes = OP.botoes_portfolio(pf, armado, conta_id=demo and demo["conta_id"],
                                 envio=envio,
                                 real_id=real_c and real_c["conta_id"],
                                 envio_real=envio_real)
    nomes = {v["ligacao_id"]: v["nome"] for v in vs}
    # contratos e fase vão junto: o editor do ✎ abre sem reler o banco
    vars_ = [{"ligacao_id": v["ligacao_id"], "nome": v["nome"], "cor": v["cor"],
              "contratos": v.get("contratos"),
              "contratos_demo": v.get("contratos_demo"),
              "contratos_real": v.get("contratos_real"), "fase": v.get("fase")}
             for v in vs]
    filtro = filtro_atual if filtro_atual in [str(l) for l in nomes] else "todas"
    curva = curva_atual if curva_atual in nomes else (vs[0]["ligacao_id"]
                                                      if vs else None)
    ligs = [v["ligacao_id"] for v in vs]
    estat = {origem: OP.estatisticas(ops_c, tot_c, ligs)
             for origem, (ops_c, tot_c) in contas.items()}
    if not vs:
        kpis = [OP._SEM_VARIANTES]
    else:
        esperado = {"diferenca": c_pf.get("diferenca_mediana"),
                    "faixas": faixas, "aviso": c_pf.get("aviso")}
        kpis = OP.kpis(res, ops, esperado, nomes)
    return (cab, botoes, kpis,
            OP.cabecalho_colunas_conta() if vs else [],
            OP.cartoes_por_conta(vs, armado, estat),
            OP.risco_dia(res) if vs else [],
            OP.lista_alertas(alertas, nomes),
            OP.tabela_comparativo({**comp, "real": (comp_real or {}).get("demo")}),
            vars_,
            _opcoes_filtro(vars_), filtro,
            [{"label": v["nome"], "value": v["ligacao_id"]} for v in vars_],
            curva)


def juntar_demo(ops: list[dict], demo: list[dict],
                chave: str = "demo") -> list[dict]:
    """Põe em cada operação do papel o que a conta fez nela (mesma chave
    `(ligacao_id, entry_ts)`): contratos executados e a derrapagem além do
    plano por ponta — as colunas "Papel × demo" e "Papel × real" da tabela
    do papel. `chave` diz em que campo a operação da conta vai ("demo" ou
    "real")."""
    por = {(o["ligacao_id"], o["entry_ts"]): o for o in demo
           if o["situacao"] != "seria_enviada"}
    out = []
    for o in ops:
        d = por.get((o["ligacao_id"], o["entry_ts"]))
        out.append({**o, chave: d} if d else o)
    return out


def ler_curva(pid, lig) -> dict:
    """A curva papel × esperado do pregão que a tela mostra (o mesmo `dia`
    de `montar`); `lig` None é o portfólio inteiro."""
    dia = D.dia_do_pregao(D.estado_captura())
    return _ler(lambda con: PL.curva_vs_esperado(con, pid, lig, dia=dia))


def _opcoes_filtro(vars_):
    # o valor é texto: "todas" e o id da ligação convivem no mesmo campo
    return ([{"label": "Todas as variantes", "value": "todas"}]
            + [{"label": v["nome"], "value": str(v["ligacao_id"])}
               for v in vars_])


def serie_do_dia(pid, tf, ocultas, agora) -> tuple[list, dict | None]:
    """(series, último candle do banco) do gráfico do dia, com os
    marcadores do papel."""
    estado = D.estado_captura()
    dia = D.dia_do_pregao(estado)
    inicio = datetime.combine(dia, datetime.min.time())
    dados = D.candles(SIMBOLO, inicio, inicio + timedelta(hours=23, minutes=59),
                      tf)
    base = dados["candles"][-1] if dados["candles"] else None
    t = OP.tick_operacao(estado, tf, base, agora)
    dados["candles"] = juntar(dados["candles"], t["bar"] if t else None)
    mk, linhas = [], []
    if pid is not None:
        m = _ler(lambda con: PL.marcadores(con, pid, dia))
        mk, linhas = OP.marcadores_tela(m, ocultas, tf)
    return charts.price_series(dados, mk, linhas), base


def _conta_do_chamado(alvo) -> str:
    """A conta de onde vem o ticket de um chamado: "real" só se ele aparece
    nos chamados da real e não nos da demo. O comando "Encerrar posição" vai
    para a pasta dessa conta — uma posição da real nunca vai à pasta da demo."""
    if not isinstance(alvo, int):
        return "demo"
    demo = (D.estado_captura() or {}).get("ordens") or {}
    if any(c.get("ticket") == alvo for c in _chamados_de(demo, "demo")):
        return "demo"
    real = D.estado_real()
    if any(c.get("ticket") == alvo for c in _chamados_de(real, "real")):
        return "real"
    return "demo"
