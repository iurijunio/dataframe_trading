"""Monta o pacote de um portfólio para o `prop_live` (contrato em `core/contratos/pacote_mesa.py`).

Só LÊ o banco, pelas funções que a tela e o papel já usam. O `engine_plan` de cada variante é o
mesmo dicionário que o papel entrega a `papel.calcular`: `plano.detalhes(plano_id)`, do plano em
vigor (`variantes.plano_em_vigor`), em unidade humana, sem conversão (ver `core/ativo.py`).

O pacote tem UM instrumento: portfólio com moedas ou ativos diferentes é recusado.
"""

from __future__ import annotations

import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from . import ativo, codigo
from . import db_manager as db
from . import engine
from . import plano as plano_db
from . import portfolio as P
from . import variantes
from .contratos import pacote_mesa as contrato

RAIZ = Path(__file__).resolve().parent.parent
PASTAS_DO_CODIGO = ("core", "strategies", "configs")
BANCO_PRESO = "o banco está ocupado: feche a captura ou tente de novo"


class ExportacaoRecusada(Exception):
    """Portfólio que não dá para exportar; a mensagem diz o que corrigir."""


def limites_do_disjuntor(disjuntor: dict) -> dict[str, float]:
    """Os números do disjuntor do plano, com nome de caminho (`nivel2.queda`).

    Só entram escalares numéricos: `None` ("não definido"), texto, lista (a faixa por pregão) e
    booleano ficam de fora, porque o limite ausente não vale como zero.
    """
    saida: dict[str, float] = {}
    _achatar(disjuntor or {}, "", saida)
    return saida


def _achatar(no: dict, prefixo: str, saida: dict[str, float]) -> None:
    for chave, valor in no.items():
        nome = f"{prefixo}{chave}"
        if isinstance(valor, dict):
            _achatar(valor, nome + ".", saida)
        elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
            saida[nome] = float(valor)


def rodar_git(args: list[str]) -> subprocess.CompletedProcess:
    """Roda o git na raiz do Dataframe (os testes trocam esta função por um git simulado)."""
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=False)


def commit_da_plataforma() -> str:
    """`git rev-parse HEAD` do Dataframe; recusa se o código do motor tem mudança sem commit."""
    sujo = rodar_git(["status", "--porcelain", "--", *PASTAS_DO_CODIGO])
    if sujo.returncode != 0:
        raise ExportacaoRecusada(f"não consegui ler o estado do git: {sujo.stderr.strip()}")
    if sujo.stdout.strip():
        raise ExportacaoRecusada(
            "há mudanças não commitadas no código do motor/estratégias/configs: "
            "faça commit antes de exportar"
        )
    saida = rodar_git(["rev-parse", "HEAD"])
    if saida.returncode != 0:
        raise ExportacaoRecusada(f"não consegui ler o commit do Dataframe: {saida.stderr.strip()}")
    return saida.stdout.strip()


def agora_utc() -> datetime:
    """O instante atual em UTC (os testes trocam por um instante fixo)."""
    return datetime.now(timezone.utc)


def hoje_local() -> date:
    """O dia do calendário do PC (os testes trocam por um dia fixo)."""
    return date.today()


def _portfolio_de(portfolio_id: int) -> dict:
    for p in P.listar():
        if p["portfolio_id"] == portfolio_id:
            return p
    raise ExportacaoRecusada(f"o portfólio {portfolio_id} não existe")


def _plano_em_vigor(membro: dict, hoje: date) -> dict:
    vigor = variantes.plano_em_vigor(membro["variante_id"], hoje)
    if vigor is None:
        raise ExportacaoRecusada(f"a variante '{membro['nome']}' está ligada e sem plano em vigor")
    return plano_db.detalhes(vigor["plano_id"])


def _hash_do_codigo(membro: dict, plano: dict, estrategia: str) -> str:
    """Hash do código no disco; recusa se sumiu ou mudou desde o plano (como o papel faz).

    Plano antigo, sem `codigo_hash`, é aceito.
    """
    hash_disco = codigo.hash_estrategia(estrategia)
    if hash_disco is None:
        raise ExportacaoRecusada(f"a variante '{membro['nome']}': código da estratégia não encontrado")
    if plano.get("codigo_hash") and plano["codigo_hash"] != hash_disco:
        raise ExportacaoRecusada(
            f"a variante '{membro['nome']}': código mudou desde o plano (plano #{plano['plano_id']})"
        )
    return hash_disco


def _variante(membro: dict, plano: dict) -> contrato.VariantePacote:
    timeframe = (plano.get("profile") or {}).get("timeframe")
    if not timeframe:
        raise ExportacaoRecusada(f"o plano #{plano['plano_id']} não grava o timeframe")
    estrategia = plano["strategy"] or membro["estrategia"]
    return contrato.VariantePacote(
        id=membro["variante_id"],
        name=membro["nome"],
        strategy=estrategia,
        plan_id=plano["plano_id"],
        symbol=plano["symbol"],
        timeframe=timeframe,
        contracts=int(plano["contratos"]),
        code_hash=_hash_do_codigo(membro, plano, estrategia),
        breaker=limites_do_disjuntor(plano.get("disjuntor")),
        engine_plan=plano,
    )


