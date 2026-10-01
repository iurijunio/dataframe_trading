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


def _reais(v, quando_falta="não medido"):
    return brl(v) if v is not None else quando_falta


def linhas_tamanho(dim: dict, ref: dict, disj: dict,
                   capital: float) -> list[tuple[str, str, list[dict]]]:
    """Os grupos do bloco 5: quanto operar e quando parar.

    Mesmo formato dos outros blocos — (título, explicação, linhas) — para
    reusar a mesma tabela com mapa de calor. Nada aqui calcula: o que chega
    já vem de `core/tamanho.py`, e o que falta chega como `None` e aparece
    como "não medido", nunca como zero.
    """
    n = dim.get("n") or 0
    efetivo = dim.get("risco_efetivo_pct")
    pedido = dim.get("risco_pedido_pct")
    margem = dim.get("margem")

    quanto = [
        {"nome": "contratos", "valor": inteiro(n),
         "nota": (dim.get("motivo") or
                  f"quem limitou: {dim.get('limite') or '—'}"),
         "tom": "ruim" if n <= 0 else "bom",
         "explica": ("Quantos contratos operar. É o menor de três contas: o "
                     "que o seu risco por pregão permite, o que a garantia da "
                     "corretora permite, e o que sobra para pagar as duas "
                     "coisas no mesmo dia. Sempre arredondado para baixo — "
                     "entre 1 e 2 contratos o risco dobra. Zero contratos não "
                     "é erro: é o capital não comportar o instrumento, e a "
                     "nota diz qual das contas zerou. Bom: 1 ou mais. Ruim: "
                     "zero — e aí baixar o risco não resolve, porque ele já "
                     "está no limite; só mais capital ou limite de operações "
                     "no dia mais apertado.")},
        {"nome": "risco por pregão",
         "valor": pct(efetivo, 2) if efetivo is not None else "não medido",
         "nota": (f"você pediu {pct(pedido, 1)}" if pedido else ""),
         "tom": None,
         "explica": ("Quanto do capital você perde num pregão ruim com os "
                     "contratos escolhidos. É por PREGÃO, não por operação: a "
                     "perda de referência é de um dia inteiro, então quem "
                     "opera três vezes por dia não multiplica por três. O "
                     "valor real fica abaixo do pedido porque o número de "
                     "contratos é inteiro, e o pedido é o teto. Bom: até 1% "
                     "por pregão. Ruim: acima de 2%, porque a sequência de "
                     "dias ruins que a tabela mostra logo abaixo viraria uma "
                     "perda grande demais para continuar operando.")},
        {"nome": "perda de referência", "valor": _reais(ref.get("valor")),
         "nota": (ref.get("de_onde") or ref.get("motivo") or ""),
         "tom": None,
         "explica": ("A perda de UM contrato que decide o tamanho da "
                     "posição: vale a pior entre a média dos 5% piores dias e "
                     "um dia ruim de execução. É uma MÉDIA dos dias ruins, "
                     "não o teto deles — metade dos dias ruins perde mais que "
                     "isso. Bom: até 2% do seu capital, porque aí 1 contrato "
                     "cabe com folga. Ruim: acima de 5%, quando o capital "
                     "praticamente não comporta o instrumento.")},
        {"nome": "dia ruim de execução", "valor": _reais(ref.get("dia_ruim")),
         "nota": "todos os stops do dia, o último com o dobro do tamanho",
         "tom": None,
         "explica": ("O dia em que todo stop que o seu limite diário permite "
                     "bate, e o último sai com o dobro do tamanho porque não "
                     "havia preço. Pode nunca ter acontecido na sua curva e "
                     "ainda assim acontecer amanhã — por isso ele entra na "
                     "conta. Quantos stops cabem no dia sai do seu limite "
                     "diário; sem limite nenhum, sai do pregão mais "
                     "movimentado que a sua curva já teve. Ruim: quando ele "
                     "fica muito maior que a média dos dias ruins, porque aí "
                     "é ele que decide o seu tamanho. Apertar o máximo de "
                     "operações por dia derruba este número direto.")},
        {"nome": "pior pregão já ocorrido",
         "valor": _reais(abs(ref["pior_dia"]) if ref.get("pior_dia") else None),
         "nota": "leitura, não dimensiona", "tom": None,
         "explica": ("O pior dia que a curva fora da amostra já teve, por "
                     "contrato. Não dimensiona nada de propósito: ele é um "
                     "recorde, que só piora conforme o histórico cresce, e um "
                     "único registro torto passaria a decidir sozinho o seu "
                     "tamanho de posição. Serve de referência: se ele for "
                     "muito maior que a média dos dias ruins, você já viveu "
                     "um dia fora da curva — e vai viver de novo. Bom: perto "
                     "da média dos dias ruins. Ruim: várias vezes maior, "
                     "porque aí o pior dia da sua curva não tem nada a ver "
                     "com o dia ruim comum.")},
        {"nome": "garantia por contrato",
         "valor": _reais(margem, "não informada"),
         "nota": (f"usando até {pct(dim.get('uso_margem_pct'), 0)} do capital"
                  if margem else "a conta da garantia ficou de fora"),
         "tom": None,
         "explica": ("Quanto a corretora exige de garantia por contrato. "
                     "Informe a INTRADIÁRIA se você fecha a posição no mesmo "
                     "dia — a cheia é dez a trinta vezes maior e derrubaria o "
                     "número de contratos na mesma proporção. Em branco, a "
                     "conta da garantia fica de fora e só o risco limita. "
                     "Bom: informada, com o valor que a sua corretora cobra "
                     "hoje. Ruim: em branco, porque o número de contratos "
                     "pode sair maior do que ela vai deixar você operar.")},
    ]

    n1, n2 = disj.get("nivel1") or {}, disj.get("nivel2") or {}
    alarme2 = n2.get("risco_de_desligar_pct")
    # com zero contratos os limites sairiam todos "não medido" e a metade de
    # baixo da tela ficaria vazia justamente para quem mais precisa dela.
    # Mostra-se a conta de 1 contrato, dizendo que é mais do que o risco
    # pedido permite — número medido, com a régua certa escrita ao lado
    # e o aviso precisa citar a conta que REALMENTE zerou: mandar mexer no
    # risco quando quem travou foi a garantia é o mesmo defeito que o motivo
    # da linha "contratos" existe para evitar
    _QUEM = {"risco": "o seu risco por pregão",
             "margem": "a garantia disponível",
             "garantia mais prejuízo do dia":
                 "o capital livre depois da garantia"}
    quem = " e ".join(_QUEM.get(k, k)
                      for k in (dim.get("limite") or "risco").split(" e "))
    hipotetico = (f"conta feita com 1 contrato, que é mais do que {quem} "
                  "permite hoje") if n <= 0 else ""

    def nota(texto):
        # o aviso vem na FRENTE: na coluna estreita da nota, o que fica no fim
        # de um texto longo é o primeiro pedaço que some
        if not hipotetico:
            return texto
        return f"{hipotetico} · {texto}" if texto else hipotetico
    parar = [
        {"nome": "reduzir para 1 contrato", "valor": _reais(n1.get("queda")),
         "nota": nota(f"reduz à toa em {pct(n1.get('alarme_pct'), 0)} dos "
                      "períodos até reotimizar" if n1.get("queda")
                      else disj.get("motivo") or ""),
         "tom": None,
         "explica": ("Quando a queda a partir do topo passar deste valor, "
                     "reduza para 1 contrato. O limite não foi escolhido no "
                     "olho: você escolhe com que frequência aceita reduzir "
                     "sem precisar — 20% das vezes, por padrão — e o valor em "
                     "reais sai disso. Esses 20% querem dizer: em 20 de cada "
                     "100 períodos até a próxima reotimização, uma estratégia "
                     "que continua boa encostaria aqui e você reduziria à "
                     "toa. Reduzir é barato e se desfaz, por isso pode "
                     "disparar mais vezes que o desligar. Bom: entre 15% e "
                     "25%. Ruim: abaixo de 10%, e você só reduz quando já "
                     "perdeu demais; acima de 35%, e você vive com meia "
                     "posição sem motivo.")},
        {"nome": "desligar e reotimizar", "valor": _reais(n2.get("queda")),
         "nota": nota((f"{pct(n2.get('pct'), 1)} do capital · desliga uma "
                       f"estratégia boa em {pct(alarme2, 1)} dos períodos até "
                       "reotimizar")
                      if n2.get("queda") else disj.get("motivo") or ""),
         "tom": _tom(alarme2, 8, 15) if alarme2 is not None else None,
         "explica": ("Quando a queda chegar aqui, desligue e reotimize antes "
                     "de voltar. Mesma lógica: você escolhe quantas vezes "
                     "aceita desligar uma estratégia que ainda funcionava — 5 "
                     "de cada 100 períodos até a reotimização, por padrão. "
                     "Bom: até 8%. Ruim: acima de 15%, porque aí o disjuntor "
                     "dispara sozinho e você nunca vai saber se a estratégia "
                     "morreu ou só teve azar.")},
        {"nome": "dias perdendo seguidos",
         "valor": (inteiro(n1["perdas_seguidas"])
                   if n1.get("perdas_seguidas") else "não medido"),
         "nota": "também reduz para 1 contrato", "tom": None,
         "explica": ("Quantos pregões seguidos no prejuízo você deve estar "
                     "preparado para viver. Passou disso, reduza — é o mesmo "
                     "sinal da queda, visto por outro lado. Dia sem operação "
                     "não conta. Bom: até 8, uma semana e meia de pregões. "
                     "Ruim: acima de 15, porque quase ninguém segue o plano "
                     "depois de três semanas perdendo.")},
        {"nome": "pior lucro esperado no prazo",
         "valor": _reais(n1.get("lucro_no_prazo")),
         "nota": nota(f"ao fim de {inteiro(disj.get('horizonte') or 0)} "
                      "pregões" if disj.get("horizonte") else ""),
         "tom": None,
         "explica": ("Onde o lucro acumulado costuma estar no PIOR dos casos "
                     "ao fim do prazo até a próxima reotimização. A "
                     "plataforma sorteia 2.000 continuações possíveis para a "
                     "sua estratégia, usando os dias que ela já viveu em "
                     "outra ordem, e só 1 em cada 10 termina abaixo deste "
                     "número. Ficar abaixo dele não é azar comum — é sinal de "
                     "reduzir. Bom: número positivo, ou seja, mesmo o mau "
                     "caminho ainda termina no lucro.")},
        {"nome": "dias sem novo topo",
         "valor": (inteiro(disj["dias_sem_topo"])
                   if disj.get("dias_sem_topo") else "não medido"),
         "nota": (f"de {inteiro(disj.get('horizonte') or 0)} pregões"
                  if disj.get("horizonte") else ""),
         "tom": None,
         "explica": ("Quanto tempo a estratégia pode passar abaixo do último "
                     "topo sem que isso signifique que ela quebrou. Passar "
                     "muito disso é motivo para olhar, mesmo sem a queda ter "
                     "batido no limite. Bom: até metade do prazo até a "
                     "reotimização. Ruim: quase o prazo inteiro, porque aí "
                     "você passaria o ciclo todo no vermelho esperando.")},
        {"nome": "limite do dia",
         "valor": _reais(disj.get("limite_dia_reais"), "não definido"),
         "nota": nota((f"{inteiro(disj['limite_dia_trades'])} operações por "
                       "dia") if disj.get("limite_dia_trades")
                      else "sem limite de operações no dia"),
         "tom": None,
         "explica": ("O limite de perda e de operações do dia que vem do seu "
                     "perfil de execução, já multiplicado pelos contratos. "
                     "Bom: ter os dois definidos. Ruim: não ter nenhum, "
                     "porque sem trava o dia pode empilhar perdas — e é "
                     "justamente isso que engorda a perda de referência lá em "
                     "cima e derruba o seu número de contratos.")},
    ]

    return [
        ("Quanto operar",
         "O tamanho da posição sai da perda de um contrato num pregão ruim, "
         "não do lucro esperado. Três contas limitam ao mesmo tempo, e vale a "
         "menor delas.",
         quanto),
        ("Quando parar",
         "Dois níveis, porque um gatilho só é mau detector: parando apenas na "
         "queda ruim, você desliga estratégia sadia às vezes e demora demais "
         "para desligar a que morreu. Os valores em reais saem da frequência "
         "com que você aceita agir à toa — não de um número escolhido no "
         "olho.",
         parar),
    ]


