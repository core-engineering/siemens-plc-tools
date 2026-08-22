"""Native rendering of `If`/`For`/`While`/`Case` headers, and of `Call`/`Return`/`Exit`.

Task 7 (headers). `generate_statements` stops rebuilding SCL text for a header line -- an
`If` branch's condition, a `While`'s condition, a `For`'s bounds, a `Case`'s selector and
each label -- and renders it from `Branch.condition_expr` / `While.condition_expr` /
`For.start_expr`/`end_expr`/`step_expr` / `Case.selector_expr` / `CaseBranch.values_expr`
directly, via `renderer.render`, falling back to the text dispatcher only when a slice
failed to parse or `render` itself raises `UnsupportedExpression` -- see
`generator._render_expression_or_fallback` and `generator._render_case_label`.

Task 8 (`Call`/`Return`/`Exit`). `Return` and `Exit` render natively unconditionally
(`generator._generate_return` / `_generate_exit` -- no tree involved). `Call` reads its
shape (FB instance call, quoted-block call statement, or neither) off
`statement.callee_expr` instead of re-parsing rebuilt SCL text with
`StatementTranslator.translate_simple_statement`'s regular expressions --
`generator._generate_call`, falling back on the same two terms as `Assignment` (no tree,
or `render` raises for a named argument).

Every output shape here is transcribed from `test_generator_statements.py`, which already
pins the byte-identical text these constructs must keep producing; this module does not
invent new shapes, it adds the native/fallback counter assertions
(`control_flow_render_counts`, `call_render_counts`) that prove the shape came from the
tree, not just from an unchanged code path that happens to still produce the same text.

Fix round 1 (post-review) adds two regression tests the corpus differential's own
per-argument-slice attribution could not surface on its own:

* `_is_write_back_candidate` wrongly returned True for a `Member` whose global-DB base
  name contains a non-word character (a hyphen, a space, a dot) -- `translate_fb_call`'s
  ``GLOBAL_DB_PATTERN`` (`r'"(\\w+)"\\s*\\.\\s*(.+)'`) never matches such a name, so the
  dispatcher never rewrites it and `_emit_named_call` never emits a write-back for it,
  while the buggy check emitted a spurious second line. The differential's own
  per-argument-slice attribution laundered this away, because the *value itself* renders
  identically on both sides regardless -- only the extra *statement* line differed, which
  no single-slice comparison can see.
* `_has_closing_parenthesis` originally checked only for an `RPAREN` token, missing a `)`
  character embedded inside a string literal argument (`translate_fb_call`'s regex
  truncates on that too, blind to token boundaries) -- now checks `STRING` token text too.
"""

from __future__ import annotations

import pytest

from plc_code.executor.generator import (
    _generate_statements_via_strings,
    _is_write_back_candidate,
    call_fallback_reasons,
    call_render_counts,
    control_flow_render_counts,
    generate_statements,
    reset_call_render_counters,
    reset_control_flow_render_counters,
)
from plc_code.executor.renderer import UnsupportedExpression
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Call, Statement


def _statements(source: str) -> list[Statement]:
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    assert result.errors == [], result.errors
    return result.statements


def test_an_if_with_elsif_and_else_renders_every_condition_natively() -> None:
    reset_control_flow_render_counters()
    source = "IF #a THEN #b := 1 ; ELSIF #c THEN #b := 2 ; ELSE #b := 3 ; END_IF ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "if self.a:",
        "    self.b = 1",
        "elif self.c:",
        "    self.b = 2",
        "else:",
        "    self.b = 3",
    ]
    native, fallback = control_flow_render_counts()
    assert (native, fallback) == (2, 0)  # one render per branch condition (IF, ELSIF)


def test_a_for_loop_with_a_step_renders_every_bound_natively() -> None:
    reset_control_flow_render_counters()
    source = "FOR #i := 1 TO 5 BY 2 DO #a := #i ; END_FOR ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "for self.i in range(1, 5 + 1, 2):",
        "    self.a = self.i",
    ]
    native, fallback = control_flow_render_counts()
    assert (native, fallback) == (3, 0)  # start, end, step


