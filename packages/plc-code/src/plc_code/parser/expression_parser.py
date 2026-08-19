"""Recursive-descent expression parser over an SCL token stream.

Like the statement parser, it reads tokens rather than text: ``Region.content``
is a lossy re-serialisation and the tokens are the only place adjacency (and
therefore `>=` versus `> =`) is decidable. The parser never guesses — a
construct it cannot read produces a ``ParseError`` and the expression is
reported as unreadable rather than reconstructed from a partial match.

This module covers only the primary and postfix layer: literals, variable
references (`#local`, `"Global"`), member access, indexing, function calls,
and parenthesised grouping. Unary and binary operators are a later addition;
``parse_expression`` and ``_ExpressionParser._parse_expression`` exist as the
seam that addition slots into, so the top-level entry point does not need to
be rewired when it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plc_code.parser.expressions import (
    Expression,
    FunctionCall,
    Index,
    Literal,
    Member,
    TypedLiteral,
    VariableRef,
)
from plc_code.parser.lexer import Token, TokenType
from plc_code.parser.statements import ParseError
from plc_code.parser.token_stream import TokenStream, adjacent

#: Identifier spellings that read as a boolean literal rather than a name.
_BOOLEAN_LITERALS = {"TRUE", "FALSE"}


@dataclass
class ExpressionResult:
    """What a token slice parsed into, and what it could not.

    Attributes
    ----------
    expression : Expression | None
        The parsed expression, or ``None`` when the slice could not be read
        as one (the reason is in ``errors``).
    errors : list[ParseError]
        One entry per construct the parser could not read, in the order the
        parser encountered them. Default is an empty list.
    consumed : int
        How many tokens the parser advanced past, out of the slice it was
        given. Equal to the length of the slice on a clean parse; shorter
        when the parser stopped before the end (e.g. after a syntax error),
        which lets a caller detect trailing, unparsed tokens.
    """

    expression: Expression | None
    errors: list[ParseError] = field(default_factory=list)
    consumed: int = 0


class _ExpressionParser:
    """Parses one expression from a token stream, collecting errors as it goes.

    Parameters
    ----------
    stream : TokenStream
        The cursor to read from. Not rewound or re-created here; the caller
        owns its lifetime and reads its final position after parsing.
    """

    def __init__(self, stream: TokenStream) -> None:
        """Create a parser over ``stream``, ready to run ``parse()``.

        Parameters
        ----------
        stream : TokenStream
            The cursor to read from.
        """
        self._stream = stream
        self._errors: list[ParseError] = []

    @property
    def errors(self) -> list[ParseError]:
        """Errors recorded while parsing, in the order they were encountered."""
        return self._errors

    def parse(self) -> Expression | None:
        """Parse one expression at the cursor.

        Returns
        -------
        Expression | None
            The parsed expression, or ``None`` when the cursor was on a
            construct this parser cannot read (an error was recorded).
        """
        return self._parse_expression()

    def _parse_expression(self) -> Expression | None:
        """Top-level expression entry point.

        For this task, delegates directly to ``_parse_postfix``: no operator
        layer exists yet. A later task replaces this method's body with the
        operator-precedence chain, without touching ``parse_expression`` or
        any caller of it.

        Returns
        -------
        Expression | None
            The parsed expression, or ``None`` when the cursor was on a
            construct this parser cannot read.
        """
        return self._parse_postfix()

    def _parse_postfix(self) -> Expression | None:
        """Parse a primary expression, then any `.member` or `[index]` chain.

        Returns
        -------
        Expression | None
            The parsed expression, with every trailing member access and
            indexing operation folded in left-to-right; ``None`` when no
            primary expression could be read at the cursor, or when a `.`
            or `[` opened a continuation that could not be completed (an
            error was recorded either way). A malformed continuation never
            returns the base built so far — a partial tree presented as a
            complete one would defeat any caller checking ``consumed``
            against the expression alone to decide whether parsing
            succeeded.
        """
        node = self._parse_primary()
        if node is None:
            return None

        while True:
            token = self._stream.peek()

            if token.type is TokenType.DOT:
                self._stream.advance()
                name_token = self._stream.peek()
                if name_token.type is not TokenType.IDENTIFIER:
                    self._error(name_token, "a member name after '.'")
                    return None
                self._stream.advance()
                node = Member(line=token.line, column=token.column, base=node, name=name_token.value)
                continue

            if token.type is TokenType.LBRACKET:
                self._stream.advance()
                index = self._parse_expression()
                if index is None:
                    return None
                if not self._expect(TokenType.RBRACKET, "']'"):
                    return None
                node = Index(line=token.line, column=token.column, base=node, index=index)
                continue

            break

        return node

    def _try_typed_literal(self) -> TypedLiteral | None:
        """Read ``T#5s`` / ``16#FF`` if the cursor is on one, else nothing.

        The lexer does not know these literals: ``16#FF`` comes out as
        ``NUMBER('16') HASH('#') IDENTIFIER('FF')``, which is also the shape of
        a number followed by a variable access. Only adjacency separates them,
        hence ``adjacent`` rather than a test on token types.

        Returns
        -------
        TypedLiteral | None
            The literal, or None when the cursor is not on this shape (the
            stream has then not moved).
        """
        prefix = self._stream.peek()
        if prefix.type not in (TokenType.NUMBER, TokenType.IDENTIFIER):
            return None
        hash_token = self._stream.peek(1)
        if hash_token.type is not TokenType.HASH or not adjacent(prefix, hash_token):
            return None

        self._stream.advance()  # the prefix
        self._stream.advance()  # the '#'

        # The value is the longest run of tokens touching one another:
        # `5` `s` -> "5s", `1` `h` `30` `m` -> "1h30m".
        parts: list[str] = []
        previous = hash_token
        while not self._stream.at_end() and adjacent(previous, self._stream.peek()):
            token = self._stream.advance()
            parts.append(token.value)
            previous = token

        return TypedLiteral(
            line=prefix.line,
            column=prefix.column,
            prefix=prefix.value,
            value="".join(parts),
        )

    def _parse_primary(self) -> Expression | None:
        """Parse a literal, variable reference, function call, or grouping.

        Returns
        -------
        Expression | None
            The parsed expression; ``None`` when the cursor is on a
            construct this parser cannot read (an error was recorded).
        """
        typed = self._try_typed_literal()
        if typed is not None:
            return typed

        token = self._stream.peek()

        if token.type is TokenType.NUMBER:
            self._stream.advance()
            return Literal(line=token.line, column=token.column, value=token.value)

        if token.type is TokenType.IDENTIFIER:
            if token.value.upper() in _BOOLEAN_LITERALS:
                self._stream.advance()
                return Literal(line=token.line, column=token.column, value=token.value)
            if self._stream.peek(1).type is TokenType.LPAREN:
                return self._parse_function_call()
            self._error(token, "an expression")
            return None

        if token.type is TokenType.HASH:
            return self._parse_local_variable()

        if token.type is TokenType.STRING:
            self._stream.advance()
            return VariableRef(line=token.line, column=token.column, name=token.value[1:-1], is_local=False)

        if token.type is TokenType.LPAREN:
            return self._parse_grouping()

        self._error(token, "an expression")
        return None

    def _parse_local_variable(self) -> Expression | None:
        """Parse `#name`, the cursor already on the `#`.

        Returns
        -------
        Expression | None
            A ``VariableRef`` with ``is_local=True``; ``None`` when `#` is
            not followed by an identifier (an error was recorded).
        """
        hash_token = self._stream.advance()  # HASH
        name_token = self._stream.peek()
        if name_token.type is not TokenType.IDENTIFIER:
            self._error(name_token, "an identifier after '#'")
            return None
        self._stream.advance()
        return VariableRef(
            line=hash_token.line, column=hash_token.column, name=name_token.value, is_local=True
        )

    def _parse_function_call(self) -> Expression | None:
        """Parse `name(args)`, the cursor already on the name.

        Only reached once the caller has confirmed an `(` immediately
        follows the identifier.

        Returns
        -------
        Expression | None
            The parsed ``FunctionCall``; ``None`` when an argument could not
            be read or the closing `)` is missing (an error was recorded
            either way). Matches ``_parse_postfix``: a malformed call never
            returns a partial node built from whatever arguments were read
            so far — a caller reading ``consumed`` alone must not be able to
            mistake it for a complete parse.
        """
        name_token = self._stream.advance()  # IDENTIFIER
        self._stream.advance()  # LPAREN

        arguments: list[Expression] = []
        if not self._stream.match(TokenType.RPAREN):
            while True:
                argument = self._parse_expression()
                if argument is None:
                    return None
                arguments.append(argument)
                if self._stream.match(TokenType.COMMA):
                    self._stream.advance()
                    continue
                break

        if not self._expect(TokenType.RPAREN, "')'"):
            return None
        return FunctionCall(
            line=name_token.line, column=name_token.column, name=name_token.value, arguments=arguments
        )

    def _parse_grouping(self) -> Expression | None:
        """Parse `(expression)`, the cursor already on the `(`.

        The parenthesised expression is returned as-is: grouping changes how
        an outer operator layer would bind, not the tree, so it creates no
        node of its own.

        Returns
        -------
        Expression | None
            The inner expression; ``None`` when nothing readable followed
            the `(`, or when the closing `)` is missing (an error was
            recorded either way).
        """
        self._stream.advance()  # LPAREN
        inner = self._parse_expression()
        if inner is None:
            return None
        if not self._expect(TokenType.RPAREN, "')'"):
            return None
        return inner

    def _expect(self, token_type: TokenType, expected: str) -> bool:
        """Consume ``token_type`` at the cursor, recording an error if absent.

        Unlike ``TokenStream.expect``, which raises on a mismatch, this
        follows the statement parser's convention: a missing token becomes a
        recorded ``ParseError`` rather than an exception, and the cursor is
        left where it is (not advanced past a token that was never there).

        Parameters
        ----------
        token_type : TokenType
            The token type expected at the cursor.
        expected : str
            What would have been valid there, in plain words.

        Returns
        -------
        bool
            True when ``token_type`` was at the cursor and consumed; False
            when a ``ParseError`` was recorded instead. Every caller must
            treat False as "the construct being built cannot be completed"
            and return ``None`` rather than the node built so far.
        """
        if self._stream.match(token_type):
            self._stream.advance()
            return True
        self._error(self._stream.peek(), expected)
        return False

    def _error(self, token: Token, expected: str) -> None:
        """Record a ``ParseError`` for ``token`` and what was expected there.

        Parameters
        ----------
        token : Token
            The token the parser stopped on.
        expected : str
            What would have been valid there, in plain words.
        """
        self._errors.append(
            ParseError(line=token.line, column=token.column, token_value=token.value, expected=expected)
        )


def parse_expression(tokens: list[Token]) -> ExpressionResult:
    """Parse one expression from a token slice.

    Parameters
    ----------
    tokens : list[Token]
        The token slice to parse, typically an ``Argument.value`` or
        ``Assignment.target``/``value`` slice from the statement parser.
        Consumed through a forward-only ``TokenStream`` cursor; the list
        itself is not mutated.

    Returns
    -------
    ExpressionResult
        The parsed expression (or ``None``), any errors encountered, and how
        many tokens of the slice were consumed.
    """
    stream = TokenStream(tokens)
    parser = _ExpressionParser(stream)
    expression = parser.parse()
    return ExpressionResult(expression=expression, errors=parser.errors, consumed=stream.position())
