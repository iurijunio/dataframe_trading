"""Trava, antes de cada ferramenta, o que já custou caro no projeto.

Regra que dá para checar por programa não depende de o agente lembrar. Qualquer
erro aqui libera a ferramenta: o guarda nunca pode travar o trabalho.
"""
import json
import re
import socket
import sys
import time
from pathlib import Path

LIMITE_LINHAS = 600
PORTA_APP = 8050
TEXTO = {".py", ".md", ".css", ".js", ".json", ".jsonl", ".txt", ".sql", ".yaml", ".yml", ".html", ".csv", ".log"}
SHELL = {"Bash", "PowerShell"}
MAX_BYTES_CONTAR = 2_000_000
ESTADO = Path(__file__).resolve().parents[2] / "data" / "ao_vivo" / "estado.json"
COPIA = ("O app real ou a captura está aberto: uma cópia disputaria o banco real. Feche-os antes. "
         "Se a porta for de uma cópia sua, pare-a com preview_stop.")
RAIZ = Path(__file__).resolve().parents[2]
EDITORES = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Há estratégias na conta real: subir o serviço que opera, ou falar com o MT5 por
# fora dos testes, pode mandar ordem de verdade. Quem opera é o usuário. É um cinto
# contra o engano comum, não uma cerca contra quem quer passar.
OPERA = ("Isso pode operar a conta real (subir a captura/ordens ou falar com o MT5 por fora dos testes). "
         "Quem envia ordem, zera posição e abre o serviço é o usuário. Peça a ele.")
SERVICO = re.compile(r"(?<![\w-])((ordens_real|captura)(\.py|\.bat|\.cmd)?|iniciar(\.bat|\.cmd)?)(?![\w-])", re.I)
LANCADOR = re.compile(r"(&\s*)?[\"']?(\S*[/\\])?(python\w*(\.exe)?|py(\.exe)?|cmd(\.exe)?|start(-process)?|call|"
                      r"invoke-item|ii)(?![\w-])", re.I)
SO_TESTA = re.compile(r"\b(pytest|py_compile|conferir\.py)\b", re.I)
PYTHON_AVULSO = re.compile(r"python\w*(\.exe)?[\"']?\s+(-\S+\s+)*(-c\b|-(\s|$)|<<)"
                           r"|\|\s*[\"']?(\S*[/\\])?python\w*(\.exe)?[\"']?\s*($|[;&|\n])", re.I)
FALA_COM_MT5 = re.compile(r"\b(order_send|MetaTrader5|ordem_teste|ordens_real|corretora)\b|core[./\\]ordens\b"
                          r"|from\s+core\s+import\s+[^\n]*\bordens\b")

# É do diário (não do banco) que a captura relê "já enviei a entrada X" e "conta
# travada hoje": perder uma linha pode reenviar uma ordem ou destravar a conta.
DIARIO = ("O diário de ordens (data/ao_vivo/ordens) não se apaga, não se move e não se edita: é dele que a "
          "captura relê o que já foi enviado e a conta travada. Só leitura (cat, Get-Content, Read).")
PASTA_DIARIO = re.compile(r"ao_vivo([/\\]ordens\b|[/\\]?\*|[/\\]?([\s\"']|$))", re.I)
DESTROI = re.compile(r"(cmd(\.exe)?\s+/[ck]\s+)?(rm|del|erase|rd|rmdir|mv|move|ren|rename|ri|mi|remove-item|"
                     r"move-item|rename-item|clear-content|set-content|add-content|out-file|truncate|cp|copy|"
                     r"copy-item|cpi|new-item|ni|tee|tee-object|sed\s+-i)(?![\w-])", re.I)
REDIRECIONA = re.compile(r">\s*[\"']?\S*ao_vivo[/\\]ordens", re.I)
PY_DESTROI = re.compile(r"\bos\.(remove|unlink|rename|replace)\b|\bshutil\.|\.unlink\(|\.write_(text|bytes)\(|"
                        r"rmtree|truncate|open\([^)]*,\s*[\"'][wax]|mode\s*=\s*[\"'][wax]", re.I)
# Com data/ fora do git, `git clean -x` apaga o banco e o diário de uma vez.
GIT_CLEAN = re.compile(r"git\b.*\bclean\b.*\s-\w*[xX]", re.I)
LIMPA = "`git clean -x` apaga o que está fora do git, inclusive o banco e o diário em data/."


