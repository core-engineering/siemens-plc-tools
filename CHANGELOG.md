# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **plc-code (CLI, analyzer)** — `plc code diff OLD NEW`: semantic diff between
  two SCL exports (directories or single `.s7dcl` files). Compares what the code
  means — blocks by name, interfaces variable by variable (added / removed /
  retyped / redefaulted), bodies statement by statement on the shared AST,
  flattened to edit granularity (a change in one `IF` branch reports that
  branch's line, not the whole construct) — so whitespace, comments and TIA
  re-export formatting never show as changes. UDT members and variable
  attributes (retain, access, setpoint) are compared; ladder networks diff by
  their canonical elements; an instance DB whose members the parser does not
  expose is reported "content differs (not semantically compared)" rather than
  a false "identical". Text and `-f json` output; exit 0 when semantically
  identical, 1 on any difference, 2 when an export could not be read
  (`analyzer/block_diff.py`).
- **plc-code (CLI, executor)** — `plc code test --coverage`: SCL line coverage
  measured while the block tests run — the qualification argument a FAT wants:
  not "the block has a test" but "these lines ran, these did not". The command
  sets `PLC_SCL_COVERAGE`; every block compiled inside the pytest subprocesses is
  instrumented (`TranspileOptions.instrument_coverage`, one
  `runtime.touch(block, line)` per statement, headers included), the runtime
  merges executable and touched lines into the named file at interpreter exit
  (processes add their shares), and the command prints a per-block table with
  percentages and missing-line ranges (`66.7% Demo (2/3 lines) missing: 14`).

## [0.3.0] - 2026-08-24

### Added
- **plc-net, plc-sup, plc-sim (tests)** — first real unit suites: the OPC UA
  dissector fed hand-built binary frames through fake packets (reassembly,
  service classification, categories), protocol classification, supervision step
  parsing and the verify executors on fake Redis/DB/API clients, simulation
  config and the `assert_stable`/`assert_flash` executors on fake OPC UA
  clients. No test opens a socket. Coverage gate raised to 68%.

### Changed
- **workspace (release)** — every package is versioned `0.3.0` (they disagreed:
  `pyproject` files said `0.1.0` while `plc_tools.__version__` said `0.3.0`),
  and the meta-package extras pin the workspace members exactly (`==0.3.0`);
  the members are not published, so a floating `>=` could have resolved to an
  unrelated PyPI package of the same name outside the workspace. First tagged
  release: `v0.3.0`.

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
- **plc-code (executor)** — the last of the production sweep: 348 of 349 blocks
  with code load (the one left reads an absolute address, `%DB5.%DBX31.1`, which
  the harness does not model and refuses with its line).

  - Bit, byte and word slices of a value: `#status.%X7` reads bit 7, `#word.%X0 :=
    #on` writes it (the base is the lvalue), `%B1`/`%W0` likewise —
    `PLCRuntime._bit_slice` / `_with_bit_slice`. Five production blocks.
  - System instructions with `=>` outputs in expression or statement position —
    `#ret := GET_DIAG(MODE := 1, LADDR := #a, CNT_DIAG => #n)`, refused until now
    — compile to `PLCRuntime.system_call(name, inputs, outputs)`, whose result
    feeds each output and the return value. `RD_SYS_T` is real: `OUT` is a DTL
    struct from the simulated clock (`PLCRuntime.system_time`, `epoch` +
    `clock`), and `DTL_TO_LDT` converts it. Every other instruction (`GET_DIAG`,
    `DPRD_DAT`, `DPWR_DAT`, `Serialize`, `RH_CTRL`, and the value-only `LED`,
    `DeviceStates`, `ModuleStates`, `RH_GetPrimaryID`) is a stub with no hardware
    behind it: a struct or array output is handed back untouched, a scalar output
    becomes 0, `RET_VAL` is `PLCRuntime.system_stub_status` (0, "no error", by
    default so the nominal path runs; set `16#8080` to exercise the block's error
    handling), and every call is appended to `PLCRuntime.system_call_log` (the
    last 10 000) so a test can assert what the block asked of the system. Only the
    instructions in `codegen.SYSTEM_INSTRUCTIONS` are stubbed; a user block called
    without quotes, or a positional argument to a system instruction, stays a
    located refusal. `RUNTIME(#mem)` measures simulated time between calls.
    `INT_TO_BYTE`, `BYTE_TO_WORD` mapped.
- **workspace (tests)** — `TestSuiteResult`, `TestCaseResult`, `TestingConfig`,
  `TestReporter` and `TestResultsCache` no longer raise a
  `PytestCollectionWarning` in every file that imports them.

- **plc-code (parser, CLI)** — a token-driven SCL statement parser, and
  `plc code transpile --conformance` to report what it reads.

  `SCLParser` lexed a block correctly and then flattened each region body back
  into a string, one space between every token (`parser.py:815-819`), leaving the
  executor to rebuild the structure with roughly a hundred regexes. `Region` now
  carries its token slice alongside that string, and a recursive-descent parser
  reads the tokens. `Region.content` is unchanged, byte for byte.

  The parser never guesses: what it cannot read becomes a located error and the
  cursor recovers to the next statement, so one unsupported construct does not
  hide the rest of a region. A committed test asserts every token is consumed by
  exactly one statement or one error — the guarantee whose absence let a whole
  `CASE` be dropped in silence.

  Measured over 649 blocks in five real PLC projects — 439 regions and, since
  `Network.tokens` landed, the 155 networks holding SCL outside any region:
  **100.00% token coverage over 178,742 tokens, every block, region and network
  clean, zero errors and zero silent loss.** The first measurement reported
  99.96% with 51 errors over the regions alone; both remaining constructs are
  read now — see the argument-depth fix below. Widening the population to all
  the SCL in those projects did not cost this layer a single error. The one silent case a
  final review found is fixed: `_at_case_label` accepted a nested
  `CASE`/`IF`/`FOR`/`WHILE` at the head of an outer CASE arm as ordinary label
  content, so the nested construct's own header was scanned for a colon that
  belonged to *it*, truncating the outer CASE there and leaking every arm after
  it to top level — the sole root cause of all 33 `silent_loss` findings the
  first measurement reported. The corpus now reports zero.

  Nothing generates from the AST yet, and the executor is untouched.
  `plc code transpile --check`'s own diagnostics did not change; its output
  routing did. The skip warning for a source file the structural parser
  cannot read used to print via the same stdout `Console` `-f json` writes
  its payload to, so `--check -f json` (and `--conformance -f json`) were
  unparsable whenever a file failed to parse. Those warnings, and the other
  messages that can precede the payload, now go to stderr in JSON mode —
  text mode is unchanged. `--conformance` always exits 0 regardless: it is a
  report, not a gate.
- **plc-code (parser, CLI)** — an expression AST alongside the statement one, and
  `plc code transpile --conformance`'s report grows an expression section to
  measure it.

  The statement parser above left every `Assignment.value`, `Branch.condition`,
  `Argument.value` and the rest as an unparsed token slice — the statement shape
  was known, but not what was inside it. `parser/expressions.py` adds eight frozen
  node types (`Literal`, `TypedLiteral`, `VariableRef`, `Member`, `Index`,
  `UnaryOp`, `BinaryOp`, `FunctionCall`) and `parser/expression_parser.py` a
  recursive-descent parser over them: the full IEC precedence chain (`OR`, `AND`,
  comparisons, `+`/`-`, `*`/`/`/`MOD`, right-associative `**`, unary `NOT`/`-`),
  typed literals (`T#5s`, `16#FF`) the lexer itself does not know how to
  recognise, and the same no-silent-loss rule as the statement parser: a
  construct the parser cannot read becomes a `ParseError`, never a guess.

  Every statement type gains a parallel `*_expr` field next to the token slice
  it is derived from (`Assignment.target_expr`, `Case.selector_expr`, ...) — no
  existing field changes name or type, which is why the executor needed no
  change and nothing generates from the tree yet; it is read-only wiring ahead
  of the code generator that will eventually consume it. Expression parse
  failures are counted in their own `expression_errors`/`expression_slices`
  channel, separate from `errors`, so an expression this toolchain cannot yet
  read does not cost the statement parser its 100% conformance — a different,
  still-in-progress grammar should not move a figure that is not about it.

  Measured over five real PLC projects (`project-A` … `project-E`): **23,279
  expression slices, all 23,279 parsed, 100.00%, zero errors** — across 649
  blocks, 439 regions and 155 networks, with token coverage exactly 1.0000 over
  178,742 tokens and every block, region and network clean.

  That measurement covers all the SCL in those projects. An earlier revision
  published 100.00% over 16,069 slices, which was every slice the pipeline could
  then see — REGION contents only. `Network.tokens` closed that hole; the rate
  went down because the population went up, and the qualifier that had to
  accompany every figure until now is gone.

  Restricted to the same population as the first measurements — SCL inside
  REGION blocks — the rate is 100.00% over 16,069 slices, from 96.30% with 594
  errors. Eight grammar gaps were closed to get there, each reported below as
  its own fix: a call whose callee is a quoted
  block name (`"ConvertAngleSafetyProcess"(...)`), a member name carrying its own
  `#` (`#armSetpoint.#angularSpeeds["SLEWING"]`), a named argument binding
  (`"PolyEval"(p := #p)`, `RD_SYS_T(OUT => #localTime)`), a structural keyword
  used as a name (`#function`, `.type`), a multi-dimensional array index
  (`#m[#i, #j]`), direct bit access (`.%X0`), the implicit enable output
  (`ENO`), and a quoted name in either name position (`."type"`, `"x" := #A`).
  Three more followed once `Network.tokens` made the rest of the SCL visible: a
  chained typed literal (`b#16#FF`), `&` written for `AND`, an absolute address
  in leading position (`%DB150.%DBX31.1`), and the lexer's folded `-`
  (`("MLA10"-1)`).

  The first two removed 331 errors, not the 469 their individual counts
  predicted, and the gap is worth recording: the counts are of error *sites
  reached*, not of independent causes. A quoted call that failed at its name
  never reached the named argument inside it, so `"ScalingAnalogicInput"(input
  := ...)` was counted once as a quoted-call error and reappeared as a
  named-argument error once the call parsed. Named arguments were therefore far
  more common than the 30 first attributed to them — 165 sites once the quoted
  calls parsed.

  The last four gaps behaved the opposite way: 76 + 12 + 7 + 2 counted, 97
  closed, exactly. Nothing was masking them, which is what the counting lesson
  above predicts once the shapes that hid the others are read.

  The one error that outlived those seven was not an expression at all, and the
  diagnosis first published here was wrong. It read:

      REGION "RCU" Default Management

  and was recorded as a nested-REGION defect. Nested REGIONs are handled and
  always were. The defect was a quoted region *name*, reported as its own fix
  below.

  Nothing in the corpus is unread. Every expression slice in every block of
  those five projects has a tree, and the statement layer accounts for every
  token.

  The lexer still folds an unspaced `-` before a digit into one `NUMBER` token
  (`#a-2` lexes as `#a`, `-2`), and it always will: the two readings are told
  apart by whether an operand precedes, which is the parser's knowledge. Two
  earlier revisions of this entry got this wrong — first claiming zero
  occurrences across the five projects (it was zero *inside REGION blocks*, the
  only SCL the measurement could then see; outside them the corpus writes 16),
  then calling the fix a lexer change. It is neither; see the split below.
- **plc-code (executor/diagnostics, CLI)** — new `plc code transpile` command and
  the `plc_code.executor.diagnostics` module behind it.

  The executor rewrites SCL as text, with no statement-level AST: anything
  `ControlFlowTranslator` does not recognise falls through to the expression
  path and is copied into the generated Python, and `transpile_block` reports
  `success=True` with zero errors and zero warnings. `REPEAT`/`UNTIL`, `GOTO`,
  `CONTINUE` and unmapped builtins (`SEL`, `LIMIT`) all reach a downstream
  project this way, surfacing as a `SyntaxError` or a `NameError` a long way
  from the SCL that caused them.

  `--check` makes that silence visible by inspecting the *generated Python*
  instead of the SCL: the module either does not parse (error — the block cannot
  load), or reads a name nothing defines (warning — `NameError` when that line
  runs). Scope analysis uses `symtable`, CPython's own resolver; the whitelist is
  derived from the new `build_runtime_globals()` that `compile_block` also execs
  into, so the check cannot drift into false positives as the runtime grows.
  `-f json` for machine consumption, exit code 1 on any finding.

  Without `--check` the command prints the generated Python, which is the
  quickest way to see what a block actually became.

  It found a real defect on its first run over the repo's own fixtures (see
  `PumpControl.s7dcl` below). The whole fixture corpus is clean now — 32 blocks,
  up from 31 because the UDT name fix below makes one more fixture countable —
  asserted by `test_diagnostics_corpus.py`, which is the no-false-positive
  guarantee, and what decides whether the command is worth running at all.
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
- **plc-code (parser, analyzer, CLI)** — the toolchain can now tell a safety block
  from a standard one, and reports where the boundary is crossed.

  `S7_Safety` was parsed nowhere: `BlockAttributes` carried author, version, family,
  optimized, editor_mode, preferred_language and two MLC fields, and nothing about
  safety, so every rule and every generated document treated an F block exactly like
  a standard one. 36 files in one delivered project carry the attribute.

  Both spellings the corpus uses are accepted — `"TRUE"` appears 20 times and
  `"True"` 16 — so the comparison is case-insensitive; a strict one would have missed
  44% of the F blocks.

  Three checks, reported by `plc code lint` in text and under `project_violations` in
  `-f json`, with the `F` prefix Siemens itself uses for fail-safe: `F001` a standard
  block calls a safety block, `F002` a safety block calls a standard block, both
  errors; `F003` declaration and path disagree, a warning because it is a heuristic.
  The path pattern is `code.quality.safety_path_pattern`, defaulting to `safety`, and
  it matches any directory in the block's path rather than the filename — Siemens keeps
  F code in a folder, while a standard block's own name routinely contains "Safety"
  because it interfaces with the safety side. Matching the filename too would have
  reported 26 blocks that are correctly standard, 14 of them in one project. Because
  any ancestor directory counts, a source root or checkout directory whose own name
  contains the pattern makes every block in the project match.

  They are not quality rules, and could not be: `Rule.check(self, block)` sees one
  block, so a cross-block check cannot reach the callee's flag. They follow the
  repository's existing shape for cross-block work instead. `ProjectAnalysisResult`
  gained `project_violations`, counted by `total_errors`, `total_warnings`,
  `total_info` and `get_violations_by_rule` so that `passed` — and, through it,
  `lint`'s exit code — reflects them; `blocks_with_errors` and `blocks_passed` still
  count blocks only. (`code.quality.fail_on_error` is a separate, pre-existing key;
  it is parsed but nothing reads it, so it is `lint`'s exit code that gates, not that
  key.) `analyze_blocks(blocks)` without the new `sources` argument behaves exactly
  as before — its signature and no-`sources` behaviour are unchanged. That is not the
  same as saying generated output is unchanged: see the UDT rename entry under Fixed
  below for what moves.

  Measured across five real PLC projects. The delivered project-A program comes out
  clean: 165 blocks, 36 carrying `S7_Safety`, and no boundary crossing of either
  kind — which is also the prediction the design committed to in advance, since all
  36 sit inside a directory matching the pattern. project-B is clean on crossings too
  (50 blocks, 23 safety) but reports 7 `F003`: six safety UDTs and one safety
  parameter DB kept in generic folders rather than under a safety tree — real
  organisational drift, and the kind of thing the check exists to surface.
  `project-E` reports the corpus's only two `F001`, and both are
  test-harness code — `Test_ArmSafetySequence` and
  `Test_ArmSafetySwitchManagement` driving safety blocks on purpose — plus 10
  `F003`: eight `Test_Safety/` harness blocks, the standard-side
  `Safety/InterfaceProcessSafety`, and one genuine drift finding in the other
  direction, `Program blocks/Parameters/ProjectSafetyParameters`, which declares
  `S7_Safety` from a generic folder just as project-B's parameter DB does.
  `project-D` carries no safety code at all, and `project-C` carries none either
  (207 blocks, zero `S7_Safety` declarations). That last figure was originally
  measured through the analyzer rather than through `lint`, because `lint` crashed
  on the whole project; the crash is fixed below and `lint` now reproduces the same
  numbers directly.

