"""Impressão digital do código de uma estratégia.

O plano grava parâmetros, mas os números que ele promete vieram de uma
VERSÃO do código. Se o arquivo muda depois, o que roda ao vivo já não é o
que foi aprovado — e nada avisava (achado real: rompimento_abertura.py
editado com o plano #4 ativo, 30/09/2026).
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from . import db_manager as db


def _importados(arquivo: Path) -> set[str]:
    """Módulos da pasta `strategies` que o arquivo importa (`from . import
    x`, `from .x import y`, `from strategies import x`, `import
    strategies.x`)."""
    try:
        arvore = ast.parse(arquivo.read_bytes())
    except (SyntaxError, ValueError):
        # arquivo quebrado: o texto dele já muda a impressão sozinho
        return set()
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            if no.level == 1 and no.module is None:
                nomes |= {a.name for a in no.names}
            elif no.level == 1:
                nomes.add(no.module.split(".")[0])
            elif no.level == 0 and no.module == "strategies":
                nomes |= {a.name for a in no.names}
            elif no.level == 0 and (no.module or "").startswith("strategies."):
                nomes.add(no.module.split(".")[1])
        elif isinstance(no, ast.Import):
            for a in no.names:
                if a.name.startswith("strategies."):
                    nomes.add(a.name.split(".")[1])
    return nomes


def ajudantes(estrategia: str, pasta: Path | None = None) -> list[str]:
    """Os módulos compartilhados que a estratégia usa (direto ou pelos
    próprios ajudantes), em ordem alfabética — fora `base`, que entra
    sempre, e ela mesma."""
    pasta = Path(pasta) if pasta else db.ROOT / "strategies"
    vistos: set[str] = set()
    fila = [estrategia]
    while fila:
        nome = fila.pop()
        arquivo = pasta / f"{nome}.py"
        if not arquivo.exists():
            continue
        for x in _importados(arquivo):
            if x not in vistos and x not in ("base", estrategia) \
                    and (pasta / f"{x}.py").exists():
                vistos.add(x)
                fila.append(x)
    return sorted(vistos)


def hash_estrategia(estrategia: str, pasta: Path | None = None) -> str | None:
    pasta = Path(pasta) if pasta else db.ROOT / "strategies"
    arquivo = pasta / f"{estrategia}.py"
    if not arquivo.exists():
        return None
    h = hashlib.sha256()
    # base.py entra junto: é o contrato de toda estratégia, e mudar ele
    # muda o sinal de todas. Os ajudantes que ela importa (ex.: saida.py,
    # que decide a saída) também: mudar um muda os trades dela. Estratégia
    # sem ajudante fica com o hash de antes de eles entrarem.
    partes = [pasta / "base.py",
              *(pasta / f"{x}.py" for x in ajudantes(estrategia, pasta)),
              arquivo]
    for parte in partes:
        if parte.exists():
            # o git troca LF por CRLF nesta máquina; sem normalizar, todo
            # checkout acusaria "código mudou"
            h.update(parte.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


# ------------------------------------------------------------ reassinar
# Mexer no código sem mudar o que ele faz (refatoração, opção nova cujo
# padrão reproduz o de antes) também muda a impressão — e o papel do plano
# para com "código mudou desde o plano". Regravar o plano pela Candidata
# trocaria um retrato aprovado por outro só para acertar o hash; reassinar
# troca SÓ o hash, e só depois de o backtest do plano com o código antigo e
# com o novo dar exatamente os mesmos trades (`scripts/reassinar_codigo.py`).

def trades_iguais(antes: dict, depois: dict) -> str | None:
    """None se os dois resultados são idênticos campo a campo; senão a
    primeira diferença, em texto. `antes`/`depois`: `n_trades` e `trades`
    (o dicionário de arrays do `BacktestResult`)."""
    import numpy as np

    if antes["n_trades"] != depois["n_trades"]:
        return f"{antes['n_trades']} trades antes, {depois['n_trades']} depois"
    ta, td = antes["trades"], depois["trades"]
    if set(ta) != set(td):
        return f"campos diferentes: {sorted(set(ta) ^ set(td))}"
    for campo in sorted(ta):
        a, d = np.asarray(ta[campo]), np.asarray(td[campo])
        if a.shape != d.shape or not np.array_equal(a, d):
            iguais = a.shape == d.shape
            onde = (int(np.flatnonzero(a != d)[0]) if iguais else None)
            return (f"campo {campo} diferente"
                    + (f" no trade {onde}" if onde is not None else ""))
    for campo in sorted(set(antes) & set(depois) - {"n_trades", "trades"}):
        a, d = antes[campo], depois[campo]
        if not np.array_equal(np.asarray(a), np.asarray(d)):
            return f"{campo} diferente"
    return None


def reassinar(con, planos: list[dict], *, pasta: Path | None = None) -> list[dict]:
    """Troca `hash_antigo` por `hash_novo` nos planos e nos pregões de papel
    calculados com eles, numa transação só.

    Cada item: `plano_id`, `hash_antigo`, `hash_novo`, `identicos` (o
    resultado da comparação antigo × novo) e `n_trades` comparados. Recusa
    TUDO (ValueError, nada gravado) se algum item não foi provado idêntico
    (ou comparou zero trades — não prova nada), se o plano já não tem o
    hash antigo, ou se o novo não é o do código no disco agora: assinar um
    código que não foi o comparado seria pior que não assinar.

    Nos pregões, só as linhas do PRÓPRIO plano com o hash antigo — é o que
    `papel_backtest._incomparavel` compara com o disco. Devolve, por plano,
    quantas linhas mudaram em cada tabela.
    """
    feitos = []
    for item in planos:
        pid = int(item["plano_id"])
        if item.get("identicos") is not True:
            raise ValueError(f"plano #{pid}: trades não provados idênticos")
        if not item.get("n_trades"):
            raise ValueError(f"plano #{pid}: nenhum trade comparado")
        antigo, novo = item["hash_antigo"], item["hash_novo"]
        if not antigo or not novo or antigo == novo:
            raise ValueError(f"plano #{pid}: hashes inválidos")
        r = con.execute(
            "SELECT p.codigo_hash, coalesce(p.strategy, ev.estrategia) "
            "FROM planos_operacao p LEFT JOIN estrategia_variantes ev "
            "ON ev.variante_id = p.variante_id WHERE p.plano_id = ?",
            [pid]).fetchone()
        if r is None:
            raise ValueError(f"plano #{pid} não existe")
        if r[0] != antigo:
            raise ValueError(f"plano #{pid}: o hash gravado não é o antigo")
        if hash_estrategia(r[1], pasta) != novo:
            raise ValueError(f"plano #{pid}: o hash novo não é o do código "
                             "no disco")
        feitos.append((pid, antigo, novo))

    out = []
    with db.transacao(con):
        for pid, antigo, novo in feitos:
            n_plano = con.execute(
                "UPDATE planos_operacao SET codigo_hash = ? "
                "WHERE plano_id = ? AND codigo_hash = ?",
                [novo, pid, antigo]).fetchone()[0]
            n_pregoes = con.execute(
                "UPDATE papel_pregoes SET codigo_hash = ? "
                "WHERE plano_id = ? AND codigo_hash = ?",
                [novo, pid, antigo]).fetchone()[0]
            out.append({"plano_id": pid, "hash_antigo": antigo,
                        "hash_novo": novo, "planos": int(n_plano),
                        "pregoes": int(n_pregoes)})
    return out
