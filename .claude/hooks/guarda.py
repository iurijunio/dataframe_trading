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
    if ferramenta in SHELL:
        for trecho in re.split(r"[;&|\n]+", entrada.get("command", "")):
            t = trecho.strip()
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
