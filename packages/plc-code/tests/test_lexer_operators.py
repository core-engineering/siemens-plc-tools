"""The lexer must classify operators instead of dumping them as UNKNOWN.

Typing only — never merging. Region.content is built by concatenating
token.value plus a space (parser.py:815-819), so combining `>` and `=` into
one token would change content from `> = ` to `>= `, and this phase promises
content is byte-identical. Composition of multi-character operators is the
statement parser's job.
"""

from plc_code.parser.lexer import TokenType, tokenize


def _types(source: str) -> list[TokenType]:
    return [t.type for t in tokenize(source) if t.type is not TokenType.EOF]


class TestOperatorsAreTyped:
    def test_no_unknown_tokens_for_arithmetic(self) -> None:
        assert TokenType.UNKNOWN not in _types("#a + #b - #c * #d / #e")

    def test_no_unknown_tokens_for_comparison(self) -> None:
        assert TokenType.UNKNOWN not in _types("#a > #b < #c = #d")

    def test_each_operator_gets_its_own_type(self) -> None:
        types = _types("+ - * / > < =")
        assert types == [
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.STAR,
            TokenType.SLASH,
            TokenType.GT,
            TokenType.LT,
            TokenType.EQ,
        ]


class TestNothingIsMerged:
    def test_ge_stays_two_tokens(self) -> None:
        assert _types(">=") == [TokenType.GT, TokenType.EQ]

    def test_ne_stays_two_tokens(self) -> None:
        assert _types("<>") == [TokenType.LT, TokenType.GT]

    def test_output_binding_stays_two_tokens(self) -> None:
        assert _types("=>") == [TokenType.EQ, TokenType.GT]

    def test_instance_variable_stays_two_tokens(self) -> None:
        assert _types("#flag") == [TokenType.HASH, TokenType.IDENTIFIER]

    def test_token_values_are_the_raw_characters(self) -> None:
        values = [t.value for t in tokenize(">=") if t.type is not TokenType.EOF]
        assert values == [">", "="]


class TestNegativeNumbersAreUndisturbed:
    """_scan_number consumes a leading '-' when a digit follows. Both existing
    behaviours must survive the new MINUS token."""

    def test_glued_negative_literal_is_one_number(self) -> None:
        tokens = [t for t in tokenize("#a := -1;") if t.type is not TokenType.EOF]
        assert TokenType.NUMBER in [t.type for t in tokens]
        assert "-1" in [t.value for t in tokens]

    def test_spaced_minus_is_an_operator(self) -> None:
        assert TokenType.MINUS in _types("#a - 1")