### Fixed
- **plc-code (executor)** — the production `--check` sweep, worked through: 349
  blocks with code on five projects, 264 loaded before, 335 load now. The 14 left
  are the six bare system builtins binding an `=>` output in expression position
  (refused on purpose), five bit/byte slice accesses (`#v.%X0`, now a located
  refusal instead of Python that does not parse), `RD_SYS_T`/`DTL` and one
  `DTL_TO_LDT` (system types without a runtime model).

  - A block whose TIA name is not a Python identifier — `"Main Loop"`, `"Cyclic
    interrupt"`, 35 OBs in the corpus — generated `class Main Loop:`. The class
    name (`TranspileResult.class_name`) is now `python_identifier(name)`;
    so is every variable's attribute, and a variable named `1X02-01` (a terminal
    strip's own naming, 157 references) is accepted by the expression parser as
    `#"1X02-01"` and compiles to `_1X02_01`. `FBTestHarness.set_inputs` /
    `get_output` take the SCL name.
  - A bare quoted name — a PLC tag `"DI_START"`, a tag-table constant
    `"MODE_ONE"`, a global DB passed whole — rendered as the Python string
    literal `"DI_START"`: always true in a condition, silently, and `"DO_PUMP"
    := x` did not parse. It now reads and writes `PLCRuntime.tags["DI_START"]`,
    a table a test sets directly; an unset tag reads as `UnsetTag` (false, `0`
    in arithmetic, equal to itself by name, so `#state := "MODE_TWO"` and `CASE
    #state OF "MODE_TWO":` agree with no table loaded). The scan of
    `Region.content` that guessed such names were enums and emitted them as
    integer class constants is deleted; `string_constants` is accepted and
    ignored by `render`/`generate_statements`.
  - `.#member` rendered `.self.member` and `."a.b[0]"` (a nested struct member
    TIA exports as one quoted path) rendered with its quotes — both reproduced
    bug-for-bug by the first native renderer, both Python that does not parse;
    they render as the attribute chain they name. A parameter name written
    quoted (`"x" := #a`, in expressions and call statements) no longer doubles
    its quotes. `01` (a valid SCL integer) renders as `1`.
  - Builtins the corpus uses and no map knew: `SQR`, `TRUNC`, `TIME_TO_DINT`,
    `DINT_TO_TIME`, `DINT_TO_WORD`, `INT_TO_WORD`, `WORD_TO_INT`, `BYTE_TO_SINT`,
    `BYTE_TO_INT`, `SWAP_WORD`, `BCD16_TO_INT`, `DIS_AIRT`/`EN_AIRT`. A builtin
    mapped to a `lambda` rendered without its own parentheses —
    `lambda x: x & 0xFF(self.a)`, valid Python that returns a lambda and never
    calls it — so `INT_TO_USINT`/`INT_TO_UINT` had been silently wrong; every
    lambda-valued builtin is parenthesized.
  - `R_TRIG`, `F_TRIG` (edge detectors) and `TONR` (retentive timer) are runtime
    classes beside the timers (`executor.timers`); a variable declared with a
    system type the runtime has no model for (`HW_IO`, `DTL`, `Program_Alarm`,
    `ACK_GL`) is hinted `Any` instead of a name that raises at class creation.

