# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

> Working-tree note (2026-05-30): all changes in this section are committed on
> `main`, which is ahead of `origin/main` and not yet pushed. The shell was
> unstable when these were made — re-verify with `git log --oneline origin/main`.

### Added
- **plc-code (executor/codegen)** — `ExpressionTranslator.BUILTIN_MAP` now maps the
  inverse-trigonometric builtins `ASIN/ACOS/ATAN/ATAN2` to `math.asin/acos/atan/atan2`
  (needed by trig-form closed solutions, e.g. Cardano's three-real-roots branch).
- **plc-code (executor/runtime)** — constant `DATA_BLOCK`s referenced as
  `"DbName".MEMBER` now auto-load from the runtime's block search paths (mirroring
  `call_named_block` for FUNCTION/FB sub-blocks), so shared constant DBs no longer
  need to be registered by hand. New public helper `load_data_block(path)`.

### Known issues
- **plc-code (parser/lexer)** — an identifier whose name ends in `of`
  (e.g. `ComputeProfile1Dof`) is mis-tokenised: the trailing `of` is read as the
  `OF` keyword (as in `Array[..] OF`), corrupting the statement. Workaround: avoid
  a trailing `of`/`Dof` in block/variable names. Candidate fix: the lexer must not
  split `OF` out of a longer identifier (respect word boundaries).

### Fixed
- **plc-code (executor/transpiler)** — five SCL constructs that previously
  transpiled to broken Python (and forced downstream workarounds) now work:
  - `REGION` names containing hyphens or digits (e.g. `REGION Per-axis validation`,
    `REGION Set 7 phases`) — the parser captured only the leading identifier and
    leaked the rest into the region body as invalid code.
  - Assignments whose right-hand side spans several source lines inside a `REGION`
    (operator-led continuation) — only the first line was translated.
  - Global DB references `"DbName".MEMBER` — the parser inserts spaces around the
    dot (`"db" . MEMBER`), which the DB-access pattern no longer matched.
  - Quoted-name sub-block calls used in expression position
    (`IF NOT "IsFiniteLreal"(x := #v) THEN ...`) — only statement-position calls
    were supported; `call_named_block` now also returns the `FUNCTION` value.
  - Hex literals in code (`#status := 16#8201;`) — the `#` was mistaken for an
    instance-variable prefix and the value was lost.

## [0.1.0] - 2026-05-29

First public release.

### Added
- **plc-core** — shared config (`plc.yaml`) loader, S7/IOL address models, CLI plugin framework, reporting (Markdown/PDF), OPC UA client, YAML scenario test framework.
- **plc-code** — SCL parser/lexer for TIA Portal V21 `.s7dcl` exports, header/interface extraction, MkDocs documentation generator, quality rules/analyzer (call graphs, DB cross-reference, state-machine detection), SCL→Python transpiler with a pytest harness, Draw.io diagram generator, PDF/Word export.
- **plc-iol** — I/O list management: XML/Excel import/export, TAGS/IOL comparison and validation.
- **plc-modbus** — async Modbus TCP client with YAML step types for integration tests.
- **plc-net** — industrial network monitoring (scapy) with an OPC UA binary dissector and Rich dashboards.
- **plc-sim** — OPC UA simulation interface, CLI, embedded web UI, integration-test runner.
- **plc-sup** — supervision pipeline integration tests (OPC UA → Redis → TimescaleDB → REST API).
- Example project under `examples/demo-project/`.
- MIT license, CI (lint + types + per-package tests).

### Known limitations
- PDF export (`plc code export pdf`) requires `pandoc`, the eisvogel template, and `xelatex` installed locally.
- `plc-sim` and `plc-sup` are runtime integration tools and require live infrastructure (OPC UA server, Redis, TimescaleDB) to exercise end to end.
- `plc code docs` writes generated output that is git-ignored.

[Unreleased]: https://github.com/core-engineering/siemens-plc-tools/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/core-engineering/siemens-plc-tools/releases/tag/v0.1.0
