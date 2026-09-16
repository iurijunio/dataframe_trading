"""Recortes de um backtest, para decidir o que ajustar na estratégia.

Cada função aqui responde a uma pergunta que tem AÇÃO do outro lado. Não é
relatório: é diagnóstico ligado a um campo da camada 4.

    por_hora           -> encurtar a janela de entrada?
    por_dia_semana     -> desligar algum dia?
    por_mes / por_ano  -> a estratégia vive de um regime só?
    por_motivo         -> quem paga a conta: stop, alvo, sinal ou fechamento?
    calor_mae_mfe      -> o stop está apertado? o alvo está longe demais?
    por_duracao        -> vale um tempo máximo em barras?
    distribuicao       -> o lucro vem de muitos trades ou de dois outliers?

Tudo em numpy puro sobre os arrays que o kernel já devolveu — nenhum backtest
roda de novo aqui. Módulo sem UI de propósito: é testável sozinho e a tela
pode mudar sem encostar nele.
"""

from __future__ import annotations

import numpy as np

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez"]


def _agrupar(chaves: np.ndarray, liquido: np.ndarray, rotulos=None) -> dict:
    """Soma, conta e mede expectativa por grupo.

    Expectativa é o que decide um corte: um horário com 400 trades e −R$ 2
    por trade sangra mais que um com 3 trades e −R$ 90, e o total sozinho
    esconde isso.
    """
    unicos, inv = np.unique(chaves, return_inverse=True)
    n = len(unicos)
    total = np.zeros(n)
    np.add.at(total, inv, liquido)
    qtd = np.bincount(inv, minlength=n)

    # ganho e prejuizo BRUTOS por grupo, nao so o saldo. Um horario que soma
    # zero pode ter girado muito dinheiro dos dois lados - o liquido sozinho
    # esconde essa rotatividade, que e onde o custo mora.
    ganhos = np.zeros(n)
    perdas = np.zeros(n)
    np.add.at(ganhos, inv, np.where(liquido > 0, liquido, 0.0))
    np.add.at(perdas, inv, np.where(liquido < 0, -liquido, 0.0))
    vencedores = np.zeros(n)
    np.add.at(vencedores, inv, (liquido > 0).astype(float))

    return {
        "chaves": [rotulos(u) for u in unicos] if rotulos else unicos.tolist(),
        "brutas": unicos.tolist(),
        "liquido": total.tolist(),
        "ganhos": ganhos.tolist(),
        "perdas": perdas.tolist(),
        "trades": qtd.tolist(),
        "expectativa": (total / np.maximum(qtd, 1)).tolist(),
        "win_rate": (vencedores / np.maximum(qtd, 1) * 100).tolist(),
    }


# ------------------------------------------------------------------- tempo
def por_hora(entry_ts: np.ndarray, liquido: np.ndarray) -> dict:
    horas = (entry_ts.astype("datetime64[h]").astype(np.int64) % 24)
    return _agrupar(horas, liquido, lambda h: f"{h:02d}h")


def por_dia_semana(entry_ts: np.ndarray, liquido: np.ndarray) -> dict:
    dias = entry_ts.astype("datetime64[D]").astype(np.int64)
    dow = (dias + 3) % 7          # 1970-01-01 foi quinta -> 0 = segunda
    return _agrupar(dow, liquido, lambda d: DIAS[d])


def por_mes(entry_ts: np.ndarray, liquido: np.ndarray) -> dict:
    """Mês do calendário, somando todos os anos: sazonalidade."""
    meses = entry_ts.astype("datetime64[M]").astype(np.int64) % 12
    return _agrupar(meses, liquido, lambda m: MESES[m])


def por_ano(entry_ts: np.ndarray, liquido: np.ndarray) -> dict:
    anos = entry_ts.astype("datetime64[Y]").astype(np.int64) + 1970
    return _agrupar(anos, liquido, str)


def calendario_mensal(entry_ts: np.ndarray, liquido: np.ndarray) -> dict:
    """Matriz ano × mês. Uma estratégia que só funcionou num semestre aparece
    aqui como uma faixa verde cercada de vermelho — a curva de capital
    suavizada esconde exatamente isso."""
    anos = entry_ts.astype("datetime64[Y]").astype(np.int64) + 1970
    meses = entry_ts.astype("datetime64[M]").astype(np.int64) % 12
    lista_anos = sorted(set(anos.tolist()))
    idx = {a: i for i, a in enumerate(lista_anos)}

    grade = np.full((len(lista_anos), 12), np.nan)
    soma = np.zeros((len(lista_anos), 12))
    houve = np.zeros((len(lista_anos), 12), dtype=bool)
    for a, m, v in zip(anos, meses, liquido):
        soma[idx[int(a)], int(m)] += v
        houve[idx[int(a)], int(m)] = True
    grade[houve] = soma[houve]

    return {"anos": [str(a) for a in lista_anos], "meses": MESES,
            "valores": grade.tolist()}


# ------------------------------------------------------------------ trades
def por_motivo(reason: np.ndarray, liquido: np.ndarray, rotulos: dict) -> dict:
    return _agrupar(reason, liquido, lambda r: rotulos.get(int(r), str(r)))