def test_a_for_loop_without_a_step_keeps_the_literal_plus_one() -> None:
    reset_control_flow_render_counters()
    source = "FOR #i := 1 TO 5 DO #a := #i ; END_FOR ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "for self.i in range(1, 5 + 1):",
        "    self.a = self.i",
    ]
    native, fallback = control_flow_render_counts()
    assert (native, fallback) == (2, 0)  # start, end -- no step clause


def test_a_while_loop_renders_its_condition_natively() -> None:
    reset_control_flow_render_counters()
    source = "WHILE #a DO #b := 1 ; END_WHILE ;"
    lines = generate_statements(_statements(source))
    assert lines == ["while self.a:", "    self.b = 1"]
    native, fallback = control_flow_render_counts()
    assert (native, fallback) == (1, 0)


def test_a_case_becomes_an_if_elif_chain_with_selector_and_labels_native() -> None:
    reset_control_flow_render_counters()
    source = "CASE #s OF 1 : #b := 1 ; 2 , 3 : #b := 2 ; ELSE #b := 9 ; END_CASE ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "if self.s == 1:",
        "    self.b = 1",
        "elif self.s in (2, 3):",
        "    self.b = 2",
        "else:",
        "    self.b = 9",
    ]
    native, fallback = control_flow_render_counts()
    # selector rendered once (shared across arms, matching the old cost) + 3 labels (1, 2, 3)
    assert (native, fallback) == (4, 0)


def test_a_case_without_an_else_arm() -> None:
    lines = generate_statements(_statements("CASE #s OF 1 : #b := 1 ; END_CASE ;"))
    assert lines == ["if self.s == 1:", "    self.b = 1"]


def test_a_symbolic_case_label_maps_to_its_bare_integer_not_self_dot_name() -> None:
    """The ruling the task brief calls out explicitly.

    `render`'s ordinary `VariableRef` substitution (a mapped string constant becomes
    `self.NAME`) must NOT apply to a CASE label position -- that would turn
    `if self.s == 1:` into `if self.s == self.MODE_ONE:`. A label whose tree is a
    non-local, non-absolute `VariableRef` matching a `string_constants` key emits the
    bare integer instead; the same symbol used elsewhere in the block (the ELSE arm's
    assignment) still gets the ordinary `self.NAME` substitution.
    """
    source = 'CASE #s OF "MODE_ONE" : #b := 1 ; ELSE #c := "MODE_ONE" ; END_CASE ;'
    lines = generate_statements(_statements(source), string_constants={'"MODE_ONE"': 1})
    assert lines == [
        "if self.s == 1:",
        "    self.b = 1",
        "else:",
        "    self.c = self.MODE_ONE",
    ]


def test_a_while_condition_falls_back_when_render_refuses_the_tree() -> None:
    """A bare builtin call binding an output has no destination -- `render` raises.

    `ABS(y => #out)` parses cleanly into a `FunctionCall` (probed directly), but
    `renderer._render_builtin_call` refuses to render it (see its own docstring): a
    positional call has nowhere to write the `=>` binding back to. The condition must
    still fall back to the text dispatcher rather than propagate the exception.
    """
    reset_control_flow_render_counters()
    source = "WHILE ABS(y => #out) DO #b := 1 ; END_WHILE ;"
    lines = generate_statements(_statements(source))
    assert lines[0].startswith("while ")
    assert lines[0].endswith(":")
    native, fallback = control_flow_render_counts()
    assert (native, fallback) == (0, 1)


def test_a_nested_if_indents_twice_and_renders_both_conditions_natively() -> None:
    reset_control_flow_render_counters()
    source = "IF #a THEN IF #b THEN #c := 1 ; END_IF ; END_IF ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "if self.a:",
        "    if self.b:",
        "        self.c = 1",
    ]
    native, fallback = control_flow_render_counts()
    assert (native, fallback) == (2, 0)


