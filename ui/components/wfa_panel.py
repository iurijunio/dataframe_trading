"""A tela do Walk-Forward: escolher a mineração, rodar, ver a curva.

A curva OOS concatenada é a leitura principal desta aba, e por isso ocupa a
faixa larga — do mesmo jeito que a curva de capital manda no Backtest. Ela é
**trade a trade**: cada ponto é uma operação, e as divisórias verticais
marcam onde a estratégia foi reotimizada.

É a coisa mais próxima de um track record que se constrói do passado: em
nenhum ponto dela o otimizador tinha visto o dado que estava operando.
"""

from __future__ import annotations

import dash_ag_grid as dag
import numpy as np
import plotly.graph_objects as go
from dash import dcc, html

from core import metrics, wfa

from .. import theme as T
from .analytics_charts import BASE, EIXO, TITULO, _vazio
from . import stats_cards as SC
from . import wfa_matriz as WM
from .cartao import brl, card, dica, faixa, inteiro, num
from .ficha import valor as _valor

BRL = {"function": "params.value == null ? '' : params.value.toLocaleString('pt-BR',"
                   "{minimumFractionDigits:2,maximumFractionDigits:2})"}
PCT = {"function": "params.value == null ? '—' : (params.value*100).toLocaleString('pt-BR',"
                   "{maximumFractionDigits:0}) + '%'"}

COLUNAS_STEPS = [
    {"field": "step", "headerName": "Step", "width": 92, "pinned": "left"},
    {"field": "params_txt", "headerName": "parâmetros", "flex": 1,
     "minWidth": 220, "pinned": "left", "cellClass": "col-params"},
    {"field": "is_de", "headerName": "IS início", "width": 120},
    {"field": "is_ate", "headerName": "IS fim", "width": 120},
    {"field": "oos_de", "headerName": "OOS início", "width": 124},
    {"field": "oos_ate", "headerName": "OOS fim", "width": 120},
    {"field": "is_lucro", "headerName": "IS lucro", "width": 118,
     "type": "numericColumn", "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "oos_lucro", "headerName": "OOS lucro", "width": 122,
     "type": "numericColumn", "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "oos_trades", "headerName": "trades", "width": 86,
     "type": "numericColumn"},
    {"field": "wfe", "headerName": "WFE", "width": 96,
     "type": "numericColumn", "valueFormatter": PCT,
     "cellClassRules": {"pos": "params.value >= 0.7",
                        "neg": "params.value != null && params.value < 0"}},
    {"field": "nota", "headerName": "", "width": 150,
     "cellClassRules": {"neg": "params.value == 'fora do mercado'",
                        "warn": "params.value == 'poucos trades no IS'"}},
]


COLUNAS_TRADES = [
    {"field": "n", "headerName": "#", "width": 74, "pinned": "left"},
    {"field": "quando", "headerName": "entrada", "width": 168, "pinned": "left"},
    {"field": "saida", "headerName": "saída", "width": 168},
    {"field": "step", "headerName": "janela", "width": 100,
     "headerTooltip": "qual janela escolheu o parâmetro deste trade"},
    {"field": "resultado", "headerName": "resultado", "width": 132,
     "type": "numericColumn", "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "custo", "headerName": "custo", "width": 110,
     "type": "numericColumn", "valueFormatter": BRL},
    {"field": "capital", "headerName": "capital", "width": 150,
     "type": "numericColumn", "valueFormatter": BRL},
]


def linhas_trades(ts, liquido, steps, capital: float,
                  saida=None, custo=None) -> list[dict]:
    """A auditoria linha a linha. Limitada às 3.000 primeiras: além disso a
    tabela não é mais auditoria, é despejo — e o navegador engasga."""
    if not len(ts):
        return []
    n = min(len(ts), 3000)
    acum = capital + np.cumsum(liquido)
    saida = ts if saida is None else saida
    custo = np.zeros(len(ts)) if custo is None else custo
    return [
        {"n": i + 1, "quando": str(ts[i])[:16].replace("T", " "),
         "saida": str(saida[i])[:16].replace("T", " "),
         "step": f"Step {steps[i]}", "resultado": round(float(liquido[i]), 2),
         "custo": round(float(custo[i]), 2),
         "capital": round(float(acum[i]), 2)}
        for i in range(n)
    ]


def _br(d) -> str:
    p = str(d)[:10].split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else str(d)[:10]


def linhas_steps(passos) -> list[dict]:
    fora = []
    for p in passos:
        j = p.janela
        fora.append({
            "step": "DEPLOY" if j.deploy else f"Step {j.step}",
            "params_txt": (" · ".join(f"{k}={_valor(v)}"
                                      for k, v in p.params.items())
                           if p.params else "—"),
            "is_de": _br(j.is_de), "is_ate": _br(j.is_ate),
            "oos_de": _br(j.oos_de), "oos_ate": _br(j.oos_ate),
            "is_lucro": round(p.is_.get("lucro", 0.0), 2) if p.is_ else None,
            "oos_lucro": (round(p.oos["lucro"], 2) if p.oos else None),
            "oos_trades": p.oos.get("trades") if p.oos else None,
            "wfe": p.wfe_lucro,
            "nota": ("o OOS é o futuro" if j.deploy
                     else "fora do mercado" if p.fora_do_mercado
                     else "poucos trades no IS" if p.poucos_trades else ""),
        })
    return fora


