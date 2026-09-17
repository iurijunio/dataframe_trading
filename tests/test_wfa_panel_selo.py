"""O selo (`ui/components/wfa_panel.py::selo`) reusado pela tela Candidata.

A tarefa 7 deu ao selo um `titulo` configurável e ensinou `_fmt_portao`/
`selo` a desenhar um portão com `ok is None` — os três testes demorados da
Candidata enquanto não têm resultado. Este arquivo trava as duas coisas sem
tocar em nada que a aba Walk-Forward já dependia (o `titulo` padrão continua
"veredito do walk-forward").
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata  # noqa: E402
from ui.components import wfa_panel as WP  # noqa: E402


def test_fmt_portao_pendente_com_texto_mostra_o_texto():
    p = candidata.portao("x", None, True, "aguardando", "exigido", "dica")
    assert WP._fmt_portao(p) == "aguardando"


def test_fmt_portao_pendente_sem_valor_mostra_travessao():
    p = candidata.portao("x", None, True, None, "exigido", "dica")
    assert WP._fmt_portao(p) == "—"


def test_fmt_portao_com_valor_em_texto_mostra_o_texto_sem_reformatar():
    """Portões da Candidata escrevem o próprio valor em português quando não
    é número — o platô ("N à esquerda · N à direita") e o holdout sem dado
    (`ok=False`, não pendente). `inteiro(int(v))` quebrava com esses dois
    antes de `_fmt_portao` saber olhar `isinstance(v, str)`."""
    plato = candidata.portao("O parâmetro está numa região larga?", True, True,
                             "18 à esquerda · 22 à direita", "≥ 2 por lado", "")
    assert WP._fmt_portao(plato) == "18 à esquerda · 22 à direita"
    sem_holdout = candidata.portao(
        "O holdout confirma?", False, True,
        "sem holdout na curva — salve o walk-forward com o holdout marcado",
        "dentro do esperado", "")
    assert WP._fmt_portao(sem_holdout).startswith("sem holdout na curva")


def test_selo_aceita_veredito_do_wfa_sem_a_chave_pendentes():
    """`wfa.portoes_wfa` nunca teve portão com `ok=None` e não devolve
    "pendentes" — a aba Walk-Forward quebrava com KeyError assim que
    carregava QUALQUER walk-forward salvo depois que `selo` passou a
    escrever o "aguardando: ..." no motivo (a chave só existe no veredito
    da Candidata, `candidata.veredito`)."""
    ver_wfa = {"portoes": [], "estado": "aprovado", "cor": "pos",
              "n_ok": 0, "n_portoes": 0, "reprovados": [], "ressalvas": []}
    WP.selo(ver_wfa)          # não pode levantar KeyError


def test_selo_titulo_padrao_continua_o_do_walk_forward():
    ver = candidata.veredito([candidata.portao("a", True, True, 1, "", "")])
    texto = str(WP.selo(ver))
    assert "veredito do walk-forward" in texto


def test_selo_aceita_titulo_da_candidata():
    ver = candidata.veredito([candidata.portao("a", True, True, 1, "", "")])
    texto = str(WP.selo(ver, titulo="a estratégia está pronta para a incubação?"))
    assert "a estratégia está pronta para a incubação?" in texto
    assert "veredito do walk-forward" not in texto


def test_fmt_portao_acaso_mostra_numero_sem_moeda():
    """"O lucro não é acaso?" mede um teste-t, não dinheiro — o "lucro" no
    nome é só a pergunta, e não pode acionar a formatação em reais."""
    p = candidata.portao_acaso(__import__("numpy").full(60, 5.0))
    assert WP._fmt_portao(p) == f"{p['valor']:.2f}".replace(".", ",")
    assert "R$" not in WP._fmt_portao(p)


def test_fmt_portao_holdout_mostra_reais_nao_percentual():
    """O exigido do holdout ("fora dos 10% piores caminhos") tem um "%" que
    descreve o LIMIAR, não o valor medido — que é uma soma em reais."""
    p = candidata.portao("O holdout confirma?", True, True, 942.0,
                         "fora dos 10% piores caminhos", "")
    assert WP._fmt_portao(p) == "R$ 942,00"


def test_fmt_portao_custo_e_1pct_mostram_reais():
    custo = candidata.portao("Aguenta custo maior?", True, True, 4454.0,
                             "> 0 com +1 tick por ponta", "")
    trades1pct = candidata.portao("Depende do 1% melhor dos trades?", True,
                                  False, 4106.0, "> 0 sem eles", "")
    assert WP._fmt_portao(custo) == "R$ 4.454,00"
    assert WP._fmt_portao(trades1pct) == "R$ 4.106,00"


def test_fmt_portao_aleatorio_e_tentativas_escalam_fracao_para_percentual():
    """`portao_aleatorio`/`portao_tentativas` guardam o p-valor como fração
    (0,03), não já em 0–100 — sem escalar, 3% de chance virava "0,0%" na
    tela (arredondado a 1 casa a partir de 0,03), como se o resultado fosse
    quase perfeito quando só passou raspando no limiar de 5%."""
    aleatorio = candidata.portao_aleatorio({"p": 0.03, "calibracao_ok": True})
    tentativas = candidata.portao_tentativas({"p": 0.024})
    assert WP._fmt_portao(aleatorio) == "3,0%"
    assert WP._fmt_portao(tentativas) == "2,4%"


def test_selo_marca_portao_pendente_como_pendente():
    pend = candidata.portao("Ganha de entradas sorteadas ao acaso?", None,
                            True, "aguardando", "exigido", "dica")
    ver = candidata.veredito([pend])
    texto = str(WP.selo(ver))
    assert "portao-marca pendente" in texto
    assert "portao-valor pendente" in texto
    assert ver["estado"] == "aguardando testes completos"
