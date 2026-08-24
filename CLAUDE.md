# PLC Tools Development Guide

This document describes the architectural patterns, coding standards, and quality processes for the PLC Tools monorepo - a unified toolset for PLC development.

## 1. Project Overview

### Purpose
PLC Tools is a monorepo containing packages for:
- **plc-core**: Shared utilities, models, config, reporting, OPC UA client, and a YAML scenario test framework
- **plc-code**: SCL/LADDER code analysis, documentation, and simulation/testing for TIA Portal V21
- **plc-iol**: I/O list management and validation
- **plc-modbus**: Async Modbus TCP client (read) for integration testing
- **plc-sim**: OPC UA simulation interface and live-PLC YAML scenario runner
- **plc-sup**: Supervision-pipeline integration tests (OPC UA → Redis → TimescaleDB → REST)
- **plc-net**: Industrial network / OPC UA traffic monitoring (scapy)

### Current Status (v0.4.0)

| Package | Status | Description |
|---------|--------|-------------|
| plc-core | Stable | config, models, CLI plugin framework, reporting, OPC UA client, YAML test framework |
| plc-code | Stable | parser (SCL + LADDER), extractor, generator, analyzer, executor (incl. F-LAD interpreter), testing, web, draw.io, PDF/Word export |
| plc-iol | Beta | importers/exporters (XML/Excel), comparison, validation |
| plc-modbus | Alpha | async Modbus TCP client (read-side) for integration tests |
| plc-sim | Alpha | OPC UA simulation + live-PLC scenario runner + web UI |
| plc-sup | Experimental | supervision-pipeline integration tests (no unit tests yet) |
| plc-net | Experimental | network / OPC UA monitoring (no unit tests yet) |
| plc-trace | Beta | cycle-granular on-PLC trace recorder: UDT-first SCL scaffold generator, OPC UA control/fetch client, CLI + scenario steps |

---

## 2. Repository Structure

```
plc-tools/                          # Monorepo root
├── packages/
│   ├── plc-core/                   # Shared library (no dependencies on other packages)
│   │   ├── src/plc_core/
│   │   │   ├── __init__.py
│   │   │   ├── config/             # Configuration framework
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py         # BaseConfig, PathsConfig
│   │   │   │   └── loader.py       # find_config(), load_yaml()
│   │   │   ├── models/             # Shared data models
│   │   │   │   ├── __init__.py
│   │   │   │   ├── address.py      # PLCAddress (S7 ↔ IOL format)
│   │   │   │   └── types.py        # DataType, IOCategory enums
│   │   │   ├── cli/                # CLI framework
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py         # Plugin discovery, command groups
│   │   │   │   └── output.py       # Rich console helpers
│   │   │   └── reporting/          # Reporting framework
│   │   │       ├── __init__.py
│   │   │       ├── models.py       # Report, Finding, Severity
│   │   │       ├── markdown.py     # Markdown generation
│   │   │       └── pdf.py          # PDF export (Pandoc)
│   │   ├── tests/
│   │   └── pyproject.toml
│   │
│   ├── plc-code/                    # PLC code analysis module
│   │   ├── src/plc_code/
│   │   │   ├── __init__.py
│   │   │   ├── cli.py              # Click commands: plc code ...
│   │   │   ├── core/               # Configuration
│   │   │   ├── parser/             # SCL lexer, parser, models
│   │   │   ├── extractor/          # Header, interface extraction
│   │   │   ├── generator/          # Markdown generation
│   │   │   ├── highlighting/       # Pygments lexer for SCL
│   │   │   ├── project/            # Pipeline and discovery
│   │   │   ├── analyzer/           # Call graphs, type graphs, quality
│   │   │   ├── executor/           # SCL-to-Python transpiler
│   │   │   └── testing/            # Unit test framework
│   │   ├── tests/
│   │   └── pyproject.toml          # depends on plc-core
│   │
│   ├── plc-iol/                    # IOL module (from 204-iol-management)
│   │   ├── src/plc_iol/
│   │   │   ├── __init__.py
│   │   │   ├── cli.py              # Click commands: plc iol ...
│   │   │   ├── core/               # IOPoint, IODatabase, config
│   │   │   ├── importers/          # XML, Excel importers
│   │   │   ├── exporters/          # XML, Excel exporters
│   │   │   └── analyzers/          # Comparison, validation
│   │   ├── tests/
│   │   └── pyproject.toml          # depends on plc-core
│   ├── plc-modbus/                 # async Modbus TCP client (read) — depends on plc-core
│   ├── plc-sim/                    # OPC UA sim + scenario runner + web — plc-core + plc-modbus
│   ├── plc-sup/                    # supervision-pipeline tests (Redis/Timescale/REST) — plc-core
│   └── plc-net/                    # network / OPC UA monitoring (scapy) — standalone
│
├── src/plc_tools/                  # Main entry point package
│   ├── __init__.py                 # Version, imports
│   └── cli.py                      # Root CLI with plugin loading
│
├── tests/                          # Integration tests
│   └── test_integration.py
│
├── pyproject.toml                  # Workspace root with optional extras
├── CLAUDE.md                       # This file
└── README.md
```

