# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- **plc-code / plc-sim (web)** — the analysis and simulation servers no longer
  install CORS middleware with `allow_origins=["*"]` and `allow_credentials=True`.
  Neither server authenticates, and the simulation API writes PLC tags, so that
  policy advertised a credentialled cross-origin channel to any page the operator
  had open (browsers reject that exact combination, so it also never worked as
  written). CORS is now opt-in via `PLC_WEB_ALLOWED_ORIGINS`, a comma-separated
  allow-list; unset means no middleware at all, which is what the bundled
  same-origin UI needs.
- **plc-code / plc-sim (CLI)** — `plc code web` and `plc sim web` now bind to
  `127.0.0.1` by default instead of `0.0.0.0`. Pass `--host 0.0.0.0` to expose
  them deliberately.

### Added
- **plc-modbus (client)** — new `ModbusClient.read_register_block(spec, count,
  dtype)`, reading `count` consecutive registers in a single request and
  returning them keyed by each register's own spec
  (`{"HOLDING:10": 42, "HOLDING:11": 99}`). The mapping shape is what lets
  plc-core report which address produced which value without importing
  plc-modbus to parse the spec. `read_register_at` is unchanged for callers and
  now delegates to it.
- **plc-code (executor/codegen)** — `ExpressionTranslator.BUILTIN_MAP` now maps the
  inverse-trigonometric builtins `ASIN/ACOS/ATAN/ATAN2` to `math.asin/acos/atan/atan2`
  (needed by trig-form closed solutions, e.g. Cardano's three-real-roots branch).
- **plc-code (executor/runtime)** — constant `DATA_BLOCK`s referenced as
  `"DbName".MEMBER` now auto-load from the runtime's block search paths (mirroring
  `call_named_block` for FUNCTION/FB sub-blocks), so shared constant DBs no longer
  need to be registered by hand. New public helper `load_data_block(path)`.

### Fixed
- **plc-core (testing/runner)** — the `modbus_read` step honours `count` again
  (#1). `_execute_modbus_read` called `read_register_at`, which is single-register
  by construction, and never referenced `step.count` — so a `count: 20` scan read
  exactly one register and reported it as success, with no error and no warning
  that the value had been dropped. The field was parsed, unit-tested and
  documented ("Read one or more Modbus registers") the whole time; only the
  executor ignored it. It now always goes through `read_register_block`, so
  `count` cannot be silently dropped by a code path again, and every register
  read appears in `actual_values` under its own spec.
  `count` is validated at parse time (must be an integer >= 1) and a `AREA:N/B`
  bit spec with `count > 1` is refused outright rather than guessed at.
  `modbus_assert` and `modbus_wait_until` were checked and have no `count` field
  at all, so nothing was being dropped there.
- **plc-code (executor)** — SCL string literals were rewritten as if they were
  code, in two independent places. Both corrupted the literal silently: the block
  still compiled, only its string content was wrong (an alarm text, a state label).
  - `control_flow._normalize_spacing` ran ~25 keyword-spacing substitutions over
    the whole line, so `'DO WHILE loop'` became `' DO WHILE loop'` and
    `'column A    column B'` lost its padding. It now normalizes only the
    unquoted segments, via a new `_quote_mask` helper shared with the
    `_INLINE_COMPOUND_SPLIT` fix. Double-quoted *symbol names*
    (`"ForwardKinematicMdh"`, `"DbSettings".member`) are opaque in the same way.
  - `codegen.ExpressionTranslator.translate` ran its ~12 rewriting passes over
    the raw expression, so `'CASE#1'` became `'CASEself.1'`, `'a = b'` became
    `'a == b'` and `'TRUE'` became `'True'`. String literals are now extracted to
    inert `__SLIT<n>__` placeholders first and restored last — the same trick the
    named sub-block call extraction already used.
- **plc-core (opcua)** — `browse_node`/`TagResolver` dereferenced a DataValue's
  `Value` without checking it was present.
- **plc-sup (testing/clients)** — a Redis stream entry with no field map raised
  `AttributeError` instead of returning `None`.

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
- **plc-code (executor/control_flow)** — a `FUNCTION` whose return value is
  consumed in an assignment while it ALSO binds `=>` VAR_OUTPUT params
  (`#ret := "Foo"(x := #a, out => #b)`) now wires both: the return value went
  through the expression path, which silently dropped the `=>` outputs (the
  targets kept their default value). Such a call is now routed through the
  multi-statement form (call into a temp dict, assign every `=>` output, then
  assign the return value). Statement-position calls (`"Foo"(out => #b);`) were
  already correct; pure return-value calls (no `=>`) are unchanged.
- **plc-code (parser/lexer/executor)** — the three items previously tracked under
  *Known issues* are verified resolved and no longer reproduce; each is now locked
  by a regression test:
  - an identifier ending in `of` (e.g. `ComputeProfile1Dof`) tokenises as a single
    `IDENTIFIER` — the array `of` clause is matched in the parser by exact value,
    never carved out of a longer identifier by the lexer
    (`test_lexer.py::TestIdentifierWithTrailingOf`);
  - two `:=` statements on one source line both translate — the parser emits one
    statement per `;`, so the second is not silently dropped end to end
    (`test_limitation_fixes.py::test_two_assignments_on_one_source_line_both_assign`);
  - an `Array[..] of <UDT>` passed as a direct FC parameter resolves
    (`test_array_of_udt.py`).

### Changed
- **workspace** — the Python version (`.python-version`, 3.12) and every dev tool
  version are now pinned exactly. Previously `ruff>=0.1.0` / `black>=23.0.0` /
  `mypy>=1.0.0` floated while the local venv ran a different Python than CI, so
  the gate turned red on tool releases rather than on code changes.
- **workspace** — ruff is configured once at the root; each package now carries
  `extend = "../../pyproject.toml"` instead of its own copy of the rules, which
  had already drifted into six independently-maintained blocks.
- **workspace** — `uv run pytest` from the repo root runs the whole suite again.
  Every `tests/` directory carried an `__init__.py`, so each package's suite
  imported as the same `tests` package and the second `conftest.py` aborted the
  run with "Plugin already registered under a different name". CI no longer needs
  its per-package loop.

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