def _pode_ter_mt5(caminho: str) -> bool:
    """Só o código do projeto (core/, tests/, os dois serviços e este guarda) fala com o MT5."""
    try:
        partes = Path(caminho).resolve().relative_to(RAIZ).parts
    except (ValueError, OSError):
        return False
    if partes[:2] == (".claude", "worktrees"):
        partes = partes[3:]
    return bool(partes) and (partes[0] in {"core", "tests"} or partes == ("ordens_real.py",)
                             or partes == ("captura.py",) or partes[:2] == (".claude", "hooks"))


def app_aberto() -> bool:
    try:
        if time.time() - ESTADO.stat().st_mtime < 60:
            return True
    except OSError:
        pass
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORTA_APP)) == 0


def _linhas(caminho: str) -> int:
    if Path(caminho).stat().st_size > MAX_BYTES_CONTAR:  # contar linhas de arquivo enorme estouraria o tempo do hook
        return LIMITE_LINHAS + 1
    with open(caminho, "rb") as f:
        return sum(1 for _ in f)


def decidir(ferramenta: str, entrada: dict, aberto=app_aberto, linhas=_linhas) -> str | None:
    """Devolve o motivo da recusa, ou None para liberar."""
    if ferramenta in EDITORES:
        caminho = entrada.get("file_path") or entrada.get("notebook_path") or ""
        if re.search(r"ao_vivo[/\\]ordens[/\\]", caminho, flags=re.I):
            return DIARIO
        partes = [entrada.get(c) for c in ("content", "new_string", "new_source")]
        partes += [e.get("new_string") for e in entrada.get("edits") or [] if isinstance(e, dict)]
        texto = " ".join(str(x) for x in partes if x)
        executavel = Path(caminho).suffix.lower() in {".py", ".pyw", ".ipynb", ".bat", ".cmd", ".ps1", ".sh"}
        if executavel and not _pode_ter_mt5(caminho):
            if FALA_COM_MT5.search(texto):
                return OPERA
            if PASTA_DIARIO.search(texto) and PY_DESTROI.search(texto):
                return DIARIO
        return None
    if ferramenta in SHELL:
        comando = entrada.get("command") or ""
        if PYTHON_AVULSO.search(comando):
            if FALA_COM_MT5.search(comando):
                return OPERA
            if PASTA_DIARIO.search(comando) and PY_DESTROI.search(comando):
                return DIARIO
        trechos = [t.strip() for t in re.split(r"[;&|\n]+", comando)]
        # pipe e cd separam o caminho do verbo (`ls ordens | Remove-Item`, `cd ordens; rm *`)
        if PASTA_DIARIO.search(comando) and (any(DESTROI.match(t) for t in trechos) or REDIRECIONA.search(comando)):
            return DIARIO
        if GIT_CLEAN.search(comando):
            return LIMPA
        for t in trechos:
            if SERVICO.search(t) and not SO_TESTA.search(t) and (
                LANCADOR.match(t) or SERVICO.match(t.lstrip("./\\\"'"))
            ):
                return OPERA
            if re.match(r"git\b.*\badd\b.*\s(-A\b|--all\b|-u\b|--update\b|\.(\s|$))", t) or re.match(
                r"git\b.*\bcommit\b.*\s(-[a-zA-Z]*a[a-zA-Z]*|--all)(\s|$)", t
            ):
                return "Adicione arquivos ao commit pelo caminho, nunca `git add -A`, `git add .` nem `git commit -a`."
            if re.match(r"\S*python(\.exe)?\s+(\S*[/\\])?ui[/\\]app\.py", t) and aberto():
                return COPIA
            if re.match(r"(rm\s+-\S*r|remove-item\b.*-recurse)", t, flags=re.I) and re.search(
                r"(^|[/\\\s\"'])(data|\.venv)[/\\]?([\"'\s]|$)", t
            ):
                return "`data` e `.venv` podem ser junções para os originais: remova com `cmd /c rmdir`."
    elif ferramenta == "mcp__Claude_Browser__preview_start":
        if entrada.get("name") == "dataframe" and aberto():
            return COPIA
    elif ferramenta == "Read":
        if any(entrada.get(c) for c in ("offset", "limit", "allow_large", "pages")):
            return None
        caminho = entrada.get("file_path", "")
        if Path(caminho).suffix.lower() in TEXTO and linhas(caminho) > LIMITE_LINHAS:
            return (f"Arquivo com mais de {LIMITE_LINHAS} linhas: leia por trecho (offset/limit), em volta da "
                    "linha achada na busca. Use allow_large só se precisar mesmo do arquivo inteiro.")
    return None


def main() -> None:
    try:
        dados = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        motivo = decidir(dados.get("tool_name", ""), dados.get("tool_input") or {})
    except Exception:
        return
    if motivo:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": motivo,
        }}))


if __name__ == "__main__":
    main()