def bloco_tamanho(dim: dict, ref: dict, disj: dict, capital: float):
    """As duas tabelas do bloco 5."""
    return html.Div([_tabela(*g) for g in linhas_tamanho(dim, ref, disj,
                                                         capital)],
                    className="cand-tabelas")


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
        # uma fase que explode vira portão "não medido" e as outras seguem;
        # dizer "testes completos" aqui escondia a falha atrás de uma barra
        # cheia, e o operador só descobria lendo o selo portão por portão
        faltou = [p["nome"] for p in e["resultado"].get("portoes") or []
                  if p.get("ok") is None]
        txt = ("testes completos" if not faltou else
               "terminou, mas não mediu: " + " · ".join(faltou))
        return dict(fase="pronto", txt=txt, pct=100, ocupado=False)
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


def _campo(id_, rotulo, valor, explica, passo=0.1, minimo=0,
           placeholder=None):
    return html.Div([
        html.Label([rotulo, dica(explica)], className="lbl"),
        dcc.Input(id=id_, type="number", value=valor, min=minimo, step=passo,
                  placeholder=placeholder, className="inp inp-cand"),
    ], className="fld fld-cand")


def entradas_tamanho() -> html.Div:
    """Os três diais do bloco 5.

    Ficam acima da tabela porque mudam todos os números dela. Só estes três
    são escolha do operador — o resto sai da curva.
    """
    return html.Div([
        _campo("cand-risco", "risco por pregão (%)", 1.0,
               "Quanto do capital você aceita perder num PREGÃO ruim — não "
               "numa operação. A perda de referência é de um dia inteiro, "
               "então quem opera três vezes por dia não multiplica por três. "
               "1% é um ponto de partida comum; acima de 2% por pregão a "
               "sequência ruim normal já machuca demais.", passo=0.1),
        _campo("cand-margem", "garantia por contrato (R$)", None,
               "Quanto a corretora exige de garantia por contrato. Informe a "
               "INTRADIÁRIA se você fecha a posição no mesmo dia: a cheia é "
               "dez a trinta vezes maior e derrubaria o número de contratos "
               "na mesma proporção. Deixe em branco e a conta da garantia "
               "fica de fora — a tela avisa que ela não foi conferida.",
               passo=10, placeholder="não informada"),
        _campo("cand-uso-margem", "capital para garantia (%)", 50.0,
               "Quanto do seu capital pode ficar preso como garantia. Usar "
               "100% não sobra dinheiro para o prejuízo do próprio dia, que "
               "é debitado da mesma conta. 50% é o padrão.", passo=5),
    ], className="cand-diais")