# ------------------------------------------------------------------- curva
def curva(ts, liquido, steps, passos, capital: float,
          fixas=None, holdout_de=None) -> go.Figure:
    """A curva de capital **trade a trade**, só com os pedaços OOS.

    Cada ponto é uma operação. As divisórias verticais marcam onde a
    estratégia foi reotimizada — dá para ver se a virada de parâmetro veio
    depois de um tranco ou no meio de uma subida.

    A escada começa no capital inicial de propósito: sem esse ponto, a
    primeira sequência perdedora ficaria escondida abaixo do eixo e o
    drawdown de largada não apareceria.

    `holdout_de`, quando o holdout está estendido, pinta de amarelo o trecho
    que começa no corte: são os meses que nenhuma combinação da mineração
    enxergou, e é ali que a curva mais se parece com o mercado de amanhã.
    """
    if not len(ts):
        return _vazio("Rode o walk-forward para ver a curva.")

    import numpy as np

    eq = capital + np.cumsum(liquido)
    x = np.concatenate(([ts[0] - np.timedelta64(1, "D")], ts))
    y = np.concatenate(([capital], eq))
    pico = np.maximum.accumulate(y)

    fig = go.Figure([
        go.Scatter(x=x, y=pico, mode="lines", line=dict(width=0),
                   hoverinfo="skip", showlegend=False),
        go.Scatter(x=x, y=y, mode="lines", name="capital",
                   line=dict(color=T.ACCENT, width=1.6),
                   fill="tonexty", fillcolor="rgba(255,74,110,.10)",
                   customdata=np.concatenate(([0], steps)),
                   hovertemplate="%{x|%d/%m/%Y}<br>R$ %{y:,.2f}"
                                 "<br>step %{customdata}<extra></extra>"),
    ])
    pct_fixas = None
    if fixas and fixas.get("quantis"):
        # A faixa das combinações FIXAS da região, atrás da curva: p10–p90
        # clara, p25–p75 mais escura, mediana pontilhada. Se a curva do WFA
        # passeia dentro dela, reotimizar não acrescentou nada além de pegar
        # uma combinação qualquer da região.
        dq, qd = fixas["dias"], fixas["quantis"]
        cinza = "rgba(132,148,179,{})"
        for baixo, alto, alfa in ((10, 90, .10), (25, 75, .16)):
            fig.add_trace(go.Scatter(x=dq, y=qd[baixo], mode="lines",
                                     line=dict(width=0), hoverinfo="skip",
                                     showlegend=False))
            fig.add_trace(go.Scatter(x=dq, y=qd[alto], mode="lines",
                                     line=dict(width=0), fill="tonexty",
                                     fillcolor=cinza.format(alfa),
                                     hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(
            x=dq, y=qd[50], mode="lines", name="mediana das fixas",
            line=dict(color=T.MUTED, width=1, dash="dot"),
            hovertemplate="mediana das fixas<br>%{x|%d/%m/%Y}<br>R$ %{y:,.2f}"
                          "<extra></extra>"))
        # as faixas vão para trás da curva do WFA e do drawdown
        fig.data = fig.data[-5:] + fig.data[:-5]
        pct_fixas = wfa.percentil_na_faixa(fixas, float(np.sum(liquido)))
    fig.add_hline(y=capital, line=dict(color=T.LINE, width=1, dash="dot"))

    nota_holdout = None
    if holdout_de is not None:
        corte = np.datetime64(holdout_de, "s")
        dentro = x >= corte
        if dentro.any():
            # faixa de fundo + a curva recolorida por cima, a partir do último
            # ponto ANTES do corte, para a linha não abrir um buraco
            i0 = max(int(np.argmax(dentro)) - 1, 0)
            fig.add_vrect(x0=corte, x1=x[-1], fillcolor="rgba(255,201,60,.07)",
                          line_width=0, layer="below")
            fig.add_vline(x=corte, line=dict(color=T.WARN, width=1.2, dash="dash"))
            nota_holdout = dict(
                x=corte, y=1, xref="x", yref="paper", xanchor="left",
                yanchor="top", showarrow=False,
                text=" HOLDOUT",
                font=dict(color=T.WARN, size=10))
            fig.add_trace(go.Scatter(
                x=x[i0:], y=y[i0:], mode="lines", name="holdout",
                line=dict(color=T.WARN, width=2),
                hovertemplate="holdout<br>%{x|%d/%m/%Y}<br>R$ %{y:,.2f}"
                              "<extra></extra>"))

    # uma divisória por reotimização
    for p in passos:
        if p.janela.deploy or p.fora_do_mercado:
            continue
        fig.add_vline(x=p.janela.oos_de,
                      line=dict(color=T.LINE_SOFT, width=1))

    fim = float(y[-1])
    # sem título próprio: o painel já tem cabeçalho, e os dois se
    # atropelavam na mesma faixa de pixels
    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=10, t=30, b=10)},
        xaxis=dict(**EIXO), yaxis=dict(**EIXO, title=dict(text="R$", font=dict(size=10))),
        annotations=[dict(
            text=(f"{len(ts)} operações · capital {brl(capital)} → "
                  f"<span style='color:"
                  f"{T.POS if fim >= capital else T.NEG}'>{brl(fim)}</span>"
                  + (" · faixa: combinações fixas" if pct_fixas is not None else "")),
            showarrow=False, xref="paper", yref="paper", x=0, y=1.07,
            xanchor="left", font=dict(color=T.MUTED, size=10))]
        # entra na MESMA lista: um add_annotation antes deste update_layout
        # era apagado por ele
        + ([nota_holdout] if nota_holdout else [])
        # o percentil, curto, na ponta direita da curva
        + ([dict(x=x[-1], y=fim, xref="x", yref="y", xanchor="left",
                 yanchor="middle", showarrow=False,
                 text=f" p{num(pct_fixas, 0)}",
                 font=dict(color=T.MUTED, size=10))]
           if pct_fixas is not None else []),
    )
    return fig


# ------------------------------------------------------------------- KPIs
# O (?) dos cartões compartilhados com o Backtest, reescrito onde a leitura
# muda. A conta é a mesma; o que muda é que esta curva nunca viu o futuro.
DICAS_OOS = {
    "período": "O trecho que a curva fora da amostra cobre: do início do OOS "
               "da primeira janela ao fim do OOS da última. O IS da primeira "
               "janela fica de fora — ali só se otimizou, nada foi operado.",
    "lucro líquido": "A soma de todos os pedaços fora da amostra, já "
                     "descontado o custo. É o único número de lucro desta "
                     "tela que não teve o otimizador olhando: em cada trecho, "
                     "os parâmetros foram escolhidos só com o dado anterior a "
                     "ele. Compare com o lucro do backtest otimizado no "
                     "período inteiro — a diferença entre os dois é o "
                     "sobreajuste, em reais.",
    "max drawdown": "O maior mergulho da curva fora da amostra, do topo ao "
                    "fundo. É o número mais realista de sofrimento que esta "
                    "plataforma produz, porque a curva dele nunca viu o "
                    "futuro. '% do pico' divide pelo topo alcançado até ali; "
                    "'% do capital', pelo que se depositou. Compare com o "
                    "drawdown do backtest otimizado: se o daqui for muito "
                    "maior, o backtest estava escondendo risco. O portão "
                    "desta plataforma aceita até 1,5× o drawdown do IS.",
    "profit factor": "Quanto se ganhou para cada R$ 1 perdido, fora da "
                     "amostra. Abaixo de 1,0 a estratégia perde dinheiro em "
                     "dado novo, por mais bonito que seja o backtest. De 1,2 "
                     "a 1,6 é o normal de um sistema real de day trade.",
    "win rate": "Percentual de operações vencedoras fora da amostra. Sozinho "
                "não diz nada: leia junto do payoff. O que importa é ele não "
                "despencar em relação ao backtest — se despencar, o gatilho "
                "estava ajustado ao ruído.",
    "expectativa": "Quanto cada operação rendeu, em média, fora da amostra. "
                   "É a expectativa honesta — a do backtest otimizado é "
                   "sempre melhor que a realidade. É ela que tem que cobrir "
                   "o slippage que o backtest não viu.",
    "sharpe": "A mesma conta do Backtest — retorno diário anualizado sobre "
              "a volatilidade diária — feita sobre os pregões da curva fora "
              "da amostra. Acima de 1,0 é bom. Espere um número menor que o "
              "do backtest otimizado; quando ficam próximos, o otimizador "
              "não estava inflando o resultado. O Sortino pune só a "
              "oscilação para baixo.",
    "trades": "Tamanho da amostra fora da amostra. O portão desta plataforma "
              "pede ao menos 300: abaixo disso o WFE e as janelas positivas "
              "ainda podem ser acaso, por melhores que pareçam.",
}