def _moeda_do_ativo(simbolo: str) -> str:
    try:
        return ativo.ficha(simbolo).currency
    except FileNotFoundError as erro:
        raise ExportacaoRecusada(f"o ativo '{simbolo}' não tem ficha (YAML) em configs/instruments") from erro


def _confere_instrumento_unico(variantes_pacote: list[contrato.VariantePacote]) -> str:
    simbolos = sorted({v.symbol for v in variantes_pacote})
    moedas = sorted({_moeda_do_ativo(s) for s in simbolos})
    if len(moedas) > 1:
        raise ExportacaoRecusada(f"o pacote não aceita moedas diferentes: {', '.join(moedas)}")
    if len(simbolos) > 1:
        raise ExportacaoRecusada(f"o pacote tem um ativo só; o portfólio usa {', '.join(simbolos)}")
    return simbolos[0]


def _variantes_do_dia(portfolio_id: int, dia: date) -> list[contrato.VariantePacote]:
    ligados = [m for m in P.membros(portfolio_id, dia) if m["ligada"]]
    if not ligados:
        raise ExportacaoRecusada("o portfólio não tem nenhuma variante ligada")
    return [_variante(m, _plano_em_vigor(m, dia)) for m in ligados]


def _simbolo_no_dia(portfolio_id: int, dia: date) -> str | None:
    """O ativo do primeiro plano em vigor no dia entre as variantes ligadas, sem validar nada."""
    for membro in P.membros(portfolio_id, dia):
        vigor = variantes.plano_em_vigor(membro["variante_id"], dia) if membro["ligada"] else None
        if vigor is not None:
            return plano_db.detalhes(vigor["plano_id"])["symbol"]
    return None


def _simbolo_provisorio(portfolio_id: int, dia: date) -> str:
    """Só descobre o ativo (para achar o pregão): o plano em vigor no dia ou, na falta, no próximo
    dia útil (plano gravado na sexta, ou variante nova, só vale na segunda)."""
    simbolo = _simbolo_no_dia(portfolio_id, dia) or _simbolo_no_dia(
        portfolio_id, plano_db.proximo_dia_util(dia)
    )
    if simbolo is None:
        _variantes_do_dia(portfolio_id, dia)  # sem ligada ou sem plano: a recusa de sempre
        raise ExportacaoRecusada("nenhuma variante ligada tem plano em vigor")
    return simbolo


def _itens_do_pregao(portfolio_id: int, hoje: date | None) -> tuple[list[contrato.VariantePacote], date]:
    """Variantes com o plano em vigor no pregão e o dia desse pregão.

    Sem `hoje`, o pregão vem da ficha do ativo (CME vira o dia às 18:00 de NY). O ativo só se
    conhece pelo plano: acha-se o ativo sem validar, calcula-se o pregão e só nele se valida.
    """
    if hoje is not None:
        return _variantes_do_dia(portfolio_id, hoje), hoje
    simbolo = _simbolo_provisorio(portfolio_id, hoje_local())
    pregao = ativo.pregao_de(agora_utc(), ativo.ficha(simbolo))
    itens = _variantes_do_dia(portfolio_id, pregao)
    final = _confere_instrumento_unico(itens)
    if final != simbolo:
        raise ExportacaoRecusada(
            f"o ativo muda de {simbolo} para {final} no pregão de {pregao:%d/%m/%Y}: "
            "tente de novo depois da virada do plano"
        )
    return itens, pregao


def _montar(portfolio_id: int, hoje: date | None) -> contrato.Pacote:
    cadastro = _portfolio_de(portfolio_id)
    if not cadastro["capital"]:
        raise ExportacaoRecusada("defina o capital do portfólio antes de exportar")
    itens, pregao = _itens_do_pregao(portfolio_id, hoje)
    simbolo = _confere_instrumento_unico(itens)
    ficha = db.load_instrument_yaml(simbolo)
    return contrato.Pacote(
        format_version=contrato.FORMATO,
        exported_at=agora_utc().replace(microsecond=0),
        platform_commit=commit_da_plataforma(),
        engine_version=engine.VERSAO,
        portfolio=contrato.PortfolioPacote(
            portfolio_id, cadastro["nome"], float(cadastro["capital"]), ativo.ficha(simbolo).currency
        ),
        variants=tuple(itens),
        instrument=ficha,
        session_date=pregao,
    )

def montar_pacote(portfolio_id: int, hoje: date | None = None) -> contrato.Pacote:
    """O pacote do portfólio. Banco preso (captura gravando): erro claro, sem insistir."""
    try:
        return _montar(portfolio_id, hoje)
    except RuntimeError as erro:
        if "ocupado" in str(erro):
            raise ExportacaoRecusada(BANCO_PRESO) from erro
        raise


def exportar(portfolio_id: int, pasta: Path, hoje: date | None = None) -> Path:
    """Grava `portfolio_<id>.json` na pasta e devolve o caminho."""
    pacote = montar_pacote(portfolio_id, hoje)
    return contrato.gravar(pacote, Path(pasta) / f"portfolio_{portfolio_id}.json")

