"""Proves that a file split only moved code around.

    .venv/Scripts/python.exe scripts/verify_split.py --since <commit>

Compares the .py files changed since the commit with what they were in it,
without importing or running the project:

- each function, class and method, by name: identical syntax tree, none
  lost, none repeated (the body of `register` counts as a container: the
  functions inside it and its other lines are compared one by one);
- each module constant: the same and in a single place;
- every name an old file offered is still offered by it (defined or
  imported), so nothing that imports it breaks;
- no undefined name in the new or changed files;
- warning for `__file__` and `__name__` in code that moved files: both
  change meaning when the file changes.

Exits with 1 if there is a problem; warnings do not fail, but are shown.
"""
import argparse
import ast
import builtins
import re
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


def _delegacao(recipiente: ast.FunctionDef, no: ast.stmt) -> str | None:
    """`part.register(app)` inside `register(app)`: the container hands over to a part. Returns the part's name."""
    if not (isinstance(no, ast.Expr) and isinstance(no.value, ast.Call)):
        return None
    f, c = no.value.func, no.value
    params = [a.arg for a in recipiente.args.args]
    if isinstance(f, ast.Attribute) and f.attr == recipiente.name and isinstance(f.value, ast.Name) \
            and not c.keywords and [getattr(a, "id", None) for a in c.args] == params:
        return f.value.id
    return None


def delegacoes(fontes: dict[str, str]) -> tuple[set[str], set[str]]:
    """(modules called by delegation, modules that have a container)."""
    orig = origens(fontes)
    chamados, com_recipiente = set(), set()
    for caminho, fonte in fontes.items():
        for no in ast.parse(fonte).body:
            if isinstance(no, ast.ImportFrom) and any(a.name in RECIPIENTES and (a.asname or a.name) == a.name
                                                      for a in no.names):
                chamados.add(_absoluto(caminho, no))  # the shell re-exports the whole register
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in RECIPIENTES:
                com_recipiente.add(_modulo_de(caminho))
                locais = {}  # `from ui import x` inside the register itself
                for filho in no.body:
                    if isinstance(filho, ast.ImportFrom):
                        for a in filho.names:
                            locais[a.asname or a.name] = f"{_absoluto(caminho, filho)}.{a.name}"
                    elif isinstance(filho, ast.Import):
                        for a in filho.names:
                            locais[a.asname or a.name] = a.name
                for filho in no.body:
                    alias = _delegacao(no, filho)
                    if alias:
                        chamados.add(locais.get(alias) or orig[caminho].get(alias, "?").removeprefix("import:"))
    return chamados, com_recipiente


