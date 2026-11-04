"""O laço da busca: MAP-Elites com a pyribs, lote a lote, retomável.

Um LOTE é um `ask()` da pyribs. As combinações já avaliadas nesta busca não
rodam de novo; as novas vão aos núcleos agrupadas pelo sinal; o `tell` volta
na ORDEM do ask — o resultado da busca não pode depender de qual núcleo
terminou primeiro, senão retomar não daria o mesmo que rodar direto.

Depois de cada lote, nesta ordem: banco (com o `lote_n`, numa transação),
arquivo da pyribs (`arquivo.pkl`, atômico) e `estado.json`. Se o processo
cair entre o banco e o arquivo, a retomada apaga do banco o lote que o
arquivo não conhece (`banco.descartar_apos`) e o roda de novo uma vez só.
Banco ocupado pelo app não derruba nada: o lote fica pendente, viaja dentro
do arquivo e é gravado junto com o seguinte.

Comandos chegam por `controle.json` (o app escreve, a busca lê a cada lote e
a cada segundo quando pausada). Nada volta sozinho: parada é parada até
alguém clicar em Continuar (desenho §5).
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import banco
from .avaliador import INVALIDA
from .espaco import Combinacao, Espaco

CONTROLE_PADRAO = {"nucleos": 4, "parar_as": "08:30", "parar_as_ligado": True,
                   "limite": None, "pedido": None}
BONS = {"fr": 3.0, "pf": 1.25}        # mesmo corte do protótipo (selo "bom")
SIGMA_ESSENCIAL = 0.02
SIGMA_FILTRO = 0.12
N_INICIAIS = 200
LOTE_POR_EMISSOR = 36
BATIMENTO_S = 5.0
# O arquivo da pyribs cresce com a busca; regravá-lo a cada lote custaria
# segundos numa noite inteira. Cair entre dois salvamentos só faz rodar de
# novo os lotes desde o último (o banco os descarta na retomada).
SALVAR_A_CADA_S = 30.0
SINAIS_POR_NUCLEO = 1     # sinais novos por lote = núcleos × isto
REAGRUPAR_A_CADA_S = 300.0   # grupos refeitos de 5 em 5 min e ao parar
MAX_HISTORICO = 200


# ------------------------------------------------------------ arquivos
def escrever_json(caminho: Path, dados: dict, tentativas: int = 40) -> None:
    """Escrita atômica com paciência: no Windows o `os.replace` falha com
    PermissionError enquanto o outro processo está lendo o arquivo."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # nome único por escrita: duas threads do app escrevendo o mesmo arquivo
    # não podem disputar o mesmo temporário
    tmp = caminho.with_suffix(caminho.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(dados, default=str, ensure_ascii=False), encoding="utf-8")
    for i in range(tentativas):
        try:
            os.replace(tmp, caminho)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"não consegui escrever {caminho}")


_ILEGIVEL = object()


def ler_json(caminho: Path, padrao: dict | None = None, tentativas: int = 20,
             falha=None) -> dict:
    """Arquivo ausente = `padrao`; ilegível depois das tentativas (o outro
    lado escrevendo) = `falha`, que por omissão é o `padrao`."""
    for _ in range(tentativas):
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return dict(padrao or {})
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
    return dict(padrao or {}) if falha is None else falha


def ler_controle(pasta: Path, ultimo: dict | None = None) -> dict:
    """Ilegível vale o `ultimo` lido: cair no padrão soltaria uma pausa e
    trocaria núcleos e horário sem ninguém pedir."""
    lido = ler_json(pasta / "controle.json", falha=_ILEGIVEL)
    if lido is _ILEGIVEL:
        return dict(ultimo) if ultimo else dict(CONTROLE_PADRAO)
    return {**CONTROLE_PADRAO, **lido}


def escrever_estado(pasta: Path, estado: dict) -> None:
    escrever_json(pasta / "estado.json", estado)


