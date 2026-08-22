"""Native rendering of `If`/`For`/`While`/`Case` headers: conditions, bounds, selector, labels.

Task 7. `generate_statements` stops rebuilding SCL text for a header line -- an `If`
branch's condition, a `While`'s condition, a `For`'s bounds, a `Case`'s selector and each
label -- and renders it from `Branch.condition_expr` / `While.condition_expr` /
`For.start_expr`/`end_expr`/`step_expr` / `Case.selector_expr` / `CaseBranch.values_expr`
directly, via `renderer.render`, falling back to the text dispatcher only when a slice
failed to parse or `render` itself raises `UnsupportedExpression` -- see
`generator._render_expression_or_fallback` and `generator._render_case_label`.

Every output shape here is transcribed from `test_generator_statements.py`, which already
pins the byte-identical text these constructs must keep producing; this module does not
invent new shapes, it adds the native/fallback counter assertions
(`control_flow_render_counts`) that prove the shape came from the tree, not just from an
unchanged code path that happens to still produce the same text.
"""

from __future__ import annotations

from plc_code.executor.generator import (
    control_flow_render_counts,
    generate_statements,
    reset_control_flow_render_counters,
)
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Statement


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
