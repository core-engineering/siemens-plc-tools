"""Unit tests for `render` over unary and binary operators (Task 4).

Every expected value was taken by running `ExpressionTranslator().translate(...)`
directly (see the task report), not copied from the brief's table. `&` is the row
that matters most: the current translator leaves it as Python's `&` rather than
translating it to `and`, and that is preserved here on purpose -- see
`test_the_ampersand_keeps_its_own_spelling`.
"""

from __future__ import annotations

import pytest

from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import BinaryOp, UnaryOp, VariableRef


def _binary(operator: str) -> BinaryOp:
    return BinaryOp(
        line=1,
        column=1,
        operator=operator,
        left=VariableRef(line=1, column=1, name="a", is_local=True),
        right=VariableRef(line=1, column=1, name="b", is_local=True),
    )


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("AND", "self.a and self.b"),
        ("OR", "self.a or self.b"),
        ("&", "self.a & self.b"),
        ("=", "self.a == self.b"),
        ("<>", "self.a != self.b"),
        ("MOD", "self.a % self.b"),
        ("DIV", "self.a // self.b"),
        ("**", "self.a ** self.b"),
        ("+", "self.a + self.b"),
        ("*", "self.a * self.b"),
        ("<", "self.a < self.b"),
        (">=", "self.a >= self.b"),
    ],
)
def test_each_operator_renders_as_the_current_path_does(operator: str, expected: str) -> None:
    assert render(_binary(operator)) == expected


def test_the_ampersand_keeps_its_own_spelling() -> None:
    assert render(_binary("&")) != render(_binary("AND"))


def test_not_takes_a_space_and_minus_takes_one_too() -> None:
    operand = VariableRef(line=1, column=1, name="a", is_local=True)
    assert render(UnaryOp(line=1, column=1, operator="NOT", operand=operand)) == "not self.a"
    assert render(UnaryOp(line=1, column=1, operator="-", operand=operand)) == "- self.a"


def test_an_unmapped_binary_operator_raises() -> None:
    with pytest.raises(UnsupportedExpression):
        render(_binary("XOR"))


def test_an_unmapped_unary_operator_raises() -> None:
    operand = VariableRef(line=1, column=1, name="a", is_local=True)
    with pytest.raises(UnsupportedExpression):
        render(UnaryOp(line=1, column=1, operator="~", operand=operand))
