"""Diário das ordens: escrita adiantada em arquivo, espelho no banco.

Spec 2026-10-08-ao-vivo-ordens-design.md §7.2. O banco tem um escritor por
vez entre processos (uma mineração gravando o segura); a ordem não pode
esperar por ele. Então cada evento vai PRIMEIRO para o arquivo do dia, com
fsync, e só depois para `ordens_eventos`. É do arquivo, na subida, que a
captura sabe "já enviei a entrada X", "o ticket da operação Y", "a conta
travou hoje" — sem isso uma queda logo depois de enviar duplicaria a
entrada.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from core import db_manager as db

log = logging.getLogger(__name__)

# constante de módulo: o tests/conftest.py a desvia para tmp_path, para um
# teste nunca escrever onde a captura real do usuário lê. Quem consome deve
# ler `diario_ordens.PASTA` na hora de usar (nunca `from ... import PASTA`),
# senão o desvio do conftest não chega nele.
PASTA = db.DATA / "ao_vivo" / "ordens"

TIPOS = frozenset({
    "enviando", "executada", "parcial", "aceita", "recusada", "perdida",
    "nao_entrou", "seria_enviada", "adotada", "saiu_antes",
    "saida_enviando", "saida_executada", "saida_recusada",
    # saída executada em parte: a posição segue viva, então NÃO fecha o
    # ticket (_abertos) nem a saída pendente (saida_desde)
    "saida_parcial",
    "protecao_enviando", "protecao", "protecao_recusada", "cancelada",
    "incerta", "cancelar_enviando", "cancelar_recusada",
    "chamado", "chamado_fechado", "conta_travada", "rolagem", "comando",
    # o preço que a bolsa não devolve na resposta da ordem (ordens._confirmar_precos)
    "preco_confirmado",
    # "Ordem de teste" (core/ordem_teste.py): cada etapa e o desfecho. Tipos
    # próprios de propósito — nenhuma conta derivada acima (ticket aberto,
    # saída pendente, proteção) pode confundir a posição de teste com a de
    # uma ligação
    "teste", "teste_ok", "teste_falhou",
})
# desfechos finais de uma tentativa de entrada: sem um deles depois do último
# "enviando", a ordem pode ter chegado à corretora (spec §5.2)
DESFECHOS_ENTRADA = frozenset({"recusada", "executada", "parcial", "adotada",
                               "perdida", "nao_entrou", "aceita"})
_COLUNAS = ("evento_id", "quando", "tipo", "conta_id", "ligacao_id", "entry_ts",
            "lado", "contratos", "simbolo", "ticket", "retcode", "preco_papel",
            "preco", "atraso_ms", "tentativa", "motivo")
_DATAS = ("quando", "entry_ts")


def _para_json(ev: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in ev.items()}


def _de_json(ev: dict) -> dict:
    for k in _DATAS:
        if ev.get(k):
            ev[k] = datetime.fromisoformat(ev[k])
    return ev


class Diario:
    def __init__(self, pasta, dia: date, origem: str = "demo"):
        self.pasta, self.dia, self.origem = Path(pasta), dia, origem
        self.arquivo = self.pasta / f"{dia:%Y-%m-%d}.jsonl"
        self._quebrar_linha = False
        self._seq = 0
        self.eventos: list[dict] = self._ler()

    def _ler(self) -> list[dict]:
        if not self.arquivo.exists():
            return []
        texto = self.arquivo.read_text(encoding="utf-8")
        # queda no meio da escrita deixa a última linha sem "\n": a próxima
        # escrita começaria nela e as duas virariam lixo juntas
        self._quebrar_linha = bool(texto) and not texto.endswith("\n")
        out, brutas, maior = [], 0, 0
        # só a quebra "\n" separa linhas: splitlines() também quebra em U+2028,
        # \x0b etc., que json.dumps(ensure_ascii=False) deixa passar dentro
        # de um texto
        for linha in texto.split("\n"):
            if not linha.strip():
                continue
            brutas += 1
            try:
                ev = _de_json(json.loads(linha))
                if not isinstance(ev, dict) or "tipo" not in ev:
                    continue
                out.append(ev)
                maior = max(maior, int(str(ev.get("evento_id", "")).rsplit("-", 1)[-1]))
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                continue
        # linha pulada (queda, lixo) não pode devolver o número dela ao
        # próximo evento: o id repetido travaria o espelho no banco para sempre
        self._seq = max(maior, brutas)
        return out

    def registrar(self, tipo: str, *, quando: datetime, **campos) -> dict:
        if tipo not in TIPOS:
            raise ValueError(f"tipo de evento de ordem desconhecido: {tipo}")
        self._seq += 1
        ev = {"evento_id": f"{self.origem}-{self.dia:%Y%m%d}-{self._seq:06d}",
              "quando": quando, "tipo": tipo, **campos}
        self.pasta.mkdir(parents=True, exist_ok=True)
        with open(self.arquivo, "a", encoding="utf-8") as f:
            if self._quebrar_linha:
                f.write("\n")
                self._quebrar_linha = False
            f.write(json.dumps(_para_json(ev), ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.eventos.append(ev)
        return ev

    # ------------------------------------------------------ estado derivado
    def _da(self, lig, entry_ts, *tipos):
        return [e for e in self.eventos
                if e.get("ligacao_id") == lig and e.get("entry_ts") == entry_ts
                and (not tipos or e["tipo"] in tipos)]

    def enviada(self, lig, entry_ts) -> bool:
        return bool(self._da(lig, entry_ts, "enviando"))

    def ticket(self, lig, entry_ts) -> int | None:
        evs = self._da(lig, entry_ts, "executada", "parcial", "adotada")
        return int(evs[-1]["ticket"]) if evs and evs[-1].get("ticket") else None

    def tentativas(self, lig, entry_ts) -> int:
        return len(self._da(lig, entry_ts, "enviando"))

    def registrado(self, lig, entry_ts, tipo) -> bool:
        return bool(self._da(lig, entry_ts, tipo))

    def ultimo_motivo(self, lig, entry_ts) -> str | None:
        evs = [e for e in self._da(lig, entry_ts) if e.get("motivo")]
        return evs[-1]["motivo"] if evs else None

    def saida_desde(self, ticket) -> datetime | None:
        """Desde quando a saída deste ticket está pendente (None = não está)."""
        desde = None
        for e in self.eventos:
            if e.get("ticket") != ticket:
                continue
            if e["tipo"] == "saida_enviando" and desde is None:
                desde = e["quando"]
            elif e["tipo"] in ("saida_executada", "saiu_antes"):
                desde = None
        return desde

    def desfecho(self, lig, entry_ts) -> str | None:
        """Tipo do desfecho final da ÚLTIMA tentativa de entrada (None = sem
        tentativa, ou tentativa ainda sem desfecho)."""
        res = None
        for e in self._da(lig, entry_ts):
            if e["tipo"] == "enviando":
                res = None
            elif e["tipo"] in DESFECHOS_ENTRADA:
                res = e["tipo"]
        return res

    def tentativa_sem_desfecho(self, lig, entry_ts) -> datetime | None:
        """Hora do último `enviando` (ou `incerta` depois dele) se a última
        tentativa ficou sem desfecho final — a ordem pode ter executado.
        Qualquer outro evento (ex.: chamado) não conta como desfecho."""
        ref, aberta = None, False
        for e in self._da(lig, entry_ts):
            if e["tipo"] == "enviando":
                ref, aberta = e["quando"], True
            elif e["tipo"] in DESFECHOS_ENTRADA:
                aberta = False
            elif e["tipo"] == "incerta" and aberta:
                ref = e["quando"]
        return ref if aberta else None

    def protecao_pendente_desde(self, ticket) -> datetime | None:
        """Desde quando a proteção deste ticket está sendo pedida sem
        sucesso: a 1ª `protecao_enviando` depois da última `protecao`."""
        desde = None
        for e in self.eventos:
            if e.get("ticket") != ticket:
                continue
            if e["tipo"] == "protecao_enviando" and desde is None:
                desde = e["quando"]
            elif e["tipo"] == "protecao":
                desde = None
        return desde

    def protecao_registrada(self, ticket):
        """(lado, stop_px, alvo_px) gravados no diário para o ticket, ou None
        — para conferir a proteção sem o papel (indisponível)."""
        lado, res = None, None
        for e in self.eventos:
            if e.get("ticket") != ticket or e["tipo"] not in (
                    "executada", "parcial", "adotada", "protecao"):
                continue
            lado = e.get("lado", lado)
            if e.get("stop_px") is not None and lado is not None:
                res = (lado, e["stop_px"], e.get("alvo_px"))
        return res

    def travada(self, conta_id) -> dict | None:
        evs = [e for e in self.eventos
               if e["tipo"] == "conta_travada" and e.get("conta_id") == conta_id]
        return evs[-1] if evs else None

    def ultimo(self, lig, entry_ts) -> dict | None:
        evs = self._da(lig, entry_ts)
        return evs[-1] if evs else None

    def ultima_tentativa(self, tipo, *, ticket=None, lig=None, entry_ts=None):
        """Hora da última `tipo` (enviando/saida_enviando/protecao_enviando)
        — para o intervalo mínimo de 1 s entre tentativas."""
        for e in reversed(self.eventos):
            if e["tipo"] != tipo:
                continue
            if ticket is not None and e.get("ticket") != ticket:
                continue
            if lig is not None and (e.get("ligacao_id"), e.get("entry_ts")) != (lig, entry_ts):
                continue
            return e["quando"]
        return None

    def executada_em(self, lig, entry_ts) -> datetime | None:
        evs = self._da(lig, entry_ts, "executada", "parcial", "adotada")
        return evs[0]["quando"] if evs else None

    def _abertos(self) -> dict:
        abertos, fechados = {}, set()
        for e in self.eventos:
            if not e.get("ticket"):
                continue
            if e["tipo"] in ("executada", "parcial", "adotada"):
                abertos[int(e["ticket"])] = (e.get("ligacao_id"), e.get("entry_ts"))
            elif e["tipo"] in ("saida_executada", "saiu_antes"):
                fechados.add(int(e["ticket"]))
        return {t: v for t, v in abertos.items() if t not in fechados}

    def tickets_abertos(self, lig) -> list[tuple[int, datetime]]:
        """(ticket, entry_ts) que a automação abriu nesta ligação e o diário
        ainda não viu sair — para registrar a saída pelo servidor mesmo com
        o papel já zerado."""
        return [(t, ts) for t, (l, ts) in self._abertos().items() if l == lig]

    def ligacoes_abertas(self) -> set:
        """Ligações com algum ticket aberto no diário."""
        return {l for l, _ in self._abertos().values() if l}

    def comandos_do_dia(self, tipo) -> list[dict]:
        return [e for e in self.eventos
                if e["tipo"] == "comando" and e.get("motivo") == tipo]

    # ------------------------------------------------------------- espelho
    def espelhar(self, con) -> int:
        """Leva ao banco o que ainda não está lá; devolve quantos. Chamado
        com a conexão de escrita já aberta pela captura."""
        prefixo = f"%-{self.dia:%Y%m%d}-%"
        ja = {r[0] for r in con.execute(
            "SELECT evento_id FROM ordens_eventos WHERE evento_id LIKE ?",
            [prefixo]).fetchall()}
        novos = [e for e in self.eventos if e["evento_id"] not in ja]
        inseridos = 0
        for e in novos:
            extra = {k: v for k, v in e.items() if k not in _COLUNAS}
            # a origem é o prefixo do próprio evento_id (demo ou real), não a
            # do Diario: o arquivo do dia pode trazer eventos de qualquer uma
            origem = str(e["evento_id"]).partition("-")[0] or self.origem
            try:
                # uma linha ruim não pode impedir as outras de chegar ao banco
                r = con.execute(
                    f"INSERT INTO ordens_eventos ({', '.join(_COLUNAS)}, origem, dados) "
                    f"VALUES ({', '.join('?' * (len(_COLUNAS) + 2))}) "
                    "ON CONFLICT (evento_id) DO NOTHING",
                    [e.get(c) for c in _COLUNAS] + [origem]
                    + [json.dumps(_para_json(extra), ensure_ascii=False, default=str)
                       if extra else None]).fetchone()
                inseridos += int(r[0]) if r else 0
            except Exception:
                log.exception("evento %s não espelhado", e.get("evento_id"))
        return inseridos


def espelhar_pendentes(pasta, con, dias: int = 5, origem: str = "demo",
                       hoje: date | None = None) -> int:
    """Espelha no banco os arquivos dos últimos `dias` dias da pasta.

    `pasta` é uma pasta ou uma lista de pastas (todas com a mesma `origem`).
    Chamada na subida, na virada do dia e na escrita da conferência: os
    eventos depois do último candle só chegam ao banco por aqui. `hoje` só
    existe para o teste fixar o relógio. Arquivos de nome fora de
    AAAA-MM-DD.jsonl são ignorados."""
    pastas = [pasta] if isinstance(pasta, (str, Path)) else list(pasta)
    corte = (hoje or date.today()) - timedelta(days=dias - 1)
    total = 0
    for pasta in pastas:
        pasta = Path(pasta)
        if not pasta.is_dir():
            continue
        for arq in sorted(pasta.glob("*.jsonl")):
            try:
                dia = date.fromisoformat(arq.stem)
            except ValueError:
                continue
            if dia >= corte:
                try:
                    total += Diario(pasta, dia, origem).espelhar(con)
                except Exception:
                    log.exception("espelho do dia %s falhou", dia)
    return total