def _positivos_pct(ag: dict) -> float:
    pp = ag.get("periodos_positivos")
    return pp if pp is not None else ag.get("consistencia_lucro", 0.0)


def kpis(passos, ts, liquido, agregado: dict, capital: float,
         custo=None, saida=None) -> html.Div:
    """Os cartões da curva OOS.

    Os de trade (lucro, drawdown, Sharpe…) são os MESMOS do Backtest,
    calculados por `metrics.resumo` sobre os trades fora da amostra — um só
    lugar para a conta, um só desenho. Entre eles entram os que só existem
    aqui: WFE, janelas positivas e lucro por mês de calendário.
    """
    if not len(ts):
        return html.Div(html.P("Rode o walk-forward.", className="empty"),
                        className="cards")

    reais = [p.janela for p in passos if not p.janela.deploy]
    # os pregões das janelas OOS, inclusive os sem trade: é a base do Sharpe
    n_pregoes = sum(wfa.pregoes(j.oos_de, j.oos_ate) for j in reais) or None
    m = metrics.resumo(liquido, custo, ts if saida is None else saida, capital,
                       n_pregoes)
    if reais:
        m["periodo"] = (f"{_br(min(j.oos_de for j in reais))} → "
                        f"{_br(max(j.oos_ate for j in reais))}")
    m["periodo_nota"] = "fora da amostra, janela após janela"
    base = SC.cartoes(m, DICAS_OOS)

    wfe_g = agregado.get("wfe_global")
    med = agregado.get("wfe_mediana")
    proprios = {
        "WFE global": card(
            "WFE global", f"{num(wfe_g * 100, 1)}%" if wfe_g is not None else "—",
            "Walk-Forward Efficiency: o desempenho anualizado FORA da amostra "
            "dividido pelo de DENTRO. Mede quanto da performance otimizada "
            "sobrevive em dado novo. A literatura usa 50% como piso; aqui o "
            "portão é 70%. Acima de 100% o resultado fora da amostra superou "
            "o de dentro — acontece, e costuma significar que a janela de "
            "otimização pegou um período difícil. "
            "É o agregado: soma os OOS e soma os IS antes de dividir, para "
            "que uma janela com IS minúsculo não desequilibre a conta.",
            "pos" if (wfe_g or 0) >= 0.7 else "neg",
            (f"mediana das janelas {num(med * 100, 1)}%" if med is not None
             else "mediana indisponível"), largo=True),
        "semestres positivos": card(
            "semestres positivos",
            f"{num(_positivos_pct(agregado), 1)}%",
            "Percentual dos SEMESTRES CIVIS (jan–jun, jul–dez) da curva fora "
            "da amostra que fecharam no azul. É o teste de repetição: lucrar no "
            "total ganhando em 2 de 8 períodos é ter vivido de um. É por "
            "semestre, e não por janela, para a régua ser a mesma em toda "
            "configuração — uma janela OOS de 3 meses tem poucos trades e "
            "fecha negativa por puro acaso bem mais vezes. Semestre que o OOS "
            "pega pela metade não entra; semestre inteiro fora do mercado não "
            "conta contra. O portão é 70%.",
            "pos" if _positivos_pct(agregado) >= 70 else "neg",
            (f"{inteiro(agregado.get('semestres_positivos', 0))} de "
             f"{inteiro(agregado.get('semestres', 0))} · por janela "
             f"{num(agregado.get('consistencia_lucro', 0), 0)}%"
             if agregado.get("periodos_positivos") is not None
             else f"{inteiro(agregado.get('janelas_operadas', 0))} janelas operadas")),
        "lucro por mês": card(
            "lucro por mês", brl(agregado.get("lucro_mes_oos", 0.0)),
            "O lucro OOS dividido pelos meses de CALENDÁRIO — inclusive os "
            "meses em que nenhuma combinação passou nos critérios e a "
            "estratégia ficou fora do mercado. Esses meses passaram do mesmo "
            "jeito; dividir só pelos meses operados inflaria justamente quem "
            "menos operou.",
            "pos" if agregado.get("lucro_mes_oos", 0) > 0 else "neg",
            f"{num(agregado.get('oos_meses', 0), 0)} meses · "
            f"{inteiro(agregado.get('fora_do_mercado', 0))} fora do mercado"),
    }
    todos = {**base, **proprios}
    # a ordem de leitura: o que só o walk-forward responde vem logo depois
    # do lucro; as métricas de trade, que o Backtest também tem, depois
    ordem = ("período", "lucro líquido", "WFE global", "semestres positivos",
             "max drawdown", "lucro por mês", "profit factor", "win rate",
             "payoff", "expectativa", "fator recuperação", "sharpe", "trades")
    return html.Div([todos[k] for k in ordem if k in todos],
                    className="cards cards-wfa")


