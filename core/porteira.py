"""A porteira: a varredura inteira passa, ou não passa?

A aba Critérios pergunta *quais combinações* servem. Esta pergunta é
anterior e mais dura: **esta mineração merece seguir para os próximos
passos?** Uma varredura pode ter dez combinações aprovadas e ainda assim ser
lixo, se essas dez forem exceções num universo que não funciona.

Duas armadilhas de estatística que este módulo evita de propósito, porque
são erros comuns e caros:

**Não multiplicar por √N.** O SQN de Van Tharp faz isso, e está certo lá: N
são os TRADES, e mais trades é mais evidência. Aqui N são as combinações que
você escolheu testar — testar mais combinações não é mais evidência de nada.
Multiplicar por √N faria uma varredura ruim de 5 mil pontos parecer melhor
que uma boa de 200.

**Não fazer teste t sobre as combinações.** Vizinhos na grade compartilham
quase todos os trades: média rápida 9 e média rápida 10 operam quase os
mesmos dias. As combinações são fortemente dependentes entre si, e um
p-valor calculado sobre elas seria absurdamente otimista. O que vale aqui é
a estatística descritiva — média, desvio, Z — e não a inferencial.

Referências dos limiares nos comentários de cada portão.
"""

from __future__ import annotations

import numpy as np

# Limiares dos portões. Separados em CRÍTICO (reprova a varredura) e
# RESSALVA (passa, mas com aviso na tela).
LIMIARES = {
    "min_combinacoes": 30,      # abaixo disto, estatística de distribuição não diz nada
    "min_pct_positivas": 60.0,  # a maioria da região precisa funcionar
    "min_z": 1.0,               # média a menos de 1σ de zero é região frouxa
    "z_forte": 3.0,             # média − 3σ > 0: o padrão "três sigma"
    "max_razao": 10.0,          # campeão até 10× a mediana ainda pertence à região
    "max_cv": 1.0,              # desvio maior que a média é dispersão demais
    "max_assimetria": 1.5,      # cauda direita longa = lucro em poucas combinações
    "max_pct_amostra_fraca": 30.0,
}


def _momentos(v: np.ndarray) -> tuple[float, float]:
    """Assimetria e curtose em excesso, sem scipy.

    Assimetria positiva alta significa cauda à direita: a maioria das
    combinações rende pouco e um punhado rende muito — a assinatura de
    região que depende de poucos pontos.
    """
    n = len(v)
    if n < 3:
        return 0.0, 0.0
    desvio = v.std(ddof=0)
    if desvio == 0:
        return 0.0, 0.0
    z = (v - v.mean()) / desvio
    return float((z ** 3).mean()), float((z ** 4).mean() - 3.0)


def estatisticas(trials: list[dict], chave: str = "lucro") -> dict:
    """A descrição numérica da varredura — a lista que decide a porteira.

    `z` é a média dividida pelo desvio padrão: **quantos desvios separam a
    média de zero**. E ele responde de uma vez a pergunta dos "três desvios",
    porque as duas formulações são a mesma conta:

        média − 3·σ > 0    ⟺    média / σ > 3    ⟺    Z > 3

    Ou seja, exigir que a média sobreviva a um choque de três desvios é
    idêntico a exigir Z ≥ 3. Não são técnicas concorrentes; são a mesma, uma
    escrita em reais e a outra em desvios.
    """
    if not trials:
        return {}

    v = np.array([t[chave] for t in trials if t.get(chave) is not None],
                 dtype=float)
    if not len(v):
        return {}

    total = len(trials)
    trades = np.array([t.get("trades") or 0 for t in trials], dtype=float)
    fracas = sum(1 for t in trials if t.get("filtro") not in (None, "ok"))

    media = float(v.mean())
    # ddof=1: é uma amostra do espaço de parâmetros, não a população dele
    desvio = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    # sem dispersao o Z e infinito, com o SINAL da media: uma regiao em que
    # todas as combinacoes perdem exatamente o mesmo devolvia 0,00, que se le
    # como "neutro" quando o correto e "reprovada com folga"
    if desvio > 0:
        z = media / desvio
    else:
        z = float("inf") if media > 0 else (0.0 if media == 0 else float("-inf"))
    assimetria, curtose = _momentos(v)

    positivos = int((v > 0).sum())
    negativos = int((v < 0).sum())
    return {
        "chave": chave,
        "total": total,
        "avaliadas": int(len(v)),
        "positivos": positivos,
        "negativos": negativos,
        "zerados": int(len(v) - positivos - negativos),
        "pct_positivas": float(positivos / len(v) * 100),
        "sem_trades": int((trades == 0).sum()),
        "amostra_fraca": fracas,
        "pct_amostra_fraca": float(fracas / total * 100),
        "media": media,
        "mediana": float(np.median(v)),
        "desvio": desvio,
        "z": float(z),
        # o limite conservador em reais: o que sobra da média depois de um
        # choque de três desvios
        "media_menos_3s": media - 3 * desvio,
        "media_menos_1s": media - desvio,
        # dispersão relativa: desvio como fração da média
        "cv": float(desvio / abs(media)) if media else None,
        "assimetria": assimetria,
        "curtose": curtose,
        "dentro_1s": float((np.abs(v - media) <= desvio).mean() * 100),
        "melhor": float(v.max()),
        "pior": float(v.min()),
        "razao_melhor_mediana": (float(v.max() / np.median(v))
                                 if np.median(v) > 0 else None),
    }


