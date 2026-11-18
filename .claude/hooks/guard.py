"""Blocks, before each tool call, what has already cost the project dearly.

A rule that a program can check does not depend on the agent remembering it. Any
error here lets the tool through: the guard must never block the work.
"""
import json
import re
import socket
import sys
import time
from pathlib import Path

LINE_LIMIT = 600
APP_PORT = 8050
TEXT_SUFFIXES = {".py", ".md", ".css", ".js", ".json", ".jsonl", ".txt", ".sql", ".yaml", ".yml", ".html", ".csv", ".log"}
SHELLS = {"Bash", "PowerShell"}
MAX_BYTES_TO_COUNT = 2_000_000
STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "ao_vivo" / "estado.json"
APP_COPY = ("The real app or the capture is open: a copy would compete for the real database. Close them first. "
            "If the port belongs to a copy of yours, stop it with preview_stop.")
ROOT = Path(__file__).resolve().parents[2]
EDITORS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Strategies are on the real account: starting the service that trades, or talking to MT5
# outside the tests, can send a real order. The user is the one who trades. This is a belt
# against the common mistake, not a fence against someone who wants to get through.
OPERATES = ("This can operate the real account (starting capture/orders or talking to MT5 outside the tests). "
            "The user sends orders, flattens positions and opens the service. Ask them.")
SERVICE = re.compile(r"(?<![\w-])((ordens_real|captura)(\.py|\.bat|\.cmd)?|iniciar(\.bat|\.cmd)?)(?![\w-])", re.I)
LAUNCHER = re.compile(r"(&\s*)?[\"']?(\S*[/\\])?(python\w*(\.exe)?|py(\.exe)?|cmd(\.exe)?|start(-process)?|call|"
                      r"invoke-item|ii)(?![\w-])", re.I)
ONLY_TESTS = re.compile(r"\b(pytest|py_compile|check_changes\.py)\b", re.I)
LOOSE_PYTHON = re.compile(r"python\w*(\.exe)?[\"']?\s+(-\S+\s+)*(-c\b|-(\s|$)|<<)"
                          r"|\|\s*[\"']?(\S*[/\\])?python\w*(\.exe)?[\"']?\s*($|[;&|\n])", re.I)

# The capture re-reads "I already sent entry X" and "account locked today" from the journal (not
# from the database): losing a line can resend an order or unlock the account.
JOURNAL = ("The order journal (data/ao_vivo/ordens) is not deleted, moved or edited: the capture re-reads from it "
           "what was already sent and the locked account. Read-only (cat, Get-Content, Read).")
JOURNAL_DIR = re.compile(r"ao_vivo([/\\]ordens\b|[/\\]?\*|[/\\]?([\s\"']|$))", re.I)
DESTROYS = re.compile(r"(cmd(\.exe)?\s+/[ck]\s+)?(rm|del|erase|rd|rmdir|mv|move|ren|rename|ri|mi|remove-item|"
                      r"move-item|rename-item|clear-content|set-content|add-content|out-file|truncate|cp|copy|"
                      r"copy-item|cpi|new-item|ni|tee|tee-object|sed\s+-i)(?![\w-])", re.I)
REDIRECTS = re.compile(r">\s*[\"']?\S*ao_vivo[/\\]ordens", re.I)
PY_DESTROYS = re.compile(r"\bos\.(remove|unlink|rename|replace)\b|\bshutil\.|\.unlink\(|\.write_(text|bytes)\(|"
                         r"rmtree|truncate|open\([^)]*,\s*[\"'][wax]|mode\s*=\s*[\"'][wax]", re.I)
# With data/ outside git, `git clean -x` deletes the database and the journal at once.
GIT_CLEAN = re.compile(r"git\b.*\bclean\b.*\s-\w*[xX]", re.I)
CLEAN = "`git clean -x` deletes what is outside git, including the database and the journal in data/."


def may_talk_to_mt5(path: str) -> bool:
    """Only project code (core/, tests/, the two services and this guard) talks to MT5."""
    try:
        parts = Path(path).resolve().relative_to(ROOT).parts
    except (ValueError, OSError):
        return False
    if parts[:2] == (".claude", "worktrees"):
        parts = parts[3:]
    return bool(parts) and (parts[0] in {"core", "tests"} or parts == ("ordens_real.py",)
                            or parts == ("captura.py",) or parts[:2] == (".claude", "hooks"))


def app_is_open() -> bool:
    try:
        if time.time() - STATE_FILE.stat().st_mtime < 60:
            return True
    except OSError:  # swallow: no readable state file just means the capture is not running
        pass
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", APP_PORT)) == 0


