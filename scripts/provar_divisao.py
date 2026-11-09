"""Prova que uma divisão de arquivo só mudou código de lugar.

    .venv/Scripts/python.exe scripts/provar_divisao.py --de <commit>

Compara os .py mudados desde o commit com o que eram nele, sem importar nem
rodar o projeto:

- cada função, classe e método, pelo nome: árvore de sintaxe idêntica, nenhum
  perdido, nenhum repetido (o corpo de `register` conta como recipiente: as
  funções de dentro e as demais linhas dele são comparadas uma a uma);
- cada constante de módulo: mesma e num só lugar;
- todo nome que um arquivo antigo oferecia continua oferecido por ele
  (definido ou importado), para nada que o importa quebrar;
- nenhum nome indefinido nos arquivos novos ou mudados;
- alerta para `__file__` e `__name__` em código que mudou de arquivo: os dois
  mudam de sentido ao trocar de arquivo.

Sai com 1 se houver problema; alertas não reprovam, mas aparecem.
"""
import argparse
import ast
import builtins
import subprocess
import sys
import symtable
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RECIPIENTES = {"register"}
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__loader__", "__package__",
                                 "__builtins__", "__path__", "__dict__"}


def _sem_docstring_de_modulo(t: ast.Module) -> list[ast.stmt]:
    corpo = list(t.body)
    if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant) \
            and isinstance(corpo[0].value.value, str):
        corpo = corpo[1:]
    return corpo


def _alvos(no: ast.stmt) -> list[str]:
    if isinstance(no, ast.Assign):
        return [n.id for t in no.targets for n in ast.walk(t) if isinstance(n, ast.Name)]
    if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
        return [no.target.id]
    return []


def pecas(fonte: str) -> dict[str, list[str]]:
    """Nome → árvores de sintaxe de cada definição com esse nome (uma por ocorrência)."""
    saida: dict[str, list[str]] = {}

    def por(chave, no):
        saida.setdefault(chave, []).append(ast.dump(no, include_attributes=False))

    for no in _sem_docstring_de_modulo(ast.parse(fonte)):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in RECIPIENTES:
            for i, filho in enumerate(no.body):
                if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    por(f"{no.name}/{filho.name}", filho)
                elif not (i == 0 and isinstance(filho, ast.Expr) and isinstance(filho.value, ast.Constant)):
                    por(f"{no.name}/<linha>", filho)
        elif isinstance(no, ast.ClassDef):
            corpo = [n for n in no.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            casca = ast.ClassDef(name=no.name, bases=no.bases, keywords=no.keywords, body=corpo,
                                 decorator_list=no.decorator_list, type_params=getattr(no, "type_params", []))
            por(f"classe {no.name}", casca)
            for m in no.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    por(f"{no.name}.{m.name}", m)
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            por(no.name, no)
        elif _alvos(no):
            for alvo in _alvos(no):
                por(f"constante {alvo}", no)
        elif isinstance(no, (ast.Import, ast.ImportFrom)):
            continue
        else:
            por("<linha de módulo>", no)
    return saida


def oferecidos(fonte: str) -> set[str]:
    """Nomes que `import modulo; modulo.X` encontra: definidos ou importados no topo."""
    return _oferecidos_em(ast.parse(fonte).body)


def _oferecidos_em(corpo: list[ast.stmt]) -> set[str]:
    nomes = set()
    for no in corpo:
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nomes.add(no.name)
        elif isinstance(no, (ast.Import, ast.ImportFrom)):
            nomes |= {(a.asname or a.name).split(".")[0] for a in no.names}
        elif isinstance(no, ast.If):
            nomes |= _oferecidos_em(no.body) | _oferecidos_em(no.orelse)
        elif isinstance(no, ast.Try):
            nomes |= _oferecidos_em(no.body)
            for h in no.handlers:
                nomes |= _oferecidos_em(h.body)
        nomes |= set(_alvos(no))
    return nomes


def _importados(fonte: str) -> set[str]:
    return {(a.asname or a.name).split(".")[0] for no in ast.parse(fonte).body
            if isinstance(no, (ast.Import, ast.ImportFrom)) for a in no.names}


def _import_usado_por_fora(caminho: str, nome: str) -> list[str]:
    """Quem lê `modulo.nome` (ex.: um teste que troca `captura.time`)."""
    modulo = Path(caminho).stem
    saida = subprocess.run(["git", "grep", "-nE", rf"\b{modulo}\.{nome}\b", "--", "*.py"], cwd=RAIZ,
                           capture_output=True, text=True, encoding="utf-8").stdout
    return [s for s in saida.splitlines() if not s.startswith(caminho + ":")]


def indefinidos(fonte: str, nome: str = "<arquivo>") -> set[str]:
    """Nomes lidos que não existem no módulo nem entre os nativos do Python."""
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(ast.parse(fonte))):
        return set()
    mod = symtable.symtable(fonte, nome, "exec")
    do_modulo = {s.get_name() for s in mod.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    faltam = set()

    def olhar(tab, topo):
        for s in tab.get_symbols():
            if not s.is_referenced():
                continue
            n = s.get_name()
            if topo:
                livre = not (s.is_assigned() or s.is_imported() or s.is_namespace())
            elif tab.get_type() == "class":
                livre = not (s.is_assigned() or s.is_imported() or s.is_namespace())
            else:
                livre = s.is_global() and not s.is_declared_global()
            if livre and n not in do_modulo and n not in BUILTINS:
                faltam.add(n)
        for filho in tab.get_children():
            olhar(filho, False)

    olhar(mod, True)
    return faltam


def comparar(antes: dict[str, str], depois: dict[str, str]) -> tuple[list[str], list[str]]:
    """antes/depois: caminho → fonte dos arquivos envolvidos. Devolve (problemas, alertas)."""
    problemas, alertas = [], []
    a, d = {}, {}
    onde_a, onde_d = {}, {}
    for lado, fontes, onde in ((a, antes, onde_a), (d, depois, onde_d)):
        for caminho, fonte in fontes.items():
            for chave, arvores in pecas(fonte).items():
                lado.setdefault(chave, []).extend(arvores)
                onde.setdefault(chave, []).extend([caminho] * len(arvores))
    for chave in sorted(set(a) | set(d)):
        va, vd = Counter(a.get(chave, [])), Counter(d.get(chave, []))
        if chave.endswith("<linha>") or chave == "<linha de módulo>":
            if va != vd:
                problemas.append(f"{chave}: linhas soltas mudaram ({sum(va.values())} → {sum(vd.values())})")
            continue
        if chave not in d:
            problemas.append(f"{chave}: sumiu (estava em {onde_a[chave][0]})")
        elif chave not in a:
            problemas.append(f"{chave}: é novo (em {onde_d[chave][0]}); divisão não cria código")
        elif len(d[chave]) > len(a[chave]):
            problemas.append(f"{chave}: repetido em {', '.join(onde_d[chave])}")
        elif va != vd:
            problemas.append(f"{chave}: o código mudou")
        elif set(onde_a[chave]) != set(onde_d[chave]):
            for caminho in set(onde_d[chave]):
                trecho = depois[caminho]
                if "__file__" in trecho or "__name__" in trecho:
                    alertas.append(f"{chave}: mudou para {caminho}, que usa __file__/__name__; confira o sentido")
                    break
    for caminho, fonte in antes.items():
        if caminho in depois:
            faltam = oferecidos(fonte) - oferecidos(depois[caminho])
            importados = faltam & _importados(fonte)
            if faltam - importados:
                problemas.append(f"{caminho}: deixou de oferecer {', '.join(sorted(faltam - importados))}")
            for nome in sorted(importados):
                alertas.append(f"{caminho}: deixou de oferecer o import {nome}")
        else:
            problemas.append(f"{caminho}: arquivo apagado; deixe-o reexportando os nomes")
    for caminho, fonte in depois.items():
        try:
            faltam = indefinidos(fonte, caminho)
        except SyntaxError as e:
            problemas.append(f"{caminho}: não compila ({e})")
            continue
        if faltam:
            problemas.append(f"{caminho}: nomes indefinidos {', '.join(sorted(faltam))}")
    return problemas, alertas


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True, encoding="utf-8").stdout


