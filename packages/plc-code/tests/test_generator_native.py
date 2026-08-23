"""Native rendering of `If`/`For`/`While`/`Case` headers, and of `Call`/`Return`/`Exit`.

`generate_statements` renders a header line -- an `If` branch's condition, a `While`'s
condition, a `For`'s bounds, a `Case`'s selector and each label -- from
`Branch.condition_expr` / `While.condition_expr` / `For.start_expr`/`end_expr`/`step_expr`
/ `Case.selector_expr` / `CaseBranch.values_expr` directly, via `renderer.render`
(`generator._render_header_expression` and `_render_case_label`). `Return` and `Exit`
render unconditionally (no tree involved). `Call` reads its shape (FB instance call,
indexed/member-callee FB instance call, quoted-block call statement, or unsupported) off
`statement.callee_expr` (`generator._generate_call`).

A construct none of these can render raises rather than falling back to any kind of text
reconstruction (Task 9 deleted that path once the corpus differentials proved the native
path handles every shape the corpus contains): `UnsupportedStatement` for a slice that
never parsed into a tree, or an uncaught `renderer.UnsupportedExpression` for a tree
`render` refuses.

Every output shape here is transcribed from `test_generator_statements.py`, which already
pins the byte-identical text these constructs must keep producing; this module does not
invent new shapes, it exercises the same constructs at the unit level with the raise/render
outcomes each one now actually reaches.

Fix round 1 (post-review) adds two regression tests the corpus differential's own
per-argument-slice attribution could not surface on its own:

* `_is_write_back_candidate` wrongly returned True for a `Member` whose global-DB base
  name contains a non-word character (a hyphen, a space, a dot) -- the old text
  translator's `GLOBAL_DB_PATTERN` (`r'"(\\w+)"\\s*\\.\\s*(.+)'`) never matched such a
  name, so the old dispatcher never rewrote it and `_emit_named_call` never emitted a
  write-back for it, while the buggy check emitted a spurious second line. The
  differential's own per-argument-slice attribution laundered this away, because the
  *value itself* rendered identically on both sides regardless -- only the extra
  *statement* line differed, which no single-slice comparison could see.
* The old text translator's paren-truncation guard originally checked only for an
  `RPAREN` token, missing a `)` character embedded inside a string literal argument --
  now moot, since Task 9 step 3 removed the guard (and its dispatcher) entirely; the
  corpus differential's own classifier for that residual class checked both cases.
"""

from __future__ import annotations

import pytest

from plc_code.executor.generator import (
    UnsupportedStatement,
    _is_write_back_candidate,
    generate_statements,
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


def test_a_for_loop_with_a_step_renders_every_bound_natively() -> None:
    source = "FOR #i := 1 TO 5 BY 2 DO #a := #i ; END_FOR ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "for self.i in range(1, 5 + 1, 2):",
        "    self.a = self.i",
    ]


def test_a_for_loop_without_a_step_keeps_the_literal_plus_one() -> None:
    source = "FOR #i := 1 TO 5 DO #a := #i ; END_FOR ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "for self.i in range(1, 5 + 1):",
        "    self.a = self.i",
    ]


def test_a_while_loop_renders_its_condition_natively() -> None:
    source = "WHILE #a DO #b := 1 ; END_WHILE ;"
    lines = generate_statements(_statements(source))
    assert lines == ["while self.a:", "    self.b = 1"]


def test_a_case_becomes_an_if_elif_chain_with_selector_and_labels_native() -> None:
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


def test_a_case_without_an_else_arm() -> None:
    lines = generate_statements(_statements("CASE #s OF 1 : #b := 1 ; END_CASE ;"))
    assert lines == ["if self.s == 1:", "    self.b = 1"]


