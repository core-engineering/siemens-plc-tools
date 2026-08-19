"""The invariant: a parsed expression consumes exactly the slice it was given.

The statement parser taught that coverage is measured in spans, not intent. A
parser that stops halfway and returns what it read is indistinguishable from a
correct one unless something counts the tokens.

The 739-token case comes from the corpus: it is the longest slice measured, and
a recursive descent must be checked against it rather than assumed safe.
"""

from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


class TestConsumption:
    def test_a_simple_expression_consumes_everything(self) -> None:
        tokens = _tokens("#a + 1")
        result = parse_expression(tokens)
        assert result.consumed == len(tokens)
        assert verify_expression_consumed(tokens, result) is True

    def test_a_production_shape_consumes_everything(self) -> None:
        tokens = _tokens('"QuayData".arms[#armNumber].status.ersState = "ERS_AUTHORIZED"')
        result = parse_expression(tokens)
        assert verify_expression_consumed(tokens, result) is True

    def test_a_trailing_unreadable_token_is_not_silently_dropped(self) -> None:
        tokens = _tokens("#a + 1 @")
        result = parse_expression(tokens)
        assert result.errors != [] or verify_expression_consumed(tokens, result) is False


class TestDeepNesting:
    def test_a_very_long_expression_does_not_blow_the_stack(self) -> None:
        """739 tokens is the corpus's longest slice; this doubles it."""
        source = " + ".join(["#a"] * 400)
        tokens = _tokens(source)
        assert len(tokens) > 739
        result = parse_expression(tokens)
        assert result.errors == []
        assert verify_expression_consumed(tokens, result) is True

    def test_deeply_nested_parentheses(self) -> None:
        source = "(" * 50 + "#a" + ")" * 50
        tokens = _tokens(source)
        result = parse_expression(tokens)
        assert result.errors == []
