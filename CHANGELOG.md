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

  Measured over 648 blocks in five real PLC projects: **100.00% token coverage,
  every block clean, zero errors and zero silent loss.** The first measurement
  reported 99.96% with 51 errors; both remaining constructs are read now — see
  the argument-depth fix below. The one silent case a
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

  Measured over five real PLC projects (`project-A` … `project-E`): **16,069
  expression slices, 16,068 parsed, 99.99%, 1 error.**

  The first measurement was 96.30% with 594 errors. Seven grammar gaps were then
  closed, each reported below as its own fix: a call whose callee is a quoted
  block name (`"ConvertAngleSafetyProcess"(...)`), a member name carrying its own
  `#` (`#armSetpoint.#angularSpeeds["SLEWING"]`), a named argument binding
  (`"PolyEval"(p := #p)`, `RD_SYS_T(OUT => #localTime)`), a structural keyword
  used as a name (`#function`, `.type`), a multi-dimensional array index
  (`#m[#i, #j]`), direct bit access (`.%X0`), and the implicit enable output
  (`ENO`).

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

  One error remains in the whole corpus, and it is not an expression at all:

      REGION "RCU" Default Management
          #InstRcuAlarmManagement(rcuRawInput := #rcuRawInput, ...);
      END_REGION

  `parse_scl_file` does not handle a REGION nested inside a REGION, so the inner
  header stays in the outer region's token slice and the statement parser reads
  it as code. That is a region-splitting defect, not a grammar gap, and it is
  left for its own fix.

  The qualifier that makes that rate honest: `parse_scl_file` only tokenises
  `REGION` contents, so SCL written directly inside a `NETWORK` is an
  untokenised string this pipeline never sees at all. Measured across the same
  corpus: 123 of 649 blocks (19%) contain such SCL — 49,151 tokens against
  126,456 inside regions, 28% of the corpus SCL. So the rate above is 99.99% of
  the expression slices in SCL that lives inside REGION blocks, not 99.99% of
  the SCL in these five projects.

  Also pre-existing and out of scope: the lexer folds an unspaced `-` before a
  digit into one `NUMBER` token (`#a-2` lexes as `#a`, `-2`, not `#a`, `-`,
  `2`), so `#a-2`, `1-2`, `ABS(#x-1)` and `#arr[#i-1]` all fail to parse today.
  Zero occurrences across the five projects is why the published rate does not
  show it, not evidence it does not happen — a project that writes `x := a-1`
  would see this rate drop sharply.
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