- **plc-code (executor)** — an FB instance call gets its `clock=` argument by the
  instance's declared type, and a bare IEC timer type (`TON`, `TOF`, `TP`) is a
  timer.

  A timer's `__call__` takes the harness clock explicitly; the generator decided
  which `#instance(...)` calls to pass it to by substrings of the instance's *name*
  (`"timer"`, `"ton"`, `"tof"`, `"tp"`). Across five production projects that rule
  missed 13 timer instances — `#delay(IN := ...)` called without a clock is a
  `TypeError` at the call — and matched FB instances that merely contained `"tp"`,
  which then received a stray `clock` keyword that a generated FB's
  `__call__(**kwargs)` stores as an attribute without complaint. The transpiler now
  hands the generator the names of the block's own variables declared with a timer
  type (`generate_statements(..., timer_instances=...)`), and the name heuristic is
  gone. A global-DB member callee (`"db".TON(...)`), which has no declaration in
  reach, counts as a timer only when its member name is exactly an IEC timer type
  name; an indexed callee never does.

  Separately, a variable declared as `TON` (12 such in the corpus, against 34
  `TON_TIME`) was not a timer at all to the transpiler — only the `*_TIME` spellings
  were — so it became an `_AutoStruct` that the generated call then could not call.
  `executor.timers.TIMER_TYPE_NAMES` is now the single table of IEC timer spellings,
  shared by the type mapper, the transpiler and the generator.
- **workspace (tests)** — `uv run pytest packages/plc-code` (or any single package
  run from its own directory) aborted collection with `import file mismatch` on
  `test_models.py`: four test files share that basename across packages, and only
  the workspace root's `pytest` options asked for `--import-mode=importlib`. Every
  package's `addopts` now carries it too.
