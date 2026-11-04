"""O que o app chama para mandar na busca. Nada aqui roda a busca: abre o
processo `busca.py`, escreve `controle.json` e lê `estado.json` + banco.

Vivo = a trava `rodando.lock` está presa. É trava do Windows (como a da
captura): se o processo morre, o sistema solta sozinho. Nunca pid: no
Windows `os.kill(pid, 0)` MATA o processo, e o pid do `Popen` é o do
lançador do venv, não o da busca.

Uma busca viva por vez (desenho §5): duas buscas dividiriam os núcleos que o
usuário escolheu e o banco da busca teria dois escritores.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from core import db_manager as db

from . import banco
from .motor import CONTROLE_PADRAO, escrever_json, ler_controle, ler_json

RAIZ = Path(__file__).resolve().parents[2]
ROTEIRO = RAIZ / "busca.py"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
FLAGS = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | BELOW_NORMAL_PRIORITY_CLASS


class BuscaJaRodando(RuntimeError):
    pass


class BuscaViva(RuntimeError):
    pass


def travar(caminho: Path):
    """Mesma trava da captura (`captura.travar`): devolve o arquivo travado
    (guarde-o pela vida do processo) ou None se outro já tem."""
    import msvcrt

    caminho.parent.mkdir(parents=True, exist_ok=True)
    f = open(caminho, "a+")
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except OSError:
        f.close()
        return None


def soltar(f) -> None:
    import msvcrt

    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        f.close()


def _trava() -> Path:
    return banco.PASTA / "rodando.lock"


def ativa() -> int | None:
    """O id da busca com processo vivo, ou None."""
    f = travar(_trava())
    if f is not None:
        soltar(f)
        return None
    info = ler_json(banco.PASTA / "rodando.json")
    return info.get("busca_id")


def _caminho_controle(busca_id: int) -> Path:
    return banco.pasta_da(busca_id) / "controle.json"


_TRAVA_AJUSTE = threading.Lock()


def ajustar(busca_id: int, **campos) -> None:
    """Muda núcleos, "Parar às", limite ou pedido — vale no próximo lote.
    Ler-mudar-gravar sob trava: dois callbacks ao mesmo tempo não podem
    apagar o ajuste um do outro."""
    with _TRAVA_AJUSTE:
        atual = ler_controle(banco.pasta_da(busca_id))
        escrever_json(_caminho_controle(busca_id), {**atual, **campos})
        _registrar(busca_id, campos)


def _registrar(busca_id: int, campos: dict) -> None:
    """Diário dos pedidos da tela (`acoes.log`): quando alguém pergunta "eu
    cliquei em Pausar e ela concluiu?", a resposta está aqui."""
    try:
        pasta = banco.pasta_da(busca_id)
        pasta.mkdir(parents=True, exist_ok=True)
        with open(pasta / "acoes.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {campos}\n")
    except OSError:
        pass                            # diário não pode impedir o comando


def resolver_periodo(config: dict) -> dict:
    """Datas FIXAS na criação: sem "até", continuar outro dia leria barras
    novas, e folds, holdout e notas mudariam no meio da busca."""
    if config.get("de") and config.get("ate"):
        return config
    ts = db.read_bars_parquet(config["simbolo"], config.get("de"), config.get("ate"))["ts"]
    import numpy as np

    def iso(v):
        return str(np.datetime64(v, "s"))

    return {**config, "de": config.get("de") or iso(ts[0]),
            "ate": config.get("ate") or iso(ts[-1])}


FOLGA_ABRIR_S = 60   # o processo leva uns segundos até pegar a trava


def _abrir(busca_id: int) -> None:
    pasta = banco.pasta_da(busca_id)
    pasta.mkdir(parents=True, exist_ok=True)
    # sem isto, a tela via "Interrompida" logo depois do Iniciar: o banco já
    # diz rodando e o processo ainda não pegou a trava
    ajustar(busca_id, aberto_em=time.time())
    log = open(pasta / "processo.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, str(ROTEIRO), str(busca_id), "--pasta", str(banco.PASTA),
         "--banco", str(banco.CAMINHO), "--db-principal", str(db.DB_PATH)],
        cwd=str(RAIZ), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=FLAGS if sys.platform == "win32" else 0, close_fds=True)
    log.close()


def iniciar(config: dict, **controle) -> int:
    if ativa() is not None:
        raise BuscaJaRodando("já existe uma busca rodando")
    bid = banco.criar(resolver_periodo(config))
    escrever_json(_caminho_controle(bid), {**CONTROLE_PADRAO, **controle})
    _abrir(bid)
    return bid


def continuar(busca_id: int) -> None:
    viva = ativa()
    if viva == busca_id:            # pausada com o processo vivo
        ajustar(busca_id, pedido=None)
        return
    if viva is not None:
        raise BuscaJaRodando("outra busca está rodando")
    ajustar(busca_id, pedido=None)  # parada, concluída ou interrompida
    _abrir(busca_id)


def pausar(busca_id: int) -> None:
    ajustar(busca_id, pedido="pausar")


def parar(busca_id: int) -> None:
    """"Parar e guardar". Sem processo (interrompida ou pausada que caiu),
    só marca como concluída: o que foi testado já está no banco."""
    if ativa() == busca_id or _abrindo(busca_id):
        # subindo: o pedido fica no controle e o processo o lê no 1º lote
        ajustar(busca_id, pedido="parar")
    else:
        ajustar(busca_id, pedido=None)
        banco.marcar_status(busca_id, "concluida")


def _abrindo(busca_id: int) -> bool:
    c = ler_controle(banco.pasta_da(busca_id))
    return time.time() - float(c.get("aberto_em") or 0) < FOLGA_ABRIR_S


def ler(busca_id: int) -> dict:
    """Estado para a tela. "interrompida" = o banco diz rodando/pausada e a
    trava está solta (o processo morreu: PC desligou, janela fechada)."""
    pasta = banco.pasta_da(busca_id)
    estado = ler_json(pasta / "estado.json")
    try:
        b = banco.ler_busca(busca_id)
    except banco.BancoOcupado:
        b = None
    status = (b or {}).get("status") or estado.get("status") or "parada"
    vivo = ativa() == busca_id
    controle = ler_controle(pasta)
    abrindo = time.time() - float(controle.get("aberto_em") or 0) < FOLGA_ABRIR_S
    if status in ("rodando", "pausada") and not vivo and not abrindo:
        status = "interrompida"
    return {**estado, "status": status, "vivo": vivo, "abrindo": abrindo and not vivo,
            "controle": controle, "busca": b}


def excluir(busca_id: int) -> None:
    if ativa() == busca_id:
        raise BuscaViva("a busca está rodando; pare antes de excluir")
    banco.excluir(busca_id)