def pecas(fonte: str, caminho: str | None = None) -> dict[str, list[str]]:
    """Name → syntax trees of each definition with that name (one per occurrence).

    A relative import inside a function becomes absolute before comparing: `from . import x`
    copied into a deeper folder has the same text and points elsewhere.
    """
    saida: dict[str, list[str]] = {}
    arvore = ast.parse(fonte)
    if caminho:
        for topo in arvore.body:
            if isinstance(topo, (ast.Import, ast.ImportFrom)):
                continue
            for n in ast.walk(topo):
                if isinstance(n, ast.ImportFrom) and n.level:
                    n.module, n.level = _absoluto(caminho, n), 0

    def por(chave, no):
        saida.setdefault(chave, []).append(ast.dump(no, include_attributes=False))

    for no in _sem_docstring_de_modulo(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in RECIPIENTES:
            for i, filho in enumerate(no.body):
                if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    por(f"{no.name}/{filho.name}", filho)
                elif _delegacao(no, filho):
                    continue
                elif not (i == 0 and isinstance(filho, ast.Expr) and isinstance(filho.value, ast.Constant)):
                    por(f"{no.name}/<line>", filho)
        elif isinstance(no, ast.ClassDef):
            corpo = [n for n in no.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            casca = ast.ClassDef(name=no.name, bases=no.bases, keywords=no.keywords, body=corpo,
                                 decorator_list=no.decorator_list, type_params=getattr(no, "type_params", []))
            por(f"class {no.name}", casca)
            for m in no.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    por(f"{no.name}.{m.name}", m)
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            por(no.name, no)
        elif _alvos(no):
            for alvo in _alvos(no):
                por(f"constant {alvo}", no)
        elif isinstance(no, (ast.Import, ast.ImportFrom)):
            continue
        else:
            por("<module line>", no)
    return saida


def oferecidos(fonte: str) -> set[str]:
    """Names that `import module; module.X` finds: defined or imported at the top level."""
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


def apelidos(fonte: str, caminho_fonte: str, modulo: str) -> set[str]:
    """Names by which `fonte` calls the module `modulo` (e.g. `from ui import callbacks_operacao as CO` → CO)."""
    saida = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            for a in no.names:
                if a.name == modulo:
                    saida.add(a.asname or a.name)
        elif isinstance(no, ast.ImportFrom):
            base = _absoluto(caminho_fonte, no)
            for a in no.names:
                if f"{base}.{a.name}" == modulo:
                    saida.add(a.asname or a.name)
    return saida


def _usos_por_apelido(caminho: str):
    """(file, line, alias) of each place in the project that imports the module of `caminho`."""
    modulo = _modulo_de(caminho)
    rastreados = subprocess.run(["git", "ls-files", "*.py"], cwd=RAIZ, capture_output=True, text=True,
                                encoding="utf-8").stdout.split()
    for outro in rastreados:
        if outro == caminho or not (RAIZ / outro).exists():
            continue
        texto = (RAIZ / outro).read_text(encoding="utf-8")
        if modulo.split(".")[-1] not in texto:
            continue
        try:
            nomes = apelidos(texto, outro, modulo)
        except SyntaxError:
            continue
        if nomes:
            yield outro, texto, nomes


def _import_usado_por_fora(caminho: str, nome: str) -> list[str]:
    """Who reads `alias.name` (e.g. a test that does `CO.AV`)."""
    usos = []
    for outro, texto, nomes in _usos_por_apelido(caminho):
        for n, linha in enumerate(texto.splitlines(), 1):
            if any(re.search(rf"\b{re.escape(a)}\.{re.escape(nome)}\b", linha) for a in nomes):
                usos.append(f"{outro}:{n}")
    return usos


def indefinidos(fonte: str, nome: str = "<file>") -> set[str]:
    """Names read that exist neither in the module nor among Python's builtins."""
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


def _modulo_de(caminho: str) -> str:
    partes = list(Path(caminho).with_suffix("").parts)
    return ".".join(partes[:-1] if partes[-1] == "__init__" else partes)


def _absoluto(caminho: str, no: ast.ImportFrom) -> str:
    if not no.level:
        return no.module or ""
    base = _modulo_de(caminho).split(".")
    if not caminho.endswith("__init__.py"):
        base = base[:-1]
    base = base[:len(base) - (no.level - 1)] if no.level > 1 else base
    return ".".join(base + ([no.module] if no.module else []))


def origens(fontes: dict[str, str]) -> dict[str, dict[str, str]]:
    """Per file: top-level name → where it comes from, in a format comparable before and after.

    A definition on its own side becomes "def:<name>", even if it arrives through an import from a
    neighbouring file; the rest becomes "import:<absolute module>.<name>".
    """
    definidos = {}
    for caminho, fonte in fontes.items():
        mod = _modulo_de(caminho)
        for no in ast.parse(fonte).body:
            nomes = [no.name] if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else _alvos(no)
            for n in nomes:
                definidos[(mod, n)] = f"def:{n}"
    saida = {}
    for caminho, fonte in fontes.items():
        mod, mapa = _modulo_de(caminho), {}
        for no in ast.parse(fonte).body:
            if isinstance(no, ast.Import):
                for a in no.names:
                    mapa[(a.asname or a.name).split(".")[0]] = f"import:{a.name if a.asname else a.name.split('.')[0]}"
            elif isinstance(no, ast.ImportFrom):
                origem = _absoluto(caminho, no)
                for a in no.names:
                    mapa[a.asname or a.name] = definidos.get((origem, a.name), f"import:{origem}.{a.name}")
        for (m, n), o in definidos.items():
            if m == mod:
                mapa[n] = o
        saida[caminho] = mapa
    return saida


def _resolucoes(fontes: dict[str, str]) -> dict[str, set[tuple[str, str]]]:
    """Per definition: the (name, origin) of the top-level names it uses."""
    orig = origens(fontes)
    saida: dict[str, set[tuple[str, str]]] = {}
    for caminho, fonte in fontes.items():
        mapa = orig[caminho]
        for no in _sem_docstring_de_modulo(ast.parse(fonte)):
            itens = []
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in RECIPIENTES:
                itens = [(f"{no.name}/{f.name}", f) for f in no.body
                         if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            elif isinstance(no, ast.ClassDef):
                itens = [(f"class {no.name}", no)] + [(f"{no.name}.{m.name}", m) for m in no.body
                                                         if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                itens = [(no.name, no)]
            elif _alvos(no):
                itens = [(f"constant {a}", no) for a in _alvos(no)]
            for chave, alvo in itens:
                usados = {n.id for n in ast.walk(alvo) if isinstance(n, ast.Name)}
                saida.setdefault(chave, set()).update((n, mapa[n]) for n in usados if n in mapa)
    return saida


def comparar(antes: dict[str, str], depois: dict[str, str]) -> tuple[list[str], list[str]]:
    """antes/depois: path → source of the files involved. Returns (problems, warnings)."""
    problemas, alertas = [], []
    ra, rd = _resolucoes(antes), _resolucoes(depois)
    for chave in sorted(set(ra) & set(rd)):
        diferentes = {n for n, _ in ra[chave] ^ rd[chave]}
        if diferentes:
            problemas.append(f"{chave}: name now comes from elsewhere: {', '.join(sorted(diferentes))}")
    chamados_a, _ = delegacoes(antes)
    chamados_d, com_recipiente = delegacoes(depois)
    novos = {_modulo_de(c) for c in depois if c not in antes}
    fora = {m for m in chamados_d if not any(_modulo_de(c) == m for c in depois)}  # module not involved in the split
    for mod in sorted(chamados_d - com_recipiente - fora):
        problemas.append(f"delegation to {mod}, which has no register")
    for mod in sorted((com_recipiente & novos) - chamados_d):
        problemas.append(f"{mod} has a register, but nobody calls it: its callbacks would not be wired")
    if chamados_a - chamados_d:
        problemas.append(f"delegation vanished: {', '.join(sorted(chamados_a - chamados_d))}")
    oa, od = origens(antes), origens(depois)
    for caminho in set(antes) & set(depois):
        for nome, origem in oa[caminho].items():
            if nome in od[caminho] and od[caminho][nome] != origem:
                problemas.append(f"{caminho}: {nome} now points to {od[caminho][nome]}, was {origem}")
    a, d = {}, {}
    onde_a, onde_d = {}, {}
    for lado, fontes, onde in ((a, antes, onde_a), (d, depois, onde_d)):
        for caminho, fonte in fontes.items():
            for chave, arvores in pecas(fonte, caminho).items():
                lado.setdefault(chave, []).extend(arvores)
                onde.setdefault(chave, []).extend([caminho] * len(arvores))
    for chave in sorted(set(a) | set(d)):
        va, vd = Counter(a.get(chave, [])), Counter(d.get(chave, []))
        if chave.endswith("<line>") or chave == "<module line>":
            if va != vd:
                problemas.append(f"{chave}: loose lines changed ({sum(va.values())} → {sum(vd.values())})")
            continue
        if chave not in d:
            problemas.append(f"{chave}: vanished (was in {onde_a[chave][0]})")
        elif chave not in a:
            problemas.append(f"{chave}: is new (in {onde_d[chave][0]}); a split does not create code")
        elif len(d[chave]) > len(a[chave]):
            problemas.append(f"{chave}: repeated in {', '.join(onde_d[chave])}")
        elif va != vd:
            problemas.append(f"{chave}: the code changed")
        elif set(onde_a[chave]) != set(onde_d[chave]):
            for caminho in set(onde_d[chave]):
                trecho = depois[caminho]
                if "__file__" in trecho or "__name__" in trecho:
                    alertas.append(f"{chave}: moved to {caminho}, which uses __file__/__name__; check the meaning")
                    break
    for caminho, fonte in antes.items():
        if caminho in depois:
            faltam = oferecidos(fonte) - oferecidos(depois[caminho])
            importados = faltam & _importados(fonte)
            if faltam - importados:
                problemas.append(f"{caminho}: stopped offering {', '.join(sorted(faltam - importados))}")
            for nome in sorted(importados):
                alertas.append(f"{caminho}: stopped offering the import {nome}")
        else:
            problemas.append(f"{caminho}: file deleted; leave it re-exporting the names")
    for caminho, fonte in depois.items():
        try:
            faltam = indefinidos(fonte, caminho)
        except SyntaxError as e:
            problemas.append(f"{caminho}: does not compile ({e})")
            continue
        if faltam:
            problemas.append(f"{caminho}: undefined names {', '.join(sorted(faltam))}")
    return problemas, alertas


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True, encoding="utf-8").stdout


def _trocas_em_testes(antes: dict[str, str], depois: dict[str, str]) -> list[str]:
    """A test that swaps (monkeypatches) a name that moved files may silently stop working."""
    alertas = []
    for caminho in antes:
        modulo = _modulo_de(caminho)
        for teste in sorted((RAIZ / "tests").glob("test_*.py")):
            for n, linha in enumerate(teste.read_text(encoding="utf-8").splitlines(), 1):
                if f'"{modulo}"' in linha or f"'{modulo}'" in linha:
                    alertas.append(f"tests/{teste.name}:{n} cites the module {modulo} as text (does it read the source?)")
    for caminho, fonte in antes.items():
        ficou = {c.split(" ")[-1] for c in pecas(depois.get(caminho, ""))}
        # the name no longer lives in the shell: swapping it there does not reach its users
        movidos = (oferecidos(fonte) - ficou) - {"<line>", "<module line>"}
        for outro, texto, nomes in _usos_por_apelido(caminho):
            for n, linha in enumerate(texto.splitlines(), 1):
                for a in nomes:
                    if re.search(rf"\b{re.escape(a)}\.__file__\b", linha):
                        alertas.append(f"{outro}:{n} reads the text of {a}.__file__, which is now only the shell")
                    m = re.search(rf"setattr\(\s*{re.escape(a)}\s*,\s*['\"](\w+)['\"]", linha)
                    if m and m.group(1) in movidos:
                        alertas.append(f"{outro}:{n} swaps {a}.{m.group(1)}, which no longer lives in the shell")
    return alertas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, dest="since", help="commit from before the split")
    args = ap.parse_args()
    mudados = _git("diff", "--name-only", args.since).split() + _git("ls-files", "--others", "--exclude-standard").split()
    mudados = sorted({m for m in mudados if m.endswith(".py") and not m.startswith("tests/")})
    antes, depois = {}, {}
    for m in mudados:
        try:
            antes[m] = _git("show", f"{args.since}:{m}")
        except subprocess.CalledProcessError:
            pass
        if (RAIZ / m).exists():
            depois[m] = (RAIZ / m).read_text(encoding="utf-8")
    problemas, alertas = comparar(antes, depois)
    alertas += _trocas_em_testes(antes, depois)
    for alerta in [a for a in alertas if ": stopped offering the import " in a]:
        caminho, nome = alerta.split(": stopped offering the import ")
        usos = _import_usado_por_fora(caminho, nome)
        if usos:
            alertas.remove(alerta)
            problemas.append(f"{caminho}: stopped offering {nome}, used from outside in {usos[0]}")
    print(f"Files: {', '.join(mudados) or 'none'}")
    for x in alertas:
        print(f"WARNING: {x}")
    for x in problemas:
        print(f"PROBLEM: {x}")
    print("Only moved around." if not problemas else f"{len(problemas)} problem(s).")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