- **plc-code (executor)** — a positional argument to a named-block call is bound to
  the callee's declared parameter, read from the project sources; it was silently
  dropped.

  SCL lets a FUNCTION be called positionally — `"Scaling"(#raw, 2.0)` — and binds each
  value to the block's interface in declaration order. The translator only ever handled `name := value` and skipped everything else, so
  such a call reached the runtime with an empty input dictionary and the callee ran on
  its defaults, with nothing reported. Five production projects hold 97 such calls in
  3 blocks, every one of them wrong in this way until now.

  The runtime already resolves a block by name to read its kind (`PLCRuntime.block_kind`,
  the `fb_type_resolver` hook); the new `PLCRuntime.block_signature` resolves the same
  file for the names positional arguments bind to, and reaches the transpiler as a
  `signature_resolver` callable (`transpile_block`, `compile_block`, `check_block`,
  `generate_statements`, `render`), threaded alongside `string_constants`. It offers
  the `VAR_INPUT` names in order, followed by the `VAR_IN_OUT` names only when the
  block declares no `VAR_OUTPUT` — the one case where their positional order is
  beyond doubt; a block with outputs offers its inputs alone, and a call reaching
  past them is refused rather than bound on an assumption about how TIA orders the
  rest. Where a binding would otherwise be a guess — no resolver, a block that cannot
  be found or parsed, or a positional argument that collides (case-insensitively,
  as SCL compares names) with a named one in the same call — the transpile fails
  with a message naming the block and the reason (`executor/arguments.py`). On the
  corpus every one of the 97 calls in the 3 blocks now binds; no block gained a
  failure.

  `plc code transpile` builds a resolver over the tree it was given, in both modes:
  `--check` binds what the harness binds, and the plain emit mode — which used to
  print the code of a failed transpile without a word — now says so on stderr (the
  exit code stays 0; emitting is for reading the output, not judging it). The
  runtime's block lookup, shared by `block_kind`, `block_signature` and
  `call_named_block`, used to look one directory level below each search path; it
  now indexes each search path once, recursively, since a callee may sit several
  folders away from its caller.

  A positional argument to an `#instance(...)` FB call raises rather than binding:
  the instance's FB type is not resolvable from inside the caller. The corpus has no
  such call. Builtins (`ABS(#x)`, `SQRT(#x)`) are positional by nature and unchanged.

- **plc-code (parser)** — two SCL constructs the expression grammar did not read.

  A call whose callee is a quoted block name — `"ConvertAngleSafetyProcess"(#x)` —
  parsed the quoted name as a variable and then choked on the `(`. A member name
  carrying its own `#` — `#armSetpoint.#angularSpeeds["SLEWING"]` — was rejected
  because a bare identifier was expected after the dot. Between them they
  accounted for 469 of the 594 expression errors in the corpus.

  Both are recorded rather than flattened, because a consumer that cannot tell
  the forms apart cannot render either one back: `FunctionCall.is_quoted` is
  True when the callee was written `"Name"(...)`, and `Member.is_local` is True
  when the member was written `.#name`, following `VariableRef.is_local` where
  `#` already means local. Both fields are additive with defaults, so no
  existing consumer changes.

  Measured: 96.30% to **98.36%**, 594 errors down to 263. That is 331 closed,
  not the 469 predicted — see the expression-AST entry above for why the two
  counts were not independent.

- **plc-code (parser)** — a call inside an expression could not bind its
  arguments by name, which is how SCL calls most blocks.

      #fl := "PolyEval"(p := #p, n := #n, x := #ll);
      #returnCode := RD_SYS_T(OUT => #localTime);

  The parameter name is a bare identifier, not a valid expression on its own, so
  the argument failed at its own name — before the `:=` was ever reached. 165 of
  the 263 remaining expression errors were this one shape.

  `FunctionCall.arguments` is now a list of `CallArgument`, wrapping positional
  arguments too so a consumer walks one list of one type in source order.
  `is_output` keeps `=>` distinct from `:=`: an output binding names a
  destination the call writes to, and a translator that collapses the two drops
  the write — the same defect already recorded for statement-level calls.

  Measured: 98.36% to **99.39%**, 263 errors down to 98. No new error class
  appeared behind the closed one; the 98 that remain are the four gaps listed in
  the expression-AST entry above.

- **plc-code (parser)** — the last four expression shapes the grammar refused,
  all of them ordinary SCL: 97 of the 98 remaining errors.

  **A structural keyword used as a name** (76 sites) — `AND #function =
  "RCU_FUNCTION_HPU"`, `#params["SLEWING_AXIS"].type = 'coder'`. `FUNCTION` and
  `TYPE` are two of the lexer's 25 keywords, and all 25 are block and
  declaration structure, so none can legitimately appear inside a REGION body: a
  token of one of those types in a name position is unambiguously a name.
  Widened in the parser, at the two positions that ask for a name — after `#`
  and after `.` — and not in the lexer, which also feeds `Region.content`. A
  bare keyword in expression position stays the error it was.

  **A multi-dimensional array index** (12) — `#matrixResult[#tempCounterRows,
  #tempCounterColumns]`. `Index.index` becomes `Index.indices`, a list;
  one-dimensional access is a list of one. `base[]` and `base[i,]` stay errors.

  **Direct bit, byte and word access** (7 reached, 77 written in the corpus) —
  `"QuayData".rcu.input.statusByte.%X0`, `#tempSwapValue.%B0`, `"Data".%DBX0.0`.
  The lexer has no token for `%`, so the selector arrives as UNKNOWN('%')
  followed by a name and only adjacency separates it from a stray character;
  `.% X0` stays an error. `Member.is_absolute` records that the `%` was written.
  A numeric member is accepted too: `#word.0` is bit 0 without the prefix.

  **The implicit enable output** (2) — `ENO := TRUE;`. An allow-list of exactly
  one name. The bare-identifier error is what catches every construct the
  grammar cannot read, so widening it past what SCL itself defines would empty
  the grammar of its ability to refuse.

  Measured: 99.39% to **99.99%**, 98 errors down to 1. The statement layer is
  unchanged at 100% token coverage over 649 blocks, every block and region
  clean.

- **plc-code (parser)** — a quoted REGION name stopped at its closing quote, and
  the rest of the header line was read as code.

      REGION "RCU" Default Management
          #InstRcuAlarmManagement(rcuRawInput := #rcuRawInput, ...);
      END_REGION

  The name came out `RCU`, and `Default Management` stayed in the region's
  `content` and `tokens` — so the transpiler, which reads `content`, was handed
  two words of prose as the first statement of the region. A bare name already
  scanned to the end of the line (`REGION Set 7 phases`); only the quoted
  spelling stopped early. Both now run the same scan, and the quotes are
  stripped from whichever part carries them: the name is `RCU Default
  Management`.

  This was previously recorded, here and in a commit message, as a nested-REGION
  defect. That was wrong: `_parse_region` recurses into a nested REGION and
  flattens its tokens into the parent, and always did. One region in the whole
  corpus is written with a quoted name, and it was the one that failed.

  With it, the corpus measures **16,069 expression slices, all parsed, 100.00%,
  zero errors** — across 649 blocks with token coverage 1.0000 and every block
  and region clean. That figure still covers only the SCL inside REGION blocks;
  see the qualifier in the expression-AST entry above.

- **plc-code (parser)** — a name may be quoted wherever a name is expected, in
  both positions that ask for one. An earlier revision denied this in writing
  and in a test.

      #phase := "Atan2"("x" := #A, y := #B);
      "QuayParameters".quayParam.armParams[0].cpmsSensorParams[0]."type" := ...

  Quoting is TIA Portal's second spelling for a name the lexer reserves — the
  first being the bare `#function` / `.type` already read. The member form
  appears 80 times in the corpus; the parameter form twice, and in the same call
  as a bare neighbour, which is what makes it unmistakably a spelling and not a
  different construct.

  The commit that added named arguments asserted "SCL parameter names are bare
  identifiers" and shipped `test_a_quoted_parameter_name_is_not_a_binding` to
  prove it. Both were wrong; the test is replaced by its opposite. Only the
  lookahead decides: without `:=` or `=>` behind it, a quoted token in an
  argument is an ordinary global read, and that case is now covered by its own
  test.

  `Member.is_quoted` and `CallArgument.is_quoted_name` record the spelling, as
  `is_local`, `is_absolute` and `FunctionCall.is_quoted` already do.

  Measured: inside REGION blocks the corpus stays at 100.00%. The shapes this
  fixes live almost entirely outside them, where a throwaway probe of what
  `Network.tokens` would yield reads 98.59% to **98.75%**, 102 errors down to 90.
  Only 12 of the 82 sites closed, and the reason is the counting lesson again:
  most `."type"` lines also carry `armParams[#arm_index-1]`, which fails first.
  They will not count until the lexer's `-` folding is fixed.

