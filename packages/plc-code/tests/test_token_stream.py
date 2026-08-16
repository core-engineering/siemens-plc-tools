"""Adjacency composition — the reason the parser reads tokens, not text.

The lexer types single characters, so `>=` arrives as GT then EQ. Whether that
is one operator or two depends on whether the characters touch in the source,
which the tokens' line and column record and Region.content does not.
"""

import pytest

from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.token_stream import TokenStream, adjacent


def _stream(source: str) -> TokenStream:
    return TokenStream([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestCursor:
    def test_peek_does_not_consume(self) -> None:
        stream = _stream("#a := 1;")
        assert stream.peek().type is TokenType.HASH
        assert stream.peek().type is TokenType.HASH

    def test_advance_consumes(self) -> None:
        stream = _stream("#a")
        assert stream.advance().type is TokenType.HASH
        assert stream.advance().type is TokenType.IDENTIFIER
        assert stream.at_end()

    def test_peek_past_the_end_is_safe(self) -> None:
        stream = _stream("#a")
        assert stream.peek(99) is not None

    def test_expect_returns_the_token(self) -> None:
        stream = _stream("#a")
        assert stream.expect(TokenType.HASH).value == "#"

    def test_expect_raises_on_mismatch(self) -> None:
        stream = _stream("#a")
        with pytest.raises(ValueError, match="expected"):
            stream.expect(TokenType.IDENTIFIER)


class TestAdjacency:
    def test_touching_tokens_are_adjacent(self) -> None:
        tokens = [t for t in tokenize(">=") if t.type is not TokenType.EOF]
        assert adjacent(tokens[0], tokens[1])

    def test_spaced_tokens_are_not(self) -> None:
        tokens = [t for t in tokenize("> =") if t.type is not TokenType.EOF]
        assert not adjacent(tokens[0], tokens[1])

    def test_tokens_on_different_lines_are_not(self) -> None:
        tokens = [t for t in tokenize(">\n=") if t.type not in (TokenType.EOF, TokenType.NEWLINE)]
        assert not adjacent(tokens[0], tokens[1])


class TestComposeOperator:
    @pytest.mark.parametrize(
        "source,expected",
        [(">=", ">="), ("<=", "<="), ("<>", "<>"), ("=>", "=>"), ("**", "**")],
        ids=["ge", "le", "ne", "output", "power"],
    )
    def test_two_character_operators(self, source: str, expected: str) -> None:
        assert _stream(source).compose_operator() == expected

    @pytest.mark.parametrize("source", ["+", "-", "*", "/", ">", "<", "="])
    def test_single_character_operators(self, source: str) -> None:
        assert _stream(source).compose_operator() == source

    def test_spaced_pair_is_not_composed(self) -> None:
        """`> =` is two operators, not `>=`."""
        stream = _stream("> =")
        assert stream.compose_operator() == ">"
        assert stream.compose_operator() == "="

    def test_returns_none_when_not_on_an_operator(self) -> None:
        assert _stream("#a").compose_operator() is None

    def test_composition_consumes_both_tokens(self) -> None:
        stream = _stream(">= 1")
        stream.compose_operator()
        assert stream.peek().type is TokenType.NUMBER