def test_an_fb_instance_call_with_input_and_output_renders_natively() -> None:
    reset_call_render_counters()
    source = "#tmr(IN := #x, PT := #t, Q => #q);"
    lines = generate_statements(_statements(source))
    assert lines == ["self.tmr(IN=self.x, PT=self.t)", "self.q = self.tmr.Q"]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_an_indexed_callee_fb_call_renders_natively_with_correct_keyword_syntax() -> None:
    """Task 9 step 3: an `Index` callee (`#arms[#i](...)`) widens the FB-instance branch.

    The old dispatcher's `translate_fb_call` regex (`#(\\w+)\\s*\\(`) never matches an
    indexed callee at all, so it falls through to translating the whole line as one bare
    *expression* instead -- `OPERATOR_MAP` maps `:=` to `=`, and the standalone-`=`-to-`==`
    rule then mangles that `=` too (nothing distinguishes it from a real `=` any more),
    while `=>` -- collapsed to one token by `translate_simple_statement`'s own
    normalisation before this ever runs -- survives untouched and merely keeps its name
    discarded: `self.arms [ self.i ] ( x == self.a , y => self.b )`, a call that
    *compiles* (`==` is a valid Python operator) and would call the FB positionally with a
    boolean, while the `y => self.b` output binding is dropped as unparseable text sitting
    inside a syntactically-invalid parameter list. Probed directly, not assumed. This is
    the *existing* "bare call `:=` mangled to `==`" residual class (see
    `test_renderer_calls.py`'s own pin of that class for a bare builtin), reached through
    an indexed callee rather than a bare `FunctionCall` expression -- not a new one.
    """
    reset_call_render_counters()
    source = "#arms[#i](x := #a, y => #b);"
    old_lines = _generate_statements_via_strings(_statements(source))
    new_lines = generate_statements(_statements(source))
    assert old_lines == ["self.arms [ self.i ] ( x == self.a , y => self.b )"]
    assert new_lines == ["self.arms[self.i](x=self.a)", "self.b = self.arms[self.i].y"]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_a_member_callee_fb_call_renders_natively_and_gets_the_clock_argument() -> None:
    """A `Member` callee (`"db".TON(...)`) widens the same branch, with a timer marker.

    `_callee_timer_marker_name` checks the `Member`'s own `.name` ("TON") against
    `_TIMER_INSTANCE_MARKERS`, so this instance gets the trailing
    `clock=self._runtime.clock` keyword argument the plain-`VariableRef` case already
    gets for a name like `#tmr` -- the old dispatcher never reached its own timer check
    for this callee shape at all (see `_callee_timer_marker_name`'s own docstring), so
    there is no old behaviour to match, only what is correct.
    """
    reset_call_render_counters()
    source = '"MyDb".TON(IN := #a, PT := #t, Q => #q);'
    lines = generate_statements(_statements(source))
    assert lines == [
        'self._runtime.global_dbs["MyDb"].TON(IN=self.a, PT=self.t, clock=self._runtime.clock)',
        'self.q = self._runtime.global_dbs["MyDb"].TON.Q',
    ]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_an_fb_instance_call_drops_positional_arguments_same_as_the_dispatcher() -> None:
    """Reproduces `translate_fb_call`'s own silent-drop behaviour, bug for bug.

    Probed directly: `StatementTranslator().translate_simple_statement("#tmr ( #x , #y ) ;")
    == ["self.tmr()"]` -- a positional argument is neither `:=` nor `=>`, so
    `translate_fb_call`'s per-param check drops it. The native path must reproduce this,
    not "fix" it.
    """
    reset_call_render_counters()
    source = "#tmr(#x, #y);"
    lines = generate_statements(_statements(source))
    assert lines == ["self.tmr()"]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_a_quoted_name_block_call_statement_renders_natively_via_emit_named_call() -> None:
    reset_call_render_counters()
    source = '"Doubler"(x := #value, result := #intermediate);'
    lines = generate_statements(_statements(source))
    assert lines == [
        "_sub_Doubler_result = self._runtime.call_named_block("
        '"Doubler", {"x": self.value, "result": self.intermediate}, {})',
        'if "x" in _sub_Doubler_result: self.value = _sub_Doubler_result["x"]',
        'if "result" in _sub_Doubler_result: self.intermediate = _sub_Doubler_result["result"]',
    ]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_a_return_statement_renders_natively() -> None:
    reset_call_render_counters()
    lines = generate_statements(_statements("RETURN ;"))
    assert lines == ["return"]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_an_exit_statement_inside_a_for_loop_renders_natively() -> None:
    reset_call_render_counters()
    source = "FOR #i := 1 TO 3 DO EXIT ; END_FOR ;"
    lines = generate_statements(_statements(source))
    assert lines == ["for self.i in range(1, 3 + 1):", "    break"]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)