### Package Dependencies
```
plc-core (standalone)
    ↑
    ├── plc-code   (→ plc-core)
    ├── plc-iol    (→ plc-core)
    ├── plc-modbus (→ plc-core)
    ├── plc-sim    (→ plc-core[opcua] + plc-modbus)
    ├── plc-sup    (→ plc-core[opcua])
    └── plc-trace  (→ plc-core[opcua] + plc-code)
plc-net (standalone — no internal deps)

plc-tools (meta-package, optional extras)
    ├── [core]  → plc-core
    ├── [code]  → plc-core + plc-code
    ├── [iol]   → plc-core + plc-iol
    ├── [sim]   → plc-core + plc-modbus + plc-sim
    ├── [sup]   → plc-core + plc-sup
    ├── [net]   → plc-net
    ├── [trace] → plc-core + plc-code + plc-trace
    └── [all]   → everything
```

The only cross-peripheral coupling is `plc-sim → plc-modbus` (declared) and
optional runtime imports of `plc_code.web` inside `plc sim web` and
`plc_trace` inside `plc sim test` (both try/except, degrade if absent).

---

## 3. CLI Structure

### Command Hierarchy

Each subgroup is contributed by a package plugin (see Plugin Architecture); a
partial install exposes only the installed groups.

```bash
plc                              # Root command group
├── code                         # plc-code: SCL/LADDER analysis, docs, simulation
│   ├── init [--with-tests]      # Initialize project
│   ├── status                   # Show project status
│   ├── lint [PATH] [-f]         # Quality analysis (text/json)
│   ├── docs [PATH] [--serve]    # Generate MkDocs documentation
│   ├── test [PATH] [-v]         # Run block unit tests
│   │   └── --coverage           #   ...and print SCL line coverage per block
│   ├── diff OLD NEW [-f]        # Semantic diff between two exports (exit 0/1/2)
│   ├── xref --tags DIR [PATH]   # Tag table vs code: unused I/O, undeclared tags
│   ├── transpile [PATH]         # Print generated Python
│   │   ├── --check [-f]         #   ...or report blocks that won't load (exit 1)
│   │   └── --conformance [-f]   #   ...or report statement-parser coverage (always exit 0)
│   ├── trace [PATH] [-b -o -f]  # I/O→logic dependency trace (text/json/mermaid)
│   ├── drawio --doc-map --out   # Generate Draw.io diagrams
│   ├── web [--port --build-docs]# FastAPI analysis server / I/O explorer
│   └── export {pdf|params}      # PDF report / Word parameter tables
│
├── iol                          # plc-iol: I/O list management
│   ├── init | status
│   ├── import {tags|iol}        # Import S7-1500 XML / IOL Excel
│   ├── export {tags|iol}        # Export S7-1500 XML / IOL Excel
│   ├── list [--category --group]
│   ├── compare <src> <tgt>
│   └── validate
│
├── sim                          # plc-sim: live-PLC OPC UA + scenario runner
│   ├── connect | browse | read | write | monitor
│   ├── web                      # OPC UA web UI (co-hosts plc-code web if present)
│   ├── test                     # YAML scenario runner (+ Modbus/flash asserts)
│   └── results
│
├── sup                          # plc-sup: supervision-pipeline integration tests
│   └── test                     # OPC UA → Redis → TimescaleDB → REST verification
│
├── net                          # plc-net: live network monitoring (needs root)
│   ├── monitor                  # multi-protocol traffic dashboard
│   └── opcua                    # OPC UA binary dissector
│
└── trace                        # plc-trace: cycle-granular on-PLC trace recorder
    ├── scaffold --udt --depth   # Generate trace UDT + instance DB + recorder FC
    ├── status                   # Show current recorder status
    ├── start [--mode --decimation]
    ├── stop
    └── fetch [-o]                # Fetch recording, save as CSV + JSON metadata
```

