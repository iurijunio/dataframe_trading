"""Pacote que o Dataframe exporta para o projeto `prop_live` (formato v1).

É a única casa das chaves do JSON: quem grava ou lê o pacote passa por aqui, ninguém monta o
dicionário na mão. As chaves e os campos são em inglês porque são a superfície entre os dois
projetos; `prop_live/adapters/platform/package.py` lê exatamente este formato.

Sem banco aqui: quem monta o pacote é `core/exportar_pacote.py`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

FORMATO = 1
TENTATIVAS_REPLACE = 5
ESPERA_REPLACE_S = 0.2


class PacoteInvalido(Exception):
    """Arquivo que não é um pacote v1 (versão diferente, campo faltando, JSON quebrado)."""


@dataclass(frozen=True)
class PortfolioPacote:
    id: int
    name: str
    capital: float
    currency: str


@dataclass(frozen=True)
class VariantePacote:
    id: int  # variante_id
    name: str
    strategy: str
    plan_id: int
    symbol: str
    timeframe: str
    contracts: int
    breaker: dict  # nome do limite -> valor numérico do disjuntor do plano
    engine_plan: dict  # o plano como `papel.calcular` o recebe, em unidade humana


@dataclass(frozen=True)
class Pacote:
    format_version: int
    exported_at: datetime
    platform_commit: str
    engine_version: str
    portfolio: PortfolioPacote
    variants: tuple[VariantePacote, ...]
    instrument: dict  # o YAML do ativo inteiro, como o backtest o usa
    session_date: date  # pregão (relógio do ativo) a que o pacote se refere


def _json_padrao(obj):
    """Datas do plano (created_at, vale_a_partir...) viram texto ISO."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"{type(obj).__name__} não cabe no pacote")


def para_dicionario(pacote: Pacote) -> dict:
    """O pacote como o objeto JSON v1."""
    return {
        "format_version": pacote.format_version,
        "exported_at": pacote.exported_at.isoformat(),
        "platform_commit": pacote.platform_commit,
        "engine_version": pacote.engine_version,
        "portfolio": {
            "id": pacote.portfolio.id,
            "name": pacote.portfolio.name,
            "capital": pacote.portfolio.capital,
            "currency": pacote.portfolio.currency,
        },
        "variants": [_variante_para_dicionario(v) for v in pacote.variants],
        "instrument": pacote.instrument,
        "session_date": pacote.session_date.isoformat(),
    }


def _variante_para_dicionario(v: VariantePacote) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "strategy": v.strategy,
        "plan_id": v.plan_id,
        "symbol": v.symbol,
        "timeframe": v.timeframe,
        "contracts": v.contracts,
        "breaker": dict(v.breaker),
        "engine_plan": v.engine_plan,
    }


def substituir(origem: Path, destino: Path) -> None:
    """`os.replace` com nova chance: no Windows o leitor (prop_live) pode segurar o arquivo."""
    for tentativa in range(1, TENTATIVAS_REPLACE + 1):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if tentativa == TENTATIVAS_REPLACE:
                raise
            time.sleep(ESPERA_REPLACE_S)


def gravar(pacote: Pacote, caminho: Path) -> Path:
    """Grava o pacote por arquivo temporário + rename: quem lê nunca vê metade."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(para_dicionario(pacote), ensure_ascii=False, indent=2, default=_json_padrao)
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        temporario.write_text(texto, encoding="utf-8")
        substituir(temporario, caminho)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    return caminho


def ler(caminho: Path) -> Pacote:
    """Lê e valida um pacote v1; recusa versão diferente."""
    try:
        bruto = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise PacoteInvalido(f"{Path(caminho).name}: {erro}") from erro
    return de_dicionario(bruto)


def de_dicionario(bruto: dict) -> Pacote:
    if not isinstance(bruto, dict) or bruto.get("format_version") != FORMATO:
        versao = bruto.get("format_version") if isinstance(bruto, dict) else None
        raise PacoteInvalido(f"format_version {versao!r}, esperado {FORMATO}")
    try:
        return _montar(bruto)
    except (KeyError, TypeError, ValueError) as erro:
        raise PacoteInvalido(f"campo faltando ou inválido: {erro}") from erro


def _montar(bruto: dict) -> Pacote:
    pf = bruto["portfolio"]
    return Pacote(
        format_version=FORMATO,
        exported_at=datetime.fromisoformat(bruto["exported_at"]),
        platform_commit=str(bruto["platform_commit"]),
        engine_version=str(bruto["engine_version"]),
        portfolio=PortfolioPacote(int(pf["id"]), str(pf["name"]), float(pf["capital"]), str(pf["currency"])),
        variants=tuple(_variante(v) for v in bruto["variants"]),
        instrument=dict(bruto["instrument"]),
        session_date=date.fromisoformat(bruto["session_date"]),
    )


def _variante(v: dict) -> VariantePacote:
    return VariantePacote(
        id=int(v["id"]),
        name=str(v["name"]),
        strategy=str(v["strategy"]),
        plan_id=int(v["plan_id"]),
        symbol=str(v["symbol"]),
        timeframe=str(v["timeframe"]),
        contracts=int(v["contracts"]),
        breaker={str(k): float(x) for k, x in v["breaker"].items()},
        engine_plan=dict(v["engine_plan"]),
    )

