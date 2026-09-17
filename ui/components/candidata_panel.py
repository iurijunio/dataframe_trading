"""O quarto modo: a candidata.

Recebe um walk-forward salvo e responde, antes de arriscar dinheiro:
quanto a estratégia aguenta, se o resultado é mérito ou sorte, e com
quantos contratos operar. Ver docs/PLANO-CANDIDATA.md.

Os números aparecem numa tabela com mapa de calor, não em cartões: numa
tela só de números, a tabela lê de cima a baixo e a cor mostra de relance
o que está bom e o que está ruim. Os textos são para quem opera — o nome
diz a pergunta que o número responde, e o (?) explica com a faixa boa e a
ruim.
"""

from __future__ import annotations

from dash import dcc, html

from core import candidata

from . import cartao, stats_cards
from .cartao import brl, dica, faixa, inteiro, pct
from .wfa_panel import DICAS_OOS, _br


def vazio(mensagem):
    return cartao.vazio(mensagem)


def _boot_do_recorte(leitura: dict, recorte: str) -> dict:
    """A simulação do recorte que deu o pior número, para ler dela os campos
    que não entram na escolha do pior (o caso típico, por exemplo)."""
    if recorte == "curva inteira":
        return leitura.get("boot") or {}
    return leitura.get("boot_12m") or {}


def _de_onde(recorte: str, holdout: bool) -> str:
    """Frase para o (?) dizendo de qual trecho da curva veio o número."""
    if recorte == "últimos 12 meses":
        return (" Neste walk-forward, o número veio dos últimos 12 meses"
                + (", que incluem o holdout." if holdout else "."))
    return " Neste walk-forward, o número veio da curva inteira."


def _meses(pregoes: int) -> int:
    return max(1, round(pregoes / 21))


def _tom(v, bom, ruim):
    """A cor da célula: a mesma faixa que o (?) descreve em palavras."""
    if v is None:
        return None
    return {"pos": "bom", "neg": "ruim"}.get(faixa(v, bom, ruim), "medio")


def _tons_do_resultado(m: dict, capital: float) -> dict:
    """As faixas dos números da curva, tiradas dos textos do (?) de
    `stats_cards` — se um mudar, o outro tem que mudar junto."""
    dd_cap = (m["max_drawdown"] / capital * 100) if capital else None
    pf = m["profit_factor"]
    return {
        "lucro líquido": "bom" if m["lucro_liquido"] > 0 else "ruim",
        "max drawdown": _tom(dd_cap, 10, 20),
        "profit factor": (None if pf == float("inf")
                          else "ruim" if pf < 1.0
                          else "bom" if pf >= 1.2 else "medio"),
        "expectativa": "bom" if m["expectativa"] > 0 else "ruim",
        "fator recuperação": _tom(m["fator_recuperacao"], 3.0, 1.0),
        "sharpe": _tom(m["sharpe"], 1.0, 0.0),
        "trades": "ruim" if m["trades"] < 100 else None,
    }


def _linha_holdout(holdout_gate: dict | None) -> dict:
    """A linha "holdout" da tabela de resultado fora da amostra.

    Os mesmos números que o portão "O holdout confirma?" já calculou — não
    roda o bootstrap uma segunda vez, só lê `lucro_mes_holdout` e
    `lucro_mes_antes` que `candidata.portao_holdout` devolve junto do
    portão. Sem cor: aqui é leitura do que aconteceu, quem reprova é o
    portão ao lado, no selo.
    """
    explica = ("Quanto a curva rendeu por mês nos meses do HOLDOUT (o "
               "trecho final que nenhuma combinação minerada enxergou) "
               "contra quanto rendia por mês ANTES do corte. É a mesma "
               "curva do portão \"O holdout confirma?\", só em reais por "
               "mês em vez de caminhos simulados — quem decide passa ou "
               "reprova é aquele portão, não esta linha.")
    tem_holdout = (holdout_gate and holdout_gate.get("pregoes_holdout")
                  and holdout_gate.get("lucro_mes_holdout") is not None)
    if not tem_holdout:
        return {"nome": "holdout", "valor": "sem holdout nesta curva",
                "nota": "", "tom": None, "explica": explica}
    return {
        "nome": "holdout",
        "valor": f"{brl(holdout_gate['lucro_mes_holdout'])}/mês no holdout",
        "nota": f"{brl(holdout_gate['lucro_mes_antes'])}/mês antes do corte",
        "tom": None, "explica": explica,
    }