def _trocas_em_testes(antes: dict[str, str], depois: dict[str, str]) -> list[str]:
    """Teste que troca (monkeypatch) um nome que mudou de arquivo pode deixar de valer em silêncio."""
    movidos = set()
    for caminho, fonte in antes.items():
        ficou = set(pecas(depois.get(caminho, "")))
        movidos |= {c.split(".")[-1].split("/")[-1] for c in pecas(fonte) if c not in ficou}
    movidos -= {"<linha>", "<linha de módulo>"}
    alertas = []
    for teste in sorted((RAIZ / "tests").glob("test_*.py")):
        for n, linha in enumerate(teste.read_text(encoding="utf-8").splitlines(), 1):
            if "setattr(" in linha and any(f'"{m}"' in linha or f"'{m}'" in linha or f".{m}," in linha
                                           for m in movidos):
                alertas.append(f"tests/{teste.name}:{n} troca nome que mudou de arquivo: {linha.strip()[:90]}")
    return alertas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", required=True, help="commit de antes da divisão")
    args = ap.parse_args()
    mudados = _git("diff", "--name-only", args.de).split() + _git("ls-files", "--others", "--exclude-standard").split()
    mudados = sorted({m for m in mudados if m.endswith(".py") and not m.startswith("tests/")})
    antes, depois = {}, {}
    for m in mudados:
        try:
            antes[m] = _git("show", f"{args.de}:{m}")
        except subprocess.CalledProcessError:
            pass
        if (RAIZ / m).exists():
            depois[m] = (RAIZ / m).read_text(encoding="utf-8")
    problemas, alertas = comparar(antes, depois)
    alertas += _trocas_em_testes(antes, depois)
    for alerta in [a for a in alertas if ": deixou de oferecer o import " in a]:
        caminho, nome = alerta.split(": deixou de oferecer o import ")
        usos = _import_usado_por_fora(caminho, nome)
        if usos:
            alertas.remove(alerta)
            problemas.append(f"{caminho}: deixou de oferecer {nome}, usado por fora em {usos[0]}")
    print(f"Arquivos: {', '.join(mudados) or 'nenhum'}")
    for x in alertas:
        print(f"ALERTA: {x}")
    for x in problemas:
        print(f"PROBLEMA: {x}")
    print("Só mudou de lugar." if not problemas else f"{len(problemas)} problema(s).")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
