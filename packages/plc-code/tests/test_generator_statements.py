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
