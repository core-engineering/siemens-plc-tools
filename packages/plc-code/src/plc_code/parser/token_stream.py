"""A cursor over a region's token slice, with adjacency-aware composition.

The lexer classifies single characters and never merges them, because merging
would change ``Region.content`` (built from ``token.value``). Multi-character
operators are therefore recognised here, from whether the characters touch in
the source — which the tokens' line and column record.
"""

from __future__ import annotations

from plc_code.parser.lexer import Token, TokenType

_OPERATOR_TYPES: dict[TokenType, str] = {
    TokenType.PLUS: "+",
    TokenType.MINUS: "-",
    TokenType.STAR: "*",
    TokenType.SLASH: "/",
    TokenType.GT: ">",
    TokenType.LT: "<",
    TokenType.EQ: "=",
}

#: Pairs of adjacent single-character operators that form one SCL operator.
_COMPOSITE_OPERATORS: dict[tuple[str, str], str] = {
    (">", "="): ">=",
    ("<", "="): "<=",
    ("<", ">"): "<>",
    ("=", ">"): "=>",
    ("*", "*"): "**",
}

_EOF = Token(TokenType.EOF, "", 0, 0)


def adjacent(left: Token, right: Token) -> bool:
    """Return True when ``right`` starts in the column just after ``left`` ends.

    Parameters
    ----------
    left, right : Token
        Two tokens in source order.

    Returns
    -------
    bool
        True only when they touch on the same line, with nothing between them.
    """
    return left.line == right.line and left.column + len(left.value) == right.column


class TokenStream:
    """A forward-only cursor over a list of tokens."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._index = 0

    def at_end(self) -> bool:
        """Whether every token has been consumed."""
        return self._index >= len(self._tokens)

    def position(self) -> int:
        """The current index, for error reporting and recovery."""
        return self._index

    def peek(self, offset: int = 0) -> Token:
        """The token ``offset`` ahead, or an EOF token past the end."""
        index = self._index + offset
        if 0 <= index < len(self._tokens):
            return self._tokens[index]
        return _EOF

    def advance(self) -> Token:
        """Consume and return the current token."""
        token = self.peek()
        self._index += 1
        return token

    def match(self, *types: TokenType) -> bool:
        """Whether the current token is one of ``types``."""
        return self.peek().type in types

    def expect(self, token_type: TokenType) -> Token:
        """Consume the current token, requiring it to be ``token_type``.

        Raises
        ------
        ValueError
            When the current token is of another type.
        """
        token = self.peek()
        if token.type is not token_type:
            raise ValueError(
                f"expected {token_type.name} at line {token.line}, "
                f"column {token.column}, got {token.type.name} ({token.value!r})"
            )
        return self.advance()

    def peek_operator(self) -> str | None:
        """What ``compose_operator`` would consume, without consuming it.

        The single lookahead this module offers over ``_OPERATOR_TYPES`` /
        ``_COMPOSITE_OPERATORS``: a caller that only needs to test which
        operator sits at the cursor — not consume it on the caller's own
        terms — uses this instead of duplicating the adjacency check.

        Returns
        -------
        str | None
            The operator text (``">="``, ``"+"``, ...) that sits at the
            cursor, or None when the cursor is not on an operator. Nothing
            is consumed either way.
        """
        first = self.peek()
        single = _OPERATOR_TYPES.get(first.type)
        if single is None:
            return None

        second = self.peek(1)
        pair = _OPERATOR_TYPES.get(second.type)
        if pair is not None and adjacent(first, second):
            composite = _COMPOSITE_OPERATORS.get((single, pair))
            if composite is not None:
                return composite

        return single

    def compose_operator(self) -> str | None:
        """Consume one operator, joining an adjacent pair into its SCL form.

        Returns
        -------
        str | None
            The operator text (``">="``, ``"+"``, ...), or None when the cursor
            is not on an operator. Nothing is consumed in the None case.
        """
        operator = self.peek_operator()
        if operator is None:
            return None
        self.advance()
        if len(operator) == 2:  # every composite is two characters; no single is
            self.advance()
        return operator