def test_a_symbolic_case_label_is_the_same_tag_lookup_as_elsewhere() -> None:
    """`"MODE_ONE"` as a CASE label and as a value render the same tag-table lookup.

    The string-constant scan that mapped such names to integers (label -> `1`,
    elsewhere -> `self.MODE_ONE`) is gone: an unset tag compares equal to itself
    by name, so the label matches a selector assigned from the same name and
    nothing else, with no table loaded. `string_constants` is accepted and ignored.
    """
    source = 'CASE #s OF "MODE_ONE" : #b := 1 ; ELSE #c := "MODE_ONE" ; END_CASE ;'
    lines = generate_statements(_statements(source), string_constants={'"MODE_ONE"': 1})
    assert lines == [
        'if self.s == self._runtime.tags["MODE_ONE"]:',
        "    self.b = 1",
        "else:",
        '    self.c = self._runtime.tags["MODE_ONE"]',
    ]


def test_a_while_condition_fails_loudly_when_render_refuses_the_tree() -> None:
    """A bare builtin call binding an output has no destination -- `render` raises.

    `ABS(y => #out)` parses cleanly into a `FunctionCall` (probed directly), but
    `renderer._render_builtin_call` refuses to render it (see its own docstring): a
    positional call has nowhere to write the `=>` binding back to. `generate_statements`
    lets that exception propagate uncaught (Task 9 step 3 removed the text-dispatcher
    fallback this used to take).
    """
    source = "WHILE ABS(y => #out) DO #b := 1 ; END_WHILE ;"
    with pytest.raises(UnsupportedExpression) as exc_info:
        generate_statements(_statements(source))
    message = str(exc_info.value)
    assert "ABS" in message
    assert "y" in message


def test_a_nested_if_indents_twice_and_renders_both_conditions_natively() -> None:
    source = "IF #a THEN IF #b THEN #c := 1 ; END_IF ; END_IF ;"
    lines = generate_statements(_statements(source))
    assert lines == [
        "if self.a:",
        "    if self.b:",
        "        self.c = 1",
    ]


def test_an_fb_instance_call_with_input_and_output_renders_natively() -> None:
    source = "#tmr(IN := #x, PT := #t, Q => #q);"
    lines = generate_statements(_statements(source))
    assert lines == ["self.tmr(IN=self.x, PT=self.t)", "self.q = self.tmr.Q"]


def test_an_indexed_callee_fb_call_renders_natively_with_correct_keyword_syntax() -> None:
    """An `Index` callee (`#arms[#i](...)`) is handled by the FB-instance branch too.

    The old (now-deleted) text dispatcher's `translate_fb_call` regex (`#(\\w+)\\s*\\(`)
    never matched an indexed callee at all, so it fell through to translating the whole
    line as one bare *expression* instead -- `OPERATOR_MAP` mapped `:=` to `=`, and the
    standalone-`=`-to-`==` rule then mangled that `=` too (nothing distinguished it from
    a real `=` any more), while `=>` -- collapsed to one token by that dispatcher's own
    normalisation before translation ran -- survived untouched and merely kept its name
    discarded: `self.arms [ self.i ] ( x == self.a , y => self.b )` (probed directly,
    not assumed, before Task 9 step 3 deleted that path). The bare `=>` left over from
    the output binding makes this *particular* reconstructed line a `SyntaxError`
    (probed with `compile()`) -- for the minimal shape with no output binding at all
    (`#arms[#i](x := #a);` -> `self.arms [ self.i ] ( x == self.a )`, also probed), the
    old path's output *did* compile and would have called the FB positionally with a
    boolean instead of by keyword. Either way this is the *existing* "bare call `:=`
    mangled to `==`" residual class (see `test_renderer_calls.py`'s own pin of that class
    for a bare builtin), reached through an indexed callee rather than a bare
    `FunctionCall` expression -- not a new one.
    """
    source = "#arms[#i](x := #a, y => #b);"
    new_lines = generate_statements(_statements(source))
    assert new_lines == ["self.arms[self.i](x=self.a)", "self.b = self.arms[self.i].y"]


