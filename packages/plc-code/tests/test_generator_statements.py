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