# ----------------------------------------------------------------- layout
def progresso() -> html.Div:
    """O estado da varredura, ao lado do botão que a dispara.

    Fica logo abaixo do Executar porque é a resposta a ele: em que fase
    está, quanto falta e, no fim, o que a varredura deixou na memória. Os
    avisos do cálculo (uma janela IS maior que a base, por exemplo) ficam ao
    lado, junto dos avisos de salvar.
    """
    return html.Div([
        html.Div([html.Span(id="wfa-prog-txt", className="wfa-prog-txt"),
                  html.Span(id="wfa-prog-pct", className="wfa-prog-pct"),
                  # fora do texto, que corta com reticências e engolia o (?)
                  dica("A varredura roda cada combinação da mineração UMA vez "
                       "sobre a base inteira e guarda os trades na memória "
                       "(é o número em MB). Cada janela do walk-forward é um "
                       "recorte desse cache — por isso trocar IS, OOS, a "
                       "inteligência ou o holdout responde na hora, sem rodar "
                       "backtest de novo. Combinações que não operaram "
                       "nenhuma vez ficam de fora. No começo, 'iniciando' é "
                       "o tempo de subir os processos, antes do primeiro "
                       "resultado.")],
                 className="wfa-prog-linha"),
        html.Div(html.Div(id="wfa-prog-bar", className="prog-bar"),
                 className="prog wfa-prog-trilho"),
    ], id="wfa-prog", className="wfa-prog ocioso")


def veu(id_, texto) -> html.Div:
    return html.Div([html.Span(className="veu-giro"),
                     html.Span(texto, className="veu-txt")],
                    id=id_, className="veu")


def estado_progresso(e: dict, run_id, teto_mb: float) -> dict:
    """Traduz o estado da varredura no que a barra mostra.

    Função pura, separada do callback, para ser testável sem servidor. As
    fases: ocioso (nada escolhido), varrendo, montando (varredura acabou e a
    tela ainda não desenhou), pronto, erro.
    """
    if e.get("rodando"):
        total, feitos = e.get("total") or 0, e.get("feitos") or 0
        if not total:
            return dict(fase="varrendo", txt="preparando os processos…",
                        pct=0, pct_txt="", ocupado=True,
                        veu="preparando a varredura…")
        if not feitos:
            # no Windows subir os processos (cada um importa o motor e lê a
            # base) leva ~1 s antes do primeiro resultado. "0 de 41" parado
            # nesse tempo parece travamento; dizer o que acontece não parece
            return dict(fase="varrendo",
                        txt=[html.Strong("iniciando "),
                             f"os processos · {inteiro(total)} combinações na fila"],
                        pct=0, pct_txt="", ocupado=True,
                        veu="iniciando a varredura…")
        pct = feitos * 100 / total
        decorrido = max(0.0, (e.get("agora") or 0) - (e.get("inicio") or 0))
        falta = (decorrido / feitos * (total - feitos)) if feitos else None
        resto = f" · falta ~{falta:.0f} s" if falta and falta >= 1 else ""
        return dict(fase="varrendo",
                    txt=[html.Strong("varrendo "),
                         f"{inteiro(feitos)} de {inteiro(total)} combinações{resto}"],
                    pct=pct, pct_txt=f"{pct:.0f}%", ocupado=True,
                    veu=f"varrendo o espaço de busca · {pct:.0f}%")
    if e.get("erro"):
        return dict(fase="erro", txt=e.get("mensagem") or "falhou", pct=100,
                    pct_txt="", ocupado=False, veu=None)
    if e.get("pronto") and e.get("run_id") == run_id and not e.get("entregue"):
        return dict(fase="montando", txt=[html.Strong("montando "), "as janelas…"],
                    pct=100, pct_txt="", ocupado=True, veu="montando as janelas…")
    if e.get("run_id") == run_id and e.get("total"):
        uteis = e.get("uteis", 0)
        if e.get("mb", 0) > teto_mb or not uteis:
            return dict(fase="erro", txt=e.get("mensagem") or "sem trades",
                        pct=100, pct_txt="", ocupado=False, veu=None)
        return dict(
            fase="pronto",
            txt=[html.Strong(f"{inteiro(uteis)} combinações"),
                 f" de {inteiro(e['total'])} · "
                 f"{num(e.get('segundos', 0.0), 1)} s · "
                 f"{num(e.get('mb', 0.0), 1)} MB"],
            pct=100, pct_txt="", ocupado=False, veu=None)
    if not run_id:
        return dict(fase="ocioso", txt="escolha uma mineração salva", pct=0,
                    pct_txt="", ocupado=False, veu=None)
    return dict(fase="ocioso", txt="pronto para executar", pct=0, pct_txt="",
                ocupado=False, veu=None)