def test_a_call_falls_back_when_an_argument_value_has_no_native_render() -> None:
    """`ABS(y => #out)` as an argument value -- `render` raises (see `test_generator_native.py`'s

    own control-flow fallback test for the same shape). `_generate_call` must fall back to
    the dispatcher rather than propagate the exception, for both call shapes.
    """
    reset_call_render_counters()
    fb_lines = generate_statements(_statements("#tmr(IN := ABS(y => #out));"))
    assert fb_lines == ["self.tmr(IN=abs( y => self.out)"]
    quoted_lines = generate_statements(_statements('"Block"(x := ABS(y => #out));'))
    assert quoted_lines == [
        '_sub_Block_result = self._runtime.call_named_block("Block", {"x": abs( y => self.out )}, {})'
    ]
    native, fallback = call_render_counts()
    assert (native, fallback) == (0, 2)


def test_an_assignment_from_a_named_call_with_outputs_renders_natively() -> None:
    """The Task 6 dispatcher-routed shape, now rendered by `_generate_named_call_assignment`.

    Counted as an `Assignment`, not a `Call` -- `call_render_counts` stays untouched; see
    `assignment_render_counts` in the differential for this shape's own native/fallback
    split.
    """
    reset_call_render_counters()
    source = '#ret := "RetWithOut"(x := #value, dbl => #doubled, trp => #tripled);'
    lines = generate_statements(_statements(source))
    assert lines == [
        "_sub_RetWithOut_result = self._runtime.call_named_block(" '"RetWithOut", {"x": self.value}, {})',
        'self.doubled = _sub_RetWithOut_result["dbl"]',
        'self.tripled = _sub_RetWithOut_result["trp"]',
        'if "x" in _sub_RetWithOut_result: self.value = _sub_RetWithOut_result["x"]',
        'self.ret = _sub_RetWithOut_result["RetWithOut"]',
    ]
    native, fallback = call_render_counts()
    assert (native, fallback) == (0, 0)


def test_an_assignment_from_a_bare_builtin_call_binding_an_output_fails_loudly() -> None:
    """Task 9 step 3: this shape no longer falls back to the dispatcher -- it raises.

    `#x := RD_SYS_T(OUT => #x);` -- a bare (non-quoted) system builtin binding a
    parameter with `=>` -- has no correct Python to fall back to (see
    `renderer._render_builtin_call`'s own docstring, and
    `generator._generate_assignment`'s own docstring for the probed-and-confirmed old
    dispatcher output this replaces: `self.x = RD_SYS_T ( OUT => self.x )`, a
    `SyntaxError` at class-definition time). `generate_statements` now lets `render`'s
    `UnsupportedExpression` propagate for this shape instead of silently reproducing
    that broken text; `SCLTranspiler.transpile`'s own top-level exception handler turns
    it into `TranspileResult(success=False, ...)` -- see
    `test_transpiler.py`/`test_cli_transpile.py`-level coverage of that, this test only
    pins the generator's own half.
    """
    source = "#x := RD_SYS_T(OUT => #x);"
    with pytest.raises(UnsupportedExpression) as exc_info:
        generate_statements(_statements(source))
    message = str(exc_info.value)
    assert "RD_SYS_T" in message
    assert "OUT" in message


def _first_call_argument_value_expr(source: str, index: int = 0):
    """The parsed value of one `Call` statement's `index`-th argument, for a direct unit check."""
    (call,) = _statements(source)
    assert isinstance(call, Call)
    value_expr = call.arguments[index].value_expr
    assert value_expr is not None
    return value_expr


