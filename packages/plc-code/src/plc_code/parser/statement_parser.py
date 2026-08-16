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
    Branch,
    Call,
    Case,
    CaseBranch,
    Exit,
    For,
    If,
    ParseError,
    Return,
    Statement,
    While,
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

        if keyword == "IF":
            return self._parse_if()
        if keyword == "CASE":
            return self._parse_case()
        if keyword == "FOR":
            return self._parse_for()
        if keyword == "WHILE":
            return self._parse_while()

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

    def _keyword_ahead(self) -> str:
        """Uppercased value of the current token when it is an identifier.

        Returns
        -------
        str
            The current token's value, uppercased, when it is an
            ``IDENTIFIER`` token (keywords are lexed as identifiers, see
            ``lexer.py``); an empty string for any other token type,
            including ``EOF``, so callers can compare it against a keyword
            set without a separate type check.
        """
        token = self._stream.peek()
        return token.value.upper() if token.type is TokenType.IDENTIFIER else ""

    def _take_until_keyword(self, *keywords: str) -> list[Token]:
        """Consume tokens up to (not including) one of ``keywords``.

        Used for the token slices that make up a condition, selector or bound
        expression, which are not parsed further in phase 1.

        Parameters
        ----------
        *keywords : str
            Keyword spellings (case-insensitive) that end the slice.

        Returns
        -------
        list[Token]
            The consumed tokens, in source order. Stops at the end of the
            stream as well, so a malformed construct missing its terminating
            keyword still yields a bounded slice rather than looping forever.
        """
        taken: list[Token] = []
        wanted = {k.upper() for k in keywords}
        while not self._stream.at_end() and self._keyword_ahead() not in wanted:
            taken.append(self._stream.advance())
        return taken

    def _parse_body(self, *terminators: str) -> list[Statement]:
        """Parse statements until one of ``terminators`` is the next keyword.

        This is the loop shared by every control-flow body (IF branches,
        ELSE, FOR, WHILE). It mirrors ``parse()``'s own loop and keeps the
        same recovery invariant: a statement that parses is appended, a
        statement that fails leaves an error in ``self._result.errors`` and
        the cursor already past the offending token (via ``_recover``), and
        if neither happened — the only remaining case, a keyword this loop
        does not recognise as a terminator and ``_parse_statement`` also does
        not recognise — exactly one token is skipped so the loop cannot spin
        without consuming input. No well-formed statement between two errors
        is ever discarded by this loop.

        Parameters
        ----------
        *terminators : str
            Keyword spellings (case-insensitive) that close this body and
            are left unconsumed for the caller.

        Returns
        -------
        list[Statement]
            Statements parsed before the terminator, in source order.
        """
        wanted = {t.upper() for t in terminators}
        body: list[Statement] = []
        while not self._stream.at_end() and self._keyword_ahead() not in wanted:
            before = self._stream.position()
            statement = self._parse_statement()
            if statement is not None:
                body.append(statement)
            elif self._stream.position() == before:
                self._stream.advance()
        return body

    def _parse_if(self) -> Statement:
        """Parse an IF statement, including any ELSIF and ELSE clauses.

        ``IF ... THEN ... ELSIF ... THEN ... ELSE ... END_IF;`` — ELSIF is
        not a separate node; each ELSIF clause becomes another ``Branch`` in
        ``If.branches``, alongside the IF clause itself as the first entry.

        Returns
        -------
        Statement
            The parsed ``If`` node.
        """
        line = self._stream.advance().line  # IF
        branches: list[Branch] = []
        condition = self._take_until_keyword("THEN")
        self._expect_keyword("THEN")
        branches.append(Branch(condition=condition, body=self._parse_body("ELSIF", "ELSE", "END_IF")))

        while self._keyword_ahead() == "ELSIF":
            self._stream.advance()
            condition = self._take_until_keyword("THEN")
            self._expect_keyword("THEN")
            branches.append(Branch(condition=condition, body=self._parse_body("ELSIF", "ELSE", "END_IF")))

        else_body: list[Statement] = []
        if self._keyword_ahead() == "ELSE":
            self._stream.advance()
            else_body = self._parse_body("END_IF")

        self._expect_keyword("END_IF")
        self._consume_semicolon()
        return If(line=line, branches=branches, else_body=else_body)

    def _parse_case(self) -> Statement:
        """Parse a CASE statement, including its default (ELSE) arm.

        ``CASE selector OF v1: ... v2, v3: ... ELSE ... END_CASE;``

        SCL's default arm is a bare ``ELSE`` with no colon, unlike the
        labelled arms above it; ``_consume_colon`` tolerates one anyway
        rather than treating it as an error, since a stray ``ELSE:`` is
        harmless and not worth flagging.

        A branch that fails to open with a label (a colon reachable before
        the next statement boundary, ELSE, END_CASE, or end of stream) does
        not abort the CASE: a ``ParseError`` is recorded naming the problem,
        and the span is still parsed as a branch body — through
        ``_parse_case_body``, exactly like a labelled one — with
        ``CaseBranch.values`` left empty to mark it as unlabelled. The loop
        then keeps going, so a well-formed label or ELSE arm later in the
        same CASE is still found and used. This is what lets `1: #b := 10;`
        immediately followed by unlabelled statements, or a labelless span
        ahead of a real ELSE, still surface every statement and still
        recognise the default — see `_parse_case_labels` for why the old
        version of this method could not do that.

        Returns
        -------
        Statement
            The parsed ``Case`` node.
        """
        line = self._stream.advance().line  # CASE
        selector = self._take_until_keyword("OF")
        self._expect_keyword("OF")

        branches: list[CaseBranch] = []
        default: list[Statement] = []

        while not self._stream.at_end() and self._keyword_ahead() not in {"ELSE", "END_CASE"}:
            values = self._parse_case_labels()
            if values is None:
                self._error(self._stream.peek(), "a case label")
                branches.append(CaseBranch(values=[], body=self._parse_case_body()))
                continue
            body = self._parse_case_body()
            branches.append(CaseBranch(values=values, body=body))

        if self._keyword_ahead() == "ELSE":
            self._stream.advance()
            self._consume_colon()  # `ELSE:` is tolerated; SCL writes it bare
            default = self._parse_body("END_CASE")

        self._expect_keyword("END_CASE")
        self._consume_semicolon()
        return Case(line=line, selector=selector, branches=branches, default=default)

    def _parse_case_labels(self) -> list[list[Token]] | None:
        """Read `v1, v2:` — one token slice per value.

        Each label value may be more than one token (e.g. a quoted symbolic
        constant is a single ``STRING`` token, but nothing here assumes a
        label is exactly one token), so values are split on commas and
        closed by the colon rather than read one token at a time.

        Gated on the non-consuming lookahead ``_at_case_label`` before a
        single token is touched. An earlier version of this method instead
        scanned speculatively into a local buffer and discarded that buffer
        on failure — which silently consumed and dropped whatever it had
        scanned (e.g. a branch that opened with a bare statement instead of
        a label), with no statement and no recorded error. Checking first
        and only then consuming means a failed attempt here leaves the
        cursor exactly where it started, so the caller (`_parse_case`) can
        record an error and still hand the same tokens to `_parse_case_body`
        to be read as ordinary statements.

        Returns
        -------
        list[list[Token]] | None
            One entry per comma-separated value, in source order; ``None``
            when no label is present at the cursor. Nothing is consumed in
            the ``None`` case.
        """
        if not self._at_case_label():
            return None

        values: list[list[Token]] = []
        current: list[Token] = []
        while not self._stream.at_end():
            if self._stream.match(TokenType.COLON):
                self._stream.advance()
                if current:
                    values.append(current)
                return values or None
            if self._stream.match(TokenType.COMMA):
                self._stream.advance()
                if current:
                    values.append(current)
                current = []
                continue
            current.append(self._stream.advance())
        return None  # pragma: no cover - unreachable once `_at_case_label` gates entry

    def _parse_case_body(self) -> list[Statement]:
        """Parse statements up to the next label, ELSE or END_CASE.

        A label is detected by lookahead (``_at_case_label``) rather than by
        line position, which is what makes `1: #b := 10;` — label and first
        statement on one line — behave the same as a label on its own line.
        The old text-based translator treated them differently and dropped
        the whole CASE when it saw the first form.

        Follows the same recovery invariant as ``_parse_body``: a statement
        either parses, leaves a recorded error with the cursor already past
        the offending token, or (only when neither `_parse_statement` nor
        the label/terminator checks above recognised what is at the cursor)
        has exactly one token skipped, so the loop always makes forward
        progress and never discards a statement it could otherwise read.

        Returns
        -------
        list[Statement]
            Statements parsed before the next label or terminator, in
            source order.
        """
        body: list[Statement] = []
        while not self._stream.at_end():
            if self._keyword_ahead() in {"ELSE", "END_CASE"}:
                break
            if self._at_case_label():
                break
            before = self._stream.position()
            statement = self._parse_statement()
            if statement is not None:
                body.append(statement)
            elif self._stream.position() == before:
                self._stream.advance()
        return body

    def _at_case_label(self) -> bool:
        """Whether a `value:` label starts here, without consuming anything.

        Scans ahead token by token, accepting the token kinds a label value
        can be made of (numbers, strings, identifiers, `#`-prefixed locals,
        and commas joining multiple values), and reports a label only if a
        colon is reached before a semicolon, `:=`, or end of stream — any of
        which means this is a statement, not a label.

        Returns
        -------
        bool
            True when the tokens ahead form a case label ending in a colon,
            without an intervening statement boundary.
        """
        offset = 0
        while True:
            token = self._stream.peek(offset)
            if token.type in (TokenType.EOF, TokenType.SEMICOLON, TokenType.ASSIGN):
                return False
            if token.type is TokenType.COLON:
                return True
            if token.type not in (
                TokenType.NUMBER,
                TokenType.STRING,
                TokenType.IDENTIFIER,
                TokenType.HASH,
                TokenType.COMMA,
            ):
                return False
            offset += 1

    def _parse_for(self) -> Statement:
        """Parse a FOR loop, with or without a BY step clause.

        ``FOR variable := start TO end BY step DO ... END_FOR;`` — the BY
        clause is optional in SCL; when absent, ``For.step`` is left empty so
        callers can tell "no BY clause" apart from an explicit step.

        Returns
        -------
        Statement
            The parsed ``For`` node.
        """
        line = self._stream.advance().line  # FOR
        variable = self._take_until(TokenType.ASSIGN)
        self._stream.expect(TokenType.ASSIGN)
        start = self._take_until_keyword("TO")
        self._expect_keyword("TO")
        end = self._take_until_keyword("BY", "DO")
        step: list[Token] = []
        if self._keyword_ahead() == "BY":
            self._stream.advance()
            step = self._take_until_keyword("DO")
        self._expect_keyword("DO")
        body = self._parse_body("END_FOR")
        self._expect_keyword("END_FOR")
        self._consume_semicolon()
        return For(line=line, variable=variable, start=start, end=end, step=step, body=body)

    def _parse_while(self) -> Statement:
        """Parse a WHILE loop.

        ``WHILE condition DO ... END_WHILE;``

        Returns
        -------
        Statement
            The parsed ``While`` node.
        """
        line = self._stream.advance().line  # WHILE
        condition = self._take_until_keyword("DO")
        self._expect_keyword("DO")
        body = self._parse_body("END_WHILE")
        self._expect_keyword("END_WHILE")
        self._consume_semicolon()
        return While(line=line, condition=condition, body=body)

    def _expect_keyword(self, keyword: str) -> None:
        """Consume ``keyword``, recording an error when it is absent.

        Unlike ``TokenStream.expect``, which raises on a type mismatch, this
        follows the rest of the parser's error handling: a missing keyword
        becomes a recorded ``ParseError`` rather than an exception, and the
        cursor is left where it is (not advanced) so the caller's own
        recovery — typically the enclosing body loop — decides what happens
        next.

        Parameters
        ----------
        keyword : str
            The keyword spelling expected at the cursor (case-insensitive).
        """
        if self._keyword_ahead() == keyword.upper():
            self._stream.advance()
            return
        self._error(self._stream.peek(), keyword)

    def _consume_colon(self) -> None:
        """Consume a colon at the cursor, if present.

        Used only for the CASE default arm, where SCL's own grammar writes a
        bare ``ELSE`` but a stray ``ELSE:`` is harmless and not worth an
        error.
        """
        if self._stream.match(TokenType.COLON):
            self._stream.advance()

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
        """Skip the single offending token, so parsing can retry from what follows.

        Recovery consumes exactly one token — the one just reported in a
        ``ParseError`` — rather than hunting for the next `;`. An unsupported
        keyword such as `REPEAT` has no statement boundary of its own: its body
        is one or more inner, semicolon-terminated statements, so jumping to
        the next `;` would consume the first of those as if it belonged to the
        unsupported construct, silently dropping a perfectly readable
        statement. Skipping one token and letting ``parse()``'s loop retry
        ``_parse_statement`` on the remainder means every well-formed statement
        between one error and the next is still parsed, at the cost of more,
        smaller errors across a genuinely unparseable span — the trade this
        module makes on purpose (see the module docstring).
        """
        if not self._stream.at_end():
            self._stream.advance()

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
