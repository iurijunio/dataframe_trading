"""Leitura da varredura inteira, e não da melhor combinação.

Depois de minerar, a pergunta que decide não é *"qual foi o melhor?"* — é
**"como está a região?"**. Se 80% das combinações do cluster dão lucro,
qualquer ponto ali dentro funciona e escolher o campeão é detalhe. Se 5% dão,
você achou ruído com uma sorte dentro, e o campeão é justamente a sorte.

    resumo   -> a região é sadia? (passo 5 da metodologia)
    curva    -> platô ou precipício?
    avaliar  -> quantas passam nos meus critérios, e qual critério corta

Tudo opera sobre as linhas que a mineração já montou (`Mineracao.estado
["trials"]`), então roda em milissegundos e não encosta no motor.
"""

from __future__ import annotations

import numpy as np

# Os critérios de aceite, com faixas de partida para day trade de mini
# índice. Não são lei: são o ponto de onde se começa a discutir. O que eles
# impedem é a régua esticar depois, para acomodar o resultado de que você
# gostou.
CRITERIOS = [
    {"id": "trades", "rotulo": "nº de operações", "campo": "trades",
     "maior": True, "padrao": 300, "passo": 10, "sufixo": "",
     "dica": "Tamanho da amostra de cada combinação. Abaixo de ~300 no "
             "período, quase nada é conclusivo — e a combinação campeã "
             "costuma ser a que operou pouco e teve sorte."},
    {"id": "pf", "rotulo": "profit factor", "campo": "pf",
     "maior": True, "padrao": 1.25, "passo": 0.05, "sufixo": "",
     "dica": "Quanto se ganha para cada R$ 1 perdido, líquido. Abaixo de 1,0 "
             "perde dinheiro. De 1,2 a 1,6 é o normal de sistema real de day "
             "trade; acima de 2,0 com poucos trades costuma ser sobreajuste."},
    {"id": "fr", "rotulo": "fator de recuperação", "campo": "fr",
     "maior": True, "padrao": 2.0, "passo": 0.1, "sufixo": "",
     "dica": "Lucro dividido pelo drawdown máximo: quantas vezes a estratégia "
             "repôs o pior mergulho que deu. Abaixo de 1,0 o lucro do período "
             "inteiro não cobre um drawdown. É o critério padrão de "
             "otimização do MT5."},
    {"id": "consistencia", "rotulo": "janelas positivas", "campo": "consistencia",
     "maior": True, "padrao": 60, "passo": 5, "sufixo": "%",
     "dica": "Percentual das janelas de teste do walk-forward em que a "
             "combinação lucrou. É o critério que separa 'rendeu' de 'rendeu "
             "de novo'. Abaixo de 50% o lucro total veio de um período só."},
    {"id": "mediana", "rotulo": "mediana por período", "campo": "mediana_fold",
     "maior": True, "padrao": 0, "passo": 100, "sufixo": "",
     "dica": "O resultado da janela mediana do walk-forward. Exigir acima de "
             "zero elimina a combinação que soma lucro no total mas perde na "
             "maioria dos períodos — o caso clássico do degrau."},
    {"id": "dd", "rotulo": "drawdown máximo", "campo": "dd",
     "maior": False, "padrao": 2500, "passo": 100, "sufixo": "",
     "dica": "O maior mergulho em reais, como teto. Referência: 25% do "
             "capital. É o critério que costuma reprovar as combinações mais "
             "lucrativas — e é por isso que ele existe."},
    {"id": "lucro", "rotulo": "lucro total", "campo": "lucro",
     "maior": True, "padrao": 0, "passo": 500, "sufixo": "",
     "dica": "Piso de lucro líquido no período de otimização. Deixe em zero "
             "para não filtrar por aqui: os outros critérios já cortam o que "
             "importa, e um piso alto demais devolve só as combinações mais "
             "ajustadas ao passado."},
]

# métricas que a distribuição sabe desenhar
METRICAS = [
    ("lucro total", "lucro"),
    ("fator de recuperação", "fr"),
    ("score robusto", "robusto"),
    ("consistência %", "consistencia"),
    ("mediana por período", "mediana_fold"),
    ("profit factor", "pf"),
    ("drawdown", "dd"),
    ("trades", "trades"),
]
DINHEIRO = {"lucro", "mediana_fold", "dd"}


def _vals(trials, chave) -> np.ndarray:
    return np.array([t[chave] for t in trials
                     if t.get(chave) is not None], dtype=float)