def por_duracao(bars_held: np.ndarray, liquido: np.ndarray,
                minutos_por_barra: int = 1,
                faixas=(1, 3, 10, 30, 60, 120)) -> dict:
    """Resultado por tempo em posição. Trade que arrasta costuma ser trade
    que deu errado — se as faixas longas sangram, um tempo máximo ajuda.

    O kernel conta barras de M1 porque a execução roda em M1. Aqui a contagem
    vira barras do TIMEFRAME da estratégia: quem opera em M15 pensa "durou 4
    candles", não "durou 60 minutos", e o campo `max_barras` da camada 4 usa
    a mesma unidade.
    """
    if minutos_por_barra > 1:
        bars_held = bars_held / minutos_por_barra
    bordas = np.array(faixas)
    # right=True para as faixas fecharem no limite: "≤1" tem que conter o
    # trade de 1 barra. Sem isso todo balde desliza uma casa e os rótulos
    # passam a descrever a faixa vizinha.
    grupo = np.digitize(bars_held, bordas, right=True)
    nomes = [f"≤{faixas[0]}"] + [f"{a+1}–{b}" for a, b in zip(faixas, faixas[1:])] \
        + [f">{faixas[-1]}"]
    return _agrupar(grupo, liquido, lambda g: nomes[int(g)] + " barras")


def distribuicao(liquido: np.ndarray, bins: int = 31) -> dict:
    """Histograma dos resultados, com largura de balde REDONDA.

    Baldes de R$ 37,4189 são ilegíveis: ninguém lê o eixo. A largura é
    arredondada para 1, 2, 2,5 ou 5 vezes uma potência de dez, e os baldes
    são alinhados ao zero — assim existe uma fronteira exata entre ganho e
    prejuízo, em vez de um balde que cruza o zero e mistura os dois.

    A cauda é aparada no p1/p99 porque um único trade de R$ 3.000 esticava a
    escala e espremia 99% dos dados em duas colunas. O que ficou de fora
    aparece contado nas pontas.
    """
    if not len(liquido):
        return {"centros": [], "contagem": [], "largura": 0,
                "fora_esq": 0, "fora_dir": 0, "mediana": 0.0, "media": 0.0}

    lo, hi = np.percentile(liquido, [1, 99])
    if hi <= lo:
        lo, hi = float(liquido.min()), float(liquido.max()) or 1.0

    bruta = max((hi - lo) / bins, 1e-9)
    escala = 10 ** np.floor(np.log10(bruta))
    for mult in (1, 2, 2.5, 5, 10):
        largura = mult * escala
        if largura >= bruta:
            break

    inicio = np.floor(lo / largura) * largura
    fim = np.ceil(hi / largura) * largura
    bordas = np.arange(inicio, fim + largura / 2, largura)

    dentro = liquido[(liquido >= bordas[0]) & (liquido <= bordas[-1])]
    cont, _ = np.histogram(dentro, bins=bordas)
    centros = (bordas[:-1] + bordas[1:]) / 2

    return {
        "centros": centros.tolist(),
        "contagem": cont.tolist(),
        "largura": float(largura),
        "fora_esq": int((liquido < bordas[0]).sum()),
        "fora_dir": int((liquido > bordas[-1]).sum()),
        "mediana": float(np.median(liquido)),
        "media": float(liquido.mean()),
    }


def calor_mae_mfe(mae: np.ndarray, mfe: np.ndarray,
                  liquido: np.ndarray) -> dict:
    """O diagnóstico mais direto para calibrar stop, alvo e breakeven.

    MAE é o quanto o trade andou CONTRA antes de fechar; MFE, o quanto andou
    a favor. Duas leituras saem daqui:

      - MAE dos trades VENCEDORES: quanto de prejuízo temporário foi preciso
        aguentar para ganhar. Um stop menor que o p95 disso teria matado 5%
        dos seus ganhadores.
      - MFE dos trades PERDEDORES: quanto de lucro eles chegaram a mostrar
        antes de virar. Se a mediana for alta, breakeven ou trailing salvam
        dinheiro que hoje escorre.
    """
    ganhou = liquido > 0
    perdeu = ~ganhou

    def pct(arr, p):
        return float(np.percentile(np.abs(arr), p)) if len(arr) else 0.0

    return {
        "mae": np.abs(mae).tolist(),
        "mfe": mfe.tolist(),
        "liquido": liquido.tolist(),
        "ganhou": ganhou.tolist(),
        "mae_ganhadores_p50": pct(mae[ganhou], 50),
        "mae_ganhadores_p95": pct(mae[ganhou], 95),
        "mfe_perdedores_p50": pct(mfe[perdeu], 50),
        "mfe_perdedores_p95": pct(mfe[perdeu], 95),
        "n_ganhadores": int(ganhou.sum()),
        "n_perdedores": int(perdeu.sum()),
    }


def sugestoes(diag: dict, stop_atual: int, alvo_atual: int) -> list[str]:
    """Traduz o MAE/MFE em frases acionáveis, sem inventar certeza.

    Nunca afirma "mude para X": diz o que os dados mostram e qual campo
    mexer. A decisão continua sua.
    """
    fora = []
    p95 = diag["mae_ganhadores_p95"]
    if diag["n_ganhadores"] >= 20 and stop_atual:
        if p95 > stop_atual * 0.95:
            fora.append(
                f"5% dos ganhadores aguentaram mais de {p95:.0f} pontos contra, "
                f"perto do stop de {stop_atual}. Um stop mais largo pode salvá-los."
            )
        elif p95 < stop_atual * 0.5:
            fora.append(
                f"nenhum ganhador passou de ~{p95:.0f} pontos contra, metade do "
                f"stop de {stop_atual}. Apertar o stop tende a cortar perda sem "
                "perder ganho."
            )

    mfe = diag["mfe_perdedores_p50"]
    if diag["n_perdedores"] >= 20 and alvo_atual and mfe > alvo_atual * 0.3:
        fora.append(
            f"metade dos perdedores chegou a mostrar {mfe:.0f} pontos de lucro "
            f"({mfe / alvo_atual * 100:.0f}% do alvo) antes de virar. "
            "Breakeven ou stop móvel recuperam parte disso."
        )
    return fora
