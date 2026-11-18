---
paths:
  - "*.py"
  - "core/**"
  - "ui/**"
  - "strategies/**"
  - "scripts/**"
---
# Small code (user's request, 2026-11-11)

Applies to all new code and to every file you touch, in any session and any agent.

- **Language:** everything committed to the repository is in English: code, names, comments,
  docstrings, logs, commit messages, docs, rules and agent prompts. Only on-screen text for the
  user stays in Portuguese, and it comes from a single module (e.g. `ui/texts.py`), never scattered
  through the logic. Chat with the user stays in Portuguese. Legacy Portuguese identifiers are not
  mass-renamed: rename only what you touch.
- **Small file, one responsibility.** Cap of 500 lines per file (the test
  `tests/test_harness_rules.py` enforces it). Aim for 150–300. Close to the cap: split before
  adding, never after.
- **Atomic function.** Does one thing and fits on one screen (aim for up to ~40 lines). If it needs
  a "now it does X" comment in the middle, X is another function.
- **Folder per subject.** A topic with more than one file becomes a package (`core/busca/`, `core/leitura/`,
  `ui/cb_operacao/`). The file name says what lives in it; no generic `utils.py`.
- **A new project starts like this:** folder structure decided in the design, before the first file.
- **Large file that already exists** (the test's `GRANDES` list): it does not grow. If you touch it,
  move your part to a new file; splitting the rest is a separate delivery, with no behavior change (plan
  `docs/superpowers/plans/2026-11-09-modularizacao.md`). Code that operates the real account (capture, orders,
  paper) is only split with the whole suite green and the user's approval.