def _portao(nome, ok, critico, valor, exigido, dica, detalhe=None) -> dict:
    """Um portão. `valor` pode ser None quando a métrica não existe."""
    return {"nome": nome, "ok": bool(ok), "critico": critico, "valor": valor,
            "exigido": exigido, "dica": dica, "detalhe": detalhe,
            # None quando não dá para avaliar: não conta como reprovação
            "avaliavel": ok is not None}


def portoes(e: dict, lim: dict | None = None) -> list[dict]:
    """Os portões, em ordem do que reprova mais rápido para o mais fino."""
    if not e:
        return []
    L = {**LIMIARES, **(lim or {})}

    k = L["z_forte"]
    fora = [
        _portao(
            "amostra da varredura", e["avaliadas"] >= L["min_combinacoes"], True,
            e["avaliadas"], f"≥ {L['min_combinacoes']} combinações",
            "Quantas combinações a varredura produziu. Abaixo de 30, média e "
            "desvio padrão não descrevem nada — qualquer conclusão sobre a "
            "'região' seria sobre meia dúzia de pontos. Não é defeito da "
            "estratégia: é varredura pequena demais para responder à "
            "pergunta. Alargue a faixa ou diminua o passo."),
        _portao(
            "média da região", e["media"] > 0, True,
            e["media"], "> 0",
            "O resultado médio de TODAS as combinações varridas, não o do "
            "campeão. Média negativa com campeão positivo é o retrato exato "
            "de uma região que não funciona e tem uma sorte dentro. Se este "
            "portão reprova, o cluster está no lugar errado — voltar ao passo "
            "2 custa menos que insistir."),
        _portao(
            "combinações lucrativas", e["pct_positivas"] >= L["min_pct_positivas"],
            True, e["pct_positivas"], f"≥ {L['min_pct_positivas']:.0f}%",
            "Percentual da região que fecha no azul. É a medida direta de "
            "platô: acima de 70% quase qualquer ponto serve e errar a escolha "
            "sai barato. Abaixo de 30% você está escolhendo entre exceções, e "
            "exceção não se repete fora da amostra. O portão reprova abaixo "
            "de 60%, que é o meio termo entre as duas faixas."),
        _portao(
            "Z-score da região", e["z"] >= L["min_z"], True,
            e["z"], f"≥ {L['min_z']:.1f}",
            "Média dividida pelo desvio padrão: quantos desvios separam a "
            "média de zero. Abaixo de 1,0 a região é frouxa — o resultado "
            "típico está a menos de um desvio do prejuízo, e uma mudança "
            "pequena de mercado leva a região para o vermelho. "
            "ATENÇÃO: aqui NÃO se multiplica por √N como no SQN de Van Tharp. "
            "Lá o N são trades, e mais trades é mais evidência; aqui o N são "
            "as combinações que você escolheu testar, e testar mais não prova "
            "nada — inflaria o número de graça."),
        _portao(
            f"{k:.0f} desvios (média − {k:.0f}σ)",
            e["media"] - k * e["desvio"] > 0, False,
            e["media"] - k * e["desvio"], "> 0",
            "O que sobra da média depois de um choque de três desvios padrão. "
            "Positivo significa que mesmo num cenário muito ruim a região "
            "ainda lucra — é o critério 'três sigma', o mais conservador de "
            "uso comum. Este portão e o Z-score são A MESMA conta escrita de "
            "duas formas: média − 3σ > 0 é idêntico a Z > 3. Um em reais, o "
            "outro em desvios. Reprovar aqui não condena a varredura; é "
            "ressalva, porque exigir três sigma de um espaço de parâmetros é "
            "exigência de sistema excepcional."),
        _portao(
            "campeão dentro da região",
            (e["razao_melhor_mediana"] is None
             or e["razao_melhor_mediana"] <= L["max_razao"]),
            False, e["razao_melhor_mediana"], f"≤ {L['max_razao']:.0f}×",
            "Quantas vezes o melhor resultado supera a mediana da região. Até "
            "3× o campeão ainda é um membro da região. Acima de 10× ele não "
            "representa mais nada além de si mesmo: é o ponto que mais se "
            "ajustou ao passado, e escolhê-lo é escolher o sobreajuste. Fica "
            "vazio quando a mediana é negativa — aí a razão inverteria de "
            "sinal e mentiria."),
        _portao(
            "dispersão (σ ÷ média)",
            (e["cv"] is None or e["cv"] <= L["max_cv"]), False,
            e["cv"], f"≤ {L['max_cv']:.1f}",
            "Coeficiente de variação: o desvio padrão como fração da média. "
            "Abaixo de 0,5 a região é homogênea — vizinhos valem quase o "
            "mesmo. Acima de 1,0 o desvio é maior que a própria média, ou "
            "seja, o resultado depende mais de qual ponto você escolheu do "
            "que da estratégia."),
        _portao(
            "assimetria da distribuição",
            e["assimetria"] <= L["max_assimetria"], False,
            e["assimetria"], f"≤ {L['max_assimetria']:.1f}",
            "Mede o quanto a distribuição pende para um lado. Perto de zero é "
            "simétrica. Assimetria alta e positiva é cauda longa à direita: a "
            "maioria das combinações rende pouco e um punhado rende muito — a "
            "assinatura de região que depende de poucos pontos, mesmo quando "
            "a média parece boa."),
        _portao(
            "combinações com amostra fraca",
            e["pct_amostra_fraca"] <= L["max_pct_amostra_fraca"], False,
            e["pct_amostra_fraca"], f"≤ {L['max_pct_amostra_fraca']:.0f}%",
            "Percentual de combinações reprovadas no mínimo de operações. "
            "Muitas combinações com poucos trades significa que a faixa "
            "varrida está entrando em território onde a estratégia quase não "
            "opera — a região boa provavelmente é menor do que a faixa que "
            "você varreu, e a estatística está diluída com pontos vazios."),
    ]
    return fora


