# PLC Tools Development Guide

This document describes the architectural patterns, coding standards, and quality processes for the PLC Tools monorepo - a unified toolset for PLC development.

## 1. Project Overview

### Purpose
PLC Tools is a monorepo containing packages for:
- **plc-core**: Shared utilities, models, and configuration
- **plc-code**: SCL code analysis, documentation, and testing for TIA Portal V21
- **plc-iol**: I/O list management and validation

### Current Status (v0.3.0)

| Package | Status | Description |
|---------|--------|-------------|
| plc-core | Complete | Shared utilities: config, models, CLI, reporting |
| plc-code | Complete | Parser, extractor, generator, analyzer, executor, testing |
| plc-iol | Complete | Importers, exporters, analyzers, validation |

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
│   └── plc-iol/                    # IOL module (from 204-iol-management)
│       ├── src/plc_iol/
│       │   ├── __init__.py
│       │   ├── cli.py              # Click commands: plc iol ...
│       │   ├── core/               # IOPoint, IODatabase, config
│       │   ├── importers/          # XML, Excel importers
│       │   ├── exporters/          # XML, Excel exporters
│       │   └── analyzers/          # Comparison, validation
│       ├── tests/
│       └── pyproject.toml          # depends on plc-core
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
    ├── plc-code (depends on plc-core)
    └── plc-iol (depends on plc-core)

plc-tools (meta-package, optional extras)
    ├── [core] → plc-core
    ├── [code]  → plc-core + plc-code
    ├── [iol]  → plc-core + plc-iol
    └── [all]  → everything
```

---

## 3. CLI Structure

### Command Hierarchy
```bash
plc                              # Root command group
├── scl                          # SCL subgroup
│   ├── init                     # Initialize project
│   ├── status                   # Show project status
│   ├── lint [PATH]              # Quality analysis
│   ├── docs [PATH] [--serve]    # Generate documentation
│   ├── test [PATH] [-v]         # Run unit tests
│   └── export pdf [-o FILE]     # Export PDF report
│
└── iol                          # IOL subgroup
    ├── init                     # Initialize IOL config
    ├── status                   # Show project status
    ├── import <source>          # Import from XML or Excel
    │   ├── tags [--path]        # Import S7-1500 XML
    │   └── excel [--path]       # Import IOL Excel
    ├── export <target>          # Export to XML or Excel
    │   ├── tags [-o DIR]        # Export S7-1500 XML
    │   └── excel [-o FILE]      # Export IOL Excel
    ├── list [--category] [--group]  # List I/O points
    ├── compare <src> <tgt>      # Compare databases
    └── validate                 # Validate database
```

### Plugin Architecture
Plugins are discovered via entry points:
```python
# Each module registers via entry point:
# [project.entry-points."plc_tools.plugins"]
# code = "plc_code.cli:code_group"
# iol = "plc_iol.cli:iol_group"
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

# IOL module configuration
iol:
  paths:
    tags: tags
    iol: specifications/iol
    database: .iol
  naming:
    pattern: "{io_category}_{location}_{signal}"
```

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
| Line length | 100 characters |
| Imports | Absolute imports, isort groups |
| Formatting | Black |
| Linting | Ruff (E, W, F, I, B, C4, UP) |

### Pre-commit Checks
```bash
# Format and lint
uv run black packages/*/src packages/*/tests
uv run ruff check --fix packages/*/src packages/*/tests

# Type check
uv run mypy packages/*/src

# Run all tests
uv run pytest packages/*/tests tests/
```

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
| Unit tests | Each package has `tests/` directory |
| Integration tests | Root `tests/` for cross-package tests |
| Coverage | Minimum 85% per package |

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
| Cross-reference | `plc-xref` | core, scl, iol |
| Logic generation | `plc-gen` | core |
| LADDER analysis | `plc-ladder` | core |

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