- **plc-code (parser, CLI)** — a `Network` now carries its tokens, so SCL
  written outside any `REGION` reaches the statement parser at all.

  `Region.tokens` was added because `Region.content` is a lossy
  re-serialisation. SCL that sits directly inside a `NETWORK` had no
  equivalent: it reached `Network.content` as the same lossy string and its
  tokens were dropped on the floor. 168 of 649 blocks in five production
  projects are written that way — 52,288 tokens, 29% of the corpus SCL — and
  none of it could be measured, parsed, or checked.

  `Network.tokens` is the same additive pair `Region` already carries.
  `Network.content` is unchanged, byte for byte, verified across the fixture
  corpus and locked by a test beside the one that locks `Region.content`.
  Comments and newlines stay out of the tokens, matching `Region.tokens`, and a
  REGION's own tokens stay with that REGION, so a caller may walk both without
  counting one twice. A LADDER network collects nothing: RUNG elements are read
  by their own branch.

  `build_report` gains a network pass, with `networks` / `clean_networks` /
  `network_clean_rate` reported separately — a network is not a region, and
  folding them would misreport both. Token, statement and expression totals
  cover both populations, and `plc code transpile --conformance` prints the new
  counts in both formats.

  What this changes about every figure this project has published: they all
  silently meant "of the SCL inside REGION blocks". Now they mean all of it.
  The statement layer needed no work to earn it — **155 of 155 networks parse
  with zero errors**, token coverage stays exactly 1.0000 over 178,742 tokens,
  and every block stays clean. Only the expression rate moves, 100.00% over
  16,069 slices to **99.61% over 23,279**, because 90 errors that were always
  there became visible.

- **plc-code (parser)** — the three shapes `Network.tokens` made visible and the
  grammar had no branch for. 74 of the 90 remaining expression errors.

  **A typed literal with chained prefixes** (51) — `b#16#FF` is byte,
  hexadecimal, FF. The value run stopped at the second `#`, leaving `#FF`
  trailing. It now crosses a `#` as well, but only one adjacent on both sides,
  so `16#FF + #a` still reads as a literal plus a local. `TypedLiteral` is
  unchanged: its `value` is already what follows the first `#`, as written.

  **`&` written for `AND`** (13) — `IF "ESD".ESD1[#b] & "PMS".mla_valid[#b] AND
  (...)`. It joins the AND precedence level as its own spelling, not an alias:
  `BinaryOp.operator` reads `"&"` where `&` was written, the way `<>` and `<=`
  keep theirs.

  **An absolute address in leading position** (10 reached, 211 written) —
  `%DB150.%DBX31.1`, `%I0.0`. `VariableRef.is_absolute` follows
  `Member.is_absolute`, which already marks the same `%` mid-chain; everything
  after it is folded in by `_parse_postfix` as for any primary.

  Neither `&` nor `%` has a token of its own, so both arrive as `UNKNOWN` and
  are recognised by value and adjacency — never by token type, which is the
  lexer's catch-all and would match anything.

  Measured: **99.61% to 99.93%**, 90 errors down to 16, exactly the 74 counted.
  Nothing was masking these three, and every error left is the lexer's `-` fold.