def linhas(leitura: dict, capital: float, holdout: bool = False,
           de=None, ate=None, holdout_gate: dict | None = None
           ) -> list[tuple[str, str, list[dict]]]:
    """Os grupos da tabela: (título, explicação, linhas).

    Cada linha tem nome, valor, nota, explicação do (?) e tom
    ('bom', 'medio', 'ruim' ou None quando o número não tem faixa).
    """
    m = dict(leitura["resumo"])
    if de and ate:
        m["periodo"] = f"{_br(de)} → {_br(ate)}"
        m["periodo_nota"] = "fora da amostra, janela após janela"
    tons = _tons_do_resultado(m, capital)
    resultado = [{"nome": i["rotulo"], "valor": i["valor"],
                  "nota": i["nota"] or "", "explica": i["explica"],
                  "tom": tons.get(i["rotulo"])}
                 for i in stats_cards.itens(m, DICAS_OOS)]
    resultado.append(_linha_holdout(holdout_gate))

    o = leitura["ordenacao"]
    pior = candidata.pior_dos_recortes(leitura)
    horizonte = int((leitura.get("boot") or {}).get("horizonte") or 1)
    meses = _meses(horizonte)

    perda, perda_rec = pior["dd_p95"]["valor"], pior["dd_p95"]["recorte"]
    perda_pct = perda / capital * 100 if capital else 0.0
    seguidas = pior["perdas_seguidas_p95"]["valor"]
    seguidas_rec = pior["perdas_seguidas_p95"]["recorte"]
    topo_pior = pior["submerso_p95"]["valor"]
    topo_rec = pior["submerso_p95"]["recorte"]
    topo_tipico = _boot_do_recorte(leitura, topo_rec).get("submerso_p50", 0.0)
    ordem = o.get("dd_p95", 0.0)
    ordem_pct = ordem / capital * 100 if capital else 0.0

    aguenta = [
        {"nome": f"perda esperada · {meses} meses", "valor": brl(perda),
         "nota": f"{pct(perda_pct, 1)} do capital",
         "tom": _tom(perda_pct, 10, 20),
         "explica": ("A maior queda a partir de um topo que você deve esperar "
                     f"nos próximos {meses} meses, até a próxima "
                     "reotimização. Só 5 de cada 100 caminhos sorteados "
                     "perdem mais do que isso. É a base para decidir quando "
                     "desligar o robô. Bom: até 10% do capital. Ruim: acima "
                     "de 20%." + _de_onde(perda_rec, holdout))},
        {"nome": "dias perdendo seguidos",
         "valor": inteiro(int(round(seguidas))),
         "nota": ("na curva real: "
                  f"{inteiro(int(leitura.get('perdas_seguidas_reais', 0)))}"),
         "tom": None,
         "explica": ("Quantos dias de operação seguidos fechando no prejuízo "
                     "você deve estar preparado para viver. Dia sem operação "
                     "não conta. Só 5 de cada 100 caminhos têm sequência "
                     "maior. Se este número for bem maior que o da curva "
                     "real, o passado teve sorte — o azar ainda não "
                     "apareceu." + _de_onde(seguidas_rec, holdout))},
        {"nome": "dias até novo topo",
         "valor": inteiro(int(round(topo_tipico))),
         "nota": (f"pior caso: {inteiro(int(round(topo_pior)))} de "
                  f"{inteiro(horizonte)} pregões"),
         "tom": _tom(topo_tipico / horizonte * 100 if horizonte else None,
                     50, 90),
         "explica": ("Quantos dias de pregão a estratégia costuma passar "
                     "abaixo do último topo antes de superá-lo. O valor é o "
                     "caso típico; o pior caso fica ao lado. O prazo é de "
                     f"{inteiro(horizonte)} pregões (até a próxima "
                     "reotimização). Bom: até metade do prazo. Ruim: quase o "
                     "prazo inteiro." + _de_onde(topo_rec, holdout))},
        {"nome": "perda com outra ordem", "valor": brl(ordem),
         "nota": f"{pct(ordem_pct, 1)} do capital · período inteiro",
         "tom": _tom(ordem_pct, 10, 20),
         "explica": ("Os MESMOS trades da curva, embaralhados: o lucro final "
                     "não muda, só a ordem. Mede o azar de os prejuízos virem "
                     "todos juntos, no período inteiro (não nos próximos "
                     "meses) — por isso é maior que a perda esperada e não se "
                     "compara direto com ela. Bom: até 10% do capital. Ruim: "
                     "acima de 20%.")},
    ]

    return [
        ("Resultado fora da amostra",
         "Os mesmos números da aba Walk-Forward: o que a estratégia fez nos "
         "meses que o otimizador não viu.",
         resultado),
        ("Quanto a estratégia aguenta",
         "A plataforma sorteia 2.000 caminhos possíveis para a estratégia, "
         "usando os dias reais que ela já operou em outra ordem e combinação. "
         "Os números dizem o que acontece nos caminhos ruins — não no que "
         "você viu, que é só um deles. Cada linha é o pior caminho PARA "
         "AQUELA métrica: os números ruins de linhas diferentes não "
         "aconteceram todos juntos, no mesmo caminho sorteado.",
         aguenta),
    ]