def _salvar_pickle(caminho: Path, dados) -> None:
    tmp = caminho.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(dados, f)
        f.flush()
        os.fsync(f.fileno())
    for _ in range(40):
        try:
            os.replace(tmp, caminho)
            return
        except PermissionError:
            time.sleep(0.05)
    raise PermissionError(f"não consegui escrever {caminho}")


def proximo_horario(hhmm: str, depois_de: datetime) -> datetime:
    """A próxima vez que o relógio marca `hhmm` depois de `depois_de`."""
    h, m = (int(x) for x in hhmm.split(":")[:2])
    alvo = depois_de.replace(hour=h, minute=m, second=0, microsecond=0)
    return alvo if alvo > depois_de else alvo + timedelta(days=1)


def digital(chave: str) -> int:
    """8 bytes por combinação na memória de "já testei": com a chave inteira
    (~250 caracteres) um milhão de testes ocupariam ~400 MB."""
    return int.from_bytes(hashlib.blake2b(chave.encode(), digest_size=8).digest(), "big")


# ------------------------------------------------------------ a busca
class Busca:
    """`avaliar(grupos, ctx, n_nucleos) -> [resultado]` existe para os testes;
    sem ele, a busca usa os núcleos de verdade."""

    def __init__(self, busca_id: int, pasta: Path | None = None, avaliar=None,
                 agora=datetime.now):
        self.busca_id = busca_id
        self.pasta = Path(pasta) if pasta else banco.pasta_da(busca_id)
        self.pasta.mkdir(parents=True, exist_ok=True)
        b = banco.ler_busca(busca_id)
        if b is None:
            raise ValueError(f"busca {busca_id} não existe")
        self.config = b["config"]
        self.esp = Espaco.de_json(self.config["espaco"])
        if not self.config.get("de") or not self.config.get("ate"):
            # sem datas fixas, continuar outro dia mudaria folds e holdout no
            # meio da busca e notas de períodos diferentes disputariam a casa
            raise ValueError("busca sem período fixo (de/até)")
        if self.esp.fechamento != self.config["perfil_base"].get("fechamento"):
            raise ValueError("fechamento do espaço difere do perfil da busca")
        self._avaliar_fora = avaliar
        self.agora = agora
        self._nucleos = None
        self._trava = threading.Lock()
        self._estado: dict = {}
        self._parar_batimento = threading.Event()

    # -------------------------------------------------------- estado salvo
    def _novo(self) -> dict:
        semente = int(self.config.get("semente", 0))
        rng = np.random.default_rng(semente)
        from ribs.archives import GridArchive
        from ribs.emitters import GaussianEmitter, IsoLineEmitter
        from ribs.schedulers import Scheduler

        dims = self.esp.dims_arquivo()
        arquivo = GridArchive(solution_dim=self.esp.n_genes, dims=dims,
                              ranges=[(0, n) for n in dims], seed=semente)
        n = self.esp.n_genes
        sigma = np.where(self.esp.genes_essenciais(), SIGMA_ESSENCIAL, SIGMA_FILTRO)
        limites = [(0.0, 1.0)] * n
        iniciais = np.array_split(rng.random((N_INICIAIS, n)), 6)
        emissores = [GaussianEmitter(arquivo, sigma=sigma, bounds=limites,
                                     initial_solutions=iniciais[i],
                                     batch_size=LOTE_POR_EMISSOR, seed=semente + 1 + i)
                     for i in range(4)]
        emissores += [IsoLineEmitter(arquivo, iso_sigma=0.05, line_sigma=0.2,
                                     bounds=limites, initial_solutions=iniciais[4 + i],
                                     batch_size=LOTE_POR_EMISSOR, seed=semente + 5 + i)
                      for i in range(2)]
        return {"scheduler": Scheduler(arquivo, emissores), "memo": {}, "melhor": {},
                "lote_n": 0, "testes": 0, "distintos": 0, "descartados": 0,
                "pendentes": [], "historico": [], "decorrido_s": 0.0, "taxas": []}

    def _carregar(self) -> dict:
        arq = self.pasta / "arquivo.pkl"
        if arq.exists():
            with open(arq, "rb") as f:
                s = pickle.load(f)
            # o lote que chegou ao banco e não ao arquivo sai e roda de novo; e
            # os pendentes do arquivo saem do banco também (podem ter sido
            # gravados logo antes da queda) e voltam a ser gravados uma vez só
            corte = (s["pendentes"][0]["lote_n"] - 1) if s["pendentes"] else s["lote_n"]
            banco.descartar_apos(self.busca_id, corte)
            banco.substituir_elites(self.busca_id, list(s["melhor"].values()))
            return s
        banco.descartar_apos(self.busca_id, 0)
        banco.substituir_elites(self.busca_id, [])
        return self._novo()

    # -------------------------------------------------------- avaliação
    def _ctx(self) -> dict:
        if not hasattr(self, "_ctx_cache"):
            from core import walkforward as wf

            c = self.config
            ini = np.datetime64(c["de"], "s")
            fim = np.datetime64(c["ate"], "s")
            self._ctx_cache = {"espaco": c["espaco"], "perfil_base": c["perfil_base"],
                               "janelas": wf.montar_janelas(ini, fim, **c["wf_config"]),
                               "minimo": int(c["minimo"]), "criterio": c["criterio"]}
        return self._ctx_cache

    def _avaliar(self, grupos, n_nucleos):
        if self._avaliar_fora is not None:
            return self._avaliar_fora(grupos, self.config, n_nucleos)
        ctx = self._ctx()
        if self._nucleos is None or self._nucleos.n != n_nucleos:
            self._fechar_nucleos()
            from .nucleos import Nucleos
            c = self.config
            self._nucleos = Nucleos(n_nucleos, c["simbolo"], c.get("de"), c.get("ate"),
                                    c["estrategia"])
        return self._nucleos.avaliar(grupos, ctx)

    def _fechar_nucleos(self):
        if self._nucleos is not None:
            self._nucleos.fechar()
            self._nucleos = None

    # -------------------------------------------------------- um lote
    def _ancorar(self, sols: np.ndarray, n_sinais: int) -> None:
        """Calcular uma vez, testar muitas (desenho §4.2), NO LUGAR.

        A mutação gaussiana mexe em todos os genes, e quase toda combinação
        nascia com um sinal próprio: o núcleo refazia o indicador a cada
        teste e 20 núcleos rendiam como 7. Aqui só os `n_sinais` primeiros
        sinais distintos do lote ficam como vieram; as demais combinações
        adotam o sinal mais próximo e variam só horário, dias, direção, stop
        e alvo.

        No lugar porque o `ask()` da pyribs devolve o mesmo array que ela usa
        no `tell`: assim o arquivo guarda exatamente a combinação avaliada.
        """
        ess = self.esp.genes_essenciais()
        ancoras, chaves = [], set()
        for x in sols:
            k = self.esp.decodificar(x).chave_essencial()
            if k not in chaves and len(ancoras) < n_sinais:
                chaves.add(k)
                ancoras.append(x[ess].copy())
        if not ancoras:
            return
        a = np.array(ancoras)
        for x in sols:
            if self.esp.decodificar(x).chave_essencial() in chaves:
                continue
            x[ess] = a[int(np.argmin(((a - x[ess]) ** 2).sum(axis=1)))]

    def _lote(self, s: dict, n_nucleos: int) -> None:
        t0 = time.monotonic()
        sols = s["scheduler"].ask()
        self._ancorar(sols, max(1, n_nucleos) * SINAIS_POR_NUCLEO)
        combos = [self.esp.decodificar(x) for x in sols]
        chaves = [c.chave() for c in combos]
        novas, grupos, vistas = [], {}, set()
        for c, k in zip(combos, chaves):
            d = digital(k)
            if d in s["memo"] or d in vistas:
                continue
            vistas.add(d)
            novas.append(k)
            teste_n = s["distintos"] + len(novas)
            grupos.setdefault(c.chave_essencial(), []).append((teste_n, k))
        resultados = self._avaliar(list(grupos.items()), n_nucleos) if grupos else []
        por_chave = {r["combo"]: r for r in resultados}
        if set(por_chave) != set(novas):
            raise RuntimeError("os núcleos não devolveram todas as combinações")

        linhas, mudaram, hist = [], {}, []
        for k in novas:          # na ordem do teste_n
            r = por_chave[k]
            c = Combinacao.de_chave(k)
            casa = json.dumps(list(self.esp.casa(c)))
            obj = float(r.get("objetivo", INVALIDA))
            s["memo"][digital(k)] = obj
            if r.get("descartada"):
                s["descartados"] += 1
            linhas.append({col: r.get(col) for col in banco.COLS_COMBO
                           if col not in ("busca_id", "lote_n")} | {"casa": casa})
            atual = s["melhor"].get(casa)
            if atual is None or obj > atual["objetivo"]:
                e = {"casa": casa, "combo": k, "objetivo": obj,
                     "valida": bool(r.get("valida")), "trades": r.get("trades"),
                     "lucro": r.get("lucro"), "pf": r.get("pf"), "dd": r.get("dd"),
                     "fr": r.get("fr"), "achado_em": r["teste_n"],
                     "trades_hash": r.get("trades_hash")}
                s["melhor"][casa] = e
                mudaram[casa] = e
                hist.append({"casa": casa, "teste_n": r["teste_n"], "objetivo": obj})
        s["distintos"] += len(novas)
        s["testes"] += len(chaves)

        # tell na ordem do ask: repetidas recebem o resultado guardado
        objs = np.array([s["memo"][digital(k)] for k in chaves], dtype=float)
        medidas = np.array([np.array(self.esp.casa(c)) + 0.5 for c in combos], dtype=float)
        s["scheduler"].tell(objs, medidas)

        s["lote_n"] += 1
        s["pendentes"].append({"lote_n": s["lote_n"], "combos": linhas,
                               "elites": list(mudaram.values()), "hist": hist})
        dt = time.monotonic() - t0
        s["decorrido_s"] += dt
        s["taxas"] = (s["taxas"] + [len(novas) / dt if dt > 0 else 0.0])[-10:]
        validas = [e for e in s["melhor"].values() if e["valida"]]
        s["historico"].append([round(s["decorrido_s"], 1), len(validas)])
        if len(s["historico"]) > MAX_HISTORICO:
            s["historico"] = s["historico"][::2]

    def _gravar_pendentes(self, s: dict) -> None:
        """Grava no banco o que ainda não foi; banco ocupado = tenta no próximo."""
        while s["pendentes"]:
            p = s["pendentes"][0]
            try:
                banco.gravar_lote(self.busca_id, p["lote_n"], p["combos"], p["elites"],
                                  p["hist"], self._contagens(s))
            except banco.BancoOcupado:
                return
            s["pendentes"].pop(0)

    def _contagens(self, s: dict) -> dict:
        return {"testes": s["testes"], "distintos": s["distintos"],
                "descartados": s["descartados"], "duracao_s": s["decorrido_s"],
                "historico": s["historico"]}

    def _salvar(self, s: dict, ja: bool = False) -> None:
        agora = time.monotonic()
        if not ja and agora - getattr(self, "_salvo_em", -1e18) < SALVAR_A_CADA_S:
            return
        _salvar_pickle(self.pasta / "arquivo.pkl", s)
        self._salvo_em = agora

    # -------------------------------------------------------- estado.json
    def _publicar(self, s: dict, status: str, ctl: dict, **extra) -> None:
        validas = [e for e in s["melhor"].values() if e["valida"]]
        crit = self.config["criterio"]
        corte = BONS.get(crit)
        melhor = max(validas, key=lambda e: e["objetivo"], default=None)
        taxa = float(np.mean(s["taxas"])) if s["taxas"] else 0.0
        estimativa = None
        restante = None
        if ctl.get("parar_as_ligado") and getattr(self, "_parar_em", None):
            restante = max(0.0, (self._parar_em - self.agora()).total_seconds())
            estimativa = s["distintos"] + int(taxa * restante)
        if ctl.get("limite"):
            estimativa = min(estimativa or 10**12, int(ctl["limite"]))
        with self._trava:
            self._estado = {
                "busca_id": self.busca_id, "status": status,
                "vivo_em": self.agora().isoformat(timespec="seconds"),
                "testes": s["testes"], "distintos": s["distintos"],
                "descartados": s["descartados"], "nichos": len(validas),
                "bons": (sum(1 for e in validas if e["objetivo"] >= corte)
                         if corte is not None else None),
                "melhor": melhor, "inicio": getattr(self, "_inicio", None),
                "decorrido_s": round(s["decorrido_s"], 1),
                "restante_s": restante, "estimativa_total": estimativa,
                "historico_nichos": s["historico"], "versao": s["lote_n"],
                "nucleos": ctl.get("nucleos"), "pendentes": len(s["pendentes"]),
                "versao_grupos": s.get("versao_grupos"),
                **extra}
            escrever_estado(self.pasta, self._estado)

    def _batimento(self):
        """`vivo_em` a cada 5 s, mesmo no meio de um lote longo: sem isto um
        lote pesado em M1 pareceria queda na tela."""
        while not self._parar_batimento.wait(BATIMENTO_S):
            with self._trava:
                if self._estado:
                    self._estado["vivo_em"] = self.agora().isoformat(timespec="seconds")
                    try:
                        escrever_estado(self.pasta, self._estado)
                    except PermissionError:
                        pass

    # -------------------------------------------------------- o laço
    def _controle(self) -> dict:
        """Lê o controle e recalcula "Parar às" quando o horário OU o liga/
        desliga muda — inclusive na pausa: religar à tarde não pode parar na
        hora por causa da manhã que já passou."""
        ctl = ler_controle(self.pasta, getattr(self, "_ctl", None))
        par = (ctl["parar_as"], bool(ctl.get("parar_as_ligado")))
        if par != getattr(self, "_parada_vista", None):
            self._parar_em = proximo_horario(ctl["parar_as"], self.agora())
            self._parada_vista = par
        self._ctl = ctl
        return ctl

    def _marcar(self, status: str | None = None, **campos) -> None:
        """Status no banco sem derrubar a busca: ocupado fica para depois."""
        pend = dict(getattr(self, "_status_pendente", {}) or {})
        pend.update(campos)
        if status is not None:
            pend["status"] = status
        try:
            banco.marcar_status(self.busca_id, **pend)
            self._status_pendente = {}
        except banco.BancoOcupado:
            self._status_pendente = pend

    @staticmethod
    def _insistir(fn, *a, prazo_s: float = 120.0, **k):
        """Início e fim da busca: o banco pode estar com o app; espera."""
        fim = time.monotonic() + prazo_s
        while True:
            try:
                return fn(*a, **k)
            except banco.BancoOcupado:
                if time.monotonic() > fim:
                    raise
                time.sleep(1.0)

    def rodar(self, max_lotes: int | None = None) -> str:
        s = self._insistir(self._carregar)
        self._inicio = self.agora().isoformat(timespec="seconds")
        ctl = self._controle()
        self._insistir(banco.marcar_status, self.busca_id, "rodando", erro=None,
                       inicio=self.agora(), fim=None)
        self._publicar(s, "rodando", ctl)
        batimento = threading.Thread(target=self._batimento, daemon=True)
        batimento.start()
        feitos = 0
        status = "concluida"
        try:
            while True:
                ctl = self._controle()
                if self._deve_parar(s, ctl):
                    break
                if ctl.get("pedido") == "pausar":
                    self._fechar_nucleos()
                    self._salvar(s, ja=True)
                    self._reagrupar(s, ja=True)
                    self._marcar("pausada")
                    self._publicar(s, "pausada", ctl, pausada_em=self.agora().isoformat(
                        timespec="seconds"))
                    while ctl.get("pedido") == "pausar" and not self._deve_parar(s, ctl):
                        time.sleep(1.0)
                        ctl = self._controle()
                        if getattr(self, "_status_pendente", None):
                            self._marcar()
                    if self._deve_parar(s, ctl):
                        break
                    self._marcar("rodando")
                self._lote(s, int(ctl.get("nucleos") or 1))
                self._gravar_pendentes(s)
                if getattr(self, "_status_pendente", None):
                    self._marcar()
                self._salvar(s)
                self._reagrupar(s)
                self._publicar(s, "rodando", ctl)
                feitos += 1
                if max_lotes is not None and feitos >= max_lotes:
                    status = "parada_teste"
                    break
        except BaseException as erro:
            self._parar_batimento.set()
            self._fechar_nucleos()
            try:
                banco.marcar_status(self.busca_id, "erro", erro=str(erro), fim=self.agora())
                self._publicar(s, "erro", ctl, erro=str(erro))
            except Exception:
                pass
            raise
        self._parar_batimento.set()
        self._fechar_nucleos()
        self._insistir(self._gravar_tudo, s)
        self._salvar(s, ja=True)
        self._reagrupar(s, ja=True)
        if status == "concluida":
            self._insistir(banco.marcar_status, self.busca_id, "concluida",
                           fim=self.agora(), **self._contagens(s))
            self._publicar(s, "concluida", ctl, fim=self.agora().isoformat(timespec="seconds"),
                           motivo=getattr(self, "_motivo", None))
        return status

    def _reagrupar(self, s: dict, ja: bool = False) -> None:
        """Refaz os grupos com o que já está no banco. Banco ocupado: fica
        para a próxima vez — grupo atrasado não estraga nada."""
        agora = time.monotonic()
        espera = max(REAGRUPAR_A_CADA_S, 5 * getattr(self, "_custo_grupos", 0.0))
        if not ja and agora - getattr(self, "_agrupado_em", agora - 1e18) < espera:
            return
        from . import grupos

        try:
            versao = int((banco.ler_busca(self.busca_id) or {}).get("versao_grupos") or 0) + 1
            gs = grupos.agrupar(banco.ler_elites(self.busca_id),
                                banco.ler_combos(self.busca_id, colunas=banco.COLS_AGRUPAR),
                                self.esp)
            banco.gravar_grupos(self.busca_id, versao, gs)
            s["versao_grupos"] = versao
        except Exception as erro:
            # o grupo é leitura secundária: errar aqui nunca pode custar a
            # busca da noite inteira — fica para a próxima vez
            print(f"reagrupar falhou: {erro!r}", flush=True)
        # o relógio conta do FIM da conta (e da tentativa que falhou): uma
        # conta longa não pode emendar na seguinte e parar a busca
        fim = time.monotonic()
        self._custo_grupos = fim - agora
        self._agrupado_em = fim

    def _gravar_tudo(self, s: dict) -> None:
        self._gravar_pendentes(s)
        if s["pendentes"]:
            raise banco.BancoOcupado("lotes pendentes")
        if getattr(self, "_status_pendente", None):
            banco.marcar_status(self.busca_id, **self._status_pendente)
            self._status_pendente = {}

    def _deve_parar(self, s: dict, ctl: dict) -> bool:
        if ctl.get("pedido") == "parar":
            self._motivo = "parar"
            return True
        if ctl.get("parar_as_ligado") and self.agora() >= self._parar_em:
            self._motivo = "horario"
            return True
        if ctl.get("limite") and s["distintos"] >= int(ctl["limite"]):
            self._motivo = "limite"
            return True
        return False
