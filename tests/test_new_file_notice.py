"""The new-file notice hook (.claude/hooks/new_file_notice.py): it reminds, and never blocks."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "new_file_notice.py"
SETTINGS = ROOT / ".claude" / "settings.json"


def load_hook():
    spec = importlib.util.spec_from_file_location(HOOK.stem, HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load_hook()


def write_call(path: str, kind: str = "create") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(ROOT / path)}, "tool_response": {"type": kind}}


@pytest.mark.parametrize("path", [
    "scripts/one_off_proof.py", "tests/dados/snapshot.json", "tests/dados/lse/part.parquet", "tests/_diag.py",
])
def test_notice_for_new_watched_files(path):
    message = hook.notice_for(write_call(path))
    assert message and path in message and "Valid until" in message


@pytest.mark.parametrize("path", [
    "core/new_module.py", "tests/test_new.py", "tests/__init__.py", "docs/notes.md", "ui/app.py",
])
def test_no_notice_for_other_files(path):
    assert hook.notice_for(write_call(path)) is None


def test_no_notice_when_overwriting_an_existing_file():
    assert hook.notice_for(write_call("scripts/check_changes.py", kind="update")) is None


def test_no_notice_for_other_tools_or_outside_the_project():
    edit = {**write_call("scripts/x.py"), "tool_name": "Edit"}
    assert hook.notice_for(edit) is None
    outside = {"tool_name": "Write", "tool_input": {"file_path": "C:/elsewhere/scripts/x.py"},
               "tool_response": {"type": "create"}}
    assert hook.notice_for(outside) is None


@pytest.mark.parametrize("data", [{}, {"tool_name": "Write"}, {"tool_name": "Write", "tool_response": "text"},
                                  {"tool_name": "Write", "tool_input": None, "tool_response": {"type": "create"}}])
def test_malformed_payload_gives_no_notice(data):
    assert hook.notice_for(data) is None


def run_hook(stdin: bytes) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, check=False)


def test_hook_prints_context_and_exits_zero():
    result = run_hook(json.dumps(write_call("scripts/x.py")).encode())
    assert result.returncode == 0
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse" and "scripts/x.py" in output["additionalContext"]


def test_hook_never_blocks_on_garbage_input():
    result = run_hook(b"not json")
    assert result.returncode == 0 and result.stdout == b"" and b"ignored error" in result.stderr


def test_hook_is_wired_as_post_tool_use_on_write():
    entries = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))["hooks"]["PostToolUse"]
    wired = [e for e in entries if e["matcher"] == "Write"
             and any("new_file_notice.py" in h["command"] for h in e["hooks"])]
    assert wired