def bloco_gravar() -> html.Div:
    """O fim da tela: transformar o que ela calculou num plano gravado.

    O botão nasce desligado e o motivo fica escrito ao lado — apagado sem
    explicação, o operador não saberia se falta rodar teste, mudar a
    estratégia ou mudar o capital, e o remédio de cada um é diferente.
    """
    return html.Div([
        html.Button("Gravar plano de operação", id="btn-cand-gravar",
                    n_clicks=0, className="btn-primary", disabled=True),
        dica("Grava tudo o que esta tela mostra — parâmetros, contratos, "
             "quando reduzir e quando desligar, o que se espera em 3, 6 e 12 "
             "meses e a régua do dia — num registro que não muda mais. É ele "
             "que a incubação vai ler. Para mudar alguma coisa, grava-se "
             "outro: plano antigo não é editado, é aposentado."),
        html.Span(id="cand-gravar-motivo", className="cand-gravar-motivo"),
        # só aparece quando o veredito é a única trava (`cand_pode_gravar`)
        html.Span([
            html.Button("Gravar mesmo assim", id="btn-cand-forcar", n_clicks=0,
                        className="btn-ghost btn-sm cand-forcar"),
            dica("Grava o plano mesmo com o veredito contra — reprovado ou "
                 "com teste sem medir. A decisão fica registrada no plano e "
                 "no diário, com a lista do que falhou, e a ficha da variante "
                 "mostra a etiqueta \"gravado mesmo assim\". Use quando você "
                 "conhece o motivo da reprovação e quer ver a estratégia "
                 "operar no papel antes de decidir."),
        ], id="cand-forcar-bloco", className="cand-forcar-bloco",
            style={"display": "none"}),
        html.Span(id="cand-forcar-aviso", className="cand-gravar-motivo"),
        html.Span(id="cand-gravar-aviso", className="cand-gravar-aviso"),
        dcc.Store(id="cand-forcar-armado"),
        # o veredito que o selo acabou de calcular, para o botão não refazer
        # os 2.000 caminhos do holdout a cada mexida no dial
        dcc.Store(id="cand-veredito"),
    ], className="cand-gravar")


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
            entradas_tamanho(),
            html.Div(id="cand-tamanho", className="cand-blocos"),
            bloco_gravar(),
        ],
        # escondido de saída: sem isto o painel aparece embaixo do Backtest
        # até o callback `modo` resolver no navegador
        id="painel-candidata", className="modo-bloco cand",
        style={"display": "none"},
    )
