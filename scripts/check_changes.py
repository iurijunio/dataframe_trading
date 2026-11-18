"""Tells what to check and what to reopen after changing code.

    .venv/Scripts/python.exe scripts/check_changes.py                 # uncommitted changes
    .venv/Scripts/python.exe scripts/check_changes.py --since <commit>  # since a commit
    .venv/Scripts/python.exe scripts/check_changes.py --run           # also runs the checks

The lists live here so the rule does not depend on memory. Only checks that need
no argument run with --run; the others come out as reminders.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(Path(".venv/Scripts/python.exe"))

CYCLE = re.compile(r"ui/(app\.py|callbacks.*\.py|cb_\w+/\w+\.py)$")
ENGINE = re.compile(r"(core/engine/|strategies/)")
STRATEGY = re.compile(r"(strategies/|core/codigo\.py$)")
SEARCH = re.compile(r"(busca\.py$|core/busca/)")
RESEARCH_SCREEN = re.compile(
    r"ui/(callbacks\.py|cb_pesquisa/\w+\.py|callbacks_(candidata|portfolio)\.py|components/(mining|mine_\w+|scatter|charts|stats_cards|"
    r"results_grid|wfa_\w+|candidata_panel|portfolio_panel|detalhes_cards|robustez_cards|analytics_charts|cartao|ficha)\.py)$"
)
HAS_CODE = re.compile(r"\.(py|sql|js|css)$")
CLOSES_CAPTURE = re.compile(
    r"(^captura\.py$|core/(captura|ingest|db_manager|papel|plano|variantes|mt5_source|contrato_dia|conferencia_ordens|ordens_backtest)\.py$|core/schema\.sql$|core/engine/|strategies/)"
)
CLOSES_BOTH = re.compile(r"(^ordens_real\.py$|core/(ordens|corretora|papel_vivo|ponte|comandos|diario_ordens|ordem_teste|contrato_dia|captura|db_manager)\.py$)")


def what_to_check(files: list[str]) -> dict[str, list[str]]:
    """Translates the changed files into checks and reopenings."""
    files = [f.replace("\\", "/") for f in files]
    has = lambda rule: any(rule.search(f) for f in files)  # noqa: E731
    run: list[str] = []
    remind: list[str] = []
    if has(HAS_CODE):
        remind.append("Whole suite: pytest -q")
    if has(CYCLE):
        run.append(f"{PY} -m pytest -q tests/test_callbacks_sem_ciclo.py")
    if has(ENGINE):
        run.append(f"{PY} -m pytest -q tests/test_motor_camadas.py")
    if has(STRATEGY):
        remind.append("Strategy code changed: scripts/resign_code_hash.py --since <commit> (outside the trading session)")
    if has(SEARCH):
        remind.append("Search proof: scripts/verify_search.py <busca_id>. A running search keeps the old code")
    if has(RESEARCH_SCREEN):
        run.append(f"{PY} scripts/screens_reference.py check")
    reopen: list[str] = []
    if has(CLOSES_BOTH):
        reopen.append("Close the windows Dataframe - Captura and Dataframe - Ordens real, then open iniciar.bat")
    elif has(CLOSES_CAPTURE):
        reopen.append("Close the window Dataframe - Captura, then open iniciar.bat")
    elif any(f.startswith(("ui/", "core/")) for f in files):
        reopen.append("Close and reopen iniciar.bat")
    return {"run": run, "remind": remind, "reopen": reopen}


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [s for s in out.splitlines() if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="HEAD", help="compare since this commit")
    ap.add_argument("--run", action="store_true", help="run the checks that need no argument")
    args = ap.parse_args()
    files = _git("diff", "--name-only", args.since) + _git("ls-files", "--others", "--exclude-standard")
    plan = what_to_check(files)
    for title, key in (("Check", "run"), ("Remember", "remind"), ("Reopen", "reopen")):
        for item in plan[key]:
            print(f"{title}: {item}")
    if not any(plan.values()):
        print("Nothing to check.")
    failed = 0
    if args.run:
        for command in plan["run"]:
            print(f"\n>>> {command}")
            failed += subprocess.run(command.split(), cwd=ROOT).returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