def test_a_global_db_name_with_a_hyphen_is_not_a_write_back_candidate() -> None:
    """Fix round 1 (Critical): `GLOBAL_DB_PATTERN` requires a word-only quoted name.

    `"My-DB" . m` never matches `r'"(\\w+)"\\s*\\.\\s*(.+)'` (the hyphen is not `\\w`), so
    the dispatcher's `translate` leaves it completely untouched -- quoted, with its
    `scl_text` spaces intact -- and `_emit_named_call` never sees a `self.`-rooted,
    space-free value for it, so it never emits a write-back line. The line *count* must
    match the old path's even though the *value text* legitimately still differs (a
    pre-existing, separately-attributed `renderer.py` residual -- see the module
    docstring's own note on this).
    """
    value_expr = _first_call_argument_value_expr('"Blk"(x := "My-DB".m);')
    assert _is_write_back_candidate(value_expr, None) is False

    source = '"Blk"(x := "My-DB".m);'
    old_lines = _generate_statements_via_strings(_statements(source))
    new_lines = generate_statements(_statements(source))
    assert len(new_lines) == len(old_lines) == 1


def test_a_global_db_name_with_a_space_is_not_a_write_back_candidate() -> None:
    value_expr = _first_call_argument_value_expr('"Blk"(x := "My DB".m);')
    assert _is_write_back_candidate(value_expr, None) is False

    source = '"Blk"(x := "My DB".m);'
    old_lines = _generate_statements_via_strings(_statements(source))
    new_lines = generate_statements(_statements(source))
    assert len(new_lines) == len(old_lines) == 1


def test_a_global_db_name_with_a_dot_is_not_a_write_back_candidate() -> None:
    value_expr = _first_call_argument_value_expr('"Blk"(x := "a.b".m);')
    assert _is_write_back_candidate(value_expr, None) is False

    source = '"Blk"(x := "a.b".m);'
    old_lines = _generate_statements_via_strings(_statements(source))
    new_lines = generate_statements(_statements(source))
    assert len(new_lines) == len(old_lines) == 1


def test_a_closing_paren_inside_a_string_argument_renders_whole_natively() -> None:
    """Task 9 step 3: the closing-parenthesis guard is gone -- this now renders natively.

    Before this change, `_generate_fb_instance_call` refused (fell back to the
    dispatcher) whenever an argument's raw value contained a `)`, so the dispatcher's
    own `translate_fb_call` truncation (`self.tmr(IN='a)` -- `PT` silently dropped, see
    `generator._has_closing_parenthesis`'s own docstring) was reproduced byte for byte.
    That guard is gone: this shape now renders the call whole and correctly, diverging
    from the old (still-truncating) dispatcher on purpose -- the fifth attributed
    residual class the corpus differential now recognises (see
    `tests/test_generator_native_differential.py`'s module docstring and its
    `fb_call_argument_would_truncate_old_path` fixture).
    """
    reset_call_render_counters()
    source = "#tmr(IN := 'a)b', PT := #t);"
    old_lines = _generate_statements_via_strings(_statements(source))
    new_lines = generate_statements(_statements(source))
    assert old_lines == ["self.tmr(IN='a)"]
    assert new_lines == ["self.tmr(IN='a)b', PT=self.t)"]
    native, fallback = call_render_counts()
    assert (native, fallback) == (1, 0)
    assert call_fallback_reasons() == {}


def test_call_fallback_reasons_are_split_by_cause() -> None:
    """`call_fallback_reasons` breaks the one `fallback` count down.

    Two different `Call` statements, two different reasons, neither collides with the
    other. `"closing_parenthesis"` no longer occurs (see
    `test_a_closing_paren_inside_a_string_argument_renders_whole_natively` above), and
    an indexed or member callee (`#arr[1](...)`, `"db".TON(...)`) no longer falls back
    at all -- `_generate_fb_instance_call` renders both natively now (Task 9 step 3, see
    `generator._generate_call`'s own docstring) -- so this now pairs
    `unsupported_expression` with `not_a_simple_callee` from an *absolute-address*
    callee (`%M0(...)`), the one shape still outside every native branch.
    """
    reset_call_render_counters()
    generate_statements(_statements('"Block"(x := ABS(y => #out));'))  # unsupported_expression
    generate_statements(_statements("%M0(x := #a);"))  # not_a_simple_callee
    reasons = call_fallback_reasons()
    assert reasons["unsupported_expression"] == 1
    assert reasons["not_a_simple_callee"] == 1
    native, fallback = call_render_counts()
    assert (native, fallback) == (0, 2)
    assert sum(reasons.values()) == fallback
