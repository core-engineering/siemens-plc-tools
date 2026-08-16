"""The AST node set, sized on what production SCL actually contains.

Measured over 11 950 body lines in five real projects: assignment 59%, then
IF/ELSIF/ELSE, call, FOR, RETURN, CASE, EXIT, WHILE. REPEAT/UNTIL, GOTO and
CONTINUE have zero occurrences and are deliberately absent — the parser rejects
them with an error, which is correct for a construct the toolchain does not
support.

Expressions are NOT parsed in phase 1: every expression position holds the
token slice it occupies.
"""

from dataclasses import FrozenInstanceError

import pytest

from plc_code.parser.lexer import Token, TokenType
from plc_code.parser.statements import (
    Argument,
    Assignment,
    Branch,
    Call,
    Case,
    CaseBranch,
    Exit,
    For,
    If,
    ParseError,
    Return,
    While,
)


def _tok(value: str = "x") -> Token:
    return Token(TokenType.IDENTIFIER, value, 1, 1)


class TestNodesAreFrozen:
    def test_assignment_is_immutable(self) -> None:
        node = Assignment(line=1, target=[_tok("a")], value=[_tok("b")])
        with pytest.raises(FrozenInstanceError):
            node.line = 2  # type: ignore[misc]


class TestExpressionsAreTokenSlices:
    def test_assignment_holds_tokens_not_text(self) -> None:
        node = Assignment(line=3, target=[_tok("a")], value=[_tok("b"), _tok("c")])
        assert node.target == [_tok("a")]
        assert len(node.value) == 2

    def test_if_condition_is_a_token_slice(self) -> None:
        branch = Branch(condition=[_tok("flag")], body=[])
        node = If(line=1, branches=[branch], else_body=[])
        assert node.branches[0].condition == [_tok("flag")]


class TestCallDistinguishesBindingDirection:
    """`:=` binds an input, `=>` binds an output. The text path loses this."""

    def test_input_and_output_arguments(self) -> None:
        node = Call(
            line=1,
            callee=[_tok("Timer")],
            arguments=[
                Argument(name="IN", value=[_tok("start")], is_output=False),
                Argument(name="Q", value=[_tok("done")], is_output=True),
            ],
        )
        assert [a.is_output for a in node.arguments] == [False, True]


class TestControlFlowNodes:
    def test_elsif_needs_no_separate_node(self) -> None:
        node = If(
            line=1,
            branches=[
                Branch(condition=[_tok("a")], body=[]),
                Branch(condition=[_tok("b")], body=[]),
            ],
            else_body=[],
        )
        assert len(node.branches) == 2

    def test_case_carries_selector_branches_and_default(self) -> None:
        node = Case(
            line=1,
            selector=[_tok("state")],
            branches=[CaseBranch(values=[[_tok("1")]], body=[])],
            default=[],
        )
        assert node.selector == [_tok("state")]
        assert node.default == []

    def test_for_carries_optional_step(self) -> None:
        node = For(
            line=1,
            variable=[_tok("i")],
            start=[_tok("1")],
            end=[_tok("9")],
            step=[],
            body=[],
        )
        assert node.step == []

    def test_while_and_terminators(self) -> None:
        assert While(line=1, condition=[_tok("run")], body=[]).condition
        assert Return(line=2).line == 2
        assert Exit(line=3).line == 3


class TestParseError:
    def test_carries_location_and_expectation(self) -> None:
        error = ParseError(line=7, column=12, token_value="REPEAT", expected="a statement")
        assert error.line == 7
        assert error.column == 12
        assert "REPEAT" in error.message
        assert "a statement" in error.message
