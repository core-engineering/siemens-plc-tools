# Contributing

Thanks for your interest in contributing to siemens-plc-tools!

## Development setup

This is a `uv` workspace monorepo (7 packages under `packages/`).

```bash
uv sync --all-extras --all-packages
```

## Running the checks

> Note: run tests **per package**. A repo-root `pytest packages/*/tests tests/`
> fails to collect because multiple packages each have a `tests/conftest.py`
> that pytest registers under the same plugin name.

```bash
# tests
for p in plc-core plc-code plc-iol plc-modbus plc-sim plc-sup; do
  (cd packages/$p && uv run pytest -q)
done
uv run pytest tests/ -q          # integration tests

# lint / format / types
uv run ruff check packages/*/src
uv run black --check packages/*/src
uv run mypy packages/*/src
```

## Commit & PR conventions

- Small, focused commits with imperative messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Add tests for new behavior; keep the suite green.
- Run lint/format/types before opening a PR.

## Adding a new package

1. Create `packages/plc-<name>/` with its own `pyproject.toml`.
2. Depend on `plc-core` (and others as needed) via `>=0.1.0`.
3. Register the CLI via the `plc_tools.plugins` entry point.
4. Add it to the workspace and to the meta-package extras.