def avaliar(trials: list[dict], chave: str = "lucro",
            lim: dict | None = None) -> dict:
    """Estatísticas + portões + veredito, numa chamada.

    O veredito tem três estados, e não dois, porque reprovar uma varredura
    por não atingir três sigma seria reprovar quase tudo: **aprovada**,
    **aprovada com ressalva** (passou no que é crítico, falhou em algum
    alerta) e **reprovada** (falhou em algo crítico).
    """
    e = estatisticas(trials, chave)
    if not e:
        return {}
    ps = portoes(e, lim)

    criticos_ruins = [p for p in ps if p["critico"] and not p["ok"]]
    ressalvas = [p for p in ps if not p["critico"] and not p["ok"]]

    if criticos_ruins:
        estado, cor = "reprovada", "neg"
    elif ressalvas:
        estado, cor = "aprovada com ressalva", "warn"
    else:
        estado, cor = "aprovada", "pos"

    return {
        "estatisticas": e,
        "portoes": ps,
        "estado": estado,
        "cor": cor,
        "n_ok": sum(1 for p in ps if p["ok"]),
        "n_portoes": len(ps),
        "reprovados": criticos_ruins,
        "ressalvas": ressalvas,
    }


# ------------------------------------------------------- qualidade do sistema
def sqn(liquido: np.ndarray, teto_n: int = 100) -> dict:
    """System Quality Number, de Van Tharp — sobre os TRADES de um sistema.

    SQN = √N × média ÷ desvio padrão dos resultados dos trades.

    Diferente do Z-score da varredura, aqui multiplicar por √N está correto:
    N são trades, e mais trades são mais evidência de que a expectativa é
    real. O teto de 100 é do próprio Tharp e existe para impedir que
    estratégia de giro altíssimo ganhe nota alta só pelo volume — sem ele,
    dez mil trades medíocres batem quinhentos excelentes.

    Faixas de Tharp: abaixo de 1,6 é difícil de operar; 1,6–1,9 abaixo da
    média; 2,0–2,4 média; 2,5–2,9 bom; 3,0–5,0 excelente; 5,1–6,9 soberbo;
    acima de 7,0 excepcional (e, na prática, motivo para desconfiar do
    backtest antes de comemorar).
    """
    n = len(liquido)
    if n < 2:
        return {}
    media = float(liquido.mean())
    desvio = float(liquido.std(ddof=1))
    if desvio == 0:
        return {}

    n_efetivo = min(n, teto_n)
    valor = float(np.sqrt(n_efetivo) * media / desvio)

    if valor < 1.6:
        faixa = "abaixo do operável"
    elif valor < 2.0:
        faixa = "abaixo da média"
    elif valor < 2.5:
        faixa = "média"
    elif valor < 3.0:
        faixa = "bom"
    elif valor < 5.0:
        faixa = "excelente"
    elif valor < 7.0:
        faixa = "soberbo"
    else:
        faixa = "excepcional — confira o backtest"

    return {
        "sqn": valor, "faixa": faixa, "n": n, "n_efetivo": n_efetivo,
        "media": media, "desvio": desvio,
        "limitado": n > teto_n,
    }