def painel():
    """Devolve uma LISTA: quem empilha é o `#painel-wfa`, que carrega a classe
    `modo-bloco`. Um `html.Div` extra aqui virava um filho de largura natural
    dentro do flex e deixava um vazio à direita da tela."""
    def num_(id_, v, minimo=1):
        return dcc.Input(id=id_, type="number", value=v, min=minimo, step=1,
                         className="inp", debounce=0.5)

    return [
        html.Section([
            # Três marcadores de trava, um por dono: a varredura (relógio), as
            # janelas e a matriz (`running=` de cada callback) — quem liga um
            # não desliga o outro. São divs VAZIAS e IRMÃS dos campos, e o
            # CSS trava pelo seletor `~`. Não podem ENVOLVER os campos: trocar
            # a classe de um ancestral re-renderiza o dcc.Input, que reemite o
            # valor, que redispara o cálculo, que troca a classe de novo — um
            # laço que ainda fazia a tela descartar as respostas da barra.
            html.Div(id="wfa-trava-varredura", className="wfa-trava"),
            html.Div(id="wfa-trava-matriz", className="wfa-trava"),
            html.Div(id="wfa-trava-janelas", className="wfa-trava"),
            html.Div([
                html.Div([html.Label("estratégia", className="fld-label"),
                          dcc.Dropdown(id="wfa-estrategia", className="dd",
                                       clearable=False, options=[])],
                         className="fld"),
                html.Div([html.Label("mineração salva", className="fld-label"),
                          dcc.Dropdown(id="wfa-mineracao", className="dd",
                                       placeholder="escolha uma mineração…",
                                       options=[])],
                         className="fld"),
                html.Div([
                    html.Button("Executar", id="btn-wfa", n_clicks=0,
                                className="btn-primary", disabled=True),
                ], className="acoes acoes-run"),
            ], className="wfa-barra"),

            # IS, OOS e inteligência continuam existindo, só não à vista: são
            # o ESTADO da configuração aberta, que vários callbacks leem. Quem
            # os escreve agora é o clique numa linha da matriz (e o
            # walk-forward salvo) — com as abas, escolher pela matriz é mais
            # informado do que digitar um número.
            html.Div([
                html.Div([html.Label(["IS (meses)",
                                      dica("A janela de otimização. Pardo "
                                           "recomenda de 4 a 6 vezes o "
                                           "tamanho do OOS.")],
                                     className="fld-label"),
                          num_("wfa-is", 12)], className="fld fld-num"),
                html.Div([html.Label(["OOS (meses)",
                                      dica("A janela de teste, aplicada logo "
                                           "depois da otimização. O passo é "
                                           "igual a ela: as janelas OOS são "
                                           "contíguas e não se sobrepõem, "
                                           "senão o mesmo trade entraria duas "
                                           "vezes na curva.")],
                                     className="fld-label"),
                          num_("wfa-oos", 6)], className="fld fld-num"),
                html.Div([html.Label(["inteligência de seleção",
                                      dica("Quem escolhe a combinação "
                                           "vencedora dentro de cada janela "
                                           "IS. Todas rodam depois dos "
                                           "critérios de aceite; se nenhuma "
                                           "combinação passa, a estratégia "
                                           "fica fora do mercado naquele OOS.")],
                                     className="fld-label"),
                          dcc.Dropdown(id="wfa-inteligencia", className="dd",
                                       value="centroide_mediana", clearable=False,
                                       options=[{"label": r, "value": v}
                                                for r, v in wfa.INTELIGENCIAS])],
                         className="fld"),
            ], style={"display": "none"}),

            html.Div([
                dcc.Input(id="wfa-nome", type="text", className="inp",
                          placeholder="nome deste walk-forward", debounce=0.4),
                html.Button("Salvar", id="btn-wfa-salvar", n_clicks=0,
                            className="btn-ghost btn-salvar", disabled=True),
                dcc.Dropdown(id="wfa-salvos", className="dd dd-carregar",
                             placeholder="walk-forwards salvos…", options=[]),
                html.Button("Excluir", id="btn-wfa-excluir", n_clicks=0,
                            className="btn-ghost btn-excluir", disabled=True),
                html.Div([html.Span(id="wfa-aviso", className="prog-txt"),
                          html.Span(id="wfa-info", className="wfa-prog-aviso")],
                         className="wfa-avisos"),
                # embaixo do Executar, na altura dos campos desta linha
                progresso(),
            ], className="wfa-guardar"),
        ], className="barra-acoes barra-wfa"),

        WM.secao(
            dag.AgGrid(
                id="grid-wfa-matriz", columnDefs=WM.colunas(WM.CONSENSO),
                rowData=[], className="ag-theme-alpine-dark grid-trades grid-matriz",
                # o id da linha é a configuração: trocar as linhas (ao mudar
                # IS/OOS, a marca "atual" muda) não perde a seleção
                getRowId="params.data.config",
                rowClassRules=WM.REGRAS_LINHA,
                dashGridOptions={
                    "rowSelection": "single", "animateRows": False,
                    "rowHeight": 30, "headerHeight": 34,
                    "suppressCellFocus": True,
                    "localeText": {"noRowsToShow":
                                   "Escolha uma mineração e clique em Executar."},
                },
                defaultColDef={"sortable": True, "resizable": True},
                style={"height": "100%", "width": "100%"},
                # as colunas esticam até a borda: sem isto sobrava uma faixa
                # vazia à direita em tela larga
                columnSize="responsiveSizeToFit",
            ),
            # três véus, um por dono: a varredura (relógio), as janelas e a
            # matriz (cada uma pelo `running=` do seu callback). Com um véu
            # só, o callback que terminasse primeiro o apagaria com o outro
            # ainda calculando.
            [veu("wfa-veu", html.Span(id="wfa-veu-txt")),
             veu("wfa-veu-janelas", "montando as janelas…"),
             veu("wfa-veu-matriz", "calculando as 7 inteligências × 12 "
                                   "configurações…")],
            cabeca_extra=html.Div([
                # na matriz, e não na curva: ligar recalcula as sete
                    # inteligências × 12 configurações, e é aqui que se decide
                    html.Div([
                        dcc.Checklist(
                            id="wfa-holdout", value=[], className="chk",
                            options=[{"label": "estender ao holdout",
                                      "value": "on"}]),
                        dica("Liga e desliga os meses lacrados do fim da base. "
                             "DESLIGADO, o walk-forward para no corte do holdout — "
                             "o mesmo período em que a mineração otimizou, e por "
                             "isso comparável com ela. LIGADO, ele avança sobre os "
                             "meses que NENHUMA combinação jamais enxergou: é o "
                             "dado mais parecido com o mercado de amanhã que "
                             "existe aqui dentro. "
                             "Ligar não gasta o holdout como um backtest gastaria: "
                             "o walk-forward nunca otimiza sobre dado posterior à "
                             "janela IS de cada passo, então esses meses só entram "
                             "como resultado — nunca como escolha."),
                    ], className="fld-chk tool-right"),
            ], className="mz-holdout")),

        html.Section([
            html.Div([
                html.H2("Curva fora da amostra", className="panel-title hero"),
                html.Span(dica(
                    "O capital operação a operação, só com os trechos FORA da "
                    "amostra de cada janela, colados em ordem. Em nenhum ponto "
                    "o otimizador tinha visto o dado que estava operando. As "
                    "divisórias verticais marcam cada reotimização; a área "
                    "vermelha é o afastamento do topo (drawdown). A FAIXA "
                    "cinza atrás é o que TODAS as combinações da mineração "
                    "teriam feito sem reotimizar, no mesmo período: a parte "
                    "clara vai do 10º ao 90º percentil, a escura do 25º ao "
                    "75º, e a pontilhada é a mediana. O 'pNN' na ponta diz "
                    "quantos por cento das combinações fixas terminaram "
                    "abaixo do walk-forward — p50 é empate com a combinação "
                    "típica; reotimizar só está acrescentando algo se a curva "
                    "sai por cima da faixa. Com o holdout estendido, o trecho "
                    "amarelo são os meses que nenhuma combinação viu."),
                    className="panel-note"),
            ], className="panel-head"),
            dcc.Graph(id="g-wfa-curva", figure=_vazio(
                "Escolha uma mineração salva e clique em Executar."),
                className="graph", config={"displayModeBar": False,
                                           "responsive": True}),
        ], className="panel panel-equity"),

        html.Div(id="wfa-kpis"),

        html.Section([
            html.Div([html.H2("Janelas e vencedora", className="panel-title"),
                      html.Span(id="wfa-resumo", className="panel-note")],
                     className="panel-head"),
            dcc.Tabs(
                id="abas-wfa", value="janelas", className="abas",
                parent_className="abas-wrap", content_className="abas-corpo",
                children=[
                    dcc.Tab(
                        label="Janelas", value="janelas", className="aba",
                        selected_className="aba-on",
                        children=html.Div([
                            html.Div([
                                html.Span(["IS lucro", dica(
                                    "Lucro da combinação escolhida DENTRO da "
                                    "janela de otimização. É otimista por "
                                    "construção: foi com ele que se escolheu.")],
                                    className="mz-item"),
                                html.Span(["OOS lucro", dica(
                                    "Lucro da mesma combinação nos meses "
                                    "SEGUINTES, que ela não viu. É o que se "
                                    "teria ganho de verdade naquela janela.")],
                                    className="mz-item"),
                                html.Span(["WFE", dica(
                                    "OOS anualizado ÷ IS anualizado desta "
                                    "janela. Por janela ele oscila muito "
                                    "(poucos meses, poucos trades); o número "
                                    "que decide é o WFE global dos cartões.")],
                                    className="mz-item"),
                                html.Span(["trades", dica(
                                    "Operações no OOS da janela. Abaixo de ~30 "
                                    "o lucro da janela é mais sorte que edge.")],
                                    className="mz-item"),
                                html.Span(["fora do mercado", dica(
                                    "Nenhuma combinação passou nos critérios "
                                    "de aceite desta janela IS: a estratégia "
                                    "não teria operado no OOS seguinte.")],
                                    className="mz-item"),
                            ], className="mz-sobre"),
                            dag.AgGrid(
                                id="grid-wfa-steps", columnDefs=COLUNAS_STEPS,
                                rowData=[],
                                dashGridOptions={
                                    "rowSelection": "single",
                                    "animateRows": False, "rowHeight": 30,
                                    "headerHeight": 34,
                                    "suppressCellFocus": True,
                                    "localeText": {
                                        "noRowsToShow": "Rode o walk-forward."},
                                },
                                defaultColDef={"sortable": False,
                                               "resizable": True},
                                style={"height": "100%", "width": "100%"},
                                className="ag-theme-alpine-dark grid-trades grid-janelas",
                            ),
                        ], className="aba-corpo aba-janelas")),
                    # A vencedora é vista AQUI dentro, e só pelo que ela É:
                    # os parâmetros e onde caíram na faixa minerada. O
                    # backtest dela no período inteiro saiu — é uma curva
                    # otimizada, e a que vale é a fora da amostra, acima.
                    dcc.Tab(
                        label="Parâmetros da vencedora", value="vencedora",
                        className="aba", selected_className="aba-on",
                        children=html.Div(
                            [html.Div(id="wfa-bt-titulo",
                                      className="wfa-bt-titulo"),
                             html.Div(id="wfa-params")],
                            className="aba-corpo aba-vencedora")),
                ]),
        ], className="panel panel-vencedora"),

        html.Div(id="wfa-veredito"),

        html.Section([
            html.Div([html.H2("Janelas", className="panel-title"),
                      html.Span("a escadinha do walk-forward na linha do tempo",
                                className="panel-note")],
                     className="panel-head"),
            dcc.Graph(id="g-wfa-fita", figure=_vazio("Rode o walk-forward."),
                      className="graph",
                      config={"displayModeBar": False, "responsive": True}),
        ], className="panel panel-fita"),

        html.Div(id="wfa-drift"),

        html.Section([
            html.Div([html.H2("Eficiência temporal", className="panel-title"),
                      html.Span("o mesmo resultado, na régua que você sente",
                                className="panel-note")],
                     className="panel-head"),
            html.Div([
                html.Div(id="wfa-cards-mes"),
                html.Div([
                    dcc.Graph(id="g-wfa-mes", className="graf-tempo",
                              config={"displayModeBar": False, "responsive": True}),
                    dcc.Graph(id="g-wfa-dia", className="graf-tempo",
                              config={"displayModeBar": False, "responsive": True}),
                    dcc.Graph(id="g-wfa-hora", className="graf-tempo",
                              config={"displayModeBar": False, "responsive": True}),
                ], className="grade-tempo"),
            ], className="bloco-tempo"),
        ], className="panel panel-tempo"),

        html.Section([
            html.Div([html.H2("Tira-teima", className="panel-title"),
                      html.Span(["cada operação da curva, uma por linha",
                                 dica("A auditoria. Toda linha da curva fora "
                                      "da amostra: ENTRADA e SAÍDA do trade, a "
                                      "JANELA que escolheu o parâmetro dele, o "
                                      "RESULTADO já líquido, o CUSTO "
                                      "(corretagem e emolumentos das duas "
                                      "pontas) e o CAPITAL acumulado depois "
                                      "dele. É onde se confere que o número do "
                                      "cartão veio de operações de verdade — "
                                      "e onde se olha quando um trecho da "
                                      "curva parece bom demais.")],
                                className="panel-note")],
                     className="panel-head"),
            dag.AgGrid(
                id="grid-wfa-trades", columnDefs=COLUNAS_TRADES, rowData=[],
                className="ag-theme-alpine-dark grid-trades",
                dashGridOptions={
                    "animateRows": False, "rowHeight": 28, "headerHeight": 34,
                    "suppressCellFocus": True,
                    "localeText": {"noRowsToShow": "Rode o walk-forward."},
                },
                defaultColDef={"sortable": True, "resizable": True},
                style={"height": "100%", "width": "100%"},
            ),
        ], className="panel panel-grid"),
    ]


