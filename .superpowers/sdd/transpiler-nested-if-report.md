# Transpiler bug: silent drop of an inline nested `IF`

Repo: `siemens-plc-tools`, branch `main`. Method: reproduce → root-cause → minimal fix → gate → cross-validate.

## 1. Reproduction (BEFORE the fix)

### Primary — silent code loss
The unit translator `translate_control_flow` works fine when the nested `IF` is on
its own physical line. It breaks only when the nested `IF` is **glued onto the same
physical line as the outer `THEN`** — which is exactly what the SCL parser produces
for that shape (region-content reconstruction keeps tokens on one line until a
newline token, and `IF a THEN IF b THEN body ;` has no newline before the first
`;`). Minimal unit input:

```
IF #status = 1 THEN IF (#a * #b) > #limit THEN #out := 1 ;
END_IF ;
END_IF ;
```

Pre-fix output (inner IF gone, stray `END_IF` leaked):
```
if self.status == 1:
    pass
END_IF
```

Harness / full parse→compile→execute (FUNCTION_BLOCK, inner IF glued as first
statement of the outer body):
- transpile reported **success = True** (silent at transpile time),
- generated `execute()` body was `if self.status == 1:\n    pass\nEND_IF`,
- at runtime `NameError: name 'END_IF' is not defined`; `out` never became `1`.

Control: the same logic with the nested `IF` **not first** (a `#pre := 0;` before
it) transpiles correctly — confirming the "first-position" symptom. Clean
multi-line layout also already worked.

### Secondary 1 — inline `//` comment leak
```
IF #flag THEN // set output      →  if self.flag:
#out := 1;                            // set output      <-- invalid Python
END_IF;                               self.out = 1
```
Reproduced for `THEN`- and `ELSE`-glued inline comments. (Comment on its **own**
line was already skipped by preprocessing; `FOR ... DO // c` was already guarded.)

### Secondary 2 — `**` operator
**Not reproducible** in the current engine. `#x ** 2`, `#x**2`, `2.0 ** #n`,
`(#a+#b) ** 2 + #c ** 3`, and `**` inside an IF condition all transpile correctly
(no `* *` split). No spacing pass in `codegen.py`/`control_flow.py` touches `*`.
Locked with guard tests; no code change.

## 2. Root cause (precise mechanism)

File: `packages/plc-code/src/plc_code/executor/control_flow.py`. Two coordinated
defects on the inline-body-after-keyword path, both triggered only when a nested
control-flow header shares the outer keyword's physical line:

1. **`_translate_if_block`** matches the outer header with
   `re.match(r"IF\s+(.+?)\s+THEN\b(.*)", line)` and appends `group(2)` (everything
   after the first `THEN`) verbatim as a single "inline body" line. For the glued
   shape that inline body is a nested `IF ... THEN #out := 1` **without its
   `END_IF`** (the `END_IF`s are on later physical lines). Recursively translating
   that inline body re-enters `_translate_if_block`; the nested-IF header sets
   `depth = 1` and captures its own inline body, but because there is no `END_IF`
   line, the branch-emission code — which lives **only** inside the
   `if upper.rstrip("; ") == "END_IF":` block — is never reached. The recursion
   returns `[]`: the entire nested statement is silently discarded.

2. **`_extract_if_block`** increments `depth` only once per physical line
   (`if upper.startswith("IF ")`), so a line carrying both the outer and the nested
   inline `IF` is counted as a single level. The two `END_IF` lines then decrement
   past the matched depth; the first `END_IF` closes the block and the function
   returns early, leaving the outer `END_IF` as a stray top-level line that later
   transpiles to the bare identifier `END_IF` (the "leaked END_IF").

Why first-position matters: the greedy `group(2)` capture only pulls a nested `IF`
into this broken path when the nested `IF` is the very first token after the outer
`THEN` on the same line. A plain, `;`-terminated statement between `THEN` and the
nested `IF` forces the nested `IF` onto its own line, where the correct multi-line
nested path (`_extract_if_block` counting + the "Nested IF increases depth" branch)
handles it.

Secondary 1 shares this path: the inline comment is captured as `group(2)` and
emitted verbatim.

## 3. Fix (minimal)

All changes in `_preprocess` of `control_flow.py` — normalize the line stream so the
already-correct multi-line paths handle these shapes; the fragile inline-body logic
is left untouched:

- **`_strip_inline_comment(line)`** (new, quote-aware): strips a trailing `//`
  comment from every source line before further processing, so an inline comment is
  never captured as a body statement. `//` inside a `'...'`/`"..."` literal is
  preserved. Fixes secondary 1.
