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

    ``statement_spans`` and ``error_spans`` are the anti-silence guarantee.
    A parse that quietly skips a construct — advances the cursor over it
    without putting it in ``statements`` or ``errors`` — leaves a gap that
    ``verify_no_silent_loss`` can detect from these two lists alone. Neither
    field is meant to be read directly by callers outside this module; they
    exist so that guarantee is checkable without re-parsing.

    Attributes
    ----------
    statements : list[Statement]
        Statements successfully parsed, in source order. Default is an empty
        list.
    errors : list[ParseError]
        One entry per construct the parser could not read, in the order the
        parser encountered them. Default is an empty list.
    consumed_tokens : int
        The cursor's final position. Always equals the input length once
        ``parse()`` returns (the recovery loop guarantees forward progress
        to the end of the stream), so on its own this says nothing about
        whether every token ended up in ``statements`` or ``errors`` — see
        ``verify_no_silent_loss`` for the check that does. Default is 0.
    statement_spans : list[tuple[int, int]]
        ``(start, end)`` token-index span for each entry in ``statements``,
        same order, recorded only for top-level statements (a nested
        statement's span is a subset of its parent's and is not recorded
        separately). Default is an empty list.
    error_spans : list[tuple[int, int]]
        ``(start, end)`` token-index span for each entry in ``errors``, same
        order. Width is 1 for an error whose token ``_recover()`` then skips,
        0 for an error that flags a shape problem without consuming anything
        (the construct's tokens are read again, as plain statements, by
        whoever called next). Default is an empty list.
    separator_spans : list[tuple[int, int]]
        ``(start, end)`` span for each bare statement-separator ``;`` the
        parser consumed on its own — an empty statement, not an error and
        not a dropped one. Not aligned with ``statements`` or ``errors``;
        exists only so ``verify_no_silent_loss`` can tell a semicolon with
        nothing before it from a genuinely missing token. Default is an
        empty list.
    unattributed_spans : list[tuple[int, int]]
        ``(start, end)`` span for each token a body loop's last-resort
        "nothing recognised this, skip one token" fallback consumed —
        typically a block-ender keyword that does not match the body it
        appears in (e.g. a stray ``END_WHILE`` inside a ``CASE`` branch).
        Unlike ``separator_spans``, this is never a legitimate no-op: no
        statement, no error and no separator claimed the token, which is
        exactly the failure mode this module exists to catch. It is kept
        deliberately as-is rather than turned into a recorded error, because
        doing so would change what ``errors`` reports for existing inputs;
        recording *that it happened* here, without changing behaviour, is
        what lets ``verify_no_silent_loss`` see it anyway. Always a defect
        when non-empty. Default is an empty list.
    """

    statements: list[Statement] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    consumed_tokens: int = 0
    statement_spans: list[tuple[int, int]] = field(default_factory=list)
    error_spans: list[tuple[int, int]] = field(default_factory=list)
    separator_spans: list[tuple[int, int]] = field(default_factory=list)
    unattributed_spans: list[tuple[int, int]] = field(default_factory=list)


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
                self._result.statement_spans.append((before, self._stream.position()))
            elif self._stream.position() == before:
                # Nothing consumed: guarantee forward progress. Nothing recognised
                # this token as a statement, an error, or a separator either, so
                # the accounting must see it — see _record_unattributed.
                self._stream.advance()
                self._record_unattributed(before)
        self._result.consumed_tokens = self._stream.position()
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
            position = self._stream.position()
            self._stream.advance()
            self._result.separator_spans.append((position, position + 1))
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
            self._recover_and_record()
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
        self._recover_and_record()
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

    @staticmethod
    def _is_block_ender(token: Token) -> bool:
        """Whether ``token`` is a block-ender keyword lexed as an identifier.

        ``ELSE``, ``END_IF``, ``END_CASE`` and the rest of ``_BLOCK_ENDERS``
        lex as ordinary ``IDENTIFIER`` tokens (see ``_keyword_ahead``), so a
        raw token-type scan cannot tell one apart from an ordinary name by
        type alone. Every unbounded expression scan in this parser
        (``_find_ahead``, ``_take_until``, ``_at_case_label``) must stop here
        in addition to its own stop set: without this check, a statement
        missing its terminating semicolon right before a block-ender would
        read straight through the keyword as if it were ordinary token
        content, consuming it into the statement instead of leaving it for
        the construct it actually closes.

        Parameters
        ----------
        token : Token
            The token to classify.

        Returns
        -------
        bool
            True when ``token`` is an identifier whose uppercased value is
            one of ``_BLOCK_ENDERS``.
        """
        return token.type is TokenType.IDENTIFIER and token.value.upper() in _BLOCK_ENDERS

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
                self._record_unattributed(before)
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
            position = self._stream.position()
            self._stream.advance()
            self._result.separator_spans.append((position, position + 1))
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
                self._record_flag_error()
                branches.append(CaseBranch(values=[], body=self._parse_case_body()))
                continue
            body = self._parse_case_body()
            branches.append(CaseBranch(values=values, body=body))

        if self._keyword_ahead() == "ELSE":
            position = self._stream.position()
            self._stream.advance()
            self._result.separator_spans.append((position, position + 1))
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
                self._record_unattributed(before)
        return body

    def _at_case_label(self) -> bool:
        """Whether a `value:` label starts here, without consuming anything.

        Scans ahead token by token, accepting the token kinds a label value
        can be made of (numbers, strings, identifiers, `#`-prefixed locals,
        and commas joining multiple values), and reports a label only if a
        colon is reached before a semicolon, `:=`, an identifier that is
        itself a block-ender keyword (``ELSE``, ``END_CASE``, ...), or end of
        stream — any of which means this is a statement or a construct
        boundary, not a label.

        The block-ender check exists because ``ELSE`` and ``END_CASE`` lex as
        ordinary ``IDENTIFIER`` tokens (see ``_keyword_ahead``), so without it
        this scan would happily walk straight through one hunting for a
        colon that belongs to something else entirely — which is exactly how
        an unterminated labelless span (`#a ELSE #b := 9;`, no semicolon
        before ``ELSE``) could make a later ``ELSE`` disappear into what this
        method reported as label content.

        Returns
        -------
        bool
            True when the tokens ahead form a case label ending in a colon,
            without an intervening statement boundary or block-ender.
        """
        offset = 0
        while True:
            token = self._stream.peek(offset)
            if token.type in (TokenType.EOF, TokenType.SEMICOLON, TokenType.ASSIGN):
                return False
            if token.type is TokenType.COLON:
                return True
            if self._is_block_ender(token):
                return False
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
        self._record_flag_error()

    def _consume_colon(self) -> None:
        """Consume a colon at the cursor, if present.

        Used only for the CASE default arm, where SCL's own grammar writes a
        bare ``ELSE`` but a stray ``ELSE:`` is harmless and not worth an
        error. When present, the colon is recorded as a separator span (like
        the ``ELSE`` keyword right before it) so it is accounted for whether
        or not the arm turns out to hold any statements.
        """
        if self._stream.match(TokenType.COLON):
            position = self._stream.position()
            self._stream.advance()
            self._result.separator_spans.append((position, position + 1))

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
            ``None`` when a semicolon, a block-ender keyword, or the end of
            the stream is reached first. The block-ender stop keeps this
            scan from reading through ``ELSE``/``END_IF``/etc. in search of
            e.g. an ``:=`` that actually belongs to a different, later
            statement — which a statement missing its own terminating
            semicolon would otherwise let through (see ``_is_block_ender``).
        """
        offset = 0
        while True:
            token = self._stream.peek(offset)
            if token.type in (TokenType.EOF, TokenType.SEMICOLON) or self._is_block_ender(token):
                return None
            if token.type is token_type:
                return offset
            offset += 1

    def _take_until(self, *stop: TokenType) -> list[Token]:
        """Consume and return tokens up to (not including) any of ``stop``.

        Also stops before a block-ender keyword (``ELSE``, ``END_IF``, ...)
        even when it is not among ``stop``, for the same reason
        ``_find_ahead`` does: those lex as plain identifiers, so nothing
        else would keep an unterminated statement from consuming one as
        ordinary token content (see ``_is_block_ender``).

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
        while (
            not self._stream.at_end()
            and not self._stream.match(*stop)
            and not self._is_block_ender(self._stream.peek())
        ):
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

    def _recover_and_record(self) -> None:
        """Call ``_recover()`` and record the span it consumed for the last error.

        Must be called immediately after ``self._error(...)``, with nothing
        consumed in between, so the span recorded here is exactly what
        recovery itself did — not an assumed width. ``verify_no_silent_loss``
        is what checks that width is 1; this method only records it.
        """
        before = self._stream.position()
        self._recover()
        self._result.error_spans.append((before, self._stream.position()))

    def _record_flag_error(self) -> None:
        """Record a zero-width span for the last error, which consumed nothing.

        Used for an error that only flags a shape problem — a missing
        keyword, a branch that failed to open with a label — where the
        tokens in question are left for whoever parses next (the enclosing
        loop's own recovery, or a case branch read as plain statements) and
        must not be double-counted as belonging to the error too.
        """
        position = self._stream.position()
        self._result.error_spans.append((position, position))

    def _record_unattributed(self, position: int) -> None:
        """Record that the token at ``position`` was skipped by a body loop's
        last-resort fallback — recognised by nothing, so accounted for by
        nothing else.

        Called immediately after that fallback's own single ``advance()``,
        so the span is always exactly one token wide.

        Parameters
        ----------
        position : int
            The stream index the skipped token was at.
        """
        self._result.unattributed_spans.append((position, position + 1))

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


def _body_width(body: list[Statement]) -> tuple[int, int]:
    """Sum ``_content_width`` over a list of statements, componentwise.

    Parameters
    ----------
    body : list[Statement]
        Statements to measure, e.g. an ``If`` branch's body.

    Returns
    -------
    tuple[int, int]
        ``(minimum, maximum)`` token count the whole list implies.
    """
    lo = hi = 0
    for statement in body:
        slo, shi = _content_width(statement)
        lo += slo
        hi += shi
    return lo, hi


def _content_width(statement: Statement) -> tuple[int, int]:
    """The token count ``statement``'s own fields imply, as a ``(min, max)`` range.

    Purely a function of ``statement``'s content — no stream access, no
    knowledge of how parsing actually went. Every unparsed expression a
    statement holds is stored verbatim as a ``list[Token]`` slice, so its
    length is exact; the range only widens where the grammar makes a token
    optional and the parser tolerates its absence without recording whether
    it was there — a trailing ``;``, a bare ``ELSE:`` colon, an ``ELSE`` or
    default arm whose body happens to be empty either because the arm was
    absent or because it was present and empty.

    ``verify_no_silent_loss`` compares this against a statement's actual
    recorded span, topped up by any error spans nested inside it, to catch
    a statement whose real span is wider than anything its content can
    explain — which is what a construct that got silently swallowed on the
    way to becoming (part of) this statement looks like from the outside.

    Parameters
    ----------
    statement : Statement
        The statement to measure.

    Returns
    -------
    tuple[int, int]
        ``(minimum, maximum)`` token count, inclusive.
    """
    if isinstance(statement, (Return, Exit)):
        return 1, 2  # keyword ['; ']

    if isinstance(statement, Assignment):
        exact = len(statement.target) + 1 + len(statement.value)  # target ':=' value
        return exact, exact + 1  # [';']

    if isinstance(statement, Call):
        lo = hi = len(statement.callee) + 2  # callee '(' ')'
        count = len(statement.arguments)
        lo += max(0, count - 1)  # commas between arguments
        hi += count  # tolerate one stray trailing comma
        for argument in statement.arguments:
            if not argument.name:
                # Positional: the leading token is folded into `value` already.
                lo += len(argument.value)
                hi += len(argument.value)
            else:
                operator = 2 if argument.is_output else 1  # ':=' or '=>'
                width = 1 + operator + len(argument.value)  # name operator value
                lo += width
                hi += width
        return lo, hi + 1  # [';']

    if isinstance(statement, If):
        lo = hi = 1  # IF
        for index, branch in enumerate(statement.branches):
            if index:
                lo += 1
                hi += 1  # ELSIF
            lo += len(branch.condition) + 1  # condition 'THEN'
            hi += len(branch.condition) + 1
            blo, bhi = _body_width(branch.body)
            lo += blo
            hi += bhi
        elo, ehi = _body_width(statement.else_body)
        lo += elo
        hi += ehi
        # No slack is added here for the ELSE keyword itself, present or not:
        # _parse_if records it as a separator span at the point it consumes
        # it (see the ELSE branch above), so verify_no_silent_loss credits it
        # to this statement directly instead of this function having to guess
        # whether an empty else_body means "absent" or "present but empty" —
        # the ambiguity that hid a dropped token behind unearned slack before
        # this was tracked at the source.
        return lo + 1, hi + 2  # END_IF [';']

    if isinstance(statement, Case):
        lo = hi = 1 + len(statement.selector) + 1  # CASE selector OF
        for case_branch in statement.branches:
            if case_branch.values:
                label = sum(len(value) for value in case_branch.values)
                label += len(case_branch.values) - 1  # commas between values
                label += 1  # colon
                lo += label
                hi += label
            blo, bhi = _body_width(case_branch.body)
            lo += blo
            hi += bhi
        dlo, dhi = _body_width(statement.default)
        lo += dlo
        hi += dhi
        # As with If above: the ELSE keyword and its tolerated bare colon are
        # each recorded as their own separator span where they're actually
        # consumed (_parse_case, _consume_colon), so this function adds no
        # slack for them — present or absent, empty arm or not.
        return lo + 1, hi + 2  # END_CASE [';']

    if isinstance(statement, For):
        lo = hi = 1 + len(statement.variable) + 1 + len(statement.start) + 1 + len(statement.end)
        # FOR variable ':=' start 'TO' end
        if statement.step:
            lo += 1 + len(statement.step)  # 'BY' step
            hi += 1 + len(statement.step)
        lo += 1  # DO
        hi += 1
        blo, bhi = _body_width(statement.body)
        lo += blo
        hi += bhi
        return lo + 1, hi + 2  # END_FOR [';']

    if isinstance(statement, While):
        lo = hi = 1 + len(statement.condition) + 1  # WHILE condition DO
        blo, bhi = _body_width(statement.body)
        lo += blo
        hi += bhi
        return lo + 1, hi + 2  # END_WHILE [';']

    raise TypeError(f"unrecognised statement type: {type(statement).__name__}")  # pragma: no cover


def verify_no_silent_loss(tokens: list[Token], result: ParseResult) -> list[str]:
    """Check that every token in ``tokens`` is accounted for by ``result``.

    This is the strong form of the anti-silence guarantee: every token must
    be covered by exactly one top-level statement's span, a recorded error,
    a bare-``;`` separator (an empty statement, not lost code), or — always
    reported as a defect — an unattributed span, with no gap left over, and
    no top-level statement's span may be wider than its own content — plus
    whatever errors and unattributed spans fall inside it — can explain.
    Counting *that* the cursor reached the end of the stream is not enough
    (the recovery loop guarantees it always does); this checks that nothing
    was swallowed on the way.

    Three classes of loss are covered: a gap (tokens covered by nothing at
    all — what an old, unbounded ``_recover()`` produces when it eats a
    well-formed statement whole), an inflated statement (a statement whose
    recorded span is wider than its fields, plus the errors and unattributed
    tokens nested inside it, can account for — what a construct that
    silently dropped a branch or a label produces: the outer statement still
    closes cleanly and covers the full span positionally, but its content
    does not contain what the span implies it read), and an unattributed
    span itself — a token none of ``statements``, ``errors`` or
    ``separator_spans`` claimed, which a body loop's last-resort fallback
    can still silently swallow (e.g. a stray block-ender keyword nested
    inside a body it does not close). The third is reported unconditionally,
    independent of whatever slack the second check tolerates elsewhere, so
    it cannot be hidden by an unrelated statement's wide bracket.

    Parameters
    ----------
    tokens : list[Token]
        The exact token slice ``parse_statements`` (or a ``StatementParser``
        built directly) was given.
    result : ParseResult
        Its return value.

    Returns
    -------
    list[str]
        One entry per violation found; an empty list means every token in
        ``tokens`` is accounted for.
    """
    problems: list[str] = []

    for error, (start, end) in zip(result.errors, result.error_spans, strict=True):
        if end - start not in (0, 1):
            problems.append(
                f"error at line {error.line}, column {error.column} spans {end - start} "
                "token(s), expected 0 (a flag) or 1 (a token _recover() skipped)"
            )

    for start, _end in result.unattributed_spans:
        token = tokens[start] if start < len(tokens) else None
        where = f"line {token.line}, column {token.column}: {token.value!r}" if token else "end of stream"
        problems.append(f"unattributed token at {where} — no statement, error or separator claimed it")

    intervals = sorted(
        result.statement_spans + result.error_spans + result.separator_spans + result.unattributed_spans
    )
    cursor = 0
    for start, end in intervals:
        if start > cursor:
            problems.append(f"tokens [{cursor}, {start}) are unaccounted for")
        cursor = max(cursor, end)
    if cursor < len(tokens):
        problems.append(f"tokens [{cursor}, {len(tokens)}) are unaccounted for")

    for statement, (start, end) in zip(result.statements, result.statement_spans, strict=True):
        lo, hi = _content_width(statement)
        # Every token this statement's span covers beyond its own fields must
        # be one the parser explicitly recorded consuming on purpose: a
        # nested error, a nested unattributed skip, or a nested separator
        # (a bare ';', an ELSE keyword, or its tolerated bare colon — see
        # _parse_if/_parse_case/_consume_colon). Each is exactly one token
        # per occurrence and individually verified at its own recording
        # site, so crediting them here cannot absorb an unrelated loss the
        # way blanket bracket slack could.
        nested = result.error_spans + result.unattributed_spans + result.separator_spans
        extra_tokens = sum(e - s for s, e in nested if start <= s and e <= end)
        actual = end - start
        if not (lo + extra_tokens <= actual <= hi + extra_tokens):
            problems.append(
                f"{type(statement).__name__} at line {statement.line} spans {actual} token(s); "
                f"its content (plus {extra_tokens} accounted token(s) inside it) implies "
                f"{lo + extra_tokens}-{hi + extra_tokens}"
            )

    return problems
