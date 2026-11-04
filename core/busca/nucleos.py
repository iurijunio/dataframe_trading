"""Os núcleos da busca: um processo por núcleo, cada um com a sua fila.

Não é um ProcessPoolExecutor de propósito: no pool o núcleo que pega a tarefa
é qualquer um, e o cache de sinais preparados de cada núcleo quase nunca
acertaria. Aqui o dono de um sinal (`chave_essencial`) é sempre o mesmo
núcleo, escolhido por um hash estável — é o que faz "calcular uma vez, testar
muitas" acontecer de verdade (desenho §4.2).

Processos e não threads: a busca roda num processo à parte (nada de servidor
web a reimportar no `spawn`), e o ADX e as estratégias em NumPy seguram o
GIL — com 20 threads a busca andaria como uma.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import zlib


def _laco(simbolo, de, ate, estrategia, entrada, saida):
    from . import avaliador, prioridade

    prioridade.baixar()
    avaliador.iniciar_nucleo(simbolo, de, ate, estrategia)
    saida.put(("pronto", None))
    while True:
        msg = entrada.get()
        if msg is None:
            return
        pedido, chave, tarefas, ctx = msg
        try:
            res = avaliador.avaliar_grupo(chave, tarefas, ctx)
        except Exception as erro:   # o grupo inteiro falhou (ex.: o sinal)
            res = [{"teste_n": t, "combo": c, "descartada": f"erro: {erro}",
                    "objetivo": avaliador.INVALIDA, "valida": False}
                   for t, c in tarefas]
        saida.put((pedido, res))


def dono(chave: tuple, n: int) -> int:
    """Hash ESTÁVEL entre execuções (o `hash()` do Python muda a cada
    processo): a mesma chave cai sempre no mesmo núcleo."""
    return zlib.crc32(repr(chave).encode("utf-8")) % n


class Nucleos:
    def __init__(self, n: int, simbolo: str, de, ate, estrategia: str,
                 espera_s: float = 600.0):
        self.n = max(1, int(n))
        self._ctx = mp.get_context("spawn")
        self._saida = self._ctx.Queue()
        self._entradas = [self._ctx.Queue() for _ in range(self.n)]
        self._procs = [self._ctx.Process(
            target=_laco, args=(simbolo, de, ate, estrategia, q, self._saida),
            daemon=True) for q in self._entradas]
        for p in self._procs:
            p.start()
        self._espera_s = espera_s
        self._pedido = 0
        prontos = 0
        while prontos < self.n:
            msg = self._receber()
            if msg[0] == "pronto":
                prontos += 1

    def _receber(self):
        while True:
            try:
                return self._saida.get(timeout=1.0)
            except queue.Empty:
                mortos = [p for p in self._procs if not p.is_alive()]
                if mortos:
                    raise RuntimeError(
                        f"núcleo caiu (código {mortos[0].exitcode})")

    def avaliar(self, grupos: list[tuple[tuple, list]], ctx: dict) -> list[dict]:
        """Manda cada grupo ao núcleo dono e junta tudo (sem ordem: quem
        ordena é o motor, pelo `teste_n`)."""
        self._pedido += 1
        for chave, tarefas in grupos:
            self._entradas[dono(chave, self.n)].put((self._pedido, chave, tarefas, ctx))
        out, faltam = [], len(grupos)
        while faltam:
            pedido, res = self._receber()
            if pedido == self._pedido:
                out += res
                faltam -= 1
        return out

    def fechar(self):
        for q in self._entradas:
            try:
                q.put(None)
            except Exception:
                pass
        for p in self._procs:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()