### Plugin Architecture
Subgroups are discovered at runtime via the `plc_tools.plugins` entry-point group
(`plc_core.cli.discover_plugins`); discovery tolerates load failures, so a partial
install still works:
```toml
# Each package registers its Click group, e.g.:
# [project.entry-points."plc_tools.plugins"]
# code = "plc_code.cli:code_group"
# iol  = "plc_iol.cli:iol_group"
# sim  = "plc_sim.cli:sim_group"
# sup  = "plc_sup.cli:sup_group"
# net  = "plc_net.cli:net_group"
```

---

## 4. Configuration

### Unified Config: `plc.yaml`
```yaml
project:
  name: "My Project"
  code: "PRJ"
  version: "1.0.0"

# Shared paths
paths:
  root: .

# SCL module configuration (consumed by `plc code ...`)
code:
  paths:
    source: program-blocks   # SCL source files (.s7dcl)
    tags: tags               # XML tag exports
    docs: docs               # Generated documentation
    tests: tests             # Unit test files (test_*.py)
  quality:
    enabled: true
    fail_on_error: false
    safety_path_pattern: safety  # default; case-insensitive substring matched against
                                 # any directory in a block's path, not the filename
                                 # (the F003 safety-boundary check) — a source root or
                                 # checkout dir containing this substring matches everything

# IOL module configuration
iol:
  paths:
    tags: tags
    iol: specifications/iol
    database: .iol
  naming:
    pattern: "{io_category}_{location}_{signal}"
```

### Environment Variables

| Variable | Effect |
|----------|--------|
| `PLC_WEB_ALLOWED_ORIGINS` | Comma-separated origins allowed to call the web API cross-origin. Unset (default) installs no CORS middleware at all. |

The web servers (`plc code web`, `plc sim web`) serve their UI, docs and API from
one application, so browser calls are same-origin and need no CORS. They also
have **no authentication**, and `plc sim` writes PLC tags — so both bind to
`127.0.0.1` by default. Pass `--host 0.0.0.0` only on a network you control.

---

## 5. Module Boundary Rules

```
ALLOWED:
  plc-code  → imports from → plc-core ✓
  plc-iol  → imports from → plc-core ✓

FORBIDDEN:
  plc-core → imports from → plc-code ✗
  plc-core → imports from → plc-iol ✗
  plc-code  → imports from → plc-iol ✗
  plc-iol  → imports from → plc-code ✗
```

---

## 6. Development Standards

### Code Standards
| Rule | Requirement |
|------|-------------|
| Type annotations | Required for all public APIs (mypy strict) |
| Docstrings | NumPy-style for public functions/classes |
| Line length | 110 characters |
| Imports | Absolute imports, isort groups |
| Formatting | Black |
| Linting | Ruff (E, W, F, I, B, C4, UP; UP042 ignored — see `pyproject.toml`) |

### Toolchain
The Python version (`.python-version`) and every dev tool version
(`[dependency-groups] dev`) are pinned exactly. The gate must fail on a code
change, never on a tool release. Bump them deliberately, in their own commit,
together with whatever fixes the new version demands.

Ruff is configured **once**, at the workspace root; each package's
`pyproject.toml` carries `extend = "../../pyproject.toml"` rather than its own
copy of the rules.

### Pre-commit Checks
```bash
# Format and lint
uv run black packages/*/src packages/*/tests src
uv run ruff check --fix packages/*/src packages/*/tests src

# Type check
uv run mypy packages/*/src

# Run all tests (whole workspace, one pass)
uv run pytest
```

Note: no `tests/` directory carries an `__init__.py`. Adding one back makes every
package's suite import as the same `tests` package, and the second `conftest.py`
collected aborts the run with "Plugin already registered under a different name".

---

## 7. Quick Reference

### Common Commands
```bash
# Create virtual environment and install everything in editable mode
uv sync --all-extras --all-packages

# Install with a single extra (e.g. only code/iol/sim)
uv pip install -e .[code]

# Run all quality checks
uv run black packages/*/src packages/*/tests && \
uv run ruff check --fix packages/*/src packages/*/tests && \
uv run mypy packages/*/src && \
uv run pytest

# Run tests for specific package
uv run pytest packages/plc-core/tests
uv run pytest packages/plc-code/tests
uv run pytest packages/plc-iol/tests

# Run integration tests
uv run pytest tests/test_integration.py

# Generate documentation
uv run plc code docs --serve
```

### CLI Commands
```bash
# SCL commands
plc code init --name "My Project" --code "PRJ"
plc code status
plc code lint
plc code docs
plc code test

# IOL commands
plc iol init --name "My Project" --code "PRJ"
plc iol status
plc iol import tags --path ./tags
plc iol validate
```