# ------------------------------------------------------- portões do WFA
def _fmt_portao(p) -> str:
    v = p["valor"]
    if v is None:
        return "—"
    nome = p["nome"]
    # o WFE vem em FRAÇÃO (1,04) e o limiar dele é escrito em porcento
    # ("≥ 70%"). Testar o "%" do limiar antes do nome fazia 1,04 virar
    # "1,0%" na tela — o portão aprovava e o número dizia o contrário.
    if "WFE" in nome:
        return f"{num(v * 100, 1)}%"
    if "lucro" in nome:
        return brl(v)
    if "%" in (p["exigido"] or ""):
        return f"{num(v, 1)}%"
    if "×" in (p["exigido"] or ""):
        return f"{num(v, 2)}×"
    return inteiro(int(v))


def selo(ver: dict) -> html.Div:
    """O carimbo do walk-forward, na gramática da Porteira da mineração."""
    if not ver:
        return html.Div()

    if ver["reprovados"]:
        motivo = "reprovado em: " + " · ".join(p["nome"] for p in ver["reprovados"])
    elif ver["ressalvas"]:
        motivo = "ressalvas em: " + " · ".join(p["nome"] for p in ver["ressalvas"])
    else:
        motivo = "passou em todos os portões"

    linhas = []
    for p in ver["portoes"]:
        marca = "✓" if p["ok"] else ("✕" if p["critico"] else "!")
        classe = "ok" if p["ok"] else ("falha" if p["critico"] else "alerta")
        linhas.append(html.Div([
            html.Span(marca, className=f"portao-marca {classe}"),
            html.Span([p["nome"], dica(p["dica"])], className="portao-nome"),
            html.Span(_fmt_portao(p), className=f"portao-valor {classe}"),
            html.Span(p["exigido"], className="portao-exigido"),
            html.Span("crítico" if p["critico"] else "alerta",
                      className=f"portao-tipo {'crit' if p['critico'] else ''}"),
        ], className="portao"))

    return html.Div([
        html.Div([
            html.Div([
                html.Span(["veredito do walk-forward",
                           dica("O carimbo sobre o PROCESSO, não sobre um "
                                "número. Reprovado significa que escolher "
                                "parâmetro desta forma não funciona em dado "
                                "novo — trocar de combinação não resolve, "
                                "porque foi escolhendo que se chegou ali. "
                                "Aprovado com ressalva passa nos críticos e "
                                "falha em algum alerta: dá para seguir "
                                "sabendo onde está a fragilidade.")],
                          className="card-label"),
                html.Span(ver["estado"], className=f"selo-valor {ver['cor']}"),
                html.Span(motivo, className="selo-motivo"),
            ], className="selo-texto"),
            html.Div(f"{ver['n_ok']}/{ver['n_portoes']}",
                     className=f"selo-nota {ver['cor']}"),
        ], className=f"selo selo-{ver['cor']}"),
        html.Div(linhas, className="portoes"),
    ], className="bloco-selo-wfa")


