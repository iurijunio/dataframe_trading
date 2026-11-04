"""O espaço da busca: vetor da pyribs <-> combinação <-> perfil do motor.

A pyribs trabalha com vetores contínuos; aqui tudo é escolha em lista. Cada
gene é um número em [0, 1] e escolhe `min(int(x * n), n - 1)` de uma lista —
o corte em n-1 existe porque o emissor cola a solução nos limites e x = 1,0
acontece.

A JANELA é o único par amarrado: o gene do fim escolhe só entre os fins
válidos para o início escolhido (duração mínima, `janela_valida`, fechamento
do menu). Assim nenhum vetor vira janela impossível, e a busca não gasta
avaliação com combinação que nem roda.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np

from core import ativo
from core.engine.execution import ExecutionProfile

from . import catalogo as C

DIMS_PADRAO = ("timeframe", "ini", "fim", "dias", "direcao")

# extras das buscas criadas em 04/11/2026 antes de `FORA_DA_BUSCA` (com
# `com_extras` e sem `nomes_extras` gravado): reabrem com o vetor delas
EXTRAS_04_11 = ("adx_filtro_di", "adx_limiar", "adx_periodo", "adx_subindo",
                "breakeven_pct", "fechamento", "filtro_adx", "limite_ganho_contrato",
                "limite_perda_contrato", "max_barras", "max_prejuizos_dia",
                "max_trades_dia", "sem_entrada1", "sem_entrada2", "sem_entrada3",
                "step_distancia_pct", "step_gatilho_pct", "trailing_pontos")

# tipo de stop/alvo -> campo do perfil que recebe o valor
CAMPO_STOP = {"pontos": "stop_pontos", "atr": "stop_atr_mult", "percentual": "stop_pct"}
CAMPO_ALVO = {"pontos": "alvo_pontos", "atr": "alvo_atr_mult",
              "multiplicador": "alvo_razao", "percentual": "alvo_pct"}


@dataclass(frozen=True)
class Combinacao:
    timeframe: str
    ini: str
    fim: str
    dias: tuple
    direcao: str
    stop_tipo: str
    stop_valor: float
    alvo_tipo: str
    alvo_valor: float
    params: tuple   # ((nome, valor), ...) em ordem de nome
    # período do ATR do stop/alvo (só com tipo ATR; None nas buscas antigas,
    # que não variavam o período)
    stop_atr_periodo: int | None = None
    alvo_atr_periodo: int | None = None
    # demais campos mineráveis da camada 4 ((campo, valor), ...) em ordem de
    # nome; vazio nas buscas antigas
    extras: tuple = ()

    def chave(self) -> str:
        """Identidade da combinação: JSON canônico, ordenado. Campo novo
        vazio não entra: a chave de uma busca antiga continua a mesma."""
        d = asdict(self)
        for k in ("stop_atr_periodo", "alvo_atr_periodo"):
            if d[k] is None:
                del d[k]
        if not d["extras"]:
            del d["extras"]
        else:
            d["extras"] = [list(p) for p in self.extras]
        d["dias"] = list(self.dias)
        d["params"] = [list(p) for p in self.params]
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def chave_essencial(self) -> tuple:
        """O que obriga a recalcular o sinal (camada "essencial")."""
        return (self.timeframe, self.params)

    @classmethod
    def de_chave(cls, chave: str) -> "Combinacao":
        d = json.loads(chave)
        d.setdefault("stop_atr_periodo", None)
        d.setdefault("alvo_atr_periodo", None)
        d["extras"] = tuple(tuple(p) for p in d.get("extras") or ())
        d["dias"] = tuple(d["dias"])
        d["params"] = tuple(tuple(p) for p in d["params"])
        return cls(**d)


def _escolher(x: float, n: int) -> int:
    return min(int(x * n), n - 1)


class Espaco:
    def __init__(self, estrategia: str, simbolo: str, fechamento: str,
                 faixas: dict | None = None,
                 dims_nicho: tuple[str, ...] = DIMS_PADRAO,
                 com_periodo_atr: bool = True, com_extras: bool = True,
                 nomes_extras: list[str] | None = None):
        self.estrategia = estrategia
        self.simbolo = simbolo
        self.fechamento = fechamento
        self.faixas = dict(faixas or {})
        self.dims_nicho = tuple(dims_nicho)
        # `nomes_extras` gravado manda: a busca reabre com o vetor que tinha,
        # mesmo que o catálogo de hoje não varra mais algum deles
        itens = C.montar_catalogo(estrategia, simbolo,
                                  com_fora_da_busca=bool(set(nomes_extras or ())
                                                         & C.FORA_DA_BUSCA))
        if nomes_extras is not None:
            itens = [i for i in itens if i.onde != "extra" or i.nome in nomes_extras]
        self.catalogo = {i.nome: i for i in itens}

        def lista(nome):
            item = self.catalogo[nome]
            return C.valores(item, self.faixas.get(nome) or item.padrao)

        self.timeframes = lista("timeframe")
        self.direcoes = lista("direcao")
        self.dias = lista("dias")
        self.horarios = lista("janela")
        self.stops = lista("stop")
        self.alvos = lista("alvo")
        # período do ATR: genes a mais só nas buscas novas (as antigas
        # reabrem com o mesmo vetor que gravaram)
        self.com_periodo_atr = com_periodo_atr

        def per(nome):
            item = self.catalogo[nome]
            tipos = (self.faixas.get(nome) or item.padrao).get("tipos") or {}
            return C.periodos_atr(tipos.get("atr")) if com_periodo_atr else None

        self.stop_periodos = per("stop")
        self.alvo_periodos = per("alvo")
        # demais campos da camada 4 (fechamento, ADX, proteções, limites…):
        # só nas buscas novas, como o período do ATR
        self.com_extras = com_extras
        self.nomes_extras = (sorted(n for n, i in self.catalogo.items() if i.onde == "extra")
                             if com_extras else [])
        self.extras_vals = {}
        for n in self.nomes_extras:
            vals = lista(n)
            if not vals:        # nada marcado = recurso desligado
                off = C.desligado(self.catalogo[n])
                if off is None:
                    raise ValueError(f"nada para varrer em {n}")
                vals = [off]
            self.extras_vals[n] = vals
        if "filtro_adx" in self.extras_vals and not lista("filtro_adx"):
            # sem régua marcada o ADX inteiro desliga (o gene fica, de um valor)
            for n in C.ADX_DEPENDENTES:
                if n in self.extras_vals:
                    self.extras_vals[n] = [0]
        self._montar_janelas()
        self.nomes_params = sorted(n for n, i in self.catalogo.items() if i.onde == "param")
        self.params_vals = {n: lista(n) for n in self.nomes_params}
        for nome, vals in [("timeframe", self.timeframes), ("direcao", self.direcoes),
                           ("dias", self.dias), ("stop", self.stops), ("alvo", self.alvos),
                           *self.params_vals.items()]:
            if not vals:
                raise ValueError(f"nada para varrer em {nome}")
        # genes: tempo, direção, início, fim, dias, tipo e valor de stop e de
        # alvo, e um por parâmetro da estratégia
        self._genes = (["timeframe", "direcao", "ini", "fim", "dias", "stop_tipo",
                        "stop_valor", "alvo_tipo", "alvo_valor"] + self.nomes_params
                       + (["stop_atr_per", "alvo_atr_per"] if com_periodo_atr else [])
                       + ["x:" + n for n in self.nomes_extras])
        self.n_genes = len(self._genes)

    # ------------------------------------------------------------ janela
    def _montar_janelas(self):
        f = ativo.ficha(self.simbolo) if self.simbolo != "WIN$N" else None
        f = f if (f and f.sessao_abertura) else None
        minima = int((self.faixas.get("janela") or self.catalogo["janela"].padrao)
                     .get("minima", C.JANELA_MINIMA))

        def motor(h):   # minutos no relógio de pregão: a ordem certa no MES
            return ativo.hora_para_minuto(ativo.hora_para_motor(h, f) if f else h)

        self._motor = motor
        self._ficha_pregao = f
        # com o fechamento minerado, a janela só não pode passar do MAIOR
        # fechamento possível; cada combinação escolhe um fechamento >= fim
        fech = self.fechamento
        if "fechamento" in getattr(self, "extras_vals", {}):
            validos = [h for h in self.extras_vals["fechamento"]
                       if ativo.janela_valida(h, h, f, h) is None]
            if not validos:
                raise ValueError("nenhum fechamento válido na faixa")
            self.extras_vals["fechamento"] = validos
            fech = max(validos, key=motor)
        self.fins_de: dict[str, list[str]] = {}
        for ini in self.horarios:
            fins = [fim for fim in self.horarios
                    if motor(fim) - motor(ini) >= minima
                    and ativo.janela_valida(ini, fim, f, fech) is None]
            if fins:
                self.fins_de[ini] = fins
        self.inicios = [h for h in self.horarios if h in self.fins_de]
        if not self.inicios:
            raise ValueError("nenhuma janela válida no horário de entrada escolhido")

    # ------------------------------------------------------------ genoma
    def decodificar(self, x: np.ndarray) -> Combinacao:
        g = dict(zip(self._genes, np.asarray(x, dtype=float)))
        ini = self.inicios[_escolher(g["ini"], len(self.inicios))]
        fins = self.fins_de[ini]
        tipos_s, tipos_a = list(self.stops), list(self.alvos)
        st = tipos_s[_escolher(g["stop_tipo"], len(tipos_s))]
        at = tipos_a[_escolher(g["alvo_tipo"], len(tipos_a))]
        fim = fins[_escolher(g["fim"], len(fins))]
        return Combinacao(
            timeframe=self.timeframes[_escolher(g["timeframe"], len(self.timeframes))],
            ini=ini,
            fim=fim,
            dias=tuple(self.dias[_escolher(g["dias"], len(self.dias))]),
            direcao=self.direcoes[_escolher(g["direcao"], len(self.direcoes))],
            stop_tipo=st,
            stop_valor=self.stops[st][_escolher(g["stop_valor"], len(self.stops[st]))],
            alvo_tipo=at,
            alvo_valor=self.alvos[at][_escolher(g["alvo_valor"], len(self.alvos[at]))],
            params=tuple((n, self.params_vals[n][_escolher(g[n], len(self.params_vals[n]))])
                         for n in self.nomes_params),
            stop_atr_periodo=(self.stop_periodos[_escolher(g["stop_atr_per"], len(self.stop_periodos))]
                              if st == "atr" and self.stop_periodos else None),
            alvo_atr_periodo=(self.alvo_periodos[_escolher(g["alvo_atr_per"], len(self.alvo_periodos))]
                              if at == "atr" and self.alvo_periodos else None),
            extras=self._decodificar_extras(g, ini, fim, at),
        )

    def _decodificar_extras(self, g: dict, ini: str, fim: str, at: str) -> tuple:
        e = {}
        for n in self.nomes_extras:
            vals = self.extras_vals[n]
            if n == "fechamento":
                # fechar antes do fim das entradas não faz sentido (e o menu recusa)
                vals = [v for v in vals if self._motor(v) >= self._motor(fim)
                        and ativo.janela_valida(fim, fim, self._ficha_pregao, v) is None] \
                    or [max(self.extras_vals[n], key=self._motor)]
            e[n] = vals[_escolher(g["x:" + n], len(vals))]
        ini_m, fim_m = self._motor(ini), self._motor(fim)

        def fora(h):            # a hora bloqueada [h, h+60) não toca a janela
            m = self._motor(h)
            return m + 60 <= ini_m or m > fim_m

        return tuple(sorted(C.canonico(e, self.extras_vals, sem_alvo=(at == "sem"),
                                       fora_da_janela=fora).items()))

    def genes_essenciais(self) -> np.ndarray:
        return np.array([g == "timeframe" or g in self.params_vals for g in self._genes])

    # ------------------------------------------------------------ nicho
    def _eixo(self, nome: str) -> list:
        return {"timeframe": self.timeframes, "ini": self.horarios, "fim": self.horarios,
                "dias": self.dias, "direcao": self.direcoes}.get(nome) \
            or self.params_vals[nome]

    def dims_arquivo(self) -> list[int]:
        return [len(self._eixo(d)) for d in self.dims_nicho]

    def casa(self, c: Combinacao) -> tuple[int, ...]:
        valor = {"timeframe": c.timeframe, "ini": c.ini, "fim": c.fim,
                 "dias": c.dias, "direcao": c.direcao, **dict(c.params)}
        return tuple(self._eixo(d).index(valor[d]) for d in self.dims_nicho)

    # ------------------------------------------------------------ motor
    def params(self, c: Combinacao) -> dict:
        return dict(c.params)

    def perfil(self, c: Combinacao, perfil_base: dict) -> ExecutionProfile:
        """O perfil que o menu montaria com esta combinação: tudo o que não é
        da busca (custos, ADX, limites, proteções, período do ATR) vem do
        `perfil_base`, que é o menu no momento de iniciar."""
        p = {**perfil_base, "timeframe": c.timeframe, "entrada_inicio": c.ini,
             "entrada_fim": c.fim, "dias_semana": tuple(c.dias), "direcao": c.direcao,
             **({"stop_tipo": "pontos", "stop_pontos": 0} if c.stop_tipo == "sem"
                else {"stop_tipo": c.stop_tipo, CAMPO_STOP[c.stop_tipo]: c.stop_valor})}
        if c.alvo_tipo == "sem":
            p.update(alvo_tipo="pontos", alvo_pontos=0)
        else:
            p.update(alvo_tipo=c.alvo_tipo, **{CAMPO_ALVO[c.alvo_tipo]: c.alvo_valor})
        if c.stop_atr_periodo is not None:
            p["stop_atr_periodo"] = int(c.stop_atr_periodo)
        if c.alvo_atr_periodo is not None:
            p["alvo_atr_periodo"] = int(c.alvo_atr_periodo)
        p.update(dict(c.extras))
        return ExecutionProfile(**p)

    # ------------------------------------------------------------ guardar
    def para_json(self) -> dict:
        return {"estrategia": self.estrategia, "simbolo": self.simbolo,
                "fechamento": self.fechamento, "faixas": self.faixas,
                "dims_nicho": list(self.dims_nicho),
                "com_periodo_atr": self.com_periodo_atr, "com_extras": self.com_extras,
                "nomes_extras": list(self.nomes_extras)}

    @classmethod
    def de_json(cls, d: dict) -> "Espaco":
        # busca gravada antes do período do ATR: sem a chave, sem os genes
        com_extras = bool(d.get("com_extras", False))
        nomes = d.get("nomes_extras")
        if nomes is None and com_extras:
            nomes = list(EXTRAS_04_11)
        return cls(d["estrategia"], d["simbolo"], d["fechamento"], d.get("faixas"),
                   tuple(d.get("dims_nicho") or DIMS_PADRAO),
                   com_periodo_atr=bool(d.get("com_periodo_atr", False)),
                   com_extras=com_extras, nomes_extras=nomes)
