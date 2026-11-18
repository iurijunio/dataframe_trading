"""Reminds the agent, after it creates a file that tends to outlive its purpose, to give it an expiry.

One-off proof scripts, fixtures and scratch helpers were left behind by past refactors because
nothing asked for their removal. This hook runs after a Write; when the written file is NEW and
lives in `scripts/`, `tests/dados/` or is a `tests/_*.py` helper, it tells the agent to declare when
the file expires and which rule references it, or to delete it at delivery.

It never blocks: it always exits 0, and any error is only logged to stderr.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WATCHED = re.compile(r"^(scripts/[^/]+|tests/dados/.+|tests/_[^/]+\.py)$")
NOTICE = ("New file `{path}`: declare when it expires and which rule references it "
          "(a 'Valid until: ...' line in .claude/rules/), or delete it at delivery. "
          "tests/test_repo_hygiene.py fails on files nothing references.")


def relative_path(file_path: str, root: Path = ROOT) -> str | None:
    """The project-relative posix path of `file_path`, or None when it is outside the project."""
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:  # swallow: a path outside the project is simply not watched
        return None


def is_new_write(tool_name: str, tool_response: object) -> bool:
    """True when a Write created the file (an overwrite of an existing file is `update`)."""
    return tool_name == "Write" and isinstance(tool_response, dict) and tool_response.get("type") == "create"


def notice_for(data: dict, root: Path = ROOT) -> str | None:
    """The reminder for this tool call, or None when nothing needs saying."""
    if not is_new_write(data.get("tool_name", ""), data.get("tool_response")):
        return None
    path = relative_path((data.get("tool_input") or {}).get("file_path", ""), root)
    if path and WATCHED.match(path) and not path.endswith("__init__.py"):
        return NOTICE.format(path=path)
    return None


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        message = notice_for(data)
    except Exception as error:  # swallow: a reminder must never block the work; the reason is logged
        print(f"new_file_notice: ignored error: {error!r}", file=sys.stderr)
        return
    if message:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))


if __name__ == "__main__":
    main()