- **plc-code (parser)** — an unspaced `-` before a digit, which the lexer folds
  into the number. The last 16 expression errors in the corpus.

      FOR #page := "MLA1" TO ("MLA10"-1) DO
      "QuayParameters".quayParam.armParams[#arm_index-1].cpmsSensorParams[...]

  `#a-1` lexes as `IDENTIFIER:'a' NUMBER:'-1'`, and so does `#a -1`: the fold
  ignores spacing. It cannot be corrected in the lexer, because the lexer cannot
  know which reading applies — `f(#a, -1)` passes a negative literal, `f(#a -1)`
  passes a subtraction, and only whether an operand precedes tells them apart.
  That is the parser's knowledge.

  So the split happens in `_binary_level`, at the additive precedence level
  only, and only when the operator lookup has already failed — which by
  construction is after a left operand was read. Everywhere else the folded
  token reaches `_parse_primary` and stays the negative literal it is:
  `#arr[-1]`, `#a * -1`, `"CONV".IN[#b] <> -32768`, `(-1)` are all unchanged.

  The recovered number re-enters the chain one level up rather than being used
  as the right operand directly, so `#a-1*2` binds `1*2` exactly as the spaced
  `#a - 1 * 2` does. One token still yields both the operator and the operand,
  so the consumption invariant holds untouched.

  No lexer change, therefore no change to `Region.content` or
  `Network.content`, which 27 rules and the transpiler read byte for byte.

  Measured: **99.93% to 100.00%**, 16 errors down to zero. With it the corpus
  is fully read: 23,279 expression slices all parsed, 178,742 tokens all
  accounted for, 649 blocks, 439 regions and 155 networks clean.

- **plc-code (parser)** — an argument value containing parentheses ended at the
  wrong one, desynchronising the rest of the call.

  `_take_until(COMMA, RPAREN)` delimited each argument's value without counting
  parenthesis depth, so on

      #block(CLK := (#state = #RUNNING), Q => #out);

  the value stopped at the paren closing `(#state = #RUNNING)`, the argument list
  ended there, and every token after it was read as a fresh statement — reporting
  "an assignment or a call" at `,`, `Q`, `=`, `>` and on into the following lines.

  One missing counter accounted for **45 of the 51** conformance errors left from
  the statement parser's first release, spread over three blocks and presenting as
  four unrelated causes: a parenthesised argument value, a nested call as a value,
  a multi-line boolean value, and an `=>` binding that appeared unsupported but
  never was. The remaining 6 came from a single `+=`, which the lexer emits as `+`
  then `=` with nothing composing them; it now desugars to `#i := #i + #n` in the
  parser, so no consumer of `Assignment` changes and the generator will need no
  special case.

  Measured across the five production projects after the fix: **648 blocks,
  100.00% clean, zero errors, zero silent loss, token coverage exactly 1.0000** —
  from 99.96% with 51 errors.

  Adjacency composition gained a public owner in the process.
  `composite_operator(left, right)` joins `TokenStream.peek_operator`, which only
  covers the cursor; the alternative was importing the private table across
  modules, contradicting the docstring that says `TokenStream` owns it.
- **plc-code (CLI)** — `plc code trace -f json` emitted an unparseable document.

  Its status line, its per-file parse warnings and, on failure, a full traceback
  all went to the same stdout the JSON payload is written to, so any project with
  one unreadable block produced output `json.load` rejected at character 0 —
  silently, since the command still exited 0. `lint` and `transpile --check` had
  the same defect and were fixed the same way; this is the third and last
  instance. Diagnostics now go to stderr in JSON mode, `traceback.print_exc` with
  them; text mode is unchanged and still prints everything to one stream.
- **plc-code (CLI)** — `code.quality.fail_on_error` had no consumer.

  The key was parsed into `QualityConfig`, documented in `CLAUDE.md`, written into
  the generated `plc.yaml` template, and set to `false` by the bundled example
  project with the comment "Report findings without failing the example" — while
  `lint` ended in an unconditional `SystemExit(0 if result.passed else 1)` and
  read it nowhere. The configuration surface promised something the tool did not
  do. `lint` now honours it: findings are reported either way, and the exit code
  is 0 when the key is false. As with `safety_path_pattern`, only a discovered
  `plc.yaml` can soften the gate — `lint <path>` reads no configuration at all and
  keeps the strict default.
- **plc-code (parser)** — `plc code lint` crashed on a whole project when a rung
  comment happened to look like a number.

  `.s7res` resource files are YAML, so an unquoted comment is parsed as whatever
  scalar it resembles: `40021` as an `int`, `1.5` as a `float`, `ON` as a `bool`,
  a bare date as a `datetime.date`, an empty value as `None`.
  `MultiLingualText.text` is annotated `str`, but a dataclass does not enforce
  that at runtime, so the wrong type flowed through untouched until the first
  string operation on it. One real project comments its rungs with Modbus
  holding-register numbers — 24 of them in a single file — and the whole project
  died with `AttributeError: 'int' object has no attribute 'lower'` at
  `extractor/header.py:169`, reached from the `D`-category documentation rule.
  A single unparseable comment took down every rule on all 207 blocks.

  `parse_resource_file` now coerces the value, which is the only place a
  `MultiLingualText` is constructed and therefore the only place the annotation
  can be guaranteed. That also fixes two silent cases the crash was hiding:
  `extract_interface` assigns the same value into a variable's and a UDT field's
  `description`, so a numeric comment used to reach generated documentation as an
  `int`.

  `plc code lint` now completes on that project — 207 blocks, valid `-f json`
  output — and the other four projects report identical figures to before.
- **plc-code (executor/control_flow)** — two CASE layouts were mistranslated,
  both silently, from one root cause: the label regex required the label to
  occupy its whole line *and* end with a colon.
  - SCL's default branch is a bare `ELSE` with **no** colon, so only `ELSE:` —
    a spelling that does not occur — ever matched. The keyword was collected as
    a body line of the *preceding* branch, which put the default body inside
    that branch and leaked the word `ELSE` into the generated Python as an
    undefined name. Found in production: project-A `UserMode.s7dcl`, whose
    user-mode state machine had its fallback folded into the `activeState == 2`
    case.
  - `1: #b := 10;` (statement on the label's line) matched nothing, so
    `current_values` stayed empty and the `if current_values and body_lines`
    guard dropped **the entire CASE**. `execute()` did nothing, with no
    diagnostic to show for it — the generated Python is valid, just empty.

  Comma-separated *quoted* labels (`"A", "B":`, real: project-A
  `ArmFinalState.s7dcl`) are deliberately still not matched: making the label
  regex accept them without teaching `_collect_string_constants` about the list
  emits a branch with unresolved conditions that is then dropped, trading a
  visible failure for a silent one. Left visible and covered by a strict
  `xfail`.

  Note for anyone reading the `transpile --check` numbers: this fix makes them
  look worse. Blocks whose CASE was previously dropped whole now emit their real
  code, and that code meets other, pre-existing gaps. Across five PLC projects
  the clean count went 510 -> 504 and syntax findings 92 -> 99. Every one of
  those blocks used to do nothing at all.
- **examples, plc-code fixtures** — `PumpControl.s7dcl` did not run. It declares
  `PROC_READY` in a `VAR CONSTANT` section and read it once without the `#`
  prefix (`IF #processState = PROC_READY THEN`), while its two other uses of the
  same constant are `#PROC_READY`. `VAR CONSTANT` members are generated as
  instance attributes, so the prefixed form resolves to `self.PROC_READY` while
  the bare one was left as a module global nothing defines. That line is the
  first transition of the initial `IDLE` state, so `execute()` raised
  `NameError` on cycle one — in the demo project shipped under `examples/`.

  Nothing executed the fixture (42 test references, all parsing, docs, draw.io
  and discovery), which is why it survived. Found by `plc code transpile --check`
  on its first run. Fixed in both copies; the block now runs and transitions
  `IDLE -> PRIMING` as intended.

  A sweep of 624 blocks across five real PLC projects found no other bare
  constant reference, confirming this as a typo in a hand-written demo rather
  than an SCL form the transpiler needs to support.
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
- **plc-code (parser)** — a UDT declared with a leading pragma lost its name.
  `_parse_udt` read the type name by expecting an `IDENTIFIER` at the cursor, but the
  token stream is `TYPE`, `PRAGMA_START`, `PRAGMA_CONTENT`, `PRAGMA_END`,
  `IDENTIFIER` — the pragma sat before the name and blocked it, leaving both
  `Block.name` and `UserDataType.name` empty. Reading `S7_Safety` there required
  consuming the pragma, which fixes the name as a direct consequence.

  This is a behaviour change rather than an addition: **24 production UDTs gain a
  name they did not have** — project-A 15, project-B 6, project-E 3 — which
  changes what any consumer of UDT names produces. No shipped fixture exercised a
  pragma before a type name, which is why nothing caught it; one has been added.

  A project regenerating docs after this fix will see generated output move, not
  just this changelog. Measured by blanking only the 24 pragma-first UDT names:
  `type-prefix` (N002) drops by exactly 24 — project-B 6→0, project-A 15→0,
  project-E 10→7 — taking project-A's `total_warnings` from 352 to 337; and
  the type graph changes shape, project-A going from 154 to 165 nodes, 49 to 71 edges,
  and 4 to 5 connected components with edges, so `type-graph-{N}.md` changes in
  page count and content. Both changes are improvements — the old N002 warnings
  were artifacts of this same parser bug, flagged against a name that had been
  mis-parsed — but an engineer regenerating a project's docs must not be told
  nothing moves.

  One UDT still parses with an empty name: project-C's `16bits.s7dcl` declares
  `TYPE "16bits" : STRUCT`, a quoted-string type name (Siemens identifiers cannot
  start with a digit) rather than a plain `IDENTIFIER`. `_parse_udt` does not
  handle that form; it is a separate, pre-existing gap and is left alone here.

### Changed
- **plc-code (executor)** — three things a harness user may have leaned on, gone
  with the sweep fixes above: a quoted enum-like name no longer becomes an
  integer class constant (`instance.MODE_ONE` raises `AttributeError`; the value
  is `runtime.tags["MODE_ONE"]`, an `UnsetTag` until set — so a `CASE` whose
  selector holds a real integer no longer matches a symbolic label unless the tag
  is set to that integer); `TranspileResult.class_name` is the Python class name,
  not the block name; `FBTestHarness.get_outputs()` and `call_named_block`'s
  result are keyed by the SCL name as declared (`"Out Value"`), which only differs
  from before for names that are not identifiers. A block declaring two names that
  compile to one attribute (`a-b` and `a_b`) is refused with a located problem.

- **plc-code (analyzer)** — the cross-block tracers (`field_tracer`,
  `forward_tracer`, `chain_builder`, `state_detector`, `tag_assignment`) read the
  shared SCL and ladder ASTs through one access index; their regexes over the
  block's re-spaced text are gone.

  Every one of them asked the same question of a block — where is this path
  read, where written, by what, inside which call — and answered it with its own
  patterns over `Region.content`, the rendering in which `<=` is `< =` and a global
  path may be `"DB" . a . b`. The new `logic_dependency.access_index` answers it
  once per block: one `Access` record per read or write of a path, with the line,
  the statement as written (`parser.scl_text`, a printer for the expression AST
  that round-trips 23 303 of the 23 305 corpus expressions exactly and the other
  two up to a literal `-1` vs `- 1`), what a write reads, and for a parameter
  binding the whole call (`CallContext`: callee, instance, parameter, direction,
  every input and output). SCL comes from `parse_statements`; LAD from
  `build_ladder_program`, falling back to one element at a time when the rung
  builder refuses a network (a bare instance name in a rung), with the refusal
  recorded. What cannot be read lands in `BlockAccessIndex.parse_errors`, which
  `plc code drawio` prints.

  Measured against the old tracers on four production projects with tag tables
  (487 I/O tags): every dependency chain is identical, node for node. Building
  them took 547 s on the largest project and takes 27 s. Where the tag and
  state-variable maps differ, the old walk was wrong: it read assignments out of
  commented code (`// "DB".x := "AI_..."`, 19 tags on one project), missed every
  global field spelled with spaces (its pattern allowed none, so `"DB" . status .
  x` was never a state field), and matched `CASE` selectors only when spelled
  `#name`. The public functions keep their signatures; `FieldAccess` gains `call`
  and `element`.

- **plc-code (analyzer)** — `analyzer.logic_dependency` reads the shared statement
  and expression AST; its private regex lexer and recursive-descent expression
  parser (597 lines) are deleted, and the extractor's own regex walk over
  `Region.content` with it.

  The private parser knew neither arithmetic nor indexing and tolerated unread
  trailing tokens, so `#a + #b` was read as `#a` and `#b` vanished from the graph.
  The text walk it sat on read a re-spaced rendering of the source in which `<=`
  had become `< =` and `T#0s` `T # 0 s`, captured several statements as one
  "expression" and parsed its first token, took the last `#name` before `:=` as
  the target (so `#status.#inner := ...` was an assignment to `inner`), read
  assignments out of commented code, and skipped anything it could not parse
  without a word. Measured on five production projects (349 blocks with code):
  it found 3 086 assignments; the AST walk finds 9 344. Of the 1 438 (target,
  dependency) pairs the old walk reported, every one of the 107 it alone reported
  was its own mistake — 48 mis-read `.#member` targets, 44 from commented code, 15
  garbage targets spanning statements. Nothing real is lost; 2 195 targets gain
  dependencies they always had.

  What is new in the result: a call statement's `=>` output is an assignment that
  depends on the callee and every input argument (`#tmr(IN := #a, Q => #q)` makes
  `q` depend on `tmr` and `a`; `=>` is not `:=`, so the text walk never saw
  these); a `FOR` loop's variable is assigned from its bounds; an index expression
  is a dependency of the indexed access (`OperatorType.INDEX`), and arithmetic
  keeps every operand (`OperatorType.ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE`,
  `MODULO`, `POWER`, `NEGATE`, all with Mermaid gate labels); a `CASE` arm depends
  on the selector and a `WHILE` body on its condition. A member path is typed by
  its root variable when the path itself is not declared, so a member of an input
  struct is an input rather than `UNKNOWN`; a bare quoted symbol (`"Clock_1Hz"`) is
  a global, named with its quotes, rather than a constant that could collide with
  a block variable; a computed index is `*` on both the read and the write side,
  so `#arr[#i]` and `#arr[#i + 1]` join on one name. Source lines are the file's
  own, not a region-relative count. What the parser refuses is recorded in the
  new `BlockDependencies.parse_errors`, printed by `plc code trace` and returned by
  the web API (zero on the corpus). The `ExpressionParser(text)` /
  `parse_expression(text)` API is kept and gains `ExpressionParser.convert(tree)`
  and `reference_text(tree)`.

  Keeping every operand exposed a pre-existing cost: `graph_builder` re-expanded a
  shared state variable once per path through the tree, and the Mermaid generator
  keyed its node cache on `id()` of a fresh tuple so it never hit. One production
  output went from a 442-byte diagram to 1.9 MB before the fix; a state variable's
  expansion is now computed once and shared, and a shared subtree is drawn once.
  The largest diagram on the corpus is 20 kB.

- **plc-code (executor)** — `TranspileResult` carries its failures as
  `problems: list[TranspileProblem]` (message plus SCL `source_line`), replacing the
  two parallel lists `errors` and `error_lines` that were aligned by convention
  only. `TranspileResult.errors` remains as a read-only property yielding the
  messages, so callers that only print them are unchanged.
- **plc-code (executor, CLI)** — `Diagnostic.line` now means one thing: a line in
  the generated Python. It used to mean that for `SYNTAX` and `UNDEFINED_NAME` and
  an SCL source line for `TRANSPILE`, with the reader expected to know which. The
  SCL line lives in the new `Diagnostic.source_line` (and `"source_line"` in
  `plc code transpile --check -f json`; `"line"` is `null` for `TRANSPILE`). Text
  mode now shows `(SCL line N)` for a `TRANSPILE` finding whose message does not
  already state its line — the renderer's own refusals did not, and were reported
  with no location at all.

- **plc-code (executor)** — `plc code transpile` (and therefore `compile_block`,
  and every downstream test harness) now generates Python from the statement AST
  (`plc_code.parser.statement_parser` / `plc_code.executor.generator`) instead of
  from `ControlFlowTranslator`, which rewrote a region's flattened text with
  regular expressions. `ControlFlowTranslator` and its differential harness are
  deleted; `generate_statements` gained a `string_constants` parameter that folds
  in the CASE-label / symbolic-constant substitution the old path did as a
  separate text-rewrite-then-repair pass.

  A corpus sweep over 646 real production blocks found 45 diverging code units
  between the two paths, classified into seven root causes — every one a bug in
  the deleted text path, never a case where the AST path disagreed and was wrong:
  a `CASE`'s leading branch dropped, comment text dropped or mis-scanned, a whole
  `IF` lost, a compound assignment garbled, dead code inside a malformed comment
  executed as if it were live, a trailing no-op `ELSE` elided, and nested
  fragments left untranslated. Expression rendering itself
  (`ExpressionTranslator`) is unchanged by this switch and shared by both the old
  and new statement layers; only how a statement reaches it changed.

  This is also a behaviour change beyond fixing those 45 units: a block whose
  tokens the statement parser cannot read now fails transpilation — a located
  error is appended and `TranspileResult.success` is `False` — instead of the old
  path copying the unrecognised construct verbatim into the generated Python and
  reporting success. There is no fallback to the old path for such a block.

  Measured, not estimated: this commit deletes 2,528 lines (`control_flow.py`'s
  1,113; its three direct unit-test files, 1,166; the two differential test
  files, 150; and the differential fixtures in `conftest.py`, 99) and 67 lines
  referencing the `re` module (`grep -c "re\."`: 58 in `control_flow.py`, 9 in
  the deleted text-substitution-then-repair block `_translate_scl_code` used to
  run).

  A follow-up review found two gaps in that same "must say so, not silently
  emit something else" guarantee, both closed here. First, `generate_statements`
  unconditionally emitted a header line for every `IF`/`ELSIF` branch, `FOR`,
  `WHILE` and `CASE` arm, then spliced in that construct's body — but never
  checked whether the body it generated was empty. A comment-only branch (an
  ordinary shape in real SCL, since comment tokens never reach the statement
  parser) therefore produced a header with nothing indented under it: `success`
  was `True` and the generated module still failed to compile. All six emission
  sites — the five construct shapes, `CASE` contributing both an arm and its
  default — now emit `pass` when their body generates zero lines. Second,
  `ParseResult.unattributed_spans` — a token a body loop's last-resort recovery
  swallows without recording it as a statement, error or separator, such as a
  stray `END_WHILE` nested inside a `CASE` branch — was produced by the parser
  but never checked by the transpiler, so that class of loss also reported
  `success=True` with no diagnostic. `_translate_scl_code` now fails
  transpilation on a non-empty `unattributed_spans` too, via the existing
  `verify_no_silent_loss`, rather than a second hand-rolled check. Also fixed in
  the same pass: a `TRANSPILE` diagnostic's message doubled its own location
  (e.g. `<Block>: line 8 column 13: line 8, column 13: unexpected 'REPEAT'`) —
  the redundant prefix is gone — and `Diagnostic.line` is now populated for
  `TRANSPILE` findings (from the new `TranspileResult.error_lines`) instead of
  always `None`, so a JSON consumer gets the location as data rather than only
  inside the message text.
- **plc-code (executor)** — `plc code transpile` now generates Python natively from
  the parsed AST for expressions too, not just statements. `ExpressionTranslator`'s
  twelve ordered regex passes (string-literal and named-call placeholder protection,
  hex/duration-literal translation, global-DB substitution, operator and builtin
  rewriting, boolean and multi-index rewriting) and the statement dispatcher built on
  top of it (`translate_simple_statement`, `translate_assignment`,
  `translate_if_condition`, `translate_fb_call`, and their named-call helpers) are
  gone. Two producers survive as pure formatters — `ExpressionTranslator._build_named_call`
  and `StatementTranslator._emit_named_call`, which turn an already-rendered
  `"Block"(...)` call's arguments into the runtime's `call_named_block(...)` call and
  output-assignment lines — receiving every argument pre-rendered from the tree;
  nothing left in the executor still constructs Python by rewriting SCL text.

  Measured, not estimated (`git show 02de048:<path> | wc -l` against `wc -l <path>`
  at the tip of this branch; `02de048` is this branch's own point of divergence from
  `main`, the one base both figures below are measured against): `codegen.py` goes
  from 1,058 lines to 225 (966 deleted, 133 added — the survivors' own docstrings).
  `generator.py` *grows*, from 270 lines to 855 (711 added, 126 deleted): most of
  this branch's earlier work moved statement-level rendering (`Assignment`,
  `If`/`For`/`While`/`Case` headers, `Call`/`Return`/`Exit`) natively into this
  module, one function per shape, where it used to live in the dispatcher this
  change deletes — `generator.py` was never the file being emptied, `codegen.py`
  and the dispatcher were. `codegen.py`'s 38 `re.` module calls, and its only
  `import re`, are gone; `generator.py` never called `re` directly at either end of
  this range. Five test files are deleted outright: the expression-level and
  unit-level differentials (177 and 623 lines) and three unit-test files whose only
  subject was the deleted text machinery (`test_codegen.py` 169,
  `test_normalize_spacing_quoting.py` 107, `test_generator_reconstruction.py` 35) —
  1,111 lines of tests.

  Two corpus-wide differentials proved the tree-driven renderer and generator
  equivalent to the deleted text machinery before any of it was removed: the
  expression differential over 23,305 slices (647 blocks) and the unit-level
  statement differential over 594 units of the same 647 blocks, both run to zero
  *unattributed* divergence. (23,305 is this task's own measurement, the day it ran;
  an earlier entry in this same series reported 23,279 for the same differential —
  both were true when measured, since the external reference corpus is regenerated
  by its owner and had grown between the two measurements.)

  Every remaining divergence was one of five named, deliberate exceptions where the
  **old** path was itself wrong, not a difference the
  new path introduced: a bare (unquoted) call binding a parameter by name, where the
  old path mangled `:=` to `==` via `OPERATOR_MAP`; a global DB name containing a
  character the old `GLOBAL_DB_PATTERN` regex's `\w+` requirement could not match; the
  acknowledged `NOT`-prefix bug (`#notReady` read as `self.not Ready`); a chained
  typed literal under a size prefix (e.g. `B#16#FF`); and a call whose parameter list
  the old path truncated at a nested `)` inside a grouped sub-expression or a string
  literal argument. `Grouping` was added to the expression AST during this same
  effort so a parenthesised sub-expression's own parentheses survive rendering.

  Six silent-loss defects the old translator carried are found across this effort and
  are now either impossible or converted into a loud failure: `#notReady` read as
  `self.not Ready`, invalid Python; `b#16#FF` translated to `bself.0xff`, and an
  assignment of it became a comparison (`self.a == bself.0xff`), also invalid; the
  expression parser took 177 single-quoted string literals in the corpus for variable
  references before a node-type fix separated a string `Literal` from a quoted-name
  `VariableRef`; a bare system builtin's `=>` output binding, translated as a
  standalone expression, read `OUT => #x` as `OUT == > self.x`, invalid; an FB call's
  parameter list truncated at a nested `)`, silently dropping every argument after
  it; and an indexed-callee FB call's `:=` mangled to `==` — for the shape with no
  output binding, the only one of the six whose output actually compiled, calling the
  FB instance positionally with a boolean instead of by keyword.

  A seventh defect — a positional argument to an `#instance(...)` FB call silently
  dropped (`#tmr(#x, #y)` rendered as `self.tmr()`) — was first reproduced
  bug-for-bug and is now fixed; see the positional-argument entry under *Fixed*.
  The same kind of pre-existing bug, reproduced beside it:
  a quoted-block call's own parameter name written itself quoted (`"x" := #a`) renders
  with doubled quotes (`{""x"": self.a}`, not valid Python) rather than the one pair a
  reader would expect. Pinned as an intentional reproduction, not a defect this pass
  introduced, by its own test (`test_renderer_calls.py`).

  A related, eighth shape is a deliberate behaviour change, not a defect found:
  an assignment whose right-hand side is a bare (unquoted) system builtin binding an
  `=>` output — 6 `GET_DIAG`, 2 `RD_SYS_T`, 2 `DPRD_DAT`, 1 `RH_CTRL`, 1 `Serialize`
  in the corpus — used to reach the old dispatcher and leave a bare `=>` in the
  generated Python (e.g. `self.x = RD_SYS_T ( OUT => self.x )`), a `SyntaxError` at
  class-definition time. There is no correct Python for this shape — a positional
  call has nowhere to route an output binding — so it now fails the transpile loudly
  instead: `TranspileResult.success` is `False`, with a message naming the call and
  the bound parameter, and `error_lines` carrying the SCL source line it was raised
  at (`renderer.UnsupportedExpression`/`generator.UnsupportedStatement` both now
  carry their own line through `SCLTranspiler.transpile`'s top-level exception
  handler, which used to report `None` for every raised exception alike).
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

### Removed
- **plc-code (executor)** — `translate_expression`, `translate_assignment` and
  `translate_fb_call` are gone from `plc_code.executor`'s public API (module-level
  wrappers around the deleted `ExpressionTranslator.translate` /
  `StatementTranslator.translate_assignment` / `.translate_fb_call`, removed in the
  same commit as their underlying methods, above). `ExpressionTranslator` and
  `StatementTranslator` themselves are still exported, now as thin wrappers around
  the one pure-formatter method each still has.

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
