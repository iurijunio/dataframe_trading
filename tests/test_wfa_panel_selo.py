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
                         "fora dos 10% piores caminhos", "",
                         formato=candidata.REAIS)
    assert WP._fmt_portao(p) == "R$ 942,00"


def test_fmt_portao_custo_e_1pct_mostram_reais():
    """Pelas funções que produzem os portões de verdade — é delas que o
    formato vem, não do nome."""
    import numpy as np
    custo = candidata.portao_custo(4456.0, [1], 1.0)          # sobra 4.454
    trades1pct = candidata.alerta_poucos_trades(np.full(100, 41.06))
    assert WP._fmt_portao(custo) == "R$ 4.454,00"
    assert WP._fmt_portao(trades1pct) == "R$ 4.064,94"


def test_renomear_um_portao_nao_muda_o_formato_do_numero():
    """A dívida 4 da etapa 2: o formato vinha de uma tabela indexada pelo
    NOME do portão, e renomear a pergunta derrubava o número na regra
    genérica sem erro nenhum. Agora o portão declara o próprio formato."""
    renomeado = candidata.portao("Uma pergunta que acabou de mudar de nome?",
                                 True, True, 0.03, "até 5%", "",
                                 formato=candidata.FRACAO_PCT)
    assert WP._fmt_portao(renomeado) == "3,0%"


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


# ------------------- região larga no Walk-Forward (01/10/2026, mudança 4)
def _textos(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(_textos(x) for x in c)
    return _textos(getattr(c, "children", None))


def _classes(c) -> list:
    out = []
    if isinstance(c, (list, tuple)):
        for x in c:
            out += _classes(x)
        return out
    if getattr(c, "className", None):
        out.append((c.className, _textos(getattr(c, "children", None))))
    filhos = getattr(c, "children", None)
    if filhos is not None and not isinstance(filhos, str):
        out += _classes(filhos)
    return out


def _perfil_folga(lucros, centro=4):
    valores = list(range(25, 25 + len(lucros)))
    trials = [{"params": {"folga_ticks": v}, "lucro": float(l)}
              for v, l in zip(valores, lucros)]
    return candidata.perfil_plato(trials, {"folga_ticks": valores},
                                  {"folga_ticks": float(valores[centro])})


def test_regiao_larga_mostra_o_selo_e_os_vizinhos_do_mais_fragil():
    perfil = _perfil_folga([7437, 7610, 7541, 7763, 8054, 8133, 9131, 8691,
                            8877, 8132])
    bloco = WP.regiao_larga(perfil, candidata.portoes_plato(perfil), run_id=56)
    t = _textos(bloco)
    assert "Parâmetros de hoje: a região é larga?" in t
    assert "Os parâmetros estão numa região larga?" in t
    assert "mineração #56" in t
    assert "29 → 8,1 mil" in t and "27 → 7,5 mil" in t
    atuais = [txt for cls, txt in _classes(bloco) if cls == "regiao-ponto atual"]
    assert atuais == ["29 → 8,1 mil"]
    # 4 para cada lado do escolhido, não a faixa inteira
    assert "34 →" not in t and "33 →" in t


def test_regiao_larga_pinta_o_vizinho_abaixo_de_60_pct():
    perfil = _perfil_folga([7437, 7610, 7541, 4000, 8054, 8133])
    bloco = WP.regiao_larga(perfil, candidata.portoes_plato(perfil))
    abaixo = [txt for cls, txt in _classes(bloco) if cls == "regiao-ponto abaixo"]
    assert abaixo == ["28 → 4,0 mil"]
    assert "✕" in _textos(bloco)


def test_regiao_larga_sem_parametro_de_hoje_diz_o_porque():
    t = _textos(WP.regiao_larga(None, None, run_id=56))
    assert "fora do mercado" in t


def test_regiao_larga_sem_janela_deploy_nao_diz_fora_do_mercado():
    """Sem linha DEPLOY nenhuma não há "última janela fora do mercado" —
    são duas histórias, e a tela não pode contar a errada."""
    t = _textos(WP.regiao_larga(None, None, run_id=56, sem_deploy=True))
    assert "fora do mercado" not in t
    assert "DEPLOY" in t