def _tabela(titulo: str, explica: str, itens: list[dict]):
    corpo = [
        html.Tr([
            html.Td([l["nome"], cartao.dica(l["explica"])], className="ct-nome"),
            html.Td(l["valor"], className="ct-valor"
                    + (f" tom-{l['tom']}" if l["tom"] else "")),
            html.Td(l["nota"], className="ct-nota"),
        ])
        for l in itens
    ]
    return html.Div([
        html.Div([html.H3(titulo, className="grp"), cartao.dica(explica)],
                 className="secao-head"),
        html.Div(html.Table(html.Tbody(corpo), className="cand-tab"),
                 className="cand-tab-rola"),
    ], className="cand-tab-bloco")


def bloco_robustez(leitura: dict, capital: float, holdout: bool = False,
                   de=None, ate=None, holdout_gate: dict | None = None):
    """A tabela da tela: o resultado fora da amostra e quanto ele aguenta.

    Cada número de risco é calculado duas vezes — na curva inteira e só nos
    últimos 12 meses — e vale o pior dos dois, porque o comportamento
    recente pesa mais do que a média de quatro anos.
    """
    if leitura.get("erro"):
        return vazio(leitura["erro"])
    return html.Div([_tabela(*g) for g in linhas(leitura, capital, holdout,
                                                  de, ate, holdout_gate)],
                    className="cand-tabelas")


def estado_testes(e: dict, wfa_id=None) -> dict:
    """Traduz `candidata_runner.TESTES.estado` para o que a barra mostra.

    Função pura, testável sem servidor — no mesmo desenho de
    `wfa_panel.estado_progresso`. Erro tem prioridade sobre rodando: uma
    fase pode falhar e deixar `erro` preenchido com `rodando` já `False`
    (ver `TestesCompletos._rodar`), e é o erro que a tela precisa mostrar,
    não uma barra "ociosa" como se nada tivesse acontecido.

    `TESTES` é um singleton só, sem noção de "por walk-forward": sem este
    confronto, trocar do #8 (testes prontos) para outro walk-forward
    continuava mostrando "testes completos" do #8 enquanto o selo do outro
    já dizia "aguardando" — dois lugares da mesma tela contando histórias
    diferentes. `wfa_id=None` (chamada sem saber qual está aberto, como nos
    testes antigos desta função) não filtra nada.
    """
    if (e.get("wfa_id") is not None
            and (wfa_id is None or int(wfa_id) != int(e["wfa_id"]))):
        return dict(fase="ocioso", txt="escolha um walk-forward e clique em "
                                       "\"Rodar testes completos\"",
                    pct=0, ocupado=False)
    if e.get("erro"):
        return dict(fase="erro", txt=e["erro"], pct=100, ocupado=False)
    if e.get("rodando"):
        return dict(fase="rodando", txt=e.get("fase") or "preparando",
                    pct=e.get("pct") or 0, ocupado=True)
    if e.get("resultado") is not None:
        return dict(fase="pronto", txt="testes completos", pct=100,
                    ocupado=False)
    return dict(fase="ocioso", txt="escolha um walk-forward e clique em "
                                   "\"Rodar testes completos\"",
                pct=0, ocupado=False)