def count_lines(path: str) -> int:
    if Path(path).stat().st_size > MAX_BYTES_TO_COUNT:  # counting lines of a huge file would blow the hook's time budget
        return LINE_LIMIT + 1
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def editor_reason(tool_input: dict) -> str | None:
    """Refusal for Write/Edit calls that touch or would destroy the order journal."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if re.search(r"ao_vivo[/\\]ordens[/\\]", path, flags=re.I):
        return JOURNAL
    pieces = [tool_input.get(c) for c in ("content", "new_string", "new_source")]
    pieces += [e.get("new_string") for e in tool_input.get("edits") or [] if isinstance(e, dict)]
    text = " ".join(str(x) for x in pieces if x)
    executable = Path(path).suffix.lower() in {".py", ".pyw", ".ipynb", ".bat", ".cmd", ".ps1", ".sh"}
    # Looking for MT5 names in the text blocked read-only analysis (2026-11-09, user's
    # request): the lock stayed only on what launches the service and what deletes the journal.
    if executable and not may_talk_to_mt5(path) and JOURNAL_DIR.search(text) and PY_DESTROYS.search(text):
        return JOURNAL
    return None


def segment_reason(t: str, is_open) -> str | None:
    """Refusal for one shell segment (the command split on ; & | and newlines)."""
    if SERVICE.search(t) and not ONLY_TESTS.search(t) and (
        LAUNCHER.match(t) or SERVICE.match(t.lstrip("./\\\"'"))
    ):
        return OPERATES
    if re.match(r"git\b.*\badd\b.*\s(-A\b|--all\b|-u\b|--update\b|\.(\s|$))", t) or re.match(
        r"git\b.*\bcommit\b.*\s(-[a-zA-Z]*a[a-zA-Z]*|--all)(\s|$)", t
    ):
        return "Add files to the commit by path, never `git add -A`, `git add .` or `git commit -a`."
    if re.match(r"\S*python(\.exe)?\s+(\S*[/\\])?ui[/\\]app\.py", t) and is_open():
        return APP_COPY
    if re.match(r"(rm\s+-\S*r|remove-item\b.*-recurse)", t, flags=re.I) and re.search(
        r"(^|[/\\\s\"'])(data|\.venv)[/\\]?([\"'\s]|$)", t
    ):
        return "`data` and `.venv` may be junctions to the originals: remove them with `cmd /c rmdir`."
    return None


def shell_reason(tool_input: dict, is_open) -> str | None:
    """Refusal for Bash/PowerShell commands."""
    command = tool_input.get("command") or ""
    if LOOSE_PYTHON.search(command) and JOURNAL_DIR.search(command) and PY_DESTROYS.search(command):
        return JOURNAL
    segments = [t.strip() for t in re.split(r"[;&|\n]+", command)]
    # pipe and cd separate the path from the verb (`ls ordens | Remove-Item`, `cd ordens; rm *`)
    if JOURNAL_DIR.search(command) and (any(DESTROYS.match(t) for t in segments) or REDIRECTS.search(command)):
        return JOURNAL
    if GIT_CLEAN.search(command):
        return CLEAN
    return next((r for r in (segment_reason(t, is_open) for t in segments) if r), None)


def read_reason(tool_input: dict, line_count) -> str | None:
    """Refusal for whole-file reads of large text files."""
    if any(tool_input.get(c) for c in ("offset", "limit", "allow_large", "pages")):
        return None
    path = tool_input.get("file_path", "")
    if Path(path).suffix.lower() in TEXT_SUFFIXES and line_count(path) > LINE_LIMIT:
        return (f"File with more than {LINE_LIMIT} lines: read it in excerpts (offset/limit), around the "
                "line found by the search. Use allow_large only if you really need the whole file.")
    return None


def decide(tool: str, tool_input: dict, is_open=app_is_open, line_count=count_lines) -> str | None:
    """Return the reason for refusing, or None to let it through."""
    if tool in EDITORS:
        return editor_reason(tool_input)
    if tool in SHELLS:
        return shell_reason(tool_input, is_open)
    if tool == "mcp__Claude_Browser__preview_start":
        return APP_COPY if tool_input.get("name") == "dataframe" and is_open() else None
    if tool == "Read":
        return read_reason(tool_input, line_count)
    return None


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        reason = decide(data.get("tool_name", ""), data.get("tool_input") or {})
    except Exception:  # swallow: any error lets the tool through, by design (see module docstring)
        return
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))


if __name__ == "__main__":
    main()
