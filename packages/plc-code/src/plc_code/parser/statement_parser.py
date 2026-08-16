"""Recursive-descent statement parser over an SCL token stream.

It reads tokens, never text. That is the whole point: ``Region.content`` is a
lossy re-serialisation (`#a` becomes `# a`, `=>` becomes `= >`) and the
executor's ~100 regexes exist to undo it. The tokens still carry the original
line and column, so adjacency — and therefore `>=` versus `> =` — is decidable
here and is not decidable from the text.

The parser never guesses. A construct it cannot read produces a ParseError and
the cursor recovers to the next statement boundary, so one unsupported
construct does not hide the rest of the region.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plc_code.parser.lexer import Token, TokenType
from plc_code.parser.statements import (
    Argument,
    Assignment,
    Call,
    Exit,
    ParseError,
    Return,
    Statement,
)
from plc_code.parser.token_stream import TokenStream, adjacent

#: Keywords that terminate a statement list without being statements themselves.
_BLOCK_ENDERS = {"END_IF", "ELSE", "ELSIF", "END_CASE", "END_FOR", "END_WHILE"}


@dataclass
class ParseResult:
    """What a region parsed into, and what it could not.

    Neither list is exceptional: a region routinely yields statements *and*
    errors, which is exactly the report phase 1 exists to produce.

    Attributes
    ----------
    statements : list[Statement]
        Statements successfully parsed, in source order. Default is an empty
        list.
    errors : list[ParseError]
        One entry per construct the parser could not read, in the order the
        parser encountered them. Default is an empty list.
    """

    statements: list[Statement] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)


class StatementParser:
    """Parses a token slice into statements, collecting errors as it goes.

    Parameters
    ----------
    tokens : list[Token]
        The token slice to parse, typically ``Region.tokens``. The parser
        consumes this through a forward-only ``TokenStream`` cursor and does
        not mutate the list.
    """

    def __init__(self, tokens: list[Token]) -> None:
        """Create a parser over ``tokens``, ready to run ``parse()``.

        Parameters
        ----------
        tokens : list[Token]
            The token slice to parse.
        """
        self._stream = TokenStream(tokens)
        self._result = ParseResult()

    def parse(self) -> ParseResult:
        """Parse until the tokens are exhausted.

        Returns
        -------
        ParseResult
            Statements in source order, plus one error per construct that could
            not be read.
        """
        while not self._stream.at_end():
            before = self._stream.position()
            statement = self._parse_statement()
            if statement is not None:
                self._result.statements.append(statement)
            elif self._stream.position() == before:
                # Nothing consumed: guarantee forward progress.
                self._stream.advance()
        return self._result

    def _parse_statement(self) -> Statement | None:
        """Parse one statement at the cursor, or report why it could not be read.

        Returns
        -------
        Statement | None
            The parsed statement; ``None`` when the cursor was on a bare
            semicolon, on a keyword that closes an enclosing construct (left
            for that construct's caller), or on an unsupported construct (an
            error was recorded and the cursor recovered past it).
        """
        token = self._stream.peek()

        if token.type is TokenType.SEMICOLON:
            self._stream.advance()
            return None

        keyword = token.value.upper() if token.type is TokenType.IDENTIFIER else ""

        if keyword == "RETURN":
            self._stream.advance()
            self._consume_semicolon()
            return Return(line=token.line)

        if keyword == "EXIT":
            self._stream.advance()
            self._consume_semicolon()
            return Exit(line=token.line)

        if keyword in _BLOCK_ENDERS:
            # Belongs to an enclosing construct; leave it for the caller.
            return None

        if keyword in {"REPEAT", "UNTIL", "END_REPEAT", "GOTO", "CONTINUE"}:
            self._error(token, "a supported statement (this construct has no translation)")
            self._recover()
            return None

        return self._parse_assignment_or_call(token)

    def _parse_assignment_or_call(self, first: Token) -> Statement | None:
        """Distinguish `target := value;` from `callee(args);`.

        The rule is positional and mirrors the one the text path uses: an `:=`
        that appears before the first `(` opens an assignment; otherwise a `(`
        opens a call.

        Parameters
        ----------
        first : Token
            The token the cursor is currently on, used as the statement's
            reported line when neither shape matches.

        Returns
        -------
        Statement | None
            An ``Assignment`` or ``Call``; ``None`` when neither `:=` nor `(`
            was found before the statement boundary (an error was recorded and
            the cursor recovered past it).
        """
        assign_at = self._find_ahead(TokenType.ASSIGN)
        paren_at = self._find_ahead(TokenType.LPAREN)

        if assign_at is not None and (paren_at is None or assign_at < paren_at):
            target = self._take_until(TokenType.ASSIGN)
            self._stream.expect(TokenType.ASSIGN)
            value = self._take_until(TokenType.SEMICOLON)
            self._consume_semicolon()
            return Assignment(line=first.line, target=target, value=value)

        if paren_at is not None:
            callee = self._take_until(TokenType.LPAREN)
            self._stream.expect(TokenType.LPAREN)
            arguments = self._parse_arguments()
            self._consume_semicolon()
            return Call(line=first.line, callee=callee, arguments=arguments)

        self._error(first, "an assignment or a call")
        self._recover()
        return None

    def _parse_arguments(self) -> list[Argument]:
        """Read `name := value` / `name => value` pairs up to the closing paren.

        Returns
        -------
        list[Argument]
            One entry per binding, in source order. A binding with no `:=` or
            `=>` after its leading token is treated as a positional argument:
            the whole expression becomes the value and ``name`` is left empty.
        """
        arguments: list[Argument] = []
        while not self._stream.at_end() and not self._stream.match(TokenType.RPAREN):
            name_token = self._stream.peek()
            name = name_token.value
            self._stream.advance()

            is_output = False
            if self._stream.match(TokenType.ASSIGN):
                self._stream.advance()
            elif self._is_output_arrow():
                self._stream.advance()
                self._stream.advance()
                is_output = True
            else:
                # Positional argument: rewind and take the whole expression.
                value = self._take_until(TokenType.COMMA, TokenType.RPAREN)
                arguments.append(Argument(name="", value=[name_token, *value]))
                self._skip_comma()
                continue

            value = self._take_until(TokenType.COMMA, TokenType.RPAREN)
            arguments.append(Argument(name=name, value=value, is_output=is_output))
            self._skip_comma()

        if self._stream.match(TokenType.RPAREN):
            self._stream.advance()
        return arguments

    def _is_output_arrow(self) -> bool:
        """Whether the cursor sits on an adjacent `=` `>` pair.

        Returns
        -------
        bool
            True when the current token and the next one are ``=`` and ``>``
            with nothing between them in the source (i.e. the SCL `=>` output
            binding operator, which the lexer never merges into one token).
        """
        first, second = self._stream.peek(), self._stream.peek(1)
        return first.type is TokenType.EQ and second.type is TokenType.GT and adjacent(first, second)

    def _find_ahead(self, token_type: TokenType) -> int | None:
        """Offset of the next ``token_type`` before the statement ends, or None.

        Parameters
        ----------
        token_type : TokenType
            The token type to search for.

        Returns
        -------
        int | None
            The offset from the cursor to the first matching token, or
            ``None`` when a semicolon or the end of the stream is reached
            first.
        """
        offset = 0
        while True:
            token = self._stream.peek(offset)
            if token.type in (TokenType.EOF, TokenType.SEMICOLON):
                return None
            if token.type is token_type:
                return offset
            offset += 1

    def _take_until(self, *stop: TokenType) -> list[Token]:
        """Consume and return tokens up to (not including) any of ``stop``.

        Parameters
        ----------
        *stop : TokenType
            Token types that end the slice without being consumed.

        Returns
        -------
        list[Token]
            The consumed tokens, in source order.
        """
        taken: list[Token] = []
        while not self._stream.at_end() and not self._stream.match(*stop):
            taken.append(self._stream.advance())
        return taken

    def _consume_semicolon(self) -> None:
        """Consume a trailing semicolon at the cursor, if present."""
        if self._stream.match(TokenType.SEMICOLON):
            self._stream.advance()

    def _skip_comma(self) -> None:
        """Consume a separating comma at the cursor, if present."""
        if self._stream.match(TokenType.COMMA):
            self._stream.advance()

    def _recover(self) -> None:
        """Skip to just past the next `;`, so the next statement still parses."""
        while not self._stream.at_end():
            if self._stream.advance().type is TokenType.SEMICOLON:
                return

    def _error(self, token: Token, expected: str) -> None:
        """Record a ``ParseError`` for ``token`` and what was expected there.

        Parameters
        ----------
        token : Token
            The token the parser stopped on.
        expected : str
            What would have been valid there, in plain words.
        """
        self._result.errors.append(
            ParseError(
                line=token.line,
                column=token.column,
                token_value=token.value,
                expected=expected,
            )
        )


def parse_statements(tokens: list[Token]) -> ParseResult:
    """Parse a region's token slice.

    Parameters
    ----------
    tokens : list[Token]
        Typically ``Region.tokens``.

    Returns
    -------
    ParseResult
        Statements and errors.
    """
    return StatementParser(tokens).parse()