def resumo(trials: list[dict]) -> dict:
    """A saúde da região varrida, em números.

    `razao_melhor_mediana` é o cartão mais desconfortável e o mais útil: se o
    campeão faz vinte vezes a mediana da região, ele não representa a região —
    ele é o ponto que mais se ajustou ao passado, e é exatamente o que não se
    repete fora da amostra.
    """
    v = _vals(trials, "lucro")
    if not len(v):
        return {}
    mediana = float(np.median(v))
    melhor = float(v.max())
    cons = _vals(trials, "consistencia")
    return {
        "n": int(len(v)),
        "pct_lucrativas": float((v > 0).mean() * 100),
        "n_lucrativas": int((v > 0).sum()),
        "mediana": mediana,
        "media": float(v.mean()),
        "melhor": melhor,
        "pior": float(v.min()),
        "p25": float(np.percentile(v, 25)),
        "p75": float(np.percentile(v, 75)),
        # so faz sentido quando a mediana e positiva: com mediana negativa a
        # razao inverte de sinal e diria o contrario do que parece
        "razao_melhor_mediana": (melhor / mediana) if mediana > 0 else None,
        "pct_consistentes": (float((cons >= 60).mean() * 100)
                             if len(cons) else None),
    }


def curva(trials: list[dict], chave: str = "lucro") -> dict:
    """As combinações ordenadas da melhor para a pior.

    A forma responde de imediato: uma descida suave é platô — vizinhos valem
    quase o mesmo, e errar o ponto não custa caro. Um degrau nos primeiros
    pontos é precipício: meia dúzia de combinações carrega a região inteira,
    e escolher entre elas é escolher qual sorte levar para o live.
    """
    v = _vals(trials, chave)
    if not len(v):
        return {}
    ordenado = np.sort(v)[::-1]
    pct = (np.arange(len(ordenado)) + 1) / len(ordenado) * 100
    return {
        "pct": pct.tolist(),
        "valores": ordenado.tolist(),
        "mediana": float(np.median(ordenado)),
        "chave": chave,
    }


def _passa(linha: dict, crit: dict, limite) -> bool | None:
    """None quando a combinação não tem o valor — não conta como reprovada.

    O fator de recuperação fica vazio quando o drawdown é zero (divisão por
    zero): é a combinação que nunca afundou, e reprová-la por falta de dado
    seria eliminar justamente a melhor.
    """
    v = linha.get(crit["campo"])
    if v is None or limite is None:
        return None
    return v >= limite if crit["maior"] else v <= limite


def avaliar(trials: list[dict], limiares: dict) -> dict:
    """Quantas combinações passam em cada critério e em todos eles.

    O `por_criterio` é o que diz **onde mexer**: se 90% passam em tudo e 4%
    passam no drawdown, o drawdown é o critério que manda — afrouxá-lo ou
    aceitar menos candidatas é a decisão, e ela fica explícita.
    """
    if not trials:
        return {}

    por_criterio, aprovadas = [], []
    for c in CRITERIOS:
        lim = limiares.get(c["id"])
        marcas = [_passa(l, c, lim) for l in trials]
        avaliadas = [m for m in marcas if m is not None]
        por_criterio.append({
            "id": c["id"], "rotulo": c["rotulo"], "limite": lim,
            "ativo": lim is not None,
            # ligado E com dado para responder. Um critério que ninguém pôde
            # atender por falta do número não reprova ninguém — e não pode
            # aparecer como "o que mais corta".
            "avaliavel": bool(avaliadas),
            "passam": int(sum(avaliadas)),
            "avaliadas": len(avaliadas),
            "pct": (float(sum(avaliadas) / len(avaliadas) * 100)
                    if avaliadas else None),
        })

    for linha in trials:
        if all(_passa(linha, c, limiares.get(c["id"])) is not False
               for c in CRITERIOS):
            aprovadas.append(linha)

    return {
        "total": len(trials),
        "n_aprovadas": len(aprovadas),
        "pct": float(len(aprovadas) / len(trials) * 100),
        "aprovadas": aprovadas,
        "por_criterio": por_criterio,
        # O critério que mais corta — e só quando ele CORTA. Duas exclusões,
        # cada uma de um sintoma real: sem o `< 100`, com todas as
        # combinações passando, o min() devolvia o primeiro da lista e a tela
        # o pintava de vermelho; sem o `avaliavel`, um critério que ninguém
        # tinha o dado para responder (fator de recuperação vazio quando o
        # drawdown é zero) ficava com 0% e virava o gargalo — barra vermelha
        # em 0% ao lado de "aproveitamento 100%".
        "gargalo": min((c for c in por_criterio
                        if c["ativo"] and c["avaliavel"] and c["pct"] < 100),
                       key=lambda c: c["pct"], default=None),
        "sem_dado": [c["rotulo"] for c in por_criterio
                     if c["ativo"] and not c["avaliavel"]],
    }