- **`_INLINE_COMPOUND_SPLIT`** (new regex `\b(THEN|ELSE|DO)\b\s+(IF|CASE|WHILE|FOR)\b`)
  + a final expansion pass in `_preprocess`: a nested control-flow header directly
  following `THEN`/`ELSE`/`DO` is broken onto its own line. Each nested header then
  gets its own physical line, so `_extract_if_block` counts depth correctly and
  `_translate_if_block` routes it through the correct multi-line nested path
  (which already emits it with its `END_IF`). Fixes the primary bug; also covers
  the `ELSE`-body and deeply-nested variants.

The inline **simple**-body path (e.g. `Sign.s7dcl`'s `IF #x < 0.0 THEN #Sign := -1.0;`
/ `ELSIF` / `ELSE` on one line) is untouched — the split only fires when a control
keyword follows, and `ELSIF` (no space) is never matched.

## 4. Gate

- New test file `packages/plc-code/tests/test_executor/test_control_flow_nested_if.py`
  (15 tests): harness execution of the glued nested-IF FB (`out == 1`), inner/outer
  false variants, clean multi-line pin, nested-not-first pin, ELSE-body variant,
  triple-nested, inline-comment (own-line/THEN/ELSE + string-`//` safety), `**` guards.
- Pre-fix confirmation: stashing the `control_flow.py` change → **8 of 15 fail**
  (all glued-form + inline-comment cases), 7 pass (already-correct behaviour). Post-fix
  all 15 pass.
- Full plc-code suite: **933 passed, 7 skipped** (no regressions).
- `black` (reformatted test file only), `ruff check` (all checks passed),
  `mypy` on `control_flow.py` and the test file (Success, no issues).

## 5. Critical-review fix (quote-aware compound split) — 2026-07-02

### Finding
`_INLINE_COMPOUND_SPLIT.sub(r"\1\n\2", line)` was applied to the whole line without
quote awareness, unlike `_strip_inline_comment` which correctly tracks `'...'`/`"..."`.
A string literal containing a control-keyword pair was split mid-string:

```
#msg := 'PUMP DO WHILE RUN';  →  self.msg = 'PUMP DO   (unterminated) + spurious WHILE line
#msg := 'ELSE IF x';          →  self.msg = 'ELSE      (corrupted)
```

### Fix
`_quote_aware_compound_split(line: str) -> str` added to `ControlFlowTranslator`.
Builds a per-character `inside[]` boolean array (mirrors `_strip_inline_comment`'s
state machine, adds SCL doubled-quote escaping `''`/`""`), then passes a replacement
function to `re.sub` that returns the match unchanged when `inside[m.start()]` is True.
The regex itself is untouched. `_preprocess` now calls the new method instead of raw
`.sub`.

### Tests added (red → green)
`TestSplitQuoteAwareness` (3 tests):
- `test_split_does_not_break_string_literal` — the three reviewer-specified repros
- `test_split_does_not_break_string_in_if_body` — string literal inside IF body
- `test_split_applied_outside_string` — real keyword pair still split (regression guard)

`TestSplitPinnedKeywordPairs` (2 tests, previously untested working behaviour):
- `test_then_case_split` — `THEN CASE` glued on one line, correct IF + CASE output
- `test_do_while_nested_split` — `DO WHILE` glued on one line, two nested while loops

Gate: 20/20 passed (5 new green, 15 pre-existing), full suite 938 passed 7 skipped,
black+ruff+mypy all clean, project-E 35 passed.

## 6. Cross-validation

`project-E` suite (its venv uses this repo editable):
`uv run --no-sync pytest -q` → **35 passed**. The WS2 FB carrying the
`IF (a) AND (b)` workaround still passes.

## 6. Secondary bugs — disposition

- **Comment-first inline leak (WS1-B): FIXED** — same root-cause family, fixed by
  the inline-comment strip. Regression tests added.
- **`**` operator: UNTOUCHED (not reproducible)** — verified correct across many
  forms in the current engine; locked with guard tests so a future regression is
  caught. The legacy sibling blocks `CpmsSensorInput.s7dcl` /
  `AutomaticTrajectoryPlan.s7dcl` are not harnessed here, but their `**` usage would
  transpile correctly through this engine.

## Controller closure (2026-07-02)
- Adversarial review found a Critical in the first fix (split regex not quote-aware; string
  literals containing THEN IF/DO WHILE/ELSE IF corrupted). Fixed in d119b8d
  (_quote_aware_compound_split, inside[] state machine); re-review verdict: RESOLVED
  (original live repros + doubled-quote parity + mixed unquoted/quoted case all correct).
- main @ d119b8d pushed. plc-code suite 938 passed; project-E cross-check 35 passed.
- KNOWN PRE-EXISTING ISSUE (follow-up, not a blocker): _normalize_spacing
  (control_flow.py:~297) is also quote-unaware — inserts a space inside string literals
  containing keywords like DO (alters string content, e.g. 'DO WHILE loop' -> ' DO WHILE loop').
  Same class; fix by reusing the inside[] scan if it ever matters for HMI text.
