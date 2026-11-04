"""O que a busca automática pode varrer, declarado num lugar só.

A tela de configuração, a busca e o relatório percorrem ESTA lista; nenhum
deles conhece um parâmetro pelo nome. Parâmetro novo da estratégia entra pelo
`params_schema`; parâmetro global novo (ex.: preço médio) entra como mais um
`Item` aqui. É o requisito de escala do desenho (§6).

Cada item diz a sua CAMADA. "essencial" muda o sinal e obriga a recalcular o
indicador (`engine.preparar`); "filtro" só roda por cima do sinal pronto
(`engine.executar`). É o que deixa a busca calcular uma vez e testar muitas.

As declarações por estratégia (que parâmetro anda em degrau proporcional)
moram aqui, e não no arquivo da estratégia: mexer no arquivo muda o
`codigo_hash`, e um plano operando na conta real passaria a acusar "código
mudou". Estratégia nova pode trazer `busca = {...}` no próprio módulo.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from core import ativo
from core.engine.execution import TIMEFRAMES as _TF_MOTOR

# Parâmetros de período: 250 e 251 dão quase o mesmo, então o degrau cresce
# com o valor (desenho §4.4).
POR_ESTRATEGIA: dict[str, dict] = {
    "adx_direcao": {"proporcional": ["di_periodo", "adx_suavizacao"]},
    "setup_cruzamento": {"proporcional": ["media_rapida", "media_lenta"]},
    "reversao_rsi": {"proporcional": ["periodo_rsi", "periodo_tendencia",
                                      "periodo_saida"]},
    "rompimento_abertura": {"proporcional": ["barras_abertura"]},
    "rompimento_ema_abertura": {"proporcional": ["ema_curta", "ema_longa"]},
    "rompimento_canal": {"proporcional": ["periodo_canal"]},
}

# Espelho do motor: todo tempo gráfico que o motor conhece entra aqui sozinho,
# em ordem de duração. Marcados de saída: de 2 a 30 minutos.
TIMEFRAMES = sorted(_TF_MOTOR, key=_TF_MOTOR.get)
TIMEFRAMES_LIGADOS = [t for t in TIMEFRAMES if 2 <= _TF_MOTOR[t] <= 30]
DIRECOES = ["compra", "venda", "ambas"]

# A sessão de ENTRADAS que a busca percorre. Nos micros é o pregão diurno de
# Nova York: a ficha vai de 18:00 a 16:30, atravessando a meia-noite, e uma
# janela "das 20:00 às 03:00" não é o que se procura aqui.
JANELA_PADRAO = {"WIN$N": ("09:00", "17:00")}
JANELA_CME = ("09:30", "16:00")
PASSO_JANELA = 30
JANELA_MINIMA = 30

# Stop e alvo em pontos saem do stop/alvo PADRÃO da ficha do ativo
# (`perfil_padrao`), na mesma proporção para todo ativo: passo = padrão / 6,
# até = padrão × 20/3. No WIN (300/600) dá 50–2.000 e 100–4.000. Largos de
# propósito (decisão do usuário, 04/11/2026): a busca não testa tudo,
# escolhe onde testar — faixa estreita só esconde trade bom de 1.200 pts.
# Ativo novo entra sozinho pela ficha. Sem padrão na ficha, vale isto:
PONTOS_SEM_FAIXA = {
    "stop_pontos": {"de": 50, "ate": 2000, "passo": 50},
    "alvo_pontos": {"de": 100, "ate": 4000, "passo": 100},
}
# Período do ATR do stop e do alvo: de 5 em 5. Busca gravada sem "passo"
# (ou passo vazio na tela) anda em degrau proporcional, como as médias.
ATR_PERIODO = {"de": 5, "ate": 60, "passo": 5}
# Múltiplos e porcentagens valem para qualquer ativo.
STOP_TIPOS = {
    "atr": {"on": True, "de": 0.25, "ate": 6.0, "passo": 0.25, "periodo": dict(ATR_PERIODO)},
    "percentual": {"on": True, "de": 0.05, "ate": 1.50, "passo": 0.05},
    # stop em pontos = 0: o kernel trata como "sem stop" (sai pela saída da
    # estratégia, tempo máximo ou fechamento)
    "sem": {"on": False},
}
ALVO_TIPOS = {
    "multiplicador": {"on": True, "de": 0.5, "ate": 6.0, "passo": 0.5},
    "atr": {"on": True, "de": 0.5, "ate": 10.0, "passo": 0.25, "periodo": dict(ATR_PERIODO)},
    "percentual": {"on": False, "de": 0.10, "ate": 3.0, "passo": 0.10},
    # alvo em pontos = 0: o kernel trata como "sem alvo"
    "sem": {"on": False},
}


# Todo campo do perfil de execução do motor tem lugar aqui. Campo novo no
# motor quebra `test_todo_campo_do_motor_esta_classificado` até ser posto
# numa das listas abaixo (ou virar extra) — ninguém precisa conferir um por um (04/11/2026).
JA_NA_BUSCA = {"timeframe", "entrada_inicio", "entrada_fim", "dias_semana", "direcao",
               "alvo_tipo", "alvo_pontos", "alvo_atr_periodo", "alvo_atr_mult",
               "alvo_razao", "alvo_pct", "stop_tipo", "stop_pontos", "stop_atr_periodo",
               "stop_atr_mult", "stop_pct"}
# custo e tamanho não são vantagem a achar: são fatos da conta
NAO_MINERAVEIS = {"corretagem_por_contrato", "emolumentos_por_contrato", "slippage_ticks",
                  "modo_posicao", "contratos", "risco_por_trade", "capital_inicial",
                  "min_operacoes"}
# a busca não varre (decisão do usuário, 04/11/2026): valem o do menu
# (`perfil_base`) e aparecem no bloco "Fixos". Buscas criadas antes disso os
# varriam e reabrem com eles (`Espaco.de_json`), por isso `_extras` ainda os
# declara.
# "Sem entradas" e o filtro ADX saíram em 04/11/2026, também a pedido.
FORA_DA_BUSCA = {"step_gatilho_pct", "step_distancia_pct", "trailing_pontos",
                 "sem_entrada1", "sem_entrada2", "sem_entrada3", "filtro_adx",
                 "adx_periodo", "adx_limiar", "adx_filtro_di", "adx_subindo"}


@dataclass(frozen=True)
class Item:
    nome: str
    rotulo: str
    tipo: str      # "lista" | "inteiro" | "real" | "hora" | "dias" | "gestao"
    camada: str    # "essencial" | "filtro"
    degrau: str    # "fixo" | "proporcional" | "minutos" | "-"
    padrao: dict = field(hash=False, compare=False)
    onde: str = "perfil"   # "param" (estratégia) | "perfil" (camada 4) | "extra"
    limites: tuple | None = None   # min/max duros do schema


def degraus_proporcionais(de: int, ate: int) -> list[int]:
    """Perto de zero anda de 1 em 1; lá em cima ~8% (250 -> 270)."""
    out, v = [], int(de)
    while v <= ate:
        out.append(v)
        v = max(v + 1, int(round(v * 1.08)))
    if out and out[-1] != ate and ate > out[-1]:
        out.append(int(ate))
    return out


def _grade(de, ate, passo, inteiro: bool) -> list:
    """Mesma régua de `optimizer.montar_espaco`: (2,3 - 2,0) / 0,1 dá
    2,9999… e o int() cortaria o último valor; arredondar antes."""
    if passo is None or passo <= 0 or ate < de:
        return [de]
    n = int(round((ate - de) / passo, 9)) + 1
    casas = max(len(f"{passo:.10f}".rstrip("0").split(".")[1]),
                len(f"{de:.10f}".rstrip("0").split(".")[1]))
    vals = [round(de + i * passo, casas) for i in range(n)]
    if inteiro:
        return sorted({int(round(v)) for v in vals})
    return vals


def _min(hhmm: str) -> int:
    return ativo.hora_para_minuto(hhmm)


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _mascaras(dias: list[int]) -> list[tuple[int, ...]]:
    """Toda combinação não vazia dos dias ligados: 1 dia, depois 2… e, dentro
    de cada tamanho, de segunda para sexta."""
    dias = sorted(dias)
    return [c for k in range(1, len(dias) + 1)
            for c in itertools.combinations(dias, k)]


def valores(item: Item, faixa: dict):
    """A lista que a busca percorre para `item` com a `faixa` da tela.

    Gestão (stop/alvo) devolve {tipo: [valores]} só dos tipos ligados.
    """
    if item.tipo == "lista":
        ligados = faixa.get("ligados", item.padrao.get("ligados", item.padrao["valores"]))
        return [v for v in item.padrao["valores"] if v in ligados]
    if item.tipo == "dias":
        return _mascaras(faixa.get("ligados", item.padrao["ligados"]))
    if item.tipo == "hora":
        de, ate = _min(faixa["de"]), _min(faixa["ate"])
        passo = int(faixa.get("passo") or PASSO_JANELA)
        out = [_hhmm(m) for m in range(de, ate + 1, passo)]
        if item.nome != "janela" and de <= ate and out[-1] != _hhmm(ate):
            out.append(_hhmm(ate))
        return out
    if item.tipo == "gestao":
        out = {}
        for tipo, f in (faixa.get("tipos") or {}).items():
            if not f.get("on"):
                continue
            if tipo == "sem":
                out[tipo] = [0]
            else:
                out[tipo] = _grade(f["de"], f["ate"], f["passo"],
                                   inteiro=(tipo == "pontos"))
        return out
    # inteiro / real
    de, ate = faixa["de"], faixa["ate"]
    if item.limites:
        lo, hi = item.limites
        de = max(de, lo) if lo is not None else de
        ate = min(ate, hi) if hi is not None else ate
    if item.degrau == "proporcional":
        return degraus_proporcionais(int(de), int(ate))
    return _grade(de, ate, faixa.get("passo", item.padrao.get("passo")),
                  inteiro=(item.tipo == "inteiro"))


def _declaracao(mod, estrategia: str) -> dict:
    return getattr(mod, "busca", None) or POR_ESTRATEGIA.get(estrategia, {})


def _janela_padrao(simbolo: str) -> tuple[str, str]:
    if simbolo in JANELA_PADRAO:
        return JANELA_PADRAO[simbolo]
    try:
        f = ativo.ficha(simbolo)
    except FileNotFoundError:
        return JANELA_PADRAO["WIN$N"]
    if f.sessao_abertura:
        return JANELA_CME
    p = f.perfil_padrao or {}
    return p.get("entrada_inicio", "09:00"), p.get("entrada_fim", "17:00")


def _pontos(simbolo: str, campo: str) -> dict:
    """Faixa de stop/alvo em pontos a partir do padrão da ficha do ativo."""
    try:
        padrao = (ativo.ficha(simbolo).perfil_padrao or {}).get(campo)
    except FileNotFoundError:
        padrao = None
    if not padrao:
        f = PONTOS_SEM_FAIXA[campo]
        return {"on": True, "de": f["de"], "ate": f["ate"], "passo": f["passo"]}
    passo = max(1, round(padrao / 6))
    ate = max(passo, round(padrao * 20 / 3 / passo) * passo)
    return {"on": True, "de": passo, "ate": ate, "passo": passo}


def periodos_atr(faixa_tipo: dict) -> list[int] | None:
    """Os períodos de ATR que a busca percorre para um tipo (None se o tipo
    não tem período, ou busca antiga sem ele)."""
    p = (faixa_tipo or {}).get("periodo")
    if not p:
        return None
    if p.get("passo"):
        return _grade(int(p["de"]), int(p["ate"]), int(p["passo"]), inteiro=True)
    return degraus_proporcionais(int(p["de"]), int(p["ate"]))


def _extras(simbolo: str, janela_de: str, estrategia: str | None = None,
            com_fora_da_busca: bool = False) -> list[Item]:
    """Os demais campos mineráveis da camada 4. Em toda faixa entra o
    "desligado" (0 ou vazio): a busca compara com e sem o recurso, como a
    Varredura já faz com o ADX. Pontos e dinheiro saem do padrão da ficha.
    Listas sem nada marcado (sem entradas, régua do ADX) = desligado.
    `com_fora_da_busca` traz também os de `FORA_DA_BUSCA` (buscas antigas)."""
    try:
        f = ativo.ficha(simbolo)
        pp, pv = f.perfil_padrao or {}, float(f.point_value or 1)
    except FileNotFoundError:
        pp, pv = {}, 1.0
    stop = int(pp.get("stop_pontos") or 300)
    passo_pts = max(1, round(stop / 6))
    passo_rs = round(stop * pv / 2, 2) or 1.0
    fech = pp.get("fechamento") or "17:30"
    horas = sorted({f"{h:02d}:00" for h in range(int(janela_de[:2]), int(fech[:2]) + 1)})

    da_ficha = ativo.faixas_do_ativo(simbolo, estrategia)

    def it(nome, rotulo, tipo, padrao, degrau="fixo"):
        if nome in da_ficha and tipo in ("inteiro", "real"):
            # a ficha manda (espelhar, não copiar); o desligado continua
            ff = da_ficha[nome]
            padrao = {"de": 0 if tipo == "inteiro" else 0.0,
                      "ate": ff.get("ate", padrao["ate"]),
                      "passo": ff.get("passo", padrao["passo"])}
            degrau = "fixo"
        return Item(nome, rotulo, tipo, "filtro", degrau, padrao, onde="extra")

    sem = {"valores": [""] + horas, "ligados": []}
    itens = [
        it("fechamento", "Fechar posições às", "hora",
           {"de": janela_de, "ate": fech, "passo": PASSO_JANELA}, "minutos"),
        it("max_barras", "Tempo máximo na operação (barras)", "inteiro",
           {"de": 0, "ate": 300, "passo": 1}, "proporcional"),
        it("sem_entrada1", "Sem entradas · 1", "lista", dict(sem)),
        it("sem_entrada2", "Sem entradas · 2", "lista", dict(sem)),
        it("sem_entrada3", "Sem entradas · 3", "lista", dict(sem)),
        it("filtro_adx", "ADX · régua", "lista",
           {"valores": ["tendencia", "rango"], "ligados": []}),
        it("adx_periodo", "ADX · período", "inteiro", {"de": 0, "ate": 50, "passo": 1},
           "proporcional"),
        it("adx_limiar", "ADX · limiar", "inteiro", {"de": 0, "ate": 50, "passo": 5}),
        it("adx_filtro_di", "DI confirma o lado", "lista", {"valores": [0, 1], "ligados": [0, 1]}),
        it("adx_subindo", "ADX subindo", "lista", {"valores": [0, 1], "ligados": [0, 1]}),
        it("breakeven_pct", "Breakeven · gatilho (% do alvo)", "real",
           {"de": 0.0, "ate": 100.0, "passo": 10.0}),
        it("step_gatilho_pct", "Stop móvel · gatilho (% do alvo)", "real",
           {"de": 0.0, "ate": 100.0, "passo": 10.0}),
        it("step_distancia_pct", "Stop móvel · trava (% do alvo)", "real",
           {"de": 0.0, "ate": 100.0, "passo": 10.0}),
        it("trailing_pontos", "Trailing (pontos)", "inteiro",
           {"de": 0, "ate": stop * 3, "passo": passo_pts}),
        it("limite_ganho_contrato", "Ganho máx. por contrato no dia", "real",
           {"de": 0.0, "ate": round(passo_rs * 12, 2), "passo": passo_rs}),
        it("limite_perda_contrato", "Perda máx. por contrato no dia", "real",
           {"de": 0.0, "ate": round(passo_rs * 12, 2), "passo": passo_rs}),
        it("max_trades_dia", "Máx. operações no dia", "inteiro", {"de": 0, "ate": 10, "passo": 1}),
        it("max_prejuizos_dia", "Máx. prejuízos no dia", "inteiro", {"de": 0, "ate": 5, "passo": 1}),
    ]
    return [i for i in itens if com_fora_da_busca or i.nome not in FORA_DA_BUSCA]


# régua do ADX sem nada marcado: o ADX inteiro desliga, e estes ficam em 0
# mesmo que a faixa deles tenha valores
ADX_DEPENDENTES = ("adx_periodo", "adx_limiar", "adx_filtro_di", "adx_subindo")


def desligado(item: Item):
    """O valor "recurso desligado" de um extra (o que vale com a lista
    vazia); None quando não há (horário de fechamento)."""
    if item.tipo == "lista":
        vals = item.padrao["valores"]
        return "" if "" in vals else vals[0]
    if item.tipo == "inteiro":
        return 0
    if item.tipo == "real":
        return 0.0
    return None


def canonico(extras: dict, listas: dict | None = None, sem_alvo: bool = False,
             fora_da_janela=None) -> dict:
    """Combinações que dão os MESMOS trades viram uma só (cópia cria platô
    falso e gasta teste): ADX desligado ignora o resto do ADX; DI e "subindo"
    só valem na tendência; stop móvel sem gatilho ignora a trava; sem alvo
    não há breakeven nem stop móvel (são % do alvo); hora sem entrada fora da
    janela não bloqueia nada; as três horas não dependem da ordem nem se
    repetem; prejuízos >= operações nunca dispara.

    `listas` (os valores da faixa) garante que o canônico é um valor que a
    busca testa: quando o "desligado" não está na faixa, vale o primeiro."""
    e = dict(extras)

    def off(n, real):
        vals = (listas or {}).get(n)
        return real if not vals or real in vals else vals[0]

    def pode(n, real):
        vals = (listas or {}).get(n)
        return not vals or real in vals

    if "adx_periodo" in e and not (int(e.get("adx_periodo") or 0) and int(e.get("adx_limiar") or 0)):
        e.update(adx_periodo=off("adx_periodo", 0), adx_limiar=off("adx_limiar", 0),
                 filtro_adx=off("filtro_adx", "tendencia"),
                 adx_filtro_di=off("adx_filtro_di", 0), adx_subindo=off("adx_subindo", 0))
        if e["adx_periodo"] and e["adx_limiar"]:        # faixa sem desligado
            e = dict(extras)
    if e.get("filtro_adx") == "rango":
        e.update(adx_filtro_di=off("adx_filtro_di", 0), adx_subindo=off("adx_subindo", 0))
    if sem_alvo:
        for n in ("breakeven_pct", "step_gatilho_pct", "step_distancia_pct"):
            if n in e:
                e[n] = off(n, 0.0)
    if "step_gatilho_pct" in e and not e.get("step_gatilho_pct"):
        e["step_distancia_pct"] = off("step_distancia_pct", 0.0)
    sem = [k for k in ("sem_entrada1", "sem_entrada2", "sem_entrada3") if k in e]
    if sem and all(pode(k, "") for k in sem):
        horas = sorted({e[k] for k in sem
                        if e[k] and not (fora_da_janela and fora_da_janela(e[k]))})
        horas += [""] * (len(sem) - len(horas))
        e.update(dict(zip(sem, horas)))
    mt, mp = int(e.get("max_trades_dia") or 0), int(e.get("max_prejuizos_dia") or 0)
    if "max_prejuizos_dia" in e and mt and mp >= mt and pode("max_prejuizos_dia", 0):
        e["max_prejuizos_dia"] = 0
    return {k: e[k] for k in extras}


def montar_catalogo(estrategia: str, simbolo: str,
                    com_fora_da_busca: bool = False) -> list[Item]:
    """Itens na ordem da aba "Espaço de busca": tempo, direção, janela, dias,
    stop, alvo e os parâmetros da estratégia."""
    from strategies import registry

    mod = registry.carregar(estrategia)
    faixas_ativo = ativo.faixas_do_ativo(simbolo, estrategia)
    proporcionais = set(_declaracao(mod, estrategia).get("proporcional", []))
    ini, fim = _janela_padrao(simbolo)

    itens = [
        Item("timeframe", "Tempo gráfico", "lista", "essencial", "-",
             {"valores": TIMEFRAMES, "ligados": TIMEFRAMES_LIGADOS}),
        Item("direcao", "Direção", "lista", "filtro", "-",
             {"valores": DIRECOES, "ligados": DIRECOES}),
        Item("janela", "Horário de entrada", "hora", "filtro", "minutos",
             {"de": ini, "ate": fim, "passo": PASSO_JANELA, "minima": JANELA_MINIMA}),
        Item("dias", "Dias da semana", "dias", "filtro", "-",
             {"valores": [1, 2, 3, 4, 5], "ligados": [1, 2, 3, 4, 5]}),
        Item("stop", "Stop", "gestao", "filtro", "fixo",
             {"tipos": {"pontos": _pontos(simbolo, "stop_pontos"),
                        **{k: dict(v) for k, v in STOP_TIPOS.items()}}}),
        Item("alvo", "Alvo", "gestao", "filtro", "fixo",
             {"tipos": {"pontos": _pontos(simbolo, "alvo_pontos"),
                        **{k: dict(v) for k, v in ALVO_TIPOS.items()}}}),
        *_extras(simbolo, ini, estrategia, com_fora_da_busca),
    ]
    for nome, meta in mod.params_schema.items():
        lo, hi = meta.get("min"), meta.get("max")
        if nome == "saida":
            # modos de saída são categorias: varre todos, como chips
            modos = list(range(int(lo or 0), int(hi) + 1))
            itens.append(Item(nome, meta.get("label", nome), "lista", "essencial",
                              "-", {"valores": modos, "ligados": modos},
                              onde="param", limites=(lo, hi)))
            continue
        f = faixas_ativo.get(nome) or {}
        padrao = {"de": f.get("de", lo if lo is not None else meta["default"]),
                  "ate": f.get("ate", hi if hi is not None else meta["default"]),
                  "passo": f.get("passo", meta.get("step") or 1)}
        tipo = "inteiro" if meta.get("tipo", "int") == "int" else "real"
        degrau = "proporcional" if nome in proporcionais else "fixo"
        itens.append(Item(nome, meta.get("label", nome), tipo, "essencial", degrau,
                          padrao, onde="param", limites=(lo, hi)))
    return itens
