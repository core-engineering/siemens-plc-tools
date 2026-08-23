"""What the generator emits, per statement kind.

Shapes are transcribed from the text path's actual output, probed directly, not
from what the SCL ought to mean. The bar is byte-identical output.
"""

from __future__ import annotations

from plc_code.executor.generator import generate_statements
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements


def _statements(source: str):
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    assert result.errors == [], result.errors
    return result.statements


def test_an_assignment_becomes_a_python_assignment() -> None:
    assert generate_statements(_statements("#a := #b ;")) == ["self.a = self.b"]


def test_indentation_is_applied_in_four_space_units() -> None:
    assert generate_statements(_statements("#a := #b ;"), indent=2) == ["        self.a = self.b"]


def test_several_assignments_keep_source_order() -> None:
    assert generate_statements(_statements("#a := 1 ; #b := 2 ;")) == [
        "self.a = 1",
        "self.b = 2",
    ]


def test_an_if_with_elsif_and_else() -> None:
    source = "IF #a THEN #b := 1 ; ELSIF #c THEN #b := 2 ; ELSE #b := 3 ; END_IF ;"
    assert generate_statements(_statements(source)) == [
        "if self.a:",
        "    self.b = 1",
        "elif self.c:",
        "    self.b = 2",
        "else:",
        "    self.b = 3",
    ]


def test_an_if_without_else_emits_no_else() -> None:
    source = "IF #a THEN #b := 1 ; END_IF ;"
    assert generate_statements(_statements(source)) == ["if self.a:", "    self.b = 1"]


def test_a_nested_if_indents_twice() -> None:
    source = "IF #a THEN IF #b THEN #c := 1 ; END_IF ; END_IF ;"
    assert generate_statements(_statements(source)) == [
        "if self.a:",
        "    if self.b:",
        "        self.c = 1",
    ]


def test_a_for_loop_without_a_step() -> None:
    source = "FOR #i := 1 TO 5 DO #a := #i ; END_FOR ;"
    assert generate_statements(_statements(source)) == [
        "for self.i in range(1, 5 + 1):",
        "    self.a = self.i",
    ]


def test_a_for_loop_with_a_step() -> None:
    source = "FOR #i := 1 TO 5 BY 2 DO #a := #i ; END_FOR ;"
    assert generate_statements(_statements(source)) == [
        "for self.i in range(1, 5 + 1, 2):",
        "    self.a = self.i",
    ]


def test_a_while_loop() -> None:
    source = "WHILE #a DO #b := 1 ; END_WHILE ;"
    assert generate_statements(_statements(source)) == ["while self.a:", "    self.b = 1"]


def test_a_case_becomes_an_if_elif_chain() -> None:
    source = "CASE #s OF 1 : #b := 1 ; 2 , 3 : #b := 2 ; ELSE #b := 9 ; END_CASE ;"
    assert generate_statements(_statements(source)) == [
        "if self.s == 1:",
        "    self.b = 1",
        "elif self.s in (2, 3):",
        "    self.b = 2",
        "else:",
        "    self.b = 9",
    ]


def test_a_case_without_an_else_arm() -> None:
    source = "CASE #s OF 1 : #b := 1 ; END_CASE ;"
    assert generate_statements(_statements(source)) == ["if self.s == 1:", "    self.b = 1"]


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


def test_a_block_call_with_input_and_output_bindings() -> None:
    # Probed: StatementTranslator().translate_simple_statement(
    #     "#tmr ( IN := #x , PT := #t , Q => #q ) ;"
    # ) == ["self.tmr(IN=self.x, PT=self.t)", "self.q = self.tmr.Q"]
    source = "#tmr(IN := #x, PT := #t, Q => #q);"
    assert generate_statements(_statements(source)) == [
        "self.tmr(IN=self.x, PT=self.t)",
        "self.q = self.tmr.Q",
    ]


def test_a_quoted_name_block_call() -> None:
    # A call to a named FUNCTION/FUNCTION_BLOCK (quoted callee, not `#instance`)
    # routes through `StatementTranslator._translate_named_block_call`, which the
    # generator only reaches by going through `translate_simple_statement`
    # rather than `StatementTranslator.translate_fb_call` directly. Probed:
    # StatementTranslator().translate_simple_statement(
    #     '"Doubler" ( x := #value , result := #intermediate ) ;'
    # ) == [
    #     '_sub_Doubler_result = self._runtime.call_named_block('
    #     '"Doubler", {"x": self.value, "result": self.intermediate}, {})',
    #     'if "x" in _sub_Doubler_result: self.value = _sub_Doubler_result["x"]',
    #     'if "result" in _sub_Doubler_result: self.intermediate = _sub_Doubler_result["result"]',
    # ]
    source = '"Doubler"(x := #value, result := #intermediate);'
    assert generate_statements(_statements(source)) == [
        "_sub_Doubler_result = self._runtime.call_named_block("
        '"Doubler", {"x": self.value, "result": self.intermediate}, {})',
        'if "x" in _sub_Doubler_result: self.value = _sub_Doubler_result["x"]',
        'if "result" in _sub_Doubler_result: self.intermediate = _sub_Doubler_result["result"]',
    ]


def test_an_assignment_from_a_named_call_with_outputs() -> None:
    # An assignment whose RHS is a quoted-name call that also binds `=>`
    # outputs. `translate_simple_statement`'s assignment branch special-cases
    # this (the plain expression path would silently drop the outputs), so it
    # is only reached by routing `Assignment` through it as well.
    # Probed: StatementTranslator().translate_simple_statement(
    #     '#ret := "RetWithOut" ( x := #value , dbl => #doubled , trp => #tripled ) ;'
    # ) == [
    #     '_sub_RetWithOut_result = self._runtime.call_named_block('
    #     '"RetWithOut", {"x": self.value}, {})',
    #     'self.doubled = _sub_RetWithOut_result["dbl"]',
    #     'self.tripled = _sub_RetWithOut_result["trp"]',
    #     'if "x" in _sub_RetWithOut_result: self.value = _sub_RetWithOut_result["x"]',
    #     'self.ret = _sub_RetWithOut_result["RetWithOut"]',
    # ]
    source = '#ret := "RetWithOut"(x := #value, dbl => #doubled, trp => #tripled);'
    assert generate_statements(_statements(source)) == [
        "_sub_RetWithOut_result = self._runtime.call_named_block(" '"RetWithOut", {"x": self.value}, {})',
        'self.doubled = _sub_RetWithOut_result["dbl"]',
        'self.tripled = _sub_RetWithOut_result["trp"]',
        'if "x" in _sub_RetWithOut_result: self.value = _sub_RetWithOut_result["x"]',
        'self.ret = _sub_RetWithOut_result["RetWithOut"]',
    ]


def test_a_return_statement() -> None:
    # Probed: StatementTranslator().translate_simple_statement("RETURN ;") == ["return"]
    assert generate_statements(_statements("RETURN ;")) == ["return"]


def test_an_exit_statement_inside_a_for_loop() -> None:
    # Probed: StatementTranslator().translate_simple_statement("EXIT ;") == ["break"]
    source = "FOR #i := 1 TO 3 DO EXIT ; END_FOR ;"
    assert generate_statements(_statements(source)) == [
        "for self.i in range(1, 3 + 1):",
        "    break",
    ]
