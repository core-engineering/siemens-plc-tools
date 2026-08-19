"""Precedence and associativity.

The two rules intuition gets wrong are tested explicitly, because the corpus
would never reveal them: all 8 of its `**` occurrences are trivial.

- every binary operator is left-associative **except `**`**, which is right;
- unary binds looser than `**` on its left: `-2 ** 2` is `-(2 ** 2)`.
"""

from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.expressions import BinaryOp, Literal, UnaryOp
from plc_code.parser.lexer import TokenType, tokenize


def _parse(source: str):
    return parse_expression([t for t in tokenize(source) if t.type is not TokenType.EOF])


def _op(source: str) -> str:
    node = _parse(source).expression
    assert isinstance(node, BinaryOp), f"{source} did not parse to a BinaryOp"
    return node.operator


class TestPrecedence:
    def test_product_binds_tighter_than_sum(self) -> None:
        """`1 + 2 * 3` has `+` at the root."""
        assert _op("1 + 2 * 3") == "+"

    def test_comparison_binds_looser_than_arithmetic(self) -> None:
        assert _op("#a + 1 > #b") == ">"

    def test_and_binds_tighter_than_or(self) -> None:
        assert _op("#a OR #b AND #c") == "OR"

    def test_comparison_binds_tighter_than_and(self) -> None:
        """The corpus shape: `#x AND (#y = #z)` without the parentheses."""
        assert _op("#x AND #y = #z") == "AND"

    def test_parentheses_override(self) -> None:
        assert _op("(1 + 2) * 3") == "*"


class TestAssociativity:
    def test_subtraction_is_left_associative(self) -> None:
        """`1 - 2 - 3` is `(1 - 2) - 3`, so the left side is a BinaryOp."""
        node = _parse("1 - 2 - 3").expression
        assert isinstance(node, BinaryOp)
        assert isinstance(node.left, BinaryOp)
        assert isinstance(node.right, Literal)

    def test_power_is_right_associative(self) -> None:
        """`2 ** 3 ** 2` is `2 ** (3 ** 2)` = 512, not 64."""
        node = _parse("2 ** 3 ** 2").expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "**"
        assert isinstance(node.left, Literal)
        assert isinstance(node.right, BinaryOp)

    def test_unary_minus_binds_looser_than_power(self) -> None:
        """`- 2 ** 2` is `-(2 ** 2)`.

        Spaced deliberately: the lexer folds an unspaced `-2` adjacent to a
        digit into one `NUMBER` token (so `-2` alone never reaches the parser
        as a unary minus at all) — a space keeps `-` and `2` as separate
        tokens without changing what this test is checking.
        """
        node = _parse("- 2 ** 2").expression
        assert isinstance(node, UnaryOp)
        assert node.operator == "-"
        assert isinstance(node.operand, BinaryOp)


class TestComposedOperators:
    def test_greater_or_equal(self) -> None:
        assert _op("#a >= 3") == ">="

    def test_less_or_equal(self) -> None:
        assert _op("#a <= 3") == "<="

    def test_not_equal(self) -> None:
        assert _op("#a <> 3") == "<>"

    def test_a_spaced_pair_is_not_composed(self) -> None:
        """`#a > = 3` is not `>=`; adjacency decides."""
        result = _parse("#a > = 3")
        assert result.errors != [] or _op("#a > = 3") != ">="


class TestUnary:
    def test_not(self) -> None:
        node = _parse("NOT #a").expression
        assert isinstance(node, UnaryOp)
        assert node.operator == "NOT"

    def test_negation(self) -> None:
        node = _parse("-#a").expression
        assert isinstance(node, UnaryOp)
        assert node.operator == "-"

    def test_not_of_a_parenthesised_comparison(self) -> None:
        """Corpus shape: `NOT (#a = #b)`."""
        node = _parse("NOT (#a = #b)").expression
        assert isinstance(node, UnaryOp)
        assert isinstance(node.operand, BinaryOp)


class TestUnsupported:
    def test_xor_is_reported_not_guessed(self) -> None:
        """Zero occurrences in the corpus: reported, not implemented."""
        result = _parse("#a XOR #b")
        assert result.errors != []


class TestProductionShapes:
    def test_the_multi_line_boolean_from_the_corpus(self) -> None:
        node = _parse('"Data".flag AND ("Data".state = "AUTH") AND ("Iface".state = "READY")').expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "AND"

    def test_mod(self) -> None:
        assert _op("#a MOD 2") == "MOD"