# ------------------------------------------------ deriva dos parâmetros
def drift_figs(itens: list[dict]) -> html.Div:
    """Um gráfico por parâmetro, com o veredito de estabilidade em cima.

    Parâmetro que a mineração varreu com um valor só não ganha gráfico: a
    reta plana não diz nada e só rouba espaço dos que derivam.
    """
    if not itens:
        return html.Div()

    variaveis = [i for i in itens if not i["fixo"]]
    blocos = []

    for it in variaveis:
        cor = {"estável": T.POS, "em transição": T.WARN,
               "instável": T.NEG}[it["estado"]]
        fig = go.Figure(go.Scatter(
            x=it["rotulos"], y=it["valores"], mode="lines+markers",
            line=dict(color=T.ACCENT, width=1.8),
            marker=dict(size=6, color=T.ACCENT),
            hovertemplate="%{x}<br>%{y}<extra></extra>",
        ))
        fig.add_hline(y=it["media"],
                      line=dict(color=T.ACCENT_2, width=1, dash="dot"))
        fig.update_layout(
            **{**BASE, "margin": dict(l=10, r=10, t=34, b=10)},
            title={**TITULO, "text": it["nome"]},
            xaxis=dict(**EIXO, type="category"),
            yaxis=dict(**EIXO),
        )
        blocos.append(html.Div([
            html.Div([
                html.Span("●", style={"color": cor}),
                html.Span(it["estado"], className="drift-estado",
                          style={"color": cor}),
                html.Span(
                    (f"desvio {num(it['volatilidade'] * 100, 0)}% da faixa minerada "
                     f"({num(it['faixa_de'], 0)}→{num(it['faixa_ate'], 0)}) · "
                     f"percorreu {num(it['percurso'] * 100, 0)}% dela · "
                     if it.get("referencia") == "faixa" else
                     f"volatilidade {num(it['volatilidade'] * 100, 1)}% da média · ")
                    + f"{it['trocas']} trocas em {it['janelas']} janelas",
                    className="drift-nota"),
            ], className="drift-head"),
            dcc.Graph(figure=fig, className="graf-drift",
                      config={"displayModeBar": False, "responsive": True}),
        ], className="drift-item"))

    cabeca = [html.H3("Estabilidade e deriva dos parâmetros", className="grp"),
              dica("Como cada parâmetro escolhido mudou de janela em janela. "
                   "Linha plana significa que a região boa fica no mesmo "
                   "lugar ano após ano — o edge tem endereço. Serrote "
                   "significa que o otimizador persegue ruído: a cada janela "
                   "ele acha um ótimo diferente, e nenhum descreve o mercado. "
                   "A régua é o desvio dos valores escolhidos dividido pela "
                   "FAIXA QUE A MINERAÇÃO TESTOU: até 5% é estável, até 15% "
                   "está em transição, acima é instável (um parâmetro "
                   "sorteado ao acaso na faixa inteira dá ~29%). 'Percorreu' "
                   "é quanto da faixa ficou entre o menor e o maior valor "
                   "escolhido. Pela faixa, e não pela média, porque a média "
                   "depende de onde fica o zero da escala: um parâmetro de "
                   "1.000 a 1.010 pareceria estável pulando de ponta a ponta.")]

    return html.Div([
        html.Div(cabeca, className="secao-head"),
        html.Div(blocos, className="grade-drift"),
    ], className="bloco-drift")