def test_a_member_callee_fb_call_renders_natively_and_gets_the_clock_argument() -> None:
    """A `Member` callee (`"db".TON(...)`) is handled by the same branch.

    `_callee_is_timer` has no declaration in reach for a global DB member, so it
    counts the member as a timer only when its name *is* an IEC timer type name
    ("TON" here) -- then the trailing `clock=self._runtime.clock` keyword argument a
    timer's `__call__` requires is added, as for a declared local timer.
    """
    source = '"MyDb".TON(IN := #a, PT := #t, Q => #q);'
    lines = generate_statements(_statements(source))
    assert lines == [
        'self._runtime.global_dbs["MyDb"].TON(IN=self.a, PT=self.t, clock=self._runtime.clock)',
        'self.q = self._runtime.global_dbs["MyDb"].TON.Q',
    ]


def test_an_fb_instance_call_with_a_positional_argument_raises_instead_of_dropping_it() -> None:
    """The old text dispatcher dropped a positional argument (neither `:=` nor `=>`)
    and called the instance with nothing -- `#tmr(#x, #y)` became `self.tmr()`. An
    instance's FB type is not resolvable from inside the caller, so there is no
    signature to bind against: the native path refuses instead of losing the call."""
    source = "#tmr(#x, #y);"
    with pytest.raises(UnsupportedStatement, match="positional argument"):
        generate_statements(_statements(source))


def test_a_quoted_name_block_call_statement_renders_natively_via_emit_named_call() -> None:
    source = '"Doubler"(x := #value, result := #intermediate);'
    lines = generate_statements(_statements(source))
    assert lines == [
        "_sub_Doubler_result = self._runtime.call_named_block("
        '"Doubler", {"x": self.value, "result": self.intermediate}, {})',
        'if "x" in _sub_Doubler_result: self.value = _sub_Doubler_result["x"]',
        'if "result" in _sub_Doubler_result: self.intermediate = _sub_Doubler_result["result"]',
    ]


def test_a_return_statement_renders_natively() -> None:
    lines = generate_statements(_statements("RETURN ;"))
    assert lines == ["return"]


def test_an_exit_statement_inside_a_for_loop_renders_natively() -> None:
    source = "FOR #i := 1 TO 3 DO EXIT ; END_FOR ;"
    lines = generate_statements(_statements(source))
    assert lines == ["for self.i in range(1, 3 + 1):", "    break"]


def test_a_call_fails_loudly_when_an_argument_value_has_no_native_render() -> None:
    """`ABS(y => #out)` as an argument value -- `render` raises, uncaught, for both call shapes."""
    with pytest.raises(UnsupportedExpression):
        generate_statements(_statements("#tmr(IN := ABS(y => #out));"))
    with pytest.raises(UnsupportedExpression):
        generate_statements(_statements('"Block"(x := ABS(y => #out));'))


def test_a_call_with_no_supported_callee_shape_fails_loudly() -> None:
    """An absolute-address callee (`%M0(...)`) is not an FB instance, an indexed/member
    callee, or a quoted-block call -- `_generate_call` raises `UnsupportedStatement`."""
    with pytest.raises(UnsupportedStatement, match="no supported callee shape"):
        generate_statements(_statements("%M0(x := #a);"))


def test_an_assignment_from_a_named_call_with_outputs_renders_natively() -> None:
    """The shape `render` alone cannot express, rendered by `_generate_named_call_assignment`."""
    source = '#ret := "RetWithOut"(x := #value, dbl => #doubled, trp => #tripled);'
    lines = generate_statements(_statements(source))
    assert lines == [
        "_sub_RetWithOut_result = self._runtime.call_named_block(" '"RetWithOut", {"x": self.value}, {})',
        'self.doubled = _sub_RetWithOut_result["dbl"]',
        'self.tripled = _sub_RetWithOut_result["trp"]',
        'if "x" in _sub_RetWithOut_result: self.value = _sub_RetWithOut_result["x"]',
        'self.ret = _sub_RetWithOut_result["RetWithOut"]',
    ]