def relogio_ligado(estado: dict, store: dict | None) -> bool:
    """Decide se `cand-tick` continua ligado — função pura, extraída para
    ser testável sem montar o app, na ordem exata que travava o selo.

    `cand_botao_testes` e `cand_fim_dos_testes` escutam o MESMO `cand-tick`
    e cada um lê `TESTES.estado` na sua hora: se `cand_fim_dos_testes` lê
    "rodando" um instante antes de a thread terminar (e não anuncia nada
    nesta batida) e, logo depois, `cand_botao_testes` já lê "parado", ele
    desligava o relógio sem o Store `cand-testes` nunca ter recebido a
    geração nova — e sem relógio não há próxima batida para
    `cand_fim_dos_testes` tentar de novo. O selo ficava preso em
    "aguardando testes completos" para sempre.

    A regra: enquanto está rodando, liga. Quando termina (resultado ou
    erro), só desliga depois que o Store já tiver a MESMA geração do
    `TESTES.estado` — ou seja, depois que `cand_fim_dos_testes` já
    conseguiu anunciar esta rodada. Nunca rodou nada (nem resultado nem
    erro) não é "terminou esperando anúncio": fica desligado, como sempre.
    """
    if estado.get("rodando"):
        return True
    pronto = estado.get("resultado") is not None or estado.get("erro")
    if not pronto:
        return False
    return (store or {}).get("g") != estado.get("geracao")


def bloco_testes() -> html.Div:
    """O botão que dispara os três testes demorados (aleatório, tentativas,
    reotimizar) e a barra de progresso deles.

    Mesmo desenho da varredura da aba Walk-Forward, com relógio PRÓPRIO
    (`cand-tick`, desligado por padrão): o `dcc.Interval` `tick` já tem dono
    único (`pulso`, em `ui/callbacks.py`), e ligar nele faria o progresso da
    Candidata reagir a toda batida da mineração e da varredura, sem
    relação nenhuma com os testes completos.
    """
    return html.Div([
        html.Button("Rodar testes completos", id="btn-cand-testes",
                    n_clicks=0, className="btn-ghost", disabled=True),
        html.Div([
            html.Div([html.Span(id="cand-prog-txt", className="wfa-prog-txt"),
                      html.Span(id="cand-prog-pct", className="wfa-prog-pct")],
                     className="wfa-prog-linha"),
            html.Div(html.Div(id="cand-prog-bar", className="prog-bar"),
                     className="prog wfa-prog-trilho"),
        ], id="cand-prog", className="wfa-prog ocioso"),
        html.Span(id="cand-aviso-testes", className="wfa-prog-aviso"),
        dcc.Interval(id="cand-tick", interval=800, disabled=True),
        dcc.Store(id="cand-testes"),
    ], className="cand-testes-linha")


def painel():
    return html.Div(
        [
            html.Div(
                [
                    # os dois nascem vazios: quem preenche são os callbacks
                    # `cand_estrategias` e `cand_opcoes`
                    dcc.Dropdown(id="cand-estrategia", className="dd dd-cand-est",
                                 placeholder="estratégia…", clearable=False,
                                 options=[], value=None),
                    dcc.Dropdown(id="cand-wfa", className="dd dd-wfa",
                                 placeholder="walk-forward salvo…",
                                 options=[], value=None),
                    html.Span(id="cand-resumo", className="cand-resumo"),
                ],
                className="cand-topo",
            ),
            bloco_testes(),
            html.Div(id="cand-portoes", className="cand-portoes"),
            html.Div(id="cand-blocos", className="cand-blocos"),
        ],
        # escondido de saída: sem isto o painel aparece embaixo do Backtest
        # até o callback `modo` resolver no navegador
        id="painel-candidata", className="modo-bloco cand",
        style={"display": "none"},
    )
