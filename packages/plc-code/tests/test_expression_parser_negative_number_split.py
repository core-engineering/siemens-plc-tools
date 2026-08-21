"""An unspaced `-` before a digit, which the lexer folds into the number.

`#a-1` comes out as `IDENTIFIER:'a' NUMBER:'-1'`, and so does `#a -1`: the
lexer folds a `-` into the number whenever a digit follows, spacing included.
That left `("MLA10"-1)` and `armParams[#arm_index-1]` unreadable — the last 16
expression errors in the corpus.

The fold cannot be corrected in the lexer, because the lexer cannot know which
of the two readings applies:

    f(#a, -1)     two arguments, the second a negative literal
    f(#a -1)      one argument, a subtraction

Only a parser knows whether an operand precedes. So the split happens there,
inside the `+ -` precedence level, which by construction runs only once a left
operand has been read. Everywhere else a folded `-1` stays the literal it is,
and `Region.content` — which 27 rules and the transpiler read byte for byte —
is untouched.
"""

from __future__ import annotations

from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.expressions import BinaryOp, Grouping, Index, Literal, VariableRef
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


def _parse(source: str):
    return parse_expression(_tokens(source))


class TestSubtraction:
    def test_a_folded_minus_after_an_operand_is_a_subtraction(self) -> None:
        result = _parse('("MLA10"-1)')
        assert result.errors == []
        grouping = result.expression
        assert isinstance(grouping, Grouping)
        node = grouping.inner
        assert isinstance(node, BinaryOp)
        assert node.operator == "-"
        assert node.left == VariableRef(line=1, column=2, name="MLA10", is_local=False)
        assert node.right == Literal(line=1, column=10, value="1")

    def test_it_works_as_an_array_index(self) -> None:
        result = _parse("#arr[#i-1]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert len(node.indices) == 1
        index = node.indices[0]
        assert isinstance(index, BinaryOp)
        assert index.operator == "-"

    def test_a_decimal_keeps_its_fraction(self) -> None:
        result = _parse("#a-2.5")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.right == Literal(line=1, column=4, value="2.5")

    def test_an_exponent_keeps_its_form(self) -> None:
        result = _parse("#a-1e3")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.right == Literal(line=1, column=4, value="1e3")

    def test_two_numbers_subtract(self) -> None:
        result = _parse("2-1")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "-"
        assert node.left == Literal(line=1, column=1, value="2")
        assert node.right == Literal(line=1, column=3, value="1")

    def test_a_spaced_minus_is_unchanged(self) -> None:
        # This one the lexer already emits as MINUS; the split must not be the
        # only path to a subtraction.
        result = _parse("#a - 1")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "-"
        assert node.right == Literal(line=1, column=6, value="1")

    def test_it_chains_left_to_right(self) -> None:
        result = _parse("#a-1-2")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.right == Literal(line=1, column=6, value="2")
        assert isinstance(node.left, BinaryOp)
        assert node.left.right == Literal(line=1, column=4, value="1")

    def test_it_binds_looser_than_multiplication(self) -> None:
        result = _parse("#a-1*2")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "-"
        assert isinstance(node.right, BinaryOp)
        assert node.right.operator == "*"


class TestNegativeLiteralIsUntouched:
    def test_a_leading_negative_stays_a_literal(self) -> None:
        result = _parse("-1 + 2")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "+"
        assert node.left == Literal(line=1, column=1, value="-1")

    def test_an_argument_after_a_comma_stays_a_literal(self) -> None:
        result = _parse("ABS(#a, -1)")
        assert result.errors == []
        call = result.expression
        assert call.arguments[1].value == Literal(line=1, column=9, value="-1")

    def test_an_index_of_minus_one_stays_a_literal(self) -> None:
        result = _parse("#arr[-1]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert node.indices == [Literal(line=1, column=6, value="-1")]

    def test_a_grouped_negative_stays_a_literal(self) -> None:
        result = _parse("(-1)")
        assert result.errors == []
        assert result.expression == Grouping(line=1, column=1, inner=Literal(line=1, column=2, value="-1"))

    def test_a_negative_after_an_operator_stays_a_literal(self) -> None:
        result = _parse("#a * -1")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "*"
        assert node.right == Literal(line=1, column=6, value="-1")

    def test_a_comparison_against_a_negative_stays_a_literal(self) -> None:
        result = _parse('"CONV".IN[#b] <> -32768')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "<>"
        assert node.right == Literal(line=1, column=18, value="-32768")


class TestConsumption:
    def test_a_split_number_consumes_its_one_token(self) -> None:
        for source in ('("MLA10"-1)', "#arr[#i-1]", "2-1", "#a * -1"):
            tokens = _tokens(source)
            result = parse_expression(tokens)
            assert verify_expression_consumed(tokens, result) is True, source