# ------------------------------------------------------ fita das janelas
def fita(passos) -> go.Figure:
    """A escadinha IS/OOS desenhada na linha do tempo.

    Barra apagada é a janela de otimização; barra acesa é o pedaço testado
    logo depois dela. Entender a mecânica do walk-forward olhando é bem mais
    rápido do que lendo — e a fita mostra de imediato quanto do histórico
    cada configuração consome antes de produzir o primeiro resultado.
    """
    if not passos:
        return _vazio("Rode o walk-forward.")

    # Plotly serializa a figura em JSON, e `np.timedelta64` nao tem
    # travessia: a largura da barra tem que ir em MILISSEGUNDOS, e a base
    # como texto ISO. Sem isso o callback inteiro morria com
    # "Object of type timedelta is not JSON serializable" - e como o erro
    # acontecia na serializacao, nada aparecia na tela e nada explicava.
    ms = lambda a, b: float((b - a) / np.timedelta64(1, "ms"))
    iso = lambda d: str(d)

    fig = go.Figure()
    for p in passos:
        j = p.janela
        y = f"{'DEPLOY' if j.deploy else j.step}"
        fig.add_trace(go.Bar(
            y=[y], x=[ms(j.is_de, j.is_ate)], base=[iso(j.is_de)],
            orientation="h",
            marker=dict(color=T.SURFACE_3, line=dict(color=T.LINE, width=1)),
            hovertemplate=(f"IS · {_br(j.is_de)} a {_br(j.is_ate)}"
                           "<extra></extra>"), showlegend=False))
        if j.deploy:
            # o OOS do DEPLOY é o futuro: hachurado, para não se confundir
            # com resultado que aconteceu
            cor, texto = T.ACCENT_DIM, "OOS · o futuro"
        elif p.fora_do_mercado:
            cor, texto = T.NEG, "fora do mercado"
        else:
            lucro = p.oos.get("lucro", 0.0)
            cor = T.POS if lucro > 0 else T.NEG
            texto = f"OOS · {_br(j.oos_de)} a {_br(j.oos_ate)}<br>{brl(lucro)}"
        fig.add_trace(go.Bar(
            y=[y], x=[ms(j.oos_de, j.oos_ate)], base=[iso(j.oos_de)],
            orientation="h",
            marker=dict(color=cor, line=dict(width=0)),
            opacity=.45 if j.deploy else .9,
            hovertemplate=texto + "<extra></extra>", showlegend=False))

    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=10, t=30, b=10)},
        barmode="overlay", bargap=.35,
        # type="date" e obrigatorio: sem ele o Plotly le o `base` ISO como
        # texto, ignora, e todas as barras nascem em zero - a escadinha
        # virava um bloco solido comecando no mesmo ponto
        xaxis=dict(**EIXO, type="date"),
        yaxis=dict(**EIXO, autorange="reversed",
                                       title=dict(text="janela",
                                                  font=dict(size=10))),
        annotations=[dict(
            text="cinza = otimização (IS) · colorido = teste (OOS), verde "
                 "lucrou e vermelho perdeu",
            showarrow=False, xref="paper", yref="paper", x=0, y=1.08,
            xanchor="left", font=dict(color=T.MUTED, size=10))],
    )
    return fig


# --------------------------------------------- eficiência temporal (OOS)
def mensal_fig(m: dict) -> go.Figure:
    if not m:
        return _vazio("Rode o walk-forward.")
    fig = go.Figure(go.Bar(
        x=m["rotulos"], y=m["valores"],
        marker=dict(color=[T.POS if v > 0 else T.NEG for v in m["valores"]],
                    line=dict(width=0)),
        hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        **{**BASE, "margin": dict(l=10, r=10, t=30, b=10)},
        title={**TITULO, "text": "Resultado mês a mês, fora da amostra"},
        xaxis=dict(**EIXO, type="category"),
        yaxis=dict(**EIXO, title=dict(text="R$", font=dict(size=10))),
        bargap=.2,
    )
    return fig


def cards_mensais(m: dict) -> html.Div:
    if not m:
        return html.Div()
    return html.Div([
        card("meses positivos", f"{num(m['pct_positivos'], 0)}%",
             "Percentual dos meses fora da amostra que fecharam no azul. É a "
             "métrica de 'eu aguentaria operar isto': o total anual esconde a "
             "experiência de operar mês a mês. Acima de 60% é sólido; abaixo "
             "de 45% a maior parte do tempo você está perdendo, mesmo que o "
             "ano feche positivo.",
             faixa(m["pct_positivos"], 60, 45),
             f"{inteiro(m['positivos'])} de {inteiro(m['meses'])} meses"),
        card("média mensal", brl(m["media"]),
             "O que a estratégia entregou por mês, em média, fora da amostra. "
             "Multiplique pelo número de contratos que você pretende operar "
             "para ter a expectativa mensal em dinheiro de verdade.",
             "pos" if m["media"] > 0 else "neg",
             f"melhor {brl(m['melhor'])} · pior {brl(m['pior'])}", largo=True),
        card("mês bom × mês ruim",
             f"{brl(m['media_lucro'])} × {brl(m['media_prejuizo'])}",
             "Quanto rende um mês positivo típico contra quanto custa um mês "
             "negativo típico. Se o mês ruim for maior que o bom, a "
             "estratégia depende de acertar a frequência — e frequência é "
             "justamente o que muda quando o mercado muda.",
             None, "média dos positivos × média dos negativos",
             largo=True, texto=True),
        card("tempo médio de recuperação",
             f"{num(m['tempo_medio_recuperacao'], 1)} meses",
             "Quanto tempo, em média, a curva mensal leva para voltar ao topo "
             "anterior depois de afundar. É a métrica que ninguém olha e que "
             "decide se você continua operando: dois meses se atravessa, sete "
             "faz qualquer um desistir.",
             faixa(m["tempo_medio_recuperacao"], 2, 5),
             f"{inteiro(m['n_episodios'])} mergulhos"),
        card("maior período sem novo topo", f"{inteiro(m['maior_sub_topo'])} meses",
             "O pior desses episódios. Antes de ligar a estratégia, olhe este "
             "número e pergunte se você teria aguentado esse tempo no "
             "vermelho sem mexer em nada — porque foi exatamente isso que a "
             "simulação assumiu que você faria.",
             faixa(m["maior_sub_topo"], 3, 8),
             "de ponta a ponta, sem fazer novo topo"),
        card("fator de recuperação mensal",
             num(m["fator_recuperacao"], 2) if m["fator_recuperacao"] else "—",
             "Lucro total dividido pelo maior mergulho da curva MENSAL — a "
             "mesma ideia do fator de recuperação, medida na régua que você "
             "sente. Acima de 3,0 é confortável; abaixo de 1,0 o lucro do "
             "período inteiro não cobre um mergulho.",
             faixa(m["fator_recuperacao"], 3, 1) if m["fator_recuperacao"] else None,
             f"profit factor mensal {num(m['profit_factor'], 2)}"),
    ], className="cards cards-wfa")