### Import Examples
```python
# From plc-core
from plc_core.config import find_config_file, load_yaml
from plc_core.models import PLCAddress, DataType, IOCategory
from plc_core.reporting import Severity, Finding, Report

# From plc-code
from plc_code.parser import parse_scl_file
from plc_code.extractor import extract_header, extract_interface
from plc_code.generator import generate_markdown

# From plc-iol
from plc_iol import IOPoint, IODatabase
from plc_iol.importers import XMLImporter
from plc_iol.exporters import ExcelExporter
```

---

## 8. Testing Requirements

| Requirement | Details |
|-------------|---------|
| Unit tests | Each package has `tests/` directory (no `__init__.py` — see §6) |
| Integration tests | Root `tests/` for cross-package tests |
| Coverage goal | 85% per package |
| Coverage gate | `fail_under = 68` (whole workspace), a ratchet — raise it, never lower it |

### Coverage: goal vs. state

`uv run pytest` measures all nine coverage targets and fails below the floor in
`[tool.coverage.report]`. As of the last full run: **68.26%** overall
(14019/20537 statements).

| Package | Coverage | Covered / statements |
|---------|----------|----------------------|
| plc-modbus | 97.8% | 135 / 138 |
| plc-trace | 72.9% | 312 / 428 |
| plc-code | 72.8% | 10661 / 14649 |
| plc-iol | 67.3% | 1082 / 1608 |
| plc-tools | 65.3% | 32 / 49 |
| plc-core | 58.0% | 1033 / 1780 |
| plc-net | 49.9% | 230 / 461 |
| plc-sup | 48.0% | 214 / 446 |
| plc-sim | 32.7% | 320 / 978 |

The statement counts matter as much as the percentages: `plc-code` is 71% of the
workspace, so it alone sets the headline number.

`plc-net`, `plc-sup` and `plc-sim` now have unit suites over their pure logic
(dissector, step parsing, executors on fakes); what remains uncovered there is
live I/O (capture, OPC UA/Redis/DB connections, the web layer).

---

## 9. Review Checklist

Before committing, verify:

**Code Quality:**
- [ ] All functions have complete type annotations
- [ ] Docstrings follow NumPy style
- [ ] Error messages are clear and actionable

**Testing:**
- [ ] New code has corresponding tests
- [ ] All tests pass
- [ ] Integration tests pass

**Code Quality Tools:**
- [ ] Black formatting
- [ ] Ruff linting
- [ ] Type checking (mypy)

---

## 10. Future Extension Points

New features follow this pattern:
1. Create `packages/plc-<name>/`
2. Depend on `plc-core` (and others as needed)
3. Register CLI via entry point
4. Add as optional extra

| Future Feature | Package | Dependencies |
|----------------|---------|--------------|
| Cross-reference | `plc-xref` | core, code, iol |
| Logic generation | `plc-gen` | core |
| LADDER analysis | `plc-ladder` | core |

Note: LADDER **execution** already exists inside `plc-code` (`executor/ladder/`, a
fixed-point F-LAD interpreter that runs ladder blocks through the same harness as
SCL). The planned `plc-ladder` package above is for static LADDER **analysis**,
which is distinct and not yet started.

---

## 11. Regenerating Project Documentation

For a downstream PLC project that depends on `plc-tools` (e.g.
`<your-project>`), the full doc-regeneration cycle is:

```bash
# 1. From the project root (where plc.yaml lives)
plc code docs            # writes <docs_dir>/ via the pipeline
mkdocs build             # renders <site_dir>/

# Optional during iteration
mkdocs serve --dev-addr 0.0.0.0:8000   # live reload at http://localhost:8000
```

`plc code docs` populates everything under `<docs_dir>/` from `plc.yaml`:

- `index.md` — auto-generated landing page (project name, live stats)
- `plc-blocks/`, `types/`, `data-blocks/` — per-block pages by category
- `graphs/`, `type-graphs/` — Mermaid call/type graphs
- `analysis/` — quality summary + rules reference
- `tests/summary.md` + `tests/coverage.md` — unit test results
- `tests/integration.md` — EFAT scenario index when `code.efat.test_dir`
  is set
- `global-data/` — DB cross-reference and audit
- `audits/` (or any name set via `code.external_docs[].dest`) — copies
  of external markdown groups (e.g. `audit-*.md` from your source tree)

`<docs_dir>` is overwritten on every run; old files from previous
generations stay unless removed manually. Add `<docs_dir>/` and
`<site_dir>/` to the project `.gitignore`.
