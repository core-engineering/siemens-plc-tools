# Contributing

Thanks for your interest in contributing to siemens-plc-tools!

## This repository is public

That is easy to forget, because the tool is developed against real PLC programs
that are not. Customer project names, contract codes, site names, document
numbers and absolute developer paths have leaked into this repo before — through
design docs, CHANGELOG measurements and test docstrings that cited real programs
by name. Clearing them required a full history rewrite.

**Never commit, in code, comments, docstrings, tests, commit messages or the
CHANGELOG:**

- a customer, site or end-user name;
- a contract or project code (the `C2NNNNN` shape, and anything like it);
- a real document reference number;
- an absolute developer path (anything rooted at a user's home directory, on
  either Windows or WSL — the guard below matches both shapes);
- a block, tag or file name *attributed to* a named customer.

Measurements taken against real programs are welcome and valuable — they are
what justifies design decisions. It is the **attribution** that must go, not the
number. Write `project-A carries 36 safety blocks`, never `<customer> carries 36
safety blocks`. The alias-to-project mapping is kept by the maintainer, outside
this repository, on purpose: putting it here would undo the aliasing.

An unattributed block name is not a leak. `UserMode.s7dcl` on its own is one
filename among thousands; `<customer>'s UserMode.s7dcl` identifies a delivery.

**Internal working notes are deliberately untracked** — `.superpowers/`,
implementation plans, task briefs, execution ledgers, internal audits. They name
customers freely and have no place in a public toolchain repo. `.gitignore`
covers them; do not add exceptions.

`tests/test_no_confidential_references.py` enforces this and runs in CI. It uses
a base64-encoded deny-list, because spelling those identifiers out in plaintext
would put the very strings the test excludes back into a public repo. To add a
term, follow the instructions in that file's docstring. If the test fails, scrub
the finding — do not extend an exclusion.

Found something already committed that should not be here? See
[SECURITY.md](SECURITY.md) — please report it privately rather than opening a
public issue that quotes it.

## Development setup

This is a `uv` workspace monorepo (7 packages under `packages/`).

```bash
uv sync --all-extras --all-packages
```

## Running the checks

These are exactly what CI runs (`.github/workflows/ci.yml`) — run them and you
know whether your PR will be green.

```bash
uv run pytest -q                 # whole workspace, one pass, with coverage

uv run ruff check packages/*/src packages/*/tests src tests
uv run black --check packages/*/src packages/*/tests src tests
uv run mypy packages/*/src       # src only: see below
```

Three things worth knowing:

- **One pytest run covers everything.** A per-package loop used to be required,
  because every `tests/` directory carried an `__init__.py`, so each suite
  imported as the same `tests` package and the second `conftest.py` collected
  aborted the run with "Plugin already registered under a different name". They
  are plain directories now. **Do not add an `__init__.py` to a tests directory** —
  it brings that failure back.
- **Lint and format cover tests too**, not just `src`. CI has always gated them;
  when this file told contributors otherwise, the test suites drifted.
- **mypy stays on `src`.** The per-package `tests/` directories collide as one
  module for mypy, so `pyproject.toml` excludes them.

The full run measures coverage and fails below the floor in
`[tool.coverage.report]`. That floor is a ratchet: raise it, never lower it.

## Commit & PR conventions

- Small, focused commits with imperative messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Add tests for new behavior; keep the suite green.
- Run lint/format/types before opening a PR.

## Adding a new package

1. Create `packages/plc-<name>/` with its own `pyproject.toml`.
2. Depend on `plc-core` (and others as needed) via `>=0.1.0`.
3. Register the CLI via the `plc_tools.plugins` entry point.
4. Add it to the workspace and to the meta-package extras.