def test_an_assignment_from_a_bare_builtin_call_binding_an_output_is_a_system_call() -> None:
    """`#x := RD_SYS_T(OUT => #t);` -- a bare system builtin binding a `=>` output.

    Once refused (a positional call has nowhere to route the output; the old text
    dispatcher emitted `self.x = RD_SYS_T ( OUT => self.x )`, a SyntaxError). It is
    a `PLCRuntime.system_call` now: the result dict feeds the output and the return.
    """
    source = "#x := RD_SYS_T(OUT => #t);"
    assert generate_statements(_statements(source)) == [
        '_sys = self._runtime.system_call("RD_SYS_T", {}, {"OUT": self.t})',
        'self.t = _sys["OUT"]',
        'self.x = _sys["RET_VAL"]',
    ]


def _first_call_argument_value_expr(source: str, index: int = 0):
    """The parsed value of one `Call` statement's `index`-th argument, for a direct unit check."""
    (call,) = _statements(source)
    assert isinstance(call, Call)
    value_expr = call.arguments[index].value_expr
    assert value_expr is not None
    return value_expr


def test_a_global_db_name_with_a_hyphen_is_not_a_write_back_candidate() -> None:
    """Fix round 1 (Critical): the old text translator's `GLOBAL_DB_PATTERN` required a
    word-only quoted name.

    `"My-DB" . m` never matched `r'"(\\w+)"\\s*\\.\\s*(.+)'` (the hyphen is not `\\w`), so
    the old dispatcher's `translate` left it completely untouched -- quoted, with its
    spaces intact -- and `_emit_named_call` never saw a `self.`-rooted, space-free value
    for it, so it never emitted a write-back line. `render` renders this shape
    `self.`-rooted regardless (`self._runtime.global_dbs["My-DB"].m`), which is why
    `_is_write_back_candidate` must judge this from the tree, not from `render`'s own
    output text -- see its own docstring.
    """
    value_expr = _first_call_argument_value_expr('"Blk"(x := "My-DB".m);')
    assert _is_write_back_candidate(value_expr, None) is False

    source = '"Blk"(x := "My-DB".m);'
    new_lines = generate_statements(_statements(source))
    assert len(new_lines) == 1


def test_a_global_db_name_with_a_space_is_not_a_write_back_candidate() -> None:
    value_expr = _first_call_argument_value_expr('"Blk"(x := "My DB".m);')
    assert _is_write_back_candidate(value_expr, None) is False

    source = '"Blk"(x := "My DB".m);'
    new_lines = generate_statements(_statements(source))
    assert len(new_lines) == 1


def test_a_global_db_name_with_a_dot_is_not_a_write_back_candidate() -> None:
    value_expr = _first_call_argument_value_expr('"Blk"(x := "a.b".m);')
    assert _is_write_back_candidate(value_expr, None) is False

    source = '"Blk"(x := "a.b".m);'
    new_lines = generate_statements(_statements(source))
    assert len(new_lines) == 1


def test_a_closing_paren_inside_a_string_argument_renders_whole_natively() -> None:
    """Task 9 step 3: the closing-parenthesis guard is gone -- this now renders natively.

    Before this change, `_generate_fb_instance_call` refused (fell back to the
    dispatcher) whenever an argument's raw value contained a `)`, so the old
    dispatcher's own `translate_fb_call` truncation (`self.tmr(IN='a)` -- `PT` silently
    dropped, probed directly) was reproduced byte for byte. That guard is gone: this
    shape now renders the call whole and correctly -- the fifth attributed residual
    class the corpus differential recognised while this was being proven equivalent to
    the old path ("old path truncates the call at a nested `)`").
    """
    source = "#tmr(IN := 'a)b', PT := #t);"
    new_lines = generate_statements(_statements(source))
    assert new_lines == ["self.tmr(IN='a)b', PT=self.t)"]
