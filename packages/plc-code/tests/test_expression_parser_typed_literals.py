"""Typed literals: `T#5s`, `16#FF`.

The lexer does not recognise them. `16#FF` comes out as `NUMBER:'16' HASH:'#'
IDENTIFIER:'FF'` — exactly the shape of a number followed by a variable access.
`T#5s` comes out as `IDENTIFIER:'T' HASH:'#' NUMBER:'5' IDENTIFIER:'s'`.

Untreated, both parse without error and *wrongly*. This is the only construct in
the corpus whose failure would be silent, which is why it gets its own task.

What separates a typed literal from a `#access` is adjacency: `16#FF` has no
space in it, and a leading `#a` has nothing before it. `adjacent()` from
`token_stream` decides.
"""

from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.expressions import (
    BinaryOp,
    FunctionCall,
    Index,
    Literal,
    TypedLiteral,
    VariableRef,
)
from plc_code.parser.lexer import TokenType, tokenize


def _parse(source: str):
    return parse_expression([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestTypedLiterals:
    def test_a_time_literal(self) -> None:
        node = _parse("T#5s").expression
        assert isinstance(node, TypedLiteral)
        assert node.prefix == "T"
        assert node.value == "5s"

    def test_a_hex_literal(self) -> None:
        node = _parse("16#FF").expression
        assert isinstance(node, TypedLiteral)
        assert node.prefix == "16"
        assert node.value == "FF"

    def test_a_binary_literal(self) -> None:
        node = _parse("2#1010").expression
        assert isinstance(node, TypedLiteral)
        assert node.prefix == "2"

    def test_a_long_time_literal(self) -> None:
        node = _parse("T#1h30m").expression
        assert isinstance(node, TypedLiteral)
        assert node.value == "1h30m"


class TestNotConfusedWithVariableAccess:
    def test_a_plain_local_variable_is_still_a_variable(self) -> None:
        assert isinstance(_parse("#armNumber").expression, VariableRef)

    def test_a_number_then_a_spaced_variable_is_addition(self) -> None:
        """`16 + #FF` is not a typed literal."""
        node = _parse("16 + #FF").expression
        assert isinstance(node, BinaryOp)

    def test_spacing_decides(self) -> None:
        """`16 # FF` with spaces is not `16#FF`."""
        node = _parse("16 # FF").expression
        assert not isinstance(node, TypedLiteral)


class TestTypedLiteralsAwayFromPositionZero:
    """The shapes the corpus actually contains.

    A rule that only holds at the start of a slice would pass every test above
    and fail on the first typed literal used as a call argument or an index.
    """

    def test_inside_a_function_call(self) -> None:
        result = _parse("ABS(T#5s)")
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert isinstance(call.arguments[0].value, TypedLiteral)

    def test_as_an_array_index(self) -> None:
        result = _parse("#arr[16#FF]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert isinstance(node.indices[0], TypedLiteral)

    def test_inside_parentheses(self) -> None:
        result = _parse("(T#5s)")
        assert result.errors == []
        assert isinstance(result.expression, TypedLiteral)

    def test_the_run_stops_at_an_operator(self) -> None:
        """`T#5s+1` has no spaces at all; the literal must still end at `5s`.

        Before operators existed this returned the bare literal. It returns the
        addition now, and the point is unchanged and in fact sharper: the value
        run must not have swallowed `+1`, and the operator must be read as an
        operator.
        """
        node = _parse("T#5s+1").expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "+"
        assert isinstance(node.left, TypedLiteral)
        assert node.left.value == "5s"
        assert isinstance(node.right, Literal)
        assert node.right.value == "1"
