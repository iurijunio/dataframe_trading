"""Repo hygiene: nothing is left behind that no rule, test or script uses.

One-off proof scripts, fixtures and scratch helpers used to outlive the change that
needed them. Each check below fails when such a leftover shows up, so deleting it
at delivery is enforced, not remembered (see "At delivery" in AGENTS.md).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "dados"
TESTS = ROOT / "tests"
PLANS = ROOT / "docs" / "superpowers" / "plans"
RULES = ROOT / ".claude" / "rules"
THIS_FILE = Path(__file__).resolve()
PLAN_STATUS_LINES = 8
CACHE_DIRS = {"__pycache__"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def files_under(folder: Path, pattern: str = "*") -> list[Path]:
    """Real files below `folder`, skipping caches."""
    return sorted(p for p in folder.rglob(pattern)
                  if p.is_file() and not CACHE_DIRS & set(p.relative_to(folder).parts))


def corpus(paths: list[Path], skip: set[Path]) -> str:
    """The text of every readable path that is not in `skip`, joined."""
    return "\n".join(read(p) for p in paths if p.resolve() not in skip)


def word_in(name: str, text: str) -> bool:
    """`name` appears as a whole token (not inside a longer identifier)."""
    return re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text) is not None


def agent_docs() -> list[Path]:
    """Documents that may point at a script: AGENTS.md and every area rule."""
    return [ROOT / "AGENTS.md", *sorted(RULES.glob("*.md"))]


def python_sources() -> list[Path]:
    """Every test and script: the code that may import or run another file."""
    return files_under(TESTS, "*.py") + files_under(SCRIPTS, "*.py")


def unreferenced_scripts() -> list[str]:
    """Scripts that no rule, test, `check_changes.py` or other script mentions."""
    orphans = []
    for script in files_under(SCRIPTS, "*.py"):
        others = corpus(agent_docs() + python_sources(), {THIS_FILE, script.resolve()})
        if not (word_in(script.name, others) or word_in(script.stem, others)):
            orphans.append(script.relative_to(ROOT).as_posix())
    return orphans


def fixture_tokens(fixture: Path) -> list[str]:
    """Names a test can use to point at a fixture: its file, its stem, its folder."""
    relative = fixture.relative_to(FIXTURES)
    return [fixture.name, fixture.stem, *relative.parts[:-1]]


def mentioned_as_path(token: str, text: str) -> bool:
    """`token` shows up quoted or as a path segment, which is how tests name data."""
    return re.search(rf"[\"'/\\]{re.escape(token)}[\"'/\\.]", text) is not None


def unreferenced_fixtures() -> list[str]:
    """Files in tests/dados that no test or script names."""
    orphans = []
    code = corpus(python_sources(), {THIS_FILE})
    for fixture in files_under(FIXTURES):
        tokens = fixture_tokens(fixture)
        if not any(word_in(t, code) and mentioned_as_path(t, code) for t in tokens):
            orphans.append(fixture.relative_to(ROOT).as_posix())
    return orphans


def unused_test_helpers() -> list[str]:
    """`tests/_*.py` helpers that nothing imports: scratch files nobody removed."""
    orphans = []
    for helper in sorted(TESTS.glob("_*.py")):
        if helper.name == "__init__.py":
            continue
        others = corpus(python_sources(), {THIS_FILE, helper.resolve()})
        if not word_in(helper.stem, others):
            orphans.append(helper.relative_to(ROOT).as_posix())
    return orphans


def plans_without_status(folder: Path = PLANS) -> list[str]:
    """Plans whose first lines carry no `Status: active` marker."""
    missing = []
    for plan in sorted(folder.glob("*.md")):
        head = read(plan).splitlines()[:PLAN_STATUS_LINES]
        if not any(line.strip() == "Status: active" for line in head):
            missing.append(plan.as_posix())
    return missing


def test_every_script_is_referenced():
    assert unreferenced_scripts() == [], (
        "unreferenced scripts: reference them from a rule/test/check_changes.py, or delete them")


def test_every_fixture_is_referenced_by_a_test():
    assert unreferenced_fixtures() == [], "unreferenced fixtures in tests/dados: use or delete them"


def test_every_underscore_test_helper_is_imported():
    assert unused_test_helpers() == [], "scratch helpers in tests/ that nothing imports: delete them"


def test_every_plan_declares_it_is_active():
    assert plans_without_status() == [], (
        "plans without a 'Status: active' line near the top: archive (move/delete) delivered plans")


def test_plan_detector_flags_a_plan_without_marker(tmp_path):
    """Without this the plan check could pass empty: a plan with no marker must be flagged."""
    (tmp_path / "2026-01-01-x.md").write_text("# plan\n\nno marker\n", encoding="utf-8")
    (tmp_path / "2026-01-02-y.md").write_text("# plan\n\nStatus: active\n", encoding="utf-8")
    assert [p.rsplit("/", 1)[-1] for p in plans_without_status(tmp_path)] == ["2026-01-01-x.md"]


def test_word_in_ignores_longer_identifiers():
    assert word_in("verify_search", "run scripts/verify_search.py")
    assert not word_in("search", "my_search_tool")
