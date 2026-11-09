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
    """`parte.register(app)` dentro de `register(app)`: o recipiente repassa a uma parte. Devolve o nome da parte."""
    if not (isinstance(no, ast.Expr) and isinstance(no.value, ast.Call)):
        return None
    f, c = no.value.func, no.value
    params = [a.arg for a in recipiente.args.args]
    if isinstance(f, ast.Attribute) and f.attr == recipiente.name and isinstance(f.value, ast.Name) \
            and not c.keywords and [getattr(a, "id", None) for a in c.args] == params:
        return f.value.id
    return None


def delegacoes(fontes: dict[str, str]) -> tuple[set[str], set[str]]:
    """(módulos chamados por delegação, módulos que têm recipiente)."""
    orig = origens(fontes)
    chamados, com_recipiente = set(), set()
    for caminho, fonte in fontes.items():
        for no in ast.parse(fonte).body:
            if isinstance(no, ast.ImportFrom) and any(a.name in RECIPIENTES and (a.asname or a.name) == a.name
                                                      for a in no.names):
                chamados.add(_absoluto(caminho, no))  # a casca reexporta o register inteiro
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in RECIPIENTES:
                com_recipiente.add(_modulo_de(caminho))
                for filho in no.body:
                    alias = _delegacao(no, filho)
                    if alias:
                        chamados.add(orig[caminho].get(alias, "?").removeprefix("import:"))
    return chamados, com_recipiente


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
                elif _delegacao(no, filho):
                    continue
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


def apelidos(fonte: str, caminho_fonte: str, modulo: str) -> set[str]:
    """Nomes pelos quais `fonte` chama o módulo `modulo` (ex.: `from ui import callbacks_operacao as CO` → CO)."""
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
    """(arquivo, linha, apelido) de cada lugar do projeto que importa o módulo de `caminho`."""
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
    """Quem lê `apelido.nome` (ex.: um teste que faz `CO.AV`)."""
    usos = []
    for outro, texto, nomes in _usos_por_apelido(caminho):
        for n, linha in enumerate(texto.splitlines(), 1):
            if any(re.search(rf"\b{re.escape(a)}\.{re.escape(nome)}\b", linha) for a in nomes):
                usos.append(f"{outro}:{n}")
    return usos


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
    """Por arquivo: nome do topo → de onde ele vem, num formato comparável entre antes e depois.

    Definição do próprio lado vira "def:<nome>", mesmo que chegue por import de um
    arquivo vizinho; o resto vira "import:<módulo absoluto>.<nome>".
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
    """Por definição: os (nome, origem) dos nomes do topo que ela usa."""
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
                itens = [(f"classe {no.name}", no)] + [(f"{no.name}.{m.name}", m) for m in no.body
                                                         if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                itens = [(no.name, no)]
            elif _alvos(no):
                itens = [(f"constante {a}", no) for a in _alvos(no)]
            for chave, alvo in itens:
                usados = {n.id for n in ast.walk(alvo) if isinstance(n, ast.Name)}
                saida.setdefault(chave, set()).update((n, mapa[n]) for n in usados if n in mapa)
    return saida


def comparar(antes: dict[str, str], depois: dict[str, str]) -> tuple[list[str], list[str]]:
    """antes/depois: caminho → fonte dos arquivos envolvidos. Devolve (problemas, alertas)."""
    problemas, alertas = [], []
    ra, rd = _resolucoes(antes), _resolucoes(depois)
    for chave in sorted(set(ra) & set(rd)):
        diferentes = {n for n, _ in ra[chave] ^ rd[chave]}
        if diferentes:
            problemas.append(f"{chave}: nome agora vem de outro lugar: {', '.join(sorted(diferentes))}")
    chamados_a, _ = delegacoes(antes)
    chamados_d, com_recipiente = delegacoes(depois)
    novos = {_modulo_de(c) for c in depois if c not in antes}
    for mod in sorted(chamados_d - com_recipiente):
        problemas.append(f"delegação para {mod}, que não tem register")
    for mod in sorted((com_recipiente & novos) - chamados_d):
        problemas.append(f"{mod} tem register, mas ninguém o chama: os callbacks dele não seriam ligados")
    if chamados_a - chamados_d:
        problemas.append(f"delegação sumiu: {', '.join(sorted(chamados_a - chamados_d))}")
    oa, od = origens(antes), origens(depois)
    for caminho in set(antes) & set(depois):
        for nome, origem in oa[caminho].items():
            if nome in od[caminho] and od[caminho][nome] != origem:
                problemas.append(f"{caminho}: {nome} agora aponta para {od[caminho][nome]}, era {origem}")
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
    alertas = []
    for caminho, fonte in antes.items():
        ficou = {c.split(" ")[-1] for c in pecas(depois.get(caminho, ""))}
        # o nome não mora mais na casca: trocá-lo nela não chega a quem usa
        movidos = (oferecidos(fonte) - ficou) - {"<linha>", "<linha de módulo>"}
        for outro, texto, nomes in _usos_por_apelido(caminho):
            for n, linha in enumerate(texto.splitlines(), 1):
                for a in nomes:
                    if re.search(rf"\b{re.escape(a)}\.__file__\b", linha):
                        alertas.append(f"{outro}:{n} lê o texto de {a}.__file__, que agora é só a casca")
                    m = re.search(rf"setattr\(\s*{re.escape(a)}\s*,\s*['\"](\w+)['\"]", linha)
                    if m and m.group(1) in movidos:
                        alertas.append(f"{outro}:{n} troca {a}.{m.group(1)}, que não mora mais na casca")
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
